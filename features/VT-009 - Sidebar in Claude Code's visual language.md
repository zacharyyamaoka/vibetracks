---
vibe-track: feature
vibe-id: VT-009
vibe-status: done
vibe-description: 'Claude Desktop''s own sidebar CSS: 26 px rows, the status dots and blink, project headers, account bottom-left, phone drawer.'
vibe-areas:
- sidebar
- renderer
vibe-depends-on:
- '[[VT-054 - Derived state from Claude Code''s own files]]'
- '[[VT-035 - Codex-model projects, a name plus one or more folders]]'
vibe-priority: high
vibe-commits:
- '6695008'
- '6f4bb0f'
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b2-2026-10-09/index.html'
- 'docs/peps/0002-claude-sidebar-codex-projects.md'
vibe-origin:
- 'vault: Daily Note - Oct 9 2026 > Vibe tracks feedback'
- 'vault: PROJECT - Vibe Tracks > 1 Sidebar'
---

# Sidebar in Claude Code's visual language

The always-on sidebar copies Claude Desktop's own CSS (26 px rows, 13 px anthropic-sans, the dot colours, the
1.2 s blink), with projects as collapsible headers, their tracks under them, the account button bottom-left, and a
drawer at phone width. B2, merged in `d0b4b5a`.

Zach (Oct 9): "I don't want to have to relearn a new side bar... I am in claude code alot anyways".

The dots follow Claude's real meaning, not the first brief: grey blinking = working, blue = new since you looked,
amber = waiting on you, hollow = idle. Keeping Claude's meaning is the default (B2 report, "Next").

## Where it came from

- vault: Daily Note - Oct 9 2026 > Vibe tracks feedback
- vault: PROJECT - Vibe Tracks > 1 Sidebar
