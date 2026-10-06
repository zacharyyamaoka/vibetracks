#!/usr/bin/env python3
"""The Vibe Tracks dashboard's backend: a loopback, stdlib HTTP server for Clank's plugin proxy.

    python3 clank/backend/server.py --port P [--workspace W] [--data-home DIR]

Routes (Clank proxies ``/api/plugins/vibetracks/<rest>`` here, clank-workbench CLAUDE.md §2.3):

- ``GET /health``            -> ``{ok, live, registry, data_home, projection, projection_exists, media, media_rev,
  media_revisions_kept}``
- ``GET /projection``        -> LIVE when the workspace's ``.vtdash`` names a work-track registry: built on each
  request from the registry by ``vibetracks.dashboard.build.LiveBuilder`` (adapters rerun only when a note, an
  adapter module or a declared source file changed); ``?rebuild=1`` drops that cache first. Without a registry,
  ``projection.json`` from the data home, re-read when it changes on disk, its media targets re-resolved on every
  request (so ``media_rev`` follows a retargeted alias even when the file is unchanged); ``?rebuild=1`` first reruns
  ``python3 -m vibetracks.dashboard.build --snapshot`` (the snapshot adapter).
- ``POST /tracks/<id>/title`` -> rename one work track: JSON ``{title, revision}`` (``Content-Type:
  application/json``, else 415). Revision-fenced (409 when the note changed since ``revision``), atomic, and it
  edits only the note's ``vibe-title`` value (``registry.rename_title``); ``vibe-id`` never changes. 400 for a bad
  title (empty, whitespace only, or containing a line break; never trimmed: it is stored exactly as typed) or body, 404 for an unknown id. Answers
  ``{ok, id, title, revision}`` with the note's new revision.
- ``GET /media/<id>?rev=<media_rev>`` -> one file named by ``media[<id>]`` of the projection that answered with that
  ``media_rev``, streamed with Range support (so a ``<video>`` seeks) and its real content type. Every /projection
  answer carries ``media_rev``; the backend keeps the canonical targets recorded under each of the last
  ``MEDIA_REVISIONS_KEPT`` revisions. A missing, unknown or evicted ``rev`` is 409 (reload), as is a listed path that
  now resolves elsewhere; an id that revision did not list is 404.
- ``GET <mount prefix>/...`` -> the callable ``mounts.MOUNTS`` names for that prefix (backend/mounts.py has the
  handler signature), imported lazily; 503 when its import fails, 501 for any method but GET.

The rename is the only write: every other POST, and every PUT, PATCH and DELETE, answers 501. WHY an allowlist built
from the projection and never a path parameter: the page names media by id only, so a crafted URL cannot reach a file
the projection does not list (BRIEF G3, local-only); and by revision, so a URL reaches only the files listed in the
projection it came from.

Data home: ``--data-home`` > ``$VIBETRACKS_DASHBOARD_HOME`` > the ``data_home`` of the workspace's ``.vtdash`` files
(when they agree) > ``dashboard_data_home`` from vibetracks/sources.py (``~/.local/share/vibetracks/dashboard``).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parents[1]


def _load_mounts():
    """The sibling ``mounts.py``. WHY not a bare ``import mounts`` alone: run as a program (Clank, or
    ``python3 clank/backend/server.py``) this directory is ``sys.path[0]`` and the import finds the sibling; loaded by
    file location from a test elsewhere (tests/test_dashboard_needs_unreadable.py) it is not on the path, and a test
    must not put it there (it would shadow ``tests/test_server.py`` with this directory's ``test_server.py`` and break
    ``unittest discover -s tests``). So: the importable sibling when it is that file, else load it by its path."""
    try:
        import mounts as found  # noqa: PLC0415
    except ModuleNotFoundError:
        found = None
    if found is not None and Path(getattr(found, "__file__", "") or "").resolve() == BACKEND_DIR / "mounts.py":
        return found
    spec = importlib.util.spec_from_file_location("vibetracks_dashboard_backend_mounts", BACKEND_DIR / "mounts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mounts = _load_mounts()
if str(REPO_ROOT) not in sys.path:
    # Clank sets PYTHONPATH={pluginDir}/.. (the repo root); a bare `python3 clank/backend/server.py` or the unittest
    # run from clank/backend does not, and vibetracks.sources must import either way.
    sys.path.append(str(REPO_ROOT))
from vibetracks.dashboard.build import LiveBuilder  # noqa: E402
from vibetracks.dashboard.registry import TitleInvalid, find_registry, rename_title  # noqa: E402
from vibetracks.edits import read_note_exact  # noqa: E402
from vibetracks.errors import RevisionConflict, UnknownFeature, VibeTracksError  # noqa: E402
from vibetracks.notes import note_revision  # noqa: E402
from vibetracks.safe_open import UnsafePath, open_no_symlinks  # noqa: E402
from vibetracks.sources import load_sources  # noqa: E402


def default_home() -> Path:
    return Path(load_sources()["dashboard_data_home"])


DEFAULT_HOME = default_home()
#: A media id's spelling. WHY ":" is allowed (verifier, 2026-10-05, leftover (d)): adapters namespace ids by track
#: ("grasping:gallery-preview"), and a regex that forbade ":" made those ids 404 forever beside a dead "Open in new
#: tab" link. Renaming ids to fit the regex was rejected: an id is a reference other entries and links carry, and the
#: client already sends it through encodeURIComponent (":" travels as %3A and is unquoted before this check). Still no
#: "/", "%", "?", "#", whitespace or a leading dot, so an id can never read as a path or a query.
MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,200}$")
RENAME_ROUTE = re.compile(r"^/tracks/([^/]+)/title$")
#: A rename body is a title and a revision; anything near this size is not one.
MAX_JSON_BODY = 64 * 1024
#: Content types the backend will stream; a projection entry of any other suffix is refused.
SERVABLE = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}
CHUNK = 1 << 16
#: How many media revisions keep their recorded targets. A page open on an older one is told to reload (409).
MEDIA_REVISIONS_KEPT = 64
#: The key the backend adds to every /projection answer; media URLs carry its value as ``?rev=``.
MEDIA_REV_KEY = "media_rev"


def resolve_data_home(cli: str | None, workspace: str | None, environ: dict[str, str] | os._Environ = os.environ) -> Path:
    if cli:
        return Path(cli).expanduser()
    if environ.get("VIBETRACKS_DASHBOARD_HOME"):
        return Path(environ["VIBETRACKS_DASHBOARD_HOME"]).expanduser()
    if workspace:
        homes = set()
        try:
            files = sorted(Path(workspace).glob("*.vtdash"))
        except OSError:
            files = []
        for file in files:
            try:
                value = json.loads(file.read_text(encoding="utf-8")).get("data_home")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(value, str) and value.strip():
                homes.add(str(Path(value).expanduser()))
        if len(homes) == 1:
            return Path(homes.pop())
    return default_home()


MountHandler = Callable[[str, str, "dict[str, list[str]]", Mapping[str, str]], "tuple[int, dict[str, str], Iterable[bytes]]"]


class MountUnavailable(Exception):
    """The mount's module or callable could not be imported."""


