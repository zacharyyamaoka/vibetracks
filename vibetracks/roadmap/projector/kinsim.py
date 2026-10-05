"""project_kinsim: bam-roadmap/1 from the kinsim curriculum loop's own files, read-only.

Reads (and never writes): ``curriculum.json``, ``triage.json``, ``tiers.json``, the ruler it names, and
in the data home ``status.json`` (the fold's cache), ``runs.jsonl`` (the ledger), ``runs/<id>/batch.json``
and ``episodes.jsonl``, ``loop_events.jsonl``; plus each gate run's ``gate_report.json`` and JUnit
files, every log or audit an event cites, and git.

How each gate kind becomes ``done_when`` (ROADMAP.md §1 "Rules every rung follows"):

- std / throughput / ratchet: ``gate_run`` over the ledger rows themselves (a second implementation
  beside the fold, so a hand-edited ``status.json`` cannot carry a green), plus the latest ``fast``
  gate;
- infra: ``test`` over ``gate.acceptance``;
- same_as: ``alias`` of the named rung; none: the baseline, ``done`` resting on an ``inspection``;
- every rung with prerequisites: ``prerequisites`` (Codex F03, for every kind);
- a condition an infra gate states in a sentence this format recognises becomes typed and is checked
  against the data the loop recorded (Codex G09): ``no in_domain Codex blocker or major left on X``
  is an ``audit`` resting on the audit report the rung's status event cites; ``identical
  verdict_hash over N judged MODE-mode runs at V m/s`` rests on those ledger rows;
- any other sentence that says more than the gate's fields becomes a ``stated`` criterion that stays
  unknown until the loop declares it (Codex F11).

Every target carries its freshness ``scope`` and the ruler ``context``. An acceptance test's scope is
its package, its declared dependencies and its import closure (``scope.CodeIndex.scope``); a measured
reading's is the producer command's execution path plus the scorer the judge calls (Codex G08), stored
once in the document's ``scopes`` and named ``@producer``. Every verdict comes from
``evaluate.Evaluator``; the validator checks a document by projecting again.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import artifacts, links, model, proof
from .evaluate import (Binding, Evaluator, Judgement, RulerAt, artifact_commit, capped, case_keys, gated_window,
                       tier_definition_at, window_specs)
from .files import LINE_KEY, ProjectionError, canonical_sha256, file_sha256, read_json, read_json_quiet, read_jsonl
from .gitinfo import Repo
from .links import EvidenceBook, Roots
from .scope import CodeIndex, command_entry

MEASURED_KINDS = ("std", "throughput", "ratchet")
RUN_EVIDENCE_LIMIT = 12
WITNESS_CODES = 4
FAST_TIER = "fast"
PRODUCER_SCOPE = "@producer"  # a target scope entry that stands for the document's scopes["producer"]
_REVIEW_WORDS = re.compile(r"\b(?:Codex|audit|VERDICT|SHIP)\b")
# WHY recognised sentences, not free parsing (Codex G09): each is a shape this loop actually writes, mapped to
# a predicate over data it records; any other prose stays a stated condition, unknown until declared.
_CONDITIONS = (
    ("audit", re.compile(r"(?:,?\s*with\s+)?\bno in_domain (?P<reviewer>Codex) blocker or major left on (?P<subject>[\w.-]+)")),
    ("determinism", re.compile(r"\bidentical verdict_hash over (?P<runs>\d+) judged (?P<mode>[a-z]+)-mode runs at "
                               r"(?P<speed>\d+(?:\.\d+)?) m/s")),
)
# "(w3-b1, T36)" and "(T41; the B1/L1 audit failed a2-v1)": where a clause came from, never a condition.
_REFERENCE_NOTE = re.compile(r"\s*\((?:[A-Za-z]*\d[\w.-]*(?:,\s*[A-Za-z]*\d[\w.-]*)*|T\d+;[^()]*)\)")
_PIECES = re.compile(r",|;|\band\b|\bplus\b")
_AUDIT_LINK = re.compile(r"\]\((/[^)\s]+?)(?::\d+(?:-\d+)?)?\)")


@dataclass
class Condition:
    """A condition an infra gate states in a sentence this format recognises (Codex G09)."""

    kind: str
    text: str
    fields: dict[str, str]


def split_gate_text(text: str) -> tuple[list[Condition], str, bool]:
    """``(recognised conditions, what is left, is what is left only the acceptance?)`` for an infra gate text.

    What is left is "only the acceptance" when every clause names acceptance suites ("B1 + L1 acceptance",
    "ruler a2-v2's acceptance and its physical-envelope acceptance", "lane w1-log-replay acceptance"),
    once reference notes are dropped. WHY that strict (Codex F11): VZ1's "3 runs in a row" or RG1's "an
    unexpected red and an unexpected green both exit 1" are conditions the acceptance files may or may not
    check; this format does not guess which, the loop declares it.
    """

    conditions: list[Condition] = []
    rest = text or ""
    for kind, pattern in _CONDITIONS:
        conditions += [Condition(kind, match.group(0).strip(" ,"), {key: value for key, value in match.groupdict().items() if value})
                       for match in pattern.finditer(rest)]
        rest = pattern.sub(" ", rest)
    rest = _REFERENCE_NOTE.sub(" ", rest)
    body = re.sub(r"^\s*infra:\s*", "", rest).strip(" ,;")
    pieces = [piece.strip() for piece in _PIECES.split(body) if piece.strip()]
    acceptance_only = all(piece.lower().endswith("acceptance") and "(" not in piece and ")" not in piece for piece in pieces)
    return conditions, body, acceptance_only


# ---------------------------------------------------------------- gate runs (JUnit records)
@dataclass
class GateRun:
    """One ``gate_run`` event and the test-level record its report left, if it still exists."""

    event: Mapping[str, Any]
    console: list[links.Citation] = field(default_factory=list)
    report_raw: str | None = None
    report: Mapping[str, Any] | None = None
    files: dict[str, list[artifacts.JunitCase]] = field(default_factory=dict)  # repository-relative test file -> its cases
    junit_of_file: dict[str, str] = field(default_factory=dict)
    suite_dir_of_file: dict[str, str] = field(default_factory=dict)
    suite_of_file: dict[str, str] = field(default_factory=dict)
    head_log: str | None = None  # a console log whose own HEAD line records the run's commit
    binding: Binding = field(default_factory=lambda: Binding(None, None))

    @property
    def ts(self) -> str | None:
        return self.event.get("ts")

    @property
    def commit(self) -> str | None:
        return self.binding.commit

    @property
    def commit_source(self) -> str | None:
        return self.binding.source


def load_gate_runs(events: Sequence[Mapping[str, Any]], repo: Repo, roots: Roots) -> list[GateRun]:
    runs = []
    for event in events:
        if event.get("kind") != "gate_run":
            continue
        gate_run = GateRun(event)
        for citation in links.cited_paths(event.get("evidence")):
            kind = links.classify(citation.raw)
            if kind == "gate_report":
                gate_run.report_raw = gate_run.report_raw or citation.raw
            elif kind == "log":
                gate_run.console.append(citation)
                if Path(citation.raw).is_file():
                    pointer = artifacts.read_log(Path(citation.raw)).pointer
                    if pointer and gate_run.report_raw is None:
                        gate_run.report_raw = pointer
                    if gate_run.head_log is None and _has_head_line(Path(citation.raw)):
                        gate_run.head_log = citation.raw
        if gate_run.report_raw and Path(gate_run.report_raw).is_file():
            gate_run.report = artifacts.read_gate_report(Path(gate_run.report_raw))
        if gate_run.report:
            _index_junit(gate_run, repo)
        runs.append(gate_run)
    return runs


def _index_junit(gate_run: GateRun, repo: Repo) -> None:
    report_root = str(gate_run.report.get("root") or "")
    for suite in gate_run.report.get("suites") or []:
        junit_raw = artifacts.junit_path_of(suite)
        if not junit_raw or not Path(junit_raw).is_file():
            continue
        cwd = str(suite.get("cwd") or "")
        suite_dir = os.path.relpath(cwd, report_root) if report_root and cwd.startswith(report_root) else cwd
        for case in artifacts.junit_cases(Path(junit_raw)) or ():
            test_file, _class_name = links.junit_file_for(case.classname, suite_dir, lambda relative: (repo.root / relative).is_file())
            if test_file is None:
                continue
            gate_run.files.setdefault(test_file, []).append(case)
            gate_run.junit_of_file[test_file] = junit_raw
            gate_run.suite_dir_of_file[test_file] = suite_dir
            gate_run.suite_of_file[test_file] = str(suite.get("suite"))


def _has_head_line(path: Path) -> bool:
    return artifact_commit(path)[0] is not None


# ---------------------------------------------------------------- the projection
@dataclass
class KinsimInputs:
    curriculum_dir: Path
    data_home: Path
    curriculum: Mapping[str, Any]
    triage: Mapping[str, Any]
    status: Mapping[str, Any]
    ledger: list[dict]
    events: list[dict]
    answers: list[dict]
    ruler_sha256: str | None
    ruler_path: Path


def read_inputs(curriculum_dir: Path, data_home: Path) -> KinsimInputs:
    curriculum_dir, data_home = Path(curriculum_dir).resolve(), Path(data_home).expanduser().resolve()
    curriculum = read_json(curriculum_dir / "curriculum.json")
    if curriculum.get("schema") != "bam-curriculum/1":
        raise ProjectionError(f"{curriculum_dir / 'curriculum.json'} is {curriculum.get('schema')!r}, not bam-curriculum/1")
    status_path = data_home / "status.json"
    status = read_json(status_path) if status_path.exists() else {"rungs": []}
    ruler_path = curriculum_dir / str(curriculum.get("ruler") or "")
    ruler_sha = canonical_sha256(read_json(ruler_path)) if ruler_path.is_file() else None
    triage_path = curriculum_dir / "triage.json"
    return KinsimInputs(
        curriculum_dir=curriculum_dir, data_home=data_home, curriculum=curriculum,
        triage=read_json(triage_path) if triage_path.exists() else {"items": []},
        status=status, ledger=read_jsonl(data_home / "runs.jsonl", numbered=True),
        events=read_jsonl(data_home / "loop_events.jsonl", numbered=True),
        answers=read_jsonl(data_home / "triage_answers.jsonl"), ruler_sha256=ruler_sha, ruler_path=ruler_path,
    )


def project_kinsim(curriculum_dir: Path, data_home: Path, *, now: str, head: str | None = None) -> dict[str, Any]:
    """bam-roadmap/1 for the kinsim curriculum, judged at ``head`` (default: the checkout's HEAD)."""

    inputs = read_inputs(curriculum_dir, data_home)
    repo = Repo(inputs.curriculum_dir, head)
    if not repo.available:
        raise ProjectionError(f"{inputs.curriculum_dir} is not inside a git checkout")
    roots = Roots(repo=repo.root, data_home=inputs.data_home, repo_aliases=repo.other_checkouts())
    return _Projector(inputs, repo, roots).document(now)


def gate_text_is_represented(rung: Mapping[str, Any], corpora: Mapping[str, Mapping[str, Any]]) -> bool:
    """Does the rung's ``gate_text`` say anything its structured gate does not? (Codex F11)

    Represented: an empty text, the kind word alone, the canonical summary of a measured gate's own
    fields, ``ratchet on <metric>``, ``same_as <rung>``, an infra text that only names acceptance,
    or a gate that declares ``text_is_covered: true`` (the loop-side declaration this format proposes).
    """

    gate = rung["gate"]
    text = (rung.get("gate_text") or "").strip()
    kind = gate.get("kind")
    if gate.get("text_is_covered") is True or text in ("", "—", "-"):
        return True
    if kind == "infra":
        return split_gate_text(text)[2]
    if kind in MEASURED_KINDS:
        if text == kind or (kind == "ratchet" and text == f"ratchet on {gate.get('metric')}"):
            return True
        return text == _canonical_measured(gate, corpora)
    if kind == "same_as":
        return text == f"same_as {gate.get('rung')}"
    return False


def _canonical_measured(gate: Mapping[str, Any], corpora: Mapping[str, Mapping[str, Any]]) -> str | None:
    promotion = corpora.get(str(gate.get("promotion_corpus"))) or {}
    regression = corpora.get(str(gate.get("regression_corpus"))) or {}
    budget = (promotion.get("latency") or {}).get("budget_s")
    if not promotion or not regression or budget is None:
        return None
    return (f"{gate['kind']}: regression {regression.get('count')} + promotion {promotion.get('count')} of "
            f"{promotion.get('producer_corpus_id')} · {promotion.get('scenario')}, budget {float(budget)} s")


class _Projector:
    def __init__(self, inputs: KinsimInputs, repo: Repo, roots: Roots) -> None:
        self.inputs, self.repo, self.roots = inputs, repo, roots
        self.curriculum = inputs.curriculum
        self.rungs_by_id = {rung["rung_id"]: rung for rung in self.curriculum["rungs"]}
        self.fold_rows = {row["rung_id"]: row for row in inputs.status.get("rungs") or []}
        self.corpora = {corpus["corpus_id"]: corpus for corpus in self.curriculum.get("corpora") or []}
        self.curriculum_path = inputs.curriculum_dir / "curriculum.json"
        self.curriculum_rel = self.curriculum_path.relative_to(repo.root).as_posix()
        self.roadmap_path = inputs.curriculum_dir / "ROADMAP.md"
        self.events = proof.EventLog(inputs.data_home / "loop_events.jsonl", roots, rows=inputs.events)
        self.code = CodeIndex(repo)
        self.evaluator = Evaluator(repo, roots, ruler_at=RulerAt(repo, self.curriculum_rel))
        # WHY every kinsim criterion carries the ruler (Codex F08): a pin move changes what "pass" means
        # for anything judged; until the curriculum declares which rungs are ruler-independent, a proof
        # made under another ruler reads stale. Reversible: re-running the acceptance refreshes it.
        self.context = {"ruler_sha256": inputs.ruler_sha256} if inputs.ruler_sha256 else {}
        self.judged_run_events = {str(event.get("subject")): event for event in inputs.events if event.get("kind") == "judged_run"}
        self.superseded: dict[str, dict[str, str | None]] = {}
        self.gate_runs = load_gate_runs(inputs.events, repo, roots)
        for gate_run in self.gate_runs:
            gate_run.binding = self.evaluator.gate_run_binding(
                {"console": self._console(gate_run), "report": gate_run.report_raw}, gate_run.event.get("commit"))
        self.ledger_rows, self.conflicting_runs = self._dedupe_ledger(inputs.ledger)
        self.tiers = read_json_quiet(inputs.curriculum_dir / "tiers.json") or {}
        self.tiers_rel = (inputs.curriculum_dir / "tiers.json").relative_to(repo.root).as_posix()
        acceptance = [path for rung in self.curriculum["rungs"] for path in rung["gate"].get("acceptance") or []]
        self.scopes = {target: self.code.scope(target) for target in sorted(set(acceptance))}
        self.test_index = proof.TestIndex(roots, acceptance, self.events)
        self._index_junit_proofs()
        for event in inputs.events:
            self.test_index.add_event(event, origin="event")
        fast_cwds = [str(suite.get("cwd") or "") for suite in ((self.tiers.get("tiers") or {}).get(FAST_TIER) or [])]
        self.fast_scope = self.code.folders_scope(fast_cwds)
        self.measured_scope = self._measured_scope()
        self.rung_index = {rung["rung_id"]: index for index, rung in enumerate(self.curriculum["rungs"])}
        self.derived: dict[str, dict[str, Any]] = {}
        self.scope_roots = self._scope_roots()

    # ------------------------------------------------------------ document
    def document(self, now: str) -> dict[str, Any]:
        for rung in self.curriculum["rungs"]:
            self._rung(rung["rung_id"], ())
        rungs = [self.derived[rung["rung_id"]] for rung in self.curriculum["rungs"]]
        axes = [{"id": axis["axis_id"], "title": axis["title"], "order": axis.get("order", index)}
                for index, axis in enumerate(sorted(self.curriculum["axes"], key=lambda axis: axis.get("order", 0)))]
        edges = []
        for rung in self.curriculum["rungs"]:
            edges += [{"from": parent, "to": rung["rung_id"], "kind": "prerequisite", "via": None} for parent in rung["prerequisites"]]
            if rung["gate"]["kind"] == "same_as":
                edges.append({"from": rung["gate"].get("rung"), "to": rung["rung_id"], "kind": "same_as", "via": None})
        status = self.inputs.status
        return {
            "schema": model.SCHEMA_ID,
            "loop": "kinsim",
            "title": "Kinsim curriculum",
            "generated_at": now,
            "as_of": {"head": self.repo.head, "branch": self.repo.branch,
                      "context": {"ruler_id": Path(str(self.curriculum.get("ruler") or "")).stem or None,
                                  "ruler_sha256": self.inputs.ruler_sha256, "ruler_via": self.curriculum_rel}},
            "roots": self.roots.as_dict(),
            "sources": self._sources(),
            "rules": {"proof_strengths": list(model.PROOF_STRENGTHS),
                      "status_rule": "bam_roadmap.model.derive_status",
                      "loop_rules": proof.source_link(self.roadmap_path, self.roots, "### Rules every rung follows", "")},
            "summary": {"wave": status.get("wave"), "phase": status.get("phase"), "frontier": status.get("frontier") or [],
                        "milestone": None, "links": {}},
            "counts": proof.counts(rungs),
            "warnings": self._warnings(),
            "axes": axes,
            "where": proof.where_rows(axes, rungs),
            "rungs": rungs,
            "edges": edges,
            "work": self._work(),
            "unresolved": proof.unresolved_list(rungs),
            "scopes": {PRODUCER_SCOPE[1:]: self.measured_scope},
        }

    def _measured_scope(self) -> list[str]:
        """What a measured reading depends on (Codex G08): the producer command's execution path, the scorer the loop's
        judge calls, and the producer's environment.

        WHY not whole packages: a reading ran one command (``kinematic-pick run``) and was scored by bam_eval's
        score_log / fold_batch; a change to the replay viewer, another subcommand, or the loop's own bookkeeping
        (schemas, events, ledger plumbing in bam_curriculum) cannot change the verdicts it recorded, and staling it
        for one would tell Zach "no proof" where the loop recorded one. The ruler is checked as context, and the
        corpus definition through the run's manifest. Reversible: a narrower or wider scope is one function.
        """

        producer = self.curriculum.get("producer") or {}
        cwd = str(producer.get("cwd") or "")
        module, words = command_entry([str(token) for token in producer.get("argv") or []])
        files: set[str] = set()
        if module and cwd:
            files |= self.code.execution_closure(self.code.entry_files(module, cwd), words)
        judge = self.inputs.curriculum_dir / "bam_curriculum" / "judge.py"
        loop_package = PurePosixPath(self.curriculum_rel).parent.as_posix()
        if judge.is_file():
            judge_rel = judge.relative_to(self.repo.root).as_posix()
            files |= self.code.execution_closure(self.code.external_imports(judge_rel, loop_package), None)
        if not files:
            return self.code.folders_scope([cwd])  # nothing could be traced: the whole producer package, the safe side
        root = self.code.package_root(f"{cwd}/x") or cwd
        environment = [f"{root}/{name}" for name in ("pyproject.toml", "uv.lock") if f"{root}/{name}" in self.code.tracked]
        return sorted(set(self.code.compress(files)) | set(environment))

    def expand_scope(self, scope: Sequence[str]) -> list[str]:
        return [path for entry in scope for path in (self.measured_scope if entry == PRODUCER_SCOPE else [entry])]

    def _sources(self) -> list[dict[str, Any]]:
        files = [(self.curriculum_path, "curriculum"), (self.inputs.curriculum_dir / "triage.json", "triage"),
                 (self.inputs.ruler_path, "ruler"), (self.inputs.data_home / "status.json", "status fold (cache)"),
                 (self.inputs.data_home / "runs.jsonl", "ledger"), (self.inputs.data_home / "loop_events.jsonl", "loop events"),
                 (self.inputs.data_home / "triage_answers.jsonl", "triage answers")]
        rows = []
        for path, role in files:
            entry = links.link("file", str(path), self.roots)
            entry.update({"role": role, "sha256": file_sha256(path) if path.is_file() else None})
            rows.append(entry)
        return rows

    def _warnings(self) -> list[str]:
        warnings = []
        status = self.inputs.status
        if not status.get("rungs"):
            warnings.append("status.json is missing: every claimed status reads missing")
        if status.get("ruler_sha256") and status.get("ruler_sha256") != self.inputs.ruler_sha256:
            warnings.append(f"status.json was folded under ruler {str(status.get('ruler_sha256'))[:12]}, "
                            f"the curriculum names {str(self.inputs.ruler_sha256)[:12]}: the fold's claims are stale")
        if status.get("ledger_rows_seen") is not None and status.get("ledger_rows_seen") != len(self.inputs.ledger):
            warnings.append(f"status.json saw {status.get('ledger_rows_seen')} ledger rows, runs.jsonl has {len(self.inputs.ledger)}")
        if self.conflicting_runs:
            warnings.append(f"conflicting ledger rows for {', '.join(sorted(self.conflicting_runs))}")
        for rung in self.curriculum["rungs"]:
            latest = self.events.latest_status_event(rung["rung_id"])
            folded = (self.fold_rows.get(rung["rung_id"]) or {}).get("status")
            if rung["gate"]["kind"] == "infra" and latest is not None and folded is not None and latest.get("status") != folded:
                warnings.append(f"{rung['rung_id']}: status.json says {folded}, but its latest status event "
                                f"(loop_events.jsonl line {latest.get(LINE_KEY)}) says {latest.get('status')}; the event governs")
        return warnings

    def _scope_roots(self) -> list[str]:
        """The loop's own package folders: where its acceptance files live and where its gate suites run."""

        roots = set()
        for rung in self.curriculum["rungs"]:
            for path in rung["gate"].get("acceptance") or []:
                parts = path.split("/tests/", 1)
                roots.add(parts[0] if len(parts) == 2 else str(Path(path).parent))
        for suites in (self.tiers.get("tiers") or {}).values():
            for suite in suites:
                cwd = str(suite.get("cwd") or "")
                roots.add(cwd[:-4] if cwd.endswith("/src") else cwd)
        return sorted(root for root in roots if root)

    # ------------------------------------------------------------ JUnit records as candidates
    def _index_junit_proofs(self) -> None:
        """One candidate per (gate run, acceptance file).

        WHY no cases pooled from other runs (Codex G06): what a run had to cover is its own recorded collection
        (the suite's argv and summary, ``artifacts.suite_collection``), never what earlier runs happened to execute.
        """

        targets = set(self.test_index.targets)
        for gate_run in self.gate_runs:
            for target in sorted(targets & set(gate_run.files)):
                self.test_index.add(self._junit_proof(gate_run, target))

    def _junit_proof(self, gate_run: GateRun, target: str) -> proof.Proof:
        cases = gate_run.files[target]
        functions = links.test_functions(self.repo.root / target)
        lines = {function.key: function.line for function in functions}
        keys = case_keys(cases)
        shown = [{"node_id": links.node_id(target, key), "line": lines.get(key.split("[", 1)[0]), "outcome": case.outcome}
                 for key, case in sorted(zip(keys, cases), key=lambda pair: pair[0])]
        totals = {"passed": sum(1 for case in cases if case.outcome == "passed"),
                  "skipped": sum(1 for case in cases if case.outcome == "skipped"),
                  "red": sum(1 for case in cases if case.outcome not in ("passed", "skipped"))}
        result = artifacts.junit_result(cases)
        tier = gate_run.event.get("subject")
        reference = self.events.ref(gate_run.event)
        junit_raw = gate_run.junit_of_file[target]
        junit_item = links.link("junit", junit_raw, self.roots)
        console = self._console(gate_run)
        # WHY the binding caps the strength (Codex G04, H02): a run belongs to a commit only when a record it wrote
        # says so (its console's HEAD line, its report's git); a dirty or citation-only run is no commit anyone can check out.
        strength = capped("record", gate_run.commit_source)
        run_facts = {"report": gate_run.report_raw, "suite": gate_run.suite_of_file[target], "console": console}
        junit_payload = {**junit_item, "result": artifacts.read_any("junit", Path(junit_raw)).result if junit_item["exists"] else None,
                         "strength": strength, "commit": gate_run.commit, "ts": gate_run.ts, "origin": "gate_report",
                         "facts": {"tier": tier, **run_facts}, "as_cited": None,
                         "event": reference, "commit_source": gate_run.commit_source}
        test_item = links.link("test", target, self.roots, line=min(lines.values()) if lines else None)
        payload = {**test_item, "label": f"{test_item['label']} (JUnit, {tier} gate at {(gate_run.commit or '?')[:8]})",
                   "result": result, "strength": strength, "commit": gate_run.commit, "ts": gate_run.ts, "origin": "junit",
                   "facts": {**totals, "suite_dir": gate_run.suite_dir_of_file[target], **run_facts},
                   "cases": shown, "as_cited": None, "event": reference, "commit_source": gate_run.commit_source}
        return proof.Proof(target, payload, ("junit-test", target, gate_run.commit, gate_run.ts, reference and reference["line"]),
                           f"JUnit from the {tier} gate run (events line {reference and reference['line']})",
                           via=(junit_payload, ("junit", junit_raw)))

    def _console(self, gate_run: GateRun) -> dict[str, Any] | None:
        """``{path, base}`` of the console log whose own HEAD line records the run's commit, if one does."""

        if gate_run.head_log is None:
            return None
        found = links.link("log", gate_run.head_log, self.roots)
        return {"path": found["path"], "base": found["base"]}

    # ------------------------------------------------------------ ledger
    @staticmethod
    def _dedupe_ledger(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], set[str]]:
        """First row per run id, in ledger order; a run id whose rows differ is conflicting (the fold's rule)."""

        first: dict[Any, Mapping[str, Any]] = {}
        conflicting = set()
        for row in rows:
            run_id = row.get("run_id")
            if run_id in first:
                if _without_line(row) != _without_line(first[run_id]):
                    conflicting.add(str(run_id))
                continue
            first[run_id] = row
        return list(first.values()), conflicting

    def _readings(self, rung_id: str) -> list[Mapping[str, Any]]:
        return [row for row in self.ledger_rows if (row.get("metrics") or {}).get("rung_id") == rung_id]

    # ------------------------------------------------------------ one rung
    def _claimed(self, rung_id: str, kind: str) -> tuple[str, Mapping[str, Any] | None]:
        """The loop's own word: the fold's, unless a later status event revokes it (Codex F02).

        For an infra rung the latest status event IS the word (the fold follows it); for any other
        rung a status event can only lower the fold's word, never raise it.
        """

        fold_row = self.fold_rows.get(rung_id) or {}
        folded = fold_row.get("status") if fold_row.get("status") in model.CLAIMED_STATUSES else "missing"
        latest = self.events.latest_status_event(rung_id)
        if latest is None:
            return folded, None
        if kind == "infra":
            return str(latest.get("status")), latest
        return model.lowest_claim(folded, latest.get("status")), latest

    def _rung(self, rung_id: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if rung_id in self.derived:
            return self.derived[rung_id]
        if rung_id in stack:
            raise ProjectionError(f"curriculum cycle through {rung_id}")
        rung = self.rungs_by_id[rung_id]
        gate = rung["gate"]
        for parent in rung["prerequisites"]:
            if parent in self.rungs_by_id:
                self._rung(parent, (*stack, rung_id))
        if gate["kind"] == "same_as" and gate.get("rung") in self.rungs_by_id:
            self._rung(gate["rung"], (*stack, rung_id))

        book = EvidenceBook()
        index = self.rung_index[rung_id]
        gate_source = proof.source_link(self.curriculum_path, self.roots, f'"rung_id": "{rung_id}"', f"/rungs/{index}/gate")
        fold_row = self.fold_rows.get(rung_id) or {}
        kind = gate["kind"]
        claimed, claiming_event = self._claimed(rung_id, kind)
        history = proof.history(book, self.events, rung_id, self.roots)

        text = rung.get("gate_text") or ""
        if kind in MEASURED_KINDS:
            criteria = [self._gate_criterion(rung, book, gate_source), self._fast_gate_criterion(rung, book)]
        elif kind == "infra":
            criteria = [self._infra_criterion(rung, book, gate_source)]
            if gate.get("text_is_covered") is not True:
                conditions, remainder, _acceptance_only = split_gate_text(text)
                for condition in conditions:
                    criteria.append(self._audit_criterion(rung, condition, book, gate_source) if condition.kind == "audit"
                                    else self._determinism_criterion(rung, condition, book, gate_source))
                text = remainder
        elif kind == "same_as":
            criteria = [self._alias_criterion(rung, gate_source)]
        else:
            criteria = self._baseline_criteria(rung, book)
        if rung["prerequisites"]:
            criteria.append(self._prerequisites_criterion(rung, gate_source))
        if not gate_text_is_represented(rung, self.corpora) and not (kind == "none" and (rung.get("baseline") or {}).get("status") == "done"):
            criteria.append(proof.stated_criterion(criterion_id=f"{rung_id}#stated", text=text, source=gate_source,
                                                   audit=_REVIEW_WORDS.search(text) is not None))

        status, reason = model.derive_status(claimed, criteria)
        baseline = rung.get("baseline") or {}
        last = fold_row.get("last_reading") or None
        kpis = []
        if last:
            for name, unit in (("feasible_rate", "ratio"), ("recovery", "ratio"), ("ppm", "picks/min"), ("compute_s_p95", "s")):
                if last.get(name) is not None:
                    kpis.append({"name": name, "value": last.get(name), "unit": unit, "run": last.get("run_id"), "ts": last.get("ts")})
        fold_index = next((position for position, row in enumerate(self.inputs.status.get("rungs") or [])
                           if row.get("rung_id") == rung_id), None)
        # WHY claimed_by names the exact row and event (Codex A06 on the frontend, F02 here): a later
        # partial event revokes an earlier green, and no viewer may print "green at <the revoking commit>".
        claimed_by = {
            "source": proof.source_link(self.inputs.data_home / "status.json", self.roots, f'"rung_id": "{rung_id}"',
                                        f"/rungs/{fold_index}" if fold_index is not None else ""),
            "event": self.events.ref(claiming_event),
        }
        self.derived[rung_id] = {
            "id": rung_id,
            "axis": rung["axis_id"],
            "title": rung["title"],
            "adds": rung.get("adds") or None,
            "order": index,
            "wave": rung.get("wave"),
            "depends_on": list(rung["prerequisites"]),
            "alias_of": gate.get("rung") if kind == "same_as" else None,
            "status": status,
            "claimed_status": claimed,
            "status_reason": reason,
            "claimed_by": claimed_by,
            "frontier": rung_id in (self.inputs.status.get("frontier") or []),
            "done_when": {"rule": "alias" if kind == "same_as" else ("all" if criteria else "none"),
                          "text": rung.get("gate_text") or "", "source": gate_source},
            "criteria": criteria,
            "support": None,
            "evidence": book.items,
            "history": history,
            "blockers": proof.blockers_from_triage(self.inputs.triage, rung_id, fold_row.get("blocking_triage") or [],
                                                   self.roots, str(self.inputs.curriculum_dir / "triage.json")),
            "kpis": kpis,
            "notes": [text for text in (baseline.get("note"),) if text],
            "x": {"gate_kind": kind, "gate": gate, "kpi_weight": rung.get("kpi_weight"), "est_waves": rung.get("est_waves"),
                  "cell": rung.get("cell") or {}, "baseline": baseline, "fold_reason": fold_row.get("reason"),
                  "fold_status": fold_row.get("status"), "readings": fold_row.get("readings"),
                  "green_since_run_id": fold_row.get("green_since_run_id")},
        }
        proof.finish_rung(self.derived[rung_id], book, self.superseded.get(rung_id))
        return self.derived[rung_id]

    # ------------------------------------------------------------ infra: acceptance tests
    def _infra_criterion(self, rung: Mapping[str, Any], book: EvidenceBook, source: dict) -> dict[str, Any]:
        targets = list(rung["gate"].get("acceptance") or [])
        return proof.test_criterion(criterion_id=f"{rung['rung_id']}#acceptance", title="acceptance tests pass",
                                    text=rung.get("gate_text") or "", source=source, targets=targets, index=self.test_index,
                                    evaluator=self.evaluator, book=book, roots=self.roots,
                                    scopes={target: self.scopes[target] for target in targets}, context=self.context)

    # ------------------------------------------------------------ same_as, none, prerequisites
    def _alias_criterion(self, rung: Mapping[str, Any], source: dict) -> dict[str, Any]:
        target_id = rung["gate"].get("rung")
        target_status = self.derived[target_id]["status"] if target_id in self.derived else "missing"
        verdict, strength = model.alias_verdict(target_status)
        target = proof.rung_target(target_id, target_status, target_id in self.derived)
        return proof.criterion(criterion_id=f"{rung['rung_id']}#alias", kind="alias", method=None,
                               title=f"same gate as {target_id}", text=rung.get("gate_text") or "", source=source,
                               targets=[target], verdict=verdict, strength=strength,
                               reason=f"follows {target_id}, which is {target_status}", evidence=[])

    def _prerequisites_criterion(self, rung: Mapping[str, Any], source: dict) -> dict[str, Any]:
        statuses = {parent: self.derived[parent]["status"] if parent in self.derived else "missing" for parent in rung["prerequisites"]}
        verdict, strength, reason = model.prerequisites_verdict(statuses)
        targets = [proof.rung_target(parent, status, parent in self.derived) for parent, status in statuses.items()]
        return proof.criterion(criterion_id=f"{rung['rung_id']}#prerequisites", kind="prerequisites", method=None,
                               title="every prerequisite green", text="every prerequisite is green or done",
                               source=source, targets=targets, verdict=verdict, strength=strength, reason=reason, evidence=[])

    def _baseline_criteria(self, rung: Mapping[str, Any], book: EvidenceBook) -> list[dict[str, Any]]:
        """A none-gate rung: ``done`` rests on an inspection of the code its baseline cites; otherwise nothing to verify."""

        baseline = rung.get("baseline") or {}
        if baseline.get("status") != "done":
            return []
        index = self.rung_index[rung["rung_id"]]
        source = proof.source_link(self.curriculum_path, self.roots, f'"rung_id": "{rung["rung_id"]}"', f"/rungs/{index}/baseline")
        tracked = self.repo.tracked_files()
        targets = []
        references = links.bare_code_references(baseline.get("evidence"))
        first_pass = [links.resolve_bare_name(name, before, tracked, self.scope_roots)[0] for name, _l, _e, before in references]
        neighbours = [path for path in first_pass if path]
        for name, line, end_line, before in references:
            relative, how = links.resolve_bare_name(name, before, tracked, self.scope_roots, neighbours)
            label = f"{name}:{line}" if line else name
            if relative is None:
                target = {**links.link("file", None, self.roots, label=label), "why_unresolved": how}
                targets.append(proof.target_entry(target, Judgement("unknown", None, [], how), []))
                continue
            target = links.link("file", relative, self.roots, label=label, line=line, end_line=end_line)
            item = {**target, "result": "passed" if target["exists"] else None, "strength": "record" if target["exists"] else "claim",
                    "commit": self.repo.head, "ts": None, "origin": "curriculum", "facts": {"resolved_by": how},
                    "as_cited": None, "event": None, "commit_source": "artifact"}
            evidence_id = book.add(item, key=("baseline", relative, line))
            judgement = self.evaluator.judge_inspection(item)
            targets.append(proof.target_entry(target, judgement, [evidence_id]))
        return [proof.reduce(f"{rung['rung_id']}#baseline", "inspection", "inspection", "the existing code it cites",
                             baseline.get("evidence") or "", source, targets, empty_reason="the baseline cites no code")]

    # ------------------------------------------------------------ the fast gate
    def _fast_gate_criterion(self, rung: Mapping[str, Any], book: EvidenceBook) -> dict[str, Any]:
        source = proof.source_link(self.roadmap_path, self.roots, "The fast gate is green", "")
        fast_runs = [gate_run for gate_run in self.gate_runs if gate_run.event.get("subject") == FAST_TIER]
        if not fast_runs:
            return proof.reduce(f"{rung['rung_id']}#fast-gate", "gate_run", "test", "the fast gate is green", "", source, [],
                                empty_reason="no fast gate run recorded")
        latest = fast_runs[-1]
        reference = self.events.ref(latest.event)
        candidates: list[dict[str, Any]] = []
        for citation in latest.console:
            candidates.append(proof.cited_item(citation, self.roots, commit=latest.event.get("commit"), ts=latest.ts,
                                               origin="event", event=reference))
        definition = tier_definition_at(self.repo, self.tiers_rel, FAST_TIER, latest.commit or latest.event.get("commit"))
        if latest.report_raw:
            report_link = links.link("gate_report", latest.report_raw, self.roots)
            report = artifacts.read_gate_report(Path(latest.report_raw)) if report_link["exists"] else None
            reading = artifacts.gate_report_reading(report, definition) if report is not None else artifacts.Reading()
            candidates.append({**report_link, "result": reading.result,
                               "strength": capped("record" if reading.result else "claim", latest.commit_source),
                               "commit": latest.commit, "ts": latest.ts, "origin": "gate_report",
                               "facts": {**reading.facts, "console": self._console(latest)},
                               "as_cited": None, "event": reference, "commit_source": latest.commit_source})
        event_status = latest.event.get("status")
        candidates.append(proof.statement_item(f"gate_run {event_status}: {latest.event.get('evidence') or ''}",
                                               result="passed" if event_status == "pass" else ("failed" if event_status == "fail" else None),
                                               commit=latest.event.get("commit"), ts=latest.ts, origin="event", event=reference))
        expected = [str(suite.get("suite")) for suite in definition] if definition is not None else None
        judged = [(candidate, self.evaluator.judge_gate(candidate, FAST_TIER, self.fast_scope, self.context, tier_definition=definition))
                  for candidate in candidates]
        # WHY any red artifact decides: one run of the gate either passed or not; a sentence saying "pass"
        # beside a report that says otherwise is not a second opinion.
        failing = [pair for pair in judged if pair[1].verdict == "unmet"]
        chosen, judgement = failing[0] if failing else min(judged, key=lambda pair: (
            proof.standing(pair[1]), model.STRENGTHS.index(pair[1].strength) if pair[1].strength else 9))
        shown = [book.add(candidate, key=proof.cited_key(candidate) if candidate.get("path") else ("fast-claim", latest.ts))
                 for candidate, _judgement in judged]
        resting = shown[[candidate for candidate, _judgement in judged].index(chosen)]
        target_link = {"kind": "gate", "label": f"fast gate at {(latest.commit or '?')[:8]}", "path": None, "base": None,
                       "abs": None, "line": None, "end_line": None, "exists": True, "why_unresolved": None}
        target = proof.target_entry(target_link, judgement, [resting], scope=self.fast_scope, context=self.context,
                                    spec={"rule": "gate", "tier": FAST_TIER, "tiers": self.tiers_rel, "expected_suites": expected})
        return proof.reduce(f"{rung['rung_id']}#fast-gate", "gate_run", "test", "the fast gate is green",
                            "the latest fast-tier gate run passed (ROADMAP §1)", source, [target], empty_reason="")

    # ------------------------------------------------------------ recognised conditions (Codex G09)
    def _audit_criterion(self, rung: Mapping[str, Any], condition: Condition, book: EvidenceBook, source: dict) -> dict[str, Any]:
        """``no in_domain Codex blocker or major left on X``: the newest audit of X the rung's status events cite.

        The audit binds itself to the commit it reviewed (its ``candidate `<sha>``` line); its scope is the
        packages of the code it cites. WHY no ruler context: a review is of code at a commit; a later pin move
        is data the review never saw, and the ruler's own acceptance tests carry it.
        """

        rung_id = rung["rung_id"]
        subject, reviewer = condition.fields.get("subject", ""), condition.fields.get("reviewer", "Codex")
        # The subject as its own token, "-" allowed around it ("…-ruler-a2-v2-r1.md" is an audit of a2-v2).
        mentions = re.compile(r"(?<![A-Za-z0-9])" + re.escape(subject) + r"(?![A-Za-z0-9])")
        candidates = []
        for event in reversed(self.events.status_events(rung_id)):
            for citation in links.cited_paths(event.get("evidence")) + links.cited_paths(event.get("detail")):
                if links.classify(citation.raw) != "audit" or not Path(citation.raw).is_file():
                    continue
                if not (mentions.search(citation.raw) or mentions.search((artifacts.whole_text(Path(citation.raw)) or "")[:4000])):
                    continue  # an audit of something else
                item = proof.cited_item(citation, self.roots, commit=event.get("commit"), ts=event.get("ts"), origin="event",
                                        event=self.events.ref(event))
                candidates.append(proof.Proof(rung_id, item, proof.cited_key(item), f"the audit report the {event.get('kind')} "
                                              f"event at line {event.get(LINE_KEY)} cites"))
        label = f"{reviewer} review of {subject}"
        if not candidates:
            target = proof.condition_target("audit", label, Judgement("unknown", None, [], f"no status event of {rung_id} cites an "
                                                                       f"audit report of {subject}"), [])
        else:
            judged = [(candidate, self.evaluator.judge_audit(candidate.item, self._audit_scope(candidate.item), {}))
                      for candidate in candidates]
            chosen, judgement = proof.choose(judged)
            judgement.note = "; ".join(part for part in (chosen.note, judgement.note) if part)
            target = proof.condition_target("audit", label, judgement, [proof.materialize(book, chosen)],
                                            scope=self._audit_scope(chosen.item))
        return proof.reduce(f"{rung_id}#audit", "audit", "inspection", f"no in_domain {reviewer} blocker or major on {subject}",
                            condition.text, source, [target], empty_reason="")

    def _audit_scope(self, item: Mapping[str, Any]) -> list[str]:
        """What an audit reviewed, so what a later change must not touch: every file it cites, and the source folder of
        each package it cites code in (``bam_eval/bam_eval/``, not the package's tests or fixtures).

        WHY not the whole package: a test file added later for other work (wave 4's scene-pin acceptance) changes no
        code the review read; a file the review cited, or the package code it reviewed, does. Markdown never counts.
        """

        path = self.evaluator.resolve(item)
        text = artifacts.whole_text(path) if path is not None else None
        scope = set()
        for raw in _AUDIT_LINK.findall(text or ""):
            if raw.endswith(".md"):
                continue
            relative = links.repo_relative(raw, self.roots)
            if relative is None:
                continue
            scope.add(relative)
            root = self.code.package_root(relative)
            inner = relative[len(root) + 1:].split("/", 1) if root else []
            if root and len(inner) == 2 and inner[0] not in ("tests", "test", "fixtures", "docs", "examples", "scripts"):
                scope.add(f"{root}/{inner[0]}/")
        return sorted(scope)

    def _determinism_criterion(self, rung: Mapping[str, Any], condition: Condition, book: EvidenceBook, source: dict) -> dict[str, Any]:
        """``identical verdict_hash over N judged MODE-mode runs at V m/s``: N ledger rows at that timing and belt speed.

        Which N: the run ids the rung's latest status event names when they qualify, else the newest N readings of one
        corpus at one commit under one ruler. The predicate is evaluated on the rows themselves, never on the sentence.
        """

        rung_id = rung["rung_id"]
        wanted = int(condition.fields.get("runs", "2"))
        spec = {"rule": "determinism", "runs": wanted, "mode": condition.fields.get("mode"),
                "belt_speed_m_s": float(condition.fields.get("speed", "0"))}
        rows = [row for row in self.ledger_rows if ((row.get("metrics") or {}).get("latency") or {}).get("mode") == spec["mode"]
                and isinstance(self.evaluator.belt_speed(row), (int, float))
                and abs(float(self.evaluator.belt_speed(row)) - spec["belt_speed_m_s"]) <= 1e-9]
        latest = self.events.latest_status_event(rung_id)
        named = set(re.findall(r"[\w.-]+", f"{(latest or {}).get('evidence') or ''} {(latest or {}).get('detail') or ''}"))
        groups: dict[tuple, list[Mapping[str, Any]]] = {}
        for row in rows:
            key = ((row.get("metrics") or {}).get("corpus_id"), (row.get("git") or {}).get("sha"), (row.get("metrics") or {}).get("ruler_sha256"))
            groups.setdefault(key, []).append(row)
        cited = [row for row in rows if row.get("run_id") in named]
        cited_groups = {key: [row for row in group if row.get("run_id") in named] for key, group in groups.items()}
        chosen = next((group[-wanted:] for group in cited_groups.values() if len(group) >= wanted), None) if cited else None
        if chosen is None:
            full = [group for group in groups.values() if len(group) >= wanted]
            chosen = max(full, key=lambda group: (proof.sort_key_time(group[-1].get("ts")), group[-1].get(LINE_KEY) or 0))[-wanted:] if full else []
        conflicts = [f"run {row.get('run_id')} has conflicting ledger rows" for row in chosen if str(row.get("run_id")) in self.conflicting_runs]
        judgement = self.evaluator.judge_determinism([_without_line(row) for row in chosen], spec, self.measured_scope, self.context,
                                                     problems=conflicts)
        evidence = [self._run_evidence(book, row) for row in chosen]
        corpus = (chosen[0].get("metrics") or {}).get("corpus_id") if chosen else None
        label = f"{wanted} judged {spec['mode']}-mode runs at {spec['belt_speed_m_s']:g} m/s" + (f" on {corpus}" if corpus else "")
        target = proof.condition_target("corpus", label, judgement, evidence, scope=[PRODUCER_SCOPE], context=self.context, spec=spec)
        return proof.reduce(f"{rung_id}#determinism", "gate_run", "test", "identical verdict_hash over judged runs",
                            condition.text, source, [target], empty_reason="")

    # ------------------------------------------------------------ measured gates
    def _gate_criterion(self, rung: Mapping[str, Any], book: EvidenceBook, source: dict) -> dict[str, Any]:
        """The gate re-derived from the ledger rows, judged by the shared evaluator (Codex F08, F12).

        Readings under an older ruler are kept and judged stale, never dropped: their provenance stays.
        """

        gate = rung["gate"]
        readings = self._readings(rung["rung_id"])
        run_ids: dict[Any, str] = {}
        for row in list(reversed(readings))[:RUN_EVIDENCE_LIMIT]:
            run_ids[row.get("run_id")] = self._run_evidence(book, row)
        targets: list[dict[str, Any]] = []
        resting_ids: list[str] = []
        for spec in window_specs(gate, self.corpora):
            corpus_id, tier = spec["corpus"], spec["tier"]
            target_link = self._corpus_link(corpus_id, tier)
            if corpus_id is None:
                targets.append(proof.target_entry({**target_link, "why_unresolved": "no corpus set"},
                                                  Judgement("unknown", None, [], f"no {tier} corpus is set"), [], spec=spec))
                continue
            window = gated_window(self.inputs.ledger, rung["rung_id"], spec)
            evidence = [run_ids[row.get("run_id")] if row.get("run_id") in run_ids else self._run_evidence(book, row) for row in window]
            conflicts = [f"run {row.get('run_id')} has conflicting ledger rows" for row in window
                         if str(row.get("run_id")) in self.conflicting_runs]
            judgement = self.evaluator.judge_window([_without_line(row) for row in window], spec, self.measured_scope,
                                                    self.context, problems=conflicts)
            resting_ids += evidence
            targets.append(proof.target_entry(target_link, judgement, evidence, scope=[PRODUCER_SCOPE], context=self.context,
                                              spec=spec))
        self.superseded[rung["rung_id"]] = self._superseded_runs(book, list(run_ids.values()), resting_ids)
        return proof.reduce(f"{rung['rung_id']}#gate", "gate_run", "test", f"{gate['kind']} gate on the ledger",
                            rung.get("gate_text") or "", source, targets, empty_reason="no corpus is set")

    @staticmethod
    def _superseded_runs(book: EvidenceBook, shown: Sequence[str], resting_on: Sequence[str]) -> dict[str, str | None]:
        """Every shown run the gate does not rest on, mapped to the newest resting run on the same tier and corpus.

        WHY by exact run id, never by text (Codex A07 on the frontend, Oct 3): "run-1" must not look
        cited because a reason names "run-10".
        """

        def lane(evidence_id: str) -> tuple:
            facts = book.get(evidence_id)["facts"]
            return facts.get("tier"), facts.get("corpus")

        newest_by_lane: dict[tuple, str] = {}
        for evidence_id in resting_on:
            item = book.get(evidence_id)
            current = newest_by_lane.get(lane(evidence_id))
            if current is None or proof.sort_key_time(item["ts"]) >= proof.sort_key_time(book.get(current)["ts"]):
                newest_by_lane[lane(evidence_id)] = evidence_id
        return {evidence_id: newest_by_lane.get(lane(evidence_id)) for evidence_id in shown if evidence_id not in resting_on}

    def _corpus_link(self, corpus_id: str | None, tier: str) -> dict[str, Any]:
        label = f"{tier}: {corpus_id or 'none'}"
        if corpus_id is None:
            return links.link("corpus", None, self.roots, label=label)
        corpus = self.corpora.get(corpus_id) or {}
        return links.link("corpus", str(self.curriculum_path), self.roots, label=f"{label} ({corpus.get('count', '?')} cases)",
                          line=proof.json_line_of(self.curriculum_path, f'"corpus_id": "{corpus_id}"'))

    def _run_evidence(self, book: EvidenceBook, row: Mapping[str, Any]) -> str:
        run_id = str(row.get("run_id"))
        metrics, totals, gates, git = row.get("metrics") or {}, row.get("totals") or {}, row.get("gates") or {}, row.get("git") or {}
        run_dir = (row.get("artifacts") or {}).get("run_dir") or f"runs/{run_id}"
        batch_path = self.inputs.data_home / run_dir / "batch.json"
        item = links.link("run", str(batch_path), self.roots, label=run_id)
        ledger_line = row.get(LINE_KEY)
        if not item["exists"]:
            # WHY fall back to the ledger row: the row in runs.jsonl IS the record the gate reads; a missing
            # batch.json loses the run's detail, not its verdict. The link then opens that exact row.
            item = {**links.link("run", str(self.inputs.data_home / "runs.jsonl"), self.roots, label=run_id, line=ledger_line),
                    "why_unresolved": None}
        batch = read_json_quiet(batch_path)
        histogram = dict(sorted(((batch or {}).get("primary_histogram") or {}).items(), key=lambda pair: -pair[1]))
        facts = {
            "tier": metrics.get("tier"), "corpus": metrics.get("corpus_id"), "feasible": totals.get("feasible"),
            "presented": totals.get("presented"), "void": totals.get("void"), "coverage": gates.get("coverage"),
            "all_passed": gates.get("all_passed"), "feasible_rate": _json_number(metrics.get("feasible_rate")),
            "recovery": _json_number(metrics.get("recovery")), "ppm": _json_number(metrics.get("ppm")),
            "verdict_hash": str(metrics.get("verdict_hash") or "")[:12], "ruler_sha256": str(metrics.get("ruler_sha256") or "")[:12],
            "on_current_ruler": metrics.get("ruler_sha256") == self.inputs.ruler_sha256, "latency": metrics.get("latency"),
            "dirty": git.get("dirty"), "gate_met_by_judge": metrics.get("gate_met"), "primary_histogram": histogram,
            "ledger_line": ledger_line, "batch_json": batch_path.is_file(),
        }
        return book.add({**item, "result": None, "strength": "record", "commit": git.get("sha"), "ts": row.get("ts"),
                         "origin": "ledger", "facts": facts, "run_id": run_id, "as_cited": None,
                         "event": self.events.ref(self.judged_run_events.get(run_id)), "commit_source": "artifact",
                         "witnesses": self._witnesses(run_dir, histogram)}, key=("run", run_id))

    def _witnesses(self, run_dir: str, histogram: Mapping[str, int]) -> list[dict[str, Any]]:
        """One example episode per top failure code: its scorecard and log, to open and inspect."""

        wanted = list(histogram)[:WITNESS_CODES]
        if not wanted:
            return []
        found: dict[str, dict[str, Any]] = {}
        episodes = self.inputs.data_home / run_dir / "episodes.jsonl"
        try:
            with episodes.open(encoding="utf-8") as handle:
                for line in handle:
                    if len(found) == len(wanted):
                        break
                    try:
                        episode = json.loads(line)
                    except ValueError:
                        continue
                    code = episode.get("primary_failure")
                    if code in wanted and code not in found:
                        found[code] = {"code": code, "count": histogram[code], "episode": episode.get("episode_id"),
                                       "scorecard": links.link("file", str(self.inputs.data_home / str(episode.get("scorecard"))), self.roots),
                                       "log": links.link("file", str(self.inputs.data_home / str(episode.get("log"))), self.roots)}
        except OSError:
            return []
        return [found[code] for code in wanted if code in found]

    # ------------------------------------------------------------ lanes
    def _work(self) -> list[dict[str, Any]]:
        latest: dict[str, Mapping[str, Any]] = {}
        audits: dict[str, list[Mapping[str, Any]]] = {}
        for event in self.events.rows:
            if event.get("kind") == "lane_status":
                latest[str(event.get("subject"))] = event
            elif event.get("kind") == "audit":
                audits.setdefault(str(event.get("subject")), []).append(event)
        work = []
        for lane_id, event in latest.items():
            work.append({"id": lane_id, "title": lane_id, "rung": None, "kind": "lane", "status": str(event.get("status")),
                         "commit": event.get("commit"), "updated": event.get("ts"), "note": event.get("detail") or "",
                         "depends_on": [], "acceptance": None, "targets": [], "write_set": [],
                         "audits": [proof.audit_summary(audit, self.roots, self.events) for audit in audits.get(lane_id, [])]})
        return work


def _json_number(value: Any) -> Any:
    """A number JSON can carry: NaN and infinity become their text (the row is judged unmet elsewhere)."""

    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return str(value)
    return value


def _without_line(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != LINE_KEY}


__all__ = ["project_kinsim", "ProjectionError", "read_inputs", "load_gate_runs", "canonical_sha256", "gate_text_is_represented"]
