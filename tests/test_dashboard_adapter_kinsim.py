"""The live kinsim adapter (vibetracks/dashboard/adapters/kinsim.py) over small hand-made loop files.

    python3 -m pytest -q tests/test_dashboard_adapter_kinsim.py      (from the repo root)

Every expected number below was worked out by hand from the fixture; one optional smoke test reads the real loop
home (~/.local/share/bam_curriculum) and is skipped when it is missing.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.dashboard.adapters import base, kinsim
from vibetracks.dashboard.registry import WorkTrack

LIVE_HOME = Path("~/.local/share/bam_curriculum").expanduser()


def work_track(sources: list[str]) -> WorkTrack:
    return WorkTrack(id="kinsim", title="Kinematic Sim", status="running", priority=1, owner=None, adapter="kinsim",
                     sources=sources, roadmap=None, children=[], note_path="/x/tracks/kinsim.md", revision="r1")


def rung(rung_id: str, gate: dict, *, baseline: str = "missing", weight: int = 1) -> dict:
    return {"rung_id": rung_id, "axis_id": "a", "title": rung_id, "gate": gate, "kpi_weight": weight,
            "baseline": {"status": baseline}, "prerequisites": [], "wave": 1}


STD = {"kind": "std", "regression_corpus": "r", "promotion_corpus": "p", "repeats": 2, "feasible_rate_min": 1.0}
CURRICULUM = {"schema": "bam-curriculum/1", "axes": [{"axis_id": "a", "title": "A", "order": 1}], "rungs": [
    rung("A0", {"kind": "none"}, baseline="done", weight=0),
    rung("LT", {"kind": "none"}, baseline="later", weight=0),       # gateless but not done: never counted
    rung("RB0", STD, weight=5),
    rung("OB0", {"kind": "same_as", "rung": "RB0"}, weight=0),
    rung("EV1", {"kind": "infra"}, weight=2),
    rung("BT2", {"kind": "ratchet", "promotion_corpus": "bt2", "metric": "recovery", "feasible_rate_min": 1.0}, weight=3),
]}
TRIAGE = {"schema": "x", "items": [
    {"triage_id": "T1", "title": "Pick at 1 m/s?", "opened_wave": 1, "blocks": ["BT2"], "status": "open",
     "default": "Not yet.", "default_applies_after_wave": 3},
    {"triage_id": "T2", "title": "Mount where?", "opened_wave": 2, "blocks": ["RB1"], "status": "open",
     "default": "Hang it.", "default_applies_after_wave": 2},
    {"triage_id": "T33", "title": "Disk?", "opened_wave": 1, "blocks": [], "status": "defaulted",
     "default": "The loop stops cleanly at 92 %."},
]}


def ev(ts: str, wave: int, kind: str, subject: str, status: str, detail: str = "", evidence: str | None = None,
       commit: str = "c0ffee00") -> dict:
    return {"ts": ts, "wave": wave, "kind": kind, "subject": subject, "status": status, "detail": detail,
            "evidence": evidence, "commit": commit}


def run_row(run_id: str, rung_id: str, tier: str, rate: float, gate_met: bool, ruler: str, ts: str) -> dict:
    presented = 64 if tier == "regression" else 1000
    return {"run_id": run_id, "ts": ts, "git": {"sha": "abcdef1234", "dirty": False}, "note": f"{rung_id} {tier}",
            "metrics": {"rung_id": rung_id, "tier": tier, "feasible_rate": rate, "ppm": 10.0 * rate, "recovery": rate,
                        "compute_s_p95": 0.01, "gate_met": gate_met, "ruler_sha256": ruler, "verdict_hash": "v" * 64},
            "totals": {"presented": presented, "feasible": round(presented * rate), "void": 0}}


class Fixture:
    """A loop home + loop checkout + reports dir in a temp folder; ``build()`` runs the adapter on it."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.loop = root / "loop"
        self.reports = root / "reports"
        for folder in (self.home, self.loop, self.reports, self.reports / "audits"):
            folder.mkdir(parents=True)
        self.audit = self.reports / "audits" / "2026-10-02-w2-rb0.md"
        self.audit.write_text("VERDICT: SHIP\n")
        (self.reports / "kinematic-curriculum-wave2-2026-10-02.html").write_text("<html></html>")
        (self.loop / "curriculum.json").write_text(json.dumps(CURRICULUM))
        (self.loop / "triage.json").write_text(json.dumps(TRIAGE))
        self.events = [
            ev("2026-10-01T10:00:00+00:00", 1, "wave_started", "wave-1", "running",
               "recorded at wave close (2026-10-01): wave 1 began at the freeze commit on 2026-09-30"),
            ev("2026-10-01T10:00:01+00:00", 1, "rung_status_changed", "EV1", "green"),
            ev("2026-10-01T10:00:02+00:00", 1, "gate_run", "fast", "pass"),
            ev("2026-10-01T10:00:03+00:00", 1, "audit", "w1-b1", "not_run"),
            ev("2026-10-01T10:00:04+00:00", 1, "wave_finished", "wave-1", "finished",
               "2 of 3 packages landed; fast gate PASS; df 80%"),
            ev("2026-10-02T00:00:00+00:00", 2, "wave_started", "wave-2", "running", "wave 2 preflight: df -h / 85 %"),
            ev("2026-10-02T01:00:00+00:00", 2, "audit", "rb0", "pass", "Codex SHIP",
               evidence=f"{self.audit}:12 VERDICT: SHIP; {self.reports / 'audits' / 'missing.md'}"),
            ev("2026-10-02T01:00:01+00:00", 2, "audit", "vz3", "fail", "DO-NOT-SHIP"),
            ev("2026-10-02T02:00:00+00:00", 2, "judged_run", "rb0-reg-r1", "recorded"),
            ev("2026-10-02T02:00:01+00:00", 2, "judged_run", "rb0-reg-r2", "recorded"),
            ev("2026-10-02T02:00:02+00:00", 2, "judged_run", "rb0-promo", "recorded"),
            ev("2026-10-02T02:00:03+00:00", 2, "judged_run", "bt2-promo", "recorded"),
            ev("2026-10-02T03:00:00+00:00", 2, "gate_run", "fast", "fail"),
            ev("2026-10-02T03:30:00+00:00", 2, "gate_run", "fast", "pass"),
            ev("2026-10-02T03:30:01+00:00", 2, "triage_changed", "T2", "opened"),
            ev("2026-10-02T06:00:00+00:00", 2, "wave_finished", "wave-2", "finished", "3 of 3 packages landed; df 70 %"),
        ]
        self.runs = [
            run_row("rb0-reg-r1", "RB0", "regression", 1.0, True, "ruler-x", "2026-10-02T02:00:00+00:00"),
            run_row("rb0-reg-r2", "RB0", "regression", 1.0, True, "ruler-x", "2026-10-02T02:00:01+00:00"),
            run_row("rb0-promo", "RB0", "promotion", 1.0, True, "ruler-x", "2026-10-02T02:00:02+00:00"),
            run_row("bt2-promo", "BT2", "promotion", 0.4, False, "ruler-x", "2026-10-02T02:00:03+00:00"),
        ]
        self.status = {
            "schema": "bam-curriculum-status/1", "wave": 2, "phase": "between_waves", "frontier": ["BT2"],
            "blocking_triage": ["T1"], "generated_at": "2026-10-02T06:00:00+00:00",
            "stuck": {"status": "ok", "detail": ""},
            "rungs": [{"rung_id": r, "status": s} for r, s in
                      (("A0", "done"), ("LT", "missing"), ("RB0", "green"), ("OB0", "green"), ("EV1", "green"), ("BT2", "partial"))],
        }

    def sources(self) -> dict[str, str]:
        """Every key kinsim.READS names, as the track note declares them (the reports folder included)."""

        return {"kinsim_status": str(self.home / "status.json"), "kinsim_events": str(self.home / "loop_events.jsonl"),
                "kinsim_runs": str(self.home / "runs.jsonl"), "kinsim_loop_dir": str(self.loop),
                "reports_media_dir": str(self.reports)}

    def build(self, sources: dict[str, str] | None = None) -> dict:
        (self.home / "status.json").write_text(json.dumps(self.status))
        (self.home / "loop_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.events))
        (self.home / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.runs))
        sources = self.sources() if sources is None else sources
        # WHY a poisoned sources file: the adapter must read only what it is handed, never the machine's map.
        overrides = self.root / "sources.json"
        overrides.write_text(json.dumps({"reports_media_dir": "/nonexistent/poisoned"}))
        with mock.patch.dict(os.environ, {"VIBETRACKS_SOURCES": str(overrides)}):
            return kinsim.build_track(work_track(list(sources)), sources)


