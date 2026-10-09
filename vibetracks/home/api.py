"""The home's routes on the dashboard backend, mounted at ``/home`` (clank/backend/mounts.py; docs/peps/0001).

    GET /home                -> the ``vibetracks-home/1`` document (JSON). A browser asking for HTML (``Accept:
                                text/html`` without JSON) is redirected to ``home/``, the page.
    GET /home/doc            -> the same document (the page fetches this, relative to itself)
    GET /home/               -> the page (static/index.html)
    GET /home/static/<file>  -> the page's CSS and JS (an allowlist: the files in static/, nothing else)

Through Clank the page is ``/api/plugins/vibetracks/home/`` on every channel (Stable, Preview, a lane), same origin
as Clank itself, so its links into Clank's track pages and review are plain ``/?vtdash=...#vt?...`` hrefs.

The workspace is ``$VIBETRACKS_WORKSPACE`` (the backend exports its ``--workspace``), else this repo's ``workspace/``.
The transcript index persists in ``$VIBETRACKS_HOME_CACHE``, else ``~/.local/share/vibetracks/home``, so a restarted
backend reads only what changed instead of 4.6 GB (~12 s cold).

GET only (the backend answers 501 for anything else on a mount). Stdlib only.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compose import build_home

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".json": "application/json"}
_LOCK = threading.Lock()


def workspace() -> Path:
    return Path(os.environ.get("VIBETRACKS_WORKSPACE") or DEFAULT_WORKSPACE)


def cache_dir() -> Path:
    return Path(os.environ.get("VIBETRACKS_HOME_CACHE") or Path.home() / ".local/share/vibetracks/home").expanduser()


def _json(status: int, payload: Any) -> tuple[int, dict[str, str], list[bytes]]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body)),
                    "Cache-Control": "no-store"}, [body]


def document() -> dict[str, Any]:
    # WHY one request at a time: the transcript index and the caches are shared; a poll every few seconds never queues.
    with _LOCK:
        doc = build_home(workspace(), cache_dir=cache_dir())
    _save_later()
    return doc


_SAVER: threading.Thread | None = None


def _save_later() -> None:
    """Persist the transcript index off the request path (at most once a minute; the index throttles itself)."""

    global _SAVER
    if _SAVER is not None and _SAVER.is_alive():
        return
    from .compose import _INDEXES  # noqa: PLC0415

    def run() -> None:
        for index in list(_INDEXES.values()):
            try:
                index.save()
            except Exception:  # noqa: BLE001 - a cache that cannot be written only costs the next cold start
                traceback.print_exc()

    _SAVER = threading.Thread(target=run, name="vibetracks-home-save", daemon=True)
    _SAVER.start()


def _wants_html(headers: Mapping[str, str]) -> bool:
    accept = next((value for key, value in (headers or {}).items() if key.lower() == "accept"), "") or ""
    return "text/html" in accept and "application/json" not in accept


def _static(name: str) -> tuple[int, dict[str, str], Iterable[bytes]]:
    allowed = {path.name: path for path in STATIC.iterdir() if path.is_file()} if STATIC.is_dir() else {}
    path = allowed.get(name)
    if path is None or path.suffix not in TYPES:
        return _json(404, {"error": f"no page file {name!r}"})
    body = path.read_bytes()
    return 200, {"Content-Type": TYPES[path.suffix], "Content-Length": str(len(body)), "Cache-Control": "no-cache"}, [body]


def handle(method: str, subpath: str, query: Mapping[str, list[str]], headers: Mapping[str, str]):
    if method != "GET":
        return _json(501, {"error": "the home is read-only"})
    if subpath == "" and _wants_html(headers):
        # WHY a relative Location: the same answer is right on the bare backend (/home -> /home/) and through Clank's
        # proxy (/api/plugins/vibetracks/home -> .../home/).
        return 302, {"Location": "home/", "Content-Length": "0"}, [b""]
    if subpath in ("", "/doc"):
        started = time.perf_counter()
        try:
            doc = document()
        except Exception as error:  # noqa: BLE001 - the page shows the reason, never a stale or made-up document
            traceback.print_exc()
            return _json(500, {"error": "the home could not be built", "detail": f"{type(error).__name__}: {error}"})
        doc["sources"]["timing_ms"]["total"] = round((time.perf_counter() - started) * 1000, 1)
        return _json(200, doc)
    if subpath in ("/", "/index.html"):
        return _static("index.html")
    if subpath.startswith("/static/"):
        return _static(subpath[len("/static/"):])
    return _json(404, {"error": f"no home route {subpath!r}"})
