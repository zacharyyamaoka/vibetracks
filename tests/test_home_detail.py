"""B2: the track page's and project page's documents (vibetracks/home/detail.py), on B1's frozen fixtures and on
hand-made KPI and audit inputs.

    python3 -m unittest tests/test_home_detail.py      (from the repo root)

- Hard gates are the KPIs whose target kind is ``gate``, judged pass/fail from their own direction, never averaged
  in; every other KPI is a soft KPI; an unmeasured gate is "unknown", never a pass.
- Audit rounds come only from the track note's ``vibe-audits`` globs; the verdict is read from the file's first lines
  (UNSOUND is never read as SOUND); the model and effort come from the ``.log`` beside it; a file outside the globs is
  never served.
- The project page's lagging north star is a pointer from the descriptor; with none it is "unknown".
- The timeline is newest first and every event names its source.

Written before the code it tests (B2, 2026-10-09).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vibetracks.home import compose, detail
from vibetracks.home.compose import build_home

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home"
NOW = datetime.fromisoformat("2026-10-09T12:00:00-07:00").timestamp()


def kpi(kid: str, values: list, target=None, direction=None) -> dict:
    return {"id": kid, "label": kid, "unit": None, "direction": direction, "target": target,
            "values": [{"iteration": f"W{i}", "value": v, "of": None, "measured": v is not None} for i, v in enumerate(values)]}


PROJECTION = {"schema": "vibetracks-dashboard/1", "tracks": [{
    "id": "t-claim", "title": "Claim fixture", "kind": "loop", "parent": None, "reporting": True,
    "state": {"word": "Running", "tone": "ok", "detail": "fixture loop", "since": None},
    "freshness": {"newest": "2026-10-08T03:00:00-07:00", "newest_source": "fixture_events", "stall_hours": 24.0},
    "north_star": "rungs",
    "iterations": [{"id": "W0", "label": "W0", "date": "2026-10-05"}, {"id": "W1", "label": "W1", "date": "2026-10-07"},
                   {"id": "W2", "label": "W2", "date": None}],
    "kpis": [
        kpi("rungs", [3, 5, 8], {"value": 20, "kind": "scope", "label": "of 20"}, "higher"),
        kpi("gap", [2.0, 1.1, 0.7], {"value": 0.8, "kind": "gate", "label": "≤ 0.8"}, "lower"),
        kpi("faults", [0, 1, 2], {"value": 0, "kind": "gate", "label": "zero faults"}, "lower"),
        kpi("unmeasured", [None, None, None], {"value": 1, "kind": "gate", "label": "one"}, "higher"),
        kpi("hours", [4, 9, 12]),
    ],
    "needs_you": [], "needs_you_count": {"open": None, "blocking": None}}]}


class DetailTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / name, self.root / name)
        self.workspace = self.root / "workspace"
        audits = self.root / "audits"
        audits.mkdir()
        (audits / "2026-10-08-claim-r1.md").write_text("**UNSOUND - the ruler can be gamed.**\n\nDetail.\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r1.log").write_text("OpenAI Codex v0.159\n--------\nmodel: gpt-6.1-sol\nprovider: openai\n"
                                                        "reasoning effort: xhigh\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r1-prompt.md").write_text("# prompt\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r2.md").write_text("SOUND WITH FIXES: two minor findings.\n", encoding="utf-8")
        (audits / "2026-10-08-other-r1.md").write_text("PASS\n", encoding="utf-8")
        note = self.workspace / "tracks" / "t-claim.md"
        text = note.read_text(encoding="utf-8")
        note.write_text(text.replace("vibe-sessions:", f'vibe-audits: ["{audits}/*-claim-*.md"]\nvibe-sessions:', 1), encoding="utf-8")
        (self.workspace / "projects").mkdir()
        (self.workspace / "projects" / "fixture.vibetrack").write_text(
            "vibetracks:\n  version: 1\n  kind: project\n  name: Fixture Robotics\n  roots: [/home/fix]\n", encoding="utf-8")
        self.doc = build_home(self.workspace, claude_homes=[self.root / "claude-fixa"], proc_root=self.root / "proc",
                              now=NOW, projection=PROJECTION, needs={})
        self.last = compose.LAST[str(self.workspace.resolve())]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_soft_kpis_and_hard_gates_are_separate(self) -> None:
        page = detail.build_track(self.doc, self.last, "t-claim")
        self.assertEqual(page["schema"], "vibetracks-home-track/1")
        self.assertEqual([k["id"] for k in page["kpis"]["soft"]], ["rungs", "hours"], "north star first, gates excluded")
        gates = {g["id"]: g["gate"] for g in page["kpis"]["gates"]}
        self.assertEqual(set(gates), {"gap", "faults", "unmeasured"})
        self.assertIs(gates["gap"]["pass"], True)
        self.assertIs(gates["faults"]["pass"], False)
        self.assertIsNone(gates["unmeasured"]["pass"], "an unmeasured gate is unknown, never a pass")

    def test_series_carry_iteration_dates(self) -> None:
        page = detail.build_track(self.doc, self.last, "t-claim")
        rungs = page["kpis"]["soft"][0]
        self.assertEqual([p["date"] for p in rungs["series"]], ["2026-10-05", "2026-10-07", None])

    def test_audits_come_from_the_globs_with_verdict_and_model(self) -> None:
        page = detail.build_track(self.doc, self.last, "t-claim")
        rounds = {r["name"]: r for r in page["audits"]["rounds"]}
        self.assertEqual(set(rounds), {"2026-10-08-claim-r1.md", "2026-10-08-claim-r2.md"}, "prompts and other tracks excluded")
        self.assertEqual(rounds["2026-10-08-claim-r1.md"]["verdict"], "Unsound")
        self.assertEqual(rounds["2026-10-08-claim-r1.md"]["tone"], "red")
        self.assertEqual(rounds["2026-10-08-claim-r1.md"]["model"], "gpt-6.1-sol")
        self.assertEqual(rounds["2026-10-08-claim-r1.md"]["effort"], "xhigh")
        self.assertEqual(rounds["2026-10-08-claim-r2.md"]["tone"], "yellow")

    def test_audit_files_outside_the_globs_are_never_served(self) -> None:
        self.assertIsNotNone(detail.serve_audit(self.doc, "t-claim", "2026-10-08-claim-r1.md"))
        self.assertIsNone(detail.serve_audit(self.doc, "t-claim", "2026-10-08-other-r1.md"))
        self.assertIsNone(detail.serve_audit(self.doc, "t-claim", "../t-claim.md"))
        self.assertIsNone(detail.serve_audit(self.doc, "t-busy", "2026-10-08-claim-r1.md"), "t-busy declares no globs")

    def test_track_without_globs_says_so(self) -> None:
        page = detail.build_track(self.doc, self.last, "t-busy")
        self.assertEqual(page["audits"]["rounds"], [])
        self.assertTrue(page["audits"]["unknown"])
        self.assertEqual(page["kpis"]["unknown"], "no KPI adapter yet")

    def test_timeline_newest_first_with_sources(self) -> None:
        page = detail.build_track(self.doc, self.last, "t-claim")
        stamps = [e["ts"] for e in page["timeline"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertTrue(page["timeline"])
        self.assertTrue(all("source" in e for e in page["timeline"]))
        self.assertIn("audit", {e["kind"] for e in page["timeline"]})

    def test_project_without_north_star_is_unknown(self) -> None:
        page = detail.build_project(self.doc, self.last, "fixture-robotics")
        self.assertEqual(page["schema"], "vibetracks-home-project/1")
        self.assertIsNone(page["north_star"]["declared"])
        self.assertTrue(page["north_star"]["unknown"])
        self.assertEqual(len(page["days"]), 7)
        leading = {row["track"]: row for row in page["leading"]}
        self.assertEqual(leading["t-claim"]["kpi"]["id"], "rungs")
        self.assertIsNone(leading["t-busy"]["kpi"])
        self.assertTrue(leading["t-busy"]["unknown"])

    def test_unknown_ids_are_none(self) -> None:
        self.assertIsNone(detail.build_track(self.doc, self.last, "nope"))
        self.assertIsNone(detail.build_project(self.doc, self.last, "nope"))


if __name__ == "__main__":
    unittest.main()
