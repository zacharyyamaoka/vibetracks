"""Compose ``vibetracks-home/1``: every track's derived state, from what the harness and the loops wrote.

    from vibetracks.home.compose import build_home
    doc = build_home("/home/bam/vibetracks/workspace")       # live: real sessions, transcripts, projection, needs

Inputs, all read-only:

- the work-track registry (``tracks/*.md`` with ``vibe-track: worktrack``) and the home-only notes beside it
  (``vibe-track: activity``: a track with sessions but no KPI adapter yet). Home keys on either kind of note:
  ``vibe-project``, ``vibe-target`` (a date already written down; never invented), ``vibe-sessions`` (join.py),
  ``vibe-stall-hours`` and, on activity notes, ``vibe-loop-files`` (absolute paths, ``@worktree:`` allowed, whose
  newest mtime is the loop's last write). When a work track and an activity note share an id (fivebar and kincal
  once their adapter branches merge), the work track is the row and a home key it lacks comes from the activity note.
- the dashboard projection (``vibetracks.dashboard.build.LiveBuilder``): progress (north star), the loop's freshness,
  ``reporting``, and the Needs-you counts (which are needs.py's own).
- needs.py's documents, for the age of the oldest open question (cached 15 s).
- ``vibetracks.activity.harness``: live session files and the transcript index.

Nothing an agent says about itself is read; a note's ``vibe-status`` counts only as ``done`` or ``archived``. What
was not observed is null in the document and "unknown" on the page, never 0 and never "fine".
"""

from __future__ import annotations

import bisect
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from ..activity import harness
from ..activity.derive import GAP_S, LABELS, Facts, health_of, track_state
from ..activity.join import SessionRules, match, parse_rules
from ..dashboard.registry import find_registry, read_registry
from ..descriptor import load_descriptor
from ..edits import read_note_exact
from ..notes import first_paragraph, parse_frontmatter
from ..sources import _resolve_worktree
from .projects import read_projects, slug

SCHEMA = "vibetracks-home/1"
ACTIVITY_MARKER = "activity"
DAY_S = 86400
NEEDS_TTL_S = 15.0
#: The projection is rebuilt at most this often (LiveBuilder reruns needs.py for every track: ~25 ms).
PROJECTION_TTL_S = 5.0
DEFAULT_STALL_HOURS = 24.0
#: Muted project colours (the accepted mock's), assigned in project order.
PROJECT_COLORS = ["#8d7cc3", "#5aa6a0", "#c39a6b", "#7c9cc3", "#c37c8d", "#8da35a", "#a07cc3"]
PERSON_STATUSES = ("done", "archived")


@dataclass
class HomeTrack:
    id: str
    title: str
    kind: str                   # "adapter" (a work-track registry row) | "activity" (a home-only note)
    status: str
    priority: int | None
    adapter: str | None
    project: str | None
    target: str | None
    stall_hours: float
    rules: SessionRules
    loop_files: list[str]
    purpose: str
    note_path: str
    problems: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------ the notes


def _priority(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


def _target(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float)) and str(v).strip()]
    return []


_NOTES: dict[str, tuple[tuple, tuple]] = {}


def _notes_stamp(workspace: Path) -> tuple:
    """mtime/size of every file the track list depends on: the .vtdash files, the descriptor and every note."""

    stamp = []
    descriptor = find_registry(workspace)
    paths = sorted(workspace.glob("*.vtdash")) + ([descriptor] if descriptor else [])
    if descriptor is not None:
        try:
            paths += sorted(load_descriptor(descriptor).source.rglob("*.md"))
        except Exception:  # noqa: BLE001 - read_tracks says why
            pass
    for path in paths:
        try:
            info = path.stat()
            stamp.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append((str(path), None, None))
    return tuple(stamp)


def read_tracks(workspace: str | os.PathLike[str]) -> tuple[list[HomeTrack], list[dict[str, str]], Path]:
    """``read_tracks_uncached`` behind a cache keyed by every note's mtime and size (YAML parsing was 15 ms)."""

    workspace = Path(workspace)
    key = str(workspace.resolve())
    stamp = _notes_stamp(workspace)
    cached = _NOTES.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    result = read_tracks_uncached(workspace)
    _NOTES[key] = (stamp, result)
    return result


