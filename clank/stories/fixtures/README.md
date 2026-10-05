# Story fixtures

Real documents captured from a running Vibe Tracks lane, for the Storybook stories (../backend.ts serves them to the
components). They are BAM loop data, and this repo is public, so they are captured locally and NEVER committed: the
root .gitignore ignores everything in this folder except this README. Without them Storybook still builds; each story
that needs one says "Fixture missing: run `python3 clank/stories/capture_fixtures.py` with the lane up".

Capture (or refresh) them, with the lane up, from the repo root:

```bash
python3 clank/stories/capture_fixtures.py
```

`--url` picks another lane (default http://127.0.0.1:4400); ports 4380, 4381, 4390 and 4391 are refused. Every
request is a read-only GET through Clank's plugin proxy (/api/plugins/vibetracks/...), and every file is the response body byte for byte.
Restart a running Storybook after a capture: it lists the art files when it starts.

Last capture: 2026-10-05T13:15:49Z from http://127.0.0.1:4400 (this README is rewritten by each capture).

| File | GET | Status | Bytes | sha256[:12] |
|---|---|---|---|---|
| projection.json | /projection | 200 | 879189 | f2d622df6a60 |
| roadmap/kinsim.json | /roadmap/doc?track=kinsim | 200 | 969269 | a00da36058d9 |
| roadmap/rig.json | /roadmap/doc?track=rig | 200 | 359799 | 27bd62c6e52c |
| roadmap/grasping.json | /roadmap/doc?track=grasping | 200 | 336632 | 1a63595d4d65 |
| roadmap/detection.json | /roadmap/doc?track=detection | 200 | 51769 | 026f71d153d5 |
| roadmap/pyblocks.404.json | /roadmap/doc?track=pyblocks | 404 | 36 | 76a88b6549b6 |
| roadmap/art.json | /roadmap/art | 200 | 550 | e66c97be86e2 |
| art/*.png (14 files) | /roadmap/art/<name> for every name in roadmap/art.json | 200 | 245145 total | |

The only story data that is not a captured byte is the server-stale warning (../backend.ts `serverStaleText`): it
prepends to roadmap/kinsim.json the warning vibetracks/roadmap/api.py writes when a live projection fails and the stored
document is served, with a placeholder failure reason inside the parentheses, said as such in the warning.
