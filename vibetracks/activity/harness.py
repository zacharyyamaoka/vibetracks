"""Read what the Claude Code harness writes: live session files and transcripts. Read-only, stdlib only.

    homes = claude_homes()                          # ~/.claude-* that hold sessions/ or projects/
    live = live_sessions(homes)                     # alive pids only, checked against /proc
    index = TranscriptIndex(homes, cache_dir=...)   # one per process; refresh() reads only new bytes
    files = index.refresh(now)

**Live sessions.** ``<home>/sessions/<pid>.json`` (Claude Code 2.1.284) carries ``pid``, ``procStart``, ``sessionId``,
``status`` (busy | idle | waiting), ``waitingFor``, ``name``, ``cwd`` and ``bridgeSessionId``. A file is live only
when ``/proc/<pid>/stat`` exists AND its field 22 (start time in clock ticks) equals ``procStart``: Claude Code does not
delete the file of a session that crashed, and a pid is reused. WHY never trust the file alone: 17 of 45 files on this
machine on 2026-10-09 named a dead pid.

**Transcripts.** ``<home>/projects/<project>/<session>.jsonl`` and, for subagents and workflow agents,
``<home>/projects/<project>/<session>/subagents/**/agent-*.jsonl``. Every line carries ``timestamp``, ``sessionId``
(a subagent's lines carry the PARENT's), ``cwd`` and ``gitBranch``. The index folds each file into a small
``FileState`` (agent-entry times, the last agent entry, the last error, open questions, branch, cwd, title) and keeps a
byte cursor, so a warm refresh stats the recent files and parses only appended lines.

WHY only files modified in the window (7 days): the projects tree holds 16 GB in 8,674 files; the last 7 days are
2,000 files and 4.6 GB, and nothing older can move a state word. A live session whose transcript is older is still
shown (its session file says so) and its branch is read from the file's tail.
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .derive import parse_reset

WINDOW_S = 7 * 86400
#: How often a refresh re-walks the whole projects tree for new files (a known file is re-stat'ed on every refresh).
WALK_TTL_S = 30.0
#: Persist the index at most this often (a cold read is ~10 s; a restart should not pay it again).
SAVE_TTL_S = 60.0
INDEX_VERSION = 3
TAIL_BYTES = 256 * 1024
_TS = re.compile(rb'"timestamp":"([0-9T:.+\-Z]+)"')


def account_of(home: Path) -> str:
    """``~/.claude-bam`` -> ``bam``."""

    return home.name.lstrip(".").removeprefix("claude-") or home.name


def claude_homes(base: str | os.PathLike[str] | None = None) -> list[Path]:
    """Every ``~/.claude-*`` holding ``sessions/`` or ``projects/``, one per real directory (``~/.claude`` itself is a
    link to one of them on this machine, so it is not globbed). ``$VIBETRACKS_CLAUDE_HOMES`` (os.pathsep-separated)
    overrides the glob."""

    override = os.environ.get("VIBETRACKS_CLAUDE_HOMES")
    candidates = [Path(p) for p in override.split(os.pathsep) if p] if override else \
        sorted(Path(p) for p in glob.glob(os.path.join(str(base or Path.home()), ".claude-*")))
    out, seen = [], set()
    for path in candidates:
        try:
            real = path.resolve()
        except OSError:
            continue
        if real in seen or not ((path / "sessions").is_dir() or (path / "projects").is_dir()):
            continue
        seen.add(real)
        out.append(path)
    return out


def iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def parse_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------ live sessions


def proc_start(pid: int, proc_root: str | os.PathLike[str] = "/proc") -> str | None:
    """Field 22 of ``<proc_root>/<pid>/stat`` (start time, clock ticks since boot), or None when there is no such pid.
    WHY split after the LAST ")": the command name in field 2 may itself hold spaces and parentheses."""

    try:
        text = Path(proc_root, str(pid), "stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        return text.rsplit(")", 1)[1].split()[19]
    except IndexError:
        return None


@dataclass
class LiveSession:
    account: str
    home: str
    pid: int
    session_id: str
    status: str | None
    waiting_for: str | None
    name: str | None
    cwd: str | None
    bridge: str | None
    entrypoint: str | None
    kind: str | None
    started_at: float | None
    status_since: float | None
    file: str


def live_sessions(homes: Iterable[Path], proc_root: str | os.PathLike[str] = "/proc") -> tuple[list[LiveSession], dict[str, int]]:
    """The session files whose pid is alive with the start time they recorded, and counts of the rest."""

    live: list[LiveSession] = []
    counts = {"files": 0, "dead": 0, "unreadable": 0}
    for home in homes:
        for path in sorted((home / "sessions").glob("*.json")):
            counts["files"] += 1
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pid = data["pid"]
                session_id = data["sessionId"]
            except (OSError, ValueError, KeyError, TypeError):
                counts["unreadable"] += 1
                continue
            if not isinstance(pid, int) or not isinstance(session_id, str) or \
                    proc_start(pid, proc_root) != str(data.get("procStart")):
                counts["dead"] += 1
                continue
            status_since = data.get("statusUpdatedAt")
            started = data.get("startedAt")
            live.append(LiveSession(
                account=account_of(home), home=str(home), pid=pid, session_id=session_id,
                status=data.get("status") if isinstance(data.get("status"), str) else None,
                waiting_for=data.get("waitingFor") if isinstance(data.get("waitingFor"), str) else None,
                name=data.get("name") if isinstance(data.get("name"), str) else None,
                cwd=data.get("cwd") if isinstance(data.get("cwd"), str) else None,
                bridge=data.get("bridgeSessionId") if isinstance(data.get("bridgeSessionId"), str) else None,
                entrypoint=data.get("entrypoint") if isinstance(data.get("entrypoint"), str) else None,
                kind=data.get("kind") if isinstance(data.get("kind"), str) else None,
                started_at=started / 1000 if isinstance(started, (int, float)) else None,
                status_since=status_since / 1000 if isinstance(status_since, (int, float)) else None,
                file=str(path)))
    return live, counts


# ------------------------------------------------------------------------------------------------ transcripts


@dataclass
class FileState:
    """One transcript folded to what the home needs. Everything here is metadata: never a tool's input or output."""

    path: str
    account: str
    kind: str                      # "top" | "sub"
    session: str                   # the session this file belongs to (a subagent: its parent's)
    dev: int = 0
    ino: int = 0
    offset: int = 0                # bytes folded so far (always at a line boundary)
    size: int = 0
    mtime: float = 0.0
    agent: str | None = None       # a subagent's agentId
    branch: str | None = None      # the newest line's gitBranch
    cwd: str | None = None         # the newest line's cwd
    title: str | None = None       # the newest custom-title / agent-name
    first_ts: float | None = None
    last_ts: float | None = None   # newest timestamped line of any kind
    agent_ts: list[int] = field(default_factory=list)   # agent entries (thought|action|response|error|elicitation)
    last_agent: list | None = None                      # [ts, type, body]
    last_error: list | None = None                      # [ts, kind, text, resets-epoch|None]
    open_asks: dict[str, list] = field(default_factory=dict)   # tool_use id -> [ts, question]
    lines: int = 0

    def reset(self) -> None:
        keep = {"path": self.path, "account": self.account, "kind": self.kind, "session": self.session}
        self.__dict__.update(FileState(**keep).__dict__)


