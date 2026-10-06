"""The validator rejects a document that claims more than its own evidence shows, whoever wrote it."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import gitinfo, project_kinsim, project_rig, schema_check
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import append_jsonl, ledger_row

NOW = "2026-10-03T19:00:00+00:00"


@pytest.fixture()
def kinsim_document(kinsim_loop) -> dict:
    gitinfo.clear_cache()
    return project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)


@pytest.fixture()
def failing_promotion_document(kinsim_loop) -> dict:
    kinsim_loop.add_reading({
        **ledger_row("rb9-promo-2", "promotion", "rb9-promotion", 8, 7, kinsim_loop.first_commit, kinsim_loop.ruler_sha, "p2"),
        "ts": "2026-10-03T05:00:00+00:00"})
    kinsim_loop.fold({"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"})
    gitinfo.clear_cache()
    return project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)


@pytest.fixture()
def rig_document(rig_loop) -> dict:
    gitinfo.clear_cache()
    return project_rig(rig_loop.rig_dir, now=NOW)


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


def test_the_projections_are_valid(kinsim_document, rig_document):
    assert validate_document(kinsim_document) == []
    assert validate_document(rig_document) == []


def test_a_hand_edited_green_is_rejected(failing_promotion_document):
    """The mutant: a rung marked green although its own done_when gives partial."""

    mutant = copy.deepcopy(failing_promotion_document)
    rung(mutant, "RB9")["status"] = "green"
    problems = validate_document(mutant)
    assert any("RB9: status green but done_when gives partial" in problem for problem in problems), problems


def test_a_criterion_cannot_claim_more_strength_than_its_evidence(rig_document):
    mutant = copy.deepcopy(rig_document)
    acceptance = rung(mutant, "TW0")["criteria"][1]
    acceptance["strength"] = "record"
    acceptance["targets"][0]["strength"] = "record"
    problems = validate_document(mutant)
    assert any("claims record on" in problem and "only claim" in problem for problem in problems), problems
    assert any("status claimed but done_when gives green" in problem for problem in problems), problems


def test_support_must_be_exactly_what_the_criteria_rest_on(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    rb9 = rung(mutant, "RB9")
    dropped = rb9["support"]["evidence"].pop()
    problems = validate_document(mutant)
    assert any("support.evidence" in problem for problem in problems), problems
    assert any(f"{dropped} has role supports but is not in support.evidence" in problem for problem in problems), problems


def test_support_runs_are_the_supporting_run_ids_verbatim(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    rung(mutant, "RB9")["support"]["runs"].append("rb9-reg-r1x")
    assert any("support.runs" in problem for problem in validate_document(mutant))


def test_a_superseded_status_event_chain_must_hold(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    rung(mutant, "EV9")["history"][0]["superseded_by"] = 999
    assert any("superseded_by 999" in problem for problem in validate_document(mutant))


def test_a_link_that_says_it_exists_must_open(kinsim_document, tmp_path):
    mutant = copy.deepcopy(kinsim_document)
    item = rung(mutant, "EV9")["evidence"][0]
    item["abs"] = str(tmp_path / "never-written.txt")
    assert any("abs differs from the loop's sources" in problem for problem in validate_document(mutant))
    # without the loop's sources, the disk layer still catches it; with neither, the document is self-consistent
    problems = validate_document(mutant, against_sources=False)
    assert any("does not open" in problem for problem in problems), problems
    assert validate_document(mutant, against_sources=False, check_disk=False) == []


def test_counts_and_where_are_recomputed(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    mutant["counts"]["by_status"]["green"] += 1
    mutant["where"][0]["here"] = "MR9"
    problems = validate_document(mutant)
    assert any(problem.startswith("counts disagree") for problem in problems)
    assert any(problem.startswith("where rows disagree") for problem in problems)


# ---------------------------------------------------------------- round 2-3: validate projects the loop again (Codex F01, F02, F12, G01-G03)
def test_a_loosened_bar_is_rebuilt_from_the_curriculum(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    gate = next(criterion for criterion in rung(mutant, "RB9")["criteria"] if criterion["id"] == "RB9#gate")
    gate["targets"][0]["spec"]["feasible_rate_min"] = 0.0
    assert any("RB9#gate target" in problem and "spec differs from the loop's sources" in problem
               for problem in validate_document(mutant))


def test_a_window_must_be_the_latest_gated_readings(kinsim_loop, kinsim_document):
    """A newer promotion reading lands after the projection: the old window no longer speaks for the gate."""

    kinsim_loop.add_reading({
        **ledger_row("rb9-promo-3", "promotion", "rb9-promotion", 8, 8, kinsim_loop.first_commit, kinsim_loop.ruler_sha, "p3"),
        "ts": "2026-10-03T05:00:00+00:00"})
    problems = validate_document(kinsim_document)
    assert problems[0].startswith("the loop's sources changed since this document was projected (ledger)"), problems
    assert any(problem.startswith("rung RB9") for problem in problems), problems


def test_a_claim_must_be_the_loops_latest_word(kinsim_loop, kinsim_document):
    """Codex F02 at validation: a later status event the document does not name revokes its claim."""

    kinsim_loop.event(ts="2026-10-03T20:00:00+00:00", kind="rung_status_changed", subject="EV9", status="partial",
                      commit=kinsim_loop.first_commit[:8], evidence="revoked")
    problems = validate_document(kinsim_document)
    assert problems[0].startswith("the loop's sources changed since this document was projected (loop events)"), problems
    assert any(problem.startswith("rung EV9: claimed_status differs") for problem in problems), problems
    assert any(problem.startswith("rung EV9: claimed_by.event differs") for problem in problems), problems


def test_a_rewritten_commit_or_result_is_caught(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    ev9 = rung(mutant, "EV9")
    item = next(item for item in ev9["evidence"] if item["id"] in ev9["support"]["evidence"] and item["kind"] == "test")
    item["commit"], item["result"] = "0" * 40, "failed"
    problems = validate_document(mutant)
    assert any(f"{item['id']}: commit differs from the loop's sources" in problem for problem in problems), problems
    assert any(f"{item['id']}: result differs from the loop's sources" in problem for problem in problems), problems


def test_a_ledger_row_edited_after_projection_is_caught(kinsim_loop, kinsim_document):
    """Codex F12 at validation: the run evidence is re-read from runs.jsonl at its line, so its numbers count."""

    ledger = kinsim_loop.data_home / "runs.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    rows[-1]["totals"]["feasible"] = 0
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    problems = validate_document(kinsim_document)
    assert problems[0].startswith("the loop's sources changed since this document was projected (ledger)"), problems
    assert any("RB9#gate target" in problem and "verdict differs" in problem and '"unmet"' in problem for problem in problems), problems


def test_a_source_locator_must_name_something(kinsim_document):
    """Codex F01: line ranges and source locators are checked, not trusted."""

    mutant = copy.deepcopy(kinsim_document)
    rung(mutant, "RB9")["done_when"]["source"]["pointer"] = "/rungs/99/gate"
    rung(mutant, "EV9")["done_when"]["source"]["line"] = 99999
    problems = validate_document(mutant)
    assert any(problem.startswith("rung RB9: done_when differs") for problem in problems), problems
    assert any(problem.startswith("rung EV9: done_when differs") for problem in problems), problems


# ---------------------------------------------------------------- the stdlib validator vs jsonschema
SCHEMA_MUTANTS = {
    "missing loop": lambda document: document.pop("loop"),
    "extra top-level key": lambda document: document.update(extra=1),
    "unknown status": lambda document: document["rungs"][0].update(status="golden"),
    "short head sha": lambda document: document["as_of"].update(head="abc"),
    "superseded_by is a number": lambda document: document["rungs"][0]["evidence"][0].update(superseded_by=5),
    "count is a string": lambda document: document["counts"].update(evidence_items="3"),
    "unmet with a strength": lambda document: document["rungs"][1]["criteria"][0].update(verdict="unmet", strength="record"),
    "extra evidence key": lambda document: document["rungs"][0]["evidence"][0].update(colour="red"),
    "event line 0": lambda document: document["rungs"][0]["history"][0]["event"].update(line=0),
    "path glued to a line": lambda document: document["rungs"][0]["evidence"][0].update(line="12"),
    "bool where an integer goes": lambda document: document["rungs"][0].update(order=True),
}


@pytest.mark.parametrize("mutation", sorted(SCHEMA_MUTANTS))
def test_the_stdlib_validator_agrees_with_jsonschema(kinsim_document, mutation):
    jsonschema = pytest.importorskip("jsonschema")
    oracle = jsonschema.Draft202012Validator(schema_check.load())
    assert not list(oracle.iter_errors(kinsim_document)) and not schema_check.errors(kinsim_document)
    mutant = copy.deepcopy(kinsim_document)
    SCHEMA_MUTANTS[mutation](mutant)
    oracle_errors = list(oracle.iter_errors(mutant))
    stdlib_errors = schema_check.errors(mutant)
    assert bool(oracle_errors) == bool(stdlib_errors) == True, (mutation, oracle_errors[:1], stdlib_errors[:1])  # noqa: E712


def test_the_stdlib_validator_refuses_keywords_it_does_not_implement(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "unevaluatedProperties": False}))
    with pytest.raises(schema_check.SchemaError, match="unevaluatedProperties"):
        schema_check.load(str(schema))


def test_the_schema_file_is_valid_draft_2020_12():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(json.loads(Path(schema_check.SCHEMA_PATH).read_text()))
