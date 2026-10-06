"""vibetracks/sources.py: the machine path map the adapter, build and backend read.

    python3 -m unittest tests/test_dashboard_sources.py      (from the repo root)
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from vibetracks import sources
from vibetracks.dashboard import build as build_module
from vibetracks.dashboard.adapters import bam_loops

HOME = str(Path("~").expanduser())
KEYS = {"kinsim_home", "kinsim_curriculum_dir", "rig_loop_dir", "deployments_fixtures_dir", "run_media_root",
        "reports_media_dir", "dashboard_data_home"}


class SourcesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "sources.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def load(self, payload: object | None = None, raw: str | None = None) -> dict[str, str]:
        if raw is not None:
            self.file.write_text(raw, encoding="utf-8")
        elif payload is not None:
            self.file.write_text(json.dumps(payload), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as self.stderr:
            return sources.load_sources(self.file)

    def test_defaults_when_the_file_is_missing(self) -> None:
        loaded = self.load()
        # WHY: the key set is append-only by agreement with the roadmap session, so pin the
        # dashboard's own keys as a subset, never the exact set (their appends must not break this).
        self.assertLessEqual(KEYS, set(loaded))
        self.assertEqual(loaded["kinsim_home"], os.path.join(HOME, ".local/share/bam_curriculum"))
        self.assertEqual(loaded["dashboard_data_home"], os.path.join(HOME, ".local/share/vibetracks/dashboard"))
        self.assertEqual(loaded["run_media_root"],
                         "/home/bam/bam_ws/src/core/mdp/agent/actor/trajectory_generation/traj_integration_tests/out")
        self.assertEqual(loaded["reports_media_dir"], "/home/bam/bam_ws/reports/media")
        self.assertEqual(loaded["rig_loop_dir"],
                         "/home/bam/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop")
        for value in loaded.values():
            self.assertTrue(Path(value).is_absolute(), value)
            self.assertNotIn("~", value)

    def test_the_file_overrides_and_expands_tilde(self) -> None:
        loaded = self.load({"run_media_root": "~/runs", "extra_dir": "~/extra"})
        self.assertEqual(loaded["run_media_root"], os.path.join(HOME, "runs"))
        self.assertEqual(loaded["extra_dir"], os.path.join(HOME, "extra"))
        self.assertEqual(loaded["reports_media_dir"], "/home/bam/bam_ws/reports/media")

    def test_bad_values_and_bad_files_fall_back_with_a_warning(self) -> None:
        loaded = self.load({"run_media_root": 3, "reports_media_dir": "  "})
        self.assertEqual(loaded["run_media_root"], sources.load_sources(Path(self.tmp.name) / "none.json")["run_media_root"])
        self.assertIn("run_media_root", self.stderr.getvalue())
        for raw in ("{not json", "[1, 2]"):
            with self.subTest(raw=raw):
                self.assertEqual(self.load(raw=raw)["kinsim_home"], os.path.join(HOME, ".local/share/bam_curriculum"))
                self.assertIn("ignoring", self.stderr.getvalue())

    def test_work_track_keys_follow_the_folder_they_name(self) -> None:
        loaded = self.load()
        self.assertEqual(loaded["kinsim_status"], os.path.join(HOME, ".local/share/bam_curriculum/status.json"))
        self.assertEqual(loaded["rig_loop_status"], loaded["rig_loop_dir"] + "/loop-status.json")
        moved = self.load({"rig_loop_dir": "/elsewhere/bam_rig_loop", "self_ref": "{self_ref}/x", "unknown": "{nope}/x"})
        self.assertEqual(moved["rig_loop_status"], "/elsewhere/bam_rig_loop/loop-status.json")
        self.assertEqual(moved["self_ref"], str(Path("{self_ref}/x")))  # verbatim: a typo stays visible
        self.assertEqual(moved["unknown"], str(Path("{nope}/x")))

    def test_the_environment_names_the_file(self) -> None:
        self.file.write_text(json.dumps({"kinsim_home": "/elsewhere"}), encoding="utf-8")
        self.assertEqual(sources.load_sources(environ={"VIBETRACKS_SOURCES": str(self.file)})["kinsim_home"], "/elsewhere")

    def test_the_adapter_and_build_read_their_paths_through_it(self) -> None:
        loaded = sources.load_sources()
        self.assertEqual(bam_loops.TRAJ_OUT, Path(loaded["run_media_root"]))
        self.assertEqual(bam_loops.AUDITS_DIR, Path(loaded["reports_media_dir"]) / "audits")
        self.assertEqual(build_module.CURRICULUM_ORIGIN, Path(loaded["kinsim_curriculum_dir"]) / "curriculum.json")
        self.assertEqual(build_module.DEFAULT_HOME, Path(loaded["dashboard_data_home"]))
        saved = os.environ.pop("VIBETRACKS_DASHBOARD_HOME", None)
        try:
            self.assertEqual(build_module.data_home(), Path(loaded["dashboard_data_home"]))
        finally:
            if saved is not None:
                os.environ["VIBETRACKS_DASHBOARD_HOME"] = saved


if __name__ == "__main__":
    unittest.main()


class WorktreeResolveTest(unittest.TestCase):
    def setUp(self) -> None:
        sources._WORKTREE_CACHE.clear()

    def test_resolves_the_branch_checkout_and_falls_back(self) -> None:
        porcelain = "worktree /x/main\nHEAD 1\nbranch refs/heads/main\n\nworktree /x/wt\nHEAD 2\nbranch refs/heads/feat\n"
        class Done:
            stdout = porcelain
        original = sources.subprocess.run
        sources.subprocess.run = lambda *a, **k: Done()
        try:
            self.assertEqual(sources._resolve_worktree("@worktree:/x:feat:src/a|/fallback"), "/x/wt/src/a")
            sources._WORKTREE_CACHE.clear()
            self.assertEqual(sources._resolve_worktree("@worktree:/x:gone:src/a|/fallback"), "/fallback")
        finally:
            sources.subprocess.run = original

    def test_live_kinsim_default_is_the_loop_branch_checkout(self) -> None:
        loaded = sources.load_sources(Path("/nonexistent/sources.json"))
        self.assertTrue(loaded["kinsim_curriculum_dir"].endswith("src/dev/bam_curriculum"))
        self.assertNotIn("roadmap-curriculum-viz", loaded["kinsim_curriculum_dir"])
        self.assertEqual(loaded["kinsim_loop_dir"], loaded["kinsim_curriculum_dir"])