_mount_cache: dict[str, MountHandler] = {}
_mount_lock = threading.Lock()


def find_mount(path: str) -> tuple[str, str, str] | None:
    """(prefix, target, subpath) for the first mount whose prefix owns ``path``, else None.

    ``/roadmap`` owns ``/roadmap`` and ``/roadmap/...`` but not ``/roadmapx``. Read at request time, so a test (or the
    roadmap session) can append to ``mounts.MOUNTS`` without restarting anything.
    """

    for prefix, target in list(mounts.MOUNTS):
        prefix = "/" + prefix.strip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return prefix, target, path[len(prefix):]
    return None


def resolve_mount(target: str) -> MountHandler:
    """Import ``"package.module:callable"`` once; a failure raises MountUnavailable and is not cached (retried)."""

    with _mount_lock:
        cached = _mount_cache.get(target)
        if cached is not None:
            return cached
        module_name, _, attribute = target.partition(":")
        try:
            module = importlib.import_module(module_name)
            handler = getattr(module, attribute or "handle")
        except Exception as error:  # ImportError, a SyntaxError inside the module, a missing attribute, ...
            raise MountUnavailable(f"{type(error).__name__}: {error}") from error
        if not callable(handler):
            raise MountUnavailable(f"{target} is not callable")
        _mount_cache[target] = handler
        return handler


