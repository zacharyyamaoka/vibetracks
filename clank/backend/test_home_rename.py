"""Inline rename on the home (Zach, Oct 9: "I want to be able to double click to rename", like Claude's sidebar):
two fenced writes on the backend, written before the code they test (r3, 2026-10-09).

    python3 -m unittest discover -s clank/backend -p 'test_*.py'      (from the repo root)

- ``POST /tracks/<id>/title`` already renames a WORK track (test_server.RenameTest). The home also lists activity
  tracks (``vibe-track: activity`` notes, no KPI adapter yet); the same route renames their ``vibe-title``, with the
  same fence (409 on a stale revision), the same atomic write and the same title rules (never trimmed, one line).
- ``POST /projects/<id>/name`` renames a project: the ``name`` of its descriptor (``workspace/projects/*.vibetrack``),
  JSON ``{name, revision}``, fenced on the descriptor's revision (409 when it changed), atomic, and only the name line
  changes. Tracks that name the project by its old name (``vibe-project``) stay under it. The project's id is the slug
  of its name (B2's contract, pinned by the frozen tests/test_home_detail.py), so the answer carries the new id.

Amended once after it was committed (r3): it first asked for the id to be the descriptor's file stem; the frozen B2
test_home_detail.py requests a project by the slug of its name ("fixture.vibetrack" named "Fixture Robotics" is
"fixture-robotics"), so the id follows the name and only the tracks' survival is required.

Every case runs on a temp copy of tests/fixtures/home/workspace; nothing outside the temp dir is written.
"""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import server  # noqa: E402  (clank/backend is on the path for every way this suite runs; see test_server.py)

