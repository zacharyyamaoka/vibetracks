"""Extra read-only routes the dashboard backend serves, one per prefix: an append-only list.

Each entry is ``(prefix, "package.module:callable")``. A GET whose path is the prefix, or starts with the prefix
plus ``/``, goes to that callable, imported lazily on the first such request:

    handle(method: str, subpath: str, query: dict[str, list[str]], headers: Mapping[str, str])
        -> tuple[int, dict[str, str], Iterable[bytes]]

- ``method`` is ``"GET"`` (any other method on a mount is answered 501 before the handler is reached).
- ``subpath`` is the path after the prefix, ``""`` or starting with ``/`` (``/roadmap/doc`` -> ``/doc``), still
  percent-encoded.
- ``query`` is ``urllib.parse.parse_qs`` of the query string.
- The answer is ``(status, headers, body chunks)``. Set ``Content-Type``; set ``Content-Length`` to stream the chunks,
  otherwise the server joins them and sets it. ``close()`` on the iterable is called when it has one.

If the import fails the route answers 503 with a JSON ``error`` and the rest of the server keeps working; the import
is retried on the next request, so fixing the module needs no restart. A handler that raises answers 500.

WHY a list of import strings and not a plugin registry: the roadmap session (and any later one) adds a route by
appending one line here, without touching server.py, and a broken or missing module costs only its own route.
The module must be importable from the repo root (Clank runs the backend with ``PYTHONPATH={pluginDir}/..``).
"""

from __future__ import annotations

MOUNTS: list[tuple[str, str]] = [
    ("/roadmap", "vibetracks.roadmap.api:handle"),
    ('/needs', 'vibetracks.dashboard.needs:handle'),
    # WHY a page beside Clank and not inside it: docs/peps/0001-home-surface-and-derived-state.md
    ('/home', 'vibetracks.home.api:handle'),
]
