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
configuration, else the stored document when it is that configuration's (``_owned``), with a ``warnings`` entry saying
it is stale and why; 503 only when there is no such document at all. A failure is retried when its stamp moves, and
after ``_RETRY_FAILED_S`` regardless.
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
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
class RootClaim:
    """A source location a projector consumes and the document root it produces: ``roots[root]`` is ``location``
    (``exact``), or the checkout holding ``location`` while the document's declared sources include ``location /
    entry``, the projector's entry file there."""

    root: str
    location: Path
    exact: bool
    entry: str | None = None


@dataclass(frozen=True)
class LiveProjector:
    """One loop's live projection: what marks its loop present, which files stamp it, which checkout's HEAD, the call.

    ``loop`` is the ``loop`` its documents carry, and ``keys`` the ``sources.py`` keys it reads. ``claims`` is every
    source location it consumes, as the document ``roots`` entry that location produces (``_owned``).
    """

    name: str
    loop: str
    title: str
    present: Callable[[Mapping[str, str]], bool]
    keys: frozenset[str]
    inputs: Callable[[Mapping[str, str]], list[Path]]
    checkout: Callable[[Mapping[str, str]], Path]
    project: Callable[[Mapping[str, str], str], dict]
    claims: Callable[[Mapping[str, str]], list[RootClaim]]


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
    name="kinsim", loop="kinsim", title="Kinsim curriculum",
    present=lambda sources: (Path(sources["kinsim_curriculum_dir"]) / "curriculum.json").is_file(),
    keys=frozenset({"kinsim_curriculum_dir", "kinsim_home"}), inputs=_kinsim_inputs, checkout=lambda sources: Path(sources["kinsim_curriculum_dir"]),
    project=lambda sources, now: project_kinsim(Path(sources["kinsim_curriculum_dir"]), Path(sources["kinsim_home"]), now=now),
    claims=lambda sources: [RootClaim("repo", Path(sources["kinsim_curriculum_dir"]), exact=False, entry="curriculum.json"),
                            RootClaim("data_home", Path(sources["kinsim_home"]), exact=True)],
)
RIG = LiveProjector(
    name="rig", loop="rig", title="Rig loop",
    present=lambda sources: (Path(sources["rig_loop_dir"]) / "ladder.json").is_file(),
    keys=frozenset({"rig_loop_dir"}), inputs=_rig_inputs, checkout=lambda sources: Path(sources["rig_loop_dir"]),
    project=lambda sources, now: project_rig(Path(sources["rig_loop_dir"]), now=now),
    claims=lambda sources: [RootClaim("repo", Path(sources["rig_loop_dir"]), exact=False, entry="ladder.json")],
)
def _grasping_inputs(sources: Mapping[str, str]) -> list[Path]:
    package = Path(sources["grasp_bench_dir"]) / "src" / "grasp_bench"
    # registry.py is read from the working tree (each gate's env and model scope), so an uncommitted edit to it moves no
    # HEAD; the scoped code itself is judged by commits since each row's, which HEAD already covers.
    # gallery.py, ledger.py and attestations.jsonl are the bench's verdict (grasp_bench_bridge runs them): a change to its
    # rule or to what vouches for a row moves the verdict without moving the ledger or HEAD.
    # WHY every .py in the package and the venv's interpreter (Codex A01/A02, 2026-10-05): the verdict is whatever the
    # bench's own code computes in its own venv, and gallery.py reaches registry/contracts/envs through imports; a fixed
    # list missed some, and a removed or replaced venv left the cached document looking fresh. A few dozen stats.
    bench = Path(sources["grasp_bench_dir"])
    ledger = bench / "out" / "ledger"
    code = sorted(package.rglob("*.py")) if package.is_dir() else []
    return [*code, bench / ".venv" / "bin" / "python", bench / ".venv" / "pyvenv.cfg", ledger / "runs.jsonl",
            ledger / "attestations.jsonl"]


