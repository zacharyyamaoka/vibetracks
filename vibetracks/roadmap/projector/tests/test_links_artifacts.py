"""Citations, names and readers: the one place free text is parsed, pinned case by case.

The first block replays the three ways the frontend's own scraper went wrong (Codex A02, A07,
Oct 3) so this parser can never regress into them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibetracks.roadmap.projector import artifacts, evaluate, links


# ---------------------------------------------------------------- citations (Codex A02, F10, C02)
# WHY these expectations changed in round 2: the rule is now the one the dashboard serves and links by
# (bam-citation-corpus/1, pinned case by case in test_codex_r1.py); a whole token or nothing.
@pytest.mark.parametrize(("text", "expected"), [
    ("see /a/events.jsonl now", [("/a/events.jsonl", None, "text")]),
    ("a log /a/x.json.gz.", []),                                    # an archive is never a citation
    ("/a/x.tar.gz and /a/y.jsonl.gz", []),
    ("Codex /a/r.md:188 VERDICT: SHIP", [("/a/r.md", 188, "text")]),
    ("(/a/live.txt:11-13)", []),                                    # :LINE or :LINE:COL only
    ("w /a/v1.2/report.html:5,9", []),                              # html is not a served suffix
    ("the end is /a/x.txt.", [("/a/x.txt", None, "text")]),
    ("screenshots /a/shots/ here", []),                             # a folder is never cited
    ("a still (/a/frame.png)", [("/a/frame.png", None, "image")]),
    ("'/a/one.log /a/two.log' then /a/three.log", [("/a/three.log", None, "text")]),  # a quoted span (C02)
    ("no path in this sentence", []),
])
def test_a_cited_path_keeps_its_whole_name_and_its_line_apart(text, expected):
    assert [(citation.raw, citation.line, citation.kind) for citation in links.cited_paths(text)] == expected


def test_a_sibling_suffix_is_not_a_citation():
    """Round 1 expanded "_run2.txt" beside a cited path; the shared rule cites only whole absolute tokens."""

    assert [citation.raw for citation in links.cited_paths("three runs (/a/vz1_run1.txt, _run2.txt, _run3.txt)")] == [
        "/a/vz1_run1.txt"]


def test_run_1_is_not_run_10():
    """Codex A07: substring matching made run-1 look cited when only run-10 was."""

    citations = links.cited_paths("runs /a/run-10/batch.json only")
    assert [citation.raw for citation in citations] == ["/a/run-10/batch.json"]
    assert not links.names_target("run-10 passed", "tests/run-1")


@pytest.mark.parametrize(("clause", "target", "named"), [
    ("pytest tests/test_identify_twin.py -> 195 passed", "src/x/tests/test_identify_twin.py", True),
    ("(16/16 test_mjcf_camera)", "src/x/tests/test_mjcf_camera.py", True),
    ("pytest tests/test_identify_twin.py -> 195 passed", "src/dev/bam_deployments/tests", False),
    ("src/dev/bam_deployments: uv run pytest -q -> 142 passed", "src/dev/bam_deployments/tests", True),
    ("src/dev/bam_deployments: uv run pytest -q -> 200 passed", "src/dev/bam_deployments/tests/test_ingest.py", True),
    ("bam_gravity_comp: uv run pytest -q -> 59 passed", "src/core/bam_gravity_comp/tests/test_homing_sweep.py", True),
    ("traj_integration_tests: pytest tests/test_a.py -> 9 passed", "src/t/traj_integration_tests/tests/test_b.py", False),
    ("test_widget_acceptance.py.bak is old", "src/pkg/tests/test_widget_acceptance.py", False),
])
def test_names_target(clause, target, named):
    assert links.names_target(clause, target) is named


# ---------------------------------------------------------------- paths
def test_normalise_prefers_roots_and_keeps_existing_absolute_paths(tmp_path):
    repo, home, outside = tmp_path / "repo", tmp_path / "home", tmp_path / "reports"
    for folder in (repo / "src", home / "runs", outside):
        folder.mkdir(parents=True)
    (outside / "x.txt").write_text("x")
    (repo / "src" / "f.py").write_text("x")
    roots = links.Roots(repo=repo, data_home=home)
    assert links.normalise(str(repo / "src/f.py"), roots)[:2] == ("src/f.py", "repo")
    assert links.normalise(str(home / "runs/a.json"), roots)[:2] == ("runs/a.json", "data_home")
    assert links.normalise(str(outside / "x.txt"), roots)[:2] == (str(outside / "x.txt"), "abs")
    swept = "/home/nobody/.claude/worktrees/lane-1/src/f.py"
    assert links.normalise(swept, roots)[:2] == ("src/f.py", "repo")
    gone = links.link("log", "/tmp/bam-gate-xyz/gate_report.json", roots)
    assert gone["exists"] is False and gone["abs"] is None
    assert gone["why_unresolved"] == "folder not found (it was under /tmp, which is cleared at reboot)"


def test_a_line_past_the_end_does_not_resolve(tmp_path):
    (tmp_path / "a.md").write_text("one\ntwo\n")
    roots = links.Roots(repo=tmp_path)
    assert links.link("audit", str(tmp_path / "a.md"), roots, line=2)["exists"] is True
    past = links.link("audit", str(tmp_path / "a.md"), roots, line=9)
    assert past["exists"] is False and "past the end" in past["why_unresolved"]


def test_resolve_bare_name_never_guesses_among_equals():
    tracked = ["a/pkg/collision.py", "b/old/collision.py", "a/pkg/replay.py", "c/cli.py", "a/pkg/cli.py", "x/unique.py"]
    assert links.resolve_bare_name("unique.py", "", tracked, []) == ("x/unique.py", "unique file name")
    assert links.resolve_bare_name("collision.py", "", tracked, ["a/pkg"])[0] == "a/pkg/collision.py"
    assert links.resolve_bare_name("collision.py", "the old ", tracked, [])[0] == "b/old/collision.py"
    assert links.resolve_bare_name("cli.py", "", tracked, [], ["a/pkg/replay.py"])[0] == "a/pkg/cli.py"
    relative, why = links.resolve_bare_name("cli.py", "", tracked, [])
    assert relative is None and why.startswith("ambiguous: 2")


def test_bare_code_references():
    refs = links.bare_code_references("one URDF (collision.py:238-268); commits it as scripts/kinematic_gate.sh; notes.md")
    assert [(name, line, end) for name, line, end, _before in refs] == [
        ("collision.py", 238, 268), ("scripts/kinematic_gate.sh", None, None)]


def test_junit_classnames_map_to_files_and_classes():
    exists = {"src/pkg/tests/test_x.py", "src/pkg/bam/geometry_test.py"}.__contains__
    assert links.junit_file_for("tests.test_x", "src/pkg", exists) == ("src/pkg/tests/test_x.py", None)
    assert links.junit_file_for("tests.test_x.TestThing", "src/pkg", exists) == ("src/pkg/tests/test_x.py", "TestThing")
    assert links.junit_file_for("bam.geometry_test", "src/pkg", exists) == ("src/pkg/bam/geometry_test.py", None)
    assert links.junit_file_for("tests.test_gone", "src/pkg", exists) == (None, None)


def test_test_functions_give_def_lines_without_importing(tmp_path):
    test_file = tmp_path / "test_x.py"
    test_file.write_text("import sys\nsys.exit(3)\n\ndef test_a():\n    pass\n\nclass TestB:\n    @staticmethod\n    def test_c():\n        pass\n\ndef helper():\n    pass\n")
    assert [(function.key, function.line) for function in links.test_functions(test_file)] == [("test_a", 4), ("TestB::test_c", 9)]
    assert links.node_id("src/tests/test_x.py", "TestB::test_c") == "src/tests/test_x.py::TestB::test_c"


# ---------------------------------------------------------------- readers
def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.mark.parametrize(("text", "result", "facts"), [
    ("....\n328 passed in 10.41s\nEXIT 0\n", "passed", {"passed": 328, "exit": 0}),
    ("6 passed, 1 warning in 4.87s\n", "passed", {"passed": 6}),
    ("FAILED tests/test_a.py::test_b\n30 failed, 199 passed in 5.15s\nexit 1\n", "failed", {"failed": 30, "passed": 199, "exit": 1}),
    ("4 failed, 7 errors in 0.18s\n", "failed", {"failed": 4, "errors": 7}),
    ("34/34 checks passed; screenshots in /x\nEXIT 0\n", "passed", {"checks_passed": 34, "checks": 34}),
    ("5/6 checks passed\nEXIT 1\n", "failed", {"checks_passed": 5, "checks": 6}),
    ("10 passed in 1.0s\nEXIT 2\n", "failed", {"passed": 10, "exit": 2}),
    ("installing...\nno summary here\n", None, {}),
])
def test_read_log_reads_the_result_from_the_artifact(tmp_path, text, result, facts):
    reading = artifacts.read_log(write(tmp_path, "run.txt", text))
    assert reading.result == result
    assert {key: reading.facts[key] for key in facts} == facts


def test_read_log_follows_the_gate_line(tmp_path):
    reading = artifacts.read_log(write(tmp_path, "gate.txt", "suites...\nGATE PASS tier=fast report=/r/gate_report.json\nexit 0\n"))
    assert (reading.result, reading.pointer, reading.line) == ("passed", "/r/gate_report.json", 2)


@pytest.mark.parametrize(("text", "result", "verdict", "line"), [
    ("# Review\n...\nVERDICT: SHIP\n", "passed", "SHIP", 3),
    ("**DO-NOT-SHIP: x.**\n\nVERDICT: DO-NOT-SHIP\n", "failed", "DO-NOT-SHIP", 3),
    ("**SOUND WITH FIXES.** Findings 2 and 4 close.\n", "warned", "SOUND WITH FIXES", 1),
    ("**UNSOUND.** Re-approach can certify a stall.\n", "failed", "UNSOUND", 1),
    ("**FIX — nine majors remain.**\n", "failed", "FIX", 1),
    ("A report with no verdict line.\n", None, None, None),
])
def test_read_audit(tmp_path, text, result, verdict, line):
    reading = artifacts.read_audit(write(tmp_path, "audit.md", text))
    assert (reading.result, reading.facts.get("verdict"), reading.line) == (result, verdict, line)


def test_junit_keeps_every_case_with_its_parameters_and_every_red_kind(tmp_path):
    """Codex F06: cases are never folded by function, so a run of some parameters cannot stand for all of them."""

    junit = write(tmp_path, "junit.xml", '<testsuites><testsuite>'
                  '<testcase classname="tests.test_a" name="test_x[1]"/>'
                  '<testcase classname="tests.test_a" name="test_x[2]"><failure/></testcase>'
                  '<testcase classname="tests.test_a" name="test_y"><failure/><error/></testcase>'
                  '<testcase classname="tests.test_a.TestK" name="test_z"><skipped/></testcase>'
                  '</testsuite></testsuites>')
    cases = artifacts.junit_cases(junit)
    assert [(case.name, case.outcome) for case in cases] == [
        ("test_x[1]", "passed"), ("test_x[2]", "failed"), ("test_y", "failed+error"), ("test_z", "skipped")]
    assert evaluate.case_keys(cases) == ["test_x[1]", "test_x[2]", "test_y", "TestK::test_z"]
    assert artifacts.junit_result(cases) == "failed"
    assert artifacts.junit_result(cases[:1]) == "passed" and artifacts.junit_result(cases[3:]) is None


def test_log_mentions_reads_failed_lines_and_mentions(tmp_path):
    red = write(tmp_path, "red.txt", "FAILED tests/test_a.py::test_one\ntests/test_b.py::test_two warning\n1 failed, 3 passed in 1s\n")
    assert artifacts.log_mentions(red, {"test_a.py"}) == ("failed", True)
    assert artifacts.log_mentions(red, {"test_b.py"}) == ("ran", True)
    assert artifacts.log_mentions(red, {"test_c.py"}) == (None, True)


# ---------------------------------------------------------------- round 3: what a log shows about one file (Codex G05, G06)
TARGET = "src/pkg/tests/test_x.py"


@pytest.mark.parametrize(("name", "text", "result", "how", "ceiling"), [
    ("progress line, all passed", "$ (cd /r/src/pkg && pytest tests/test_x.py tests/test_y.py)\ntests/test_x.py ...   [ 50%]\n"
     "tests/test_y.py ..    [100%]\n5 passed in 0.10s\n", "passed", "pytest's progress line", None),
    ("a long file's progress wraps", "$ (cd /r/src/pkg && pytest tests/test_x.py)\ntests/test_x.py ......   [ 60%]\n....   [100%]\n"
     "10 passed in 0.10s\n", "passed", "pytest's progress line", None),
    ("progress line with a skip", "$ (cd /r/src/pkg && pytest tests/test_x.py)\ntests/test_x.py ..s   [100%]\n2 passed, 1 skipped in 0.10s\n",
     None, "pytest's progress line", None),
    ("progress line with a failure", "tests/test_x.py .F.   [100%]\n1 failed, 2 passed in 0.10s\n", "failed", "pytest's progress line", None),
    # Codex H01: the summary and the per-test record must agree; neither stands in for the other.
    ("a summary that disagrees with the progress line", "$ (cd /r/src/pkg && pytest tests/test_x.py)\ntests/test_x.py ..   [100%]\n"
     "3 passed in 0.10s\n", None, "pytest's progress line", None),
    ("a short summary beside skips", "$ (cd /r/src/pkg && pytest -rA tests/test_x.py)\ntests/test_x.py .sssss   [100%]\n"
     "PASSED tests/test_x.py::test_a\n1 passed, 5 skipped in 0.10s\n", None, "pytest's progress line", None),
    ("verbose lines of the whole file", "$ (cd /r/src/pkg && pytest -v tests/test_x.py)\ntests/test_x.py::test_a PASSED\n"
     "tests/test_x.py::test_b PASSED\n2 passed in 0.10s\n", "passed", "per-test lines", None),
    ("verbose lines of one node", "$ (cd /r/src/pkg && pytest -v tests/test_x.py::test_a)\ntests/test_x.py::test_a PASSED\n"
     "1 passed in 0.10s\n", None, "per-test lines", None),
    ("verbose lines, no command recorded", "tests/test_x.py::test_a PASSED\ntests/test_x.py::test_b PASSED\n2 passed in 0.10s\n",
     "passed", "per-test lines", "claim"),
    ("a short summary only", "$ (cd /r/src/pkg && pytest -q -rA tests/test_x.py::test_a)\n.   [100%]\nPASSED tests/test_x.py::test_a\n"
     "1 passed in 0.10s\n", None, "pytest's short summary only", None),
    ("pytest -q, selected whole and green", "$ (cd /r/src/pkg && pytest -q tests/test_x.py)\n...   [100%]\n3 passed in 0.1s\n",
     "passed", "selected whole, no per-test record", "claim"),
    ("pytest -q, deselected and not accounted", "$ (cd /r/src/pkg && pytest -q -k fast tests/test_x.py)\n..   [100%]\n"
     "2 passed, 1 deselected in 0.1s\n", None, "selected whole, no per-test record", None),
    ("pytest -q, deselected elsewhere, named", "$ (cd /r/src/pkg && pytest -q tests/test_x.py tests/test_y.py --deselect "
     "tests/test_y.py::test_slow)\n..   [100%]\n2 passed, 1 deselected in 0.1s\n", "passed", "selected whole, no per-test record", "claim"),
    ("only named on the command line of a red run", "$ (cd /r/src/pkg && pytest tests/test_x.py tests/test_z.py)\nERROR tests/test_z.py\n"
     "1 error in 0.1s\nEXIT 2\n", None, "none", None),
])
def test_target_evidence_needs_positive_execution(tmp_path, name, text, result, how, ceiling):
    """Codex G05, H01: the file's whole collection, selected by the run's own command, one outcome per test printed, every
    one a pass, and a summary that agrees; anything less keeps its word (ceiling claim) or proves nothing (None)."""

    reading = artifacts.target_evidence(write(tmp_path, "run.txt", text), TARGET)
    assert (reading.result, reading.facts.get("evidence"), reading.facts.get("ceiling")) == (result, how, ceiling), (name, reading)


def test_pytest_selection_reads_files_nodes_and_deselections():
    selection = artifacts.pytest_selection(["uv", "run", "--with", "pytest", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                            "-m", "acceptance", "tests/a.py", "tests/b.py::test_one", "--deselect", "tests/a.py::test_slow",
                                            "--junitxml=/x/junit.xml"])
    assert (selection.paths, selection.nodes, selection.deselect, selection.filtered) == (
        ["tests/a.py"], ["tests/b.py::test_one"], ["tests/a.py::test_slow"], True)
    assert artifacts.pytest_selection(["python", "-m", "traj_integration_tests", "run"]) is None
    assert artifacts.selects_whole(selection, "src/pkg/tests/a.py", "/r/src/pkg")
    assert not artifacts.selects_whole(selection, "src/pkg/tests/b.py", "/r/src/pkg")


TIER = [{"suite": "ladder", "cwd": "src/ladder", "argv": ["pytest", "-q"], "junit": True,
         "then": [{"argv": ["python", "-m", "ladder", "run", "--out", "{out}/smoke"]}, {"argv": ["python", "-m", "ladder", "gather"]}]}]


def ladder_report(then: list[dict], out: str = "/o") -> dict:
    return {"schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [], "root": "/r",
            "suites": [{"suite": "ladder", "cwd": "/r/src/ladder", "argv": ["pytest", "-q", f"--junitxml={out}/ladder/junit.xml"],
                        "junit": True, "exit_code": 0, "log": f"{out}/ladder/output.log", "then": then,
                        "counts": {"passed": 1, "failed": 0, "error": 0, "skipped": 0},
                        "unexpected_red": [], "unexpected_green": [], "expected_red": []}]}


def test_then_commands_are_reconciled_with_the_tier(tmp_path):
    """Codex G07: every declared then command ran, in order, with its declared argv, and exited 0."""

    out = str(tmp_path)
    (tmp_path / "ladder").mkdir()
    write(tmp_path / "ladder", "junit.xml", '<testsuites><testsuite><testcase classname="tests.test_l" name="test_one"/></testsuite></testsuites>')
    complete = [{"argv": ["python", "-m", "ladder", "run", "--out", f"{out}/ladder/smoke"], "exit_code": 0},
                {"argv": ["python", "-m", "ladder", "gather"], "exit_code": 0}]
    assert artifacts.gate_report_reading(ladder_report(complete, out), TIER).result == "passed"
    short = artifacts.gate_report_reading(ladder_report(complete[:1], out), TIER)
    assert short.result is None and "ran 1 of the tier's 2 then commands" in " ".join(short.facts["problems"])
    other = [{**complete[0], "argv": ["python", "-m", "ladder", "run"]}, complete[1]]
    assert artifacts.gate_report_reading(ladder_report(other, out), TIER).result is None
    assert artifacts.gate_report_reading({**ladder_report(complete, out), "suites": []}, TIER).result is None
    # Codex H03: the report's own counts must equal its JUnit file reopened; one forged failure certifies nothing.
    forged = ladder_report(complete, out)
    forged["suites"][0]["counts"]["failed"] = 1
    assert artifacts.gate_report_reading(forged, TIER).result is None
