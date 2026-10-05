"""A verdict is accepted only with the bench's required module witnesses, each inside its src/grasp_bench (Codex r2, 6).

The fault: verdict() checked the module entries the subprocess happened to print, but never required any, so a
document with ``modules: {}`` came back with ``error: null``. These tests run the real bridge against a fake bench and
rewrite only the document its subprocess prints, the seam a wrong or partial import would show up at.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from tests.test_grasp_bench_bridge_deps import make_bench
from vibetracks.benches import grasp_bench_bridge

LIVE_BENCH = Path("/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/policy/grasp_bench")
LIVE_PYTHON = LIVE_BENCH / ".venv" / "bin" / "python"

Rewrite = Callable[[dict[str, Any], Path], dict[str, Any]]


class Doctored:
    """Runs the bench subprocess for real, then hands the bridge ``rewrite(document, code_dir)`` in its place."""

    def __init__(self, rewrite: Rewrite, code: Path) -> None:
        self.rewrite, self.code, self.real = rewrite, code, subprocess.run

    def __call__(self, args, *rest, **kwargs):
        done = self.real(args, *rest, **kwargs)
        if not any(arg in (grasp_bench_bridge.SCRIPT, grasp_bench_bridge.VERDICT_SCRIPT) for arg in args):
            return done
        doc = json.loads([line for line in done.stdout.splitlines() if line.strip()][-1])
        return subprocess.CompletedProcess(args, 0, "\n" + json.dumps(self.rewrite(doc, self.code)) + "\n", "")


def drop_module(name: str) -> Rewrite:
    def rewrite(doc: dict[str, Any], code: Path) -> dict[str, Any]:
        doc["modules"].pop(name, None)
        return doc
    return rewrite


def drop_dependency(file: str) -> Rewrite:
    def rewrite(doc: dict[str, Any], code: Path) -> dict[str, Any]:
        doc["dependencies"] = [path for path in doc["dependencies"] if Path(path).name != file]
        return doc
    return rewrite


def move_module(name: str) -> Rewrite:
    """The witness names a real file, but one outside the bench's src/grasp_bench."""

    def rewrite(doc: dict[str, Any], code: Path) -> dict[str, Any]:
        elsewhere = code.parent.parent / "elsewhere" / f"{name}.py"
        elsewhere.parent.mkdir(exist_ok=True)
        elsewhere.write_text((code / f"{name}.py").read_text(encoding="utf-8"), encoding="utf-8")
        doc["modules"][name] = str(elsewhere)
        doc["dependencies"] = sorted({*doc["dependencies"], str(elsewhere)})
        return doc
    return rewrite


def add_outside_dependency(doc: dict[str, Any], code: Path) -> dict[str, Any]:
    outside = code.parent.parent / "stray.py"
    outside.write_text("", encoding="utf-8")
    doc["dependencies"] = sorted({*doc["dependencies"], str(outside)})
    return doc


def empty_modules(doc: dict[str, Any], code: Path) -> dict[str, Any]:
    doc["modules"] = {}
    return doc


def no_dependencies(doc: dict[str, Any], code: Path) -> dict[str, Any]:
    del doc["dependencies"]
    return doc


BROKEN: dict[str, Rewrite] = {
    "modules: {} (the audit's probe)": empty_modules,
    "registry witness missing": drop_module("registry"),
    "contracts witness missing": drop_module("contracts"),
    "package __init__ witness missing": drop_module("__init__"),
    "registry imported from outside src/grasp_bench": move_module("registry"),
    "a dependency outside src/grasp_bench": add_outside_dependency,
    "no dependency list": no_dependencies,
    "stats.py missing from the dependency list": drop_dependency("stats.py"),
}


