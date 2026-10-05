"""Codex round 2 (reports/media/audits/2026-10-03-bam-roadmap-format-r2.md): one regression per finding, G01-G09.

Each test replays Codex's own reproduction: a forged document checked by ``validate`` (G01-G03), an artifact judged
at the evaluator boundary (G04-G07), or the real projection (G08, G09). Every one failed on 2fe75bd9 before its fix.
Documents that ``validate`` must check against the loop's sources are projected from a snapshot of the data home,
so the live loop cannot move under a test. Real-data tests skip where the kinsim loop's files are absent.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import artifacts, gitinfo, kinsim, links, model, proof
from vibetracks.roadmap.projector.evaluate import Evaluator, RulerAt
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import KINSIM_CURRICULUM_DIR, append_jsonl, commit_all, write, write_json

CURRICULUM_DIR = KINSIM_CURRICULUM_DIR
DATA_HOME = Path(os.environ.get("BAM_CURRICULUM_HOME", "~/.local/share/bam_curriculum")).expanduser()
NOW = "2026-10-03T22:00:00+00:00"
VZ1_LOG = "/home/bam/bam_ws/reports/media/kinematic-curriculum-wave3-2026-10-02/close/vz1_api_acceptance_run1.txt"
API_ACCEPTANCE = "src/dev/bam_kinsim_dashboard/tests/acceptance/test_api_acceptance.py"
LATENCY_ACCEPTANCE = "src/core/mdp/agent/actor/trajectory_generation/bam_traj_gen/src/tests/test_latency_modes_acceptance.py"
LOOP_TOOLS = "test_loop_tools_acceptance.py"
REAL_REPORT = Path("/tmp/bam-gate-fast-rwst_bvo/gate_report.json")
BT2_RUNS = ("bt2-promotion-20261003T034421Z-r1", "bt2-promotion-20261003T034421Z-r2")

needs_kinsim = pytest.mark.skipif(not (CURRICULUM_DIR / "curriculum.json").is_file() or not (DATA_HOME / "status.json").is_file(),
                                  reason="the kinsim loop's curriculum or data home is not on this machine")


# ---------------------------------------------------------------- helpers
def snapshot_home(tmp_path: Path) -> Path:
    """A frozen copy of the data home: its JSON files copied, its runs/ linked (they are append-only per run)."""

    home = tmp_path / "home"
    home.mkdir()
    for name in ("status.json", "runs.jsonl", "loop_events.jsonl", "triage_answers.jsonl"):
        if (DATA_HOME / name).is_file():
            shutil.copyfile(DATA_HOME / name, home / name)
    (home / "runs").symlink_to(DATA_HOME / "runs")
    return home


def project_home(home: Path) -> dict:
    gitinfo.clear_cache()
    return kinsim.project_kinsim(CURRICULUM_DIR, home, now=NOW)


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


def criteria_of(rung_entry: dict, kind: str) -> list[dict]:
    return [criterion for criterion in rung_entry["criteria"] if criterion["kind"] == kind]


def refresh(document: dict) -> dict:
    """Re-derive everything a forged edit would also have to change, the way Codex refreshed its mutants.

    Criteria from their targets, support and roles from the criteria, structural criteria and statuses from the
    rungs, then counts and ``where``. Only the shared pure rules are used (they exist in every version).
    """

    rungs = document["rungs"]
    for _ in range(6):  # structural criteria follow other rungs' statuses: settle them
        statuses = {entry["id"]: entry["status"] for entry in rungs}
        for entry in rungs:
            by_id = {item["id"]: item for item in entry["evidence"]}
            for criterion in entry["criteria"]:
                targets = criterion["targets"]
                if criterion["kind"] == "prerequisites":
                    parents = {target["label"]: statuses.get(target["label"], "missing") for target in targets}
                    for target in targets:
                        target["verdict"], target["strength"] = model.alias_verdict(parents[target["label"]])
                    verdict, strength, _reason = model.prerequisites_verdict(parents)
                elif criterion["kind"] == "alias":
                    for target in targets:
                        target["verdict"], target["strength"] = model.alias_verdict(statuses.get(target["label"], "missing"))
                    verdict, strength = model.alias_verdict(statuses.get(entry["alias_of"], "missing"))
                elif criterion["kind"] == "stated" or not targets:
                    continue
                else:
                    verdict = model.combine_verdicts([target["verdict"] for target in targets])
                    strength = model.weakest([target["strength"] for target in targets])
                    criterion["evidence"] = links.unique(evidence_id for target in targets for evidence_id in target["evidence"])
                    criterion["at"] = links.unique(target["commit"] for target in targets if target["commit"])
                criterion["verdict"] = verdict
                criterion["strength"] = strength if verdict in ("met", "stale") else None
            resting = [evidence_id for criterion in entry["criteria"] for target in criterion["targets"] for evidence_id in target["evidence"]]
            resting += [by_id[evidence_id]["via"] for evidence_id in list(resting) if by_id[evidence_id].get("via")]
            resting = links.unique(resting)
            for item in entry["evidence"]:
                if item["id"] in resting:
                    item["role"], item["superseded_by"] = "supports", None
                elif item["role"] == "supports":
                    item["role"], item["superseded_by"] = "context", None
            events = {}
            for evidence_id in resting:
                reference = by_id[evidence_id].get("event")
                if reference is not None:
                    events.setdefault(reference["line"], reference)
            entry["support"] = {
                "evidence": resting,
                "runs": links.unique(by_id[evidence_id]["run_id"] for evidence_id in resting if by_id[evidence_id].get("run_id")),
                "events": [events[line] for line in sorted(events)],
                "commits": entry["support"]["commits"],
                "rungs": links.unique(target["label"] for criterion in entry["criteria"] for target in criterion["targets"]
                                      if target["kind"] == "rung"),
            }
            entry["status"], entry["status_reason"] = model.derive_status(entry["claimed_status"], entry["criteria"])
    document["counts"] = proof.counts(rungs)
    document["where"] = proof.where_rows(document["axes"], rungs)
    return document


def evaluator_for(repo: gitinfo.Repo, home: Path = DATA_HOME) -> Evaluator:
    roots = links.Roots(repo=repo.root, data_home=home, repo_aliases=repo.other_checkouts())
    curriculum_rel = (CURRICULUM_DIR / "curriculum.json").resolve().relative_to(repo.root).as_posix()
    return Evaluator(repo, roots, ruler_at=RulerAt(repo, curriculum_rel))


# ---------------------------------------------------------------- G01-G03: validate re-derives from the loop's sources
@needs_kinsim
def test_g01_a_required_test_cannot_be_left_out_of_a_valid_document(tmp_path):
    """Codex G01: RG2's test_loop_tools_acceptance.py target removed and every derived field refreshed validated []."""

    document = project_home(snapshot_home(tmp_path))
    mutant = copy.deepcopy(document)
    acceptance = criteria_of(rung(mutant, "RG2"), "test")[0]
    acceptance["targets"] = [target for target in acceptance["targets"] if not target["path"].endswith(LOOP_TOOLS)]
    assert len(acceptance["targets"]) == 1
    problems = validate_document(refresh(mutant))
    assert any("RG2" in problem and LOOP_TOOLS in problem for problem in problems), problems


