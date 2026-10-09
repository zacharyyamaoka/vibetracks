"""B1 acceptance, frozen before the build (checks 2 and 3, and check 1 on fixtures): the home's state rules on frozen
fixture transcript tails, the claim test, and the live-session bookkeeping.

    python3 -m unittest tests/test_home_rules.py      (from the repo root)

The fixtures (tests/fixtures/home/, written by make_fixtures.py) are one fake Claude Code account, a fake /proc and a
workspace of seven tracks, one per rule case; the clock is frozen at 2026-10-09 12:00 PDT. Every test copies them to a
temp dir first, so a test may edit a note or a session file without touching the checked-in copy.

WHY these are read-only to the builder (dispatch discipline, 2026-09-16): they are the ruler. If one is wrong, the
build reports FAIL and says why; it never edits the test to pass.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import yaml

from vibetracks.activity.derive import parse_reset
from vibetracks.home.compose import build_home

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home"
NOW = datetime.fromisoformat("2026-10-09T12:00:00-07:00").timestamp()
LIVE_PIDS = {1001, 1002, 1004, 1005, 1006, 1007}
PROJECTION = {"schema": "vibetracks-dashboard/1", "tracks": [{
    "id": "t-claim", "title": "Claim fixture", "kind": "loop", "parent": None, "reporting": True,
    "state": {"word": "Running", "tone": "ok", "detail": "fixture loop", "since": None},
    "freshness": {"newest": "2026-10-08T03:00:00-07:00", "newest_source": "fixture_events", "stall_hours": 24.0},
    "north_star": None, "kpis": [], "needs_you": [], "needs_you_count": {"open": None, "blocking": None}}]}


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def tracks_of(doc: dict) -> dict[str, dict]:
    return {track["id"]: track for project in doc["projects"] for track in project["tracks"]}


def live_on_page(doc: dict) -> list[tuple[str, int]]:
    """(account, pid) of every live session the page shows: matched under a track, or in Other sessions."""

    out = [(s["account"], s["pid"]) for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]]
    out += [(s["account"], s["pid"]) for s in doc["other_sessions"] if s["live"]]
    return out


def set_frontmatter(note: Path, key: str, value) -> None:
    text = note.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    data = yaml.safe_load(match.group(1))
    data[key] = value
    note.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + text[match.end():], encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / name, self.root / name)
        self.workspace = self.root / "workspace"
        self.account = self.root / "claude-fixa"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build(self) -> dict:
        return build_home(self.workspace, claude_homes=[self.account], proc_root=self.root / "proc", now=NOW,
                          projection=PROJECTION, needs={})

    def set_status(self, pid: int, status: str) -> None:
        path = self.account / "sessions" / f"{pid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        path.write_text(json.dumps(data), encoding="utf-8")


class RuleOrderTest(Fixture):
    """Check 2: the rule order on frozen transcript tails."""

    def test_schema(self) -> None:
        doc = self.build()
        self.assertEqual(doc["schema"], "vibetracks-home/1")
        self.assertEqual(set(tracks_of(doc)), {"t-waiting", "t-ratelimit", "t-stale", "t-busy", "t-openask",
                                               "t-subagent", "t-claim"})

    def test_waiting_session_reads_needs_you(self) -> None:
        track = tracks_of(self.build())["t-waiting"]
        self.assertEqual(track["state"]["word"], "needs_you", track["state"])
        self.assertIn("waiting", track["state"]["why"])

    def test_without_the_waiting_status_it_reads_working(self) -> None:
        self.set_status(1001, "busy")
        self.assertEqual(tracks_of(self.build())["t-waiting"]["state"]["word"], "working")

    def test_trailing_rate_limit_error_reads_error_with_its_reset_time(self) -> None:
        track = tracks_of(self.build())["t-ratelimit"]
        self.assertEqual(track["state"]["word"], "error", track["state"])
        self.assertEqual(track["last_error"]["kind"], "rate_limit")
        self.assertEqual(ts(track["last_error"]["resets"]), ts("2026-10-09T17:20:00-07:00"))
        self.assertIn("resets", track["state"]["why"])
        self.assertEqual(ts(track["last_error"]["ts"]), ts("2026-10-09T11:20:00-07:00"))

    def test_quiet_past_the_stall_rule_reads_stale(self) -> None:
        track = tracks_of(self.build())["t-stale"]
        self.assertEqual(track["state"]["word"], "stale", track["state"])
        self.assertEqual(ts(track["last_action"]["ts"]), ts("2026-10-08T06:00:00-07:00"),
                         "the subagent whose own branch matches t-stale's rule must not count here")

    def test_busy_session_reads_working(self) -> None:
        track = tracks_of(self.build())["t-busy"]
        self.assertEqual(track["state"]["word"], "working", track["state"])
        self.assertEqual(ts(track["last_action"]["ts"]), ts("2026-10-09T11:40:00-07:00"))

    def test_the_same_track_idle_reads_idle(self) -> None:
        self.set_status(1004, "idle")
        self.assertEqual(tracks_of(self.build())["t-busy"]["state"]["word"], "idle")

    def test_open_question_outranks_a_newer_action(self) -> None:
        track = tracks_of(self.build())["t-openask"]
        self.assertEqual(track["state"]["word"], "needs_you", track["state"])
        self.assertIn("Which gripper should the bench use?", track["state"]["why"])
        self.assertNotIn("Ship the probe now?", track["state"]["why"], "an answered question is not open")
        self.assertEqual(ts(track["last_action"]["ts"]), ts("2026-10-09T11:58:00-07:00"))

    def test_subagent_lines_count_toward_the_parent_track(self) -> None:
        track = tracks_of(self.build())["t-subagent"]
        self.assertEqual(track["state"]["word"], "working", track["state"])
        self.assertEqual(ts(track["last_action"]["ts"]), ts("2026-10-09T11:56:00-07:00"))
        # parent 09:00-09:10 (600 s) + workflow agent 10:00-10:10 (600 s) + subagent 11:00-11:56 (3360 s)
        self.assertEqual(track["worked"]["h24_s"], 4560)
        self.assertEqual(track["worked"]["d7_s"], 4560)

    def test_health_follows_the_state(self) -> None:
        tracks = tracks_of(self.build())
        self.assertEqual(tracks["t-stale"]["health"]["color"], "red")
        self.assertEqual(tracks["t-ratelimit"]["health"]["color"], "red")
        self.assertEqual(tracks["t-waiting"]["health"]["color"], "yellow")
        self.assertEqual(tracks["t-busy"]["health"]["color"], "green")

    def test_parse_reset_reads_both_card_forms(self) -> None:
        at = ts("2026-10-09T11:20:00-07:00")
        self.assertEqual(ts(parse_reset("You've hit your session limit · resets 5:20pm (America/Vancouver)", at)),
                         ts("2026-10-09T17:20:00-07:00"))
        self.assertEqual(ts(parse_reset("You've hit your session limit · resets 2am (America/Vancouver)", at)),
                         ts("2026-10-10T02:00:00-07:00"))
        self.assertEqual(ts(parse_reset("You've hit your weekly limit · resets Oct 11, 9pm (America/Vancouver)", at)),
                         ts("2026-10-11T21:00:00-07:00"))
        self.assertIsNone(parse_reset("Prompt is too long", at))


class ClaimTest(Fixture):
    """Check 3: a note's claim never changes the derived state word; only a person's done or archived does."""

    def note(self) -> Path:
        return self.workspace / "tracks" / "t-claim.md"

    def test_running_claim_on_a_quiet_track_reads_stale(self) -> None:
        set_frontmatter(self.note(), "vibe-status", "running")
        self.assertEqual(tracks_of(self.build())["t-claim"]["state"]["word"], "stale")

    def test_other_claims_change_nothing(self) -> None:
        set_frontmatter(self.note(), "vibe-status", "running")
        set_frontmatter(self.note(), "vibe-state", "working")
        set_frontmatter(self.note(), "vibe-health", "green")
        track = tracks_of(self.build())["t-claim"]
        self.assertEqual(track["state"]["word"], "stale")
        self.assertEqual(track["health"]["color"], "red")

    def test_done_wins(self) -> None:
        set_frontmatter(self.note(), "vibe-status", "done")
        self.assertEqual(tracks_of(self.build())["t-claim"]["state"]["word"], "done")

    def test_archived_wins(self) -> None:
        set_frontmatter(self.note(), "vibe-status", "archived")
        self.assertEqual(tracks_of(self.build())["t-claim"]["state"]["word"], "archived")

    def test_running_claim_on_an_activity_track_changes_nothing(self) -> None:
        set_frontmatter(self.workspace / "tracks" / "t-stale.md", "vibe-status", "running")
        self.assertEqual(tracks_of(self.build())["t-stale"]["state"]["word"], "stale")


class LiveSessionsFixtureTest(Fixture):
    """Check 1 on the fixtures: every live session file is on the page exactly once; dead ones are not."""

    def test_live_sessions_are_exactly_the_alive_files(self) -> None:
        doc = self.build()
        shown = live_on_page(doc)
        self.assertEqual(len(shown), len(set(shown)), "a live session is shown twice")
        self.assertEqual({pid for _, pid in shown}, LIVE_PIDS)
        self.assertEqual({account for account, _ in shown}, {"fixa"})
        self.assertEqual(doc["summary"]["sessions_live"], len(LIVE_PIDS))

    def test_unmatched_live_session_is_in_other(self) -> None:
        other = {s["pid"]: s for s in self.build()["other_sessions"]}
        self.assertIn(1007, other)
        self.assertIsNone(other[1007]["join"]["by"])

    def test_every_matched_session_records_how_it_was_matched(self) -> None:
        for track in tracks_of(self.build()).values():
            for session in track["sessions"]:
                self.assertIn(session["join"]["by"], ("branch", "cwd", "title"), (track["id"], session))
                self.assertTrue(session["join"]["value"], (track["id"], session))

    def test_deleting_a_matching_rule_moves_the_session_to_other(self) -> None:
        before = tracks_of(self.build())["t-busy"]
        self.assertIn(1004, [s["pid"] for s in before["sessions"] if s["live"]])
        set_frontmatter(self.workspace / "tracks" / "t-busy.md", "vibe-sessions", {"branches": [], "cwds": [], "titles": []})
        doc = self.build()
        self.assertNotIn(1004, [s["pid"] for s in tracks_of(doc)["t-busy"]["sessions"]])
        self.assertIn(1004, [s["pid"] for s in doc["other_sessions"] if s["live"]])
        self.assertEqual({pid for _, pid in live_on_page(doc)}, LIVE_PIDS, "a session disappeared")

    def test_deleting_every_rule_keeps_every_session(self) -> None:
        for note in (self.workspace / "tracks").glob("*.md"):
            set_frontmatter(note, "vibe-sessions", None)
        doc = self.build()
        self.assertEqual([s for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]], [])
        self.assertEqual({s["pid"] for s in doc["other_sessions"] if s["live"]}, LIVE_PIDS)


if __name__ == "__main__":
    unittest.main()