def walk_transcripts(homes: Iterable[Path]) -> tuple[list[tuple[Path, str, str, str, os.stat_result]], int]:
    """Every transcript file under each home's projects/ with its stat: (path, account, kind, session, stat), one entry
    per real file (a symlinked transcript, as ~/.claude-personal holds, is the same file twice and kept once), and
    the number of .jsonl files seen. ``kind`` is "top" for ``<project>/<session>.jsonl`` and "sub" (with the PARENT
    session) for ``<project>/<parent>/subagents/**/agent-*.jsonl``.

    WHY strings and os.scandir, not pathlib: this lists ~8,700 files every WALK_TTL_S; Path objects tripled its cost.
    """

    found: list[tuple[str, str, str, str, os.stat_result, bool]] = []
    total = 0
    for home in homes:
        root = os.path.join(str(home), "projects")
        account = account_of(Path(home))
        stack = [(root, 0, "")]  # (directory, depth below projects/, parent session name at depth 1)
        while stack:
            directory, depth, parent = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if depth == 0:
                            stack.append((entry.path, 1, ""))
                        elif depth == 1:
                            stack.append((entry.path, 2, entry.name))
                        elif depth == 2 and entry.name != "subagents":
                            continue
                        else:
                            stack.append((entry.path, depth + 1, parent))
                        continue
                    if not entry.name.endswith(".jsonl"):
                        continue
                    total += 1
                    if depth == 1:
                        kind, session = "top", entry.name[:-6]
                    elif depth >= 3:
                        kind, session = "sub", parent
                    else:
                        continue
                    link = entry.is_symlink()
                    info = os.stat(entry.path) if link else entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                found.append((entry.path, account, kind, session, info, link))
    found.sort(key=lambda item: item[5])  # real files before links, so the link is the one dropped
    out, seen = [], set()
    for path, account, kind, session, info, _link in found:
        key = (info.st_dev, info.st_ino)
        if key in seen:
            continue
        seen.add(key)
        out.append((Path(path), account, kind, session, info))
    return out, total


