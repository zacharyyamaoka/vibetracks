"""The frozen Needs-you counts contract: vibetracks/dashboard/needs.py is the ONE source.

    python3 -m unittest tests/test_dashboard_needs_counts.py      (from the repo root)

For every registry track, the projection's ``needs_you_count`` equals what ``/needs?track=<id>`` serves
(``blocking == counts.blocking_now``, ``open == counts.wants_you``); a track with no structured source is null/null;
grasping and detection are structured items parsed by their adapters' own parsers. Fixtures only, except
``LiveCountsTest``, which runs against this machine's real loop files when they exist.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard import build as build_module
from vibetracks.dashboard import needs, registry
from vibetracks.dashboard.adapters import detection as detection_adapter
from vibetracks.dashboard.adapters import grasping as grasping_adapter
from vibetracks.sources import load_sources

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"

CURRICULUM = '''"""Fixture curriculum, same shape as grasp_bench/src/grasp_bench/curriculum.py."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import EnvSpec, ModelSpec

TIERS = {1: "Toy grasping - synthetic images", 2: "MuJoCo physics - heightmap"}
ENVS = (
    EnvSpec("toy/x", "1-DoF: pick a disc along a strip", 1, "1", "F0", "synthetic image", "top1_success", "planar", "jaw"),
    EnvSpec("mujoco/stage0", "MuJoCo stage 0: one elongated box", 2, "3+1", "F2", "GT heightmap", "top1_success",
            "planar", "2F-85"),
)
MODELS = (
    ModelSpec("M0.uniform", "Random", 0, "floor", "none", "planar", False, "BAM (ours)"),
    ModelSpec("M5.ggcnn", "GG-CNN (planar, Cornell)", 5, "published", "depth", "planar", False, "BSD-3",
              notes="Needs a download (weights in the release zip)."),
    ModelSpec("M5.rngnet", "RNGNet (CoRL 2024)", 5, "published", "rgbd", "6dof", False, "no LICENSE file",
              notes="Needs a download (~85 MB)."),
)


@dataclass(frozen=True)
class Cell:
    model: str
    env: str
    status: str
    why: str = ""

    @property
    def id(self) -> str:
        return f"{self.model}@{self.env}"


