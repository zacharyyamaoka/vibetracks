"""The home across machines (r3, 2026-10-09), written before the code it tests. Zach: "please also merge the git remote
work into this: so I can start like using this across machines".

    python3 -m unittest tests/test_home_remote.py      (from the repo root)

The remote layer (docs/remote/DESIGN.md) already publishes every worker's data into the share, one folder per machine:
``hosts/<host>/host.json`` (the heartbeat, ``last_sync``), ``hosts/<host>/sessions/<id>.json`` (session cards written
by the Claude Code hook) and ``hosts/<host>/sources.json`` + ``files/`` (mirrored loop files). The home reads them:

- other machines' sessions appear on the home, under the track they join (the card's ``track`` from the hook's
  tracks-map, else the same branch / cwd / title rules as local sessions) or in ``other_sessions``, each labelled
  with its host;
- liveness is honest: a remote session is never ``live`` (no pid here can be checked). It is ``current`` as of its
  host's last report (``as_of`` = the newer of the host's ``last_sync`` and the card's ``last_seen``), and only while
  the host reports (online or stale, not offline), the card is not ended and its last hook event is at most 30 min
  older than ``as_of`` (the hub's rule for a live card);
- a track whose loop files another machine supplies, or whose sessions run there, names that host;
- this machine's own host folder is skipped (its sessions come from its own files), and a session id seen locally
  wins over any card;
- with no share, the document is exactly what it was: no ``remote`` block, no remote fields anywhere.

Fixtures: B1's frozen fixtures (tests/fixtures/home/) copied to a temp dir, plus a scratch share written here.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from vibetracks.home.compose import build_home

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home"
NOW = datetime.fromisoformat("2026-10-09T12:00:00-07:00").timestamp()
PROJECTION = {"schema": "vibetracks-dashboard/1", "tracks": []}
WAITING = "11111111-0000-4000-8000-000000000001"   # a live local session (pid 1001) joined to t-waiting
OWN = {"bam-gpu"}


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def card(session_id: str, host: str, *, event: str, seen_ago: float, cwd: str, track: str | None = None,
         title: str | None = None, branch: str | None = None, ended: bool = False, **extra) -> dict:
    out = {"session_id": session_id, "host": host, "account": "bam", "agent": "claude-code", "model": "claude-opus-5-5",
           "cwd": cwd, "track": track, "url": f"https://claude.ai/code/session_{session_id[:6]}", "event": event,
           "started_at": iso(NOW - 3600), "last_seen": iso(NOW - seen_ago), "ended": ended}
    if title is not None:
        out["title"] = title
    if branch is not None:
        out["branch"] = branch
    out.update(extra)
    return out


class RemoteHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / name, self.root / name)
        self.workspace = self.root / "workspace"
        claim = self.workspace / "tracks" / "t-claim.md"
        claim.write_text(claim.read_text(encoding="utf-8").replace("vibe-sources: []", "vibe-sources: [fixture_events]"),
                         encoding="utf-8")
        self.share = self.root / "share"
        hosts = self.share / "hosts"
        # win-a: online (synced 2 min ago)
        write(hosts / "win-a" / "host.json", {"host": "win-a", "platform": "Windows-11", "last_sync": iso(NOW - 120),
                                              "interval_s": 3, "heartbeat_s": 300, "mirrors": [], "skipped": [], "error": None})
        write(hosts / "win-a" / "sources.json", {"fixture_events": "files/fixture_events/events.jsonl"})
        (hosts / "win-a" / "files" / "fixture_events").mkdir(parents=True)
        (hosts / "win-a" / "files" / "fixture_events" / "events.jsonl").write_text("{}\n", encoding="utf-8")
        sessions = hosts / "win-a" / "sessions"
        # A: pinned to t-stale by the hook's tracks-map, a prompt 1 min ago: working, as of the last sync
        write(sessions / "aaaa0001.json", card("aaaa0001", "win-a", event="UserPromptSubmit", seen_ago=60,
                                                cwd="C:/Users/BAM/bam_ws", track="t-stale", title="Stale work on win-a"))
        # B: no track on the card; its branch matches t-claim's rule; its turn ended 5 min ago: idle
        write(sessions / "bbbb0002.json", card("bbbb0002", "win-a", event="Stop", seen_ago=300,
                                                cwd="C:/Users/BAM/claim", branch="claude/t-claim-remote"))
        # C: matches no rule and no project: Other
        write(sessions / "cccc0003.json", card("cccc0003", "win-a", event="UserPromptSubmit", seen_ago=90,
                                                cwd="C:/Users/BAM/scratch", title="Scratch on win-a"))
        # D: ended
        write(sessions / "dddd0004.json", card("dddd0004", "win-a", event="SessionEnd", seen_ago=600,
                                                cwd="C:/Users/BAM/bam_ws", track="t-stale", ended=True))
        # E: quiet for 2 h (no hook event since): not current even though win-a reports
        write(sessions / "eeee0005.json", card("eeee0005", "win-a", event="UserPromptSubmit", seen_ago=7200,
                                                cwd="C:/Users/BAM/bam_ws", track="t-stale"))
        # F: a card written before r3's hook (no title / branch keys)
        legacy = card("ffff0006", "win-a", event="Stop", seen_ago=30, cwd="C:/Users/BAM/legacy")
        write(sessions / "ffff0006.json", legacy)
        # win-b: offline (last sync 3 h ago); its card G says working, as of 3 h ago
        write(hosts / "win-b" / "host.json", {"host": "win-b", "platform": "Linux", "last_sync": iso(NOW - 3 * 3600),
                                              "interval_s": 3, "heartbeat_s": 300})
        write(hosts / "win-b" / "sessions" / "gggg0007.json", card("gggg0007", "win-b", event="UserPromptSubmit",
                                                                   seen_ago=3 * 3600 + 30, cwd="/home/bam/x", track="t-stale"))
        # this machine's own folder: a card for a session this machine already sees, and one it does not
        write(hosts / "bam-gpu" / "host.json", {"host": "bam-gpu", "last_sync": iso(NOW - 5), "interval_s": 3})
        write(hosts / "bam-gpu" / "sessions" / f"{WAITING}.json", card(WAITING, "bam-gpu", event="UserPromptSubmit",
                                                                       seen_ago=5, cwd="/home/fix/waiting"))
        write(hosts / "bam-gpu" / "sessions" / "hhhh0008.json", card("hhhh0008", "bam-gpu", event="UserPromptSubmit",
                                                                     seen_ago=5, cwd="/home/fix/elsewhere"))
        write(hosts / "bam-gpu" / "sources.json", {"own_key": "files/own_key/x.json"})
        # a card on win-a claiming a session id this machine has live: the local one wins
        write(sessions / f"{WAITING}.json", card(WAITING, "win-a", event="UserPromptSubmit", seen_ago=10, cwd="C:/x"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build(self, share: Path | None = "default") -> dict:
        kwargs = {} if share == "default" else {"share": share, "own_hosts": OWN}
        return build_home(self.workspace, claude_homes=[self.root / "claude-fixa"], proc_root=self.root / "proc", now=NOW,
                          projection=PROJECTION, needs={}, **kwargs)

    @staticmethod
    def tracks(doc: dict) -> dict[str, dict]:
        return {t["id"]: t for p in doc["projects"] for t in p["tracks"]}

    @staticmethod
    def remote_sessions(doc: dict) -> dict[str, dict]:
        out = {s["id"]: s for t in RemoteHome.tracks(doc).values() for s in t["sessions"] if s.get("remote")}
        out.update({s["id"]: s for s in doc["other_sessions"] if s.get("remote")})
        return out

    # ------------------------------------------------------------------ no share: nothing changes
    def test_no_share_means_the_document_is_unchanged(self) -> None:
        plain = self.build()
        none = self.build(share=None)
        for doc in (plain, none):
            self.assertNotIn("remote", doc)
            self.assertNotIn("sessions_remote", doc["summary"])
            for track in self.tracks(doc).values():
                self.assertNotIn("hosts", track)
                self.assertFalse(any("remote" in s or "host" in s for s in track["sessions"]))
        strip = lambda d: {k: v for k, v in d.items() if k != "sources"}  # noqa: E731 - timings differ run to run
        self.assertEqual(strip(plain), strip(none))

    def test_a_missing_share_folder_reads_as_no_other_machines(self) -> None:
        doc = self.build(share=self.root / "no-such-share")
        self.assertEqual(doc["remote"]["hosts"], [])
        self.assertEqual(self.remote_sessions(doc), {})

    # ------------------------------------------------------------------ other machines appear, labelled
    def test_hosts_are_listed_with_their_last_sync(self) -> None:
        doc = self.build(share=self.share)
        hosts = {h["host"]: h for h in doc["remote"]["hosts"]}
        self.assertEqual(set(hosts), {"win-a", "win-b"}, "this machine's own folder is not another machine")
        self.assertEqual(hosts["win-a"]["status"], "online")
        self.assertEqual(hosts["win-a"]["last_sync"], iso(NOW - 120))
        self.assertEqual(hosts["win-a"]["age_s"], 120)
        self.assertEqual(hosts["win-b"]["status"], "offline")
        self.assertEqual(sorted(doc["remote"]["this_machine"]), sorted(OWN))

    def test_remote_sessions_join_tracks_and_are_never_live(self) -> None:
        doc = self.build(share=self.share)
        tracks = self.tracks(doc)
        a = next(s for s in tracks["t-stale"]["sessions"] if s["id"] == "aaaa0001")
        self.assertFalse(a["live"], "a session on another machine is never claimed live")
        self.assertIsNone(a["pid"])
        self.assertEqual(a["remote"]["host"], "win-a")
        self.assertTrue(a["remote"]["current"])
        self.assertEqual(a["remote"]["as_of"], iso(NOW - 60), "as of the newer of last_sync and the card's last event")
        self.assertEqual(a["state"]["word"], "working")
        self.assertEqual(a["join"]["by"], "card")
        self.assertEqual(a["title"], "Stale work on win-a")
        self.assertEqual(a["open"]["remote_control"], "https://claude.ai/code/session_aaaa00")
        self.assertIsNone(a["open"]["desktop"])
        b = next(s for s in tracks["t-claim"]["sessions"] if s["id"] == "bbbb0002")
        self.assertEqual((b["join"]["by"], b["state"]["word"], b["remote"]["current"]), ("branch", "idle", True))
        self.assertEqual(b["remote"]["as_of"], iso(NOW - 120))

    def test_only_current_remote_sessions_count_and_reach_other(self) -> None:
        doc = self.build(share=self.share)
        remote = self.remote_sessions(doc)
        self.assertEqual(remote["dddd0004"]["state"]["word"], "ended")
        self.assertFalse(remote["dddd0004"]["remote"]["current"])
        self.assertFalse(remote["eeee0005"]["remote"]["current"], "no hook event for 2 h: not current")
        self.assertFalse(remote["gggg0007"]["remote"]["current"], "its host stopped reporting 3 h ago")
        self.assertEqual(remote["gggg0007"]["remote"]["host_status"], "offline")
        other = {s["id"]: s for s in doc["other_sessions"]}
        self.assertIn("cccc0003", other)
        self.assertEqual(other["cccc0003"]["projects"], [])
        self.assertIn("ffff0006", other, "a card from before r3's hook (no title or branch) still reads")
        self.assertIsNone(other["ffff0006"]["title"])
        self.assertNotIn("dddd0004", other)
        self.assertEqual(doc["summary"]["sessions_remote"], 4, "A, B, C and F are current; D, E and G are not")
        plain = self.build(share=None)
        for key in ("sessions_live", "sessions_matched", "sessions_other"):
            self.assertEqual(doc["summary"][key], plain["summary"][key], f"{key} counts this machine's live sessions only")

    def test_this_machine_wins_over_any_card(self) -> None:
        doc = self.build(share=self.share)
        remote = self.remote_sessions(doc)
        self.assertNotIn("hhhh0008", remote, "this machine's own folder is skipped: its sessions come from its own files")
        self.assertNotIn(WAITING, remote, "a session id this machine sees locally is never doubled by a card")
        waiting = [s for t in self.tracks(doc).values() for s in t["sessions"] if s["id"] == WAITING]
        self.assertEqual(len(waiting), 1)
        self.assertTrue(waiting[0]["live"])

    def test_a_track_names_the_machines_it_runs_on(self) -> None:
        doc = self.build(share=self.share)
        tracks = self.tracks(doc)
        claim = {h["host"]: h for h in tracks["t-claim"]["hosts"]}
        self.assertEqual(set(claim), {"win-a"})
        self.assertEqual(sorted(claim["win-a"]["via"]), ["sessions", "sources"])
        stale = {h["host"]: h for h in tracks["t-stale"]["hosts"]}
        self.assertEqual(set(stale), {"win-a"}, "only hosts with a CURRENT session (or a source) label the track")
        self.assertEqual(tracks["t-busy"]["hosts"], [])

    def test_a_remote_working_session_moves_its_track(self) -> None:
        plain = self.tracks(self.build(share=None))["t-stale"]
        self.assertEqual(plain["state"]["word"], "stale")
        doc = self.tracks(self.build(share=self.share))["t-stale"]
        self.assertEqual(doc["state"]["word"], "working")
        self.assertEqual(doc["state"]["rule"], "remote")
        self.assertIn("win-a", doc["state"]["why"])
        self.assertIn("as of", doc["state"]["why"])

    def test_merged_sources_take_other_machines_keys_but_not_this_ones(self) -> None:
        from vibetracks.home.remote import merged_sources

        merged = merged_sources(self.share, OWN)
        self.assertEqual(merged["fixture_events"], str((self.share / "hosts" / "win-a" / "files" / "fixture_events" / "events.jsonl").resolve()))
        self.assertNotIn("own_key", merged, "this machine's own mirror never overrides its own files")
        self.assertIn("kinsim_status", merged, "every local key is still there")

    def test_share_discovery(self) -> None:
        from vibetracks.home.remote import default_share, this_host_names

        self.assertIsNone(default_share({"VIBETRACKS_SHARE": "off"}, home=self.root))
        self.assertEqual(default_share({"VIBETRACKS_SHARE": str(self.share)}, home=self.root), self.share)
        self.assertIsNone(default_share({}, home=self.root), "no ~/vibetracks-share: no share")
        (self.root / "vibetracks-share" / "hosts").mkdir(parents=True)
        self.assertEqual(default_share({}, home=self.root), self.root / "vibetracks-share")
        (self.root / ".vibetracks").mkdir()
        (self.root / ".vibetracks" / "remote.json").write_text(json.dumps({"host": "Win-A"}), encoding="utf-8")
        self.assertIn("win-a", this_host_names({"VIBETRACKS_HOST": "lap-1"}, home=self.root))
        self.assertIn("lap-1", this_host_names({"VIBETRACKS_HOST": "lap-1"}, home=self.root))


class SessionHookCard(unittest.TestCase):
    """The hook also records the session's title and git branch (read from its transcript's tail), so a card joins a
    track by the same branch and title rules as a local session."""

    def test_card_carries_title_and_branch(self) -> None:
        from vibetracks.remote import session_hook

        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in [
                {"type": "user", "gitBranch": "claude/old", "cwd": "C:/x", "timestamp": "2026-10-09T10:00:00Z"},
                {"type": "custom-title", "customTitle": "Win-A kinsim run", "sessionId": "s1"},
                {"type": "assistant", "gitBranch": "claude/kinsim-win", "cwd": "C:/x", "timestamp": "2026-10-09T10:01:00Z",
                 "message": {"model": "claude-opus-5-5"}},
            ]) + "\n", encoding="utf-8")
            event = json.dumps({"session_id": "s1", "cwd": "C:/x", "hook_event_name": "Stop", "transcript_path": str(transcript)})
            self.assertEqual(session_hook.main(["--share", tmp, "--host", "win-a"], event, {}), 0)
            saved = json.loads((Path(tmp) / "hosts" / "win-a" / "sessions" / "s1.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["title"], "Win-A kinsim run")
            self.assertEqual(saved["branch"], "claude/kinsim-win")
            self.assertEqual(saved["model"], "claude-opus-5-5")


if __name__ == "__main__":
    unittest.main()
