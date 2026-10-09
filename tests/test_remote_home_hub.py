"""The hub serves the new home (r3, 2026-10-09), written before the code it tests: the phone and other machines see the
same page as the dock icon, not the old dashboard. Zach: "please also merge the git remote work into this: so I can
start like using this across machines".

    python3 -m unittest tests/test_remote_home_hub.py      (from the repo root)

- ``/`` sends the browser to ``/home/``, the home page (vibetracks/home/static) over the hub's own document: this
  workspace, the hub's projection (built over the merged sources) and the share's other machines.
- ``/home/doc`` is that ``vibetracks-home/1`` document, with ``remote`` (the share's hosts) and
  ``capabilities.rename`` false: the hub serves no writes, so the page offers no rename there.
- ``/needs`` and ``/roadmap/...`` answer as on the dashboard backend (Review and the track page read them).
- The old hub app stays reachable at ``/hub/`` (its API is unchanged).
- The home's pages may use inline style attributes (the page sets column widths and colours inline), so their CSP
  allows them; the old app keeps the strict one.

Hermetic: a temp share (not a git clone: the hub only checks a clone), a copy of B1's fixture workspace and fixture
Claude home, nothing of this machine's sessions read.
"""

from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from vibetracks.remote import hub

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class HubServesTheHome(unittest.TestCase):
    def setUp(self) -> None:
        import time

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for name in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / name, root / name)
        share = root / "share"
        (share / "hosts" / "win-a" / "sessions").mkdir(parents=True)
        now = time.time()
        (share / "hosts" / "win-a" / "host.json").write_text(json.dumps(
            {"host": "win-a", "last_sync": iso(now - 30), "interval_s": 3, "heartbeat_s": 300}), encoding="utf-8")
        (share / "hosts" / "win-a" / "sessions" / "s-win-a.json").write_text(json.dumps(
            {"session_id": "s-win-a", "host": "win-a", "account": "bam", "agent": "claude-code", "cwd": "C:/x",
             "track": "t-stale", "url": None, "event": "UserPromptSubmit", "started_at": iso(now - 600),
             "last_seen": iso(now - 40), "ended": False, "title": "On win-a"}), encoding="utf-8")
        self.hub = hub.Hub(share, root / "workspace", root / "data-home", host_name="bam-gpu",
                           home_options={"claude_homes": [root / "claude-fixa"], "proc_root": root / "proc", "cache_dir": None})
        self.hub.projection = {"schema": "vibetracks-dashboard/1", "tracks": []}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), hub.make_handler(self.hub, set(hub.LOOPBACK)))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port

    def tearDown(self) -> None:
        self.hub.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            conn.close()

    def test_root_goes_to_the_home(self) -> None:
        status, headers, _ = self.request("GET", "/")
        self.assertIn(status, (301, 302, 303, 307, 308))
        self.assertEqual(headers["location"], "/home/")
        status, headers, body = self.request("GET", "/home/")
        self.assertEqual(status, 200)
        self.assertIn(b'data-testid="vt-home"', body)
        self.assertIn("'unsafe-inline'", headers["content-security-policy"].split("style-src", 1)[1].split(";", 1)[0])
        status, headers, body = self.request("GET", "/home/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["content-type"])

    def test_the_home_document_carries_the_other_machines(self) -> None:
        status, _, body = self.request("GET", "/home/doc")
        self.assertEqual(status, 200, body[:300])
        doc = json.loads(body)
        self.assertEqual(doc["schema"], "vibetracks-home/1")
        self.assertEqual([h["host"] for h in doc["remote"]["hosts"]], ["win-a"])
        self.assertEqual(doc["capabilities"]["rename"], False, "the hub serves no writes")
        self.assertIsNone(doc["links"]["workbench"], "no Clank on the hub")
        stale = next(t for p in doc["projects"] for t in p["tracks"] if t["id"] == "t-stale")
        card = next(s for s in stale["sessions"] if s["id"] == "s-win-a")
        self.assertFalse(card["live"])
        self.assertEqual(card["remote"]["host"], "win-a")
        status, _, body = self.request("GET", "/home/track?id=t-stale")
        self.assertEqual(status, 200, body[:300])

    def test_review_and_the_old_app_still_answer(self) -> None:
        status, _, body = self.request("GET", "/needs")
        self.assertEqual(status, 200, body[:300])
        self.assertIn("tracks", json.loads(body))
        status, _, body = self.request("GET", "/hub/")
        self.assertEqual(status, 200)
        self.assertIn(b"/static/hub.js", body)
        status, _, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)

    def test_no_writes_and_the_host_guard_holds(self) -> None:
        status, _, _ = self.request("POST", "/tracks/t-stale/title", json.dumps({"title": "x", "revision": "y"}).encode(),
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", "/home/doc", headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
