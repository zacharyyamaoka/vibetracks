---
vibe-track: feature
vibe-id: VT-068
vibe-status: running
vibe-description: 'The home also reads other machines'' sessions from vibetracks-share, live only as of each host''s sync.'
vibe-areas:
- multi-machine
- home
vibe-depends-on:
- '[[VT-067 - Remote v1 with quiet workers, Refresh and setup-machine]]'
- '[[VT-017 - Home on derived state, the Linear initiatives table]]'
vibe-priority: high
vibe-origin:
- 'Daily Note Oct 9 round-4 callout (agent 1)'
- 'lane claude/vibetracks-home-r3'
---

# The home reads other machines' sessions

The new home sees only this machine's sessions. It reads other machines' data from `vibetracks-share`, labelled
by host; a remote session counts as live only as of its host's last sync. Being built on `claude/vibetracks-home-r3`.

## Where it came from

- Daily Note Oct 9 round-4 callout (agent 1)
- lane claude/vibetracks-home-r3
