"""The work-track registry (vibetracks/dashboard/registry.py) and its rename.

    python3 -m unittest tests/test_dashboard_registry.py      (from the repo root)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard import registry
from vibetracks.errors import RevisionConflict, UnknownFeature, VibeTracksError
from vibetracks.notes import first_paragraph, note_revision

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"

DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "worktrack"'
    - 'file.inFolder("tracks")'
vibetracks:
  version: 1
  id: work-tracks
  title: Work tracks
  vaultRoot: .
  source: tracks
  statuses: [running, paused, archived]
"""


def note(track_id: str, title: str, *, priority: object = 1, status: str = "running", extra: str = "",
         marker: str = "worktrack") -> str:
    return (f"---\nvibe-track: {marker}\nvibe-id: {track_id}\nvibe-title: {title}\nvibe-status: {status}\n"
            f"vibe-priority: {priority}\nvibe-owner: an agent  # a comment that must survive\nvibe-adapter: none\n"
            f"vibe-sources: [kinsim_home]\nvibe-roadmap: null\nvibe-children: []\n{extra}---\n\n# {title}\n\n"
            f"Purpose line one.\nMilestone line two.\n")


class Workspace:
    """A temporary workspace: one .vtdash naming the registry, the descriptor, and tracks/<file>.md notes."""

    def __init__(self, notes: dict[str, str]):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Agent work.vtdash").write_text(json.dumps({"schema": "vibetracks-dashboard-file/1", "title": "t",
                                                                 "registry": "Work tracks.vibetrack"}), encoding="utf-8")
        (self.root / "Work tracks.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
        (self.root / "tracks").mkdir()
        for name, content in notes.items():
            (self.root / "tracks" / name).write_text(content, encoding="utf-8")

    def path(self, name: str) -> Path:
        return self.root / "tracks" / name

    def cleanup(self) -> None:
        self.tmp.cleanup()


class RealRegistryTest(unittest.TestCase):
    """The checked-in workspace: the five tracks Zach named, in his order."""

    def test_five_tracks_in_order_with_their_fields(self) -> None:
        tracks = registry.load_registry(WORKSPACE)
        self.assertEqual([t.id for t in tracks], ["kinsim", "rig", "grasping", "detection", "pyblocks"])
        self.assertEqual([t.title for t in tracks], ["Kinematic Sim", "Sim to Real & Trajectory Tracking", "Grasping",
                                                     "Object Detection & Hyperspectral", "Pyblocks"])
        self.assertEqual([t.adapter for t in tracks], ["kinsim", "rig", "grasping", "detection", "pyblocks"])
        by_id = {t.id: t for t in tracks}
        self.assertEqual(by_id["rig"].children, ["can12", "can16"])
        self.assertEqual(by_id["kinsim"].roadmap, {"projector": "kinsim", "sources": ["kinsim_curriculum_dir", "kinsim_home"]})
        self.assertEqual(by_id["rig"].roadmap["projector"], "rig")
        self.assertEqual(by_id["grasping"].roadmap, {"projector": "grasping", "sources": ["grasp_bench_dir"]})
        self.assertEqual(by_id["detection"].roadmap, {"projector": "detection", "sources": ["detection_dir"]})
        self.assertIsNone(by_id["pyblocks"].roadmap)
        for track in tracks:
            self.assertRegex(track.id, registry.TRACK_ID)
            self.assertEqual(track.status, "running")
            self.assertTrue(track.purpose)
            self.assertEqual(track.revision, note_revision(Path(track.note_path).read_text(encoding="utf-8")))
        self.assertEqual(registry.read_registry(WORKSPACE).problems, [])

    def test_every_declared_source_key_is_a_sources_key(self) -> None:
        from vibetracks.sources import load_sources

        keys = set(load_sources())
        for track in registry.load_registry(WORKSPACE):
            self.assertLessEqual(set(track.sources), keys, track.id)
            for key in (track.roadmap or {}).get("sources", []):
                self.assertIn(key, keys, f"{track.id} roadmap source")

    def test_find_registry_from_folder_vtdash_or_descriptor(self) -> None:
        expected = (WORKSPACE / "Work tracks.vibetrack").resolve()
        self.assertEqual(registry.find_registry(WORKSPACE), expected)
        self.assertEqual(registry.find_registry(WORKSPACE / "Agent work.vtdash"), expected)
        self.assertEqual(registry.find_registry(expected), expected)
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(registry.find_registry(empty))
            with self.assertRaises(VibeTracksError):
                registry.load_registry(empty)


class ParsingTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.ws.cleanup()

    def test_order_status_and_problems(self) -> None:
        self.ws = Workspace({
            "b.md": note("b-track", "B", priority=2),
            "a.md": note("a", "A", priority=1),
            "z.md": note("zz", "Z", priority="high"),
            "old.md": note("old", "Old", priority=3, status="archived"),
            "bad-id.md": note("Bad Id", "Bad"),
            "dup.md": note("a", "Duplicate"),
            "feature.md": note("feat", "Not a work track", marker="feature"),
            "nottitled.md": note("untitled", "", priority=4).replace("vibe-title: \n", ""),
        })
        result = registry.read_registry(self.ws.root)
        self.assertEqual([t.id for t in result.tracks], ["a", "b-track", "old", "untitled", "zz"])
        by_id = {t.id: t for t in result.tracks}
        self.assertTrue(by_id["old"].archived)
        self.assertIsNone(by_id["zz"].priority)
        self.assertEqual(by_id["untitled"].title, "untitled")
        self.assertEqual(by_id["a"].title, "A")  # the first a.md wins; the duplicate is skipped
        self.assertEqual(by_id["a"].purpose, "Purpose line one. Milestone line two.")
        self.assertEqual(by_id["a"].heartbeat, ["kinsim_home"])
        self.assertEqual(by_id["a"].stall_hours, registry.DEFAULT_STALL_HOURS)
        errors = " | ".join(p["error"] for p in result.problems)
        self.assertIn("'Bad Id' must match", errors)
        self.assertIn("duplicate id 'a'", errors)
        self.assertIn("'high' is not a positive integer", errors)
        self.assertIn("vibe-title is missing", errors)
        self.assertNotIn("feat", [t.id for t in result.tracks])

    def test_children_that_are_registry_tracks_are_refused(self) -> None:
        self.ws = Workspace({
            "p.md": note("p", "Parent", extra="vibe-heartbeat: [kinsim_status]\nvibe-stall-hours: 72\n").replace(
                "vibe-children: []", "vibe-children: [c1, q, 'Bad Child']"),
            "q.md": note("q", "Q", priority=2),
        })
        result = registry.read_registry(self.ws.root)
        parent = result.by_id("p")
        self.assertEqual(parent.children, ["c1"])
        self.assertEqual(parent.heartbeat, ["kinsim_status"])
        self.assertEqual(parent.stall_hours, 72.0)
        self.assertEqual(len(result.problems), 2)


class RenameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Workspace({"a.md": note("a", "Old name"), "b.md": note("b", "Other", priority=2)})
        self.original = self.ws.path("a.md").read_text(encoding="utf-8")
        self.revision = note_revision(self.original)

    def tearDown(self) -> None:
        self.ws.cleanup()

    def test_rename_changes_only_the_title_line(self) -> None:
        title, revision = registry.rename_title(self.ws.root, "a", "  New name  ", self.revision)
        after = self.ws.path("a.md").read_text(encoding="utf-8")
        self.assertEqual(title, "New name")
        self.assertEqual(revision, note_revision(after))
        self.assertEqual(after, self.original.replace("vibe-title: Old name\n", "vibe-title: New name\n"))
        track = registry.read_registry(self.ws.root).by_id("a")
        self.assertEqual((track.id, track.title, track.revision), ("a", "New name", revision))

    def test_titles_yaml_would_misread_round_trip(self) -> None:
        revision = self.revision
        for title in ("yes", "a: b", "#hash", "Sim to Real & Trajectory Tracking", "null", "Grasping — v2 «ü»", "123"):
            with self.subTest(title=title):
                stored, revision = registry.rename_title(self.ws.root, "a", title, revision)
                self.assertEqual(registry.read_registry(self.ws.root).by_id("a").title, title)
                self.assertEqual(stored, title)
                self.assertIn("vibe-id: a\n", self.ws.path("a.md").read_text(encoding="utf-8"))

    def test_same_title_is_a_no_op(self) -> None:
        title, revision = registry.rename_title(self.ws.root, "a", "Old name", self.revision)
        self.assertEqual((title, revision), ("Old name", self.revision))
        self.assertEqual(self.ws.path("a.md").read_text(encoding="utf-8"), self.original)

    def test_stale_revision_conflicts_and_writes_nothing(self) -> None:
        with self.assertRaises(RevisionConflict):
            registry.rename_title(self.ws.root, "a", "New", "0000000000000000")
        self.assertEqual(self.ws.path("a.md").read_text(encoding="utf-8"), self.original)

    def test_bad_titles_are_refused(self) -> None:
        for title in ("", "   ", "two\nlines", "tab\there", "x" * 81, None, 7, ["list"]):
            with self.subTest(title=title):
                with self.assertRaises(registry.TitleInvalid):
                    registry.rename_title(self.ws.root, "a", title, self.revision)
        self.assertEqual(registry.rename_title(self.ws.root, "a", "x" * 80, self.revision)[0], "x" * 80)

    def test_unknown_id(self) -> None:
        for track_id in ("nope", "../a", "A"):
            with self.subTest(track_id=track_id):
                with self.assertRaises(UnknownFeature):
                    registry.rename_title(self.ws.root, track_id, "New", self.revision)


class FirstParagraphLimitTest(unittest.TestCase):
    """notes.first_paragraph's one optional parameter: the default is unchanged for every other caller."""

    BODY = "# Title\n\n" + "\n".join(f"Line {n} " + "word " * 12 for n in range(12)) + "\n\nSecond paragraph.\n"

    def test_default_still_stops_near_240_and_cuts_at_280(self) -> None:
        text = first_paragraph(self.BODY)
        self.assertLessEqual(len(text), 280)
        self.assertEqual(text, first_paragraph(self.BODY, limit=240))
        self.assertTrue(text.startswith("Line 0 "))

    def test_none_keeps_the_whole_first_paragraph(self) -> None:
        text = first_paragraph(self.BODY, limit=None)
        self.assertGreater(len(text), 280)
        self.assertTrue(text.rstrip().endswith("Line 11 " + "word " * 11 + "word"))
        self.assertNotIn("Second paragraph", text)

    def test_registry_purpose_is_never_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "tracks").mkdir()
            (ws / "Agent work.vtdash").write_text(json.dumps({"registry": "Work tracks.vibetrack"}), encoding="utf-8")
            (ws / "Work tracks.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
            body = self.BODY.split("\n\n", 1)[1]
            (ws / "tracks" / "long.md").write_text(note("long", "Long").split("---\n\n", 1)[0] + "---\n\n" + body,
                                                   encoding="utf-8")
            track = registry.load_registry(ws)[0]
        self.assertEqual(track.purpose, first_paragraph(body, limit=None, raw=True))
        self.assertGreater(len(track.purpose), 280)

    def test_default_still_strips_markup_for_other_callers(self) -> None:
        body = "Tune `pll_filter_hz` on **can16** and *watch* it.\n"
        self.assertEqual(first_paragraph(body), "Tune pllfilterhz on can16 and watch it.")
        self.assertEqual(first_paragraph(body, limit=None), "Tune pllfilterhz on can16 and watch it.")

    def test_raw_keeps_every_character(self) -> None:
        body = "Tune `pll_filter_hz` on **can16** and *watch* it.\nSecond __line__.\n\nNext paragraph.\n"
        self.assertEqual(first_paragraph(body, limit=None, raw=True),
                         "Tune `pll_filter_hz` on **can16** and *watch* it. Second __line__.")

    def test_registry_purpose_keeps_identifiers_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "tracks").mkdir()
            (ws / "Agent work.vtdash").write_text(json.dumps({"registry": "Work tracks.vibetrack"}), encoding="utf-8")
            (ws / "Work tracks.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
            (ws / "tracks" / "rig.md").write_text(
                note("rig", "Rig").split("---\n\n", 1)[0] + "---\n\n# Rig\n\nTunes `pll_filter_hz` on **can16**.\n",
                encoding="utf-8")
            track = registry.load_registry(ws)[0]
        self.assertEqual(track.purpose, "Tunes `pll_filter_hz` on **can16**.")


if __name__ == "__main__":
    unittest.main()
