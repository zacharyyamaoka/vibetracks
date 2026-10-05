"""Codex round 1 (reports/media/audits/2026-10-03-bam-roadmap-format-r1.md): one regression per finding.

Each test replays Codex's own reproduction: a mutation of the real loop inputs in memory (as Codex
did), a mutation of a projected document, or a synthetic artifact. Every one failed on c203b7a1
before its fix. Real-data tests skip where the kinsim loop's files are absent.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import artifacts, gitinfo, kinsim, links
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import KINSIM_CURRICULUM_DIR, LOOP_DEV_DIR

REPOSITORY = LOOP_DEV_DIR.parents[1]
CURRICULUM_DIR = KINSIM_CURRICULUM_DIR
DATA_HOME = Path(os.environ.get("BAM_CURRICULUM_HOME", "~/.local/share/bam_curriculum")).expanduser()
#: WHY the corpus vibetracks ships (next to citations.py), not the loop checkout's: that checkout's dashboard predates it,
#: so reading it there skipped the shared rule's pin silently.
CORPUS = Path(__file__).resolve().parents[2] / "citation_corpus.json"
NOW = "2026-10-03T21:00:00+00:00"
ACC_B1_LOG = "/home/bam/bam_ws/reports/media/kinematic-curriculum-wave1-2026-09-30/report-verify/acc_b1_log_v2.log"
LOG_V2 = "src/core/mdp/env/sim/bam_eval/tests/test_log_v2_acceptance.py"

needs_kinsim = pytest.mark.skipif(not (CURRICULUM_DIR / "curriculum.json").is_file() or not (DATA_HOME / "status.json").is_file(),
                                  reason="the kinsim loop's curriculum or data home is not on this machine")


def project(mutate=None) -> dict:
    """Project the real kinsim loop with its inputs changed in memory first, the way Codex reproduced."""

    inputs = kinsim.read_inputs(CURRICULUM_DIR, DATA_HOME)
    if mutate is not None:
        mutate(inputs)
    gitinfo.clear_cache()
    repo = gitinfo.Repo(inputs.curriculum_dir)
    roots = links.Roots(repo=repo.root, data_home=inputs.data_home, repo_aliases=repo.other_checkouts())
    return kinsim._Projector(inputs, repo, roots).document(NOW)


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


def criteria_of(rung_entry: dict, kind: str) -> list[dict]:
    return [criterion for criterion in rung_entry["criteria"] if criterion["kind"] == kind]


def append_event(inputs, **row) -> dict:
    """An event appended to loop_events.jsonl, with the next physical line."""

    line = max((event.get("_line") or 0 for event in inputs.events), default=0) + 1
    event = {"ts": "2026-10-03T20:00:00+00:00", "wave": 4, "kind": "note", "subject": "x", "status": "ok", "detail": "",
             "commit": None, "evidence": None, "_line": line, **row}
    inputs.events.append(event)
    return event


@pytest.fixture(scope="module")
def document() -> dict:
    if not (CURRICULUM_DIR / "curriculum.json").is_file() or not (DATA_HOME / "status.json").is_file():
        pytest.skip("the kinsim loop's files are not on this machine")
    return project()


# ---------------------------------------------------------------- F01 (blocker)
@needs_kinsim
def test_f01_validate_rereads_the_evidence_it_was_handed(document):
    """Codex F01: EV1's supporting evidence rewritten to failed, an unknown commit, /etc/hostname:999999 -> still valid."""

    mutant = copy.deepcopy(document)
    ev1 = rung(mutant, "EV1")
    for item in ev1["evidence"]:
        if item["id"] in ev1["support"]["evidence"]:
            item.update(result="failed", commit="0" * 40, path="/etc/hostname", base="abs", abs="/etc/hostname", line=999999)
    assert validate_document(mutant) != []


@needs_kinsim
def test_f01_a_met_criterion_needs_its_evidence(document):
    """Codex F01: removing every target evidence id and clearing support still validated."""

    mutant = copy.deepcopy(document)
    ev1 = rung(mutant, "EV1")
    for criterion in ev1["criteria"]:
        criterion["evidence"] = []
        for target in criterion["targets"]:
            target["evidence"] = []
    ev1["support"] = {"evidence": [], "runs": [], "events": [], "commits": [], "rungs": []}
    for item in ev1["evidence"]:
        item["role"], item["superseded_by"] = "context", None
    assert validate_document(mutant) != []


