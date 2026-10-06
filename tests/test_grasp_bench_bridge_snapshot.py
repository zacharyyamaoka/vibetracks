"""verdict() judges and digests ONE byte snapshot of runs.jsonl, through the REAL bench's parser (Codex r2, finding 4).

The fault: the bridge used to read runs.jsonl as bytes, then let ``Ledger.load_runs()`` read it again, and paired the
two with a check that compared only the keys present in the raw row. A legacy sparse row (no ``value``, no
``env_options``, no ``schema_version``) that a writer enriched in place between the two reads still "aligned", so the
verdict returned the digest of the OLD bytes beside the frozen/beaten judgement of the NEW row.

WHY the real bench and not the fake one: the fault lives in how ``CellRun.from_dict`` fills absent fields (value None,
schema_version inferred 0) and in how the real gallery judges that. So this test copies the live grasp_bench package
verbatim into a temp bench, runs it on the live venv's interpreter and site-packages, and adds only a hook to the
copied ledger.py that plays the concurrent writer: the first ``load_runs()`` rewrites the bench's real runs.jsonl with
the enriched row before parsing. The expected answer is the bench's own judgement of the bytes the digest names.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibetracks.benches import grasp_bench_bridge

LIVE_BENCH = Path("/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/policy/grasp_bench")
LIVE_PYTHON = LIVE_BENCH / ".venv" / "bin" / "python"

# A real frozen row that beats toy/x (live ledger row 97 on 2026-10-05, artifacts emptied), and its legacy sparse form.
ENRICHED = {
    "run_id": "20261005T054725Z_M0.masked_toy_x_c02c44", "cell_id": "M0.masked@toy/x", "model": "M0.masked",
    "env": "toy/x", "tier": 1, "protocol": {"name": "eval-2000", "seed": 20261004, "episodes": 2000, "split": "test",
                                            "k": 1},
    "train_summary": {}, "env_options": {}, "env_info": {},
    "model_info": {"input": "height", "output": "planar", "notes": "bam_grasp's masked random; the honest floor in clutter.",
                   "settings": None},
    "n": 2000, "metric": "top1_success", "value": 1.0, "ci_lo": 0.9980829527187469, "ci_hi": 1.0, "ap": None,
    "ap_ci_lo": None, "ap_ci_hi": None, "precision_at_1": None, "latency_ms_p50": 0.0853575038490817,
    "latency_ms_p95": 0.09482150708208792, "lost_in_conversion": 0, "git_sha": "9157d468610961fd3c981dfa16711ab06b6005d6",
    "git_dirty": False, "started_at": "2026-10-05T05:47:25+00:00", "duration_s": 0.883, "notes": "", "artifacts": {},
    "schema_version": 2, "custom_factory": False,
}
ENRICHED_ONLY = ("env_options", "env_info", "value", "ci_lo", "ci_hi", "schema_version", "custom_factory")
SPARSE = {key: value for key, value in ENRICHED.items() if key not in ENRICHED_ONLY}

# The concurrent writer, appended to the COPIED ledger.py only: the first load_runs() in any process rewrites the
# bench's real runs.jsonl (enriching the legacy row in place), then parses whatever its own Ledger points at.
RACE_HOOK = '''

# ---- test hook (tests/test_grasp_bench_bridge_snapshot.py): a writer that enriches a row between two reads
import os as _race_os

_RACE_RUNS = {runs!r}
_RACE_MARK = {mark!r}
_RACE_BYTES = {data!r}
_race_original_load_runs = Ledger.load_runs


def _race_load_runs(self):
    if not _race_os.path.exists(_RACE_MARK):
        open(_RACE_MARK, "w").close()
        with open(_RACE_RUNS, "wb") as handle:
            handle.write(_RACE_BYTES)
    return _race_original_load_runs(self)


Ledger.load_runs = _race_load_runs
'''

# The bench's own judgement of one ledger root, by its own code, nothing from the bridge.
OWN_JUDGEMENT = r'''
import json, sys
from grasp_bench import curriculum, gallery
from grasp_bench.ledger import Ledger
runs = Ledger(sys.argv[1]).load_runs()
heads = gallery.headline_runs(runs)
print(json.dumps({"runs": [{"frozen": bool(gallery.is_frozen_protocol(run)), "gap": str(gallery.provenance_gap(run))}
                           for run in runs],
                  "beaten": sorted(env for env in curriculum.GATES if gallery.env_verdict(env, heads)[0])}))
'''


def _line(row: dict) -> bytes:
    return json.dumps(row, separators=(",", ":")).encode("utf-8")


def make_real_bench(root: Path, hook: str = "") -> Path:
    """A temp bench holding a verbatim copy of the live grasp_bench package, on the live venv's interpreter and libs.

    WHY a fresh venv with a .pth and not a symlink to the live .venv: the live venv's editable install points at the
    live src, so the copy (and its hook) would never be imported. Here the copy comes first on sys.path and the live
    site-packages (numpy, bam_grasp, ...) are added after it with site.addsitedir, which also runs their .pth files.
    """

    package = root / "src" / "grasp_bench"
    shutil.copytree(LIVE_BENCH / "src" / "grasp_bench", package, ignore=shutil.ignore_patterns("__pycache__"))
    if hook:
        with open(package / "ledger.py", "a", encoding="utf-8") as handle:
            handle.write(hook)
    live_site = next((LIVE_BENCH / ".venv" / "lib").glob("python3*/site-packages"))
    subprocess.run([os.path.realpath(LIVE_PYTHON), "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    site = root / ".venv" / "lib" / live_site.parent.name / "site-packages"
    (site / "grasp_bench_copy.pth").write_text(
        f"{root / 'src'}\nimport site; site.addsitedir({str(live_site)!r})\n", encoding="utf-8")
    (root / "out" / "ledger").mkdir(parents=True)
    return root


def own_judgement(bench: Path, ledger_root: Path) -> dict:
    env = {name: value for name, value in os.environ.items()
           if name not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
    done = subprocess.run([str(bench / ".venv" / "bin" / "python"), "-I", "-c", OWN_JUDGEMENT, str(ledger_root)],
                          cwd=bench, env=env, capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


@unittest.skipUnless(LIVE_PYTHON.exists(), f"no bench venv at {LIVE_PYTHON}")
class SnapshotAlignmentTest(unittest.TestCase):
    def test_a_sparse_row_enriched_in_place_during_the_call_cannot_pair_old_bytes_with_a_new_judgement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            runs_jsonl = folder / "bench" / "out" / "ledger" / "runs.jsonl"
            sparse_bytes = _line(SPARSE) + b"\n"
            hook = RACE_HOOK.format(runs=str(runs_jsonl), mark=str(folder / "rewritten"),
                                    data=_line(ENRICHED) + b"\n")
            bench = make_real_bench(folder / "bench", hook)
            runs_jsonl.write_bytes(sparse_bytes)

            # One-row ledgers of each form, judged by the bench itself AFTER the call (the hook fires once, so it is
            # spent by then and these reads see exactly the bytes written here).
            for name, row in (("sparse", SPARSE), ("enriched", ENRICHED)):
                (folder / name).mkdir()
                (folder / name / "runs.jsonl").write_bytes(_line(row) + b"\n")

            result = grasp_bench_bridge.verdict(bench, cache_dir=folder / "cache")
            self.assertIsNone(result["error"], result["error"])
            self.assertTrue((folder / "rewritten").exists(), "the writer must have enriched the row during the call")
            self.assertEqual(runs_jsonl.read_bytes(), _line(ENRICHED) + b"\n")

            sparse_own = own_judgement(bench, folder / "sparse")
            enriched_own = own_judgement(bench, folder / "enriched")
            self.assertNotEqual(sparse_own, enriched_own, "the fixture must discriminate the two rows")

            self.assertEqual(len(result["runs"]), 1)
            run = result["runs"]["0"]
            digested = {hashlib.sha256(_line(SPARSE)).hexdigest(): sparse_own,
                        hashlib.sha256(_line(ENRICHED)).hexdigest(): enriched_own}
            self.assertIn(run["line_sha256"], digested, "the digest names neither version of the row")
            own = digested[run["line_sha256"]]
            # WHY these are the assertions: whichever bytes the digest names, the judgement beside it is the bench's
            # own judgement of THOSE bytes. On b53567e the digest named the sparse row and the judgement the enriched.
            self.assertEqual({"frozen": run["frozen"], "gap": run["gap"]}, own["runs"][0])
            self.assertEqual(sorted(env for env, row in result["envs"].items() if row["beaten"]), own["beaten"])

    def test_the_real_bench_agrees_with_itself_on_a_crlf_ledger_with_blank_and_torn_lines(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bench = make_real_bench(folder / "bench")
            runs_jsonl = bench / "out" / "ledger" / "runs.jsonl"
            lines = [_line(SPARSE), _line(ENRICHED)]
            runs_jsonl.write_bytes(b"\r\n" + lines[0] + b"\r\n   \r\n" + lines[1] + b"\r\n" + b'{"run_id": "torn')
            result = grasp_bench_bridge.verdict(bench, cache_dir=folder / "cache")
            self.assertIsNone(result["error"], result["error"])
            own = own_judgement(bench, runs_jsonl.parent)
            self.assertEqual(len(result["runs"]), 2)
            for index, line in enumerate(lines):
                run = result["runs"][str(index)]
                self.assertEqual(run["line_sha256"], hashlib.sha256(line).hexdigest(), index)
                self.assertEqual({"frozen": run["frozen"], "gap": run["gap"]}, own["runs"][index])


if __name__ == "__main__":
    unittest.main()
