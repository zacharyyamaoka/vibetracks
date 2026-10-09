#!/usr/bin/env python3
"""Write the frozen fixtures for the home's rule tests (tests/test_home_rules.py): one fake Claude Code account, a fake
/proc, and a work-track workspace whose notes declare session rules.

    python3 tests/fixtures/home/make_fixtures.py      (from the repo root; rewrites the files below, byte-identical)

Everything here mirrors the shapes Claude Code 2.1.284 writes, copied from real files on 2026-10-09 with the content
replaced: ``sessions/<pid>.json`` (pid, procStart, status busy|idle|waiting, waitingFor, name, bridgeSessionId) and
``projects/<project>/<session>.jsonl`` transcripts whose every line carries timestamp, sessionId, cwd and gitBranch,
including an API-error line (``isApiErrorMessage``, ``error: rate_limit``, ``quotaLimits.resetsAt``), an
``AskUserQuestion`` tool_use with and without its tool_result, ``custom-title`` lines, and subagent transcripts under
``<session>/subagents/agent-*.jsonl`` and ``<session>/subagents/workflows/<wf>/agent-*.jsonl`` whose lines carry the
PARENT's sessionId, ``isSidechain: true`` and their own cwd and branch.

The clock is frozen at NOW (2026-10-09 12:00 PDT); the tests pass it as ``now``. One track per rule case:

    t-waiting    live session status "waiting", last action 3 min ago              -> needs_you
    t-ratelimit  live idle session whose last agent entry is a rate-limit error     -> error, resets 17:20 PDT
    t-stale      ended session, last entry 30 h ago, stall rule 24 h               -> stale
    t-busy       live session status "busy", last entry 20 min ago                 -> working (busy, not recency)
    t-openask    an ended session's unanswered AskUserQuestion (50 min ago) and a
                 live session's newer actions (2 min ago)                          -> needs_you (the question wins)
    t-subagent   parent entries 3 h ago; a subagent (whose own branch matches
                 t-stale's rule) and a workflow agent working until 4 min ago      -> working, worked 4560 s
    t-claim      a work track (adapter, projection injected by the test), quiet
                 32 h, vibe-status running                                         -> stale; done/archived win

Session files: pids 1001 1002 1004 1005 1006 1007 are alive with their recorded start time; 1008 is alive with a
DIFFERENT start time (a reused pid); 1009 has no /proc entry. 1007 matches no rule ("Other sessions").
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=PDT)
ACCOUNT_DIR = HERE / "claude-fixa"
PROC_DIR = HERE / "proc"
WORKSPACE = HERE / "workspace"
VERSION = "2.1.284"


def sid(n: int) -> str:
    return f"11111111-0000-4000-8000-{n:012x}"


def zulu(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def at(hour: int, minute: int, day: int = 9) -> datetime:
    return datetime(2026, 10, day, hour, minute, 0, tzinfo=PDT)


class Transcript:
    """Lines in the shape Claude Code writes them; ``uuid``/``parentUuid`` chain like the real files."""

    def __init__(self, session: str, cwd: str, branch: str, *, sidechain: bool = False, agent: str | None = None):
        self.session, self.cwd, self.branch, self.sidechain, self.agent = session, cwd, branch, sidechain, agent
        self.lines: list[dict] = []
        self.counter = 0
        self.parent: str | None = None

    def _base(self, kind: str, when: datetime) -> dict:
        self.counter += 1
        uuid = f"{self.session[:8]}-{(self.agent or 'main')[:4]:0>4}-4000-8000-{self.counter:012d}"
        row = {"parentUuid": self.parent, "isSidechain": self.sidechain}
        if self.agent:
            row["agentId"] = self.agent
        row.update({"type": kind, "uuid": uuid, "timestamp": zulu(when), "userType": "external",
                    "entrypoint": "claude-desktop", "cwd": self.cwd, "sessionId": self.session, "version": VERSION,
                    "gitBranch": self.branch})
        self.parent = uuid
        return row

    def title(self, text: str) -> None:
        self.lines.append({"type": "custom-title", "customTitle": text, "sessionId": self.session})

    def prompt(self, when: datetime, text: str) -> None:
        row = self._base("user", when)
        row["message"] = {"role": "user", "content": text}
        row["promptId"] = f"p-{self.counter}"
        self.lines.append(row)

    def action(self, when: datetime, tool: str = "Bash", tool_id: str | None = None, tool_input: dict | None = None) -> str:
        row = self._base("assistant", when)
        tool_id = tool_id or f"toolu_fix{self.session[-4:]}{self.counter:06d}"
        row["message"] = {"model": "claude-opus-5-5", "id": f"msg_fix{self.counter:06d}", "type": "message",
                          "role": "assistant",
                          "content": [{"type": "tool_use", "id": tool_id, "name": tool,
                                       "input": tool_input if tool_input is not None else {"command": "true"},
                                       "caller": {"type": "direct"}}],
                          "stop_reason": "tool_use", "stop_sequence": None,
                          "usage": {"input_tokens": 2, "output_tokens": 10}}
        row["requestId"] = f"req_fix{self.counter:06d}"
        self.lines.append(row)
        return tool_id

    def result(self, when: datetime, tool_id: str, text: str = "ok") -> None:
        row = self._base("user", when)
        row["message"] = {"role": "user", "content": [{"tool_use_id": tool_id, "type": "tool_result", "content": text}]}
        row["toolUseResult"] = {"stdout": text, "stderr": ""}
        self.lines.append(row)

    def ask(self, when: datetime, question: str) -> str:
        return self.action(when, "AskUserQuestion", tool_input={"questions": [{
            "question": question, "header": "Decide", "multiSelect": False,
            "options": [{"label": "Yes (Recommended)", "description": "Go ahead."},
                        {"label": "No", "description": "Hold."}]}]})

    def text(self, when: datetime, text: str) -> None:
        row = self._base("assistant", when)
        row["message"] = {"model": "claude-opus-5-5", "id": f"msg_fix{self.counter:06d}", "type": "message",
                          "role": "assistant", "content": [{"type": "text", "text": text}],
                          "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 2, "output_tokens": 10}}
        self.lines.append(row)

    def rate_limit(self, when: datetime, text: str, resets_at: datetime) -> None:
        row = self._base("assistant", when)
        row["message"] = {"diagnostics": None, "id": "fix-ratelimit-msg", "container": None, "model": "<synthetic>",
                          "role": "assistant", "stop_reason": "stop_sequence", "stop_sequence": "", "type": "message",
                          "usage": {"input_tokens": 0, "output_tokens": 0},
                          "content": [{"type": "text", "text": text}]}
        row["requestId"] = "req_fixratelimit"
        row["quotaLimits"] = {"status": "rejected", "resetsAt": int(resets_at.timestamp()), "rateLimitType": "five_hour"}
        row["error"] = "rate_limit"
        row["isApiErrorMessage"] = True
        row["apiErrorStatus"] = 429
        self.lines.append(row)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line, separators=(",", ":")) + "\n" for line in self.lines), encoding="utf-8")


def every(start: datetime, end: datetime, minutes: int) -> list[datetime]:
    out, cursor = [], start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(minutes=minutes)
    return out


def session_file(pid: int, session: str, *, cwd: str, name: str, status: str, start: str, bridge: str | None = None,
                 waiting_for: str | None = None) -> dict:
    data = {"pid": pid, "sessionId": session, "cwd": cwd, "startedAt": int((NOW - timedelta(hours=5)).timestamp() * 1000),
            "procStart": start, "version": VERSION, "peerProtocol": 1, "peerFeatures": ["notify_idle"],
            "kind": "interactive", "entrypoint": "claude-desktop", "hostSessionId": f"local_fix_{pid}",
            "pidDomain": "linux:fixture:pid:[4026531836]", "messagingSocketPath": f"/run/user/1000/cc-socks/{pid}.sock",
            "name": name, "nameSource": "user", "nameSince": int((NOW - timedelta(hours=5)).timestamp() * 1000),
            "status": status, "updatedAt": int((NOW - timedelta(minutes=1)).timestamp() * 1000),
            "statusUpdatedAt": int((NOW - timedelta(minutes=1)).timestamp() * 1000)}
    if waiting_for:
        data["waitingFor"] = waiting_for
    if bridge:
        data["bridgeSessionId"] = bridge
    return data


def proc_stat(pid: int, start: str) -> str:
    # /proc/<pid>/stat: field 22 (starttime, clock ticks since boot) is the 20th field after the ")" closing comm.
    after = ["S", "1000", str(pid), str(pid), "0", "-1", "4194560", "100", "0", "0", "0", "10", "5", "0", "0", "20",
             "0", "12", "0", start, "123456789", "4567"]
    return f"{pid} (claude) " + " ".join(after) + "\n"


NOTE = """---
vibe-track: {marker}
vibe-id: {id}
vibe-title: {title}
vibe-status: {status}
vibe-priority: {priority}
vibe-owner: fixture
{adapter}vibe-project: Fixture Robotics
vibe-stall-hours: 24
vibe-sessions:
  branches: [{branch}]
  cwds: []
  titles: []
