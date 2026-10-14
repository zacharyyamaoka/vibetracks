---
vibe-track: feature
vibe-id: VT-058
vibe-status: ready
vibe-description: 'Fenced, revision-checked write routes from the home, one per write, extending the panel''s three note writes.'
vibe-areas:
- data
- writes
vibe-depends-on:
- '[[VT-054 - Derived state from Claude Code''s own files]]'
vibe-priority: high
vibe-evidence:
- 'docs/peps/0001-home-surface-and-derived-state.md'
vibe-origin:
- 'B1 and B2 reports (the backend is read-only by design)'
- 'vault: Daily Note - Oct 9 2026 > Vibe tracks feedback (rename, reassign)'
---

# Fenced write routes from the home

The home's backend is read-only (pep 0001). Rename (VT-012), reassign a session (VT-013), Board writes (VT-025),
answers (VT-029), snooze (VT-032), New project (VT-037), discussion (VT-051) and phone writes (VT-073) all need a
write. The panel already has three fenced, revision-checked note writes (`edits.py`); this extends that pattern to
the home, one route per write, each a fenced edit of a file.

Needs a decision record first (which writes, which files, how a stale revision is refused).

## Where it came from

- B1 and B2 reports (the backend is read-only by design)
- vault: Daily Note - Oct 9 2026 > Vibe tracks feedback (rename, reassign)
