// core.js's public helpers, called directly: the status slot, the sparkline, state words, health and age badges.
import { expect } from 'storybook/test';
import { fixtureSet, useFixture } from './_page.js';

export default { title: 'Home/Primitives', parameters: { home: false } };
const VT = () => window.VT;
const frame = (html) => `<div class="vlm sb-pad" style="display:block;min-height:0">${html}</div>`;

/** core.js#VT.sd — Claude's status slot: awaiting · running · ready · idle · error · done · asof. */
export const StatusDots = {
  render: () => frame(`<div class="sb-row">${['awaiting', 'running', 'ready', 'idle', 'error', 'done', 'asof']
    .map((k) => `<span class="sb-row" style="gap:2px">${VT().sd(k, k)}<span>${k}</span></span>`).join('')}</div>`),
  play: async ({ canvasElement }) => {
    const dots = [...canvasElement.querySelectorAll('[data-dot]')];
    await expect(dots.map((d) => d.dataset.dot)).toEqual(['awaiting', 'running', 'ready', 'idle', 'error', 'done', 'asof']);
    // the error slot is a glyph, never a dot: Claude's warning triangle
    await expect(canvasElement.querySelector('[data-dot="error"] svg')).not.toBeNull();
    // awaiting is amber, ready is blue: measured, not assumed
    const fill = (k) => getComputedStyle(canvasElement.querySelector(`[data-dot="${k}"] i`)).backgroundColor;
    await expect(fill('awaiting')).not.toBe(fill('ready'));
  },
};

/** core.js#VT.sparkline — a null point is a gap (the pen lifts), never a zero; the target is a hairline. */
export const Sparkline = {
  args: { gap: true, target: 0.9 },
  argTypes: { target: { control: { type: 'number', step: 0.05 } } },
  render: ({ gap, target }) => {
    const pts = [0.4, 0.55, gap ? null : 0.6, 0.72, 0.81, 0.86].map((y, x) => ({ x, y }));
    return frame(`<p class="sb-cap">six readings${gap ? ', the third not taken' : ''} · target ${target}</p>${VT().sparkline(pts, { w: 220, h: 44, target })}
      <p class="sb-cap" style="margin-top:14px">no reading at all</p>${VT().sparkline([{ x: 0, y: null }, { x: 1, y: null }], { w: 220, h: 44 })}`);
  },
  play: async ({ canvasElement, args }) => {
    const [first, empty] = canvasElement.querySelectorAll('svg.spark');
    const moves = (first.querySelector('path').getAttribute('d').match(/M/g) || []).length;
    await expect(moves).toBe(args.gap ? 2 : 1);
    await expect(first.querySelector('.spark-target')).not.toBeNull();
    // nothing measured draws the "none" line, not a line at zero
    await expect(empty.querySelector('path')).toBeNull();
    await expect(empty.querySelector('.spark-none')).not.toBeNull();
  },
};

/** core.js#VT.stateWord, VT.health, VT.ageBadge — every track of the fixture, as the ledger shows its state. */
export const StateWords = {
  parameters: { home: true },
  render: (_, ctx) => {
    const set = fixtureSet(ctx.globals);
    useFixture(set);
    const tracks = set.doc.projects.flatMap((p) => p.tracks);
    return frame(`<p class="sb-cap">fixture: ${VT().esc(set.label)}</p><div style="display:grid;grid-template-columns:220px 1fr 120px;gap:6px 16px;align-items:center">${tracks.map((t) =>
      `<span class="ell">${VT().esc(t.title)}</span><span data-testid="sb-state" data-word="${VT().esc(t.state.word)}">${VT().stateWord(t)}</span><span>${VT().health(t.health.color)}</span>`).join('')}</div>
      <p class="sb-cap" style="margin-top:14px">age badges: 5 min · 3 h · 2 d · unknown (nothing)</p><div class="sb-row">${[300, 10800, 172800, null].map((s) => VT().ageBadge(s) || '<span class="faint">—</span>').join('')}</div>`);
  },
  play: async ({ canvasElement }) => {
    const words = [...canvasElement.querySelectorAll('[data-testid="sb-state"]')];
    await expect(words.length).toBeGreaterThan(0);
    // a track that needs you links to Review; no other state word is a link
    for (const w of words) await expect(!!w.querySelector('a.needs')).toBe(w.dataset.word === 'needs_you');
  },
};
