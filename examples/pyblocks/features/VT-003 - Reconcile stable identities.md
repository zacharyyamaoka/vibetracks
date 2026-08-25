---
vibe-track: feature
vibe-id: VT-003
vibe-status: ready
vibe-priority: high
vibe-areas: [blockview, writeback]
vibe-depends-on: ["[[VT-001 - Define source-edit envelope]]"]
vibe-description: Match edited occurrences across a fresh parse without treating Python names as permanent IDs.
---

# Reconcile stable identities

Build the smallest occurrence-matching layer required by the literal-edit kernel. The matching evidence must survive unrelated formatting and reject ambiguous duplicate-looking calls.
