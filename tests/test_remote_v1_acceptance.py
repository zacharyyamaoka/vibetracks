"""Acceptance for remote v1 (frozen BEFORE the build, never edited by the builder).

    python3 -m pytest -q tests/test_remote_v1_acceptance.py      (from the repo root)

What v1 adds over the prototype, as observable behaviour:
- A worker with nothing new does no network git at all (the prototype pulled and pushed every 3 s, which against
  GitHub is ~2,400 round trips an hour per machine). It goes to the network only to push a change or a due heartbeat.
- After a push, a worker can poke the hub (``poke_url``), so the hub learns about it at once: interrupt, not polling.
- The hub can be told to check right now (``POST /api/refresh``, the app's Refresh button), and only JSON POSTs from
  an allowed Host are accepted.
- Every session card shows under its machine in ``/api/state`` (``hosts[].sessions``), with or without a track, so
  "which agents are running on win-a, and how do I talk to them" needs no track.
"""

from __future__ import annotations

import json
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


def origin_head(origin: Path) -> str:
    return git(origin, "rev-parse", "main").strip()


class QuietWorker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-v1-worker-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_nothing_new_means_no_network_and_a_due_heartbeat_still_pushes(self) -> None:
        from vibetracks.remote import sync

        origin, clones = make_share(self.tmp, "win-a")
        status = self.tmp / "status.json"
        status.write_text('{"wave": 1}')
        config = {"host": "win-a", "share": str(clones["win-a"]), "interval_s": 3, "heartbeat_s": 300,
                  "mirror": [{"key": "kinsim_status", "path": str(status)}]}
        t0 = time.time()
        first = sync.sync_once(config, now=t0)
        self.assertIsNone(first["error"], first)
        self.assertTrue(first["pushed"])

        # Take the remote away. A quiet round must not notice, because it must not touch the network.
        parked = self.tmp / "origin-parked.git"
        origin.rename(parked)
        quiet = sync.sync_once(config, now=t0 + 10)
        self.assertIsNone(quiet["error"], quiet)
        self.assertFalse(quiet["pushed"])
        parked.rename(origin)

        head = origin_head(origin)
        due = sync.sync_once(config, now=t0 + 400)  # the heartbeat (300 s) is due: one commit + push
        self.assertIsNone(due["error"], due)
        self.assertTrue(due["pushed"])
        self.assertNotEqual(origin_head(origin), head)

        head = origin_head(origin)
        status.write_text('{"wave": 2}')
        changed = sync.sync_once(config, now=t0 + 410)
        self.assertIsNone(changed["error"], changed)
        self.assertTrue(changed["pushed"])
        self.assertNotEqual(origin_head(origin), head)


class HubV1(unittest.TestCase):
    """A hub whose own polling is effectively off (600 s), so only Refresh or a poke can make it see a push."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-v1-hub-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin, self.clones = make_share(self.tmp, "win-a", "hub")
        self.workspace = self.tmp / "workspace"
        (self.workspace / "tracks").mkdir(parents=True)
        for name in ("Agent work.vtdash", "Work tracks.vibetrack"):
            shutil.copy2(REPO / "workspace" / name, self.workspace / name)
        self.server = subprocess.Popen(
            [sys.executable, "-m", "vibetracks.remote.hub", "--share", str(self.clones["hub"]),
             "--workspace", str(self.workspace), "--data-home", str(self.tmp / "data-home"), "--port", "0",
             "--check-fast", "600", "--check-slow", "600"],
            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._stop)
        line = self.server.stdout.readline().strip()
        self.assertTrue(line.startswith("listening on http://127.0.0.1:"), line)
        self.base = line.split("listening on ", 1)[1].rstrip("/")
        self.wait_for(lambda s: s["hub"].get("share_head"))  # the startup check has run

    def _stop(self) -> None:
        self.server.terminate()
        try:
            self.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.server.kill()

    def request(self, path: str, *, method: str = "GET", body: bytes | None = None,
                content_type: str | None = None, host: str | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def state(self) -> dict:
        status, body = self.request("/api/state")
        self.assertEqual(status, 200, body[:300])
        return json.loads(body)

    def wait_for(self, predicate, seconds: float = 20.0) -> dict:
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = self.state()
            if predicate(last):
                return last
            time.sleep(0.3)
        self.fail(f"not met within {seconds}s; last state: {json.dumps(last)[:1500]}")

    def push_a_trackless_session_from_win_a(self, poke_url: str | None = None) -> None:
        from vibetracks.remote import session_hook, sync

        stdin = json.dumps({"session_id": "0000aaaa-1111-2222-3333-444455556666", "cwd": "C:/Users/BAM/cad-exporter",
                            "hook_event_name": "UserPromptSubmit"})
        env = {"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01WinA", "CLAUDE_CONFIG_DIR": "C:/Users/BAM/.claude-bam"}
        self.assertEqual(session_hook.main(["--share", str(self.clones["win-a"]), "--host", "win-a"], stdin, env), 0)
        config = {"host": "win-a", "share": str(self.clones["win-a"]), "interval_s": 3, "heartbeat_s": 300, "mirror": []}
        if poke_url:
            config["poke_url"] = poke_url
        result = sync.sync_once(config)
        self.assertIsNone(result["error"], result)
        self.assertTrue(result["pushed"])

    @staticmethod
    def win_a(state: dict) -> dict | None:
        return next((host for host in state["hosts"] if host["host"] == "win-a"), None)

    def test_refresh_now_picks_up_a_push_the_hub_would_otherwise_miss(self) -> None:
        self.push_a_trackless_session_from_win_a()
        time.sleep(2.0)
        self.assertIsNone(self.win_a(self.state()), "with checks at 600 s the hub must not have seen the push yet")

        status, body = self.request("/api/refresh", method="POST", body=b"{}", content_type="application/json")
        self.assertEqual(status, 200, body[:300])
        reply = json.loads(body)
        self.assertTrue(reply["ok"])

        host = self.win_a(self.state())
        self.assertIsNotNone(host)
        card = next(c for c in host["sessions"] if c["session_id"] == "0000aaaa-1111-2222-3333-444455556666")
        self.assertEqual(card["url"], "https://claude.ai/code/session_01WinA")
        self.assertIsNone(card["track"])
        self.assertTrue(card["live"])
        self.assertIn("last_check", self.state()["hub"])

    def test_a_worker_poke_makes_the_hub_look_at_once(self) -> None:
        self.push_a_trackless_session_from_win_a(poke_url=self.base + "/api/poke")
        self.wait_for(lambda s: self.win_a(s) is not None, seconds=6.0)

    def test_writes_need_json_and_an_allowed_host(self) -> None:
        status, _ = self.request("/api/refresh", method="POST", body=b"x", content_type="text/plain")
        self.assertEqual(status, 415)
        status, _ = self.request("/api/refresh", method="POST", body=b"{}", content_type="application/json",
                                 host="evil.example.com")
        self.assertEqual(status, 403)
        status, _ = self.request("/api/poke", method="POST", body=b"{}", content_type="application/json",
                                 host="evil.example.com")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
