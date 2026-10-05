"""The roadmap's read-only routes, mounted at ``/roadmap`` by ``clank/backend/mounts.py``.

    GET /tracks                                   -> {"tracks": [{track, title, generated_at}]}
    GET /doc?track=<id>[&refresh=1]               -> the track's bam-roadmap/1 document, projected live from its loop
    GET /evidence?track=<id>&path=<abs>[&line=N]  -> a file the document links to (``files.read_evidence``)
    GET /art, GET /art/<name>                     -> the art PNG names, one PNG's bytes

``handle`` is the backend's mount contract: ``(method, subpath, query, headers) -> (status, headers, chunks)``. Sources
are read on every request (``load_sources``), so a changed ``sources.json`` needs no restart.

``/doc`` projects the loop's current files with ``vibetracks.roadmap.projector`` (``project_kinsim``, ``project_rig``)
and caches the document per (track, projector, sources) under a stamp of its inputs and of every file it links to
(``_stamp``); ``refresh=1`` projects again regardless. A failed projection serves the last good document of that same
configuration with a ``warnings`` entry saying it is stale and why; 503 only when there is no good document at all.
``/evidence`` takes its allowlist from that same document, through the same cache, and only from the schema's declared
Link locations (``_links``).
"""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from ..sources import load_sources
from .files import RoadmapForbidden, RoadmapNotFound, art_entries, read_art, read_evidence
from .projector import gitinfo, project_kinsim, project_rig, schema_check
from .projector.detection import project_detection
from .projector.grasping import project_grasping
from .projector.validate import validate_document

SCHEMA = "bam-roadmap/1"
_TRACK_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
#: ASCII digits only: ``int()`` and ``\d`` would also take Unicode digits, signs and surrounding space.
_LINE = re.compile(r"[0-9]+")
_GIT_TIMEOUT_S = 10

Response = tuple[int, dict[str, str], list[bytes]]


class _BadRequest(Exception):
    """A malformed query; the message is the 400 body's ``error``."""


class _InvalidDocument(Exception):
    """A document file that is not valid JSON or not ``bam-roadmap/1``; the message is the 500 body's ``error``."""


class _NoRoadmap(Exception):
    """No projector and no stored document for the track: the 404 the widget renders calmly."""


class _Unavailable(Exception):
    """The live projection failed and there is no good document to fall back on; the message is the 503 body's ``error``."""


class UnknownSourceKey(Exception):
    """The registry maps or names a source key ``load_sources()`` lacks; the message is the 500 body's ``error``."""


# ---------------------------------------------------------------- live projectors
@dataclass(frozen=True)
class LiveProjector:
    """One loop's live projection: what marks its loop present, which files stamp it, which checkout's HEAD, the call."""

    name: str
    title: str
    present: Callable[[Mapping[str, str]], bool]
    inputs: Callable[[Mapping[str, str]], list[Path]]
    checkout: Callable[[Mapping[str, str]], Path]
    project: Callable[[Mapping[str, str], str], dict]


def _kinsim_inputs(sources: Mapping[str, str]) -> list[Path]:
    curriculum, home = Path(sources["kinsim_curriculum_dir"]), Path(sources["kinsim_home"])
    return [curriculum / "curriculum.json", curriculum / "triage.json", curriculum / "tiers.json",
            home / "status.json", home / "runs.jsonl", home / "loop_events.jsonl", home / "triage_answers.jsonl"]


def _rig_inputs(sources: Mapping[str, str]) -> list[Path]:
    rig = Path(sources["rig_loop_dir"])
    return [rig / "ladder.json", rig / "loop_events.jsonl", rig / "triage.json", rig / "loop-status.json"]


