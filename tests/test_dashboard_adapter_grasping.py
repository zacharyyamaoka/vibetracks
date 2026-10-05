"""The grasping adapter against small temp fixtures, plus one live smoke test against the bench's real ledger.

    cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_adapter_grasping.py

The adapter no longer decides any verdict: grasp_bench_bridge runs the bench's own gallery.py. So the fixture tests
hand it a FAKE bridge (no bench venv needed) whose verdict table is written out by hand below, one row per rule: a
frozen run that clears its gate (beaten), a smoke run that clears it (provisional, not beaten), an oracle that clears
it (cannot beat an env), a floor below gate, a second training seed (its own phase), and a "needs" cell that asks for a
download approval. The fake also asserts the adapter asks for exactly the cumulative phase subsets. The live test
checks the real bridge's answer against the bench's gallery run independently.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard import registry
from vibetracks.benches import grasp_bench_bridge
from vibetracks.dashboard.adapters import base, grasping
from vibetracks.dashboard.registry import WorkTrack
from vibetracks.sources import load_sources

REPO = Path(__file__).resolve().parents[1]

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


#: The fixture's frozen protocols (test data only; the adapter has no copy of the bench's table any more).
FROZEN = {"toy": ("eval-2000", 2000), "mujoco": ("eval-200", 200)}


def row(model: str, env: str, tier: int, value: float, ci_lo: float, *, started: str, protocol: str | None = None,
        episodes: int | None = None, seed: int | None = None, dirty: bool = False, p95: float = 5.0,
        input_: str = "rgb") -> dict:
    name, default_n = FROZEN[env.split("/", 1)[0]]
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


def _rid(index: int) -> str:
    return ROWS[index]["run_id"]


#: The bench's verdict over ROWS, written out by hand (what gallery.py says under its rules): per run
#: (frozen, privileged, clears_gate, provenance_gap). Row 5 is the 20-episode smoke: it clears the gate, unfrozen.
JUDGED = {0: (True, False, True, ""), 1: (True, True, False, ""), 2: (True, False, False, ""),
          3: (True, False, True, ""), 4: (True, False, False, ""), 5: (False, False, True, ""),
          6: (True, True, False, ""), 7: (True, False, False, ""), 8: (True, False, True, "")}
#: Per phase: the head run of each cell, and per gated env (beaten, provisional, best non-privileged headline).
PHASES = {
    "T1": {"rows": [0, 1, 2], "heads": [0, 1, 2],
           "envs": {"toy/x": (True, False, 0), "mujoco/stage0": (False, False, None), "mujoco/stage1": (False, False, None)}},
    "T2": {"rows": list(range(8)), "heads": list(range(8)),
           "envs": {"toy/x": (True, False, 0), "mujoco/stage0": (True, False, 3), "mujoco/stage1": (False, True, 5)}},
    "T1-s1": {"rows": list(range(9)), "heads": [8, 1, 2, 3, 4, 5, 6, 7],
              "envs": {"toy/x": (True, False, 8), "mujoco/stage0": (True, False, 3), "mujoco/stage1": (False, True, 5)}},
}


def _brief(index: int | None) -> dict | None:
    if index is None:
        return None
    r = ROWS[index]
    return {"run_id": r["run_id"], "cell_id": r["cell_id"], "model": r["model"], "env": r["env"], "value": r["value"],
            "ci_lo": r["ci_lo"], "n": r["n"], "started_at": r["started_at"], "frozen": JUDGED[index][0],
            "privileged": JUDGED[index][1]}


def fixture_doc() -> dict:
    return {
        "schema": grasp_bench_bridge.SCHEMA, "modules": {}, "attestations_path": "", "ledger_rows": len(ROWS),
        "duplicate_run_ids": [], "gated": ["toy/x", "mujoco/stage0", "mujoco/stage1"],
        "runs": {_rid(i): {"frozen": f, "privileged": p, "clears_gate": c, "provenance_gap": g, "schema_version": 2}
                 for i, (f, p, c, g) in JUDGED.items()},
        "snapshots": {pid: {"heads": {ROWS[i]["cell_id"]: _brief(i) for i in spec["heads"]}, "missing": [],
                            "envs": {env: {"beaten": b, "provisional": pv, "best_run": _brief(best)}
                                     for env, (b, pv, best) in spec["envs"].items()}}
                      for pid, spec in PHASES.items()},
    }


class FakeBridge:
    """Stands in for grasp_bench_bridge.bench_verdict: a canned verdict, or a canned reason it is unavailable."""

    def __init__(self, test: unittest.TestCase, reason: str | None = None) -> None:
        self.test, self.reason, self.calls = test, reason, []

    def __call__(self, paths: grasp_bench_bridge.BenchPaths, subsets: dict) -> grasp_bench_bridge.BridgeResult:
        self.calls.append(subsets)
        if self.reason is not None:
            return grasp_bench_bridge.BridgeResult(None, self.reason, seconds=0.0)
        # The adapter must ask the bench about exactly the cumulative rows of each phase.
        self.test.assertEqual(subsets, {pid: [_rid(i) for i in spec["rows"]] for pid, spec in PHASES.items()})
        return grasp_bench_bridge.BridgeResult(fixture_doc(), seconds=0.0, run_seconds=0.0)


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

    def build(self, bridge: FakeBridge | None = None) -> dict:
        self.bridge = bridge or FakeBridge(self)
        track = grasping.build_track(work_track(), self.sources, bridge=self.bridge)
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

    def test_beaten_is_the_bench_verdict(self) -> None:
        track = self.build()
        # toy/x by the learner; stage0 on the frozen protocol. stage1: the smoke is provisional and the oracle cannot beat.
        self.assertEqual(self.series(track, "envs_beaten"), [1.0, 2.0, 2.0])
        self.assertEqual(self.kpi(track, "envs_beaten")["values"][1]["note"], "beaten: x, stage0 · provisional: stage1")
        self.assertTrue(track["source"]["bench_verdict"]["ok"])
        self.assertEqual(track["source"]["problems"], ["1 unreadable ledger lines skipped"])
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
        self.assertIn("1 of 2 gates beaten (open: stage1)", track["state"]["detail"])
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
        track = grasping.build_track(work_track(), self.sources, bridge=FakeBridge(self))
        self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
        self.assertIn("ledger missing", track["summary"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})

    def test_empty_ledger_reports_no_runs(self) -> None:
        self.ledger.write_text("", encoding="utf-8")
        track = self.build()
        self.assertEqual(track["iterations"], [])
        self.assertEqual(track["state"]["word"], "No runs yet")
        self.assertEqual(self.bridge.calls, [])   # nothing to judge, so the bench is not asked

    def test_changed_contract_fails_loudly(self) -> None:
        self.curriculum.write_text(CURRICULUM.replace('"jaw"),', '"jaw", colour="red"),', 1), encoding="utf-8")
        with self.assertRaises(TypeError):
            grasping.build_track(work_track(), self.sources, bridge=FakeBridge(self))

    # ---- no bench verdict: never a replica, always the reason

    def test_unavailable_verdict_is_null_with_the_reason_never_a_guess(self) -> None:
        reason = "bench venv missing: /nowhere/.venv/bin/python"
        track = self.build(FakeBridge(self, reason))
        north = self.kpi(track, track["north_star"])
        self.assertEqual(track["north_star"], "envs_beaten")
        for point in north["values"]:
            self.assertIsNone(point["value"])
            self.assertFalse(point["measured"])
            self.assertEqual(point["note"], f"bench verdict unavailable: {reason}")
        self.assertEqual(north["status"], {"word": "bench verdict unavailable", "tone": "warn"})
        self.assertIn(f"bench verdict unavailable: {reason}", track["source"]["problems"])
        self.assertFalse(track["source"]["bench_verdict"]["ok"])
        for kpi_id in ("mujoco_beaten", "hardest_lb", "hardest_margin", "dataset_ap", "latency_p95", "wave1_cells"):
            kpi = self.kpi(track, kpi_id)
            self.assertEqual([p["note"] for p in kpi["values"]], ["unconfirmed: bench verdict unavailable"] * 3, kpi_id)
            self.assertTrue(all(p["value"] is None for p in kpi["values"]), kpi_id)
            self.assertEqual(kpi["status"]["word"], "unconfirmed: bench verdict unavailable", kpi_id)
        # raw ledger counts need no verdict and stay measured
        self.assertEqual(self.series(track, "dirty_share"), [0.0, 37.5, 33.3])
        self.assertEqual(self.series(track, "seed_rule"), [0.0, 0.0, 0.0])
        # no frontier without the verdict: the state says why, the rung is unknown, nothing claims "beaten"
        self.assertEqual(track["state"]["word"], "Bench verdict unavailable")
        self.assertIn(reason, track["state"]["detail"])
        self.assertIsNone(track["rung"])
        self.assertNotIn("beaten", track["summary"].replace("verdict", ""))
        self.assertTrue(track["summary"].startswith(f"bench verdict unavailable: {reason}"))
        statuses = {item["status"] for items in track["evidence"]["by_iteration"].values() for item in items
                    if item["kind"] == "run"}
        self.assertNotIn("pass", statuses)
        self.assertNotIn("provisional", statuses)

    def test_the_real_bridge_without_a_venv_says_so(self) -> None:
        sources = dict(self.sources, grasping_bench_python=str(self.out / "no-venv" / "python"),
                       grasping_attestations=str(self.ledger.parent / "attestations.jsonl"),
                       grasping_gallery_py=str(self.curriculum), grasping_ledger_py=str(self.curriculum),
                       grasping_runner_py=str(self.curriculum), grasping_contracts_py=str(self.curriculum),
                       grasping_verdict_cache=str(self.out / "cache"))
        track = grasping.build_track(work_track(), sources)   # the real bench_verdict, no fake
        self.assertEqual(base.problems(track), [])
        self.assertEqual(self.kpi(track, "envs_beaten")["values"][-1]["note"],
                         f"bench verdict unavailable: bench venv missing: {self.out / 'no-venv' / 'python'}")
        undeclared = grasping.build_track(work_track(), self.sources)
        self.assertIn("vibe-sources lacks", self.kpi(undeclared, "envs_beaten")["values"][-1]["note"])

    def test_a_verdict_that_misses_rows_is_not_used(self) -> None:
        class Partial(FakeBridge):
            def __call__(self, paths, subsets):
                result = super().__call__(paths, subsets)
                del result.doc["runs"][_rid(8)]
                return result
        track = self.build(Partial(self))
        self.assertIsNone(self.kpi(track, "envs_beaten")["values"][-1]["value"])
        self.assertIn("the bench did not judge 1 ledger rows", track["source"]["problems"][0])


class BridgeTest(unittest.TestCase):
    """grasp_bench_bridge's own seams, with a stand-in interpreter that prints a canned document."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        src = root / "bench" / "src" / "grasp_bench"
        src.mkdir(parents=True)
        self.files = {}
        for name in ("gallery", "ledger", "curriculum", "runner", "contracts"):
            self.files[name] = src / f"{name}.py"
            self.files[name].write_text("# stand-in\n", encoding="utf-8")
        (root / "bench" / "out" / "ledger").mkdir(parents=True)
        self.ledger = root / "bench" / "out" / "ledger" / "runs.jsonl"
        self.ledger.write_text(json.dumps(ROWS[0]) + "\n", encoding="utf-8")
        self.calls = root / "calls.log"
        doc = {"schema": grasp_bench_bridge.SCHEMA,
               "modules": {name: str(path) for name, path in self.files.items()},
               "dependencies": sorted(str(path) for path in self.files.values()),
               "attestations_path": str(self.ledger.parent / "attestations.jsonl"), "runs": {}, "snapshots": {}}
        python = root / "bench" / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        # WHY a shell script: the bridge's contract is "run this interpreter, read the last stdout line"; a stand-in
        # proves caching and checks without the bench's real venv. It logs each call so the cache can be counted.
        python.write_text("#!/bin/sh\ncat >/dev/null\necho call >> " + str(self.calls) + "\necho 'noise'\necho '"
                          + json.dumps(doc) + "'\n", encoding="utf-8")
        python.chmod(0o755)
        self.paths = grasp_bench_bridge.BenchPaths(
            python=str(python), ledger=str(self.ledger), attestations=str(self.ledger.parent / "attestations.jsonl"),
            gallery_py=str(self.files["gallery"]), ledger_py=str(self.files["ledger"]),
            curriculum_py=str(self.files["curriculum"]), runner_py=str(self.files["runner"]),
            contracts_py=str(self.files["contracts"]), cache_dir=str(root / "cache"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ran(self) -> int:
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def test_cached_until_an_input_changes(self) -> None:
        first = grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a"]})
        self.assertTrue(first.ok, first.reason)
        self.assertFalse(first.cached)
        second = grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a"]})
        self.assertTrue(second.cached)
        self.assertEqual(self.ran(), 1)
        for changed in (self.ledger, self.files["gallery"], Path(self.paths.attestations)):
            with open(changed, "a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertFalse(grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a"]}).cached, changed)
        self.assertEqual(self.ran(), 4)
        self.assertFalse(grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a", "b"]}).cached)  # a new request

    def test_a_verdict_without_its_module_list_is_returned_but_never_cached(self) -> None:
        python = Path(self.paths.python)
        python.write_text(python.read_text(encoding="utf-8").replace('"dependencies": ', '"unreported": '),
                          encoding="utf-8")
        first = grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a"]})
        self.assertTrue(first.ok, first.reason)
        self.assertIn("did not report the module files", first.info()["uncached"])
        self.assertFalse(grasp_bench_bridge.bench_verdict(self.paths, {"T1": ["a"]}).cached)
        self.assertEqual(self.ran(), 2)

    def test_a_bench_importing_other_code_is_refused(self) -> None:
        other = Path(self.tmp.name) / "elsewhere.py"
        other.write_text("", encoding="utf-8")
        paths = grasp_bench_bridge.BenchPaths(**{**self.paths.__dict__, "gallery_py": str(other)})
        result = grasp_bench_bridge.bench_verdict(paths, {})
        self.assertFalse(result.ok)
        self.assertIn("imports gallery.py from", result.reason)

    def test_failures_name_the_reason(self) -> None:
        python = Path(self.paths.python)
        python.write_text("#!/bin/sh\necho 'ImportError: no module named grasp_bench' >&2\nexit 1\n", encoding="utf-8")
        result = grasp_bench_bridge.bench_verdict(self.paths, {})
        self.assertEqual(result.reason, "the bench's gallery exited 1: ImportError: no module named grasp_bench")
        python.write_text("#!/bin/sh\nexec sleep 5\n", encoding="utf-8")
        result = grasp_bench_bridge.bench_verdict(self.paths, {}, timeout=0.5)
        self.assertFalse(result.ok)
        self.assertIn("did not answer within", result.reason)


class NoReplicaTest(unittest.TestCase):
    def test_the_gallery_rules_have_no_copy_in_the_dashboard(self) -> None:
        # WHY import-level: the replica drifted once (6 of 10 beaten vs the gallery's 2); none may come back.
        for module in (grasping, grasp_bench_bridge):
            for name in ("is_frozen", "is_frozen_protocol", "is_privileged", "clears_gate", "env_verdict",
                         "env_provisional", "headline_runs", "provenance_gap", "frozen_protocol", "FROZEN_EVAL_SEED",
                         "DEFAULT_PROTOCOLS", "FALLBACK_PROTOCOL"):
                self.assertFalse(hasattr(module, name), f"{module.__name__}.{name} is a copy of the bench's rule")


LIVE = load_sources()
LIVE_TRACK = next((t for t in registry.load_registry(REPO / "workspace") if t.id == "grasping"), None)
LIVE_SOURCES = {key: LIVE[key] for key in (LIVE_TRACK.sources if LIVE_TRACK else []) if key in LIVE}
LIVE_LEDGER = Path(LIVE_SOURCES.get("grasping_ledger", "/nonexistent"))
LIVE_PYTHON = Path(LIVE_SOURCES.get("grasping_bench_python", "/nonexistent"))


@unittest.skipUnless(LIVE_LEDGER.is_file() and LIVE_PYTHON.is_file(), f"grasp bench not on this machine: {LIVE_LEDGER}")
class LiveSmokeTest(unittest.TestCase):
    def test_live_ledger_builds_and_agrees_with_the_bench_gallery(self) -> None:
        track = grasping.build_track(LIVE_TRACK, dict(LIVE_SOURCES))
        self.assertEqual(base.problems(track), [])
        self.assertTrue(track["source"]["bench_verdict"]["ok"], track["source"]["bench_verdict"])
        self.assertTrue(track["iterations"])
        self.assertGreaterEqual(len(track["kpis"]), 4)
        beaten_kpi = next(k for k in track["kpis"] if k["id"] == "envs_beaten")
        self.assertTrue(all(v["value"] is not None for v in beaten_kpi["values"]))
        # Independent oracle: the bench's own gallery.env_verdict in the bench's own venv, written here and not
        # through the bridge, over exactly the rows the adapter read (the ledger may have grown since the build).
        run_ids = [item["id"] for items in track["evidence"]["by_iteration"].values() for item in items
                   if item["kind"] == "run"]
        script = ("import json, sys\nfrom grasp_bench import gallery, curriculum\nfrom grasp_bench.ledger import Ledger\n"
                  "wanted = set(json.load(sys.stdin))\n"
                  f"runs = [r for r in Ledger({str(LIVE_LEDGER.parent)!r}).load_runs() if r.run_id in wanted]\n"
                  "heads = gallery.headline_runs(runs)\n"
                  "print(json.dumps([e for e in curriculum.GATES if gallery.env_verdict(e, heads)[0]]))\n")
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        # WHY fail and never skip from here on (audit 2026-10-04, finding 12): the prerequisites (ledger, venv) are
        # present, so an import error, a nonzero exit or a timeout is the oracle breaking, and a skip would let a warm
        # bridge cache keep this test green while nothing independent checks the north star any more.
        try:
            done = subprocess.run([str(LIVE_PYTHON), "-c", script], cwd=LIVE_PYTHON.parents[2],
                                  input=json.dumps(run_ids), capture_output=True, text=True, timeout=120, env=env,
                                  check=False)
        except (OSError, subprocess.SubprocessError) as error:
            self.fail(f"the bench's own gallery did not run although its venv and ledger exist: {error!r}")
        self.assertEqual(done.returncode, 0, f"the bench's own gallery exited {done.returncode}: {done.stderr}")
        lines = done.stdout.strip().splitlines()
        self.assertTrue(lines, f"the bench's own gallery printed nothing: {done.stderr}")
        gallery_beaten = json.loads(lines[-1])
        last = beaten_kpi["values"][-1]
        self.assertEqual(last["value"], float(len(gallery_beaten)))
        names = [env_id.split("/", 1)[1] for env_id in gallery_beaten]
        expected = ("beaten: " + ", ".join(names)) if names else "none beaten yet"
        self.assertEqual(last["note"].split(" · ")[0], expected)


if __name__ == "__main__":
    unittest.main()