def _body_of_tool(item: dict) -> tuple[str, str]:
    name = item.get("name") if isinstance(item.get("name"), str) else "tool"
    if name == "AskUserQuestion":
        questions = (item.get("input") or {}).get("questions") if isinstance(item.get("input"), dict) else None
        first = questions[0] if isinstance(questions, list) and questions and isinstance(questions[0], dict) else {}
        question = first.get("question") if isinstance(first.get("question"), str) else ""
        return "elicitation", question
    return "action", name


def fold_line(state: FileState, raw: bytes, window_start: float) -> None:
    """Fold one transcript line into ``state``. Only assistant lines, error lines, titles and the user lines that
    answer an open question are parsed; the rest (tool results, attachments, snapshots: most of the bytes) are not."""

    error_line = b'"isApiErrorMessage":true' in raw
    if error_line or b'"type":"assistant"' in raw:
        try:
            row = json.loads(raw)
        except ValueError:
            return
        if not isinstance(row, dict) or row.get("type") != "assistant":
            return
        when = parse_ts(row.get("timestamp"))
        if when is None:
            return
        _place(state, row, when)
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if row.get("isApiErrorMessage"):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)).strip()
            kind = row.get("error") if isinstance(row.get("error"), str) else "unknown"
            quota = row.get("quotaLimits") if isinstance(row.get("quotaLimits"), dict) else {}
            resets = quota.get("resetsAt") if isinstance(quota.get("resetsAt"), (int, float)) else None
            if resets is None:
                parsed = parse_reset(text, when)
                resets = parse_ts(parsed) if parsed else None
            state.last_error = [when, kind, text[:400], resets]
            entry = ("error", text[:200])
        else:
            entry = None
            for item in content:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                if kind == "tool_use":
                    entry_type, body = _body_of_tool(item)
                    if entry_type == "elicitation" and isinstance(item.get("id"), str):
                        state.open_asks[item["id"]] = [when, body[:300]]
                    if entry is None or entry[0] != "elicitation":
                        entry = (entry_type, body)
                elif kind == "text" and entry is None:
                    entry = ("response", "")
                elif kind == "thinking" and entry is None:
                    entry = ("thought", "")
            if entry is None:
                return
        # WHY a later agent entry closes an older question in the same transcript: the API needs a tool_result before
        # the conversation can continue, so a newer entry means it was answered or dismissed even when the result
        # line was not matched; an unanswered question is the LAST thing its transcript says.
        for tool_id, (asked, _q) in list(state.open_asks.items()):
            if asked < when:
                del state.open_asks[tool_id]
        if when >= window_start:
            state.agent_ts.append(int(when))
        if state.last_agent is None or when >= state.last_agent[0]:
            state.last_agent = [when, entry[0], entry[1]]
        return
    if state.open_asks and b'"type":"user"' in raw and any(tool_id.encode() in raw for tool_id in state.open_asks):
        try:
            row = json.loads(raw)
        except ValueError:
            return
        message = row.get("message") if isinstance(row, dict) and isinstance(row.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                state.open_asks.pop(item.get("tool_use_id"), None)
        return
    if b'"custom-title"' in raw or b'"agent-name"' in raw:
        try:
            row = json.loads(raw)
        except ValueError:
            return
        if isinstance(row, dict):
            title = row.get("customTitle") if row.get("type") == "custom-title" else row.get("agentName")
            if isinstance(title, str) and title.strip() and (row.get("type") == "custom-title" or state.title is None):
                state.title = title.strip()


def _place(state: FileState, row: dict, when: float) -> None:
    state.lines += 1
    if state.first_ts is None or when < state.first_ts:
        state.first_ts = when
    if state.last_ts is None or when >= state.last_ts:
        state.last_ts = when
        if isinstance(row.get("gitBranch"), str) and row["gitBranch"]:
            state.branch = row["gitBranch"]
        if isinstance(row.get("cwd"), str) and row["cwd"]:
            state.cwd = row["cwd"]
        if state.agent is None and isinstance(row.get("agentId"), str):
            state.agent = row["agentId"]


def fold_file(state: FileState, info: os.stat_result, window_start: float) -> int:
    """Read what was appended since ``state.offset`` (from 0 when the file was replaced or truncated); bytes read."""

    if (info.st_dev, info.st_ino) != (state.dev, state.ino) or info.st_size < state.offset:
        state.reset()
        state.dev, state.ino = info.st_dev, info.st_ino
    state.size, state.mtime = info.st_size, info.st_mtime
    if info.st_size == state.offset:
        return 0
    read = 0
    try:
        with open(state.path, "rb") as handle:
            handle.seek(state.offset)
            buffer = b""
            while True:
                chunk = handle.read(8 << 20)
                if not chunk:
                    break
                read += len(chunk)
                buffer += chunk
                cut = buffer.rfind(b"\n")
                if cut < 0:
                    continue
                complete, buffer = buffer[:cut], buffer[cut + 1:]
                for raw in complete.split(b"\n"):
                    if raw:
                        fold_line(state, raw, window_start)
                state.offset += cut + 1
    except OSError:
        return read
    return read


def tail_fields(path: str) -> dict[str, Any]:
    """Branch, cwd and title from the last lines of an old transcript (a live session idle for longer than the window)."""

    out: dict[str, Any] = {}
    try:
        with open(path, "rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read()
    except OSError:
        return out
    for raw in reversed(data.split(b"\n")[1:] if len(data) == TAIL_BYTES else data.split(b"\n")):
        if not raw or (b'"gitBranch"' not in raw and b'"custom-title"' not in raw):
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if "branch" not in out and isinstance(row.get("gitBranch"), str) and row["gitBranch"]:
            out["branch"] = row["gitBranch"]
            out["cwd"] = row.get("cwd") if isinstance(row.get("cwd"), str) else None
            out["last_ts"] = parse_ts(row.get("timestamp"))
        if "title" not in out and row.get("type") == "custom-title" and isinstance(row.get("customTitle"), str):
            out["title"] = row["customTitle"]
        if "branch" in out and "title" in out:
            break
    return out


class TranscriptIndex:
    """The folded transcripts of a set of Claude homes, refreshed incrementally. Thread-safe."""

    def __init__(self, homes: Iterable[Path], cache_dir: str | os.PathLike[str] | None = None):
        self.homes = [Path(h) for h in homes]
        self.cache_file = Path(cache_dir) / f"transcripts-v{INDEX_VERSION}.json" if cache_dir else None
        self.files: dict[str, FileState] = {}
        self.listing: list[tuple[Path, str, str, str, os.stat_result]] = []
        self.total_files = 0
        self.walked_at = 0.0
        self.saved_at = 0.0
        self.dirty = False
        self.lock = threading.Lock()
        self.stats: dict[str, Any] = {}
        self.recent: dict[str, tuple] = {}
        self.by_session: dict[tuple[str, str], tuple] = {}
        self.pending: tuple[list, int] | None = None
        self.walker: threading.Thread | None = None
        self._load()

    def _start_walker(self) -> None:
        """Re-list the projects tree every WALK_TTL_S in a daemon thread; refresh() adopts the new listing.
        WHY a thread: a walk costs 50-300 ms (page cache), which inside a request would set the p95."""

        if self.walker is not None and self.walker.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(WALK_TTL_S)
                try:
                    listing = walk_transcripts(self.homes)
                except Exception:  # noqa: BLE001 - a failed walk keeps the previous listing
                    continue
                with self.lock:
                    self.pending = listing
                    self.walked_at = time.time()

        self.walker = threading.Thread(target=loop, name="vibetracks-transcript-walk", daemon=True)
        self.walker.start()

    # ---------------------------------------------------------------------------------------------- persistence

    def _load(self) -> None:
        if self.cache_file is None:
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("version") != INDEX_VERSION or data.get("homes") != [str(h) for h in self.homes]:
            return
        for raw in data.get("files") or []:
            try:
                state = FileState(**raw)
            except TypeError:
                continue
            self.files[state.path] = state

    def save(self, force: bool = False) -> None:
        """Write the index atomically (temp file + rename), at most once a minute unless ``force``."""

        if self.cache_file is None or not self.dirty or (not force and time.time() - self.saved_at < SAVE_TTL_S):
            return
        with self.lock:
            payload = json.dumps({"version": INDEX_VERSION, "homes": [str(h) for h in self.homes],
                                  "files": [asdict(state) for state in self.files.values()]}, separators=(",", ":"))
            self.dirty = False
            self.saved_at = time.time()
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.cache_file.parent), prefix=".transcripts-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.cache_file)
        except OSError:
            self.dirty = True

    # ---------------------------------------------------------------------------------------------- refresh

    def refresh(self, now: float, must_include: Iterable[tuple[str, str]] = ()) -> dict[str, FileState]:
        """Fold every transcript modified since ``now - WINDOW_S`` up to its end; returns path -> state.

        ``must_include``: (account, session) pairs (the live sessions); their top-level transcript is looked up by
        name when the cached listing does not have it yet (a session that started since the last walk).
        """

        started = time.perf_counter()
        window_start = now - WINDOW_S
        walked = False
        if not self.listing:
            self.listing, self.total_files = walk_transcripts(self.homes)
            self.walked_at = time.time()
            walked = True
        walk_ms = (time.perf_counter() - started) * 1000
        self._start_walker()
        with self.lock:
            if not walked and self.pending is not None:
                self.listing, self.total_files = self.pending
                self.pending = None
                walked = True
            if walked:
                self.by_session = {(item[1], item[3]): item for item in self.listing if item[2] == "top"}
                candidates = list(self.listing)
            else:
                # WHY only the files that were recent at the last walk (plus the live sessions' own transcripts):
                # statting all 8,700 files costs ~23 ms a request; a file that wakes up after a week is picked up
                # by the next walk (WALK_TTL_S).
                candidates = [self.recent[key] for key in self.recent]
                listed = {str(item[0]) for item in candidates}
                for account, session in must_include:
                    item = self.by_session.get((account, session))
                    if item is None:
                        item = self._lookup(account, session)
                    if item is not None and str(item[0]) not in listed:
                        candidates.append(item)
                        listed.add(str(item[0]))
            read = 0
            folded = 0
            current: dict[str, FileState] = {}
            recent: dict[str, tuple] = {}
            stat_started = time.perf_counter()
            for path, account, kind, session, info in candidates:
                key = str(path)
                if not walked:
                    try:
                        info = os.stat(path)
                    except OSError:
                        continue
                if info.st_mtime < window_start:
                    continue
                recent[key] = (path, account, kind, session, info)
                state = self.files.get(key)
                if state is None:
                    state = FileState(path=key, account=account, kind=kind, session=session)
                    self.files[key] = state
                if walked and state.agent_ts and state.agent_ts[0] < window_start:
                    state.agent_ts = [t for t in state.agent_ts if t >= window_start]
                # WHY size and not offset: a transcript whose last line is still being written keeps offset < size;
                # it is reread when it grows, not on every refresh.
                if (info.st_dev, info.st_ino) != (state.dev, state.ino) or info.st_size != state.size:
                    got = fold_file(state, info, window_start)
                    if got:
                        read += got
                        folded += 1
                        self.dirty = True
                current[key] = state
            self.recent = recent
            if walked:
                known = {str(item[0]) for item in self.listing}
                for key in list(self.files):
                    if key not in current and key not in known:
                        del self.files[key]
                        self.dirty = True
            self.stats = {"files_on_disk": self.total_files, "recent": len(current),
                          "subagent_files": sum(1 for s in current.values() if s.kind == "sub"),
                          "folded_now": folded, "bytes_read_now": read, "walked": walked,
                          "walk_ms": round(walk_ms, 1), "stat_ms": round((time.perf_counter() - stat_started) * 1000, 1)}
            return current

    def _lookup(self, account: str, session: str) -> tuple | None:
        """A session's top-level transcript found by name (it started after the last walk)."""

        for home in self.homes:
            if account_of(home) != account:
                continue
            for match in (home / "projects").glob(f"*/{session}.jsonl"):
                try:
                    item = (match, account, "top", session, os.stat(match))
                except OSError:
                    continue
                self.by_session[(account, session)] = item
                return item
        return None

    def find_transcript(self, account: str, session: str) -> str | None:
        """The top-level transcript of a session (any age): from the last walk, else looked up by name."""

        item = self.by_session.get((account, session)) or self._lookup(account, session)
        return str(item[0]) if item else None
