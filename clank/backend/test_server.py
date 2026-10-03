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


if __name__ == "__main__":
    unittest.main()
