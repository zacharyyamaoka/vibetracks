"""Captures REAL story fixtures from a running Vibe Tracks home, read-only (GET only), into fixtures/real/, which is
gitignored: these are BAM's live loop documents and the repo is public.

    python3 /home/bam/vibetracks-storybook/storybook/scripts/capture_real.py
    python3 /home/bam/vibetracks-storybook/storybook/scripts/capture_real.py --base http://127.0.0.1:4396/api/plugins/vibetracks

Default base: Zach's Stable (4394). Files: home.json (GET home/doc), project.<id>.json, track.<id>.json,
roadmap.<track>.json (only where the projector answers), needs.json. The stories read whatever is here and say
"no real capture" where a file is missing; they never fall back to a blank component.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "real"


def get(url: str) -> object | None:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        print(f"  {error.code} {url}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:4394/api/plugins/vibetracks")
    base = parser.parse_args().base.rstrip("/")
    OUT.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    doc = get(f"{base}/home/doc")
    if not isinstance(doc, dict) or doc.get("schema") != "vibetracks-home/1":
        sys.exit(f"{base}/home/doc did not answer a vibetracks-home/1 document")
    files["home.json"] = doc
    for project in doc["projects"]:
        page = get(f"{base}/home/project?id={urllib.parse.quote(project['id'])}")
        if page is not None:
            files[f"project.{project['id']}.json"] = page
        for track in project["tracks"]:
            tid = track["id"]
            page = get(f"{base}/home/track?id={urllib.parse.quote(tid)}")
            if page is not None:
                files[f"track.{tid}.json"] = page
            road = get(f"{base}/roadmap/doc?track={urllib.parse.quote(tid)}")
            if road is not None:
                files[f"roadmap.{tid}.json"] = road
    needs = get(f"{base}/needs")
    if needs is not None:
        files["needs.json"] = needs
    for old in OUT.glob("*.json"):
        old.unlink()
    for name, body in files.items():
        (OUT / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    total = sum((OUT / name).stat().st_size for name in files)
    print(f"{len(files)} real fixtures ({total / 1e6:.1f} MB) from {base} -> {OUT}  (generated_at {doc['generated_at']})")


if __name__ == "__main__":
    main()
