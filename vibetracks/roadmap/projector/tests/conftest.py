"""Fixtures: a throwaway git repository holding a tiny kinsim-shaped loop and a tiny rig-shaped loop.

Every rule of the status derivation is exercised on these, so a test can commit a change and
watch a green go stale, tamper with a fold and watch the green fall, without touching the real
loops. Real-data tests live in test_real_data.py and skip when the loops are not on this machine.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from vibetracks.roadmap.projector import files, gitinfo
from vibetracks.sources import load_sources

PACKAGE_DIR = Path(__file__).resolve().parents[1]
#: The checkout that holds ``vibetracks``: where ``python -m vibetracks.roadmap.projector`` runs from.
REPO_ROOT = PACKAGE_DIR.parents[2]
#: WHY from the sources map: in bam_ws the real loops were this package's siblings (``PACKAGE_DIR.parent``); moved into
#: vibetracks, the real-data tests read the same map the dashboard's live /doc reads, so both judge the same loop.
KINSIM_CURRICULUM_DIR = Path(load_sources()["kinsim_curriculum_dir"])
LOOP_DEV_DIR = KINSIM_CURRICULUM_DIR.parent  # bam_ws src/dev of the checkout the kinsim loop is read from
RIG_LOOP_DIR = Path(load_sources()["rig_loop_dir"])
ACCEPTANCE = "src/pkg/tests/test_widget_acceptance.py"
RIG_ACCEPTANCE = "src/rig/tests/test_twin.py"


def git(repo: Path, *arguments: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                   "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    completed = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True, env=environment)
    return completed.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    gitinfo.clear_cache()
    return git(repo, "rev-parse", "HEAD")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, payload) -> Path:
    return write(path, json.dumps(payload, indent=1) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


TEST_FILE = '''import pytest


def test_widget_builds():
    assert True


class TestWidget:
    def test_widget_spins(self):
        assert True
'''

RULER = {"schema": "bam-ruler/1", "ruler_id": "r1", "rows": [], "tolerances": {}}


def curriculum() -> dict:
    corpus = lambda corpus_id, count: {"corpus_id": corpus_id, "count": count, "latency": {"mode": "budget", "budget_s": 1.0}}  # noqa: E731
    return {
        "schema": "bam-curriculum/1",
        "axes": [{"axis_id": "eval", "title": "Eval", "order": 1}, {"axis_id": "robots", "title": "Robots", "order": 2},
                 {"axis_id": "objects", "title": "Objects", "order": 3}, {"axis_id": "multi", "title": "Multi", "order": 4}],
        "rungs": [
            {"rung_id": "EV9", "axis_id": "eval", "title": "Widget log", "adds": "a widget", "cell": {},
             "gate": {"kind": "infra", "acceptance": [ACCEPTANCE]}, "gate_text": "infra: widget acceptance",
             "prerequisites": [], "baseline": {"status": "next", "evidence": "", "note": ""}, "wave": 1, "kpi_weight": 3, "est_waves": 1},
            {"rung_id": "RB9", "axis_id": "robots", "title": "Widget robot", "adds": "a robot", "cell": {},
             "gate": {"kind": "std", "regression_corpus": "rb9-regression", "promotion_corpus": "rb9-promotion", "repeats": 2,
                      "feasible_rate_min": 1.0, "recovery_min": None},
             "gate_text": "std", "prerequisites": ["EV9"],
             "baseline": {"status": "partial", "evidence": "", "note": ""}, "wave": 2, "kpi_weight": 5, "est_waves": 1},
            {"rung_id": "OB9", "axis_id": "objects", "title": "Widget objects", "adds": "objects", "cell": {},
             "gate": {"kind": "same_as", "rung": "RB9"}, "gate_text": "same_as RB9", "prerequisites": [],
             "baseline": {"status": "partial", "evidence": "", "note": ""}, "wave": 2, "kpi_weight": 0, "est_waves": 0},
            {"rung_id": "MR9", "axis_id": "multi", "title": "One widget", "adds": "one", "cell": {}, "gate": {"kind": "none"},
             "gate_text": "-", "prerequisites": [],
             "baseline": {"status": "done", "evidence": "The only mode (widget.py:1-2).", "note": "the only mode"},
             "wave": 0, "kpi_weight": 0, "est_waves": 0},
        ],
        "corpora": [corpus("rb9-regression", 4), corpus("rb9-promotion", 8)],
        "ruler": "ruler/r1.json",
    }


def ledger_row(run_id: str, tier: str, corpus_id: str, count: int, feasible: int, sha: str, ruler_sha: str, verdict_hash: str) -> dict:
    return {"run_id": run_id, "ts": "2026-10-03T03:00:00+00:00", "schema": "bam-ledger/1", "n_episodes": count,
            "artifacts": {"run_dir": f"runs/{run_id}"}, "git": {"sha": sha, "dirty": False, "branch": "fixture"},
            "gates": {"all_passed": True, "coverage": 1.0, "void_reasons": {}},
            "totals": {"feasible": feasible, "presented": count, "void": 0},
            "metrics": {"rung_id": "RB9", "tier": tier, "corpus_id": corpus_id, "feasible_rate": feasible / count, "recovery": 1.0,
                        "ruler_sha256": ruler_sha, "verdict_hash": verdict_hash, "latency": {"mode": "budget", "budget_s": 1.0},
                        "gate_met": feasible == count}}


def manifest_for(row: dict, corpus: dict) -> dict:
    """The ``bam-run-manifest/1`` a judged run writes for itself: what it ran on (Codex H04) and where (H02)."""

    metrics = row["metrics"]
    return {"schema": "bam-run-manifest/1", "run_id": row["run_id"], "rung_id": metrics["rung_id"], "tier": metrics["tier"],
            "corpus_id": metrics["corpus_id"], "corpus": dict(corpus), "git": dict(row["git"]), "kind": "judged",
            "ruler_sha256": metrics["ruler_sha256"], "latency": dict(metrics["latency"]), "presented": row["totals"]["presented"]}


@dataclass
class KinsimLoop:
    repo: Path
    curriculum_dir: Path
    data_home: Path
    evidence_dir: Path
    first_commit: str
    ruler_sha: str

    def fold(self, statuses: dict[str, str], reasons: dict[str, str] | None = None) -> None:
        """Write status.json the way the loop's fold would (only the fields the projector reads)."""

        reasons = reasons or {}
        rows = [{"rung_id": rung_id, "status": status, "reason": reasons.get(rung_id, ""), "blocking_triage": [],
                 "last_reading": None, "readings": 0, "green_since_run_id": None} for rung_id, status in statuses.items()]
        ledger = files.read_jsonl(self.data_home / "runs.jsonl")
        write_json(self.data_home / "status.json", {"schema": "bam-curriculum-status/1", "ruler_sha256": self.ruler_sha,
                                                    "ledger_rows_seen": len(ledger), "wave": 2, "phase": "between_waves",
                                                    "frontier": [], "rungs": rows})

    def event(self, **row) -> None:
        base = {"ts": "2026-10-03T04:00:00+00:00", "wave": 2, "kind": "note", "subject": "x", "status": "ok", "detail": "",
                "commit": None, "evidence": None}
        append_jsonl(self.data_home / "loop_events.jsonl", {**base, **row})

    def corpora(self) -> dict[str, dict]:
        curriculum_json = json.loads((self.curriculum_dir / "curriculum.json").read_text(encoding="utf-8"))
        return {corpus["corpus_id"]: corpus for corpus in curriculum_json.get("corpora") or []}

    def add_reading(self, row: dict, *, manifest: bool = True) -> None:
        """A judged run as the loop records it: its ledger row and the run manifest it wrote (unless ``manifest`` is False)."""

        append_jsonl(self.data_home / "runs.jsonl", row)
        if manifest:
            write_json(self.data_home / "runs" / row["run_id"] / "manifest.json",
                       manifest_for(row, self.corpora().get(row["metrics"]["corpus_id"], {})))

    def retake(self, sha: str) -> None:
        """Every recorded reading taken at ``sha`` instead: both of its records, the ledger row and its manifest."""

        ledger = self.data_home / "runs.jsonl"
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            row["git"]["sha"] = sha
            manifest_path = self.data_home / "runs" / row["run_id"] / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["git"]["sha"] = sha
                write_json(manifest_path, manifest)
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def log(self, name: str, text: str) -> Path:
        return write(self.evidence_dir / name, text)

    def gate_run(self, name: str, commit: str, outcomes: dict[str, str], ts: str, *, select: list[str] | None = None,
                 deselected: int = 0) -> None:
        """A gate run as bam_curriculum's gate leaves it: a console log, gate_report.json, the suite's output.log and
        JUnit file, plus its gate_run event.

        The console log starts with the run's own ``HEAD <sha>;`` line (the binding the evaluator needs, Codex G04, H02);
        the suite's log records the pytest command and its summary (its recorded collection, Codex G06); the report's
        counts, exit code and red sets are what the gate computes from the JUnit file (``gate.run_suite``), so every record
        agrees (Codex H03). ``select`` adds pytest selection arguments (``-k``, node ids), ``deselected`` the count its
        summary reports.
        """

        out = self.evidence_dir / name
        cases = []
        for case, outcome in outcomes.items():
            classname, function = case.rsplit("::", 1)
            child = {"failed": '<failure message="boom"/>', "error": '<error message="boom"/>', "skipped": "<skipped/>"}.get(outcome, "")
            cases.append(f'<testcase classname="{classname}" name="{function}" time="0.01">{child}</testcase>')
        junit = write(out / "acc" / "junit.xml", '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
                      + "".join(cases) + "</testsuite></testsuites>")
        red = sorted(case for case, outcome in outcomes.items() if outcome in ("failed", "error"))
        cwd = str(self.repo / "src/pkg")
        argv = ["pytest", "-q", "-p", "no:cacheprovider", *(select or []), f"--junitxml={junit}"]
        counts = {word: sum(1 for outcome in outcomes.values() if outcome == key)
                  for key, word in (("failed", "failed"), ("passed", "passed"), ("skipped", "skipped"), ("error", "errors"))}
        counts["deselected"] = deselected
        summary = ", ".join(f"{number} {word}" for word, number in counts.items() if number) + " in 0.05s"
        log = write(out / "acc" / "output.log", f"$ (cd {cwd} && {' '.join(argv)})\n{'.' * len(outcomes)}  [100%]\n{summary}\n")
        report = write_json(out / "gate_report.json", {
            "schema": "bam-gate-report/1", "passed": not red, "unexpected_red": red, "unexpected_green": [], "tier": "fast",
            "root": str(self.repo), "wall_s": 0.0,
            "suites": [{"suite": "acc", "cwd": cwd, "junit": True, "exit_code": 1 if red else 0, "argv": argv,
                        "counts": {status: sum(1 for outcome in outcomes.values() if outcome == status)
                                   for status in ("passed", "failed", "error", "skipped")},
                        "then": [], "unexpected_red": red, "unexpected_green": [], "expected_red": [], "log": str(log)}]})
        console = self.log(f"{name}.txt", f"HEAD {commit};\nsuite acc ...\nGATE {'FAIL' if red else 'PASS'} tier=fast report={report}\n"
                                          f"exit {1 if red else 0}\n")
        self.event(ts=ts, kind="gate_run", subject="fast", status="fail" if red else "pass", commit=commit[:8],
                   evidence=f"python -m bam_curriculum gate --tier fast ({console})")


