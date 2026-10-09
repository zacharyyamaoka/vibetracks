"""The rules that turn harness facts into a track's state word, health and worked time (docs/peps/0001).

Rule order (the accepted mock's, Oct 6, as the 2026-10-09 integration report states it); the first that holds wins:

1. **done / archived**: a person's verdict in the note (``vibe-status``). The only claim the home believes.
2. **needs_you**: a live session is waiting, OR a transcript holds an unanswered AskUserQuestion, OR the loop's triage
   file wants an answer (needs.py's ``wants_you`` > 0). WHY first: an open question outranks a newer action; the
   agent may well keep working around it, and the person is still the blocker.
3. **error**: the track's newest agent entry is an API error (rate limit, auth, overload, prompt too long), OR its
   adapter cannot read its files (``reporting: false`` in the projection).
4. **stale**: no agent entry and no loop write for longer than the track's stall rule (``vibe-stall-hours``, 24 h).
5. **working**: a live session is busy, OR the newest agent entry is at most 15 minutes old.
6. **idle**: otherwise.

Health: red for error or stale, yellow for needs_you, green for working or idle, none for done or archived.

Worked: the gaps of at most 15 minutes between consecutive agent entries, over the union of every session and
subagent of the track, so overlapping agents count once (elapsed time, not agent-hours).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

GAP_S = 15 * 60
WORDS = ("needs_you", "error", "stale", "working", "idle", "done", "archived")
LABELS = {"needs_you": "Needs you", "error": "Error", "stale": "Stale", "working": "Working", "idle": "Idle",
          "done": "Done", "archived": "Archived"}
HEALTH = {"needs_you": "yellow", "error": "red", "stale": "red", "working": "green", "idle": "green",
          "done": "none", "archived": "none"}
ERROR_KINDS = {"rate_limit": "rate limit", "authentication_failed": "not signed in", "server_error": "API overloaded",
               "invalid_request": "invalid request", "unknown": "API error"}

_RESET = re.compile(
    r"resets\s+(?:(?P<mon>[A-Z][a-z]{2})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*"
    r"(?P<ampm>am|pm)\s*(?:\((?P<tz>[A-Za-z_]+/[A-Za-z_/]+)\))?", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_reset(text: str, at: float) -> str | None:
    """The reset time a usage-limit card names, as ISO 8601 with its offset, or None when it names none.

    ``"... resets 5:20pm (America/Vancouver)"`` is the next 17:20 in that zone at or after ``at`` (the card's own
    timestamp); ``"... resets Oct 11, 9pm (America/Vancouver)"`` is that date, in the card's year (the next year when
    that date already passed by more than a day).
    """

    match = _RESET.search(text or "")
    if not match:
        return None
    zone = None
    if match.group("tz") and ZoneInfo is not None:
        try:
            zone = ZoneInfo(match.group("tz"))
        except (ZoneInfoNotFoundError, ValueError):
            zone = None
    base = datetime.fromtimestamp(at, zone) if zone else datetime.fromtimestamp(at).astimezone()
    hour = int(match.group("h")) % 12 + (12 if match.group("ampm").lower() == "pm" else 0)
    minute = int(match.group("m") or 0)
    if match.group("mon"):
        month = _MONTHS.get(match.group("mon").lower()[:3])
        if month is None:
            return None
        when = base.replace(month=month, day=int(match.group("day")), hour=hour, minute=minute, second=0, microsecond=0)
        if when < base - timedelta(days=1):
            when = when.replace(year=when.year + 1)
    else:
        when = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when < base:
            when += timedelta(days=1)
    return when.isoformat(timespec="seconds")


def worked_seconds(times: Iterable[float], since: float, until: float | None = None) -> int:
    """Sum of the gaps of at most ``GAP_S`` between consecutive entries at or after ``since`` (duplicates merged)."""

    ordered = sorted({t for t in times if t >= since and (until is None or t <= until)})
    return int(sum(b - a for a, b in zip(ordered, ordered[1:]) if b - a <= GAP_S))


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h {minutes % 60:02d} min" if hours < 10 else f"{hours} h"
    return f"{hours / 24:.1f} d"


def fmt_local(epoch: float) -> str:
    when = datetime.fromtimestamp(epoch).astimezone()
    return when.strftime("%a %H:%M %Z").strip()


@dataclass
class Facts:
    """Everything the rule order looks at for one track. All of it observed; ``None`` means not observed."""

    now: float
    person_status: str | None = None
    stall_hours: float = 24.0
    waiting: list[tuple[str, str | None]] = field(default_factory=list)   # (session title, waitingFor)
    busy: int = 0
    open_questions: list[tuple[float, str]] = field(default_factory=list)  # (asked at, question)
    triage_open: int | None = None
    triage_blocking: int | None = None
    last_agent: tuple[float, str, str] | None = None                        # (ts, type, body)
    last_error: tuple[float, str, str, float | None] | None = None          # (ts, kind, text, resets)
    not_reporting: str | None = None
    last_loop_write: float | None = None


def track_state(facts: Facts) -> dict[str, str]:
    """``{"word", "label", "rule", "why"}`` by the rule order above."""

    def out(word: str, rule: str, why: str) -> dict[str, str]:
        return {"word": word, "label": LABELS[word], "rule": rule, "why": why}

    now = facts.now
    if facts.person_status in ("done", "archived"):
        return out(facts.person_status, "person", f"marked {facts.person_status} in the note (vibe-status)")

    reasons: list[str] = []
    rules: list[str] = []
    if facts.waiting:
        detail = ", ".join(sorted({w or "input" for _t, w in facts.waiting}))
        count = len(facts.waiting)
        reasons.append(f"{count} live session{'s' if count > 1 else ''} waiting ({detail})")
        rules.append("waiting")
    if facts.open_questions:
        asked, question = max(facts.open_questions)
        more = len(facts.open_questions) - 1
        reasons.append(f"unanswered question “{question}” ({fmt_duration(now - asked)} ago)"
                       + (f" and {more} more" if more else ""))
        rules.append("open_question")
    if facts.triage_open:
        reasons.append(f"loop triage: {facts.triage_blocking or 0} blocking · {facts.triage_open} open")
        rules.append("triage")
    if reasons:
        return out("needs_you", "+".join(rules), " · ".join(reasons))

    if facts.last_agent is not None and facts.last_agent[1] == "error" and facts.last_error is not None:
        when, kind, text, resets = facts.last_error
        why = f"last agent entry is an error, {fmt_duration(now - when)} ago · {ERROR_KINDS.get(kind, kind.replace('_', ' '))}"
        if text:
            why += f": {text}"
        if resets is not None:
            when_text = fmt_local(resets) + (", passed; not resumed since" if resets < now else "")
            why += f" ({when_text})" if "resets" in (text or "") else f" · resets {when_text}"
        return out("error", "error_entry", why)
    if facts.not_reporting:
        return out("error", "not_reporting", facts.not_reporting)

    newest = max([t for t in (facts.last_agent[0] if facts.last_agent else None, facts.last_loop_write) if t is not None],
                 default=None)
    stall_s = facts.stall_hours * 3600
    if newest is None:
        return out("stale", "stale", f"no agent entry in 7 d and no loop write observed (stall rule {facts.stall_hours:g} h)")
    if now - newest > stall_s:
        return out("stale", "stale", f"no agent entry or loop write for {fmt_duration(now - newest)} "
                                     f"(stall rule {facts.stall_hours:g} h)")
    if facts.busy:
        return out("working", "busy", f"{facts.busy} live session{'s' if facts.busy > 1 else ''} busy")
    if facts.last_agent is not None and now - facts.last_agent[0] <= GAP_S:
        return out("working", "recent", f"last {facts.last_agent[1]} {fmt_duration(now - facts.last_agent[0])} ago")
    if facts.last_agent is not None:
        return out("idle", "idle", f"last agent entry {fmt_duration(now - facts.last_agent[0])} ago · nothing open")
    return out("idle", "idle", f"no agent entry in 7 d; last loop write {fmt_duration(now - newest)} ago · nothing open")


def health_of(state: dict[str, str]) -> dict[str, str]:
    color = HEALTH[state["word"]]
    rule = {"red": f"red: {state['label'].lower()}", "yellow": "yellow: waiting on you", "green": "green: moving or idle, nothing open",
            "none": f"none: {state['label'].lower()}"}[color]
    return {"color": color, "rule": rule}
