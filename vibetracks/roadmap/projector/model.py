"""The vocabulary of bam-roadmap/1 and the pure rules that turn evidence into a status.

Everything here is pure: no files, no git, no clock. The projectors gather evidence and call
these rules; the validator calls the same rules again on a finished document, so a document
whose ``status`` disagrees with its own criteria is rejected, whoever wrote it.

The one rule that matters (Zach, Oct 3 2026: "when I click an item and it says it's done I
want to see proof of its completion"): a rung is ``green`` only when every criterion of its
``done_when`` is met by evidence that is a *record* or a *log*, at a commit in the projected
history, with nothing relevant changed since. A loop can always hold a rung below green; it
can never lift one to green by saying so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

SCHEMA_ID = "bam-roadmap/1"

# ---------------------------------------------------------------- statuses
# WHY six words, not the loops' three (green / partial / missing): "the loop says green" and
# "the proof says green" are different facts, and the gap between them is exactly what Zach
# asked to see. done is kept from the kinsim curriculum: it existed before the loop, needs no
# gate, and its proof is an inspection of existing code.
STATUSES = ("green", "done", "stale", "claimed", "partial", "missing")
SATISFIED = ("green", "done")
CLAIMED_STATUSES = ("green", "done", "partial", "missing")

# How each derived status reads in loop-status/1's three-word `where` vocabulary.
LOOP_STATUS_WORD = {"green": "green", "done": "green", "stale": "partial", "claimed": "partial",
                    "partial": "partial", "missing": "missing"}

# ---------------------------------------------------------------- criteria
# stated = a condition the loop states only in prose (Codex F11): always unknown until the loop declares it.
CRITERION_KINDS = ("test", "gate_run", "audit", "inspection", "demonstration", "package", "prerequisites", "alias", "stated")
STRUCTURAL_KINDS = ("prerequisites", "alias")
# NASA/SP-2016-6105 Rev2 and the INCOSE handbook's four verification methods (IADT). Structural
# criteria (prerequisites, alias) verify nothing themselves, so their method is null.
METHODS = ("test", "analysis", "demonstration", "inspection")
VERDICTS = ("met", "stale", "unknown", "unmet")

# ---------------------------------------------------------------- evidence
# statement = the loop's own sentence, kept when nothing it cites can be read (always strength claim).
EVIDENCE_KINDS = ("test", "junit", "gate_report", "log", "run", "commit", "file", "image", "video", "audit", "statement")
# What a criterion's targets can be: files to open, or things the document itself lists.
TARGET_KINDS = ("test", "file", "corpus", "rung", "package", "gate", "audit")
# Where an evidence item's commit came from (Codex G04, H02): a record the run itself wrote (a log's HEAD line, a run
# manifest's or ledger row's git, a gate report's git, an audit's candidate line), the same record saying its tree was
# dirty or not saying it was clean, or only the loop's event (a claim). A file time or git's reflog binds nothing.
COMMIT_SOURCES = ("artifact", "artifact-dirty", "citation")
# Strongest first. record: the result AND what it covers are read from a machine-readable
# artifact (a JUnit testcase under the target file, a ledger row, an audit's verdict line).
# log: the result is read from an artifact (a pytest summary line, EXIT 0, "34/34 checks
# passed"), but what it covers is the loop's citation. claim: only the loop's sentence.
STRENGTHS = ("record", "log", "claim")
# WHY log counts as proof and claim never does: a cited log can be opened and its pass line
# read; a sentence cannot. Raising this to ("record",) is decision 1 in the Oct 3 report.
PROOF_STRENGTHS = ("record", "log")
# passed / warned / failed are the in-toto test-result predicate's PASSED / WARNED / FAILED, lowercased;
# error and skipped are JUnit's, kept for single test cases. warned = an audit that passed with findings.
RESULTS = ("passed", "warned", "failed", "error", "skipped")
PASSING_RESULTS = ("passed", "warned")
FAILING_RESULTS = ("failed", "error")
BASES = ("repo", "data_home", "abs")


CLAIM_RANK = {"missing": 0, "partial": 1, "green": 2, "done": 2}


def lowest_claim(first: str, second: str | None) -> str:
    """The lower of two claims: a later revocation always wins over an earlier or cached green (Codex F02)."""

    if second not in CLAIM_RANK:
        return first
    return first if CLAIM_RANK.get(first, 0) <= CLAIM_RANK[second] else second


def weakest(strengths: Iterable[str | None]) -> str | None:
    """The weakest of some evidence strengths; None when any is None (nothing to rest on)."""

    ranked = list(strengths)
    if not ranked or any(strength not in STRENGTHS for strength in ranked):
        return None
    return max(ranked, key=STRENGTHS.index)


def is_proof(strength: str | None) -> bool:
    return strength in PROOF_STRENGTHS


# ---------------------------------------------------------------- one target, one criterion
def target_verdict(result: str | None, *, in_history: bool | None, changed_since: Sequence[str]) -> str:
    """The verdict one piece of evidence gives its target.

    ``in_history``: the evidence commit is an ancestor of the projected head (None: unknown).
    ``changed_since``: commits after the evidence that touched what it proves.
    """

    if result in FAILING_RESULTS:
        return "unmet"
    if result not in PASSING_RESULTS:
        return "unknown"
    if in_history is False or changed_since:
        return "stale"
    return "met"


def combine_verdicts(verdicts: Sequence[str]) -> str:
    """A criterion over several targets is only as good as its worst target.

    Order of badness: unmet (evidence says no) > unknown (no evidence) > stale > met.
    """

    if not verdicts:
        return "unknown"
    for verdict in ("unmet", "unknown", "stale"):
        if verdict in verdicts:
            return verdict
    return "met"


def alias_verdict(target_status: str) -> tuple[str, str | None]:
    """(verdict, strength) of an ``alias`` criterion, from its target rung's derived status."""

    if target_status in SATISFIED:
        return "met", "record"
    if target_status == "stale":
        return "stale", "record"
    if target_status == "claimed":
        return "met", "claim"
    return "unmet", None