def kpi(track: dict, kpi_id: str) -> dict:
    return next(k for k in track["kpis"] if k["id"] == kpi_id)


def series(track: dict, kpi_id: str) -> list:
    return [v["value"] for v in kpi(track, kpi_id)["values"]]


class KinsimAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shape_is_sound_and_waves_are_the_iterations(self) -> None:
        track = self.fx.build()
        self.assertEqual(base.problems(track), [])
        self.assertEqual([i["id"] for i in track["iterations"]], ["start", "W1", "W2"])
        self.assertEqual(track["iteration"], {"unit": "wave", "label": "wave 2"})
        self.assertEqual(track["iterations"][0]["date"], "2026-09-30")
        self.assertIn("wave closed: 3/3 landed", track["iterations"][2]["marker"])
        self.assertIn("+2 rungs (OB0, RB0)", track["iterations"][2]["marker"])
        self.assertEqual(track["north_star"], "rungs_green")
        self.assertTrue(4 <= len(track["kpis"]) <= 10)

    def test_burn_up_refolds_events_and_gated_ledger_rows(self) -> None:
        track = self.fx.build()
        # start: A0 (baseline done; LT's "later" is not done) · W1: + EV1 by event · W2: + RB0 by ledger, OB0 same_as
        self.assertEqual(series(track, "rungs_green"), [1, 2, 4])
        self.assertEqual(kpi(track, "rungs_green")["values"][-1]["of"], 6)
        self.assertEqual(series(track, "weighted_capability"), [0, 2, 7])
        self.assertEqual(series(track, "rungs_moved"), [None, 1, 2])
        self.assertEqual(kpi(track, "rungs_green")["status"]["word"], "+2 in W2")

    def test_refold_that_disagrees_with_the_fold_says_so_and_shows_the_fold(self) -> None:
        self.fx.status["rungs"][2]["status"] = "partial"   # the fold says RB0 is not green (e.g. a red fast gate)
        self.fx.status["rungs"][3]["status"] = "partial"
        track = self.fx.build()
        last = kpi(track, "rungs_green")["values"][-1]
        self.assertEqual(last["value"], 2)
        self.assertIn("disagrees with status.json at W2", last["note"])

    def test_ruler_change_voids_older_readings(self) -> None:
        # a third wave pins a new ruler and re-reads only one RB0 regression: RB0 (and OB0) drop out
        self.fx.events += [ev("2026-10-03T00:00:00+00:00", 3, "wave_started", "wave-3", "running"),
                           ev("2026-10-03T01:00:00+00:00", 3, "judged_run", "rb0-new", "recorded")]
        self.fx.runs.append(run_row("rb0-new", "RB0", "regression", 1.0, True, "ruler-y", "2026-10-03T01:00:00+00:00"))
        # status.json still holds the W2 fold, so the W3 value is the refold alone (no fold override to hide it)
        track = self.fx.build()
        self.assertEqual(series(track, "rungs_green"), [1, 2, 4, 2])
        self.assertIn("status.json still says wave 2 between_waves", track["state"]["detail"])
        self.assertIn("−2 (OB0, RB0)", track["iterations"][-1]["marker"])
        self.assertEqual(track["state"]["word"], "Running")
        self.assertIsNone(series(track, "packages_landed")[-1])
        self.assertIn("in progress", kpi(track, "elapsed_h")["values"][-1]["note"])

    def test_frontier_gate_reads_the_ledger_and_says_n_is_small(self) -> None:
        track = self.fx.build()
        frontier = kpi(track, "frontier_feasible")
        self.assertEqual(frontier["label"], "BT2 feasible")  # the page prints "Frontier gate" above it
        self.assertEqual(series(track, "frontier_feasible"), [None, None, 40.0])
        self.assertFalse(frontier["values"][1]["measured"])
        self.assertEqual(frontier["values"][2]["n"], 1)
        self.assertEqual(frontier["target"]["value"], 100.0)
        self.assertEqual(frontier["status"]["word"], "below gate · 40.0 % of 100 %")

    def test_delivery_cost_and_trust_series(self) -> None:
        track = self.fx.build()
        self.assertEqual(series(track, "packages_landed"), [None, 2, 3])
        self.assertEqual([v["of"] for v in kpi(track, "packages_landed")["values"]], [None, 3, 3])
        self.assertEqual(series(track, "gate_runs"), [None, 1, 1])
        self.assertEqual(kpi(track, "gate_runs")["values"][2]["of"], 2)
        self.assertEqual(series(track, "audits_passed"), [None, 0, 1])
        self.assertEqual(kpi(track, "audits_passed")["values"][1]["note"], "1 not run")
        elapsed = kpi(track, "elapsed_h")
        self.assertEqual(elapsed["unit"], "h elapsed")
        self.assertIsNone(elapsed["values"][1]["value"])           # W1's wave_started was written at the close
        self.assertIn("written at the close", elapsed["values"][1]["note"])
        self.assertEqual(elapsed["values"][2]["value"], 6.0)

    def test_questions_disk_and_needs_you(self) -> None:
        track = self.fx.build()
        self.assertEqual(series(track, "questions_opened"), [None, 2, 1])
        # History only: what is open now comes from /needs (build.py), never from a second count here (finding 5).
        self.assertEqual(kpi(track, "questions_opened")["status"]["word"], "3 opened in all")
        disk = kpi(track, "disk_pct")
        self.assertEqual(series(track, "disk_pct"), [None, 80.0, 85.0])     # W2 is its peak (85 then 70)
        self.assertEqual(disk["target"], {"value": 92.0, "kind": "limit", "label": "stop line: df -h / prints 92 %"})
        self.assertIn("last reading 70 %", disk["status"]["word"])
        needs = track["needs_you"]
        self.assertEqual([n["id"] for n in needs], ["T1", "T2"])
        self.assertEqual(needs[0]["blocks"], ["BT2"])
        self.assertEqual(needs[1]["blocks"], [])                            # its default is in force: it holds nothing
        self.assertEqual(needs[1]["applies"], "after W2 · in force (W2 closed)")

    def test_state_and_summary(self) -> None:
        track = self.fx.build()
        self.assertEqual(track["state"]["word"], "Between waves")
        self.assertEqual(track["state"]["tone"], "ok")
        self.assertIn("wave 3 not started", track["state"]["detail"])
        self.assertEqual(track["state"]["since"], "2026-10-02T06:00:00+00:00")
        self.assertEqual(track["summary"], "Wave 2 closed; 4 of 6 rungs green or done (+2: OB0, RB0); "
                                           "frontier BT2 at 40 % feasible.")

    def test_rung_between_waves_is_the_frontier_and_next_is_the_wave_plan(self) -> None:
        track = self.fx.build()
        self.assertEqual(track["rung"], {"current": "Frontier · BT2", "next": None,
                                         "source": "kinsim_status (frontier) · curriculum.json (wave plan)"})
        self.assertIn("frontier: BT2", track["state"]["detail"])
        self.assertRegex(track["state"]["detail"], r"wave 2 closed \d\d-\d\d \d\d:\d\d [A-Z]{3,4}")
        plan = json.loads(json.dumps(CURRICULUM))
        for row in plan["rungs"]:
            if row["rung_id"] in ("BT2", "LT"):
                row["wave"] = 3
        (self.fx.loop / "curriculum.json").write_text(json.dumps(plan))
        self.assertEqual(self.fx.build()["rung"]["next"], "Wave 3 · LT, BT2")  # still open, planned for wave 3

    def test_rung_while_running_is_the_waves_own_targets(self) -> None:
        plan = json.loads(json.dumps(CURRICULUM))
        for row in plan["rungs"]:
            row["wave"] = {"BT2": 3, "LT": 4}.get(row["rung_id"], row["wave"])
        (self.fx.loop / "curriculum.json").write_text(json.dumps(plan))
        self.fx.events.append(ev("2026-10-02T07:00:00+00:00", 3, "wave_started", "wave-3", "running", "wave 3 preflight"))
        track = self.fx.build()
        self.assertEqual(track["state"]["word"], "Running")
        self.assertEqual(track["rung"]["current"], "Wave 3 · BT2")
        self.assertEqual(track["rung"]["next"], "Wave 4 · LT")
        self.assertEqual(base.problems(track), [])

    def test_wave_reports_come_only_from_the_declared_folder(self) -> None:
        sources = self.fx.sources()
        del sources["reports_media_dir"]
        track = self.fx.build(sources)
        self.assertNotIn("kinsim.wave2.report", track["media"])
        self.assertNotIn("Wave 2 report", [link["label"] for link in track["links"]])

    def test_paused_loop_reads_paused(self) -> None:
        self.fx.events.append(ev("2026-10-02T07:00:00+00:00", 2, "loop_paused", "disk", "paused",
                                 "wave 3 not dispatched: df -h / prints 91 %; resumes when disk is freed"))
        track = self.fx.build()
        self.assertEqual(track["state"]["word"], "Paused")
        self.assertEqual(track["state"]["tone"], "warn")
        self.assertIn("status.json still says wave 2 between_waves", track["state"]["detail"])
        self.assertEqual(series(track, "disk_pct")[-1], 91.0)

    def test_evidence_and_media_only_for_files_that_exist(self) -> None:
        track = self.fx.build()
        media = track["media"]
        paths = {entry["path"] for entry in media.values()}
        self.assertIn(str(self.fx.audit), paths)
        self.assertNotIn(str(self.fx.reports / "audits" / "missing.md"), paths)
        self.assertIn(str(self.fx.reports / "kinematic-curriculum-wave2-2026-10-02.html"), paths)
        self.assertTrue(all(media_id.startswith("kinsim.") for media_id in media))
        self.assertTrue(all(Path(p).is_file() for p in paths))
        w2 = {item["id"]: item for item in track["evidence"]["by_iteration"]["W2"]}
        self.assertEqual(w2["bt2-promo"]["metrics"]["feasible"], "400/1000")
        self.assertEqual(kpi(track, "frontier_feasible")["values"][2]["evidence"], ["bt2-promo"])
        self.assertEqual(track["links"][0], {"label": "Wave 2 report", "kind": "media", "media": "kinsim.wave2.report"})

    def test_missing_curriculum_gives_gaps_not_zeros(self) -> None:
        (self.fx.loop / "curriculum.json").unlink()
        track = self.fx.build()
        self.assertEqual(base.problems(track), [])
        values = kpi(track, "rungs_green")["values"]
        self.assertEqual([v["value"] for v in values], [None, None, 4])      # only the fold's current count
        self.assertTrue(all(v["note"] for v in values[:2]))
        self.assertTrue(all(v["value"] is None and v["note"] for v in kpi(track, "weighted_capability")["values"]))

    def test_stored_text_reaches_the_projection_whole(self) -> None:
        # WHY (audit 2026-10-04, finding 10): event details were cut at 600 characters with "…" (w3-review-rule was
        # 642 characters, w3-intervention-5 carried 600); leading/trailing spaces were trimmed too.
        long_detail = "  " + " ".join(f"word{n}" for n in range(200)) + " end.  "
        self.assertGreater(len(long_detail), 1200)
        self.fx.events.insert(-1, ev("2026-10-02T05:00:00+00:00", 2, "intervention", "w3-review-rule", "noted",
                                     long_detail))
        self.fx.events[-1]["detail"] = "3 of 3 packages landed; df 70 % · " + "x" * 700
        track = self.fx.build()
        notes = [item.get("note") for item in track["evidence"]["by_iteration"]["W2"]]
        self.assertIn(long_detail, notes)
        self.assertIn(self.fx.events[-1]["detail"], notes)
        self.assertFalse(any(isinstance(note, str) and note.endswith("…") for note in notes))

    def test_a_rung_without_a_weight_is_not_weighed_as_zero(self) -> None:
        curriculum = json.loads(json.dumps(CURRICULUM))
        del curriculum["rungs"][2]["kpi_weight"]   # RB0
        (self.fx.loop / "curriculum.json").write_text(json.dumps(curriculum))
        values = kpi(self.fx.build(), "weighted_capability")["values"]
        self.assertTrue(all(v["value"] is None and not v["measured"] for v in values))
        self.assertIn("without a numeric kpi_weight: RB0", values[0]["note"])

    def test_no_python_none_reaches_any_text(self) -> None:
        from test_dashboard_adapter_rig import assert_no_none_text
        assert_no_none_text(self, self.fx.build())
        (self.fx.loop / "curriculum.json").unlink()
        self.fx.status["rungs"] = []
        assert_no_none_text(self, self.fx.build())

    def test_no_loop_files_is_not_reporting(self) -> None:
        track = kinsim.build_track(work_track([]), {"kinsim_status": str(self.fx.home / "nope.json")})
        self.assertFalse(track["reporting"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})


@unittest.skipUnless((LIVE_HOME / "status.json").is_file(), "no live kinsim loop home on this machine")
class KinsimLiveSmokeTest(unittest.TestCase):
    def test_live_track_matches_the_fold(self) -> None:
        from vibetracks.sources import load_sources

        keys = list(kinsim.READS)
        paths = load_sources()
        track = kinsim.build_track(work_track(keys), {key: paths[key] for key in keys})
        self.assertEqual(base.problems(track), [])
        status = json.loads((LIVE_HOME / "status.json").read_text())
        green_done = sum(1 for r in status["rungs"] if r["status"] in ("green", "done"))
        last = kpi(track, "rungs_green")["values"][-1]
        if last["iteration"] == f"W{status['wave']}":
            self.assertEqual(last["value"], green_done)
        self.assertGreaterEqual(len(track["kpis"]), 4)
        self.assertTrue(all(Path(entry["path"]).is_file() for entry in track["media"].values()))


if __name__ == "__main__":
    unittest.main()
