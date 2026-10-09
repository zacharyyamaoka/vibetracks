"""Unit tests for vibetracks/remote/ (the builder's own; tests/test_remote_acceptance.py is the frozen contract).

    python3 -m pytest -q tests/test_remote_units.py      (from the repo root)
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from vibetracks.remote import hub, session_hook, share, sync

PAST = 1767268800  # 2026-01-01T12:00:00Z
REPO = Path(__file__).resolve().parents[1]
NETWORK_GIT = {"fetch", "pull", "push", "ls-remote", "clone"}


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
        # an idle worker heartbeats every 300 s: still online at 320 s, stale only after heartbeat + grace
        self.assertEqual(hub.host_status(now - 320, 3, now, 300), "online")
        self.assertEqual(hub.host_status(now - 331, 3, now, 300), "stale")

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


def spy_git(calls: list[str]):
    """A stand-in for sync._git that records each git subcommand, then runs it."""

    real = sync._git

    def spy(share_path, *args, **kwargs):
        calls.append(args[0])
        return real(share_path, *args, **kwargs)

    return mock.patch.object(sync, "_git", spy)


class QuietWorker(Temp):
    def config(self, clone: Path, **extra) -> dict:
        status = self.tmp / "status.json"
        if not status.exists():
            status.write_text('{"wave": 1}')
        return {"host": "win-a", "share": str(clone), "interval_s": 3, "heartbeat_s": 300,
                "mirror": [{"key": "kinsim_status", "path": str(status)}], **extra}

    def test_an_idle_tick_runs_no_network_git(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        cfg = self.config(clones["win-a"])
        t0 = time.time()
        self.assertTrue(sync.sync_once(cfg, now=t0)["pushed"])
        calls: list[str] = []
        with spy_git(calls):
            quiet = sync.sync_once(cfg, now=t0 + 10)
        self.assertIsNone(quiet["error"], quiet)
        self.assertFalse(quiet["committed"] or quiet["pushed"] or quiet["pulled"], quiet)
        # Local reads only (status / rev-parse / rev-list): what decides "anything to send" without the network.
        self.assertEqual(set(calls) & NETWORK_GIT, set(), calls)
        self.assertLessEqual(set(calls), {"status", "rev-parse", "rev-list"}, calls)

    def test_a_card_written_by_the_hook_is_sent_without_any_mirror_change(self) -> None:
        origin, clones = make_share(self.tmp, "win-a")
        cfg = self.config(clones["win-a"])
        t0 = time.time()
        sync.sync_once(cfg, now=t0)
        session_hook.main(["--share", str(clones["win-a"]), "--host", "win-a"], json.dumps({"session_id": "s9"}), {})
        result = sync.sync_once(cfg, now=t0 + 5)
        self.assertTrue(result["pushed"], result)
        self.assertIn("hosts/win-a/sessions/s9.json", git(origin, "ls-tree", "-r", "--name-only", "HEAD"))

    def test_an_unpushed_local_commit_is_sent(self) -> None:
        origin, clones = make_share(self.tmp, "win-a")
        cfg = self.config(clones["win-a"])
        t0 = time.time()
        sync.sync_once(cfg, now=t0)
        (clones["win-a"] / "hosts/win-a/note.txt").write_text("x")
        git(clones["win-a"], "add", "hosts/win-a/note.txt")
        git(clones["win-a"], "commit", "-q", "-m", "local only")
        self.assertTrue(sync.sync_once(cfg, now=t0 + 5)["pushed"])
        self.assertEqual(git(origin, "rev-parse", "main"), git(clones["win-a"], "rev-parse", "HEAD"))

    def test_receive_interval_pulls_while_idle_and_zero_never_does(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        t0 = time.time()
        for receive, expect in ((0, [False, False]), (60, [False, True])):
            with self.subTest(receive_interval_s=receive):
                sync._last_receive.clear()
                cfg = self.config(clones["win-a"], receive_interval_s=receive)
                sync.sync_once(cfg, now=t0)  # the first round of a fresh process sends its heartbeat
                pulled = []
                for offset in (10, 70):
                    calls: list[str] = []
                    with spy_git(calls):
                        result = sync.sync_once(cfg, now=t0 + offset)
                    self.assertIsNone(result["error"], result)
                    self.assertNotIn("push", calls)
                    pulled.append("pull" in calls)
                self.assertEqual(pulled, expect)
                t0 += 1000  # past the next heartbeat for the next subtest's first round

    def test_poke_after_a_push_and_a_failed_poke_is_never_an_error(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        received: list[tuple[str, str, bytes]] = []

        class Catch(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received.append((self.path, self.headers["Content-Type"], body))
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Catch)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        cfg = self.config(clones["win-a"], poke_url=f"http://127.0.0.1:{server.server_port}/api/poke")
        result = sync.sync_once(cfg)
        self.assertTrue(result["pushed"] and result["poked"], result)
        self.assertEqual(received, [("/api/poke", "application/json", b'{"host": "win-a"}')])

        # Nothing to send: no push, so no poke either.
        self.assertIsNone(sync.sync_once(cfg)["poked"])

        # A hub that is down: the push still counts, the poke is logged and returns False.
        dead = socket_port()
        (self.tmp / "status.json").write_text('{"wave": 2}')
        cfg["poke_url"] = f"http://127.0.0.1:{dead}/api/poke"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = sync.sync_once(cfg)
        self.assertIsNone(result["error"], result)
        self.assertTrue(result["pushed"])
        self.assertIs(result["poked"], False)
        self.assertIn("poke", out.getvalue())

    def test_log_file(self) -> None:
        log = self.tmp / "sync.log"
        self.addCleanup(setattr, sync, "_log_path", None)
        sync._log_path = str(log)
        with contextlib.redirect_stdout(io.StringIO()):
            sync._log("hello")
        self.assertRegex(log.read_text(), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d hello\n$")


def socket_port() -> int:
    """A loopback port nothing listens on (bound, read, released)."""

    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class SetupCommands(Temp):
    def run_main(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sync.main(list(argv)), 0)
        return out.getvalue()

    def test_init_writes_a_valid_config_and_sets_the_identity(self) -> None:
        origin, _ = make_share(self.tmp)
        clone = self.tmp / "fresh"
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
        loop = self.tmp / "loop"
        loop.mkdir()
        target = self.tmp / "cfg" / "sync.json"
        printed = self.run_main("init", "--share", str(clone), "--host", "win-a", "--config", str(target),
                                "--mirror", f"kinsim_events={loop}", "--poke-url", "http://hub:4470/api/poke",
                                "--heartbeat", "120")
        config = json.loads(target.read_text())
        self.assertEqual(config, {"host": "win-a", "share": clone.resolve().as_posix(), "interval_s": 3,
                                  "heartbeat_s": 120, "receive_interval_s": 0,
                                  "mirror": [{"key": "kinsim_events", "path": loop.resolve().as_posix()}],
                                  "poke_url": "http://hub:4470/api/poke"})
        self.assertEqual(git(clone, "config", "--local", "user.name").strip(), "win-a")
        self.assertEqual(git(clone, "config", "--local", "user.email").strip(), "win-a@vibetracks.invalid")
        self.assertIn("--once", printed)
        self.assertIn("hook-config", printed)
        # the config it wrote runs
        result = sync.sync_once(sync.load_config(target))
        self.assertIsNone(result["error"], result)
        self.assertTrue(result["pushed"])

        # an identity that is already set is kept
        git(clone, "config", "--local", "user.name", "Zach")
        self.run_main("init", "--share", str(clone), "--host", "win-a", "--config", str(target))
        self.assertEqual(git(clone, "config", "--local", "user.name").strip(), "Zach")

    def test_init_refuses_a_folder_that_is_not_a_clone_or_a_remote_that_does_not_answer(self) -> None:
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sync.main(["init", "--share", str(plain), "--host", "win-a", "--config", str(self.tmp / "c.json")])
        self.assertIn("not the top of a git clone", str(caught.exception))
        origin, clones = make_share(self.tmp, "win-a")
        origin.rename(self.tmp / "gone.git")
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sync.main(["init", "--share", str(clones["win-a"]), "--host", "win-a", "--config", str(self.tmp / "c.json")])
        self.assertIn("ls-remote", str(caught.exception))
        self.assertFalse((self.tmp / "c.json").exists())

    def test_hook_config_writes_remote_json_and_prints_the_guarded_line(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        home = self.tmp / "home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            printed = self.run_main("hook-config", "--share", str(clones["win-a"]), "--host", "win-a",
                                    "--tracks-map", '{"kinsim": ["/home/bam/bam_ws"]}')
        remote = json.loads((home / ".vibetracks/remote.json").read_text())
        self.assertEqual(remote, {"python": sys.executable, "share": clones["win-a"].resolve().as_posix(),
                                  "host": "win-a", "tracks_map": {"kinsim": ["/home/bam/bam_ws"]}})
        self.assertIn(sync.HOOK_LINE, printed)
        self.assertNotIn(sys.executable, sync.HOOK_LINE)  # the shared line names no machine's paths
        launcher = home / ".vibetracks/hook"
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn(Path(sys.executable).as_posix(), launcher.read_text())
        self.assertIn(sync.HOOK_SCRIPT.as_posix(), launcher.read_text())
        self.assertTrue(sync.HOOK_SCRIPT.is_file())
        for event in ("UserPromptSubmit", "Stop", "SessionEnd"):
            self.assertIn(event, printed)


    def test_the_shared_line_runs_this_machines_launcher_end_to_end(self) -> None:
        # The exact line from settings.json, run by a POSIX shell the way Claude Code runs hooks: it must reach the
        # launcher hook-config wrote, which must reach the hook script, which must write the session card.
        _, clones = make_share(self.tmp, "win-a")
        home = self.tmp / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO),
               "CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01Shared"}
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.run_main("hook-config", "--share", str(clones["win-a"]), "--host", "win-a")
        stdin = json.dumps({"session_id": "5e55e55e-0000-1111-2222-333344445555", "cwd": "/x",
                            "hook_event_name": "Stop"})
        done = subprocess.run(["sh", "-c", sync.HOOK_LINE], input=stdin, capture_output=True, text=True,
                              timeout=30, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        card = json.loads((clones["win-a"] / "hosts/win-a/sessions/5e55e55e-0000-1111-2222-333344445555.json")
                          .read_text())
        self.assertEqual(card["url"], "https://claude.ai/code/session_01Shared")
        # and on a machine that never ran hook-config the same line is a silent no-op
        bare = self.tmp / "bare-home"
        bare.mkdir()
        done = subprocess.run(["sh", "-c", sync.HOOK_LINE], input=stdin, capture_output=True, text=True,
                              timeout=30, env={**env, "HOME": str(bare)})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))


class HookWrapper(Temp):
    def run_hook(self, home: Path, stdin: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(sync.HOOK_SCRIPT)], input=stdin, capture_output=True, text=True,
                              timeout=30, env={**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO), **env})

    def test_without_remote_json_it_does_nothing_and_exits_0(self) -> None:
        home = self.tmp / "home"
        home.mkdir()
        done = self.run_hook(home, json.dumps({"session_id": "s1"}))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        (home / ".vibetracks").mkdir()
        (home / ".vibetracks/remote.json").write_text("{not json")
        self.assertEqual(self.run_hook(home, "{}").returncode, 0)
        (home / ".vibetracks/remote.json").write_text(json.dumps({"python": "/no/such/python", "share": "x",
                                                                  "host": "win-a"}))
        self.assertEqual(self.run_hook(home, "{}").returncode, 0)

    def test_with_remote_json_it_passes_stdin_and_environment_through(self) -> None:
        _, clones = make_share(self.tmp, "win-a")
        home = self.tmp / "home"
        (home / ".vibetracks").mkdir(parents=True)
        share.write_json_atomic(home / ".vibetracks/remote.json",
                                {"python": sys.executable, "share": str(clones["win-a"]), "host": "win-a",
                                 "tracks_map": {"cad": ["C:/Users/BAM/cad-exporter"]}})
        event = {"session_id": "0000aaaa-1111", "cwd": "C:/Users/BAM/cad-exporter/sub",
                 "hook_event_name": "UserPromptSubmit"}
        done = self.run_hook(home, json.dumps(event), CLAUDE_CODE_BRIDGE_SESSION_ID="session_01Wrapped",
                             CLAUDE_CONFIG_DIR="C:/Users/BAM/.claude-bam")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        card = json.loads((clones["win-a"] / "hosts/win-a/sessions/0000aaaa-1111.json").read_text())
        self.assertEqual(card["url"], "https://claude.ai/code/session_01Wrapped")
        self.assertEqual(card["account"], "bam")
        self.assertEqual(card["track"], "cad")  # the tracks_map from remote.json reached the hook


class HubChecks(Temp):
    def make_hub(self, **kwargs) -> tuple[hub.Hub, list[float], list[int]]:
        clock = [1000.0]
        builds = [0]
        instance = hub.Hub(self.tmp / "share", self.tmp / "workspace", self.tmp / "data-home", host_name="hub",
                           log=lambda message: None, clock=lambda: clock[0], **kwargs)

        def fake_rebuild() -> None:
            builds[0] += 1
            instance.last_build = time.time()

        instance.rebuild = fake_rebuild
        return instance, clock, builds

    def test_adaptive_mode_switching(self) -> None:
        (self.tmp / "share").mkdir()
        h, clock, _ = self.make_hub(check_fast=5, check_slow=60, fast_window=120, rebuild_interval=10_000)
        h.tick()  # the first tick checks at once
        info = h.hub_info()
        self.assertEqual(info["check_mode"], "slow")
        self.assertEqual(info["next_check_in_s"], 60)
        self.assertIsNotNone(info["last_check"])

        h.poke("win-a")
        self.assertEqual(h.check_mode(), "fast")
        self.assertEqual(h.next_check_in_s(), 5)  # the switch takes effect now, not after the slow wait
        self.assertTrue(h._wake.is_set())
        h.tick(force_check=True)
        self.assertEqual(h.next_check_in_s(), 5)

        clock[0] += 119
        self.assertEqual(h.check_mode(), "fast")
        clock[0] += 2
        self.assertEqual(h.check_mode(), "slow")
        h.tick()  # the fast-period check was due: it runs and schedules the slow period
        self.assertEqual(h.next_check_in_s(), 60)
        state = h.live_state()["hub"]
        self.assertEqual((state["check_mode"], state["next_check_in_s"]), ("slow", 60))

    def test_a_stat_detected_local_change_triggers_a_rebuild_and_a_share_file_does_not(self) -> None:
        (self.tmp / "share/hosts/win-a/files").mkdir(parents=True)
        local_file = self.tmp / "local/status.json"
        local_dir = self.tmp / "local/runs"
        local_dir.mkdir(parents=True)
        local_file.write_text("{}")
        in_share = self.tmp / "share/hosts/win-a/files/x.json"
        in_share.write_text("{}")
        h, _, builds = self.make_hub(check_fast=5, check_slow=60, rebuild_interval=10_000)
        h.projection = {"tracks": [{"id": "t", "freshness": {"sources": [
            {"key": "a", "path": str(local_file)}, {"key": "b", "path": str(local_dir)},
            {"key": "c", "path": str(in_share)}]}}]}
        self.assertEqual([str(p) for p in hub.local_source_paths(h.projection, h.share)],
                         sorted([str(local_dir.resolve()), str(local_file.resolve())]))
        h.tick()
        self.assertEqual(builds[0], 1)  # the first build
        h.tick()
        self.assertEqual(builds[0], 1)  # nothing changed

        in_share.write_text('{"changed": "in the share"}')
        h.tick()
        self.assertEqual(builds[0], 1)  # the share's files arrive by pull, not by stat

        local_file.write_text('{"wave": 2}')
        h.tick()
        self.assertEqual(builds[0], 2)
        self.assertEqual(h.check_mode(), "fast")

        (local_dir / "run-7.json").write_text("{}")  # a new child of a source directory
        h.tick()
        self.assertEqual(builds[0], 3)


class HubPosts(Temp):
    def setUp(self) -> None:
        super().setUp()
        (self.tmp / "share").mkdir()
        self.hub = hub.Hub(self.tmp / "share", self.tmp / "workspace", self.tmp / "data-home", host_name="hub",
                           log=lambda message: None)
        self.hub.rebuild = lambda: setattr(self.hub, "last_build", time.time())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), hub.make_handler(self.hub, hub.LOOPBACK))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def post(self, path: str, body: bytes, content_type: str = "application/json") -> tuple[int, dict]:
        request = urllib.request.Request(self.base + path, data=body, method="POST",
                                         headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_body_size_limit_and_routes(self) -> None:
        status, reply = self.post("/api/poke", json.dumps({"host": "win-a", "pad": "x" * 5000}).encode())
        self.assertEqual(status, 413, reply)
        self.assertEqual(self.post("/api/poke", b'{"host": "win-a"}'), (202, {"ok": True}))
        self.assertEqual(self.post("/api/poke", b'{"host": "win-a"}', "application/json; charset=utf-8")[0], 202)
        self.assertEqual(self.post("/api/poke", b"[1]")[0], 400)
        self.assertEqual(self.post("/api/nope", b"{}")[0], 404)
        status, reply = self.post("/api/refresh", b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(set(reply), {"ok", "revision", "changed", "took_s"})
        self.assertTrue(reply["ok"])

    def test_refresh_joins_one_in_flight(self) -> None:
        started, release = threading.Event(), threading.Event()
        builds = []

        def slow_rebuild() -> None:
            builds.append(1)
            started.set()
            release.wait(10)
            self.hub.last_build = time.time()

        self.hub.rebuild = slow_rebuild
        results = []
        first = threading.Thread(target=lambda: results.append(self.hub.refresh_now()))
        first.start()
        self.assertTrue(started.wait(10))
        second = threading.Thread(target=lambda: results.append(self.hub.refresh_now()))
        second.start()
        time.sleep(0.2)
        release.set()
        first.join(10)
        second.join(10)
        self.assertEqual(len(builds), 1)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])


class HostSessions(Temp):
    def test_every_card_shows_under_its_machine_live_first_and_capped(self) -> None:
        now = time.time()
        write_host(self.tmp, "win-a", now - 2)
        sessions = self.tmp / "hosts/win-a/sessions"
        share.write_json_atomic(sessions / "live.json", {"session_id": "live", "cwd": "C:\\Users\\BAM\\cad-exporter",
                                                         "track": None, "url": "https://claude.ai/code/session_1",
                                                         "last_seen": share.iso_utc(now - 5), "ended": False})
        for n in range(12):
            share.write_json_atomic(sessions / f"old{n:02d}.json", {"session_id": f"old{n:02d}", "cwd": "/home/bam/x/",
                                                                     "last_seen": share.iso_utc(now - 7200 - n),
                                                                     "ended": True})
        state = hub.compute_state(None, self.tmp, "hub", {}, now)
        rows = state["hosts"][0]["sessions"]
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0]["session_id"], "live")
        self.assertTrue(rows[0]["live"])
        self.assertEqual(rows[0]["project"], "cad-exporter")
        self.assertIsNone(rows[0]["track"])
        self.assertEqual([r["session_id"] for r in rows[1:]], [f"old{n:02d}" for n in range(10)])
        self.assertEqual(rows[1]["project"], "x")
        self.assertEqual(set(rows[0]), set(hub.HOST_SESSION_FIELDS))


if __name__ == "__main__":
    unittest.main()
