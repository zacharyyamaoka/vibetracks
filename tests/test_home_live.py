"""B1 acceptance, frozen before the build (checks 1, 4 and 5 on this machine's REAL data): the home served by the real
backend, against oracles read outside the code under test.

    python3 -m unittest tests/test_home_live.py      (from the repo root)

- Check 1, live sessions: the sessions on the page (matched plus "Other") are exactly the ``~/.claude-*/sessions/
  <pid>.json`` files whose pid is alive with the recorded start time, read here from /proc. Deleting matching rules
  moves sessions to "Other"; none disappears.
- Check 4, real-data spot check: kinsim's last loop write is its heartbeat files' mtime and it reads Stale while it is
  quiet past its stall rule; rig's blocking/open counts equal /needs?track=rig; grasping reads Error and names the
  worktree its sources point into when that worktree is gone. Every expectation is derived from the live sources at
  run time (the files' mtimes, needs.py, the registry), so the check follows the data instead of rotting with it.
- Check 5, warm speed: a warm GET /home answers in under 150 ms at p95.

The backend runs as Clank runs it (``clank/backend/server.py --workspace workspace``) on a free port, with
``VIBETRACKS_HOME_CACHE`` in a temp dir so the test never writes the real cache. Skipped when this machine has no
Claude Code session files at all.

WHY read-only to the builder: this is the ruler (dispatch discipline, 2026-09-16); a wrong check is reported, not edited.
"""

from __future__ import annotations

import glob
import importlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

from vibetracks.dashboard import needs as needs_module
from vibetracks.dashboard.build import heartbeat_keys
from vibetracks.dashboard.registry import read_registry
from vibetracks.home.compose import build_home
from vibetracks.sources import load_sources

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"
SESSION_GLOB = os.path.expanduser("~/.claude-*/sessions/*.json")
P95_BUDGET_S = 0.150
WARM_REQUESTS = 40
RULE_KEYS = {"branch": "branches", "cwd": "cwds", "title": "titles"}

SERVER: subprocess.Popen | None = None
BASE = ""
CACHE: tempfile.TemporaryDirectory | None = None
COLD_S = 0.0


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def tracks_of(doc: dict) -> dict[str, dict]:
    return {track["id"]: track for project in doc["projects"] for track in project["tracks"]}


def live_on_page(doc: dict) -> list[tuple[str, int]]:
    out = [(s["account"], s["pid"]) for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]]
    out += [(s["account"], s["pid"]) for s in doc["other_sessions"] if s["live"]]
    return out


def proc_start(pid: int) -> str | None:
    """Field 22 (starttime) of /proc/<pid>/stat, or None when the pid is not running."""

    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return text.rsplit(")", 1)[1].split()[19]


def account_of(path: str) -> str:
    return Path(path).parent.parent.name.lstrip(".").removeprefix("claude-")


def oracle() -> dict[tuple[str, int], dict]:
    """Every session file whose pid is alive with the start time it recorded: (account, pid) -> file contents."""

    alive: dict[tuple[str, int], dict] = {}
    seen: set[str] = set()
    for path in sorted(glob.glob(SESSION_GLOB)):
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid = data.get("pid")
        if isinstance(pid, int) and proc_start(pid) == str(data.get("procStart")):
            alive[(account_of(path), pid)] = data
    return alive


def get(path: str, timeout: float = 30.0) -> tuple[float, dict]:
    request = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return time.perf_counter() - started, json.loads(body)