GRASPING = LiveProjector(
    name="grasping", loop="grasping", title="Grasp bench",
    present=lambda sources: (Path(sources["grasp_bench_dir"]) / "src" / "grasp_bench" / "curriculum.py").is_file(),
    keys=frozenset({"grasp_bench_dir"}), inputs=_grasping_inputs, checkout=lambda sources: Path(sources["grasp_bench_dir"]),
    project=lambda sources, now: project_grasping(Path(sources["grasp_bench_dir"]), now=now),
    claims=lambda sources: [RootClaim("repo", Path(sources["grasp_bench_dir"]), exact=False,
                                      entry="src/grasp_bench/curriculum.py"),
                            RootClaim("data_home", Path(sources["grasp_bench_dir"]) / "out", exact=True)],
)
DETECTION = LiveProjector(
    name="detection", loop="detection", title="Hyperspectral ladder (planned)",
    present=lambda sources: (Path(sources["detection_dir"]) / "ladder_data.py").is_file(),
    keys=frozenset({"detection_dir"}), inputs=lambda sources: [Path(sources["detection_dir"]) / "ladder_data.py"],
    checkout=lambda sources: Path(sources["detection_dir"]),
    project=lambda sources, now: project_detection(Path(sources["detection_dir"]), now=now),
    claims=lambda sources: [RootClaim("repo", Path(sources["detection_dir"]), exact=False, entry="ladder_data.py")],
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
    # WHY the destination keys too (Codex W04): {grasp_bench_dri: detection_dir} named a real source, so it resolved,
    # added a key no projector reads and left grasp_bench_dir on its default, projecting another loop's data silently.
    for input_key in named if isinstance(named, Mapping) else []:
        if input_key not in projector.keys:
            raise UnknownSourceKey(f"registry for {track} maps unknown destination key {input_key} (the {projector.name} "
                                   f"projector reads {', '.join(sorted(projector.keys))})")
    if isinstance(named, Mapping):  # {projector input: sources.py key}: read each input from the named key
        sources.update({input_key: sources[source_key] for input_key, source_key in named.items()})
    return True, (projector, sources)


def projector_for(track: str) -> tuple[LiveProjector, Mapping[str, str]] | None:
    """The projector that answers ``track`` live and the sources it reads; None when no loop projects it.

    The track registry from the Dashboard lane maps each track id to ``{"projector": <PROJECTORS key> | null,
    "sources": [<sources.py keys>] | {<projector input>: <sources.py key>}}``; without a reachable registry the built-in
    table answers. Raises ``UnknownSourceKey`` when the registry names a source key ``load_sources()`` lacks, or maps a
    destination key the projector does not read.
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
    #: ``_clock()`` when that projection failed.
    failed_at: float | None = None
    #: Requests holding this entry now (``_acquired``); read and written under ``_CACHES_LOCK``.
    refs: int = 0
    #: ``_clock()`` when a request last acquired or released it; read and written under ``_CACHES_LOCK``.
    touched: float = 0.0


#: Keyed by ``_cache_key``: (track, projector name, the resolved sources).
_CACHES: dict[tuple, _Cache] = {}
_CACHES_LOCK = threading.Lock()
#: An entry no request holds is dropped once it has gone this many seconds without a request.
_IDLE_EVICT_S = 600.0
#: A failed projection is tried again on the first request this many seconds after it failed, stamp moved or not.
_RETRY_FAILED_S = 60.0
#: How far before a projection started a newly linked file's mtime may sit and still count as written during it.
_MTIME_SLACK_NS = 2_000_000_000
_clock = time.monotonic


def _cache_key(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> tuple:
    # WHY the projector and its sources in the key, not only the track (Codex V08): a fallback document is the last
    # good projection of this exact configuration. Keyed by track alone, a track switched to another projector (or
    # pointed at other files) whose first projection failed was served the previous loop's document as its own.
    return track, projector.name, tuple(sorted(sources.items()))


@contextmanager
def _acquired(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> Iterator[_Cache]:
    """This configuration's entry, held for the request: never evicted while held, so it has one lock throughout."""

    key = _cache_key(track, projector, sources)
    with _CACHES_LOCK:
        now = _clock()
        cache = _CACHES.get(key)
        if cache is None:
            cache = _CACHES[key] = _Cache()
        cache.refs, cache.touched = cache.refs + 1, now
        # WHY evict only entries no request holds that have sat idle for _IDLE_EVICT_S, not by count (Codex W05, X03):
        # any count bound let a burst of requests on obsolete configurations push out the current configuration's last
        # good document, and even an entry mid-projection, whose next request then built a second lock and projected
        # beside the first. The current configuration is polled every 30 s, so it is never idle. The bound stays
        # honest without a count: an entry is a handful of documents, and configurations change only when someone edits
        # the registry or sources.json, so the idle ones are few and leave within ten minutes.
        for other_key, other in list(_CACHES.items()):
            if other.refs == 0 and now - other.touched >= _IDLE_EVICT_S:
                del _CACHES[other_key]
    try:
        yield cache
    finally:
        with _CACHES_LOCK:
            cache.refs, cache.touched = cache.refs - 1, _clock()


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


def _toplevel(path: Path) -> str | None:
    try:
        completed = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True,
                                   text=True, timeout=_GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return os.path.realpath(completed.stdout.strip())


def _same_checkout(repo: object, checkout: Path) -> bool:
    """Whether a document's ``roots.repo`` is the checkout ``checkout`` lies in.

    Their git toplevels when ``checkout`` is in a git checkout here; otherwise the real paths, ``checkout`` being
    ``repo`` or a directory under it (the projectors are handed a directory inside their checkout, e.g. the curriculum's).
    """

    if not isinstance(repo, str) or not repo.startswith("/"):
        return False
    mine = _toplevel(checkout) if checkout.exists() else None
    if mine is not None:
        return os.path.isdir(repo) and _toplevel(Path(repo)) == mine
    # WHY realpath even though the checkout is missing (Codex Z02): realpath resolves every symlink in the part that does
    # exist, so a loop configured through an alias still matches its own snapshot; the exact-entry claim stays the guard.
    checkout_path, repo_path = os.path.realpath(str(checkout)), os.path.realpath(repo)
    return checkout_path == repo_path or checkout_path.startswith(repo_path.rstrip("/") + "/")


def _declared_sources(document: dict) -> list[str]:
    """Every file the document's ``sources`` (the files its projection read) resolves to, existing or not."""

    roots = document.get("roots") if isinstance(document.get("roots"), Mapping) else {}
    sources = document.get("sources") if isinstance(document.get("sources"), list) else []
    return [path for link in sources if isinstance(link, Mapping) for path in [_link_path(link, roots)] if path]


def _owned(document: dict, projector: LiveProjector, sources: Mapping[str, str]) -> bool:
    """Whether a stored document is an earlier projection of this configuration: the projector's loop, and every source
    location it consumes (``LiveProjector.claims``) producing the document's ``roots``.

    WHY every consumed location and not only the checkout (Codex X01): kinsim reads a curriculum in the checkout and a
    data home outside it, so with ``kinsim_home`` pointed elsewhere the checkout still matched and the old data home's
    verdict was served for the new one. WHY the exact entry file and not any declared source under the directory (Codex
    Y01): the parent of a configured curriculum or rig directory contains the child's sources too, so pointing a key at
    the parent served the child's snapshot as that absent loop's. Paths are compared resolved.
    """

    roots = document.get("roots") if isinstance(document.get("roots"), Mapping) else {}
    if document.get("loop") != projector.loop:
        return False
    declared = {os.path.realpath(path) for path in _declared_sources(document)}
    for claim in projector.claims(sources):
        value = roots.get(claim.root)
        if claim.exact:
            if not isinstance(value, str) or os.path.realpath(value) != os.path.realpath(claim.location):
                return False
        elif not _same_checkout(value, claim.location) or claim.entry is None \
                or os.path.realpath(claim.location / claim.entry) not in declared:
            return False
    return True


def _stored_fallback(track: str, projector: LiveProjector, sources: Mapping[str, str]) -> dict | None:
    """The stored document of ``track`` when it may stand in for this configuration's live one (``_owned``), else None."""

    try:
        stored = _read_document(track)
    except _InvalidDocument:
        return None
    if stored is None or not _owned(stored[1], projector, sources):
        return None
    return stored[1]


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
    found = {path for link in _links(document) for path in [_link_path(link, roots)] if path}
    return [Path(path) for path in sorted(found)]


def _link_path(link: Mapping, roots: Mapping) -> str | None:
    """A Link's absolute file: its ``abs``, else its ``path`` resolved against its ``base``; None when neither resolves."""

    absolute, path, base = link.get("abs"), link.get("path"), link.get("base")
    if isinstance(absolute, str) and absolute.startswith("/"):
        return absolute
    if isinstance(path, str) and path:
        root = "/" if base == "abs" else roots.get(base) if isinstance(base, str) else None
        if isinstance(root, str) and root.startswith("/"):
            resolved = os.path.join(root, path)
            if resolved.startswith("/"):
                return os.path.normpath(resolved)
    return None


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


def _settled_stamp(projector: LiveProjector, sources: Mapping[str, str], basis: dict | None, before: tuple,
                   document: dict, started_ns: int) -> tuple | None:
    """The stamp to keep for ``document``, projected from what ``before`` stamped; None to project again next request.

    WHY not simply the stamp read after projecting (Codex W02): a file rewritten while the projector ran was read at
    its old version, and stamping its new version blessed that old verdict until something else moved. So the declared
    inputs, HEAD and the earlier document's linked files are read again and must equal ``before``; a file only the new
    document links to has no earlier reading, so it must have been written before the projection started (less
    ``_MTIME_SLACK_NS`` for coarse filesystem timestamps). The cost: a file being written right now re-projects on each
    request until it settles, which is right, since the data it carries is still moving.

    WHY each path is read once here and that reading is what is kept (Codex X02): a known link read again for the
    stored stamp could change between the comparison and that read, and its unchecked new version was then stamped onto
    the old verdict. A known link keeps the reading ``after`` compared; only the new document's other links are read.
    """

    after = _stamp(projector, sources, basis)
    if after != before:
        return None
    known = {stamp[0]: stamp for stamp in after[-1]}
    paths = [str(path) for path in _linked_files(document)]
    fresh = {stamp[0]: stamp for stamp in _file_stamps([Path(path) for path in paths if path not in known])}
    for path, *stat in fresh.values():
        if stat[0] is not None and stat[0] >= started_ns - _MTIME_SLACK_NS:
            return None
    return after[:-1] + (tuple(known[path] if path in known else fresh[path] for path in paths),)


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

    with _acquired(track, projector, sources) as cache:
        return _live_held(track, projector, sources, refresh, cache)


def _live_held(track: str, projector: LiveProjector, sources: Mapping[str, str], refresh: bool,
               cache: _Cache) -> tuple[bytes, dict]:
    # WHY one lock per configuration, held across the projection: the backend is threaded and a projection takes
    # seconds of git calls; concurrent requests for one configuration wait for that one projection and then read its
    # result from the cache. ``_acquired`` keeps the entry, and so this lock, for as long as any request holds it.
    with cache.lock:
        # WHY the stored fallback's links join the stamp while there is no good document in memory (Codex W06): a cold
        # start whose projection failed for want of a linked file otherwise never noticed that file coming back.
        fallback = None if cache.document is not None else _stored_fallback(track, projector, sources)
        basis = cache.document if cache.document is not None else fallback
        stamp = _stamp(projector, sources, basis)
        # WHY retry a failure after _RETRY_FAILED_S even on an unmoved stamp: the stamp cannot see every cause of a
        # failure (a file outside it, a git lock, a transient error), and a failure kept forever is a dashboard stuck stale.
        retry = cache.failure is not None and cache.failed_at is not None and _clock() - cache.failed_at >= _RETRY_FAILED_S
        if refresh or stamp != cache.stamp or retry:
            started_ns = time.time_ns()
            try:
                document = _project(projector, sources)
            # WHY every exception, not only ProjectionError: a projector bug on one odd loop row must leave the dashboard
            # on the last good document with the reason shown, not turn the track into a 500. Its stamp still covers the
            # last good document's linked files, so a failure is retried as soon as one of them changes or comes back.
            except Exception as error:  # noqa: BLE001
                cache.stamp, cache.failure, cache.failed_at = stamp, f"{type(error).__name__}: {error}", _clock()
            else:
                cache.stamp = _settled_stamp(projector, sources, basis, stamp, document, started_ns)
                cache.document, cache.body, cache.failure, cache.failed_at = document, _encode(document), None, None
        if cache.failure is None and cache.body is not None and cache.document is not None:
            return cache.body, cache.document
        failure, last_good = cache.failure, cache.document
    if last_good is not None:
        return _stale(last_good, f"stale: projecting the {track} loop live failed ({failure}); this is the last good "
                                 f"projection, generated {last_good.get('generated_at')}")
    if fallback is None:
        raise _Unavailable(f"projecting the {track} loop live failed ({failure}) and there is no earlier document of "
                           f"the {projector.loop} loop at {projector.checkout(sources)}")
    return _stale(fallback, f"stale: projecting the {track} loop live failed ({failure}); this is the stored document, "
                            f"generated {fallback.get('generated_at')}")


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
    # WHY a track with a live projector takes only its own loop's snapshot, always marked stale (Codex W01): any
    # <track>.json was served before, so a track pointed at another loop or checkout showed that loop's old green rungs
    # under its name, and an absent loop's snapshot read as current. Ineligible means 404, as if no file were there.
    if live is not None:
        projector, sources = live
        stored = _read_document(track)
        if stored is None or not _owned(stored[1], projector, sources):
            raise _NoRoadmap
        return _stale(stored[1], f"stale: the {projector.loop} loop is not on this machine; showing the stored "
                                 f"snapshot, generated {stored[1].get('generated_at')}")
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