@needs_kinsim
def test_f01_a_fabricated_audit_criterion_is_rejected(document):
    """Codex F01: an audit criterion that says met/record with no targets validated."""

    mutant = copy.deepcopy(document)
    rung(mutant, "RB0")["criteria"].append({
        "id": "RB0#audit", "kind": "audit", "method": "inspection", "title": "Codex said SHIP", "text": "", "source": None,
        "targets": [], "verdict": "met", "strength": "record", "reason": "trust me", "evidence": [], "at": []})
    assert validate_document(mutant, check_disk=False) != []


# ---------------------------------------------------------------- F02
@needs_kinsim
def test_f02_a_later_partial_event_revokes_a_stale_green_fold():
    """Codex F02: a later EV1 status event says partial; status.json (the fold) still says green."""

    def revoke(inputs):
        append_event(inputs, ts="2026-10-03T20:30:00+00:00", kind="rung_status_changed", subject="EV1", status="partial",
                     commit="23cfa12f", evidence="revoked")

    ev1 = rung(project(revoke), "EV1")
    assert ev1["claimed_by"]["event"]["status"] == "partial"
    assert ev1["claimed_status"] == "partial"
    assert ev1["status"] == "partial"


# ---------------------------------------------------------------- F03
@needs_kinsim
def test_f03_an_alias_cycle_is_rejected(document):
    """Codex F03: green OB0 made an alias of itself (target and support updated) validated."""

    mutant = copy.deepcopy(document)
    ob0 = rung(mutant, "OB0")
    ob0["alias_of"] = "OB0"
    for criterion in criteria_of(ob0, "alias"):
        for target in criterion["targets"]:
            target["label"], target["note"] = "OB0", "OB0 is green"
    ob0["support"]["rungs"] = ["OB0"]
    for edge in mutant["edges"]:
        if edge["to"] == "OB0" and edge["kind"] == "same_as":
            edge["from"] = "OB0"
    assert validate_document(mutant, check_disk=False) != []


@needs_kinsim
def test_f03_a_prerequisite_is_checked_for_strength_too(document):
    """Codex F03: EV1 downgraded to claimed; RB0's prerequisite criterion left met/record still validated.

    The mutation sets Codex's whole end state (EV1 claimed, RB0's prerequisites still met/record on it), so the
    test reproduces it whatever EV1 projects to today (since round 1 it projects to claimed on its own).
    """

    mutant = copy.deepcopy(document)
    rung(mutant, "EV1")["status"] = "claimed"
    prerequisites = criteria_of(rung(mutant, "RB0"), "prerequisites")[0]
    prerequisites["verdict"], prerequisites["strength"] = "met", "record"
    for target in prerequisites["targets"]:
        target["verdict"], target["strength"] = "met", "record"
    problems = validate_document(mutant, check_disk=False)
    assert any("RB0" in problem and "prerequisite" in problem for problem in problems), problems


@needs_kinsim
def test_f03_every_rung_with_prerequisites_checks_them():
    """Codex F03: OB0 given a claimed VZ4 prerequisite stayed green (no prerequisites criterion on aliases)."""

    def depend(inputs):
        next(item for item in inputs.curriculum["rungs"] if item["rung_id"] == "OB0")["prerequisites"] = ["VZ4"]

    ob0 = rung(project(depend), "OB0")
    prerequisites = criteria_of(ob0, "prerequisites")
    assert prerequisites and [target["label"] for target in prerequisites[0]["targets"]] == ["VZ4"]
    assert ob0["status"] != "green"