def canonical_targets(media: Mapping[str, Any]) -> dict[str, str | None]:
    """Each media id's canonical file (``os.path.realpath``) at the moment the allowlist is built.

    None when the entry cannot be served at all then: no absolute path, a ``..`` part, a missing file, or a listed
    suffix not in ``SERVABLE``. ``media_lookup`` refuses (403) any id whose path resolves elsewhere later, or whose
    resolved target's own suffix is not served.
    """

    targets: dict[str, str | None] = {}
    for media_id, entry in media.items():
        raw = entry.get("path") if isinstance(entry, dict) else None
        target = None
        if isinstance(raw, str) and Path(raw).is_absolute() and ".." not in Path(raw).parts \
                and Path(raw).suffix.lower() in SERVABLE:
            try:
                resolved = os.path.realpath(raw, strict=True)
            except OSError:
                resolved = None
            target = resolved  # its own suffix is checked when served (403), so a refusal can say why
        targets[str(media_id)] = target
    return targets


def media_revision(media: Mapping[str, Any], targets: Mapping[str, str | None]) -> str:
    """A digest of every media id with its listed path and the canonical target recorded for it.

    WHY a digest of the targets and not a counter: the same allowlist resolving to the same files gives the same
    revision, so a poll or a second tab that changes nothing leaves every media URL (and a playing video) untouched,
    while a retargeted alias gives a new revision and a new URL.
    """
    rows = []
    for media_id in sorted(targets):
        entry = media.get(media_id)
        listed = entry.get("path") if isinstance(entry, dict) else None
        rows.append([media_id, listed if isinstance(listed, str) else None, targets[media_id]])
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class MediaRevisions:
    """The canonical targets recorded under each media revision handed out: a bounded LRU, newest last.

    WHY (audit 2026-10-05 round 2, sibling of finding 1): the allowlist used to be "whatever the latest /projection
    load resolved", so another tab or a poll re-authorised a media URL minted before a symlink was retargeted. A
    /media request now names its revision and is served only from the targets recorded under it; a revision this
    backend no longer holds (evicted, or a restart) is never rebuilt from the current state: the page must reload.
    """

    def __init__(self, limit: int = MEDIA_REVISIONS_KEPT):
        self.limit = limit
        self._lock = threading.Lock()
        self._kept: OrderedDict[str, dict[str, tuple[str | None, str | None]]] = OrderedDict()

    def record(self, media: Mapping[str, Any], targets: Mapping[str, str | None]) -> str:
        revision = media_revision(media, targets)
        rows: dict[str, tuple[str | None, str | None]] = {}
        for media_id, target in targets.items():
            entry = media.get(media_id)
            listed = entry.get("path") if isinstance(entry, dict) else None
            rows[media_id] = (listed if isinstance(listed, str) else None, target)
        with self._lock:
            # WHY keep the first record of a revision: equal digests mean equal rows, and the original is the one
            # every URL carrying this revision was minted against.
            self._kept.setdefault(revision, rows)
            self._kept.move_to_end(revision)
            while len(self._kept) > self.limit:
                self._kept.popitem(last=False)
        return revision

    def get(self, revision: str) -> dict[str, tuple[str | None, str | None]] | None:
        with self._lock:
            rows = self._kept.get(revision)
            if rows is not None:
                self._kept.move_to_end(revision)
            return rows

    def __len__(self) -> int:
        with self._lock:
            return len(self._kept)


def with_media_rev(raw: bytes, data: Any, revision: str) -> bytes:
    """``raw`` with ``"media_rev": revision`` added as the object's LAST member; every other byte is left as stored.

    WHY splice and not ``json.dumps(json.loads(raw))``: projection.json is served as written (no number or string is
    re-spelled), and a key added last wins in ``JSON.parse`` even if the file already had one of that name.
    """
    if not isinstance(data, dict):
        return raw
    end = raw.rstrip().rfind(b"}")
    if end < 0:
        return raw
    member = json.dumps(MEDIA_REV_KEY).encode("utf-8") + b":" + json.dumps(revision).encode("utf-8")
    return raw[:end] + (b"," if data else b"") + member + raw[end:]


