"""Audit 2026-10-04 findings 3 and 9: unreadable triage is "not reported", and served files stay the files listed.

    python3 -m pytest -q tests/test_dashboard_needs_unreadable.py      (from the repo root)
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.dashboard import build as build_module
from vibetracks.dashboard import needs

from test_dashboard_needs import Fixture

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "clank" / "backend"))
import server  # noqa: E402

#: Every way a triage.json can fail to be a countable document, and the words the note must carry.
BROKEN_TRIAGE = {
    "invalid JSON": (b"{not json", "invalid JSON"),
    "not an object": (b"[1, 2]", "not an object"),
    "an empty object": (b"{}", "no items list"),
    "items not a list": (b'{"items": {"T1": {}}}', "not a list"),
    "an item not an object": (b'{"items": ["T1"]}', "items[0] is a JSON str"),
    "an item without an id": (b'{"items": [{"title": "x"}]}', "items[0] has no triage_id"),
    "not UTF-8": (b'{"items": []}\xff', "UnicodeDecodeError"),
}


class UnreadableTriageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.sources = self.fx.sources()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def assert_not_reported(self, doc: dict, reason: str) -> None:
        self.assertEqual(set(doc["counts"].values()), {None}, doc["counts"])
        self.assertEqual(doc["items"], [])
        self.assertFalse(doc["source"]["live"])
        self.assertTrue(doc["source"]["note"].startswith("not reported: triage.json could not be read: "),
                        doc["source"]["note"])
        self.assertIn(reason, doc["source"]["note"])
        self.assertEqual(needs.needs_you_count(doc), {"open": None, "blocking": None})

    def test_every_broken_document_is_null_counts_with_the_reason(self) -> None:
        for track, folder in (("kinsim", self.fx.kinsim_dir), ("rig", self.fx.rig_dir)):
            for case, (raw, reason) in BROKEN_TRIAGE.items():
                with self.subTest(track=track, case=case):
                    (folder / "triage.json").write_bytes(raw)
                    self.assert_not_reported(needs.build_track(track, self.sources), reason)

    def test_a_read_error_is_null_counts_with_the_error(self) -> None:
        for track in ("kinsim", "rig"):
            with self.subTest(track=track):
                with mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")):
                    doc = needs.build_track(track, self.sources)
                self.assert_not_reported(doc, "PermissionError")

    def test_a_valid_empty_queue_is_still_a_measured_zero(self) -> None:
        (self.fx.kinsim_dir / "triage.json").write_text('{"schema": "bam-triage/1", "items": []}', encoding="utf-8")
        doc = needs.build_track("kinsim", self.sources)
        self.assertEqual((doc["counts"]["wants_you"], doc["counts"]["blocking_now"], doc["source"]["live"]), (0, 0, True))

    def test_an_unreadable_status_file_is_said_not_hidden(self) -> None:
        (self.fx.kinsim_home / "status.json").write_text("{broken", encoding="utf-8")
        doc = needs.build_track("kinsim", self.sources)
        self.assertIn("status.json could not be read", doc["source"]["note"])
        (self.fx.rig_dir / "loop-status.json").write_text('"a string"', encoding="utf-8")
        self.assertIn("loop-status.json could not be read", needs.build_track("rig", self.sources)["source"]["note"])


class NeedsEvidenceSymlinkTest(unittest.TestCase):
    """GET /needs/evidence serves the file recorded when the entry was listed, or 403."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.allowed = root / "allowed.md"
        self.allowed.write_text("# the listed file\n", encoding="utf-8")
        self.other = root / "other.md"
        self.other.write_text("# a different file\n", encoding="utf-8")
        self.secret = root / "id_rsa"
        self.secret.write_text("PRIVATE\n", encoding="utf-8")
        self.link = root / "link.md"
        self.link.symlink_to(self.allowed)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def listed(self) -> dict:
        evidence = needs.extract_evidence(f"See `{self.link}`.", [])
        self.assertEqual([entry["path"] for entry in evidence], [str(self.link)])
        return {"items": [{"local_id": "T1", "evidence": evidence}]}

    def get(self, doc: dict) -> tuple[int, bytes]:
        with mock.patch.object(needs, "build_track", return_value=doc):
            status, _, body = needs.handle("GET", "/evidence", {"track": ["kinsim"], "item": ["T1"], "n": ["0"]}, {})
        return status, b"".join(body)

    def test_the_listed_symlink_is_served(self) -> None:
        doc = self.listed()
        self.assertEqual(doc["items"][0]["evidence"][0]["target"], os.path.realpath(self.allowed))
        self.assertEqual(self.get(doc), (200, b"# the listed file\n"))

    def test_a_symlink_retargeted_after_listing_is_403(self) -> None:
        doc = self.listed()
        self.link.unlink()
        self.link.symlink_to(self.other)
        status, body = self.get(doc)
        self.assertEqual(status, 403)
        self.assertNotIn(b"different file\n", body)

    def test_a_symlink_to_a_disallowed_suffix_is_403(self) -> None:
        self.link.unlink()
        self.link.symlink_to(self.secret)
        status, body = self.get(self.listed())
        self.assertEqual(status, 403)
        self.assertNotIn(b"PRIVATE", body)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MediaSymlinkTest(unittest.TestCase):
    """GET /media/<id> on the backend serves the canonical file recorded when the allowlist was built, or 403."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.clip = root / "clip.mp4"
        self.clip.write_bytes(b"listed video")
        self.other = root / "other.mp4"
        self.other.write_bytes(b"unlisted video")
        self.secret = root / "secret.key"
        self.secret.write_bytes(b"PRIVATE")
        self.link = root / "link.mp4"
        self.link.symlink_to(self.clip)
        self.bad = root / "bad.mp4"
        self.bad.symlink_to(self.secret)
        media = {"clip": {"id": "clip", "kind": "video", "label": "c", "path": str(self.link)},
                 "bad": {"id": "bad", "kind": "video", "label": "b", "path": str(self.bad)}}
        (self.home / "projection.json").write_text(json.dumps({"tracks": [], "media": media}), encoding="utf-8")
        self.port = free_port()
        self.httpd = server.serve(self.port, self.home)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def get(self, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_a_listed_symlink_is_served_from_its_canonical_target(self) -> None:
        self.assertEqual(self.get("/media/clip"), (200, b"listed video"))

    def test_a_symlink_retargeted_after_listing_is_403(self) -> None:
        self.assertEqual(self.get("/media/clip")[0], 200)  # listed and recorded
        self.link.unlink()
        self.link.symlink_to(self.other)
        status, body = self.get("/media/clip")
        self.assertEqual(status, 403)
        self.assertNotIn(b"unlisted", body)

    def test_a_symlink_to_a_disallowed_suffix_is_403(self) -> None:
        status, body = self.get("/media/bad")
        self.assertEqual(status, 403)
        self.assertNotIn(b"PRIVATE", body)

    def test_the_live_projection_records_targets_at_each_build(self) -> None:
        projection = server.Projection(self.home)
        projection.load()
        self.assertEqual(projection._targets["clip"], os.path.realpath(self.clip))
        self.assertEqual(projection._targets["bad"], os.path.realpath(self.secret))


if __name__ == "__main__":
    unittest.main()
