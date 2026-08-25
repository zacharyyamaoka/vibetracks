from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vibetracks import (
    RevisionConflict,
    VibeTracksError,
    append_feature_comment,
    create_feature,
    load_project,
    update_feature_dependencies,
)
from vibetracks.edits import replace_frontmatter_entry
from vibetracks.notes import parse_frontmatter


class FrontmatterSpliceTests(unittest.TestCase):
    def test_scalar_replacement_preserves_other_keys_verbatim(self) -> None:
        original = "---\ntitle: Keep  me\nvibe-status: ready\nweird:   spacing\n---\n\nBody.\n"
        updated = replace_frontmatter_entry(original, "vibe-status", "done")
        self.assertIn("vibe-status: done", updated)
        self.assertIn("title: Keep  me", updated)
        self.assertIn("weird:   spacing", updated)
        self.assertIn("Body.", updated)

    def test_list_replacement_consumes_the_whole_block(self) -> None:
        original = (
            "---\nvibe-depends-on:\n  - '[[Old one]]'\n  - '[[Old two]]'\nafter: kept\n---\n\nBody.\n"
        )
        updated = replace_frontmatter_entry(original, "vibe-depends-on", ["[[New]]"])
        self.assertNotIn("Old one", updated)
        self.assertNotIn("Old two", updated)
        self.assertIn("[[New]]", updated)
        self.assertIn("after: kept", updated)

    def test_zero_indent_list_items_belong_to_the_key(self) -> None:
        original = "---\nvibe-depends-on:\n- '[[Old]]'\nafter: kept\n---\nBody.\n"
        updated = replace_frontmatter_entry(original, "vibe-depends-on", [])
        self.assertNotIn("Old", updated)
        self.assertIn("vibe-depends-on: []", updated)
        self.assertIn("after: kept", updated)

    def test_blank_lines_inside_a_block_list_stay_in_the_span(self) -> None:
        # Regression: the span used to stop at the blank line, leaving a
        # stranded "  - item" that made the whole note unparseable.
        original = (
            "---\nvibe-depends-on:\n  - '[[Old one]]'\n\n  - '[[Old two]]'\nafter: kept\n---\nBody.\n"
        )
        updated = replace_frontmatter_entry(original, "vibe-depends-on", ["[[New]]"])
        self.assertNotIn("Old one", updated)
        self.assertNotIn("Old two", updated)
        self.assertIn("after: kept", updated)
        parse_frontmatter(updated)  # must stay valid YAML

    def test_comment_lines_inside_a_block_list_stay_in_the_span(self) -> None:
        # Regression: a zero-indent comment used to end the span, so deleted
        # entries after it silently re-merged into the list.
        original = (
            "---\nvibe-depends-on:\n# pinned\n- '[[Old]]'\nafter: kept\n---\nBody.\n"
        )
        updated = replace_frontmatter_entry(original, "vibe-depends-on", [])
        self.assertNotIn("Old", updated)
        self.assertIn("after: kept", updated)
        frontmatter, _ = parse_frontmatter(updated)
        self.assertEqual(frontmatter["vibe-depends-on"], [])

    def test_trailing_comment_before_next_key_is_preserved(self) -> None:
        original = "---\nvibe-status: ready\n\n# belongs to other\nother: x\n---\nBody.\n"
        updated = replace_frontmatter_entry(original, "vibe-status", "done")
        self.assertIn("# belongs to other", updated)
        self.assertIn("other: x", updated)

    def test_duplicate_keys_are_collapsed_to_one(self) -> None:
        # Regression: only the first duplicate was rewritten, and YAML's
        # last-wins reading kept returning the stale value.
        original = "---\nvibe-status: ready\nmiddle: kept\nvibe-status: done\n---\nBody.\n"
        updated = replace_frontmatter_entry(original, "vibe-status", "review")
        frontmatter, _ = parse_frontmatter(updated)
        self.assertEqual(frontmatter["vibe-status"], "review")
        self.assertEqual(updated.count("vibe-status"), 1)
        self.assertIn("middle: kept", updated)

    def test_missing_key_is_appended_and_missing_frontmatter_created(self) -> None:
        appended = replace_frontmatter_entry("---\na: 1\n---\nBody.\n", "vibe-status", "ready")
        self.assertIn("a: 1", appended)
        self.assertIn("vibe-status: ready", appended)
        created = replace_frontmatter_entry("Just a body.\n", "vibe-status", "ready")
        self.assertTrue(created.startswith("---\nvibe-status: ready\n---\n"))
        self.assertIn("Just a body.", created)


class TrackFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "features").mkdir()
        self.descriptor = self.root / "Project.vibetrack"
        self.descriptor.write_text(
            "vibetracks:\n"
            "  title: Fixture\n"
            "  source: features\n"
            "  idPrefix: VT\n"
            "  statuses: [ready, running, review, done]\n"
            "  areas:\n"
            "    backend: Server side work\n",
            encoding="utf-8",
        )
        (self.root / "features" / "VT-001 - First.md").write_text(
            "---\nvibe-id: VT-001\nvibe-status: done\n---\n# First\n",
            encoding="utf-8",
        )
        (self.root / "features" / "VT-002 - Second.md").write_text(
            "---\nvibe-id: VT-002\nvibe-status: ready\nvibe-areas: [frontend]\n---\n# Second\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()


class DependencyUpdateTests(TrackFixture):
    def test_dependencies_serialize_as_wikilinks_and_keep_unresolved_verbatim(self) -> None:
        project = load_project(self.descriptor)
        item = project.item_by_id("VT-002")
        assert item is not None
        updated = update_feature_dependencies(
            self.descriptor, "VT-002", ["VT-001", "not-a-feature"], item.revision
        )
        self.assertEqual(updated.dependencies, ["VT-001"])
        self.assertEqual(updated.unresolved_dependencies, ["not-a-feature"])
        content = (self.root / "features" / "VT-002 - Second.md").read_text(encoding="utf-8")
        self.assertIn("[[VT-001 - First]]", content)
        self.assertIn("not-a-feature", content)

    def test_self_dependency_is_dropped_not_fatal(self) -> None:
        # A stray hand-written self-edge must not brick subsequent edits: the
        # full-list resend just drops it.
        project = load_project(self.descriptor)
        item = project.item_by_id("VT-002")
        assert item is not None
        updated = update_feature_dependencies(
            self.descriptor, "VT-002", ["VT-002", "VT-001"], item.revision
        )
        self.assertEqual(updated.dependencies, ["VT-001"])
        self.assertNotIn("VT-002", updated.unresolved_dependencies)

    def test_stale_revision_conflicts(self) -> None:
        with self.assertRaises(RevisionConflict):
            update_feature_dependencies(self.descriptor, "VT-002", ["VT-001"], "0" * 16)


class CommentTests(TrackFixture):
    def test_comment_appends_a_quote_callout(self) -> None:
        project = load_project(self.descriptor)
        item = project.item_by_id("VT-002")
        assert item is not None
        append_feature_comment(self.descriptor, "VT-002", "Looks good.\nShip it.", item.revision)
        content = (self.root / "features" / "VT-002 - Second.md").read_text(encoding="utf-8")
        self.assertIn("> [!quote] 👦 Feedback —", content)
        self.assertIn("> Looks good.", content)
        self.assertIn("> Ship it.", content)

    def test_empty_comment_is_rejected(self) -> None:
        project = load_project(self.descriptor)
        item = project.item_by_id("VT-002")
        assert item is not None
        with self.assertRaises(VibeTracksError):
            append_feature_comment(self.descriptor, "VT-002", "   ", item.revision)


class CreateFeatureTests(TrackFixture):
    def test_create_assigns_next_id_marker_and_dependencies(self) -> None:
        item = create_feature(
            self.descriptor,
            "Third thing",
            areas=["backend"],
            depends_on=["VT-001"],
            description="A third feature.",
        )
        self.assertEqual(item.id, "VT-003")
        self.assertEqual(item.status, "ready")
        self.assertEqual(item.dependencies, ["VT-001"])
        content = (self.root / "features" / "VT-003 - Third thing.md").read_text(encoding="utf-8")
        self.assertIn("vibe-track: feature", content)
        self.assertIn("# Third thing", content)
        project = load_project(self.descriptor)
        self.assertEqual(len(project.items), 3)

    def test_filename_strips_hostile_characters(self) -> None:
        item = create_feature(self.descriptor, 'Fix: the "bad" <path>?')
        self.assertTrue(Path(item.absolute_path).name.startswith("VT-003 - "))
        for character in '<>:"/\\|?*':
            self.assertNotIn(character, Path(item.absolute_path).name.replace("VT-003 - ", "", 1))

    def test_area_catalog_unions_descriptor_and_items(self) -> None:
        project = load_project(self.descriptor)
        catalog = {entry["name"]: entry["description"] for entry in project.area_catalog()}
        self.assertEqual(catalog["backend"], "Server side work")
        self.assertEqual(catalog["frontend"], "")


class ResilienceTests(TrackFixture):
    def test_malformed_note_is_skipped_and_surfaced_not_fatal(self) -> None:
        (self.root / "features" / "Broken.md").write_text(
            "---\nvibe-id: [unclosed\n---\n# Broken\n", encoding="utf-8"
        )
        project = load_project(self.descriptor)
        self.assertEqual(len(project.items), 2)
        self.assertEqual(len(project.problems), 1)
        self.assertIn("Broken.md", project.problems[0]["path"])

    def test_a_title_cannot_hijack_another_features_id(self) -> None:
        (self.root / "features" / "ZZ-Meta.md").write_text(
            "---\nvibe-id: VT-009\nvibe-status: ready\n---\n# VT-001\n", encoding="utf-8"
        )
        project = load_project(self.descriptor)
        resolved = project.resolve_reference("VT-001")
        assert resolved is not None
        self.assertEqual(resolved.id, "VT-001")

    def test_next_id_counts_marker_filtered_and_filename_ids(self) -> None:
        # A note whose typoed marker hides it from the projection still owns
        # its id — creating must not mint VT-003 twice.
        marked = self.root / "Marked.vibetrack"
        marked.write_text(
            "vibetracks:\n  source: features\n  marker: {property: vibe-track, value: feature}\n",
            encoding="utf-8",
        )
        (self.root / "features" / "VT-003 - Hidden.md").write_text(
            "---\nvibe-track: Feature\nvibe-id: VT-003\n---\n# Hidden\n", encoding="utf-8"
        )
        item = create_feature(marked, "Fresh")
        self.assertEqual(item.id, "VT-004")

    def test_declared_status_vocabulary_is_not_alias_mapped(self) -> None:
        descriptor = self.root / "Todo.vibetrack"
        descriptor.write_text(
            "vibetracks:\n  source: features\n  statuses: [todo, doing, done]\n",
            encoding="utf-8",
        )
        (self.root / "features" / "T1.md").write_text(
            "---\nvibe-id: T-1\nvibe-status: todo\n---\n# T1\n", encoding="utf-8"
        )
        project = load_project(descriptor)
        self.assertIn("todo", project.statuses)
        item = project.item_by_id("T-1")
        assert item is not None
        self.assertEqual(item.status, "todo")

    def test_dependency_wikilink_with_heading_anchor_resolves(self) -> None:
        project = load_project(self.descriptor)
        item = project.item_by_id("VT-002")
        assert item is not None
        updated = update_feature_dependencies(
            self.descriptor, "VT-002", ["[[VT-001 - First#Decision]]"], item.revision
        )
        self.assertEqual(updated.dependencies, ["VT-001"])


if __name__ == "__main__":
    unittest.main()
