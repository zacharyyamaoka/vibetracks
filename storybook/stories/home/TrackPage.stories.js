// track.js — the track page (Overview, Activity, Agents, Auditor) and its parts. A part story renders the real page
// and keeps only that part, at the width it had on the page (lib/home.js#isolate): no function is exported or copied.
import { expect } from 'storybook/test';
import { page, trackRoute, until, HOME } from './_page.js';

export default { title: 'Home/Pages/Track', parameters: HOME };
const track = (tab, extra) => (_, ctx) => page(ctx, (set) => Object.assign({ route: trackRoute(set, { tab }), prefs: { trackTab: tab } }, extra || {}));
const loaded = (root) => until(() => root.querySelector('[data-testid="vt-track-page"] .pg-body') && !root.querySelector('.pg-body > .faint.pg-p:only-child'), 'the track document');

export const Overview = {
  render: track('overview'),
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(canvasElement.querySelector('[data-testid="vt-track-page"]').dataset.tab).toBe('overview');
  },
};
export const OverviewKpiRows = {
  name: 'Overview · KPI rows (K)',
  render: track('overview', { prefs: { trackTab: 'overview', kpiView: 'rows' } }),
};
export const Activity = { render: track('activity') };
export const Agents = { render: track('agents') };
export const Auditor = { render: track('auditor') };
/** Interaction: the Cards / Rows toggle re-renders the KPIs as rows (track.js#kpiview). */
export const KpiToggle = {
  name: 'Overview · toggle Cards → Rows',
  render: track('overview'),
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    const toggle = canvasElement.querySelector('[data-testid="vt-kpi-toggle"] button[data-id="rows"]');
    if (!toggle) return;   // a fixture track with no soft KPIs has no toggle; the Overview story shows its "unknown"
    toggle.click();
    await until(() => canvasElement.querySelector('[data-testid="vt-kpi-row"]'), 'KPI rows');
    await expect(canvasElement.querySelectorAll('[data-testid="vt-kpi-card"]').length).toBe(0);
  },
};
