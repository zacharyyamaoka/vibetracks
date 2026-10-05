"""Audit 2026-10-04 findings 3 and 9, and 2026-10-05 findings 1, 2 and 5: unreadable triage is "not reported", and
served files stay the files Zach reviewed.

    python3 -m pytest -q tests/test_dashboard_needs_unreadable.py      (from the repo root)
    python3 -m unittest discover -s tests                               (from the repo root)
"""

from __future__ import annotations

import errno
import http.client
import importlib.util
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from vibetracks.dashboard import build as build_module
from vibetracks.dashboard import needs
from vibetracks.safe_open import UnsafePath, open_no_symlinks

from test_dashboard_needs import Fixture

REPO = Path(__file__).resolve().parents[1]


def _load_backend_server():
    """clank/backend/server.py by file location under a private name. WHY not ``sys.path.insert`` + ``import server``:
    that put clank/backend on the path at import time, so ``unittest discover -s tests`` then found
    clank/backend/test_server.py for ``test_server`` and died ("module incorrectly imported")."""
    spec = importlib.util.spec_from_file_location("vibetracks_dashboard_backend_server_under_test",
                                                  REPO / "clank" / "backend" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_backend_server()

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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _ParentSwap:
    """Swap ``directory`` for a symlink to ``elsewhere`` at the first ``os.open`` after the check has run.

    WHY this hook and not a real race: the check (a document rebuild, or media_lookup's realpath) and the open are two
    steps; arming on the check's return and swapping on the very next ``os.open`` lands the substitution exactly
    between them, whatever the open is (one ``os.open`` of the full path, or a component walk starting at ``/``).
    """

    def __init__(self, directory: Path, elsewhere: Path) -> None:
        self.directory, self.elsewhere = directory, elsewhere
        self.armed = False
        self.swapped = False
        self.real_open = os.open

    def arm(self, result):
        self.armed = True
        return result

    def open(self, *args, **kwargs):
        if self.armed and not self.swapped:
            self.swapped = True
            os.rename(self.directory, self.directory.with_name(self.directory.name + ".moved"))
            os.symlink(self.elsewhere, self.directory)
        return self.real_open(*args, **kwargs)


class EvidenceRouteTest(unittest.TestCase):
    """The whole sequence a click makes: GET /needs?track=kinsim, then that document's evidence URL, over HTTP through
    the backend and its /needs mount (audit 2026-10-05 findings 1 and 5: the old tests handed ``serve_evidence`` a
    prebuilt entry and never saw the route re-authorize a substituted target)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.fx = Fixture(self.root / "fx")
        self.sources = self.fx.sources()
        ev = self.root / "ev"
        (ev / "dir").mkdir(parents=True)
        (ev / "elsewhere").mkdir()
        self.listed = ev / "dir" / "listed.md"
        self.listed.write_text("# the listed file\n", encoding="utf-8")
        (ev / "elsewhere" / "listed.md").write_text("# SUBSTITUTED\n", encoding="utf-8")
        self.other = ev / "other.md"
        self.other.write_text("# a different file\n", encoding="utf-8")
        self.second = ev / "second.md"
        self.second.write_text("# the second entry\n", encoding="utf-8")
        self.link = ev / "link.md"
        self.link.symlink_to(self.listed)
        self.ev = ev
        self.write_item(f"See `{self.link}` and `{self.second}`.")
        home = self.root / "home"
        home.mkdir()
        (home / "projection.json").write_text(json.dumps({"tracks": [], "media": {}}), encoding="utf-8")
        self.patch = mock.patch.object(needs, "load_sources", return_value=self.sources)
        self.patch.start()
        self.port = free_port()
        self.httpd = server.serve(self.port, home)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def write_item(self, question: str) -> None:
        from test_dashboard_needs import item
        self.fx.write_kinsim([item("T70", after=None, question=question)])

    def get(self, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def document(self) -> dict:
        status, body = self.get("/needs?track=kinsim")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def entries(self, doc: dict) -> list[dict]:
        return next(item for item in doc["items"] if item["local_id"] == "T70")["evidence"]

    def url(self, doc: dict, entry: dict) -> str:
        """The URL clank/src/needs/api.ts evidenceUrl() builds: track, item, eid and rev, never a list index."""
        return "/needs/evidence?" + urlencode({"track": doc["track"], "item": "T70", "eid": entry["eid"],
                                               "rev": doc["evidence_rev"]})

    def test_a_reviewed_link_opens(self) -> None:
        doc = self.document()
        first, second = self.entries(doc)
        self.assertEqual(first["target"], str(self.listed))
        self.assertEqual(self.get(self.url(doc, first)), (200, b"# the listed file\n"))
        self.assertEqual(self.get(self.url(doc, second)), (200, b"# the second entry\n"))

    def test_a_symlink_retargeted_after_the_document_was_read_is_409_until_reload(self) -> None:
        doc = self.document()
        first = self.entries(doc)[0]
        self.assertEqual(self.get(self.url(doc, first))[0], 200)
        self.link.unlink()
        self.link.symlink_to(self.other)
        status, body = self.get(self.url(doc, first))
        self.assertEqual(status, 409, body)
        self.assertEqual(json.loads(body)["error"], "the document changed; reload")
        self.assertNotIn(b"different file", body)
        reloaded = self.document()
        self.assertNotEqual(reloaded["evidence_rev"], doc["evidence_rev"])
        again = self.entries(reloaded)[0]
        self.assertEqual(again["eid"], first["eid"], "the same written evidence keeps its id")
        self.assertEqual(self.get(self.url(reloaded, again)), (200, b"# a different file\n"))

    def test_reordered_evidence_is_409_and_ids_follow_the_entry_not_the_index(self) -> None:
        doc = self.document()
        first, second = self.entries(doc)
        self.write_item(f"See `{self.second}` and `{self.link}`.")
        self.assertEqual(self.get(self.url(doc, first))[0], 409)
        self.assertEqual(self.get(self.url(doc, second))[0], 409)
        reordered = self.entries(self.document())
        self.assertEqual([entry["eid"] for entry in reordered], [second["eid"], first["eid"]])

    def test_an_unknown_eid_or_a_missing_parameter_is_refused(self) -> None:
        doc = self.document()
        first = self.entries(doc)[0]
        self.assertEqual(self.get(self.url(doc, {**first, "eid": "0" * 16}))[0], 404)
        query = {"track": "kinsim", "item": "T70", "n": "0"}  # the old index-only URL
        self.assertEqual(self.get("/needs/evidence?" + urlencode(query))[0], 400)

    def test_a_parent_directory_swapped_for_a_symlink_between_check_and_open_is_refused(self) -> None:
        self.write_item(f"See `{self.listed}`.")
        doc = self.document()
        entry = self.entries(doc)[0]
        swap = _ParentSwap(self.ev / "dir", self.ev / "elsewhere")
        real_build = needs.build_track
        with mock.patch.object(needs, "build_track", side_effect=lambda *a, **k: swap.arm(real_build(*a, **k))), \
                mock.patch("os.open", side_effect=swap.open):
            status, body = self.get(self.url(doc, entry))
        self.assertTrue(swap.swapped, "the hook must have swapped the parent between the check and the open")
        self.assertEqual(status, 403, body)
        self.assertNotIn(b"SUBSTITUTED", body)


class SafeOpenTest(unittest.TestCase):
    """vibetracks.safe_open.open_no_symlinks: a symlink at ANY component is refused, not only the last."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        (self.root / "real").mkdir()
        self.file = self.root / "real" / "file.md"
        self.file.write_bytes(b"content")
        (self.root / "via").symlink_to(self.root / "real")
        (self.root / "real" / "alias.md").symlink_to(self.file)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def read(self, path: str) -> bytes:
        fd = open_no_symlinks(path)
        with os.fdopen(fd, "rb") as handle:
            return handle.read()

    def test_a_canonical_path_opens(self) -> None:
        self.assertEqual(self.read(str(self.file)), b"content")

    def test_a_symlinked_parent_is_refused(self) -> None:
        with self.assertRaises(UnsafePath) as caught:
            open_no_symlinks(str(self.root / "via" / "file.md"))
        self.assertIn(caught.exception.errno, (errno.ELOOP, errno.ENOTDIR))

    def test_a_symlinked_last_component_is_refused(self) -> None:
        with self.assertRaises(UnsafePath):
            open_no_symlinks(str(self.root / "real" / "alias.md"))

    def test_proc_self_root_is_refused(self) -> None:
        with self.assertRaises(UnsafePath):
            open_no_symlinks("/proc/self/root" + str(self.file))

    def test_non_canonical_and_non_regular_paths_are_refused(self) -> None:
        real = f"{self.root}/real"  # spelled as strings: pathlib would quietly drop the "." being tested
        for path in ("relative/file.md", f"{real}/./file.md", f"{real}/../real/file.md", f"{real}//file.md",
                     f"{self.file}/", real):
            with self.subTest(path=path), self.assertRaises(UnsafePath):
                open_no_symlinks(path)
        fifo = self.root / "real" / "pipe.md"
        os.mkfifo(fifo)
        with self.assertRaises(UnsafePath):  # refused at once: never blocks waiting for a writer
            open_no_symlinks(str(fifo))

    def test_a_missing_file_is_the_plain_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            open_no_symlinks(str(self.root / "real" / "gone.md"))


class MediaSymlinkTest(unittest.TestCase):
    """GET /media/<id> on the backend serves the canonical file recorded when the allowlist was built, or 403."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(os.path.realpath(self.tmp.name))
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

    def test_a_parent_directory_swapped_for_a_symlink_between_check_and_open_is_refused(self) -> None:
        (self.root / "dir").mkdir()
        (self.root / "elsewhere").mkdir()
        (self.root / "dir" / "clip.mp4").write_bytes(b"listed video")
        (self.root / "elsewhere" / "clip.mp4").write_bytes(b"SUBSTITUTED video")
        media = {"clip": {"id": "clip", "kind": "video", "label": "c", "path": str(self.root / "dir" / "clip.mp4")}}
        (self.home / "projection.json").write_text(json.dumps({"tracks": [], "media": media}), encoding="utf-8")
        self.assertEqual(self.get("/media/clip"), (200, b"listed video"))
        swap = _ParentSwap(self.root / "dir", self.root / "elsewhere")
        real_lookup = server.Projection.media_lookup
        with mock.patch.object(server.Projection, "media_lookup",
                               lambda projection, media_id: swap.arm(real_lookup(projection, media_id))), \
                mock.patch("os.open", side_effect=swap.open):
            status, body = self.get("/media/clip")
        self.assertTrue(swap.swapped, "the hook must have swapped the parent between the check and the open")
        self.assertEqual(status, 403, body)
        self.assertNotIn(b"SUBSTITUTED", body)

    def test_the_live_projection_records_targets_at_each_build(self) -> None:
        projection = server.Projection(self.home)
        projection.load()
        self.assertEqual(projection._targets["clip"], os.path.realpath(self.clip))
        self.assertEqual(projection._targets["bad"], os.path.realpath(self.secret))


if __name__ == "__main__":
    unittest.main()
