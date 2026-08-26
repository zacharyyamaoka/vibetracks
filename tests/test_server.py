from __future__ import annotations

from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vibetracks.server import VibeTracksApplication, VibeTracksHandler


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "features").mkdir()
        self.descriptor = self.root / "Project.vibetrack"
        self.descriptor.write_text(
            "vibetracks:\n  title: Test Track\n  source: features\n  statuses: [ready, review, done]\n",
            encoding="utf-8",
        )
        (self.root / "features" / "Feature.md").write_text(
            "---\nvibe-id: F-1\nvibe-status: review\n---\n# Feature\n",
            encoding="utf-8",
        )
        application = VibeTracksApplication(self.descriptor)
        handler = partial(VibeTracksHandler, application=application)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def json_get(self, path: str) -> dict:
        with urlopen(self.base + path) as response:
            return json.load(response)

    def test_snapshot_and_revision_safe_status_endpoint(self) -> None:
        project = self.json_get("/api/project")
        self.assertEqual(project["title"], "Test Track")
        item = project["items"][0]
        request = Request(
            self.base + "/api/features/F-1/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"status": "done", "expectedRevision": item["revision"]}).encode(),
        )
        with urlopen(request) as response:
            updated = json.load(response)["item"]
        self.assertEqual(updated["status"], "done")

        stale = Request(
            self.base + "/api/features/F-1/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"status": "ready", "expectedRevision": item["revision"]}).encode(),
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(stale)
        self.assertEqual(caught.exception.code, 409)

    def test_media_endpoint_refuses_path_escape(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/media?path=../outside.txt")
        self.assertEqual(caught.exception.code, 400)

    def json_post(self, path: str, payload: dict, content_type: str = "application/json") -> dict:
        request = Request(
            self.base + path,
            method="POST",
            headers={"Content-Type": content_type},
            data=json.dumps(payload).encode(),
        )
        with urlopen(request) as response:
            return json.load(response)

    def test_known_revision_short_circuits_polling(self) -> None:
        revision = self.json_get("/api/project")["revision"]
        cheap = self.json_get(f"/api/project?known={revision}")
        self.assertTrue(cheap["unchanged"])
        self.assertEqual(cheap["revision"], revision)
        self.assertNotIn("items", cheap)
        # The cheap reply still carries the server clock: the panel ages a
        # `running` claim between snapshots, so its skew must stay fresh.
        self.assertIsInstance(datetime.fromisoformat(cheap["now"]), datetime)
        full = self.json_get("/api/project?known=stale")
        self.assertIn("items", full)

    def test_dependencies_and_comment_endpoints(self) -> None:
        (self.root / "features" / "Second.md").write_text(
            "---\nvibe-id: F-2\nvibe-status: ready\n---\n# Second\n",
            encoding="utf-8",
        )
        item = next(
            entry
            for entry in self.json_get("/api/project")["items"]
            if entry["id"] == "F-2"
        )
        updated = self.json_post(
            "/api/features/F-2/dependencies",
            {"dependsOn": ["F-1"], "expectedRevision": item["revision"]},
        )["item"]
        self.assertEqual(updated["dependencies"], ["F-1"])

        commented = self.json_post(
            "/api/features/F-2/comment",
            {"text": "Please add a screenshot.", "expectedRevision": updated["revision"]},
        )["item"]
        self.assertIn("Please add a screenshot.", commented["body"])
        self.assertIn("[!quote]", commented["body"])

    def test_post_requires_json_content_type(self) -> None:
        item = self.json_get("/api/project")["items"][0]
        with self.assertRaises(HTTPError) as caught:
            self.json_post(
                "/api/features/F-1/status",
                {"status": "done", "expectedRevision": item["revision"]},
                content_type="text/plain",
            )
        self.assertEqual(caught.exception.code, 415)

    def test_media_svg_gets_csp_and_nosniff(self) -> None:
        (self.root / "assets").mkdir()
        (self.root / "assets" / "proof.svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8"
        )
        with urlopen(self.base + "/api/media?path=assets/proof.svg") as response:
            self.assertIn("default-src 'none'", response.headers.get("Content-Security-Policy", ""))
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_rebound_hostname_is_forbidden(self) -> None:
        request = Request(self.base + "/api/project", headers={"Host": "evil.example:8777"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_malformed_note_shows_as_problem_not_500(self) -> None:
        (self.root / "features" / "Broken.md").write_text(
            "---\nx: [unclosed\n---\n# Broken\n", encoding="utf-8"
        )
        project = self.json_get("/api/project")
        self.assertEqual(len(project["problems"]), 1)
        self.assertIn("Broken.md", project["problems"][0]["path"])

    def test_unknown_feature_is_404(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.json_post(
                "/api/features/NOPE/status",
                {"status": "done", "expectedRevision": "0" * 16},
            )
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