def read_tracks_uncached(workspace: str | os.PathLike[str]) -> tuple[list[HomeTrack], list[dict[str, str]], Path]:
    """Every track the home shows (archived and done included), the problems met reading them, and the registry."""

    registry = read_registry(workspace)
    problems = [dict(p) for p in registry.problems]
    source = load_descriptor(registry.descriptor).source
    notes: dict[str, tuple[dict[str, Any], str, Path]] = {}
    activity: dict[str, tuple[dict[str, Any], str, Path]] = {}
    for path in sorted(source.rglob("*.md")):
        try:
            frontmatter, body = parse_frontmatter(read_note_exact(path))
        except Exception as error:  # noqa: BLE001 - one bad note never takes the home down
            problems.append({"path": path.name, "error": str(error)})
            continue
        marker = str(frontmatter.get("vibe-track", ""))
        track_id = frontmatter.get("vibe-id")
        if not isinstance(track_id, str):
            continue
        if marker == "worktrack":
            notes[track_id] = (frontmatter, body, path)
        elif marker == ACTIVITY_MARKER:
            if track_id in activity:
                problems.append({"path": path.name, "error": f"duplicate activity id {track_id!r}; skipped"})
                continue
            activity[track_id] = (frontmatter, body, path)

    def home_key(track_id: str, key: str) -> Any:
        """A home key from the work track's note, else from an activity note of the same id."""
        own = notes.get(track_id, ({}, "", None))[0]
        if key in own and own[key] is not None:
            return own[key]
        return activity.get(track_id, ({}, "", None))[0].get(key)

    def build(track_id: str, frontmatter: dict, body: str, path: Path, kind: str, *, title: str, status: str,
              priority: int | None, adapter: str | None, stall: float, purpose: str) -> HomeTrack:
        rules = parse_rules(track_id, home_key(track_id, "vibe-sessions"))
        stall_raw = home_key(track_id, "vibe-stall-hours")
        if kind == "activity" and isinstance(stall_raw, (int, float)) and not isinstance(stall_raw, bool) and stall_raw > 0:
            stall = float(stall_raw)
        track = HomeTrack(id=track_id, title=title, kind=kind, status=status, priority=priority, adapter=adapter,
                          project=str(home_key(track_id, "vibe-project")).strip() if home_key(track_id, "vibe-project") else None,
                          target=_target(home_key(track_id, "vibe-target")), stall_hours=stall, rules=rules,
                          loop_files=_string_list(home_key(track_id, "vibe-loop-files")), purpose=purpose,
                          note_path=str(path), problems=list(rules.problems))
        for text in rules.problems:
            problems.append({"path": path.name, "error": text})
        return track

    out: list[HomeTrack] = []
    for work_track in registry.tracks:
        frontmatter, body, path = notes.get(work_track.id, ({}, "", Path(work_track.note_path)))
        out.append(build(work_track.id, frontmatter, body, path, "adapter", title=work_track.title,
                         status=work_track.status, priority=work_track.priority, adapter=work_track.adapter,
                         stall=work_track.stall_hours, purpose=work_track.purpose))
    seen = {track.id for track in out}
    for track_id, (frontmatter, body, path) in activity.items():
        if track_id in seen:
            continue
        title = frontmatter.get("vibe-title")
        title = str(title) if isinstance(title, (str, int, float)) and str(title).strip() else track_id
        status = str(frontmatter.get("vibe-status") or "running").strip().lower()
        out.append(build(track_id, frontmatter, body, path, "activity", title=title, status=status,
                         priority=_priority(frontmatter.get("vibe-priority")), adapter=None, stall=DEFAULT_STALL_HOURS,
                         purpose=first_paragraph(body, limit=None, raw=True)))
    out.sort(key=lambda t: (t.priority is None, t.priority or 0, t.id))
    return out, problems, registry.descriptor


# ------------------------------------------------------------------------------------------------ live inputs

_LOCK = threading.Lock()
_INDEXES: dict[tuple, harness.TranscriptIndex] = {}
_BUILDERS: dict[str, Any] = {}
_NEEDS: dict[str, tuple[float, dict[str, dict]]] = {}
_TAILS: dict[tuple[str, int], dict[str, Any]] = {}


def transcript_index(homes: list[Path], cache_dir: str | os.PathLike[str] | None) -> harness.TranscriptIndex:
    key = (tuple(str(h) for h in homes), str(cache_dir) if cache_dir else None)
    with _LOCK:
        index = _INDEXES.get(key)
        if index is None:
            index = _INDEXES[key] = harness.TranscriptIndex(homes, cache_dir=cache_dir)
        return index


