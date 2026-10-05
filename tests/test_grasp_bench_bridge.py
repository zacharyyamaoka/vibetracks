"""verdict() of vibetracks.benches.grasp_bench_bridge: the one reader of the grasp bench's verdict (grasp-bench-verdict/2)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_grasp_bench_bridge_deps import ROWS, Counting, make_bench
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


def raw_lines(runs_jsonl: Path) -> list[bytes]:
    """The ledger's non-blank lines as raw bytes without their one terminator, in file order (what line_sha256 hashes)."""

    return [line for line in runs_jsonl.read_bytes().splitlines() if line.strip()]


def digests(runs_jsonl: Path) -> list[str]:
    return [hashlib.sha256(line).hexdigest() for line in raw_lines(runs_jsonl)]


# A concurrent writer: every load_runs() first appends a new row to the bench's REAL runs.jsonl (the path is baked in
# per test), whatever root its own Ledger reads. The bridge must judge and digest the one snapshot it read, unmoved.
GROWING_LEDGER = '''
import json, os
from types import SimpleNamespace

from . import contracts

REAL_RUNS = __REAL_RUNS__


class Ledger:
    def __init__(self, root):
        self.root = root
        self.attestations_path = os.path.join(root, "attestations.jsonl")
        self.runs_path = os.path.join(root, "runs.jsonl")

    def load_runs(self):
        with open(REAL_RUNS, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"run_id": "grown", "cell_id": "m@toy/a", "model": "m", "env": "toy/a",
                                     "value": 0.99, "ci_lo": 0.98, "n": 10, "started_at": "t"}) + "\\n")
        with open(self.runs_path, encoding="utf-8") as handle:
            return [SimpleNamespace(**json.loads(line)) for line in handle if line.strip()]
'''

# A bench whose parser is not line-for-line (a newer reader that keeps only the last row of a re-used run_id): the
# bridge cannot say which line a run came from, so it must refuse rather than pair a digest by position.
DEDUPLICATING_LEDGER = '''
import json, os
from types import SimpleNamespace

from . import contracts


class Ledger:
    def __init__(self, root):
        self.root = root
        self.attestations_path = os.path.join(root, "attestations.jsonl")
        self.runs_path = os.path.join(root, "runs.jsonl")

    def load_runs(self):
        with open(self.runs_path, encoding="utf-8") as handle:
            rows = {}
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    rows.pop(row["run_id"], None)
                    rows[row["run_id"]] = row
        return [SimpleNamespace(**row) for row in rows.values()]
'''


