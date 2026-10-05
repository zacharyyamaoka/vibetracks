"""Read a result out of the artifact itself, never out of the sentence that cites it.

Each reader takes a file the loops already write and returns what it says, in the in-toto
test-result vocabulary (``passed`` / ``warned`` / ``failed``), plus the numbers behind it and
the line it was read from, so a link can open on that line:

- a console log, read one run at a time (Codex F05): a ``$ command`` header starts a run, a
  summary line (``328 passed in 10.41s``), a journey line (``34/34 checks passed``) or the gate's
  line (``GATE PASS tier=fast report=…``) ends one, and an ``EXIT n`` line closes the run it follows;
- what a log shows about one test file (Codex G05, H01): the file's complete collection, selected whole by the
  run's own command, one outcome per test printed and every one a pass, and a summary line that agrees with them;
  a node-level PASSED proves only that node, and a summary line never stands in for the per-test record;
- an audit report: ``VERDICT: SHIP`` (kinsim) or a leading ``**SOUND WITH FIXES.**`` (rig);
- a JUnit XML file, case by case with parameters kept (Codex F06), folded by test id the gate's way (H05);
- the gate's ``bam-gate-report/1``, certified only when its counts, exit codes, expected and unexpected sets,
  ``then`` commands, the JUnit files it names reopened, and the tier that was declared all agree (Codex F07, G07, H03).

A file with no readable result returns ``result: None``: it can be shown, never counted.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

MAX_READ_BYTES = 8 * 1024 * 1024

_SUMMARY_ITEM = r"\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun)"
# WHY a whole line, decorations allowed but nothing else (Codex F05): "Expected output: 123 passed in
# 0.1s" quoted inside a log is not a run's summary; pytest's own line is only counts, a duration and "=".
_PYTEST_SUMMARY = re.compile(rf"^=*\s*(?P<counts>{_SUMMARY_ITEM}(?:, {_SUMMARY_ITEM})*) in \d+(?:\.\d+)?s"
                             r"(?: \(\d+:\d\d:\d\d\))?\s*=*$")
_NO_TESTS = re.compile(r"^=*\s*no tests ran in \d+(?:\.\d+)?s\s*=*$")
_PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun)")
_JOURNEY = re.compile(r"^(\d+)/(\d+) checks passed\b")
_GATE = re.compile(r"^GATE (PASS|FAIL) tier=(\S+) report=(\S+)\s*$")
_EXIT = re.compile(r"^(?:EXIT|exit)[ =](-?\d+)\s*$")
# The gate writes "$ (cd CWD && ARGV)" before each command it runs; an agent's log may write "$ ARGV".
_COMMAND = re.compile(r"^\$ (?:\(cd (?P<cwd>\S+) && (?P<wrapped>.*)\)|(?P<plain>.*))$")
# pytest's own per-file progress line (default verbosity): "tests/test_x.py ..s.F   [ 40%]".
_PROGRESS = re.compile(r"^(?P<path>[\w./-]+\.py) (?P<marks>[.sFExX]+)\s*(?:\[\s*\d+%\])?\s*$")
# pytest -v ("path::name PASSED") and -r short summaries ("PASSED path::name", "ERROR path").
_VERBOSE = re.compile(r"^(?P<node>[\w./-]+\.py::\S+) (?P<word>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
_SHORT = re.compile(r"^(?P<word>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (?P<node>[\w./-]+\.py(?:::\S+)?)")
_VERDICT_LINE = re.compile(r"^\s*VERDICT:\s*([A-Z][A-Z -]*[A-Z])\s*$")
_LEADING_VERDICT = re.compile(r"^\s*\*\*\s*(SOUND WITH FIXES|SOUND|UNSOUND|SHIP|DO-NOT-SHIP|FIX|FAIL|PASS)\b")
_RED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)")
_PLACEHOLDER = re.compile(r"\{(root|out)\}")  # bam_curriculum gate.expand

# Audit words, both loops, onto in-toto's three results.
AUDIT_RESULTS = {
    "SHIP": "passed", "PASS": "passed", "SOUND": "passed",
    "SOUND WITH FIXES": "warned",
    "DO-NOT-SHIP": "failed", "UNSOUND": "failed", "FAIL": "failed", "FIX": "failed",
}
# pytest options that take the next token as their value (so it is not a file to collect).
_VALUE_OPTIONS = frozenset({"-k", "-m", "-p", "-c", "-o", "-W", "-n", "--deselect", "--ignore", "--ignore-glob", "--rootdir",
                            "--junitxml", "--junit-xml", "--tb", "--maxfail", "--durations", "--basetemp", "--confcutdir",
                            "--cov", "--timeout", "--dist", "--log-level", "--log-file", "--override-ini", "--import-mode"})


@dataclass
class Reading:
    """What one artifact says."""

    result: str | None = None
    line: int | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    pointer: str | None = None  # another artifact this one names (the gate log's report=)


def _text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            return None
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


@lru_cache(maxsize=512)
def _text_cached(path: str, mtime: float, size: int) -> str | None:
    return _text(Path(path))


def whole_text(path: Path | str) -> str | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return _text_cached(str(path), stat.st_mtime, stat.st_size)


# ---------------------------------------------------------------- pytest command lines
@dataclass
class Selection:
    """What one pytest command asked to collect: its file/dir arguments, node ids, and explicit deselections."""

    paths: list[str]
    nodes: list[str]
    deselect: list[str]
    filtered: bool  # -k or -m: pytest may deselect tests the command line does not name


def pytest_selection(argv: Sequence[str]) -> Selection | None:
    """The collection a pytest argv asks for, or None when the argv does not run pytest."""

    tokens = list(argv)
    start = None
    for index in range(len(tokens) - 1):
        if tokens[index] == "-m" and tokens[index + 1] == "pytest":
            start = index + 2
    if start is None:
        for index, token in enumerate(tokens):
            if (token == "pytest" or token.endswith("/pytest")) and (index == 0 or tokens[index - 1] not in ("--with", "-w")):
                start = index + 1
    if start is None:
        return None
    paths, nodes, deselect, filtered = [], [], [], False
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--deselect="):
            deselect.append(token.split("=", 1)[1])
        elif token in ("-k", "-m"):
            filtered = True
            index += 1
        elif token == "--deselect":
            deselect.append(tokens[index + 1] if index + 1 < len(tokens) else "")
            index += 1
        elif token in _VALUE_OPTIONS:
            index += 1
        elif (token.startswith("-k") or token.startswith("-m")) and len(token) > 2 and not token.startswith("--"):
            filtered = True
        elif not token.startswith("-"):
            (nodes if "::" in token else paths).append(token)
        index += 1
    return Selection(paths, nodes, deselect, filtered)


def _relative(target: str, cwd: str | None) -> str | None:
    """``target`` (repository-relative) as pytest prints it from ``cwd`` (an absolute path in some checkout)."""

    if not cwd:
        return None
    parts = PurePosixPath(cwd).parts
    for cut in range(len(parts)):
        tail = "/".join(parts[cut:])
        if target.startswith(tail.rstrip("/") + "/"):
            return target[len(tail.rstrip("/")) + 1:]
    return None


def selects_whole(selection: Selection, target: str, cwd: str | None) -> bool:
    """Does the command collect every test of ``target`` (a file named, a folder above it, or no paths at all)?"""

    printed = _relative(target, cwd)
    if printed is None:
        return False
    if any(node.split("::", 1)[0] == printed for node in selection.nodes):
        return False
    if not selection.paths and not selection.nodes:
        return True
    return any(printed == path.rstrip("/") or printed.startswith(path.rstrip("/") + "/") or path in (".", "./")
               for path in selection.paths)


# ---------------------------------------------------------------- logs, one run at a time
# pytest's per-item outcome letters (progress marks) and words (-v lines), onto its summary's count names.
_MARK_COUNTS = {".": "passed", "F": "failed", "E": "errors", "s": "skipped", "x": "xfailed", "X": "xpassed"}
_WORD_COUNTS = {"PASSED": "passed", "FAILED": "failed", "ERROR": "errors", "SKIPPED": "skipped", "XFAIL": "xfailed",
                "XPASS": "xpassed"}
_ITEM_COUNTS = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")
# A long file's progress wraps onto lines of marks alone; they continue the file above them.
_CONTINUATION = re.compile(r"^(?P<marks>[.sFExX]+)\s*(?:\[\s*\d+%\])?\s*$")
_COLLECTED = re.compile(r"^collected (?P<collected>\d+) items?(?P<rest>(?: / \d+ [a-z]+)*)\s*$")


@dataclass
class Run:
    """One run inside a log: its command (if recorded), what it printed per file and per test, and how it ended.

    ``files`` holds pytest's progress marks per printed file (default verbosity), ``nodes`` its ``-v`` lines per node,
    ``short`` the ``-r`` short-summary lines per node. Only the first two are a per-item record of what ran: the short
    summary is a digest, printed after the fact (Codex H01).
    """

    command: str | None = None
    cwd: str | None = None
    result: str | None = None
    line: int | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    pointer: str | None = None
    exit: int | None = None
    exit_line: int | None = None
    has_result_line: bool = False
    files: dict[str, str] = field(default_factory=dict)        # printed path -> outcome marks (progress lines)
    nodes: dict[str, list[str]] = field(default_factory=dict)  # printed node id -> outcome words (-v lines)
    short: dict[str, list[str]] = field(default_factory=dict)  # printed node id -> outcome words (-r short summary)
    collected: dict[str, int] | None = None                    # pytest's "collected N items / M deselected" line
    continuing: str | None = None                              # the file a marks-only line continues (parser state)

    def verdict(self) -> str | None:
        if self.exit is not None and self.exit != 0:
            return "failed"
        return self.result

    def has_content(self) -> bool:
        return bool(self.command or self.has_result_line or self.files or self.nodes or self.short)

    @property
    def argv(self) -> list[str]:
        try:
            return shlex.split(self.command or "")
        except ValueError:
            return (self.command or "").split()

    def item_counts(self) -> dict[str, int]:
        """What the per-item record shows, in the summary's own words (passed, failed, errors, ...)."""

        counts = {name: 0 for name in _ITEM_COUNTS}
        for marks in self.files.values():
            for mark in marks:
                counts[_MARK_COUNTS[mark]] += 1
        for words in self.nodes.values():
            for word in words:
                counts[_WORD_COUNTS[word]] += 1
        return counts

    def summary_counts(self) -> dict[str, int]:
        return {name: int(self.facts.get(name, 0) or 0) for name in _ITEM_COUNTS}


