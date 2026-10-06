"""The one evaluator every projection uses, and the validator re-runs by projecting again (Codex F01, F09, G01).

What one piece of evidence can earn, from strongest to weakest:

- ``record``: the artifact states the result and what it covers (every JUnit case of the file, a
  ledger row consistent with itself, its batch and its run manifest, an audit's verdict line, a gate
  report whose every record agrees), and a record the run itself wrote binds it to its commit and a
  clean tree: a log's own ``HEAD <sha>;`` line, a run manifest's or ledger row's ``git``, a gate
  report's ``git``, an audit's own ``candidate <sha>`` line;
- ``log``: the same binding, but the result is a log's own per-test record of the whole file;
- ``claim``: the loop's word: a sentence, a log that never shows the whole file run, a run on a dirty
  or unrecorded tree, or a commit that only an agent's event, a file time or git's reflog would
  give (Codex F04, G04, H02).

Verdicts: a failing result is ``unmet``; no readable result, required tests that never ran, were
skipped or cannot be shown collected (Codex F06, G06, H05) is ``unknown``; evidence at a commit outside
the head's history, or with its scope, its ruler or its run's recorded inputs changed since (Codex F08,
H04), is ``stale``; else ``met``.
"""

from __future__ import annotations

import ast
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from . import artifacts, links, model
from .files import canonical_sha256, read_json_quiet
from .gitinfo import Repo
from .links import Roots

RATE_TOLERANCE = 1e-12
_HEAD_LINE = re.compile(r"^HEAD ([0-9a-f]{7,40})(?P<dirty>\s*\+[^;]*)?;")
_AUDIT_COMMIT = (re.compile(r"\bcandidate `([0-9a-f]{7,40})`"), re.compile(r"\bfound at `([0-9a-f]{7,40})`"),
                 re.compile(r"\breviewed commit `?([0-9a-f]{7,40})"))
_CLAIMED_PASS = re.compile(r"\b(\d+) passed\b|->\s*(\d+)/(\d+)\b|\b(\d+)/(\d+) checks\b|\bPASS\b")
_CLAIMED_FAIL = re.compile(r"\b(\d+) failed\b|\b(\d+) errors?\b|\bFAIL\b|\bexit [1-9]")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
# The strongest evidence each way of knowing the commit allows. WHY no time-based entry (Codex H02): a file's mtime
# or git's reflog places a checkout, not the bytes of an artifact; a copy of an old report would bind to a new HEAD.
STRENGTH_CAP = {"artifact": "record", "artifact-dirty": "claim", "citation": "claim", None: "claim"}


@dataclass
class Judgement:
    """What one target's evidence earns now."""

    verdict: str
    strength: str | None
    changed_since: list[str] = field(default_factory=list)
    note: str = ""
    result: str | None = None
    commit: str | None = None
    placed: bool = False  # the commit is the head or an ancestor of it


@dataclass
class Binding:
    """The commit a piece of evidence ran at, and what says so (``commit_source``)."""

    commit: str | None
    source: str | None
    note: str = ""


def capped(strength: str | None, source: str | None) -> str | None:
    if strength is None:
        return None
    cap = STRENGTH_CAP.get(source, "claim")
    return max(strength, cap, key=model.STRENGTHS.index)


def claimed_result(clause: str) -> tuple[str | None, str]:
    """What a sentence *says* happened (only ever a claim): (result, the words)."""

    failed = _CLAIMED_FAIL.search(clause)
    if failed and not re.search(r"\b0 failed\b", clause):
        return "failed", failed.group(0)
    passed = _CLAIMED_PASS.search(clause)
    if passed:
        return "passed", passed.group(0).lstrip("-> ").strip()
    return None, ""


def artifact_commit(path: Path) -> tuple[str | None, bool]:
    """``(commit, dirty)`` a log records about itself (a ``HEAD <sha>[ + dirty];`` header), or ``(None, False)``."""

    text = artifacts.whole_text(path)
    if text is None:
        return None, False
    for line in text.splitlines()[:5]:
        match = _HEAD_LINE.match(line.strip())
        if match:
            return match.group(1), bool(match.group("dirty"))
    return None, False


def audit_commit(path: Path) -> str | None:
    """The commit an audit report says it reviewed (``candidate `<sha>```, ``found at `<sha>```), or None."""

    text = artifacts.whole_text(path)
    if text is None:
        return None
    for pattern in _AUDIT_COMMIT:
        found = pattern.findall(text)
        if found:
            return found[-1]
    return None


def git_record_binding(git: Any, what: str) -> Binding:
    """A run's own ``git`` record, ``{"sha", "dirty"}`` (a run manifest, a ledger row, a gate report): commit and tree."""

    if not isinstance(git, Mapping) or not isinstance(git.get("sha"), str) or not _SHA.match(git["sha"]):
        return Binding(None, None, f"{what} records no commit of its own")
    if git.get("dirty") is False:
        return Binding(git["sha"], "artifact", "")
    why = "says its tree had uncommitted changes" if git.get("dirty") is True else "does not record whether its tree was clean"
    return Binding(git["sha"], "artifact-dirty", f"{what} {why}")


def report_binding(path: Path, report: Mapping[str, Any] | None = None) -> Binding:
    """A gate report's commit, from the report's own ``git`` record (commit and tree), and nothing else (Codex H02)."""

    report = report if report is not None else artifacts.read_gate_report(path)
    if report is None:
        return Binding(None, None, "the report does not open")
    return git_record_binding(report.get("git"), "the gate report")


