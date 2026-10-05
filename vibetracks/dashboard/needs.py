"""The "Needs you" projection: every open question an agent loop holds for Zach, read LIVE and normalized to one shape.

    GET /needs?track=kinsim     -> one ``vibetracks-needs/1`` document
    GET /needs                  -> ``vibetracks-needs-all/1``: ``{"schema", "generated_at", "tracks": [doc, ...]}``
    GET /needs/evidence?track=kinsim&item=T47&n=0
                                -> the file behind that item's n-th evidence entry (only paths this module itself
                                   extracted from the item's text, only servable suffixes, only regular files)

Mounted by ``clank/backend/mounts.py`` (``('/needs', 'vibetracks.dashboard.needs:handle')``). Stdlib only.

WHY read the loops' own triage files on every request instead of the dashboard snapshot: the row Zach saw ("T14 ·
blocks GP2 · no default recorded") was a stale 10-03 snapshot plus an adapter that dropped question, recommendation
and default. A question he is asked to answer must be the loop's current text, verbatim, or his answer lands on a
question that no longer exists. Loops keep their own formats; this is a projection, never a second source of truth.

WHY compute ``default.state`` and ``blocking_now`` here instead of trusting ``status``: integrators leave items
``open`` after their default applied (kinsim T11/T15, rig T4/T6/...). The schema's own rule (an item blocks while it
is open, unanswered and its default has not applied; a finished iteration >= ``default_applies_after_wave`` applies
it) is evaluated against the loop's finished iteration.

Machine paths come from ``vibetracks.sources.load_sources()``. This module reads extra keys when the sources file has
them (``kinsim_triage_dir``, ``kinsim_loop_branch``, ``rig_loop_branch``, ``bam_ws_root``) and otherwise uses the
defaults below, so the shared sources module is untouched. Kinsim's folder: ``kinsim_triage_dir`` if set, else the
worktree holding ``kinsim_loop_branch``, else ``kinsim_loop_dir``, else ``kinsim_curriculum_dir``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from vibetracks.sources import load_sources

SCHEMA = "vibetracks-needs/1"
SCHEMA_ALL = "vibetracks-needs-all/1"
ANSWER_SCHEMA = "bam-triage-answer/1"

#: Extra source keys this module understands, with their defaults (overridable in ~/.local/share/vibetracks/sources.json).
NEEDS_DEFAULTS: dict[str, str] = {
    "bam_ws_root": "/home/bam/bam_ws",
    # WHY a branch and not a path: the kinsim loop's worktree moves between waves (wave-3-handoff-af2b9b today), while
    # the integration branch it commits triage.json to stays put. The path in kinsim_curriculum_dir is a fallback.
    "kinsim_loop_branch": "claude/kinematic-simulator-waste-sorting-cc14d6",
    "rig_loop_branch": "claude/rig-loop-work-continue-cb3c52",
}

#: Track order on the page and in /needs. Titles match the home table.
TRACKS: list[tuple[str, str]] = [
    ("kinsim", "Kinematic Sim"),
    ("rig", "Sim to Real · 1-DOF rig"),
    ("grasping", "Grasping"),
    ("detection", "Object Detection & Hyperspectral"),
    ("pyblocks", "pyblocks"),
]

#: Tracks with no machine-readable needs-you file yet: where the questions live and how an answer gets back.
UNSTRUCTURED: dict[str, dict[str, Any]] = {
    "grasping": {
        "note": "No needs-you file. The live record is curriculum.py CELLS with status 'needs' (download approvals per "
                "model id) and the morning packet in docs/grasping/ladder_data.py; neither has ids, defaults or status.",
        "paths": [
            "/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/policy/grasp_bench/src/grasp_bench/curriculum.py",
            "/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/docs/grasping/ladder_data.py",
        ],
        "channel": {"kind": "chat_paste", "target": "the grasping track session (ebbbbd1c, ~/.claude-proprotectives)",
                    "row_schema": None,
                    "read_back": "by hand: the session edits curriculum.py CELLS by model id, so name model ids verbatim"},
    },
    "detection": {
        "note": "Plan only, no loop running. The 3 decisions are prose in the vault note's '## Needs you' section.",
        "paths": ["/home/bam/zach_brain/Projects/BAM Robotics/Notes/Hyperspectral — KPIs and Curriculum Roadmap (2026-10-04).md"],
        "channel": {"kind": "note_paste", "target": "Daily Note '# Hyper feedback', or the loop's start prompt",
                    "row_schema": None, "read_back": "no loop reads answers yet"},
    },
    "pyblocks": {
        "note": "No loop running (integrator stopped Oct 1). The 6 calls live in the Oct 2 summary page, all with their "
                "default already in effect.",
        "paths": ["/home/bam/pyblocks/reports/media/single-file-evaluation-summary-2026-09-30.html"],
        "channel": {"kind": "chat_paste", "target": "the pyblocks integrator session", "row_schema": None,
                    "read_back": "by hand, from a chat paste of the page's feedback sheet"},
    },
}

#: Suffixes the evidence route serves, and as what. Code and logs go out as plain text.
SERVABLE: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webm": "video/webm",
    ".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".json": "application/json",
    ".jsonl": "text/plain; charset=utf-8", ".py": "text/plain; charset=utf-8", ".toml": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8", ".yml": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8", ".ts": "text/plain; charset=utf-8", ".tsx": "text/plain; charset=utf-8",
}
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024

GROUP_ORDER = ["blocking", "no_default", "waiting", "defaulting", "answered", "done"]
TRIAGE_ID = re.compile(r"^T(\d+)$")


# ---------------------------------------------------------------------------------------------------------------- io

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


_worktree_cache: dict[str, tuple[float, dict[str, str]]] = {}


def worktrees_by_branch(repo: str) -> dict[str, str]:
    """``{branch: worktree path}`` from ``git worktree list --porcelain``; cached 30 s. Empty when git fails."""
    now = time.monotonic()
    hit = _worktree_cache.get(repo)
    if hit and now - hit[0] < 30:
        return hit[1]
    found: dict[str, str] = {}
    try:
        out = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"], capture_output=True, text=True,
                             timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and path:
            found[line[len("branch "):].removeprefix("refs/heads/")] = path
    _worktree_cache[repo] = (now, found)
    return found


def _git_last_commit(directory: Path, file_name: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(directory), "log", "-1", "--format=%h", "--", file_name],
                             capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def _repo_root(directory: Path) -> Path | None:
    for parent in [directory, *directory.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def resolve_loop_dir(sources: Mapping[str, str], *, explicit_key: str | None, branch_key: str, subdir: str,
                     fallback_keys: tuple[str, ...] = ()) -> Path | None:
    """The loop folder: an explicit sources key wins, then the worktree that has the loop's branch, then fallback keys."""
    if explicit_key and sources.get(explicit_key):
        path = Path(sources[explicit_key]).expanduser()
        if (path / "triage.json").is_file():
            return path
    branch = sources.get(branch_key) or NEEDS_DEFAULTS[branch_key]
    repo = sources.get("bam_ws_root") or NEEDS_DEFAULTS["bam_ws_root"]
    worktree = worktrees_by_branch(repo).get(branch)
    if worktree:
        path = Path(worktree) / subdir
        if (path / "triage.json").is_file():
            return path
    for key in fallback_keys:
        if sources.get(key):
            path = Path(sources[key]).expanduser()
            if (path / "triage.json").is_file():
                return path
    return None