def _result_line(text: str) -> Run | None:
    gate = _GATE.match(text)
    if gate:
        return Run(result="passed" if gate.group(1) == "PASS" else "failed", facts={"gate": gate.group(1), "tier": gate.group(2)},
                   pointer=gate.group(3), has_result_line=True)
    journey = _JOURNEY.match(text)
    if journey:
        done, total = int(journey.group(1)), int(journey.group(2))
        return Run(result="passed" if done == total and total > 0 else "failed", facts={"checks_passed": done, "checks": total},
                   has_result_line=True)
    summary = _PYTEST_SUMMARY.match(text)
    if summary:
        counts = {_plural(kind): int(number) for number, kind in _PYTEST_COUNT.findall(summary.group("counts"))}
        red = counts.get("failed", 0) + counts.get("errors", 0)
        # WHY skipped-only is no result: a run that skipped everything proved nothing (Codex F05/F06).
        return Run(result="failed" if red else ("passed" if counts.get("passed", 0) > 0 else None), facts=counts,
                   has_result_line=True)
    if _NO_TESTS.match(text):
        return Run(facts={"passed": 0}, has_result_line=True)
    return None


def log_runs(text: str) -> list[Run]:
    """Split a log into runs: a ``$`` command header starts one, a result line ends one, ``EXIT`` closes the one it follows."""

    runs: list[Run] = []
    current = Run()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        command = _COMMAND.match(line)
        if command:
            if current.has_content():
                runs.append(current)
            current = Run(command=command.group("wrapped") or command.group("plain"), cwd=command.group("cwd"))
            continue
        exit_match = _EXIT.match(line)
        if exit_match:
            code = int(exit_match.group(1))
            if current.has_content():
                current.exit, current.exit_line = code, number
                runs.append(current)
                current = Run()
            elif runs and runs[-1].exit is None:
                runs[-1].exit, runs[-1].exit_line = code, number
            else:
                runs.append(Run(exit=code, exit_line=number))
            continue
        progress = _PROGRESS.match(line)
        if progress:
            current.files[progress.group("path")] = current.files.get(progress.group("path"), "") + progress.group("marks")
            current.continuing = progress.group("path")
            continue
        continuation = _CONTINUATION.match(line)
        if continuation and current.continuing is not None:
            current.files[current.continuing] += continuation.group("marks")
            continue
        current.continuing = None
        collected = _COLLECTED.match(line)
        if collected:
            current.collected = {"collected": int(collected.group("collected")),
                                 **{word: int(number) for number, word in re.findall(r" / (\d+) ([a-z]+)", collected.group("rest"))}}
            continue
        verbose = _VERBOSE.match(line)
        if verbose:
            current.nodes.setdefault(verbose.group("node"), []).append(verbose.group("word"))
            continue
        short = _SHORT.match(line)
        if short:
            current.short.setdefault(short.group("node"), []).append(short.group("word"))
            continue
        found = _result_line(line)
        if found is not None:
            current.result, current.facts, current.pointer = found.result, found.facts, found.pointer
            current.line, current.has_result_line = number, True
            runs.append(current)
            current = Run()
    if current.has_content() or current.exit is not None:
        runs.append(current)
    return runs