def bind(kind: str | None, path: Path | None, cited: str | None) -> Binding:
    """Where an artifact ran, from a record the run itself wrote, else the event's word (Codex G04, H02)."""

    if path is not None and path.is_file():
        if kind == "log":
            head, dirty = artifact_commit(path)
            if head:
                return Binding(head, "artifact-dirty" if dirty else "artifact",
                               "the log's own header says the tree had uncommitted changes" if dirty else "")
            pointer = artifacts.read_log(path).pointer
            if pointer and Path(pointer).is_file():
                bound = report_binding(Path(pointer))
                if bound.commit:
                    return bound
        elif kind == "gate_report":
            bound = report_binding(path)
            if bound.commit:
                return bound
        elif kind == "audit":
            reviewed = audit_commit(path)
            if reviewed:
                return Binding(reviewed, "artifact", "")
    if cited:
        return Binding(cited, "citation", "no record the run wrote binds it to a commit; only the loop's event names one")
    return Binding(None, None, "no record the run wrote binds it to a commit")


@lru_cache(maxsize=1024)
def _functions_in_source(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ()
    keys = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            keys.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            keys += [f"{node.name}::{child.name}" for child in node.body
                     if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")]
    return tuple(keys)


def _parametrize_count(decorators: Sequence[ast.expr]) -> int | None:
    """Cases the literal ``parametrize`` decorators generate (their product); None when any list is not a literal."""

    total = 1
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func.attr if isinstance(decorator.func, ast.Attribute) else getattr(decorator.func, "id", "")
        if name != "parametrize":
            continue
        values = decorator.args[1] if len(decorator.args) > 1 else next(
            (keyword.value for keyword in decorator.keywords if keyword.arg == "argvalues"), None)
        if not isinstance(values, (ast.List, ast.Tuple)):
            return None
        total *= len(values.elts)
    return total


@lru_cache(maxsize=1024)
def declared_case_counts(source: str) -> tuple[tuple[str, int], ...]:
    """``(function key, cases)`` for test functions whose parameters are literal lists in the source (Codex G06).

    Only what the source spells out: a list built at import time, or a parametrized fixture, is counted by
    the recorded collection instead.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ()
    counts = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            cases = _parametrize_count(node.decorator_list)
            if cases is not None and cases != 1:
                counts.append((node.name, cases))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            outer = _parametrize_count(node.decorator_list)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                    inner = _parametrize_count(child.decorator_list)
                    if outer is not None and inner is not None and outer * inner != 1:
                        counts.append((f"{node.name}::{child.name}", outer * inner))
    return tuple(counts)


def _literal_id(node: ast.expr) -> str | None:
    """pytest's id for one literal parameter value (str, int, float, bool, None), or None when it is not that simple."""

    if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, int, float, bool, type(None))):
        return None
    value = node.value
    if isinstance(value, str):
        if not value or not value.isascii() or not value.isprintable() or "[" in value or "]" in value:
            return None
        return value
    return str(value)


