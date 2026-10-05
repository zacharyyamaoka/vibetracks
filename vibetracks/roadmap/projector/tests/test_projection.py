"""Projection rules on throwaway loops: green needs proof, proof goes stale, a loop cannot assert green.

Every document projected here must also pass the full validator (schema, consistency, disk).
"""

from __future__ import annotations

import json

import pytest

from vibetracks.roadmap.projector import gitinfo, project_kinsim, project_rig
from vibetracks.roadmap.projector.validate import validate_document

from .conftest import ACCEPTANCE, RIG_ACCEPTANCE, append_jsonl, commit_all, ladder, ledger_row, write, write_json

NOW = "2026-10-03T19:00:00+00:00"


def kinsim(loop) -> dict:
    gitinfo.clear_cache()
    document = project_kinsim(loop.curriculum_dir, loop.data_home, now=NOW)
    assert validate_document(document) == []
    return document


def rig(loop) -> dict:
    gitinfo.clear_cache()
    document = project_rig(loop.rig_dir, now=NOW)
    assert validate_document(document) == []
    return document


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


def evidence(rung_entry: dict, evidence_id: str) -> dict:
    return next(item for item in rung_entry["evidence"] if item["id"] == evidence_id)


# ---------------------------------------------------------------- kinsim: the happy path
def test_every_rung_is_proven_on_the_fixture(kinsim_loop):
    document = kinsim(kinsim_loop)
    statuses = {item["id"]: item["status"] for item in document["rungs"]}
    assert statuses == {"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"}
    ev9 = rung(document, "EV9")
    target = ev9["criteria"][0]["targets"][0]
    assert (target["verdict"], target["strength"]) == ("met", "record")
    test_item = evidence(ev9, target["evidence"][0])
    assert test_item["kind"] == "test" and test_item["path"] == ACCEPTANCE and test_item["line"] == 4
    assert [(case["node_id"], case["line"], case["outcome"]) for case in test_item["cases"]] == [
        (f"{ACCEPTANCE}::TestWidget::test_widget_spins", 9, "passed"), (f"{ACCEPTANCE}::test_widget_builds", 4, "passed")]
    assert test_item["commit_source"] == "artifact"  # the fixture's gate log starts with its own HEAD line
    assert test_item["event"]["kind"] == "gate_run" and isinstance(test_item["event"]["line"], int)


def test_support_names_exact_runs_and_events(kinsim_loop):
    rb9 = rung(kinsim(kinsim_loop), "RB9")
    assert set(rb9["support"]["runs"]) == {"rb9-reg-r1", "rb9-reg-r2", "rb9-promo"}
    assert rb9["support"]["rungs"] == ["EV9"]
    assert [reference["kind"] for reference in rb9["support"]["events"]] == ["gate_run"]
    roles = {item["id"]: item["role"] for item in rb9["evidence"]}
    assert all(roles[evidence_id] == "supports" for evidence_id in rb9["support"]["evidence"])
    assert rb9["claimed_by"]["source"]["pointer"] == "/rungs/1" and rb9["claimed_by"]["event"] is None


def test_the_baseline_is_an_inspection_of_code_that_exists(kinsim_loop):
    mr9 = rung(kinsim(kinsim_loop), "MR9")
    target = mr9["criteria"][0]["targets"][0]
    assert (mr9["status"], target["path"], target["line"], target["end_line"]) == ("done", "src/pkg/widget.py", 1, 2)


# ---------------------------------------------------------------- kinsim: proof goes stale
def test_changing_the_test_after_its_proof_makes_the_rung_stale(kinsim_loop):
    write(kinsim_loop.repo / ACCEPTANCE, (kinsim_loop.repo / ACCEPTANCE).read_text() + "\n\ndef test_widget_new():\n    assert True\n")
    commit_all(kinsim_loop.repo, "a new acceptance test after the proof")
    document = kinsim(kinsim_loop)
    ev9 = rung(document, "EV9")
    assert ev9["status"] == "stale"
    assert "a new acceptance test after the proof" in ev9["criteria"][0]["targets"][0]["changed_since"][0]
    # the cascade: RB9 needs EV9; OB9 is RB9's alias
    assert rung(document, "RB9")["status"] == "stale" and rung(document, "OB9")["status"] == "stale"
    assert document["where"][0]["here"] is None and document["where"][0]["here_claimed"] == "EV9"