def read_log(path: Path) -> Reading:
    """A console log's result: the LAST run decides, and any earlier red run makes the whole log red.

    WHY any earlier red (Codex F05): a cited log that contains a red run is not proof of green; the
    loop re-runs into a clean log. An EXIT line belongs to the run it closes, never to another one.
    This is the log's word about itself (its last summary line): it can make a log red, never prove one file.
    """

    text = whole_text(path)
    if text is None:
        return Reading()
    runs = [run for run in log_runs(text) if run.has_result_line or run.exit is not None]
    if not runs:
        return Reading()
    last = runs[-1]
    red = next((run for run in runs if run.verdict() == "failed"), None)
    decided = red if red is not None else last
    facts = dict(decided.facts)
    if decided.exit is not None:
        facts["exit"] = decided.exit
    facts["runs"] = len(runs)
    result = "failed" if red is not None else last.verdict()
    line = decided.line or decided.exit_line
    return Reading(result, line, facts, decided.pointer if decided is last else None)


def _plural(kind: str) -> str:
    if kind in ("error", "errors"):
        return "errors"
    if kind in ("warning", "warnings"):
        return "warnings"
    return kind


def _names_target(printed: str, target: str, cwd: str | None) -> bool:
    relative = _relative(target, cwd)
    if relative is not None:
        return printed == relative
    return "/" in printed and (target == printed or target.endswith("/" + printed))