@lru_cache(maxsize=1024)
def declared_case_ids(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``(function key, its case ids)`` where one ``parametrize`` over literal values lets pytest's ids be read off the
    source (Codex H05): ``["a", "b"]`` gives ``test_x[a]`` and ``test_x[b]``. Anything else (``ids=``, ``pytest.param``,
    stacked or class-level parametrize, non-literal values) is left to the case count and the recorded collection.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ()
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
            continue
        decorators = [decorator for decorator in node.decorator_list if isinstance(decorator, ast.Call) and
                      (decorator.func.attr if isinstance(decorator.func, ast.Attribute) else getattr(decorator.func, "id", "")) == "parametrize"]
        if len(decorators) != 1 or decorators[0].keywords or len(decorators[0].args) != 2:
            continue
        names, values = decorators[0].args
        if isinstance(names, ast.Constant) and isinstance(names.value, str):
            arity = len([name for name in names.value.split(",") if name.strip()])
        elif isinstance(names, (ast.List, ast.Tuple)):
            arity = len(names.elts)
        else:
            continue
        if not isinstance(values, (ast.List, ast.Tuple)):
            continue
        ids = []
        for value in values.elts:
            parts = [value] if arity == 1 else (value.elts if isinstance(value, (ast.List, ast.Tuple)) and len(value.elts) == arity else None)
            part_ids = [_literal_id(part) for part in parts] if parts is not None else [None]
            if any(part is None for part in part_ids):
                ids = None
                break
            ids.append("-".join(part_ids))
        if ids and len(set(ids)) == len(ids):
            found.append((node.name, tuple(ids)))
    return tuple(found)


def coverage_shortfall(source: str | None, items: int, node_ids: Sequence[str]) -> str | None:
    """Why a log's per-test record does not cover every test the file's source declares, or None (Codex H01).

    ``node_ids`` (a ``-v`` record) are checked by name, function by function and, where the source spells its
    parameters out, case by case; progress marks only by count, at least one per test function.
    """

    if source is None:
        return None
    functions = _functions_in_source(source)
    counts = dict(declared_case_counts(source))
    if node_ids:
        shown = {node.split("::", 1)[1] for node in node_ids if "::" in node}
        present = {key.split("[", 1)[0] for key in shown}
        missing = [key for key in functions if key not in present]
        if missing:
            return f"{len(missing)} of its test functions are not in the run's record ({', '.join(missing[:3])})"
        for key, ids in declared_case_ids(source):
            absent = [case for case in ids if f"{key}[{case}]" not in shown]
            if absent:
                return f"{key} declares cases {', '.join(absent[:3])} the run's record does not show"
        short = [key for key, cases in counts.items() if len({case for case in shown if case.split("[", 1)[0] == key}) < cases]
        if short:
            return f"fewer cases of {', '.join(short[:3])} are in the run's record than its source declares"
        return None
    minimum = sum(counts.get(key, 1) for key in functions)
    if items < minimum:
        return f"the run shows {items} outcome(s) for it; its source declares at least {minimum} test(s)"
    return None


def same_value(first: Any, second: Any) -> bool:
    """JSON values equal as values: 1 and 1.0 are one number, a bool is never a number, NaN equals nothing."""

    if isinstance(first, bool) or isinstance(second, bool):
        return first is second
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return float(first) == float(second)
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        return set(first) == set(second) and all(same_value(first[key], second[key]) for key in first)
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(same_value(left, right) for left, right in zip(first, second))
    return first == second


def input_changes(recorded: Any, wanted: Mapping[str, Any] | None) -> list[str]:
    """What the gate's corpus asks for now that the run did not run on (Codex H04): every field, as the manifest recorded it.

    WHY every field and not a chosen few: the run's manifest records the corpus definition it ran (producer corpus,
    slice start and count, seed, scenario, robot, timing, belt speed); a reading of one slice does not answer a gate
    that now names another, whichever field moved.
    """

    if wanted is None:
        return []
    if not isinstance(recorded, Mapping):
        return [f"the run's manifest records no corpus, the gate's corpus is {wanted.get('corpus_id')}"]
    changes = []
    for key in sorted(set(recorded) | set(wanted)):
        if not same_value(recorded.get(key), wanted.get(key)):
            changes.append(f"corpus {wanted.get('corpus_id')} {key}: the run recorded {json.dumps(recorded.get(key))}, "
                           f"the gate's corpus is now {json.dumps(wanted.get(key))}")
    return changes


class RulerAt:
    """The ruler a commit's curriculum named, as bam_eval's canonical sha256 (kinsim's ruler custody)."""

    def __init__(self, repo: Repo, curriculum_path: str) -> None:
        self.repo, self.curriculum_path = repo, curriculum_path
        self._cache: dict[str, str | None] = {}

    def sha_at(self, commit: str) -> str | None:
        if commit not in self._cache:
            self._cache[commit] = self._compute(commit)
        return self._cache[commit]

    def _compute(self, commit: str) -> str | None:
        text = self.repo.show(commit, self.curriculum_path)
        try:
            ruler = json.loads(text)["ruler"] if text else None
        except (ValueError, KeyError, TypeError):
            return None
        if not ruler:
            return None
        ruler_text = self.repo.show(commit, str(PurePosixPath(self.curriculum_path).parent / ruler))
        try:
            return canonical_sha256(json.loads(ruler_text)) if ruler_text else None
        except ValueError:
            return None


class Evaluator:
    """Judge evidence against the head of one checkout. Pure apart from reading files and asking git."""

    def __init__(self, repo: Repo, roots: Roots, *, ruler_at: RulerAt | None = None) -> None:
        self.repo, self.roots, self.ruler_at = repo, roots, ruler_at

    # ------------------------------------------------------------ files and commits
    def resolve(self, item: Mapping[str, Any] | None) -> Path | None:
        """The file a link names, from its ``path`` and ``base``."""

        if not item:
            return None
        path, base = item.get("path"), item.get("base")
        if not path:
            return None
        if base == "abs":
            return Path(path)
        root = {"repo": self.roots.repo, "data_home": self.roots.data_home}.get(base)
        return (root / path) if root is not None else None

    def place(self, commit: str | None) -> tuple[str | None, bool | None]:
        if not commit:
            return None, None
        full = self.repo.full_sha(commit)
        if full is None:
            return None, False
        return full, self.repo.in_history(full)

    def finish(self, result: str | None, ceiling: str, commit: str | None, scope: Sequence[str],
               context: Mapping[str, Any], *, notes: Iterable[str] = (), unproven: bool = False,
               context_value: str | None = None, source: str | None = "artifact", changes: Sequence[str] = ()) -> Judgement:
        """The shared tail every judge ends in: placement, freshness, verdict, strength (capped by how the commit is known)."""

        notes = [note for note in notes if note]
        strength = capped(ceiling, source)
        full, in_history = self.place(commit)
        if commit is None:
            strength = "claim"
            notes.append("no commit recorded, so it cannot be placed in this history")
        elif full is None:
            strength, in_history = "claim", False
            notes.append(f"commit {commit[:8]} is not in this repository")
        elif in_history is False:
            notes.append(f"commit {commit[:8]} is not in this history")
        elif in_history is None:
            # WHY (Codex F09): proof needs ancestry established positively; an unanswered question is not a yes.
            strength = "claim"
            notes.append(f"commit {commit[:8]} could not be placed against the head")
        changed = [*(self.repo.changed_since(full, tuple(scope)) if in_history else []), *changes]
        wanted = context.get("ruler_sha256") if isinstance(context, Mapping) else None
        if wanted and full:
            had = context_value if context_value is not None else (self.ruler_at.sha_at(full) if self.ruler_at else None)
            if had != wanted:
                changed = [*changed, f"ruler {str(had)[:12] if had else 'unknown'} at {full[:8]}, now {str(wanted)[:12]}"]
        verdict = model.target_verdict(result, in_history=in_history, changed_since=changed)
        if verdict in ("met", "stale") and unproven:
            verdict = "unknown"  # it did not prove the target even at its own commit
        strength_out = strength if verdict in ("met", "stale") else None
        if changed:
            notes.append(f"changed since: {changed[0]}" + (f" (+{len(changed) - 1})" if len(changed) > 1 else ""))
        return Judgement(verdict, strength_out, changed, "; ".join(notes), result, full or commit, placed=bool(in_history))

    # ------------------------------------------------------------ a test target
    def judge_test(self, item: Mapping[str, Any] | None, target: str, scope: Sequence[str], context: Mapping[str, Any],
                   *, via: Mapping[str, Any] | None = None) -> Judgement:
        """One piece of evidence for one test file (a JUnit record, a log, or a sentence)."""

        if item is None:
            return Judgement("unknown", None, [], "no recorded run")
        kind = item.get("kind")
        if kind == "statement":
            result, words = claimed_result(str((item.get("facts") or {}).get("text") or ""))
            return self.finish(result, "claim", item.get("commit"), scope, context,
                               notes=[f"claimed: {words}" if words else "a sentence"], source="citation")
        path = self.resolve(item)
        if path is None or not path.is_file():
            return Judgement("unknown", None, [], "its artifact does not open", None, item.get("commit"))
        if kind == "log":
            return self._judge_log(path, item, target, scope, context)
        if kind == "test":
            return self._judge_junit(item, target, scope, context, via)
        return Judgement("unknown", None, [], f"a {kind} cannot prove a test file", None, item.get("commit"))

    def _judge_log(self, path: Path, item: Mapping[str, Any], target: str, scope: Sequence[str], context: Mapping[str, Any]) -> Judgement:
        """A log proves a file only with its whole collection run and passed (Codex G05, H01), at a bound commit (G04, H02).

        ``log`` strength needs the run's own per-test record of the whole file (``artifacts.target_evidence``) that
        covers every test the file's source declares at the run's commit. What the log shows short of that keeps its
        word and no more: a green record whose command is not recorded, a green run that included the file without a
        per-file outcome, or a green log that never shows it, is a claim; a record of some of its tests, or one that
        contradicts its own summary, proves nothing about the file (unknown).
        """

        binding = bind("log", path, item.get("commit"))
        evidence = artifacts.target_evidence(path, target)
        notes = [binding.note]
        how = evidence.facts.get("evidence")
        if how == "none":
            if artifacts.read_log(path).result == "passed":
                notes.append("the log never shows this file run; only the loop's citation ties them")
                return self.finish("passed", "claim", binding.commit, scope, context, notes=notes, source=binding.source)
            notes.append("the log never shows this file run, and its own run is not green")
            return Judgement("unknown", None, [], "; ".join(note for note in notes if note), None, binding.commit)
        notes.append(f"read from {how}")
        notes += evidence.facts.get("notes") or []
        ceiling = evidence.facts.get("ceiling") or "log"
        unproven = False
        if evidence.result == "passed" and ceiling == "log":
            source = self.repo.show(binding.commit, target) if binding.commit else None
            if source is None:
                source = artifacts.whole_text(self.roots.repo / target)
            shortfall = coverage_shortfall(source, int(evidence.facts.get("items") or 0), evidence.facts.get("node_ids") or [])
            if shortfall:
                notes.append(shortfall)
                unproven = True
        return self.finish(evidence.result, ceiling, binding.commit, scope, context, notes=notes, source=binding.source,
                           unproven=unproven)

    def gate_run_binding(self, facts: Mapping[str, Any], cited: str | None) -> Binding:
        """A gate run's commit: its console log's HEAD line, else its report's own ``git`` record, else the event (Codex H02)."""

        console = facts.get("console")
        if isinstance(console, Mapping):
            path = self.resolve(console)
            if path is not None and path.is_file():
                head, dirty = artifact_commit(path)
                if head:
                    return Binding(head, "artifact-dirty" if dirty else "artifact",
                                   "the run's own header says the tree had uncommitted changes" if dirty else "")
        report = facts.get("report")
        if isinstance(report, str) and Path(report).is_file():
            bound = report_binding(Path(report))
            if bound.commit:
                return bound
        return bind(None, None, cited)

    def _judge_junit(self, item: Mapping[str, Any], target: str, scope: Sequence[str], context: Mapping[str, Any],
                     via: Mapping[str, Any] | None) -> Judgement:
        facts = item.get("facts") or {}
        junit = self.resolve(via) if via else None
        cases = artifacts.junit_cases(junit) if junit is not None else None
        if cases is None:
            return Judgement("unknown", None, [], "its JUnit file does not open", None, item.get("commit"))
        mine = junit_cases_for(cases, str(facts.get("suite_dir") or ""), target)
        binding = self.gate_run_binding(facts, item.get("commit"))
        notes = [binding.note]
        source = self.repo.show(binding.commit, target) if binding.commit else None
        functions = _functions_in_source(source) if source is not None else tuple(
            function.key for function in links.test_functions(self.roots.repo / target))
        ran = [_case_key(case) for case in mine]
        distinct = set(ran)  # WHY distinct (Codex H05): a repeated case is one test, never a parameter that did not run
        present = {key.split("[", 1)[0] for key in distinct}
        missing = sorted(key for key in functions if key not in present)
        if missing:
            notes.append(f"{len(missing)} of its test functions never ran in it ({', '.join(missing[:3])})")
        declared = dict(declared_case_counts(source)) if source is not None else {}
        short = sorted(key for key, cases_declared in declared.items() if key in present
                       and len({case_key for case_key in distinct if case_key.split("[", 1)[0] == key}) < cases_declared)
        for key, ids in declared_case_ids(source) if source is not None else ():
            if key in present and any(f"{key}[{case}]" not in distinct for case in ids) and key not in short:
                short.append(key)
        if short:
            notes.append(f"fewer cases ran than the source declares for {', '.join(sorted(short)[:3])}")
        repeated = len(ran) - len(distinct)
        if repeated and not any(case.outcome not in ("passed", "skipped") for case in mine):
            notes.append(f"its JUnit file lists {repeated} passing case(s) more than once")
        skipped = sorted(_case_key(case) for case in mine if case.outcome == "skipped")
        if skipped:
            notes.append(f"{len(skipped)} case(s) were skipped, which is not coverage")
        collection = self._collection(facts, cases, target)
        notes += collection.notes
        result = artifacts.junit_result(mine)
        unproven = bool(missing or short or skipped or not mine or not collection.complete
                        or (repeated and not any(case.outcome not in ("passed", "skipped") for case in mine)))
        return self.finish(result, "record", binding.commit, scope, context, notes=notes, unproven=unproven, source=binding.source)

    def _collection(self, facts: Mapping[str, Any], cases: Sequence[artifacts.JunitCase], target: str) -> artifacts.Collection:
        """The recorded collection of the suite the JUnit file came from (Codex G06); none recorded is not complete."""

        report_path, name = facts.get("report"), facts.get("suite")
        report = artifacts.read_gate_report(Path(report_path)) if isinstance(report_path, str) and report_path else None
        suite = next((entry for entry in (report or {}).get("suites") or [] if isinstance(entry, Mapping) and entry.get("suite") == name),
                     None)
        if suite is None:
            return artifacts.Collection(False, ["no recorded collection: the run's suite and log are not on record"])
        return artifacts.suite_collection(suite, cases, target)

    # ------------------------------------------------------------ a gate tier
    def judge_gate(self, item: Mapping[str, Any] | None, tier: str, scope: Sequence[str], context: Mapping[str, Any],
                   *, expected_suites: Sequence[str] | None = None,
                   tier_definition: Sequence[Mapping[str, Any]] | None = None) -> Judgement:
        if item is None:
            return Judgement("unknown", None, [], "no gate run recorded")
        kind = item.get("kind")
        if kind == "statement":
            result, _words = claimed_result(str((item.get("facts") or {}).get("text") or ""))
            return self.finish(result, "claim", item.get("commit"), scope, context, notes=["the gate_run event's own word"],
                               source="citation")
        path = self.resolve(item)
        if path is None or not path.is_file():
            return Judgement("unknown", None, [], "its artifact does not open", None, item.get("commit"))
        declared = tier_definition if tier_definition is not None else expected_suites
        if kind == "gate_report":
            report = artifacts.read_gate_report(path)
            if report is None:
                return Judgement("unknown", None, [], "not a bam-gate-report/1", None, item.get("commit"))
            binding = self.gate_run_binding({**(item.get("facts") or {}), "report": str(path)}, item.get("commit"))
            reading = artifacts.gate_report_reading(report, declared)
            notes = [binding.note]
            if reading.result is None:
                notes.append("the report cannot certify: " + (reading.facts.get("contradiction") or "it records nothing to check"))
            notes += [problem for problem in reading.facts.get("problems") or [] if problem not in (reading.facts.get("contradictions") or [])]
            return self.finish(reading.result, "record", binding.commit, scope, context, notes=notes, source=binding.source)
        if kind == "log":
            reading = artifacts.read_log(path)
            binding = bind("log", path, item.get("commit"))
            notes = [binding.note]
            if reading.facts.get("tier") != tier:
                notes.append(f"the log has no GATE line for the {tier} tier")
                return self.finish(reading.result, "claim", binding.commit, scope, context, notes=notes, source=binding.source)
            report = artifacts.read_gate_report(Path(reading.pointer)) if reading.pointer and Path(reading.pointer).is_file() else None
            if report is None:
                # WHY (Codex F07, H03): "GATE PASS" is the gate's own summary of itself; only the report it names, with
                # every record agreeing, can certify what ran.
                notes.append("the report its GATE line names does not open, so the line is the gate's own word")
                return self.finish(reading.result, "claim", binding.commit, scope, context, notes=notes, source=binding.source)
            checked = artifacts.gate_report_reading(report, declared)
            if checked.result is None:
                notes.append("the report it names cannot certify: " + (checked.facts.get("contradiction") or ""))
            notes += [problem for problem in checked.facts.get("problems") or [] if problem not in (checked.facts.get("contradictions") or [])]
            result = "failed" if "failed" in (reading.result, checked.result) else checked.result
            # The log points at the record; the record is the report, judged as its own candidate at record strength.
            return self.finish(result, "log", binding.commit, scope, context, notes=notes, source=binding.source)
        return Judgement("unknown", None, [], f"a {kind} cannot prove a gate run", None, item.get("commit"))

    # ------------------------------------------------------------ an audit report
    def judge_audit(self, item: Mapping[str, Any] | None, scope: Sequence[str], context: Mapping[str, Any]) -> Judgement:
        """An audit report's verdict line, at the commit the report itself says it reviewed (else only a claim)."""

        if item is None:
            return Judgement("unknown", None, [], "no audit report cited")
        path = self.resolve(item)
        if item.get("kind") != "audit" or path is None or not path.is_file():
            return Judgement("unknown", None, [], "no audit report opens", None, item.get("commit"))
        reading = artifacts.read_audit(path)
        binding = bind("audit", path, item.get("commit"))
        notes = [f"VERDICT {reading.facts.get('verdict')}" if reading.result else "the report states no verdict", binding.note]
        return self.finish(reading.result, "record", binding.commit, scope, context, notes=notes, source=binding.source)

    # ------------------------------------------------------------ a landed package, a cited line of code
    def judge_commit(self, item: Mapping[str, Any] | None) -> Judgement:
        if item is None or not item.get("commit"):
            return Judgement("unknown", None, [], "no commit recorded")
        full, in_history = self.place(item["commit"])
        if full is None:
            return Judgement("stale", "claim", [], f"commit {item['commit'][:8]} is not in this repository", None, item["commit"])
        if not in_history:
            return Judgement("stale", "record", [], f"commit {item['commit'][:8]} is not in this history", "passed", full)
        return Judgement("met", "record", [], f"{full[:8]} is an ancestor of the head", "passed", full)

    def judge_package(self, package: Mapping[str, Any], item: Mapping[str, Any] | None) -> Judgement:
        """A rig package: landed (the ladder's word) at a commit git places (the evidence)."""

        if package.get("status") != "landed":
            return Judgement("unmet", None, [], f"{package.get('id')} is {package.get('status')}")
        if item is None:
            return Judgement("unknown", None, [], "landed, but no commit recorded")
        recorded = str(package.get("commit") or "")
        cited = str(item.get("commit") or "")
        if not recorded or not cited or not (recorded.startswith(cited) or cited.startswith(recorded)):
            return Judgement("unknown", None, [], f"the evidence names {cited or 'no commit'}, the ladder {recorded or 'none'}")
        return self.judge_commit(item)

    def judge_inspection(self, item: Mapping[str, Any] | None) -> Judgement:
        if item is None:
            return Judgement("unknown", None, [], "nothing cited")
        path = self.resolve(item)
        if path is None or not path.is_file():
            return Judgement("unknown", None, [], "the cited file does not exist at the head")
        lines = links.count_lines(str(path)) or 0
        for number in (item.get("line"), item.get("end_line")):
            if number is not None and not 1 <= number <= lines:
                return Judgement("unknown", None, [], f"line {number} is outside the file ({lines} lines)")
        return Judgement("met", "record", [], "the cited code exists at the head", "passed", self.repo.head)

    # ------------------------------------------------------------ a measured gate on the ledger
    def judge_window(self, rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any], scope: Sequence[str],
                     context: Mapping[str, Any], *, problems: Sequence[str] = ()) -> Judgement:
        """A window of gated readings on one corpus (std/throughput), or a ratchet's latest two."""

        rows, problems = list(rows), list(problems)
        needed = int(spec.get("needed") or 1)
        if not rows:
            return Judgement("unknown", None, [], f"no gated {spec.get('tier')} reading on {spec.get('corpus')}")
        if spec.get("rule") == "ratchet":
            return self._judge_ratchet(rows, spec, scope, context, problems)
        if len(rows) < needed:
            return Judgement("unmet", None, [], f"needs {needed} gated {spec.get('tier')} reading(s), has {len(rows)}")
        if len({(row.get("metrics") or {}).get("verdict_hash") for row in rows}) > 1:
            problems.append(f"{len(rows)} runs disagree on verdict_hash")
        for row in rows:
            problems += [f"{row.get('run_id')} {failure}" for failure in self.bar_failures(row, spec)]
        return self._window_tail(rows, problems, scope, context, spec)

    def _judge_ratchet(self, rows, spec, scope, context, problems) -> Judgement:
        if len(rows) < 2:
            # WHY: a ratchet's first reading is a recorded baseline, never a pass (ROADMAP §1; Zach Jul 31).
            return Judgement("unmet", None, [], f"{rows[-1].get('run_id')} is the baseline; a second reading must reach it")
        previous, latest = rows[-2], rows[-1]
        metric = spec.get("metric")
        latest_value = _finite((latest.get("metrics") or {}).get(metric))
        previous_value = _finite((previous.get("metrics") or {}).get(metric))
        if latest_value is None or previous_value is None or latest_value < previous_value - RATE_TOLERANCE:
            problems.append(f"{metric} {latest_value} < previous {previous_value}")
        problems += [f"{latest.get('run_id')} {failure}" for failure in self.bar_failures(latest, spec)]
        problems += [f"baseline {previous.get('run_id')} {failure}" for failure in self.bar_failures(previous, spec, feasibility=False)]
        return self._window_tail([previous, latest], problems, scope, context, spec)

    def judge_determinism(self, rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any], scope: Sequence[str],
                          context: Mapping[str, Any], *, problems: Sequence[str] = ()) -> Judgement:
        """``identical verdict_hash over N judged <mode>-mode runs at <v> m/s`` over the ledger rows themselves (Codex G09)."""

        rows, problems = list(rows), list(problems)
        wanted = int(spec.get("runs") or 2)
        if len(rows) < wanted:
            return Judgement("unknown", None, [], f"needs {wanted} judged {spec.get('mode')}-mode runs at "
                                                  f"{spec.get('belt_speed_m_s')} m/s on one corpus and commit, has {len(rows)}")
        hashes = {str((row.get("metrics") or {}).get("verdict_hash") or "") for row in rows}
        if len(hashes) != 1 or "" in hashes:
            problems.append(f"{len(rows)} runs give {len(hashes)} verdict_hash values")
        for row in rows:
            metrics = row.get("metrics") or {}
            if (metrics.get("latency") or {}).get("mode") != spec.get("mode"):
                problems.append(f"{row.get('run_id')} ran in {(metrics.get('latency') or {}).get('mode')!r} mode")
            speed = _finite(self.belt_speed(row))
            if speed is None or abs(speed - float(spec.get("belt_speed_m_s") or 0.0)) > 1e-9:
                problems.append(f"{row.get('run_id')} ran at {self.belt_speed(row)!r} m/s")
            corpus_spec = {"tier": metrics.get("tier"), "corpus": metrics.get("corpus_id"), "count": None, "latency": None,
                           "feasible_rate_min": 0.0, "recovery_min": None}
            problems += [f"{row.get('run_id')} {failure}" for failure in self.bar_failures(row, corpus_spec, feasibility=False)
                         if "all_passed" not in failure]
        recorded = [(self._run_file(row, "manifest.json") or {}).get("corpus") for row in rows]
        if any(not same_value(recorded[0], other) for other in recorded[1:]):
            # WHY (Codex H04): one verdict_hash over runs of different inputs says nothing about determinism.
            problems.append(f"the {len(rows)} runs' manifests record different corpus inputs")
        judgement = self._window_tail(rows, problems, scope, context)
        if judgement.verdict in ("met", "stale"):
            judgement.note = f"{', '.join(str(row.get('run_id')) for row in rows)}: one verdict_hash " \
                             f"{next(iter(hashes))[:12]}" + (f"; {judgement.note.split('; ', 1)[1]}" if '; ' in judgement.note else "")
        return judgement

    def belt_speed(self, row: Mapping[str, Any]) -> Any:
        """The belt speed a run recorded for itself (its manifest), else its corpus's (the curriculum's)."""

        manifest = self._run_file(row, "manifest.json") or {}
        if "belt_speed_m_s" in manifest:
            return manifest.get("belt_speed_m_s")
        return ((manifest.get("corpus") or {}).get("belt_speed_m_s"))

    def _window_tail(self, rows, problems, scope, context, spec: Mapping[str, Any] | None = None) -> Judgement:
        """The rows' shared verdict: each at the commit its own records give, its inputs compared with what the gate asks now.

        WHY a manifest is required (Codex H04): the run's manifest is its own record of the inputs it ran on (corpus,
        slice, ruler, timing); without it a reading cannot be shown to answer the gate's corpus as it is now.
        """

        if problems:
            return Judgement("unmet", None, [], "; ".join(dict.fromkeys(problems)), "failed",
                             ((rows[-1].get("git") or {}).get("sha")))
        judgements = []
        for row in rows:
            git = row.get("git") or {}
            binding = git_record_binding(git, "the ledger row")
            manifest = self._run_file(row, "manifest.json")
            notes = [binding.note.replace("the ledger row", f"{row.get('run_id')}'s ledger row") if binding.note else ""]
            if manifest is None:
                notes.append(f"{row.get('run_id')} left no run manifest, so the inputs it ran on are not recorded")
            changes = input_changes((manifest or {}).get("corpus"), (spec or {}).get("inputs")) if manifest is not None else []
            judgements.append(self.finish("passed", "record", binding.commit, scope, context, notes=notes,
                                          context_value=(row.get("metrics") or {}).get("ruler_sha256"), source=binding.source,
                                          unproven=manifest is None, changes=changes))
        verdict = model.combine_verdicts([judgement.verdict for judgement in judgements])
        strength = model.weakest([judgement.strength for judgement in judgements]) if verdict in ("met", "stale") else None
        changed = [change for judgement in judgements for change in judgement.changed_since]
        totals = rows[-1].get("totals") or {}
        note = (f"{', '.join(str(row.get('run_id')) for row in rows)}: {totals.get('feasible')}/{totals.get('presented')} feasible, "
                f"0 VOID" + (", one verdict_hash" if len(rows) > 1 else ""))
        extra = "; ".join(dict.fromkeys(judgement.note for judgement in judgements if judgement.note))
        return Judgement(verdict, strength, list(dict.fromkeys(changed)), note + (f"; {extra}" if extra else ""), "passed",
                         judgements[-1].commit, placed=all(judgement.placed for judgement in judgements))

    def bar_failures(self, row: Mapping[str, Any], spec: Mapping[str, Any], *, feasibility: bool = True) -> list[str]:
        """Why one ledger row cannot count (Codex F12: numbers must be finite and agree with each other)."""

        metrics, totals, gates = row.get("metrics") or {}, row.get("totals") or {}, row.get("gates") or {}
        failures = []
        if metrics.get("tier") != spec.get("tier") or metrics.get("corpus_id") != spec.get("corpus"):
            failures.append(f"is {metrics.get('tier')} on {metrics.get('corpus_id')}, not {spec.get('tier')} on {spec.get('corpus')}")
        presented, feasible, void = totals.get("presented"), totals.get("feasible"), totals.get("void")
        counts_ok = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (presented, feasible, void))
        if not counts_ok:
            failures.append(f"totals are not counts (presented {presented!r}, feasible {feasible!r}, void {void!r})")
        else:
            if feasible > presented or void > presented:
                failures.append(f"totals contradict each other ({feasible} feasible, {void} void of {presented})")
            manifest_count = ((self._run_file(row, "manifest.json") or {}).get("corpus") or {}).get("count")
            expected = manifest_count if manifest_count is not None else spec.get("count")
            if expected is not None and (presented != expected or row.get("n_episodes") != expected):
                # WHY the run's own slice: a run that did not present every case it was given failed; a gate whose corpus
                # now asks for another slice is an input change, judged stale by input_changes (Codex H04).
                failures.append(f"covers {presented} of its {expected} cases")
            if void != 0:
                failures.append(f"{void} VOID")
        rate = _finite(metrics.get("feasible_rate"))
        if rate is None:
            failures.append(f"feasible_rate {metrics.get('feasible_rate')!r} is not a finite number")
        elif counts_ok and presented and abs(rate - feasible / presented) > 1e-9:
            failures.append(f"feasible_rate {rate} disagrees with {feasible}/{presented}")
        coverage = _finite(gates.get("coverage"))
        if coverage is None or coverage < 1.0 - RATE_TOLERANCE:
            failures.append(f"coverage {gates.get('coverage')!r}")
        if gates.get("all_passed") is not True:
            failures.append("gates.all_passed is not true")
        declared = spec.get("latency")
        if declared is not None and not _same_latency(metrics.get("latency"), declared):
            failures.append("not taken under the corpus's declared timing")
        batch = self._run_file(row, "batch.json")
        if batch is not None:
            for key, value in (("presented", presented), ("feasible", feasible), ("void", void)):
                if batch.get(key) != value:
                    failures.append(f"batch.json says {key} {batch.get(key)!r}, the ledger {value!r}")
            if batch.get("verdict_hash") != metrics.get("verdict_hash"):
                failures.append("batch.json and the ledger disagree on verdict_hash")
        manifest = self._run_file(row, "manifest.json")
        if manifest is not None:
            failures += manifest_disagreements(manifest, row)
        if feasibility:
            minimum = float(spec.get("feasible_rate_min") or 0.0)
            if rate is not None and rate < minimum - RATE_TOLERANCE:
                failures.append(f"feasible {feasible}/{presented} < {minimum:g}")
            if spec.get("recovery_min") is not None:
                recovery = _finite(metrics.get("recovery"))
                if recovery is None or recovery < float(spec["recovery_min"]) - RATE_TOLERANCE:
                    failures.append(f"recovery {metrics.get('recovery')!r} < {spec['recovery_min']}")
        return failures

    def _run_file(self, row: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
        if self.roots.data_home is None:
            return None
        run_dir = (row.get("artifacts") or {}).get("run_dir") or f"runs/{row.get('run_id')}"
        payload = read_json_quiet(self.roots.data_home / run_dir / name)
        return payload if isinstance(payload, Mapping) else None


# ---------------------------------------------------------------- measured gates: the spec and its window
def manifest_disagreements(manifest: Mapping[str, Any], row: Mapping[str, Any]) -> list[str]:
    """Where a run's manifest (its own record) and its ledger row (the judge's) disagree (Codex H03's rule, for runs).

    WHY each is a failure, not a choice between them: two records of one run that disagree certify neither.
    """

    metrics, totals, git = row.get("metrics") or {}, row.get("totals") or {}, row.get("git") or {}
    failures = []
    for what, mine, theirs in (("run id", manifest.get("run_id"), row.get("run_id")),
                               ("rung", manifest.get("rung_id"), metrics.get("rung_id")),
                               ("tier", manifest.get("tier"), metrics.get("tier")),
                               ("corpus", manifest.get("corpus_id"), metrics.get("corpus_id")),
                               ("ruler", manifest.get("ruler_sha256"), metrics.get("ruler_sha256")),
                               ("presented", manifest.get("presented"), totals.get("presented"))):
        if mine != theirs:
            failures.append(f"its manifest says {what} {json.dumps(mine)}, the ledger {json.dumps(theirs)}")
    recorded_git = manifest.get("git") or {}
    sha, ledger_sha = str(recorded_git.get("sha") or ""), str(git.get("sha") or "")
    if not sha or not ledger_sha or not (sha.startswith(ledger_sha) or ledger_sha.startswith(sha)) \
            or recorded_git.get("dirty") != git.get("dirty"):
        failures.append(f"its manifest records commit {sha[:8] or 'none'} (dirty {recorded_git.get('dirty')!r}), "
                        f"the ledger {ledger_sha[:8] or 'none'} (dirty {git.get('dirty')!r})")
    if not _same_latency(manifest.get("latency"), metrics.get("latency") or {}):
        failures.append("its manifest and the ledger record different timing")
    return failures


def window_specs(gate: Mapping[str, Any], corpora: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The windows a bam-curriculum/1 measured gate needs, one spec per corpus (ROADMAP.md §1).

    std / throughput: the promotion corpus once, plus ``repeats`` readings of the regression corpus (or of
    the promotion corpus when there is none and ``repeats`` > 1), all on one verdict_hash. ratchet: the
    promotion corpus's latest two readings. ``inputs`` is the corpus as the curriculum defines it now, which
    each reading's manifest must have recorded (Codex H04).
    """

    kind = gate.get("kind")
    promotion, regression = gate.get("promotion_corpus"), gate.get("regression_corpus")
    repeats = int(gate.get("repeats") or 1)
    parts: list[tuple[str | None, str, int, str]] = []
    if kind == "ratchet":
        parts.append((promotion, "promotion", 2, "ratchet"))
    else:
        parts.append((promotion, "promotion", 1, "window"))
        repeat_tier, repeat_corpus = ("regression", regression) if regression else ("promotion", promotion)
        if repeat_corpus is not None and (regression or repeats > 1):
            parts.append((repeat_corpus, repeat_tier, max(repeats, 1), "window"))
    specs = []
    for corpus_id, tier, needed, rule in parts:
        corpus = corpora.get(str(corpus_id)) or {}
        specs.append({"rule": rule, "tier": tier, "corpus": corpus_id, "count": corpus.get("count"),
                      "latency": corpus.get("latency"), "producer_corpus_id": corpus.get("producer_corpus_id"), "needed": needed,
                      "inputs": dict(corpus) if corpus else None,
                      "feasible_rate_min": float(gate.get("feasible_rate_min") or 0.0),
                      "recovery_min": gate.get("recovery_min") if kind == "throughput" else None,
                      "metric": gate.get("metric") if rule == "ratchet" else None})
    return specs


def gated_window(rows: Iterable[Mapping[str, Any]], rung_id: str, spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The latest ``needed`` gated readings for one window: this rung, tier and corpus, under the corpus's timing.

    A run id's first row wins (the fold's rule); a reading under another timing is a KPI reading, never a gate
    reading (ROADMAP §1, T4). Readings under any ruler count here and are judged stale by the ruler context,
    so an older ruler's proof is kept and shown, never silently dropped (Codex F08).
    """

    seen: set[Any] = set()
    gated = []
    for row in rows:
        run_id = row.get("run_id")
        if run_id in seen:
            continue
        seen.add(run_id)
        metrics = row.get("metrics") or {}
        if metrics.get("rung_id") != rung_id or metrics.get("tier") != spec.get("tier") or metrics.get("corpus_id") != spec.get("corpus"):
            continue
        declared = spec.get("latency")
        if declared is not None and not _same_latency(metrics.get("latency"), declared):
            continue
        gated.append(row)
    return gated[-int(spec.get("needed") or 1):]


def tier_definition_at(repo: Repo, tiers_path: str, tier: str, commit: str | None) -> list[dict[str, Any]] | None:
    """A gate tier's suites as ``tiers.json`` declared them at ``commit``: name, cwd, argv, junit, then (Codex G07)."""

    text = repo.show(commit, tiers_path) if commit else None
    try:
        tiers = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(tiers, Mapping):
        return None
    return [dict(suite) for suite in ((tiers.get("tiers") or {}).get(tier) or []) if isinstance(suite, Mapping)]


def junit_cases_for(cases: Sequence[artifacts.JunitCase], suite_dir: str, target: str) -> list[artifacts.JunitCase]:
    """The cases of one test file in a JUnit file (classnames are module paths relative to the suite's cwd)."""

    return [case for case in cases
            if links.junit_file_for(case.classname, suite_dir, lambda relative: relative == target)[0] == target]


def case_keys(cases: Sequence[artifacts.JunitCase]) -> list[str]:
    return [_case_key(case) for case in cases]


def _case_key(case: artifacts.JunitCase) -> str:
    """``Class::name[params]`` or ``name[params]``: a case's identity with its parameters kept (Codex F06)."""

    parts = case.classname.split(".")
    klass = parts[-1] if parts and parts[-1][:1].isupper() and parts[-1].startswith("Test") else None
    return f"{klass}::{case.name}" if klass else case.name


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _same_latency(actual: Any, declared: Mapping[str, Any]) -> bool:
    if not isinstance(actual, Mapping) or actual.get("mode") != declared.get("mode"):
        return False
    actual_budget, declared_budget = _finite(actual.get("budget_s")), _finite(declared.get("budget_s"))
    if actual_budget is None or declared_budget is None:
        return actual_budget is None and declared_budget is None
    return abs(actual_budget - declared_budget) <= RATE_TOLERANCE


__all__ = ["Evaluator", "Judgement", "Binding", "RulerAt", "artifact_commit", "audit_commit", "bind", "claimed_result",
           "report_binding", "git_record_binding", "window_specs", "gated_window", "tier_definition_at", "declared_case_counts",
           "declared_case_ids", "coverage_shortfall", "input_changes", "manifest_disagreements"]
