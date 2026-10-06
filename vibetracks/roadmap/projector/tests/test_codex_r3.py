"""Codex round 3 (reports/media/audits/2026-10-03-bam-roadmap-format-r3.md): one regression per finding, H01-H06, and
the OUTDATED verdict both reviews asked for.

H01-H04 share one root: proof inferred from logs, timestamps and self-reported summaries. Each test replays Codex's own
mutation (of a real artifact where the artifact can be copied, in memory where it is a loop file this package must not
touch) and asserts the class is closed. Only APIs that existed at 69697676 are used outside the OUTDATED test, so each
case fails there on its assertion, not on an import. Real-data cases skip where the loop's files are absent; they pin
the head they judge at, so the live loop cannot move under them.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import artifacts, gitinfo, kinsim, links, model, proof
from vibetracks.roadmap.projector import validate as validate_module
from vibetracks.roadmap.projector.evaluate import Evaluator, tier_definition_at
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import ACCEPTANCE, append_jsonl, commit_all, write, write_json
from .test_codex_r2 import (CURRICULUM_DIR, LATENCY_ACCEPTANCE, NOW, REAL_REPORT, SIZES_TEST, criteria_of, evaluator_for,
                            needs_kinsim, rung, snapshot_home)

STATE_CONTRACT = "src/dev/bam_curriculum/tests/acceptance/test_loop_state_contract_acceptance.py"
LOOP_TOOLS_FILE = "src/dev/bam_curriculum/tests/acceptance/test_loop_tools_acceptance.py"
PARTIAL_NODES = ((STATE_CONTRACT, "test_package_and_contract_files_exist"),
                 (LOOP_TOOLS_FILE, "test_judge_writes_a_complete_run_and_exactly_one_ledger_row"))
TIERS = "src/dev/bam_curriculum/tiers.json"
REPORT_COMMIT = "5b225c15"  # where git's reflog placed the real fast-gate report (Codex H02, H03)


def pinned_head() -> str:
    gitinfo.clear_cache()
    return gitinfo.Repo(CURRICULUM_DIR).head


def project_at(home: Path, head: str) -> dict:
    gitinfo.clear_cache()
    return kinsim.project_kinsim(CURRICULUM_DIR, home, now=NOW, head=head)


def report_checkout() -> tuple[gitinfo.Repo, Evaluator]:
    """The checkout the real fast-gate report names (the loop's own), at its HEAD now: where Codex judged it."""

    root = Path(json.loads(REAL_REPORT.read_text())["root"])
    if not root.is_dir():
        pytest.skip("the checkout the fast gate ran in is gone")
    gitinfo.clear_cache()
    repo = gitinfo.Repo(root)
    return repo, Evaluator(repo, links.Roots(repo=repo.root, data_home=None))


def after_the_last_head_move(root: Path, wall_s: float) -> float:
    """A file time whose whole run window [t - wall_s, t] follows the checkout's last HEAD move: the time a copy made now
    would carry when the loop is quiet (Codex's st_mtime=time.time()), without depending on whether it is quiet."""

    stamp = subprocess.run(["git", "-C", str(root), "reflog", "show", "--date=unix", "--format=%gd", "-1", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
    return float(stamp[stamp.index("{") + 1:stamp.rindex("}")]) + wall_s + 2.0


# ---------------------------------------------------------------- H01: a partial run does not prove a whole file
def partial_log(head: str, cwd: str, style: str) -> str:
    """Codex's log: one test of each of RG2's two files, each run printing PASSED, "1 passed" and EXIT 0."""

    lines = [f"HEAD {head};"]
    for target, name in PARTIAL_NODES:
        node = f"{target.split('bam_curriculum/', 1)[1]}::{name}"
        if style == "verbose":
            lines += [f"$ (cd {cwd} && python -m pytest -v -p no:cacheprovider {node})", f"{node} PASSED{' ' * 20}[100%]"]
        elif style == "short summary":
            lines += [f"$ (cd {cwd} && python -m pytest -q -rA -p no:cacheprovider {node})", f".{' ' * 40}[100%]",
                      "=========================== short test summary info ============================", f"PASSED {node}"]
        else:  # no command line recorded
            lines += [f"{node} PASSED{' ' * 20}[100%]"]
        lines += ["1 passed in 0.50s", "EXIT 0"]
    return "\n".join(lines) + "\n"


@needs_kinsim
@pytest.mark.parametrize("style", ["verbose", "short summary", "no command line"])
def test_h01_a_partial_run_does_not_prove_a_whole_file(tmp_path, style):
    """Codex H01: a commit-bound log that ran only test_package_and_contract_files_exist and
    test_judge_writes_a_complete_run_and_exactly_one_ledger_row, each "PASSED, 1 passed, EXIT 0", made RG2 green."""

    head = pinned_head()
    home = snapshot_home(tmp_path)
    log = write(tmp_path / "evidence" / "rg2_partial.txt", partial_log(head, str(CURRICULUM_DIR.resolve()), style))
    append_jsonl(home / "loop_events.jsonl", {"ts": "2026-10-03T21:59:00+00:00", "wave": 4, "kind": "rung_status_changed",
                                              "subject": "RG2", "status": "green", "detail": "Codex H01", "commit": head[:8],
                                              "evidence": f"B3 + lane acceptance ({log})"})
    rg2 = rung(project_at(home, head), "RG2")
    targets = criteria_of(rg2, "test")[0]["targets"]
    proven = [target["path"] for target in targets if target["verdict"] == "met" and target["strength"] in model.PROOF_STRENGTHS]
    assert rg2["status"] != "green" and not proven, (rg2["status"], [(t["path"], t["verdict"], t["strength"], t["note"]) for t in targets])


@needs_kinsim
def test_h01_a_short_summary_never_overrides_the_progress_line(tmp_path):
    """Codex H01: a passing short-summary line beside ".sssss" progress and "1 passed, 5 skipped" earned met/log."""

    head = pinned_head()
    repo = gitinfo.Repo(CURRICULUM_DIR, head)
    cwd = repo.root / "src/core/mdp/agent/actor/trajectory_generation/bam_traj_gen/src"
    log = write(tmp_path / "run.txt",
                f"HEAD {head};\n$ (cd {cwd} && pytest -rA -p no:cacheprovider tests/test_latency_modes_acceptance.py)\n"
                f"tests/test_latency_modes_acceptance.py .sssss{' ' * 30}[100%]\n"
                "=========================== short test summary info ============================\n"
                "PASSED tests/test_latency_modes_acceptance.py::test_budget_mode_calls_the_planner_once_with_the_declared_latency\n"
                "1 passed, 5 skipped in 0.50s\nEXIT 0\n")
    evaluator = evaluator_for(repo)
    item = proof.cited_item(links.cited_paths(f"({log})")[0], evaluator.roots, commit=head, ts=NOW, origin="event", event=None)
    judgement = evaluator.judge_test(item, LATENCY_ACCEPTANCE, [LATENCY_ACCEPTANCE], {})
    assert judgement.verdict != "met", judgement


# ---------------------------------------------------------------- H02: a file time binds no commit
@pytest.mark.parametrize("copied", [False, True], ids=["in place", "copied"])
def test_h02_a_file_time_binds_no_commit(tmp_path, copied):
    """Codex H02: the real fast-gate report's mtime placed it, through git's reflog, at 5b225c15; a copy with the same
    bytes and a new mtime was placed at the checkout's newest HEAD and earned met/log."""

    if not REAL_REPORT.is_file():
        pytest.skip("the fast gate's /tmp report is not on this machine")
    repo, evaluator = report_checkout()
    path = REAL_REPORT
    if copied:
        path = tmp_path / "gate_report.json"
        shutil.copyfile(REAL_REPORT, path)  # the report's bytes; the file time is the copy's own
        moment = after_the_last_head_move(repo.root, float(json.loads(REAL_REPORT.read_text()).get("wall_s") or 0.0))
        os.utime(path, (moment, moment))
    item = {**links.link("gate_report", str(path), evaluator.roots), "result": "passed", "strength": "record", "commit": None,
            "ts": NOW, "origin": "gate_report", "facts": {}, "as_cited": None, "event": None, "commit_source": None}
    judgement = evaluator.judge_gate(item, "fast", [], {})
    assert judgement.strength not in model.PROOF_STRENGTHS, judgement
    assert judgement.commit is None, judgement  # nothing the run wrote names a commit


# ---------------------------------------------------------------- H03: contradictory counts certify nothing
def synthetic_report(tmp_path: Path) -> dict:
    """A one-suite report whose records all agree: three passing cases in its JUnit file, counted as three."""

    out = tmp_path / "gate"
    junit = write(out / "ladder" / "junit.xml", '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
                  + "".join(f'<testcase classname="tests.test_ladder" name="test_{index}" time="0.01"/>' for index in range(3))
                  + "</testsuite></testsuites>")
    log = write(out / "ladder" / "output.log", f"$ (cd /x/root/ladder && pytest -q --junitxml={junit})\n...  [100%]\n3 passed in 0.10s\n")
    return {"schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [], "tier": "fast",
            "root": "/x/root", "suites": [{"suite": "ladder", "cwd": "/x/root/ladder", "argv": ["pytest", "-q", f"--junitxml={junit}"],
                                           "junit": True, "exit_code": 0, "counts": {"passed": 3, "failed": 0, "error": 0, "skipped": 0},
                                           "unexpected_red": [], "unexpected_green": [], "expected_red": [], "then": [], "log": str(log)}]}


def failed_count(report: dict) -> dict:
    mutant = copy.deepcopy(report)
    mutant["suites"][0]["counts"]["failed"] = 1  # exit_code 0, expected_red empty, aggregate flags untouched
    return mutant


@pytest.mark.parametrize("which", ["synthetic", "real"])
def test_h03_contradictory_counts_certify_nothing(tmp_path, which):
    """Codex H03: suites[0].counts.failed 0 -> 1 in the real fast-gate report, exit 0 and empty expected_red kept, read
    passed with the actual tier definition supplied."""

    if which == "real":
        if not REAL_REPORT.is_file():
            pytest.skip("the fast gate's /tmp report is not on this machine")
        report = json.loads(REAL_REPORT.read_text())
        definition = tier_definition_at(report_checkout()[0], TIERS, "fast", REPORT_COMMIT)
    else:
        report, definition = synthetic_report(tmp_path), None
    assert artifacts.gate_report_reading(report, definition).result == "passed"
    assert artifacts.gate_report_reading(failed_count(report), definition).result != "passed"


def test_h03_judge_gate_does_not_certify_contradictory_counts(tmp_path):
    """Codex H03, at the evaluator: the same mutant, at its original bound commit, judged met/log."""

    if not REAL_REPORT.is_file():
        pytest.skip("the fast gate's /tmp report is not on this machine")
    repo, evaluator = report_checkout()
    mutated = write(tmp_path / "gate_report.json", json.dumps(failed_count(json.loads(REAL_REPORT.read_text()))))
    shutil.copystat(REAL_REPORT, mutated)  # its original file time: where 69697676's reflog binding placed it, 5b225c15
    item = {**links.link("gate_report", str(mutated), evaluator.roots), "result": "passed", "strength": "record",
            "commit": REPORT_COMMIT, "ts": NOW, "origin": "gate_report", "facts": {}, "as_cited": None, "event": None,
            "commit_source": "citation"}
    judgement = evaluator.judge_gate(item, "fast", [], {}, tier_definition=tier_definition_at(repo, TIERS, "fast", REPORT_COMMIT))
    assert judgement.verdict != "met", judgement


# ---------------------------------------------------------------- H04: the run's recorded inputs are part of freshness
@needs_kinsim
@pytest.mark.parametrize(("field", "value"), [("start", 64), ("count", 128), ("seed", 1), ("producer_corpus_id", "kinematic-pick/other")])
def test_h04_a_changed_corpus_input_stales_the_measured_proof(tmp_path, field, value):
    """Codex H04: rb0-regression's start moved 0 -> 64 in the curriculum input (in memory); both run manifests still
    record start 0, count 64; RB0's gate stayed met/record and default validation returned []. The other fields are
    the same class: whatever the gate's corpus asks for now that the run did not run on."""

    head = pinned_head()
    home = snapshot_home(tmp_path)
    gitinfo.clear_cache()
    inputs = kinsim.read_inputs(CURRICULUM_DIR, home)
    corpus = next(corpus for corpus in inputs.curriculum["corpora"] if corpus["corpus_id"] == "rb0-regression")
    assert corpus[field] != value
    corpus[field] = value
    repo = gitinfo.Repo(inputs.curriculum_dir, head)
    roots = links.Roots(repo=repo.root, data_home=inputs.data_home, repo_aliases=repo.other_checkouts())
    document = kinsim._Projector(inputs, repo, roots).document(NOW)
    gate = next(criterion for criterion in rung(document, "RB0")["criteria"] if criterion["id"] == "RB0#gate")
    regression = next(target for target in gate["targets"] if "regression" in target["label"])
    assert regression["verdict"] == "stale" and any(field in change for change in regression["changed_since"]), regression
    if field == "start":
        assert validate_document(document, head=head), "the document says start 64; the loop's curriculum says 0"


# ---------------------------------------------------------------- H05: a repeated JUnit case is one test
def test_h05_duplicate_junit_cases_cannot_cover_a_missing_parameter(kinsim_loop, tmp_path):
    """Codex H05: the source declares parameters a and b; the JUnit file holds test_widget_sizes[a] twice; the run's
    summary says 2 passed. The evaluator returned met/record."""

    target = "src/pkg/tests/test_sizes_acceptance.py"
    write(kinsim_loop.repo / target, SIZES_TEST)
    commit = commit_all(kinsim_loop.repo, "a parametrized acceptance test")
    junit = write(tmp_path / "acc" / "junit.xml", '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
                  + '<testcase classname="tests.test_sizes_acceptance" name="test_widget_sizes[a]" time="0.01"/>' * 2
                  + "</testsuite></testsuites>")
    cwd = kinsim_loop.repo / "src/pkg"
    argv = ["pytest", "-q", "-p", "no:cacheprovider", "tests/test_sizes_acceptance.py", f"--junitxml={junit}"]
    log = write(tmp_path / "acc" / "output.log", f"$ (cd {cwd} && {' '.join(argv)})\n..  [100%]\n2 passed in 0.05s\n")
    report = write_json(tmp_path / "gate_report.json", {
        "schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [], "tier": "fast",
        "root": str(kinsim_loop.repo), "suites": [{"suite": "acc", "cwd": str(cwd), "argv": argv, "junit": True, "exit_code": 0,
                                                    "counts": {"passed": 2, "failed": 0, "error": 0, "skipped": 0}, "then": [],
                                                    "unexpected_red": [], "unexpected_green": [], "expected_red": [], "log": str(log)}]})
    console = write(tmp_path / "gate.txt", f"HEAD {commit};\nGATE PASS tier=fast report={report}\nexit 0\n")
    repo = gitinfo.Repo(kinsim_loop.repo)
    roots = links.Roots(repo=repo.root, data_home=kinsim_loop.data_home)
    console_link = links.link("log", str(console), roots)
    facts = {"report": str(report), "suite": "acc", "suite_dir": "src/pkg", "console": {"path": console_link["path"], "base": console_link["base"]},
             "passed": 2, "skipped": 0, "red": 0}
    via = {**links.link("junit", str(junit), roots), "result": "passed", "strength": "record", "commit": commit, "ts": NOW,
           "origin": "gate_report", "facts": facts, "as_cited": None, "event": None, "commit_source": "artifact"}
    item = {**links.link("test", target, roots), "result": "passed", "strength": "record", "commit": commit, "ts": NOW,
            "origin": "junit", "facts": facts, "as_cited": None, "event": None, "commit_source": "artifact"}
    judgement = Evaluator(repo, roots).judge_test(item, target, [target], {}, via=via)
    assert judgement.verdict != "met", judgement


# ---------------------------------------------------------------- H06: a source link is compared and opened
@needs_kinsim
def test_h06_a_broken_source_link_does_not_validate(tmp_path):
    """Codex H06: the ledger source's abs changed to /definitely/missing/ledger.jsonl, role and hash kept, validated []."""

    head = pinned_head()
    document = project_at(snapshot_home(tmp_path), head)
    mutant = copy.deepcopy(document)
    ledger = next(source for source in mutant["sources"] if source["role"] == "ledger")
    ledger["abs"] = "/definitely/missing/ledger.jsonl"
    problems = validate_document(mutant, head=head)
    assert any(problem.startswith("source ledger") for problem in problems), problems


# ---------------------------------------------------------------- OUTDATED: the loop moved, every status still holds
def test_outdated_is_a_moved_loop_whose_statuses_hold(kinsim_loop, capsys):
    """Both reviews (Codex round 3, the round-2 report): a document whose loop moved since it was projected, but which
    projects again with every rung's status and claim unchanged, is OUTDATED; one whose statuses changed is INVALID."""

    check = getattr(validate_module, "validate", None)
    assert check is not None, "validate gives no verdict, only a list of problems"
    gitinfo.clear_cache()
    document = kinsim.project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)
    assert check(document).verdict == "valid"
    write(kinsim_loop.repo / "docs/notes.md", "an unrelated change\n")
    commit_all(kinsim_loop.repo, "the loop moves on")
    kinsim_loop.event(ts="2026-10-03T14:00:00+00:00", kind="note", subject="wave", status="ok", evidence="a note")
    gitinfo.clear_cache()
    outdated = check(document)
    assert outdated.verdict == "outdated" and outdated.differences and not outdated.problems, outdated
    assert any("moved" in what for what in outdated.moved), outdated.moved
    path = write_json(kinsim_loop.repo.parent / "outdated.json", document)
    from vibetracks.roadmap.projector.__main__ import main

    assert main(["validate", str(path)]) == 3
    assert "OUTDATED" in capsys.readouterr().out
    kinsim_loop.gate_run("gate_red", kinsim_loop.first_commit, {"tests.test_widget_acceptance::test_widget_builds": "failed",
                                                                "tests.test_widget_acceptance.TestWidget::test_widget_spins": "passed"},
                         ts="2026-10-03T15:00:00+00:00")
    gitinfo.clear_cache()
    assert check(document).verdict == "invalid"  # EV9's status changed: the document misstates the loop now


def test_a_document_that_reprojects_exactly_is_valid_and_its_details_are_not_outdated(kinsim_loop):
    """Nothing moved and nothing differs: valid. Nothing moved but a detail differs: invalid, never outdated."""

    check = getattr(validate_module, "validate", None)
    assert check is not None, "validate gives no verdict, only a list of problems"
    gitinfo.clear_cache()
    document = kinsim.project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)
    mutant = copy.deepcopy(document)
    rung(mutant, "EV9")["criteria"][0]["targets"][0]["note"] = "a forged detail"
    assert check(mutant).verdict == "invalid"
    assert check(document).verdict == "valid"
    assert ACCEPTANCE in json.dumps(document)
