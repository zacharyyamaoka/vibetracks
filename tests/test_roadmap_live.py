"""Live ``/roadmap/doc``: the roadmap projected from the loop's current files, cached under a stamp of its inputs.

The kinsim loop here is the projector tests' own fixture (``vibetracks/roadmap/projector/tests/conftest.py``,
``kinsim_loop``): a throwaway git repository with a tiny kinsim-shaped curriculum and data home. ``VIBETRACKS_SOURCES``
points the routes at it. The last class projects the real loops on this machine and skips where they are absent.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote

from vibetracks.roadmap import api
from vibetracks.roadmap.api import handle
from vibetracks.roadmap.projector import ProjectionError, project_kinsim
from vibetracks.sources import load_sources

try:
    from vibetracks.roadmap.projector.tests import conftest as fixtures
except ImportError:  # the fixtures are pytest's; without pytest the fixture-backed cases skip
    fixtures = None

SCHEMA = "bam-roadmap/1"


def fixture_body(fixture):
    """The plain function behind a pytest fixture: pytest refuses a direct call to the decorated one."""

    wrapped = getattr(fixture, "__pytest_wrapped__", None)
    if wrapped is not None:
        return wrapped.obj
    return getattr(fixture, "__wrapped__", fixture)


def clear_caches() -> None:
    with api._CACHES_LOCK:
        api._CACHES.clear()


def get(subpath: str, query: str = "") -> tuple[int, bytes]:
    status, _headers, chunks = handle("GET", subpath, parse_qs(query), {})
    return status, b"".join(chunks)


def get_json(subpath: str, query: str = "") -> tuple[int, dict]:
    status, body = get(subpath, query)
    return status, json.loads(body)


def touch(path: Path) -> None:
    """A new mtime, same bytes: what the stamp must notice."""

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


@unittest.skipIf(fixtures is None, "pytest is not importable, so the projector's kinsim fixture is not")
class LiveDocTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(os.path.realpath(temporary.name))
        (self.tmp / "loop").mkdir()
        self.loop = fixture_body(fixtures.kinsim_loop)(self.tmp / "loop")
        for directory, _dirs, files in os.walk(self.tmp / "loop"):  # a loop at rest: nothing written mid-projection
            for name in files:
                path = os.path.join(directory, name)
                if not os.path.islink(path):
                    stat = os.stat(path)
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns - 30_000_000_000))
        self.docs = self.tmp / "docs"
        self.docs.mkdir()
        sources = self.tmp / "sources.json"
        sources.write_text(json.dumps({
            "kinsim_curriculum_dir": str(self.loop.curriculum_dir), "kinsim_home": str(self.loop.data_home),
            "rig_loop_dir": str(self.tmp / "no-rig-loop"), "roadmap_docs_dir": str(self.docs),
            "grasp_bench_dir": str(self.tmp / "no-grasping"), "detection_dir": str(self.tmp / "no-detection"),
            "roadmap_art_dir": str(self.docs / "art")}), encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_SOURCES": str(sources)})
        patcher.start()
        self.addCleanup(patcher.stop)
        clear_caches()
        self.addCleanup(clear_caches)

    def counting(self, **kwargs) -> mock.MagicMock:
        """``project_kinsim`` as the routes call it, counted (and wrapped unless ``side_effect`` replaces it)."""

        kwargs.setdefault("wraps", project_kinsim)
        patcher = mock.patch("vibetracks.roadmap.api.project_kinsim", **kwargs)
        counted = patcher.start()
        self.addCleanup(patcher.stop)
        return counted

    def store(self, track: str, document: dict) -> None:
        (self.docs / f"{track}.json").write_text(json.dumps(document), encoding="utf-8")


class ProjectedLiveTest(LiveDocTestCase):
    def test_doc_is_projected_from_the_loops_files(self) -> None:
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertEqual((document["schema"], document["loop"]), (SCHEMA, "kinsim"))
        self.assertEqual([rung["id"] for rung in document["rungs"]], ["EV9", "RB9", "OB9", "MR9"])
        self.assertEqual(document["as_of"]["head"], fixtures.git(self.loop.repo, "rev-parse", "HEAD"))
        self.assertFalse([warning for warning in document["warnings"] if warning.startswith("stale")])

    def test_a_stored_document_does_not_shadow_the_live_one(self) -> None:
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "2026-01-01T00:00:00+00:00", "rungs": []})
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertEqual(document["title"], "Kinsim curriculum")
        self.assertEqual(len(document["rungs"]), 4)


class StampCacheTest(LiveDocTestCase):
    def test_an_unchanged_loop_is_not_projected_again(self) -> None:
        counted = self.counting()
        first = get("/doc", "track=kinsim")
        second = get("/doc", "track=kinsim")
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(first[1], second[1])
        self.assertEqual(counted.call_count, 1)

    def test_touching_the_event_log_projects_again(self) -> None:
        counted = self.counting()
        get("/doc", "track=kinsim")
        touch(self.loop.data_home / "loop_events.jsonl")
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)

    def test_every_stamped_input_and_a_new_head_project_again(self) -> None:
        counted = self.counting()
        get("/doc", "track=kinsim")
        expected = 1
        for path in (self.loop.data_home / "status.json", self.loop.data_home / "runs.jsonl",
                     self.loop.curriculum_dir / "curriculum.json"):
            with self.subTest(path=path.name):
                touch(path)
                get("/doc", "track=kinsim")
                expected += 1
                self.assertEqual(counted.call_count, expected)
        fixtures.write(self.loop.repo / "src/pkg/widget.py", "WIDGET = 1\nSPIN = 3\n")
        head = fixtures.commit_all(self.loop.repo, "the widget changed")
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count, document["as_of"]["head"]), (200, expected + 1, head))

    def test_refresh_projects_again(self) -> None:
        counted = self.counting()
        get("/doc", "track=kinsim")
        self.assertEqual(get("/doc", "track=kinsim&refresh=1")[0], 200)
        self.assertEqual(counted.call_count, 2)
        get("/doc", "track=kinsim&refresh=0")
        self.assertEqual(counted.call_count, 2)

    def test_a_bad_refresh_is_400(self) -> None:
        for query in ("track=kinsim&refresh=yes", "track=kinsim&refresh=1&refresh=1"):
            with self.subTest(query=query):
                self.assertEqual(get_json("/doc", query)[0], 400)

    def test_concurrent_requests_wait_for_one_projection(self) -> None:
        def slow(*args, **kwargs):
            time.sleep(0.3)
            return project_kinsim(*args, **kwargs)

        counted = self.counting(side_effect=slow, wraps=None)
        results: list[int] = []
        threads = [threading.Thread(target=lambda: results.append(get("/doc", "track=kinsim")[0])) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(results, [200] * 4)
        self.assertEqual(counted.call_count, 1)


class FailedProjectionTest(LiveDocTestCase):
    def test_a_failure_serves_the_last_good_document_with_a_warning(self) -> None:
        status, good = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        counted = self.counting(side_effect=ProjectionError("cannot read status.json: boom"), wraps=None)
        touch(self.loop.data_home / "loop_events.jsonl")
        status, stale = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertTrue(stale["warnings"][0].startswith("stale: projecting the kinsim loop live failed"), stale["warnings"])
        self.assertIn("boom", stale["warnings"][0])
        self.assertEqual(stale["generated_at"], good["generated_at"])
        self.assertEqual(stale["rungs"], good["rungs"])
        self.assertEqual(stale["warnings"][1:], good["warnings"])
        get("/doc", "track=kinsim")  # the same stamp failed already: not projected again
        self.assertEqual(counted.call_count, 1)

    def test_a_failure_with_no_good_document_is_503(self) -> None:
        self.counting(side_effect=RuntimeError("boom"), wraps=None)
        status, body = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 503)
        self.assertIn("boom", body["error"])
        self.assertEqual(get_json("/evidence", f"track=kinsim&path={quote('/etc/hostname', safe='')}")[0], 503)

    def test_a_failure_falls_back_to_the_stored_document(self) -> None:
        self.counting(side_effect=RuntimeError("boom"), wraps=None)
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "2026-01-01T00:00:00+00:00",
                              "loop": "kinsim", "roots": {"repo": str(self.loop.repo), "data_home": str(self.loop.data_home)},
                              "sources": [{"kind": "file", "path": str(self.loop.curriculum_dir / "curriculum.json"),
                                           "base": "abs", "abs": None}],
                              "warnings": ["its own"]})
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"]), (200, "Stored"))
        self.assertTrue(document["warnings"][0].startswith("stale:"), document["warnings"])
        self.assertIn("stored document", document["warnings"][0])
        self.assertEqual(document["warnings"][1:], ["its own"])

    def test_a_projection_that_fails_its_validator_is_a_failure(self) -> None:
        with mock.patch("vibetracks.roadmap.api.validate_document", return_value=["rung EV9: made up"]):
            status, body = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 503)
        self.assertIn("the projection is invalid", body["error"])


class UnknownTrackTest(LiveDocTestCase):
    def test_an_unknown_track_is_404(self) -> None:
        self.assertEqual(get_json("/doc", "track=nobody"), (404, {"error": "no roadmap reported yet"}))

    def test_a_builtin_track_whose_loop_is_absent_is_404_or_its_stored_document(self) -> None:
        self.assertEqual(get_json("/doc", "track=rig"), (404, {"error": "no roadmap reported yet"}))
        stored = {"schema": SCHEMA, "title": "Rig loop", "generated_at": "2026-10-03T19:00:00+00:00", "loop": "rig",
                  "roots": {"repo": str(self.tmp / "no-rig-loop")},
                  "sources": [{"kind": "file", "path": str(self.tmp / "no-rig-loop" / "ladder.json"), "base": "abs",
                               "abs": None}]}
        self.store("rig", stored)
        status, document = get_json("/doc", "track=rig")
        self.assertEqual((status, {**document, "warnings": []}), (200, {**stored, "warnings": []}))
        self.assertTrue(document["warnings"][0].startswith("stale: the rig loop is not on this machine"))


class EvidenceLiveTest(LiveDocTestCase):
    def test_the_allowlist_is_the_live_documents(self) -> None:
        counted = self.counting()
        secret = self.tmp / "secret.txt"
        secret.write_text("secret\n", encoding="utf-8")
        link = {"kind": "file", "label": None, "path": str(secret), "base": "abs", "abs": str(secret), "line": None,
                "end_line": None, "exists": True, "why_unresolved": None}
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "t", "sources": [link]})
        acceptance = self.loop.repo / fixtures.ACCEPTANCE
        self.assertIn(str(acceptance), get("/doc", "track=kinsim")[1].decode("utf-8"))
        status, body = get_json("/evidence", f"track=kinsim&path={quote(str(acceptance), safe='')}")
        self.assertEqual(status, 200)
        self.assertEqual(body["text"], fixtures.TEST_FILE)
        self.assertEqual(get_json("/evidence", f"track=kinsim&path={quote(str(secret), safe='')}")[0], 403)
        self.assertEqual(counted.call_count, 1)  # /evidence read the cached projection


class TracksLiveTest(LiveDocTestCase):
    def test_lists_live_tracks_and_stored_documents(self) -> None:
        self.store("other", {"schema": SCHEMA, "title": "Other", "generated_at": "t"})
        status, body = get_json("/tracks")
        self.assertEqual(status, 200)
        self.assertEqual(body["tracks"], [{"track": "kinsim", "title": "Kinsim curriculum", "generated_at": None},
                                          {"track": "other", "title": "Other", "generated_at": "t"}])
        _, document = get_json("/doc", "track=kinsim")
        _, body = get_json("/tracks")
        self.assertEqual(body["tracks"][0]["generated_at"], document["generated_at"])


class RealLoopsSmokeTest(unittest.TestCase):
    """The real loops on this machine, read through the default sources map; skipped where they are absent."""

    def setUp(self) -> None:
        clear_caches()
        self.addCleanup(clear_caches)

    def check(self, track: str, present: Path) -> None:
        if not present.is_file():
            self.skipTest(f"the {track} loop is not on this machine ({present})")
        before = datetime.now(timezone.utc).replace(microsecond=0)
        started = time.monotonic()
        status, body = get("/doc", f"track={track}")
        elapsed = time.monotonic() - started
        self.assertEqual(status, 200, body[:500])
        document = json.loads(body)
        self.assertEqual((document["schema"], document["loop"]), (SCHEMA, track))
        generated = datetime.fromisoformat(document["generated_at"])
        self.assertTrue(before <= generated <= datetime.now(timezone.utc) + timedelta(seconds=1), document["generated_at"])
        self.assertFalse([warning for warning in document["warnings"] if warning.startswith("stale")], document["warnings"])
        started = time.monotonic()
        self.assertEqual(get("/doc", f"track={track}")[1], body)
        cached = time.monotonic() - started
        print(f"\n[roadmap live] {track}: projected in {elapsed:.1f}s, served from the cache in {cached * 1000:.0f}ms")

    def test_kinsim(self) -> None:
        self.check("kinsim", Path(load_sources()["kinsim_curriculum_dir"]) / "curriculum.json")

    def test_rig(self) -> None:
        self.check("rig", Path(load_sources()["rig_loop_dir"]) / "ladder.json")


if __name__ == "__main__":
    unittest.main()
