---
vibe-track: feature
vibe-id: VT-001
vibe-status: done
vibe-description: 'Codex V0: Base-compatible loading, Graph/Kanban/Focus, fenced status writes, pyblocks example.'
vibe-areas:
- data
- renderer
- model
vibe-commits:
- '9d95e71'
vibe-origin:
- 'Codex session 01a03921 (Aug 25)'
---

# File-first renderer V0

Shipped by the original Codex session (01a03921). Nine-feature example, seven tests, real-browser QA. Superseded in detail by VT-002 but the architecture decisions (files are the database, one schema with .base/.vibetrack extensions) all originate here.

## Roadmap pass, 2026-10-09

Landed as `9d95e71`; its rule (the files are the database) is still the base of every surface since.
