"""validate: a bam-roadmap/1 document is well-formed, consistent, and exactly what its loop's sources give.

Three verdicts (``validate``): **valid** (exactly what the loop gives now), **outdated** (the loop's sources moved
since it was projected, and projecting again gives every rung the same status and the same claim: what it shows
still holds, its details are not checked; project it again), **invalid** (anything else). Layers:

1. the JSON Schema (``schema_check``), for shape;
2. consistency a document can show on its own (no loop files needed): ids resolve, the prerequisite and
   alias graph has no cycle, every criterion's verdict and strength follow from its targets, structural
   criteria follow the rungs they name, and every status re-derives from its criteria; and every source
   link opens and agrees with its own roots (Codex H06);
3. the loop's sources (the default): the loop is projected again from the sources the document names
   (its curriculum or ladder, its data home, its checkout, at the checkout's HEAD), and every field of
   the document, its source links included (H06), must equal the re-projection (Codex G01-G03). Nothing
   the document supplies is trusted here: a required target left out, a scope or context narrowed, a
   claim event's status rewritten, or an evidence item moved to another commit is a difference. Where the
   sources moved (a new head, a source file changed) and every rung keeps its status, the document is
   outdated, not invalid; where nothing moved, or a status differs, it is invalid;
4. links, only when layer 3 is skipped: every link that says ``exists: true`` opens now.

What it cannot see: a defect the projector itself shares with its re-projection (the tests carry that), and a
whole loop forged consistently at another path the document names as its sources.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import links, model, proof, schema_check
from .files import ProjectionError

DIFFERENCE_LIMIT = 60
CLAIM_FIELDS = ("claimed_status", "claimed_by", "status")
RUNG_FIELDS = ("status", "claimed_status", "claimed_by", "status_reason", "depends_on", "alias_of", "done_when", "criteria",
               "support", "evidence", "history", "blockers", "kpis", "notes", "x", "title", "axis", "order", "wave", "frontier", "adds")


@dataclass
class Validation:
    """A document's verdict: ``valid``, ``outdated`` or ``invalid``, and why."""

    verdict: str
    problems: list[str] = field(default_factory=list)     # what makes it invalid (empty otherwise)
    moved: list[str] = field(default_factory=list)        # what moved in the loop since the document was projected
    differences: list[str] = field(default_factory=list)  # how it differs from projecting the loop again


def validate(document: Any, *, check_disk: bool = True, against_sources: bool = True, head: str | None = None,
             verdict_fn: Any = None) -> Validation:
    """The verdict on one document (see the module docstring for the three verdicts and the layers).

    ``verdict_fn`` is the grasping projector's bench-verdict reader (default: the same bridge and cache the live
    projection uses); only a grasping document reads it.
    """

    problems = [f"schema {error}" for error in schema_check.errors(document)]
    if problems:
        return Validation("invalid", problems)
    problems += _consistency(document)
    problems += _source_links(document)
    if not against_sources:
        if check_disk:
            problems += _disk(document)
        return Validation("invalid" if problems else "valid", problems)
    try:
        fresh = reproject(document, head=head, verdict_fn=verdict_fn)
    except (ProjectionError, OSError, ValueError, KeyError) as error:
        return Validation("invalid", problems + [f"cannot project the loop again from the sources this document names: {error}"])
    found = differences(document, fresh)
    moved = moved_since(document, fresh)
    if problems:
        return Validation("invalid", problems + found, moved, found)
    if not found:
        return Validation("valid")
    # WHY outdated is its own verdict (Codex round 3, and the round-2 report): a document made a minute before the loop
    # committed again is not a forgery, and calling it INVALID taught readers to ignore INVALID. It never covers a
    # status: if projecting again changes any rung's status or claim, the document misstates the loop now.
    if moved and same_statuses(document, fresh):
        return Validation("outdated", [], moved, found)
    return Validation("invalid", found, moved, found)


def validate_document(document: Any, *, check_disk: bool = True, against_sources: bool = True, head: str | None = None,
                      verdict_fn: Any = None) -> list[str]:
    """Every problem with the document; empty only when it is valid. An outdated document returns its differences:
    ``validate`` tells outdated from invalid."""

    result = validate(document, check_disk=check_disk, against_sources=against_sources, head=head, verdict_fn=verdict_fn)
    return result.problems if result.verdict == "invalid" else result.differences


