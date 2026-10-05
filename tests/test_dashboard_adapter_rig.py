"""The rig work-track adapter (vibetracks/dashboard/adapters/rig.py) over small hand-built loop files.

    python3 -m unittest tests/test_dashboard_adapter_rig.py      (from the repo root)

Every expected number below was computed by hand from the fixture written in ``setUp``; the last test is a live smoke
test over the real rig loop folder, skipped when that folder is not on this machine.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vibetracks.dashboard.adapters import base, rig
from vibetracks.dashboard.adapters.bam_loops import N1_WORD
from vibetracks.dashboard.registry import WorkTrack

PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=PDT)
DEG = 57.29577951308232


def _event(ts: str, wave: int, kind: str, subject: str, status: str, detail: str = "", evidence: str | None = None) -> dict:
    return {"ts": ts, "wave": wave, "kind": kind, "subject": subject, "status": status, "detail": detail,
            "commit": None, "evidence": evidence}


def _period(name: str, start: str, real: int, sim: int, **kpis) -> dict:
    keys = ("real_tracking_rms", "floor_real_vs_real", "real_runs", "sim_runs", "aborted_runs", "twin_fidelity_gap", "twin_tracking_ratio")
    values = {key: None for key in keys} | {"real_runs": real, "sim_runs": sim, "aborted_runs": 0} | kpis
    return {"period": name, "start": start, "end": start, "bundles": [name], "counts": {"real": real, "sim": sim, "aborted": 0}, "kpis": values}


KPI_DEFS = [
    {"key": "real_tracking_rms", "label": "Real tracking error (RMS)", "unit": "deg", "lower_is_better": True, "scale": DEG},
    {"key": "floor_real_vs_real", "label": "Floor (relative repeat)", "unit": "deg", "lower_is_better": None, "scale": DEG},
    {"key": "real_runs", "label": "Real runs", "unit": "", "lower_is_better": None, "scale": 1.0},
    {"key": "sim_runs", "label": "Sim runs", "unit": "", "lower_is_better": None, "scale": 1.0},
    {"key": "aborted_runs", "label": "Aborted runs", "unit": "", "lower_is_better": None, "scale": 1.0},
    {"key": "twin_fidelity_gap", "label": "Twin fidelity gap (held-out)", "unit": "deg", "lower_is_better": True, "scale": DEG},
    {"key": "twin_tracking_ratio", "label": "Twin tracking ratio (sim / real)", "unit": "×", "lower_is_better": None, "scale": 1.0},
]


class RigAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.loop = root / "bam_rig_loop"
        self.fixtures = root / "fixtures"
        self.cache = root / "cache"
        for folder in (self.loop, self.fixtures, self.cache):
            folder.mkdir()
        self.write(self.loop / "loop-status.json", {
            "schema": "loop-status/1", "loop": "rig", "generated_at": "2026-10-02T11:30:00-07:00",
            "tick": {"kind": "wave", "n": 2, "phase": "running", "head": "abc1234"},
            "rate": {"rungs_moved_per_tick": [0, 2], "product_rungs_moved": 3, "hours_spent": 30.0, "days_since_real_row": 10},
            "milestone": {"title": "Pick up waste", "due": "2026-10-22", "state": "sim first"},
            "where": [{"axis": "A", "here": "A2", "status": "partial", "next": "A3"}],
            "now": [{"lane": "P3 building", "kind": "lane", "status": "building", "since": "10:00"}],
            "next": ["Bench window 1"],
            "needs_you": [{"id": "T2", "kind": "decision", "q": "Flash diff", "default": "no default", "applies": None}],
            "defaulting": ["T4", "T6"],
            "blockers": ["No rig attached", "Needs you, no default: T9 Arm support"],
            "links": {"dashboard": "sps open", "report": "/nonexistent/report.html"},
        })
        events = [
            _event("2026-10-01T10:00:00-07:00", 0, "wave_started", "bootstrap", "running"),
            _event("2026-10-01T10:10:00-07:00", 0, "rung_status_changed", "A0", "green", "dashboard live"),
            _event("2026-10-01T10:20:00-07:00", 0, "triage_changed", "T1", "answered", "Old worktrees removed; / at 90%"),
            _event("2026-10-01T11:00:00-07:00", 0, "wave_finished", "bootstrap", "finished"),
            _event("2026-10-02T09:00:00-07:00", 2, "wave_started", "tick-2", "running"),
            _event("2026-10-02T10:00:00-07:00", 2, "lane_status", "P1", "landed", "landed after 2 rounds"),
            _event("2026-10-02T10:05:00-07:00", 2, "audit", "P1", "SOUND WITH FIXES", "closure", evidence="reports/media/audits/none.md"),
            _event("2026-10-02T10:30:00-07:00", 2, "rung_status_changed", "A1", "green", "twin fit"),
            _event("2026-10-02T11:00:00-07:00", 2, "note", "disk", "freed", "Disk / at 78% (194 GB free) under the line"),
        ]
        (self.loop / "loop_events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n{not json\n", encoding="utf-8")
        self.write(self.loop / "ladder.json", {
            "schema": "rig-ladder/1", "last_real_run": "2026-09-22",
            "episode": {"started": "2026-10-01", "stop": "2026-10-16", "stop_condition": "a floor from one bench session"},
            "milestone": {"title": "Pick up waste", "due": "2026-10-22"},
            "axes": [
                {"id": "A", "title": "Axis A", "rungs": [
                    {"id": "A0", "title": "start", "status": "green", "packages": []},
                    {"id": "A1", "title": "one", "status": "green", "packages": ["P1"]},
                    {"id": "A2", "title": "two", "status": "green", "packages": ["P2"]},
                    {"id": "A3", "title": "three", "status": "missing", "packages": ["P3"]}]},
                {"id": "TWIN", "title": "Twin", "rungs": [
                    {"id": "TW2", "title": "Two-knob twin ≤ 0.8° held-out", "status": "partial", "packages": []}]},
            ],
            "packages": [
                {"id": "P1", "title": "first", "rung": "A1", "kind": "lane", "status": "landed", "updated": "2026-10-02T10:00:00-07:00"},
                {"id": "P2", "title": "second", "rung": "A2", "kind": "lane", "status": "landed", "updated": "2026-10-02T09:30:00-07:00"},
                {"id": "P3", "title": "third", "rung": "A3", "kind": "lane", "status": "building", "updated": "2026-10-02T09:40:00-07:00"},
            ],
        })
        self.write(self.loop / "triage.json", {"schema": "bam-triage/1", "items": [
            {"triage_id": "T1", "status": "answered", "title": "Disk", "default": "No default", "blocks": []},
            {"triage_id": "T6", "status": "open", "title": "Torque cap", "default": "Sim scores at 7.19", "default_applies_after_wave": 1, "blocks": []},
            {"triage_id": "T4", "status": "open", "title": "Open a bench window", "default": "Keep climbing in sim", "default_applies_after_wave": 1, "blocks": ["BN1"]},
            {"triage_id": "T2", "status": "open", "title": "Flash diff", "default": "No default: nothing is flashed", "blocks": ["BN1"]},
        ]})
        (self.loop / "ROADMAP.md").write_text("1. **Preflight:** `/` under 92% (`df -h /`)\n", encoding="utf-8")

        dep = "can12-pendulum-10to1"
        self.write(self.fixtures / "deployments.json", [{
            "id": dep, "title": "1-DOF pendulum · CAN 12", "summary": "One servo and a bar.",
            "counts": {"real": 3, "sim": 17, "aborted": 0},
            "latest": {"real_tracking_rms": 0.04, "floor_real_vs_real": 0.001, "real_runs": 0, "sim_runs": 2, "aborted_runs": 0,
                       "twin_fidelity_gap": 0.0111, "twin_tracking_ratio": 0.93},
            "latest_period": {"real_tracking_rms": "2026-09-22", "floor_real_vs_real": "2026-09-22", "real_runs": "2026-10-02",
                              "sim_runs": "2026-10-02", "aborted_runs": "2026-10-02", "twin_fidelity_gap": "2026-10-02",
                              "twin_tracking_ratio": "2026-10-02"},
        }])
        self.write(self.fixtures / f"kpis_session_{dep}.json", {"kpi_defs": KPI_DEFS, "periods": [
            _period("bench_a_2026-09-20", "2026-09-20T10:00:00", 1, 0, real_tracking_rms=0.02),
            _period("bench_b_2026-09-21", "2026-09-21T10:00:00", 1, 0, real_tracking_rms=0.03),
            _period("bench_c_2026-09-22", "2026-09-22T10:00:00", 1, 0, real_tracking_rms=0.04),
            _period(f"{dep}__twin-V0__2026-10-01", "2026-10-01T10:30:00-07:00", 0, 15, twin_fidelity_gap=0.06, twin_tracking_ratio=0.005),
        ]})
        self.write(self.fixtures / f"kpis_day_{dep}.json", {"kpi_defs": KPI_DEFS, "periods": [
            _period("2026-09-22", "2026-09-20T10:00:00", 3, 0, real_tracking_rms=0.03, floor_real_vs_real=0.001),
        ]})
        self.video = self.cache / "bench_a.mp4"
        self.video.write_bytes(b"\x00")
        for session, day, rms, video in (("bench_a_2026-09-20", "2026-09-20", 0.02, str(self.video)),
                                          ("bench_b_2026-09-21", "2026-09-21", 0.03, str(self.cache / "missing.mp4")),
                                          ("bench_c_2026-09-22", "2026-09-22", 0.04, None)):
            self.record(session, "slow_step__real__ff_fb", {"deployment_id": dep, "session": session, "bundle": session, "day": day,
                                                           "started_at": f"{day}T10:00:00", "environment": "real", "control_mode": "ff_fb",
                                                           "trajectory_name": "slow_step", "config": "default", "aborted": False,
                                                           "metrics": {"tracking_rms_rad": rms}, "video_path": video})
        twin = f"{dep}__twin-V1__2026-10-02"
        for name in ("chirp", "step"):
            self.record(twin, f"{name}__sim__ff_fb", {"deployment_id": dep, "session": twin, "bundle": twin, "day": "2026-10-02",
                                                     "started_at": "2026-10-02T09:45:00-07:00", "environment": "sim", "control_mode": "ff_fb",
                                                     "trajectory_name": name, "config": "default", "aborted": False,
                                                     "replay_of": f"bench_a/{name}__real__ff_fb",
                                                     "metrics": {"tracking_rms_rad": 0.04, "replay_gap_aligned_rad": 0.011}})
        self.sources = {"rig_loop_status": str(self.loop / "loop-status.json"), "rig_events": str(self.loop / "loop_events.jsonl"),
                        "rig_ladder": str(self.loop / "ladder.json"), "deployments_fixtures_dir": str(self.fixtures),
                        rig.CACHE_KEY: str(self.cache)}
        self.work_track = WorkTrack(id="rig", title="Sim to Real", status="running", priority=2, owner=None, adapter="rig",
                                    sources=list(self.sources), roadmap=None, children=["can12", "can16"],
                                    note_path="/tmp/rig.md", revision="r1")
        patcher = mock.patch.object(rig, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    @staticmethod
    def write(path: Path, payload) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def record(self, bundle: str, name: str, record: dict) -> None:
        folder = self.cache / bundle
        folder.mkdir(exist_ok=True)
        self.write(folder / f"{name}.json", {"fingerprint": {}, "record": record})

    def track(self) -> dict:
        return rig.build_track(self.work_track, dict(self.sources))

    @staticmethod
    def kpi(track: dict, kpi_id: str) -> dict:
        return next(k for k in track["kpis"] if k["id"] == kpi_id)

    @staticmethod
    def series(kpi: dict) -> list:
        return [v["value"] for v in kpi["values"]]

    # ------------------------------------------------------------------------------------------------ the loop

    def test_track_is_sound(self) -> None:
        track = self.track()
        self.assertEqual(base.problems(track), [])
        self.assertEqual([it["id"] for it in track["iterations"]], ["T0", "T1", "T2"])
        self.assertTrue(4 <= len(track["kpis"]) <= 10)
        self.assertEqual(track["north_star"], "rungs_green")
        self.assertEqual(track["state"]["word"], "Running")
        self.assertEqual(track["state"]["tone"], "warn")  # a blocker is recorded
        self.assertIn("blocker: No rig attached", track["state"]["detail"])
        self.assertTrue(track["summary"].startswith("Tick 2 running: 3 of 5 rungs green"))
        self.assertIn("1 unparseable event lines", track["source"]["problems"])

    def test_rungs_green_per_tick_from_events_and_ladder(self) -> None:
        kpi = self.kpi(self.track(), "rungs_green")
        self.assertEqual(self.series(kpi), [1, 1, 3])  # A0 | carried (no events) | A1 by event + A2 placed by P2's landing
        self.assertEqual(kpi["values"][2]["of"], 5)
        self.assertIn("no event recorded", kpi["values"][1]["note"])
        self.assertIn("A2: no rung_status_changed event", kpi["values"][2]["note"])
        self.assertEqual(kpi["status"]["word"], "3 of 5 · +2 in T2")

    def test_missing_is_null_never_zero(self) -> None:
        track = self.track()
        for kpi_id in ("packages_landed", "audits", "elapsed_h", "days_since_real", "disk_pct", "twin_gap"):
            value = self.kpi(track, kpi_id)["values"][1]  # T1 recorded no event
            self.assertIsNone(value["value"], kpi_id)
            self.assertFalse(value["measured"], kpi_id)
            self.assertTrue(value["note"], kpi_id)
        self.assertEqual(self.series(self.kpi(track, "packages_landed")), [0, None, 2])
        self.assertEqual(self.series(self.kpi(track, "audits")), [0, None, 1])
        self.assertEqual(self.series(self.kpi(track, "days_since_real")), [9, None, 10])

    def test_elapsed_hours_are_wall_clock(self) -> None:
        kpi = self.kpi(self.track(), "elapsed_h")
        self.assertEqual(kpi["unit"], "h elapsed")
        self.assertEqual(self.series(kpi), [1.0, None, 30.0])
        self.assertIn("never agent-hours", kpi["note"])

    def test_twin_gap_placed_by_time_with_gate(self) -> None:
        kpi = self.kpi(self.track(), "twin_gap")
        self.assertEqual(self.series(kpi), [3.438, None, 0.636])
        self.assertEqual(kpi["target"]["value"], 0.8)
        self.assertEqual(kpi["status"]["word"], "under gate")
        self.assertIn("(cache)", kpi["values"][2]["note"])

    def test_disk_parsed_from_prose_against_the_roadmap_line(self) -> None:
        kpi = self.kpi(self.track(), "disk_pct")
        self.assertEqual(self.series(kpi), [90.0, None, 78.0])
        self.assertEqual(kpi["target"]["value"], 92.0)
        self.assertIn("triage T1", kpi["values"][0]["note"])
        self.assertIn("194 GB free", kpi["values"][2]["note"])

    def test_needs_you_from_triage_no_default_first(self) -> None:
        track = self.track()
        self.assertEqual([n["id"] for n in track["needs_you"]], ["T2", "T4", "T6"])
        self.assertIsNone(track["needs_you"][0]["default"])
        self.assertEqual(track["needs_you"][1]["applies"], "after T1")
        self.assertNotIn("needs_you_count", track)  # the build counts the list
        self.assertEqual(self.series(self.kpi(track, "open_questions")), [None, None, 3])

    def test_needs_you_falls_back_to_loop_status(self) -> None:
        (self.loop / "triage.json").unlink()
        track = self.track()
        self.assertEqual([n["id"] for n in track["needs_you"]], ["T2", "T9"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})
        self.assertEqual(base.problems(track), [])

    def test_missing_loop_status_is_not_reporting(self) -> None:
        (self.loop / "loop-status.json").unlink()
        track = self.track()
        self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
        self.assertIn("loop-status.json missing", track["summary"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})
        self.assertEqual(track["kpis"], [])

    def test_media_lists_only_existing_files(self) -> None:
        track = self.track()
        self.assertEqual(track.get("media"), {})  # the audit and report paths do not exist
        for path in (m["path"] for c in rig.build_children(self.work_track, dict(self.sources)) for m in c["media"].values()):
            self.assertTrue(os.path.isfile(path), path)

    # ------------------------------------------------------------------------------------------------ children

    def test_children_from_fixtures_and_cache(self) -> None:
        children = rig.build_children(self.work_track, dict(self.sources))
        self.assertEqual([c["id"] for c in children], ["can12"])  # no can16 in deployments.json: the build falls back
        can12 = children[0]
        self.assertEqual(base.problems(can12), [])
        self.assertEqual(len(can12["iterations"]), 5)
        self.assertIn("newer than the session fixture", can12["iterations"][-1]["marker"])
        twin = self.kpi(can12, "twin_fidelity_gap")
        self.assertEqual(self.series(twin)[-2:], [3.438, 0.636])
        self.assertIn("deployments.json latest", twin["values"][-1]["note"])
        self.assertEqual(self.series(self.kpi(can12, "sim_runs"))[-1], 2)  # counted from the cache records
        self.assertEqual(self.series(self.kpi(can12, "real_tracking_rms"))[:3], [1.146, 1.719, 2.292])

    def test_held_condition_on_n1_reads_unconfirmed(self) -> None:
        can12 = rig.build_children(self.work_track, dict(self.sources))[0]
        held = self.kpi(can12, "held_slow_step_ff_fb_default")
        self.assertEqual(self.series(held)[:3], [1.146, 1.719, 2.292])
        self.assertEqual(held["status"]["word"], N1_WORD)
        self.assertEqual(can12["state"]["word"], "Repeat needed")
        self.assertEqual(len(can12["media"]), 1)  # only bench_a's video exists
        notes = [e["note"] for items in can12["evidence"]["by_iteration"].values() for e in items if e["kind"] == "run"]
        self.assertIn("video path recorded but no file on disk", notes)


LIVE_STATUS = "/home/bam/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop/loop-status.json"


@unittest.skipUnless(os.path.isfile(LIVE_STATUS), "the live rig loop folder is not on this machine")
class RigAdapterLiveSmokeTest(unittest.TestCase):
    def test_live_track_reports_real_kpis(self) -> None:
        from vibetracks.sources import load_sources

        paths = load_sources()
        keys = ["rig_loop_status", "rig_events", "rig_ladder", "deployments_fixtures_dir"]
        sources = {key: paths[key] for key in keys}
        work_track = WorkTrack(id="rig", title="Sim to Real", status="running", priority=2, owner=None, adapter="rig",
                               sources=keys, roadmap=None, children=["can12", "can16"], note_path="/tmp/rig.md", revision="r")
        track = rig.build_track(work_track, sources)
        self.assertEqual(base.problems(track), [])
        self.assertNotEqual(track["state"]["word"], base.NOT_REPORTING)
        with open(paths["rig_ladder"], encoding="utf-8") as handle:
            ladder = json.load(handle)
        green = sum(1 for axis in ladder["axes"] for rung in axis["rungs"] if rung["status"] == "green")
        rungs = next(k for k in track["kpis"] if k["id"] == "rungs_green")
        self.assertEqual(rungs["values"][-1]["value"], green)
        self.assertTrue(any(v["measured"] for k in track["kpis"] for v in k["values"]))
        for child in rig.build_children(work_track, sources):
            self.assertEqual(base.problems(child), [], child["id"])


if __name__ == "__main__":
    unittest.main()