def live_projection(workspace: str | os.PathLike[str]) -> dict[str, Any]:
    from ..dashboard.build import LiveBuilder  # noqa: PLC0415 - heavy; only the live path needs it

    key = str(Path(workspace).resolve())
    with _LOCK:
        entry = _BUILDERS.get(key)
        if entry is None:
            entry = _BUILDERS[key] = [LiveBuilder(workspace), 0.0, None]
    if entry[2] is None or time.monotonic() - entry[1] > PROJECTION_TTL_S:
        entry[2] = entry[0].build()
        entry[1] = time.monotonic()
    return entry[2]


def live_needs(workspace: str | os.PathLike[str], now: float) -> dict[str, dict]:
    """needs.py's documents by track (cached ``NEEDS_TTL_S``): only the ages of open questions are read from them;
    the counts come from the projection, which is needs.py's own count (build.py)."""

    from ..dashboard import needs as needs_module  # noqa: PLC0415

    key = str(Path(workspace).resolve())
    cached = _NEEDS.get(key)
    if cached is not None and time.monotonic() - cached[0] < NEEDS_TTL_S:
        return cached[1]
    docs = {doc["track"]: doc for doc in needs_module.build_all(workspace=workspace).get("tracks") or []}
    _NEEDS[key] = (time.monotonic(), docs)
    return docs


def _tail(path: str) -> dict[str, Any]:
    try:
        size = os.stat(path).st_size
    except OSError:
        return {}
    key = (path, size)
    if key not in _TAILS:
        if len(_TAILS) > 512:
            _TAILS.clear()
        _TAILS[key] = harness.tail_fields(path)
    return _TAILS[key]


# ------------------------------------------------------------------------------------------------ helpers


def _ago(now: float, when: float | None) -> int | None:
    return None if when is None else int(now - when)


def _missing_worktrees(sources: Iterable[Mapping[str, Any]]) -> list[str]:
    gone = []
    for source in sources:
        path = source.get("path") if isinstance(source, Mapping) else None
        if not isinstance(path, str) or source.get("exists"):
            continue
        marker = "/.claude/worktrees/"
        if marker in path:
            root, rest = path.split(marker, 1)
            name = rest.split("/", 1)[0]
            if name and not os.path.isdir(root + marker + name) and name not in gone:
                gone.append(name)
    return gone


def _progress(track: HomeTrack, projected: Mapping[str, Any] | None) -> dict[str, Any]:
    if track.kind == "activity":
        return {"label": None, "value": None, "of": None, "unit": None, "unknown": "no KPI adapter yet", "source": None}
    if not projected:
        return {"label": None, "value": None, "of": None, "unit": None, "unknown": "no projection for this track", "source": None}
    if not projected.get("reporting", True):
        return {"label": None, "value": None, "of": None, "unit": None, "unknown": "not reporting", "source": "projection"}
    north = projected.get("north_star")
    kpi = next((k for k in projected.get("kpis") or [] if isinstance(k, Mapping) and k.get("id") == north), None)
    if kpi is None:
        return {"label": None, "value": None, "of": None, "unit": None, "unknown": "no north-star KPI reported",
                "source": "projection"}
    measured = [v for v in kpi.get("values") or [] if isinstance(v, Mapping) and v.get("measured") and v.get("value") is not None]
    target = kpi.get("target") if isinstance(kpi.get("target"), Mapping) else {}
    base = {"label": kpi.get("label"), "unit": kpi.get("unit"), "direction": kpi.get("direction"),
            "target": target.get("value"), "target_label": target.get("label"), "source": f"projection north_star {north}"}
    if not measured:
        return {**base, "value": None, "of": None, "unknown": "not measured yet"}
    last = measured[-1]
    return {**base, "value": last.get("value"), "of": last.get("of"), "iteration": last.get("iteration"), "unknown": None}


def _mode(track: HomeTrack, projected: Mapping[str, Any] | None) -> dict[str, str]:
    """Discover or Optimize, a label only (Zach, Oct 9: "shown only as a mode label for now"). Derived: a track whose
    loop reports a north-star KPI is optimizing it; a track with no KPI adapter, or none reported, is discovering what
    to measure."""

    if track.kind == "adapter" and projected and projected.get("north_star"):
        return {"word": "optimize", "why": f"its loop reports a north-star KPI ({projected.get('north_star')})"}
    if track.kind == "activity":
        return {"word": "discover", "why": "no KPI adapter yet: nothing is measured, so it is still finding what to measure"}
    return {"word": "discover", "why": "no north-star KPI is reported"}