---

# {title}

{purpose}
"""

DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "worktrack"'
    - 'file.inFolder("tracks")'
vibetracks:
  version: 1
  id: work-tracks
  title: Work tracks
  vaultRoot: .
  source: tracks
  statuses: [running, paused, archived]
"""


def write_workspace() -> None:
    (WORKSPACE / "tracks").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "Work tracks.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
    (WORKSPACE / "Agent work.vtdash").write_text(json.dumps({
        "schema": "vibetracks-dashboard-file/1", "title": "Fixture work", "registry": "Work tracks.vibetrack"}, indent=2) + "\n",
        encoding="utf-8")
    tracks = [
        ("t-waiting", "Waiting fixture", "claude/t-waiting-*", "activity", "paused", ""),
        ("t-ratelimit", "Rate-limit fixture", "claude/t-ratelimit-*", "activity", "running", ""),
        ("t-stale", "Stale fixture", "claude/t-stale-*", "activity", "paused", ""),
        ("t-busy", "Busy fixture", "claude/t-busy-*", "activity", "running", ""),
        ("t-openask", "Open question fixture", "claude/t-openask-*", "activity", "running", ""),
        ("t-subagent", "Subagent fixture", "claude/t-subagent-*", "activity", "running", ""),
        ("t-claim", "Claim fixture", "claude/t-claim-*", "worktrack", "running", "vibe-adapter: fixture\nvibe-sources: []\n"),
    ]
    for priority, (track_id, title, branch, marker, status, adapter) in enumerate(tracks, start=1):
        (WORKSPACE / "tracks" / f"{track_id}.md").write_text(NOTE.format(
            marker=marker, id=track_id, title=title, status=status, priority=priority, adapter=adapter, branch=branch,
            purpose=f"The {title.lower()}: one rule case for tests/test_home_rules.py."), encoding="utf-8")


