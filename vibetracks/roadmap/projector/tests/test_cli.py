"""``python -m vibetracks.roadmap.projector``: project, validate, show, and the exit codes a loop's tick can rely on."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .conftest import REPO_ROOT


def run(*arguments: str) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    environment["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run([sys.executable, "-m", "vibetracks.roadmap.projector", *arguments], capture_output=True, text=True,
                          cwd=REPO_ROOT, env=environment, timeout=120)


def test_project_validate_show_round_trip(kinsim_loop, tmp_path):
    out = tmp_path / "kinsim.json"
    projected = run("project", "kinsim", "--curriculum-dir", str(kinsim_loop.curriculum_dir),
                    "--data-home", str(kinsim_loop.data_home), "--now", "2026-10-03T19:00:00+00:00", "--out", str(out))
    assert projected.returncode == 0, projected.stderr
    assert "kinsim: 4 rungs (3 green, 1 done)" in projected.stderr
    document = json.loads(out.read_text())
    assert document["schema"] == "bam-roadmap/1"

    validated = run("validate", str(out))
    assert validated.returncode == 0 and "valid." in validated.stdout

    shown = run("show", str(out), "EV9")
    assert shown.returncode == 0 and "EV9 Widget log: GREEN (the loop says green)" in shown.stdout
    assert "test_widget_acceptance.py" in shown.stdout

    for rung in document["rungs"]:
        if rung["id"] == "MR9":
            rung["status"] = "green"
    out.write_text(json.dumps(document))
    rejected = run("validate", str(out))
    assert rejected.returncode == 1 and "INVALID" in rejected.stdout and "MR9: status green but done_when gives done" in rejected.stdout


def test_rig_projection_and_unreadable_loops(rig_loop, tmp_path):
    projected = run("project", "rig", "--rig-dir", str(rig_loop.rig_dir), "--now", "2026-10-03T19:00:00+00:00")
    assert projected.returncode == 0, projected.stderr
    assert json.loads(projected.stdout)["loop"] == "rig"
    missing = run("project", "rig", "--rig-dir", str(tmp_path / "nowhere"))
    assert missing.returncode == 2 and "cannot read" in missing.stderr


def test_validate_refuses_a_file_that_is_not_json(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    result = run("validate", str(broken))
    assert result.returncode == 1 and "unreadable" in result.stdout


def test_the_package_runs_with_no_dependencies():
    """The runtime imports only the standard library (pytest and jsonschema are test-only)."""

    # WHY a stand-in for the parent package: vibetracks/__init__.py loads the tracker, which needs PyYAML; the projector
    # (and the sources map its CLI reads) must still run on the standard library alone, so the probe imports them
    # without executing that __init__.
    probe = ("import sys, types; "
             f"parent = types.ModuleType('vibetracks'); parent.__path__ = [{str(REPO_ROOT / 'vibetracks')!r}]; "
             "sys.modules['vibetracks'] = parent; "
             "import vibetracks.roadmap.projector, vibetracks.roadmap.projector.__main__; "
             "bad = sorted(name for name in sys.modules if name.split('.')[0] in {'jsonschema', 'pytest', 'yaml', 'numpy'}); "
             "print(bad)")
    result = subprocess.run([sys.executable, "-S", "-c", probe], capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
                            env={"PYTHONPATH": str(REPO_ROOT), "PATH": os.environ.get("PATH", "")})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_the_readme_commands_are_paste_ready():
    """Repo rule (AGENTS.md): every command block starts with a standalone `cd ~/bam_ws/...` line."""

    repository = Path(__file__).resolve().parents[4]
    checker = repository / "src/dev/bam_docs/check_command_cwds.py"
    if not checker.is_file():
        import pytest

        pytest.skip("the repository's command checker is not in this checkout")
    result = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, cwd=repository, timeout=300)
    mine = [line for line in (result.stdout + result.stderr).splitlines() if "src/dev/bam_roadmap" in line]
    assert mine == []