#: The CLI's own calls (``projector/__main__.py``, ``command_project``): the kinsim projector is handed the curriculum
#: directory and finds the checkout (and so git history) from it, the rig projector likewise from its loop directory.
KINSIM = LiveProjector(
    name="kinsim", title="Kinsim curriculum",
    present=lambda sources: (Path(sources["kinsim_curriculum_dir"]) / "curriculum.json").is_file(),
    inputs=_kinsim_inputs, checkout=lambda sources: Path(sources["kinsim_curriculum_dir"]),
    project=lambda sources, now: project_kinsim(Path(sources["kinsim_curriculum_dir"]), Path(sources["kinsim_home"]), now=now),
)
RIG = LiveProjector(
    name="rig", title="Rig loop",
    present=lambda sources: (Path(sources["rig_loop_dir"]) / "ladder.json").is_file(),
    inputs=_rig_inputs, checkout=lambda sources: Path(sources["rig_loop_dir"]),
    project=lambda sources, now: project_rig(Path(sources["rig_loop_dir"]), now=now),
)
def _grasping_inputs(sources: Mapping[str, str]) -> list[Path]:
    package = Path(sources["grasp_bench_dir"]) / "src" / "grasp_bench"
    return [package / "curriculum.py", package / "contracts.py", package / "runner.py",
            Path(sources["grasp_bench_dir"]) / "out" / "ledger" / "runs.jsonl"]


GRASPING = LiveProjector(
    name="grasping", title="Grasp bench",
    present=lambda sources: (Path(sources["grasp_bench_dir"]) / "src" / "grasp_bench" / "curriculum.py").is_file(),
    inputs=_grasping_inputs, checkout=lambda sources: Path(sources["grasp_bench_dir"]),
    project=lambda sources, now: project_grasping(Path(sources["grasp_bench_dir"]), now=now),
)
DETECTION = LiveProjector(
    name="detection", title="Hyperspectral ladder (planned)",
    present=lambda sources: (Path(sources["detection_dir"]) / "ladder_data.py").is_file(),
    inputs=lambda sources: [Path(sources["detection_dir"]) / "ladder_data.py"],
    checkout=lambda sources: Path(sources["detection_dir"]),
    project=lambda sources, now: project_detection(Path(sources["detection_dir"]), now=now),
)
PROJECTORS: dict[str, LiveProjector] = {"kinsim": KINSIM, "rig": RIG, "grasping": GRASPING, "detection": DETECTION}


def _registry_roadmap(track: str) -> tuple[bool, dict | None]:
    """(registered, roadmap) for ``track`` from the Dashboard lane's work-track registry.

    ``registered`` is False when no registry is reachable (no workspace, or the dashboard package absent), so the
    caller falls back to the built-in table. The workspace is ``$VIBETRACKS_WORKSPACE`` or the backend's working
    directory, which Clank sets to the workspace (clank/package.json, ``"cwd": "{workspace}"``); the mount contract
    does not pass it.
    """

    try:
        from vibetracks.dashboard.registry import find_registry, load_registry
    except ImportError:
        return False, None
    workspace = os.environ.get("VIBETRACKS_WORKSPACE") or os.getcwd()
    if find_registry(workspace) is None:
        return False, None
    for entry in load_registry(workspace):
        if entry.id == track:
            return True, entry.roadmap
    return True, None


def _resolve(track: str) -> tuple[bool, tuple[LiveProjector, Mapping[str, str]] | None]:
    """(authoritative, live) for ``track``: whether a registry decided it, and the projector and sources if any.

    ``UnknownSourceKey`` when the registry's ``sources`` maps or names a key ``load_sources()`` lacks.
    """

    registered, roadmap = _registry_roadmap(track)
    if not registered:
        projector = PROJECTORS.get(track)
        return False, None if projector is None else (projector, load_sources())
    # WHY the registry decides once it exists: a track's note says which projector answers it (or null: "No roadmap
    # reported yet"), so Zach's registry, not this table, is where a track gains or loses a roadmap.
    if not roadmap or not roadmap.get("projector"):
        return True, None
    projector = PROJECTORS.get(str(roadmap["projector"]))
    if projector is None:
        return True, None
    sources = dict(load_sources())
    named = roadmap.get("sources")
    # WHY refuse rather than skip an unknown key (Codex V09): skipping it left the projector's default path in place, so
    # a misspelt key in a track's note projected some other checkout's data under that track's name, with no diagnostic.
    keys = list(named.values()) if isinstance(named, Mapping) else named if isinstance(named, list) else []
    for source_key in keys:
        if not isinstance(source_key, str) or source_key not in sources:
            raise UnknownSourceKey(f"registry for {track} names unknown source key {source_key}")
    if isinstance(named, Mapping):  # {projector input: sources.py key}: read each input from the named key
        sources.update({input_key: sources[source_key] for input_key, source_key in named.items()})
    return True, (projector, sources)