def write_account() -> None:
    projects = ACCOUNT_DIR / "projects"
    sessions = ACCOUNT_DIR / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    # t-waiting: live, status waiting; it would read Working on recency alone.
    t = Transcript(sid(1), "/home/fix/waiting", "claude/t-waiting-aa11")
    t.title("Waiting fixture session")
    t.prompt(at(11, 30), "Carry on with the waiting fixture.")
    for when in every(at(11, 31), at(11, 57), 2):
        t.action(when)
    t.write(projects / "-home-fix-waiting" / f"{sid(1)}.jsonl")

    # t-ratelimit: actions, then the session limit card as the last agent entry (40 min ago).
    t = Transcript(sid(2), "/home/fix/ratelimit", "claude/t-ratelimit-bb22")
    t.prompt(at(10, 29), "Run the rate-limit fixture.")
    for when in every(at(10, 30), at(11, 15), 3):
        tool = t.action(when)
        t.result(when + timedelta(seconds=30), tool)
    t.rate_limit(at(11, 20), "You've hit your session limit · resets 5:20pm (America/Vancouver)", at(17, 20))
    t.write(projects / "-home-fix-ratelimit" / f"{sid(2)}.jsonl")

    # t-stale: ended session (no session file), quiet for 30 h.
    t = Transcript(sid(3), "/home/fix/stale", "claude/t-stale-cc33")
    t.title("Stale fixture session")
    t.prompt(at(4, 58, day=8), "Stale fixture.")
    for when in every(at(5, 0, day=8), at(6, 0, day=8), 5):
        t.action(when)
    t.write(projects / "-home-fix-stale" / f"{sid(3)}.jsonl")

    # t-busy: live busy; last entry 20 min ago (past the 15-min gap), so only the busy status makes it Working.
    t = Transcript(sid(4), "/home/fix/busy", "claude/t-busy-dd44")
    t.prompt(at(10, 59), "Busy fixture.")
    for when in every(at(11, 0), at(11, 40), 4):
        t.action(when)
    t.write(projects / "-home-fix-busy" / f"{sid(4)}.jsonl")

    # t-openask: session 5 (ended) asked a question 50 min ago and nobody answered it ...
    t = Transcript(sid(5), "/home/fix/openask", "claude/t-openask-ee55")
    t.prompt(at(11, 0), "Open question fixture, part one.")
    t.action(at(11, 5))
    t.ask(at(11, 10), "Which gripper should the bench use?")
    t.write(projects / "-home-fix-openask" / f"{sid(5)}.jsonl")
    # ... while session 6 (live, idle) asked and got an answer, then kept working until 2 min ago.
    t = Transcript(sid(6), "/home/fix/openask", "claude/t-openask-ee55")
    t.prompt(at(11, 29), "Open question fixture, part two.")
    asked = t.ask(at(11, 30), "Ship the probe now?")
    t.result(at(11, 32), asked, 'Your questions have been answered: "Ship the probe now?"="Yes (Recommended)".')
    for when in every(at(11, 50), at(11, 58), 2):
        t.action(when)
    t.write(projects / "-home-fix-openask" / f"{sid(6)}.jsonl")

    # t-subagent: the parent worked 09:00-09:10 (600 s); its subagent 11:00-11:56 every 2 min (3360 s) on a branch
    # that matches t-stale's rule; a workflow agent 10:00-10:10 (600 s). Worked (24 h) = 4560 s, last action 11:56.
    t = Transcript(sid(7), "/home/fix/subagent", "claude/t-subagent-ff66")
    t.prompt(at(8, 59), "Subagent fixture: dispatch the builder.")
    for when in every(at(9, 0), at(9, 10), 2):
        t.action(when, "Agent" if when == at(9, 10) else "Bash")
    t.write(projects / "-home-fix-subagent" / f"{sid(7)}.jsonl")
    sub = Transcript(sid(7), "/home/fix", "claude/t-stale-cc33", sidechain=True, agent="a1b2c3d4e5f60718")
    sub.prompt(at(10, 59), "You are the builder.")
    for when in every(at(11, 0), at(11, 56), 2):
        sub.action(when, "Edit")
    sub.write(projects / "-home-fix-subagent" / sid(7) / "subagents" / "agent-a1b2c3d4e5f60718.jsonl")
    flow = Transcript(sid(7), "/home/fix", "HEAD", sidechain=True, agent="a9f8e7d6c5b4a392")
    flow.prompt(at(9, 59), "Workflow step.")
    for when in every(at(10, 0), at(10, 10), 2):
        flow.action(when, "Read")
    flow.write(projects / "-home-fix-subagent" / sid(7) / "subagents" / "workflows" / "wf_fix0001-001" / "agent-a9f8e7d6c5b4a392.jsonl")

    # Other: live, matches no rule.
    t = Transcript(sid(8), "/home/fix/prusa", "claude/prusa-input-shaper-1a2b")
    t.prompt(at(11, 44), "Tune the input shaper.")
    t.action(at(11, 45))
    t.write(projects / "-home-fix-prusa" / f"{sid(8)}.jsonl")

    # t-claim: ended session, quiet 32 h.
    t = Transcript(sid(11), "/home/fix/claim", "claude/t-claim-gg77")
    t.prompt(at(3, 59, day=8), "Claim fixture.")
    for when in every(at(4, 0, day=8), at(4, 0, day=8), 1):
        t.action(when)
    t.write(projects / "-home-fix-claim" / f"{sid(11)}.jsonl")

    files = [
        session_file(1001, sid(1), cwd="/home/fix/waiting", name="Waiting fixture session", status="waiting",
                     start="5000001", waiting_for="input needed", bridge="session_01FixWaiting"),
        session_file(1002, sid(2), cwd="/home/fix/ratelimit", name="Rate-limit fixture session", status="idle", start="5000002"),
        session_file(1004, sid(4), cwd="/home/fix/busy", name="Busy fixture session", status="busy", start="5000004",
                     bridge="session_01FixBusy"),
        session_file(1005, sid(6), cwd="/home/fix/openask", name="Open question fixture session", status="idle", start="5000005"),
        session_file(1006, sid(7), cwd="/home/fix/subagent", name="Subagent fixture session", status="idle", start="5000006"),
        session_file(1007, sid(8), cwd="/home/fix/prusa", name="Prusa input shaper", status="idle", start="5000007"),
        session_file(1008, sid(9), cwd="/home/fix/old", name="Reused pid", status="busy", start="5000008"),
        session_file(1009, sid(10), cwd="/home/fix/gone", name="Dead pid", status="idle", start="5000009"),
    ]
    for data in files:
        (sessions / f"{data['pid']}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    for pid, start in [(1001, "5000001"), (1002, "5000002"), (1004, "5000004"), (1005, "5000005"), (1006, "5000006"),
                       (1007, "5000007"), (1008, "7777777")]:  # 1008: alive, but a different process (reused pid)
        (PROC_DIR / str(pid)).mkdir(parents=True, exist_ok=True)
        (PROC_DIR / str(pid) / "stat").write_text(proc_stat(pid, start), encoding="utf-8")


def main() -> None:
    for path in (ACCOUNT_DIR, PROC_DIR, WORKSPACE):
        if path.exists():
            shutil.rmtree(path)
    write_workspace()
    write_account()
    print(f"wrote {ACCOUNT_DIR}, {PROC_DIR} and {WORKSPACE}")


if __name__ == "__main__":
    main()