def setUpModule() -> None:
    global SERVER, BASE, CACHE, COLD_S
    if not glob.glob(SESSION_GLOB):
        raise unittest.SkipTest("no Claude Code session files on this machine")
    CACHE = tempfile.TemporaryDirectory()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "VIBETRACKS_HOME_CACHE": CACHE.name, "PYTHONPATH": str(REPO)}
    SERVER = subprocess.Popen([sys.executable, str(REPO / "clank" / "backend" / "server.py"), "--port", str(port),
                               "--workspace", str(WORKSPACE)], cwd=str(WORKSPACE), env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    BASE = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while True:
        try:
            get("/health", timeout=2)
            break
        except OSError:
            if time.time() > deadline or SERVER.poll() is not None:
                raise
            time.sleep(0.2)
    COLD_S, _ = get("/home", timeout=300)


def tearDownModule() -> None:
    if SERVER is not None:
        SERVER.terminate()
        try:
            SERVER.wait(timeout=10)
        except subprocess.TimeoutExpired:
            SERVER.kill()
    if CACHE is not None:
        CACHE.cleanup()


class LiveSessionsTest(unittest.TestCase):
    """Check 1 on real data."""

    def test_page_sessions_equal_the_alive_session_files(self) -> None:
        for attempt in range(3):
            before = oracle()
            _, doc = get("/home")
            after = oracle()
            if set(before) == set(after):
                break
        else:
            self.fail("sessions kept starting or stopping; no stable oracle in 3 tries")
        shown = live_on_page(doc)
        self.assertEqual(len(shown), len(set(shown)), "a live session is shown twice")
        self.assertEqual(set(shown), set(before), f"missing: {set(before) - set(shown)} extra: {set(shown) - set(before)}")
        ids = {(s["account"], s["pid"]): s["id"] for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]}
        ids.update({(s["account"], s["pid"]): s["id"] for s in doc["other_sessions"] if s["live"]})
        for key, data in before.items():
            self.assertEqual(ids[key], data["sessionId"], key)
        self.assertEqual(doc["summary"]["sessions_live"], len(before))

    def test_every_matched_session_records_how(self) -> None:
        _, doc = get("/home")
        for track in tracks_of(doc).values():
            for session in track["sessions"]:
                self.assertIn(session["join"]["by"], RULE_KEYS, (track["id"], session["id"]))

    def _copy_workspace(self) -> Path:
        target = Path(tempfile.mkdtemp()) / "workspace"
        self.addCleanup(shutil.rmtree, target.parent, True)
        shutil.copytree(WORKSPACE, target, ignore=shutil.ignore_patterns(".clank"))
        return target

    @staticmethod
    def _edit_rules(note: Path, edit) -> None:
        text = note.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        data = yaml.safe_load(match.group(1))
        data["vibe-sessions"] = edit(data.get("vibe-sessions"))
        note.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + text[match.end():], encoding="utf-8")

    def _build(self, workspace: Path) -> tuple[dict, dict]:
        for attempt in range(3):
            before = oracle()
            doc = build_home(workspace, projection={"schema": "vibetracks-dashboard/1", "tracks": []}, needs={},
                             cache_dir=CACHE.name)
            if set(before) == set(oracle()):
                return doc, before
        self.fail("sessions kept starting or stopping; no stable oracle in 3 tries")

    def test_deleting_every_rule_moves_every_live_session_to_other(self) -> None:
        workspace = self._copy_workspace()
        for note in (workspace / "tracks").rglob("*.md"):
            if "vibe-sessions" in note.read_text(encoding="utf-8"):
                self._edit_rules(note, lambda _rules: None)
        doc, alive = self._build(workspace)
        self.assertEqual([s for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]], [])
        self.assertEqual({(s["account"], s["pid"]) for s in doc["other_sessions"] if s["live"]}, set(alive))

    def test_deleting_one_matching_rule_never_loses_the_session(self) -> None:
        _, doc = get("/home")
        candidates = [(t, s) for t in tracks_of(doc).values() for s in t["sessions"] if s["live"]]
        if not candidates:
            self.skipTest("no live session matches a track right now")
        track, session = candidates[0]
        by, value = session["join"]["by"], session["join"]["value"]
        workspace = self._copy_workspace()
        notes = [n for n in (workspace / "tracks").rglob("*.md")
                 if re.search(rf"^vibe-id: {re.escape(track['id'])}\s*$", n.read_text(encoding="utf-8"), re.M)]
        self.assertTrue(notes, f"no note declares {track['id']}")

        def drop(rules):
            rules = dict(rules or {})
            rules[RULE_KEYS[by]] = [rule for rule in rules.get(RULE_KEYS[by]) or [] if rule != value]
            return rules

        for note in notes:
            self._edit_rules(note, drop)
        after, alive = self._build(workspace)
        shown = {(s["account"], s["pid"]) for s in live_on_page(after)}
        self.assertEqual(shown, set(alive), "a session disappeared when its rule was deleted")
        moved = [s for s in tracks_of(after)[track["id"]]["sessions"]
                 if s["id"] == session["id"] and s["join"] == {"by": by, "value": value}]
        self.assertEqual(moved, [], f"{session['id']} still matched by the deleted rule {by}: {value}")


