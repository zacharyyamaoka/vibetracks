"""Every media id a projection can emit is servable: it matches the backend's MEDIA_ID and answers 200/206 under its rev.

    python3 -m pytest -q tests/test_dashboard_media_served.py      (from the repo root)

WHY (verifier, 2026-10-05, leftover (d)): the grasping adapter names media ``grasping:gallery-preview`` while the
backend's MEDIA_ID forbade ":", so the item always read "Could not load: HTTP 404" beside a dead "Open in new tab"
link. The adapter tests checked the projection and the backend tests checked hand-written ids, and neither checked one
against the other. These tests walk what the adapters actually emit, through the real HTTP handler, with the URL
spelled exactly as the page spells it (``shared/api.ts`` ``mediaUrl``: ``encodeURIComponent`` of the id and the rev).
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from vibetracks.dashboard.adapters import grasping

# WHY the module and not its names: a TestCase class imported by name would be collected and run again here.
import test_dashboard_adapter_grasping as grasping_fixture

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"


def _load_backend_server():
    """clank/backend/server.py by file location under a private name (as tests/test_dashboard_needs_unreadable.py):
    a ``sys.path.insert`` would let ``unittest discover -s tests`` collide with clank/backend/test_server.py."""
    spec = importlib.util.spec_from_file_location("vibetracks_dashboard_backend_server_media_test",
                                                  REPO / "clank" / "backend" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_backend_server()


def encode_uri_component(text: str) -> str:
    """JavaScript's ``encodeURIComponent``: everything but ``A-Z a-z 0-9 - _ . ! ~ * ' ( )`` is percent-encoded."""
    return quote(text, safe="-_.!~*'()")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Served:
    """A backend on a free loopback port, plus the GETs the page makes."""

    def __init__(self, home: Path, workspace: Path | None = None) -> None:
        self.port = free_port()
        self.httpd = server.serve(self.port, home, workspace=workspace)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def projection(self) -> dict:
        status, body = self.get("/projection")
        if status != 200:
            raise AssertionError(f"/projection answered {status}: {body[:400]!r}")
        return json.loads(body)

    def assert_every_media_id_serves(self, test: unittest.TestCase, projection: dict) -> int:
        """Each ``media`` id matches MEDIA_ID and answers 200 or 206 (one byte asked for) under the projection's rev;
        returns how many were checked."""
        revision = projection["media_rev"]
        media = projection.get("media") or {}
        for media_id, entry in media.items():
            with test.subTest(media_id=media_id):
                test.assertRegex(media_id, server.MEDIA_ID, "the backend would refuse this id as a bad spelling")
                test.assertEqual(entry.get("id"), media_id)
                url = f"/media/{encode_uri_component(media_id)}?rev={encode_uri_component(revision)}"
                # WHY a one-byte Range: the live allowlist holds GiBs of video; the status is the point here.
                status, body = self.get(url, {"Range": "bytes=0-0"})
                test.assertIn(status, (200, 206), f"{url} answered {status}: {body[:300]!r}")
        # Every evidence reference and media link names an id that is listed (and so served, above).
        for track in projection.get("tracks", []):
            refs = [link.get("media") for link in track.get("links", []) if link.get("kind") == "media"]
            for items in track.get("evidence", {}).get("by_iteration", {}).values():
                for item in items:
                    refs += [m.get("id") for m in item.get("media", [])]
                    refs += [link.get("media") for link in item.get("links", []) if link.get("kind") == "media"]
            for ref in refs:
                with test.subTest(track=track.get("id"), ref=ref):
                    test.assertIn(ref, media, "a reference to a media id the allowlist does not list")
        return len(media)


class GraspingGalleryIsServedTest(unittest.TestCase):
    """Hermetic: the grasping adapter's three gallery ids, through a snapshot-mode backend."""

    def setUp(self) -> None:
        self.fixture = grasping_fixture.FixtureTest("test_media_only_for_files_that_exist")
        self.fixture.setUp()
        out = self.fixture.out
        (out / "gallery.html").write_text("<!doctype html><title>gallery</title>", encoding="utf-8")
        (out / "gallery-preview.html").write_text("<!doctype html><title>preview</title>", encoding="utf-8")
        (out / "gallery-preview.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
        self.home_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.home_dir.name)

    def tearDown(self) -> None:
        self.home_dir.cleanup()
        self.fixture.tearDown()

    def test_every_gallery_id_is_served_under_its_rev(self) -> None:
        track = grasping.build_track(grasping_fixture.work_track(), self.fixture.sources,
                                     bridge=grasping_fixture.FakeBridge(self.fixture))
        self.assertEqual(sorted(track["media"]),
                         ["grasping:gallery", "grasping:gallery-preview", "grasping:gallery-preview-png"])
        projection = {"schema": "vibetracks-dashboard/1", "tracks": [track], "media": track["media"]}
        (self.home / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
        backend = _Served(self.home)
        try:
            self.assertEqual(backend.assert_every_media_id_serves(self, backend.projection()), 3)
            # The bytes are the listed file's, not just a status.
            answered = backend.projection()
            status, body = backend.get(f"/media/{encode_uri_component('grasping:gallery-preview-png')}"
                                       f"?rev={answered['media_rev']}")
            self.assertEqual((status, body), (200, (self.fixture.out / "gallery-preview.png").read_bytes()))
        finally:
            backend.close()

    def test_a_colon_never_opens_a_path_or_a_query(self) -> None:
        # Allowing ":" must not widen the spelling to anything that reads as a path, a query or an escape.
        for bad in ("a/b", "a%3Ab", "a?b", "a#b", "a b", ".hidden", ":lead", "a\\b", "a\nb", ""):
            with self.subTest(bad=bad):
                self.assertIsNone(server.MEDIA_ID.match(bad))
        self.assertIsNotNone(server.MEDIA_ID.match("grasping:gallery-preview-png"))


class LiveProjectionMediaIsServedTest(unittest.TestCase):
    """The checked-in registry with the real adapters, served live: every media id it emits on this machine serves.

    A loop whose files are not on this machine lists no media, so the walk is meaningful wherever the files exist and
    vacuous (never red) where they do not.
    """

    def test_every_live_media_id_matches_and_serves_under_its_rev(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            backend = _Served(Path(home), WORKSPACE)
            try:
                projection = backend.projection()
                self.assertTrue(projection["source"]["live"])
                checked = backend.assert_every_media_id_serves(self, projection)
            finally:
                backend.close()
        if checked == 0:
            self.skipTest("no loop on this machine lists media")


if __name__ == "__main__":
    unittest.main()
