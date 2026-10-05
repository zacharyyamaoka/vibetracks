"""The pure status rule: a loop can hold a rung below green, never lift one to green by saying so."""

from __future__ import annotations

import pytest

from vibetracks.roadmap.projector import model


def criterion(verdict: str, strength: str | None, title: str = "c") -> dict:
    return {"id": f"X#{title}", "title": title, "verdict": verdict, "strength": strength}


@pytest.mark.parametrize(("claimed", "criteria", "expected"), [
    ("green", [criterion("met", "record")], "green"),
    ("green", [criterion("met", "log")], "green"),
    ("done", [criterion("met", "record")], "done"),
    # the mutants: a claimed green that its own done_when does not support
    ("green", [criterion("met", "record"), criterion("unmet", None)], "partial"),
    ("green", [criterion("met", "claim")], "claimed"),
    ("green", [criterion("unknown", None)], "claimed"),
    ("green", [], "claimed"),
    ("green", [criterion("stale", "record")], "stale"),
    ("green", [criterion("stale", "record"), criterion("met", "claim")], "claimed"),
    ("green", [criterion("stale", "record"), criterion("unmet", None)], "partial"),
    # a loop may hold a rung below what the evidence allows
    ("partial", [criterion("met", "record")], "partial"),
    ("missing", [criterion("met", "record")], "missing"),
    ("missing", [], "missing"),
])
def test_derive_status(claimed, criteria, expected):
    status, reason = model.derive_status(claimed, criteria)
    assert status == expected, reason


def test_derive_status_never_exceeds_the_claim():
    for claimed in ("partial", "missing"):
        for verdict, strength in (("met", "record"), ("met", "log"), ("stale", "record")):
            status, _reason = model.derive_status(claimed, [criterion(verdict, strength)])
            assert status == claimed


def test_a_sentence_is_never_proof():
    assert model.is_proof("record") and model.is_proof("log")
    assert not model.is_proof("claim") and not model.is_proof(None)


@pytest.mark.parametrize(("verdicts", "expected"), [
    ([], "unknown"), (["met"], "met"), (["met", "stale"], "stale"), (["met", "unknown", "stale"], "unknown"),
    (["met", "unmet", "unknown"], "unmet"),
])
def test_a_criterion_is_as_good_as_its_worst_target(verdicts, expected):
    assert model.combine_verdicts(verdicts) == expected


def test_weakest():
    assert model.weakest(["record", "log"]) == "log"
    assert model.weakest(["record", "claim", "log"]) == "claim"
    assert model.weakest(["record", None]) is None
    assert model.weakest([]) is None


@pytest.mark.parametrize(("result", "in_history", "changed", "expected"), [
    ("passed", True, [], "met"), ("warned", True, [], "met"), ("failed", True, [], "unmet"), ("error", True, [], "unmet"),
    (None, True, [], "unknown"), ("skipped", True, [], "unknown"),
    ("passed", False, [], "stale"), ("passed", True, ["abc1234 touched the test"], "stale"),
    ("failed", False, [], "unmet"),
])
def test_target_verdict(result, in_history, changed, expected):
    assert model.target_verdict(result, in_history=in_history, changed_since=changed) == expected


def test_alias_and_prerequisites_follow_their_rungs():
    assert model.alias_verdict("green") == ("met", "record")
    assert model.alias_verdict("stale") == ("stale", "record")
    assert model.alias_verdict("claimed") == ("met", "claim")
    assert model.alias_verdict("partial") == ("unmet", None)
    assert model.prerequisites_verdict({})[0] == "met"
    assert model.prerequisites_verdict({"A": "green", "B": "done"})[:2] == ("met", "record")
    assert model.prerequisites_verdict({"A": "green", "B": "claimed"})[:2] == ("met", "claim")
    assert model.prerequisites_verdict({"A": "stale"})[:2] == ("stale", "record")
    assert model.prerequisites_verdict({"A": "green", "B": "missing"})[0] == "unmet"