@needs_kinsim
@pytest.mark.parametrize("field", ["scope", "context"])
def test_g02_freshness_inputs_are_rebuilt_not_read_from_the_document(tmp_path, field):
    """Codex G02: RB0's measured targets with scope (or context) cleared and re-derived to met/record validated []."""

    document = project_home(snapshot_home(tmp_path))
    mutant = copy.deepcopy(document)
    gate = next(criterion for criterion in rung(mutant, "RB0")["criteria"] if criterion["id"] == "RB0#gate")
    for target in gate["targets"]:
        target[field] = [] if field == "scope" else {}
        target["verdict"], target["strength"], target["changed_since"] = "met", "record", []
    problems = validate_document(refresh(mutant))
    assert any("RB0" in problem and field in problem for problem in problems), problems


@needs_kinsim
def test_g03_a_forged_claim_event_cannot_lift_a_revoked_rung(tmp_path):
    """Codex G03: a later EV0 partial event; the document's copy of it forged to green and EV0 refreshed to done."""

    home = snapshot_home(tmp_path)
    append_jsonl(home / "loop_events.jsonl", {"ts": "2026-10-03T21:59:00+00:00", "wave": 4, "kind": "rung_status_changed",
                                              "subject": "EV0", "status": "partial", "detail": "revoked for G03", "commit": None,
                                              "evidence": "revoked"})
    document = project_home(home)
    ev0 = rung(document, "EV0")
    assert (ev0["claimed_status"], ev0["status"], ev0["claimed_by"]["event"]["status"]) == ("partial", "partial", "partial")
    mutant = copy.deepcopy(document)
    forged = rung(mutant, "EV0")
    forged["claimed_by"]["event"]["status"] = "green"
    forged["history"][-1]["status"] = forged["history"][-1]["event"]["status"] = "green"
    forged["claimed_status"] = "done"
    refresh(mutant)
    assert forged["status"] == "done"
    problems = validate_document(mutant)
    assert any(problem.startswith("rung EV0") and "claim" in problem for problem in problems), problems