def deselection_accounted(run_facts: Mapping[str, Any], selection: Selection | None, printed_target: str | None) -> tuple[bool, str]:
    """Is every deselected test of a run known, and none of them in the target? ``(complete, why not)``."""

    deselected = int(run_facts.get("deselected", 0) or 0)
    if deselected == 0:
        return True, ""
    explicit = selection.deselect if selection else []
    if printed_target is not None and any(node.split("::", 1)[0] == printed_target for node in explicit):
        return False, f"the run deselected {', '.join(node for node in explicit if node.startswith(printed_target))}"
    if len(explicit) == deselected:
        return True, ""
    return False, f"the run deselected {deselected} test(s) it does not name, so this file's may be among them"


def _reconciled(run: Run) -> tuple[bool, str]:
    """Do a run's per-item record and its summary line say the same thing? (Codex H01: neither overrides the other.)"""

    if not run.has_result_line:
        return False, "the run has no summary line, so its collection is not recorded"
    shown, summary = run.item_counts(), run.summary_counts()
    if shown != summary:
        differing = ", ".join(f"{name} {summary[name]} in the summary, {shown[name]} shown" for name in _ITEM_COUNTS
                              if shown[name] != summary[name])
        return False, f"the run's summary disagrees with what it printed per test ({differing})"
    if run.collected is not None and not summary["errors"]:
        selected = run.collected.get("selected", run.collected["collected"] - run.collected.get("deselected", 0))
        ran = sum(summary[name] for name in _ITEM_COUNTS if name != "errors")
        if selected != ran:
            return False, f"pytest collected {selected} test(s) to run, the run shows {ran}"
    return True, ""


def _selected_whole(run: Run, selection: Selection | None, target: str, shown_as: str | None) -> bool:
    """Did the run's own command collect every test of ``target``? With no cwd recorded, the path pytest printed stands in."""

    if selection is None:
        return False
    if run.cwd:
        return selects_whole(selection, target, run.cwd)
    if shown_as is None:
        return False
    if any(node.split("::", 1)[0] == shown_as for node in selection.nodes):
        return False
    if not selection.paths and not selection.nodes:
        return True
    return any(shown_as == path.rstrip("/") or shown_as.startswith(path.rstrip("/") + "/") or path in (".", "./")
               for path in selection.paths)


@dataclass
class _FileInRun:
    """What one run printed about one file."""

    marks: str          # progress marks (default verbosity)
    nodes: dict          # node id -> -v words
    short: list          # -r short-summary words
    shown_as: str | None  # the path pytest printed for it


def _file_in_run(run: Run, target: str) -> _FileInRun:
    names = lambda printed: _names_target(printed, target, run.cwd)  # noqa: E731
    marks = "".join(file_marks for printed, file_marks in run.files.items() if names(printed))
    nodes = {node: words for node, words in run.nodes.items() if names(node.split("::", 1)[0])}
    short = [word for node, words in run.short.items() if names(node.split("::", 1)[0]) for word in words]
    shown_as = next((printed for printed in run.files if names(printed)), None) \
        or next((node.split("::", 1)[0] for node in nodes), None) \
        or next((node.split("::", 1)[0] for node in run.short if names(node.split("::", 1)[0])), None)
    return _FileInRun(marks, nodes, short, shown_as)


