"""Capture the Storybook fixtures from a running Vibe Tracks lane, with read-only GETs, into stories/fixtures/.

Fetches exactly what the stories use (stories/backend.ts): the projection, the roadmap documents of kinsim, rig,
grasping and detection, pyblocks' 404 ("no roadmap reported yet"), the art name list and every PNG it names. Each file
is the response body byte for byte. Then rewrites fixtures/README.md with the capture time and each file's hash.

Run with the lane up:
  python3 ~/vibetracks-roadmap/clank/stories/capture_fixtures.py [--url http://127.0.0.1:4400]

WHY the data is captured and never committed: it is real BAM loop data and the repo is public (.gitignore ignores
everything under fixtures/ but the README). WHY everything is fetched before anything is written: a capture that fails
halfway must leave the previous fixtures whole, not a mix of two moments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
API = "/api/plugins/vibetracks"
TRACKS = ("kinsim", "rig", "grasping", "detection")
NO_ROADMAP_TRACK = "pyblocks"
# WHY refused: the Stable/Preview channels of other apps live on these ports; this script must never touch them.
REFUSED_PORTS = {4380, 4381, 4390, 4391}
TIMEOUT_S = 180


def get(base: str, path: str) -> tuple[int, bytes]:
    """One GET through the lane's plugin proxy: (status, body). A 4xx/5xx answer is returned, not raised."""

    request = urllib.request.Request(f"{base}{API}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def expect(status: int, body: bytes, wanted: int, what: str) -> bytes:
    if status != wanted:
        raise SystemExit(f"capture_fixtures: {what} answered HTTP {status}, expected {wanted}: {body[:300]!r}")
    return body


def readme(captured_at: str, base: str, rows: list[tuple[str, str, int, bytes]], art_bytes: int, art_count: int) -> str:
    sha = lambda body: hashlib.sha256(body).hexdigest()[:12]  # noqa: E731 - one-line helper for the table
    table = "\n".join(f"| {name} | {path} | {status} | {len(body)} | {sha(body)} |" for name, path, status, body in rows)
    return f"""# Story fixtures

Real documents captured from a running Vibe Tracks lane, for the Storybook stories (../backend.ts serves them to the
components). They are BAM loop data, and this repo is public, so they are captured locally and NEVER committed: the
root .gitignore ignores everything in this folder except this README. Without them Storybook still builds; each story
that needs one says "Fixture missing: run `python3 clank/stories/capture_fixtures.py` with the lane up".

Capture (or refresh) them, with the lane up, from the repo root:

```bash
python3 clank/stories/capture_fixtures.py
```

`--url` picks another lane (default http://127.0.0.1:4400); ports 4380, 4381, 4390 and 4391 are refused. Every
request is a read-only GET through Clank's plugin proxy ({API}/...), and every file is the response body byte for byte.
Restart a running Storybook after a capture: it lists the art files when it starts.

Last capture: {captured_at} from {base} (this README is rewritten by each capture).

| File | GET | Status | Bytes | sha256[:12] |
|---|---|---|---|---|
{table}
| art/*.png ({art_count} files) | /roadmap/art/<name> for every name in roadmap/art.json | 200 | {art_bytes} total | |

The only story data that is not a captured byte is the server-stale warning (../backend.ts `serverStaleText`): it
prepends to roadmap/kinsim.json the warning vibetracks/roadmap/api.py writes when a live projection fails and the stored
document is served, with a placeholder failure reason inside the parentheses, said as such in the warning.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:4400", help="the lane's origin (Clank with the vibetracks plugin)")
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(f"capture_fixtures: --url must be http(s)://host:port, got {args.url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port in REFUSED_PORTS:
        raise SystemExit(f"capture_fixtures: port {port} is refused (4380/4381/4390/4391 are never touched)")
    base = f"{parsed.scheme}://{parsed.netloc}"
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # (file under fixtures/, GET path, status, body), all fetched before any write.
    rows: list[tuple[str, str, int, bytes]] = []
    rows.append(("projection.json", "/projection", 200, expect(*get(base, "/projection"), 200, "/projection")))
    for track in TRACKS:
        path = f"/roadmap/doc?track={track}"
        rows.append((f"roadmap/{track}.json", path, 200, expect(*get(base, path), 200, path)))
    path = f"/roadmap/doc?track={NO_ROADMAP_TRACK}"
    # WHY a 404 is required: the pyblocks stories show "No roadmap reported yet."; a 200 means that premise moved on.
    rows.append((f"roadmap/{NO_ROADMAP_TRACK}.404.json", path, 404, expect(*get(base, path), 404, path)))
    art_list = expect(*get(base, "/roadmap/art"), 200, "/roadmap/art")
    rows.append(("roadmap/art.json", "/roadmap/art", 200, art_list))
    names = json.loads(art_list).get("entries", [])
    if not isinstance(names, list) or not all(isinstance(name, str) and "/" not in name and name not in ("", ".", "..") for name in names):
        raise SystemExit(f"capture_fixtures: /roadmap/art gave an unexpected entry list: {names!r}")
    art = {name: expect(*get(base, f"/roadmap/art/{urllib.parse.quote(name)}"), 200, f"/roadmap/art/{name}") for name in names}

    for name, _path, _status, body in rows:
        target = FIXTURES / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    art_dir = FIXTURES / "art"
    # WHY the art dir is replaced whole: a render the backend no longer lists must not linger as a fixture.
    if art_dir.exists():
        shutil.rmtree(art_dir)
    art_dir.mkdir(parents=True)
    for name, body in art.items():
        (art_dir / name).write_bytes(body)
    (FIXTURES / "README.md").write_text(readme(captured_at, base, rows, sum(len(body) for body in art.values()), len(art)))

    for name, _path, status, body in rows:
        print(f"{status}  {len(body):>9}  {name}")
    print(f"200  {sum(len(body) for body in art.values()):>9}  art/ ({len(art)} PNGs)")
    print(f"captured {captured_at} from {base} into {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
