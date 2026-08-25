from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vibetracks.model import (
    RevisionConflict,
    VibeTracksError,
    load_project,
    update_feature_status,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "pyblocks" / "Project.base"


class ProjectLoadingTests(unittest.TestCase):
    def test_loads_base_compatible_example_and_relations(self) -> None:
        project = load_project(EXAMPLE)
        self.assertEqual(project.title, "Pyblocks development")
        self.assertEqual(len(project.items), 9)
        literal = project.item_by_id("VT-002")
        self.assertIsNotNone(literal)
        assert literal is not None
        self.assertEqual(literal.dependencies, ["VT-001"])
        self.assertEqual(literal.review_packet, "reports/literal-writer-review.html")
        self.assertEqual(literal.preview, "assets/literal-writer-proof.svg")
        self.assertEqual(literal.status, "review")
        envelope = project.item_by_id("VT-001")
        assert envelope is not None
        self.assertIn("VT-002", envelope.dependents)

    def test_vibetrack_extension_uses_same_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "features").mkdir()
            (root / "Project.vibetrack").write_text(
                """filters:\n  and:\n    - note[\"vibe-track\"] == \"feature\"\n    - file.inFolder(\"features\")\nvibetracks:\n  title: Portable\n  source: features\n""",
                encoding="utf-8",
            )
            (root / "features" / "One.md").write_text(
                "---\nvibe-track: feature\nvibe-id: F-1\nvibe-status: in-progress\n---\n# One\n",
                encoding="utf-8",
            )
            project = load_project(root / "Project.vibetrack")
            self.assertEqual(project.title, "Portable")
            self.assertEqual(project.items[0].status, "running")

    def test_marker_filter_excludes_unmarked_notes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "features").mkdir()
            (root / "Project.base").write_text(
                "filters:\n  and:\n    - 'note[\"vibe-track\"] == \"feature\"'\n    - 'file.inFolder(\"features\")'\n",
                encoding="utf-8",
            )
            (root / "features" / "Included.md").write_text(
                "---\nvibe-track: feature\n---\n# Included\n",
                encoding="utf-8",
            )
            (root / "features" / "Ignored.md").write_text("# Ignored\n", encoding="utf-8")
            project = load_project(root / "Project.base")
            self.assertEqual([item.title for item in project.items], ["Included"])

    def test_project_paths_cannot_escape_root(self) -> None:
        project = load_project(EXAMPLE)
        with self.assertRaises(VibeTracksError):
            project.resolve_project_path("../secret.txt")


class StatusUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "features").mkdir()
        (self.root / "Project.vibetrack").write_text(
            "vibetracks:\n  source: features\n  statuses: [ready, review, done]\n",
            encoding="utf-8",
        )
        self.note = self.root / "features" / "Feature.md"
        self.note.write_text(
            "---\ntitle: Keep formatting\nvibe-id: F-1\nvibe-status: review\ncustom-field: untouched\n---\n\n# Body\n\nHuman content.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_atomic_revision_fenced_status_update(self) -> None:
        descriptor = self.root / "Project.vibetrack"
        before = load_project(descriptor).item_by_id("F-1")
        assert before is not None
        after = update_feature_status(descriptor, "F-1", "done", before.revision)
        content = self.note.read_text(encoding="utf-8")
        self.assertEqual(after.status, "done")
        self.assertNotEqual(after.revision, before.revision)
        self.assertIn("vibe-status: done", content)
        self.assertIn("custom-field: untouched", content)
        self.assertIn("Human content.", content)
        with self.assertRaises(RevisionConflict):
            update_feature_status(descriptor, "F-1", "ready", before.revision)


if __name__ == "__main__":
    unittest.main()
