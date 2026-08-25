from __future__ import annotations

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

from .model import (
    InvalidTransition,
    RevisionConflict,
    TrackProject,
    VibeTracksError,
    load_project,
    update_feature_status,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
STATUS_ROUTE = re.compile(r"^/api/features/(?P<feature>[^/]+)/status$")


class VibeTracksApplication:
    def __init__(self, descriptor: Path):
        self.descriptor = descriptor.resolve()

    def project(self) -> TrackProject:
        return load_project(self.descriptor)

    def snapshot(self) -> dict[str, Any]:
        return self.project().to_dict()

    def change_status(self, feature_id: str, status: str, expected_revision: str) -> dict[str, Any]:
        return update_feature_status(
            self.descriptor,
            feature_id,
            status,
            expected_revision,
        ).to_dict()


class VibeTracksHandler(SimpleHTTPRequestHandler):
    server_version = "VibeTracks/0.1"

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
        if content_type == "text/html":
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/project":
            try:
                self._json(self.application.snapshot())
            except VibeTracksError as exc:
                self._error(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        match = STATUS_ROUTE.match(parsed.path)
        if not match:
            self._error("Unknown endpoint", HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error("Invalid content length", HTTPStatus.BAD_REQUEST)
            return
        if length <= 0 or length > 64_000:
            self._error("Expected a small JSON request body", HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            status = str(payload["status"])
            revision = str(payload["expectedRevision"])
            item = self.application.change_status(unquote(match.group("feature")), status, revision)
            self._json({"item": item})
        except RevisionConflict as exc:
            self._error(str(exc), HTTPStatus.CONFLICT)
        except (InvalidTransition, KeyError, TypeError, json.JSONDecodeError) as exc:
            self._error(str(exc), HTTPStatus.BAD_REQUEST)
        except VibeTracksError as exc:
            self._error(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)


def serve(
    descriptor: Path,
    host: str = "127.0.0.1",
    port: int = 8777,
    open_browser: bool = False,
) -> None:
    application = VibeTracksApplication(descriptor)
    project = application.project()
    handler = partial(VibeTracksHandler, application=application)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
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

