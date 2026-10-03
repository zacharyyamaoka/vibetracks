#!/usr/bin/env python3
"""The Vibe Tracks dashboard's backend: a read-only, loopback, stdlib HTTP server for Clank's plugin proxy.

    python3 clank/backend/server.py --port P [--workspace W] [--data-home DIR]

Routes (Clank proxies ``/api/plugins/vibetracks/<rest>`` here, clank-workbench CLAUDE.md §2.3):

- ``GET /health``            -> ``{ok, data_home, projection, projection_exists, media}``
- ``GET /projection``        -> ``projection.json`` from the data home, re-read when it changes on disk;
  ``?rebuild=1`` first reruns ``python3 -m vibetracks.dashboard.build`` (the snapshot adapter).
- ``GET /media/<id>``        -> one file named by ``projection.media[<id>]``, streamed with Range support (so a
  ``<video>`` seeks) and its real content type. Anything else is 404.
- ``GET <mount prefix>/...`` -> the callable ``mounts.MOUNTS`` names for that prefix (backend/mounts.py has the
  handler signature), imported lazily; 503 when its import fails, 501 for any method but GET.

There are no write endpoints: POST, PUT, PATCH and DELETE answer 501 everywhere. WHY an allowlist built from the projection and never a path parameter: the page names
media by id only, so a crafted URL cannot reach a file the projection does not list (BRIEF G3, local-only).

Data home: ``--data-home`` > ``$VIBETRACKS_DASHBOARD_HOME`` > the ``data_home`` of the workspace's ``.vtdash`` files
(when they agree) > ``dashboard_data_home`` from vibetracks/sources.py (``~/.local/share/vibetracks/dashboard``).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

import mounts

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    # Clank sets PYTHONPATH={pluginDir}/.. (the repo root); a bare `python3 clank/backend/server.py` or the unittest
    # run from clank/backend does not, and vibetracks.sources must import either way.
    sys.path.append(str(REPO_ROOT))
from vibetracks.sources import load_sources  # noqa: E402


def default_home() -> Path:
    return Path(load_sources()["dashboard_data_home"])


DEFAULT_HOME = default_home()
MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
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


class Projection:
    """projection.json, re-read when its mtime or size changes; the media allowlist comes from it."""

    def __init__(self, home: Path):
        self.home = home
        self.path = home / "projection.json"
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._raw: bytes | None = None
        self._media: dict[str, dict[str, Any]] = {}

    def load(self) -> bytes | None:
        with self._lock:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                self._stamp, self._raw, self._media = None, None, {}
                return None
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self._stamp:
                raw = self.path.read_bytes()
                data = json.loads(raw)
                media = data.get("media") if isinstance(data, dict) else None
                self._media = media if isinstance(media, dict) else {}
                self._raw, self._stamp = raw, stamp
            return self._raw

    def media(self, media_id: str) -> Path | None:
        """The file for ``media_id``, or None: unknown id, bad spelling, unservable type, or not a regular file."""

        if not MEDIA_ID.match(media_id):
            return None
        self.load()
        entry = self._media.get(media_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return None
        path = Path(entry["path"])
        if not path.is_absolute() or ".." in path.parts or path.suffix.lower() not in SERVABLE:
            return None
        try:
            if not path.is_file():
                return None
        except OSError:
            return None
        return path


def rebuild(home: Path) -> tuple[bool, str]:
    env = {**os.environ, "VIBETRACKS_DASHBOARD_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run([sys.executable, "-m", "vibetracks.dashboard.build", "--data-home", str(home)],
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


def make_handler(projection: Projection):
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

        do_POST = do_PUT = do_PATCH = do_DELETE = _not_implemented

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
                    raw = projection.load()
                except ValueError:
                    pass
                return self._json(200, {
                    "ok": True,
                    "data_home": str(projection.home),
                    "projection": str(projection.path),
                    "projection_exists": raw is not None,
                    "media": len(projection._media),
                })
            if path == "/projection":
                if parse_qs(url.query).get("rebuild", ["0"])[0] in ("1", "true"):
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
                file = projection.media(media_id)
                if file is None:
                    return self._json(404, {"error": "unknown media id"})
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
            size = file.stat().st_size
            content_type = SERVABLE[file.suffix.lower()]
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
                with open(file, "rb") as handle:
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


def serve(port: int, home: Path, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit(f"refusing to bind {host}: loopback only")
    server = ThreadingHTTPServer((host, port), make_handler(Projection(home)))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workspace")
    parser.add_argument("--data-home")
    args = parser.parse_args(argv)
    home = resolve_data_home(args.data_home, args.workspace)
    server = serve(args.port, home)
    # Exit on SIGTERM (clank-workbench CLAUDE.md §2.4): the host stops the process group this way.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"[vibetracks] serving {home} on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
