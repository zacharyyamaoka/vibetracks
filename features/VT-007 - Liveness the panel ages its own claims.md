---
vibe-track: feature
vibe-id: VT-007
vibe-status: done
vibe-description: 'Cards carry their age, a quiet running claim is drawn stale, and per-track briefings feed one pinned agent per lane.'
vibe-areas:
- data
- renderer
- agent
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
vibe-priority: high
vibe-review-packet: ../reports/VT-007-liveness-review.html
vibe-runs:
- 'claude:VT-007/attempt-001'
vibe-commits:
- '8490224'
vibe-origin:
- 'vault: PROJECT - Vibe Tracks > Not working as I expect (Aug 25-26)'
---

# Liveness: the panel ages its own claims

## Why

The board looked alive and was not. On 2026-08-25 the Pyblocks track showed
`RUNNING 0` and `DONE 0` while an agent had been working for 41 minutes, and
nothing in the panel distinguished that from a board nobody had touched in a
week. Zach's read was exact: *"a pile of static mess. I have no confidence
it's actually driving anything."*

The mechanism: `vibe-status` is a **self-report**. The dispatcher is also the
worker, and a worker deep in a turn never stops to write `running`. The panel
had no independent oracle, so it rendered a 41-minute-old claim identically to
a live one.

## What this adds

- `touched` — the note's mtime — travels with every item, separate from the
  declarable `vibe-updated`. It is the one timestamp a busy agent cannot forge.
- The panel renders time everywhere: ages on cards and rail rows, a header
  pulse (`files changed 51 min ago`), a **stale** badge on a `running` note
  that has not changed in 15 minutes, and `nothing is reporting work` when no
  note claims to run and nothing has moved.
- **New since you last looked** — a per-board seen-marker, so a feature added
  to a 35-node graph cannot get lost in it.
- Deep-linkable views: `#kanban`, `#graph/whiteboard`.
- `vibetracks track` / `vibetracks track <area>` — lanes, and a paste-ready
  brief for one pinned agent per lane.
- `AGENT.md` now states the consequence for agents plainly: work you do not
  claim does not exist.

## Honest limit

mtime is a proxy. This can prove nobody is reporting; it cannot prove someone
is working. An agent that never claims its lane is still invisible — the panel
now just says so out loud instead of looking empty.

## Roadmap pass, 2026-10-09

Marked done by the roadmap pass: on main since `8490224`, and its rule (state from what files show, not from what agents claim) became the home's derived state (VT-054). `done` is Zach's gesture: set it back to `review` if this was not yours to close.
