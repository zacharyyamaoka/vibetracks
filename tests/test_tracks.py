from __future__ import annotations

from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread
import tempfile
import unittest

from vibetracks.errors import VibeTracksError
from vibetracks.project import load_project
from vibetracks.server import VibeTracksApplication, VibeTracksHandler, probe_panel
from vibetracks.tracks import UNTRACKED, lane_table, lanes, track_briefing

DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "feature"'
    - 'file.inFolder("features")'
vibetracks:
  title: Lanes
  source: features
  areas:
    canvas: Selection, movement, viewport
    docs: The durable reasoning trail
"""

NOTES = {
    "A.md": "---\nvibe-track: feature\nvibe-id: F-1\nvibe-status: review\nvibe-areas: [canvas]\n---\n# Resize handles\n",
    "B.md": "---\nvibe-track: feature\nvibe-id: F-2\nvibe-status: ready\nvibe-areas: [canvas]\nvibe-priority: high\n---\n# Zoom parity\n",
    # depends across the lane boundary — the briefing must say so
    "C.md": "---\nvibe-track: feature\nvibe-id: F-3\nvibe-status: waiting\nvibe-areas: [docs]\nvibe-depends-on:\n  - \"[[A]]\"\n---\n# Write it down\n",
    # no area at all — invisible to every per-track agent unless surfaced
    "D.md": "---\nvibe-track: feature\nvibe-id: F-4\nvibe-status: backlog\n---\n# Nobody owns this\n",
}


def _fixture(root: Path) -> Path:
    (root / "features").mkdir()
    descriptor = root / "Project.vibetrack"
    descriptor.write_text(DESCRIPTOR, encoding="utf-8")
    for name, text in NOTES.items():
        (root / "features" / name).write_text(text, encoding="utf-8")
    return descriptor


class TouchedTests(unittest.TestCase):
    def test_touched_reports_file_time_even_when_frontmatter_claims_otherwise(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            descriptor = _fixture(root)
            note = root / "features" / "A.md"
            note.write_text(
                "---\nvibe-track: feature\nvibe-id: F-1\nvibe-status: running\n"
                "vibe-updated: 2999-01-01T00:00:00-07:00\n---\n# Resize handles\n",
                encoding="utf-8",
            )
            long_ago = datetime(2020, 1, 1).timestamp()
            os.utime(note, (long_ago, long_ago))

            item = load_project(descriptor).item_by_id("F-1")
            assert item is not None
            # The note may claim any `updated` it likes...
            self.assertTrue(item.updated.startswith("2999"))
            # ...but the file's own clock is what the panel ages a claim against.
            self.assertTrue(item.touched.startswith("2020"))

    def test_snapshot_carries_the_server_clock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = _fixture(Path(raw))
            snapshot = load_project(descriptor).to_dict()
            self.assertIsInstance(datetime.fromisoformat(snapshot["now"]), datetime)


class LaneTests(unittest.TestCase):
    def test_lanes_group_by_area_and_surface_untagged_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = load_project(_fixture(Path(raw)))
            by_name = {lane.name: lane for lane in lanes(project)}
            self.assertEqual({item.id for item in by_name["canvas"].items}, {"F-1", "F-2"})
            self.assertEqual({item.id for item in by_name["docs"].items}, {"F-3"})
            self.assertEqual({item.id for item in by_name[UNTRACKED].items}, {"F-4"})

    def test_lane_order_puts_the_lane_that_wants_a_human_first(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = load_project(_fixture(Path(raw)))
            names = [lane.name for lane in lanes(project)]
            self.assertEqual(names[0], "canvas")  # holds the one `review`
            self.assertEqual(names[-1], UNTRACKED)

    def test_lane_table_reports_counts_and_a_missing_panel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            table = lane_table(load_project(_fixture(Path(raw))), None)
            self.assertIn("Lanes · 4 features · 3 tracks", table)
            self.assertIn("panel: not running", table)
            self.assertIn("1 review", table)

    def test_briefing_names_cross_lane_blockers_and_scopes_the_panel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = load_project(_fixture(Path(raw)))
            brief = track_briefing(project, "docs", "http://127.0.0.1:8781/")
            self.assertIn("You are the **docs** track", brief)
            self.assertIn("http://127.0.0.1:8781/#kanban/docs", brief)
            self.assertIn("waits on another track: F-1 (review)", brief)
            self.assertIn("Never set `done`", brief)

    def test_briefing_of_a_self_contained_lane_claims_no_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brief = track_briefing(load_project(_fixture(Path(raw))), "canvas", None)
            self.assertNotIn("waits on another track", brief)
            self.assertIn("F-2 · Zoom parity [high]", brief)

    def test_unknown_track_lists_the_real_ones(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = load_project(_fixture(Path(raw)))
            with self.assertRaises(VibeTracksError) as caught:
                track_briefing(project, "nope", None)
            self.assertIn("canvas", str(caught.exception))


class ProbeTests(unittest.TestCase):
    def test_probe_finds_only_a_panel_serving_this_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            descriptor = _fixture(root)
            application = VibeTracksApplication(descriptor)
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                partial(VibeTracksHandler, application=application),
            )
            port = server.server_address[1]
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                found = probe_panel(descriptor, ports=[port])
                self.assertEqual(found, f"http://127.0.0.1:{port}/")
                # A live panel for a *different* track must not be claimed.
                other_root = root / "other"
                other_root.mkdir()
                other = _fixture(other_root)
                self.assertIsNone(probe_panel(other, ports=[port]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_probe_returns_none_when_nothing_is_listening(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = _fixture(Path(raw))
            self.assertIsNone(probe_panel(descriptor, ports=[9], timeout=0.05))


if __name__ == "__main__":
    unittest.main()
