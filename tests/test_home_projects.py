"""B2: projects follow the Codex model (Zach, Oct 6 "Project = Codex model: a named set of 1..N folders"; Oct 9).

    python3 -m unittest tests/test_home_projects.py      (from the repo root)

A project is a descriptor file (``workspace/projects/*.vibetrack``, the existing ``.vibetrack`` shape) with
``roots: [..]`` and an optional ``name``; with one root and no name, the name is that folder's name. A session belongs
to a project when its cwd is under ANY of the project's roots (a ``<root>/.claude/worktrees/...`` cwd is under the
root; a git worktree checked out elsewhere counts as its main checkout's folder). A folder in two projects shows an
unpinned session under both, until a track's join pins it to that track's project alone.

Fixtures: B1's frozen fixtures (tests/fixtures/home/) copied to a temp dir; this test adds descriptors and moves
session cwds in the copy only. Written before the code it tests (B2, 2026-10-09).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vibetracks.home.compose import build_home

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home"
NOW = datetime.fromisoformat("2026-10-09T12:00:00-07:00").timestamp()
PROJECTION = {"schema": "vibetracks-dashboard/1", "tracks": []}
PRUSA = "11111111-0000-4000-8000-000000000008"     # pid 1007, cwd /home/fix/prusa, no track rule matches it
WAITING = "11111111-0000-4000-8000-000000000001"   # pid 1001, cwd /home/fix/waiting, joined to t-waiting


def descriptor(path: Path, roots: list[str], name: str | None = None) -> None:
    lines = ["vibetracks:", "  version: 1", "  kind: project"]
    if name:
        lines.append(f"  name: {json.dumps(name)}")
    lines.append("  roots: [" + ", ".join(json.dumps(r) for r in roots) + "]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CodexProjectsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / name, self.root / name)
        self.workspace = self.root / "workspace"
        self.account = self.root / "claude-fixa"
        projects = self.workspace / "projects"
        # The fixture tracks all name "Fixture Robotics"; its SECOND root holds the prusa session.
        descriptor(projects / "fixture-robotics.vibetrack", ["/home/fix/main", "/home/fix/prusa"], "Fixture Robotics")
        # A second project sharing that folder, and one sharing the waiting session's folder.
        descriptor(projects / "shared-tools.vibetrack", ["/home/fix/prusa"], "Shared Tools")
        descriptor(projects / "waiting-lab.vibetrack", ["/home/fix/waiting"], "Waiting Lab")
        # One root and no name: the name is the folder's name.
        descriptor(projects / "unnamed.vibetrack", ["/home/fix/solo-repo"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build(self) -> dict:
        return build_home(self.workspace, claude_homes=[self.account], proc_root=self.root / "proc", now=NOW,
                          projection=PROJECTION, needs={})

    def set_cwd(self, pid: int, cwd: str) -> None:
        path = self.account / "sessions" / f"{pid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cwd"] = cwd
        path.write_text(json.dumps(data), encoding="utf-8")
        # The transcript's own cwd wins over the session file's; this session has no transcript lines with a cwd
        # other than the fixture's, so move those too.
        for transcript in (self.account / "projects").rglob(f"{data['sessionId']}.jsonl"):
            text = transcript.read_text(encoding="utf-8").replace('"cwd":"/home/fix/prusa"', f'"cwd":{json.dumps(cwd)}')
            text = text.replace('"cwd": "/home/fix/prusa"', f'"cwd": {json.dumps(cwd)}')
            transcript.write_text(text, encoding="utf-8")

    def projects(self, doc: dict) -> dict[str, dict]:
        return {p["name"]: p for p in doc["projects"]}

    def unpinned(self, project: dict) -> set[str]:
        return {s["id"] for s in project["sessions_unpinned"]}

    def test_roots_and_default_name(self) -> None:
        projects = self.projects(self.build())
        self.assertEqual([r["path"] for r in projects["Fixture Robotics"]["roots"]], ["/home/fix/main", "/home/fix/prusa"])
        self.assertIn("solo-repo", projects, "one root and no name: the project takes the folder's name")
        self.assertEqual(projects["solo-repo"]["tracks"], [])

    def test_session_in_a_secondary_folder_lands_under_the_project(self) -> None:
        projects = self.projects(self.build())
        self.assertIn(PRUSA, self.unpinned(projects["Fixture Robotics"]),
                      "the prusa session's cwd is the project's second root")

    def test_a_folder_in_two_projects_shows_the_session_under_both(self) -> None:
        doc = self.build()
        projects = self.projects(doc)
        self.assertIn(PRUSA, self.unpinned(projects["Fixture Robotics"]))
        self.assertIn(PRUSA, self.unpinned(projects["Shared Tools"]))
        other = {s["id"]: s for s in doc["other_sessions"]}
        self.assertIn(PRUSA, other, "an unpinned session stays in other_sessions (B1's page contract), once")
        self.assertEqual(sorted(other[PRUSA]["projects"]),
                         sorted([projects["Fixture Robotics"]["id"], projects["Shared Tools"]["id"]]))
        self.assertEqual(sum(1 for s in doc["other_sessions"] if s["id"] == PRUSA), 1, "never listed twice")

    def test_a_track_join_pins_the_session_to_one_project(self) -> None:
        projects = self.projects(self.build())
        self.assertNotIn(WAITING, self.unpinned(projects["Waiting Lab"]),
                         "joined to t-waiting, so it belongs to that track's project only")
        self.assertNotIn(WAITING, self.unpinned(projects["Fixture Robotics"]), "pinned sessions sit under their track")
        waiting = next(t for t in projects["Fixture Robotics"]["tracks"] if t["id"] == "t-waiting")
        self.assertIn(WAITING, {s["id"] for s in waiting["sessions"]})

    def test_a_claude_worktree_under_a_root_counts_as_that_root(self) -> None:
        self.set_cwd(1007, "/home/fix/prusa/.claude/worktrees/lane-1-abc123")
        projects = self.projects(self.build())
        self.assertIn(PRUSA, self.unpinned(projects["Fixture Robotics"]))
        self.assertIn(PRUSA, self.unpinned(projects["Shared Tools"]))

    def test_a_git_worktree_elsewhere_counts_as_its_main_checkout(self) -> None:
        main = self.root / "repos" / "toolbox"
        (main / ".git" / "worktrees" / "toolbox-lane").mkdir(parents=True)
        lane = self.root / "repos" / "toolbox-lane"
        lane.mkdir(parents=True)
        (lane / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'toolbox-lane'}\n", encoding="utf-8")
        descriptor(self.workspace / "projects" / "toolbox.vibetrack", [str(main)])
        self.set_cwd(1007, str(lane / "src"))
        (lane / "src").mkdir()
        projects = self.projects(self.build())
        self.assertIn(PRUSA, self.unpinned(projects["toolbox"]),
                      "a sibling git worktree belongs to the project of its main checkout")
        self.assertNotIn(PRUSA, self.unpinned(projects["Shared Tools"]))

    def test_session_in_no_project_has_no_projects(self) -> None:
        self.set_cwd(1007, "/home/fix/elsewhere")
        doc = self.build()
        other = {s["id"]: s for s in doc["other_sessions"]}
        self.assertEqual(other[PRUSA]["projects"], [])
        for project in doc["projects"]:
            self.assertNotIn(PRUSA, self.unpinned(project))


if __name__ == "__main__":
    unittest.main()
