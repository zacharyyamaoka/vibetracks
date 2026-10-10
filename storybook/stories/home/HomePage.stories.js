// views.js — the Home ledger in its four views (Rows, Table, Board, Cards) and the Display popover, with the
// sidebar beside it, exactly as app.js renders the page.
import { expect } from 'storybook/test';
import { page, HOME } from './_page.js';

export default { title: 'Home/Pages/Home', parameters: HOME };
const home = (view, extra) => (_, ctx) => page(ctx, Object.assign({ route: { name: 'home' }, prefs: { view, tabset: 'all' } }, extra || {}));
const tracksIn = (root) => window.VT.doc.projects.flatMap((p) => p.tracks).length;

export const Rows = {
  render: home('rows'),
  play: async ({ canvasElement }) => {
    const rows = canvasElement.querySelectorAll('[data-testid="vt-home-track"]');
    await expect(rows.length).toBe(tracksIn(canvasElement));
    // one grid: every row's State cell starts on the same pixel column
    const lefts = new Set([...canvasElement.querySelectorAll('[data-testid="vt-home-track"] .c-state')].map((c) => Math.round(c.getBoundingClientRect().left)));
    await expect(lefts.size).toBe(1);
  },
};
export const Table = { render: home('table') };
export const Board = {
  render: home('board'),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-testid="vt-home-board"]')).not.toBeNull();
    await expect(canvasElement.querySelectorAll('[data-testid="vt-home-lane"]').length).toBeGreaterThan(0);
  },
};
export const Cards = { render: home('cards') };
/** The Display popover open over Rows (views.js#displayPop). */
export const DisplayPopover = {
  render: home('rows', { pop: 'display' }),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-testid="vt-home-display"]')).not.toBeNull();
  },
};