class Projection:
    """projection.json, re-read when its mtime or size changes; the media allowlist comes from it, its targets
    re-resolved on every load."""

    live = False
    registry: Path | None = None

    def __init__(self, home: Path):
        self.home = home
        self.path = home / "projection.json"
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        #: projection.json's bytes and parsed value as last read (snapshot mode); ``_raw`` is them plus ``media_rev``
        self._stored: bytes | None = None
        self._data: Any = None
        self._raw: bytes | None = None
        self._media: dict[str, dict[str, Any]] = {}
        #: media id -> the canonical file its path resolved to when the allowlist was built (None: not servable then)
        self._targets: dict[str, str | None] = {}
        #: the media revision of the last projection answered; every answer carries it (``media_rev``)
        self._rev: str | None = None
        self.revisions = MediaRevisions()

    def load(self) -> bytes | None:
        """projection.json plus the ``media_rev`` of the targets its media paths resolve to NOW.

        WHY the targets are re-resolved on every load and not only when the file's stamp changes (verifier, 2026-10-05,
        leftover (a)): an alias retargeted while projection.json stays byte-identical used to keep the old revision,
        so its URL answered 409 "reload" forever and the page's reload control could never recover. Re-resolving here
        gives that reload a new revision that lists what the path names now; the old revision still holds its own
        recorded targets, so it never serves the new file. Same files, same digest: a poll changes no URL.
        """
        with self._lock:
            try:
                info = self.path.stat()
            except FileNotFoundError:
                self._stamp, self._stored, self._data, self._raw = None, None, None, None
                self._media, self._targets, self._rev = {}, {}, None
                return None
            stamp = (info.st_mtime_ns, info.st_size)
            if stamp != self._stamp or self._stored is None:
                raw = self.path.read_bytes()
                data = json.loads(raw)
                media = data.get("media") if isinstance(data, dict) else None
                self._stored, self._data, self._stamp = raw, data, stamp
                self._media = media if isinstance(media, dict) else {}
                self._raw = None
            self._targets = canonical_targets(self._media)
            revision = self.revisions.record(self._media, self._targets)  # also keeps the revision on screen newest
            if revision != self._rev or self._raw is None:
                self._rev = revision
                self._raw = with_media_rev(self._stored, self._data, revision)
            return self._raw

    def media(self, media_id: str, revision: str | None) -> Path | None:
        """The canonical file to open for ``media_id`` under ``revision``, or None when ``media_lookup`` refuses it."""

        return self.media_lookup(media_id, revision)[0]

    def media_lookup(self, media_id: str, revision: str | None) -> tuple[Path | None, int, str]:
        """``(canonical file, 200, "")``, or ``(None, status, why)``.

        Looked up ONLY in the targets recorded under ``revision`` (the ``media_rev`` of the projection the page
        shows), never in the latest load: 409 when that revision is missing, unknown or evicted, or when the listed
        path now resolves somewhere other than the file recorded under it (reload; the page then gets a revision
        that lists what is there now); 404 for an id that revision did not list, a bad spelling, an entry that was
        not servable when recorded, or a file that is gone; 403 when the recorded file's own suffix is not served.

        WHY re-resolve and compare (audit 2026-10-04, finding 9): a listed path that is a symlink can be retargeted
        after listing; the caller opens the returned canonical path (recorded, symlink-free), never the alias.
        """

        if not MEDIA_ID.match(media_id):
            return None, 404, "unknown media id"
        rows = self.revisions.get(revision) if isinstance(revision, str) and revision else None
        if rows is None:
            return None, 409, "this page's media list is no longer held by the backend; reload"
        row = rows.get(media_id)
        if row is None:
            return None, 404, "unknown media id"
        listed, recorded = row
        if listed is None:
            return None, 404, "unknown media id"
        path = Path(listed)
        if not path.is_absolute() or ".." in path.parts or path.suffix.lower() not in SERVABLE:
            return None, 404, "unknown media id"  # an unservable listing is no entry at all, as before
        if recorded is None:
            return None, 404, "the listed file was not a servable file when the projection was built"
        try:
            current = os.path.realpath(path, strict=True)
        except OSError:
            return None, 404, "the listed file is gone"
        if current != recorded:
            return None, 409, "the listed path now resolves to a different file than when this page loaded; reload"
        if Path(recorded).suffix.lower() not in SERVABLE:
            return None, 403, f"the listed path resolves to a {Path(recorded).suffix or 'suffix-less'} file, which is not served"
        try:
            if not Path(recorded).is_file():
                return None, 404, "not a regular file"
        except OSError:
            return None, 404, "not a regular file"
        return Path(recorded), 200, ""


