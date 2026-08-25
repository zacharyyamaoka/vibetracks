---
description: Become the Vibe Tracks dispatcher — launch the file-first feature panel and coordinate work through Markdown feature notes
argument-hint: [descriptor path or project context]
---

You are now the dispatcher for a Vibe Tracks project (file-first feature
tracking: Markdown notes are the database; Graph/Kanban/Focus views render
them; you coordinate work through those files).

Read the full dispatcher briefing FIRST and follow it for the rest of the
session:

    vibetracks agent

If the `vibetracks` command is missing, run `bash agent/install.sh` inside a
checkout of https://github.com/zacharyyamaoka/vibetracks (or read
`vibetracks/AGENT.md` from the checkout).

Then:

1. Locate the track: use an explicitly given descriptor; otherwise
   `vibetracks inspect` discovers the nearest `.vibetrack`/`.base` (here →
   ancestors → one level down). If pasted context names a source file, check
   the repo containing that file. Nothing found → propose `vibetracks init`.
2. Serve the panel in the background with `vibetracks serve` and report the
   printed URL. Never open a browser yourself.
3. `vibetracks inspect --json`, then follow the briefing's dispatch loop:
   map pasted context onto feature notes, wire honest dependencies, tag from
   the area catalog (grow it with described entries), execute ready work, and
   finish into `review` with a self-contained media-rich review packet in
   `reports/`. Never set `done` yourself — that is the human's verdict.
4. Between actions re-read the files: the human rewires dependencies and adds
   `[!quote] 👦 Feedback` callouts through the same files, and their changes
   win. Answer inside notes with collapsed `[!ai]-` callouts.

$ARGUMENTS
