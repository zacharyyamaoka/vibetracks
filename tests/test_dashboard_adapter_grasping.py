"""The grasping adapter against small temp fixtures, plus one live smoke test against the bench's real ledger.

    cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_adapter_grasping.py

The adapter no longer decides any verdict: grasp_bench_bridge runs the bench's own gallery.py. So the fixture tests
hand it a FAKE bridge (no bench venv needed) whose verdict table is written out by hand below, one row per rule: a
frozen run that clears its gate (beaten), a smoke run that clears it (provisional, not beaten), an oracle that clears
it (cannot beat an env), a floor below gate, a second training seed (its own phase), and a "needs" cell that asks for a
download approval. The fake also asserts the adapter asks for exactly the cumulative phase subsets, named by each
row's line_sha256. RaceTest runs the REAL adapter and the REAL bridge on a verbatim copy of the live bench while a
writer enriches a sparse row between the adapter's read and the bench's (Codex r3 finding 2). The live test checks the
real bridge's answer against the bench's gallery run independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_grasp_bench_bridge_snapshot import ENRICHED, SPARSE, make_real_bench
from vibetracks.dashboard import needs, registry
from vibetracks.benches import grasp_bench_bridge
from vibetracks.dashboard.adapters import base, grasping
from vibetracks.dashboard.registry import WorkTrack
from vibetracks.home import detail
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


def _digest(index: int) -> str:
    """The bridge's line_sha256 of ROWS[index] as the fixture ledger writes it (json.dumps + "\\n")."""
    return hashlib.sha256(json.dumps(ROWS[index]).encode("utf-8")).hexdigest()


def _ref(index: int | None) -> str | None:
    return None if index is None else str(index)


def fixture_doc(present: set[str], subsets: dict) -> dict:
    """grasp-bench-verdict/2 over ROWS, as verdict(subsets=...) prints it; ``present`` = the digests in its snapshot."""

    return {
        "schema": grasp_bench_bridge.VERDICT_SCHEMA, "bench_head": None, "error": None,
        "runs": {str(i): {"frozen": f, "privileged": p, "clears_gate": c, "gap": g, "line_sha256": _digest(i),
                          "env": ROWS[i]["env"], "model": ROWS[i]["model"], "started_at": ROWS[i]["started_at"]}
                 for i, (f, p, c, g) in JUDGED.items() if _digest(i) in present},
        "envs": {env: {"beaten": b, "provisional": pv, "best_run": _ref(best)}
                 for env, (b, pv, best) in PHASES["T1-s1"]["envs"].items()},
        "headline": {ROWS[i]["cell_id"]: str(i) for i in PHASES["T1-s1"]["heads"]},
        "snapshots": {pid: {"headline": {ROWS[i]["cell_id"]: str(i) for i in spec["heads"]},
                            "envs": {env: {"beaten": b, "provisional": pv, "best_run": _ref(best)}
                                     for env, (b, pv, best) in spec["envs"].items()},
                            "missing": sorted(set(subsets.get(pid, [])) - present)}
                      for pid, spec in PHASES.items()},
    }


class FakeBridge:
    """Stands in for grasp_bench_bridge.verdict: a canned verdict over the ledger bytes it finds, or a canned error."""

    def __init__(self, test: unittest.TestCase, reason: str | None = None) -> None:
        self.test, self.reason, self.calls, self.out_dirs = test, reason, [], []

    def __call__(self, bench: Path, *, out_dir: Path, cache_dir: str, subsets: dict, info: dict) -> dict:
        self.calls.append(subsets)
        self.out_dirs.append(out_dir)
        info.update(cached=False, seconds=0.0, bench_seconds=0.0, computed_at=None)
        if self.reason is not None:
            return {"schema": grasp_bench_bridge.VERDICT_SCHEMA, "envs": {}, "runs": {}, "headline": {},
                    "bench_head": None, "error": self.reason}
        # The adapter must ask the bench about exactly the cumulative rows of each phase, named by their digests.
        self.test.assertEqual(subsets, {pid: [_digest(i) for i in spec["rows"]] for pid, spec in PHASES.items()})
        ledger = Path(out_dir) / "ledger" / "runs.jsonl"
        present = {hashlib.sha256(line).hexdigest() for line in ledger.read_bytes().splitlines()}
        return fixture_doc(present, subsets)


def bench_sources(root: Path, out: Path | None = None) -> dict[str, str]:
    """Every sources.py key the adapter declares: the bench's code under ``root``, its data under ``out`` (the out root,
    ``$GRASP_BENCH_OUT``; default ``root/out``, the bench's old in-checkout layout)."""

    code = root / "src" / "grasp_bench"
    out = root / "out" if out is None else out
    return {"grasping_ledger": str(out / "ledger" / "runs.jsonl"),
            "grasping_curriculum": str(code / "curriculum.py"), "grasping_out_dir": str(out),
            "grasping_bench_python": str(root / ".venv" / "bin" / "python"),
            "grasping_attestations": str(out / "ledger" / "attestations.jsonl"),
            "grasping_gallery_py": str(code / "gallery.py"), "grasping_ledger_py": str(code / "ledger.py"),
            "grasping_runner_py": str(code / "runner.py"), "grasping_contracts_py": str(code / "contracts.py"),
            "grasping_bench_src": str(code), "grasping_verdict_cache": str(root / "cache"),
            "grasping_record": str(out / "record" / "report_record_2026-10-06.json"),
            "grasping_rebuild_status": str(out / "loop" / "STATUS.md"),
            "grasping_rebuild_status_json": str(out / "loop" / "status.json"),
            "grasping_roadmap_v4": str(root / "docs" / "grasping" / "roadmap_v4.json")}


