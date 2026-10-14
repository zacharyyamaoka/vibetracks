// Parts of the track page, each isolated from the real render (see TrackPage.stories.js).
import { expect } from 'storybook/test';
import { page, trackRoute, until, HOME } from './_page.js';

export default { title: 'Home/Parts/Track', parameters: HOME };
const part = (tab, focus, prefs, want) => (_, ctx) => page(ctx, (set) => ({ route: trackRoute(set, { tab }, want), prefs: Object.assign({ trackTab: tab }, prefs || {}), focus, sidebar: true }));
const has = (key) => (d) => ((d.kpis || {})[key] || []).length > 0;
const found = (root) => until(() => root.querySelector('#vt-home[data-part]'), 'the part').then(() =>
  until(() => root.querySelector('#vt-home').dataset.part === 'found' && root.querySelector('[data-testid="sb-part"]'), 'the part on this fixture\'s page', 6000));

/** track.js#kpiCards — every soft KPI side by side, north star first; "not measured yet" when nothing was read. */
export const KpiCards = {
  render: part('overview', '.pg-kcards', null, has('soft')),
  play: async ({ canvasElement }) => {
    await found(canvasElement);
    const cards = [...canvasElement.querySelectorAll('[data-testid="vt-kpi-card"]')];
    await expect(cards.length).toBeGreaterThan(0);
    // a card with no measured reading says so in words, never "0"
    for (const c of cards) {
      const v = c.querySelector('.pg-kv');
      if (v.querySelector('.unk-big')) await expect(v.textContent.trim()).toBe('not measured yet');
    }
  },
};
/** track.js#kpiRows — the same KPIs as rows (K). */
export const KpiRows = { render: part('overview', '.pg-krows', { kpiView: 'rows' }, has('soft')) };
/** track.js#gates — pass / fail / unknown, never averaged in. */
export const HardGates = {
  render: part('overview', '.pg-gates', null, has('gates')),
  play: async ({ canvasElement }) => {
    await found(canvasElement);
    for (const g of canvasElement.querySelectorAll('[data-testid="vt-gate"]')) await expect(['true', 'false', 'unknown']).toContain(g.dataset.pass);
  },
};
/** track.js#roadmap — the rung ladder from the roadmap projector (real fixture: a track that has one). */
export const RungLadder = { render: part('overview', '.pg-road', null, (d, set) => !!set.get(`roadmap.${d.track.id}.json`)) };
/** track.js#activity — the read-only timeline, newest first. */
export const Timeline = { render: part('activity', '.pg-tl') };
/** track.js#worked — agent hours per day (not a KPI). */
export const AgentHours = { render: part('activity', '.pg-days') };
/** track.js#agentsTab — who works this track, on which account and model, and how they were joined. */
export const AgentsTable = { render: part('agents', '[data-testid="vt-track-agents"]') };
/** track.js#auditorTab — audit rounds and their verdicts. */
export const AuditRounds = { render: part('auditor', '.pg-aus', null, (d) => ((d.audits || {}).rounds || []).length > 0) };
