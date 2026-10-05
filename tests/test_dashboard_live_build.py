"""The live projection (vibetracks/dashboard/build.py LiveBuilder) over the work-track registry.

    python3 -m unittest tests/test_dashboard_live_build.py      (from the repo root)

Adapters here live in a throwaway package on sys.path, so these tests never depend on the five real adapters, which
other lanes are about to replace.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from vibetracks.dashboard import build as build_module
from vibetracks.dashboard import registry
from vibetracks.dashboard.adapters import base
from vibetracks.notes import note_revision

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"
DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "worktrack"'
    - 'file.inFolder("tracks")'
vibetracks:
  version: 1
  id: work-tracks
  title: Work tracks
  vaultRoot: .
  source: tracks
"""

GOOD = '''
from vibetracks.dashboard.adapters.base import skeleton

CALLS = []

def build_track(work_track, sources):
    CALLS.append(dict(sources))
    track = skeleton(work_track, unit="wave")
    track.update(id="ignored-id", title="ignored title", summary="two waves", reporting=True)
    track["state"] = {"word": "Running", "tone": "ok", "detail": "wave 2", "since": None}
    track["iterations"] = [{"id": "W1", "label": "W1", "date": None, "marker": "", "provenance": {}},
                           {"id": "W2", "label": "W2", "date": None, "marker": "", "provenance": {}}]
    track["iteration"] = {"unit": "wave", "label": "wave 2"}
    track["kpis"] = [{"id": "rungs", "label": "Rungs green", "slot": "S1", "unit": "rungs", "direction": "higher",
                      "target": None, "baseline": None, "status": {"word": "+1", "tone": "muted"}, "note": None,
                      "aggregate": None, "provenance": {},
                      "values": [{"iteration": "W1", "value": None, "of": None, "n": None, "spread": None,
                                  "measured": False, "note": "not read in W1", "evidence": []},
                                 {"iteration": "W2", "value": 3, "of": 9, "n": None, "spread": None,
                                  "measured": True, "note": None, "evidence": []}]}]
    track["north_star"] = "rungs"
    track["needs_you"] = [{"id": "T1", "q": "?", "blocks": ["R2"], "default": None, "applies": None},
                          {"id": "T2", "q": "?", "blocks": [], "default": "x", "applies": None}]
    track["media"] = {work_track.id + "-report": {"id": work_track.id + "-report", "kind": "html", "label": "r",
                                                  "path": sources.get("status", "/nonexistent"), "mime": "text/html", "bytes": 1}}
    return track

def build_children(work_track, sources):
    child = skeleton(work_track)
    child.update(id="kid", summary="a deployment", reporting=True)
    child["state"] = {"word": "Live", "tone": "ok", "detail": None, "since": None}
    return [child, dict(child, id="not-declared")]
'''
BOOM = "def build_track(work_track, sources):\n    raise RuntimeError('loop file torn')\n"
BAD = "def build_track(work_track, sources):\n    return {'summary': 3}\n"
NO_ENTRY = "VALUE = 1\n"


def note(track_id: str, title: str, adapter: str, *, priority: int = 1, status: str = "running", children: str = "[]",
         sources: str = "[status]", extra: str = "") -> str:
    return (f"---\nvibe-track: worktrack\nvibe-id: {track_id}\nvibe-title: {title}\nvibe-status: {status}\n"
            f"vibe-priority: {priority}\nvibe-adapter: {adapter}\nvibe-sources: {sources}\nvibe-roadmap: null\n"
            f"vibe-children: {children}\n{extra}---\n\n# {title}\n\nWhat this loop is for.\n")


class LiveBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "ws"
        (self.ws / "tracks").mkdir(parents=True)
        (self.ws / "Agent work.vtdash").write_text(json.dumps({"registry": "Work tracks.vibetrack"}), encoding="utf-8")
        (self.ws / "Work tracks.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
        self.status = root / "loop" / "status.json"
        self.status.parent.mkdir()
        self.status.write_text("{}", encoding="utf-8")
        self.now = time.time()
        os.utime(self.status, (self.now - 3600, self.now - 3600))  # one hour quiet
        self.package = "vt_live_test_" + uuid.uuid4().hex[:8]
        self.package_dir = root / "pkgs" / self.package
        self.package_dir.mkdir(parents=True)
        (self.package_dir / "__init__.py").write_text("", encoding="utf-8")
        for name, source in (("good", GOOD), ("boom", BOOM), ("bad", BAD), ("noentry", NO_ENTRY)):
            (self.package_dir / f"{name}.py").write_text(source, encoding="utf-8")
        sys.path.insert(0, str(root / "pkgs"))
        self.paths = {"status": str(self.status), "missing": str(root / "nope.json")}
        self.builder = build_module.LiveBuilder(self.ws, root / "home", sources=lambda: dict(self.paths),
                                                clock=lambda: self.now, package=self.package)
        # The builder prints an adapter's traceback to stderr (the backend log); keep the test output readable.
        self.quiet = contextlib.redirect_stderr(io.StringIO())
        self.quiet.__enter__()

    def tearDown(self) -> None:
        self.quiet.__exit__(None, None, None)
        sys.path.remove(str(Path(self.tmp.name) / "pkgs"))
        for name in [n for n in sys.modules if n.startswith(self.package)]:
            del sys.modules[name]
        self.tmp.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.ws / "tracks" / name
        path.write_text(content, encoding="utf-8")
        return path

    def track(self, projection: dict, track_id: str) -> dict:
        return next(t for t in projection["tracks"] if t["id"] == track_id)

    # ---- shape and order
    def test_order_archived_and_source_block(self) -> None:
        self.write("a.md", note("second", "Second", "good", priority=2))
        self.write("b.md", note("first", "First", "good", priority=1))
        self.write("c.md", note("gone", "Gone", "good", priority=3, status="archived"))
        self.write("d.md", note("paused", "Paused", "good", priority=4, status="paused"))
        projection = self.builder.build()
        self.assertEqual(projection["schema"], "vibetracks-dashboard/1")
        self.assertTrue(projection["source"]["live"])
        self.assertEqual(projection["source"]["kind"], "live")
        self.assertEqual(projection["source"]["todo"], "")
        self.assertEqual([t["id"] for t in projection["tracks"]], ["first", "second", "paused"])
        self.assertEqual(projection["registry"]["order"], ["first", "second", "paused"])
        self.assertEqual(projection["registry"]["archived"], [{"id": "gone", "title": "Gone"}])
        self.assertEqual(self.track(projection, "paused")["registry"]["status"], "paused")

    def test_the_build_owns_id_title_and_lifts_media(self) -> None:
        path = self.write("a.md", note("kin", "Kinematic Sim", "good"))
        track = self.track(self.builder.build(), "kin")
        self.assertEqual((track["id"], track["title"], track["kind"], track["parent"]), ("kin", "Kinematic Sim", "loop", None))
        self.assertTrue(track["reporting"])
        self.assertEqual(track["registry"]["revision"], note_revision(path.read_text(encoding="utf-8")))
        self.assertEqual(track["purpose"], "What this loop is for.")
        self.assertEqual(track["needs_you_count"], {"open": 2, "blocking": 1})
        self.assertNotIn("media", track)
        self.assertEqual(track["source"], {"adapter": "good", "kind": "live", "live": True})
        module = importlib.import_module(f"{self.package}.good")
        self.assertEqual(module.CALLS[-1], {"status": str(self.status)})  # only the declared keys
        projection = self.builder.build()
        self.assertIn("kin-report", projection["media"])

    # ---- honest failure
    def test_failing_adapters_read_not_reporting(self) -> None:
        self.write("a.md", note("boom", "Boom", "boom", priority=1))
        self.write("b.md", note("bad", "Bad", "bad", priority=2))
        self.write("c.md", note("missing", "Missing", "no_such_adapter", priority=3))
        self.write("d.md", note("noentry", "No entry", "noentry", priority=4))
        self.write("e.md", note("none", "None", "none", priority=5).replace("vibe-adapter: none\n", ""))
        projection = self.builder.build()
        details = {t["id"]: t["state"]["detail"] for t in projection["tracks"]}
        self.assertEqual(details["boom"], "adapter error · RuntimeError: loop file torn")
        self.assertTrue(details["bad"].startswith("adapter output invalid · "), details["bad"])
        self.assertEqual(details["missing"], "no adapter module adapters/no_such_adapter.py")
        self.assertEqual(details["noentry"], "adapter noentry has no build_track")
        self.assertEqual(details["none"], "no adapter declared (vibe-adapter)")
        for track in projection["tracks"]:
            self.assertFalse(track["reporting"])
            self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
            self.assertTrue(track["summary"].startswith("not reporting · "))
            self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})
            self.assertEqual((track["kpis"], track["iterations"], track["north_star"]), ([], [], None))
            self.assertEqual(track["source"]["live"], False)
            self.assertEqual(base.problems(track), [])
        self.assertIn("boom (adapter error", projection["source"]["todo"])

    def test_stub_adapters_are_valid_not_reporting_tracks(self) -> None:
        work_track = registry.load_registry(WORKSPACE)[0]
        for name in ("kinsim", "rig", "grasping", "detection", "pyblocks"):
            module = importlib.import_module(f"vibetracks.dashboard.adapters.{name}")
            track = module.build_track(work_track, {})
            self.assertEqual(base.problems(track), [], name)
            self.assertEqual(track["summary"], "not reporting · adapter pending")

    # ---- cache
    def test_adapter_reruns_only_when_its_inputs_change(self) -> None:
        path = self.write("a.md", note("kin", "Kin", "good"))
        self.builder.build()
        self.builder.build()
        self.assertEqual(self.builder.adapter_runs, 1)
        os.utime(self.status, (self.now - 60, self.now - 60))  # the loop wrote its status file
        self.builder.build()
        self.assertEqual(self.builder.adapter_runs, 2)
        registry.rename_title(self.ws, "kin", "Kinematic Sim", note_revision(path.read_text(encoding="utf-8")))
        renamed = self.builder.build()
        self.assertEqual(self.builder.adapter_runs, 3)
        self.assertEqual(self.track(renamed, "kin")["title"], "Kinematic Sim")
        self.builder.build(force=True)
        self.assertEqual(self.builder.adapter_runs, 4)

    def test_an_edited_adapter_module_is_reloaded(self) -> None:
        self.write("a.md", note("kin", "Kin", "boom"))
        self.assertEqual(self.track(self.builder.build(), "kin")["state"]["detail"], "adapter error · RuntimeError: loop file torn")
        module_file = self.package_dir / "boom.py"
        module_file.write_text(GOOD, encoding="utf-8")
        later = time.time() + 5
        os.utime(module_file, (later, later))
        track = self.track(self.builder.build(), "kin")
        self.assertTrue(track["reporting"])
        self.assertEqual(track["state"]["word"], "Running")

    # ---- freshness
    def test_freshness_and_the_stall_rule(self) -> None:
        self.write("a.md", note("fresh", "Fresh", "good", priority=1))
        self.write("b.md", note("quiet", "Quiet", "good", priority=2, extra="vibe-stall-hours: 0.5\n"))
        self.write("c.md", note("lost", "Lost", "good", priority=3, sources="[missing]"))
        self.write("d.md", note("typo", "Typo", "good", priority=4, sources="[status, not_a_key]",
                                extra="vibe-heartbeat: [status]\n"))
        projection = self.builder.build()
        fresh = self.track(projection, "fresh")
        self.assertEqual(fresh["freshness"]["stale"], False)
        self.assertEqual(fresh["freshness"]["newest_source"], "status")
        self.assertAlmostEqual(fresh["freshness"]["age_h"], 1.0, places=1)
        self.assertEqual(fresh["freshness"]["stall_hours"], 24.0)
        self.assertEqual(fresh["state"]["tone"], "ok")
        quiet = self.track(projection, "quiet")
        self.assertTrue(quiet["freshness"]["stale"])
        self.assertEqual(quiet["state"]["tone"], "stale")
        self.assertEqual(quiet["state"]["word"], "Running")
        self.assertIn("sources quiet 1 h · stall rule 0.5 h", quiet["state"]["detail"])
        lost = self.track(projection, "lost")
        self.assertIsNone(lost["freshness"]["stale"])  # unknown, never "fine"
        self.assertEqual(lost["freshness"]["note"], "no source file found · liveness unknown")
        self.assertIn({"path": "d.md", "error": "vibe-sources key 'not_a_key' is not in sources.py"},
                      projection["registry"]["problems"])

    # ---- children
    def test_children_are_embedded_under_their_parent_never_top_level(self) -> None:
        self.write("a.md", note("rigx", "Rig", "good", children="[kid, other]"))
        projection = self.builder.build()
        self.assertEqual(projection["registry"]["order"], ["rigx"])
        ids = [t["id"] for t in projection["tracks"]]
        self.assertEqual(ids, ["rigx", "kid", "other"])
        kid, other = self.track(projection, "kid"), self.track(projection, "other")
        self.assertEqual((kid["parent"], kid["kind"], kid["state"]["word"]), ("rigx", "deployment", "Live"))
        self.assertEqual(other["parent"], "rigx")
        self.assertFalse(other["reporting"])
        self.assertNotIn("not-declared", ids)
        self.assertEqual(self.track(projection, "rigx")["children"], ["kid", "other"])
        self.assertEqual([t["id"] for t in projection["tracks"] if t["parent"] is None], ["rigx"])