def projector_for(track: str) -> tuple[LiveProjector, Mapping[str, str]] | None:
    """The projector that answers ``track`` live and the sources it reads; None when no loop projects it.

    The track registry from the Dashboard lane maps each track id to ``{"projector": <PROJECTORS key> | null,
    "sources": [<sources.py keys>] | {<projector input>: <sources.py key>}}``; without a reachable registry the built-in
    table answers. Raises ``UnknownSourceKey`` when the registry names a source key ``load_sources()`` lacks.
    """

    return _resolve(track)[1]


@dataclass
class _Cache:
    """One configuration's live document, keyed by the stamp of the inputs it was projected from."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    stamp: tuple | None = None
    document: dict | None = None
    body: bytes | None = None
    #: Why the projection at ``stamp`` failed; None when ``document`` is the projection at ``stamp``.
    failure: str | None = None


#: Keyed by ``_cache_key``: (track, projector name, the resolved sources).
_CACHES: dict[tuple, _Cache] = {}
_CACHES_LOCK = threading.Lock()


def _cache_key(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> tuple:
    # WHY the projector and its sources in the key, not only the track (Codex V08): a fallback document is the last
    # good projection of this exact configuration. Keyed by track alone, a track switched to another projector (or
    # pointed at other files) whose first projection failed was served the previous loop's document as its own.
    return track, projector.name, tuple(sorted(sources.items()))


def _cache(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> _Cache:
    key = _cache_key(track, projector, sources)
    with _CACHES_LOCK:
        if key not in _CACHES:
            # an older configuration of the track can never be served again, so its entry is dropped, not kept
            for stale in [other for other in _CACHES if other[0] == track]:
                del _CACHES[stale]
            _CACHES[key] = _Cache()
        return _CACHES[key]


def _cached_document(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> dict | None:
    with _CACHES_LOCK:
        cache = _CACHES.get(_cache_key(track, projector, sources))
    return None if cache is None else cache.document


def _head(checkout: Path) -> str | None:
    try:
        completed = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True,
                                   timeout=_GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _file_stamps(paths: Iterator[Path] | list[Path]) -> tuple:
    """Each path with ``(mtime_ns, size)``, or None when it does not exist (so a file vanishing or coming back counts)."""

    files = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            files.append((str(path), None))
        else:
            files.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(files)


def _linked_files(document: dict | None) -> list[Path]:
    """Every file ``document`` links to, as an absolute path, whether or not it exists now.

    A Link's ``abs``; else its ``path`` resolved against its ``base`` (``abs``, or the document's ``roots``), so a linked
    file that was missing when the document was projected is watched for coming back too.
    """

    if document is None:
        return []
    roots = document.get("roots") if isinstance(document.get("roots"), Mapping) else {}
    found: set[str] = set()
    for link in _links(document):
        absolute, path, base = link.get("abs"), link.get("path"), link.get("base")
        if isinstance(absolute, str) and absolute.startswith("/"):
            found.add(absolute)
        elif isinstance(path, str) and path:
            root = "/" if base == "abs" else roots.get(base) if isinstance(base, str) else None
            if isinstance(root, str) and root.startswith("/"):
                resolved = os.path.join(root, path)
                if resolved.startswith("/"):
                    found.add(os.path.normpath(resolved))
    return [Path(path) for path in sorted(found)]


def _stamp(projector: LiveProjector, sources: Mapping[str, str], document: dict | None) -> tuple:
    """A cheap fingerprint of what the projection reads: each declared input file's ``(mtime_ns, size)``, the checkout's
    HEAD, and the same for every file ``document`` (the last good projection of this configuration) links to.

    WHY the declared inputs: they are the ones the projector reads whole (``kinsim.read_inputs`` and ``_sources``,
    ``project_rig``), so a new event or ledger row moves them, and committed code moves HEAD. WHY every linked file as
    well (Codex V06): proof also rests on artifacts no event touches (a supporting test file, the ruler, a gate report);
    one rewritten in place or deleted would otherwise leave the cached verdict standing until someone pressed refresh.
    The links come from the last good document because the next projection's links are unknown until it runs; a file a
    new projection starts linking to joins the stamp when that projection lands.
    """

    return (projector.name, _file_stamps(projector.inputs(sources)), _head(projector.checkout(sources)),
            _file_stamps(_linked_files(document)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _encode(document: dict) -> bytes:
    return (json.dumps(document, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _project(projector: LiveProjector, sources: Mapping[str, str]) -> dict:
    # WHY clear git's answer cache first: ``gitinfo`` caches every git query per process, HEAD included, which is right
    # for one CLI run and wrong for a server that outlives the loop's next commit. Another track projecting at the same
    # moment then only repeats some git calls; it never sees a wrong answer.
    gitinfo.clear_cache()
    document = projector.project(sources, _now())
    # WHY validate before serving, as the CLI does before writing: a projection that fails its own validator would teach
    # the widget a wrong shape, so it counts as a failed projection (the last good document is served instead).
    problems = validate_document(document, against_sources=False)
    if problems:
        raise ValueError(f"the projection is invalid ({len(problems)} problems; first: {problems[0]})")
    return document


def _stale(document: dict, warning: str) -> tuple[bytes, dict]:
    warnings = document.get("warnings") if isinstance(document.get("warnings"), list) else []
    stale = dict(document, warnings=[warning, *warnings])
    return _encode(stale), stale


def _live(track: str, projector: LiveProjector, sources: Mapping[str, str], refresh: bool) -> tuple[bytes, dict]:
    """The track's live document: cached while its stamp holds, projected again when it moves (or on ``refresh``)."""

    cache = _cache(track, projector, sources)
    # WHY one lock per track, held across the projection: the backend is threaded and a projection takes seconds of git
    # calls; concurrent requests for one track wait for that one projection and then read its result from the cache.
    with cache.lock:
        stamp = _stamp(projector, sources, cache.document)
        if refresh or stamp != cache.stamp:
            try:
                document = _project(projector, sources)
            # WHY every exception, not only ProjectionError: a projector bug on one odd loop row must leave the dashboard
            # on the last good document with the reason shown, not turn the track into a 500. Its stamp still covers the
            # last good document's linked files, so a failure is retried as soon as one of them changes or comes back.
            except Exception as error:  # noqa: BLE001
                cache.stamp, cache.failure = stamp, f"{type(error).__name__}: {error}"
            else:
                # the declared inputs and HEAD as read before projecting (a change during it re-projects next time),
                # plus the new document's own linked files
                cache.stamp = stamp[:-1] + (_file_stamps(_linked_files(document)),)
                cache.document, cache.body, cache.failure = document, _encode(document), None
        if cache.failure is None and cache.body is not None and cache.document is not None:
            return cache.body, cache.document
        failure, last_good = cache.failure, cache.document
    if last_good is not None:
        return _stale(last_good, f"stale: projecting the {track} loop live failed ({failure}); this is the last good "
                                 f"projection, generated {last_good.get('generated_at')}")
    try:
        stored = _read_document(track)
    except _InvalidDocument:
        stored = None
    if stored is None:
        raise _Unavailable(f"projecting the {track} loop live failed ({failure}) and there is no earlier document")
    return _stale(stored[1], f"stale: projecting the {track} loop live failed ({failure}); this is the stored document, "
                             f"generated {stored[1].get('generated_at')}")


