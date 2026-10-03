"""The roadmap's read-only routes, mounted at ``/roadmap`` by ``clank/backend/mounts.py``.

    GET /tracks                                   -> {"tracks": [{track, title, generated_at}]}
    GET /doc?track=<id>                           -> the track's bam-roadmap/1 document, as stored
    GET /evidence?track=<id>&path=<abs>[&line=N]  -> a file the document links to (``files.read_evidence``)
    GET /art, GET /art/<name>                     -> the art PNG names, one PNG's bytes

``handle`` is the backend's mount contract: ``(method, subpath, query, headers) -> (status, headers, chunks)``. Sources
are read on every request (``load_sources``), so a changed ``sources.json`` needs no restart.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from urllib.parse import unquote

from ..sources import load_sources
from .files import RoadmapForbidden, RoadmapNotFound, art_entries, read_art, read_evidence

SCHEMA = "bam-roadmap/1"
_TRACK_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
#: ASCII digits only: ``int()`` and ``\d`` would also take Unicode digits, signs and surrounding space.
_LINE = re.compile(r"[0-9]+")

Response = tuple[int, dict[str, str], list[bytes]]


class _BadRequest(Exception):
    """A malformed query; the message is the 400 body's ``error``."""


class _InvalidDocument(Exception):
    """A document file that is not valid JSON or not ``bam-roadmap/1``; the message is the 500 body's ``error``."""


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


def _links(node: object) -> Iterator[dict]:
    """Every Link-shaped object anywhere in a document: one with a ``path`` and an ``abs`` (or ``base: "abs"``).

    WHY a generic walk and not a list of the sections that hold links: a section the format adds later cannot then fall
    silently outside the allowlist; and only a link the document carries is ever served.
    """

    if isinstance(node, dict):
        if "path" in node and ("abs" in node or node.get("base") == "abs"):
            yield node
        for value in node.values():
            yield from _links(value)
    elif isinstance(node, list):
        for value in node:
            yield from _links(value)


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
    docs_dir = Path(load_sources()["roadmap_docs_dir"])
    try:
        names = sorted(os.listdir(docs_dir))
    except (FileNotFoundError, NotADirectoryError):
        names = []
    tracks = []
    for name in names:
        track = name.removesuffix(".json")
        if track == name or not _TRACK_ID.fullmatch(track):
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
        tracks.append({"track": track, "title": title, "generated_at": generated_at})
    return _json(200, {"tracks": tracks})


def _doc(query: Mapping[str, list[str]]) -> Response:
    track = _track_id(query)
    found = _read_document(track)
    if found is None:
        return _error(404, f"no roadmap document for track {track!r}")
    # WHY the stored bytes, not a re-dump: for now the documents are projections written by the format's projector
    # (bam_ws src/dev/bam_roadmap, ``python -m bam_roadmap project``). Live projection comes when that package moves
    # into vibetracks/roadmap/; /doc keeps its shape.
    return _bytes(200, "application/json; charset=utf-8", found[0])


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
    found = _read_document(track)
    if found is None:
        return _error(404, f"no roadmap document for track {track!r}")
    try:
        return _json(200, read_evidence(path, _allowlist(found[1]), line))
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
    except _InvalidDocument as error:
        return _error(500, str(error))
