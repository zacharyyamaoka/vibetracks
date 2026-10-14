---
vibe-track: feature
vibe-id: VT-061
vibe-status: backlog
vibe-description: 'Read kinsim''s triage.json from git (an @git: source form), so its needs stop reading null.'
vibe-areas:
- data
vibe-depends-on:
- '[[VT-056 - Needs-you documents]]'
vibe-priority: low
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b1-2026-10-09/index.html'
vibe-origin:
- 'B1 report > What''s unknown'
---

# Kinsim needs read from git

Kinsim's "needs you" reads null because its `triage.json` exists only in git, not on disk. Needs an `@git:` form
in the sources map.

## Where it came from

- B1 report > What's unknown