@unittest.skipUnless(build_module.SNAPSHOT_ORIGIN.is_file(), f"snapshot not on this machine: {build_module.SNAPSHOT_ORIGIN}")
class RealWorkspaceTest(unittest.TestCase):
    """The checked-in registry with the stub adapters: five rows, and rig's deployments from the snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projection = build_module.LiveBuilder(WORKSPACE, cls.tmp.name).build()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_five_top_level_tracks(self) -> None:
        top = [t for t in self.projection["tracks"] if t["parent"] is None]
        self.assertEqual([t["id"] for t in top], ["kinsim", "rig", "grasping", "detection", "pyblocks"])
        self.assertEqual(top[1]["title"], "Sim to Real & Trajectory Tracking")
        self.assertTrue(self.projection["source"]["live"])
        for track in top:
            self.assertIn("freshness", track)
            self.assertEqual(base.problems(track), [])

    def test_rig_children_come_from_the_snapshot_and_say_so(self) -> None:
        children = [t for t in self.projection["tracks"] if t["parent"] is not None]
        self.assertEqual([(t["id"], t["parent"], t["kind"]) for t in children],
                         [("can12", "rig", "deployment"), ("can16", "rig", "deployment")])
        for child in children:
            self.assertEqual(child["source"]["kind"], "snapshot")
            self.assertFalse(child["source"]["live"])
            self.assertTrue(child["freshness"]["stale"])  # a 10-03 snapshot is never fresh
            self.assertTrue(child["kpis"])

    def test_every_media_reference_is_in_the_allowlist(self) -> None:
        media = self.projection["media"]
        self.assertTrue(media)
        for track in self.projection["tracks"]:
            for ref in build_module._media_ids(track):
                self.assertIn(ref, media, f"{track['id']} -> {ref}")
        for entry in media.values():
            self.assertTrue(Path(entry["path"]).is_file(), entry["path"])


if __name__ == "__main__":
    unittest.main()
