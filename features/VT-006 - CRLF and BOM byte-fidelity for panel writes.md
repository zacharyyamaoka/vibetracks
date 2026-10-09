---
vibe-track: feature
vibe-id: VT-006
vibe-status: done
vibe-description: 'read_text universal newlines mean one status flip rewrites a CRLF note entirely to LF; revisions are computed over translated text. Needs raw-byte reads and newline-preserving transforms.'
vibe-areas:
- data
- writes
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
vibe-commits:
- 'b587822'
vibe-evidence:
- 'tests/test_edits.py'
vibe-origin:
- 'Aug 25 review of VT-002'
---

# CRLF and BOM byte-fidelity for panel writes

## Roadmap pass, 2026-10-09

Done in `b587822` (Codex round 1, finding 8, Oct 5): `edits.read_note_exact` reads bytes with no newline translation, the splicer keeps the BOM, CRLF and the delimiters exactly, writes use `newline=""`, and the fence accepts either spelling of the revision. Pinned by `tests/test_edits.py` (FrontmatterSpliceTests).
