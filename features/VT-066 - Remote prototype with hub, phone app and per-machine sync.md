---
vibe-track: feature
vibe-id: VT-066
vibe-status: done
vibe-description: 'Per-host folders in a git share, a hub restoring file times, a phone-first app, Talk to agent.'
vibe-areas:
- multi-machine
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
vibe-priority: medium
vibe-commits:
- '23d9239'
- '97b3dc5'
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-remote-2026-10-06.html'
vibe-origin:
- 'vault: Daily Note - Oct 6 2026 > Vibe tracks accross computers'
- '/home/bam/vibetracks/reports/media/vibetracks-remote-2026-10-06.html'
---

# Remote prototype with hub, phone app and per-machine sync

Each machine writes only its own `hosts/<host>/` folder in a git share (single writer, so merges cannot
conflict); the hub restores file times from commit dates; "Talk to agent" is the session's Remote Control link. Zach
(Oct 6): "So git feels like a simple v1".

## Where it came from

- vault: Daily Note - Oct 6 2026 > Vibe tracks accross computers
- /home/bam/vibetracks/reports/media/vibetracks-remote-2026-10-06.html