# ---------------------------------------------------------------- kinsim: a loop cannot assert green
def test_a_fold_that_says_green_over_a_failing_promotion_is_downgraded(kinsim_loop):
    """The mutant: status.json claims RB9 green, but the newest promotion reading fails the bar."""

    kinsim_loop.add_reading({
        **ledger_row("rb9-promo-2", "promotion", "rb9-promotion", 8, 7, kinsim_loop.first_commit, kinsim_loop.ruler_sha, "promo-2"),
        "ts": "2026-10-03T05:00:00+00:00"})
    kinsim_loop.fold({"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"})
    document = kinsim(kinsim_loop)
    rb9 = rung(document, "RB9")
    assert (rb9["claimed_status"], rb9["status"]) == ("green", "partial")
    assert "feasible 7/8" in rb9["criteria"][0]["reason"]
    assert "RB9" in document["counts"]["claimed_green_not_proven"]
    assert set(rb9["support"]["runs"]) == {"rb9-promo-2", "rb9-reg-r1", "rb9-reg-r2"}
    promo_2 = next(item for item in rb9["evidence"] if item.get("run_id") == "rb9-promo-2")
    # its batch.json was never written, so the link opens the exact ledger row instead
    assert (promo_2["path"], promo_2["line"], promo_2["exists"]) == ("runs.jsonl", promo_2["facts"]["ledger_line"], True)


def test_a_fold_that_says_green_with_no_runs_is_only_claimed(kinsim_loop):
    (kinsim_loop.data_home / "runs.jsonl").write_text("")
    kinsim_loop.fold({"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"})
    rb9 = rung(kinsim(kinsim_loop), "RB9")
    assert (rb9["status"], rb9["criteria"][0]["verdict"]) == ("claimed", "unknown")
    assert rb9["support"]["runs"] == []


def test_a_newer_red_junit_overrides_an_older_green_log(kinsim_loop):
    kinsim_loop.gate_run("gate_fast_2", kinsim_loop.first_commit, {
        "tests.test_widget_acceptance::test_widget_builds": "failed",
        "tests.test_widget_acceptance.TestWidget::test_widget_spins": "passed"}, ts="2026-10-03T06:00:00+00:00")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    assert (ev9["claimed_status"], ev9["status"]) == ("green", "partial")
    chosen = evidence(ev9, ev9["criteria"][0]["targets"][0]["evidence"][0])
    assert chosen["result"] == "failed" and chosen["facts"]["red"] == 1


def test_a_revoked_green_is_superseded_by_the_event_that_revoked_it(kinsim_loop):
    """Codex A06: a newer partial event must never read as "green at <its commit>"."""

    revoke_log = kinsim_loop.log("ev9_revoke.txt", "1 failed, 1 passed in 0.2s\nEXIT 1\n")
    kinsim_loop.event(ts="2026-10-03T07:00:00+00:00", kind="rung_status_changed", subject="EV9", status="partial",
                      commit=kinsim_loop.first_commit[:8], evidence=f"re-run red ({revoke_log})")
    kinsim_loop.fold({"EV9": "partial", "RB9": "partial", "OB9": "partial", "MR9": "done"})
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    assert (ev9["claimed_status"], ev9["status"]) == ("partial", "partial")
    green_row, partial_row = ev9["history"]
    assert (green_row["status"], partial_row["status"]) == ("green", "partial")
    assert green_row["superseded_by"] == partial_row["event"]["line"] and partial_row["superseded_by"] is None
    assert ev9["claimed_by"]["event"]["line"] == partial_row["event"]["line"]
    assert ev9["claimed_by"]["event"]["status"] == "partial"
    green_log = [evidence(ev9, evidence_id) for evidence_id in green_row["evidence"]]
    assert green_log and all(item["role"] == "superseded" for item in green_log)


