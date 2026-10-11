"""Proof-phase fixes to the grasping track (2026-10-11), pinned so a refactor cannot undo them.

    cd ~/vibetracks-grasping && python3 -m unittest tests/test_dashboard_grasping_proof_fixes.py

- Decisions come from the loop's triage.json (open items, at most three, its ids are the answer keys); roadmap_v4.json's
  needs_you is the fallback only when triage.json is missing.
- A stale scoreboard is its own field beside the tile's status, so a card can show both in full.
- A gate without a holder carries no bare lower bound and names the model.
- The runner KPI counts runs when the runner reports them, and says requests when it does not.
- The older gallery KPIs are relabelled when the scoreboard leads.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

# WHY the module, not its classes: importing a TestCase class by name makes the runner collect its tests twice.
from tests import test_dashboard_adapter_grasping as fx
from vibetracks.dashboard import needs
from vibetracks.dashboard.adapters import grasping
from vibetracks.home import detail

TRIAGE = {"schema": "bam-triage/1", "updated_at": "2026-10-11T19:40:00+00:00", "items": [
    {"id": "D1", "status": "open", "title": "One yes for the download packet", "recommendation": "yes",
     "default": "Nothing is downloaded."},
    {"id": "N1", "status": "open", "title": "Raise the toy bars to 0.99?", "recommendation": "yes",
     "default": "Bars unchanged."},
    {"id": "V51-x", "status": "queued", "title": "an agent item", "default": "keep"},
    {"id": "N2", "status": "open", "title": "Harden the sealed folder?", "recommendation": "not yet",
     "default": "No."},
    {"id": "N3", "status": "open", "title": "a fourth open one", "default": "none"}]}


class ProofFixesTest(unittest.TestCase):
    tearDown, build, kpi = fx.FixtureTest.tearDown, fx.FixtureTest.build, fx.FixtureTest.kpi

    def setUp(self) -> None:
        fx.FixtureTest.setUp(self)
        self.roadmap = Path(self.sources["grasping_roadmap_v4"])
        self.roadmap.parent.mkdir(parents=True, exist_ok=True)
        self.roadmap.write_text(json.dumps(fx.ROADMAP), encoding="utf-8")
        self.triage = self.root / "loop" / "triage.json"
        self.triage.parent.mkdir(parents=True, exist_ok=True)
        self.triage.write_text(json.dumps(TRIAGE), encoding="utf-8")
        self.sources = {**self.sources, "grasping_triage": str(self.triage),
                        "grasping_triage_answers": str(self.root / "loop" / "triage_answers.jsonl")}
        self.board = Path(self.sources["grasping_scoreboard"])
        self.board.parent.mkdir(parents=True, exist_ok=True)

    def write_board(self, **overrides) -> None:
        self.board.write_text(json.dumps(fx.scoreboard_doc(self.ledger, **overrides)), encoding="utf-8")

    # ---- decisions
    def test_needs_you_reads_triage_open_items_at_most_three(self) -> None:
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        self.assertEqual(doc["source"]["adapter"], "grasp_triage")
        self.assertEqual([item["local_id"] for item in doc["items"]], ["D1", "N1", "N2"])
        self.assertIn("1 more wait in the file", doc["source"]["note"])
        self.assertEqual(doc["items"][1]["recommendation_md"], "yes")
        self.assertEqual(doc["items"][1]["default"]["text_md"], "Bars unchanged.")
        track = self.build()
        self.assertEqual([n["id"] for n in track["needs_you"]], ["D1", "N1", "N2"])
        self.assertIn("4 decisions open (triage.json)", track["summary"])

    def test_an_answer_keyed_by_a_triage_id_lands_on_its_item(self) -> None:
        answers = Path(self.sources["grasping_triage_answers"])
        answers.write_text(json.dumps({"triage_id": "N1", "choice": "use_default", "ts": "2026-10-11T20:00:00Z"}) + "\n",
                           encoding="utf-8")
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        items = {item["local_id"]: item for item in doc["items"]}
        self.assertEqual(items["N1"]["status"], "answered")

    def test_the_milestone_card_shows_triage_decisions_not_the_roadmaps(self) -> None:
        ms = self.build()["milestones"]
        self.assertEqual([n["id"] for n in ms["needs_you"]], ["D1", "N1", "N2"])
        self.assertEqual(ms["needs_you_total"], 4)

    def test_roadmap_is_the_fallback_when_triage_is_missing(self) -> None:
        self.triage.unlink()
        doc = needs.build_track("grasping", self.sources, title="Grasping")
        self.assertEqual(doc["source"]["adapter"], "grasp_roadmap")

    # ---- header tiles
    def test_stale_is_its_own_field_beside_the_full_status(self) -> None:
        self.write_board()
        extra = dict(fx.ROWS[0], run_id="20261011T193000Z_extra", started_at="2026-10-11T19:30:00+00:00")
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(extra) + "\n")
        track = grasping.build_track(fx.work_track(), self.sources,
                                     bridge=fx.FakeBridge(self, reason="not judged"))
        status = self.kpi(track, "picks_per_hour")["status"]
        self.assertTrue(status["stale"].startswith("stale since"))
        self.assertEqual(status["core"], "estimate · better elsewhere: M6.sim_finetuned_bandit about 1,869 (estimate)")
        self.assertEqual(status["word"], f"{status['stale']} · {status['core']}")   # the one-line form is unchanged

    # ---- gates
    def test_a_gate_without_holder_names_the_model_and_carries_no_value(self) -> None:
        doc = fx.scoreboard_doc(self.ledger)
        doc["gates"][2].update(best="M0.uniform", worst_seed_lb=0.00615, best_is_floor=True)
        doc["gates"].append({"kind": "gate", "env": "mujoco/stage3", "bar": 0.90, "protocol": {"name": "eval-1000"},
                             "status": "not_beaten", "holder": None, "best": "M3.bandit", "worst_seed_lb": 0.93,
                             "seeds": {}, "held": False, "v4": None,
                             "seeds_short": {"model": "M3.bandit", "have": 1, "need": 3, "worst_seed_lb": 0.93}})
        self.board.write_text(json.dumps(doc), encoding="utf-8")
        track = self.build()
        floor = detail.gate_verdict(self.kpi(track, "gate_mujoco_stage1"))
        self.assertIsNone(floor["value"])
        self.assertIn("best so far M0.uniform (random floor), LB 0.61 %", floor["why"])
        short = detail.gate_verdict(self.kpi(track, "gate_mujoco_stage3"))
        self.assertEqual(short["why"], "not beaten · M3.bandit clears the bar on 1 of 3 training seeds, LB 93.00 %")
        self.assertFalse(short["pass"])
        held = detail.gate_verdict(self.kpi(track, "gate_toy_xy_rz"))
        self.assertEqual(held["value"], 96.66)

    # ---- runner
    def test_the_runner_kpi_counts_runs_when_the_runner_reports_them(self) -> None:
        status = Path(self.sources["grasping_queue_status_json"])
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps(fx.runner_status(runs_done_24h=10, runs_failed_24h=0, requests_done_24h=2,
                                                   done_24h=2)), encoding="utf-8")
        kpi = self.kpi(self.build(), "runner_queue")
        self.assertEqual(kpi["label"], "Runner · runs done in 24 h")
        self.assertEqual(kpi["values"][-1]["value"], 10.0)
        self.assertIn("10 runs (2 requests) done · 0 runs failed in 24 h", kpi["status"]["word"])
        status.write_text(json.dumps(fx.runner_status(done_24h=2)), encoding="utf-8")
        kpi = self.kpi(self.build(), "runner_queue")
        self.assertEqual((kpi["label"], kpi["unit"]), ("Runner · requests done in 24 h", "requests"))

    # ---- legacy detail
    def test_the_legacy_cards_are_relabelled_under_a_scoreboard(self) -> None:
        self.write_board()
        track = self.build()
        labels = {k["id"]: k["label"] for k in track["kpis"]}
        self.assertTrue(labels["tier_best_toy"].endswith("best single seed, v4 gallery"))
        self.assertEqual(labels["envs_beaten"], "Gated envs beaten · v4 gallery verdict")


if __name__ == "__main__":
    unittest.main()
