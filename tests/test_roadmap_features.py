"""A file-first project's own feature notes, projected as bam-roadmap/1 (``vibetracks.roadmap.projector.features``).

Each test builds a throwaway git repo with a ``Project.vibetrack`` and a few ``features/*.md`` notes, so what the real
plan says today never moves these results. The last class drives ``/roadmap/doc`` the way the home's track page does:
an activity note (``vibe-track: activity``) names the projector, and the route answers with the projected document.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.roadmap import api
from vibetracks.roadmap.projector.features import project_features
from vibetracks.roadmap.projector.files import ProjectionError
from vibetracks.roadmap.projector.validate import validate

WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"
NOW = "2026-10-09T12:00:00+00:00"

DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "feature"'
    - 'file.inFolder("features")'
vibetracks:
  version: 1
  id: demo
  title: Demo
  source: features
  idPrefix: DM
  statuses: [backlog, ready, running, waiting, review, frontier, done, archived]
  areas:
    home: The home
    data: The backend
    legacy: An old tag
  roadmap:
    axes:
      home: Home
      data: Data / Backend
"""


def note(feature_id: str, title: str, status: str, areas: list[str], depends: list[str] = (), commits: list[str] = ()) -> str:
    lines = ["---", "vibe-track: feature", f"vibe-id: {feature_id}", f"vibe-status: {status}",
             f"vibe-description: {title} described", "vibe-areas:", *[f"- {area}" for area in areas]]
    if depends:
        lines += ["vibe-depends-on:", *[f"- '[[{name}]]'" for name in depends]]
    if commits:
        lines += ["vibe-commits:", *[f"- {commit}" for commit in commits]]
    return "\n".join([*lines, "---", "", f"# {title}", ""])


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True,
                               env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return completed.stdout.strip()


class FeaturesRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "Project.vibetrack").write_text(DESCRIPTOR, encoding="utf-8")
        (self.repo / "features").mkdir()
        (self.repo / "code.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "landed")
        self.landed = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "-b", "elsewhere")
        (self.repo / "other.py").write_text("y = 2\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "on another branch")
        self.unmerged = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")

    def write(self, name: str, text: str) -> None:
        (self.repo / "features" / f"{name}.md").write_text(text, encoding="utf-8")

    def project(self) -> dict:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "notes", "--allow-empty")
        return project_features(self.repo / "Project.vibetrack", now=NOW)

    @staticmethod
    def rung(document: dict, feature_id: str) -> dict:
        return next(rung for rung in document["rungs"] if rung["id"] == feature_id)