# ---------------------------------------------------------------- requests
def _bytes(status: int, content_type: str, body: bytes) -> Response:
    headers = {"Content-Type": content_type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    return status, headers, [body]


def _json(status: int, payload: object) -> Response:
    return _bytes(status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))


def _error(status: int, message: str) -> Response:
    return _json(status, {"error": message})


def _single(query: Mapping[str, list[str]], name: str) -> str | None:
    """The one value of ``name``; None when absent; ``_BadRequest`` when repeated."""

    values = query.get(name, [])
    if len(values) > 1:
        raise _BadRequest(f"{name} is given more than once")
    return values[0] if values else None


def _track_id(query: Mapping[str, list[str]]) -> str:
    track = _single(query, "track")
    if track is None or not _TRACK_ID.fullmatch(track):
        raise _BadRequest("track must be one id matching [a-z0-9][a-z0-9_-]*")
    return track


def _refresh(query: Mapping[str, list[str]]) -> bool:
    refresh = _single(query, "refresh")
    if refresh not in (None, "0", "1"):
        raise _BadRequest("refresh must be 1 or 0")
    return refresh == "1"


def _parse_document(raw: bytes, name: str) -> dict:
    try:
        document = json.loads(raw)
    except ValueError as error:  # JSONDecodeError and UnicodeDecodeError
        raise _InvalidDocument(f"{name} is not valid JSON ({error})") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise _InvalidDocument(f"{name} is not a {SCHEMA} document")
    return document


