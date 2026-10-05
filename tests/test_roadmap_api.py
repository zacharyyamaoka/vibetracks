"""The roadmap's read-only routes (``vibetracks.roadmap.api.handle``), against a temporary sources file.

Each test calls ``handle`` the way ``clank/backend/server.py`` does (method, subpath, parsed query, headers), with
``VIBETRACKS_SOURCES`` pointing at a temporary ``sources.json`` that names a temporary docs and art directory.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote

from vibetracks.roadmap.api import handle

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))
SCHEMA = "bam-roadmap/1"


def link(path: str | None, base: str | None = "abs", line: int | None = None) -> dict:
    """A bam-roadmap/1 Link object: ``abs`` is set only when the file exists."""

    exists = path is not None and os.path.exists(path)
    return {"kind": "evidence", "label": None, "path": path, "base": base, "abs": path if exists else None,
            "line": line, "end_line": None, "exists": exists, "why_unresolved": None}


class RoadmapApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(os.path.realpath(temporary.name))
        self.docs = self.tmp / "docs"
        self.art = self.tmp / "docs" / "art"
        self.art.mkdir(parents=True)
        self.linked = self.tmp / "linked.txt"
        self.linked.write_text("one\ntwo\nthree\n", encoding="utf-8")
        self.unlinked = self.tmp / "unlinked.txt"
        self.unlinked.write_text("secret\n", encoding="utf-8")
        self.missing = self.tmp / "missing.log"
        self.nested = self.tmp / "nested.txt"
        self.nested.write_text("deep\n", encoding="utf-8")
        self.document = {
            "schema": SCHEMA,
            "title": "Kinsim curriculum",
            "generated_at": "2026-10-03T22:35:10+00:00",
            # a link at the top, one buried in a criteria target, one a rung's evidence item, one absent: each at a
            # place the schema declares a Link (api._links reads no other)
            "sources": [link(str(self.linked))],
            "rungs": [{"criteria": [{"targets": [link(None, None), link(str(self.nested), line=2)]}],
                       "evidence": [link(str(self.missing))]}],
        }
        self.document_bytes = (json.dumps(self.document, indent=1) + "\n").encode("utf-8")
        (self.docs / "kinsim.json").write_bytes(self.document_bytes)
        sources = self.tmp / "sources.json"
        # the live loops point nowhere, so these cases pin the stored-document fallback (tests/test_roadmap_live.py: live)
        sources.write_text(json.dumps({"roadmap_docs_dir": str(self.docs), "roadmap_art_dir": str(self.art),
                                       "kinsim_curriculum_dir": str(self.tmp / "no-kinsim"), "rig_loop_dir": str(self.tmp / "no-rig"), "grasp_bench_dir": str(self.tmp / "no-grasping"), "detection_dir": str(self.tmp / "no-detection")}),
                           encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_SOURCES": str(sources)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, subpath: str, query: str = "") -> tuple[int, dict[str, str], bytes]:
        status, headers, chunks = handle("GET", subpath, parse_qs(query), {})
        return status, headers, b"".join(chunks)

    def get_json(self, subpath: str, query: str = "") -> tuple[int, dict]:
        status, headers, body = self.get(subpath, query)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        return status, json.loads(body)


class TracksTest(RoadmapApiTestCase):
    def test_lists_only_valid_ids(self) -> None:
        (self.docs / "rig-loop_2.json").write_text(json.dumps({"schema": SCHEMA, "title": "Rig", "generated_at": "t"}),
                                                   encoding="utf-8")
        for bad in ("Upper.json", "-lead.json", "has space.json", ".hidden.json", "dots.in.name.json", "notes.txt"):
            (self.docs / bad).write_text("{}", encoding="utf-8")
        status, body = self.get_json("/tracks")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(entry["track"] for entry in body["tracks"]), ["kinsim", "rig-loop_2"])
        kinsim = next(entry for entry in body["tracks"] if entry["track"] == "kinsim")
        self.assertEqual(kinsim, {"track": "kinsim", "title": "Kinsim curriculum", "generated_at": "2026-10-03T22:35:10+00:00"})

    def test_missing_docs_dir_is_an_empty_list(self) -> None:
        sources = self.tmp / "other.json"
        sources.write_text(json.dumps({"roadmap_docs_dir": str(self.tmp / "nope"), "kinsim_curriculum_dir": str(self.tmp / "no-kinsim"), "rig_loop_dir": str(self.tmp / "no-rig"), "grasp_bench_dir": str(self.tmp / "no-grasping"), "detection_dir": str(self.tmp / "no-detection")}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"VIBETRACKS_SOURCES": str(sources)}):
            self.assertEqual(self.get_json("/tracks"), (200, {"tracks": []}))

    def test_sources_are_read_on_each_request(self) -> None:
        other = self.tmp / "other-docs"
        other.mkdir()
        (other / "rig.json").write_text(json.dumps({"schema": SCHEMA, "title": "Rig", "generated_at": "t"}), encoding="utf-8")
        sources = self.tmp / "other.json"
        sources.write_text(json.dumps({"roadmap_docs_dir": str(other), "kinsim_curriculum_dir": str(self.tmp / "no-kinsim"), "rig_loop_dir": str(self.tmp / "no-rig"), "grasp_bench_dir": str(self.tmp / "no-grasping"), "detection_dir": str(self.tmp / "no-detection")}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"VIBETRACKS_SOURCES": str(sources)}):
            _, body = self.get_json("/tracks")
        self.assertEqual([entry["track"] for entry in body["tracks"]], ["rig"])
        _, body = self.get_json("/tracks")
        self.assertEqual([entry["track"] for entry in body["tracks"]], ["kinsim"])


class DocTest(RoadmapApiTestCase):
    def test_returns_the_stored_bytes(self) -> None:
        status, headers, body = self.get("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.document_bytes)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_missing_or_bad_track_is_400(self) -> None:
        for query in ("", "track=", "track=Upper", "track=../kinsim", "track=a%2Fb", "track=-x", "track=kinsim&track=kinsim"):
            with self.subTest(query=query):
                status, body = self.get_json("/doc", query)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_absent_track_is_404(self) -> None:
        status, body = self.get_json("/doc", "track=rig")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_invalid_json_or_wrong_schema_is_500(self) -> None:
        (self.docs / "broken.json").write_text("{not json", encoding="utf-8")
        (self.docs / "binary.json").write_bytes(b"\xff\xfe\x00")
        (self.docs / "other.json").write_text(json.dumps({"schema": "bam-roadmap/2"}), encoding="utf-8")
        (self.docs / "list.json").write_text("[]", encoding="utf-8")
        for track in ("broken", "binary", "other", "list"):
            with self.subTest(track=track):
                status, body = self.get_json("/doc", f"track={track}")
                self.assertEqual(status, 500)
                self.assertIn("error", body)


class EvidenceTest(RoadmapApiTestCase):
    def evidence(self, path: Path | str, extra: str = "", track: str = "kinsim") -> tuple[int, dict]:
        return self.get_json("/evidence", f"track={track}&path={quote(str(path), safe='')}{extra}")

    def test_serves_a_linked_file(self) -> None:
        status, body = self.evidence(self.linked)
        self.assertEqual(status, 200)
        self.assertEqual(body["path"], str(self.linked))
        self.assertEqual(body["text"], "one\ntwo\nthree\n")
        self.assertEqual(body["lines"], 3)

    def test_serves_a_file_linked_deep_in_the_document(self) -> None:
        status, body = self.evidence(self.nested, "&line=2")
        self.assertEqual((status, body["text"]), (200, "deep\n"))

    def test_unlinked_existing_file_is_403(self) -> None:
        status, body = self.evidence(self.unlinked)
        self.assertEqual(status, 403)
        self.assertIn("error", body)
        self.assertNotIn("secret", json.dumps(body))

    def test_linked_but_missing_file_is_404(self) -> None:
        status, body = self.evidence(self.missing)
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_another_tracks_links_do_not_count(self) -> None:
        other = dict(self.document, sources=[link(str(self.unlinked))], rungs=[], history=[])
        (self.docs / "rig.json").write_text(json.dumps(other), encoding="utf-8")
        self.assertEqual(self.evidence(self.unlinked, track="rig")[0], 200)
        self.assertEqual(self.evidence(self.unlinked, track="kinsim")[0], 403)

    def test_path_in_a_link_with_no_abs_counts_only_for_base_abs(self) -> None:
        repo_relative = {"kind": "evidence", "label": None, "path": str(self.unlinked), "base": "repo", "abs": None,
                         "line": None, "end_line": None, "exists": False, "why_unresolved": "x"}
        (self.docs / "rig.json").write_text(json.dumps(dict(self.document, sources=[repo_relative], rungs=[], history=[])),
                                            encoding="utf-8")
        self.assertEqual(self.evidence(self.unlinked, track="rig")[0], 403)

    def test_bad_line_is_400(self) -> None:
        for extra in ("&line=0", "&line=-1", "&line=abc", "&line=1.5", "&line=%EF%BC%91", "&line=1&line=2", "&line=+1", "&line=1%20"):
            with self.subTest(extra=extra):
                status, body = self.evidence(self.linked, extra)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_missing_or_repeated_path_is_400(self) -> None:
        self.assertEqual(self.get_json("/evidence", "track=kinsim")[0], 400)
        both = f"track=kinsim&path={quote(str(self.linked), safe='')}&path={quote(str(self.nested), safe='')}"
        self.assertEqual(self.get_json("/evidence", both)[0], 400)
        self.assertEqual(self.get_json("/evidence", f"path={quote(str(self.linked), safe='')}")[0], 400)

    def test_absent_or_invalid_document_is_404_or_500(self) -> None:
        self.assertEqual(self.evidence(self.linked, track="rig")[0], 404)
        (self.docs / "broken.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.evidence(self.linked, track="broken")[0], 500)

    def test_honours_line(self) -> None:
        big = self.tmp / "big.txt"
        big.write_text("".join(f"row {number}\n" for number in range(1, 200_001)), encoding="utf-8")
        (self.docs / "rig.json").write_text(json.dumps(dict(self.document, sources=[link(str(big), line=150_000)], rungs=[], history=[])),
                                            encoding="utf-8")
        status, body = self.evidence(big, track="rig")
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])
        status, windowed = self.evidence(big, "&line=100000", track="rig")
        self.assertEqual(status, 200)
        self.assertTrue(windowed["first_line"] <= 100000)
        self.assertIn("row 100000\n", windowed["text"])
        self.assertNotEqual(windowed["first_line"], body["first_line"])


class ArtTest(RoadmapApiTestCase):
    def test_lists_and_serves(self) -> None:
        (self.art / "shot.png").write_bytes(PNG)
        (self.art / "notes.txt").write_bytes(b"x")
        status, body = self.get_json("/art")
        self.assertEqual((status, body), (200, {"entries": ["shot.png"]}))
        status, headers, data = self.get("/art/shot.png")
        self.assertEqual(status, 200)
        self.assertEqual(data, PNG)
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_bad_or_missing_name_is_404(self) -> None:
        (self.art / "shot.png").write_bytes(PNG)
        for subpath in ("/art/gone.png", "/art/Shot.PNG", "/art/", "/art/notes.txt", "/art/..%2Fkinsim.json",
                        "/art/a/shot.png", "/art/%2e%2e"):
            with self.subTest(subpath=subpath):
                status, body = self.get_json(subpath)
                self.assertEqual(status, 404)
                self.assertIn("error", body)


class RoutingTest(RoadmapApiTestCase):
    def test_unknown_subpath_is_404(self) -> None:
        for subpath in ("", "/", "/nope", "/tracks/", "/doc/x", "/evidence/x", "/artx"):
            with self.subTest(subpath=subpath):
                status, body = self.get_json(subpath)
                self.assertEqual(status, 404)
                self.assertIn("error", body)

    def test_every_response_carries_the_security_headers(self) -> None:
        (self.art / "shot.png").write_bytes(PNG)
        for subpath, query in (("/tracks", ""), ("/doc", "track=kinsim"), ("/doc", ""), ("/doc", "track=rig"),
                               ("/evidence", "track=kinsim"), ("/art", ""), ("/art/shot.png", ""), ("/art/gone.png", ""),
                               ("/nope", "")):
            with self.subTest(subpath=subpath, query=query):
                _, headers, _ = self.get(subpath, query)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("Content-Type", headers)

    def test_non_get_is_405(self) -> None:
        status, headers, _ = handle("POST", "/tracks", {}, {})
        self.assertEqual(status, 405)
        self.assertEqual(headers["Cache-Control"], "no-store")


class DispatcherTest(RoadmapApiTestCase):
    """The real clank backend resolves ``/roadmap/...`` to this handler through ``mounts.MOUNTS``, without a socket."""

    def test_roadmap_doc_through_the_backend_dispatcher(self) -> None:
        backend = Path(__file__).resolve().parents[1] / "clank" / "backend"
        if not (backend / "server.py").is_file():
            self.skipTest(f"{backend}/server.py is not in this checkout")
        sys.path.insert(0, str(backend))
        self.addCleanup(sys.path.remove, str(backend))
        import mounts  # noqa: PLC0415
        import server  # noqa: PLC0415

        found = server.find_mount("/roadmap/doc")
        self.assertIsNotNone(found, "clank/backend/mounts.py has no /roadmap entry")
        prefix, target, subpath = found
        self.assertEqual((prefix, subpath), ("/roadmap", "/doc"))
        self.assertIn(("/roadmap", "vibetracks.roadmap.api:handle"), mounts.MOUNTS)
        status, headers, chunks = server.resolve_mount(target)("GET", subpath, parse_qs("track=kinsim"), {})
        self.assertEqual((status, b"".join(chunks)), (200, self.document_bytes))
        self.assertEqual(headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