class LiveProjection(Projection):
    """The projection built live from the work-track registry; the media allowlist is the last build's ``media``."""

    live = True

    def __init__(self, home: Path, workspace: Path, registry: Path):
        super().__init__(home)
        self.registry = registry
        self.builder = LiveBuilder(workspace, home)

    def load(self, force: bool = False) -> bytes:
        projection = self.builder.build(force=force)
        with self._lock:
            media = projection.get("media")
            self._media = media if isinstance(media, dict) else {}
            self._targets = canonical_targets(self._media)
            self._rev = self.revisions.record(self._media, self._targets)
            # A shallow copy: the builder may hand back its cached dict, which must not gain our key.
            raw = json.dumps({**projection, MEDIA_REV_KEY: self._rev}, ensure_ascii=False).encode("utf-8")
            self._raw = raw
        return raw


def rebuild(home: Path) -> tuple[bool, str]:
    env = {**os.environ, "VIBETRACKS_DASHBOARD_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run([sys.executable, "-m", "vibetracks.dashboard.build", "--snapshot", "--data-home", str(home)],
                            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """(start, end) inclusive, None for no/ignored Range, 'unsatisfiable' for a range outside the file."""

    if not header:
        return None
    match = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header)
    if not match or (not match.group(1) and not match.group(2)):
        return None  # multi-range or malformed: answer the whole file (RFC 9110 allows ignoring Range)
    first, last = match.group(1), match.group(2)
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        length = int(last)
        if length == 0:
            return "unsatisfiable"
        start, end = max(0, size - length), size - 1
    if start >= size or start > end:
        return "unsatisfiable"
    return start, end


