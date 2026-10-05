"""How one target picks the evidence it rests on, and what the shared evaluator grants it, without git."""

from __future__ import annotations

from pathlib import Path

from vibetracks.roadmap.projector import artifacts, proof
from vibetracks.roadmap.projector.evaluate import Evaluator, Judgement
from vibetracks.roadmap.projector.links import Roots


class Repo:
    """Every commit is known and in history, nothing changed since, unless told otherwise."""

    def __init__(self, changed: dict[str, list[str]] | None = None, outside: set[str] | None = None,
                 unknown: set[str] | None = None) -> None:
        self.changed, self.outside, self.unknown = changed or {}, outside or set(), unknown or set()
        self.head = "f" * 40

    def full_sha(self, commit):
        return None if commit in self.unknown else commit

    def in_history(self, commit):
        return commit not in self.outside

    def changed_since(self, commit, paths):
        return self.changed.get(commit, [])


def evaluator(repo: Repo | None = None) -> Evaluator:
    return Evaluator(repo or Repo(), Roots(repo=Path("/nonexistent")))


def judged(evidence_id: str, verdict: str, strength: str | None, ts: str, *, result: str = "passed", line: int | None = None):
    item = {"id": evidence_id, "ts": ts, "event": {"line": line} if line else None}
    return proof.Proof("t.py", item, (evidence_id,), f"from {evidence_id}"), Judgement(verdict, strength, [], "", result, "abc1234")


def chosen(pairs) -> str:
    return proof.choose(pairs)[0].item["id"]


def test_a_newer_failure_beats_an_older_pass():
    assert chosen([judged("e1", "met", "record", "2026-10-03T01:00:00+00:00"),
                   judged("e2", "unmet", None, "2026-10-03T02:00:00+00:00", result="failed")]) == "e2"


def test_the_strongest_fresh_proof_wins_over_a_newer_claim():
    assert chosen([judged("e1", "met", "record", "2026-10-03T01:00:00+00:00"),
                   judged("e2", "met", "claim", "2026-10-03T02:00:00+00:00")]) == "e1"


def test_a_stale_record_outranks_a_fresh_claim():
    """derive_status reads a claim as no proof at all, so the real (if old) record is what the target shows."""

    assert chosen([judged("e1", "stale", "record", "2026-10-03T01:00:00+00:00"),
                   judged("e2", "met", "claim", "2026-10-03T02:00:00+00:00")]) == "e1"


def test_same_second_evidence_is_ordered_by_the_event_line():
    """Two gate runs logged in one second: the later line is the newer evidence (it named the FAIL run otherwise)."""

    same = "2026-10-03T04:25:43+00:00"
    assert chosen([judged("e76", "met", "record", same, line=76), judged("e77", "met", "record", same, line=77)]) == "e77"
    assert chosen([judged("e77", "met", "record", same, line=77), judged("e76", "met", "record", same, line=76)]) == "e77"


def test_evidence_from_another_branch_is_stale():
    judgement = evaluator(Repo(outside={"lane999"})).finish("passed", "record", "lane999", ["t.py"], {})
    assert (judgement.verdict, judgement.strength) == ("stale", "record") and "not in this history" in judgement.note


def test_evidence_with_no_commit_or_an_unknown_one_is_only_a_claim():
    """Codex F09: a result nobody can place in git is the loop's word, whatever the artifact."""

    assert (evaluator().finish("passed", "record", None, ["t.py"], {}).strength) == "claim"
    unknown = evaluator(Repo(unknown={"0" * 40})).finish("passed", "record", "0" * 40, ["t.py"], {})
    assert (unknown.verdict, unknown.strength) == ("stale", "claim") and "not in this repository" in unknown.note


def test_ancestry_that_cannot_be_established_is_only_a_claim():
    """Codex F09: proof needs a yes from git; an unanswered ancestry question is not one."""

    class Unanswered(Repo):
        def in_history(self, commit):
            return None

    judgement = evaluator(Unanswered()).finish("passed", "record", "abc1234", ["t.py"], {})
    assert judgement.strength == "claim" and "could not be placed" in judgement.note


def test_a_change_in_scope_or_ruler_makes_proof_stale():
    """Codex F08: freshness is the scope's history plus the context the evidence was made under."""

    changed = evaluator(Repo(changed={"abc1234": ["fff0001 the code changed"]})).finish("passed", "record", "abc1234", ["pkg/"], {})
    assert changed.verdict == "stale" and changed.changed_since == ["fff0001 the code changed"]
    ruler = evaluator().finish("passed", "record", "abc1234", ["pkg/"], {"ruler_sha256": "b" * 64}, context_value="a" * 64)
    assert ruler.verdict == "stale" and ruler.changed_since[0].startswith("ruler aaaaaaaaaaaa")


def test_a_record_that_skipped_or_missed_a_test_does_not_prove_the_file(tmp_path):
    """Codex F06: skipped is not coverage, and a missing case is unproven even at its own commit."""

    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuites><testsuite><testcase classname="tests.test_a" name="test_x"/>'
                     '<testcase classname="tests.test_a" name="test_y"><skipped/></testcase></testsuite></testsuites>')
    assert artifacts.junit_result(artifacts.junit_cases(junit)) is None
    assert evaluator().finish("passed", "record", "abc1234", ["t.py"], {}, unproven=True).verdict == "unknown"
    assert evaluator(Repo(outside={"abc1234"})).finish("passed", "record", "abc1234", ["t.py"], {}, unproven=True).verdict == "unknown"


def test_commits_are_listed_once_however_abbreviated():
    assert proof._unique_commits(["42f81d93", "42f81d93aa11bb22cc33dd44ee55ff6677889900", "741460aa"]) == [
        "42f81d93aa11bb22cc33dd44ee55ff6677889900", "741460aa"]
