---
vibe-track: feature
vibe-id: VT-002
vibe-status: review
vibe-priority: urgent
vibe-areas: [writeback, round-trip]
vibe-depends-on:
  - "[[VT-001 - Define source-edit envelope]]"
vibe-description: First closed reverse-pass kernel for changing one existing literal argument.
vibe-review-packet: ../reports/literal-writer-review.html
vibe-preview: ../assets/literal-writer-proof.svg
vibe-evidence:
  - ../evidence/literal-writer-tests.txt
vibe-runs:
  - codex:literal-writer/attempt-003
  - claude:literal-writer/critic-001
---

# Implement literal writer

The candidate replaces exactly one owned literal token, reparses the file, and compares a fresh forward projection with the requested semantic result.

## Review question

Should V1 permit only an existing literal argument and reject all expression-shaped replacements?

![[../assets/literal-writer-proof.svg]]