def pytest_configure(config) -> None:
    # WHY here: in bam_ws the marker was registered by the package's own pyproject.toml, which did not move.
    config.addinivalue_line("markers", "real_data: reads the live loop state on this machine; skipped when it is absent")


@pytest.fixture()
def kinsim_loop(tmp_path: Path) -> KinsimLoop:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    curriculum_dir = repo / "src/dev/bam_curriculum"
    write_json(curriculum_dir / "curriculum.json", curriculum())
    write_json(curriculum_dir / "ruler/r1.json", RULER)
    write_json(curriculum_dir / "triage.json", {"schema": "bam-triage/1", "items": []})
    write(repo / "src/pkg/widget.py", "WIDGET = 1\nSPIN = 2\n")
    write(repo / ACCEPTANCE, TEST_FILE)
    first = commit_all(repo, "fixture: the loop and its acceptance")
    data_home = tmp_path / "home"
    data_home.mkdir()
    loop = KinsimLoop(repo, curriculum_dir, data_home, tmp_path / "evidence", first, files.canonical_sha256(RULER))
    for run_id, tier, corpus_id, count in (("rb9-reg-r1", "regression", "rb9-regression", 4), ("rb9-reg-r2", "regression", "rb9-regression", 4),
                                           ("rb9-promo", "promotion", "rb9-promotion", 8)):
        loop.add_reading(ledger_row(run_id, tier, corpus_id, count, count, first, loop.ruler_sha,
                                    "same-hash" if tier == "regression" else "promo-hash"))
        write_json(data_home / "runs" / run_id / "batch.json", {
            "schema": "bam-batch-verdict/1", "presented": count, "feasible": count, "void": 0,
            "verdict_hash": "same-hash" if tier == "regression" else "promo-hash", "primary_histogram": {}})
    acceptance_log = loop.log("ev9_acceptance.txt", "..\n2 passed in 0.10s\nEXIT 0\n")
    loop.event(ts="2026-10-03T04:00:00+00:00", kind="rung_status_changed", subject="EV9", status="green", commit=first[:8],
               evidence=f"'pytest tests/test_widget_acceptance.py' -> 2 passed ({acceptance_log})")
    loop.gate_run("gate_fast_1", first, {"tests.test_widget_acceptance::test_widget_builds": "passed",
                                         "tests.test_widget_acceptance.TestWidget::test_widget_spins": "passed"},
                  ts="2026-10-03T04:10:00+00:00")
    loop.fold({"EV9": "green", "RB9": "green", "OB9": "green", "MR9": "done"},
              {"RB9": "gate met by rb9-reg-r1, rb9-reg-r2, rb9-promo"})
    return loop


