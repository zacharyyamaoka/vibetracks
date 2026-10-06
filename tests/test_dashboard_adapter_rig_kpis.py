"""Rig track page acceptance (2026-10-06): the rig leads with Zach's robot KPIs, read from the KPI-table export.

    python3 -m unittest tests/test_dashboard_adapter_rig_kpis.py      (from the repo root)

Why (Zach, Daily Note - Oct 6 2026): "When I started this work we had set up some very clear KPIs ... A key thing here
is like a table that shows the different deployments, and then the KPIs based in different simulators and with
different settings ... right now at a glance I cannot see that at all ... I want to be able to see the rerun io things
that show the playbacks for the various trajectories." Spec: the KPI-VIEW brief's "Rig track page acceptance"
(bam_ws src/dev/bam_rig_loop/briefs/KPI-VIEW.md) and this file.

The rulers are copies of the two reference outputs, under tests/fixtures/rig_kpis/ (sha256 pinned below; never a live
path):

- ``api-export/kpi_table.json`` + ``kpi_table.csv``: bam_deployments contract v2.5 ``export``, 22 rows (deployment x
  backend x settings), cache stamp cf574129... over 293 cached runs; from the KPI-table lane's reference
  (/home/bam/.cache/rig-kpi-build/kpi-table/export-demo/api-export/). Its rows equal the live
  /archive/datasets/bam_rig/api-export/ of 2026-10-06 12:02 row for row.
- ``playbacks/index.json``: the ``bam_runtime.playback`` batch index, 57 CAN 12 real runs in 13 sessions, 15 with twin
  re-runs (V0, V1, V1-f2308e5f); from the playback lane's reference (.../playback/pt/green_ref/playback_batch0/
  playbacks/). The 75 MB of .rrd files are not copied: each test makes empty stand-ins in a temporary folder.

Hand-checked against the export (python over kpi_table.json, 2026-10-06): the CAN 12 real row at the newest twin's own
setting (twin V1-f2308e5f, ff_fb, gravity, torque cap 6.3754 N·m) is ``real|ff_fb|4f5b9571ff``, 26 real runs: tracking
RMS 0.04582706 rad = 2.626°, p95 4.682°, feedback torque proxy 0.341 N·m, floor 0.610°; the newest twin's held-out gap
is 0.639° (gate 0.8° from ladder.json TW2) against V0's 3.526°; the newest real row ends 2026-07-29, 69 days before
2026-10-06.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vibetracks import sources as sources_module
from vibetracks.dashboard import registry
from vibetracks.dashboard.adapters import base, rig
from vibetracks.dashboard.registry import WorkTrack

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rig_kpis"
FIXTURE_SHA256 = {
    "api-export/kpi_table.json": "8d456c4b7d60d1f3d6751fa81eb28ba330a04101f9694626af326cd9b727464d",
    "api-export/kpi_table.csv": "e093aaf7219eb454f1fb540dfaf330b7eaadb1da52eb65eabc9e19c9cc6b1823",
    "playbacks/index.json": "5dccb0ab1147d5786b6e18a0b5d1532893f7da8716ae6222e2cb4e7bb609b472",
}
STAMP = "cf574129fdabbeea449148e606f972703edb272a9c94dfa3861b3d96fa2fe2a7"
PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=PDT)

ROBOT = ["real_tracking_rms", "real_tracking_p95", "feedback_torque_proxy", "twin_fidelity_gap", "floor_real_vs_real",
         "days_since_real_run"]
LOOP = ["rungs_green", "packages_landed", "audits", "elapsed_h", "disk_pct", "open_questions"]
NEW_KEYS = {"rig_kpi_table": "input", "rig_playbacks": "input", "rig_rerun_viewer": "input", "rig_kpi_docs": "evidence",
            "rig_living_report": "evidence"}
HEADLINE_REAL = "real|ff_fb|4f5b9571ff"
HEADLINE_TWIN = "mujoco_twin_replay:V1-f2308e5f|ff_fb|bb945462de"
BASELINE_TWIN = "mujoco_twin_replay:V0|ff_fb|44bce2c259"
RIG_LOOP_BRANCH = "claude/rig-loop-work-continue-cb3c52"
WORKTREE = "/home/bam/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52"
# A clock time a person reads must carry its zone (ADAPTERS.md truth rule 6); machine ISO fields copied verbatim from
# the export and the index (start, end, started_at, scanned_at, generated_at) are not text a person reads.
BARE_TIME = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])(?!\s?(?:[A-Z]{2,5}\b|UTC[+-]))")
MACHINE_KEYS = frozenset({"start", "end", "started_at", "scanned_at", "generated_at", "when", "since", "date", "ts",
                          "path", "value", "provenance", "media", "rows", "command", "rrd", "file", "video_path", "dir",
                          "json", "csv", "index", "viewer", "source", "evidence", "freshness", "registry"})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event(ts: str, wave: int, kind: str, subject: str, status: str, detail: str = "") -> dict:
    return {"ts": ts, "wave": wave, "kind": kind, "subject": subject, "status": status, "detail": detail,
            "commit": None, "evidence": None}


def _strings(node, where=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in MACHINE_KEYS:
                yield from _strings(value, f"{where}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{where}/{index}")
    elif isinstance(node, str):
        yield where, node


class FixtureGuardTest(unittest.TestCase):
    def test_the_fixtures_are_the_reference_outputs(self) -> None:
        for name, digest in FIXTURE_SHA256.items():
            self.assertEqual(_sha(FIXTURES / name), digest, f"{name} is not the pinned reference output")
        export = json.loads((FIXTURES / "api-export/kpi_table.json").read_text(encoding="utf-8"))
        self.assertEqual((export["schema"], export["contract"], export["cache"]["sha256"], len(export["rows"])),
                         ("bam-deployments/kpi-table/1", "2.5", STAMP, 22))
        index = json.loads((FIXTURES / "playbacks/index.json").read_text(encoding="utf-8"))
        self.assertEqual((index["schema"], index["deployment_id"], len(index["runs"])),
                         ("bam-playback-index/1", "can12-pendulum-10to1", 57))


class RigKpisTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.loop = root / "bam_rig_loop"
        self.fixtures_dir = root / "fixtures"
        self.cache = root / "cache"
        self.audits = root / "audits"
        for folder in (self.loop, self.fixtures_dir, self.cache, self.audits):
            folder.mkdir()
        self.write(self.loop / "loop-status.json", {
            "schema": "loop-status/1", "loop": "rig", "generated_at": "2026-10-06T11:30:00-07:00",
            "tick": {"kind": "wave", "n": 2, "phase": "running", "head": "abc1234"},
            # WHY 10 and a ladder date of 09-22: days since a real run must come from the KPI table's rows (07-29),
            # so a build that still reads loop-status or ladder.json gives a different number and fails.
            "rate": {"rungs_moved_per_tick": [0, 1], "product_rungs_moved": 2, "hours_spent": 30.0, "days_since_real_row": 10},
            "where": [], "now": [], "next": ["Bench window 1"], "needs_you": [], "blockers": ["No rig attached"], "links": {},
        })
        events = [
            _event("2026-10-01T10:00:00-07:00", 0, "wave_started", "bootstrap", "running"),
            _event("2026-10-01T10:10:00-07:00", 0, "rung_status_changed", "A0", "green", "dashboard live"),
            _event("2026-10-01T11:00:00-07:00", 0, "wave_finished", "bootstrap", "finished"),
            _event("2026-10-02T09:00:00-07:00", 2, "wave_started", "tick-2", "running"),
            _event("2026-10-02T10:00:00-07:00", 2, "lane_status", "P1", "landed", "landed"),
            _event("2026-10-02T10:05:00-07:00", 2, "audit", "P1", "SOUND", "closure"),
            _event("2026-10-02T11:00:00-07:00", 2, "note", "disk", "freed", "Disk / at 78% (194 GB free)"),
        ]
        (self.loop / "loop_events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        self.write(self.loop / "ladder.json", {
            "schema": "rig-ladder/1", "last_real_run": "2026-09-22",
            "axes": [{"id": "A", "rungs": [{"id": "A0", "title": "start", "status": "green", "packages": []},
                                           {"id": "A1", "title": "one", "status": "missing", "packages": ["P1"]}]},
                     {"id": "TWIN", "rungs": [{"id": "TW2", "title": "Two-knob twin ≤ 0.8° held-out", "status": "green",
                                               "packages": []}]}],
            "packages": [{"id": "P1", "title": "first", "rung": "A1", "status": "landed", "updated": "2026-10-02T10:00:00-07:00"}],
        })
        self.write(self.loop / "triage.json", {"schema": "bam-triage/1", "items": [
            {"triage_id": "T2", "status": "open", "title": "Flash diff", "default": "No default: nothing is flashed", "blocks": ["BN1"]}]})
        (self.loop / "ROADMAP.md").write_text("1. **Preflight:** `/` under 92% (`df -h /`)\n", encoding="utf-8")

        # The two reference outputs, copied so a test may remove or corrupt them.
        self.export = root / "api-export"
        shutil.copytree(FIXTURES / "api-export", self.export)
        self.export_doc = json.loads((self.export / "kpi_table.json").read_text(encoding="utf-8"))
        self.batch = root / "rig-playbacks"
        self.batch.mkdir()
        self.videos = root / "videos"
        self.videos.mkdir()
        index = json.loads((FIXTURES / "playbacks/index.json").read_text(encoding="utf-8"))
        # WHY rewritten: the fixture's mp4 paths are live bam_ws paths; each points at a stand-in here instead. The
        # first listed video is left absent, so "listed but gone" is exercised; the first run's .rrd is absent too.
        listed = [run for run in index["runs"] if run["video_path"]]
        self.gone_video_run = listed[0]["run_id"]
        for run in listed:
            stand_in = self.videos / (run["run_id"].replace("/", "__") + ".mp4")
            run["video_path"] = str(stand_in)
            if run["run_id"] != self.gone_video_run:
                stand_in.write_bytes(b"\x00")
        self.gone_rrd_run = index["runs"][0]["run_id"]
        for run in index["runs"]:
            if run["run_id"] != self.gone_rrd_run:
                (self.batch / run["file"]).write_bytes(b"")
        self.write(self.batch / "index.json", index)
        self.index = index
        # The viewer lives in bam_runtime/.venv/bin (its project is where the playback command runs); the KPI doc lives in
        # bam_deployments (its project is where the export command runs).
        self.viewer = root / "bam_runtime" / ".venv" / "bin" / "rerun"
        self.viewer.parent.mkdir(parents=True)
        self.viewer.write_text("#!/bin/sh\n", encoding="utf-8")
        self.docs = root / "bam_deployments" / "KPIS.md"
        self.docs.parent.mkdir()
        self.docs.write_text("# Rig KPIs\n", encoding="utf-8")
        self.report = root / "rig-loop-2026-10-04.html"
        self.report.write_text("<!doctype html><title>rig loop</title>", encoding="utf-8")

        self.sources = {"rig_loop_status": str(self.loop / "loop-status.json"), "rig_events": str(self.loop / "loop_events.jsonl"),
                        "rig_ladder": str(self.loop / "ladder.json"), "deployments_fixtures_dir": str(self.fixtures_dir),
                        "rig_deployments_cache": str(self.cache), "rig_triage": str(self.loop / "triage.json"),
                        "rig_roadmap": str(self.loop / "ROADMAP.md"), "rig_audits_dir": str(self.audits),
                        "rig_kpi_table": str(self.export), "rig_playbacks": str(self.batch),
                        "rig_rerun_viewer": str(self.viewer), "rig_kpi_docs": str(self.docs),
                        "rig_living_report": str(self.report)}
        self.work_track = WorkTrack(id="rig", title="Sim to Real", status="running", priority=2, owner=None, adapter="rig",
                                    sources=list(self.sources), roadmap=None, children=["can12", "can16"],
                                    note_path="/tmp/rig.md", revision="r1")
        patcher = mock.patch.object(rig, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def write(path: Path, payload) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def track(self) -> dict:
        return rig.build_track(self.work_track, dict(self.sources))

    @staticmethod
    def kpi(track: dict, kpi_id: str) -> dict:
        return next(k for k in track["kpis"] if k["id"] == kpi_id)

    def row(self, period: str) -> dict:
        return next(r for r in self.export_doc["rows"] if r["period"] == period)

    def scale(self, key: str) -> float:
        return next(d["scale"] for d in self.export_doc["kpi_defs"] if d["key"] == key)

    # ------------------------------------------------------------------------------------------- sources

    def test_reads_and_the_note_declare_the_five_new_inputs(self) -> None:
        for key, role in NEW_KEYS.items():
            self.assertEqual(rig.READS.get(key), role, key)
        note = registry.read_registry(REPO / "workspace").by_id("rig")
        self.assertIsNotNone(note)
        self.assertEqual(sorted(note.sources), sorted(rig.READS), "rig.md vibe-sources must name exactly READS")
        for key in NEW_KEYS:
            self.assertIn(key, sources_module.WORKTRACK_SOURCES, f"{key} is appended to WORKTRACK_SOURCES")
        # appended, never renamed: every key the rig read before is still there
        for key in ("rig_loop_status", "rig_events", "rig_ladder", "rig_triage", "rig_roadmap", "rig_deployments_cache",
                    "rig_audits_dir", "deployments_fixtures_dir"):
            self.assertIn(key, rig.READS)

    def test_sources_resolve_to_the_live_locations(self) -> None:
        sources_module._WORKTREE_CACHE.clear()
        loaded = sources_module.load_sources(Path(self.tmp.name) / "no-sources.json")
        self.assertEqual(loaded["rig_kpi_table"], "/archive/datasets/bam_rig/api-export")
        self.assertEqual(loaded["rig_playbacks"], loaded["reports_media_dir"] + "/rig-playbacks-2026-10-06")
        self.assertEqual(loaded["rig_living_report"], "/home/bam/bam_ws/reports/rig-loop-2026-10-04.html")
        self.assertTrue(loaded["rig_kpi_docs"].endswith("/src/dev/bam_deployments/KPIS.md"), loaded["rig_kpi_docs"])
        self.assertTrue(loaded["rig_rerun_viewer"].endswith("/src/core/mdp/bam_runtime/.venv/bin/rerun"), loaded["rig_rerun_viewer"])
        for key in NEW_KEYS:
            self.assertTrue(Path(loaded[key]).is_absolute(), key)

    def test_rig_loop_dir_resolves_through_git_like_kinsim(self) -> None:
        raw = sources_module.DEFAULT_SOURCES["rig_loop_dir"]
        self.assertTrue(raw.startswith(f"@worktree:/home/bam/bam_ws:{RIG_LOOP_BRANCH}:src/dev/bam_rig_loop|"), raw)
        porcelain = (f"worktree /x/main\nHEAD 1\nbranch refs/heads/main\n\nworktree /x/rig-lane\nHEAD 2\n"
                     f"branch refs/heads/{RIG_LOOP_BRANCH}\n")

        class Done:
            stdout = porcelain

        sources_module._WORKTREE_CACHE.clear()
        with mock.patch.object(sources_module.subprocess, "run", lambda *a, **k: Done()):
            moved = sources_module.load_sources(Path(self.tmp.name) / "no-sources.json")
        sources_module._WORKTREE_CACHE.clear()
        self.assertEqual(moved["rig_loop_dir"], "/x/rig-lane/src/dev/bam_rig_loop")
        self.assertEqual(moved["rig_loop_status"], "/x/rig-lane/src/dev/bam_rig_loop/loop-status.json")
        self.assertEqual(moved["rig_kpi_docs"], "/x/rig-lane/src/dev/bam_deployments/KPIS.md")
        self.assertEqual(moved["rig_rerun_viewer"], "/x/rig-lane/src/core/mdp/bam_runtime/.venv/bin/rerun")

        class Gone:
            stdout = "worktree /x/main\nHEAD 1\nbranch refs/heads/main\n"

        with mock.patch.object(sources_module.subprocess, "run", lambda *a, **k: Gone()):
            fallback = sources_module.load_sources(Path(self.tmp.name) / "no-sources.json")
        sources_module._WORKTREE_CACHE.clear()
        self.assertEqual(fallback["rig_loop_dir"], f"{WORKTREE}/src/dev/bam_rig_loop")

    # ------------------------------------------------------------------------------------------- headline

    def test_robot_kpis_lead_and_the_loop_folds_away(self) -> None:
        track = self.track()
        self.assertEqual(base.problems(track), [])
        self.assertEqual([k["id"] for k in track["kpis"]], ROBOT + LOOP)
        self.assertEqual(track["north_star"], "real_tracking_rms")
        self.assertEqual([k.get("group") for k in track["kpis"]], ["robot"] * 6 + ["loop_health"] * 6)
        self.assertEqual([(g["id"], g["label"], g["collapsed"]) for g in track["kpi_groups"]],
                         [("robot", "Robot KPIs", False), ("loop_health", "Loop health", True)])
        for gone in ("twin_gap", "days_since_real"):  # superseded by the export's twin gap and days since a real run
            self.assertNotIn(gone, [k["id"] for k in track["kpis"]])

    def test_headline_values_equal_the_export_exactly(self) -> None:
        track = self.track()
        ids = [it["id"] for it in track["iterations"]]
        self.assertEqual(ids, ["T0", "T1", "T2"])
        real, twin = self.row(HEADLINE_REAL), self.row(HEADLINE_TWIN)
        expected = {key: real["kpis"][key] * self.scale(key)
                    for key in ("real_tracking_rms", "real_tracking_p95", "feedback_torque_proxy", "floor_real_vs_real")}
        expected["twin_fidelity_gap"] = twin["kpis"]["twin_fidelity_gap"] * self.scale("twin_fidelity_gap")
        for key, value in expected.items():
            kpi = self.kpi(track, key)
            latest = kpi["values"][-1]
            self.assertEqual(latest["iteration"], "T2", key)
            self.assertEqual(latest["value"], value, f"{key}: the export's value x its kpi_defs scale, never re-derived")
            self.assertTrue(latest["measured"], key)
            for earlier in kpi["values"][:-1]:  # the export keeps no per-tick history: earlier ticks say so
                self.assertIsNone(earlier["value"], key)
                self.assertFalse(earlier["measured"], key)
                self.assertTrue(earlier["note"], key)
        # the same numbers, hand-checked against the export (module docstring)
        self.assertEqual({key: round(value, 3) for key, value in expected.items()},
                         {"real_tracking_rms": 2.626, "real_tracking_p95": 4.682, "feedback_torque_proxy": 0.341,
                          "floor_real_vs_real": 0.61, "twin_fidelity_gap": 0.639})
        for key in ("real_tracking_rms", "real_tracking_p95", "feedback_torque_proxy"):
            self.assertEqual(self.kpi(track, key)["values"][-1]["n"], 26, key)
            self.assertEqual(self.kpi(track, key)["unit"], "N·m" if key == "feedback_torque_proxy" else "deg")
            self.assertIn("07-29", self.kpi(track, key)["status"]["word"])
            self.assertEqual(self.kpi(track, key)["status"]["tone"], "stale")  # 69 days old
        for key in ROBOT[:5]:
            label = next(d["label"] for d in self.export_doc["kpi_defs"] if d["key"] == key)
            self.assertEqual(self.kpi(track, key)["label"], f"{label} · CAN 12")
        self.assertIn("(proxy)", self.kpi(track, "feedback_torque_proxy")["label"])

    def test_twin_gap_carries_its_gate_and_its_v0_baseline(self) -> None:
        kpi = self.kpi(self.track(), "twin_fidelity_gap")
        self.assertEqual(kpi["target"], {"value": 0.8, "kind": "gate", "label": "TW2 gate ≤ 0.8°"})
        base_row = self.row(BASELINE_TWIN)
        self.assertEqual(kpi["baseline"]["value"], base_row["kpis"]["twin_fidelity_gap"] * self.scale("twin_fidelity_gap"))
        self.assertEqual(kpi["baseline"]["label"], "twin V0")
        self.assertTrue(kpi["status"]["word"].startswith("under gate"), kpi["status"]["word"])
        self.assertIn("V1-f2308e5f", kpi["status"]["word"])
        floor = self.kpi(self.track(), "floor_real_vs_real")
        self.assertEqual(floor["target"]["kind"], "descriptive")  # a floor describes, never judges (truth rule 4)
        self.assertEqual(floor["direction"], "info")

    def test_days_since_a_real_run_from_the_exports_dates(self) -> None:
        kpi = self.kpi(self.track(), "days_since_real_run")
        # T0's last event is 10-01, T1 has no event, T2 is today (10-06); the newest real row ends 2026-07-29
        self.assertEqual([v["value"] for v in kpi["values"]], [64, None, 69])
        self.assertTrue(kpi["values"][1]["note"])
        self.assertEqual(kpi["status"]["tone"], "warn")
        self.assertIn("69 days", kpi["status"]["word"])

    def test_the_headline_row_rule(self) -> None:
        # Rule 1: the real row at the newest twin's own setting, even when another real row has more runs.
        doc = json.loads((self.export / "kpi_table.json").read_text(encoding="utf-8"))
        bigger = next(r for r in doc["rows"] if r["period"] == "real|ff_fb|a69eef4352")
        bigger["counts"]["real"] = 40
        self.write(self.export / "kpi_table.json", doc)
        track = self.track()
        self.assertEqual(track["kpi_table"]["rows"][track["kpi_table"]["headline"]["real_row"]]["period"], HEADLINE_REAL)
        self.assertEqual(track["kpi_table"]["headline"]["rule"], "twin setting")
        # Rule 2: with no real row at the twin's setting, the real row with the most real runs.
        for row in doc["rows"]:
            if row["backend"] == "mujoco_twin_replay":
                row["settings"] = dict(row["settings"], torque_cap_nm=999.0)
        self.write(self.export / "kpi_table.json", doc)
        track = self.track()
        self.assertEqual(track["kpi_table"]["rows"][track["kpi_table"]["headline"]["real_row"]]["period"], "real|ff_fb|a69eef4352")
        self.assertEqual(track["kpi_table"]["headline"]["rule"], "most real runs")
        self.assertEqual(self.kpi(track, "real_tracking_rms")["values"][-1]["value"],
                         bigger["kpis"]["real_tracking_rms"] * self.scale("real_tracking_rms"))
        self.assertEqual(self.kpi(track, "real_tracking_rms")["values"][-1]["n"], 40)

    # ------------------------------------------------------------------------------------------- the table

    def test_the_table_is_the_export_verbatim(self) -> None:
        table = self.track()["kpi_table"]
        self.assertEqual(table["state"], "ok")
        self.assertEqual(table["rows"], self.export_doc["rows"])
        self.assertEqual(table["kpi_defs"], self.export_doc["kpi_defs"])
        self.assertEqual(table["cache"], self.export_doc["cache"])
        self.assertEqual(table["cache"]["sha256"], STAMP)
        self.assertEqual((table["contract"], table["generated_at"]), ("2.5", self.export_doc["generated_at"]))
        self.assertEqual(table["generated_label"], base.local_time(self.export_doc["generated_at"]))
        self.assertEqual(table["csv"], str(self.export / "kpi_table.csv"))
        self.assertEqual(table["settings_keys"], ["torque_cap_nm", "mounting", "kp", "kd", "friction_ff",
                                                  "coulomb_friction_nm", "plant"])
        self.assertEqual(table["deployments"], {"can12-pendulum-10to1": "can12", "can16-bench-rotor": "can16"})
        headline = table["headline"]
        self.assertEqual((table["rows"][headline["real_row"]]["period"], table["rows"][headline["twin_row"]]["period"],
                          table["rows"][headline["twin_baseline_row"]]["period"]), (HEADLINE_REAL, HEADLINE_TWIN, BASELINE_TWIN))
        self.assertEqual(table["command"], f"env -u VIRTUAL_ENV uv run --directory {self.docs.parent} python -m bam_deployments "
                                           f"export {self.export}")
        kinematic = [r for r in table["rows"] if r["backend"] == "kinematic"]
        self.assertEqual(len(kinematic), 2)
        self.assertTrue(all(r["na_reason"] for r in kinematic))

    def test_a_missing_export_says_so_with_the_command_that_makes_it(self) -> None:
        shutil.rmtree(self.export)
        track = self.track()
        self.assertEqual(base.problems(track), [])
        table = track["kpi_table"]
        self.assertEqual((table["state"], table["rows"]), ("missing", []))
        self.assertIn(str(self.export), table["message"])
        self.assertTrue(table["command"].endswith(f"python -m bam_deployments export {self.export}"), table["command"])
        self.assertEqual(track["north_star"], "real_tracking_rms")
        for key in ROBOT:
            kpi = self.kpi(track, key)
            self.assertEqual([v["value"] for v in kpi["values"]], [None, None, None], key)
            self.assertFalse(any(v["measured"] for v in kpi["values"]), key)
            self.assertIn("No KPI table export", kpi["values"][-1]["note"], key)
            self.assertTrue(kpi["status"]["word"].startswith("not measured"), key)
        self.assertEqual([k["id"] for k in track["kpis"]][6:], LOOP)  # the loop's numbers still report
        self.assert_no_none_text(track)

    def test_an_unreadable_export_is_not_a_table(self) -> None:
        for content, word in (("{not json", "unreadable"), (json.dumps({"schema": "something-else/1", "rows": []}), "schema")):
            (self.export / "kpi_table.json").write_text(content, encoding="utf-8")
            track = self.track()
            self.assertEqual(base.problems(track), [])
            self.assertEqual(track["kpi_table"]["state"], "unreadable")
            self.assertEqual(track["kpi_table"]["rows"], [])
            self.assertIn(word, track["kpi_table"]["message"])
            self.assertIsNone(self.kpi(track, "real_tracking_rms")["values"][-1]["value"])

    # ------------------------------------------------------------------------------------------- playbacks

    def test_the_playback_entries_equal_index_json(self) -> None:
        track = self.track()
        playbacks = track["playbacks"]
        self.assertEqual(playbacks["state"], "ok")
        self.assertEqual((playbacks["viewer"], playbacks["viewer_exists"], playbacks["count"]), (str(self.viewer), True, 57))
        entries = [entry for group in playbacks["groups"] for entry in group["runs"]]
        fields = ("run_id", "trajectory", "session", "started_at", "twin_versions", "twin_vs_real_rms_rad", "video_path",
                  "size_bytes", "file")
        self.assertEqual([{f: e[f] for f in fields} for e in entries], [{f: run[f] for f in fields} for run in self.index["runs"]])
        sessions = list(dict.fromkeys(run["session"] for run in self.index["runs"]))
        self.assertEqual([g["id"] for g in playbacks["groups"]], sessions)
        self.assertEqual(len(sessions), 13)
        self.assertEqual(sum(g["twin_runs"] for g in playbacks["groups"]), 15)
        ladder = next(g for g in playbacks["groups"] if g["id"] == "one_dof_gravity_amplitude_ladder_2026-07-29")
        self.assertEqual((ladder["label"], ladder["count"], ladder["twin_runs"]), ("07-29 gravity amplitude ladder", 15, 15))
        for entry in entries:
            rrd = str(self.batch / entry["file"])
            self.assertEqual(entry["rrd"], rrd)
            self.assertEqual(entry["command"], f"{self.viewer} {rrd}")  # one line: the viewer, a space, the recording
            self.assertNotIn("\n", entry["command"])
            self.assertEqual(entry["rrd_exists"], entry["run_id"] != self.gone_rrd_run)
            if entry["video_path"] and entry["run_id"] != self.gone_video_run:
                media = track["media"][entry["video"]]
                self.assertEqual((media["kind"], media["path"]), ("video", entry["video_path"]))
            else:
                self.assertIsNone(entry["video"], entry["run_id"])
        self.assertEqual(sum(1 for e in entries if e["video"]), 43)  # 44 listed, one stand-in left absent
        chirp = next(e for e in entries if e["run_id"].endswith("/chirp_090deg__real__ff_fb"))
        self.assertEqual(chirp["twin_versions"], ["V0", "V1", "V1-f2308e5f"])
        self.assertEqual(round(chirp["twin_vs_real_rms_rad"]["V0"], 10), 0.0676669668)

    def test_missing_playbacks_say_so_with_the_command_that_makes_them(self) -> None:
        shutil.rmtree(self.batch)
        track = self.track()
        self.assertEqual(base.problems(track), [])
        playbacks = track["playbacks"]
        self.assertEqual((playbacks["state"], playbacks["groups"], playbacks["count"]), ("missing", [], 0))
        self.assertIn(str(self.batch), playbacks["message"])
        self.assertEqual(playbacks["command"], f"env -u VIRTUAL_ENV uv run --directory {self.viewer.parents[2]} --extra viz "
                                               f"python -m bam_runtime.playback can12-pendulum-10to1 --out {self.batch}")

    def test_an_unreadable_index_is_not_a_list(self) -> None:
        for content, word in (("{not json", "unreadable"), (json.dumps({"schema": "other/1", "runs": []}), "schema"),
                              (json.dumps({"schema": "bam-playback-index/1"}), "runs")):
            (self.batch / "index.json").write_text(content, encoding="utf-8")
            playbacks = self.track()["playbacks"]
            self.assertEqual((playbacks["state"], playbacks["groups"], playbacks["count"]), ("unreadable", [], 0))
            self.assertIn(word, playbacks["message"])

    # ------------------------------------------------------------------------------------------- links, rules

    def test_links_lead_with_the_kpi_doc_the_csv_and_the_living_report(self) -> None:
        track = self.track()
        first = track["links"][:3]
        self.assertEqual([link["label"] for link in first], ["KPI doc (KPIS.md)", "KPI table CSV", "Living report"])
        self.assertEqual((first[0]["kind"], track["media"][first[0]["media"]]["path"]), ("media", str(self.docs)))
        self.assertEqual(first[1], {"label": "KPI table CSV", "kind": "path", "value": str(self.export / "kpi_table.csv")})
        self.assertEqual((first[2]["kind"], track["media"][first[2]["media"]]["kind"]), ("media", "html"))
        self.docs.unlink()
        doc = self.track()["links"][0]
        self.assertEqual((doc["kind"], doc["value"]), ("path", str(self.docs)))
        self.assertIn("not written yet", doc["label"])

    def test_undeclared_inputs_are_missing_never_looked_up(self) -> None:
        for key in NEW_KEYS:
            del self.sources[key]
        track = self.track()
        self.assertEqual(base.problems(track), [])
        self.assertEqual(track["kpi_table"]["state"], "missing")
        self.assertIn("rig_kpi_table is not declared", track["kpi_table"]["message"])
        self.assertEqual(track["playbacks"]["state"], "missing")
        self.assertIn("rig_playbacks is not declared", track["playbacks"]["message"])
        self.assertFalse(any(link["label"].startswith(("KPI doc", "KPI table CSV", "Living report")) for link in track["links"]))

    def test_it_opens_only_what_it_is_handed(self) -> None:
        roots = [(os.path.realpath(path), rig.DEPTH.get(key, 1)) for key, path in self.sources.items()]
        opened: list[str] = []

        def hook(event, args):
            if event in ("open", "os.scandir", "os.listdir") and args and isinstance(args[0], (str, bytes, os.PathLike)):
                opened.append(os.path.realpath(os.fsdecode(os.fspath(args[0]))))

        recording = [True]

        def guarded(event, args):
            if recording[0]:
                hook(event, args)

        sys.addaudithook(guarded)
        try:
            self.track()
        finally:
            recording[0] = False
        tmp = os.path.realpath(self.tmp.name)
        stray = [path for path in opened if path.startswith(tmp) and not any(
            path == root or (path.startswith(root.rstrip(os.sep) + os.sep) and path[len(root) + 1:].count(os.sep) < depth)
            for root, depth in roots)]
        self.assertEqual(stray, [])
        self.assertIn(os.path.realpath(self.export / "kpi_table.json"), opened)
        self.assertIn(os.path.realpath(self.batch / "index.json"), opened)
        self.assertFalse(any(path.endswith(".rrd") or path.endswith(".mp4") or path.endswith(".csv") for path in opened),
                         "the recordings, videos and CSV are linked, never read")

    def test_human_times_say_their_zone_and_nothing_reads_none(self) -> None:
        track = self.track()
        for key in ("kpi_table", "playbacks", "kpis"):
            for where, text in _strings(track[key], key):
                match = BARE_TIME.search(text)
                self.assertIsNone(match, f"{where}: a clock time with no zone in {text!r}")
        self.assert_no_none_text(track)

    def assert_no_none_text(self, track: dict) -> None:
        """No string the page shows says Python's None ("rule: None", "of None"); provenance and notes included. Only the
        export's own rows and defs, copied verbatim, are not walked."""

        def walk(node, where):
            if isinstance(node, dict):
                for key, value in node.items():
                    if not (where == "rig/kpi_table" and key in ("rows", "kpi_defs")):
                        walk(value, f"{where}/{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{where}/{index}")
            elif isinstance(node, str):
                self.assertNotRegex(node, r"\bNone\b", where)

        walk(track, "rig")


if __name__ == "__main__":
    unittest.main()