def _needs_age(doc: Mapping[str, Any] | None, now: float) -> tuple[int | None, int]:
    """(age in seconds of the oldest question that wants you, how many of them have no recorded ask time)."""

    if not doc:
        return None, 0
    oldest, unknown = None, 0
    for item in doc.get("items") or []:
        if item.get("group") not in ("blocking", "no_default", "waiting"):
            continue
        created = (item.get("created") or {}).get("ts")
        when = harness.parse_ts(created) if created else None
        if when is None:
            unknown += 1
        elif oldest is None or when < oldest:
            oldest = when
    return _ago(now, oldest), unknown


def _vtdash_name(workspace: Path) -> str | None:
    for file in sorted(workspace.glob("*.vtdash")):
        if find_registry(file) is not None:
            return file.name
    return None


def _loop_write(track: HomeTrack, projected: Mapping[str, Any] | None, now: float) -> dict[str, Any] | None:
    if track.kind == "adapter":
        fresh = (projected or {}).get("freshness") or {}
        when = harness.parse_ts(fresh.get("newest"))
        if when is None:
            return None
        path = next((s.get("path") for s in fresh.get("sources") or [] if s.get("key") == fresh.get("newest_source")), None)
        return {"ts": harness.iso(when), "age_s": _ago(now, when), "key": fresh.get("newest_source"), "path": path}
    best = None
    for raw in track.loop_files:
        path = os.path.expanduser(_resolve_worktree(raw))
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, path)
    if best is None:
        return None
    return {"ts": harness.iso(best[0]), "age_s": _ago(now, best[0]), "key": "vibe-loop-files", "path": best[1]}


# ------------------------------------------------------------------------------------------------ worked time

_SERIES: dict[tuple, tuple[list[int], list[int]]] = {}


def _series(files: Iterable[harness.FileState]) -> tuple[list[int], list[int]]:
    """The union of the files' agent-entry times, sorted and deduplicated, with prefix sums of the gaps that count
    (at most GAP_S). Cached by each file's fold position, so a warm request does no sorting."""

    files = list(files)
    key = tuple(sorted((f.path, f.offset, len(f.agent_ts)) for f in files))
    cached = _SERIES.get(key)
    if cached is not None:
        return cached
    times = sorted({t for f in files for t in f.agent_ts})
    prefix = [0] * len(times)
    for i in range(1, len(times)):
        gap = times[i] - times[i - 1]
        prefix[i] = prefix[i - 1] + (gap if gap <= GAP_S else 0)
    if len(_SERIES) > 4096:
        _SERIES.clear()
    _SERIES[key] = (times, prefix)
    return times, prefix


def worked(files: Iterable[harness.FileState], since: float, until: float) -> int:
    """Exactly ``derive.worked_seconds`` over the files' entries in [since, until], in O(log n) once cached."""

    times, prefix = _series(files)
    i = bisect.bisect_left(times, since)
    j = bisect.bisect_right(times, until) - 1
    return int(prefix[j] - prefix[i]) if j > i else 0


# ------------------------------------------------------------------------------------------------ sessions


@dataclass
class Record:
    account: str
    session: str
    top: harness.FileState | None = None
    subs: list[harness.FileState] = field(default_factory=list)
    live: list[harness.LiveSession] = field(default_factory=list)
    track: str | None = None
    join: dict[str, Any] = field(default_factory=lambda: {"by": None, "value": None})
    branch: str | None = None
    cwd: str | None = None
    title: str | None = None
    transcript: str | None = None

    @property
    def files(self) -> list[harness.FileState]:
        return ([self.top] if self.top else []) + self.subs

    def last_agent(self) -> list | None:
        best = None
        for state in self.files:
            if state.last_agent and (best is None or state.last_agent[0] > best[0]):
                best = state.last_agent
        return best

    def last_error(self) -> list | None:
        best = None
        for state in self.files:
            if state.last_error and (best is None or state.last_error[0] > best[0]):
                best = state.last_error
        return best

    def open_asks(self) -> list[tuple[float, str]]:
        return [(asked, question) for state in self.files for asked, question in state.open_asks.values()]