# ---------------------------------------------------------------- F04
@needs_kinsim
def test_f04_a_citation_alone_does_not_bind_a_log_to_a_test():
    """Codex F04: acc_b1_log_v2.log cited beside test_model.py at c203b7a1; the log never names that file."""

    target = "src/dev/bam_roadmap/tests/test_model.py"

    def cite(inputs):
        next(item for item in inputs.curriculum["rungs"] if item["rung_id"] == "RG1")["gate"]["acceptance"] = [target]
        append_event(inputs, ts="2026-10-03T20:40:00+00:00", kind="rung_status_changed", subject="RG1", status="green",
                     commit="c203b7a1", evidence=f"'pytest {target}' -> 26 passed ({ACC_B1_LOG})")

    assert artifacts.log_mentions(Path(ACC_B1_LOG), {"test_model.py"})[0] is None
    rg1 = rung(project(cite), "RG1")
    entry = next(item for criterion in criteria_of(rg1, "test") for item in criterion["targets"] if item["path"] == target)
    assert entry["strength"] == "claim", entry
    assert rg1["status"] != "green"


# ---------------------------------------------------------------- F05
@pytest.mark.parametrize(("name", "text", "allowed"), [
    ("a quoted example is not a summary", "Expected output: 123 passed in 0.1s\n", (None,)),
    ("the last run decides, not an earlier one", "....\n10 passed in 1.0s\n\nsecond run\n1 skipped in 0.1s\nEXIT 0\n", (None,)),
    ("an earlier red run is not erased by a later green one", "EXIT 1\n10 passed in 1.0s\nEXIT 0\n", ("failed",)),
])
def test_f05_a_log_is_read_one_run_at_a_time(tmp_path, name, text, allowed):
    log = tmp_path / "run.txt"
    log.write_text(text)
    assert artifacts.read_log(log).result in allowed, name


# ---------------------------------------------------------------- F06
def write_gate_run(tmp_path: Path, name: str, cases: list[tuple[str, str, str]], *, suite_dir: str) -> Path:
    """A console log + gate_report.json + junit.xml for one suite; cases are (classname, name, outcome)."""

    out = tmp_path / name
    (out / "acc").mkdir(parents=True)
    body = "".join(f'<testcase classname="{classname}" name="{case}" time="0.01">'
                   + {"skipped": "<skipped/>", "failed": "<failure/>", "error": "<error/>"}.get(outcome, "") + "</testcase>"
                   for classname, case, outcome in cases)
    junit = out / "acc" / "junit.xml"
    junit.write_text(f'<testsuites><testsuite name="pytest" timestamp="2026-10-03T20:00:00+00:00">{body}</testsuite></testsuites>')
    report = out / "gate_report.json"
    report.write_text(json.dumps({"schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [],
                                  "tier": "fast", "root": "/x/root", "suites": [
                                      {"suite": "acc", "cwd": f"/x/root/{suite_dir}", "junit": True, "exit_code": 0,
                                       "argv": ["pytest", f"--junitxml={junit}"], "counts": {}, "then": [],
                                       "unexpected_red": [], "unexpected_green": [], "expected_red": [], "details": {},
                                       "log": str(out / "acc" / "output.log")}]}))
    console = tmp_path / f"{name}.txt"
    console.write_text(f"GATE PASS tier=fast report={report}\nexit 0\n")
    return console


@needs_kinsim
def test_f06_skipped_tests_are_not_coverage(tmp_path):
    """Codex F06: one passing testcase plus 17 skipped for test_log_v2_acceptance.py became met/record."""

    functions = links.test_functions(REPOSITORY / LOG_V2)
    assert len(functions) == 18
    cases = [("tests.test_log_v2_acceptance", functions[0].key.split("::")[-1], "passed")]
    cases += [("tests.test_log_v2_acceptance", function.key.split("::")[-1], "skipped") for function in functions[1:]]
    console = write_gate_run(tmp_path, "gate_skips", cases, suite_dir="src/core/mdp/env/sim/bam_eval")

    def only_this_run(inputs):
        inputs.events[:] = []
        append_event(inputs, ts="2026-10-03T20:50:00+00:00", kind="gate_run", subject="fast", status="pass",
                     commit="23cfa12f", evidence=f"gate ({console})")

    ev1 = rung(project(only_this_run), "EV1")
    entry = next(item for criterion in criteria_of(ev1, "test") for item in criterion["targets"] if item["path"] == LOG_V2)
    assert entry["verdict"] != "met", entry


