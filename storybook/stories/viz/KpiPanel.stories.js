// VT.ui.kpiPanel (vibetracks/home/static/kpi-panel.js): a project's trailing, outside-view KPIs. A pure part:
// spec in, HTML string out. Plays check the truthful states: not measured is words (never 0), modelled says so.
import { expect } from 'storybook/test';
import base from '../../fixtures/synthetic/project-kpis.bam-today.json';
import illustrative from '../../fixtures/synthetic/project-kpis.illustrative.json';

const local = Object.values(import.meta.glob('../../fixtures/local/project-kpis.bam-robotics.json', { eager: true, import: 'default' }))[0] || null;
export default { title: 'Viz/Project KPI panel', parameters: { home: false } };

/** The committed definitions, overlaid with the local modelled values when this machine has them. */
function bamToday(useLocal) {
  const spec = JSON.parse(JSON.stringify(base));
  if (useLocal && local) {
    for (const g of spec.groups) for (const k of g.kpis) Object.assign(k, local.kpis[k.id] || {});
    spec.foot = local.foot;
    spec.as_of = local.as_of;
  }
  return spec;
}
const frame = (html, chip) => {
  const el = document.createElement('div');
  el.className = 'sb-pad';
  el.style.maxWidth = '1180px';
  el.innerHTML = html + (chip ? `<div class="sb-fixture">${chip}</div>` : '');
  return el;
};
const tiles = (root) => [...root.querySelectorAll('[data-testid="vt-kpi-tile"]')];

async function truthful(root) {
  for (const t of tiles(root)) {
    const v = t.querySelector('.kp-v');
    if (t.dataset.measured === 'false') {
      // not measured is said in words, with what to record; never a number, never 0
      await expect(v.textContent.trim()).toBe('not measured yet');
      await expect(v.querySelector('b')).toBeNull();
      await expect(t.querySelector('.kp-rec')).not.toBeNull();
    }
    if (t.dataset.basis === 'modelled') await expect(t.querySelector('.kp-basis .modelled')).not.toBeNull();
  }
}

/** BAM Robotics today: nothing measured; modelled unit economics (local overlay) labelled and flagged. */
export const BamToday = {
  name: 'BAM Robotics · today',
  render: () => frame(window.VT.ui.kpiPanel(bamToday(true)), `fixture: ${local ? 'committed definitions + local modelled overlay (fixtures/local)' : 'committed definitions only (no local overlay on this machine)'}`),
  play: async ({ canvasElement }) => {
    await truthful(canvasElement);
    const impact = canvasElement.querySelector('[data-group="impact"] [data-testid="vt-kpi-tile"]');
    await expect(impact.dataset.kpiId).toBe('profit_per_tonne');   // the north star leads
    // nothing at BAM is a measurement yet
    await expect(tiles(canvasElement).filter((t) => t.dataset.basis === 'measured').length).toBe(0);
    // the one number with no instrument: 0 t diverted, because no site exists; it says so
    const tonnes = canvasElement.querySelector('[data-kpi-id="tonnes_diverted"]');
    await expect(tonnes.querySelector('.kp-v b').textContent).toBe('0');
    await expect(tonnes.textContent).toMatch(/No BAM site is deployed/);
    if (local) {
      const p = canvasElement.querySelector('[data-kpi-id="profit_per_tonne"]');
      await expect(p.dataset.basis).toBe('modelled');
      await expect(p.querySelector('.kp-basis .flag')).not.toBeNull();   // the untrusted-rung flag rides on the number
    }
  },
};

/** What a fresh clone shows: the public definitions, every KPI "not measured yet" with what to record. */
export const BamTodayPublic = {
  name: 'BAM Robotics · today (public)',
  render: () => frame(window.VT.ui.kpiPanel(bamToday(false)), 'fixture: committed definitions only'),
  play: async ({ canvasElement }) => {
    await truthful(canvasElement);
    await expect(tiles(canvasElement).filter((t) => t.dataset.measured === 'false').length).toBe(tiles(canvasElement).length - 1);
  },
};

/** The filled design, with made-up numbers, labelled as such on the panel itself. */
export const Illustrative = {
  name: 'Illustrative · filled',
  render: () => frame(window.VT.ui.kpiPanel(illustrative)),
  play: async ({ canvasElement }) => {
    await truthful(canvasElement);
    await expect(canvasElement.querySelector('[data-testid="vt-kpi-illustrative"]')).not.toBeNull();
    // a reading not taken is a gap in the sparkline (the pen lifts), not a dip to zero
    const d = canvasElement.querySelector('[data-kpi-id="profit_per_tonne"] svg.spark path').getAttribute('d');
    await expect((d.match(/M/g) || []).length).toBe(2);
    // money keeps its sign and its unit: −$18.5k a month, not 18500
    await expect(canvasElement.querySelector('[data-kpi-id="net_income"] .kp-v').textContent).toMatch(/^−\$18\.5k/);
  },
};

/** One tile in each state, side by side: measured, modelled (range, n/N, flag), known without an instrument, not measured. */
export const TileStates = {
  name: 'Tile states',
  render: () => frame(window.VT.ui.kpiPanel({ title: 'Tile states', groups: [{ id: 'states', label: 'Every state a KPI can be in', kpis: [
    { id: 'measured', label: 'Measured, with a trend', unit: '%', better: 'higher', basis: 'measured', value: 96.2, target: { value: 95, label: '≥ 95%' },
      series: [91.5, 93, null, 95.4, 95.9, 96.2].map((value, i) => ({ date: `2027-0${i + 1}-01`, value })) },
    { id: 'modelled', label: 'Modelled, not measured', unit: 'USD/t', better: 'lower', basis: 'modelled', value: 41.2, low: 33, high: 58.5,
      inputs_measured: { n: 7, of: 12 }, flags: ['labour rate from one pilot week'], record: 'the cost ledger ÷ weigh-scale tonnes' },
    { id: 'known', label: 'Known, no instrument', unit: 't/week', better: 'higher', basis: 'known', value: 0, note: 'No site is deployed, so this is a known 0.' },
    { id: 'none', label: 'Not measured yet', unit: 'count', better: 'higher', basis: 'none', value: null, record: 'bale grades per stream from the buyers' },
  ] }] }, { head: false })),
  play: async ({ canvasElement }) => {
    await truthful(canvasElement);
    const by = (id) => canvasElement.querySelector(`[data-kpi-id="${id}"]`);
    await expect(by('modelled').querySelector('.range').textContent).toBe('range $33.00 / t to $58.50 / t');
    await expect(by('modelled').querySelector('.modelled').textContent).toMatch(/inputs measured 7\/12/);
    await expect(by('none').querySelector('.kp-spark')).toBeNull();
    await expect(by('measured').querySelector('.kp-basis .measured')).not.toBeNull();
  },
};
