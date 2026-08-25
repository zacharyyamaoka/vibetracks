from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