class ProjectionTests(FeaturesRepo):
    def test_a_done_note_is_done_only_when_its_commits_landed_in_this_history(self) -> None:
        self.write("DM-1 - Landed", note("DM-1", "Landed", "done", ["data"], commits=[self.landed[:8]]))
        self.write("DM-2 - Unproven", note("DM-2", "Unproven", "done", ["data"]))
        self.write("DM-3 - Elsewhere", note("DM-3", "Elsewhere", "done", ["data"], commits=[self.unmerged[:8]]))
        self.write("DM-4 - Unknown", note("DM-4", "Unknown", "done", ["data"], commits=["deadbeef"]))
        document = self.project()
        self.assertEqual(self.rung(document, "DM-1")["status"], "done")
        self.assertEqual(self.rung(document, "DM-1")["support"]["commits"], [self.landed])
        self.assertEqual(self.rung(document, "DM-2")["status"], "claimed")   # the note's word, nothing to check
        self.assertEqual(self.rung(document, "DM-3")["status"], "stale")     # a commit outside this history
        # A commit this repository does not know is only the note's word (judge_commit: stale at claim strength).
        self.assertEqual(self.rung(document, "DM-4")["status"], "claimed")
        self.assertEqual(validate(document).verdict, "valid")

    def test_work_in_hand_is_partial_and_everything_else_missing(self) -> None:
        for number, status in enumerate(["running", "review", "waiting", "ready", "backlog"], 1):
            self.write(f"DM-{number} - {status}", note(f"DM-{number}", status, status, ["home"]))
        document = self.project()
        self.assertEqual([self.rung(document, f"DM-{n}")["status"] for n in range(1, 6)],
                         ["partial", "partial", "missing", "missing", "missing"])

    def test_the_frontier_is_unblocked_scheduled_work(self) -> None:
        self.write("DM-1 - Base", note("DM-1", "Base", "done", ["data"], commits=[self.landed]))
        self.write("DM-2 - Next", note("DM-2", "Next", "ready", ["home"], depends=["DM-1 - Base"]))
        self.write("DM-3 - Parked", note("DM-3", "Parked", "backlog", ["home"], depends=["DM-1 - Base"]))
        self.write("DM-4 - Blocked", note("DM-4", "Blocked", "ready", ["home"], depends=["DM-2 - Next"]))
        document = self.project()
        self.assertEqual(document["summary"]["frontier"], ["DM-2"])
        self.assertEqual(self.rung(document, "DM-4")["x"]["blocked_by"], ["DM-2"])
        self.assertIn({"from": "DM-1", "to": "DM-2", "kind": "prerequisite", "via": None}, document["edges"])
        self.assertEqual(validate(document).verdict, "valid")

    def test_a_done_note_over_an_open_prerequisite_reads_partial(self) -> None:
        self.write("DM-1 - Open", note("DM-1", "Open", "ready", ["data"]))
        self.write("DM-2 - Claimed", note("DM-2", "Claimed", "done", ["data"], depends=["DM-1 - Open"], commits=[self.landed]))
        self.assertEqual(self.rung(self.project(), "DM-2")["status"], "partial")

    def test_axes_follow_the_descriptor_and_the_first_listed_axis_area(self) -> None:
        self.write("DM-1 - Two", note("DM-1", "Two", "ready", ["legacy", "data", "home"]))
        self.write("DM-2 - None", note("DM-2", "None", "ready", ["legacy"]))
        self.write("DM-3 - Home", note("DM-3", "Home", "ready", ["home"]))
        document = self.project()
        self.assertEqual([axis["id"] for axis in document["axes"]], ["home", "data", "other"])
        self.assertEqual(document["axes"][1]["title"], "Data / Backend")
        self.assertEqual(self.rung(document, "DM-1")["axis"], "data")
        self.assertEqual(self.rung(document, "DM-2")["axis"], "other")

    def test_done_leads_each_axis_then_open_work_in_dependency_order(self) -> None:
        self.write("DM-1 - Later", note("DM-1", "Later", "ready", ["home"], depends=["DM-3 - First"]))
        self.write("DM-2 - Banked", note("DM-2", "Banked", "done", ["home"], commits=[self.landed]))
        self.write("DM-3 - First", note("DM-3", "First", "backlog", ["home"]))
        document = self.project()
        self.assertEqual([rung["id"] for rung in document["rungs"]], ["DM-2", "DM-3", "DM-1"])
        self.assertEqual(document["where"][0]["here"], "DM-2")
        self.assertEqual(document["where"][0]["next"], "DM-3")

    def test_archived_notes_are_left_out_and_named(self) -> None:
        self.write("DM-1 - Gone", note("DM-1", "Gone", "archived", ["home"]))
        self.write("DM-2 - Kept", note("DM-2", "Kept", "ready", ["home"], depends=["DM-1 - Gone"]))
        document = self.project()
        self.assertEqual([rung["id"] for rung in document["rungs"]], ["DM-2"])
        self.assertEqual(self.rung(document, "DM-2")["depends_on"], [])
        self.assertTrue(any("archived" in warning and "DM-1" in warning for warning in document["warnings"]))

    def test_a_dependency_cycle_refuses(self) -> None:
        self.write("DM-1 - A", note("DM-1", "A", "ready", ["home"], depends=["DM-2 - B"]))
        self.write("DM-2 - B", note("DM-2", "B", "ready", ["home"], depends=["DM-1 - A"]))
        with self.assertRaises(ProjectionError):
            self.project()

    def test_outside_a_git_checkout_refuses(self) -> None:
        plain = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, plain)
        shutil.copy(self.repo / "Project.vibetrack", plain / "Project.vibetrack")
        (plain / "features").mkdir()
        with self.assertRaises(ProjectionError):
            project_features(plain / "Project.vibetrack", now=NOW)


