"""Local HTTP server: the browser lens over the files, plus the panel writes.

Reads re-derive everything from disk. Writes are limited to the three panel
gestures — status, dependencies, feedback comment — each revision-fenced and
atomic (see `edits`). The API is documented in docs/api.md.
"""

from __future__ import annotations

import errno
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from threading import Timer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser

from .edits import (
    append_feature_comment,
    update_feature_dependencies,
    update_feature_status,
)
from .errors import (
    InvalidTransition,
    RevisionConflict,
    UnknownFeature,
    VibeTracksError,
)
from .project import TrackProject, load_project

STATIC_DIR = Path(__file__).resolve().parent / "static"
FEATURE_ROUTE = re.compile(
    r"^/api/features/(?P<feature>[^/]+)/(?P<action>status|dependencies|comment)$"
)
MAX_BODY_BYTES = 256_000
REPORT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'none'; frame-ancestors 'self'"
)


class VibeTracksApplication:
    """Thin façade the HTTP handler calls into; owns no state but the path."""

    def __init__(self, descriptor: Path):
        self.descriptor = descriptor.resolve()

    def project(self) -> TrackProject:
        return load_project(self.descriptor)

    def snapshot(self) -> dict[str, Any]:
        return self.project().to_dict()

    def change_status(self, feature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return update_feature_status(
            self.descriptor,
            feature_id,
            str(payload["status"]),
            str(payload["expectedRevision"]),
        ).to_dict()

    def change_dependencies(self, feature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        depends_on = payload["dependsOn"]
        if not isinstance(depends_on, list):
            raise VibeTracksError("dependsOn must be a list")
        return update_feature_dependencies(
            self.descriptor,
            feature_id,
            [str(token) for token in depends_on],
            str(payload["expectedRevision"]),
        ).to_dict()

    def add_comment(self, feature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return append_feature_comment(
            self.descriptor,
            feature_id,
            str(payload["text"]),
            str(payload["expectedRevision"]),
        ).to_dict()


class VibeTracksHandler(SimpleHTTPRequestHandler):
    server_version = "VibeTracks/0.2"

    def __init__(self, *args: Any, application: VibeTracksApplication, **kwargs: Any):
        self.application = application
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, message: str, status: HTTPStatus) -> None:
        self._json({"error": message}, status)

    def _serve_project_file(self, relative_path: str) -> None:
        try:
            project = self.application.project()
            path = project.resolve_project_path(relative_path)
        except VibeTracksError as exc:
            self._error(str(exc), HTTPStatus.BAD_REQUEST)
            return
        if not path.is_file():
            self._error("File not found", HTTPStatus.NOT_FOUND)
            return
        content_type, _ = mimetypes.guess_type(path.name)
        content_type = content_type or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # Every project file gets the restrictive CSP, not just text/html —
        # SVG and XHTML can carry scripts and would otherwise run same-origin
        # with the write API when opened top-level from a hostile note.
        self.send_header("Content-Security-Policy", REPORT_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _host_allowed(self) -> bool:
        """DNS-rebinding guard: only loopback names (or the explicitly bound
        host) may address this server; a rebound public hostname gets 403."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        allowed = {"127.0.0.1", "localhost", "::1"}
        bound = self.server.server_address[0]
        if isinstance(bound, str) and bound not in {"", "0.0.0.0", "::"}:
            allowed.add(bound.lower())
        return host in allowed

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._error("Forbidden host", HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/project":
            try:
                known = parse_qs(parsed.query).get("known", [""])[0]
                project = self.application.project()
                if known and known == project.revision:
                    self._json({"revision": project.revision, "unchanged": True})
                else:
                    self._json(project.to_dict())
            except VibeTracksError as exc:
                self._error(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)
            except Exception as exc:  # a handler thread must answer, never die
                self._error(f"Internal error: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/media":
            requested = parse_qs(parsed.query).get("path", [""])[0]
            self._serve_project_file(unquote(requested))
            return
        if parsed.path == "/api/health":
            self._json({"ok": True, "descriptor": str(self.application.descriptor)})
            return
        if parsed.path in {"", "/"}:
            self.path = "/index.html"
        super().do_GET()

    def _read_json_body(self) -> dict[str, Any] | None:
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._error(
                "POST requests must send Content-Type: application/json",
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error("Invalid content length", HTTPStatus.BAD_REQUEST)
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            self._error("Expected a small JSON request body", HTTPStatus.BAD_REQUEST)
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            self._error(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._error("Expected a JSON object", HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._error("Forbidden host", HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        match = FEATURE_ROUTE.match(parsed.path)
        if not match:
            self._error("Unknown endpoint", HTTPStatus.NOT_FOUND)
            return
        payload = self._read_json_body()
        if payload is None:
            return
        feature_id = unquote(match.group("feature"))
        actions = {
            "status": self.application.change_status,
            "dependencies": self.application.change_dependencies,
            "comment": self.application.add_comment,
        }
        try:
            item = actions[match.group("action")](feature_id, payload)
            self._json({"item": item})
        except RevisionConflict as exc:
            self._error(str(exc), HTTPStatus.CONFLICT)
        except UnknownFeature as exc:
            self._error(str(exc), HTTPStatus.NOT_FOUND)
        except (InvalidTransition, KeyError, TypeError) as exc:
            self._error(str(exc), HTTPStatus.BAD_REQUEST)
        except VibeTracksError as exc:
            self._error(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:  # a handler thread must answer, never die
            self._error(f"Internal error: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)


def _bind(host: str, port: int, handler: Any, port_is_explicit: bool) -> ThreadingHTTPServer:
    """Bind the requested port; when it was a default, walk forward to a free one.

    Concurrent dispatcher sessions are normal — two agents each serving their
    own track must not fight over the default port.
    """
    attempts = [port] if port_is_explicit else list(range(port, port + 10))
    last_error: OSError | None = None
    for candidate in attempts:
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last_error = exc
    raise VibeTracksError(
        f"No free port in {attempts[0]}–{attempts[-1]} on {host}"
    ) from last_error


def serve(
    descriptor: Path,
    host: str = "127.0.0.1",
    port: int = 8777,
    open_browser: bool = False,
    port_is_explicit: bool = False,
) -> None:
    application = VibeTracksApplication(descriptor)
    project = application.project()
    handler = partial(VibeTracksHandler, application=application)
    server = _bind(host, port, handler, port_is_explicit)
    url = f"http://{host}:{server.server_port}/"
    print(f"Vibe Tracks · {project.title}: {url}", flush=True)
    print(f"Files: {project.source}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        Timer(0.15, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
