---
vibe-track: feature
vibe-id: VT-004
vibe-status: backlog
vibe-description: 'Replace polling (the home every 10 s, the roadmap every 30 s) with file watching and server-sent events, so a page shows an agent''s write at once.'
vibe-areas:
- data
- renderer
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
- '[[VT-017 - Home on derived state, the Linear initiatives table]]'
vibe-priority: medium
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b1-2026-10-09/index.html'
vibe-origin:
- 'Aug 25 plan'
- 'B1 report > Left for B2 (push updates instead of polling)'
---

# File watching and SSE

## Roadmap pass, 2026-10-09

Re-scoped from the Aug 25 panel to the home: B1 and B2 left "push updates instead of polling" open, and `vibetracks/home/static/app.js` still calls `setInterval`. The remote hub already serves server-sent events (`/api/events`, `23d9239`), which is the pattern to reuse. A lane's Vite server has died when inotify ran out watching agent worktrees, so watch only the files a page reads.