ACTIVITY = """---
vibe-track: activity
vibe-id: {id}
vibe-title: {id}
vibe-status: running
vibe-roadmap: {roadmap}
---

# {id}
"""


class RouteTests(FeaturesRepo):
    """The home's track page asks ``/roadmap/doc?track=<id>``; an activity note may name the projector."""

    def setUp(self) -> None:
        super().setUp()
        self.write("DM-1 - Landed", note("DM-1", "Landed", "done", ["data"], commits=[self.landed]))
        self.write("DM-2 - Next", note("DM-2", "Next", "ready", ["home"], depends=["DM-1 - Landed"]))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "notes")
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace)
        for name in ("Agent work.vtdash", "Work tracks.vibetrack"):
            shutil.copy(WORKSPACE / name, self.workspace / name)
        (self.workspace / "tracks" / "activity").mkdir(parents=True)
        roadmap = "{projector: features, sources: {features_project_dir: demo_plan}}"
        (self.workspace / "tracks" / "activity" / "demo.md").write_text(ACTIVITY.format(id="demo", roadmap=roadmap),
                                                                        encoding="utf-8")
        (self.workspace / "tracks" / "activity" / "quiet.md").write_text(ACTIVITY.format(id="quiet", roadmap="null"),
                                                                         encoding="utf-8")
        sources = self.workspace / "sources.json"
        sources.write_text(json.dumps({"demo_plan": str(self.repo),
                                       "roadmap_docs_dir": str(self.workspace / "docs")}), encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.workspace),
                                               "VIBETRACKS_SOURCES": str(sources)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def doc(self, track: str) -> tuple[int, dict]:
        status, _headers, chunks = api.handle("GET", "/doc", {"track": [track]}, {})
        return status, json.loads(b"".join(chunks))

    def test_an_activity_note_names_the_features_projector(self) -> None:
        projector, sources = api.projector_for("demo")
        self.assertEqual(projector.name, "features")
        self.assertEqual(sources["features_project_dir"], str(self.repo))
        status, document = self.doc("demo")
        self.assertEqual(status, 200)
        self.assertEqual(document["loop"], "features")
        self.assertEqual(document["summary"]["frontier"], ["DM-2"])
        self.assertEqual(self.rung(document, "DM-1")["status"], "done")

    def test_a_null_roadmap_on_an_activity_note_stays_404(self) -> None:
        self.assertIsNone(api.projector_for("quiet"))
        self.assertEqual(self.doc("quiet")[0], 404)

    def test_a_work_track_of_the_same_id_wins(self) -> None:
        (self.workspace / "tracks" / "demo.md").write_text(
            "---\nvibe-track: worktrack\nvibe-id: demo\nvibe-title: demo\nvibe-status: running\nvibe-adapter: none\n"
            "vibe-sources: []\nvibe-roadmap: null\n---\n\n# demo\n", encoding="utf-8")
        self.assertIsNone(api.projector_for("demo"))

    def test_a_new_feature_note_moves_the_stamp(self) -> None:
        projector, sources = api.projector_for("demo")
        before = api._stamp(projector, sources, None)
        self.write("DM-3 - New", note("DM-3", "New", "backlog", ["home"]))
        self.assertNotEqual(api._stamp(projector, sources, None), before)


if __name__ == "__main__":
    unittest.main()