class RowDigestTest(unittest.TestCase):
    """line_sha256: the digest of the ledger row's exact bytes, taken in the bench subprocess beside the judgement."""

    def verdict(self, bench: Path, cache: Path) -> dict:
        result = grasp_bench_bridge.verdict(bench, cache_dir=cache)
        self.assertIsNone(result["error"], result["error"])
        return result

    def test_every_run_carries_the_sha256_of_its_raw_ledger_line(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            result = self.verdict(bench, Path(folder) / "cache")
            self.assertEqual(result["schema"], "grasp-bench-verdict/2")
            expected = digests(bench / "out" / "ledger" / "runs.jsonl")
            self.assertEqual(len(expected), len(ROWS))
            self.assertEqual({run_id: run["line_sha256"] for run_id, run in result["runs"].items()},
                             {str(index): digest for index, digest in enumerate(expected)})

    def test_blank_lines_and_crlf_do_not_misalign_or_leak_into_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            first, second = (json.dumps(row).encode() for row in ROWS)
            runs_jsonl.write_bytes(b"\r\n" + first + b"\r\n\r\n" + second + b"\r\n")
            result = self.verdict(bench, Path(folder) / "cache")
            # WHY by hand and not via raw_lines: the CRLF is a terminator and is not hashed, a blank line is not a row.
            self.assertEqual(result["runs"]["0"]["line_sha256"], hashlib.sha256(first).hexdigest())
            self.assertEqual(result["runs"]["1"]["line_sha256"], hashlib.sha256(second).hexdigest())
            self.assertEqual(len(result["runs"]), 2)

    def test_rows_that_agree_on_started_at_env_and_model_but_differ_in_content_get_different_digests(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            twin = dict(ROWS[0], run_id="r0-twin", value=0.71, notes="re-measured")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            runs_jsonl.write_text("".join(json.dumps(row) + "\n" for row in (ROWS[0], twin)), encoding="utf-8")
            result = self.verdict(bench, Path(folder) / "cache")
            first, second = result["runs"]["0"], result["runs"]["1"]
            for field in ("started_at", "env", "model"):
                self.assertEqual(first[field], second[field])
            self.assertNotEqual(first["line_sha256"], second["line_sha256"])

    def test_a_whitespace_only_difference_in_the_raw_line_changes_the_digest(self) -> None:
        # WHY: the digest is of the exact bytes, not of the parsed row, so a re-serialised row is a different row.
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            compact = self.verdict(bench, Path(folder) / "cache-a")["runs"]["0"]["line_sha256"]
            runs_jsonl.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in ROWS), encoding="utf-8")
            self.assertNotEqual(self.verdict(bench, Path(folder) / "cache-b")["runs"]["0"]["line_sha256"], compact)

    def test_an_old_cache_entry_without_the_field_is_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            cache = Path(folder) / "cache"
            counter = Counting()
            with mock.patch.object(grasp_bench_bridge.subprocess, "run", side_effect=counter):
                first = self.verdict(bench, cache)
                self.assertEqual(self.verdict(bench, cache), first)
                self.assertEqual(counter.runs, 1, "an entry with the field is a hit")
                file = cache / grasp_bench_bridge.VERDICT_CACHE_NAME
                entry = json.loads(file.read_text(encoding="utf-8"))
                for run in entry["doc"]["runs"].values():
                    del run["line_sha256"]
                file.write_text(json.dumps(entry), encoding="utf-8")
                again = self.verdict(bench, cache)
            self.assertEqual(counter.runs, 2, "an entry written before line_sha256 existed must be recomputed")
            self.assertEqual(again, first)
            self.assertEqual(grasp_bench_bridge.VERDICT_CACHE_NAME, "verdict-v3.json")

    def test_a_ledger_that_keeps_growing_during_the_call_is_judged_as_the_one_snapshot_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            snapshot = digests(runs_jsonl)
            (bench / "src" / "grasp_bench" / "ledger.py").write_text(
                GROWING_LEDGER.replace("__REAL_RUNS__", repr(str(runs_jsonl))), encoding="utf-8")
            result = self.verdict(bench, Path(folder) / "cache")
            self.assertGreater(len(digests(runs_jsonl)), len(snapshot), "the writer must have appended during the call")
            self.assertEqual([result["runs"][str(index)]["line_sha256"] for index in range(len(result["runs"]))],
                             snapshot)
            self.assertNotIn("grown", json.dumps(result))

    def test_a_parser_that_is_not_line_for_line_is_an_error_with_nothing_to_misread(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bench = make_bench(Path(folder) / "grasp_bench")
            (bench / "src" / "grasp_bench" / "ledger.py").write_text(DEDUPLICATING_LEDGER, encoding="utf-8")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            runs_jsonl.write_text("".join(json.dumps(row) + "\n" for row in (ROWS[0], ROWS[1], dict(ROWS[0], value=0.1))),
                                  encoding="utf-8")
            cache = Path(folder) / "cache"
            result = grasp_bench_bridge.verdict(bench, cache_dir=cache)
            self.assertEqual(result["error"], grasp_bench_bridge.LEDGER_UNALIGNED)
            self.assertEqual((result["envs"], result["runs"], result["headline"]), ({}, {}, {}))
            self.assertFalse((cache / grasp_bench_bridge.VERDICT_CACHE_NAME).exists())


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

            # WHY read after the call and compare only indices that existed: the ledger is append-only and live.
            lines = raw_lines(LIVE_BENCH / "out" / "ledger" / "runs.jsonl")
            checked = 0
            for run_id, run in result["runs"].items():
                if int(run_id) < len(lines):
                    self.assertEqual(run["line_sha256"], hashlib.sha256(lines[int(run_id)]).hexdigest(), run_id)
                    checked += 1
            self.assertEqual(checked, len(result["runs"]), "every judged row was still in the file")

            self.assertTrue((cache / grasp_bench_bridge.VERDICT_CACHE_NAME).is_file())
            again = grasp_bench_bridge.verdict(LIVE_BENCH, cache_dir=cache)
            self.assertEqual(again, result)


if __name__ == "__main__":
    unittest.main()