def _session_word(record: Record, live: harness.LiveSession | None, now: float) -> str:
    last = record.last_agent()
    if live is not None and live.status == "waiting":
        return "needs_you"
    if record.open_asks():
        return "needs_you"
    if last is not None and last[1] == "error":
        return "error"
    if live is not None and live.status == "busy":
        return "working"
    if last is not None and now - last[0] <= GAP_S:
        return "working"
    return "idle" if live is not None else "ended"


def _session_entries(record: Record, now: float) -> list[dict[str, Any]]:
    last = record.last_agent()
    error = record.last_error()
    base = {
        "id": record.session, "account": record.account, "title": record.title, "branch": record.branch,
        "cwd": record.cwd, "transcript": record.transcript, "subagent_files": len(record.subs),
        "open_questions": len(record.open_asks()),
        "last_action": None if last is None else {"ts": harness.iso(last[0]), "age_s": _ago(now, last[0]),
                                                   "type": last[1], "body": last[2]},
        "last_error": None if error is None else {"ts": harness.iso(error[0]), "kind": error[1], "text": error[2],
                                                   "resets": harness.iso(error[3])},
        "worked": {"h24_s": worked(record.files, now - DAY_S, now), "d7_s": worked(record.files, now - harness.WINDOW_S, now)},
        "join": dict(record.join),
    }
    home = next((s.home for s in record.live), None) or f"{Path.home()}/.claude-{record.account}"
    resume = f"CLAUDE_CONFIG_DIR={home} claude --resume {record.session}"
    out = []
    for live in record.live or [None]:
        word = _session_word(record, live, now)
        entry = dict(base)
        entry.update({
            "pid": live.pid if live else None, "live": live is not None,
            "status": live.status if live else None, "waiting_for": live.waiting_for if live else None,
            "status_since": harness.iso(live.status_since) if live and live.status_since else None,
            "entrypoint": live.entrypoint if live else None,
            "state": {"word": word, "label": "Ended" if word == "ended" else LABELS[word]},
            # WHY desktop first: claude://code/continue?session=<hostSessionId> is Claude Desktop's own deep link (the
            # 200x sidebar's handoff route); the system handler (claude-url-router) gives it to the primary profile.
            "open": {"desktop": f"claude://code/continue?session={live.host_session}" if live and live.host_session else None,
                     "remote_control": f"https://claude.ai/code/{live.bridge}" if live and live.bridge else None,
                     "resume": resume},
        })
        out.append(entry)
    return out


def _records(files: Mapping[str, harness.FileState], live: list[harness.LiveSession],
             index: harness.TranscriptIndex, rules: list[SessionRules]) -> dict[tuple[str, str], Record]:
    records: dict[tuple[str, str], Record] = {}
    for state in files.values():
        record = records.setdefault((state.account, state.session), Record(state.account, state.session))
        if state.kind == "top":
            record.top = state
        else:
            record.subs.append(state)
    for session in live:
        records.setdefault((session.account, session.session_id), Record(session.account, session.session_id)).live.append(session)
    for record in records.values():
        top = record.top
        newest_sub = max(record.subs, key=lambda s: s.last_ts or 0, default=None)
        live_one = record.live[0] if record.live else None
        record.transcript = top.path if top else (index.find_transcript(record.account, record.session) if record.live else None)
        tail = _tail(record.transcript) if record.live and top is None and record.transcript else {}
        record.branch = (top.branch if top else None) or tail.get("branch") or (newest_sub.branch if newest_sub else None)
        record.cwd = (top.cwd if top else None) or tail.get("cwd") or (live_one.cwd if live_one else None) \
            or (newest_sub.cwd if newest_sub else None)
        record.title = (live_one.name if live_one and live_one.name else None) or (top.title if top else None) or tail.get("title")
        # WHY a parent's subagents never match on their own: their lines run with the parent's work but their own
        # cwd (often /home/bam) and sometimes another branch; only the parent decides (the fixture t-subagent).
        record.track, record.join = match(rules, branch=record.branch, cwd=record.cwd, title=record.title)
    return records


# ------------------------------------------------------------------------------------------------ the document

#: The last document's inputs per workspace, for the detail routes (detail.py): records by track, the projection,
#: the needs documents and the clock, so a track or project page never re-reads the transcripts.
LAST: dict[str, dict[str, Any]] = {}


def _folder_matches(folder: str) -> list[str]:
    import glob as _glob  # noqa: PLC0415

    return _glob.glob(folder) if any(ch in folder for ch in "*?[") else [folder]



