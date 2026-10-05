"""The two real loops on this machine: both project, both validate, every link opens or says why.

Skipped where the loops are absent. The loops are found through vibetracks' sources map (``kinsim_curriculum_dir``,
``rig_loop_dir``); ``BAM_RIG_LOOP_DIR`` still overrides the rig loop:

    cd ~/vibetracks
    BAM_RIG_LOOP_DIR=~/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop env -u VIRTUAL_ENV uv run --isolated --with pytest --with jsonschema python -m pytest -q vibetracks/roadmap/projector/tests
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import gitinfo, project_kinsim, project_rig, schema_check
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import KINSIM_CURRICULUM_DIR, RIG_LOOP_DIR

pytestmark = pytest.mark.real_data

NOW = "2026-10-03T19:00:00+00:00"
CURRICULUM_DIR = KINSIM_CURRICULUM_DIR
DATA_HOME = Path(os.environ.get("BAM_CURRICULUM_HOME", "~/.local/share/bam_curriculum")).expanduser()
RIG_DIR = Path(os.environ.get("BAM_RIG_LOOP_DIR", str(RIG_LOOP_DIR))).expanduser()
OPENABLE_KINDS = {"test", "log", "file", "junit", "gate_report", "audit", "run", "image", "video"}


@pytest.fixture(scope="module")
def kinsim_document() -> dict:
    if not (CURRICULUM_DIR / "curriculum.json").is_file() or not (DATA_HOME / "status.json").is_file():
        pytest.skip("the kinsim loop's curriculum or data home is not on this machine")
    gitinfo.clear_cache()
    return project_kinsim(CURRICULUM_DIR, DATA_HOME, now=NOW)


@pytest.fixture(scope="module")
def rig_document() -> dict:
    if not (RIG_DIR / "ladder.json").is_file():
        pytest.skip("set BAM_RIG_LOOP_DIR to the rig loop's bam_rig_loop directory")
    gitinfo.clear_cache()
    return project_rig(RIG_DIR, now=NOW)


def project_and_validate(project) -> tuple[dict, list[str]]:
    """A real projection validated against its loop at once; projected again if the live loop moved in between.

    WHY a second try: ``validate`` projects the loop again and a live loop appends events and commits while it
    runs, so a difference that starts with "the loop's sources changed" or "as_of differs" is the loop moving,
    not a defect. Twice in a row would be one.
    """

    document = project()
    problems = validate_document(document)
    if problems and problems[0].startswith(("the loop's sources changed", "as_of differs")):
        document = project()
        problems = validate_document(document)
    return document, problems


@pytest.mark.parametrize("which", ["kinsim_document", "rig_document"])
def test_the_real_projection_validates(request, which):
    request.getfixturevalue(which)  # skips where the loop is not on this machine
    gitinfo.clear_cache()
    project = ((lambda: project_kinsim(CURRICULUM_DIR, DATA_HOME, now=NOW)) if which == "kinsim_document"
               else (lambda: project_rig(RIG_DIR, now=NOW)))
    document, problems = project_and_validate(project)
    assert problems == []
    jsonschema = pytest.importorskip("jsonschema")
    assert list(jsonschema.Draft202012Validator(schema_check.load()).iter_errors(document)) == []


def every_link(document: dict):
    for source in document["sources"]:
        yield "source", source
    for rung in document["rungs"]:
        for item in rung["evidence"]:
            yield f"{rung['id']} {item['id']}", item
            for witness in item.get("witnesses") or []:
                yield f"{rung['id']} {item['id']} witness", witness["scorecard"]
                yield f"{rung['id']} {item['id']} witness", witness["log"]
        for criterion in rung["criteria"]:
            for target in criterion["targets"]:
                yield f"{rung['id']} {criterion['id']}", target


@pytest.mark.parametrize("which", ["kinsim_document", "rig_document"])
def test_every_link_opens_or_says_why(request, which):
    document = request.getfixturevalue(which)
    checked = 0
    for where, link in every_link(document):
        if link.get("kind") not in OPENABLE_KINDS or link.get("path") is None:
            continue
        checked += 1
        if link["exists"]:
            assert link["abs"] and Path(link["abs"]).exists(), where
            if link.get("line"):
                assert link["line"] >= 1, where
        else:
            assert link["why_unresolved"], where
        assert ":" not in Path(str(link["path"])).name or link["kind"] == "run", f"{where}: a line glued to a path"
    assert checked > 0


def test_the_real_kinsim_support_is_exact(kinsim_document):
    by_id = {rung["id"]: rung for rung in kinsim_document["rungs"]}
    rb0 = by_id["RB0"]
    if rb0["status"] == "green":
        assert len(rb0["support"]["runs"]) == 3
        ledger = {json.loads(line)["run_id"] for line in (DATA_HOME / "runs.jsonl").read_text().splitlines() if line.strip()}
        assert set(rb0["support"]["runs"]) <= ledger
    for rung in kinsim_document["rungs"]:
        event = rung["claimed_by"]["event"]
        if event is not None:
            assert event["subject"] == rung["id"] and event["kind"] == "rung_status_changed"


def test_a_real_rung_marked_green_against_its_evidence_is_rejected(kinsim_document):
    mutant = copy.deepcopy(kinsim_document)
    target = next(rung for rung in mutant["rungs"] if rung["status"] in ("partial", "claimed", "stale"))
    target["status"] = "green"
    problems = validate_document(mutant, against_sources=False)
    assert any(f"rung {target['id']}: status green but done_when gives" in problem for problem in problems), problems


def test_a_tampered_real_fold_cannot_make_bt2_green(tmp_path):
    """status.json is a cache: claim BT2 green in a copy, and the ledger (373/1000) still says no."""

    if not (DATA_HOME / "status.json").is_file() or not (CURRICULUM_DIR / "curriculum.json").is_file():
        pytest.skip("the kinsim loop's data home is not on this machine")
    home = tmp_path / "home"
    home.mkdir()
    for name in ("runs.jsonl", "loop_events.jsonl", "triage_answers.jsonl"):
        if (DATA_HOME / name).is_file():
            (home / name).write_bytes((DATA_HOME / name).read_bytes())
    (home / "runs").symlink_to(DATA_HOME / "runs")
    status = json.loads((DATA_HOME / "status.json").read_text())
    rows = [row for row in status["rungs"] if row["rung_id"] == "BT2"]
    if not rows:
        pytest.skip("BT2 is not in this curriculum")
    rows[0].update(status="green", reason="gate met by (tampered)")
    (home / "status.json").write_text(json.dumps(status))
    gitinfo.clear_cache()
    document = project_kinsim(CURRICULUM_DIR, home, now=NOW)
    bt2 = next(rung for rung in document["rungs"] if rung["id"] == "BT2")
    assert bt2["claimed_status"] == "green" and bt2["status"] == "partial"
    assert "BT2" in document["counts"]["claimed_green_not_proven"]
    assert validate_document(document) == []  # projected again from the tampered copy, it is what that copy gives
