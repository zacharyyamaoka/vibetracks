---
vibe-track: feature
vibe-id: VT-054
vibe-status: done
vibe-description: 'The activity spine reads Claude Code''s sessions and transcripts, no hooks; state is derived, never claimed.'
vibe-areas:
- data
- model
vibe-depends-on:
- '[[VT-007 - Liveness the panel ages its own claims]]'
vibe-priority: high
vibe-commits:
- '2384169'
- 'a5cca31'
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b1-2026-10-09/index.html'
- 'docs/peps/0001-home-surface-and-derived-state.md'
vibe-origin:
- '/home/bam/vibetracks/reports/media/vibetracks-linear-proposals-2026-10-06/index.html (#2 derived state)'
- 'vault: Daily Note - Oct 6 2026 > Linear feedback (State should be derived never claimed)'
---

# Derived state from Claude Code's own files

`vibetracks/activity/` (harness, join, derive) reads the live `sessions/<pid>.json` files and the transcripts,
with no hooks, and composes `vibetracks-home/1`. A note's `vibe-status` counts only as done or archived; every session
records how it joined its track (`join.by`). Zach (Oct 6): "agreed State should be derived never claimed".

## Where it came from

- /home/bam/vibetracks/reports/media/vibetracks-linear-proposals-2026-10-06/index.html (#2 derived state)
- vault: Daily Note - Oct 6 2026 > Linear feedback (State should be derived never claimed)