def target_evidence(path: Path, target: str) -> Reading:
    """What a log shows about one test file: its complete collection run and passed, or less (Codex G05, H01).

    A run proves the file (result ``passed``, ``facts.ceiling`` absent) only when its own record says the whole file
    ran and passed:

    - its command is recorded and selects the file whole (the file or a folder above it, no node id of it), and every
      test it deselected is named and outside the file;
    - it printed one outcome per collected test of the file, pytest's progress line(s) for the file (default
      verbosity) or one ``-v`` line per test, and every one is a pass;
    - its summary line agrees with everything it printed per test (and with pytest's ``collected`` line), so neither
      the summary nor a ``-r`` short-summary line can stand in for the per-test record.

    Less than that is said, never upgraded: a green record of the file whose run's command is not recorded, or a green
    ``pytest -q`` run that selected the file whole but printed no per-file outcome, is ``passed`` with ``ceiling:
    claim`` (the log's word for it); a record of some of its tests (a node id selected, a test of it deselected, a
    skip, a short summary only) or a record that contradicts its own summary is result None: a node-level PASSED
    proves only that node. A red outcome for any of its tests, in any run, makes the file red. ``facts.items`` counts
    the outcomes shown for the file and ``facts.node_ids`` lists what a ``-v`` record shows, so the evaluator can
    check them against the file's source at the run's commit.
    """

    text = whole_text(path)
    if text is None:
        return Reading(facts={"evidence": "none"})
    found: list[tuple[str | None, int | None, str, list[str], dict[str, Any]]] = []
    for run in log_runs(text):
        selection = pytest_selection(run.argv) if run.command else None
        shown = _file_in_run(run, target)
        words = [word for node_words in shown.nodes.values() for word in node_words]
        line = run.line or run.exit_line
        if any(mark in "FE" for mark in shown.marks) or any(word in ("FAILED", "ERROR") for word in words + shown.short):
            found.append(("failed", line, "pytest's progress line" if shown.marks else "per-test lines",
                          [f"a test of it is red in the run ending at line {line}"], {}))
            continue
        relative = _relative(target, run.cwd) or shown.shown_as
        notes: list[str] = []
        extra: dict[str, Any] = {}
        if shown.marks or shown.nodes:
            how = "pytest's progress line" if shown.marks else "per-test lines"
            extra = {"items": len(shown.marks) if shown.marks else len(words), "node_ids": sorted(shown.nodes)}
            unrun = [mark for mark in shown.marks if mark in "sxX"] + [word for word in words if word in ("SKIPPED", "XFAIL", "XPASS")]
            result: str | None = "passed"
            if unrun:
                result = None
                notes.append(f"{len(unrun)} of its {extra['items']} tests did not pass (skipped or xfail)")
            if shown.marks and shown.nodes:
                result = None
                notes.append("the run printed both progress marks and -v lines for it, which one pytest run never does")
            if selection is None:
                if result == "passed":
                    extra["ceiling"] = "claim"
                notes.append("the run's command is not recorded, so what it collected of the file is not shown")
            elif not _selected_whole(run, selection, target, shown.shown_as):
                result = None
                notes.append("the run's command did not select the whole file; a node-level record proves only those tests")
        elif shown.short:
            how, result = "pytest's short summary only", None
            extra = {"items": len(shown.short)}
            notes.append("only pytest's short summary names its tests: a digest printed after the run, not its per-test record")
        elif selection is not None and _selected_whole(run, selection, target, None) and run.has_result_line \
                and run.verdict() == "passed":
            counts = run.summary_counts()
            if counts["skipped"] or counts["xfailed"] or counts["xpassed"]:
                continue  # a run of several files with skips says nothing about this one
            how, result = "selected whole, no per-test record", "passed"
            extra["ceiling"] = "claim"
            notes.append("the run selected it whole and was green, but printed no outcome per file (pytest -q)")
        else:
            continue
        if result == "passed":
            complete, why = deselection_accounted(run.facts, selection, relative)
            if complete and how != "selected whole, no per-test record":
                complete, why = _reconciled(run)
            if not complete:
                result = None
                extra.pop("ceiling", None)
                notes.append(why)
        if run.exit not in (None, 0):
            result = None
            extra.pop("ceiling", None)
            notes.append(f"the run exited {run.exit}")
        found.append((result, line, how, notes, extra))
    if not found:
        return Reading(facts={"evidence": "none"})
    red = next((entry for entry in found if entry[0] == "failed"), None)
    proven = next((entry for entry in reversed(found) if entry[0] == "passed" and "ceiling" not in entry[4]), None)
    claimed = next((entry for entry in reversed(found) if entry[0] == "passed"), None)
    result, line, how, notes, extra = red or proven or claimed or found[-1]
    return Reading(result, line, {"evidence": how, "notes": notes, "runs": len(found), **extra})


def log_mentions(path: Path, names: set[str]) -> tuple[str | None, bool]:
    """Does a log's own text name a test file? ``(how, itemised)`` (shown in notes; never a result).

    ``how`` is ``"failed"`` when one of pytest's ``FAILED`` / ``ERROR`` lines names it, ``"ran"``
    when the file is named anywhere else, and None when the log never names it.
    """

    text = whole_text(path)
    if text is None:
        return None, False
    patterns = [re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.\w)") for name in names]
    red_lines = [match.group(1) for line in text.splitlines() if (match := _RED_LINE.match(line.strip()))]
    if any(pattern.search(node) for node in red_lines for pattern in patterns):
        return "failed", True
    named = any(pattern.search(text) for pattern in patterns)
    return ("ran" if named else None), bool(red_lines)


def read_audit(path: Path) -> Reading:
    """An audit report's verdict: the last ``VERDICT:`` line, else a bold verdict on the first line."""

    text = whole_text(path)
    if text is None:
        return Reading()
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        match = _VERDICT_LINE.match(lines[index])
        if match and match.group(1) in AUDIT_RESULTS:
            return Reading(AUDIT_RESULTS[match.group(1)], index + 1, {"verdict": match.group(1)})
    for index, line in enumerate(lines[:3]):
        match = _LEADING_VERDICT.match(line)
        if match:
            return Reading(AUDIT_RESULTS[match.group(1)], index + 1, {"verdict": match.group(1)})
    return Reading()


# ---------------------------------------------------------------- JUnit, case by case
@dataclass(frozen=True)
class JunitCase:
    """One testcase: ``classname``, ``name`` with its parameters kept, and its outcome."""

    classname: str
    name: str
    outcome: str  # passed | skipped | failed | error | failed+error

    @property
    def function(self) -> str:
        return self.name.split("[", 1)[0]


@lru_cache(maxsize=256)
def _junit_cached(path: str, mtime: float, size: int) -> tuple[JunitCase, ...] | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    cases = []
    for case in root.iter("testcase"):
        kinds = [kind for tag, kind in (("failure", "failed"), ("error", "error")) if case.find(tag) is not None]
        outcome = "+".join(kinds) if kinds else ("skipped" if case.find("skipped") is not None else "passed")
        cases.append(JunitCase(case.get("classname") or "", case.get("name") or "", outcome))
    return tuple(cases)


