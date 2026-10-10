// <vt-map> under REAL input (Chromium's own mouse and keyboard, see realInput in _map.js). These plays exist because
// the first two interaction bugs of the map (a period slider that moved one step and stopped, a tooltip that stayed
// over the next level) were invisible to plays that set `.value` or dispatch synthetic events.
import { expect } from 'storybook/test';
import { mountMap, mapOf, ready, until, realInput } from './_map.js';
import { cesiRows, bcRows, LEVELS, DIVERSION, BOUNDARY_NOTE } from './data.js';

export default { title: 'Viz/Map real input', parameters: { home: false } };

const spec = (extra) => Object.assign({ metric: DIVERSION, levels: LEVELS, values: cesiRows().concat(bcRows()), sources: [BOUNDARY_NOTE] }, extra);
const frames = (n = 3) => new Promise((r) => { const tick = (i) => (i ? requestAnimationFrame(() => tick(i - 1)) : r()); tick(n); });
const BC = [-123.5, 54.5], METRO = [-122.95, 49.25];

/** Centre of the slider thumb for period index i (Chromium's range thumb is 16 px wide). */
const thumbX = (range, i) => { const r = range.getBoundingClientRect(), th = 16; return r.left + th / 2 + ((r.width - th) * i) / +range.max; };
const yearOf = (el) => el.dataset.period;

export const SliderDrag = {
  name: 'Period slider · a 20-step real drag follows the pointer',
  render: () => mountMap(spec({ view: { level: 'district', focus: 'CA-BC' } }), { period: '2010' }),
  play: async ({ canvasElement }) => {
    const input = await realInput();
    if (!input) return;
    const el = await ready(mapOf(canvasElement));
    const range = el.querySelector('.vtm-period input[type=range]');
    const idx = (y) => el._periods.indexOf(String(y));
    await expect(yearOf(el)).toBe('2010');
    // 2010 -> 1996 in 20 mouse moves with the button held (bug: the thumb stopped after one step, at 2009 or 2008)
    const r = range.getBoundingClientRect(), y = r.top + r.height / 2;
    const from = thumbX(range, idx(2010)), to = thumbX(range, idx(1996));
    await input.move(from, y);
    await input.down();
    let last = null;
    for (let s = 1; s <= 20; s++) {
      await input.move(from + ((to - from) * s) / 20, y, 1, true);
      last = range.value;
    }
    await input.up();
    await until(() => el.dataset.state === 'ready', 'the map after the drag');
    await el.whenReady();
    await expect(+last).toBeLessThan(idx(2010) - 10);
    await expect(Math.abs(idx(yearOf(el)) - idx(1996))).toBeLessThanOrEqual(1);
    await expect(el.querySelector('.vtm-period output').textContent).toBe(yearOf(el));
    await expect(range.getAttribute('aria-valuetext')).toBe(yearOf(el));
    await expect(el.querySelector('.vtm-period input[type=range]')).toBe(range);   // the same control, never rebuilt
  },
};

export const SliderArrowKeys = {
  name: 'Period slider · focus stays, ArrowLeft x3 steps three years',
  render: () => mountMap(spec({ view: { level: 'district', focus: 'CA-BC' } }), { period: '2010' }),
  play: async ({ canvasElement }) => {
    const input = await realInput();
    if (!input) return;
    const el = await ready(mapOf(canvasElement));
    const range = el.querySelector('.vtm-period input[type=range]');
    const idx = (y) => el._periods.indexOf(String(y));
    range.focus();
    await expect(document.activeElement).toBe(range);
    // bug: focus left the slider after the first press, so the next two presses went nowhere (2009 three times)
    for (let n = 1; n <= 3; n++) {
      const before = idx(yearOf(el));
      await input.userEvent.keyboard('{ArrowLeft}');
      await until(() => idx(yearOf(el)) === before - 1 && el.dataset.state === 'ready', `year ${el._periods[before - 1]} after ArrowLeft ${n}`);
      await expect(document.activeElement).toBe(range);
    }
    await expect(yearOf(el)).toBe('2007');
    await expect(el.querySelector('.vtm-period input[type=range]')).toBe(range);
  },
};

export const TooltipClearsOnDrill = {
  name: 'Tooltip · cleared when you drill in',
  render: () => mountMap(spec({ view: { level: 'province', focus: 'CAN' } })),
  play: async ({ canvasElement }) => {
    const input = await realInput();
    if (!input) return;
    const el = await ready(mapOf(canvasElement));
    const tip = el.querySelector('.vtm-tip');
    const [x, y] = input.lonLat(el, BC);
    await input.move(x - 30, y - 30);
    await input.move(x, y, 4);
    await until(() => !tip.hidden && /British Columbia/.test(tip.textContent), 'the BC tooltip');
    await input.down();
    await input.up();                       // the pointer stays where it is: no mousemove follows the click
    await until(() => el.dataset.level === 'district' && el.dataset.state === 'ready', 'BC\'s districts');
    await el.whenReady();
    await frames();
    await expect(tip.hidden).toBe(true);
  },
};

export const TooltipClearsOnBreadcrumb = {
  name: 'Tooltip · cleared on breadcrumb navigation',
  render: () => mountMap(spec({ view: { level: 'district', focus: 'CA-BC' } })),
  play: async ({ canvasElement }) => {
    const input = await realInput();
    if (!input) return;
    const el = await ready(mapOf(canvasElement));
    const tip = el.querySelector('.vtm-tip');
    const [x, y] = input.lonLat(el, METRO);
    await input.move(x - 20, y - 20);
    await input.move(x, y, 4);
    await until(() => !tip.hidden && /Metro Vancouver/.test(tip.textContent), 'the Metro Vancouver tooltip');
    // the keyboard path up: the pointer rests on the map while the breadcrumb is used
    el.querySelector('.vtm-crumb button[data-level="1"]').focus();
    await input.userEvent.keyboard('{Enter}');
    await until(() => el.dataset.level === 'province' && el.dataset.state === 'ready', 'back to provinces');
    await el.whenReady();
    await frames();
    await expect(tip.hidden).toBe(true);
  },
};