def moved_since(document: Mapping[str, Any], fresh: Mapping[str, Any]) -> list[str]:
    """What moved in the loop between the document and projecting it again: its checkout's head, its source files."""

    moved = []
    old_head, new_head = (document.get("as_of") or {}).get("head"), (fresh.get("as_of") or {}).get("head")
    if old_head != new_head:
        moved.append(f"its checkout moved from {str(old_head)[:8]} to {str(new_head)[:8]}")
    old_sources = {source.get("role"): source.get("sha256") for source in document.get("sources") or []}
    new_sources = {source.get("role"): source.get("sha256") for source in fresh.get("sources") or []}
    changed = sorted(str(role) for role in set(old_sources) & set(new_sources) if old_sources[role] != new_sources[role])
    if changed:
        moved.append(f"{', '.join(changed)} changed")
    return moved


def same_statuses(document: Mapping[str, Any], fresh: Mapping[str, Any]) -> bool:
    """Does projecting again give every rung the status and the claim the document shows?"""

    def statuses(payload: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
        return {rung.get("id"): (rung.get("status"), rung.get("claimed_status")) for rung in payload.get("rungs") or []}

    return statuses(document) == statuses(fresh)


# ---------------------------------------------------------------- 3. the loop's sources
def reproject(document: Mapping[str, Any], *, head: str | None = None, verdict_fn: Any = None) -> dict[str, Any]:
    """The loop projected again from the sources ``document`` names, as of ``head`` (default: its checkout's HEAD)."""

    from .kinsim import project_kinsim  # here, not at the top: the projectors import this module's peers
    from .rig import project_rig

    sources = {source.get("role"): source for source in document.get("sources") or []}
    roots = document.get("roots") or {}

    def located(role: str) -> Path:
        source = sources.get(role)
        if source is None:
            raise ProjectionError(f"the document names no {role} source")
        if source.get("abs"):
            return Path(source["abs"])
        base = roots.get(source.get("base") or "", "") if source.get("base") != "abs" else ""
        return Path(base) / source["path"] if base else Path(source["path"])

    now = str(document.get("generated_at"))
    if document.get("loop") == "kinsim":
        data_home = roots.get("data_home")
        if not data_home:
            raise ProjectionError("the document names no data home")
        return project_kinsim(located("curriculum").parent, Path(data_home), now=now, head=head)
    # WHY one branch per loop: each projector reads its own sources; sending every other loop to project_rig (as before
    # grasping and detection existed) made a valid grasping or detection document read invalid.
    if document.get("loop") == "grasping":
        from .grasping import project_grasping
        # WHY the same call as the live projection: the same bridge and cache, so a re-projection cannot disagree with it.
        return project_grasping(located("curriculum").parents[2], now=now, head=head, ledger_path=located("ledger"),
                                verdict_fn=verdict_fn)
    if document.get("loop") == "detection":
        from .detection import project_detection
        return project_detection(located("ladder").parent, now=now, head=head)
    return project_rig(located("ladder").parent, now=now, head=head)


def differences(document: Mapping[str, Any], fresh: Mapping[str, Any]) -> list[str]:
    """Every way ``document`` differs from the re-projection ``fresh``, the most explanatory first.

    Order: a source that changed (it explains everything after it), the head, then each rung's claim and
    status, then each rung's criteria and evidence, then the document-wide summaries that follow from them.
    """

    document, fresh = _plain(document), _plain(fresh)
    problems: list[str] = []
    old_sources = {source.get("role"): source for source in document.get("sources") or []}
    new_sources = {source.get("role"): source for source in fresh.get("sources") or []}
    changed = sorted(str(role) for role in set(old_sources) & set(new_sources)
                     if old_sources[role].get("sha256") != new_sources[role].get("sha256"))
    if changed:
        problems.append(f"the loop's sources changed since this document was projected ({', '.join(changed)}); project it again")
    # WHY every field of every source link (Codex H06): a source is where the document says its proof comes from; a link
    # that points elsewhere, or nowhere, while its role and hash stay put is a difference, not a detail.
    for role in sorted(set(old_sources) | set(new_sources), key=str):
        mine, theirs = old_sources.get(role), new_sources.get(role)
        if mine is None or theirs is None:
            problems.append(f"source {role}: {'missing from the document' if mine is None else 'not a source the loop has'}")
            continue
        problems += [f"source {role}: {key} differs from the loop's sources (document {_short(mine.get(key))}, sources {_short(theirs.get(key))})"
                     for key in sorted(set(mine) | set(theirs)) if key != "sha256" and mine.get(key) != theirs.get(key)]
    if document.get("as_of") != fresh.get("as_of"):
        problems.append(f"as_of differs: the document was judged at {_short(document.get('as_of'))}, the loop's checkout is now "
                        f"{_short(fresh.get('as_of'))}")
    mine = {rung["id"]: rung for rung in document.get("rungs") or []}
    theirs = {rung["id"]: rung for rung in fresh.get("rungs") or []}
    order = [rung["id"] for rung in fresh.get("rungs") or [] if rung["id"] in mine]
    for rung_id in order:
        problems += _rung_differences(mine[rung_id], theirs[rung_id], CLAIM_FIELDS)
    for rung_id in order:
        problems += _rung_differences(mine[rung_id], theirs[rung_id], tuple(key for key in RUNG_FIELDS if key not in CLAIM_FIELDS))
    problems += [f"rung {rung_id}: the loop's sources have no such rung" for rung_id in sorted(set(mine) - set(theirs))]
    problems += [f"rung {rung_id}: the loop's sources give this rung, the document does not" for rung_id in sorted(set(theirs) - set(mine))]
    for key in sorted(set(document) | set(fresh)):
        if key in ("rungs", "sources", "as_of", "generated_at") or document.get(key) == fresh.get(key):
            continue
        problems.append(f"{key} differs from the loop's sources (document {_short(document.get(key))}, sources {_short(fresh.get(key))})")
    if len(problems) > DIFFERENCE_LIMIT:
        problems = problems[:DIFFERENCE_LIMIT] + [f"... and {len(problems) - DIFFERENCE_LIMIT} more differences"]
    return problems


def _rung_differences(mine: Mapping[str, Any], theirs: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    where = f"rung {mine['id']}"
    problems: list[str] = []
    for key in fields:
        if mine.get(key) == theirs.get(key):
            continue
        if key == "criteria":
            problems += _criteria_differences(where, mine.get(key) or [], theirs.get(key) or [])
        elif key == "evidence":
            problems += _keyed_differences(f"{where} evidence", mine.get(key) or [], theirs.get(key) or [], "id")
        elif key == "claimed_by":
            for part in ("source", "event"):
                if (mine.get(key) or {}).get(part) != (theirs.get(key) or {}).get(part):
                    problems.append(f"{where}: claimed_by.{part} differs from the loop's sources "
                                    f"(document {_short((mine.get(key) or {}).get(part))}, sources {_short((theirs.get(key) or {}).get(part))})")
        else:
            problems.append(f"{where}: {key} differs from the loop's sources (document {_short(mine.get(key))}, "
                            f"sources {_short(theirs.get(key))})")
    return problems


def _criteria_differences(where: str, mine: Sequence[Mapping[str, Any]], theirs: Sequence[Mapping[str, Any]]) -> list[str]:
    problems: list[str] = []
    by_id = {criterion["id"]: criterion for criterion in mine}
    for criterion in theirs:
        own = by_id.pop(criterion["id"], None)
        if own is None:
            problems.append(f"{where}: the loop's sources give criterion {criterion['id']} ({criterion['title']}), the document does not")
            continue
        label = f"{where} {criterion['id']}"
        for key in ("kind", "method", "title", "text", "source", "verdict", "strength", "reason", "evidence", "at"):
            if own.get(key) != criterion.get(key):
                problems.append(f"{label}: {key} differs from the loop's sources (document {_short(own.get(key))}, "
                                f"sources {_short(criterion.get(key))})")
        problems += _target_differences(label, own.get("targets") or [], criterion.get("targets") or [])
    problems += [f"{where}: the document has criterion {criterion_id}, which the loop's sources do not give" for criterion_id in by_id]
    return problems


def _target_key(target: Mapping[str, Any]) -> tuple:
    # WHY the label and line too: two corpus targets of one gate both point at curriculum.json.
    return target.get("kind"), target.get("path"), target.get("label"), target.get("line")


def _target_differences(label: str, mine: Sequence[Mapping[str, Any]], theirs: Sequence[Mapping[str, Any]]) -> list[str]:
    problems: list[str] = []
    own = {_target_key(target): target for target in mine}
    for target in theirs:
        name = target.get("path") or target.get("label")
        match = own.pop(_target_key(target), None)
        if match is None:
            problems.append(f"{label}: the loop's sources require target {name}, which the document leaves out")
            continue
        for key in sorted(set(target) | set(match)):
            if match.get(key) != target.get(key):
                problems.append(f"{label} target {name}: {key} differs from the loop's sources (document {_short(match.get(key))}, "
                                f"sources {_short(target.get(key))})")
    problems += [f"{label}: the document has target {target.get('path') or target.get('label')}, which the loop's sources do not require"
                 for target in own.values()]
    return problems


def _keyed_differences(label: str, mine: Sequence[Mapping[str, Any]], theirs: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    problems: list[str] = []
    own = {item.get(key): item for item in mine}
    for item in theirs:
        match = own.pop(item.get(key), None)
        if match is None:
            problems.append(f"{label} {item.get(key)}: given by the loop's sources, missing from the document")
            continue
        for field in sorted(set(item) | set(match)):
            if match.get(field) != item.get(field):
                problems.append(f"{label} {item.get(key)}: {field} differs from the loop's sources (document {_short(match.get(field))}, "
                                f"sources {_short(item.get(field))})")
    problems += [f"{label} {name}: in the document, not given by the loop's sources" for name in own]
    return problems


def _plain(value: Any) -> Any:
    """The document as JSON would carry it (tuples become lists, NaN and infinity their text), so the comparison is
    JSON's and a NaN compares equal to itself."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit - 3] + "..."


# ---------------------------------------------------------------- 2. consistency
def _consistency(document: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    rungs = document["rungs"]
    rung_ids = [rung["id"] for rung in rungs]
    axis_ids = [axis["id"] for axis in document["axes"]]
    problems += [f"rung id {rung_id} repeats" for rung_id in sorted({rung_id for rung_id in rung_ids if rung_ids.count(rung_id) > 1})]
    problems += [f"axis id {axis_id} repeats" for axis_id in sorted({axis_id for axis_id in axis_ids if axis_ids.count(axis_id) > 1})]
    known, by_id = set(rung_ids), {rung["id"]: rung for rung in rungs}
    for edge in document["edges"]:
        for end in ("from", "to"):
            if edge[end] not in known:
                problems.append(f"edge {edge['from']}->{edge['to']}: unknown rung {edge[end]}")
    expected_edges = {("prerequisite", parent, rung["id"]) for rung in rungs for parent in rung["depends_on"]}
    expected_edges |= {("same_as", rung["alias_of"], rung["id"]) for rung in rungs if rung["alias_of"] is not None}
    actual_edges = {(edge["kind"], edge["from"], edge["to"]) for edge in document["edges"] if edge["kind"] in ("prerequisite", "same_as")}
    if actual_edges != expected_edges:
        problems.append(f"prerequisite and same_as edges disagree with depends_on and alias_of: "
                        f"extra {sorted(actual_edges - expected_edges)}, missing {sorted(expected_edges - actual_edges)}")
    problems += _cycles(rungs, known)
    for rung in rungs:
        where = f"rung {rung['id']}"
        if rung["axis"] not in axis_ids:
            problems.append(f"{where}: unknown axis {rung['axis']}")
        if rung["alias_of"] is not None and rung["alias_of"] not in known:
            problems.append(f"{where}: alias_of names unknown rung {rung['alias_of']}")
        problems += [f"{where}: depends_on names unknown rung {parent}" for parent in rung["depends_on"] if parent not in known]
        problems += _rung_consistency(rung, by_id)
    expected_counts = proof.counts(rungs)
    if document["counts"] != expected_counts:
        problems.append(f"counts disagree with the rungs: expected {expected_counts}")
    expected_where = proof.where_rows(document["axes"], rungs)
    if document["where"] != expected_where:
        problems.append("where rows disagree with the rungs' statuses")
    return problems


def _cycles(rungs: Sequence[Mapping[str, Any]], known: set[str]) -> list[str]:
    """A rung that rests on itself through prerequisites or aliases (Codex F03): its status could prove itself."""

    resting = {rung["id"]: [*rung["depends_on"], *([rung["alias_of"]] if rung["alias_of"] else [])] for rung in rungs}
    problems, state = [], {}

    def visit(rung_id: str, path: list[str]) -> None:
        state[rung_id] = "open"
        for parent in resting.get(rung_id, []):
            if parent not in known:
                continue
            if state.get(parent) == "open":
                cycle = path[path.index(parent):] + [parent] if parent in path else [rung_id, parent]
                problems.append(f"rung {rung_id}: prerequisites and aliases form a cycle ({' -> '.join(cycle)})")
            elif parent not in state:
                visit(parent, [*path, parent])
        state[rung_id] = "done"

    for rung_id in resting:
        if rung_id not in state:
            visit(rung_id, [rung_id])
    return problems


def _rung_consistency(rung: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    where = f"rung {rung['id']}"
    problems: list[str] = []
    evidence = {item["id"]: item for item in rung["evidence"]}
    if len(evidence) != len(rung["evidence"]):
        problems.append(f"{where}: evidence ids repeat")
    for item in rung["evidence"]:
        if item.get("via") is not None and item["via"] not in evidence:
            problems.append(f"{where}: {item['id']} via unknown {item['via']}")
        if item["strength"] in model.PROOF_STRENGTHS and not item["exists"] and item["kind"] != "commit":
            problems.append(f"{where}: {item['id']} is {item['strength']} evidence but its artifact does not resolve")
        if item["kind"] == "statement" and item["strength"] != "claim":
            problems.append(f"{where}: {item['id']} is the loop's sentence, so its strength can only be claim")
        if item["commit_source"] == "artifact-dirty" and item["strength"] != "claim":
            problems.append(f"{where}: {item['id']} ran on a dirty tree, so it can only be a claim")
    for row in rung["history"]:
        problems += [f"{where}: history cites unknown {evidence_id}" for evidence_id in row["evidence"] if evidence_id not in evidence]

    kinds = [criterion["kind"] for criterion in rung["criteria"]]
    if rung["depends_on"] and kinds.count("prerequisites") != 1:
        problems.append(f"{where}: has prerequisites {rung['depends_on']} but {kinds.count('prerequisites')} prerequisites criteria")
    if not rung["depends_on"] and "prerequisites" in kinds:
        problems.append(f"{where}: a prerequisites criterion but no depends_on")
    if (rung["alias_of"] is not None) != ("alias" in kinds) or kinds.count("alias") > 1:
        problems.append(f"{where}: alias_of {rung['alias_of']} but {kinds.count('alias')} alias criteria")

    for criterion in rung["criteria"]:
        problems += _criterion_consistency(rung, criterion, evidence, by_id)

    if rung["claimed_by"]["event"] is not None and rung["claimed_by"]["event"]["kind"] == proof.STATUS_EVENT:
        event_status = rung["claimed_by"]["event"]["status"]
        if event_status in model.CLAIM_RANK and model.CLAIM_RANK.get(rung["claimed_status"], 0) > model.CLAIM_RANK[event_status]:
            problems.append(f"{where}: claimed {rung['claimed_status']} outranks its latest status event "
                            f"(line {rung['claimed_by']['event']['line']}: {event_status})")
    derived, reason = model.derive_status(rung["claimed_status"], rung["criteria"])
    if rung["status"] != derived:
        problems.append(f"{where}: status {rung['status']} but done_when gives {derived} ({reason})")
    problems += _support_consistency(rung, evidence)
    return problems


def _criterion_consistency(rung: Mapping[str, Any], criterion: Mapping[str, Any], evidence: Mapping[str, Mapping[str, Any]],
                           by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    label = f"rung {rung['id']} {criterion['id']}"
    problems: list[str] = []
    targets = criterion["targets"]
    cited = [evidence_id for target in targets for evidence_id in target["evidence"]]
    problems += [f"{label}: cites unknown evidence {evidence_id}" for evidence_id in [*criterion["evidence"], *cited]
                 if evidence_id not in evidence]
    if set(criterion["evidence"]) != set(cited):
        problems.append(f"{label}: evidence {criterion['evidence']} is not what its targets cite {links.unique(cited)}")
    if criterion["kind"] in model.STRUCTURAL_KINDS:
        return problems + _structural(rung, criterion, by_id)
    if criterion["kind"] == "stated" and (targets or criterion["verdict"] != "unknown"):
        problems.append(f"{label}: a stated condition has nothing typed to check, so it is unknown with no targets")
    expected_verdict = model.combine_verdicts([target["verdict"] for target in targets]) if targets else "unknown"
    if criterion["verdict"] != expected_verdict:
        problems.append(f"{label}: verdict {criterion['verdict']} but its targets give {expected_verdict}"
                        + ("" if targets else " (it has no targets to rest on)"))
    expected_strength = model.weakest([target["strength"] for target in targets]) if expected_verdict in ("met", "stale") else None
    if criterion["strength"] != expected_strength:
        problems.append(f"{label}: strength {criterion['strength']} but its targets give {expected_strength}")
    for target in targets:
        if target["kind"] == "rung":
            problems.append(f"{label}: a {criterion['kind']} criterion cannot rest on a rung ({target['label']})")
        if target["verdict"] in ("met", "stale") and not target["evidence"]:
            problems.append(f"{label}: target {target['label']} is {target['verdict']} but cites no evidence")
        if target["verdict"] in ("met", "stale") and target["strength"] is None:
            problems.append(f"{label}: target {target['label']} is {target['verdict']} with no strength")
        for evidence_id in target["evidence"]:
            item = evidence.get(evidence_id)
            if item and target["strength"] and model.STRENGTHS.index(item["strength"]) > model.STRENGTHS.index(target["strength"]):
                problems.append(f"{label}: target {target['label']} claims {target['strength']} on {evidence_id}, "
                                f"which is only {item['strength']}")
    return problems


def _structural(rung: Mapping[str, Any], criterion: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """An alias or prerequisites criterion follows the rungs it names: verdict AND strength (Codex F03)."""

    label = f"rung {rung['id']} {criterion['id']}"
    problems: list[str] = []
    names = rung["depends_on"] if criterion["kind"] == "prerequisites" else [rung["alias_of"]]
    labels = [target["label"] for target in criterion["targets"]]
    if labels != list(names):
        problems.append(f"{label}: names {labels}, but the rung's {'depends_on' if criterion['kind'] == 'prerequisites' else 'alias_of'} "
                        f"is {list(names)}")
    statuses = {name: by_id[name]["status"] if name in by_id else "missing" for name in names}
    for target in criterion["targets"]:
        status = statuses.get(target["label"], "missing")
        verdict, strength = model.alias_verdict(status)
        if (target["verdict"], target["strength"]) != (verdict, strength):
            problems.append(f"{label}: target {target['label']} says {target['verdict']}/{target['strength']}, "
                            f"but {target['label']} is {status} ({verdict}/{strength})")
        if target["kind"] != "rung" or target["evidence"]:
            problems.append(f"{label}: target {target['label']} must be a rung and cite no evidence")
    if criterion["kind"] == "prerequisites":
        verdict, strength, _reason = model.prerequisites_verdict(statuses)
        what = f"prerequisites {', '.join(f'{name} {status}' for name, status in statuses.items())}"
    else:
        verdict, strength = model.alias_verdict(statuses.get(rung["alias_of"], "missing"))
        what = f"{rung['alias_of']} is {statuses.get(rung['alias_of'], 'missing')}"
    strength = strength if verdict in ("met", "stale") else None
    if (criterion["verdict"], criterion["strength"]) != (verdict, strength):
        problems.append(f"{label}: says {criterion['verdict']}/{criterion['strength']}, but the {what} give {verdict}/{strength}")
    return problems


def _support_consistency(rung: Mapping[str, Any], evidence: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """``support`` is exactly what the criteria rest on, and every item's ``role`` agrees with it."""

    where = f"rung {rung['id']}"
    problems: list[str] = []
    resting = [evidence_id for criterion in rung["criteria"] for target in criterion["targets"] for evidence_id in target["evidence"]]
    resting += [evidence[evidence_id]["via"] for evidence_id in list(resting)
                if evidence_id in evidence and evidence[evidence_id].get("via")]
    support = rung["support"]
    if set(support["evidence"]) != set(resting):
        problems.append(f"{where}: support.evidence {sorted(support['evidence'])} is not what its criteria rest on {sorted(set(resting))}")
    rungs_named = links.unique(target["label"] for criterion in rung["criteria"] for target in criterion["targets"] if target["kind"] == "rung")
    if list(support["rungs"]) != rungs_named:
        problems.append(f"{where}: support.rungs {support['rungs']} is not the rungs its criteria name {rungs_named}")
    for item in rung["evidence"]:
        in_support = item["id"] in support["evidence"]
        if in_support != (item["role"] == "supports"):
            problems.append(f"{where}: {item['id']} has role {item['role']} but is {'in' if in_support else 'not in'} support.evidence")
        if item["superseded_by"] is not None and (item["role"] != "superseded" or item["superseded_by"] not in evidence):
            problems.append(f"{where}: {item['id']} superseded_by {item['superseded_by']} does not name a newer item")
    runs = {evidence[evidence_id]["run_id"] for evidence_id in support["evidence"]
            if evidence_id in evidence and evidence[evidence_id].get("run_id")}
    if set(support["runs"]) != runs:
        problems.append(f"{where}: support.runs {sorted(support['runs'])} is not the run ids its supporting runs carry {sorted(runs)}")
    lines = {evidence[evidence_id]["event"]["line"] for evidence_id in support["evidence"]
             if evidence_id in evidence and evidence[evidence_id].get("event")}
    if {reference["line"] for reference in support["events"]} != lines:
        problems.append(f"{where}: support.events is not the events its supporting items cite")
    for index, row in enumerate(rung["history"]):
        expected = rung["history"][index + 1]["event"]["line"] if index + 1 < len(rung["history"]) else None
        if row["superseded_by"] != expected:
            problems.append(f"{where}: history row at line {row['event']['line']} says superseded_by {row['superseded_by']}, "
                            f"the next status event is {expected}")
    return problems


# ---------------------------------------------------------------- 4. disk
def _links(document: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = [(f"source {source.get('label')}", source) for source in document["sources"]]
    found.append(("rules.loop_rules", document["rules"]["loop_rules"]))
    for rung in document["rungs"]:
        if rung["done_when"]["source"]:
            found.append((f"rung {rung['id']} done_when.source", rung["done_when"]["source"]))
        for item in rung["evidence"]:
            found.append((f"rung {rung['id']} {item['id']}", item))
            for witness in item.get("witnesses") or []:
                found += [(f"rung {rung['id']} {item['id']} witness {witness['code']}", witness[key]) for key in ("scorecard", "log")]
        for criterion in rung["criteria"]:
            if criterion["source"]:
                found.append((f"rung {rung['id']} {criterion['id']} source", criterion["source"]))
            found += [(f"rung {rung['id']} {criterion['id']} target {target['label']}", target) for target in criterion["targets"]]
    for work in document["work"]:
        found += [(f"work {work['id']} target {target['label']}", target) for target in work["targets"]]
        found += [(f"work {work['id']} audit report", audit["report"]) for audit in work["audits"]]
    return found


def _source_links(document: Mapping[str, Any]) -> list[str]:
    """Every source link opens, and its own fields agree: ``abs`` is its root joined with its ``path`` (Codex H06)."""

    problems = []
    roots = document.get("roots") or {}
    for source in document.get("sources") or []:
        where = f"source {source.get('role')}"
        absolute, path, base = source.get("abs"), source.get("path"), source.get("base")
        if source.get("exists"):
            if not absolute or not Path(absolute).is_file():
                problems.append(f"{where}: says it exists, but {absolute or path} does not open")
        elif path and not source.get("why_unresolved"):
            problems.append(f"{where}: does not resolve and does not say why")
        if absolute and path:
            expected = str(Path(roots[base]) / path) if base in ("repo", "data_home") and roots.get(base) else (path if base == "abs" else None)
            if expected != absolute:
                problems.append(f"{where}: abs {absolute} is not its {base} root joined with its path {path}")
    return problems


def _disk(document: Mapping[str, Any]) -> list[str]:
    problems = []
    for where, link in _links(document):
        if link.get("exists"):
            absolute = link.get("abs")
            if absolute is None and link.get("path") is None:
                continue  # a thing in this document (a rung, a package, a gate, a review), not a file
            if not absolute or not Path(absolute).exists():
                problems.append(f"{where}: says it exists, but {absolute or link.get('path')} does not open")
        elif link.get("path") and not link.get("why_unresolved"):
            problems.append(f"{where}: does not resolve and does not say why")
    return problems


def summarize(document: Mapping[str, Any]) -> str:
    counts = document["counts"]["by_status"]
    words = ", ".join(f"{counts[status]} {status}" for status in model.STATUSES if counts[status])
    return (f"{document['loop']}: {len(document['rungs'])} rungs ({words}); "
            f"{document['counts']['evidence_items']} evidence items, {document['counts']['unresolved_links']} unresolved")


__all__ = ["Validation", "validate", "validate_document", "moved_since", "same_statuses", "summarize"]