def junit_cases(path: Path | str) -> tuple[JunitCase, ...] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return _junit_cached(str(path), stat.st_mtime, stat.st_size)


def junit_result(cases: Iterable[JunitCase]) -> str | None:
    """passed only when every case passed (a skipped case is not coverage, Codex F06); failed on any red."""

    outcomes = [case.outcome for case in cases]
    if any(outcome != "passed" and outcome != "skipped" for outcome in outcomes):
        return "failed"
    if outcomes and all(outcome == "passed" for outcome in outcomes):
        return "passed"
    return None


def case_id(case: JunitCase) -> str:
    """The gate's own test id, ``classname::name`` (bam_curriculum ``gate.parse_junit``)."""

    return f"{case.classname}::{case.name}" if case.classname else case.name


def merged_outcomes(cases: Iterable[JunitCase]) -> dict[str, str]:
    """One outcome per test id, the way the gate folds them (Codex H05).

    WHY merge: pytest writes a failing call and a failing teardown as two testcases with one id, so the id, not the
    element, is the unit. Every red kind is kept (``failed+error``); a repeated passing id is still one test, so a
    duplicate can never stand for a parameter that did not run.
    """

    kinds: dict[str, set[str]] = {}
    for case in cases:
        found = set(case.outcome.split("+")) if case.outcome not in ("passed", "skipped") else {case.outcome}
        kinds.setdefault(case_id(case), set()).update(found)
    outcomes = {}
    for test_id, found in kinds.items():
        reds = sorted(found & {"failed", "error"})
        outcomes[test_id] = "+".join(reds) if reds else ("passed" if "passed" in found else "skipped")
    return outcomes


def outcome_counts(outcomes: Mapping[str, str]) -> dict[str, int]:
    """The gate's ``counts`` from merged outcomes: an id counts once under every kind it carries."""

    return {status: sum(1 for value in outcomes.values() if status in value.split("+")) for status in ("passed", "failed", "error", "skipped")}


# ---------------------------------------------------------------- the gate's report
def read_gate_report(path: Path) -> Mapping[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, Mapping) and report.get("schema") == "bam-gate-report/1" else None


def expand(value: str, root: str, out: str) -> str:
    """bam_curriculum ``gate.expand``: ``{root}`` and ``{out}`` placeholders in a tier's argv."""

    return _PLACEHOLDER.sub(lambda match: root if match.group(1) == "root" else out, value)


def suite_out_dir(suite: Mapping[str, Any]) -> str | None:
    log = suite.get("log")
    return os.path.dirname(str(log)) if isinstance(log, str) and log else None


_RUNNER_FAILURE = "<runner did not finish cleanly"
_COUNT_KEYS = ("passed", "failed", "error", "skipped")


def _is_red(outcome: str | None) -> bool:
    return outcome is not None and outcome not in ("passed", "skipped")


