"""The roadmap routes take each track's projector from the Dashboard lane's work-track registry when one is reachable.

A temp copy of the workspace (its .vtdash, its registry descriptor, and track notes written here) keeps these tests
independent of what the real notes say today.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.roadmap import api

WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"

NOTE = """---
vibe-track: worktrack
vibe-id: {id}
vibe-title: {id}
vibe-status: running
vibe-priority: 1
vibe-owner: test
vibe-adapter: none
vibe-sources: []
vibe-roadmap: {roadmap}
vibe-children: []
---

# {id}
"""


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for name in ("Agent work.vtdash", "Work tracks.vibetrack"):
            shutil.copy(WORKSPACE / name, self.tmp / name)
        tracks = self.tmp / "tracks"
        tracks.mkdir()
        roadmaps = {
            "kinsim": "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}",
            "grasping": "{projector: grasping, sources: [grasp_bench_dir]}",
            "pyblocks": "null",
            "oddball": "{projector: nothing-like-this, sources: []}",
            "renamed": "{projector: rig, sources: {rig_loop_dir: kinsim_home}}",
        }
        for track, roadmap in roadmaps.items():
            (tracks / f"{track}.md").write_text(NOTE.format(id=track, roadmap=roadmap), encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_note_names_the_projector(self) -> None:
        self.assertEqual(api.projector_for("kinsim")[0].name, "kinsim")
        self.assertEqual(api.projector_for("grasping")[0].name, "grasping")

    def test_a_null_roadmap_an_unknown_projector_or_an_unregistered_track_reports_none(self) -> None:
        # "No roadmap reported yet": the registry decides once it exists, so even a built-in id is not answered.
        self.assertIsNone(api.projector_for("pyblocks"))
        self.assertIsNone(api.projector_for("oddball"))
        self.assertIsNone(api.projector_for("rig"))

    def test_a_sources_mapping_reads_each_input_from_the_named_key(self) -> None:
        projector, sources = api.projector_for("renamed")
        self.assertEqual(projector.name, "rig")
        self.assertEqual(sources["rig_loop_dir"], sources["kinsim_home"])

    def test_without_a_reachable_registry_the_built_in_table_answers(self) -> None:
        with mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp / "nowhere")}):
            self.assertEqual(api.projector_for("rig")[0].name, "rig")
            self.assertIsNone(api.projector_for("pyblocks"))


if __name__ == "__main__":
    unittest.main()