def build_home(workspace: str | os.PathLike[str], *, claude_homes: Iterable[str | os.PathLike[str]] | None = None,
               proc_root: str | os.PathLike[str] = "/proc", now: float | None = None,
               projection: Mapping[str, Any] | None = None, needs: Mapping[str, Mapping[str, Any]] | None = None,
               cache_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """The ``vibetracks-home/1`` document for ``workspace``.

    ``projection`` and ``needs`` default to the live ones (LiveBuilder, needs.py); tests pass their own. ``claude_homes``
    defaults to every ``~/.claude-*``; ``proc_root`` is where pids are checked; ``cache_dir`` persists the transcript
    index between processes (None: memory only).
    """

    clock = time.perf_counter()
    timing: dict[str, float] = {}

    def lap(name: str) -> None:
        nonlocal clock
        timing[name] = round((time.perf_counter() - clock) * 1000, 1)
        clock = time.perf_counter()

    now = time.time() if now is None else float(now)
    workspace = Path(workspace)
    homes = [Path(h) for h in claude_homes] if claude_homes is not None else harness.claude_homes()
    tracks, problems, descriptor = read_tracks(workspace)
    lap("notes")
    if projection is None:
        try:
            projection = live_projection(workspace)
        except Exception as error:  # noqa: BLE001 - the home still answers; the problem says why
            traceback.print_exc()
            problems.append({"path": "projection", "error": f"live build failed · {type(error).__name__}: {error}"})
            projection = {"tracks": []}
    lap("projection")
    if needs is None:
        try:
            needs = live_needs(workspace, now)
        except Exception as error:  # noqa: BLE001
            problems.append({"path": "needs", "error": f"needs.py failed · {type(error).__name__}: {error}"})
            needs = {}
    lap("needs")
    projected = {t["id"]: t for t in projection.get("tracks") or [] if isinstance(t, Mapping) and t.get("parent") is None}

    live, live_counts = harness.live_sessions(homes, proc_root)
    lap("sessions")
    index = transcript_index(homes, cache_dir)
    files = index.refresh(now, must_include=[(s.account, s.session_id) for s in live])
    lap("transcripts")
    rules = [t.rules for t in tracks]
    records = _records(files, live, index, rules)
    lap("join")

    vtdash = _vtdash_name(workspace)
    by_track: dict[str, list[Record]] = {t.id: [] for t in tracks}
    for record in records.values():
        if record.track in by_track:
            by_track[record.track].append(record)

    track_docs: list[dict[str, Any]] = []
    for track in tracks:
        mine = by_track[track.id]
        proj = projected.get(track.id)
        track_files = [state for record in mine for state in record.files]
        last = max((r.last_agent() for r in mine if r.last_agent()), key=lambda x: x[0], default=None)
        error = max((r.last_error() for r in mine if r.last_error()), key=lambda x: x[0], default=None)
        asks = [ask for r in mine for ask in r.open_asks()]
        waiting = [(r.title or r.session, s.waiting_for) for r in mine for s in r.live if s.status == "waiting"]
        busy = sum(1 for r in mine for s in r.live if s.status == "busy")
        counts = (proj or {}).get("needs_you_count") or {}
        loop = _loop_write(track, proj, now)
        not_reporting = None
        if proj is not None and not proj.get("reporting", True):
            detail = ((proj.get("state") or {}).get("detail") or "not reporting").strip()
            gone = _missing_worktrees(((proj.get("freshness") or {}).get("sources")) or [])
            not_reporting = (f"worktree {', '.join(gone)} is gone (deleted or swept) · " if gone else "") + \
                f"adapter not reporting: {detail}"
        facts = Facts(now=now, person_status=track.status if track.status in PERSON_STATUSES else None,
                      stall_hours=track.stall_hours, waiting=waiting, busy=busy, open_questions=asks,
                      triage_open=counts.get("open"), triage_blocking=counts.get("blocking"),
                      last_agent=tuple(last) if last else None, last_error=tuple(error) if error else None,
                      not_reporting=not_reporting, last_loop_write=harness.parse_ts(loop["ts"]) if loop else None)
        state = track_state(facts)
        oldest, unknown_ages = _needs_age(needs.get(track.id), now)
        sessions = [entry for record in mine for entry in _session_entries(record, now)]
        rank = {"needs_you": 0, "error": 1, "working": 2, "idle": 3, "ended": 4}
        sessions.sort(key=lambda s: (not s["live"], rank.get(s["state"]["word"], 5),
                                     -(harness.parse_ts((s["last_action"] or {}).get("ts")) or 0)))
        track_link = f"/?vtdash={quote(vtdash)}#vt?track={quote(track.id)}" if vtdash and track.kind == "adapter" and proj else None
        review_link = f"{track_link}&needs=1" if track_link and counts.get("open") else None
        track_docs.append({
            "id": track.id, "title": track.title, "kind": track.kind, "adapter": track.adapter,
            "project": track.project, "status": track.status, "priority": track.priority, "target": track.target,
            "purpose": track.purpose, "stall_hours": track.stall_hours,
            "state": {**state, "since": None},
            "health": health_of(state),
            "progress": _progress(track, proj),
            "mode": _mode(track, proj),
            "worked": {"h24_s": worked(track_files, now - DAY_S, now), "d7_s": worked(track_files, now - harness.WINDOW_S, now)},
            "last_action": None if last is None else {"ts": harness.iso(last[0]), "age_s": _ago(now, last[0]),
                                                       "type": last[1], "body": last[2]},
            "last_loop_write": loop,
            "last_error": None if error is None else {"ts": harness.iso(error[0]), "age_s": _ago(now, error[0]),
                                                       "kind": error[1], "text": error[2], "resets": harness.iso(error[3])},
            "needs_you": {"blocking": counts.get("blocking") if proj else None, "open": counts.get("open") if proj else None,
                          "oldest_age_s": oldest, "unknown_ages": unknown_ages,
                          "source": ((proj or {}).get("needs_you_source") or {}).get("note") if proj else
                          ("no triage file: an activity-only track" if track.kind == "activity" else None),
                          "waiting_sessions": len(waiting),
                          "open_questions": [{"ts": harness.iso(t), "age_s": _ago(now, t), "question": q} for t, q in sorted(asks)],
                          "review": review_link},
            "sessions": sessions,
            "links": {"track": track_link, "review": review_link},
            "provenance": {
                "note": track.note_path,
                "state": state["rule"],
                "loop": (loop or {}).get("path"),
                "projection": bool(proj),
                "transcripts": sorted(state_.path for r in mine for state_ in r.files),
                "join": {by: sum(1 for r in mine if r.join["by"] == by) for by in ("branch", "cwd", "title")},
            },
            "problems": track.problems,
        })
    lap("derive")

    descriptors, project_problems = read_projects(workspace)
    problems += project_problems
    # Session -> project (Codex model): an unpinned live session (no track rule matched it) belongs to EVERY project
    # whose roots hold its cwd; a pinned one belongs to its track's project only, and stays under its track.
    other = []
    unpinned: dict[str, list[dict[str, Any]]] = {name: [] for name in descriptors}
    for record in records.values():
        if record.track is not None or not record.live:
            continue
        owners = [name for name, project in descriptors.items() if project.owns(record.cwd)]
        for entry in _session_entries(record, now):
            entry["projects"] = [descriptors[name].id for name in owners]
            other.append(entry)
            for name in owners:
                unpinned[name].append(entry)
    other.sort(key=lambda s: (s["account"], (s["title"] or "").casefold()))
    ended_other = sum(1 for r in records.values() if r.track is None and not r.live)

    projects: dict[str, dict[str, Any]] = {name: {"tracks": []} for name in descriptors}
    for doc in track_docs:
        name = doc["project"] or "No project"
        projects.setdefault(name, {"tracks": []})["tracks"].append(doc)
    project_docs = []
    ordered = sorted(projects.items(), key=lambda kv: (min([(t["priority"] or 10**6) for t in kv[1]["tracks"]] or [10**7]),
                                                       kv[0].casefold()))
    for position, (name, group) in enumerate(ordered):
        mine = group["tracks"]
        active = [t for t in mine if t["state"]["word"] not in PERSON_STATUSES]
        colors = [t["health"]["color"] for t in active]
        health = "red" if "red" in colors else "yellow" if "yellow" in colors else "green" if colors else "none"
        targets = sorted((t["target"], t["id"]) for t in active if t["target"])
        descriptor = descriptors.get(name)
        loose = sorted(unpinned.get(name, []), key=lambda s: (s["account"], (s["title"] or "").casefold()))
        project_docs.append({
            "id": slug(name),
            "name": name, "color": PROJECT_COLORS[position % len(PROJECT_COLORS)],
            "target": targets[0][0] if targets else None, "target_from": targets[0][1] if targets else None,
            "health": health,
            "rollup": {c: colors.count(c) for c in ("green", "yellow", "red")},
            "needs_you": {"blocking": sum(t["needs_you"]["blocking"] or 0 for t in active),
                          "open": sum(t["needs_you"]["open"] or 0 for t in active),
                          "tracks": sum(1 for t in active if t["state"]["word"] == "needs_you")},
            "worked": {"h24_s": sum(t["worked"]["h24_s"] for t in active), "d7_s": sum(t["worked"]["d7_s"] for t in active)},
            # WHY roots and not "folders" only: Zach's Codex model (Oct 6), a project IS a named set of 1..N roots.
            "roots": [{"path": root, "exists": any(os.path.isdir(m) for m in _folder_matches(root))}
                      for root in (descriptor.roots if descriptor else [])],
            "descriptor": descriptor.path if descriptor else None,
            "north_star": descriptor.north_star if descriptor else None,
            "sessions_unpinned": loose,
            "sessions_live": sum(1 for t in mine for s in t["sessions"] if s["live"]) + len(loose),
            "tracks": mine,
        })

    active = [t for t in track_docs if t["state"]["word"] not in PERSON_STATUSES]
    live_entries = [s for t in track_docs for s in t["sessions"] if s["live"]]
    review_items = sorted(((t["needs_you"]["blocking"] or 0, t["needs_you"]["oldest_age_s"] or 0, t) for t in active
                           if t["needs_you"]["open"]), key=lambda x: (-x[0], -x[1]))
    ages = [t["needs_you"]["oldest_age_s"] for t in active if t["needs_you"]["open"] and t["needs_you"]["oldest_age_s"] is not None]
    accounts = []
    for home in homes:
        account = harness.account_of(home)
        accounts.append({"id": account, "home": str(home),
                         "sessions_live": sum(1 for s in live if s.account == account)})
    lap("compose")
    LAST[str(workspace.resolve())] = {"now": now, "records": records, "tracks": tracks, "projected": projected,
                                      "needs": needs, "homes": homes, "built": time.monotonic()}
    return {
        "schema": SCHEMA,
        "generated_at": harness.iso(now),
        "window": {"days": harness.WINDOW_S // DAY_S, "gap_s": GAP_S},
        "summary": {
            "tracks": len(active),
            **{word: sum(1 for t in active if t["state"]["word"] == word) for word in ("needs_you", "error", "stale", "working", "idle")},
            "done": sum(1 for t in track_docs if t["state"]["word"] == "done"),
            "archived": sum(1 for t in track_docs if t["state"]["word"] == "archived"),
            "sessions_live": len(live_entries) + sum(1 for s in other if s["live"]),
            "sessions_matched": len(live_entries),
            "sessions_other": sum(1 for s in other if s["live"]),
            "sessions_other_ended_7d": ended_other,
        },
        "review": {"open": sum(t["needs_you"]["open"] or 0 for t in active),
                   "blocking": sum(t["needs_you"]["blocking"] or 0 for t in active),
                   "oldest_age_s": max(ages) if ages else None,
                   "href": review_items[0][2]["links"]["review"] if review_items else None,
                   "tracks": [{"id": t["id"], "title": t["title"], "open": t["needs_you"]["open"],
                               "blocking": t["needs_you"]["blocking"], "oldest_age_s": t["needs_you"]["oldest_age_s"],
                               "href": t["links"]["review"]} for _b, _a, t in review_items]},
        "accounts": accounts,
        "projects": project_docs,
        "other_sessions": other,
        "links": {"workbench": f"/?vtdash={quote(vtdash)}" if vtdash else "/"},
        "sources": {
            "workspace": str(workspace.resolve()), "registry": str(descriptor),
            "claude_homes": [str(h) for h in homes],
            "session_files": live_counts,
            "transcripts": {"files": index.stats.get("files_on_disk"), "recent": index.stats.get("recent"),
                            "subagent_files": index.stats.get("subagent_files"),
                            "read_now_bytes": index.stats.get("bytes_read_now"), "walked": index.stats.get("walked")},
            "projection": {"live": projection.get("source", {}).get("live") if isinstance(projection.get("source"), Mapping) else None,
                           "generated_at": projection.get("generated_at")},
            "timing_ms": timing,
        },
        "problems": problems,
    }
