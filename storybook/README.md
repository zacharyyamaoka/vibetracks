# Vibe Tracks storyboard

The component catalogue for Vibe Tracks (Zach, Oct 10: "start a storyboard so we can ensure we are taking a
component based approach … get the map working once and then we can reuse it"). Storybook 10 with the **html**
renderer: the home is plain strings and DOM, so a story renders the home's real files from
`vibetracks/home/static/` unchanged (no React wrapper, no copy). Dev-only: the home itself stays a no-build page.

```bash
npm --prefix /home/bam/vibetracks-storybook/storybook run storybook
```

Then http://127.0.0.1:6126/. Toolbar: **Theme** (dark / light, html[data-theme] as the home's own setting) and
**Data** (real / synthetic).

| Command (`npm --prefix /home/bam/vibetracks-storybook/storybook run …`) | What it does |
|---|---|
| `storybook` | dev server on 127.0.0.1:6126 |
| `test` | every story in headless Chromium: renders, play functions, axe at `error` |
| `build-storybook` | static build in `storybook-static/` (gitignored; holds real data if captured) |
| `shots` | screenshots every story, dark and light, from the static build (see `scripts/shoot.mjs`) |
| `fixtures` | rebuilds the committed synthetic fixtures with the home's own code |
| `capture` | captures real fixtures from a running home, GET only (default Stable :4394), into gitignored `fixtures/real/` |
| `geo` | rebuilds the map's boundary files: countries and provinces from Natural Earth, BC's waste reporting districts from the BC Data Catalogue (no Statistics Canada boundaries) |

## Two kinds of component

- **Part**: a pure function `(data, opts) → HTML string`, like everything in the home today (`VT.sd`,
  `VT.sparkline`, `VT.ui.kpiPanel`). No lifecycle, so it survives the home's whole-page `innerHTML` re-render.
- **Island**: a custom element (`<vt-map>`) for anything stateful or WebGL. Data goes in as a `.spec` property;
  selections come out as bubbling events. It works unchanged in the vanilla home, in React 19 (Clank) and here.

A new visualization is born in `stories/viz/` with its states (real data, illustrative data, not measured,
light and dark) and play assertions, then the home wires the same file.

## Data

- `fixtures/synthetic/`: committed. Built by `scripts/make_fixtures.py` from `tests/fixtures/home` with
  `compose.build_home` / `detail.build_*`, the same inputs as `tests/test_home_detail.py`; paths normalised.
- `fixtures/real/`: gitignored (BAM loop data; the repo is public). A chip on every page story names the set.
  Stable runs the main build, so r3-only fields (revisions) are absent there: the rename story pins synthetic.
- `fixtures/public/`: committed open data for the viz stories, each file with a `.source.json` (URL, licence,
  retrieved date, definition).
- `VITE_VT_SB_DATA=synthetic npm --prefix … test` runs everything on the committed set, as a fresh clone would.

## Accessibility

New components fail the gate on any axe violation. The existing home stories report but do not fail
(`stories/home/_page.js`): axe flags Claude Desktop's own muted ink below 4.5:1, which tokens.css copies verbatim on
purpose; retuning it is Zach's call.
