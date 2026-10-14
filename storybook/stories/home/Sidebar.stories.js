// sidebar.js — Claude-style sidebar: Home, Review (with its count), tracks grouped by project, "Other" sessions.
import { expect } from 'storybook/test';
import { page, HOME } from './_page.js';

export default { title: 'Home/Parts/Sidebar', parameters: HOME };

export const Sidebar = {
  render: (_, ctx) => page(ctx, { route: { name: 'home' }, part: 'sidebar' }),
  play: async ({ canvasElement }) => {
    const side = canvasElement.querySelector('[data-testid="vt-home-sidebar"]');
    await expect(side).not.toBeNull();
    // Claude's row pitch: 26 px rows (tokens.css --row-h), measured
    const row = side.querySelector('[data-testid="vt-side-home"]');
    await expect(Math.round(row.getBoundingClientRect().height)).toBe(26);
  },
};
/** The account menu (Settings, theme, accounts on this machine) open. */
export const AccountMenu = {
  render: (_, ctx) => page(ctx, { route: { name: 'home' }, prefs: { view: 'rows' }, pop: 'acct' }),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-testid="vt-home-settings"]')).not.toBeNull();
  },
};
