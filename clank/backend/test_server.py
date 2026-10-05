"""Backend tests: python3 -m unittest discover -s clank/backend -p 'test_*.py' (from the repo root)."""

from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mounts  # noqa: E402
import server  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.video = root / "clip.mp4"
        self.video.write_bytes(bytes(range(256)) * 40)  # 10,240 bytes with known content
        self.report = root / "report.html"
        self.report.write_text("<!doctype html><title>r</title>", encoding="utf-8")
        self.secret = root / "secret.txt"
        self.secret.write_text("not listed", encoding="utf-8")
        self.script = root / "evil.sh"
        self.script.write_text("echo", encoding="utf-8")
        projection = {
            "schema": "vibetracks-dashboard/1",
            "tracks": [{"id": "t"}],
            "media": {
                "clip": {"id": "clip", "kind": "video", "label": "Clip", "path": str(self.video)},
                "report": {"id": "report", "kind": "html", "label": "Report", "path": str(self.report)},
                "relative": {"id": "relative", "kind": "html", "label": "x", "path": "report.html"},
                "script": {"id": "script", "kind": "html", "label": "x", "path": str(self.script)},
                "gone": {"id": "gone", "kind": "video", "label": "x", "path": str(root / "missing.mp4")},
            },
        }
        (self.home / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
        self.port = free_port()
        self.httpd = server.serve(self.port, self.home)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            conn.close()

    def test_health(self) -> None:
        status, _, body = self.get("/health")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["projection_exists"])

    def test_projection_is_served(self) -> None:
        status, headers, body = self.get("/projection")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(json.loads(body)["schema"], "vibetracks-dashboard/1")

    def test_projection_is_reread_when_it_changes(self) -> None:
        self.get("/projection")
        data = json.loads((self.home / "projection.json").read_text())
        data["tracks"].append({"id": "u"})
        (self.home / "projection.json").write_text(json.dumps(data) + "\n")
        _, _, body = self.get("/projection")
        self.assertEqual([t["id"] for t in json.loads(body)["tracks"]], ["t", "u"])

    def test_listed_media_is_streamed_with_its_type(self) -> None:
        status, headers, body = self.get("/media/clip")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "video/mp4")
        self.assertEqual(headers["accept-ranges"], "bytes")
        self.assertEqual(body, self.video.read_bytes())
        status, headers, _ = self.get("/media/report")
        self.assertEqual((status, headers["content-type"]), (200, "text/html; charset=utf-8"))

    def test_unknown_media_id_is_404(self) -> None:
        for media_id in ("nope", "relative", "script", "gone", "secret.txt"):
            with self.subTest(media_id=media_id):
                status, _, _ = self.get(f"/media/{media_id}")
                self.assertEqual(status, 404)

    def test_path_traversal_is_refused(self) -> None:
        for path in ("/media/../projection", "/media/..%2F..%2Fsecret.txt", "/media/%2Ftmp%2Fsecret.txt",
                     "/media/clip/../../etc/passwd", "/media/" + str(self.secret), "/../projection.json", "/media/"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"not listed", body)

    def test_range_requests(self) -> None:
        data = self.video.read_bytes()
        status, headers, body = self.get("/media/clip", {"Range": "bytes=100-199"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["content-range"], f"bytes 100-199/{len(data)}")
        self.assertEqual(body, data[100:200])
        status, headers, body = self.get("/media/clip", {"Range": "bytes=10000-"})
        self.assertEqual((status, body), (206, data[10000:]))
        status, headers, body = self.get("/media/clip", {"Range": "bytes=-40"})
        self.assertEqual((status, body), (206, data[-40:]))
        status, headers, _ = self.get("/media/clip", {"Range": f"bytes={len(data)}-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["content-range"], f"bytes */{len(data)}")

    def test_no_write_endpoints(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/projection", body=b"{}")
            self.assertEqual(conn.getresponse().status, 501)
        finally:
            conn.close()

    def test_refuses_a_non_loopback_bind(self) -> None:
        with self.assertRaises(SystemExit):
            server.serve(free_port(), self.home, host="0.0.0.0")

    def test_data_home_from_the_workspace_file(self) -> None:
        workspace = Path(self.tmp.name) / "ws"
        workspace.mkdir()
        (workspace / "Agent work.vtdash").write_text(json.dumps({"data_home": str(self.home)}), encoding="utf-8")
        self.assertEqual(server.resolve_data_home(None, str(workspace), environ={}), self.home)
        self.assertEqual(server.resolve_data_home(None, None, environ={}), server.DEFAULT_HOME)


class MountTest(unittest.TestCase):
    """backend/mounts.py: a GET under a mount prefix goes to the imported callable, lazily and safely."""

    FAKE = "vt_fake_mount_for_tests"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.calls: list[tuple] = []
        calls = self.calls

        def handle(method, subpath, query, headers):
            calls.append((method, subpath, query, headers.get("X-Probe")))
            return 200, {"Content-Type": "application/json"}, [b'{"ok": ', b"true}"]

        fake = types.ModuleType(self.FAKE)
        fake.handle = handle  # type: ignore[attr-defined]
        sys.modules[self.FAKE] = fake
        self.saved = list(mounts.MOUNTS)
        mounts.MOUNTS[:] = [("/fake", f"{self.FAKE}:handle"), ("/broken", "vt_no_such_module_anywhere.api:handle")]
        server._mount_cache.clear()
        self.port = free_port()
        self.httpd = server.serve(self.port, Path(self.tmp.name))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        mounts.MOUNTS[:] = self.saved
        server._mount_cache.clear()
        sys.modules.pop(self.FAKE, None)
        self.tmp.cleanup()

    def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_get_dispatches_to_the_mount(self) -> None:
        status, body = self.request("GET", "/fake/doc/x?track=kinsim&track=rig", {"X-Probe": "here"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(self.calls, [("GET", "/doc/x", {"track": ["kinsim", "rig"]}, "here")])
        status, _ = self.request("GET", "/fake")
        self.assertEqual((status, self.calls[-1][1]), (200, ""))

    def test_prefix_needs_a_segment_boundary(self) -> None:
        status, _ = self.request("GET", "/fakery")
        self.assertEqual(status, 404)
        self.assertEqual(self.calls, [])

    def test_broken_import_is_503_and_the_server_keeps_serving(self) -> None:
        status, body = self.request("GET", "/broken/anything")
        self.assertEqual(status, 503)
        self.assertIn("unavailable", json.loads(body)["error"])
        self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.request("GET", "/fake")[0], 200)

    def test_non_get_is_501(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            with self.subTest(method=method):
                status, _ = self.request(method, "/fake/doc")
                self.assertEqual(status, 501)
        self.assertEqual(self.calls, [])

    def test_a_raising_handler_is_500(self) -> None:
        def boom(*_args):
            raise RuntimeError("bad doc")

        sys.modules[self.FAKE].handle = boom  # type: ignore[attr-defined]
        server._mount_cache.clear()
        status, body = self.request("GET", "/fake")
        self.assertEqual(status, 500)
        self.assertIn("bad doc", json.loads(body)["detail"])


REGISTRY_DESCRIPTOR = """filters:
  and:
    - 'note["vibe-track"] == "worktrack"'
    - 'file.inFolder("tracks")'
vibetracks:
  version: 1
  id: work-tracks
  title: Work tracks
  vaultRoot: .
  source: tracks
"""
TRACK_NOTE = """---
vibe-track: worktrack
vibe-id: kinsim
vibe-title: Kinematic Sim
vibe-status: running
vibe-priority: 1
vibe-owner: Kinematic Sim (AGENT) session   # label only
vibe-adapter: none
vibe-sources: [kinsim_home]
vibe-roadmap:
  projector: kinsim
  sources: [kinsim_curriculum_dir, kinsim_home]
vibe-children: []
---

# Kinematic Sim

The curriculum loop.
"""


class RenameTest(unittest.TestCase):
    """POST /tracks/<id>/title: the one write, fenced, atomic and title-only; GET /projection is live from the registry."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.workspace = root / "ws"
        (self.workspace / "tracks").mkdir(parents=True)
        (self.workspace / "Agent work.vtdash").write_text(json.dumps({"registry": "Work tracks.vibetrack"}), encoding="utf-8")
        (self.workspace / "Work tracks.vibetrack").write_text(REGISTRY_DESCRIPTOR, encoding="utf-8")
        self.note = self.workspace / "tracks" / "kinsim.md"
        self.note.write_text(TRACK_NOTE, encoding="utf-8")
        self.port = free_port()
        self.httpd = server.serve(self.port, root / "home", workspace=self.workspace)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def revision(self) -> str:
        return server.note_revision(self.note.read_text(encoding="utf-8"))

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

    def get_projection(self) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/projection")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            return json.loads(response.read())
        finally:
            conn.close()

    def test_projection_is_live_from_the_registry(self) -> None:
        projection = self.get_projection()
        self.assertTrue(projection["source"]["live"])
        self.assertEqual([(t["id"], t["title"]) for t in projection["tracks"]], [("kinsim", "Kinematic Sim")])
        self.assertEqual(projection["tracks"][0]["state"]["word"], "Not reporting")

    def test_rename_changes_only_the_title_and_returns_the_new_revision(self) -> None:
        before = self.note.read_text(encoding="utf-8")
        # WHY the spaces stay (audit 2026-10-04, finding 8): the title is stored exactly as typed, never trimmed.
        status, body = self.post("/tracks/kinsim/title", {"title": "  Kinsim curriculum  ", "revision": self.revision()})
        self.assertEqual(status, 200, body)
        after = self.note.read_text(encoding="utf-8")
        self.assertEqual(body, {"ok": True, "id": "kinsim", "title": "  Kinsim curriculum  ", "revision": server.note_revision(after)})
        self.assertEqual(after, before.replace("vibe-title: Kinematic Sim\n", "vibe-title: '  Kinsim curriculum  '\n"))
        self.assertIn("vibe-id: kinsim\n", after)
        track = self.get_projection()["tracks"][0]
        self.assertEqual((track["id"], track["title"], track["registry"]["revision"]), ("kinsim", "  Kinsim curriculum  ", body["revision"]))
        # The returned revision fences the next rename.
        status, again = self.post("/tracks/kinsim/title", {"title": "Kinematic Sim", "revision": body["revision"]})
        self.assertEqual((status, self.note.read_text(encoding="utf-8")), (200, before))

    def test_a_stale_revision_is_409_and_writes_nothing(self) -> None:
        before = self.note.read_text(encoding="utf-8")
        stale = self.revision()
        self.note.write_text(before.replace("The curriculum loop.", "Edited by hand."), encoding="utf-8")
        edited = self.note.read_text(encoding="utf-8")
        status, body = self.post("/tracks/kinsim/title", {"title": "New", "revision": stale})
        self.assertEqual(status, 409)
        self.assertEqual(body["revision"], server.note_revision(edited))
        self.assertEqual(self.note.read_text(encoding="utf-8"), edited)

    def test_a_bad_title_or_body_is_400(self) -> None:
        before = self.note.read_text(encoding="utf-8")
        revision = self.revision()
        for payload in ({"title": "", "revision": revision}, {"title": "   ", "revision": revision},
                        {"title": "two\nlines", "revision": revision}, {"title": "cr\rhere", "revision": revision},
                        {"title": "\t ", "revision": revision},
                        {"title": 5, "revision": revision}, {"revision": revision}, {"title": "ok"},
                        {"title": "ok", "revision": ""}, ["title"], b"{not json"):
            with self.subTest(payload=payload):
                status, body = self.post("/tracks/kinsim/title", payload)
                self.assertEqual(status, 400, body)
                self.assertIn("error", body)
        self.assertEqual(self.note.read_text(encoding="utf-8"), before)

    def test_a_bad_content_type_is_415(self) -> None:
        for content_type in ("text/plain", "application/x-www-form-urlencoded", None):
            with self.subTest(content_type=content_type):
                status, _ = self.post("/tracks/kinsim/title", {"title": "New", "revision": self.revision()}, content_type)
                self.assertEqual(status, 415)
        status, _ = self.post("/tracks/kinsim/title", {"title": "New", "revision": self.revision()},
                              "application/json; charset=utf-8")
        self.assertEqual(status, 200)

    def test_an_unknown_id_is_404(self) -> None:
        for track_id in ("nope", "KINSIM", "..%2Fkinsim"):
            with self.subTest(track_id=track_id):
                status, _ = self.post(f"/tracks/{track_id}/title", {"title": "New", "revision": self.revision()})
                self.assertEqual(status, 404)

    def test_other_writes_stay_501(self) -> None:
        for path in ("/projection", "/tracks/kinsim", "/tracks/kinsim/title/x", "/tracks/kinsim/status"):
            with self.subTest(path=path):
                status, _ = self.post(path, {"title": "x", "revision": self.revision()})
                self.assertEqual(status, 501)

    def test_no_registry_is_404(self) -> None:
        port = free_port()
        httpd = server.serve(port, Path(self.tmp.name) / "home2")  # no workspace: projection.json mode
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("POST", "/tracks/kinsim/title", body=b'{"title": "x", "revision": "r"}',
                         headers={"Content-Type": "application/json"})
            self.assertEqual(conn.getresponse().status, 404)
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
