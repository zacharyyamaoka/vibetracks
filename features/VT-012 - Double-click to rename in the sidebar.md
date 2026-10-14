---
vibe-track: feature
vibe-id: VT-012
vibe-status: ready
vibe-description: 'Double-click a track (or session) in the sidebar to rename it in place.'
vibe-areas:
- sidebar
- writes
vibe-depends-on:
- '[[VT-009 - Sidebar in Claude Code''s visual language]]'
- '[[VT-058 - Fenced write routes from the home]]'
vibe-priority: medium
vibe-origin:
- 'vault: Daily Note - Oct 9 2026 > Vibe tracks feedback (I want to be able to double click to rename)'
---

# Double-click to rename in the sidebar

Zach (Oct 9): "I ant to be able to double click to rename", with a screenshot.

A track's title is `vibe-title` in its note, which already has a fenced writer (`registry.rename_title`, the
dashboard's `POST /tracks/<id>/title`); the home has no write route yet (VT-058). What renaming a *session* writes
(Claude's own session title?) is open.

## Where it came from

- vault: Daily Note - Oct 9 2026 > Vibe tracks feedback (I want to be able to double click to rename)