# ---------------------------------------------------------------- G04-G07: evidence binding
@needs_kinsim
def test_g04_a_log_with_no_commit_record_cannot_be_moved_to_a_newer_commit():
    """Codex G04: vz1_api_acceptance_run1.txt (no HEAD header) judged at a newer citation commit earned met/log."""

    if not Path(VZ1_LOG).is_file():
        pytest.skip("the VZ1 acceptance log is not on this machine")
    gitinfo.clear_cache()
    repo = gitinfo.Repo(CURRICULUM_DIR)
    document = kinsim.project_kinsim(CURRICULUM_DIR, DATA_HOME, now=NOW)
    target = next(item for criterion in criteria_of(rung(document, "VZ1"), "test") for item in criterion["targets"]
                  if item["path"] == API_ACCEPTANCE)
    evaluator = evaluator_for(repo)
    citation = links.cited_paths(f"({VZ1_LOG})")[0]
    as_cited = proof.cited_item(citation, evaluator.roots, commit="741460aa", ts="2026-10-03T04:03:04+00:00", origin="event", event=None)
    assert evaluator.judge_test(as_cited, API_ACCEPTANCE, target["scope"], target["context"]).verdict == "stale"
    moved = proof.cited_item(citation, evaluator.roots, commit=repo.head, ts="2026-10-03T04:03:04+00:00", origin="event", event=None)
    judgement = evaluator.judge_test(moved, API_ACCEPTANCE, target["scope"], target["context"])
    assert judgement.strength not in ("record", "log"), judgement


@needs_kinsim
@pytest.mark.parametrize(("name", "body"), [
    ("the named tests were all skipped",
     "$ pytest -p no:cacheprovider tests/test_latency_modes_acceptance.py tests/test_other.py\n"
     "tests/test_latency_modes_acceptance.py ssssss                           [ 85%]\n"
     "tests/test_other.py .                                                   [100%]\n"
     "1 passed, 6 skipped in 0.50s\nEXIT 0\n"),
    ("collection aborted on another file",
     "$ pytest -p no:cacheprovider tests/test_latency_modes_acceptance.py tests/test_other.py\n"
     "ERROR tests/test_other.py\n!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
     "1 error in 0.20s\nEXIT 2\n"),
])
def test_g05_naming_a_test_is_not_running_it(tmp_path, name, body):
    """Codex G05: a log that names the target but never shows it pass earned met/log."""

    gitinfo.clear_cache()
    repo = gitinfo.Repo(CURRICULUM_DIR)
    log = tmp_path / "run.txt"
    log.write_text(f"HEAD {repo.head};\n{body}")
    evaluator = evaluator_for(repo)
    item = proof.cited_item(links.cited_paths(f"({log})")[0], evaluator.roots, commit=repo.head, ts=NOW, origin="event", event=None)
    judgement = evaluator.judge_test(item, LATENCY_ACCEPTANCE, [LATENCY_ACCEPTANCE], {})
    assert judgement.verdict != "met", (name, judgement)


SIZES_TEST = '''import pytest


@pytest.mark.parametrize("size", ["a", "b"])
def test_widget_sizes(size):
    assert size
'''


def test_g06_parameter_completeness_needs_a_recorded_collection(kinsim_loop, tmp_path):
    """Codex G06: a test declares parameters a and b; only test_widget_sizes[a] ever ran, and required_cases said so."""

    target = "src/pkg/tests/test_sizes_acceptance.py"
    write(kinsim_loop.repo / target, SIZES_TEST)
    commit = commit_all(kinsim_loop.repo, "a parametrized acceptance test")
    junit = write(tmp_path / "junit.xml", '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
                  '<testcase classname="tests.test_sizes_acceptance" name="test_widget_sizes[a]" time="0.01"/>'
                  '</testsuite></testsuites>')
    repo = gitinfo.Repo(kinsim_loop.repo)
    roots = links.Roots(repo=repo.root, data_home=kinsim_loop.data_home)
    via = {**links.link("junit", str(junit), roots), "result": "passed", "strength": "record", "commit": commit, "ts": NOW,
           "origin": "gate_report", "facts": {}, "as_cited": None, "event": None, "commit_source": "artifact"}
    item = {**links.link("test", target, roots), "result": "passed", "strength": "record", "commit": commit, "ts": NOW,
            "origin": "junit", "facts": {"suite_dir": "src/pkg", "required_cases": ["test_widget_sizes[a]"], "passed": 1, "skipped": 0,
                                         "red": 0},
            "as_cited": None, "event": None, "commit_source": "artifact"}
    judgement = Evaluator(repo, roots).judge_test(item, target, [target], {}, via=via)
    assert judgement.verdict != "met", judgement


