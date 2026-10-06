"""Codex round 7 (2026-10-05): the grasping live stamp covers everything the bench's verdict depends on."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vibetracks.roadmap import api


class A02BenchInterpreterTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bench = Path(temporary.name) / "grasp_bench"
        package = self.bench / "src" / "grasp_bench"
        (package / "envs").mkdir(parents=True)
        for name in ("curriculum.py", "gallery.py", "ledger.py", "registry.py", "envs/toy.py"):
            (package / name).write_text("X = 1\n")
        (self.bench / ".venv" / "bin").mkdir(parents=True)
        (self.bench / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
        (self.bench / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (self.bench / "out" / "ledger").mkdir(parents=True)
        (self.bench / "out" / "ledger" / "runs.jsonl").write_text("{}\n")
        self.sources = {"grasp_bench_dir": str(self.bench)}

    def test_the_stamp_covers_the_venv_interpreter_and_every_module(self) -> None:
        inputs = {str(path.relative_to(self.bench)) for path in api._grasping_inputs(self.sources)}
        self.assertLessEqual({".venv/bin/python", ".venv/pyvenv.cfg", "src/grasp_bench/envs/toy.py",
                              "src/grasp_bench/registry.py", "out/ledger/runs.jsonl", "out/ledger/attestations.jsonl"}, inputs)

    def test_codex_reproduction_a_removed_venv_moves_the_stamp(self) -> None:
        before = api._file_stamps(api._grasping_inputs(self.sources))
        (self.bench / ".venv" / "bin" / "python").unlink()
        self.assertNotEqual(before, api._file_stamps(api._grasping_inputs(self.sources)))

    def test_an_edited_module_the_verdict_imports_moves_the_stamp(self) -> None:
        before = api._file_stamps(api._grasping_inputs(self.sources))
        (self.bench / "src" / "grasp_bench" / "envs" / "toy.py").write_text("X = 22\n")
        self.assertNotEqual(before, api._file_stamps(api._grasping_inputs(self.sources)))
