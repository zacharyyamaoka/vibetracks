---
vibe-track: feature
vibe-id: VT-059
vibe-status: ready
vibe-description: 'Move loop ledgers out of sweepable worktrees (kincal''s 12 MB ledger first); re-run or archive grasping.'
vibe-areas:
- data
vibe-priority: high
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html'
- '/home/bam/vibetracks/reports/media/vibetracks-linear-integration-2026-10-09/index.html'
vibe-origin:
- 'vault: 2026-10-06 — 75d64cb1 (CHAT) (queued task: move kincal''s ledger)'
- '/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html (Durable homes for loop files)'
- 'vault: PROJECT - Vibe Tracks > Known traps, Open questions 8'
---

# Durable homes for loop data

Ledgers in a worktree's gitignored `out/` die when the worktree is swept. Grasping's did (its track now reads
Error); kincal's 12 MB ledger (`runs.jsonl`, 348 rows) sits in the same kind of folder, in
`grasping-agent-roadmap-707400`, on an unmerged bam_ws branch.

- Move kincal's ledger to a stable data folder and point its source at it (the task queued on Oct 6).
- Grasping: re-run it into a stable folder, or archive the track. **Default: it shows Error with the reason.**

## Where it came from

- vault: 2026-10-06 — 75d64cb1 (CHAT) (queued task: move kincal's ledger)
- /home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html (Durable homes for loop files)
- vault: PROJECT - Vibe Tracks > Known traps, Open questions 8
