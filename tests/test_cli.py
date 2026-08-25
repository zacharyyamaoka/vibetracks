from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from vibetracks.cli import discover_descriptor, main
from vibetracks.errors import VibeTracksError
from vibetracks.scaffold import init_project


class ScaffoldTests(unittest.TestCase):
    def test_init_creates_vibetrack_descriptor_and_starter_feature(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = init_project(raw, title="My Robot")
            self.assertEqual(descriptor.name, "Project.vibetrack")
            self.assertTrue((Path(raw) / "features").is_dir())
            self.assertTrue((Path(raw) / "reports").is_dir())
            notes = list((Path(raw) / "features").glob("*.md"))
            self.assertEqual(len(notes), 1)
            self.assertIn("VT-001", notes[0].name)
            with self.assertRaises(VibeTracksError):
                init_project(raw)

    def test_init_picks_base_inside_an_obsidian_vault(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            (Path(raw) / ".obsidian").mkdir()
            target = Path(raw) / "projects" / "thing"
            descriptor = init_project(target)
            self.assertEqual(descriptor.suffix, ".base")


class DiscoveryTests(unittest.TestCase):
    def test_discovers_in_ancestors_and_one_level_down(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            descriptor = init_project(root, title="Up")
            nested = root / "src" / "deep"
            nested.mkdir(parents=True)
            self.assertEqual(discover_descriptor(nested), descriptor)

            with tempfile.TemporaryDirectory() as sibling_raw:
                sibling = Path(sibling_raw)
                child_descriptor = init_project(sibling / "trackdir", title="Down")
                self.assertEqual(discover_descriptor(sibling), child_descriptor)

    def test_missing_descriptor_reports_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(VibeTracksError) as caught:
                discover_descriptor(Path(raw))
            self.assertIn("vibetracks init", str(caught.exception))

    def test_walk_never_escapes_the_repo_even_from_its_root(self) -> None:
        # Regression: starting AT a repo root used to skip the boundary check
        # and pick up an unrelated descriptor from a parent directory.
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            init_project(home, title="Elsewhere")
            repo = home / "myrepo"
            (repo / ".git").mkdir(parents=True)
            with self.assertRaises(VibeTracksError):
                discover_descriptor(repo)

    def test_init_title_with_colon_stays_valid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = init_project(raw, title="Robots: phase 2")
            from vibetracks import load_project
            self.assertEqual(load_project(descriptor).title, "Robots: phase 2")


class CliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.descriptor = init_project(self.root, title="CLI Track")
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def run_cli(self, *argv: str) -> str:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            main(list(argv))
        return stream.getvalue()

    def test_new_status_comment_inspect_round_trip(self) -> None:
        output = self.run_cli(
            "new", "Wire the encoder", "--area", "hardware", "--depends-on", "VT-001"
        )
        self.assertIn("VT-002", output)

        self.assertIn("VT-002 → running", self.run_cli("status", "VT-002", "running"))
        self.run_cli("comment", "VT-002", "Watch the sign convention.")

        snapshot = json.loads(self.run_cli("inspect", "--json"))
        item = next(entry for entry in snapshot["items"] if entry["id"] == "VT-002")
        self.assertEqual(item["status"], "running")
        self.assertEqual(item["dependencies"], ["VT-001"])
        self.assertIn("Watch the sign convention.", item["body"])
        self.assertIn(
            "hardware", [entry["name"] for entry in snapshot["areaCatalog"]]
        )

    def test_agent_briefing_prints(self) -> None:
        briefing = self.run_cli("agent")
        self.assertIn("dispatcher", briefing.lower())
        self.assertIn("vibetracks serve", briefing)


if __name__ == "__main__":
    unittest.main()