class RealDataSpotCheck(unittest.TestCase):
    """Check 4: expectations derived from the live sources at run time."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.doc = get("/home")
        cls.tracks = tracks_of(cls.doc)
        cls.registry = read_registry(WORKSPACE)
        cls.sources = load_sources()
        cls.alive = oracle()

    def needs_counts(self, track_id: str) -> dict:
        status, _headers, body = needs_module.handle("GET", "", {"track": [track_id]}, {})
        self.assertEqual(status, 200)
        return json.loads(b"".join(body))["counts"]

    def waiting_live(self, track: dict) -> bool:
        return any(self.alive.get((s["account"], s["pid"]), {}).get("status") == "waiting"
                   for s in track["sessions"] if s["live"])

    def test_projects_and_targets(self) -> None:
        names = [project["name"] for project in self.doc["projects"]]
        self.assertEqual(sorted(names), sorted(["BAM Robotics", "claude-transcript-viewer", "pyblocks", "vibetracks"]))
        targets = {tid: t["target"] for tid, t in self.tracks.items() if t.get("target")}
        self.assertEqual(targets, {"rig": "2026-10-22"})
        for work_track in self.registry.tracks:
            if not work_track.archived:
                self.assertIn(work_track.id, self.tracks)

    def test_kinsim_last_loop_write_and_stale(self) -> None:
        kinsim = self.tracks["kinsim"]
        work_track = self.registry.by_id("kinsim")
        module = importlib.import_module(f"vibetracks.dashboard.adapters.{work_track.adapter}")
        paths = [Path(self.sources[key]) for key in heartbeat_keys(work_track, module) if key in self.sources]
        stamps = []
        for path in paths:
            if path.is_file():
                stamps.append(path.stat().st_mtime)
            elif path.is_dir():
                stamps += [entry.stat().st_mtime for entry in os.scandir(path) if entry.is_file()]
        self.assertTrue(stamps, f"no kinsim heartbeat file exists: {paths}")
        loop_write = max(stamps)
        self.assertAlmostEqual(ts(kinsim["last_loop_write"]["ts"]), loop_write, delta=1.0)

        transcripts = [p for p in kinsim["provenance"]["transcripts"] if os.path.exists(p)]
        newest = max([loop_write] + [os.stat(p).st_mtime for p in transcripts])
        quiet = time.time() - newest
        wants = self.needs_counts("kinsim")["wants_you"] or 0
        error_last = (kinsim.get("last_error") and kinsim.get("last_action")
                      and ts(kinsim["last_error"]["ts"]) >= ts(kinsim["last_action"]["ts"]))
        if work_track.status in ("done", "archived"):
            expected = work_track.status
        elif wants or self.waiting_live(kinsim):
            expected = "needs_you"
        elif error_last:
            expected = "error"
        elif quiet > work_track.stall_hours * 3600:
            expected = "stale"
        else:
            expected = None
        if expected is None:
            self.assertNotEqual(kinsim["state"]["word"], "stale", f"kinsim moved {quiet / 3600:.1f} h ago")
        else:
            self.assertEqual(kinsim["state"]["word"], expected,
                             f"quiet {quiet / 3600:.1f} h, stall {work_track.stall_hours} h, wants {wants}")

    def test_rig_counts_equal_needs(self) -> None:
        rig = self.tracks["rig"]
        counts = self.needs_counts("rig")
        self.assertEqual(rig["needs_you"]["blocking"], counts["blocking_now"])
        self.assertEqual(rig["needs_you"]["open"], counts["wants_you"])
        if counts["wants_you"] and self.registry.by_id("rig").status not in ("done", "archived"):
            self.assertEqual(rig["state"]["word"], "needs_you")
            self.assertIn(f"{counts['blocking_now']} blocking", rig["state"]["why"])
            self.assertIn(f"{counts['wants_you']} open", rig["state"]["why"])

    def test_grasping_names_its_deleted_worktree(self) -> None:
        grasping = self.tracks["grasping"]
        work_track = self.registry.by_id("grasping")
        gone = set()
        for key in work_track.sources:
            path = self.sources.get(key)
            match = re.search(r"^(.*?/\.claude/worktrees/([^/]+))(/|$)", path or "")
            if path and not os.path.exists(path) and match and not os.path.isdir(match.group(1)):
                gone.add(match.group(2))
        wants = self.needs_counts("grasping")["wants_you"] or 0
        if gone and work_track.status not in ("done", "archived") and not wants and not self.waiting_live(grasping):
            self.assertEqual(grasping["state"]["word"], "error", grasping["state"])
            self.assertTrue(any(name in grasping["state"]["why"] for name in gone), (gone, grasping["state"]["why"]))
        elif not gone:
            self.assertNotIn("worktree", grasping["state"]["why"])


class WarmSpeedTest(unittest.TestCase):
    """Check 5: a warm /home answers in under 150 ms at p95."""

    def test_warm_p95(self) -> None:
        get("/home")
        times = sorted(get("/home")[0] for _ in range(WARM_REQUESTS))
        p95 = times[math.ceil(0.95 * len(times)) - 1]
        _, doc = get("/home")
        print(f"\n[home] cold {COLD_S * 1000:.0f} ms · warm p50 {times[len(times) // 2] * 1000:.1f} ms · "
              f"p95 {p95 * 1000:.1f} ms · max {times[-1] * 1000:.1f} ms over {WARM_REQUESTS} · "
              f"{doc['sources']['transcripts']['files']} transcript files on disk", file=sys.stderr)
        self.assertLess(p95, P95_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
