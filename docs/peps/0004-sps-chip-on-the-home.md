# 0004 · The Stable/Preview chip on the home comes from the switcher runtime, not from the home

- **Date:** 2026-10-10
- **Status:** built on `claude/vibetracks-sps` (this repo) and `claude/sps-proxied-pages` (`/home/bam/stable_preview_switcher`); not merged
- **Source:** Zach, Oct 10: "Please add the stable preview management thing to vibe tracks; you can just use the repo
  verbatim." 0001 recorded the gap: "The sps chip is not injected into the home … Fixing that is a runtime change, not
  an app change."

## What was measured first (scratch clone, the switcher's `main` runtime)

| Page | Chip |
|---|---|
| Stable `/` → the home (`/api/plugins/vibetracks/home/`) | none: the Stable server streams proxied responses untouched |
| Stable `/?workbench` (Clank) | yes |
| Preview `/` → the home | none |
| Preview `/?workbench` (Clank) | **none either**: Preview ran Clank's own `vite.js` through the command adapter, which neither injects the chip nor answers `/__sps` (`/__sps/status` came back as Clank's `index.html`) |

So the dock opened a page with no chip, and Preview had no chip at all: no Open Preview on the page you land on, and no
Make Stable anywhere but the dock.

## Decision

1. **The runtime tags pages a backend serves (switcher contract §10.12).** When a browser opens a document
   (`GET`, `Sec-Fetch-Dest: document`) and the answer through the channel's own proxy is a complete page (200,
   `text/html`, no compression, a `Content-Length` of at most 8 MiB, UTF-8, no chip tag yet), the Stable server adds
   the release meta and the chip tag exactly as it does for its static pages, and the Vite plugin adds the chip tag on
   Preview and lanes. `fetch()` answers, iframes, curl, streamed or compressed pages keep their bytes.
2. **Preview and lanes run Clank's Vite through the switcher's own dev server** (switcher contract §10.3):
   `stable-preview.json` names `{assets}/vite/serve.mjs --root {checkout} --vite-root /home/bam/clank-workbench
   --config {checkout}/vite.vibetracks.config.mjs`. Same Vite, same wrapper config; the switcher's server is the one
   that answers `/__sps` and injects the chip.
3. **No chip code in this repo.** No chip component, no badge, no Vite plugin of ours; the page is served from the same
   URL on every channel and the Clank plugin is unchanged.
4. **The home names its theme the way the chip reads it.** The chip takes the app's shadcn token names
   (`--background`, `--foreground`, `--border`, `--muted-foreground`, `--secondary`, `--secondary-foreground`,
   `--destructive`) through inheritance, else a light neutral, so on Zach's dark home it was a white pill.
   `tokens.css` now aliases those names to the Claude tokens it already has (no value retuned); measured: the chip's
   background is the home's surface in dark (`#1a1a1a` at 90 %) and light (`#fff` at 90 %).
5. **Chip placement unchanged:** `bottom-right`, `avoid` Clank's status bar. Measured on the home (Stable and Preview;
   home, Display popover open, account menu open, scrolled to the bottom, Review, a project page, a track page) at
   1440×900 and 1280×720: 0 px² of overlap with the Display button, the account button, the settings gear, the
   sidebar's resize handle, the Display popover and the account menu. At 1440×900 nothing clickable is under the chip
   in any of those views. At 1280×720 the right end of the bottom row (the rows scroll) sits under it; the chip passes
   clicks through except on its own button.

## Options, against what had to hold

| Criterion (weight) | 1 · config only | 2 · home built into Stable's `dist` | 3 · runtime tags proxied pages + Preview on `serve.mjs` |
|---|---|---|---|
| Chip on the home in Stable, Preview and lanes (5) | no — no contract key covers proxied pages, and Preview had no chip at all | Stable only; Preview still has no chip, and Vite never transforms a page it proxies | yes, all three, measured |
| The app holds data, never chip code (4) | yes | the page's relative URLs (`doc`, `../needs`, `#/track/…`) must change, the bare-`/` redirect moves, the hub serves the page too | yes: two lines of `stable-preview.json` |
| Other adopted apps unaffected unless they serve pages through a proxy (3) | — | yes | yes: only a document navigation to a complete HTML page is touched; an app's own (already tagged) pages keep their bytes, and a page it serves through its proxy now gets the chip too |
| Reversible (2) | — | invasive | revert one config line; the runtime part is inert without a proxied page |

1 is not available; 2 does not reach Preview and rewrites the page; 3 is the runtime gap 0001 named.

## Consequences

- **Merge order:** the switcher branch first, then `sps install` (refreshes the runtime every dock icon runs), then
  this branch. With an older runtime this branch's Preview fails closed (`no vite in <checkout>`) instead of showing
  another app's chip.
- The Vibe Tracks dock keeps opening Stable; Zach's next `sps promote` (or Make Stable) after the merge is what puts
  the chip on the home he opens from the dock. A running Preview restarts once (its command changed).
- `chip.position` is one setting for the whole app, Clank pages and home alike; the home has no fixed bottom bar, so
  `avoid` needs no home selector.
