"""The bam_loops adapter against the real 2026-10-03 snapshot.

    python3 -m unittest tests/test_dashboard_adapter.py      (from the repo root)

Every expected number below is copied from facts.md (the checked summary of the snapshot), so a test fails when the
adapter's derivation drifts from what was verified by hand.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard import build as build_module
from vibetracks.dashboard.adapters import bam_loops

SNAPSHOT = build_module.SNAPSHOT_ORIGIN
CURRICULUM = build_module.CURRICULUM_ORIGIN


@unittest.skipUnless(SNAPSHOT.is_file(), f"snapshot not on this machine: {SNAPSHOT}")
class AdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = Path(cls.tmp.name)
        cls.projection = build_module.build(cls.home)
        cls.tracks = {t["id"]: t for t in cls.projection["tracks"]}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def kpi(self, track: str, kpi_id: str) -> dict:
        return next(k for k in self.tracks[track]["kpis"] if k["id"] == kpi_id)

    def series(self, track: str, kpi_id: str) -> list:
        return [v["value"] for v in self.kpi(track, kpi_id)["values"]]

    # ---- shape
    def test_schema_and_sources_copied_into_the_data_home(self) -> None:
        self.assertEqual(self.projection["schema"], "vibetracks-dashboard/1")
        self.assertFalse(self.projection["source"]["live"])
        self.assertIn("TODO(live)", self.projection["source"]["todo"])
        self.assertTrue((self.home / "sources" / build_module.SNAPSHOT_NAME).is_file())
        self.assertTrue(self.projection["source"]["snapshot"].startswith(str(self.home)))
        self.assertTrue((self.home / "projection.json").is_file())

    def test_tracks(self) -> None:
        self.assertEqual(list(self.tracks), ["kinsim", "rig", "can12", "can16"])
        self.assertEqual(self.tracks["can12"]["parent"], "rig")
        self.assertEqual(self.tracks["can16"]["kind"], "deployment")
        for track in self.tracks.values():
            ids = [it["id"] for it in track["iterations"]]
            self.assertIn(track["north_star"], [k["id"] for k in track["kpis"]])
            for kpi in track["kpis"]:
                self.assertEqual([v["iteration"] for v in kpi["values"]], ids, f"{track['id']}.{kpi['id']} is not aligned")
                self.assertRegex(kpi["slot"], r"^S[1-7]$")
                self.assertIn(kpi["direction"], ("higher", "lower", "info", "count"))
                self.assertIn(kpi["status"]["tone"], ("ok", "warn", "risk", "stale", "muted"))
                for v in kpi["values"]:
                    self.assertEqual(v["measured"], v["value"] is not None)
                    if v["value"] is None:
                        self.assertTrue(v["note"], f"{track['id']}.{kpi['id']}@{v['iteration']}: a gap must say why")

    # ---- facts.md numbers
    def test_kinsim_burn_up_and_weighted(self) -> None:
        self.assertEqual([it["id"] for it in self.tracks["kinsim"]["iterations"]], ["start", "W1", "W2", "W3"])
        self.assertEqual(self.series("kinsim", "rungs_green"), [4, 7, 7, 16])
        self.assertEqual(self.series("kinsim", "weighted_capability")[-1], 25)
        self.assertEqual(self.kpi("kinsim", "weighted_capability")["values"][-1]["of"], 118)
        self.assertEqual(self.series("kinsim", "bt1_feasible"), [None, None, None, 73.4])
        self.assertEqual(self.series("kinsim", "elapsed_h"), [None, None, 22.2, 9.3])
        self.assertEqual([(v["value"], v["of"]) for v in self.kpi("kinsim", "packages_landed")["values"][1:]], [(7, 9), (2, 6), (7, 7)])
        self.assertEqual(self.series("kinsim", "rungs_moved")[1:], [3, 0, 9])
        self.assertEqual([n["id"] for n in self.tracks["kinsim"]["needs_you"] if n["blocks"]], ["T14", "T46", "T47", "T48"])

    def test_rig_burn_up_and_twin_gap(self) -> None:
        self.assertEqual(self.series("rig", "rungs_green"), [1, 5, 5, 6])
        twin = self.kpi("rig", "tw2_twin_gap")
        self.assertEqual(twin["baseline"]["value"], 3.526)
        self.assertEqual(twin["values"][1]["value"], 0.6394)
        self.assertEqual(twin["target"]["value"], 0.8)
        self.assertEqual(self.series("rig", "elapsed_h")[-1], 12.2)
        self.assertEqual(self.series("rig", "days_since_real")[-1], 66)
        self.assertEqual([n["id"] for n in self.tracks["rig"]["needs_you"] if n["blocks"]], ["T2", "T4", "T11"])

    def test_deployments(self) -> None:
        can16 = self.tracks["can16"]
        self.assertEqual(self.series("can16", "real_tracking_rms"), [None, 2.775, 4.435, 5.466])
        held = self.kpi("can16", "held_gentle_step_ff_fb_default")
        self.assertEqual([v["value"] for v in held["values"]], [None, 2.78, 2.78, 9.03])
        self.assertEqual(held["status"]["word"], "unconfirmed · repeat needed")
        self.assertEqual(can16["state"]["word"], "Repeat needed")
        self.assertEqual(self.tracks["can12"]["state"]["word"], "Stale")
        floor = self.kpi("can12", "floor_real_vs_real")
        self.assertEqual(floor["target"]["kind"], "descriptive")
        self.assertEqual(floor["target"]["band"][1], 0.7339)

    # ---- the hard rules
    def test_no_status_word_says_regressed_and_no_agent_hours(self) -> None:
        # WHY status words and state only: "regression" is also a corpus tier name (rb0-regression) in the data.
        for track in self.tracks.values():
            words = [track["state"]["word"], track["state"]["detail"]] + [k["status"]["word"] for k in track["kpis"]]
            for word in words:
                self.assertNotIn("regress", word.lower(), f"{track['id']}: {word}")
        text = json.dumps(self.projection, ensure_ascii=False).lower()
        for match in re.finditer(r"agent-hours", text):
            self.assertEqual(text[match.start() - 4: match.start()], "not ", text[match.start() - 60: match.end()])

    def test_n1_changes_read_unconfirmed(self) -> None:
        for track in self.tracks.values():
            for kpi in track["kpis"]:
                measured = [v for v in kpi["values"] if v["measured"]]
                if kpi["id"].startswith("held_") and len(measured) >= 2 and min(measured[-1]["n"], measured[-2]["n"]) <= 1 \
                        and kpi["status"]["word"] not in ("within day band · n = 1", "unchanged · n = 1"):
                    self.assertEqual(kpi["status"]["word"], "unconfirmed · repeat needed")

    # ---- evidence and media
    def test_every_media_reference_resolves_to_an_existing_file(self) -> None:
        media = self.projection["media"]
        self.assertTrue(media)
        for media_id, entry in media.items():
            self.assertRegex(media_id, r"^[a-z0-9][a-z0-9._-]*$")
            self.assertTrue(Path(entry["path"]).is_file(), entry["path"])
        for track in self.tracks.values():
            for items in track["evidence"]["by_iteration"].values():
                for item in items:
                    for ref in item["media"]:
                        self.assertIn(ref["id"], media)
            for link in track["links"]:
                if link["kind"] == "media":
                    self.assertIn(link["media"], media)

    def test_deployment_runs_carry_their_real_videos(self) -> None:
        for track_id, flagged in (("can12", 44), ("can16", 22)):
            runs = [i for items in self.tracks[track_id]["evidence"]["by_iteration"].values() for i in items
                    if i["kind"] == "run" and "twin" not in i["title"].lower()]
            with_real = [i for i in runs if any(m["kind"] == "video" and m["label"].startswith("Real") for m in i["media"])]
            self.assertEqual(len(with_real), flagged, track_id)

    def test_wave_reports_open(self) -> None:
        kinsim = self.tracks["kinsim"]
        for wave in ("W1", "W2", "W3"):
            report = next(i for i in kinsim["evidence"]["by_iteration"][wave] if i["kind"] == "report")
            self.assertEqual(report["media"][0]["kind"], "html")

    def test_value_evidence_points_at_items_of_its_iteration(self) -> None:
        for track in self.tracks.values():
            by_id = {i["id"]: i for items in track["evidence"]["by_iteration"].values() for i in items}
            for kpi in track["kpis"]:
                for v in kpi["values"]:
                    for item_id in v["evidence"]:
                        self.assertEqual(by_id[item_id]["iteration"], v["iteration"])
        bt1 = self.kpi("kinsim", "bt1_feasible")["values"][-1]["evidence"]
        self.assertEqual(bt1, ["bt1-regression-20261003t034736z"])


class ChangeStatusTest(unittest.TestCase):
    def v(self, value: float, n: int) -> dict:
        return {"iteration": "x", "value": value, "n": n, "measured": True}

    def test_n1_is_unconfirmed_never_regressed(self) -> None:
        status = bam_loops.change_status([self.v(2.78, 1), self.v(9.03, 1)], "lower", "deg")
        self.assertEqual(status, {"word": "unconfirmed · repeat needed", "tone": "warn"})

    def test_band_is_descriptive(self) -> None:
        status = bam_loops.change_status([self.v(2.0, 1), self.v(2.5, 1)], "lower", "deg", band=0.734)
        self.assertEqual(status["word"], "within day band · n = 1")

    def test_repeated_change_is_direction_aware(self) -> None:
        self.assertEqual(bam_loops.change_status([self.v(3, 5), self.v(2, 5)], "lower", "deg")["word"], "better than previous")
        self.assertEqual(bam_loops.change_status([self.v(3, 5), self.v(2, 5)], "higher", "%")["word"], "worse than previous")


if __name__ == "__main__":
    unittest.main()
