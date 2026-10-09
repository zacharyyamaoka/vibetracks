"""The home's routes on the dashboard backend, mounted at ``/home`` (clank/backend/mounts.py; docs/peps/0001).

    GET /home                -> the ``vibetracks-home/1`` document (JSON). A browser asking for HTML (``Accept:
                                text/html`` without JSON) is redirected to ``home/``, the page.
    GET /home/doc            -> the same document (the page fetches this, relative to itself)
    GET /home/               -> the page (static/index.html)
    GET /home/static/<file>  -> the page's CSS and JS (an allowlist: the files in static/, nothing else)
    GET /home/track?id=<id>  -> vibetracks-home-track/1 (KPIs and gates, activity timeline, audits; detail.py)
    GET /home/project?id=<id> -> vibetracks-home-project/1 (north star, leading KPIs, worked per day; detail.py)
    GET /home/audit?track=<id>&name=<file> -> one audit file of that track, text/plain (only what its globs list)
    GET /home/font/<name>    -> Anthropic Sans, read from this machine's Claude Desktop extraction (see FONT_DIRS)

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

from . import detail
from .compose import LAST, build_home

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".json": "application/json"}
_LOCK = threading.Lock()
#: Where Anthropic Sans is read from, first hit wins. WHY never committed: the face is Anthropic's, extracted from
#: Claude Desktop on this machine by the claude-hub / transcript-viewer work; this page uses it locally (so its
#: sidebar reads exactly like Claude's) and falls back to system-ui where no copy exists. $VIBETRACKS_HOME_FONT_DIR
#: overrides.
FONT_DIRS = [os.environ.get("VIBETRACKS_HOME_FONT_DIR", ""), str(Path.home() / ".local/share/vibetracks/fonts"),
             "/home/bam/claude-transcript-viewer/web/public/fonts", "/home/bam/claude-hub-sidebar/app/public/fonts"]
FONTS = {"anthropic-sans.woff2": "cc27851ad-DDVos-BJ.woff2", "anthropic-sans-italic.woff2": "c9d3a3a49-CJtkx3-S.woff2"}


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


def _font(name: str) -> tuple[int, dict[str, str], Iterable[bytes]]:
    real = FONTS.get(name)
    for folder in FONT_DIRS:
        if not folder or real is None:
            continue
        for candidate in (Path(folder) / name, Path(folder) / real):
            if candidate.is_file():
                body = candidate.read_bytes()
                return 200, {"Content-Type": "font/woff2", "Content-Length": str(len(body)),
                             "Cache-Control": "max-age=86400"}, [body]
    return _json(404, {"error": f"no local copy of {name}; the page falls back to system-ui"})


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
    if subpath in ("/track", "/project"):
        key = (query.get("id") or [""])[0]
        try:
            doc = document()
            last = LAST.get(str(workspace().resolve()))
            built = (detail.build_track if subpath == "/track" else detail.build_project)(doc, last, key) if last else None
        except Exception as error:  # noqa: BLE001 - the page shows the reason
            traceback.print_exc()
            return _json(500, {"error": f"the {subpath[1:]} page could not be built", "detail": f"{type(error).__name__}: {error}"})
        if built is None:
            return _json(404, {"error": f"no {subpath[1:]} {key!r}"})
        return _json(200, built)
    if subpath == "/audit":
        served = detail.serve_audit(document(), (query.get("track") or [""])[0], (query.get("name") or [""])[0])
        return served if served else _json(404, {"error": "not an audit file of that track"})
    if subpath.startswith("/font/"):
        return _font(subpath[len("/font/"):])
    if subpath in ("/", "/index.html"):
        return _static("index.html")
    if subpath.startswith("/static/"):
        return _static(subpath[len("/static/"):])
    return _json(404, {"error": f"no home route {subpath!r}"})