def _suite_reading(suite: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """``(reds, contradictions)`` of one suite, from its own records only (Codex G07, H03).

    Reds are what the suite's records agree went wrong: an unexpected red or green, a ``then`` command that did not exit
    0. Contradictions are records that disagree: counts that are not counts, or that differ from the suite's own JUnit
    file reopened and folded the gate's way; an exit code its counts cannot explain; a red case the suite lists as
    neither expected nor unexpected, or an expected red the JUnit does not show red.
    """

    name = str(suite.get("suite"))
    reds: list[str] = []
    contradictions: list[str] = []
    unexpected_red = [str(entry) for entry in suite.get("unexpected_red") or []]
    if unexpected_red:
        reds.append(f"suite {name} has {len(unexpected_red)} unexpected red")
    if suite.get("unexpected_green"):
        reds.append(f"suite {name} has {len(suite.get('unexpected_green') or [])} unexpected green")
    counts = suite.get("counts")
    if not isinstance(counts, Mapping) or not all(isinstance(counts.get(key), int) and not isinstance(counts.get(key), bool)
                                                   and counts.get(key) >= 0 for key in _COUNT_KEYS):
        contradictions.append(f"suite {name} records no counts ({counts!r})")
        counts = None
    runner_failed = any(_RUNNER_FAILURE in entry for entry in unexpected_red)
    exit_code = suite.get("exit_code")
    if suite.get("junit") is True:
        junit = junit_path_of(suite)
        cases = junit_cases(junit) if junit else None
        if cases is None:
            if not runner_failed:
                contradictions.append(f"suite {name}'s JUnit file does not open, so its counts cannot be checked")
        else:
            outcomes = merged_outcomes(cases)
            recounted = outcome_counts(outcomes)
            if counts is not None and {key: counts[key] for key in _COUNT_KEYS} != recounted:
                contradictions.append(f"suite {name} records counts {dict((key, counts[key]) for key in _COUNT_KEYS)}, "
                                      f"its JUnit file shows {recounted}")
            red_ids = {test_id for test_id, outcome in outcomes.items() if _is_red(outcome)}
            expected = {str(entry) for entry in suite.get("expected_red") or []}
            if expected - red_ids:
                contradictions.append(f"suite {name} lists {len(expected - red_ids)} expected red its JUnit does not show red")
            unlisted = red_ids - expected - set(unexpected_red)
            if unlisted:
                contradictions.append(f"suite {name} has {len(unlisted)} red case(s) it lists neither as expected nor unexpected")
            if exit_code == 0 and red_ids:
                contradictions.append(f"suite {name} exited 0 with {len(red_ids)} red case(s)")
            elif exit_code == 1 and not red_ids and not runner_failed:
                contradictions.append(f"suite {name} exited 1 with nothing red and no runner failure listed")
            elif exit_code not in (0, 1) and not runner_failed:
                contradictions.append(f"suite {name} exited {exit_code!r} and lists no runner failure")
    else:
        if counts is not None and any(counts[key] for key in _COUNT_KEYS):
            contradictions.append(f"suite {name} runs no JUnit but records counts")
        if exit_code != 0 and not runner_failed:
            contradictions.append(f"suite {name} exited {exit_code!r} and lists no runner failure")
    if counts is not None and exit_code == 0 and (counts["failed"] or counts["error"]):
        contradictions.append(f"suite {name} exited 0 with {counts['failed']} failed and {counts['error']} error")
    for index, command in enumerate(suite.get("then") or []):
        code = command.get("exit_code") if isinstance(command, Mapping) else None
        if code != 0:
            reds.append(f"suite {name} then[{index}] exited {code!r}")
    return reds, contradictions


def gate_report_reading(report: Mapping[str, Any], tier: Sequence[Mapping[str, Any]] | Sequence[str] | None = None) -> Reading:
    """The gate's verdict, only when every record in the report agrees with every other (Codex F07, G07, H03).

    Certified ``passed``: suites are listed; each suite's counts equal its JUnit file reopened and folded the gate's
    way, its exit code is the one those counts give, every red case is listed as expected or unexpected, and every
    ``then`` command exited 0; the report's own ``unexpected_red`` / ``unexpected_green`` are its suites' lists and
    its ``passed`` follows from them; and, when the tier's definition is known (``tiers.json`` at the run's
    commit), every declared suite ran with its declared argv and every declared ``then`` command ran. ``failed``:
    the records agree that something is red. Any contradiction certifies nothing (result None, said in ``facts``),
    whatever ``passed`` says.
    """

    reds: list[str] = []
    contradictions: list[str] = []
    suites = report.get("suites")
    if not isinstance(suites, list) or not suites:
        contradictions.append("the report lists no suites")
        suites = []
    by_name: dict[str, Mapping[str, Any]] = {}
    suite_red: list[str] = []
    suite_green: list[str] = []
    for suite in suites:
        if not isinstance(suite, Mapping):
            contradictions.append("a suite is not an object")
            continue
        by_name[str(suite.get("suite"))] = suite
        suite_reds, suite_contradictions = _suite_reading(suite)
        reds += suite_reds
        contradictions += suite_contradictions
        suite_red += [str(entry) for entry in suite.get("unexpected_red") or []]
        suite_green += [str(entry) for entry in suite.get("unexpected_green") or []]
    red = [str(entry) for entry in report.get("unexpected_red") or []]
    green = [str(entry) for entry in report.get("unexpected_green") or []]
    if sorted(red) != sorted(suite_red):
        contradictions.append(f"the report lists {len(red)} unexpected red, its suites {len(suite_red)}")
    if not set(suite_green) <= set(green):
        contradictions.append(f"the report lists {len(green)} unexpected green, its suites {len(set(suite_green) - set(green))} more")
    if green and not suite_green:
        reds.append(f"{len(green)} unexpected green (a known issue no longer collected or now passing)")
    if tier is not None:
        declared = [entry if isinstance(entry, Mapping) else {"suite": entry} for entry in tier]
        names = [str(entry.get("suite")) for entry in declared]
        missing = sorted(set(names) - set(by_name))
        extra = sorted(set(by_name) - set(names))
        if missing:
            contradictions.append(f"suites the tier declares are missing: {', '.join(missing)}")
        if extra:
            contradictions.append(f"suites the tier does not declare: {', '.join(extra)}")
        root = str(report.get("root") or "")
        for entry in declared:
            suite = by_name.get(str(entry.get("suite")))
            if suite is None or "argv" not in entry:
                continue
            contradictions += _suite_against_tier(suite, entry, root)
    flag = report.get("passed")
    if flag is not True and flag is not False:
        contradictions.append(f"passed is {flag!r}, not true or false")
    elif flag is True and reds:
        contradictions.append(f"the report says passed=true, but {reds[0]}")
    elif flag is False and not reds and not contradictions:
        contradictions.append("the report says passed=false, but nothing in it is red")
    facts = {"suites": len(suites), "unexpected_red": len(red), "unexpected_green": len(green),
             "problems": [*reds, *contradictions], "contradictions": contradictions}
    if contradictions:
        facts["contradiction"] = "; ".join(contradictions[:3]) + (f" (+{len(contradictions) - 3})" if len(contradictions) > 3 else "")
        return Reading(None, None, facts)
    return Reading("failed" if reds else "passed", None, facts)


def _suite_against_tier(suite: Mapping[str, Any], entry: Mapping[str, Any], root: str) -> list[str]:
    """One suite of a report against its declaration: the argv it ran, and every ``then`` command, in order."""

    name = str(entry.get("suite"))
    out = suite_out_dir(suite)
    if out is None:
        return [f"suite {name} records no log, so its commands cannot be matched to the tier"]
    problems = []
    expected = [expand(str(token), root, out) for token in entry.get("argv") or []]
    if entry.get("junit"):
        expected.append(f"--junitxml={out}/junit.xml")
    if list(suite.get("argv") or []) != expected:
        problems.append(f"suite {name} ran {' '.join(map(str, suite.get('argv') or []))!r}, the tier declares {' '.join(expected)!r}")
    declared_then = [[expand(str(token), root, out) for token in command.get("argv") or []] for command in entry.get("then") or []]
    ran_then = [list(command.get("argv") or []) for command in suite.get("then") or [] if isinstance(command, Mapping)]
    failed_then = any(isinstance(command, Mapping) and command.get("exit_code") != 0 for command in suite.get("then") or [])
    if ran_then != declared_then[:len(ran_then)]:
        problems.append(f"suite {name} ran then commands the tier does not declare")
    elif len(ran_then) < len(declared_then) and not failed_then:
        # WHY "and not failed": the gate stops a suite's smokes at the first that fails; the red is counted already.
        problems.append(f"suite {name} ran {len(ran_then)} of the tier's {len(declared_then)} then commands")
    return problems


@dataclass
class Collection:
    """What one gate suite recorded about its own collection (Codex G06): enough to say a file ran whole."""

    complete: bool
    notes: list[str]


def suite_collection(suite: Mapping[str, Any], cases: Sequence[JunitCase], target: str) -> Collection:
    """Did a gate suite collect ``target`` whole? Read from the suite's own record, never from earlier runs.

    The record is the suite's argv (in the report) and the first run in its ``output.log`` (the pytest
    command, then its summary). Complete when the argv selects the file whole, the summary's counts equal
    the JUnit file's cases, and every deselected test is named by ``--deselect`` and not in the file.
    """

    argv = list(suite.get("argv") or [])
    selection = pytest_selection(argv)
    cwd = str(suite.get("cwd") or "")
    if selection is None:
        return Collection(False, ["the suite's argv is not a pytest command"])
    if not selects_whole(selection, target, cwd):
        return Collection(False, ["the suite's argv does not select this file whole"])
    log = suite.get("log")
    text = whole_text(Path(str(log))) if isinstance(log, str) and log else None
    runs = log_runs(text) if text else []
    main = next((run for run in runs if run.has_result_line), None)
    if main is None:
        return Collection(False, ["the suite's log records no summary, so what it collected is unknown"])
    counts = main.facts
    # WHY outcome by outcome over merged ids (Codex H05): a JUnit file that repeats a case must not make up the count
    # of a case that never ran; pytest's summary counts each test once per outcome kind, as the merged ids do.
    recounted = outcome_counts(merged_outcomes(cases))
    number = lambda key: int(counts.get(key, 0) or 0)  # noqa: E731
    # JUnit writes an xfail as a skip and a (non-strict) xpass as a pass.
    summary = {"passed": number("passed") + number("xpassed"), "failed": number("failed"), "error": number("errors"),
               "skipped": number("skipped") + number("xfailed")}
    if summary != recounted:
        return Collection(False, [f"the suite's summary counts {summary}, its JUnit file's tests {recounted}"])
    if len(merged_outcomes(cases)) != len(cases) and not any(_is_red(case.outcome) for case in cases):
        return Collection(False, ["its JUnit file lists a passing test more than once"])
    complete, why = deselection_accounted(counts, selection, _relative(target, cwd))
    return Collection(complete, [why] if why else [])


def read_any(kind: str, path: Path) -> Reading:
    """The reader for an evidence kind; kinds with no readable result return an empty reading."""

    if not path.is_file():
        return Reading()
    if kind == "log":
        return read_log(path)
    if kind == "audit":
        return read_audit(path)
    if kind == "gate_report":
        report = read_gate_report(path)
        return Reading() if report is None else gate_report_reading(report)
    if kind == "junit":
        cases = junit_cases(path)
        if cases is None:
            return Reading()
        totals = {outcome: sum(1 for case in cases if case.outcome == outcome) for outcome in ("passed", "skipped")}
        totals["red"] = sum(1 for case in cases if case.outcome not in ("passed", "skipped"))
        return Reading(junit_result(cases), None, totals)
    return Reading()


def junit_path_of(suite: Mapping[str, Any]) -> str | None:
    """The ``--junitxml=`` a gate suite was run with (the gate appends it to the suite's argv)."""

    for argument in suite.get("argv") or []:
        if isinstance(argument, str) and argument.startswith("--junitxml="):
            return argument.split("=", 1)[1]
    return None
