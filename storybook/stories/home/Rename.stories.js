// rename.js — double-click a name to rename it, like Claude's sidebar. Esc cancels and sends nothing.
import { expect, userEvent } from 'storybook/test';
import { page, trackRoute, until, HOME } from './_page.js';
import { fetchLog } from '../../lib/home.js';

export default { title: 'Home/Interactions/Rename', parameters: HOME };

export const DoubleClickThenEscape = {
  parameters: { data: 'synthetic' },
  render: (_, ctx) => page(ctx, (set) => ({ route: trackRoute(set, { tab: 'overview' }) })),
  play: async ({ canvasElement }) => {
    const h1 = await until(() => canvasElement.querySelector('h1[data-rename^="track:"]'), 'the track title');
    const name = h1.textContent;
    h1.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    const input = await until(() => canvasElement.querySelector('[data-testid="vt-rename"]'), 'the rename input');
    // the whole name, exactly, all of it selected
    await expect(input.value).toBe(name);
    await expect([input.selectionStart, input.selectionEnd]).toEqual([0, name.length]);
    const before = fetchLog.filter((c) => c.method !== 'GET').length;
    await userEvent.keyboard('{Escape}');
    await until(() => !canvasElement.querySelector('[data-testid="vt-rename"]'), 'the input to close');
    await expect(fetchLog.filter((c) => c.method !== 'GET').length).toBe(before);
  },
};