def test_f06_a_run_of_some_parameters_does_not_cover_all_of_them(kinsim_loop, tmp_path):
    """Codex F06: parameter folding hid a run that executed only a subset of a test's parameter cases."""

    from .conftest import ACCEPTANCE

    module = "tests.test_widget_acceptance"
    kinsim_loop.gate_run("gate_full", kinsim_loop.first_commit, {
        f"{module}::test_widget_builds[a]": "passed", f"{module}::test_widget_builds[b]": "passed",
        f"{module}.TestWidget::test_widget_spins": "passed"}, ts="2026-10-03T10:00:00+00:00")
    # The subset run records how it was selected: "-k not b", 1 deselected (Codex G06: completeness comes from the
    # run's recorded collection, never from what other runs happened to execute).
    kinsim_loop.gate_run("gate_subset", kinsim_loop.first_commit, {
        f"{module}::test_widget_builds[a]": "passed", f"{module}.TestWidget::test_widget_spins": "passed"},
        ts="2026-10-03T11:00:00+00:00", select=["-k", "not b"], deselected=1)
    gitinfo.clear_cache()
    document = kinsim.project_kinsim(kinsim_loop.curriculum_dir, kinsim_loop.data_home, now=NOW)
    ev9 = rung(document, "EV9")
    target = ev9["criteria"][0]["targets"][0]
    assert target["path"] == ACCEPTANCE
    by_id = {item["id"]: item for item in ev9["evidence"]}
    chosen = by_id[target["evidence"][0]]
    record = by_id[chosen["via"]] if chosen.get("via") else chosen  # the JUnit file the chosen result was read from
    assert "gate_subset" not in record["path"], (chosen, record)


# ---------------------------------------------------------------- F07
@pytest.mark.parametrize(("name", "report"), [
    ("an empty report", {"schema": "bam-gate-report/1", "passed": True, "suites": []}),
    ("a report that contradicts its suites", {"schema": "bam-gate-report/1", "passed": True, "unexpected_red": ["acc::test_x"],
                                              "unexpected_green": [], "suites": [{"suite": "acc", "junit": True, "exit_code": 1,
                                                                                  "unexpected_red": ["acc::test_x"]}]}),
])
def test_f07_a_gate_report_cannot_certify_itself(tmp_path, name, report):
    path = tmp_path / "gate_report.json"
    path.write_text(json.dumps(report))
    assert artifacts.read_any("gate_report", path).result != "passed", name


@needs_kinsim
def test_f07_an_empty_report_does_not_make_the_fast_gate_a_record(tmp_path):
    report = tmp_path / "gate_report.json"
    report.write_text(json.dumps({"schema": "bam-gate-report/1", "passed": True, "suites": []}))
    console = tmp_path / "gate_empty.txt"
    console.write_text(f"GATE PASS tier=fast report={report}\nexit 0\n")

    def empty_gate(inputs):
        append_event(inputs, ts="2026-10-03T20:55:00+00:00", kind="gate_run", subject="fast", status="pass",
                     commit="23cfa12f", evidence=f"gate ({console})")

    fast = next(criterion for criterion in rung(project(empty_gate), "RB0")["criteria"] if criterion["id"].endswith("#fast-gate"))
    assert not (fast["verdict"] == "met" and fast["strength"] == "record"), fast


# ---------------------------------------------------------------- F08
@needs_kinsim
def test_f08_a_change_to_code_the_acceptance_runs_makes_it_stale(document):
    """Codex F08: VZ2 stayed green on teardown evidence at ddfb6e97 after 6f7f37cc changed visualize_collision_scenarios.py."""

    vz2 = rung(document, "VZ2")
    teardown = next(item for criterion in criteria_of(vz2, "test") for item in criterion["targets"]
                    if item["path"].endswith("test_viewer_teardown_acceptance.py"))
    assert teardown["verdict"] == "stale", teardown
    assert vz2["status"] != "green"


@needs_kinsim
def test_f08_a_ruler_change_makes_old_proof_stale_not_discarded():
    """Codex F08: a new ruler digest left EV1 green, and RB0 lost its readings instead of keeping them as stale."""

    def new_ruler(inputs):
        inputs.ruler_sha256 = "f" * 64

    document = project(new_ruler)
    assert rung(document, "EV1")["status"] != "green"
    gate = next(criterion for criterion in rung(document, "RB0")["criteria"] if criterion["id"].endswith("#gate"))
    assert gate["verdict"] == "stale", gate
    assert all(target["evidence"] for target in gate["targets"]), gate
    assert all(any(change.startswith("ruler ") for change in target["changed_since"]) for target in gate["targets"]), gate


