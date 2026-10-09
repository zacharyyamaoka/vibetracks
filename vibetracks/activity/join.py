"""Which track a session belongs to, and how that was decided (``join.by``) — the crux of derived state.

A track's note declares the harness fields that mark its sessions:

    vibe-sessions:
      branches: [claude/rig-loop-work-continue-*]   # fnmatch on the transcript's own gitBranch
      cwds: [/home/bam/pyblocks]                    # a path prefix of the session's cwd (a glob: its dir pattern)
      titles: [traj tracking, sim to real]          # case-insensitive substring of the session's title

Precedence: any branch rule, then any cwd rule (the longest prefix wins), then any title rule; within a kind, the
first track in registry order. A subagent's transcript belongs to its parent session (``join.by: parent`` on the
file), never to the track its own branch would match. A session no rule matches goes to "Other sessions": it is
always shown, never dropped.

WHY branch first and title last: the branch is written by the harness on every line; a title is typed by a person
and drifts ("Traj tracking" vs "Traj Tracking"), so it is the weakest rule and the page says so.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable

RULE_KINDS = (("branch", "branches"), ("cwd", "cwds"), ("title", "titles"))


@dataclass
class SessionRules:
    track: str
    branches: list[str] = field(default_factory=list)
    cwds: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.branches or self.cwds or self.titles)


def parse_rules(track: str, value: Any) -> SessionRules:
    """``vibe-sessions`` as written; anything malformed is named in ``problems`` and ignored, never guessed."""

    rules = SessionRules(track)
    if value is None:
        return rules
    if not isinstance(value, dict):
        rules.problems.append("vibe-sessions must be a mapping of branches / cwds / titles")
        return rules
    for _by, key in RULE_KINDS:
        raw = value.get(key)
        if raw is None:
            continue
        items = [raw] if isinstance(raw, str) else raw
        if not isinstance(items, list):
            rules.problems.append(f"vibe-sessions.{key} must be a list of strings")
            continue
        clean = [str(item).strip() for item in items if isinstance(item, (str, int, float)) and str(item).strip()]
        if key == "cwds":
            clean = [item.rstrip("/") or "/" for item in clean]
        setattr(rules, key, clean)
    unknown = sorted(set(value) - {key for _by, key in RULE_KINDS})
    if unknown:
        rules.problems.append(f"vibe-sessions keys {unknown} are not branches / cwds / titles; ignored")
    return rules


def _under(cwd: str, prefix: str) -> bool:
    """``cwd`` is ``prefix`` or below it. A prefix with a glob character (``/home/bam/vibetracks*``) is a pattern
    for the directory, so every sibling checkout of a repo matches with one rule."""

    if any(ch in prefix for ch in "*?["):
        return fnmatch.fnmatchcase(cwd, prefix) or fnmatch.fnmatchcase(cwd, prefix.rstrip("/") + "/*")
    return cwd == prefix or cwd.startswith(prefix.rstrip("/") + "/")


def match(rules: Iterable[SessionRules], *, branch: str | None, cwd: str | None, title: str | None) -> tuple[str | None, dict[str, Any]]:
    """``(track id or None, {"by": "branch"|"cwd"|"title"|None, "value": the rule that matched})``."""

    rules = list(rules)
    if branch:
        for rule in rules:
            for pattern in rule.branches:
                if fnmatch.fnmatchcase(branch, pattern):
                    return rule.track, {"by": "branch", "value": pattern}
    if cwd:
        best: tuple[int, str, str] | None = None
        for rule in rules:
            for prefix in rule.cwds:
                if _under(cwd, prefix) and (best is None or len(prefix) > best[0]):
                    best = (len(prefix), rule.track, prefix)
        if best is not None:
            return best[1], {"by": "cwd", "value": best[2]}
    if title:
        folded = title.casefold()
        for rule in rules:
            for needle in rule.titles:
                if needle.casefold() in folded:
                    return rule.track, {"by": "title", "value": needle}
    return None, {"by": None, "value": None}
