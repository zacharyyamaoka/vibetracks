---
vibe-track: feature
vibe-id: VT-008
vibe-status: waiting
vibe-description: 'One standing prompt per track, and review packets the human answers in the page and pastes back (unmerged, never reviewed).'
vibe-areas:
- review
- agent
- renderer
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
vibe-priority: medium
vibe-commits:
- 'cef2ff9'
vibe-origin:
- 'branch wip/vt-008-uncommitted-2026-09-01 (cef2ff9)'
- 'tag archive/wip-vt-008-uncommitted-2026-09-01-2026-10-06'
- 'vault: PROJECT - Vibe Tracks > Open questions 14'
---

# Per-track agents and answerable review packets

Recovered from the unmerged branch `wip/vt-008-uncommitted-2026-09-01` (`cef2ff9`): 24 files found uncommitted in
the main checkout on Oct 5, committed verbatim so the fast-forward to the dashboard work would not overwrite them.
Never reviewed. The note as written then:

- **The track agent.** `vibetracks track <area>` prints a complete standing prompt, so one pinned session owns one
  lane; `/vibetracks-agent` sets the same thing up from inside a session.
- **The packet.** `vibetracks report` renders a self-contained HTML report with the evidence embedded and an answer
  composer (verdict, one answer per question, Copy feedback). The clipboard is the whole transport.

It is VT-005's implementation (`vibetracks/packet.py`, 497 lines). The branch is cut from the Aug 25 code and
collides with main on `pyproject.toml` and `vibetracks/edits.py`.

## Needs you

Merge, rebase or drop it. **Default: kept on its branch, unreviewed** (vault open question 14). The review surface
has since moved to Zen over `/needs` (VT-027), which may make the clipboard packet redundant.

## Where it came from

- branch wip/vt-008-uncommitted-2026-09-01 (cef2ff9)
- tag archive/wip-vt-008-uncommitted-2026-09-01-2026-10-06
- vault: PROJECT - Vibe Tracks > Open questions 14