# ---------------------------------------------------------------- rig
def ladder(r1_status: str = "landed", r1_commit: str | None = None) -> dict:
    return {
        "schema": "rig-ladder/1", "loop": "rig",
        "episode": {"started": "2026-10-02", "stop": "2026-10-16", "stop_condition": "a floor"},
        "milestone": {"title": "Pick up real waste", "due": "2026-10-22", "state": "sim first"},
        "last_real_run": "2026-07-29", "links": {"dashboard": "sps open", "report": "reports/x.html"},
        "axes": [{"id": "TWIN", "title": "Twin", "rungs": [
            {"id": "TW0", "title": "Replay harness", "status": "green" if r1_status == "landed" else "partial", "packages": ["R1"]},
            {"id": "TW1", "title": "Twin on the dashboard", "status": "green", "packages": []}]}],
        "packages": [{"id": "R1", "title": "Replay harness", "rung": "TW0", "kind": "barrier", "size": "M", "needs_hardware": False,
                      "depends_on": [], "acceptance": "replays within 1e-6 rad", "acceptance_paths": [RIG_ACCEPTANCE],
                      "acceptance_is_tests": True,
                      "write_set": ["src/rig/twin.py", RIG_ACCEPTANCE], "status": r1_status, "commit": r1_commit,
                      "updated": "2026-10-02T22:39:58-07:00", "note": ""}],
        "blockers": [],
    }


