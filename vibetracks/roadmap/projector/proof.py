"""The shared engine both projectors use: events, candidate evidence, criteria, support.

A *criterion* is one clause of a rung's ``done_when`` (a test file must pass, a gate must be
met, a package must land). Its *targets* are what it names (test files, corpora, packages,
rungs). Every target's verdict comes from ``evaluate.Evaluator``, the same code the validator runs
again on the finished document, and a criterion is only as good as its worst target.

How a target picks its evidence: every candidate is judged; the newest one with a definite
result wins when it is a failure (a newer red overrides an older green); otherwise the best one
wins, by verdict (met > stale > unknown), then strength (record > log > claim), then recency.

What a status rests on is never inferred from prose (Codex A06/A07 on the frontend, Oct 3):
``finish_rung`` lists the exact evidence ids, ledger run ids and event lines the derived
status was computed from (``support``), and marks every other item ``superseded`` or
``context``. An event is named by its physical line in ``loop_events.jsonl``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import artifacts, links, model
from .evaluate import Evaluator, Judgement, bind, capped, claimed_result
from .files import LINE_KEY, read_jsonl
from .links import EvidenceBook, Roots

STATUS_EVENT = "rung_status_changed"


# ---------------------------------------------------------------- events
class EventLog:
    """A loop's ``loop_events.jsonl``: its rows, each stamped with the line that names it."""

    def __init__(self, path: Path, roots: Roots, rows: list[dict] | None = None) -> None:
        self.file = links.link("file", str(path), roots)
        self.rows = rows if rows is not None else read_jsonl(path, numbered=True)

    def ref(self, event: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """``{path, base, abs, line, kind, subject, status, ts, commit}``: one event, by its line."""

        if event is None:
            return None
        return {"path": self.file["path"], "base": self.file["base"], "abs": self.file["abs"], "line": event.get(LINE_KEY),
                "kind": event.get("kind"), "subject": event.get("subject"), "status": event.get("status"),
                "ts": event.get("ts"), "commit": event.get("commit")}

    def status_events(self, rung_id: str) -> list[Mapping[str, Any]]:
        return [event for event in self.rows if event.get("kind") == STATUS_EVENT and event.get("subject") == rung_id]

    def latest_status_event(self, rung_id: str, statuses: Sequence[str] = ("green", "partial", "missing")) -> Mapping[str, Any] | None:
        """The latest status change the loop recorded for a rung (the one a claim must not outrank, Codex F02)."""

        latest = None
        for event in self.status_events(rung_id):
            if event.get("status") in statuses:
                latest = event
        return latest


# ---------------------------------------------------------------- candidates
def parse_time(stamp: str | None) -> datetime:
    try:
        return datetime.fromisoformat(stamp) if stamp else datetime.min
    except ValueError:
        return datetime.min


def sort_key_time(stamp: str | None) -> float:
    moment = parse_time(stamp)
    if moment == datetime.min:
        return float("-inf")
    return moment.timestamp() if moment.tzinfo else moment.replace(tzinfo=None).timestamp()


@dataclass
class Proof:
    """One candidate piece of evidence for one target, before it is judged or shown under any rung."""

    target: str
    item: dict[str, Any]
    key: tuple
    note: str
    via: tuple[dict[str, Any], tuple] | None = None

    @property
    def ts(self) -> str | None:
        return self.item.get("ts")

    @property
    def line(self) -> int | None:
        return (self.item.get("event") or {}).get("line")


def choose(judged: Sequence[tuple[Proof, Judgement]]) -> tuple[Proof, Judgement] | None:
    """The candidate a target rests on (see the module docstring for the rule)."""

    if not judged:
        return None
    definite = [pair for pair in judged if pair[1].result in model.PASSING_RESULTS + model.FAILING_RESULTS]
    # WHY the event line breaks ties: two runs logged in the same second are told apart by the order
    # the loop appended them, and the later one is the newer evidence.
    newest = max(definite, key=lambda pair: (sort_key_time(pair[0].ts), pair[0].line or 0), default=None)
    if newest is not None and newest[1].result in model.FAILING_RESULTS:
        return newest
    # WHY placed before strength: evidence from this history that a later change staled says more than evidence
    # from a commit outside it (which could be any tree), whatever its strength.
    return min(judged, key=lambda pair: (standing(pair[1]), not pair[1].placed,
                                         model.STRENGTHS.index(pair[1].strength) if pair[1].strength else 9,
                                         -sort_key_time(pair[0].ts), -(pair[0].line or 0)))


def standing(judgement: Judgement) -> int:
    """How far a judgement carries its target, in derive_status's own order (lower is better).

    WHY a stale record outranks a fresh claim: ``derive_status`` reads a claim as "no recorded proof"
    (claimed) and a stale record as "proof that predates a change" (stale); showing the claim would
    hide the only real proof the target has.
    """

    proven = judgement.strength in model.PROOF_STRENGTHS
    return {("met", True): 0, ("stale", True): 1, ("met", False): 2, ("stale", False): 3}.get(
        (judgement.verdict, proven), 4 if judgement.verdict == "unknown" else 5)


def materialize(book: EvidenceBook, proof_item: Proof) -> str:
    """Add one chosen candidate (and the artifact it was read from) to a rung's book."""

    payload = dict(proof_item.item)
    if proof_item.via is not None:
        via_item, via_key = proof_item.via
        payload["via"] = book.add(dict(via_item), key=via_key)
    return book.add(payload, key=proof_item.key)


# ---------------------------------------------------------------- criteria
def criterion(*, criterion_id: str, kind: str, method: str | None, title: str, text: str, source: dict | None,
              targets: list[dict], verdict: str, strength: str | None, reason: str, evidence: Iterable[str],
              at: Iterable[str | None] = ()) -> dict[str, Any]:
    return {
        "id": criterion_id, "kind": kind, "method": method, "title": title, "text": text, "source": source,
        "targets": targets, "verdict": verdict, "strength": strength if verdict in ("met", "stale") else None,
        "reason": reason, "evidence": links.unique(evidence), "at": links.unique(commit for commit in at if commit),
    }


def target_entry(target_link: dict, judgement: Judgement, evidence: list[str], *, scope: Sequence[str] = (),
                 context: Mapping[str, Any] | None = None, spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {**target_link, "verdict": judgement.verdict, "strength": judgement.strength, "evidence": evidence,
            "commit": judgement.commit, "note": judgement.note, "changed_since": list(judgement.changed_since),
            "scope": list(scope), "context": dict(context or {}), "spec": dict(spec) if spec is not None else None}


def rung_target(rung_id: str, status: str, known: bool) -> dict[str, Any]:
    """A target that is another rung of the same document (an alias, a prerequisite)."""

    verdict, strength = model.alias_verdict(status)
    return {"kind": "rung", "label": rung_id, "path": None, "base": None, "abs": None, "line": None, "end_line": None,
            "exists": known, "why_unresolved": None if known else "unknown rung", "verdict": verdict, "strength": strength,
            "evidence": [], "commit": None, "note": f"{rung_id} is {status}", "changed_since": [], "scope": [], "context": {},
            "spec": None}


def reduce(criterion_id: str, kind: str, method: str | None, title: str, text: str, source: dict | None,
           targets: list[dict], *, empty_reason: str) -> dict[str, Any]:
    """A criterion over its targets: as good as the worst one, as strong as the weakest."""

    verdicts = [target["verdict"] for target in targets]
    verdict = model.combine_verdicts(verdicts) if targets else "unknown"
    strength = model.weakest([target["strength"] for target in targets]) if verdict in ("met", "stale") else None
    problems = [f"{target['label']}: {target['verdict']}" + (f" ({target['strength']})" if target["strength"] else "")
                + (f", {target['note']}" if target["note"] else "")
                for target in targets if target["verdict"] != "met" or target["strength"] not in model.PROOF_STRENGTHS]
    if not targets:
        reason = empty_reason
    elif problems:
        reason = "; ".join(problems)
    else:
        reason = f"all {len(targets)} target(s) met, {strength} evidence"
    evidence = [evidence_id for target in targets for evidence_id in target["evidence"]]
    return criterion(criterion_id=criterion_id, kind=kind, method=method, title=title, text=text, source=source,
                     targets=targets, verdict=verdict, strength=strength, reason=reason, evidence=evidence,
                     at=[target["commit"] for target in targets])


def test_criterion(*, criterion_id: str, title: str, text: str, source: dict | None, targets: Sequence[str],
                   index: "TestIndex", evaluator: Evaluator, book: EvidenceBook, roots: Roots,
                   scopes: Mapping[str, Sequence[str]], context: Mapping[str, Any]) -> dict[str, Any]:
    """``kind: test``: every target (a test file, a test folder, a journey script) must pass at a commit in history.

    Only the evidence each target's verdict rests on is added to the rung's book; the other recorded
    runs are counted in the target's note.
    """

    entries = []
    for target in targets:
        candidates = index.candidates(target)
        judged = [(candidate, evaluator.judge_test(candidate.item, target, scopes[target], context,
                                                   via=candidate.via[0] if candidate.via else None))
                  for candidate in candidates]
        picked = choose(judged)
        target_link = links.link("test", target, roots)
        if picked is None:
            judgement, evidence = Judgement("unknown", None, [], "no recorded run"), []
        else:
            chosen, judgement = picked
            evidence = [materialize(book, chosen)]
            others = len(judged) - 1
            judgement = Judgement(judgement.verdict, judgement.strength, judgement.changed_since,
                                  "; ".join(part for part in (chosen.note, judgement.note,
                                                              f"{others} other recorded run(s) of it" if others else "") if part),
                                  judgement.result, judgement.commit)
        if not target_link["exists"]:
            judgement.note = (judgement.note + "; " if judgement.note else "") + "the test file itself does not resolve"
        entries.append(target_entry(target_link, judgement, evidence, scope=scopes[target], context=context))
    return reduce(criterion_id, "test", "test", title, text, source, entries,
                  empty_reason="no test files declared; the acceptance is prose only")


def stated_criterion(*, criterion_id: str, text: str, source: dict | None, audit: bool) -> dict[str, Any]:
    """A condition the loop states only in prose (Codex F11): typed, shown, and unknown until the loop declares it."""

    kind = "audit" if audit else "stated"
    reason = ("the gate requires a cross-provider review verdict, but the loop declares no audit subject for this rung, "
              "so no verdict can be checked" if audit else
              "a condition stated in prose that no field declares; it stays unknown until the loop declares it")
    return criterion(criterion_id=criterion_id, kind=kind, method="inspection" if audit else None,
                     title="the stated review verdict" if audit else "the condition stated in prose", text=text,
                     source=source, targets=[], verdict="unknown", strength=None, reason=reason, evidence=[])


def condition_target(kind: str, label: str, judgement: Judgement, evidence: list[str], *, scope: Sequence[str] = (),
                     context: Mapping[str, Any] | None = None, spec: Mapping[str, Any] | None = None,
                     path_link: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The target of a condition the loop wrote in prose and this format recognises (Codex G09): a review, a run set."""

    link = dict(path_link) if path_link else {"path": None, "base": None, "abs": None, "line": None, "end_line": None,
                                              "exists": True, "why_unresolved": None}
    link.update({"kind": kind, "label": label})
    return target_entry(link, judgement, evidence, scope=scope, context=context, spec=spec)


# ---------------------------------------------------------------- evidence from cited paths
def cited_item(citation: links.Citation, roots: Roots, *, commit: str | None, ts: str | None, origin: str,
               event: dict[str, Any] | None) -> dict[str, Any]:
    """One cited path as an evidence payload (no id yet), its result read from the file itself.

    ``as_cited`` is the path exactly as the loop wrote it, so a viewer that only serves cited
    paths can match it without parsing anything (bam-citation-corpus/1).
    """

    kind = links.classify(citation.raw)
    item = links.link(kind, citation.raw, roots, line=citation.line, end_line=citation.end_line)
    path = Path(item["abs"]) if item["exists"] and item["abs"] else None
    reading = artifacts.read_any(kind, path) if path is not None else artifacts.Reading()
    strength = "record" if kind in ("audit", "gate_report", "junit") and reading.result else ("log" if reading.result else "claim")
    if reading.line and not item["line"]:
        item["line"] = reading.line
    facts = {**reading.facts, "report": reading.pointer} if reading.pointer else dict(reading.facts)
    # WHY the binding caps the strength (Codex G04): a result belongs to the commit it ran at, and only the
    # artifact or git can say which; when only the event says so, the item can never be more than a claim.
    binding = bind(kind, path, commit)
    return {**item, "result": reading.result, "strength": capped(strength, binding.source), "commit": binding.commit, "ts": ts,
            "origin": origin, "facts": facts, "as_cited": citation.raw, "event": event, "commit_source": binding.source}


def cited_key(item: Mapping[str, Any]) -> tuple:
    return ("cited", item["path"], item["line"], item.get("commit"))


def evidence_from_citation(book: EvidenceBook, citation: links.Citation, roots: Roots, *, commit: str | None,
                           ts: str | None, origin: str, event: dict[str, Any] | None) -> str:
    """Add one cited path to ``book`` as an evidence item whose result is read from the file."""

    item = cited_item(citation, roots, commit=commit, ts=ts, origin=origin, event=event)
    return book.add(item, key=cited_key(item))


def statement_item(text: str, *, result: str | None, commit: str | None, ts: str | None, origin: str,
                   event: dict[str, Any] | None) -> dict[str, Any]:
    """The loop's own sentence, kept as evidence of strength ``claim`` when nothing it cites can be read."""

    return {"kind": "statement", "label": "the loop's sentence", "path": None, "base": None, "abs": None, "line": None,
            "end_line": None, "exists": False, "why_unresolved": "a sentence, not an artifact", "result": result,
            "strength": "claim", "commit": commit, "ts": ts, "origin": origin, "facts": {"text": text[:400]},
            "as_cited": None, "event": event, "commit_source": "citation" if commit else None}


class TestIndex:
    """Every candidate the loop has recorded for each of its declared test files, loop-wide.

    WHY loop-wide, not per rung: the unit of proof is the test file at a commit. When EV1's green
    event cites a log of test_loop_tools_acceptance.py, that log is a candidate for RG1 and RG2 too,
    which target the same file.

    From an event's text a target gets: every readable log the event cites that shows the file run
    (``artifacts.target_evidence``), and every readable log cited in a clause that names the file; the
    evaluator grants a log more than ``claim`` only on positive evidence for the file at a commit a
    machine record binds (Codex F04, G04, G05). A clause that names the file and cites nothing readable
    gives its sentence (``claim``). JUnit records from gate runs come in through ``add``.
    """

    __test__ = False  # not a pytest class, despite the name

    def __init__(self, roots: Roots, targets: Iterable[str], events: EventLog) -> None:
        self.roots = roots
        self.events = events
        self.targets = sorted(set(targets))
        self.by_target: dict[str, list[Proof]] = {target: [] for target in self.targets}

    def add(self, proof_item: Proof) -> None:
        bucket = self.by_target.setdefault(proof_item.target, [])
        if all(existing.key != proof_item.key for existing in bucket):
            bucket.append(proof_item)

    def add_event(self, event: Mapping[str, Any], origin: str) -> None:
        text, commit, ts = event.get("evidence"), event.get("commit"), event.get("ts")
        if not text:
            return
        reference = self.events.ref(event)
        source = f"{event.get('kind')} {event.get('subject')}, events line {event.get(LINE_KEY)}"
        per_clause = []
        # WHY parse the whole text before splitting it (Codex C02): a quoted span can cross a "; ".
        for clause, citations in links.clauses_with_citations(text):
            items = [cited_item(citation, self.roots, commit=commit, ts=ts, origin=origin, event=reference)
                     for citation in citations if citation.kind == "text"]
            per_clause.append((clause, items))
        readable_logs = [item for _clause, items in per_clause for item in items
                         if item["kind"] == "log" and item["result"] and item["abs"]]
        for target in self.targets:
            if not links.is_file_target(target):
                continue  # a folder is never shown run by a log
            for item in readable_logs:
                if artifacts.target_evidence(Path(item["abs"]), target).facts.get("evidence") != "none":
                    self.add(Proof(target, item, cited_key(item), f"a log that shows the file run ({source})"))
        for clause, items in per_clause:
            named = [target for target in self.targets if links.names_target(clause, target)]
            if not named:
                continue
            readable = [item for item in items if item["kind"] == "log" and item["result"]]
            if readable:
                for target in named:
                    for item in readable:
                        self.add(Proof(target, item, cited_key(item), f"a log cited beside its name ({source})"))
                continue
            result, _words = claimed_result(clause)
            statement = statement_item(clause, result=result, commit=commit, ts=ts, origin=origin, event=reference)
            for target in named:
                self.add(Proof(target, statement, ("claim", event.get(LINE_KEY), clause[:200]), f"the loop's sentence ({source})"))

    def candidates(self, target: str) -> list[Proof]:
        return list(self.by_target.get(target, []))


def split_clauses(text: str | None) -> list[str]:
    return links.split_clauses(text)


# ---------------------------------------------------------------- history, support, roles
def history(book: EvidenceBook, events: EventLog, rung_id: str, roots: Roots, *, origin: str = "event") -> list[dict[str, Any]]:
    """Every status change the loop recorded for a rung, oldest first, each superseded by the next one.

    ``superseded_by`` is the line of the later status event that replaced it (null for the
    current one), so "green at commit X" can never be read off an event a later one revoked.
    """

    rows = []
    status_events = events.status_events(rung_id)
    for index, event in enumerate(status_events):
        reference = events.ref(event)
        cited = [evidence_from_citation(book, citation, roots, commit=event.get("commit"), ts=event.get("ts"),
                                        origin=origin, event=reference)
                 for citation in links.cited_paths(event.get("evidence"))]
        later = status_events[index + 1] if index + 1 < len(status_events) else None
        rows.append({"ts": event.get("ts"), "wave": event.get("wave"), "kind": event.get("kind"), "status": event.get("status"),
                     "commit": event.get("commit"), "detail": event.get("detail") or "", "evidence_text": event.get("evidence"),
                     "evidence": links.unique(cited), "event": reference,
                     "superseded_by": later.get(LINE_KEY) if later is not None else None})
    return rows


def finish_rung(rung: dict[str, Any], book: EvidenceBook, superseded: Mapping[str, str | None] | None = None) -> dict[str, Any]:
    """Name what the derived status rests on, and mark every evidence item's role.

    ``support.evidence``: exactly the items the criteria's targets rest on (and the artifacts
    they were read from); ``support.runs``: the ledger run ids among them, verbatim;
    ``support.events``: the events that cited them, by line; ``support.rungs``: the rungs an alias
    or a prerequisite rests on. Every other item is ``superseded`` (an older status event's
    citation, a run outside the gate's window; ``superseded_by`` names the item that replaced it
    when there is one) or ``context`` (cited, shown, not part of the verdict).
    """

    superseded = dict(superseded or {})
    by_id = {item["id"]: item for item in book.items}
    support_ids: list[str] = []
    rung_ids: list[str] = []
    for criterion_entry in rung["criteria"]:
        for target in criterion_entry["targets"]:
            support_ids += target["evidence"]
            if target["kind"] == "rung":
                rung_ids.append(target["label"])
    for evidence_id in list(support_ids):
        via = by_id[evidence_id].get("via")
        if via:
            support_ids.append(via)
    support_ids = links.unique(support_ids)
    current_lines = {row["event"]["line"] for row in rung["history"] if row["superseded_by"] is None}
    stale_lines = {row["event"]["line"] for row in rung["history"] if row["superseded_by"] is not None}
    for item in book.items:
        line = (item.get("event") or {}).get("line")
        if item["id"] in support_ids:
            item["role"], item["superseded_by"] = "supports", None
        elif item["id"] in superseded:
            item["role"], item["superseded_by"] = "superseded", superseded[item["id"]]
        elif line in stale_lines and line not in current_lines:
            item["role"], item["superseded_by"] = "superseded", None
        else:
            item["role"], item["superseded_by"] = "context", None
    events_seen: dict[Any, dict[str, Any]] = {}
    for evidence_id in support_ids:
        reference = by_id[evidence_id].get("event")
        if reference is not None:
            events_seen.setdefault(reference["line"], reference)
    rung["support"] = {
        "evidence": support_ids,
        "runs": links.unique(by_id[evidence_id]["run_id"] for evidence_id in support_ids if by_id[evidence_id].get("run_id")),
        "events": [events_seen[line] for line in sorted(events_seen, key=lambda value: (value is None, value))],
        "commits": _unique_commits(by_id[evidence_id]["commit"] for evidence_id in support_ids if by_id[evidence_id].get("commit")),
        "rungs": links.unique(rung_ids),
    }
    rung["evidence"] = book.items
    return rung


def _unique_commits(commits: Iterable[str]) -> list[str]:
    """One entry per commit, however the loops abbreviated it (the longest spelling wins)."""

    kept: list[str] = []
    for commit in commits:
        match = next((index for index, known in enumerate(kept) if known.startswith(commit) or commit.startswith(known)), None)
        if match is None:
            kept.append(commit)
        elif len(commit) > len(kept[match]):
            kept[match] = commit
    return kept


# ---------------------------------------------------------------- shared shapes
def where_rows(axes: Sequence[Mapping[str, Any]], rungs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """loop-status/1's ``where`` rows, from derived statuses (and, beside them, from the loop's claims).

    here = the last rung of the axis's leading run of satisfied rungs; next = the first one that is not.
    """

    rows = []
    for axis in axes:
        mine = [rung for rung in rungs if rung["axis"] == axis["id"]]
        if not mine:
            continue
        rows.append({"axis": axis["id"], **_position(mine, "status"),
                     "here_claimed": _position(mine, "claimed_status")["here"]})
    return rows


def _position(rungs: Sequence[Mapping[str, Any]], field_name: str) -> dict[str, Any]:
    here, upcoming = None, None
    for rung in rungs:
        if model.satisfied(rung[field_name]):
            here = rung["id"]
        else:
            upcoming = rung["id"]
            break
    statuses = [rung[field_name] for rung in rungs]
    if all(model.satisfied(status) for status in statuses):
        word = "green"
    elif any(status != "missing" for status in statuses):
        word = "partial"
    else:
        word = "missing"
    return {"here": here, "status": word, "next": upcoming}


def counts(rungs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_status = {status: 0 for status in model.STATUSES}
    for rung in rungs:
        by_status[rung["status"]] += 1
    disagreements = [rung["id"] for rung in rungs
                     if model.satisfied(rung["claimed_status"]) and not model.satisfied(rung["status"])]
    links_total = sum(len(rung["evidence"]) for rung in rungs)
    unresolved = sum(1 for rung in rungs for item in rung["evidence"] if item["path"] and not item["exists"])
    return {"by_status": by_status, "claimed_green_not_proven": disagreements, "evidence_items": links_total,
            "unresolved_links": unresolved}


def unresolved_list(rungs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rung in rungs:
        for item in rung["evidence"]:
            if item["path"] and not item["exists"]:
                rows.append({"rung": rung["id"], "evidence": item["id"], "kind": item["kind"], "path": item["path"],
                             "why": item.get("why_unresolved") or "not found"})
        for criterion_entry in rung["criteria"]:
            for target in criterion_entry["targets"]:
                if target.get("path") and not target.get("exists"):
                    rows.append({"rung": rung["id"], "criterion": criterion_entry["id"], "kind": target["kind"],
                                 "path": target["path"], "why": target.get("why_unresolved") or "not found"})
    return rows


def blockers_from_triage(triage: Mapping[str, Any], rung_id: str, open_ids: Iterable[str] | None = None,
                         roots: Roots | None = None, triage_path: str | None = None) -> list[dict[str, Any]]:
    """Open triage items that name ``rung_id`` in ``blocks`` (or, when given, only ``open_ids``)."""

    wanted = set(open_ids) if open_ids is not None else None
    rows = []
    for item in triage.get("items") or []:
        if rung_id not in (item.get("blocks") or []):
            continue
        if wanted is not None and item.get("triage_id") not in wanted:
            continue
        if wanted is None and item.get("status") != "open":
            continue
        source = None
        if roots and triage_path:
            source = links.link("file", triage_path, roots,
                                line=json_line_of(Path(triage_path), f'"triage_id": "{item.get("triage_id")}"'))
        rows.append({"id": item.get("triage_id"), "title": item.get("title") or "", "default": item.get("default"),
                     "default_applies_after_wave": item.get("default_applies_after_wave"), "source": source})
    return rows


def json_line_of(path: Path, needle: str) -> int | None:
    """The 1-based line of the first occurrence of ``needle`` in a text file (to open a JSON entry where it is)."""

    try:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if needle in line:
                    return number
    except OSError:
        return None
    return None


def source_link(path: Path, roots: Roots, needle: str, pointer: str) -> dict[str, Any]:
    """Where a requirement (or a claim) is declared: the file, the line it starts on, and its RFC 6901 JSON Pointer."""

    found = links.link("file", str(path), roots, line=json_line_of(path, needle))
    found["pointer"] = pointer
    return found


def audit_summary(event: Mapping[str, Any], roots: Roots, events: EventLog) -> dict[str, Any]:
    """One audit event, with its verdict read from the report it cites."""

    cited = [citation for citation in links.cited_paths(event.get("evidence")) if links.classify(citation.raw) == "audit"]
    report = links.link("audit", cited[-1].raw, roots, line=cited[-1].line) if cited else links.link("audit", None, roots)
    reading = artifacts.read_audit(Path(report["abs"])) if report["exists"] and report["abs"] else artifacts.Reading()
    return {"ts": event.get("ts"), "status": event.get("status"), "commit": event.get("commit"),
            "result": reading.result, "verdict": reading.facts.get("verdict"),
            "report": {**report, "line": reading.line or report["line"]}, "detail": event.get("detail") or "",
            "event": events.ref(event)}