def _read_document(track: str) -> tuple[bytes, dict] | None:
    """The stored bytes and parsed document of ``track``; None when there is no such file."""

    path = Path(load_sources()["roadmap_docs_dir"]) / f"{track}.json"
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return raw, _parse_document(raw, path.name)


def _document(track: str, refresh: bool = False) -> tuple[bytes, dict]:
    """The bytes and parsed document ``/doc`` serves for ``track``: live when its loop is here, else the stored file.

    WHY the stored documents in ``roadmap_docs_dir`` are only a fallback: Zach wants the dashboard real and current, read
    from the loops' files now, not from a snapshot someone last wrote. A stored document still answers a track no
    projector covers yet, a loop that is not on this machine, and a failed projection with nothing better to show.
    """

    authoritative, live = _resolve(track)
    if live is not None and live[0].present(live[1]):
        return _live(track, live[0], live[1], refresh)
    # WHY no stored fallback once the registry has decided there is no roadmap (Codex V10): a track whose note says null,
    # names an unknown projector, or is not in the registry at all has been switched off by Zach, and an old snapshot
    # left in roadmap_docs_dir must not bring it back. Without a reachable registry the stored file still answers.
    if authoritative and live is None:
        raise _NoRoadmap
    stored = _read_document(track)
    if stored is None:
        raise _NoRoadmap
    return stored


#: The schema definitions that are a Link: ``link_fields`` (and every definition built on it with ``allOf``) and
#: ``event_ref``, a line of the loop's event log, which the widget opens the same way.
_LINK_REFS = frozenset({"#/$defs/link_fields", "#/$defs/event_ref"})
#: A step into every item of an array, in a ``_link_locations`` path.
_ITEM = None


def _schema_link_locations(node: object, root: Mapping, prefix: tuple, refs: frozenset[str]) -> Iterator[tuple]:
    if not isinstance(node, Mapping):
        return
    reference = node.get("$ref")
    if reference in _LINK_REFS:
        yield prefix
    if isinstance(reference, str) and reference not in refs:
        yield from _schema_link_locations(schema_check._resolve(root, reference), root, prefix, refs | {reference})
    for keyword in ("allOf", "anyOf", "oneOf"):
        for child in node.get(keyword) or []:
            yield from _schema_link_locations(child, root, prefix, refs)
    for keyword in ("then", "else"):
        yield from _schema_link_locations(node.get(keyword), root, prefix, refs)
    for name, child in (node.get("properties") or {}).items():
        yield from _schema_link_locations(child, root, (*prefix, name), refs)
    yield from _schema_link_locations(node.get("items"), root, (*prefix, _ITEM), refs)
    # ``additionalProperties`` is not followed: no Link sits under one today, and if one ever did it would fail closed
    # (403), never open a path the schema does not declare.


@functools.lru_cache(maxsize=1)
def _link_locations() -> frozenset[tuple]:
    """Every place ``bam-roadmap/1`` declares a Link, as a path of property names and ``_ITEM`` (each array item)."""

    schema = schema_check.load()
    return frozenset(_schema_link_locations(schema, schema, (), frozenset()))


def _follow(node: object, location: tuple) -> Iterator[dict]:
    if not location:
        if isinstance(node, dict):
            yield node
        return
    step, rest = location[0], location[1:]
    if step is _ITEM:
        if isinstance(node, list):
            for item in node:
                yield from _follow(item, rest)
    elif isinstance(node, dict) and step in node:
        yield from _follow(node[step], rest)


def _links(document: dict) -> Iterator[dict]:
    """Every Link in a document, found only where the schema declares one (``_link_locations``).

    WHY the schema's declared locations and not every object with a ``path`` and an ``abs`` (Codex V07): evidence
    ``facts``, ``x`` and other free-form objects carry whatever a loop wrote (a ledger row's protocol metadata), so a
    generic walk let any loop row widen the allowlist to any file on the machine. A section the format adds later still
    joins the allowlist the moment the schema declares its Link, since the locations are read from the schema itself.
    """

    for location in _link_locations():
        yield from _follow(document, location)