def failed_then(report: dict) -> dict:
    mutant = copy.deepcopy(report)
    suite = next(suite for suite in mutant["suites"] if suite.get("then"))
    suite["then"][0]["exit_code"] = 1  # the aggregate flags (passed, unexpected_red) are left as they were
    return mutant


def synthetic_report(tmp_path: Path) -> dict:
    """A one-suite report whose records agree (its counts are its JUnit file's, Codex H03), with one smoke after the tests."""

    junit = write(tmp_path / "ladder" / "junit.xml", '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
                  + "".join(f'<testcase classname="tests.test_ladder" name="test_{index}" time="0.01"/>' for index in range(3))
                  + "</testsuite></testsuites>")
    return {"schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [], "tier": "fast",
            "suites": [{"suite": "ladder", "cwd": "/x/root/ladder", "argv": ["pytest", "-q", f"--junitxml={junit}"], "junit": True,
                        "exit_code": 0, "counts": {"passed": 3, "failed": 0, "error": 0, "skipped": 0}, "unexpected_red": [],
                        "unexpected_green": [], "expected_red": [],
                        "then": [{"argv": ["python", "-m", "ladder", "smoke"], "exit_code": 0, "wall_s": 1.0}]}]}


@pytest.mark.parametrize("which", ["synthetic", "real"])
def test_g07_a_failed_then_command_fails_the_gate_report(tmp_path, which):
    """Codex G07: the real fast-gate report with suites[1].then[0].exit_code 0 -> 1, aggregate flags untouched, read passed."""

    if which == "real" and not REAL_REPORT.is_file():
        pytest.skip("the fast gate's /tmp report is not on this machine")
    report = json.loads(REAL_REPORT.read_text()) if which == "real" else synthetic_report(tmp_path)
    assert artifacts.gate_report_reading(report).result == "passed"
    assert artifacts.gate_report_reading(failed_then(report)).result != "passed"


@needs_kinsim
def test_g07_judge_gate_does_not_certify_a_failed_then_command(tmp_path):
    if not REAL_REPORT.is_file():
        pytest.skip("the fast gate's /tmp report is not on this machine")
    gitinfo.clear_cache()
    repo = gitinfo.Repo(CURRICULUM_DIR)
    mutated = tmp_path / "gate_report.json"
    mutated.write_text(json.dumps(failed_then(json.loads(REAL_REPORT.read_text()))))
    evaluator = evaluator_for(repo)
    item = {**links.link("gate_report", str(mutated), evaluator.roots), "result": "passed", "strength": "record", "commit": repo.head,
            "ts": NOW, "origin": "gate_report", "facts": {}, "as_cited": None, "event": None, "commit_source": "artifact"}
    judgement = evaluator.judge_gate(item, "fast", [], {})
    assert judgement.verdict != "met", judgement


# ---------------------------------------------------------------- G08: the measured scope is the producer's run path
@needs_kinsim
def test_g08_replay_and_viewer_changes_do_not_stale_rb0s_readings(tmp_path):
    """Codex G08: RB0's three clean readings at 741460aa read stale because 6f7f37cc changed log_replay.py and the viewer."""

    gate = next(criterion for criterion in rung(project_home(snapshot_home(tmp_path)), "RB0")["criteria"] if criterion["id"] == "RB0#gate")
    # WHY no ("met", "record") pin any more: this runs on the live loop, so it pins the invariant (no target blames the
    # replay/viewer commit 6f7f37cc), not today's verdict. The loop moved (21407ef6 changed RB0's producer), so RB0's
    # readings now read stale for a reason this test is not about; the synthetic case below still pins met -> stale.
    for target in gate["targets"]:
        assert not any(change.startswith("6f7f37cc") for change in target["changed_since"]), target


