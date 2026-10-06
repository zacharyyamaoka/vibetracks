"""The detection track's projector: a planned ladder, no loop yet, so nothing is green and nothing is proven.

Every document projected here also passes the schema, the stdlib checker and the validator's own consistency rules
(``against_sources=False``: the validator re-projects only the kinsim and rig loops). Fixtures are copies of
``fixtures/detection/*.py`` placed in a throwaway git repository, because the real ladder lives untracked in a worktree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import ProjectionError, gitinfo, model, schema_check
from vibetracks.roadmap.projector.detection import project_detection
from vibetracks.roadmap.projector.validate import validate_document
from vibetracks.sources import load_sources

from .conftest import commit_all, git, write

NOW = "2026-10-04T19:00:00+00:00"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "detection"
#: Where the real ladder is today (the planning session's worktree). ``detection_dir`` in the sources map, or
#: ``BAM_DETECTION_DIR``, overrides it; the real-data test skips when it is not there.
REAL_DETECTION_DIR = Path("/home/bam/bam_ws/.claude/worktrees/hyperspectral-synthetic-data-ddb809/docs/hyperspectral")


def make_loop(tmp_path: Path, fixture: str = "ladder_data.py", *, text: str | None = None, tracked: bool = False) -> Path:
    """``<repo>/docs/hyperspectral/ladder_data.py`` from a fixture; untracked by default, like the real one."""

    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    write(repo / "README.md", "fixture\n")
    commit_all(repo, "fixture: a repository")
    directory = repo / "docs" / "hyperspectral"
    write(directory / "ladder_data.py", text if text is not None else (FIXTURES / fixture).read_text(encoding="utf-8"))
    if tracked:
        commit_all(repo, "fixture: the ladder")
    gitinfo.clear_cache()
    return directory


def project(directory: Path) -> dict:
    gitinfo.clear_cache()
    document = project_detection(directory, now=NOW)
    assert schema_check.errors(document) == []
    assert validate_document(document, against_sources=False) == []
    return document


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


# ---------------------------------------------------------------- the ladder maps onto rungs
def test_rungs_follow_the_ladder_order_and_its_dependencies(tmp_path):
    document = project(make_loop(tmp_path))
    assert document["loop"] == "detection"
    assert [item["id"] for item in document["rungs"]] == ["D0", "D1", "D2", "D3", "D4"]
    assert [item["order"] for item in document["rungs"]] == [0, 1, 2, 3, 4]
    assert {item["id"]: item["depends_on"] for item in document["rungs"]} == {
        "D0": [], "D1": [], "D2": ["D0", "D1"], "D3": ["D0"], "D4": ["D2", "D3"]}
    assert [item["title"] for item in document["rungs"]][:2] == ["Plumbing ruler", "Published ruler"]
    assert [axis["id"] for axis in document["axes"]] == ["hyperspectral"]
    assert {item["axis"] for item in document["rungs"]} == {"hyperspectral"}
    assert {(edge["from"], edge["to"], edge["kind"]) for edge in document["edges"]} == {
        ("D0", "D2", "prerequisite"), ("D1", "D2", "prerequisite"), ("D0", "D3", "prerequisite"),
        ("D2", "D4", "prerequisite"), ("D3", "D4", "prerequisite")}
    via = {(edge["from"], edge["to"]): edge["via"] for edge in document["edges"]}
    assert via[("D1", "D2")] == "only the RGB rows reproduced" and via[("D0", "D2")] is None


def test_each_rung_keeps_its_gate_as_a_stated_condition_with_a_source_line(tmp_path):
    directory = make_loop(tmp_path)
    document = project(directory)
    d1 = rung(document, "D1")
    assert d1["done_when"]["text"].startswith("All 8 configs within")
    assert d1["done_when"]["source"]["pointer"] == "/RUNGS/1"
    assert d1["done_when"]["source"]["line"] == 12  # the line of dict(id="D1" in the fixture
    stated = [criterion for criterion in d1["criteria"] if criterion["kind"] == "stated"]
    assert len(stated) == 1 and (stated[0]["verdict"], stated[0]["strength"], stated[0]["targets"]) == ("unknown", None, [])
    assert d1["x"]["needs"] == "drive" and d1["x"]["kind"] == "external" and d1["x"]["ruler"] == "The paper's numbers"
    assert rung(document, "D2")["x"]["needs_detail"] == {"D1": "only the RGB rows reproduced"}


# ---------------------------------------------------------------- nothing is green
def test_nothing_is_green_or_proven(tmp_path):
    document = project(make_loop(tmp_path))
    assert {item["status"] for item in document["rungs"]} == {"missing"}
    assert {item["claimed_status"] for item in document["rungs"]} == {"missing"}
    assert document["counts"]["by_status"] == {"green": 0, "done": 0, "stale": 0, "claimed": 0, "partial": 0, "missing": 5}
    assert document["counts"]["claimed_green_not_proven"] == [] and document["counts"]["evidence_items"] == 0
    assert all(not item["evidence"] and not item["history"] and item["support"]["evidence"] == [] for item in document["rungs"])
    assert all(criterion["verdict"] != "met" for item in document["rungs"] for criterion in item["criteria"])
    assert document["work"] == []
    assert [row["status"] for row in document["where"]] == ["missing"]


def test_a_rung_the_ladder_calls_green_shows_as_claimed_never_green(tmp_path):
    text = (FIXTURES / "ladder_data.py").read_text(encoding="utf-8").replace('id="D0", short=', 'id="D0", status="green", short=')
    document = project(make_loop(tmp_path, text=text))
    d0 = rung(document, "D0")
    assert (d0["claimed_status"], d0["status"]) == ("green", "claimed")
    assert not model.satisfied(d0["status"]) and document["counts"]["claimed_green_not_proven"] == ["D0"]
    # a rung that claims green over a prerequisite that is not green is contradicted, not claimed
    text = text.replace('id="D2", short=', 'id="D2", status="green", short=')
    document = project(make_loop(tmp_path / "again", text=text))
    assert rung(document, "D2")["status"] == "partial"
    assert "unmet" in rung(document, "D2")["status_reason"]


# ---------------------------------------------------------------- the frontier
def test_the_frontier_is_the_rung_the_plan_names_and_carries_its_progress(tmp_path):
    document = project(make_loop(tmp_path))
    assert document["summary"]["frontier"] == ["D1"]
    assert [item["id"] for item in document["rungs"] if item["frontier"]] == ["D1"]
    assert rung(document, "D1")["x"]["progress"] == {
        "done": 3, "of": 8, "text": "D1: 3 of 8 configs reproduced", "source": "KPIS S2 Frontier gate, today"}
    assert all("progress" not in item["x"] for item in document["rungs"] if item["id"] != "D1")
    # the first unproven rung of the lane is a different fact, and stays what the validator derives
    assert document["where"][0]["next"] == "D0" and document["where"][0]["here"] is None
    assert [row["slot"] for row in document["summary"]["kpis"]] == ["S1 North star", "S2 Frontier gate"]


def test_a_ladder_that_names_no_current_rung_has_no_frontier_and_says_so(tmp_path):
    document = project(make_loop(tmp_path, "ladder_kpis_not_literal.py"))
    assert document["summary"]["frontier"] == [] and not rung(document, "K0")["frontier"]
    assert any("KPIS" in warning and "not literal" in warning for warning in document["warnings"])
    assert any("names no current rung" in warning for warning in document["warnings"])


# ---------------------------------------------------------------- honesty about what this is
def test_the_document_says_it_is_a_plan_that_reads_no_runs_and_has_no_history(tmp_path):
    directory = make_loop(tmp_path)
    document = project(directory)
    assert any(warning.startswith("planned ladder: this projector reads only ladder_data.py") for warning in document["warnings"])
    assert any("untracked" in warning and "ladder_data.py" in warning for warning in document["warnings"])
    assert document["summary"]["phase"] == "planned: no run evidence read" and document["summary"]["wave"] is None
    assert document["as_of"]["head"] == git(directory, "rev-parse", "HEAD")
    assert [(source["role"], source["exists"]) for source in document["sources"]] == [("ladder", True)]
    assert document["sources"][0]["sha256"] is not None and document["sources"][0]["path"].endswith("ladder_data.py")


def test_a_tracked_ladder_carries_no_untracked_warning(tmp_path):
    document = project(make_loop(tmp_path, tracked=True))
    assert not any("untracked" in warning for warning in document["warnings"])
    assert any(warning.startswith("planned ladder: this projector reads only ladder_data.py") for warning in document["warnings"])


# ---------------------------------------------------------------- the ladder is read, never run
def test_a_ladder_that_is_code_is_refused_and_never_executed(tmp_path):
    marker = Path("/tmp/detection-fixture-was-executed")
    assert not marker.exists()
    with pytest.raises(ProjectionError, match="not literal"):
        project_detection(make_loop(tmp_path, "ladder_not_literal.py"), now=NOW)
    assert not marker.exists()


def test_reading_writes_nothing(tmp_path):
    directory = make_loop(tmp_path)
    before = sorted((path.relative_to(tmp_path), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if ".git" not in path.parts)
    project(directory)
    after = sorted((path.relative_to(tmp_path), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if ".git" not in path.parts)
    assert before == after


# ---------------------------------------------------------------- bad ladders fail loudly
def test_a_ladder_with_a_cycle_is_refused(tmp_path):
    text = (FIXTURES / "ladder_data.py").read_text(encoding="utf-8").replace('needs_rungs=[], kind="external"', 'needs_rungs=["D4"], kind="external"', 1)
    with pytest.raises(ProjectionError, match="cycle"):
        project_detection(make_loop(tmp_path, text=text), now=NOW)


def test_a_dependency_on_an_unknown_rung_is_dropped_with_a_warning(tmp_path):
    text = (FIXTURES / "ladder_data.py").read_text(encoding="utf-8").replace('needs_rungs=["D0"], kind="correctness"', 'needs_rungs=["D0", "Z9"], kind="correctness"', 1)
    document = project(make_loop(tmp_path, text=text))
    assert rung(document, "D3")["depends_on"] == ["D0"]
    assert any("D3" in warning and "Z9" in warning for warning in document["warnings"])


def test_a_directory_without_a_ladder_or_outside_git_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ProjectionError):
        project_detection(empty, now=NOW)
    elsewhere = tmp_path / "elsewhere"
    write(elsewhere / "ladder_data.py", (FIXTURES / "ladder_data.py").read_text(encoding="utf-8"))
    gitinfo.clear_cache()
    with pytest.raises(ProjectionError, match="git"):
        project_detection(elsewhere, now=NOW)


def test_the_jsonschema_oracle_agrees(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    document = project(make_loop(tmp_path))
    schema = json.loads(schema_check.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert [error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(document)] == []


# ---------------------------------------------------------------- the real ladder
def real_detection_dir() -> Path:
    configured = os.environ.get("BAM_DETECTION_DIR") or load_sources().get("detection_dir")
    return Path(configured).expanduser() if configured else REAL_DETECTION_DIR


@pytest.mark.real_data
def test_the_real_ladder_projects_with_nothing_green():
    directory = real_detection_dir()
    if not (directory / "ladder_data.py").is_file():
        pytest.skip("the hyperspectral ladder (docs/hyperspectral/ladder_data.py) is not on this machine")
    document = project(directory)
    by_status = document["counts"]["by_status"]
    frontier = document["summary"]["frontier"]
    print(f"\nreal detection ladder: {len(document['rungs'])} rungs, by_status={by_status}, frontier={frontier}, "
          f"progress={[item['x']['progress']['text'] for item in document['rungs'] if 'progress' in item['x']]}, "
          f"where={document['where']}")
    for warning in document["warnings"]:
        print(f"  warning: {warning}")
    assert [item["id"] for item in document["rungs"]] == [f"H{number}" for number in range(10)]
    assert by_status["missing"] == 10 and by_status["green"] == by_status["done"] == by_status["claimed"] == 0
    assert frontier == ["H1"]
    assert rung(document, "H1")["x"]["progress"]["done"] == 2 and rung(document, "H1")["x"]["progress"]["of"] == 12
    assert rung(document, "H4")["depends_on"] == ["H1", "H2", "H3"] and rung(document, "H9")["depends_on"] == ["H4", "H7", "H8"]


def test_the_planned_ladder_never_asserts_that_no_loop_ran(tmp_path):
    """It reads only ladder_data.py, so it cannot know whether the loop ran; it says what it reads, not what happened."""

    from vibetracks.roadmap.projector import detection
    assert "no loop has run" not in detection.PHASE