CELLS = (
    Cell("M0.uniform", "toy/x", "wave1"),
    Cell("M5.ggcnn", "toy/x", "needs", "download approval (planar classics, BSD-3)"),
    Cell("M5.ggcnn", "mujoco/stage0", "needs", "download approval"),
    Cell("M5.rngnet", "mujoco/stage0", "needs", "download approval"),
    Cell("M0.uniform", "mujoco/stage0", "needs", "arm homing + hand-eye calibration"),
)
GATES = {"toy/x": 0.97}
'''

PLAN = """# Plan

## Needs you

Three decisions.

1. **Data.** The drive is not mounted, and it blocks H1, H2 and H4: run `udisksctl mount -b /dev/sdb` yourself. *Default if silent:* the loop runs H0.
2. **Host.** Linux or Windows; H0–H7 never touch the camera. Keep `pll_filter_hz` as is.
\t- a reason that is not the question

\tThe Windows box becomes the capture station. *Default if silent:* Linux.
3. **Start the loop.** The work order is ready.

**For your information (no default needed):**
- An aside that is not part of item 3.

## Next section
"""

LADDER = '''
RUNGS = [
    dict(id="H1", short="Published ruler", needs_rungs=[]),
    dict(id="H2", short="Real class spectra", needs_rungs=[]),
    dict(id="H4", short="Sim → real", needs_rungs=["H1"]),
]
KPIS = []
'''


def triage_item(triage_id, *, after, blocks=(), status="open"):
    return {"triage_id": triage_id, "title": f"Title of {triage_id}", "opened_wave": 1, "question": "Q.",
            "recommendation": "R.", "default": "D.", "default_applies_after_wave": after, "blocks": list(blocks),
            "status": status}


class Fixture:
    """Loop files for kinsim, rig, grasping and detection in one temp dir; pyblocks has none (it writes no questions)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        kinsim_dir = root / "kinsim"
        home = root / "home"
        rig_dir = root / "rig"
        for path in (kinsim_dir, home, rig_dir):
            path.mkdir(parents=True)
        self.json(kinsim_dir / "triage.json", {"schema": "bam-triage/1", "items": [
            triage_item("T47", after=5, blocks=["BT3"]),   # blocking (default pending)
            triage_item("T12", after=None),                # no default
            triage_item("T53", after=6),                   # waiting
            triage_item("T11", after=1),                   # defaulting: not wanted
            triage_item("T1", after=1, status="defaulted"),
        ]})
        self.json(home / "status.json", {"wave": 4, "phase": "between_waves"})
        self.json(rig_dir / "triage.json", {"schema": "bam-triage/1", "items": [
            triage_item("T2", after=None, blocks=["BN1"]),  # blocking, no default
            triage_item("T4", after=1, blocks=["BN1"]),     # names a rung but its default is in effect: not blocking
            triage_item("T17", after=None),
        ]})
        self.json(rig_dir / "loop-status.json", {"tick": {"n": 4, "phase": "running"}})
        self.curriculum = root / "grasp" / "curriculum.py"
        self.curriculum.parent.mkdir()
        self.curriculum.write_text(CURRICULUM, encoding="utf-8")
        self.plan = root / "vault" / "Plan.md"
        self.plan.parent.mkdir()
        self.plan.write_text(PLAN, encoding="utf-8")
        self.ladder = root / "ladder_data.py"
        self.ladder.write_text(LADDER, encoding="utf-8")
        self.paths = {"kinsim_triage_dir": str(kinsim_dir), "kinsim_home": str(home), "rig_loop_dir": str(rig_dir),
                      "bam_ws_root": str(root / "no-repo"), "kinsim_loop_branch": "no-such-branch",
                      "rig_loop_branch": "no-such-branch", "grasping_curriculum": str(self.curriculum),
                      "detection_plan_note": str(self.plan), "detection_ladder": str(self.ladder)}

    @staticmethod
    def json(path: Path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")


def served(track_id: str, sources, workspace=WORKSPACE) -> dict:
    status, _, body = needs.handle("GET", "", {"track": [track_id]}, {}, sources=sources, workspace=workspace)
    assert status == 200, (track_id, status)
    return json.loads(b"".join(body))


class CountsContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.quiet = contextlib.redirect_stderr(io.StringIO())
        self.quiet.__enter__()
        builder = build_module.LiveBuilder(WORKSPACE, Path(self.tmp.name) / "data-home", sources=lambda: dict(self.fx.paths))
        self.projection = builder.build()
        self.tracks = {t["id"]: t for t in self.projection["tracks"] if t["kind"] == "loop"}

    def tearDown(self) -> None:
        self.quiet.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_every_registry_track_matches_what_needs_serves(self) -> None:
        ids = [t.id for t in registry.load_registry(WORKSPACE) if not t.archived]
        self.assertEqual(sorted(self.tracks), sorted(ids))
        for track_id in ids:
            with self.subTest(track=track_id):
                doc = served(track_id, self.fx.paths)
                count = self.tracks[track_id]["needs_you_count"]
                self.assertEqual(count, {"open": doc["counts"]["wants_you"], "blocking": doc["counts"]["blocking_now"]})
                self.assertEqual([row["id"] for row in self.tracks[track_id]["needs_you"]],
                                 [it["local_id"] for it in doc["items"] if it["group"] in needs.WANTS_YOU_GROUPS])

    def test_the_numbers(self) -> None:
        counts = {track_id: track["needs_you_count"] for track_id, track in self.tracks.items()}
        self.assertEqual(counts["kinsim"], {"open": 3, "blocking": 1})
        self.assertEqual(counts["rig"], {"open": 2, "blocking": 1}, "T4 names BN1 but its default is in effect")
        self.assertEqual(counts["grasping"], {"open": 2, "blocking": 0}, "two model ids; approvals hold cells, not rungs")
        self.assertEqual(counts["detection"], {"open": 3, "blocking": 1})
        self.assertEqual(counts["pyblocks"], {"open": None, "blocking": None}, "no structured source: null, never 0")
        self.assertEqual(self.tracks["pyblocks"]["needs_you"], [])

    def test_needs_you_rows_keep_the_shape_and_order(self) -> None:
        rows = self.tracks["kinsim"]["needs_you"]
        self.assertEqual([row["id"] for row in rows], ["T47", "T12", "T53"])
        self.assertEqual(rows[0], {"id": "T47", "q": "Title of T47", "blocks": ["BT3"], "default": "D.", "applies": "after W5"})
        self.assertEqual(rows[1]["applies"], None)
        for track in self.tracks.values():
            for row in track["needs_you"]:
                self.assertEqual(set(row), {"id", "q", "blocks", "default", "applies"})

    def test_titles_follow_the_registry(self) -> None:
        for track in registry.load_registry(WORKSPACE):
            if not track.archived:
                self.assertEqual(served(track.id, self.fx.paths)["track_title"], track.title)


class RenameAndUnknownTest(unittest.TestCase):
    def test_a_rename_shows_on_the_needs_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "tracks").mkdir()
            (ws / "w.vtdash").write_text(json.dumps({"registry": "Work tracks.vibetrack"}), encoding="utf-8")
            (ws / "Work tracks.vibetrack").write_text(
                "filters:\n  and:\n    - 'note[\"vibe-track\"] == \"worktrack\"'\nvibetracks:\n  version: 1\n"
                "  id: work-tracks\n  title: Work tracks\n  vaultRoot: .\n  source: tracks\n", encoding="utf-8")
            (ws / "tracks" / "rig.md").write_text("---\nvibe-track: worktrack\nvibe-id: rig\nvibe-title: Renamed rig\n"
                                                  "vibe-priority: 1\n---\n\nPurpose.\n", encoding="utf-8")
            (ws / "tracks" / "extra.md").write_text("---\nvibe-track: worktrack\nvibe-id: extra\nvibe-title: Extra\n"
                                                    "vibe-priority: 2\n---\n\nPurpose.\n", encoding="utf-8")
            self.assertEqual(served("rig", {}, ws)["track_title"], "Renamed rig")
            extra = served("extra", {}, ws)
            self.assertEqual(extra["items"], [])
            self.assertEqual(needs.needs_you_count(extra), {"open": None, "blocking": None})
            status, _, body = needs.handle("GET", "", {}, {}, sources={}, workspace=ws)
            self.assertEqual([doc["track"] for doc in json.loads(b"".join(body))["tracks"]], ["rig", "extra"])
            self.assertEqual(needs.handle("GET", "", {"track": ["nope"]}, {}, sources={}, workspace=ws)[0], 404)

    def test_an_unreadable_registry_falls_back_to_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            listed, problem = needs.registry_tracks(tmp)
        self.assertEqual([track for track, _ in listed], needs.FALLBACK_TRACK_IDS)
        self.assertEqual([title for _, title in listed], needs.FALLBACK_TRACK_IDS)
        self.assertIn("registry unreadable", problem)


class GraspingItemsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.doc = needs.build_track("grasping", self.fx.paths, title="Grasping")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_one_item_per_model_id_from_the_adapters_own_parser(self) -> None:
        approvals, other = grasping_adapter.needs_cells(grasping_adapter.load_curriculum(self.fx.curriculum))
        self.assertEqual([it["local_id"] for it in self.doc["items"]], list(approvals))
        for item in self.doc["items"]:
            self.assertEqual([b["id"] for b in item["blocks"]], [cell.id for cell in approvals[item["local_id"]]])
            self.assertTrue(all(b["kind"] == "cell" for b in item["blocks"]))
        self.assertIn("arm homing + hand-eye calibration", self.doc["source"]["note"])
        self.assertEqual(list(other), ["arm homing + hand-eye calibration"])

    def test_words_are_the_files_own_and_no_default_is_recorded(self) -> None:
        ggcnn = self.doc["items"][0]
        self.assertEqual(ggcnn["id"], "grasping:M5.ggcnn")
        self.assertEqual(ggcnn["ask"], "M5.ggcnn · download approval", "the model id plus the cells' own words")
        self.assertEqual(ggcnn["title"], "GG-CNN (planar, Cornell)")
        self.assertEqual(ggcnn["context_lead_md"], "Needs a download (weights in the release zip).")
        for verbatim in ("download approval (planar classics, BSD-3)", "`M5.ggcnn@mujoco/stage0`", "Licence: BSD-3"):
            self.assertIn(verbatim, ggcnn["context_md"])
        self.assertEqual(ggcnn["default"], {"text_md": "", "applies": {"unit": "never", "after": None}, "state": "none"})
        self.assertEqual(ggcnn["group"], "no_default")
        self.assertFalse(ggcnn["blocking_now"])
        self.assertEqual(ggcnn["blocks"][0]["label"], "1-DoF: pick a disc along a strip · tier 1")
        self.assertEqual([o["key"] for o in ggcnn["options"]], ["approve", "use_default", "other"])
        self.assertTrue(all(o["source"] == "dashboard" and not o["recommended"] for o in ggcnn["options"]),
                        "the answer affordances are the dashboard's, and the file records no recommendation")
        self.assertEqual(ggcnn["evidence"][0]["kind"], "file_line")
        self.assertEqual(self.doc["answer_channel"]["kind"], "chat_paste")
        self.assertIn("name model ids verbatim", self.doc["answer_channel"]["read_back"])
        self.assertTrue(self.doc["source"]["live"])

    def test_a_broken_curriculum_is_a_reason_with_null_counts(self) -> None:
        self.fx.curriculum.write_text("from .other import X\n", encoding="utf-8")
        doc = needs.build_track("grasping", self.fx.paths, title="Grasping")
        self.assertEqual(doc["items"], [])
        self.assertIn("could not be read", doc["source"]["note"])
        self.assertIsNone(doc["counts"]["wants_you"])


class DetectionItemsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.doc = needs.build_track("detection", self.fx.paths, title="Detection")
        self.items = {it["local_id"]: it for it in self.doc["items"]}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_adapters_parser_and_the_page_agree(self) -> None:
        entries = detection_adapter.parse_needs_section(PLAN)
        self.assertEqual(sorted(self.items), [f"plan-{entry['n']}" for entry in entries])
        adapter_rows = {row["id"]: row for row in detection_adapter.read_needs(self.fx.plan)}
        for local_id, item in self.items.items():
            self.assertEqual([b["id"] for b in item["blocks"]], adapter_rows[local_id]["blocks"])

    def test_prose_is_verbatim(self) -> None:
        host = self.items["plan-2"]
        self.assertEqual(host["title"], "Host.")
        self.assertIn("`pll_filter_hz`", host["context_md"], "no *, _ or backtick is stripped")
        self.assertIn("\t- a reason that is not the question", host["context_md"])
        self.assertEqual(host["default"]["text_md"], "Linux.")
        self.assertEqual(host["default"]["applies"], {"unit": "unstated", "after": None})
        self.assertEqual(host["group"], "waiting")
        data = self.items["plan-1"]
        self.assertEqual(data["group"], "blocking")
        self.assertEqual([(b["id"], b["label"]) for b in data["blocks"]],
                         [("H1", "Published ruler"), ("H2", "Real class spectra"), ("H4", "Sim → real")])
        self.assertEqual(data["ask"], "**Data.** The drive is not mounted, and it blocks H1, H2 and H4: run "
                                      "`udisksctl mount -b /dev/sdb` yourself.")
        self.assertIsNone(data["context_lead_md"], "the ask took the only sentence; nothing is left to lead with")
        self.assertEqual(host["ask"], "**Host.** Linux or Windows; H0–H7 never touch the camera.")
        self.assertEqual(host["context_lead_md"], "Keep `pll_filter_hz` as is.")
        self.assertNotIn("/dev/sdb", [e.get("path") for e in data["evidence"]], "a device file is not evidence")
        self.assertEqual(data["evidence"][0]["line"], 7)

    def test_no_default_recorded_says_so(self) -> None:
        start = self.items["plan-3"]
        self.assertEqual(start["default"]["text_md"], "")
        self.assertEqual(start["default"]["applies"]["unit"], "never")
        self.assertEqual(start["group"], "no_default")
        self.assertNotIn("An aside", start["context_md"], "the section's trailing aside is not part of item 3")
        row = next(r for r in needs.needs_you_rows(self.doc) if r["id"] == "plan-3")
        self.assertIsNone(row["default"], "PROJECTION.md: a null default reads 'no default recorded'")

    def test_counts(self) -> None:
        self.assertEqual(needs.needs_you_count(self.doc), {"open": 3, "blocking": 1})


@unittest.skipUnless(Path(load_sources().get("grasping_curriculum", "/nonexistent")).is_file(),
                     "the grasp bench is not on this machine")
class LiveCountsTest(unittest.TestCase):
    """The real loops' files: the projection and /needs agree for every registry track, whatever the numbers are."""

    def test_projection_equals_needs_for_every_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            projection = build_module.LiveBuilder(WORKSPACE, tmp).build()
        sources = load_sources()
        for track in (t for t in projection["tracks"] if t["kind"] == "loop"):
            with self.subTest(track=track["id"]):
                doc = served(track["id"], sources)
                self.assertEqual(track["needs_you_count"], needs.needs_you_count(doc))
        pyblocks = next(t for t in projection["tracks"] if t["id"] == "pyblocks")
        self.assertEqual(pyblocks["needs_you_count"], {"open": None, "blocking": None})


if __name__ == "__main__":
    unittest.main()
