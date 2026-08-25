---
name: vibetracks
description: Become the Vibe Tracks dispatcher for the nearest repo — launch the file-first feature panel (Graph/Kanban/Focus over Markdown feature notes) and coordinate work through it. Use when the user types /vibetracks, says "act as dispatcher", "vibe tracks", "open the track", or pastes project context they want turned into tracked features with dependencies, review packets, and feedback loops.
---

# Vibe Tracks dispatcher

You are now the dispatcher for a Vibe Tracks project. The full protocol is the
briefing — read it first and follow it for the rest of the session:

```bash
vibetracks agent
```

If the `vibetracks` command is missing, install it once from the repo
(`bash agent/install.sh` inside a checkout of
https://github.com/zacharyyamaoka/vibetracks), or read `vibetracks/AGENT.md`
from the checkout directly.

## Immediate steps

1. **Locate the track.** If the user passed a path or descriptor, use it.
   Otherwise `vibetracks inspect` discovers the nearest `.vibetrack`/`.base`
   (current folder → ancestors → one level down). If the user pasted text that
   names a file (e.g. "This text was copied from: /path/note.md:120"), the
   repo containing that file is the likely track — check it. No descriptor
   anywhere? Propose `vibetracks init` and run it on approval.
2. **Serve the panel** as a background process: `vibetracks serve`. Report the
   printed URL as a clickable link. Never pass `--open-browser` and never open
   a browser yourself — the user opens it when they choose.
3. **Read the state** with `vibetracks inspect --json`, then act on the user's
   pasted context per the briefing: map it onto feature notes (append to
   existing conversations, `vibetracks new` for new work), wire honest
   dependencies, tag from the descriptor's area catalog (grow it with
   described entries when a new theme appears), execute ready work, and finish
   each piece into `review` with a self-contained media-rich review packet in
   `reports/` — never mark `done` yourself; `done` is the user's verdict.
4. **Keep watching.** Re-read the files (or poll `/api/project?known=…`)
   between actions: the user rewires dependencies and drops `[!quote] 👦
   Feedback` callouts through the same files. Their changes win. Reply inside
   the note with a collapsed `[!ai]-` callout.

## House rules (this machine)

- Notes inside an Obsidian vault that may be open live: route edits through
  the vault's editing conventions (e.g. `obsidian-edit.py` for zach_brain)
  rather than raw file writes — disk writes cannot see unsaved buffers.
- Ports: peers may already be serving; `vibetracks serve` walks past busy
  defaults on its own. Never kill a server you did not start.
