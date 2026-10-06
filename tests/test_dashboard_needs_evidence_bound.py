"""Codex audit 2026-10-05 round 3, finding 1: a Needs evidence link stays bound to the document Zach reviewed.

    python3 -m pytest -q tests/test_dashboard_needs_evidence_bound.py      (from the repo root)
    python3 -m unittest discover -s tests                                  (from the repo root)

Every evidence link on a Needs page now opens through ``/needs/evidence?track&item&eid&rev`` (clank/src/needs/
evidence.ts), never ``/media/<id>?rev=<projection rev>``. These tests hold an OLD /needs document while a NEWER
projection or a retargeted alias arrives, over HTTP through the real backend and its /needs mount, and pin that the
old document's link serves the reviewed file or answers 409 (the page's reload line), never the new file. They also
pin that the route can stand in for /media: Range answers (a video seeks) and no size cap /media does not have.
On e0bd8e5 the Range and size checks fail (200 whole file; 413 over 64 MiB); the client half is
clank/src/needs/evidence.check.mjs and tests/browser/needs_evidence_bound.mjs.
"""

from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from vibetracks.dashboard import needs

from test_dashboard_needs import Fixture, item
from test_dashboard_needs_unreadable import free_port, server

REVIEWED = b"REVIEWED clip: the bytes Zach was shown 0123456789"
NEW = b"NEW clip: a different file swapped in later"


class NeedsEvidenceBoundTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.fx = Fixture(self.root / "fx")
        self.sources = self.fx.sources()
        self.ev = self.root / "ev"
        self.ev.mkdir()
        self.reviewed = self.ev / "reviewed.mp4"
        self.reviewed.write_bytes(REVIEWED)
        self.new = self.ev / "new.mp4"
        self.new.write_bytes(NEW)
        self.still = self.ev / "still.png"
        self.still.write_bytes(b"\x89PNG still")
        self.report = self.ev / "report.html"
        self.report.write_bytes(b"<!doctype html><title>r</title>")
        # The alias both the Needs item and the projection name: the shape the audit probed (projection.media and an
        # item's evidence listing the same path).
        self.alias = self.ev / "clip.mp4"
        self.alias.symlink_to(self.reviewed)
        self.fx.write_kinsim([item("T70", after=None,
                                   question=f"Compare `{self.alias}`, `{self.still}` and `{self.report}`.")])
        self.home = self.root / "home"
        self.home.mkdir()
        self.write_projection({"clip": str(self.alias)})
        self.patch = mock.patch.object(needs, "load_sources", return_value=self.sources)
        self.patch.start()
        self.port = free_port()
        self.httpd = server.serve(self.port, self.home)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    # ----------------------------------------------------------------------------------------------------- helpers

    writes = 0

    def write_projection(self, media: dict[str, str]) -> None:
        """A new projection.json snapshot: new bytes and a strictly later mtime, so the backend reloads it."""
        self.writes += 1
        body = {"tracks": [], "media": {key: {"id": key, "kind": "video", "label": key, "path": path}
                                        for key, path in media.items()}, "write": self.writes}
        path = self.home / "projection.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        stamp = time.time() + self.writes
        os.utime(path, (stamp, stamp))

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            conn.close()

    def needs_doc(self) -> dict:
        status, _, body = self.get("/needs?track=kinsim")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def media_rev(self) -> str:
        status, _, body = self.get("/projection")
        self.assertEqual(status, 200, body)
        return json.loads(body)["media_rev"]

    @staticmethod
    def entry(doc: dict, path: Path) -> dict:
        evidence = next(it for it in doc["items"] if it["local_id"] == "T70")["evidence"]
        return next(e for e in evidence if e["path"] == str(path))

    def link(self, doc: dict, path: Path) -> str:
        """The URL clank/src/needs/evidence.ts evidenceHref() builds for this entry: eid + the DOCUMENT's revision."""
        entry = self.entry(doc, path)
        return "/needs/evidence?" + urlencode({"track": doc["track"], "item": "T70", "eid": entry["eid"],
                                               "rev": doc["evidence_rev"]})

    # ------------------------------------------------------------------------------------- the old document holds

    def test_old_document_with_a_retargeted_alias_and_a_newer_projection_is_409_never_the_new_file(self) -> None:
        old_doc = self.needs_doc()
        old_rev = self.media_rev()
        self.assertEqual(self.get(self.link(old_doc, self.alias))[2], REVIEWED)
        # The alias is retargeted and a newer projection arrives listing it.
        self.alias.unlink()
        self.alias.symlink_to(self.new)
        self.write_projection({"clip": str(self.alias)})
        new_rev = self.media_rev()
        self.assertNotEqual(new_rev, old_rev)
        # This is what e0bd8e5's Needs link opened (/media under the PROJECTION's revision): the new file.
        self.assertEqual(self.get(f"/media/clip?rev={new_rev}")[2], NEW)
        # The Needs link carries the OLD document's revision: refused with the page's reload answer, never NEW.
        for headers in (None, {"Range": "bytes=0-0"}, {"Range": "bytes=0-"}):
            status, _, body = self.get(self.link(old_doc, self.alias), headers)
            self.assertEqual(status, 409, (headers, body))
            self.assertEqual(json.loads(body)["error"], "the document changed; reload")
            self.assertNotIn(b"NEW clip", body)
        # Reload: the new document's link opens the new file, as a fresh review.
        new_doc = self.needs_doc()
        self.assertNotEqual(new_doc["evidence_rev"], old_doc["evidence_rev"])
        self.assertEqual(self.get(self.link(new_doc, self.alias))[2], NEW)

    def test_old_document_beside_a_newer_projection_still_serves_the_reviewed_file(self) -> None:
        old_doc = self.needs_doc()
        old_rev = self.media_rev()
        # A newer projection (more media, a new revision); the item's evidence and its targets did not change.
        self.write_projection({"clip": str(self.alias), "other": str(self.new)})
        self.assertNotEqual(self.media_rev(), old_rev)
        status, headers, body = self.get(self.link(old_doc, self.alias))
        self.assertEqual((status, body), (200, REVIEWED))
        self.assertEqual(headers["content-type"], "video/mp4")

    # ------------------------------------------------------------------------------ the route can stand in for /media

    def test_range_answers_like_media_so_a_video_seeks(self) -> None:
        doc = self.needs_doc()
        url = self.link(doc, self.alias)
        status, headers, body = self.get(url, {"Range": "bytes=2-9"})
        self.assertEqual(status, 206, body)
        self.assertEqual(body, REVIEWED[2:10])
        self.assertEqual(headers["content-range"], f"bytes 2-9/{len(REVIEWED)}")
        self.assertEqual(headers["content-length"], "8")
        self.assertEqual(headers["accept-ranges"], "bytes")
        status, headers, body = self.get(url, {"Range": "bytes=-5"})
        self.assertEqual((status, body), (206, REVIEWED[-5:]))
        status, headers, body = self.get(url, {"Range": "bytes=0-"})
        self.assertEqual((status, body), (206, REVIEWED))
        status, headers, _ = self.get(url, {"Range": f"bytes={len(REVIEWED)}-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["content-range"], f"bytes */{len(REVIEWED)}")
        status, headers, body = self.get(url, {"Range": "bytes=0-1,4-5"})  # multi-range: the whole file, as /media
        self.assertEqual((status, body), (200, REVIEWED))
        self.assertEqual(headers["accept-ranges"], "bytes")
        # The same answers /media gives for the same file and the same Range.
        media = self.get(f"/media/clip?rev={self.media_rev()}", {"Range": "bytes=2-9"})
        self.assertEqual((media[0], media[2], media[1]["content-range"]), (206, REVIEWED[2:10], f"bytes 2-9/{len(REVIEWED)}"))

    def test_every_media_type_opens_with_the_type_media_gives_it(self) -> None:
        doc = self.needs_doc()
        self.write_projection({"clip": str(self.alias), "still": str(self.still), "report": str(self.report)})
        rev = self.media_rev()
        for media_id, path in (("clip", self.alias), ("still", self.still), ("report", self.report)):
            needs_answer = self.get(self.link(doc, path))
            media_answer = self.get(f"/media/{media_id}?rev={rev}")
            self.assertEqual(needs_answer[0], 200, needs_answer[2])
            self.assertEqual(needs_answer[2], media_answer[2], path)
            self.assertEqual(needs_answer[1]["content-type"], media_answer[1]["content-type"], path)

    def test_a_file_larger_than_the_old_64_mib_cap_is_served_as_media_serves_it(self) -> None:
        big = self.ev / "long-run.mp4"
        with big.open("wb") as handle:  # sparse: 65 MiB on paper, nothing on disk
            handle.truncate(65 * 1024 * 1024)
        self.fx.write_kinsim([item("T70", after=None, question=f"Watch `{big}`.")])
        doc = self.needs_doc()
        status, headers, body = self.get(self.link(doc, big), {"Range": "bytes=0-0"})
        self.assertEqual(status, 206, body)
        self.assertEqual(body, b"\x00")
        self.assertEqual(headers["content-range"], f"bytes 0-0/{65 * 1024 * 1024}")


if __name__ == "__main__":
    unittest.main()