# ----------------------------------------------------------------------------------------------------- text helpers

def parse_subject_ids(subject: str) -> set[str]:
    """``"T14 T45 T46 T48-T51"`` -> {T14, T45, T46, T48, T49, T50, T51}."""
    ids: set[str] = set()
    for token in re.findall(r"T\d+(?:\s*-\s*T?\d+)?", subject or ""):
        match = re.match(r"T(\d+)(?:\s*-\s*T?(\d+))?", token)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if end < start or end - start > 200:
            end = start
        ids.update(f"T{n}" for n in range(start, end + 1))
    return ids


# WHY "the first colon followed by whitespace": headers carry times ("UPDATE 17:15: W0c round 7 ..."), so a plain
# [^:] header would cut "17" off as the header and start the text at "15:".
UPDATE_RE = re.compile(r"\s*\bUPDATE\s+([^\n]{1,80}?):\s+")


def split_updates(question: str) -> tuple[str, list[dict[str, str]]]:
    """The question's base text and its appended ``UPDATE <header>: ...`` paragraphs (oldest first), all verbatim."""
    matches = list(UPDATE_RE.finditer(question or ""))
    if not matches:
        return (question or "").strip(), []
    base = question[: matches[0].start()].strip()
    updates = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(question)
        updates.append({"header": match.group(1).strip(), "text_md": question[match.end():end].strip()})
    return base, updates


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(`'\"])")


def lead_and_provenance(base: str) -> tuple[str | None, str | None]:
    """(lead sentence, provenance sentence): verbatim slices of the base text, never rewritten.

    A kinsim question opens with "Filed at wave-N close from `research/...` §k ..." which is provenance, not the why;
    it is returned separately so a page can show the first sentence that says why without inventing a summary.
    """
    sentences = [part.strip() for part in SENTENCE_END.split(base or "") if part.strip()]
    provenance = None
    if sentences and re.match(r"^(Filed|Opened|Raised|Found) (at|from|by|in)\b", sentences[0]):
        provenance = sentences.pop(0)
    return (sentences[0] if sentences else None), provenance


RIG_ANSWER = re.compile(r"Answer:\s*Zach\s+(\d{4}-\d{2}-\d{2})\s*:\s*(.+)$", re.S)
QUOTED = re.compile(r"^[\"“](.+?)[\"”]\.?\s*(.*)$", re.S)


def parse_folded_answer(recommendation: str) -> dict[str, Any] | None:
    """The rig loop folds an answer into the recommendation: ``Answer: Zach 2026-10-02: "<quote>". <action>``.

    Unquoted answers (``Answer: Zach 2026-10-02: another agent owns ...``) are the integrator's paraphrase: the whole
    tail is kept as the note and ``quoted`` says it is not Zach's verbatim words. ``choice`` is null because the loop
    records words, not one of the three choices.
    """
    match = RIG_ANSWER.search(recommendation or "")
    if not match:
        return None
    tail = match.group(2).strip()
    quoted = QUOTED.match(tail)
    note, action = (quoted.group(1).strip(), quoted.group(2).strip() or None) if quoted else (tail, None)
    return {"choice": None, "note": note, "ts": match.group(1), "by": "zach", "channel": "chat_paste", "folded": True,
            "action_md": action, "quoted": bool(quoted)}


TOKEN_RE = re.compile(r"`([^`\n]{2,300})`|((?:/|~/|\b[\w.-]+/)[\w./@+-]*[\w/](?::\d+(?:-\d+)?)?)")
URL_RE = re.compile(r"https?://[^\s`)\"'<>]+")


def extract_evidence(text: str, roots: Iterable[Path]) -> list[dict[str, Any]]:
    """Paths named in the item's text that exist on disk, as absolute paths; URLs as they are. Order of first mention."""
    roots = [root for root in roots if root]
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for url in URL_RE.findall(text or ""):
        url = url.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            found.append({"label": url, "kind": "url", "value": url})
    for match in TOKEN_RE.finditer(text or ""):
        raw = (match.group(1) or match.group(2) or "").strip()
        # A backticked command or phrase is not a path: take its first path-looking word, if any.
        candidates = [raw] if " " not in raw else [word for word in raw.split() if "/" in word]
        for candidate in candidates:
            candidate = candidate.strip(".,;:()[]'\"")
            if "/" not in candidate and not re.search(r"\.\w{1,5}$", candidate):
                continue
            line = None
            line_match = re.match(r"^(.*?):(\d+)(?:-\d+)?$", candidate)
            if line_match:
                candidate, line = line_match.group(1), int(line_match.group(2))
            resolved = _resolve(candidate, roots)
            if resolved is None:
                continue
            key = f"{resolved}:{line or ''}"
            if key in seen:
                continue
            seen.add(key)
            kind = "file_line" if line else ("report" if resolved.suffix.lower() == ".html" else "path")
            value = f"{resolved}#L{line}" if line else str(resolved)
            found.append({"label": raw if len(raw) <= 120 else candidate, "kind": kind, "value": value,
                          "path": str(resolved), "line": line, "is_dir": resolved.is_dir()})
    return found


def _resolve(candidate: str, roots: list[Path]) -> Path | None:
    if candidate.startswith("~"):
        path = Path(candidate).expanduser()
        return path if path.exists() else None
    if candidate.startswith("/"):
        path = Path(candidate)
        return path if path.is_absolute() and ".." not in path.parts and path.exists() else None
    if ".." in Path(candidate).parts:
        return None
    for root in roots:
        path = root / candidate
        if path.exists():
            return path
    return None


# ------------------------------------------------------------------------------------------------ the triage tracks

def _number(local_id: str) -> int:
    match = TRIAGE_ID.match(local_id or "")
    return int(match.group(1)) if match else 10**6


def _event_index(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per triage id: when it was opened, and its latest triage_changed row (ts, status, detail)."""
    index: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.get("kind") != "triage_changed":
            continue
        for local_id in parse_subject_ids(str(row.get("subject") or "")):
            entry = index.setdefault(local_id, {})
            opened = row.get("status") == "opened" or str(row.get("detail") or "").startswith(f"Opened {local_id}")
            if opened and "opened" not in entry:
                entry["opened"] = row
            entry["last"] = row
    return index


def _latest_answers(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:  # WHY file order and not ts: the latest row per triage_id wins, as TriageView latestAnswers reads it
        local_id = row.get("triage_id")
        if isinstance(local_id, str) and row.get("choice") in ("accept_recommendation", "use_default", "other"):
            latest[local_id] = row
    return latest


def _finished_iteration(n: int | None, phase: str | None, events: list[dict[str, Any]]) -> int | None:
    """The last iteration that FINISHED: the status file's n when its phase says it closed, else n - 1; a
    wave_finished event can only raise it."""
    finished: int | None = None
    if isinstance(n, int):
        finished = n if phase in ("between_waves", "finished", "closed", "done") else n - 1
    for row in events:
        if row.get("kind") == "wave_finished" and isinstance(row.get("wave"), int):
            finished = row["wave"] if finished is None else max(finished, row["wave"])
    return finished


def _synth_options(recommendation: str, default_text: str, never: bool) -> list[dict[str, Any]]:
    """The loop's three implicit options (bam-triage-answer/1 choices), each carrying the loop's own words."""
    return [
        {"key": "accept_recommendation", "label": "Go with the recommendation", "detail_md": recommendation,
         "recommended": True, "is_default": False},
        {"key": "use_default", "label": "Keep waiting (no default)" if never else "Let the default apply",
         "detail_md": default_text, "recommended": False, "is_default": True},
        {"key": "other", "label": "Something else (write it)", "detail_md": None, "recommended": False,
         "is_default": False, "needs_note": True},
    ]


def build_triage_item(track: str, raw: Mapping[str, Any], *, finished: int | None, unit: str,
                      events: Mapping[str, dict[str, Any]], answers: Mapping[str, dict[str, Any]],
                      rung_labels: Mapping[str, tuple[str, str]], roots: list[Path],
                      answer_channel_kind: str) -> dict[str, Any]:
    local_id = str(raw.get("triage_id") or "")
    title = str(raw.get("title") or "")
    question = str(raw.get("question") or "")
    recommendation = str(raw.get("recommendation") or "")
    default_text = str(raw.get("default") or "")
    after = raw.get("default_applies_after_wave")
    raw_status = str(raw.get("status") or "open")
    never = not isinstance(after, int)

    if never:
        state = "none"
        applies = {"unit": "never", "after": None}
    else:
        applies = {"unit": unit, "after": after}
        state = "in_effect" if finished is not None and finished >= after else "pending"

    answer = None
    row = answers.get(local_id)
    if row is not None:
        answer = {"choice": row.get("choice"), "note": row.get("note") or "", "ts": row.get("ts"), "by": "zach",
                  "channel": "jsonl_append", "folded": raw_status != "open", "action_md": None, "quoted": True}
    if answer is None and raw_status == "answered":
        answer = parse_folded_answer(recommendation)
        if answer is None:
            # WHY by=None: the loop marked it answered without recording Zach's words (rig T12 "Resolved ..."), so
            # the page must not attribute an answer to him.
            answer = {"choice": None, "note": "", "ts": None, "by": None, "channel": answer_channel_kind,
                      "folded": True, "action_md": None, "quoted": False}

    # Effective status: an answer written but not yet folded by the integrator already counts as answered.
    status = raw_status
    if raw_status == "open" and answer is not None:
        status = "answered"
    if status not in ("open", "answered", "defaulted", "closed", "superseded"):
        status = "open"

    blocks = []
    for block_id in raw.get("blocks") or []:
        kind, label = rung_labels.get(str(block_id), ("rung", None))
        blocks.append({"id": str(block_id), "kind": kind, "label": label})

    unanswered_open = status == "open"
    blocking_now = unanswered_open and state != "in_effect" and bool(blocks) and (never or state == "pending")
    if blocking_now:
        group = "blocking"
    elif unanswered_open and never:
        group = "no_default"
    elif unanswered_open and state == "pending":
        group = "waiting"
    elif unanswered_open:
        group = "defaulting"
    elif status == "answered":
        group = "answered"
    else:
        group = "done"

    base, updates = split_updates(question)
    lead, provenance = lead_and_provenance(base)
    event = events.get(local_id, {})
    opened, last = event.get("opened"), event.get("last")
    created_iteration = raw.get("opened_wave") if isinstance(raw.get("opened_wave"), int) else None
    return {
        "id": f"{track}:{local_id}",
        "local_id": local_id,
        "kind": "decision",
        "title": title,
        "ask": title,
        "context_md": question,
        "context_summary": None,
        "context_base_md": base,
        "context_lead_md": lead,
        "provenance_md": provenance,
        "updates": updates,
        "options": _synth_options(recommendation, default_text, never),
        "recommendation_md": recommendation,
        "default": {"text_md": default_text, "applies": applies, "state": state},
        "blocks": blocks,
        "blocking_now": blocking_now,
        "group": group,
        "evidence": extract_evidence("\n".join([question, recommendation, default_text]), roots),
        "asked_by": {"agent": "integrator", "session": None, "account": None},
        "created": {"iteration": created_iteration, "ts": opened.get("ts") if opened else None},
        "updated": {"ts": last.get("ts") if last else None,
                    "note": (f"UPDATE {updates[-1]['header']}" if updates else (last.get("detail") if last else None))},
        "status": status,
        "raw_status": raw_status,
        "answer": answer,
        "effort": None,
    }


def _sort_key(item: Mapping[str, Any]) -> tuple:
    applies = item["default"]["applies"]
    fires = applies["after"] if isinstance(applies.get("after"), int) else 10**6
    return (GROUP_ORDER.index(item["group"]), fires if item["group"] in ("blocking", "waiting") else 0,
            _number(item["local_id"]))


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"open": 0, "blocking_now": 0, "no_default": 0, "waiting": 0, "defaulting": 0, "answered": 0,
              "defaulted": 0, "closed": 0, "total": len(items)}
    for item in items:
        if item["status"] == "open":
            counts["open"] += 1
        if item["blocking_now"]:
            counts["blocking_now"] += 1
        if item["group"] == "no_default" or (item["blocking_now"] and item["default"]["applies"]["unit"] == "never"):
            counts["no_default"] += 1
        if item["group"] == "waiting":
            counts["waiting"] += 1
        if item["group"] == "defaulting":
            counts["defaulting"] += 1
        if item["status"] == "answered":
            counts["answered"] += 1
        if item["status"] == "defaulted":
            counts["defaulted"] += 1
        if item["status"] in ("closed", "superseded"):
            counts["closed"] += 1
    return counts


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _empty_doc(track: str, title: str, note: str, *, paths: list[str] | None = None,
               channel: dict[str, Any] | None = None, adapter: str = "none") -> dict[str, Any]:
    return {
        "schema": SCHEMA, "track": track, "track_title": title, "generated_at": _now(), "iteration": None,
        "source": {"adapter": adapter, "paths": paths or [], "commit": None, "live": False, "note": note},
        "answer_channel": channel or {"kind": "none", "target": None, "row_schema": None, "read_back": None},
        "counts": _counts([]), "items": [],
    }


def build_kinsim(sources: Mapping[str, str]) -> dict[str, Any]:
    title = dict(TRACKS)["kinsim"]
    loop_dir = resolve_loop_dir(sources, explicit_key="kinsim_triage_dir", branch_key="kinsim_loop_branch",
                                subdir="src/dev/bam_curriculum",
                                fallback_keys=("kinsim_loop_dir", "kinsim_curriculum_dir"))
    if loop_dir is None:
        return _empty_doc("kinsim", title, "triage.json not found: no worktree has the kinsim loop branch and "
                          "kinsim_curriculum_dir has no triage.json", adapter="bam_triage")
    home = Path(sources.get("kinsim_home") or "~/.local/share/bam_curriculum").expanduser()
    triage = _read_json(loop_dir / "triage.json") or {}
    status = _read_json(home / "status.json") or {}
    events = _read_jsonl(home / "loop_events.jsonl")
    answers_path = home / "triage_answers.jsonl"
    answers = _latest_answers(_read_jsonl(answers_path))
    finished = _finished_iteration(status.get("wave"), status.get("phase"), events)
    rung_labels: dict[str, tuple[str, str]] = {}
    for rung in (_read_json(loop_dir / "curriculum.json") or {}).get("rungs") or []:
        if isinstance(rung, dict) and rung.get("id"):
            rung_labels[str(rung["id"])] = ("rung", rung.get("title"))
    for rung in status.get("rungs") or []:
        if isinstance(rung, dict) and rung.get("rung_id"):
            rung_labels[str(rung["rung_id"])] = ("rung", rung.get("title"))
    repo = _repo_root(loop_dir)
    roots = [loop_dir, *( [repo] if repo else [] ), Path(sources.get("bam_ws_root") or NEEDS_DEFAULTS["bam_ws_root"]), home]
    items = [build_triage_item("kinsim", raw, finished=finished, unit="wave", events=_event_index(events),
                               answers=answers, rung_labels=rung_labels, roots=roots, answer_channel_kind="jsonl_append")
             for raw in triage.get("items") or [] if isinstance(raw, dict)]
    items.sort(key=_sort_key)
    return {
        "schema": SCHEMA, "track": "kinsim", "track_title": title, "generated_at": _now(),
        "iteration": {"unit": "wave", "n": status.get("wave"), "phase": status.get("phase"), "finished": finished},
        "source": {"adapter": "bam_triage", "paths": [str(loop_dir / "triage.json"), str(home / "status.json"),
                                                      str(home / "loop_events.jsonl"), str(answers_path)],
                   "commit": _git_last_commit(loop_dir, "triage.json"), "live": True,
                   "note": f"{triage.get('schema', '?')} read live; blocking per status.json: "
                           f"{', '.join(status.get('blocking_triage') or []) or 'none'}"},
        "answer_channel": {"kind": "jsonl_append", "target": str(answers_path), "row_schema": ANSWER_SCHEMA,
                           "read_back": "at the next wave start (integrator)",
                           "alternatives": ["POST /api/triage/<id>/answer on the kinsim dashboard API",
                                            "paste into the loop's chat"]},
        "counts": _counts(items), "items": items,
    }


def build_rig(sources: Mapping[str, str]) -> dict[str, Any]:
    title = dict(TRACKS)["rig"]
    loop_dir = resolve_loop_dir(sources, explicit_key="rig_loop_dir", branch_key="rig_loop_branch",
                                subdir="src/dev/bam_rig_loop")
    if loop_dir is None:
        return _empty_doc("rig", title, "triage.json not found in rig_loop_dir or the rig loop branch's worktree",
                          adapter="bam_triage")
    triage = _read_json(loop_dir / "triage.json") or {}
    loop_status = _read_json(loop_dir / "loop-status.json") or {}
    events = _read_jsonl(loop_dir / "loop_events.jsonl")
    tick = loop_status.get("tick") or {}
    finished = _finished_iteration(tick.get("n"), tick.get("phase"), events)
    rung_labels: dict[str, tuple[str, str]] = {}
    ladder = _read_json(loop_dir / "ladder.json") or {}
    for package in ladder.get("packages") or []:
        if isinstance(package, dict) and package.get("id"):
            rung_labels[str(package["id"])] = ("package", package.get("title"))
    for axis in ladder.get("axes") or []:
        for rung in (axis or {}).get("rungs") or []:
            if isinstance(rung, dict) and rung.get("id"):
                rung_labels[str(rung["id"])] = ("rung", rung.get("title"))
    repo = _repo_root(loop_dir)
    roots = [loop_dir, *([repo] if repo else []), Path(sources.get("bam_ws_root") or NEEDS_DEFAULTS["bam_ws_root"])]
    items = [build_triage_item("rig", raw, finished=finished, unit="wave", events=_event_index(events), answers={},
                               rung_labels=rung_labels, roots=roots, answer_channel_kind="chat_paste")
             for raw in triage.get("items") or [] if isinstance(raw, dict)]
    items.sort(key=_sort_key)
    return {
        "schema": SCHEMA, "track": "rig", "track_title": title, "generated_at": _now(),
        "iteration": {"unit": "wave", "n": tick.get("n"), "phase": tick.get("phase"), "finished": finished},
        "source": {"adapter": "bam_triage", "paths": [str(loop_dir / "triage.json"), str(loop_dir / "loop-status.json"),
                                                      str(loop_dir / "loop_events.jsonl")],
                   "commit": _git_last_commit(loop_dir, "triage.json"), "live": True,
                   "note": f"{triage.get('schema', '?')} read live; answers are folded into recommendation by the integrator"},
        "answer_channel": {"kind": "chat_paste", "target": "the rig loop's integrator (/loop session)", "row_schema": None,
                           "read_back": "by hand: the integrator quotes your words into the item and sets it answered"},
        "counts": _counts(items), "items": items,
    }


def build_track(track: str, sources: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    sources = sources if sources is not None else load_sources()
    if track == "kinsim":
        return build_kinsim(sources)
    if track == "rig":
        return build_rig(sources)
    if track in UNSTRUCTURED:
        spec = UNSTRUCTURED[track]
        return _empty_doc(track, dict(TRACKS)[track], spec["note"], paths=spec["paths"], channel=spec["channel"],
                          adapter="none (prose only)")
    return None


def build_all(sources: Mapping[str, str] | None = None) -> dict[str, Any]:
    sources = sources if sources is not None else load_sources()
    docs = [doc for track, _ in TRACKS if (doc := build_track(track, sources)) is not None]
    return {"schema": SCHEMA_ALL, "generated_at": _now(), "tracks": docs}


# ------------------------------------------------------------------------------------------------------------ route

def _json(status: int, body: Any) -> tuple[int, dict[str, str], list[bytes]]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}, [payload]


def _first(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def _stream(path: Path, chunk: int = 256 * 1024) -> Iterable[bytes]:
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk)
            if not data:
                return
            yield data


def handle(method: str, subpath: str, query: Mapping[str, list[str]], headers: Mapping[str, str],
           sources: Mapping[str, str] | None = None):
    if method != "GET":
        return _json(405, {"error": "GET only"})
    subpath = subpath.rstrip("/")
    track = _first(query, "track")
    if subpath == "":
        if not track:
            return _json(200, build_all(sources))
        doc = build_track(track, sources)
        return _json(200, doc) if doc is not None else _json(404, {"error": f"unknown track {track!r}",
                                                                   "tracks": [t for t, _ in TRACKS]})
    if subpath == "/evidence":
        item_id, index = _first(query, "item"), _first(query, "n")
        if not track or not item_id or index is None or not index.isdigit():
            return _json(400, {"error": "need track, item and n"})
        doc = build_track(track, sources)
        if doc is None:
            return _json(404, {"error": f"unknown track {track!r}"})
        local = item_id.split(":", 1)[-1]
        item = next((it for it in doc["items"] if it["local_id"] == local), None)
        if item is None or int(index) >= len(item["evidence"]):
            return _json(404, {"error": "no such evidence entry"})
        entry = item["evidence"][int(index)]
        path = Path(entry.get("path") or "")
        # WHY serve only what this module extracted from the item's own text: the route must not become a way to
        # read any file on the machine by naming it; the evidence list is the allowlist, rebuilt on every request.
        if not entry.get("path") or not path.is_absolute() or ".." in path.parts or not path.is_file():
            return _json(404, {"error": "evidence is not a servable file", "path": entry.get("path")})
        content_type = SERVABLE.get(path.suffix.lower())
        if content_type is None:
            return _json(415, {"error": f"{path.suffix or 'no suffix'} is not served", "path": str(path)})
        size = path.stat().st_size
        if size > MAX_EVIDENCE_BYTES:
            return _json(413, {"error": "file too large to serve here", "path": str(path), "bytes": size})
        return 200, {"Content-Type": content_type, "Content-Length": str(size)}, _stream(path)
    return _json(404, {"error": f"no route {subpath!r} under /needs"})


if __name__ == "__main__":  # python3 -m vibetracks.dashboard.needs [track] -> the JSON on stdout
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(build_track(target) if target else build_all(), indent=1, ensure_ascii=False))