class VerdictV2WitnessTest(unittest.TestCase):
    @unittest.skipUnless(LIVE_PYTHON.exists(), f"no bench venv at {LIVE_PYTHON}")
    def test_the_pinned_set_is_what_a_real_run_of_the_live_bench_imports(self) -> None:
        seen: list[dict[str, Any]] = []

        def keep(doc: dict[str, Any], code: Path) -> dict[str, Any]:
            seen.append(doc)
            return doc

        with tempfile.TemporaryDirectory() as folder:
            doctored = Doctored(keep, (LIVE_BENCH / "src" / "grasp_bench").resolve())
            with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=doctored):
                result = grasp_bench_bridge.verdict(LIVE_BENCH, cache_dir=Path(folder) / "cache")
        self.assertIsNone(result["error"], result["error"])
        # WHY a subset and not equality: a new import in the bench is still stamped for the cache and placed inside
        # src/grasp_bench; only losing a pinned witness (or importing it from elsewhere) refuses the verdict.
        self.assertLessEqual(set(grasp_bench_bridge.REQUIRED_MODULES), set(seen[0]["modules"]))
        self.assertEqual(set(grasp_bench_bridge.REQUIRED_MODULES),
                         {"__init__", "contracts", "curriculum", "gallery", "grasp", "ledger", "registry", "runner",
                          "stats"})

    def test_an_honest_document_is_accepted_and_cached(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            result = grasp_bench_bridge.verdict(bench, cache_dir=Path(folder) / "cache")
            self.assertIsNone(result["error"], result["error"])
            self.assertTrue((Path(folder) / "cache" / grasp_bench_bridge.VERDICT_CACHE_NAME).is_file())

    def test_a_document_missing_or_misplacing_a_required_witness_is_an_error_and_never_cached(self) -> None:
        for label, rewrite in BROKEN.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as folder:
                bench = make_bench(Path(folder) / "grasp_bench")
                cache = Path(folder) / "cache"
                doctored = Doctored(rewrite, (bench / "src" / "grasp_bench").resolve())
                with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=doctored):
                    result = grasp_bench_bridge.verdict(bench, cache_dir=cache)
                self.assertTrue(result["error"], f"{label}: accepted")
                self.assertEqual((result["envs"], result["runs"], result["headline"]), ({}, {}, {}), label)
                self.assertFalse((cache / grasp_bench_bridge.VERDICT_CACHE_NAME).exists(), f"{label}: cached")
                # WHY a second, honest call: the refusal left nothing behind that could answer for the bench later.
                honest = grasp_bench_bridge.verdict(bench, cache_dir=cache)
                self.assertIsNone(honest["error"], f"{label}: {honest['error']}")


class BenchVerdictV1WitnessTest(unittest.TestCase):
    """The sibling reader: bench_verdict() checked its five declared modules, but took any other reported file on trust.

    WHY only placement here and not the full REQUIRED_MODULES set: bench_verdict()'s contract (its five declared
    modules exact, a missing dependency list "returned, never cached") is pinned by
    tests/test_dashboard_adapter_grasping.py::BridgeTest, outside this lane. What it now refuses is a module or
    dependency outside the bench's src/grasp_bench, which it used to accept and cache.
    """

    def paths(self, bench: Path, cache: Path) -> grasp_bench_bridge.BenchPaths:
        code = bench / "src" / "grasp_bench"
        return grasp_bench_bridge.BenchPaths(
            python=str(bench / ".venv" / "bin" / "python"), ledger=str(bench / "out" / "ledger" / "runs.jsonl"),
            attestations=str(bench / "out" / "ledger" / "attestations.jsonl"), gallery_py=str(code / "gallery.py"),
            ledger_py=str(code / "ledger.py"), curriculum_py=str(code / "curriculum.py"),
            runner_py=str(code / "runner.py"), contracts_py=str(code / "contracts.py"), cache_dir=str(cache))

    def test_a_module_or_dependency_outside_the_package_is_refused_and_never_cached(self) -> None:
        for label, rewrite in (("registry imported from outside src/grasp_bench", move_module("registry")),
                               ("a dependency outside src/grasp_bench", add_outside_dependency)):
            with self.subTest(label), tempfile.TemporaryDirectory() as folder:
                bench = make_bench(Path(folder) / "grasp_bench")
                cache = Path(folder) / "cache"
                doctored = Doctored(rewrite, (bench / "src" / "grasp_bench").resolve())
                with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=doctored):
                    result = grasp_bench_bridge.bench_verdict(self.paths(bench, cache), {"T1": ["r0", "r1"]})
                self.assertFalse(result.ok, f"{label}: accepted")
                self.assertTrue(result.reason)
                self.assertFalse((cache / grasp_bench_bridge.CACHE_NAME).exists(), f"{label}: cached")
                honest = grasp_bench_bridge.bench_verdict(self.paths(bench, cache), {"T1": ["r0", "r1"]})
                self.assertTrue(honest.ok, f"{label}: {honest.reason}")


if __name__ == "__main__":
    unittest.main()
