---
vibe-track: feature
vibe-id: VT-035
vibe-status: done
vibe-description: 'A project is a .vibetrack with a name and roots: [..], so one project spans several repos.'
vibe-areas:
- project-page
- model
vibe-depends-on:
- '[[VT-054 - Derived state from Claude Code''s own files]]'
vibe-priority: high
vibe-commits:
- '1b8d244'
- '51656e4'
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b2-2026-10-09/index.html'
- 'docs/peps/0002-claude-sidebar-codex-projects.md'
vibe-origin:
- 'vault: Daily Note - Oct 6 2026 > Claude code inspired vibe tracks'
- 'vault: PROJECT - Vibe Tracks > 4 Project page'
---

# Codex-model projects, a name plus one or more folders

A project is a `.vibetrack` with `kind: project`, `roots: [..]` and an optional `name` (one folder takes that
folder's name), read by `vibetracks/home/projects.py`. Zach (Oct 9, reconfirming Oct 6): "we want to follow the CODEX
model, so we could have multi folder projecst".

## Where it came from

- vault: Daily Note - Oct 6 2026 > Claude code inspired vibe tracks
- vault: PROJECT - Vibe Tracks > 4 Project page
