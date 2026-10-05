"""The grasping adapter against small temp fixtures, plus one live smoke test against the bench's real ledger.

    cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_adapter_grasping.py

The fixture numbers are chosen so each rule has a case: a frozen run that clears its gate (beaten), a smoke run that
clears it (provisional, not beaten), an oracle that clears it (cannot beat an env), a floor below gate, a second
training seed (its own phase), and a "needs" cell that asks for a download approval.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard.adapters import base, grasping
from vibetracks.dashboard.registry import WorkTrack
from vibetracks.sources import load_sources

CURRICULUM = '''"""Fixture curriculum, same shape as grasp_bench/src/grasp_bench/curriculum.py."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import EnvSpec, ModelSpec

TIERS = {1: "Toy grasping - synthetic images", 2: "MuJoCo physics - heightmap", 3: "Real images, offline - GraspNet"}
ENVS = (
    EnvSpec("toy/x", "1-DoF", 1, "1", "F0 analytic", "synthetic image", "top1_success", "planar", "jaw"),
    EnvSpec("mujoco/stage0", "stage 0", 2, "3+1", "F2 physics", "GT heightmap", "top1_success", "planar", "2F-85"),
    EnvSpec("mujoco/stage1", "stage 1", 2, "3+1", "F2 physics", "GT heightmap", "top1_success", "planar", "2F-85"),
    EnvSpec("graspnet1b/seen/realsense", "GN-1B seen", 3, "3+3+1", "F2 analytic-on-real", "real RGB-D", "ap",
            "6dof", "canonical", min_grasps=50, request_k=300),
)
MODELS = (
    ModelSpec("M0.uniform", "Random", 0, "floor", "none", "planar", False, "BAM (ours)"),
    ModelSpec("M1.oracle", "Oracle", 1, "privileged", "privileged", "planar", False, "BAM (ours)"),
    ModelSpec("M2.hill", "Hill", 2, "heuristic", "height", "planar", False, "BAM (ours)"),
    ModelSpec("M3.bandit", "Bandit", 3, "learned", "rgb", "planar", True, "BAM (ours)"),
    ModelSpec("M5.ggcnn", "GG-CNN (planar, Cornell)", 5, "published", "depth", "planar", False, "BSD-3",
              notes="Needs a download (weights in the release zip)."),
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
    *(Cell(m, e, "wave1") for e in ("toy/x", "mujoco/stage0", "mujoco/stage1")
      for m in ("M0.uniform", "M1.oracle", "M3.bandit")),
    Cell("M0.uniform", "graspnet1b/seen/realsense", "wave1"),
    Cell("M5.ggcnn", "toy/x", "needs", "download approval (planar classics, BSD-3)"),
    Cell("M5.ggcnn", "mujoco/stage0", "needs", "download approval"),
    Cell("M3.bandit", "graspnet1b/seen/realsense", "needs", "kinsim: grasp_command"),
)
GATES = {"toy/x": 0.97, "mujoco/stage0": 0.93, "mujoco/stage1": 0.93}
PUBLISHED_AP = {"graspnet1b/seen/realsense": {"RGB Matters (paper)": 27.98, "RNGNet": 75.2}}
'''


def row(model: str, env: str, tier: int, value: float, ci_lo: float, *, started: str, protocol: str | None = None,
        episodes: int | None = None, seed: int | None = None, dirty: bool = False, p95: float = 5.0,
        input_: str = "rgb") -> dict:
    name, default_n = grasping.frozen_protocol(env)
    episodes = default_n if episodes is None else episodes
    train = {"seed": seed} if seed is not None else {}
    return {
        "run_id": f"{started}_{model}_{env}", "cell_id": f"{model}@{env}", "model": model, "env": env, "tier": tier,
        "protocol": {"name": protocol or name, "seed": 20261004, "episodes": episodes, "split": "test", "k": 1},
        "train_summary": train, "model_info": {"input": input_}, "n": episodes, "metric": "top1_success",
        "value": value, "ci_lo": ci_lo, "ci_hi": min(1.0, value + 0.01), "ap": None,
        "latency_ms_p50": p95 / 2, "latency_ms_p95": p95, "git_sha": "abc", "git_dirty": dirty,
        "started_at": started, "duration_s": 1.0, "notes": "", "artifacts": {},
    }


ROWS = [
    # tier 1: the learner clears toy/x on the frozen protocol (beaten); the oracle is privileged.
    row("M3.bandit", "toy/x", 1, 1.0, 0.998, started="2026-10-05T01:00:00+00:00", seed=20261004),
    row("M1.oracle", "toy/x", 1, 1.0, 0.998, started="2026-10-05T01:00:01+00:00", input_="privileged"),
    row("M0.uniform", "toy/x", 1, 0.18, 0.16, started="2026-10-05T01:00:02+00:00"),
    # tier 2: stage0 beaten on eval-200; stage1 cleared only by a 20-episode smoke (provisional) and by the oracle.
    row("M3.bandit", "mujoco/stage0", 2, 0.97, 0.936, started="2026-10-05T02:00:00+00:00", dirty=True, p95=8.0),
    row("M0.uniform", "mujoco/stage0", 2, 0.01, 0.003, started="2026-10-05T02:00:01+00:00", dirty=True),
    row("M3.bandit", "mujoco/stage1", 2, 1.0, 0.95, started="2026-10-05T02:00:02+00:00", protocol="eval-20",
        episodes=20, dirty=True),
    row("M1.oracle", "mujoco/stage1", 2, 1.0, 0.99, started="2026-10-05T02:00:03+00:00", input_="privileged"),
    row("M0.uniform", "mujoco/stage1", 2, 0.02, 0.008, started="2026-10-05T02:00:04+00:00", p95=1500.0),
    # tier 1 again: a second training seed (the 3-seed rule) is its own phase.
    row("M3.bandit", "toy/x", 1, 1.0, 0.998, started="2026-10-05T03:00:00+00:00", seed=1),
]


def work_track() -> WorkTrack:
    return WorkTrack(id="grasping", title="Grasping", status="running", priority=3, owner=None, adapter="grasping",
                     sources=["grasping_ledger", "grasping_curriculum"], roadmap=None, children=[],
                     note_path="/tmp/grasping.md", revision="r1")


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "src" / "grasp_bench").mkdir(parents=True)
        (root / "out" / "ledger").mkdir(parents=True)
        self.curriculum = root / "src" / "grasp_bench" / "curriculum.py"
        self.curriculum.write_text(CURRICULUM, encoding="utf-8")
        self.ledger = root / "out" / "ledger" / "runs.jsonl"
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in ROWS) + "not json\n", encoding="utf-8")
        self.out = root / "out"
        self.sources = {"grasping_ledger": str(self.ledger), "grasping_curriculum": str(self.curriculum),
                        "grasping_out_dir": str(self.out)}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self) -> dict:
        track = grasping.build_track(work_track(), self.sources)
        self.assertEqual(base.problems(track), [])
        return track

    def kpi(self, track: dict, kpi_id: str) -> dict:
        return next(k for k in track["kpis"] if k["id"] == kpi_id)

    def series(self, track: dict, kpi_id: str) -> list:
        return [v["value"] for v in self.kpi(track, kpi_id)["values"]]

    def test_phases_are_tier_then_seed_in_ledger_order(self) -> None:
        track = self.build()
        self.assertEqual([i["id"] for i in track["iterations"]], ["T1", "T2", "T1-s1"])
        self.assertEqual(track["iterations"][0]["label"], "T1 · Toy grasping")
        self.assertEqual(track["iterations"][2]["label"], "T1 · seed 1")
        self.assertIn("beaten: x", track["iterations"][0]["marker"])
        self.assertIn("beaten: stage0", track["iterations"][1]["marker"])
        self.assertEqual(track["iteration"]["unit"], "wave")
        self.assertEqual(track["iteration"]["label"], "T1 · seed 1")

    def test_beaten_follows_the_gallery_rule(self) -> None:
        track = self.build()
        # toy/x by the learner; stage0 on the frozen protocol. stage1: the smoke is provisional and the oracle cannot beat.
        self.assertEqual(self.series(track, "envs_beaten"), [1.0, 2.0, 2.0])
        self.assertEqual(self.kpi(track, "envs_beaten")["values"][0]["of"], 3)
        self.assertEqual(self.kpi(track, "envs_beaten")["target"]["kind"], "scope")
        self.assertEqual(track["north_star"], "envs_beaten")
        mujoco = self.kpi(track, "mujoco_beaten")["values"]
        self.assertEqual([v["value"] for v in mujoco], [None, 1.0, 1.0])
        self.assertFalse(mujoco[0]["measured"])
        self.assertTrue(mujoco[0]["note"])
        self.assertIn("stage1", mujoco[1]["note"])

    def test_missing_is_null_with_a_note_never_zero(self) -> None:
        track = self.build()
        for point in self.kpi(track, "dataset_ap")["values"]:
            self.assertIsNone(point["value"])
            self.assertFalse(point["measured"])
            self.assertIn("no graspnet1b/seen/realsense row", point["note"])
        self.assertEqual(self.kpi(track, "dataset_ap")["target"]["value"], 75.2)
        self.assertEqual(self.kpi(track, "dataset_ap")["status"]["word"], "not measured yet")

    def test_hardest_env_lb_and_margin(self) -> None:
        track = self.build()
        # hardest gated env = mujoco/stage1. The best non-privileged headline is the smoke (1.0, LB 0.95).
        lb = self.kpi(track, "hardest_lb")
        self.assertEqual([v["value"] for v in lb["values"]], [None, 95.0, 95.0])
        self.assertEqual(lb["target"]["gate"], 93.0)
        self.assertEqual(lb["values"][1]["n"], 20)
        margin = self.kpi(track, "hardest_margin")["values"]
        self.assertEqual(margin[1]["value"], 98.0)       # bandit 100 % - uniform 2 %
        self.assertIn("oracle M1.oracle", margin[1]["note"])

    def test_cells_latency_seeds_and_dirty(self) -> None:
        track = self.build()
        self.assertEqual(self.series(track, "wave1_cells"), [3.0, 7.0, 7.0])   # the stage1 smoke is not frozen
        self.assertIn("1 more measured only off the frozen protocol", self.kpi(track, "wave1_cells")["values"][1]["note"])
        latency = self.kpi(track, "latency_p95")
        self.assertEqual(latency["values"][1]["value"], 1500.0)
        self.assertEqual(latency["status"]["tone"], "warn")
        self.assertEqual(latency["target"], {"value": 1000.0, "kind": "limit", "label": "< 1 s (Zach's deck; BAM KPIs)"})
        seeds = self.kpi(track, "seed_rule")
        self.assertEqual([(v["value"], v["of"]) for v in seeds["values"]], [(0.0, 1), (0.0, 1), (0.0, 1)])
        self.assertEqual(seeds["status"]["word"], "unconfirmed · repeat needed")
        self.assertEqual(self.series(track, "dirty_share"), [0.0, 37.5, 33.3])

    def test_values_carry_evidence_from_their_own_phase(self) -> None:
        track = self.build()
        items = {item["id"]: item for items in track["evidence"]["by_iteration"].values() for item in items}
        stage0 = items["2026-10-05T02:00:00+00:00_M3.bandit_mujoco/stage0"]
        self.assertEqual(stage0["status"], "pass")
        self.assertEqual(items["2026-10-05T02:00:02+00:00_M3.bandit_mujoco/stage1"]["status"], "provisional")
        self.assertEqual(items["2026-10-05T02:00:03+00:00_M1.oracle_mujoco/stage1"]["status"],
                         "privileged (cannot beat an env)")
        for kpi in track["kpis"]:
            for point in kpi["values"]:
                for evidence_id in point["evidence"]:
                    self.assertEqual(items[evidence_id]["iteration"], point["iteration"])

    def test_state_summary_and_needs(self) -> None:
        track = self.build()
        self.assertEqual(track["state"]["word"], "Tier 2 · MuJoCo physics")
        self.assertIn("1 of 2 gates cleared (open: stage1)", track["state"]["detail"])
        self.assertIn("1 unreadable ledger lines skipped", track["state"]["detail"])
        self.assertEqual(track["state"]["since"], "2026-10-05T02:00:00+00:00")
        self.assertTrue(track["summary"].startswith("2 of 3 gated envs beaten (toy 1/1, MuJoCo 1/2)"))
        self.assertEqual([n["id"] for n in track["needs_you"]], ["grasping:download:M5.ggcnn"])
        self.assertEqual(track["needs_you"][0]["blocks"], ["M5.ggcnn@toy/x", "M5.ggcnn@mujoco/stage0"])
        self.assertIn("BSD-3", track["needs_you"][0]["q"])
        notes = [item for item in track["evidence"]["by_iteration"]["T1-s1"] if item["id"] == "grasping:blocked-cells"]
        self.assertEqual(notes[0]["metrics"], {"kinsim: grasp_command": 1})

    def test_media_only_for_files_that_exist(self) -> None:
        self.assertNotIn("media", self.build())
        (self.out / "gallery.html").write_text("<html></html>", encoding="utf-8")
        track = self.build()
        self.assertEqual(list(track["media"]), ["grasping:gallery"])
        self.assertEqual(track["media"]["grasping:gallery"]["bytes"], 13)
        self.assertEqual(track["links"][0], {"label": "Grasp bench gallery", "kind": "media", "media": "grasping:gallery"})

    def test_gallery_is_linked_only_from_the_declared_out_dir(self) -> None:
        (self.out / "gallery.html").write_text("<html></html>", encoding="utf-8")
        del self.sources["grasping_out_dir"]
        self.assertNotIn("media", self.build())  # never found beside the ledger: the build would not see it change

    def test_the_rung_is_the_frontier_tier_not_the_latest_phase(self) -> None:
        track = self.build()
        # The newest phase is "T1 · seed 1" (a re-run of tier 1); the loop stands at tier 2, whose stage1 is still open.
        self.assertEqual(track["iteration"]["label"], "T1 · seed 1")
        self.assertEqual(track["rung"]["current"], "Tier 2 · MuJoCo physics")
        self.assertEqual(track["rung"]["current"], track["state"]["word"])
        self.assertTrue(track["rung"]["source"].startswith("curriculum.py"))
        self.assertEqual(base.problems(track), [])

    def test_human_times_are_local_with_a_zone(self) -> None:
        self.assertRegex(self.build()["state"]["detail"],
                         r"last run started \d\d-\d\d \d\d:\d\d [A-Z]{3,4} · ledger written \d\d-\d\d \d\d:\d\d [A-Z]{3,4}")

    def test_missing_ledger_is_not_reporting(self) -> None:
        self.ledger.unlink()
        track = grasping.build_track(work_track(), self.sources)
        self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
        self.assertIn("ledger missing", track["summary"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})

    def test_empty_ledger_reports_no_runs(self) -> None:
        self.ledger.write_text("", encoding="utf-8")
        track = self.build()
        self.assertEqual(track["iterations"], [])
        self.assertEqual(track["state"]["word"], "No runs yet")

    def test_changed_contract_fails_loudly(self) -> None:
        self.curriculum.write_text(CURRICULUM.replace('"jaw"),', '"jaw", colour="red"),', 1), encoding="utf-8")
        with self.assertRaises(TypeError):
            grasping.build_track(work_track(), self.sources)


LIVE = load_sources()
LIVE_LEDGER = Path(LIVE.get("grasping_ledger", "/nonexistent"))
LIVE_CURRICULUM = Path(LIVE.get("grasping_curriculum", "/nonexistent"))


@unittest.skipUnless(LIVE_LEDGER.is_file() and LIVE_CURRICULUM.is_file(), f"grasp bench not on this machine: {LIVE_LEDGER}")
class LiveSmokeTest(unittest.TestCase):
    def test_live_ledger_builds_and_agrees_with_the_bench_gallery(self) -> None:
        track = grasping.build_track(work_track(), {"grasping_ledger": str(LIVE_LEDGER),
                                                     "grasping_curriculum": str(LIVE_CURRICULUM)})
        self.assertEqual(base.problems(track), [])
        self.assertTrue(track["iterations"])
        self.assertGreaterEqual(len(track["kpis"]), 4)
        beaten_series = [v["value"] for v in next(k for k in track["kpis"] if k["id"] == "envs_beaten")["values"]]
        self.assertTrue(all(v is not None for v in beaten_series))
        # Independent oracle: the bench's own gallery.env_verdict, run in the bench's own venv.
        bench = LIVE_CURRICULUM.parent.parent.parent
        python = bench / ".venv" / "bin" / "python"
        if not python.is_file():
            self.skipTest(f"bench venv missing: {python}")
        script = ("import json\nfrom grasp_bench import gallery, curriculum\nfrom grasp_bench.ledger import Ledger\n"
                  "heads = gallery.headline_runs(Ledger().load_runs())\n"
                  "print(json.dumps(sorted(e for e in curriculum.GATES if gallery.env_verdict(e, heads)[0])))\n")
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        try:
            out = subprocess.run([str(python), "-c", script], cwd=bench, capture_output=True, text=True, timeout=120,
                                 env=env, check=True).stdout
        except (OSError, subprocess.SubprocessError) as error:
            self.skipTest(f"bench gallery did not run: {error}")
        gallery_beaten = json.loads(out.strip().splitlines()[-1])
        # Recompute from the same ledger state the oracle just read (the ledger may have grown since the build).
        cur = grasping.load_curriculum(LIVE_CURRICULUM)
        runs, _ = grasping.load_ledger(LIVE_LEDGER)
        self.assertEqual(sorted(grasping.snapshot(runs, cur).beaten), gallery_beaten)


if __name__ == "__main__":
    unittest.main()