def _allowlist(document: dict) -> frozenset[str]:
    """Every absolute path the document links to: each Link's ``abs``, or its ``path`` when ``base`` is ``"abs"``."""

    allowed: set[str] = set()
    for link in _links(document):
        absolute, path = link.get("abs"), link.get("path")
        if isinstance(absolute, str) and absolute.startswith("/"):
            allowed.add(absolute)
        if link.get("base") == "abs" and isinstance(path, str) and path.startswith("/"):
            allowed.add(path)
    return frozenset(allowed)


def _tracks() -> Response:
    """The built-in projector tracks whose loop is on this machine, plus every stored document.

    A live track is listed from its cached projection when there is one; listing never projects (that takes seconds).
    """

    docs_dir = Path(load_sources()["roadmap_docs_dir"])
    try:
        names = sorted(os.listdir(docs_dir))
    except (FileNotFoundError, NotADirectoryError):
        names = []
    tracks: dict[str, dict] = {}
    for track in PROJECTORS:
        try:
            live = projector_for(track)
        except UnknownSourceKey:
            continue  # not listed live: /doc?track=<id> says which key is unknown
        if live is None or not live[0].present(live[1]):
            continue
        cached = _cached_document(track, *live)
        tracks[track] = {"track": track, "title": (cached or {}).get("title") or live[0].title,
                         "generated_at": (cached or {}).get("generated_at")}
    for name in names:
        track = name.removesuffix(".json")
        if track == name or not _TRACK_ID.fullmatch(track) or track in tracks:
            continue
        title, generated_at = track, None
        try:
            document = _parse_document((docs_dir / name).read_bytes(), name)
        except (_InvalidDocument, OSError):
            pass  # still listed: /doc?track=<id> then says what is wrong with it
        else:
            if isinstance(document.get("title"), str):
                title = document["title"]
            if isinstance(document.get("generated_at"), str):
                generated_at = document["generated_at"]
        tracks[track] = {"track": track, "title": title, "generated_at": generated_at}
    return _json(200, {"tracks": [tracks[track] for track in sorted(tracks)]})


def _doc(query: Mapping[str, list[str]]) -> Response:
    track = _track_id(query)
    return _bytes(200, "application/json; charset=utf-8", _document(track, _refresh(query))[0])


def _evidence(query: Mapping[str, list[str]]) -> Response:
    track = _track_id(query)
    path = _single(query, "path")
    if path is None:
        raise _BadRequest("path is required")
    raw_line = _single(query, "line")
    line = None
    if raw_line is not None:
        if not _LINE.fullmatch(raw_line) or int(raw_line) < 1:
            raise _BadRequest("line must be a positive integer")
        line = int(raw_line)
    document = _document(track)[1]
    try:
        return _json(200, read_evidence(path, _allowlist(document), line))
    except RoadmapForbidden as error:
        return _error(403, str(error))
    except RoadmapNotFound as error:
        return _error(404, str(error))


def _art(name: str | None) -> Response:
    art_dir = Path(load_sources()["roadmap_art_dir"])
    if name is None:
        return _json(200, art_entries(art_dir))
    try:
        return _bytes(200, "image/png", read_art(art_dir, name))
    except RoadmapNotFound as error:
        return _error(404, str(error))


def handle(method: str, subpath: str, query: Mapping[str, list[str]], headers: Mapping[str, str]) -> Response:
    if method != "GET":
        return _error(405, "the roadmap routes are GET only")
    try:
        if subpath == "/tracks":
            return _tracks()
        if subpath == "/doc":
            return _doc(query)
        if subpath == "/evidence":
            return _evidence(query)
        if subpath == "/art":
            return _art(None)
        if subpath.startswith("/art/"):
            return _art(unquote(subpath[len("/art/"):]))
        return _error(404, f"no roadmap route {subpath or '/'!r}")
    except _BadRequest as error:
        return _error(400, str(error))
    except _NoRoadmap:
        return _error(404, "no roadmap reported yet")
    except _Unavailable as error:
        return _error(503, str(error))
    except (_InvalidDocument, UnknownSourceKey) as error:
        return _error(500, str(error))
