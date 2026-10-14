"""Writes the COMMITTED synthetic story fixtures: the home's own documents, built by the home's own code
(compose.build_home, detail.build_track, detail.build_project) over the committed test fixtures, exactly as
tests/test_home_detail.py builds them. No BAM loop data: the repo is public (real captures go to fixtures/real/,
which is gitignored; see capture_real.py).

    python3 /home/bam/vibetracks-storybook/storybook/scripts/make_fixtures.py

WHY paths are normalised: build_home runs over a temporary copy, so the documents carry this machine's temp folder
and home path; both are rewritten to /home/fix so a rebuild on another machine (or the Windows box) gives the same
bytes and no local path lands in the public repo.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE.parent / "fixtures" / "synthetic"
sys.path[:0] = [str(REPO), str(REPO / "tests")]

from test_home_detail import FIXTURES, NOW, PROJECTION  # noqa: E402  (the test's own inputs, never a copy)
from vibetracks.home import compose, detail  # noqa: E402
from vibetracks.home.compose import build_home  # noqa: E402


def normalise(text: str, tmp: Path) -> str:
    text = text.replace(str(tmp.resolve()), "/home/fix").replace(str(tmp), "/home/fix")
    home = os.path.expanduser("~")
    text = text.replace(home, "/home/fix")
    return re.sub(r"/tmp/tmp[\w-]+", "/home/fix", text)


def main() -> None:
    with tempfile.TemporaryDirectory() as name:
        root = Path(name)
        for part in ("claude-fixa", "proc", "workspace"):
            shutil.copytree(FIXTURES / part, root / part)
        workspace = root / "workspace"
        audits = root / "audits"
        audits.mkdir()
        # The same three audit rounds tests/test_home_detail.py writes, so the Auditor tab has every verdict tone.
        (audits / "2026-10-08-claim-r1.md").write_text("**UNSOUND - the ruler can be gamed.**\n\nDetail.\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r1.log").write_text("OpenAI Codex v0.159\n--------\nmodel: gpt-6.1-sol\nprovider: openai\n"
                                                        "reasoning effort: xhigh\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r1-prompt.md").write_text("# prompt\n", encoding="utf-8")
        (audits / "2026-10-08-claim-r2.md").write_text("SOUND WITH FIXES: two minor findings.\n", encoding="utf-8")
        for i, made in enumerate(sorted(audits.iterdir())):  # file times are the audit times: pin them to the clock
            os.utime(made, (NOW - 7200 + 600 * i, NOW - 7200 + 600 * i))
        note = workspace / "tracks" / "t-claim.md"
        text = note.read_text(encoding="utf-8")
        note.write_text(text.replace("vibe-sessions:", f'vibe-audits: ["{audits}/*-claim-*.md"]\nvibe-sessions:', 1), encoding="utf-8")
        (workspace / "projects").mkdir(exist_ok=True)
        (workspace / "projects" / "fixture.vibetrack").write_text(
            "vibetracks:\n  version: 1\n  kind: project\n  name: Fixture Robotics\n  roots: [/home/fix]\n", encoding="utf-8")
        doc = build_home(workspace, claude_homes=[root / "claude-fixa"], proc_root=root / "proc", now=NOW,
                         projection=PROJECTION, needs={})
        last = compose.LAST[str(workspace.resolve())]
        files: dict[str, object] = {"home.json": doc}
        for project in doc["projects"]:
            page = detail.build_project(doc, last, project["id"])
            if page is not None:
                files[f"project.{project['id']}.json"] = page
            for track in project["tracks"]:
                page = detail.build_track(doc, last, track["id"])
                if page is not None:
                    files[f"track.{track['id']}.json"] = page
        OUT.mkdir(parents=True, exist_ok=True)
        for old in OUT.glob("*.json"):
            old.unlink()
        for fname, body in files.items():
            text = normalise(json.dumps(body, indent=1, ensure_ascii=False), root)
            # timing_ms is how long this machine took; it would make every rebuild a diff.
            text = re.sub(r'"timing_ms": (\{[^}]*\}|[0-9.]+)', '"timing_ms": null', text)
            # A revision hashes the note's bytes, which hold the temp audit path: name each one by its order instead.
            revs: dict[str, str] = {}
            text = re.sub(r'"revision": "([0-9a-f]{16})"',
                          lambda m: f'"revision": "{revs.setdefault(m.group(1), f"fixture-rev-{len(revs) + 1}")}"', text)
            (OUT / fname).write_text(text + "\n", encoding="utf-8")
        print(f"{len(files)} synthetic fixtures -> {OUT}")
        print("projects:", [p["id"] for p in doc["projects"]], "states:", sorted({t["state"]["word"] for p in doc["projects"] for t in p["tracks"]}))


if __name__ == "__main__":
    main()