def test_run_1_is_superseded_by_run_10_by_id_not_by_text(kinsim_loop):
    """Codex A07: run-1 must not look cited because a reason names run-10."""

    rows = [ledger_row("rb9-run-1", "promotion", "rb9-promotion", 8, 7, kinsim_loop.first_commit, kinsim_loop.ruler_sha, "h1"),
            {**ledger_row("rb9-run-10", "promotion", "rb9-promotion", 8, 8, kinsim_loop.first_commit, kinsim_loop.ruler_sha, "h10"),
             "ts": "2026-10-03T08:00:00+00:00"}]
    for row in rows:
        kinsim_loop.add_reading(row)
    kinsim_loop.fold({"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"},
                     {"RB9": "gate met by rb9-run-10, rb9-reg-r1, rb9-reg-r2"})
    rb9 = rung(kinsim(kinsim_loop), "RB9")
    assert rb9["status"] == "green"
    assert "rb9-run-10" in rb9["support"]["runs"] and "rb9-run-1" not in rb9["support"]["runs"]
    by_run = {item["run_id"]: item for item in rb9["evidence"] if item.get("run_id")}
    assert by_run["rb9-run-1"]["role"] == "superseded"
    assert by_run["rb9-run-1"]["superseded_by"] == by_run["rb9-run-10"]["id"]
    assert by_run["rb9-promo"]["role"] == "superseded"


def test_a_partial_junit_record_falls_back_to_the_log_that_covers_the_whole_file(kinsim_loop):
    kinsim_loop.gate_run("gate_fast_3", kinsim_loop.first_commit, {"tests.test_widget_acceptance::test_widget_builds": "passed"},
                         ts="2026-10-03T09:00:00+00:00")
    target = rung(kinsim(kinsim_loop), "EV9")["criteria"][0]["targets"][0]
    assert (target["verdict"], target["strength"]) == ("met", "record")  # the older complete record still stands
    (kinsim_loop.data_home / "loop_events.jsonl").write_text("")
    kinsim_loop.gate_run("gate_fast_4", kinsim_loop.first_commit, {"tests.test_widget_acceptance::test_widget_builds": "passed"},
                         ts="2026-10-03T09:00:00+00:00")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    assert ev9["criteria"][0]["targets"][0]["verdict"] == "unknown"
    assert ev9["status"] == "claimed"


def test_a_baseline_citing_code_that_does_not_exist_is_only_claimed(kinsim_loop):
    curriculum_path = kinsim_loop.curriculum_dir / "curriculum.json"
    curriculum = json.loads(curriculum_path.read_text())
    curriculum["rungs"][3]["baseline"]["evidence"] = "The only mode (nowhere.py:3)."
    write_json(curriculum_path, curriculum)
    mr9 = rung(kinsim(kinsim_loop), "MR9")
    assert (mr9["claimed_status"], mr9["status"]) == ("done", "claimed")


def test_a_cited_file_that_vanished_is_flagged_not_dropped(kinsim_loop):
    log = kinsim_loop.evidence_dir / "ev9_acceptance.txt"
    log.unlink()
    document = kinsim(kinsim_loop)
    flagged = [row for row in document["unresolved"] if row["path"].endswith("ev9_acceptance.txt")]
    assert flagged and flagged[0]["why"].startswith("file not found")
    assert rung(document, "EV9")["status"] == "green"  # the JUnit record still proves it


# ---------------------------------------------------------------- rig
def test_a_rig_rung_whose_proof_is_a_sentence_is_claimed(rig_loop):
    document = rig(rig_loop)
    tw0, tw1 = rung(document, "TW0"), rung(document, "TW1")
    assert (tw0["claimed_status"], tw0["status"]) == ("green", "claimed")
    landed, acceptance = tw0["criteria"]
    assert (landed["kind"], landed["verdict"], landed["strength"]) == ("package", "met", "record")
    assert (acceptance["verdict"], acceptance["strength"]) == ("met", "claim")
    statement = evidence(tw0, acceptance["targets"][0]["evidence"][0])
    assert statement["kind"] == "statement" and statement["role"] == "supports" and statement["event"]["subject"] == "TW0"
    assert (tw1["status"], tw1["done_when"]["rule"]) == ("claimed", "none")
    assert [blocker["id"] for blocker in tw1["blockers"]] == ["T4"]