def make_handler(projection: Projection, workspace: Path | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "vibetracks-dashboard/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # stdout, which the host keeps
            sys.stdout.write("[vibetracks] " + (fmt % args) + "\n")

        def _json(self, status: int, payload: Any, close: bool = False) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._raw(status, body, "application/json", close=close)

        def _raw(self, status: int, body: bytes, content_type: str, head: bool = False, close: bool = False) -> None:
            self.send_response(status)
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            # WHY also check the method: a HEAD answer must carry no body, or the client (which reads none) leaves
            # bytes on the socket and the connection ends in a reset; every JSON error path goes through here.
            if not head and self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self) -> None:
            self._route(head=True)

        def do_GET(self) -> None:
            self._route(head=False)

        def _not_implemented(self) -> None:
            mount = find_mount(urlsplit(self.path).path)
            where = f"the {mount[0]} mount" if mount else "this backend"
            # WHY close: the request body is never read, so on a kept-alive connection it would parse as the next
            # request (a 400 into a socket the client already left).
            self._json(501, {"error": f"{self.command} is not supported: {where} is read-only (GET only)"}, close=True)

        do_PUT = do_PATCH = do_DELETE = _not_implemented

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            match = RENAME_ROUTE.fullmatch(path)
            if match is None or find_mount(path) is not None:
                return self._not_implemented()
            return self._rename(unquote(match.group(1)))

        def _read_json_body(self) -> tuple[Any, None] | tuple[None, tuple[int, str]]:
            """(payload, None) or (None, (status, error)); the body is always consumed or the connection closed."""

            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length) if raw_length is not None else 0
            except ValueError:
                self.close_connection = True
                return None, (400, "Content-Length is not a number")
            if length < 0 or length > MAX_JSON_BODY:
                self.close_connection = True
                return None, (413 if length > 0 else 400, f"the body must be 0-{MAX_JSON_BODY} bytes")
            body = self.rfile.read(length) if length else b""
            content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return None, (415, "Content-Type must be application/json")
            try:
                return json.loads(body.decode("utf-8")), None
            except (UnicodeDecodeError, ValueError) as error:
                return None, (400, f"the body is not JSON: {error}")

        def _rename(self, track_id: str) -> None:
            payload, failure = self._read_json_body()
            if failure is not None:
                return self._json(failure[0], {"error": failure[1]}, close=self.close_connection)
            if not isinstance(payload, dict):
                return self._json(400, {"error": "the body must be a JSON object {title, revision}"})
            revision = payload.get("revision")
            if not isinstance(revision, str) or not revision.strip():
                return self._json(400, {"error": "revision is required: the note revision the title was read at"})
            if workspace is None or find_registry(workspace) is None:
                return self._json(404, {"error": "no work-track registry in this workspace"})
            try:
                title, new_revision = rename_title(workspace, track_id, payload.get("title"), revision.strip())
            except TitleInvalid as error:
                return self._json(400, {"error": str(error)})
            except UnknownFeature as error:
                return self._json(404, {"error": str(error)})
            except RevisionConflict as error:
                return self._json(409, {"error": str(error), "revision": self._current_revision(track_id)})
            except VibeTracksError as error:
                return self._json(400, {"error": str(error)})
            return self._json(200, {"ok": True, "id": track_id, "title": title, "revision": new_revision})

        def _current_revision(self, track_id: str) -> str | None:
            """The note's revision now, so a 409 lets the page re-read and retry without a second request."""

            try:
                from vibetracks.dashboard.registry import read_registry
                track = read_registry(workspace).by_id(track_id) if workspace is not None else None
                return note_revision(read_note_exact(Path(track.note_path))) if track else None
            except (OSError, VibeTracksError):
                return None

        def _route(self, head: bool) -> None:
            url = urlsplit(self.path)
            path = url.path
            # Loopback is enforced where the socket is bound (serve() refuses any other host), so every request that
            # reaches this point is already local; mounts are dispatched before the built-in routes so a prefix wins.
            # roadmap session appends ('/roadmap', 'vibetracks.roadmap.api:handle') here  (backend/mounts.py)
            mount = find_mount(path)
            if mount is not None:
                if head:
                    return self._json(501, {"error": f"HEAD is not supported: the {mount[0]} mount is GET only"})
                return self._dispatch_mount(mount, url.query)
            if path == "/health":
                raw = None
                try:
                    raw = projection._raw if projection.live and projection._raw is not None else projection.load()
                except Exception:  # health must answer even when a build fails; /projection says why
                    pass
                return self._json(200, {
                    "ok": True,
                    "live": projection.live,
                    "registry": str(projection.registry) if projection.registry else None,
                    "data_home": str(projection.home),
                    "projection": "live" if projection.live else str(projection.path),
                    "projection_exists": raw is not None,
                    "media": len(projection._media),
                    "media_rev": projection._rev,
                    "media_revisions_kept": len(projection.revisions),
                })
            if path == "/projection":
                force = parse_qs(url.query).get("rebuild", ["0"])[0] in ("1", "true")
                if projection.live:
                    try:
                        raw = projection.load(force=force)  # type: ignore[call-arg]
                    except Exception as error:  # a broken registry answers 500 with the reason; the server keeps serving
                        return self._json(500, {"error": "live build failed", "detail": f"{type(error).__name__}: {error}"})
                    return self._raw(200, raw, "application/json", head=head)
                if force:
                    ok, log = rebuild(projection.home)
                    if not ok:
                        return self._json(500, {"error": "rebuild failed", "log": log[-4000:]})
                try:
                    raw = projection.load()
                except ValueError as error:
                    return self._json(500, {"error": f"projection.json is not valid JSON: {error}"})
                if raw is None:
                    return self._json(404, {"error": f"no projection at {projection.path}; run python3 -m vibetracks.dashboard.build or GET /projection?rebuild=1"})
                return self._raw(200, raw, "application/json", head=head)
            if path.startswith("/media/"):
                media_id = unquote(path[len("/media/"):])
                revision = parse_qs(url.query).get("rev", [None])[0]
                file, status, why = projection.media_lookup(media_id, revision)
                if file is None:
                    return self._json(status, {"error": why})
                return self._send_file(file, head)
            return self._json(404, {"error": "not found"})

        def _dispatch_mount(self, mount: tuple[str, str, str], query: str) -> None:
            prefix, target, subpath = mount
            try:
                handler = resolve_mount(target)
            except MountUnavailable as error:
                return self._json(503, {"error": f"the {prefix} mount is unavailable: {target} did not import", "detail": str(error)})
            try:
                status, headers, body = handler("GET", subpath, parse_qs(query), self.headers)
            except Exception as error:  # a handler bug answers 500 for this request; the server keeps serving
                return self._json(500, {"error": f"the {prefix} mount failed", "detail": f"{type(error).__name__}: {error}"})
            headers = dict(headers or {})
            length = next((value for key, value in headers.items() if key.lower() == "content-length"), None)
            chunks: Iterable[bytes] = body
            if length is None:
                # WHY join when no length is given: HTTP/1.1 keep-alive needs a Content-Length (or chunking) to find
                # the end of the body, and a JSON answer is small; a large stream should set its own length.
                try:
                    payload = b"".join(body)
                except Exception as error:
                    return self._json(500, {"error": f"the {prefix} mount failed", "detail": f"{type(error).__name__}: {error}"})
                headers["Content-Length"] = str(len(payload))
                chunks = (payload,)
            try:
                self.send_response(int(status))
                for key, value in headers.items():
                    self.send_header(key, value)
                if not any(key.lower() == "cache-control" for key in headers):
                    self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        def _send_file(self, file: Path, head: bool) -> None:
            # WHY open_no_symlinks on the canonical path (audit 2026-10-05, finding 2): the path holds no symlink, so
            # one found at ANY component at open time (a parent directory swapped for a link after media_lookup's
            # check) is a substitution and fails, where O_NOFOLLOW alone guarded only the last component. It also
            # refuses anything but a regular file; size and type come from the opened file itself.
            try:
                fd = open_no_symlinks(str(file))
            except UnsafePath:
                return self._json(403, {"error": "the listed file changed while it was being opened"})
            except FileNotFoundError:
                return self._json(404, {"error": "the listed file is gone"})
            except OSError as error:
                return self._json(403, {"error": f"the listed file could not be opened: {error.strerror}"})
            handle = os.fdopen(fd, "rb")
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    return self._json(403, {"error": "the listed file is not a regular file"})
                self._stream_open(handle, info.st_size, SERVABLE[file.suffix.lower()], head)
            finally:
                handle.close()

        def _stream_open(self, handle: Any, size: int, content_type: str, head: bool) -> None:
            wanted = parse_range(self.headers.get("Range"), size)
            if wanted == "unsatisfiable":
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if wanted is None:
                start, end, status = 0, size - 1, 200
            else:
                start, end = wanted
                status = 206
            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "private, max-age=300")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head or length == 0:
                return
            try:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the player moved on (a seek closes the old request)

    return Handler


