"""Unit tests for vibetracks/remote/ (the builder's own; tests/test_remote_acceptance.py is the frozen contract).

    python3 -m pytest -q tests/test_remote_units.py      (from the repo root)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from vibetracks.remote import hub, session_hook, share, sync

PAST = 1767268800  # 2026-01-01T12:00:00Z


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def make_share(root: Path, *hosts: str) -> tuple[Path, dict[str, Path]]:
    origin = root / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    seed = root / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.invalid")
    (seed / "README.md").write_text("share\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")
    clones = {}
    for host in hosts:
        clone = root / host
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
        git(clone, "config", "user.name", host)
        git(clone, "config", "user.email", f"{host}@example.invalid")
        clones[host] = clone
    return origin, clones


def write_host(share_root: Path, host: str, last_sync: float, sources: dict[str, str] | None = None,
               interval_s: float = 3) -> Path:
    folder = share_root / "hosts" / host
    folder.mkdir(parents=True, exist_ok=True)
    share.write_json_atomic(folder / "host.json", {"host": host, "last_sync": share.iso_utc(last_sync),
                                                   "interval_s": interval_s, "mirrors": [], "skipped": [], "error": None})
    if sources is not None:
        share.write_json_atomic(folder / "sources.json", sources)
    return folder


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-remote-unit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class MergeSources(Temp):
    def test_duplicate_key_goes_to_the_newer_host_and_is_reported(self) -> None:
        now = time.time()
        write_host(self.tmp, "win-a", now - 100, {"kinsim_events": "files/kinsim_events/loop_events.jsonl",
                                                  "only_a": "files/only_a/x.json"})
        write_host(self.tmp, "win-b", now - 5, {"kinsim_events": "files/kinsim_events/loop_events.jsonl"})
        paths, problems = hub.merge_sources(self.tmp)
        self.assertEqual(paths["kinsim_events"],
                         str((self.tmp / "hosts/win-b/files/kinsim_events/loop_events.jsonl").resolve()))
        self.assertEqual(paths["only_a"], str((self.tmp / "hosts/win-a/files/only_a/x.json").resolve()))
        duplicates = [p for p in problems if p["kind"] == "duplicate_key"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["key"], "kinsim_events")
        self.assertEqual(duplicates[0]["hosts"], ["win-a", "win-b"])

    def test_a_manifest_cannot_point_outside_its_host_folder(self) -> None:
        write_host(self.tmp, "win-a", time.time(), {"escape": "../win-b/files/x", "absolute": "/etc/passwd",
                                                    "fine": "files/fine/a.json"})
        paths, problems = hub.merge_sources(self.tmp)
        self.assertEqual(sorted(paths), ["fine"])
        self.assertEqual(sorted(p["key"] for p in problems if p["kind"] == "bad_path"), ["absolute", "escape"])


class HostStatus(unittest.TestCase):
    def test_thresholds(self) -> None:
        now = 10_000.0
        # online up to 3 x interval + 30 s, stale up to an hour, then offline
        self.assertEqual(hub.host_status(now - 39, 3, now), "online")
        self.assertEqual(hub.host_status(now - 39.5, 3, now), "stale")
        self.assertEqual(hub.host_status(now - 3600, 3, now), "stale")
        self.assertEqual(hub.host_status(now - 3601, 3, now), "offline")
        self.assertEqual(hub.host_status(now - 75, 15, now), "online")
        self.assertEqual(hub.host_status(None, 3, now), "offline")

    def test_host_header_guard(self) -> None:
        allowed = hub.LOOPBACK | {"hub.tailnet.ts.net"}
        for header in ("127.0.0.1:4470", "localhost", "[::1]:4470", "::1", "HUB.tailnet.ts.net:443"):
            self.assertTrue(hub.host_allowed(header, allowed), header)
        for header in ("evil.example.com", "", None, "127.0.0.1.evil.com:80", "[::2]:4470"):
            self.assertFalse(hub.host_allowed(header, allowed), header)


class Mirror(Temp):
    def config(self, clone: Path, mirror: list[dict], **extra) -> dict:
        return {"host": "win-a", "share": str(clone), "interval_s": 1, "heartbeat_s": 3600, "mirror": mirror, **extra}

    def test_oversize_file_is_skipped_and_recorded(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        local = self.tmp / "local"
        local.mkdir()
        (local / "small.json").write_text("{}")
        (local / "big.bin").write_bytes(b"x" * 2048)
        cfg = self.config(clones["win-a"], [{"key": "loop_dir", "path": str(local)}], max_file_bytes=1024)
        result = sync.sync_once(cfg)
        self.assertIsNone(result["error"], result)
        host = clones["win-a"] / "hosts/win-a"
        self.assertTrue((host / "files/loop_dir/small.json").is_file())
        self.assertFalse((host / "files/loop_dir/big.bin").exists())
        heartbeat = json.loads((host / "host.json").read_text())
        self.assertEqual([(s["key"], Path(s["path"]).name) for s in heartbeat["skipped"]], [("loop_dir", "big.bin")])
        self.assertIn("max_file_bytes", heartbeat["skipped"][0]["reason"])
        self.assertEqual(json.loads((host / "sources.json").read_text()), {"loop_dir": "files/loop_dir"})

    def test_directory_include_globs_prune_and_a_quiet_round_commits_nothing(self) -> None:
        origin, clones = make_share(self.tmp, "win-a")
        local = self.tmp / "loop"
        (local / "sub").mkdir(parents=True)
        (local / "status.json").write_text("{}")
        (local / "sub" / "events.jsonl").write_text("{}\n")
        (local / "notes.txt").write_text("not shared")
        cfg = self.config(clones["win-a"], [{"key": "rig_loop_dir", "path": str(local), "include": ["*.json", "*.jsonl"]}])
        self.assertIsNone(sync.sync_once(cfg)["error"])
        tracked = git(origin, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertIn("hosts/win-a/files/rig_loop_dir/status.json", tracked)
        self.assertIn("hosts/win-a/files/rig_loop_dir/sub/events.jsonl", tracked)
        self.assertNotIn("hosts/win-a/files/rig_loop_dir/notes.txt", tracked)

        quiet = sync.sync_once(cfg)
        self.assertIsNone(quiet["error"])
        self.assertFalse(quiet["committed"], quiet)

        (local / "status.json").unlink()
        self.assertTrue(sync.sync_once(cfg)["committed"])
        tracked = git(origin, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertNotIn("hosts/win-a/files/rig_loop_dir/status.json", tracked)

    def test_missing_source_is_recorded_and_keeps_the_last_copy(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        file = self.tmp / "status.json"
        file.write_text("{}")
        cfg = self.config(clones["win-a"], [{"key": "kinsim_status", "path": str(file)}])
        self.assertIsNone(sync.sync_once(cfg)["error"])
        file.unlink()
        result = sync.sync_once(cfg)
        self.assertIsNone(result["error"], result)
        host = clones["win-a"] / "hosts/win-a"
        self.assertTrue((host / "files/kinsim_status/status.json").is_file())
        self.assertEqual(json.loads((host / "sources.json").read_text()),
                         {"kinsim_status": "files/kinsim_status/status.json"})
        self.assertEqual(json.loads((host / "host.json").read_text())["skipped"][0]["reason"], "missing on this machine")

    def test_commit_author_date_is_the_workers_write_time(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        file = self.tmp / "loop_events.jsonl"
        file.write_text("{}\n")
        os.utime(file, (PAST, PAST))
        cfg = self.config(clones["win-a"], [{"key": "kinsim_events", "path": str(file)}])
        # a session card written now rides in the same commit but must not stamp the loop file as just written
        self.assertEqual(session_hook.main(["--share", str(clones["win-a"]), "--host", "win-a"],
                                           json.dumps({"session_id": "s1"}), {}), 0)
        self.assertIsNone(sync.sync_once(cfg)["error"])
        self.assertIn("hosts/win-a/sessions/s1.json", git(clones["win-a"], "show", "--name-only", "--format=", "HEAD"))
        log = git(clones["win-a"], "log", "-1", "--format=%at%n%B")
        self.assertEqual(int(log.splitlines()[0]), PAST)
        self.assertIn("vt-sync win-a: ", log)
        self.assertIn("Vibe-Host: win-a", log)


class RebaseConflict(Temp):
    def test_conflict_returns_an_error_and_loses_nothing(self) -> None:
        origin, clones = make_share(self.tmp, "win-a", "intruder")
        file = self.tmp / "status.json"
        file.write_text('{"v": 1}')
        cfg = {"host": "win-a", "share": str(clones["win-a"]), "heartbeat_s": 3600,
               "mirror": [{"key": "kinsim_status", "path": str(file)}]}
        self.assertIsNone(sync.sync_once(cfg)["error"])

        # Something breaks the one-writer rule: another clone rewrites win-a's heartbeat and pushes first.
        intruder = clones["intruder"]
        git(intruder, "pull", "-q", "--ff-only")
        (intruder / "hosts/win-a/host.json").write_text("{}\n")
        git(intruder, "commit", "-q", "-am", "intrude")
        git(intruder, "push", "-q", "origin", "HEAD:main")
        origin_head = git(origin, "rev-parse", "HEAD").strip()

        file.write_text('{"v": 22}')  # a new size, so win-a's own host.json changes too
        result = sync.sync_once(cfg)
        self.assertIsNotNone(result["error"], result)
        self.assertTrue(result["committed"])
        self.assertFalse(result["pushed"])
        clone = clones["win-a"]
        self.assertFalse((clone / ".git/rebase-merge").exists())
        self.assertFalse((clone / ".git/rebase-apply").exists())
        # the local commit is intact and holds the new reading; origin was never forced
        self.assertEqual(git(clone, "show", "HEAD:hosts/win-a/files/kinsim_status/status.json"), '{"v": 22}')
        self.assertEqual(git(origin, "rev-parse", "HEAD").strip(), origin_head)
        self.assertEqual(git(clone, "status", "--porcelain").strip(), "")


class PullRestore(Temp):
    def test_restore_mtimes_uses_each_files_last_commit(self) -> None:
        _, clones = make_share(self.tmp, "win-a", "hub")
        old, new = self.tmp / "old.json", self.tmp / "new.json"
        old.write_text("{}")
        new.write_text("{}")
        os.utime(old, (PAST, PAST))
        os.utime(new, (PAST + 3600, PAST + 3600))
        self.assertIsNone(sync.sync_once({"host": "win-a", "share": str(clones["win-a"]),
                                          "mirror": [{"key": "a", "path": str(old)}]})["error"])
        self.assertIsNone(sync.sync_once({"host": "win-a", "share": str(clones["win-a"]),
                                          "mirror": [{"key": "a", "path": str(old)},
                                                     {"key": "b", "path": str(new)}]})["error"])
        changed = sync.pull_and_restore(clones["hub"])
        self.assertIn("hosts/win-a/files/a/old.json", changed)
        self.assertAlmostEqual((clones["hub"] / "hosts/win-a/files/a/old.json").stat().st_mtime, PAST, delta=1)
        self.assertAlmostEqual((clones["hub"] / "hosts/win-a/files/b/new.json").stat().st_mtime, PAST + 3600, delta=1)
        self.assertEqual(sync.pull_and_restore(clones["hub"]), [])


class SessionHook(Temp):
    def test_model_track_and_account_extraction(self) -> None:
        transcript = self.tmp / "t.jsonl"
        rows = [{"type": "assistant", "message": {"model": "claude-opus-5-5"}},
                {"type": "user", "message": {"content": "hi"}},
                {"type": "assistant", "message": {"model": "<synthetic>"}}]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows) + '{"torn": ')
        tracks_map = json.dumps({"rig": ["/home/bam/bam_ws/.claude/worktrees/rig-loop"], "kinsim": ["/home/bam/bam_ws"]})
        stdin = json.dumps({"session_id": "abc-1", "cwd": "/home/bam/bam_ws/src/dev", "hook_event_name": "UserPromptSubmit",
                            "transcript_path": str(transcript)})
        env = {"CLAUDE_CONFIG_DIR": "/home/bam/.claude-bam", "AI_AGENT": "claude-code-desktop"}
        self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "win-a", "--tracks-map", tracks_map],
                                           stdin, env), 0)
        card = json.loads((self.tmp / "hosts/win-a/sessions/abc-1.json").read_text())
        self.assertEqual(card["model"], "claude-opus-5-5")
        self.assertEqual(card["track"], "kinsim")
        self.assertEqual(card["account"], "bam")
        self.assertEqual(card["agent"], "claude-code-desktop")
        self.assertFalse(card["ended"])
        started = card["started_at"]

        # the more specific prefix listed first wins; a sibling folder name does not match by string prefix
        self.assertEqual(session_hook.track_of("/home/bam/bam_ws/.claude/worktrees/rig-loop/x", None,
                                               json.loads(tracks_map)), "rig")
        self.assertIsNone(session_hook.track_of("/home/bam/bam_ws2", None, {"kinsim": ["/home/bam/bam_ws"]}))
        self.assertEqual(session_hook.account_of("/home/bam/.claude"), "claude")
        self.assertIsNone(session_hook.account_of(None))

        end = json.dumps({"session_id": "abc-1", "cwd": "/home/bam/bam_ws", "hook_event_name": "SessionEnd"})
        time.sleep(1.1)
        self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "win-a", "--track", "rig"], end, {}), 0)
        card = json.loads((self.tmp / "hosts/win-a/sessions/abc-1.json").read_text())
        self.assertTrue(card["ended"])
        self.assertEqual(card["started_at"], started)
        self.assertNotEqual(card["last_seen"], started)
        self.assertEqual(card["track"], "rig")
        self.assertIsNone(card["account"])
        self.assertEqual(card["agent"], "claude-code")

    def test_bad_input_never_fails(self) -> None:
        for stdin in ("", "[]", '{"session_id": "../escape"}', '{"session_id": 5}'):
            self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "win-a"], stdin, {}), 0)
        self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "bad/host"],
                                           json.dumps({"session_id": "s1"}), {}), 0)
        self.assertEqual(session_hook.main([], "{}", {}), 0)
        self.assertFalse((self.tmp / "hosts").exists())


class State(Temp):
    def projection(self) -> dict:
        return {"tracks": [
            {"id": "kinsim", "title": "Kinematic Sim", "kind": "loop", "parent": None, "summary": "s",
             "state": {"word": "Running", "tone": "ok"}, "needs_you_count": {"open": 1, "blocking": 0},
             "freshness": {"newest": "2026-10-04T19:03:09-07:00", "age_h": 1.0, "stale": False, "sources": []},
             "registry": {"sources": ["kinsim_status", "kinsim_loop_dir"]},
             "kpis": [{"id": "none", "label": "Nothing yet", "values": [{"value": None}]},
                      {"id": "rungs", "label": "Rungs", "unit": "rungs", "direction": "higher",
                       "values": [{"value": None}, {"value": 3}, {"value": True}, {"value": 19}]}]},
            {"id": "rig", "title": "Rig", "kind": "loop", "parent": None, "registry": {"sources": ["rig_ladder"]},
             "freshness": {"newest": None, "sources": []}, "kpis": []},
            {"id": "can12", "title": "can12", "kind": "deployment", "parent": "rig", "kpis": []},
        ], "registry": {"problems": []}}

    def test_revision_is_stable_when_nothing_changed(self) -> None:
        now = time.time()
        write_host(self.tmp, "win-a", now - 2, {"kinsim_status": "files/kinsim_status/status.json"})
        info = {"host_name": "hub", "share_head": "abc", "last_pull": share.iso_utc(now), "build_error": None}
        first = hub.compute_state(self.projection(), self.tmp, "hub", info, now)
        later = hub.compute_state(self.projection(), self.tmp, "hub", {**info, "last_pull": share.iso_utc(now + 5)},
                                  now + 5)
        self.assertEqual(first["revision"], later["revision"])
        self.assertNotEqual(first["hosts"][0]["age_s"], later["hosts"][0]["age_s"])

        moved = self.projection()
        moved["tracks"][0]["freshness"]["newest"] = "2026-10-04T19:04:00-07:00"
        self.assertNotEqual(hub.compute_state(moved, self.tmp, "hub", info, now)["revision"], first["revision"])

        # a host crossing its online threshold is a real change
        offline = hub.compute_state(self.projection(), self.tmp, "hub", info, now + 7200)
        self.assertNotEqual(offline["revision"], first["revision"])

    def test_tracks_attribution_headline_and_sessions(self) -> None:
        now = time.time()
        write_host(self.tmp, "win-a", now - 2, {"kinsim_status": "files/kinsim_status/status.json"})
        sessions = self.tmp / "hosts/win-a/sessions"
        share.write_json_atomic(sessions / "s1.json", {"session_id": "s1", "track": "kinsim", "url": None,
                                                       "last_seen": share.iso_utc(now - 60), "ended": False})
        share.write_json_atomic(sessions / "s2.json", {"session_id": "s2", "track": "kinsim", "host": "spoofed",
                                                       "last_seen": share.iso_utc(now - 3600), "ended": False})
        state = hub.compute_state(self.projection(), self.tmp, "workstation", {}, now)
        self.assertEqual([t["id"] for t in state["tracks"]], ["kinsim", "rig"])
        kinsim, rig = state["tracks"]
        self.assertEqual(kinsim["hosts"], ["win-a"])
        self.assertEqual(rig["hosts"], ["workstation"])
        self.assertEqual(kinsim["headline"]["latest"], 19)
        self.assertEqual(kinsim["headline"]["values"], [3, 19])
        self.assertIsNone(rig["headline"])
        self.assertEqual([(c["session_id"], c["live"], c["host"]) for c in kinsim["sessions"]],
                         [("s1", True, "win-a"), ("s2", False, "win-a")])
        self.assertEqual(state["hosts"][0]["sessions_live"], 1)
        self.assertEqual(state["hosts"][0]["status"], "online")

        detail = hub.track_detail(self.projection(), state, "can12", self.tmp, "workstation")
        self.assertEqual(detail["hosts"], ["workstation"])
        self.assertIsNone(hub.track_detail(self.projection(), state, "nope", self.tmp, "workstation"))


if __name__ == "__main__":
    unittest.main()