def test_a_rig_rung_with_a_cited_log_is_green_until_its_write_set_changes(rig_loop):
    # WHY the log shows the file run (Codex F04, G05), selected whole by its own recorded command (H01), and records its
    # own commit (G04, H02): a log the loop only cites beside a file's name, or only dates by its event, proves nothing
    # about the file at a commit.
    log = write(rig_loop.evidence_dir / "tw0.txt",
                f"HEAD {rig_loop.first_commit};\n$ (cd {rig_loop.repo}/src/rig && pytest tests/test_twin.py)\n"
                "tests/test_twin.py .                [100%]\n1 passed in 0.4s\nEXIT 0\n")
    rig_loop.event(ts="2026-10-02T23:00:00-07:00", kind="rung_status_changed", subject="TW0", status="green",
                   commit=rig_loop.first_commit[:8], evidence=f"src/rig: pytest tests/test_twin.py -> 3 passed ({log})")
    tw0 = rung(rig(rig_loop), "TW0")
    assert tw0["status"] == "green"
    assert tw0["support"]["events"][-1]["line"] == tw0["history"][-1]["event"]["line"]
    write(rig_loop.repo / "src/rig/twin.py", "GAP = 0.7\n")
    commit_all(rig_loop.repo, "the twin changed after its proof")
    tw0 = rung(rig(rig_loop), "TW0")
    assert tw0["status"] == "stale"
    assert "the twin changed after its proof" in tw0["criteria"][1]["targets"][0]["changed_since"][0]


@pytest.mark.parametrize(("status", "commit", "expected"), [("building", None, "partial"), ("landed", "deadbeef", "claimed")])
def test_a_rig_package_that_has_not_landed_here_holds_the_rung(rig_loop, status, commit, expected):
    write_json(rig_loop.rig_dir / "ladder.json", ladder(r1_status=status, r1_commit=commit))
    tw0 = rung(rig(rig_loop), "TW0")
    assert tw0["status"] == expected
    if commit:
        assert tw0["criteria"][0]["verdict"] == "stale" and "not in this repository" in tw0["criteria"][0]["reason"]


def test_the_rig_acceptance_file_resolves_to_the_repo(rig_loop):
    target = rung(rig(rig_loop), "TW0")["criteria"][1]["targets"][0]
    assert (target["path"], target["base"], target["exists"]) == (RIG_ACCEPTANCE, "repo", True)


# ---------------------------------------------------------------- round 2 (Codex r1) on the fixtures
def test_a_log_that_never_names_the_file_is_only_a_claim(rig_loop):
    """Codex F04: the log is real and green, but nothing in it says it ran test_twin.py."""

    log = write(rig_loop.evidence_dir / "tw0_quiet.txt", "...\n3 passed in 0.4s\nEXIT 0\n")
    rig_loop.event(ts="2026-10-02T23:00:00-07:00", kind="rung_status_changed", subject="TW0", status="green",
                   commit=rig_loop.first_commit[:8], evidence=f"src/rig: pytest tests/test_twin.py -> 3 passed ({log})")
    tw0 = rung(rig(rig_loop), "TW0")
    target = tw0["criteria"][1]["targets"][0]
    assert (tw0["status"], target["verdict"], target["strength"]) == ("claimed", "met", "claim")
    assert "never shows this file run" in target["note"]


def test_acceptance_prose_is_a_stated_criterion_until_the_ladder_declares_it(rig_loop):
    """Codex F11: without acceptance_is_tests the package's sentence is a condition nothing typed checks."""

    plan = ladder(r1_commit=rig_loop.first_commit[:8])
    plan["packages"][0].pop("acceptance_is_tests")
    write_json(rig_loop.rig_dir / "ladder.json", plan)
    tw0 = rung(rig(rig_loop), "TW0")
    stated = [criterion for criterion in tw0["criteria"] if criterion["kind"] == "stated"]
    assert stated and stated[0]["verdict"] == "unknown" and stated[0]["text"] == "replays within 1e-6 rad"