def serve(port: int, home: Path, host: str = "127.0.0.1", workspace: str | Path | None = None) -> ThreadingHTTPServer:
    """Live from the registry when ``workspace`` names one, else the data home's projection.json."""

    if host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit(f"refusing to bind {host}: loopback only")
    workspace_path = Path(workspace) if workspace else None
    registry = find_registry(workspace_path) if workspace_path is not None else None
    projection = LiveProjection(home, workspace_path, registry) if registry is not None and workspace_path is not None \
        else Projection(home)
    server = ThreadingHTTPServer((host, port), make_handler(projection, workspace_path))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workspace")
    parser.add_argument("--data-home")
    args = parser.parse_args(argv)
    if args.workspace:
        # WHY: mounted handlers (the roadmap projector) find the registry through this, not the process cwd,
        # which Clank happens to set to the workspace but nothing else guarantees.
        os.environ["VIBETRACKS_WORKSPACE"] = args.workspace
    home = resolve_data_home(args.data_home, args.workspace)
    server = serve(args.port, home, workspace=args.workspace)
    # Exit on SIGTERM (clank-workbench CLAUDE.md §2.4): the host stops the process group this way.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    mode = "live from the work-track registry" if args.workspace and find_registry(args.workspace) else "projection.json"
    print(f"[vibetracks] serving {home} ({mode}) on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
