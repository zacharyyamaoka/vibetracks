"""The grasping track's projector: grasp_bench's curriculum (tiers, envs, cells, gates) and its ledger, read-only.

Fixtures are copies of ``fixtures/grasping/*.py`` laid out like the real package (``<bench>/src/grasp_bench/``) in a
throwaway git repository, with ``fixtures/grasping/runs.jsonl`` as the ledger (``@HEAD`` becomes the fixture's commit).
Every document projected here also passes the schema, the stdlib checker and the validator's own consistency rules
(``against_sources=False``: the validator re-projects only the kinsim and rig loops today).

The real-data test reads the live loop and, when the package's own venv is there, checks the beaten envs against the
loop's own ``gallery.env_verdict`` (run read-only, ``-B``) as an independent oracle:

    cd ~/vibetracks-roadmap
    env -u VIRTUAL_ENV uv run --quiet --isolated --with pytest --with pyyaml --with 'jsonschema>=4.10' python -m pytest -q -s -p no:cacheprovider vibetracks/roadmap/projector/tests/test_grasping.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import ProjectionError, gitinfo, model, schema_check
from vibetracks.roadmap.projector.grasping import project_grasping
from vibetracks.roadmap.projector.validate import validate_document
from vibetracks.sources import load_sources

from .conftest import commit_all, git, write

NOW = "2026-10-04T19:00:00+00:00"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "grasping"
PACKAGE_FILES = ("curriculum.py", "contracts.py", "runner.py", "gallery.py")
#: The live loop today (the grasping session's worktree). ``grasp_bench_dir`` in the sources map, or
#: ``BAM_GRASP_BENCH_DIR``, overrides it; the real-data test skips when it is not there.
REAL_GRASP_BENCH_DIR = Path("/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/"
                            "policy/grasp_bench")


def fixture_rows(sha: str) -> list[dict]:
    rows = []
    for line in (FIXTURES / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row["git_sha"] = sha if row["git_sha"] == "@HEAD" else row["git_sha"]
        rows.append(row)
    return rows


def write_ledger(bench: Path, rows: list[dict]) -> None:
    write(bench / "out" / "ledger" / "runs.jsonl", "".join(json.dumps(row) + "\n" for row in rows))


def make_bench(tmp_path: Path) -> tuple[Path, str]:
    """``<repo>/src/core/grasp_bench`` with the fixture package committed and its ledger (gitignored, like the real one)."""

    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    bench = repo / "src" / "core" / "grasp_bench"
    for name in PACKAGE_FILES:
        write(bench / "src" / "grasp_bench" / name, (FIXTURES / name).read_text(encoding="utf-8"))
    write(bench / ".gitignore", "out/\n")
    sha = commit_all(repo, "fixture: grasp_bench")
    write_ledger(bench, fixture_rows(sha))
    return bench, sha


def project(bench: Path) -> dict:
    gitinfo.clear_cache()
    document = project_grasping(bench, now=NOW)
    assert schema_check.errors(document) == []
    assert validate_document(document, against_sources=False) == []
    return document


def rung(document: dict, rung_id: str) -> dict:
    return next(item for item in document["rungs"] if item["id"] == rung_id)


def criterion(document: dict, criterion_id: str) -> dict:
    rung_id = criterion_id.split("#", 1)[0]
    return next(item for item in rung(document, rung_id)["criteria"] if item["id"] == criterion_id)


def evidence(document: dict, rung_id: str, evidence_id: str) -> dict:
    return next(item for item in rung(document, rung_id)["evidence"] if item["id"] == evidence_id)


# ---------------------------------------------------------------- lanes, rungs, dependencies
def test_tiers_are_lanes_and_envs_are_rungs_in_declared_order(tmp_path):
    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    assert document["loop"] == "grasping"
    assert [(axis["id"], axis["title"]) for axis in document["axes"]] == [
        ("tier-1", "Tier 1 · Toy grasping"), ("tier-3", "Tier 3 · Real images, offline")]
    assert [(item["id"], item["axis"]) for item in document["rungs"]] == [
        ("toy.x", "tier-1"), ("toy.xy", "tier-1"), ("data.seen", "tier-3")]
    # A gated tier is a ladder in its declared order; an env past it waits on the nearest lower tier's gates.
    assert {item["id"]: item["depends_on"] for item in document["rungs"]} == {
        "toy.x": [], "toy.xy": ["toy.x"], "data.seen": ["toy.x", "toy.xy"]}
    assert {(edge["from"], edge["to"], edge["kind"]) for edge in document["edges"]} == {
        ("toy.x", "toy.xy", "prerequisite"), ("toy.x", "data.seen", "prerequisite"), ("toy.xy", "data.seen", "prerequisite")}
    # The env id stays verbatim beside the rung id ("/" is not an identifier character).
    assert rung(document, "toy.xy")["x"]["env"] == "toy/xy"
    gate_source = rung(document, "toy.x")["done_when"]["source"]
    assert gate_source["pointer"] == "/GATES/toy~1x" and gate_source["line"] is not None
    lines = (Path(gate_source["abs"])).read_text(encoding="utf-8").splitlines()
    assert '"toy/x": 0.97' in lines[gate_source["line"] - 1]
    # The loop's claim is its gallery verdict, sourced to the env's gate (or GATES for an ungated env).
    assert rung(document, "toy.x")["claimed_by"]["source"]["pointer"] == "/GATES/toy~1x"


def test_the_reader_never_executes_the_curriculum(tmp_path):
    bench, _sha = make_bench(tmp_path)
    curriculum = bench / "src" / "grasp_bench" / "curriculum.py"
    marker = tmp_path / "executed"
    text = curriculum.read_text(encoding="utf-8")
    write(curriculum, text + f"\nOPENED = open({str(marker)!r}, 'w')\n")
    document = project(bench)
    assert not marker.exists()
    assert any("OPENED" in warning for warning in document["warnings"])
    # A required table that is not data refuses the whole projection, naming the construct.
    write(curriculum, text.replace('GATES: dict[str, float] = {"toy/x": 0.97, "toy/xy": 0.95}',
                                   'GATES: dict[str, float] = load_gates()'))
    gitinfo.clear_cache()
    with pytest.raises(ProjectionError, match="GATES"):
        project_grasping(bench, now=NOW)


# ---------------------------------------------------------------- gated environments
def test_a_beaten_env_is_met_at_record_strength_with_the_rows_own_sha(tmp_path):
    bench, sha = make_bench(tmp_path)
    document = project(bench)
    gate = criterion(document, "toy.x#gate")
    assert (gate["kind"], gate["method"], gate["verdict"], gate["strength"]) == ("gate_run", "test", "met", "record")
    assert gate["at"] == [sha]
    (target,) = gate["targets"]
    resting = evidence(document, "toy.x", target["evidence"][0])
    # The frozen run of a non-privileged model, never the oracle (it reads ground truth) and never the later smoke.
    assert resting["run_id"] == "r03_bandit_toy_x"
    assert (resting["kind"], resting["origin"], resting["commit"], resting["commit_source"], resting["strength"]) == (
        "run", "ledger", sha, "artifact", "record")
    assert resting["role"] == "supports" and resting["result"] == "passed"
    assert resting["line"] == 3 and resting["path"].endswith("out/ledger/runs.jsonl")
    assert target["spec"]["protocol"] == {"name": "eval-2000", "seed": 20261004, "episodes": 2000, "split": "test", "k": 1}
    assert target["spec"]["gate"] == 0.97
    assert rung(document, "toy.x")["support"]["runs"] == ["r03_bandit_toy_x"]
    assert rung(document, "toy.x")["x"]["beaten"] is True
    assert rung(document, "toy.x")["x"]["best"]["model"] == "M3.bandit"


def test_an_env_below_its_gate_is_not_met(tmp_path):
    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    gate = criterion(document, "toy.xy#gate")
    assert (gate["verdict"], gate["strength"]) == ("unmet", None)
    (target,) = gate["targets"]
    resting = evidence(document, "toy.xy", target["evidence"][0])
    assert resting["run_id"] == "r07_bandit_toy_xy" and resting["result"] == "failed"
    assert "0.940" in target["note"] and "0.95" in target["note"]
    assert rung(document, "toy.xy")["x"]["beaten"] is False


def test_a_dirty_tree_row_is_only_a_claim(tmp_path):
    bench, sha = make_bench(tmp_path)
    rows = fixture_rows(sha)
    for row in rows:
        if row["run_id"] == "r03_bandit_toy_x":
            row["git_dirty"] = True
    write_ledger(bench, rows)
    document = project(bench)
    gate = criterion(document, "toy.x#gate")
    resting = evidence(document, "toy.x", gate["targets"][0]["evidence"][0])
    assert (gate["verdict"], gate["strength"]) == ("met", "claim")
    assert (resting["commit_source"], resting["strength"]) == ("artifact-dirty", "claim")
    assert "uncommitted changes" in gate["targets"][0]["note"]
    # Even a loop that claimed green could not lift it: the proof is the loop's word.
    assert model.derive_status("green", rung(document, "toy.x")["criteria"])[0] != "green"


def test_a_clean_winner_is_preferred_over_a_dirty_one(tmp_path):
    bench, sha = make_bench(tmp_path)
    rows = fixture_rows(sha)
    for row in rows:
        if row["run_id"] == "r03_bandit_toy_x":
            row["git_dirty"] = True
    rows.append({**rows[2], "run_id": "r09_dense_toy_x", "cell_id": "M3.dense@toy/x", "model": "M3.dense",
                 "ci_lo": 0.990, "git_dirty": False})
    write_ledger(bench, rows)
    document = project(bench)
    gate = criterion(document, "toy.x#gate")
    assert (gate["verdict"], gate["strength"]) == ("met", "record")
    assert evidence(document, "toy.x", gate["targets"][0]["evidence"][0])["run_id"] == "r09_dense_toy_x"


# ---------------------------------------------------------------- ungated environments
def test_an_ungated_env_is_measured_but_never_green(tmp_path):
    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    data = rung(document, "data.seen")
    measured = criterion(document, "data.seen#measured")
    assert (measured["kind"], measured["verdict"], measured["strength"], measured["targets"]) == ("stated", "unknown", None, [])
    assert "paired, scene-bootstrapped" in measured["text"]
    assert "1 of 2 wave-1 cells" in measured["reason"]
    assert [item["run_id"] for item in data["evidence"]] == ["r08_uniform_data_seen"]
    assert data["evidence"][0]["role"] == "context"
    assert data["kpis"][0]["value"] == 3.1 and data["kpis"][0]["run"] == "r08_uniform_data_seen"
    for claim in model.CLAIMED_STATUSES:
        assert model.derive_status(claim, data["criteria"])[0] != "green"


# ---------------------------------------------------------------- claims, frontier, blockers
def test_the_claim_is_the_gallery_verdict_and_the_evidence_caps_it(tmp_path):
    """No status file: the loop's own published rule (a frozen-protocol headline run clearing GATES) is its claim, so
    a beaten env claims green, a measured one partial, an unmeasured one missing; the evidence still decides status."""

    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    claims = {item["id"]: item["claimed_status"] for item in document["rungs"]}
    assert claims == {"toy.x": "green", "toy.xy": "partial", "data.seen": "partial"}
    assert rung(document, "toy.x")["status"] in {"green", "claimed"}  # green only on recorded proof
    assert rung(document, "toy.xy")["status"] == "partial"
    for item in document["rungs"]:
        assert item["status"] != "green" or item["claimed_status"] == "green"


def test_the_frontier_is_the_lowest_unfinished_tiers_unbeaten_envs(tmp_path):
    bench, sha = make_bench(tmp_path)
    document = project(bench)
    # Tier 1's wave-1 cells are all measured, but toy/xy is below its gate.
    assert document["summary"]["frontier"] == ["toy.xy"]
    assert [item["id"] for item in document["rungs"] if item["frontier"]] == ["toy.xy"]
    assert (document["summary"]["wave"], document["summary"]["phase"]) == (None, None)
    assert document["summary"]["beaten"] == ["toy.x"] and document["summary"]["gated"] == ["toy.x", "toy.xy"]
    # A later frozen run beats toy/xy: tier 1 is done, and tier 3 still has an unmeasured wave-1 cell.
    rows = fixture_rows(sha)
    rows.append({**rows[6], "run_id": "r10_bandit_toy_xy_rerun", "value": 0.97, "ci_lo": 0.962,
                 "started_at": "2026-10-05T03:00:00+00:00"})
    write_ledger(bench, rows)
    document = project(bench)
    assert document["summary"]["frontier"] == ["data.seen"]
    assert rung(document, "toy.xy")["x"]["cells"]["wave1_measured"] == 3
    assert rung(document, "data.seen")["x"]["cells"] == {"wave1_planned": 2, "wave1_measured": 1, "planned": 3, "measured": 1,
                                                        "by_status": {"wave1": 2, "wave2": 1}, "wave1_unmeasured": ["M1.oracle@data/seen"]}


def test_needs_cells_with_a_named_blocker_become_rung_blockers(tmp_path):
    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    (blocker,) = rung(document, "toy.xy")["blockers"]
    assert blocker["id"] == "M5.ggcnn@toy/xy"
    assert blocker["title"] == "M5.ggcnn needs download approval (planar classics, BSD-3)"
    assert blocker["source"]["exists"] and blocker["source"]["line"] is not None
    assert rung(document, "toy.x")["blockers"] == [] and rung(document, "data.seen")["blockers"] == []


def test_the_document_passes_the_schema_and_the_jsonschema_oracle(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    bench, _sha = make_bench(tmp_path)
    document = project(bench)
    oracle = jsonschema.Draft202012Validator(json.loads(schema_check.SCHEMA_PATH.read_text(encoding="utf-8")))
    assert [error.message for error in oracle.iter_errors(document)] == []
    assert json.loads(json.dumps(document)) == document


def test_a_missing_ledger_projects_with_nothing_measured(tmp_path):
    bench, _sha = make_bench(tmp_path)
    (bench / "out" / "ledger" / "runs.jsonl").unlink()
    document = project(bench)
    assert all(item["verdict"] == "unknown" for item in (criterion(document, "toy.x#gate"), criterion(document, "toy.xy#gate")))
    assert document["summary"]["frontier"] == ["toy.x", "toy.xy"]
    assert any("no ledger" in warning for warning in document["warnings"])


# ---------------------------------------------------------------- the live loop
def real_grasp_bench_dir() -> Path:
    named = os.environ.get("BAM_GRASP_BENCH_DIR") or load_sources().get("grasp_bench_dir")
    return Path(named).expanduser() if named else REAL_GRASP_BENCH_DIR


def gallery_beaten(bench: Path) -> list[str] | None:
    """The loop's own answer (``gallery.env_verdict`` over its ledger), run read-only in its venv; None without one."""

    python = bench / ".venv" / "bin" / "python"
    if not python.is_file():
        return None
    script = ("from grasp_bench import curriculum, gallery, ledger\n"
              "heads = gallery.headline_runs(ledger.Ledger().load_runs())\n"
              "print(__import__('json').dumps(sorted(e for e in curriculum.GATES if gallery.env_verdict(e, heads)[0])))\n")
    environment = {key: value for key, value in os.environ.items() if key not in ("VIRTUAL_ENV", "GRASP_BENCH_OUT")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run([str(python), "-B", "-c", script], capture_output=True, text=True, timeout=120,
                               cwd=str(bench), env=environment, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.real_data
def test_the_live_grasping_loop_projects_and_validates():
    bench = real_grasp_bench_dir()
    if not (bench / "src" / "grasp_bench" / "curriculum.py").is_file():
        pytest.skip(f"the grasping loop is not on this machine ({bench})")
    for _attempt in range(2):  # WHY twice: the live loop appends rows; a row landing between oracle and projection is it moving
        oracle = gallery_beaten(bench)
        gitinfo.clear_cache()
        started = time.perf_counter()
        document = project_grasping(bench, now=NOW)
        elapsed = time.perf_counter() - started
        beaten = [rung(document, rung_id)["x"]["env"] for rung_id in document["summary"]["beaten"]]
        if oracle is None or sorted(beaten) == oracle:
            break
    assert schema_check.errors(document) == []
    assert validate_document(document, against_sources=False) == []
    jsonschema = pytest.importorskip("jsonschema")
    assert list(jsonschema.Draft202012Validator(schema_check.load()).iter_errors(document)) == []
    gated = [rung(document, rung_id)["x"]["env"] for rung_id in document["summary"]["gated"]]
    met = sorted(item["x"]["env"] for item in document["rungs"]
                 if any(entry["id"].endswith("#gate") and entry["verdict"] in ("met", "stale") for entry in item["criteria"]))
    strengths = {item["x"]["env"]: entry["strength"] for item in document["rungs"] for entry in item["criteria"]
                 if entry["id"].endswith("#gate") and entry["verdict"] in ("met", "stale")}
    print(f"\n[grasping] projected in {elapsed:.3f}s at {document['as_of']['head'][:8]}; "
          f"{len(document['rungs'])} rungs, counts {document['counts']['by_status']}")
    print(f"[grasping] gated envs beaten {len(beaten)}/{len(gated)}: {beaten}; gate strengths {strengths}")
    print(f"[grasping] gallery.env_verdict oracle: {oracle}")
    print(f"[grasping] frontier {document['summary']['frontier']}; cells {document['summary']['cells']}")
    print(f"[grasping] needs-you blockers: {sum(len(item['blockers']) for item in document['rungs'])}")
    assert sorted(beaten) == met
    if oracle is not None:
        assert sorted(beaten) == oracle
    assert len(gated) == 10
    assert document["summary"]["frontier"]
    assert elapsed < 5.0
