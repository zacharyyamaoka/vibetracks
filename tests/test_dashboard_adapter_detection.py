"""The detection work-track adapter (vibetracks/dashboard/adapters/detection.py).

    python3 -m unittest tests/test_dashboard_adapter_detection.py      (from the repo root)

Small temp fixtures shaped like the real SpectralWaste repro queue (a lossy queue.log, per-run logs, W&B run
directories, compile_results.PAPER, ladder_data.RUNGS and the plan note's Needs you list), plus one live smoke test that
is skipped when the real queue log is missing.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from vibetracks.dashboard.adapters import base, detection
from vibetracks.dashboard.registry import WorkTrack

LIVE_QUEUE = Path("/home/bam/spectralwaste-segmentation/logs/queue.log")

PAPER = """PAPER = {
    '01_cmx_b0.rgb+hyper.labels_rgb':        ('CMX-B0 RGB-HYPER (hybrid)', 58.2),
    '02_segformer_b0.rgb.labels_rgb':        ('SegFormer-B0 RGB',          48.4),
    '03_mininet.rgb.labels_rgb':             ('MiniNet-v2 RGB',            44.5),
    '04_segformer_b0.hyper.labels_hyper_lt': ('SegFormer-B0 HYPER',        54.3),
    '01r1_cmx_b0.rgb+hyper.labels_rgb':      ('CMX-B0 RGB-HYPER (hybrid) retry1', 58.2),
}
"""

LADDER = '''RUNGS = [
    dict(id="H0", short="Plumbing ruler", gate="coupons 100%"),
    dict(id="H1", short="Published ruler", gate="All 12 Table IV configs within ±2 test mIoU of the paper."),
    dict(id="H2", short="Real class spectra", gate="spectra"),
]
KPIS = [("S1 North star", "a", "b", "c", "d"), ("S2 Frontier gate", "a", "b", "c", "d")]
'''

PLAN = """# Plan

## Needs you

Three decisions.

1. **Data.** The drive is not mounted, and it blocks H1, H2 and H4: mount it. *Default if silent:* the loop runs H0.
2. **Host.** Linux or Windows; H0–H7 never touch the camera.
\t- a reason that is not the question
\t*Default if silent:* Linux.
3. **Start the loop.** The work order is ready. *Default if silent:* nothing starts.