# ---------------------------------------------------------------- F09
@needs_kinsim
def test_f09_a_fast_gate_without_a_commit_is_not_proof(tmp_path):
    """Codex F09: the latest fast gate event's commit set to None left RB0 green (met/log, at=[]).

    Restated after Codex G04, which binds a gate run to its commit through its own HEAD line or git's reflog for the
    checkout its report names: here the latest fast gate is a passing run that records neither, so no commit is known.
    """

    report = tmp_path / "gate_report.json"
    report.write_text(json.dumps({"schema": "bam-gate-report/1", "passed": True, "unexpected_red": [], "unexpected_green": [],
                                  "tier": "fast", "root": str(tmp_path / "gone"), "suites": [
                                      {"suite": "collision", "cwd": str(tmp_path / "gone"), "junit": True, "exit_code": 0,
                                       "argv": ["pytest"], "then": [], "unexpected_red": [], "unexpected_green": [], "expected_red": []}]}))
    console = tmp_path / "gate_fast.txt"
    console.write_text(f"collision  ok   exit=0\nGATE PASS tier=fast report={report}\nexit 0\n")

    def no_commit(inputs):
        append_event(inputs, ts="2026-10-03T20:58:00+00:00", kind="gate_run", subject="fast", status="pass", commit=None,
                     evidence=f"python -m bam_curriculum gate --tier fast ({console})")

    rb0 = rung(project(no_commit), "RB0")
    fast = next(criterion for criterion in rb0["criteria"] if criterion["id"].endswith("#fast-gate"))
    assert not (fast["verdict"] == "met" and fast["strength"] in ("record", "log")), fast
    assert rb0["status"] != "green"


# ---------------------------------------------------------------- F10
@pytest.mark.parametrize("text", [
    "https://example.test/?next=/a/secret.json", "/a/../b.txt", "/a/./c.txt", "/a/x.py:L12", "/a/y.log:1:2:3",
])
def test_f10_only_whole_tokens_are_cited(text):
    assert links.cited_paths(text) == []


@pytest.mark.skipif(not CORPUS.is_file(), reason="the dashboard's citation corpus is not in this checkout")
def test_f10_the_shared_citation_corpus():
    """The one rule bam_roadmap, the dashboard API and the page all run (bam-citation-corpus/1)."""

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert corpus["schema"] == "bam-citation-corpus/1" and corpus["cases"]
    for case in corpus["cases"]:
        found = links.cited_paths(case["text"])
        cited = [citation.raw for citation in found if getattr(citation, "kind", "text") == "text"]
        images = [citation.raw for citation in found if getattr(citation, "kind", "text") == "image"]
        lines = {citation.raw: citation.line for citation in found if citation.line is not None}
        assert (cited, images, lines) == (case["cited"], case["images"], {key: int(value) for key, value in case["lines"].items()}), case


def test_f10_the_parser_agrees_with_the_dashboards_reference_on_random_text():
    """A differential check beside the corpus: 20,000 random texts, our parser vs the dashboard's cited_tokens().

    The runtime never imports the dashboard (stdlib-only); this test imports its rule as ported into vibetracks.
    """

    import importlib
    import random

    # WHY vibetracks.roadmap.citations and not the loop checkout's dashboard: moved into vibetracks, the dashboard's rule
    # is ported here (the API and the page share it), and the kinsim loop's own checkout carries an older dashboard
    # without cited_tokens. The two stay independent implementations: links.py imports nothing from citations.py.
    reference = importlib.import_module("vibetracks.roadmap.citations")
    cores = ["/a/x.txt", "/b/y.log:3", "/c/z.json", "/h.py:2:9", "/f/../g.txt", "/i.png", "word", "copy.log", "", "-"]
    marks = ["", "", "", '"', "'", "`", "(", ")", "<", ">", "[", "]", ".", ",", ";", ":"]
    gaps = [" ", " ", " ", "\n", "\t", "  "]
    generator = random.Random(20261003)
    for _ in range(20000):
        tokens = ["".join(generator.choice(marks) for _ in range(generator.randint(0, 2))) + generator.choice(cores)
                  + "".join(generator.choice(marks) for _ in range(generator.randint(0, 2))) for _ in range(generator.randint(1, 8))]
        text = "".join(token + generator.choice(gaps) for token in tokens)
        ours = [(citation.raw, citation.line) for citation in links.cited_paths(text) if getattr(citation, "kind", "text") == "text"]
        seen: set[str] = set()
        theirs = []
        for path, line in reference.cited_tokens(text):  # a path cited twice keeps its first spelling
            if path not in seen:
                seen.add(path)
                theirs.append((path, line))
        assert ours == theirs, text


