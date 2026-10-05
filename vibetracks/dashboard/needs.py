"""The "Needs you" projection: every open question an agent loop holds for Zach, read LIVE and normalized to one shape.

    GET /needs?track=kinsim     -> one ``vibetracks-needs/1`` document
    GET /needs                  -> ``vibetracks-needs-all/1``: ``{"schema", "generated_at", "tracks": [doc, ...]}``
    GET /needs/evidence?track=kinsim&item=T47&eid=<entry eid>&rev=<doc evidence_rev>
                                -> the file recorded for that evidence entry when the document was built (only paths
                                   this module itself extracted from the item's text, only servable suffixes, only
                                   regular files); 409 when the document's evidence changed since ``rev``

Mounted by ``clank/backend/mounts.py`` (``('/needs', 'vibetracks.dashboard.needs:handle')``). Stdlib only.

WHY read the loops' own triage files on every request instead of the dashboard snapshot: the row Zach saw ("T14 ·
blocks GP2 · no default recorded") was a stale 10-03 snapshot plus an adapter that dropped question, recommendation
and default. A question he is asked to answer must be the loop's current text, verbatim, or his answer lands on a
question that no longer exists. Loops keep their own formats; this is a projection, never a second source of truth.

WHY compute ``default.state`` and ``blocking_now`` here instead of trusting ``status``: integrators leave items
``open`` after their default applied (kinsim T11/T15, rig T4/T6/...). The schema's own rule (an item blocks while it
is open, unanswered and its default has not applied; a finished iteration >= ``default_applies_after_wave`` applies
it) is evaluated against the loop's finished iteration.

WHY this module is the ONE source of every Needs-you count: the home cell, the track page and the needs page used to
count from two places (each adapter's own ``needs_you`` list, with "blocking" meaning "names a rung", against this
module's ``blocking_now``), so grasping read "7 blocking / 7 open" and opened an empty page. Now ``build.py`` fills the
projection's ``needs_you_count`` and ``needs_you`` from the doc built here (``needs_you_count()``,
``needs_you_rows()``): ``open`` is ``counts.wants_you`` (the groups blocking + no_default + waiting) and ``blocking``
is ``counts.blocking_now``. A track with no structured source has every count null ("not reported"), never 0.

Track ids, order and titles come from the work-track registry (``vibetracks.dashboard.registry``; the workspace is
``VIBETRACKS_WORKSPACE``, which the backend exports, else this repo's ``workspace/``), so a rename shows here too.

Machine paths come from ``vibetracks.sources.load_sources()``. This module reads extra keys when the sources file has
them (``kinsim_triage_dir``, ``kinsim_loop_branch``, ``rig_loop_branch``, ``bam_ws_root``) and otherwise uses the
defaults below, so the shared sources module is untouched. Kinsim's folder: ``kinsim_triage_dir`` if set, else the
worktree holding ``kinsim_loop_branch``, else ``kinsim_loop_dir``, else ``kinsim_curriculum_dir``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from vibetracks.dashboard.adapters import detection as detection_adapter
from vibetracks.dashboard.adapters import grasping as grasping_adapter
from vibetracks.dashboard.registry import read_registry
from vibetracks.errors import VibeTracksError
from vibetracks.safe_open import UnsafePath, open_no_symlinks
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

#: This repo's checked-in workspace: the registry /needs reads when the backend exported no VIBETRACKS_WORKSPACE.
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"
#: Track ids and order used only when the registry cannot be read (titles then show the id, and the doc says why).
FALLBACK_TRACK_IDS = ["kinsim", "rig", "grasping", "detection", "pyblocks"]

#: Where each prose-sourced track's answer goes back. WHY kept beside the parsers: the item text names model ids and
#: rung ids verbatim, and these channels are how the session that owns the file reads them.
CHANNELS: dict[str, dict[str, Any]] = {
    "grasping": {"kind": "chat_paste", "target": "the grasping track session (ebbbbd1c, ~/.claude-proprotectives)",
                 "row_schema": None,
                 "read_back": "by hand: the session edits curriculum.py CELLS by model id, so name model ids verbatim"},
    "detection": {"kind": "note_paste", "target": "Daily Note '# Hyper feedback', or the loop's start prompt",
                  "row_schema": None, "read_back": "no loop reads answers yet"},
}

#: Registry tracks whose loop writes no questions anywhere: every count is null ("not reported"), never 0.
NOT_REPORTED: dict[str, dict[str, Any]] = {
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
#: The groups that still want Zach: open, and their default is NOT already in effect. ``counts.wants_you`` counts
#: them, and it is the one "M open" every surface shows ("B blocking · M open").
WANTS_YOU_GROUPS = ("blocking", "no_default", "waiting")
COUNT_KEYS = ("open", "blocking_now", "wants_you", "no_default", "waiting", "defaulting", "answered", "defaulted",
              "closed", "total")
TRIAGE_ID = re.compile(r"^T(\d+)$")
#: Block kinds that hold the loop's climb: a rung, a package (the rig ladder's unit) or a gate. An item counts toward
#: ``blocking_now`` only when it names one of these. WHY not "any block": grasping's download approvals name curriculum
#: CELLS (kind ``cell``), which hold only that model's cells while the loop climbs past them, so counting them made the
#: home cell read "7 blocking" for a loop nothing was holding.
GATING_KINDS = ("rung", "package", "gate")


def holds_gate(blocks: Iterable[Mapping[str, Any]]) -> bool:
    """True when any block is a rung, package or gate (``GATING_KINDS``); a cell-only item never blocks."""
    return any(block.get("kind") in GATING_KINDS for block in blocks)


# ---------------------------------------------------------------------------------------------------------------- io

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_triage(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(triage document, None)``, or ``(None, why it cannot be counted)``.

    Valid means: readable UTF-8 JSON, an object, with an ``items`` list whose every entry is an object with a
    non-empty string ``triage_id``. WHY so strict (audit 2026-10-04, finding 3): ``_read_json(...) or {}`` turned a
    read error, broken JSON, a non-object or ``{}`` into an empty queue, so the page said "0 blocking · 0 open" with
    ``live: true`` while the loop's questions were unreadable. A document that cannot be counted is "not reported".
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return None, f"{type(error).__name__}: {error}"
    try:
        data = json.loads(text)
    except ValueError as error:
        return None, f"invalid JSON: {error}"
    if not isinstance(data, dict):
        return None, f"the document is a JSON {type(data).__name__}, not an object"
    if "items" not in data:
        return None, "the document has no items list"
    items = data["items"]
    if not isinstance(items, list):
        return None, f"items is a JSON {type(items).__name__}, not a list"
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            return None, f"items[{position}] is a JSON {type(item).__name__}, not an object"
        if not isinstance(item.get("triage_id"), str) or not item["triage_id"].strip():
            return None, f"items[{position}] has no triage_id"
    return data, None


def _unreadable_triage_doc(track: str, title: str, path: Path, reason: str, paths: list[str],
                           channel: dict[str, Any]) -> dict[str, Any]:
    """The doc for a triage file that exists but cannot be counted: every count null, the reason in the note."""
    doc = _empty_doc(track, title, f"not reported: {path.name} could not be read: {reason}", paths=paths,
                     channel=channel, adapter="bam_triage")
    doc["source"]["error"] = reason
    return doc


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
                          "path": str(resolved), "target": _canonical(resolved), "line": line,
                          "is_dir": resolved.is_dir()})
    return found


def _canonical(path: str | os.PathLike[str]) -> str | None:
    """The file ``path`` resolves to now (``os.path.realpath``), recorded when the evidence allowlist is built; None
    when it does not resolve. WHY: it is bound into the document's ``evidence_rev``, so a listed symlink retargeted
    after Zach saw the document answers 409 instead of streaming an unlisted file (audit 2026-10-04 finding 9,
    2026-10-05 finding 1), and it is the one path the route opens, symlink-free at every component."""
    try:
        return os.path.realpath(path, strict=True)
    except OSError:
        return None


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


def _synth_options(recommendation: str, default_text: str, never: bool,
                   leading: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """The answer affordances for one item: the loop's implicit choices (bam-triage-answer/1), after any ``leading``.

    Every option carries ``source: "dashboard"``: its ``key`` and ``label`` are the dashboard's answer affordance,
    never the loop's words, so a page must not present a label as something the loop said. ``detail_md`` is the only
    loop text in an option (the recommendation or the default, verbatim), or null.

    WHY no "Go with the recommendation" when the source records none (grasping's download approvals, the detection
    plan's items): it would be a control whose words are empty, a fake choice (calm rule: no fake controls).
    """
    accept = [{"key": "accept_recommendation", "label": "Go with the recommendation", "detail_md": recommendation,
               "recommended": True, "is_default": False}] if recommendation.strip() else []
    options = [*leading, *accept,
               {"key": "use_default", "label": "Keep waiting (no default)" if never else "Let the default apply",
                "detail_md": default_text or None, "recommended": False, "is_default": True},
               {"key": "other", "label": "Something else (write it)", "detail_md": None, "recommended": False,
                "is_default": False, "needs_note": True}]
    return [{**option, "source": "dashboard"} for option in options]


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
    blocking_now = unanswered_open and state != "in_effect" and holds_gate(blocks) and (never or state == "pending")
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
    counts = {key: 0 for key in COUNT_KEYS}
    counts["total"] = len(items)
    for item in items:
        if item["status"] == "open":
            counts["open"] += 1
        if item["blocking_now"]:
            counts["blocking_now"] += 1
        if item["group"] in WANTS_YOU_GROUPS:
            counts["wants_you"] += 1
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
    """A doc with no items. WHY every count null and not 0: no items here means the questions could not be read (or
    the loop writes none), not that there are none; the page says "not reported" (truth rule: missing is never 0)."""
    return {
        "schema": SCHEMA, "track": track, "track_title": title, "generated_at": _now(), "iteration": None,
        "source": {"adapter": adapter, "paths": paths or [], "commit": None, "live": False, "note": note},
        "answer_channel": channel or {"kind": "none", "target": None, "row_schema": None, "read_back": None},
        "counts": {key: None for key in COUNT_KEYS}, "items": [],
    }


def build_kinsim(sources: Mapping[str, str], title: str = "kinsim") -> dict[str, Any]:
    loop_dir = resolve_loop_dir(sources, explicit_key="kinsim_triage_dir", branch_key="kinsim_loop_branch",
                                subdir="src/dev/bam_curriculum",
                                fallback_keys=("kinsim_loop_dir", "kinsim_curriculum_dir"))
    if loop_dir is None:
        return _empty_doc("kinsim", title, "triage.json not found: no worktree has the kinsim loop branch and "
                          "kinsim_curriculum_dir has no triage.json", adapter="bam_triage")
    home = Path(sources.get("kinsim_home") or "~/.local/share/bam_curriculum").expanduser()
    answers_path = home / "triage_answers.jsonl"
    channel = {"kind": "jsonl_append", "target": str(answers_path), "row_schema": ANSWER_SCHEMA,
               "read_back": "at the next wave start (integrator)",
               "alternatives": ["POST /api/triage/<id>/answer on the kinsim dashboard API",
                                "paste into the loop's chat"]}
    paths = [str(loop_dir / "triage.json"), str(home / "status.json"), str(home / "loop_events.jsonl"),
             str(answers_path)]
    triage, problem = read_triage(loop_dir / "triage.json")
    if triage is None:
        return _unreadable_triage_doc("kinsim", title, loop_dir / "triage.json", problem or "unknown", paths, channel)
    status_raw = _read_json(home / "status.json")
    status = status_raw if isinstance(status_raw, dict) else {}
    events = _read_jsonl(home / "loop_events.jsonl")
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
             for raw in triage["items"]]
    items.sort(key=_sort_key)
    note = (f"{triage.get('schema', '?')} read live; blocking per status.json: "
            f"{', '.join(status.get('blocking_triage') or []) or 'none'}" if isinstance(status_raw, dict) else
            f"{triage.get('schema', '?')} read live; status.json could not be read as an object, so the finished wave comes from "
            "loop_events.jsonl alone")
    return {
        "schema": SCHEMA, "track": "kinsim", "track_title": title, "generated_at": _now(),
        "iteration": {"unit": "wave", "n": status.get("wave"), "phase": status.get("phase"), "finished": finished},
        "source": {"adapter": "bam_triage", "paths": paths,
                   "commit": _git_last_commit(loop_dir, "triage.json"), "live": True, "note": note},
        "answer_channel": channel,
        "counts": _counts(items), "items": items,
    }


def build_rig(sources: Mapping[str, str], title: str = "rig") -> dict[str, Any]:
    loop_dir = resolve_loop_dir(sources, explicit_key="rig_loop_dir", branch_key="rig_loop_branch",
                                subdir="src/dev/bam_rig_loop")
    if loop_dir is None:
        return _empty_doc("rig", title, "triage.json not found in rig_loop_dir or the rig loop branch's worktree",
                          adapter="bam_triage")
    channel = {"kind": "chat_paste", "target": "the rig loop's integrator (/loop session)", "row_schema": None,
               "read_back": "by hand: the integrator quotes your words into the item and sets it answered"}
    paths = [str(loop_dir / "triage.json"), str(loop_dir / "loop-status.json"), str(loop_dir / "loop_events.jsonl")]
    triage, problem = read_triage(loop_dir / "triage.json")
    if triage is None:
        return _unreadable_triage_doc("rig", title, loop_dir / "triage.json", problem or "unknown", paths, channel)
    status_raw = _read_json(loop_dir / "loop-status.json")
    loop_status = status_raw if isinstance(status_raw, dict) else {}
    events = _read_jsonl(loop_dir / "loop_events.jsonl")
    tick = loop_status.get("tick") if isinstance(loop_status.get("tick"), dict) else {}
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
             for raw in triage["items"]]
    items.sort(key=_sort_key)
    note = f"{triage.get('schema', '?')} read live; answers are folded into recommendation by the integrator"
    if not isinstance(status_raw, dict):
        note += "; loop-status.json could not be read, so the finished wave comes from loop_events.jsonl alone"
    return {
        "schema": SCHEMA, "track": "rig", "track_title": title, "generated_at": _now(),
        "iteration": {"unit": "wave", "n": tick.get("n"), "phase": tick.get("phase"), "finished": finished},
        "source": {"adapter": "bam_triage", "paths": paths,
                   "commit": _git_last_commit(loop_dir, "triage.json"), "live": True, "note": note},
        "answer_channel": channel,
        "counts": _counts(items), "items": items,
    }


# ------------------------------------------------------------------------------- the prose tracks (one parser each)

def _line_of(text: str, needle: str) -> int | None:
    """1-based line of the first occurrence of ``needle`` in ``text``; None when absent."""
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else None


def _file_line(path: str, line: int | None, label: str) -> dict[str, Any]:
    return {"label": label, "kind": "file_line" if line else "path", "value": f"{path}#L{line}" if line else path,
            "path": path, "target": _canonical(path), "line": line, "is_dir": False}


def _mtime_iso(path: str) -> str | None:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def _prose_item(track: str, local_id: str, *, kind: str, title: str, ask: str, context_md: str, base_md: str,
                question_md: str, default_md: str | None, applies_unit: str, blocks: list[dict[str, Any]],
                evidence: list[dict[str, Any]], asked_by: str, updated_ts: str | None,
                raw_status: str, leading_options: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """One NeedsItem from a file that keeps its questions as prose: every text field a verbatim slice of that file.

    ``blocking_now`` is computed, not passed: a prose item is always open with its default pending (or none), so it
    blocks exactly when it names a rung, package or gate (``holds_gate``); a cell-only item never does.
    """
    never = default_md is None
    blocking_now = holds_gate(blocks)
    lead, provenance = lead_and_provenance(question_md.strip())
    if blocking_now:
        group = "blocking"
    elif never:
        group = "no_default"
    else:
        group = "waiting"
    return {
        "id": f"{track}:{local_id}", "local_id": local_id, "kind": kind, "title": title, "ask": ask,
        "context_md": context_md, "context_summary": None, "context_base_md": base_md, "context_lead_md": lead,
        "provenance_md": provenance, "updates": [],
        "options": _synth_options("", default_md or "", never, leading_options),
        "recommendation_md": "",
        "default": {"text_md": default_md or "",
                    "applies": {"unit": "never", "after": None} if never else {"unit": applies_unit, "after": None},
                    "state": "none" if never else "pending"},
        "blocks": blocks, "blocking_now": blocking_now, "group": group, "evidence": evidence,
        "asked_by": {"agent": asked_by, "session": None, "account": None},
        "created": {"iteration": None, "ts": None}, "updated": {"ts": updated_ts, "note": None},
        "status": "open", "raw_status": raw_status, "answer": None, "effort": None,
    }


def build_grasping(sources: Mapping[str, str], title: str = "grasping") -> dict[str, Any]:
    """curriculum.py CELLS with status 'needs' whose ``why`` names a download approval: one item per model id.

    Parsed by the grasping adapter's own ``load_curriculum`` + ``needs_cells`` + ``approval_phrases`` (one parser, not
    two). The question is the model id plus the cells' own words for the ask ("M5.ggcnn · download approval"): CELLS
    carry a reason, never a question, and a framed question ("Approve downloading M5.ggcnn?") read as the loop's words.
    The model's title, licence and notes and every held cell's ``why`` go in the context verbatim. The answer options
    ("Approve the download", "Keep waiting", "Something else") are the dashboard's (``source: "dashboard"``); none is
    a recommendation, because the file records none.

    WHY no_default and not blocking: a download approval holds cells, never the rung. The adapter's frontier rule
    (``frontier_tier``: wave-1 cells and gates only) does not count a ``needs`` cell, so the loop climbs past it;
    the cells it holds are listed in ``blocks`` (kind ``cell``, which ``holds_gate`` never counts) so the page can
    still say what waits on it.
    """
    channel = CHANNELS["grasping"]
    path = sources.get("grasping_curriculum")
    if not path or not Path(path).is_file():
        return _empty_doc("grasping", title, f"curriculum.py not found ({path or 'grasping_curriculum is not a sources key'})",
                          paths=[path] if path else [], channel=channel, adapter="grasp_curriculum")
    try:
        curriculum = grasping_adapter.load_curriculum(path)
        text = Path(path).read_text(encoding="utf-8")
    except Exception as error:  # curriculum.py is executed; any error in it is a reason, not a crash
        return _empty_doc("grasping", title, f"curriculum.py could not be read · {type(error).__name__}: {error}",
                          paths=[path], channel=channel, adapter="grasp_curriculum")
    approvals, other = grasping_adapter.needs_cells(curriculum)
    updated = _mtime_iso(path)
    items = []
    for model_id, cells in approvals.items():
        model = curriculum.models.get(model_id)
        model_title = str(model.title) if model else model_id
        notes = str(getattr(model, "notes", "") or "") if model else ""
        by_reason: dict[str, list[str]] = {}
        for cell in cells:
            by_reason.setdefault(str(cell.why or ""), []).append(cell.id)
        fields = ([f"- Licence: {model.licence}"] if model is not None else []) + ([f"- Notes: {notes}"] if notes else [])
        held = [f"- {reason}: " + ", ".join(f"`{cell_id}`" for cell_id in ids) for reason, ids in by_reason.items()]
        context = "\n\n".join(part for part in (
            f"**{model_title}** (`{model_id}`)", "\n".join(fields),
            "Cells it holds, by curriculum.py's own reason:", "\n".join(held)) if part)
        blocks = []
        for cell in cells:
            env = curriculum.envs.get(cell.env)
            blocks.append({"id": cell.id, "kind": "cell",
                           "label": f"{env.title} · tier {env.tier}" if env is not None else None})
        line = _line_of(text, f'"{model_id}"')
        phrases = grasping_adapter.approval_phrases(cells)
        ask = f"{model_id} · {' / '.join(phrases)}" if phrases else model_id
        approve = {"key": "approve", "label": "Approve the download", "detail_md": None, "recommended": False,
                   "is_default": False}
        items.append(_prose_item(
            "grasping", model_id, kind="approval", title=model_title, ask=ask,
            context_md=context, base_md=context, question_md=notes, default_md=None, applies_unit="never",
            blocks=blocks, leading_options=[approve],
            evidence=[_file_line(path, line, f"curriculum.py MODELS {model_id}")],
            asked_by="grasping loop (curriculum.py CELLS)", updated_ts=updated, raw_status="needs"))
    held_elsewhere = sum(len(ids) for ids in other.values())
    return {
        "schema": SCHEMA, "track": "grasping", "track_title": title, "generated_at": _now(), "iteration": None,
        "source": {"adapter": "grasp_curriculum", "paths": [path],
                   "commit": _git_last_commit(Path(path).parent, Path(path).name), "live": True,
                   "note": "curriculum.py CELLS with status 'needs' whose why names a download approval, one item per "
                           "model id, read live with the grasping adapter's own parser. No default is recorded for "
                           "any, and download approvals hold only that model's cells; no tier gate waits on them. "
                           f"{held_elsewhere} other 'needs' cells wait on something other than you "
                           f"({'; '.join(other) or 'none'}) and are not asked here."},
        "answer_channel": channel,
        "counts": _counts(items), "items": items,
    }


def build_detection(sources: Mapping[str, str], title: str = "detection") -> dict[str, Any]:
    """The vault plan note's ``## Needs you`` list, parsed by the detection adapter's own ``parse_needs_section``.

    Every text field is the note's own words; ``blocks`` are the rungs the item says it blocks. The ask is the
    parser's ``ask_md``: the bold lead plus the first sentence (or bullet) after it, verbatim; the rest of the question
    is the lead context, and the whole item stays in ``context_md``. WHY ``applies.unit``
    is ``unstated`` and the state ``pending``: the note says each default "fires if you say nothing" but not when, and
    no loop is running to have applied one. A blocking item with a pending default still blocks (the triage rule).
    """
    channel = CHANNELS["detection"]
    path = sources.get("detection_plan_note")
    if not path or not Path(path).is_file():
        return _empty_doc("detection", title, f"plan note not found ({path or 'detection_plan_note is not a sources key'})",
                          paths=[path] if path else [], channel=channel, adapter="plan_note")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return _empty_doc("detection", title, f"plan note could not be read · {error}", paths=[path], channel=channel,
                          adapter="plan_note")
    entries = detection_adapter.parse_needs_section(text)
    if not entries:
        return _empty_doc("detection", title, "the plan note has no numbered '## Needs you' list", paths=[path],
                          channel=channel, adapter="plan_note")
    rung_titles: dict[str, str] = {}
    ladder = sources.get("detection_ladder")
    if ladder and Path(ladder).is_file():
        try:
            rung_titles = {row["id"]: str(row.get("short") or "") or None
                           for row in detection_adapter.read_ladder(Path(ladder)).get("rungs") or []}
        except Exception:  # labels are a nicety; a broken ladder file must not hide the questions
            rung_titles = {}
    roots = [Path(value) for key in ("detection_repo",) if (value := sources.get(key))]
    roots.append(Path(sources.get("bam_ws_root") or NEEDS_DEFAULTS["bam_ws_root"]))
    section = text.find("## Needs you")
    updated = _mtime_iso(path)
    items = []
    for entry in entries:
        blocks = [{"id": rung, "kind": "rung", "label": rung_titles.get(rung)} for rung in entry["blocks"]]
        start = text.find(f"\n{entry['n']}. ", section) if section >= 0 else -1
        line = text.count("\n", 0, start) + 2 if start >= 0 else None
        ask = entry["ask_md"]
        item_title = entry["title_md"] if entry["title_md"] is not None else ask
        items.append(_prose_item(
            "detection", f"plan-{entry['n']}", kind="decision", title=item_title, ask=ask,
            context_md=entry["body_md"], base_md=entry["before_md"].strip(), question_md=entry["ask_rest_md"] or "",
            default_md=entry["default_md"], applies_unit="unstated", blocks=blocks,
            # WHY drop device paths: item 1 names `/dev/sdb` in a command, which exists but is nothing to open.
            evidence=[_file_line(path, line, f"Plan note · Needs you · {entry['n']}")]
                     + [found for found in extract_evidence(entry["body_md"], roots)
                        if found["kind"] == "url" or Path(found["path"]).is_file() or Path(found["path"]).is_dir()],
            asked_by="plan note (vault)", updated_ts=updated, raw_status="open"))
    items.sort(key=_sort_key)
    return {
        "schema": SCHEMA, "track": "detection", "track_title": title, "generated_at": _now(), "iteration": None,
        "source": {"adapter": "plan_note", "paths": [path], "commit": _git_last_commit(Path(path).parent, Path(path).name),
                   "live": True,
                   "note": "The plan note's '## Needs you' list, read live with the detection adapter's own parser. "
                           "Plan only, no loop running: the note does not say when a default fires, and none has."},
        "answer_channel": channel,
        "counts": _counts(items), "items": items,
    }


# --------------------------------------------------------------------------------------------- tracks and the doc

BUILDERS = {"kinsim": build_kinsim, "rig": build_rig, "grasping": build_grasping, "detection": build_detection}


def registry_tracks(workspace: str | os.PathLike[str] | None = None) -> tuple[list[tuple[str, str]], str | None]:
    """``([(id, vibe-title), ...], problem)``: the registry's live (not archived) tracks in its row order.

    The workspace is ``workspace``, else ``$VIBETRACKS_WORKSPACE`` (the backend exports it), else this repo's
    ``workspace/``. WHY the registry and not a list here: a rename (POST /tracks/<id>/title) must show on the needs
    page too, and a hard-coded title went stale ("Sim to Real · 1-DOF rig"). When the registry cannot be read, the
    fallback ids come back with the id as their title, and ``problem`` says why.
    """
    root = workspace or os.environ.get("VIBETRACKS_WORKSPACE") or DEFAULT_WORKSPACE
    try:
        registry = read_registry(root)
    except (VibeTracksError, OSError, ValueError) as error:
        return [(track, track) for track in FALLBACK_TRACK_IDS], f"registry unreadable · {error}"
    return [(track.id, track.title) for track in registry.tracks if not track.archived], None


def build_track(track: str, sources: Mapping[str, str] | None = None, *, title: str | None = None,
                workspace: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """One track's doc; None for an id that is neither a registry track nor one this module has a source for.

    ``title`` (the registry's ``vibe-title``) skips the registry read; build.py passes it. A registry track with no
    question source gets a doc whose counts are all null ("not reported").
    """
    sources = sources if sources is not None else load_sources()
    if title is None:
        listed, _ = registry_tracks(workspace)
        titles = dict(listed)
        if track not in titles and track not in BUILDERS and track not in NOT_REPORTED:
            return None
        title = titles.get(track, track)
    builder = BUILDERS.get(track)
    if builder is not None:
        return bind_evidence(builder(sources, title))
    spec = NOT_REPORTED.get(track)
    if spec is not None:
        return bind_evidence(_empty_doc(track, title, spec["note"], paths=spec["paths"], channel=spec["channel"],
                                        adapter="none (prose only)"))
    return bind_evidence(_empty_doc(track, title, "needs.py has no question source for this track yet", adapter="none"))


# ------------------------------------------------------------------------------- evidence identity and revision

def _digest(value: Any, length: int) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def evidence_id(item_id: str, entry: Mapping[str, Any]) -> str:
    """A stable id for one evidence entry: a hash of the item id and the entry as written (kind, label, value).

    WHY never a list index (audit 2026-10-05, finding 1): an index names "whatever is n-th now", so reordering an
    item's evidence silently changed what an open link served. The canonical ``target`` is deliberately NOT part of
    the id: the id says which evidence was written; ``evidence_rev`` says what it resolved to when it was reviewed.
    """
    return _digest([item_id, entry.get("kind"), entry.get("label"), entry.get("value")], 16)


def evidence_revision(doc: Mapping[str, Any]) -> str:
    """A hash over every item's evidence entries in order, each with the canonical target recorded for it.

    It changes when an entry is added, removed, reordered or rewritten, or when a listed path now resolves to a
    different file (a symlink retargeted). Items are taken by id, not page order, so an item moving between groups
    (a default applying) does not invalidate links whose evidence did not change.
    """
    items = sorted((item for item in doc.get("items") or []), key=lambda item: str(item.get("id")))
    return _digest([[item.get("id"), [[entry.get("eid"), entry.get("kind"), entry.get("label"), entry.get("value"),
                                       entry.get("path"), entry.get("target"), entry.get("line"), entry.get("is_dir")]
                                      for entry in item.get("evidence") or []]] for item in items], 32)


def bind_evidence(doc: dict[str, Any]) -> dict[str, Any]:
    """Give each evidence entry its ``eid`` and the doc its ``evidence_rev``; the /needs/evidence URL carries both."""
    for item in doc.get("items") or []:
        for entry in item.get("evidence") or []:
            entry["eid"] = evidence_id(str(item.get("id")), entry)
    doc["evidence_rev"] = evidence_revision(doc)
    return doc


def build_all(sources: Mapping[str, str] | None = None,
              workspace: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    sources = sources if sources is not None else load_sources()
    listed, problem = registry_tracks(workspace)
    docs = [doc for track, title in listed if (doc := build_track(track, sources, title=title)) is not None]
    return {"schema": SCHEMA_ALL, "generated_at": _now(), "tracks": docs, "registry_problem": problem}


# ------------------------------------------------------------------------------ what the dashboard projection shows

def needs_you_count(doc: Mapping[str, Any] | None) -> dict[str, int | None]:
    """The projection's ``needs_you_count``: ``{"open": counts.wants_you, "blocking": counts.blocking_now}``.

    Both null when there is no doc or its counts are null (no structured source): "not reported", never 0.
    """
    counts = (doc or {}).get("counts") or {}
    return {"open": counts.get("wants_you"), "blocking": counts.get("blocking_now")}


def _applies_text(item: Mapping[str, Any]) -> str | None:
    applies = item["default"]["applies"]
    unit, after = applies.get("unit"), applies.get("after")
    if unit == "never":
        return None
    if unit == "unstated":
        return "not stated"
    when = f"after W{after}" if unit == "wave" and isinstance(after, int) else f"after {unit} {after}"
    return f"{when} · in force" if item["default"]["state"] == "in_effect" else when


def needs_you_rows(doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The projection's ``needs_you`` list: the doc's items in the wants-you groups, in the doc's order, as
    ``{id, q, blocks, default, applies}`` (PROJECTION.md ``NeedsYou``). ``id`` is the loop's own id (T47, M5.ggcnn)."""
    rows = []
    for item in (doc or {}).get("items") or []:
        if item.get("group") not in WANTS_YOU_GROUPS:
            continue
        rows.append({"id": item["local_id"], "q": item.get("ask") or item.get("title") or "",
                     "blocks": [block["id"] for block in item.get("blocks") or []],
                     "default": item["default"].get("text_md") or None, "applies": _applies_text(item)})
    return rows


# ------------------------------------------------------------------------------------------------------------ route

def _json(status: int, body: Any) -> tuple[int, dict[str, str], list[bytes]]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}, [payload]