def work_track() -> WorkTrack:
    return WorkTrack(id="grasping", title="Grasping", status="running", priority=3, owner=None, adapter="grasping",
                     sources=["grasping_ledger", "grasping_curriculum"], roadmap=None, children=[],
                     note_path="/tmp/grasping.md", revision="r1")


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # WHY the out root apart from the bench (2026-10-10): the bench's data now lives outside its checkout, and the
        # adapter must read the ledger, and have the bench judge it, from there and not from <bench>/out.
        self.out = root / "data" / "grasp_bench" / "out"
        (root / "src" / "grasp_bench").mkdir(parents=True)
        (self.out / "ledger").mkdir(parents=True)
        self.curriculum = root / "src" / "grasp_bench" / "curriculum.py"
        self.curriculum.write_text(CURRICULUM, encoding="utf-8")
        self.ledger = self.out / "ledger" / "runs.jsonl"
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in ROWS) + "not json\n", encoding="utf-8")
        self.root = root
        self.sources = bench_sources(root, self.out)

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
        self.assertEqual(self.bridge.out_dirs, [self.out])   # the bench judged the out root's ledger, not <bench>/out

    def test_each_gated_env_is_a_hard_gate_whose_pass_is_the_bench_verdict(self) -> None:
        track = self.build()
        gates = [k for k in track["kpis"] if (k["target"] or {}).get("kind") == "gate"]
        self.assertEqual([k["id"] for k in gates], ["gate_toy_x", "gate_mujoco_stage0", "gate_mujoco_stage1"])
        verdicts = {k["label"]: detail.gate_verdict(k) for k in gates}
        self.assertEqual({env: v["pass"] for env, v in verdicts.items()},
                         {"toy/x": True, "mujoco/stage0": True, "mujoco/stage1": False})
        # stage1's best run (the 20-episode smoke) has LB 95 >= gate 93: value-against-target would say pass; the bench
        # says provisional, and the page shows the bench's word.
        self.assertEqual(verdicts["mujoco/stage1"]["value"], 95.0)
        self.assertTrue(verdicts["mujoco/stage1"]["why"].startswith("provisional"), verdicts["mujoco/stage1"])
        self.assertTrue(verdicts["toy/x"]["why"].startswith("beaten"))
        stage0 = next(k for k in gates if k["id"] == "gate_mujoco_stage0")
        self.assertEqual([v["value"] for v in stage0["values"]], [None, 93.6, 93.6])
        self.assertNotIn("verdict", stage0["values"][0])   # not in the ledger yet: no verdict claimed for T1
        self.assertEqual(stage0["target"]["gate"], 93.0)

    def test_missing_is_null_with_a_note_never_zero(self) -> None:
        track = self.build()
        for kpi_id, words in (("dataset_ap_graspnet1b", "no graspnet1b/seen/realsense row"),
                              ("dataset_p1_graspnet1b", "no graspnet1b/seen/realsense row with precision_at_1")):
            for point in self.kpi(track, kpi_id)["values"]:
                self.assertIsNone(point["value"])
                self.assertFalse(point["measured"])
                self.assertIn(words, point["note"])
            self.assertEqual(self.kpi(track, kpi_id)["status"]["word"], "not measured yet")
        self.assertEqual(self.kpi(track, "dataset_ap_graspnet1b")["target"]["value"], 75.2)

    def test_tier_best_is_the_best_executed_top1_on_the_tiers_hardest_env(self) -> None:
        track = self.build()
        # The fixture has tiers 1 and 2 only, so there is no sim-camera or claw KPI (never an empty one).
        self.assertEqual([k["id"] for k in track["kpis"] if k["id"].startswith("tier_best_")],
                         ["tier_best_toy", "tier_best_mujoco"])
        # tier 2's hardest env is mujoco/stage1; its best non-privileged headline is the smoke (1.0), not the oracle.
        mujoco = self.kpi(track, "tier_best_mujoco")
        self.assertEqual([v["value"] for v in mujoco["values"]], [None, 100.0, 100.0])
        self.assertIn("M3.bandit 100.0% [95.0, 100.0] on eval-20 (not the frozen protocol)", mujoco["values"][1]["note"])
        self.assertEqual(mujoco["values"][1]["n"], 20)
        self.assertEqual(mujoco["target"]["kind"], "reference")   # its gate is the hard gate, never a second one
        self.assertEqual(self.series(track, "tier_best_toy"), [100.0, 100.0, 100.0])

    def test_cells_latency_seeds_and_dirty(self) -> None:
        track = self.build()
        self.assertEqual(self.series(track, "wave1_cells"), [3.0, 7.0, 7.0])   # the stage1 smoke is not frozen
        self.assertIn("1 more measured only off the frozen protocol", self.kpi(track, "wave1_cells")["values"][1]["note"])
        # decision time is the p95 of the run the tier-best KPI shows, never the slowest floor's (row 7, 1.5 s)
        latency = self.kpi(track, "latency_mujoco")
        self.assertEqual([v["value"] for v in latency["values"]], [None, 5.0, 5.0])
        self.assertEqual(latency["status"], {"word": "within 1 s · 5 ms", "tone": "ok"})
        self.assertEqual(latency["target"], {"value": 1000.0, "kind": "limit", "label": "< 1 s (Zach's deck; BAM KPIs)"})
        self.assertEqual(latency["direction"], "lower")
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
        for kpi_id in ("tier_best_toy", "tier_best_mujoco", "dataset_ap_graspnet1b", "dataset_p1_graspnet1b",
                       "latency_toy", "latency_mujoco", "wave1_cells"):
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
        for gate in (k for k in track["kpis"] if (k["target"] or {}).get("kind") == "gate"):
            self.assertEqual(detail.gate_verdict(gate)["pass"], None, gate["id"])
            self.assertEqual(detail.gate_verdict(gate)["why"], grasping.UNCONFIRMED, gate["id"])

    def test_the_real_bridge_without_a_venv_says_so(self) -> None:
        track = grasping.build_track(work_track(), self.sources)   # the real verdict(), no fake
        self.assertEqual(base.problems(track), [])
        self.assertEqual(self.kpi(track, "envs_beaten")["values"][-1]["note"],
                         f"bench verdict unavailable: bench venv missing: {self.root / '.venv' / 'bin' / 'python'}")
        undeclared = dict(self.sources)
        del undeclared["grasping_bench_src"]
        track = grasping.build_track(work_track(), undeclared)
        self.assertIn("vibe-sources lacks grasping_bench_src", self.kpi(track, "envs_beaten")["values"][-1]["note"])

    def test_a_declared_input_outside_the_bench_is_refused(self) -> None:
        # WHY: verdict() reads the bench's own gallery.py by layout; a declared copy elsewhere would be the file the
        # build watches while the bench decided with another.
        elsewhere = self.root / "elsewhere.py"
        elsewhere.write_text("", encoding="utf-8")
        track = self.build(FakeBridge(self))
        self.assertTrue(track["source"]["bench_verdict"]["ok"])
        track = grasping.build_track(work_track(), dict(self.sources, grasping_gallery_py=str(elsewhere)),
                                     bridge=FakeBridge(self))
        self.assertIn(f"grasping_gallery_py {elsewhere} is not the bench's", track["source"]["problems"][0])
        self.assertIsNone(self.kpi(track, "envs_beaten")["values"][-1]["value"])
        # the attestations the bench reads are the out root's; a declared copy anywhere else is refused the same way
        track = grasping.build_track(work_track(), dict(self.sources, grasping_attestations=str(elsewhere)),
                                     bridge=FakeBridge(self))
        self.assertIn(f"grasping_attestations {elsewhere} is not the bench's {self.out / 'ledger' / 'attestations.jsonl'}",
                      track["source"]["problems"][0])

    def test_a_verdict_that_misses_rows_is_not_used(self) -> None:
        class Partial(FakeBridge):
            def __call__(self, *args, **kwargs):
                doc = super().__call__(*args, **kwargs)
                del doc["runs"]["8"]
                return doc
        bridge = Partial(self)
        track = self.build(bridge)
        self.assertIsNone(self.kpi(track, "envs_beaten")["values"][-1]["value"])
        self.assertIn("the bench did not judge 1 ledger rows", track["source"]["problems"][0])
        # The ledger did not move between the two reads, so this is not "changed during read": the bench is wrong.
        self.assertNotIn(grasping.LEDGER_CHANGED, track["source"]["problems"][0])
        self.assertEqual(len(bridge.calls), 2)

    def test_a_row_replaced_after_the_read_is_re_read_once_then_judged_whole(self) -> None:
        # The fake bench finds the ledger as it is when called. First call: row 8 has been rewritten (a new digest),
        # so the snapshot lacks a row the adapter read and the adapter must read again rather than mix versions.
        original = self.ledger.read_bytes()
        bridge = FakeBridge(self)
        real_call = FakeBridge.__call__
        state = {"calls": 0}

        def racing(fake, bench, **kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                self.ledger.write_bytes(original.replace(b'"tier": 1, "protocol"', b'"tier": 1,  "protocol"', 1))
                doc = real_call(fake, bench, **kwargs)
                self.ledger.write_bytes(original)   # the writer puts it back before the adapter's second read
                return doc
            return real_call(fake, bench, **kwargs)

        with mock.patch.object(FakeBridge, "__call__", racing):
            track = self.build(bridge)
        self.assertEqual(state["calls"], 2)
        self.assertEqual(track["source"]["bench_verdict"]["attempts"], 2)
        self.assertEqual(self.series(track, "envs_beaten"), [1.0, 2.0, 2.0])


def record_run(model: str, env: str, value: float, ci_lo: float | None, *, metric: str = "top1_success",
               headline: bool = True, flags: tuple[str, ...] = (), p1: float | None = None, p95: str = "4.20 ms",
               dirty: bool = False) -> dict:
    """One run of the recovered report record, in report_record_2026-10-06.json's shape."""

    return {"run_id": f"20261006T120000Z_{model}_{env}_{value}", "cell_id": f"{model}@{env}", "model": model, "env": env,
            "metric": metric, "value_text": f"{value}", "value": value, "ci_lo": ci_lo,
            "ci_hi": None if ci_lo is None else min(1.0, value + 0.01) if metric != "ap" else value + 3,
            "n": 200, "latency_p50_text": "1.00 ms", "latency_p95_text": p95, "lost_in_conversion": "0",
            "protocol": "eval-200", "eval_seed": "20261004", "started": "2026-10-06 19:41",
            "git_sha": "747c4fdd dirty" if dirty else "747c4fdd", "flags": list(flags), "precision_at_1": p1,
            "headline": headline}


RECORD = {"source": "/x/grasp-bench-wave1-2026-10-04.html", "note": "fixture", "n_runs": 8, "n_headline_cells": 7,
          "headlines": {}, "runs": [
              record_run("M3.bandit", "toy/x", 1.0, 0.998),
              record_run("M1.oracle", "toy/x", 1.0, 0.999, flags=("privileged",)),
              record_run("M3.bandit", "mujoco/stage1", 0.97, 0.94, p95="12.5 ms", dirty=True),
              # superseded (not the headline): higher, but the report did not show it as the cell's result
              record_run("M0.uniform", "mujoco/stage1", 0.99, 0.98, headline=False, flags=("superseded",)),
              record_run("M0.uniform", "mujoco/stage1", 0.02, 0.01),
              # the dataset: AP best and P@1 best are different models, and must stay two KPIs
              record_run("M3.dense", "graspnet1b/seen/realsense", 34.1, 31.2, metric="ap", p1=0.43),
              record_run("M2.hill", "graspnet1b/seen/realsense", 24.5, 21.0, metric="ap", p1=0.46),
              record_run("M1.oracle", "graspnet1b/seen/realsense", 66.2, 63.3, metric="ap", p1=0.65, flags=("privileged",)),
          ]}
RECORD_ID = "record-2026-10-06"
RECORDED = "recorded Oct 6, not yet re-proved"


class RecordTest(unittest.TestCase):
    """The ledger was deleted with its worktree (Oct 6-10); until the rebuild refills it, the recovered record is shown,
    labelled as recorded and not re-proved, and nothing claims a gate passed or "0 of N beaten"."""

    # FixtureTest's bench and helpers, without re-running its tests here
    tearDown, build, kpi, series = FixtureTest.tearDown, FixtureTest.build, FixtureTest.kpi, FixtureTest.series

    def setUp(self) -> None:
        FixtureTest.setUp(self)
        self.record = self.out / "record" / "report_record_2026-10-06.json"
        self.record.parent.mkdir(parents=True)
        self.record.write_text(json.dumps(RECORD), encoding="utf-8")

    def test_no_ledger_yet_shows_the_record_labelled_and_claims_no_verdict(self) -> None:
        self.ledger.unlink()   # the rebuild has not written ledger/runs.jsonl yet
        track = self.build()
        self.assertEqual(self.bridge.calls, [])   # nothing to judge, so the bench is not asked
        self.assertEqual([i["id"] for i in track["iterations"]], [RECORD_ID])
        self.assertEqual(track["iterations"][0]["label"], "Oct 6 record · not re-proved")
        # the north star stays unmeasured: the record has values, not the bench's verdicts; never "0 of 3 beaten"
        north = self.kpi(track, "envs_beaten")
        self.assertEqual((north["values"][0]["value"], north["values"][0]["measured"]), (None, False))
        self.assertIn(RECORDED, north["values"][0]["note"])
        self.assertEqual(north["status"], {"word": "not yet re-proved", "tone": "muted"})
        self.assertNotRegex(track["summary"], r"\d+ of \d+ gated envs beaten")
        self.assertEqual(track["state"]["word"], "Rebuilding evidence")
        self.assertIn("0 of 7 recorded cells re-run", track["summary"])
        self.assertIn(f"values are the Oct 6 record, not yet re-proved", track["summary"])
        self.assertIsNone(track["rung"])
        # every gate is unknown with the recorded value and its label, never pass on a value nobody re-proved
        for gate in (k for k in track["kpis"] if (k["target"] or {}).get("kind") == "gate"):
            verdict = detail.gate_verdict(gate)
            self.assertIsNone(verdict["pass"], gate["id"])
            self.assertTrue(verdict["why"].startswith(RECORDED) or verdict["why"] == "not measured yet", verdict)
        toy = detail.gate_verdict(self.kpi(track, "gate_toy_x"))
        self.assertEqual((toy["value"], toy["iteration"]), (99.8, RECORD_ID))   # the oracle's 99.9 is privileged
        self.assertEqual(toy["why"], f"{RECORDED} · M3.bandit")
        self.assertIn("M3.bandit Wilson LB 99.8 % on eval-200", self.kpi(track, "gate_toy_x")["values"][0]["note"])
        self.assertEqual(detail.gate_verdict(self.kpi(track, "gate_mujoco_stage0"))["why"], "not measured yet")
        # soft KPIs carry the recorded values with the label as their status
        mujoco = self.kpi(track, "tier_best_mujoco")
        self.assertEqual(self.series(track, "tier_best_mujoco"), [97.0])        # the superseded 99 % is not the headline
        self.assertEqual(mujoco["status"], {"word": RECORDED, "tone": "muted"})
        self.assertTrue(mujoco["values"][0]["note"].startswith(RECORDED))
        self.assertEqual(self.series(track, "latency_mujoco"), [12.5])
        self.assertEqual(self.kpi(track, "latency_mujoco")["status"]["word"], RECORDED)
        # AP and label-judged top-1 are separate KPIs, each its own best, the oracle excluded from both
        self.assertEqual(self.series(track, "dataset_ap_graspnet1b"), [34.1])
        self.assertEqual(self.series(track, "dataset_p1_graspnet1b"), [46.0])
        self.assertEqual(self.series(track, "wave1_cells"), [4.0])
        self.assertEqual(self.series(track, "rebuild_progress"), [0.0])
        self.assertEqual(self.series(track, "dirty_share"), [12.5])
        # every point's evidence is an item of its own column
        items = {item["id"]: item for item in track["evidence"]["by_iteration"][RECORD_ID]}
        self.assertEqual(len([item for item in items.values() if item["kind"] == "run"]), 7)   # the headline runs
        for kpi in track["kpis"]:
            for point in kpi["values"]:
                for evidence_id in point["evidence"]:
                    self.assertEqual(items[evidence_id]["status"], "recorded (not re-proved)")
        self.assertIn({"label": "Recovered record (Oct 6 record)", "kind": "path", "value": str(self.record)},
                      track["links"])

    def test_the_rebuilt_ledger_follows_the_record_and_its_verdict_wins(self) -> None:
        track = self.build()
        self.assertEqual([i["id"] for i in track["iterations"]], [RECORD_ID, "T1", "T2", "T1-s1"])
        self.assertEqual(self.series(track, "envs_beaten"), [None, 1.0, 2.0, 2.0])
        self.assertEqual(self.series(track, "rebuild_progress"), [0.0, 2.0, 4.0, 4.0])
        self.assertEqual(self.kpi(track, "rebuild_progress")["values"][-1]["of"], 7)
        self.assertIn("evidence rebuild: 4 of 7 recorded cells re-run", track["summary"])
        self.assertEqual(track["state"]["word"], "Tier 2 · MuJoCo physics")
        self.assertEqual(detail.gate_verdict(self.kpi(track, "gate_toy_x"))["pass"], True)
        self.assertEqual(self.series(track, "tier_best_mujoco"), [97.0, None, 100.0, 100.0])
        self.assertNotEqual(self.kpi(track, "tier_best_mujoco")["status"]["word"], RECORDED)
        # an env the rebuilt ledger has not reached keeps the record's word, never the bench's empty "not beaten"
        stage0 = self.kpi(track, "gate_mujoco_stage1")
        early = dict(stage0, values=stage0["values"][:2])     # the record, then T1 (no stage1 row yet)
        self.assertEqual(detail.gate_verdict(early)["pass"], None)
        self.assertTrue(detail.gate_verdict(early)["why"].startswith(RECORDED))
        self.assertEqual(base.problems(track), [])

    def test_an_unreadable_record_is_a_named_problem_never_a_crash(self) -> None:
        self.record.write_text("{not json", encoding="utf-8")
        track = self.build()
        self.assertEqual([i["id"] for i in track["iterations"]], ["T1", "T2", "T1-s1"])
        self.assertTrue(any(p.startswith("record unreadable") for p in track["source"]["problems"]))
        self.ledger.unlink()
        track = grasping.build_track(work_track(), self.sources, bridge=FakeBridge(self))
        self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
        self.assertIn("ledger missing", track["summary"])
        self.assertIn("record unreadable", track["summary"])

    def test_the_rebuild_status_file_is_linked_when_the_loop_writes_it(self) -> None:
        self.assertFalse(any(link["label"].startswith("Rebuild status") for link in self.build()["links"]))
        status = self.out / "loop" / "STATUS.md"
        status.parent.mkdir(parents=True)
        status.write_text("# rebuild\n", encoding="utf-8")
        track = self.build()
        self.assertIn({"label": "Rebuild status (loop/STATUS.md)", "kind": "path", "value": str(status)}, track["links"])
        self.assertIn("loop/STATUS.md written", self.kpi(track, "rebuild_progress")["status"]["word"])

    def test_the_lane_is_named_when_the_bench_code_sits_in_an_agent_worktree(self) -> None:
        self.assertIsNone(grasping.bench_lane(self.root))
        lane = grasping.bench_lane(Path("/home/bam/bam_ws/.claude/worktrees/grasping-evidence-rebuild-cb787d/src/core/"
                                        "mdp/agent/actor/policy/grasp_bench"))
        self.assertEqual(lane, "bench code lives on an agent lane (worktree grasping-evidence-rebuild-cb787d), "
                               "not on bam_ws main")


def rung_(rung_id: str, status: str, title: str = "a rung", display: str | None = None) -> dict:
    return {"id": rung_id, "title": title, "comparison": "harness", "done_when": [f"{rung_id} clause one", "clause two"],
            "metric": "AP", "threshold": {}, "status": status, "current": {"display": display}, "gap": "far",
            "depends_on": [], "needs": []}


#: grasp-roadmap/1 in the shape of docs/grasping/roadmap_v4.json (work order v4 section 6), trimmed to what is read.
ROADMAP = {
    "schema": "grasp-roadmap/1", "track": "grasping", "generated_at": "2026-10-10T16:30:00-07:00",
    "as_of": {"evidence": "record", "note": "Values come from the record recovered from the Oct 6 report."},
    "milestones": [
        {"id": "REAL-4DOF", "order": 2, "title": "4-DoF grasping in real life", "done_rung": "REAL-4DOF.b",
         "status": "missing", "blocked_by": ["rig:T17 arm mechanical support"], "owner": "rig",
         "current": {"value": 0, "display": "0 verified real picks", "source": "KPI note S1", "as_of": "2026-10-10"},
         "rungs": [rung_("REAL-4DOF.a", "missing", "First verified real pick"), rung_("REAL-4DOF.b", "missing", "Done")]},
        {"id": "GN1B-6DOF", "order": 1, "title": "6-DoF grasping on GraspNet-1Billion", "done_rung": "GN1B-6DOF.c",
         "status": "partial", "blocked_by": ["needs_you:D1 downloads"], "unknown_field": {"ignored": True},
         "current": {"value": 34.1, "display": "AP 34.1 (4-DoF height-only net)", "source": "record_2026-10-06",
                     "as_of": "2026-10-05", "comparable_to_published": False},
         "rungs": [rung_("GN1B-6DOF.a", "green", "Harness calibrated"), rung_("GN1B-6DOF.b", "partial", "6-DoF on the board",
                                                                              "AP 20.7"),
                   rung_("GN1B-6DOF.c", "missing", "At the frontier")]},
    ],
    "model_queue": [{"order": 1, "id": "Q0", "title": "diagnostics", "status": "ready", "unlocks": ["GN1B-6DOF.a"]},
                    {"order": 2, "id": "Q5", "title": "retrain", "status": "later"},
                    {"order": 3, "id": "Q1", "title": "CUDA build", "status": "needs_download"},
                    {"order": 4, "id": "Q10", "title": "watch list", "status": None},
                    {"order": 5, "id": "Q2", "title": "EconomicGrasp", "status": "needs_download"},
                    {"order": 6, "id": "Q3", "title": "graspnet-baseline", "status": "needs_download"}],
    "env_queue": [{"order": 1, "id": "E1", "title": "kinect envs", "status": "ready", "unlocks": ["GN1B-6DOF.b"]},
                  {"order": 2, "id": "E9", "title": "real/pick", "status": "blocked"}],
    "needs_you": [{"id": f"D{i}", "q": f"question {i}", "blocks": ["GN1B-6DOF.a"], "default": f"default {i}",
                   "applies": "now"} for i in range(1, 5)],
}


def rebuild_status(**overrides) -> dict:
    doc = {"schema": "grasp-bench-rebuild-status/1", "code_sha": "c299cd83", "started": "2026-10-10T15:00:00-07:00",
           "updated": "2026-10-10T17:05:00-07:00",
           "current": {"step": "B", "cell": "M3.dense@toy/xy_rz", "seed": 1, "started": "2026-10-10T17:00:00-07:00"},
           "steps": [{"step": "A", "title": "floors", "cells_total": 20, "cells_done": 20, "state": "done", "eta": None},
                     {"step": "B", "title": "toy learners", "cells_total": 30, "cells_done": 12, "state": "running",
                      "eta": "2026-10-10T19:40:00-07:00"},
                     {"step": "C", "title": "MuJoCo", "cells_total": 40, "cells_done": 0, "state": "queued",
                      "eta": "2026-10-11T06:00:00-07:00"}],
           "failures": []}
    doc.update(overrides)
    return doc


class MilestonesAndStatusTest(unittest.TestCase):
    """roadmap_v4.json's four-milestone ladder and loop/status.json's rebuild progress, read as the loop wrote them."""

    tearDown, build, kpi, series = FixtureTest.tearDown, FixtureTest.build, FixtureTest.kpi, FixtureTest.series

    def setUp(self) -> None:
        FixtureTest.setUp(self)
        self.roadmap = Path(self.sources["grasping_roadmap_v4"])
        self.roadmap.parent.mkdir(parents=True)
        self.roadmap.write_text(json.dumps(ROADMAP), encoding="utf-8")
        self.status = Path(self.sources["grasping_rebuild_status_json"])
        self.status.parent.mkdir(parents=True)
        self.record = self.out / "record" / "report_record_2026-10-06.json"
        self.record.parent.mkdir(parents=True)
        self.record.write_text(json.dumps(RECORD), encoding="utf-8")

    def test_the_milestone_ladder_is_the_files_own_words_in_order(self) -> None:
        ms = self.build()["milestones"]
        self.assertEqual([m["id"] for m in ms["items"]], ["GN1B-6DOF", "REAL-4DOF"])   # by order, not file position
        gn = ms["items"][0]
        self.assertEqual(gn["rung"]["id"], "GN1B-6DOF.b")       # the first rung not green: a is green, b partial
        self.assertEqual(gn["rung"]["today"], "AP 20.7")
        self.assertEqual(gn["today"]["display"], "AP 34.1 (4-DoF height-only net)")
        self.assertEqual(gn["today"]["label"], "recorded 2026-10-05, not yet re-proved")   # never shown as live
        self.assertFalse(gn["today"]["comparable_to_published"])
        self.assertEqual((gn["bar"]["rung"], gn["bar"]["title"]), ("GN1B-6DOF.c", "At the frontier"))
        self.assertEqual(gn["bar"]["done_when"], ["GN1B-6DOF.c clause one", "clause two"])
        self.assertEqual(gn["blocked_by"], ["needs_you:D1 downloads"])
        self.assertNotIn("unknown_field", gn)
        self.assertEqual([r["status"] for r in gn["rungs"]], ["green", "partial", "missing"])
        # a value that does not come from the record is never labelled as recorded, even in a record-era file
        self.assertEqual(ms["items"][1]["today"]["label"], "as of 2026-10-10")
        # S7: at most three decisions, the rest counted; the queues' next three, skipping "later" and watch items
        self.assertEqual([n["id"] for n in ms["needs_you"]], ["D1", "D2", "D3"])
        self.assertEqual(ms["needs_you_total"], 4)
        self.assertEqual(ms["needs_you"][0]["default"], "default 1")
        self.assertEqual([q["id"] for q in ms["model_queue"]], ["Q0", "Q1", "Q2"])
        self.assertEqual([q["id"] for q in ms["env_queue"]], ["E1", "E9"])
        self.assertEqual(ms["source"], str(self.roadmap))

    def test_the_track_page_document_carries_the_ladder(self) -> None:
        track = self.build()
        projected = dict(track, reporting=True)
        doc = {"projects": [{"id": "bam", "name": "BAM Robotics", "tracks": [{"id": "grasping", "provenance": {}}]}]}
        last = {"now": 1760140800.0, "records": {}, "projected": {"grasping": projected}, "needs": {}}
        page = detail.build_track(doc, last, "grasping")
        self.assertEqual(page["milestones"], track["milestones"])
        self.assertIsNone(detail.build_track(doc, dict(last, projected={"grasping": dict(projected, reporting=False)}),
                                             "grasping")["milestones"])

    def test_no_roadmap_file_means_no_ladder_and_a_bad_one_is_a_named_problem(self) -> None:
        self.roadmap.unlink()
        self.assertNotIn("milestones", self.build())
        self.roadmap.write_text(json.dumps({"schema": "bam-roadmap/1"}), encoding="utf-8")
        track = self.build()
        self.assertNotIn("milestones", track)
        self.assertTrue(any("roadmap_v4.json is not grasp-roadmap/1" in p for p in track["source"]["problems"]))

    def test_needs_you_is_the_roadmaps_decisions_at_most_three(self) -> None:
        # WHY (coordinator, 2026-10-10): the eight per-model download cells are one question, D1; S7 shows <= 3
        roadmap = json.loads(json.dumps(ROADMAP))
        roadmap["needs_you"][1]["blocks"] = ["every milestone"]
        roadmap["needs_you"][2]["default"] = None
        self.roadmap.write_text(json.dumps(roadmap), encoding="utf-8")
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        self.assertEqual(doc["source"]["adapter"], "grasp_roadmap")
        self.assertIn("1 more wait in the file", doc["source"]["note"])
        items = {item["local_id"]: item for item in doc["items"]}
        self.assertEqual(set(items), {"D1", "D2", "D3"})
        self.assertEqual(items["D1"]["ask"], "question 1")                       # the file's own words
        self.assertEqual(items["D1"]["default"]["text_md"], "default 1")
        self.assertTrue(items["D1"]["blocking_now"])                              # names a rung of the file
        self.assertEqual(items["D2"]["blocks"], [{"id": "every milestone", "kind": "note", "label": None}])
        self.assertFalse(items["D2"]["blocking_now"])                             # free words never block alone
        self.assertEqual(items["D3"]["group"], "blocking")
        self.assertEqual((doc["counts"]["open"], doc["counts"]["blocking_now"]), (3, 2))
        self.assertIn("D1/D2/D3", doc["answer_channel"]["read_back"])
        self.assertEqual([n["id"] for n in self.build()["needs_you"]], ["D1", "D2", "D3"])
        self.assertIn("3 decisions open (roadmap_v4.json)", self.build()["summary"])

    def test_needs_fall_back_to_the_curriculum_only_when_the_roadmap_is_missing(self) -> None:
        self.roadmap.unlink()
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        self.assertEqual(doc["source"]["adapter"], "grasp_curriculum")
        self.assertEqual([item["local_id"] for item in doc["items"]], ["M5.ggcnn"])
        self.assertIn("name model ids verbatim", doc["answer_channel"]["read_back"])
        self.assertEqual([n["id"] for n in self.build()["needs_you"]], ["grasping:download:M5.ggcnn"])
        # an unreadable roadmap is a stated reason with unknown counts, never a silent return to the old questions
        self.roadmap.write_text("{torn", encoding="utf-8")
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        self.assertEqual((doc["source"]["adapter"], doc["items"]), ("grasp_roadmap", []))
        self.assertIn("roadmap_v4.json unreadable", doc["source"]["note"])
        self.assertIsNone(doc["counts"]["open"])

    def test_status_json_drives_the_latest_rebuild_reading(self) -> None:
        self.status.write_text(json.dumps(rebuild_status()), encoding="utf-8")
        track = self.build()
        kpi = self.kpi(track, "rebuild_progress")
        last = kpi["values"][-1]
        self.assertEqual((last["value"], last["of"]), (32.0, 90))
        self.assertIn("step B (toy learners) · M3.dense@toy/xy_rz seed 1", last["note"])
        eta = base.local_time("2026-10-10T19:40:00-07:00")   # the current step's ETA, in local time with its zone
        self.assertIn(f"ETA {eta}", last["note"])
        self.assertEqual(kpi["status"]["word"], f"32 of 90 cells · step B (toy learners) · M3.dense@toy/xy_rz seed 1 · "
                                                f"ETA {eta}")
        self.assertEqual(kpi["target"]["label"], "of 90 cells in the rebuild plan")
        # the earlier columns keep the ledger-vs-record count they were
        self.assertEqual([v["value"] for v in kpi["values"][:-1]], [0.0, 2.0, 4.0])
        self.assertIn("32 of 90 cells (loop/status.json)", track["summary"])
        self.assertIn({"label": "Rebuild status (loop/status.json)", "kind": "path", "value": str(self.status)},
                      track["links"])
        self.assertEqual(base.problems(track), [])

    def test_status_json_with_no_ledger_yet_and_with_failures(self) -> None:
        self.ledger.unlink()
        self.status.write_text(json.dumps(rebuild_status(current=None, failures=[{"cell": "M3.x@toy/x", "reason": "OOM"}])),
                               encoding="utf-8")
        track = self.build()
        kpi = self.kpi(track, "rebuild_progress")
        self.assertEqual([(v["iteration"], v["value"]) for v in kpi["values"]], [(RECORD_ID, 32.0)])
        self.assertEqual(kpi["status"]["tone"], "warn")
        self.assertIn("no step running", kpi["status"]["word"])
        # a cell id that already names its seed is not given it twice (L1 writes "M3.dense@toy/x [seed 20261004]")
        status = grasping.RebuildStatus(path="x", updated=None, steps=[], failures=[],
                                        current={"step": 2, "cell": "M3.dense@toy/x [seed 20261004]", "seed": 20261004})
        self.assertEqual(status.where(), "step 2 · M3.dense@toy/x [seed 20261004]")
        self.assertIn(f"ETA {base.local_time('2026-10-10T19:40:00-07:00')}", kpi["status"]["word"])   # first unfinished
        self.assertIn("1 failed cells", kpi["values"][-1]["note"])

    def test_without_or_with_a_bad_status_json_the_ledger_vs_record_count_stands(self) -> None:
        self.assertEqual(self.series(self.build(), "rebuild_progress"), [0.0, 2.0, 4.0, 4.0])
        for bad in ({"schema": "other/1"}, rebuild_status(steps=[{"step": "A", "cells_total": "20", "cells_done": 1}])):
            self.status.write_text(json.dumps(bad), encoding="utf-8")
            track = self.build()
            self.assertEqual(self.series(track, "rebuild_progress"), [0.0, 2.0, 4.0, 4.0])
            self.assertTrue(any(p.startswith("loop/status.json") for p in track["source"]["problems"]), track["source"])
        self.status.write_text("{torn", encoding="utf-8")
        self.assertTrue(any("loop/status.json unreadable" in p for p in self.build()["source"]["problems"]))


#: True when every run row the page shows as clearing a gate carries the measurements that clearing needs.
def gate_claims_have_measurements(test: unittest.TestCase, track: dict) -> None:
    runs = [item for items in track["evidence"]["by_iteration"].values() for item in items if item["kind"] == "run"]
    for item in runs:
        if item["status"] in ("pass", "provisional"):
            test.assertIsNotNone(item["metrics"].get("top-1 (%)"), item)
            test.assertIsNotNone(item["metrics"].get("Wilson LB (%)"), item)
    for point in next(k for k in track["kpis"] if k["id"] == "envs_beaten")["values"]:
        if point["measured"] and point["value"]:
            beaten = [item for item in runs if item["status"] == "pass" and item["id"] in point["evidence"]]
            test.assertTrue(beaten, f"{point['value']} beaten with no passing run row beside it: {point}")


# WHY from the sources map and not a pinned path: the pinned worktree (grasping-agent-roadmap-ab12d8) was swept on
# Oct 6-10 and every live check here skipped silently; the map is what the dashboard itself reads.
LIVE_BENCH = Path(load_sources()["grasping_bench_dir"])


@unittest.skipUnless((LIVE_BENCH / ".venv" / "bin" / "python").exists(), f"no bench venv at {LIVE_BENCH}")
class RaceTest(unittest.TestCase):
    """Codex r3 finding 2 through the REAL adapter and the REAL bridge, on a verbatim copy of the live bench.

    The ledger holds one legacy sparse row (no value, no ci_lo); its enriched form clears toy/x on the frozen protocol.
    A writer swaps one form for the other just before the bench's subprocess starts, i.e. between the adapter's read and
    the bench's. On e0bd8e5 the adapter showed the sparse row (no Top-1, no Wilson LB) beside the bench's "toy/x
    beaten" for the enriched one. The page may show either version, or no verdict, but never one beside the other.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bench = make_real_bench(Path(self.tmp.name) / "bench")
        self.sources = bench_sources(self.bench)
        self.ledger = Path(self.sources["grasping_ledger"])
        self.sparse = json.dumps(SPARSE).encode("utf-8") + b"\n"
        self.enriched = json.dumps(ENRICHED).encode("utf-8") + b"\n"
        self.ledger.write_bytes(self.sparse)
        self.real_run = subprocess.run

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self, rewrite) -> dict:
        """build_track with ``rewrite(call_number)`` run just before each bench subprocess (git calls untouched)."""

        calls = {"n": 0}

        def writer(args, *rest, **kwargs):
            if "-c" in args and str(args[0]).endswith("python"):
                calls["n"] += 1
                rewrite(calls["n"])
            return self.real_run(args, *rest, **kwargs)

        with mock.patch("vibetracks.benches.grasp_bench_bridge.subprocess.run", side_effect=writer):
            track = grasping.build_track(work_track(), dict(self.sources))
        self.assertEqual(base.problems(track), [])
        return track

    def kpi(self, track: dict, kpi_id: str) -> dict:
        return next(k for k in track["kpis"] if k["id"] == kpi_id)

    def test_the_two_forms_differ_in_the_bench_verdict(self) -> None:
        # The fixture must discriminate: undisturbed, the sparse row beats nothing and the enriched one beats toy/x.
        sparse = self.build(lambda n: None)
        self.ledger.write_bytes(self.enriched)
        enriched = self.build(lambda n: None)
        self.assertEqual(self.kpi(sparse, "envs_beaten")["values"][-1]["value"], 0.0)
        self.assertEqual(self.kpi(enriched, "envs_beaten")["values"][-1]["value"], 1.0)
        for track in (sparse, enriched):
            gate_claims_have_measurements(self, track)

    def test_a_row_enriched_after_the_read_never_shows_a_verdict_beside_the_sparse_row(self) -> None:
        def enrich_once(call: int) -> None:
            if call == 1:
                self.ledger.write_bytes(self.enriched)

        track = self.build(enrich_once)
        gate_claims_have_measurements(self, track)
        # The adapter read again and judged the enriched bytes it then displayed.
        last = self.kpi(track, "envs_beaten")["values"][-1]
        self.assertEqual(last["value"], 1.0, last)
        run = next(item for items in track["evidence"]["by_iteration"].values() for item in items if item["kind"] == "run")
        self.assertEqual((run["status"], run["metrics"]["top-1 (%)"]), ("pass", 100.0))
        self.assertEqual(track["source"]["bench_verdict"]["attempts"], 2)

    def test_a_ledger_that_keeps_moving_gives_no_verdict_rather_than_a_mixed_one(self) -> None:
        def flip(call: int) -> None:
            current = self.ledger.read_bytes()
            self.ledger.write_bytes(self.enriched if current == self.sparse else self.sparse)

        track = self.build(flip)
        gate_claims_have_measurements(self, track)
        north = self.kpi(track, track["north_star"])
        self.assertEqual(track["north_star"], "envs_beaten")
        for point in north["values"]:
            self.assertIsNone(point["value"], point)
            self.assertFalse(point["measured"])
            self.assertIn(grasping.LEDGER_CHANGED, point["note"])
        self.assertEqual(north["status"], {"word": "bench verdict unavailable", "tone": "warn"})


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
        # WHY the record column is left out: it carries values, not verdicts, so its north star is null by design
        judged = [v for v in beaten_kpi["values"] if not v["iteration"].startswith("record")]
        self.assertTrue(judged and all(v["value"] is not None for v in judged), beaten_kpi["values"])
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