def prerequisites_verdict(statuses: Mapping[str, str]) -> tuple[str, str | None, str]:
    """(verdict, strength, reason) of a ``prerequisites`` criterion from each prerequisite's derived status."""

    if not statuses:
        return "met", "record", "no prerequisites"
    unmet = [rung for rung, status in statuses.items() if status in ("partial", "missing")]
    if unmet:
        return "unmet", None, f"not green: {', '.join(unmet)}"
    claimed = [rung for rung, status in statuses.items() if status == "claimed"]
    if claimed:
        return "met", "claim", f"green only by the loop's word: {', '.join(claimed)}"
    stale = [rung for rung, status in statuses.items() if status == "stale"]
    if stale:
        return "stale", "record", f"proof is stale: {', '.join(stale)}"
    return "met", "record", f"all green or done: {', '.join(statuses)}"


# ---------------------------------------------------------------- the rung
def derive_status(claimed_status: str, criteria: Sequence[Mapping]) -> tuple[str, str]:
    """(status, reason) of a rung from what its loop claims and what its criteria show.

    - A loop can hold a rung below green: a claimed ``partial`` or ``missing`` stands as is,
      even when the evidence would allow more (done_when may be missing a declared criterion).
    - A claimed ``green`` / ``done`` stands only on proof:
      any criterion ``unmet`` -> ``partial`` (the evidence contradicts the claim);
      any criterion ``unknown`` or resting on a claim -> ``claimed``;
      any criterion ``stale`` -> ``stale``;
      else the claim stands. No criteria at all -> ``claimed``: nothing was declared to check.
    """

    if claimed_status not in SATISFIED:
        return claimed_status, f"the loop holds it at {claimed_status}"
    if not criteria:
        return "claimed", f"the loop says {claimed_status}, but declares no done_when to check it against"
    unmet = [criterion for criterion in criteria if criterion.get("verdict") == "unmet"]
    if unmet:
        return "partial", f"the loop says {claimed_status}, but {_name_criteria(unmet)} {'is' if len(unmet) == 1 else 'are'} unmet"
    unproven = [criterion for criterion in criteria
                if criterion.get("verdict") == "unknown" or not is_proof(criterion.get("strength"))]
    if unproven:
        return "claimed", f"the loop says {claimed_status}; no recorded proof for {_name_criteria(unproven)}"
    stale = [criterion for criterion in criteria if criterion.get("verdict") == "stale"]
    if stale:
        return "stale", f"proof predates a relevant change for {_name_criteria(stale)}"
    return claimed_status, "every criterion met by recorded evidence at a commit in this history"


def _name_criteria(criteria: Sequence[Mapping]) -> str:
    names = [str(criterion.get("title") or criterion.get("id")) for criterion in criteria]
    return ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")


def satisfied(status: str | None) -> bool:
    return status in SATISFIED