def _first(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def _stream(handle: Any, chunk: int = 256 * 1024) -> Iterable[bytes]:
    with handle:
        while True:
            data = handle.read(chunk)
            if not data:
                return
            yield data


def serve_evidence(entry: Mapping[str, Any]) -> tuple[int, dict[str, str], Iterable[bytes]]:
    """Stream the file recorded for one evidence entry, or refuse it.

    404 when the entry names no absolute path or recorded no canonical ``target`` (it did not resolve, or names a
    directory), or that file is gone; 415 when the listed path's suffix is not served; 403 when the recorded target's
    own suffix is not served, or when a symlink now sits at ANY component of the target (``open_no_symlinks``).

    WHY open the recorded target and never the listed alias: the target is what the reviewed document resolved the
    path to (``realpath`` at build time, so it holds no symlink); a link swapped in anywhere on its path since then
    is a substitution and fails to open instead of being followed.
    """
    path = Path(entry.get("path") or "")
    if not entry.get("path") or not path.is_absolute() or ".." in path.parts or entry.get("is_dir"):
        return _json(404, {"error": "evidence is not a servable file", "path": entry.get("path")})
    if SERVABLE.get(path.suffix.lower()) is None:
        return _json(415, {"error": f"{path.suffix or 'no suffix'} is not served", "path": str(path)})
    recorded = entry.get("target")
    if not isinstance(recorded, str) or not recorded:
        return _json(404, {"error": "evidence did not resolve to a file when it was listed", "path": str(path)})
    content_type = SERVABLE.get(Path(recorded).suffix.lower())
    if content_type is None:
        return _json(403, {"error": f"the evidence path resolves to a {Path(recorded).suffix or 'suffix-less'} file, "
                                    "which is not served", "path": str(path)})
    try:
        fd = open_no_symlinks(recorded)
    except UnsafePath:
        return _json(403, {"error": "the evidence file changed while it was being opened", "path": str(path)})
    except FileNotFoundError:
        return _json(404, {"error": "the evidence file is gone", "path": str(path)})
    except OSError as error:
        return _json(403, {"error": f"the evidence file could not be opened: {error.strerror}", "path": str(path)})
    handle = os.fdopen(fd, "rb")
    info = os.fstat(fd)
    if info.st_size > MAX_EVIDENCE_BYTES:
        handle.close()
        return _json(413, {"error": "file too large to serve here", "path": str(path), "bytes": info.st_size})
    return 200, {"Content-Type": content_type, "Content-Length": str(info.st_size)}, _stream(handle)


def handle(method: str, subpath: str, query: Mapping[str, list[str]], headers: Mapping[str, str],
           sources: Mapping[str, str] | None = None, workspace: str | os.PathLike[str] | None = None):
    if method != "GET":
        return _json(405, {"error": "GET only"})
    subpath = subpath.rstrip("/")
    track = _first(query, "track")
    if subpath == "":
        if not track:
            return _json(200, build_all(sources, workspace))
        doc = build_track(track, sources, workspace=workspace)
        return _json(200, doc) if doc is not None else _json(404, {"error": f"unknown track {track!r}",
                                                                   "tracks": [t for t, _ in registry_tracks(workspace)[0]]})
    if subpath == "/evidence":
        item_id, eid, rev = _first(query, "item"), _first(query, "eid"), _first(query, "rev")
        if not track or not item_id or not eid or not rev:
            return _json(400, {"error": "need track, item, eid and rev"})
        doc = build_track(track, sources, workspace=workspace)
        if doc is None:
            return _json(404, {"error": f"unknown track {track!r}"})
        # WHY a revision check before anything is looked up (audit 2026-10-05, finding 1): the link was approved
        # against the document Zach was shown. If any evidence entry, its order or the file it resolves to changed
        # since, this rebuilt document is not that one, and serving from it would re-authorize a substituted target.
        # No current revision in the answer: the page must reload what it shows, never retry silently.
        if doc.get("evidence_rev") != rev:
            return _json(409, {"error": "the document changed; reload"})
        local = item_id.split(":", 1)[-1]
        item = next((it for it in doc["items"] if it["local_id"] == local), None)
        entry = next((found for found in (item or {}).get("evidence") or [] if found.get("eid") == eid), None)
        if entry is None:
            return _json(404, {"error": "no such evidence entry"})
        # WHY serve only what this module extracted from the item's own text: the route must not become a way to
        # read any file on the machine by naming it; the evidence list is the allowlist, and the entry's recorded
        # canonical target (bound into the revision just checked) is the one file it may serve.
        return serve_evidence(entry)
    return _json(404, {"error": f"no route {subpath!r} under /needs"})


if __name__ == "__main__":  # python3 -m vibetracks.dashboard.needs [track] -> the JSON on stdout
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(build_track(target) if target else build_all(), indent=1, ensure_ascii=False))
