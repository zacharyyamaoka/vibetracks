"""The pyblocks work-track adapter, on small temp fixtures plus one live smoke test.

    cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_adapter_pyblocks.py
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard.adapters import base, pyblocks
from vibetracks.dashboard.registry import WorkTrack

LIVE_BOARD = Path("/home/bam/pyblocks/reports/media/board")
EASY = [f"runnable/e{i}" for i in range(3)]


def work_track() -> WorkTrack:
    return WorkTrack(id="pyblocks", title="Renamed Pyblocks", status="running", priority=5, owner="t", adapter="pyblocks",
                     sources=["pyblocks_board_dir", "pyblocks_windows"], roadmap=None, children=[],
                     note_path="/tmp/pyblocks.md", revision="r1")


def board(commit: str, at: str, *, green: int, l0: int, easy_green: int, adversarial: dict | None) -> dict:
    rows = [{"key": key, "status": "green" if i < easy_green else "red"} for i, key in enumerate(EASY)]
    totals = {"runnable": {"goldens": 5, "green": green, "red": 5 - green, "grey": 0, "measuring": 0, "l0Pass": l0}}
    if adversarial is not None:
        totals["adversarial"] = adversarial
    return {"schema": 1, "commit": commit, "dirty": False, "generatedAt": at, "easy": EASY, "totals": totals,
            "goldens": rows}


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "board"
        self.dir.mkdir()
        adv = {"goldens": 4, "green": 1, "red": 2, "grey": 1, "measuring": 0, "l0Pass": 4}
        # Written out of time order on purpose: the adapter sorts by generatedAt, not by file name.
        self.write("scoreboard-aaaaaaa1.json", board("aaaaaaa1" + "0" * 32, "2026-09-30T18:00:00+00:00",
                                                     green=1, l0=4, easy_green=1, adversarial=None))
        self.write("bbbbbbb.json", board("bbbbbbb2" + "0" * 32, "2026-09-30T20:00:00+00:00",
                                         green=3, l0=5, easy_green=3, adversarial=adv))
        self.write("ccccccc.json", board("ccccccc3" + "0" * 32, "2026-10-01T18:00:00+00:00",
                                         green=3, l0=5, easy_green=3, adversarial={**adv, "l0Pass": 3}))
        (self.dir / "bbbbbbb.md").write_text("# board b\n")
        self.merges = [
            {"lane": "A", "main": "aaaaaaa1", "gate_tail": "gate --tier fast: 100 passed, 2 failed, 1 skipped in 9 s · "
                                                           "2 known red (ledgered) · GATE PASS"},
            {"lane": "B", "main": "1111111", "gate_tail": ""},
            {"lane": "C", "main": "bbbbbbb2",
             "gate_tail": "gate --tier fast (before ledger): 120 passed, 9 failed, 0 unexpected red -> GATE FAIL; "
                          "after ledger: 120 passed, 9 failed, 1 skipped · 9 known red (ledgered) · GATE PASS; "
                          "gate --tier slow: 50 passed, 40 failed, 2 skipped · 40 known red · GATE PASS"},
            {"lane": "D", "main": "ccccccc3", "gate_tail": "no gate run"},
            {"lane": "E", "main": "ddddddd4", "gate_tail": ""},
        ]
        self.windows = [
            {"window": "v5-#9", "at": "2026-09-30T20:30:00+00:00", "main": "bbbbbbb2" + "0" * 32,
             "board": {"check": {"exit": 1, "failures": 4, "notes": 0}, "vs_previous": "first window"}},
            {"window": "v5-#10", "at": "2026-10-01T18:10:00+00:00", "main": "ccccccc3" + "0" * 32,
             "board": {"check": {"exit": 0, "failures": 0, "notes": 0}, "vs_previous": "p15 over budget: load"}},
        ]
        self.write_jsonl("merges.jsonl", self.merges)
        self.write_jsonl("windows.jsonl", self.windows)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str, data: dict) -> None:
        (self.dir / name).write_text(json.dumps(data))

    def write_jsonl(self, name: str, rows: list[dict]) -> None:
        (self.dir / name).write_text("".join(json.dumps(row) + "\n" for row in rows))

    def build(self) -> dict:
        return pyblocks.build_track(work_track(), {"pyblocks_board_dir": str(self.dir),
                                                   "pyblocks_windows": str(self.dir / "windows.jsonl")})

    def series(self, track: dict, kpi_id: str) -> list:
        return [v["value"] for v in next(k for k in track["kpis"] if k["id"] == kpi_id)["values"]]

    def test_shape_is_sound_and_aligned(self) -> None:
        track = self.build()
        self.assertEqual(base.problems(track), [])
        self.assertEqual([it["id"] for it in track["iterations"]], ["aaaaaaa", "bbbbbbb", "ccccccc"])
        self.assertEqual(track["iteration"], {"unit": "wave", "label": "v5-#10 · ccccccc"})
        self.assertEqual(track["north_star"], "runnable_green")
        self.assertTrue(4 <= len(track["kpis"]) <= 10)

    def test_board_numbers(self) -> None:
        track = self.build()
        self.assertEqual(self.series(track, "runnable_green"), [1, 3, 3])
        self.assertEqual(self.series(track, "easy_green"), [1, 3, 3])
        self.assertEqual(self.series(track, "l0_runnable"), [4, 5, 5])
        self.assertEqual(self.series(track, "l0_adversarial"), [None, 4, 3])
        self.assertEqual(self.series(track, "board_check"), [None, 4, 0])

    def test_missing_is_explicit_never_zero(self) -> None:
        track = self.build()
        adv = next(k for k in track["kpis"] if k["id"] == "adversarial_green")["values"][0]
        self.assertEqual((adv["value"], adv["measured"]), (None, False))
        self.assertIn("not measured", adv["note"])
        check = next(k for k in track["kpis"] if k["id"] == "board_check")["values"][0]
        self.assertIn("no windows.jsonl line", check["note"])
        self.assertEqual(track["needs_you_count"], {"open": None, "blocking": None})

    def test_landings_and_fast_gate_bucketed_by_board_commit(self) -> None:
        track = self.build()
        self.assertEqual(self.series(track, "landings"), [1, 2, 1])
        # The last FAST result wins (the after-ledger rerun), the slow tier is ignored.
        self.assertEqual(self.series(track, "fast_gate_known_red"), [2, 9, None])
        self.assertEqual(self.series(track, "fast_gate_passed"), [100, 120, None])
        gate = next(k for k in track["kpis"] if k["id"] == "fast_gate_known_red")["values"]
        self.assertEqual(gate[1]["note"], "GATE PASS")
        self.assertIn("no landing in this window logged a fast-gate tail", gate[2]["note"])
        self.assertIn("1 landing logged since, not yet on a board", track["state"]["detail"])

    def test_n1_change_reads_unconfirmed(self) -> None:
        status = next(k for k in self.build()["kpis"] if k["id"] == "l0_adversarial")["status"]
        self.assertIn("-1 last window · unconfirmed · repeat needed", status["word"])
        self.assertEqual(status["tone"], "warn")

    def test_state_stopped_while_the_known_stop_window_is_newest(self) -> None:
        track = self.build()
        self.assertEqual((track["state"]["word"], track["state"]["tone"]), ("Stopped", "warn"))
        self.assertIn("account weekly limit", track["state"]["detail"])
        self.assertEqual(track["state"]["since"], "2026-10-01T18:10:00+00:00")
        # A newer window drops the annotation: it can never outlive the stop it describes.
        self.write_jsonl("windows.jsonl", self.windows + [{"window": "v5-#11", "at": "2026-10-06T18:00:00+00:00",
                                                            "main": "ccccccc3" + "0" * 32, "board": {}}])
        track = self.build()
        self.assertEqual(track["state"]["word"], "Measuring")
        self.assertNotIn("account weekly limit", track["state"]["detail"])

    def test_rung_is_null_because_the_board_files_name_none(self) -> None:
        track = self.build()
        self.assertIn("rung", track)
        self.assertIsNone(track["rung"])  # M1 lives only in prose; the page says "no rung reported", never a guess

    def test_human_times_are_local_with_a_zone(self) -> None:
        detail = self.build()["state"]["detail"]
        self.assertRegex(detail, r"reset due 10-06 \d\d:\d\d [A-Z]{3,4}")
        self.assertRegex(detail, r"10-01 \d\d:\d\d [A-Z]{3,4}")

    def test_an_undeclared_board_dir_is_not_reporting(self) -> None:
        track = pyblocks.build_track(work_track(), {})
        self.assertEqual(track["state"]["word"], base.NOT_REPORTING)
        self.assertIn("pyblocks_board_dir is not declared", track["summary"])

    def test_evidence_and_media_only_for_existing_files(self) -> None:
        track = self.build()
        self.assertEqual(set(track["media"]), {"pyblocks.board-bbbbbbb"})
        items = {item["id"]: item for item in track["evidence"]["by_iteration"]["bbbbbbb"]}
        self.assertIn("board-bbbbbbb", items)
        self.assertEqual(items["window-v5-#9"]["note"], "first window")
        self.assertEqual(items["board-bbbbbbb"]["media"][0]["id"], "pyblocks.board-bbbbbbb")
        first = {item["id"]: item for item in track["evidence"]["by_iteration"]["aaaaaaa"]}
        self.assertEqual(first["board-aaaaaaa"]["media"], [])   # no .md twin on disk, so no media id
        runnable = next(k for k in track["kpis"] if k["id"] == "runnable_green")["values"][1]
        self.assertEqual(runnable["evidence"], ["board-bbbbbbb"])

    def test_no_boards_is_not_reporting(self) -> None:
        for path in self.dir.glob("*.json"):
            path.unlink()
        track = self.build()
        self.assertEqual(track["state"]["word"], "Not reporting")
        self.assertIs(track["reporting"], False)
        self.assertEqual(base.problems(track), [])

    def test_fast_gate_parser(self) -> None:
        tail = ("run 1: 4506 passed, 9 failed · UNEXPECTED RED x · rerun: gate --tier fast: 4507 passed, 8 failed, "
                "38 skipped in 335 s · 8 known red (ledgered) · GATE PASS")
        self.assertEqual(pyblocks._fast_gate(tail),
                         {"passed": 4507, "failed": 8, "skipped": 38, "known_red": 8, "verdict": "PASS"})
        self.assertIsNone(pyblocks._fast_gate("gate --tier slow: 1 passed, 2 failed · 2 known red"))
        self.assertIsNone(pyblocks._fast_gate(""))


@unittest.skipUnless((LIVE_BOARD / "b07c38b.json").is_file(), f"pyblocks board not on this machine: {LIVE_BOARD}")
class LiveSmokeTest(unittest.TestCase):
    """Pins numbers checked by hand against the real board files (history; those files do not change)."""

    def test_live_board(self) -> None:
        track = pyblocks.build_track(work_track(), {"pyblocks_board_dir": str(LIVE_BOARD),
                                                    "pyblocks_windows": str(LIVE_BOARD / "windows.jsonl")})
        self.assertEqual(base.problems(track), [])
        ids = [it["id"] for it in track["iterations"]]
        at = ids.index("b07c38b")
        kpis = {k["id"]: k["values"][at]["value"] for k in track["kpis"]}
        self.assertEqual(kpis["runnable_green"], 34)
        self.assertEqual(kpis["easy_green"], 16)
        self.assertEqual(kpis["adversarial_green"], 64)
        self.assertEqual(kpis["l0_runnable"], 55)
        self.assertEqual(kpis["l0_adversarial"], 131)
        self.assertEqual(kpis["fast_gate_passed"], 4570)
        self.assertEqual(kpis["fast_gate_known_red"], 128)
        first = ids.index("a4d8221")
        self.assertEqual(next(k for k in track["kpis"] if k["id"] == "runnable_green")["values"][first]["value"], 12)


if __name__ == "__main__":
    unittest.main()
