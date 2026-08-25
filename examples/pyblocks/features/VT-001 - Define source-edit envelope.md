---
vibe-track: feature
vibe-id: VT-001
vibe-status: done
vibe-priority: high
vibe-areas: [writeback, contracts]
vibe-description: Define revision, ownership, semantic command, and structured refusal fields.
vibe-runs: [codex:01a03921/envelope]
---

# Define source-edit envelope

The source-edit command carries a subject, semantic intent, base revision, and ownership evidence. Unsupported or stale edits return a structured refusal and write nothing.

## Accepted decision

- Revision checks happen before mutation.
- The writer owns a narrow source span.
- A fresh forward projection proves the result.