def test_f10_a_quoted_span_is_parsed_whole_before_clauses():
    """Codex C02 (dashboard, Oct 3): a quoted span that crosses a "; " cites nothing inside it, in any clause."""

    text = '"see /a/x.txt; then /b/y.log" /c/z.log; ran /d/w.log -> 3 passed'
    assert [citation.raw for citation in links.cited_paths(text)] == ["/c/z.log", "/d/w.log"]
    assert [[citation.raw for citation in citations] for _clause, citations in links.clauses_with_citations(text)] == [
        [], ["/c/z.log"], ["/d/w.log"]]


# ---------------------------------------------------------------- F11
@needs_kinsim
def test_f11_a_stated_condition_with_no_data_stays_unknown(document):
    """Codex F11: EV1's done_when requires a Codex verdict that no criterion checked, yet EV1 read green.

    Restated after Codex G09: the condition must never be dropped (EV1 carries an audit criterion, judged from the
    audit report its event cites), and a condition with no data behind it (RG1's sentence) stays unknown.
    """

    ev1 = rung(document, "EV1")
    assert criteria_of(ev1, "audit"), ev1["criteria"]
    rg1 = rung(document, "RG1")
    stated = criteria_of(rg1, "stated")
    assert stated and stated[0]["verdict"] == "unknown", rg1["criteria"]
    assert ev1["status"] != "green" and rg1["status"] != "green"


# ---------------------------------------------------------------- F12
@needs_kinsim
@pytest.mark.parametrize(("name", "change"), [
    ("feasible 0 of 1000 under a 1.0 rate", {"totals.feasible": 0}),
    ("a NaN rate", {"metrics.feasible_rate": math.nan}),
    ("an infinite rate", {"metrics.feasible_rate": math.inf}),
])
def test_f12_a_ledger_row_that_contradicts_itself_cannot_certify(name, change):
    """Codex F12: RB0's latest promotion row edited in memory (0/1000 at rate 1.0; NaN; inf) stayed green."""

    # WHY the row RB0's gate cites, not the last rb0-promotion corpus row: SN1's promotion reuses that corpus (loop row
    # sn1-promotion-20261005T003425Z), so "the last such row" contradicted SN1's evidence and left RB0's untouched.
    base = rung(project(), "RB0")
    base_gate = next(criterion for criterion in base["criteria"] if criterion["id"].endswith("#gate"))
    cited = {item["id"]: item.get("run_id") for item in base["evidence"]}
    promotion = [cited[eid] for eid in base_gate["evidence"] if str(cited.get(eid) or "").startswith("rb0-promotion")]
    if not promotion:
        pytest.skip("RB0's gate cites no promotion row today")

    def contradict(inputs):
        row = next(row for row in inputs.ledger if row.get("run_id") == promotion[0])
        for dotted, value in change.items():
            section, key = dotted.split(".")
            row[section][key] = value

    gate = next(criterion for criterion in rung(project(contradict), "RB0")["criteria"] if criterion["id"].endswith("#gate"))
    # WHY != "met" and not == "unmet": this runs on the live loop, so it pins the invariant (a row that contradicts itself
    # never certifies), not today's verdict. The loop moved (21407ef6 changed RB0's producer), and RB0's gate now reads
    # stale before any row is touched; "unmet" was only what the contradiction gave on a fresh gate at 553a66f0.
    assert gate["verdict"] != "met", (name, gate)