PRODUCER = {
    "src/prod/pyproject.toml": '[project]\nname = "prod"\nversion = "0"\n',
    "src/prod/prod/__init__.py": "",
    "src/prod/prod/__main__.py": "from .cli import main\n\nraise SystemExit(main())\n",
    "src/prod/prod/cli.py": (
        "import argparse\n\n\n"
        "def _command_run(args):\n    from .engine import run\n\n    return run()\n\n\n"
        "def _command_replay(args):\n    from .viewer import show\n\n    return show()\n\n\n"
        "def main():\n    parser = argparse.ArgumentParser()\n    commands = parser.add_subparsers(required=True)\n"
        "    run_parser = commands.add_parser(\"run\")\n    run_parser.set_defaults(handler=_command_run)\n"
        "    replay_parser = commands.add_parser(\"replay\")\n    replay_parser.set_defaults(handler=_command_replay)\n"
        "    args = parser.parse_args()\n    return args.handler(args)\n"),
    "src/prod/prod/engine.py": "def run():\n    return 0\n",
    "src/prod/prod/viewer.py": "def show():\n    return 0\n",
}


def test_g08_the_measured_scope_follows_the_producer_command(kinsim_loop):
    """A change to the replay viewer leaves a reading fresh; a change to the engine the producer's run imports stales it."""

    for relative, text in PRODUCER.items():
        write(kinsim_loop.repo / relative, text)
    curriculum_path = kinsim_loop.curriculum_dir / "curriculum.json"
    curriculum = json.loads(curriculum_path.read_text())
    curriculum["producer"] = {"cwd": "src/prod", "argv": ["python", "-m", "prod", "run"]}
    write_json(curriculum_path, curriculum)
    taken_at = commit_all(kinsim_loop.repo, "a producer with a run command and a replay viewer")
    kinsim_loop.retake(taken_at)  # the readings were taken with this producer (ledger rows and run manifests both say so)

    def rb9_gate() -> dict:
        gitinfo.clear_cache()
        document = kinsim.project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)
        return next(criterion for criterion in rung(document, "RB9")["criteria"] if criterion["id"] == "RB9#gate")

    assert rb9_gate()["verdict"] == "met"
    write(kinsim_loop.repo / "src/prod/prod/viewer.py", "def show():\n    return 1\n")
    commit_all(kinsim_loop.repo, "the replay viewer changed")
    assert rb9_gate()["verdict"] == "met"
    write(kinsim_loop.repo / "src/prod/prod/engine.py", "def run():\n    return 1\n")
    commit_all(kinsim_loop.repo, "the engine changed")
    gate = rb9_gate()
    assert gate["verdict"] == "stale" and any("the engine changed" in change for target in gate["targets"]
                                              for change in target["changed_since"]), gate


# ---------------------------------------------------------------- G09: recorded proof for a stated condition counts
@needs_kinsim
def test_g09_ev1s_review_condition_rests_on_the_cited_audit(tmp_path):
    """Codex G09: EV1 event 66 cites the a2-v2 audit (VERDICT: SHIP, candidate 3f5f297b); its criterion stayed unknown."""

    ev1 = rung(project_home(snapshot_home(tmp_path)), "EV1")
    audits = criteria_of(ev1, "audit")
    assert audits and (audits[0]["verdict"], audits[0]["strength"]) == ("met", "record"), ev1["criteria"]
    by_id = {item["id"]: item for item in ev1["evidence"]}
    evidence = [by_id[evidence_id] for evidence_id in audits[0]["evidence"]]
    assert evidence and evidence[0]["kind"] == "audit" and str(evidence[0]["commit"]).startswith("3f5f297b"), evidence


@needs_kinsim
def test_g09_ev2s_determinism_condition_rests_on_its_two_judged_runs(tmp_path):
    """Codex G09: EV2 event 67 names two judged budget-mode runs at 0.3 m/s with one verdict_hash; it stayed unknown."""

    ev2 = rung(project_home(snapshot_home(tmp_path)), "EV2")
    determinism = [criterion for criterion in ev2["criteria"] if criterion["id"].endswith("#determinism")]
    assert determinism and (determinism[0]["verdict"], determinism[0]["strength"]) == ("met", "record"), ev2["criteria"]
    by_id = {item["id"]: item for item in ev2["evidence"]}
    runs = sorted(by_id[evidence_id].get("run_id") for evidence_id in determinism[0]["evidence"])
    assert runs == sorted(BT2_RUNS), runs
    assert not [criterion for criterion in ev2["criteria"] if criterion["kind"] == "stated"], ev2["criteria"]