def test_a_gate_text_that_says_more_than_its_fields_stays_unknown(kinsim_loop):
    """Codex F11: EV9's gate now also asks for a Codex verdict that no field declares."""

    curriculum_path = kinsim_loop.curriculum_dir / "curriculum.json"
    curriculum = json.loads(curriculum_path.read_text())
    curriculum["rungs"][0]["gate_text"] = "infra: widget acceptance, with no Codex blocker left"
    write_json(curriculum_path, curriculum)
    commit_all(kinsim_loop.repo, "EV9 asks for a review")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    audit = [criterion for criterion in ev9["criteria"] if criterion["kind"] == "audit"]
    assert audit and audit[0]["verdict"] == "unknown" and ev9["status"] == "claimed"
    curriculum["rungs"][0]["gate"]["text_is_covered"] = True
    write_json(curriculum_path, curriculum)
    commit_all(kinsim_loop.repo, "the loop declares the acceptance covers its text")
    assert rung(kinsim(kinsim_loop), "EV9")["status"] == "green"


def test_a_dirty_gate_run_is_only_a_claim(kinsim_loop):
    """Codex F04/F09: a gate log whose HEAD line says the tree was dirty proves nothing about a commit."""

    kinsim_loop.gate_run("gate_dirty", kinsim_loop.first_commit, {
        "tests.test_widget_acceptance::test_widget_builds": "passed",
        "tests.test_widget_acceptance.TestWidget::test_widget_spins": "passed"}, ts="2026-10-03T12:00:00+00:00")
    console = kinsim_loop.evidence_dir / "gate_dirty.txt"
    console.write_text(f"HEAD {kinsim_loop.first_commit} + dirty;\n" + console.read_text())
    (kinsim_loop.data_home / "loop_events.jsonl").write_text(
        "\n".join(line for line in (kinsim_loop.data_home / "loop_events.jsonl").read_text().splitlines()
                  if "gate_fast_1" not in line) + "\n")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    target = ev9["criteria"][0]["targets"][0]
    chosen = evidence(ev9, target["evidence"][0])
    assert (target["verdict"], target["strength"]) == ("met", "claim"), target
    assert (chosen["kind"], chosen["commit_source"], chosen["strength"]) == ("test", "artifact-dirty", "claim"), chosen
    assert ev9["status"] == "claimed"


def test_a_code_change_the_acceptance_imports_makes_it_stale(kinsim_loop):
    """Codex F08: the scope is the test's package and what it imports, not just the test file."""

    write(kinsim_loop.repo / "src/pkg/widget.py", "WIDGET = 1\nSPIN = 3\n")
    commit_all(kinsim_loop.repo, "the widget changed after its proof")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    target = ev9["criteria"][0]["targets"][0]
    assert target["verdict"] == "stale" and "the widget changed after its proof" in target["changed_since"][0]
    assert "src/pkg/tests/" in target["scope"] or "src/pkg/" in target["scope"] or "src/pkg/widget.py" in target["scope"]


def test_a_log_with_no_commit_of_its_own_is_only_a_claim(rig_loop):
    """Codex G04: the log shows the file run, but only the loop's event says at which commit."""

    log = write(rig_loop.evidence_dir / "tw0_undated.txt", "tests/test_twin.py ...                [100%]\n3 passed in 0.4s\nEXIT 0\n")
    rig_loop.event(ts="2026-10-02T23:00:00-07:00", kind="rung_status_changed", subject="TW0", status="green",
                   commit=rig_loop.first_commit[:8], evidence=f"src/rig: pytest tests/test_twin.py -> 3 passed ({log})")
    target = rung(rig(rig_loop), "TW0")["criteria"][1]["targets"][0]
    assert (target["verdict"], target["strength"]) == ("met", "claim")
    assert "only the loop's event names one" in target["note"]