REPO = Path(__file__).resolve().parents[2]
FIXTURE_WORKSPACE = REPO / "tests" / "fixtures" / "home" / "workspace"
BAM_DESCRIPTOR = (
    "# A project for the rename tests.\n"
    "vibetracks:\n"
    "  version: 1\n"
    "  kind: project\n"
    "  name: Fixture Robotics\n"
    "  roots: [/home/fix/main, /home/fix/prusa]   # two roots, so the name is required\n"
)
SOLO_DESCRIPTOR = "vibetracks:\n  version: 1\n  kind: project\n  roots: [/home/fix/solo-repo]\n"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class HomeRenameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.workspace = root / "ws"
        shutil.copytree(FIXTURE_WORKSPACE, self.workspace)
        projects = self.workspace / "projects"
        projects.mkdir()
        self.bam = projects / "fixture-robotics.vibetrack"
        self.bam.write_text(BAM_DESCRIPTOR, encoding="utf-8")
        self.solo = projects / "solo-repo.vibetrack"
        self.solo.write_text(SOLO_DESCRIPTOR, encoding="utf-8")
        self.activity = self.workspace / "tracks" / "t-busy.md"
        self.port = free_port()
        self.httpd = server.serve(self.port, root / "home", workspace=self.workspace)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    @staticmethod
    def revision(path: Path) -> str:
        return server.note_revision(path.read_text(encoding="utf-8"))

    def post(self, path: str, payload: object, content_type: str | None = "application/json") -> tuple[int, dict]:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": content_type} if content_type else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
        finally:
            conn.close()

    def home(self) -> dict:
        from vibetracks.home.compose import build_home

        return build_home(self.workspace, claude_homes=[], proc_root=Path(self.tmp.name) / "no-proc",
                          projection={"tracks": []}, needs={})

    # ---------------------------------------------------------------- activity tracks
    def test_an_activity_track_renames_through_the_same_fenced_route(self) -> None:
        before = self.activity.read_text(encoding="utf-8")
        status, body = self.post("/tracks/t-busy/title", {"title": "Busy, renamed  ", "revision": self.revision(self.activity)})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "Busy, renamed  ", "stored exactly as typed, never trimmed")
        after = self.activity.read_text(encoding="utf-8")
        self.assertEqual(body["revision"], server.note_revision(after))
        changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))
        self.assertEqual(len(changed), 1, f"only the title line changes: {changed}")
        self.assertTrue(changed[0][1].startswith("vibe-title:"), changed)
        track = next(t for p in self.home()["projects"] for t in p["tracks"] if t["id"] == "t-busy")
        self.assertEqual(track["title"], "Busy, renamed  ")
        self.assertEqual(track["revision"], body["revision"], "the home document carries the note's revision to fence on")

    def test_a_stale_revision_is_409_and_writes_nothing(self) -> None:
        stale = self.revision(self.activity)
        self.activity.write_text(self.activity.read_text(encoding="utf-8") + "\nedited elsewhere\n", encoding="utf-8")
        before = self.activity.read_text(encoding="utf-8")
        status, body = self.post("/tracks/t-busy/title", {"title": "New", "revision": stale})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("revision"), server.note_revision(before), "a 409 names the current revision")
        self.assertEqual(self.activity.read_text(encoding="utf-8"), before)

    def test_bad_titles_are_400(self) -> None:
        for title in ("", "   ", "two\nlines", 7):
            with self.subTest(title=title):
                status, _ = self.post("/tracks/t-busy/title", {"title": title, "revision": self.revision(self.activity)})
                self.assertEqual(status, 400)

    # ---------------------------------------------------------------- projects
    def test_project_rename_round_trip_keeps_id_and_tracks(self) -> None:
        doc = self.home()
        project = next(p for p in doc["projects"] if p["name"] == "Fixture Robotics")
        self.assertEqual(project["revision"], self.revision(self.bam))
        tracks = sorted(t["id"] for t in project["tracks"])
        self.assertTrue(tracks)

        status, body = self.post("/projects/fixture-robotics/name", {"name": "BAM  lab", "revision": project["revision"]})
        self.assertEqual(status, 200, body)
        self.assertEqual((body["id"], body["name"]), ("bam-lab", "BAM  lab"), "the answer carries the new id")
        text = self.bam.read_text(encoding="utf-8")
        self.assertEqual(body["revision"], server.note_revision(text))
        old, new = BAM_DESCRIPTOR.splitlines(), text.splitlines()
        self.assertEqual(len(old), len(new))
        self.assertEqual([i for i, (a, b) in enumerate(zip(old, new)) if a != b], [4], "only the name line changes")

        doc = self.home()
        renamed = next(p for p in doc["projects"] if p["id"] == "bam-lab")
        self.assertEqual(renamed["name"], "BAM  lab")
        self.assertEqual(sorted(t["id"] for t in renamed["tracks"]), tracks,
                         "tracks whose vibe-project still says the old name stay under the renamed project")
        self.assertNotIn("Fixture Robotics", [p["name"] for p in doc["projects"]], "no orphan group under the old name")

        status, body = self.post("/projects/bam-lab/name", {"name": "Fixture Robotics", "revision": body["revision"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.bam.read_text(encoding="utf-8"), BAM_DESCRIPTOR, "renaming back restores every byte")

    def test_a_project_with_no_name_line_gets_one(self) -> None:
        status, body = self.post("/projects/solo-repo/name", {"name": "Solo", "revision": self.revision(self.solo)})
        self.assertEqual(status, 200, body)
        lines = self.solo.read_text(encoding="utf-8").splitlines(keepends=True)
        added = [line for line in lines if line.strip().startswith("name:")]
        self.assertEqual(len(added), 1, lines)
        self.assertTrue(added[0].startswith("  name:"), "inside the vibetracks: block")
        self.assertEqual("".join(line for line in lines if line not in added), SOLO_DESCRIPTOR, "one name line added, nothing else")
        self.assertEqual(next(p for p in self.home()["projects"] if p["id"] == "solo")["name"], "Solo")

    def test_project_stale_revision_is_409(self) -> None:
        stale = self.revision(self.bam)
        self.bam.write_text(BAM_DESCRIPTOR + "# edited elsewhere\n", encoding="utf-8")
        before = self.bam.read_text(encoding="utf-8")
        status, body = self.post("/projects/fixture-robotics/name", {"name": "New", "revision": stale})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("revision"), server.note_revision(before))
        self.assertEqual(self.bam.read_text(encoding="utf-8"), before)

    def test_project_rename_refusals(self) -> None:
        revision = self.revision(self.bam)
        for name in ("", "  ", "a\nb", None):
            with self.subTest(name=name):
                status, _ = self.post("/projects/fixture-robotics/name", {"name": name, "revision": revision})
                self.assertEqual(status, 400)
        status, _ = self.post("/projects/fixture-robotics/name", {"name": "solo-repo", "revision": revision})
        self.assertEqual(status, 400, "a name another project already has is refused")
        status, _ = self.post("/projects/nope/name", {"name": "X", "revision": revision})
        self.assertEqual(status, 404)
        status, _ = self.post("/projects/../tracks/name", {"name": "X", "revision": revision})
        self.assertIn(status, (404, 501), "an id is a file stem, never a path")
        status, _ = self.post("/projects/fixture-robotics/name", {"name": "X", "revision": revision}, "text/plain")
        self.assertEqual(status, 415)
        status, _ = self.post("/projects/fixture-robotics/name", {"name": "X"})
        self.assertEqual(status, 400, "the revision is required")
        self.assertEqual(self.bam.read_text(encoding="utf-8"), BAM_DESCRIPTOR, "no refusal wrote anything")


if __name__ == "__main__":
    unittest.main()
