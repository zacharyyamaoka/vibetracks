# 0002 · Claude Code's sidebar language over Codex-model projects (B2)

- **Date:** 2026-10-09
- **Status:** built on `claude/vibetracks-home` (slice B2), not merged
- **Source:** Zach, Oct 9 (Daily Note, "# Vibe tracks feedback"): "the same visual language as the claude side bar…
  with the color and flashing dots"; Oct 6 ("# Claude code inspired vibe tracks"): "Project = Codex model: a named
  set of 1..N folders".

## Decision

1. **Look: Claude Desktop's own tokens, copied, not re-derived.** `vibetracks/home/static/tokens.css` holds the
   values read from the Desktop's HTTP cache (claude.ai `shared-styles` / `c6a992d55` sheets): row 26 px on a 28 px
   pitch, 13 px `anthropic-sans` in text-secondary, 12 px muted group headers, 6 px status dots. Dark is the
   "darker" variant Zach's Desktop renders (sidebar #121212). Where no token matched his screenshot, the observed
   value is used and marked `observed` (the selected row #343434, a 28 px leading slot, a ~11 px header inset).
2. **Dots mean what they mean in Claude, not what the brief paraphrased.** The brief said "blue = working, with the
   pulse". Claude's real CSS says: `running` = text-muted grey, blinking (`dframe-dot-blink`, 1.2 s); `ready` =
   blue (`--cds-fill-accent`, new since you last looked); `awaiting` = amber (`--cds-fill-warning`); `idle` = a
   hollow ring at 50 %; an error is a warning glyph. Zach's own screenshot agrees (grey dots on the two working
   sessions, blue on finished ones). Matching Claude is the point ("I don't want to relearn"), so the page follows the
   CSS; "new since you last looked" is per viewer (the last time this browser opened the track page).
3. **Grouping key: projects, not repos.** A project is a descriptor (`workspace/projects/*.vibetrack`, the existing
   `.vibetrack` shape) with `roots: [..]` and an optional `name` (one root: the folder's name). A session no track
   rule matches belongs to every project whose roots hold its cwd (`.claude/worktrees/…` and sibling git worktrees
   count as their root); a track join pins it to that track's project. `doc.other_sessions` still lists every such
   session once (B1's contract); `project.sessions_unpinned` lists it under each owning project.
4. **The track and project pages read their own documents** (`/home/track?id=`, `/home/project?id=`), composed from
   the inputs the last `/home` build already read, so `/home` stays under its 150 ms p95 budget.
5. **Nothing is written.** The mounts are GET-only, so New project prints the descriptor it would write, and Review
   (a placeholder pending the review proposals) copies answers as Markdown.

## Consequences

- The Anthropic Sans face is served from this machine's extracted copy (`/home/font/`), never committed; without it
  the page falls back to system-ui and the font delta shows in the report.
- Project descriptors live in this workspace, not inside their roots (those are other repos); moving them changes
  only where `vibetracks/home/projects.py` globs.
