"""Acceptance for the multi-computer layer (vibetracks/remote/): frozen BEFORE the build, never edited by the builder.

    python3 -m pytest -q tests/test_remote_acceptance.py      (from the repo root)

The contract these pin:
- A machine shares its loop files by mirroring them into ``hosts/<host>/`` of a git "share" and syncing (sync.py).
- The hub sees each file with the WORKER's modification time, because the dashboard's freshness/stall rule reads mtime
  and a git checkout would otherwise stamp every file with the pull time.
- A machine only ever commits its own ``hosts/<host>/`` folder (one writer per folder, so merges never conflict).
- The hub server answers only loopback Host headers unless told otherwise, and shows an edit made on another machine
  within seconds, attributed to that machine.
- A Claude Code hook records the session's Remote Control link so the hub can offer "talk to this agent".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_KINSIM_HOME = Path("~/.local/share/bam_curriculum").expanduser()
PAST = 1767268800  # 2026-01-01T12:00:00Z, a worker write time nowhere near "now"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def make_share(root: Path, *hosts: str) -> tuple[Path, dict[str, Path]]:
    """A bare origin (stand-in for GitHub) with one seeded commit, and one clone per host."""

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


def config(host: str, share: Path, mirror: list[dict]) -> dict:
    return {"host": host, "share": str(share), "interval_s": 1, "heartbeat_s": 1, "mirror": mirror}


class SyncAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-remote-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_worker_mtime_survives_the_trip_to_the_hub(self) -> None:
        from vibetracks.remote import sync

        origin, clones = make_share(self.tmp, "win-a", "hub")
        local = self.tmp / "win-a-local"
        local.mkdir()
        events = local / "loop_events.jsonl"
        events.write_text('{"event": "tick"}\n')
        os.utime(events, (PAST, PAST))

        result = sync.sync_once(config("win-a", clones["win-a"], [{"key": "kinsim_events", "path": str(events)}]))
        self.assertIsNone(result["error"], result)
        self.assertTrue(result["committed"])
        self.assertTrue(result["pushed"])

        changed = sync.pull_and_restore(clones["hub"])
        landed = [path for path in changed if path.startswith("hosts/win-a/") and path.endswith("loop_events.jsonl")]
        self.assertEqual(len(landed), 1, changed)
        hub_file = clones["hub"] / landed[0]
        self.assertEqual(hub_file.read_text(), '{"event": "tick"}\n')
        self.assertAlmostEqual(hub_file.stat().st_mtime, PAST, delta=1.0)

        manifest = json.loads((clones["hub"] / "hosts/win-a/sources.json").read_text())
        self.assertEqual((clones["hub"] / "hosts/win-a" / manifest["kinsim_events"]).resolve(), hub_file.resolve())
        self.assertTrue((clones["hub"] / "hosts/win-a/host.json").is_file())

    def test_a_machine_only_ever_commits_its_own_folder(self) -> None:
        from vibetracks.remote import sync

        origin, clones = make_share(self.tmp, "win-a")
        status = self.tmp / "status.json"
        status.write_text("{}")
        (clones["win-a"] / "stray.txt").write_text("not mine to share")
        (clones["win-a"] / "hosts" / "win-b").mkdir(parents=True)
        (clones["win-a"] / "hosts" / "win-b" / "host.json").write_text("{}")

        result = sync.sync_once(config("win-a", clones["win-a"], [{"key": "kinsim_status", "path": str(status)}]))
        self.assertIsNone(result["error"], result)

        tracked = git(origin, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertIn("README.md", tracked)
        foreign = [path for path in tracked if path != "README.md" and not path.startswith("hosts/win-a/")]
        self.assertEqual(foreign, [])


class SessionHookAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-hook-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_records_the_remote_control_link_and_never_fails_the_hook(self) -> None:
        from vibetracks.remote import session_hook

        stdin = json.dumps({"session_id": "6f0c2d1e-aaaa-bbbb-cccc-000000000001", "cwd": "/home/bam/bam_ws",
                            "hook_event_name": "UserPromptSubmit"})
        env = {"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01TestBridge", "CLAUDE_CONFIG_DIR": "/home/bam/.claude-bam"}
        code = session_hook.main(["--share", str(self.tmp), "--host", "win-a", "--track", "kinsim"], stdin, env)
        self.assertEqual(code, 0)
        card = json.loads((self.tmp / "hosts/win-a/sessions/6f0c2d1e-aaaa-bbbb-cccc-000000000001.json").read_text())
        self.assertEqual(card["url"], "https://claude.ai/code/session_01TestBridge")
        self.assertEqual(card["host"], "win-a")
        self.assertEqual(card["track"], "kinsim")

        no_link = json.dumps({"session_id": "6f0c2d1e-aaaa-bbbb-cccc-000000000002", "cwd": "/x",
                              "hook_event_name": "Stop"})
        self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "win-a"], no_link, {}), 0)
        card = json.loads((self.tmp / "hosts/win-a/sessions/6f0c2d1e-aaaa-bbbb-cccc-000000000002.json").read_text())
        self.assertIsNone(card["url"])

        self.assertEqual(session_hook.main(["--share", str(self.tmp), "--host", "win-a"], "not json", {}), 0)


@unittest.skipUnless((LIVE_KINSIM_HOME / "status.json").is_file(), "needs the real kinsim loop files as a fixture")
class HubAcceptance(unittest.TestCase):
    """The hub over a two-machine share, with the real kinsim adapter reading files that came from win-a."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-hub-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _, self.clones = make_share(self.tmp, "win-a", "hub")
        self.local = self.tmp / "win-a-local"
        self.local.mkdir()
        for name in ("status.json", "loop_events.jsonl", "runs.jsonl"):
            shutil.copy2(LIVE_KINSIM_HOME / name, self.local / name)
        self.cfg = config("win-a", self.clones["win-a"], [
            {"key": "kinsim_status", "path": str(self.local / "status.json")},
            {"key": "kinsim_events", "path": str(self.local / "loop_events.jsonl")},
            {"key": "kinsim_runs", "path": str(self.local / "runs.jsonl")},
        ])
        from vibetracks.remote import sync
        self.sync = sync
        self.assertIsNone(sync.sync_once(self.cfg)["error"])

        self.workspace = self.tmp / "workspace"
        (self.workspace / "tracks").mkdir(parents=True)
        for name in ("Agent work.vtdash", "Work tracks.vibetrack"):
            shutil.copy2(REPO / "workspace" / name, self.workspace / name)
        shutil.copy2(REPO / "workspace" / "tracks" / "kinsim.md", self.workspace / "tracks" / "kinsim.md")

        self.server = subprocess.Popen(
            [sys.executable, "-m", "vibetracks.remote.hub", "--share", str(self.clones["hub"]),
             "--workspace", str(self.workspace), "--data-home", str(self.tmp / "data-home"),
             "--port", "0", "--pull-interval", "1"],
            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._stop)
        line = self.server.stdout.readline().strip()
        self.assertTrue(line.startswith("listening on http://127.0.0.1:"), line)
        self.base = line.split("listening on ", 1)[1].rstrip("/")

    def _stop(self) -> None:
        self.server.terminate()
        try:
            self.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.server.kill()

    def get(self, path: str, host: str | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path)
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def state(self) -> dict:
        status, body = self.get("/api/state")
        self.assertEqual(status, 200, body[:300])
        return json.loads(body)

    def wait_for(self, predicate, seconds: float = 20.0) -> dict:
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = self.state()
            if predicate(last):
                return last
            time.sleep(0.5)
        self.fail(f"condition not met within {seconds}s; last state: {json.dumps(last)[:1500]}")

    @staticmethod
    def track(state: dict, track_id: str) -> dict | None:
        return next((track for track in state["tracks"] if track["id"] == track_id), None)

    def test_foreign_host_header_is_refused(self) -> None:
        status, _ = self.get("/api/state", host="evil.example.com")
        self.assertEqual(status, 403)
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())

    def test_an_edit_on_win_a_reaches_the_hub_attributed_to_win_a(self) -> None:
        first = self.wait_for(lambda s: (self.track(s, "kinsim") or {}).get("hosts") == ["win-a"])
        self.assertIn("win-a", [host["host"] for host in first["hosts"]])
        before = self.track(first, "kinsim")["freshness"]["newest"]

        with open(self.local / "loop_events.jsonl", "a") as events:
            events.write(json.dumps({"event": "remote acceptance tick", "at": time.time()}) + "\n")
        self.assertIsNone(self.sync.sync_once(self.cfg)["error"])

        after = self.wait_for(lambda s: self.track(s, "kinsim")["freshness"]["newest"] != before
                              and s["revision"] != first["revision"])
        self.assertEqual(self.track(after, "kinsim")["hosts"], ["win-a"])


if __name__ == "__main__":
    unittest.main()