def test_a_gate_run_with_no_record_of_its_commit_is_only_a_claim(kinsim_loop):
    """Codex H02 (restating G04's reflog test): a gate run whose console has no HEAD line and whose report has no git
    record is placed only by the loop's event; neither the report's file time nor git's reflog binds it."""

    for path in kinsim_loop.evidence_dir.glob("gate_fast_1.txt"):
        path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("HEAD ")) + "\n")
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    target = ev9["criteria"][0]["targets"][0]
    chosen = evidence(ev9, target["evidence"][0])
    assert chosen["commit_source"] == "citation" and (target["verdict"], target["strength"]) == ("met", "claim"), (chosen, target)
    assert ev9["status"] == "claimed"


def test_a_gate_report_that_records_its_commit_and_clean_tree_binds_it(kinsim_loop):
    """Codex H02: the record a run writes is what binds it: a gate report's own git {sha, dirty: false} does."""

    for path in kinsim_loop.evidence_dir.glob("gate_fast_1.txt"):
        path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("HEAD ")) + "\n")
    report_path = kinsim_loop.evidence_dir / "gate_fast_1" / "gate_report.json"
    report = json.loads(report_path.read_text())
    write_json(report_path, {**report, "git": {"sha": kinsim_loop.first_commit, "dirty": False}})
    ev9 = rung(kinsim(kinsim_loop), "EV9")
    target = ev9["criteria"][0]["targets"][0]
    chosen = evidence(ev9, target["evidence"][0])
    assert chosen["commit_source"] == "artifact" and (target["verdict"], target["strength"]) == ("met", "record"), (chosen, target)
    write_json(report_path, {**report, "git": {"sha": kinsim_loop.first_commit}})  # commit, but no word on the tree
    target = rung(kinsim(kinsim_loop), "EV9")["criteria"][0]["targets"][0]
    assert target["strength"] == "claim", target


def test_a_review_condition_rests_on_the_audit_the_event_cites(kinsim_loop):
    """Codex G09: "no in_domain Codex blocker or major left on X" is checked against the audit report the rung's event
    cites, at the commit the report says it reviewed, and goes stale only when what the review read changes."""

    curriculum_path = kinsim_loop.curriculum_dir / "curriculum.json"
    curriculum = json.loads(curriculum_path.read_text())
    curriculum["rungs"][0]["gate_text"] = "infra: widget acceptance, with no in_domain Codex blocker or major left on widget-v1"
    write_json(curriculum_path, curriculum)
    reviewed = commit_all(kinsim_loop.repo, "EV9 asks for a review of widget-v1")
    audit = kinsim_loop.log("audits/2026-10-03-widget-v1-r1.md",
                            f"No in_domain blocker or major found at `{reviewed[:8]}`.\n\nAt [widget.py:1]({kinsim_loop.repo}/src/pkg/widget.py:1) "
                            f"the spin is fine.\n\nReviewed candidate `{reviewed}`.\n\nVERDICT: SHIP\n")
    kinsim_loop.event(ts="2026-10-03T13:00:00+00:00", kind="rung_status_changed", subject="EV9", status="green", commit=reviewed[:8],
                      evidence=f"widget acceptance green; Codex {audit}:6 VERDICT: SHIP")

    def review() -> dict:
        ev9 = rung(kinsim(kinsim_loop), "EV9")
        return next(criterion for criterion in ev9["criteria"] if criterion["kind"] == "audit")

    criterion = review()
    assert (criterion["verdict"], criterion["strength"], criterion["at"]) == ("met", "record", [reviewed]), criterion
    assert "src/pkg/widget.py" in criterion["targets"][0]["scope"]
    write(kinsim_loop.repo / "src/pkg/tests/test_other_acceptance.py", "def test_other():\n    assert True\n")
    commit_all(kinsim_loop.repo, "an unrelated acceptance test")
    assert review()["verdict"] == "met"  # the review never read it
    write(kinsim_loop.repo / "src/pkg/widget.py", "WIDGET = 2\nSPIN = 2\n")
    commit_all(kinsim_loop.repo, "the reviewed code changed")
    assert review()["verdict"] == "stale"