## Next section
"""


def epoch_lines(count: int, *, nan_from: int | None = None, val: float = 0.40) -> str:
    lines = []
    for n in range(count):
        loss = "nan" if nan_from is not None and n >= nan_from else "0.4000"
        lines.append(f"epoch: {n:04d} | train/loss: 0.3000 | val/loss: {loss} | val/miou: {val + n / 1000:.4f}")
    return "\n".join(lines) + "\n"


def work_track() -> WorkTrack:
    return WorkTrack(id="detection", title="Renamed by Zach", status="running", priority=4, owner="test",
                     adapter="detection", sources=["detection_queue_log"], roadmap=None, children=[],
                     note_path="/tmp/detection.md", revision="r1", heartbeat=["detection_queue_log"], stall_hours=24.0)


class Fixture:
    """A temp SpectralWaste repo. Run 01 diverged (NaN), 02 and 03 reproduce, 01r1 lost its START line (the W&B run
    directory dates it), 04 is a hyperspectral run with no DONE line."""

    def __init__(self, root: Path, *, plan: bool = True, ladder: bool = True, hyper_valid: bool = False):
        self.root = root
        repo = root / "spectralwaste-segmentation"
        logs = repo / "logs"
        logs.mkdir(parents=True)
        (repo / "compile_results.py").write_text(PAPER, encoding="utf-8")
        (repo / "run_repro_queue.sh").write_text(f"DATA={root / 'not-mounted'}/spectralwaste\n", encoding="utf-8")
        wandb = repo / "wandb"
        wandb.mkdir()
        (wandb / "run-20260710_234808-r1retry").mkdir()
        queue = [
            "2026-07-10 21:40:29 START 01_cmx_b0.rgb+hyper.labels_rgb",
            "2026-07-10 23:44:18 DONE  01_cmx_b0.rgb+hyper.labels_rgb rc=0 test/miou: 0.3397570252418518",
            "2026-07-10 23:44:18 START 02_segformer_b0.rgb.labels_rgb",
            "2026-07-10 23:52:19 DONE  02_segformer_b0.rgb.labels_rgb rc=0 test/miou: 0.5028871893882751",
            "2026-07-10 23:52:19 START 03_mininet.rgb.labels_rgb",
            "2026-07-11 00:03:33 DONE  03_mininet.rgb.labels_rgb rc=0 test/miou: 0.42700016498565674",
            "2026-07-11 00:03:33 START 04_segformer_b0.hyper.labels_hyper_lt",
        ]
        if hyper_valid:
            queue.append("2026-07-11 01:03:33 DONE  04_segformer_b0.hyper.labels_hyper_lt rc=0 test/miou: 0.5512")
        (logs / "queue.log").write_text("\n".join(queue) + "\n", encoding="utf-8")
        (logs / "01_cmx_b0.rgb+hyper.labels_rgb.log").write_text(
            "wandb: \x1b[1;34mView run\x1b[0m at: https://wandb.ai/me/spectralwaste-repro/runs/cmx01\n"
            + epoch_lines(10, nan_from=4) + "test/loss: 0.42 | test/miou: 0.3397570252418518\n", encoding="utf-8")
        (logs / "01r1_cmx_b0.rgb+hyper.labels_rgb.log").write_text(
            "wandb: View run at https://wandb.ai/me/spectralwaste-repro/runs/r1retry\n" + epoch_lines(2, nan_from=1),
            encoding="utf-8")
        (logs / "02_segformer_b0.rgb.labels_rgb.log").write_text(epoch_lines(10, val=0.50), encoding="utf-8")
        (logs / "03_mininet.rgb.labels_rgb.log").write_text(epoch_lines(10, val=0.47), encoding="utf-8")
        (logs / "04_segformer_b0.hyper.labels_hyper_lt.log").write_text(
            epoch_lines(10 if hyper_valid else 1, val=0.55), encoding="utf-8")
        old = time.mktime((2026, 7, 11, 0, 7, 0, 0, 0, -1))
        for path in logs.iterdir():
            os.utime(path, (old, old))
        self.queue_log = logs / "queue.log"
        self.ladder = root / "ladder_data.py"
        if ladder:
            self.ladder.write_text(LADDER, encoding="utf-8")
            plan_time = time.mktime((2026, 10, 4, 14, 24, 0, 0, 0, -1))
            os.utime(self.ladder, (plan_time, plan_time))
        self.plan = root / "plan.md"
        if plan:
            self.plan.write_text(PLAN, encoding="utf-8")
        reports = root / "reports"
        (reports / "media").mkdir(parents=True)
        (reports / "hyperspectral-roadmap-2026-10-04.html").write_text("<html></html>", encoding="utf-8")
        self.reports_media = reports / "media"

    def sources(self) -> dict[str, str]:
        return {"detection_queue_log": str(self.queue_log), "detection_ladder": str(self.ladder),
                "detection_plan_note": str(self.plan), "reports_media_dir": str(self.reports_media)}


class DetectionAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build(self, **kwargs) -> dict:
        fixture = Fixture(self.root, **kwargs)
        track = detection.build_track(work_track(), fixture.sources())
        self.assertEqual(base.problems(track), [])
        return track

    @staticmethod
    def series(track: dict, kpi_id: str) -> list:
        kpi = next(kpi for kpi in track["kpis"] if kpi["id"] == kpi_id)
        return [value["value"] for value in kpi["values"]]

    def test_runs_become_iterations_in_start_order_with_the_plan_last(self) -> None:
        track = self.build()
        ids = [iteration["id"] for iteration in track["iterations"]]
        # 01r1 has no START line; its W&B run directory (23:48:08) places it between 02 and 03.
        self.assertEqual(ids, ["01", "02", "01r1", "03", "04", "plan-2026-10-04"])
        self.assertEqual(track["iteration"]["unit"], "session")
        markers = {iteration["id"]: iteration["marker"] for iteration in track["iterations"]}
        self.assertIn("invalid · NaN loss in 6 of 10 epochs", markers["01"])
        self.assertIn("reproduced", markers["02"])
        self.assertIn("no DONE line · 1 epoch logged", markers["04"])
        self.assertIn("no run since", markers["plan-2026-10-04"])

    def test_kpis_pin_the_hand_checked_numbers(self) -> None:
        track = self.build()
        self.assertTrue(4 <= len(track["kpis"]) <= 10)
        self.assertEqual(track["north_star"], "hsi_test_miou")
        # 02: 50.29 vs 48.4 (+1.89) and 03: 42.70 vs 44.5 (-1.80) are within ±2; 01 is invalid.
        self.assertEqual(self.series(track, "h1_reproduced"), [0, 1, 1, 2, 2, 2])
        self.assertEqual(self.series(track, "run_test_miou"), [33.98, 50.29, None, 42.7, None, None])
        self.assertEqual(self.series(track, "valid_runs"), [0, 1, 1, 2, 2, 2])
        self.assertEqual(self.series(track, "nan_runs"), [1, 1, 2, 2, 2, 2])
        self.assertEqual(self.series(track, "run_hours")[:2], [2.06, 0.13])
        h1 = next(kpi for kpi in track["kpis"] if kpi["id"] == "h1_reproduced")
        self.assertEqual(h1["target"]["value"], 4)  # the fixture's PAPER has four configs (retries excluded)
        self.assertIn("unconfirmed · repeat needed", h1["status"]["word"])

    def test_no_valid_hyperspectral_value_is_a_gap_with_a_reason_never_a_zero(self) -> None:
        track = self.build()
        north = next(kpi for kpi in track["kpis"] if kpi["id"] == "hsi_test_miou")
        self.assertTrue(all(value["value"] is None and not value["measured"] for value in north["values"]))
        self.assertIn("34.0 not counted", north["values"][0]["note"])
        self.assertEqual(north["target"]["value"], 58.2)
        self.assertEqual(north["status"]["tone"], "warn")
        guardrails = next(kpi for kpi in track["kpis"] if kpi["id"] == "guardrails")
        self.assertTrue(all(value["note"].startswith("not emitted") for value in guardrails["values"]))

    def test_a_valid_hyperspectral_run_lights_the_north_star_as_unconfirmed(self) -> None:
        track = self.build(hyper_valid=True)
        self.assertEqual(self.series(track, "hsi_test_miou")[-2:], [55.12, 55.12])
        north = next(kpi for kpi in track["kpis"] if kpi["id"] == "hsi_test_miou")
        self.assertIn("unconfirmed · repeat needed", north["status"]["word"])

    def test_state_is_planned_and_says_the_loop_has_not_started(self) -> None:
        track = self.build()
        self.assertEqual(track["state"]["word"], "Planned")
        self.assertIn("loop not started", track["state"]["detail"])
        self.assertIn("data drive not mounted", track["state"]["detail"])
        self.assertTrue(track["summary"].startswith("Planned, loop not started"))
        self.assertNotIn("Renamed by Zach", track["summary"])  # the title is the build's, never baked in

    def test_needs_you_from_the_plan_note(self) -> None:
        track = self.build()
        needs = track["needs_you"]
        self.assertEqual([need["id"] for need in needs], ["plan-1", "plan-2", "plan-3"])
        self.assertEqual(needs[0]["blocks"], ["H1", "H2", "H4"])
        self.assertEqual(needs[1]["blocks"], [])  # "H0–H7 never touch the camera" names rungs but holds none
        self.assertEqual(needs[0]["default"], "the loop runs H0.")
        self.assertNotIn("a reason that is not the question", needs[1]["q"])
        self.assertEqual(self.series(track, "needs_you")[-1], 3)

    def test_a_missing_plan_note_makes_needs_unknown_not_zero(self) -> None:
        track = self.build(plan=False)
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})
        self.assertIsNone(self.series(track, "needs_you")[-1])

    def test_a_missing_ladder_leaves_the_frontier_uncomputed(self) -> None:
        track = self.build(ladder=False, plan=False)
        self.assertNotIn("plan-2026-10-04", [iteration["id"] for iteration in track["iterations"]])
        self.assertTrue(all(value is None for value in self.series(track, "h1_reproduced")))
        self.assertEqual(track["state"]["word"], "Idle")

    def test_media_lists_only_files_that_exist(self) -> None:
        track = self.build()
        self.assertEqual(set(track["media"]), {"detection-roadmap-report"})
        for entry in track["media"].values():
            self.assertTrue(Path(entry["path"]).is_file())
        plan_items = track["evidence"]["by_iteration"]["plan-2026-10-04"]
        self.assertIn("roadmap-report", [item["id"] for item in plan_items])

    def test_evidence_links_points_to_their_runs(self) -> None:
        track = self.build()
        first = track["evidence"]["by_iteration"]["01"][0]
        self.assertEqual(first["metrics"]["NaN-loss epochs"], 6)
        self.assertIn("https://wandb.ai/me/spectralwaste-repro/runs/cmx01", [link.get("value") for link in first["links"]])
        north = next(kpi for kpi in track["kpis"] if kpi["id"] == "hsi_test_miou")
        self.assertEqual(north["values"][0]["evidence"], ["run-01"])
        self.assertEqual(north["values"][1]["evidence"], [])  # 02 is RGB-only: not hyperspectral evidence

    def test_a_running_run_reads_running(self) -> None:
        fixture = Fixture(self.root)
        now = time.time()
        os.utime(fixture.queue_log.parent / "04_segformer_b0.hyper.labels_hyper_lt.log", (now, now))
        track = detection.build_track(work_track(), fixture.sources())
        self.assertEqual(base.problems(track), [])
        self.assertEqual(track["state"]["word"], "Running")
        self.assertIn("run 04", track["state"]["detail"])

    def test_a_missing_queue_log_is_not_reporting(self) -> None:
        track = detection.build_track(work_track(), {"detection_queue_log": str(self.root / "nope" / "queue.log")})
        self.assertEqual(base.problems(track), [])
        self.assertEqual(track["state"]["word"], "Not reporting")
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})
        self.assertEqual(track["kpis"], [])


@unittest.skipUnless(LIVE_QUEUE.is_file(), f"live queue log missing: {LIVE_QUEUE}")
class DetectionLiveSmokeTest(unittest.TestCase):
    def test_live_track_is_sound_and_reads_the_july_queue(self) -> None:
        track = detection.build_track(work_track(), {"detection_queue_log": str(LIVE_QUEUE)})
        self.assertEqual(base.problems(track), [])
        first = track["iterations"][0]
        self.assertEqual(first["id"], "01")
        self.assertIn("invalid · NaN loss", first["marker"])
        runs = {kpi["id"]: kpi for kpi in track["kpis"]}
        self.assertEqual(runs["run_test_miou"]["values"][0]["value"], 33.98)
        reproduced = [value["value"] for value in runs["h1_reproduced"]["values"] if value["value"] is not None]
        if reproduced:  # needs the untracked ladder_data.py for the ±tolerance
            self.assertGreaterEqual(reproduced[-1], 2)


if __name__ == "__main__":
    unittest.main()
