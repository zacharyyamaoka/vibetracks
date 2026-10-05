"""verdict() of vibetracks.benches.grasp_bench_bridge: the one reader of the grasp bench's verdict (grasp-bench-verdict/2)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibetracks.benches import grasp_bench_bridge

LIVE_BENCH = Path("/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/policy/grasp_bench")
LIVE_PYTHON = LIVE_BENCH / ".venv" / "bin" / "python"

REPORT_BY_THE_BENCH_ITSELF = r'''
import json
from grasp_bench import curriculum, gallery
from grasp_bench.ledger import Ledger
runs = Ledger("out/ledger").load_runs()
heads = gallery.headline_runs(runs)
print(json.dumps({"beaten": sorted(env for env in curriculum.GATES if gallery.env_verdict(env, heads)[0]),
                  "rows": len(runs), "headline": sorted(heads)}))
'''


class WithoutABenchTest(unittest.TestCase):
    def test_a_bench_without_a_venv_answers_with_an_error_and_empty_maps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = grasp_bench_bridge.verdict(folder, cache_dir=Path(folder) / "cache")
        self.assertEqual(result["schema"], "grasp-bench-verdict/2")
        self.assertTrue(result["error"])
        self.assertEqual((result["envs"], result["runs"], result["headline"]), ({}, {}, {}))
        self.assertEqual(set(result), {"schema", "envs", "runs", "headline", "bench_head", "error"})

    def test_a_venv_with_no_ledger_is_an_error_too(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            python = Path(folder) / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("")
            result = grasp_bench_bridge.verdict(folder, cache_dir=Path(folder) / "cache")
        self.assertIn("ledger missing", result["error"])
        self.assertEqual(result["envs"], {})


class StandaloneTest(unittest.TestCase):
    def test_the_module_imports_nothing_from_the_dashboard(self) -> None:
        # WHY a fresh interpreter: sys.modules here is polluted by every other test in the run.
        code = ("import sys; import vibetracks.benches.grasp_bench_bridge; "
                "print([m for m in sys.modules if m.startswith('vibetracks.dashboard')])")
        done = subprocess.run(["python3", "-c", code], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).resolve().parent.parent)
        self.assertEqual(done.stdout.strip(), "[]")
        source = Path(grasp_bench_bridge.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(from|import)\s+(vibetracks|\.)")


@unittest.skipUnless(LIVE_PYTHON.exists(), f"no bench venv at {LIVE_PYTHON}")
class LiveBenchTest(unittest.TestCase):
    def test_the_verdict_is_what_the_bench_reports_itself(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "cache"
            result = grasp_bench_bridge.verdict(LIVE_BENCH, cache_dir=cache)
            self.assertIsNone(result["error"], result["error"])

            env = {name: value for name, value in os.environ.items()
                   if name not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
            done = subprocess.run([str(LIVE_PYTHON), "-I", "-c", REPORT_BY_THE_BENCH_ITSELF], cwd=LIVE_BENCH, env=env,
                                  capture_output=True, text=True, check=True)
            own = json.loads(done.stdout.strip().splitlines()[-1])
            self.assertEqual(sorted(env_id for env_id, env_row in result["envs"].items() if env_row["beaten"]),
                             own["beaten"])
            self.assertEqual(sorted(result["headline"]), own["headline"])
            self.assertEqual(len(result["runs"]), own["rows"])
            self.assertTrue(result["runs"])
            for run_id, run in result["runs"].items():
                self.assertIsInstance(run["gap"], str, run_id)
                self.assertIsInstance(run["frozen"], bool)
                self.assertIsInstance(run["privileged"], bool)
            for env_row in result["envs"].values():
                self.assertTrue(env_row["best_run"] is None or env_row["best_run"] in result["runs"])
            self.assertTrue(all(run_id in result["runs"] for run_id in result["headline"].values()))

            self.assertTrue((cache / grasp_bench_bridge.VERDICT_CACHE_NAME).is_file())
            again = grasp_bench_bridge.verdict(LIVE_BENCH, cache_dir=cache)
            self.assertEqual(again, result)


if __name__ == "__main__":
    unittest.main()