@dataclass
class RigLoop:
    repo: Path
    rig_dir: Path
    evidence_dir: Path
    first_commit: str

    def event(self, **row) -> None:
        base = {"ts": "2026-10-02T22:40:00-07:00", "wave": 1, "kind": "note", "subject": "x", "status": "ok", "detail": "",
                "commit": None, "evidence": None}
        append_jsonl(self.rig_dir / "loop_events.jsonl", {**base, **row})


@pytest.fixture()
def rig_loop(tmp_path: Path) -> RigLoop:
    repo = tmp_path / "rigrepo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo / "src/rig/twin.py", "GAP = 0.5\n")
    write(repo / RIG_ACCEPTANCE, "def test_replay_matches():\n    assert True\n")
    first = commit_all(repo, "fixture: the twin and its acceptance")
    rig_dir = repo / "src/dev/bam_rig_loop"
    write_json(rig_dir / "ladder.json", ladder(r1_commit=first[:8]))
    write_json(rig_dir / "triage.json", {"schema": "bam-triage/1", "items": [
        {"triage_id": "T4", "title": "Open a bench window", "status": "open", "blocks": ["TW1"], "default": "keep climbing in sim",
         "default_applies_after_wave": 1, "opened_wave": 0, "question": "", "recommendation": ""}]})
    commit_all(repo, "fixture: the rig loop state")
    loop = RigLoop(repo, rig_dir, tmp_path / "rig-evidence", first)
    loop.event(kind="rung_status_changed", subject="TW0", status="green", commit=first[:8],
               evidence="src/rig: pytest tests/test_twin.py -> 3 passed")
    return loop
