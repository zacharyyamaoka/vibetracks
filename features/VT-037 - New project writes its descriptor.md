---
vibe-track: feature
vibe-id: VT-037
vibe-status: ready
vibe-description: 'The New project dialog writes workspace/projects/<name>.vibetrack instead of printing it.'
vibe-areas:
- project-page
- writes
vibe-depends-on:
- '[[VT-035 - Codex-model projects, a name plus one or more folders]]'
- '[[VT-058 - Fenced write routes from the home]]'
vibe-priority: medium
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b2-2026-10-09/index.html'
- '/home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/index.html'
vibe-origin:
- 'B2 report > Home and Next'
- '/home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/index.html (New project dialog)'
---

# New project writes its descriptor

The New project dialog takes a name and its folders, but today prints the descriptor and copies it (the
backend is read-only). Done when it writes `workspace/projects/<name>.vibetrack` and the project appears.

## Where it came from

- B2 report > Home and Next
- /home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/index.html (New project dialog)
