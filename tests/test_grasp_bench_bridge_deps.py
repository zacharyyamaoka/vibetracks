"""Both bridge caches re-run the bench when ANY module its verdict imported changes (audit 2026-10-04, finding 2).

WHY a fake bench and not the live one: the live failure was registry.py, a module neither cache watched, moving the
bench's own verdict from 6 beaten envs to 2. A tiny bench whose gallery imports a registry module reproduces exactly
that seam in a second, without touching the real bench's files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.benches import grasp_bench_bridge

FAKE_PACKAGE = {
    "__init__.py": "",
    "registry.py": "THRESHOLD = 0.5\n",
    # WHY this import graph: it is the real bench's (contracts -> grasp, runner -> contracts + stats, gallery ->
    # registry + runner), so the fake imports exactly the module set the bridge requires as witnesses.
    "grasp.py": "",
    "stats.py": "",
    "contracts.py": "from . import grasp\nSCHEMA = 1\n",
    "runner.py": "from . import contracts, stats\n",
    "curriculum.py": "GATES = ('toy/a', 'toy/b')\n",
    "ledger.py": '''
import json, os
from types import SimpleNamespace

from . import contracts  # WHY: like the real ledger, a module the v2 script never names imports another


class Ledger:
    def __init__(self, root):
        self.root = root
        self.attestations_path = os.path.join(root, "attestations.jsonl")
        self.runs_path = os.path.join(root, "runs.jsonl")  # WHY: the bridge reads the very file the Ledger parses

    def load_runs(self):
        with open(self.runs_path, encoding="utf-8") as handle:
            return [SimpleNamespace(**json.loads(line)) for line in handle if line.strip()]
''',
    # WHY the threshold lives in registry.py: the verdict depends on a module only gallery.py names.
    "gallery.py": '''
from . import registry, runner


def is_frozen_protocol(run):
    return True


def _run_privileged(run):
    return False


def provenance_gap(run):
    return ""


def clears_gate(run):
    return run.value >= registry.THRESHOLD


def headline_runs(runs):
    return {run.cell_id: run for run in runs}


def env_verdict(env_id, heads):
    best = max((run for run in heads.values() if run.env == env_id), key=lambda run: run.value, default=None)
    return (best is not None and clears_gate(best)), best


def env_provisional(env_id, heads):
    return False
''',
}
ROWS = [
    {"run_id": "r0", "cell_id": "m@toy/a", "model": "m", "env": "toy/a", "value": 0.7, "ci_lo": 0.6, "n": 10,
     "started_at": "2026-10-04T00:00:00Z", "schema_version": 2},
    {"run_id": "r1", "cell_id": "m@toy/b", "model": "m", "env": "toy/b", "value": 0.2, "ci_lo": 0.1, "n": 10,
     "started_at": "2026-10-04T00:00:00Z", "schema_version": 2},
]


def make_bench(root: Path) -> Path:
    """A grasp_bench folder laid out like the real one: .venv/bin/python, src/grasp_bench, out/ledger/runs.jsonl."""

    package = root / "src" / "grasp_bench"
    package.mkdir(parents=True)
    for name, text in FAKE_PACKAGE.items():
        (package / name).write_text(text, encoding="utf-8")
    ledger = root / "out" / "ledger"
    ledger.mkdir(parents=True)
    (ledger / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in ROWS), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = root / ".venv" / "lib" / version / "site-packages"
    # WHY a .pth: the bridge runs the venv's python with -I (no cwd, no PYTHONPATH), so the package must be installed.
    (site / "grasp_bench_src.pth").write_text(str(root / "src") + "\n", encoding="utf-8")
    return root


def mutate(path: Path, old: str, new: str) -> None:
    """Rewrite one module and move its mtime 2 s on (a same-size, same-second edit could reuse a stale .pyc)."""

    before = path.stat()
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))


class Counting:
    """Counts the bench subprocesses (not git) the bridge starts."""

    def __init__(self) -> None:
        self.runs = 0
        self.real = subprocess.run

    def __call__(self, args, *rest, **kwargs):
        if any(arg in (grasp_bench_bridge.SCRIPT, grasp_bench_bridge.VERDICT_SCRIPT) for arg in args):
            self.runs += 1
        return self.real(args, *rest, **kwargs)


class VerdictV2DependencyTest(unittest.TestCase):
    def test_touching_only_an_imported_module_misses_the_cache_and_recomputes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            cache = Path(folder) / "cache"
            counter = Counting()
            with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=counter):
                first = grasp_bench_bridge.verdict(bench, cache_dir=cache)
                self.assertIsNone(first["error"], first["error"])
                self.assertTrue(first["envs"]["toy/a"]["beaten"])
                self.assertEqual(counter.runs, 1)

                entry = json.loads((cache / grasp_bench_bridge.VERDICT_CACHE_NAME).read_text(encoding="utf-8"))
                recorded = {stamp[0] for stamp in entry["deps"]}
                registry = os.path.realpath(bench / "src" / "grasp_bench" / "registry.py")
                self.assertIn(registry, recorded)
                self.assertIn(os.path.realpath(bench / "src" / "grasp_bench" / "contracts.py"), recorded)

                self.assertEqual(grasp_bench_bridge.verdict(bench, cache_dir=cache), first)
                self.assertEqual(counter.runs, 1, "an unchanged bench must be a cache hit")

                mutate(bench / "src" / "grasp_bench" / "registry.py", "0.5", "0.9")
                second = grasp_bench_bridge.verdict(bench, cache_dir=cache)
                self.assertEqual(counter.runs, 2, "a changed registry.py must be a cache miss")
                self.assertIsNone(second["error"], second["error"])
                self.assertFalse(second["envs"]["toy/a"]["beaten"], "the recomputed verdict uses the new rule")
                self.assertEqual(set(second), {"schema", "envs", "runs", "headline", "bench_head", "error"})

    def test_an_entry_without_recorded_modules_is_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            cache = Path(folder) / "cache"
            counter = Counting()
            with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=counter):
                grasp_bench_bridge.verdict(bench, cache_dir=cache)
                file = cache / grasp_bench_bridge.VERDICT_CACHE_NAME
                entry = json.loads(file.read_text(encoding="utf-8"))
                del entry["deps"]
                file.write_text(json.dumps(entry), encoding="utf-8")
                grasp_bench_bridge.verdict(bench, cache_dir=cache)
            self.assertEqual(counter.runs, 2)

    def test_a_missing_attestations_file_is_keyed_as_absent_and_its_arrival_is_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            cache = Path(folder) / "cache"
            counter = Counting()
            with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=counter):
                grasp_bench_bridge.verdict(bench, cache_dir=cache)
                (bench / "out" / "ledger" / "attestations.jsonl").write_text("{}\n", encoding="utf-8")
                grasp_bench_bridge.verdict(bench, cache_dir=cache)
            self.assertEqual(counter.runs, 2)


class BenchVerdictV1DependencyTest(unittest.TestCase):
    def paths(self, bench: Path, cache: Path) -> grasp_bench_bridge.BenchPaths:
        code = bench / "src" / "grasp_bench"
        return grasp_bench_bridge.BenchPaths(
            python=str(bench / ".venv" / "bin" / "python"), ledger=str(bench / "out" / "ledger" / "runs.jsonl"),
            attestations=str(bench / "out" / "ledger" / "attestations.jsonl"), gallery_py=str(code / "gallery.py"),
            ledger_py=str(code / "ledger.py"), curriculum_py=str(code / "curriculum.py"),
            runner_py=str(code / "runner.py"), contracts_py=str(code / "contracts.py"), cache_dir=str(cache))

    def test_touching_only_an_imported_module_misses_the_cache_and_recomputes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            paths = self.paths(bench, Path(folder) / "cache")
            subsets = {"T1": ["r0", "r1"]}
            first = grasp_bench_bridge.bench_verdict(paths, subsets)
            self.assertTrue(first.ok, first.reason)
            self.assertFalse(first.cached)
            self.assertTrue(first.doc["snapshots"]["T1"]["envs"]["toy/a"]["beaten"])
            self.assertTrue(grasp_bench_bridge.bench_verdict(paths, subsets).cached)

            mutate(bench / "src" / "grasp_bench" / "registry.py", "0.5", "0.9")
            second = grasp_bench_bridge.bench_verdict(paths, subsets)
            self.assertTrue(second.ok, second.reason)
            self.assertFalse(second.cached, "a changed registry.py must be a cache miss")
            self.assertFalse(second.doc["snapshots"]["T1"]["envs"]["toy/a"]["beaten"])
            self.assertTrue(grasp_bench_bridge.bench_verdict(paths, subsets).cached)


if __name__ == "__main__":
    unittest.main()
