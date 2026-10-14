/* Vibe Tracks · project KPI panel (2026-10-10): a project's trailing, outside-view KPIs (Zach, Oct 10: "I have the
   project BAM ROBOTICS, and yes I will essentially have some top KPIs (mostly like trailing indicators) … on the
   project page I want to see those"). Loop activity (packages, audits, hours, disk) stays one click deeper.

   A PART, not an island: VT.ui.kpiPanel(spec, opts) -> HTML string, like the home's own helpers, so it survives the
   home's whole-page re-render. Needs core.js (VT.esc, VT.sparkline) and viz.css. Built in the storyboard
   (storybook/stories/viz/KpiPanel.stories.js); the project page does not show it yet (wiring is the next step).

   spec (vibetracks-project-kpis/0, a file a model or a ledger writes; Vibe Tracks only renders it):
     { title, subtitle?, as_of?, illustrative?: bool, groups: [{ id, label, note?, kpis: [kpi] }], foot? }
     kpi: { id, label, unit, better: 'higher'|'lower', north_star?, basis: 'measured'|'modelled'|'known'|'none',
            value: number|null, low?, high?, inputs_measured?: {n, of}, flags?: [string], target?: {value?, label},
            series?: [{date, value|null}], as_of?, source?, definition?, record?, beside?: {label, value, unit}, note? }
   TRUTHFUL BY CONSTRUCTION: value null renders "not measured yet" plus what must be recorded, never 0 and never a
   blank; 'modelled' is a modelled number and says so (with its range and its flags); 'known' is a fact that needs no
   instrument (0 t diverted: no site is deployed); only 'measured' is a measurement. A null in a series is a gap. */
(function () {
  'use strict';
  const VT = (window.VT = window.VT || {});
  const esc = (s) => (VT.esc ? VT.esc(s) : String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const MINUS = '−';

  /** The number and its unit, split (the number is big, the unit small). Money keeps its $ with the number. */
  function parts(v, unit) {
    if (v == null || !isFinite(v)) return null;
    const neg = v < 0, a = Math.abs(v);
    const num = (x, d) => x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    const sign = neg ? MINUS : '';
    if (unit === 'USD' || unit === 'USD/month') {
      const s = a >= 1e6 ? `${num(a / 1e6, 1)}M` : a >= 1e5 ? `${num(a / 1e3, 0)}k` : a >= 1e4 ? `${num(a / 1e3, 1)}k` : num(a, 0);
      return { n: `${sign}$${s}`, u: unit === 'USD/month' ? '/ month' : '' };
    }
    if (unit === 'USD/t') return { n: `${sign}$${num(a, 2)}`, u: '/ t' };
    if (unit === '%') return { n: `${sign}${num(a, 1)}%`, u: '' };
    if (unit === 'bool') return { n: v ? 'yes' : 'no', u: '' };
    const d = Number.isInteger(v) ? 0 : a >= 100 ? 0 : 1;
    return { n: `${sign}${num(a, d)}`, u: unit === 'count' ? '' : unit || '' };
  }
  const text = (v, unit) => { const p = parts(v, unit); return p ? `${p.n}${p.u ? ' ' + p.u : ''}` : ''; };

  function valueHtml(k) {
    const p = parts(k.value, k.unit);
    if (!p) return `<div class="kp-v"><span class="nm">not measured yet</span></div>`;
    const range = k.low != null && k.high != null ? `<span class="range">range ${esc(text(k.low, k.unit))} to ${esc(text(k.high, k.unit))}</span>` : '';
    return `<div class="kp-v"><b>${esc(p.n)}</b>${p.u ? `<span class="u">${esc(p.u)}</span>` : ''}${range}</div>`;
  }
  function basisHtml(k) {
    const out = [];
    if (k.basis === 'measured') out.push('<span class="b measured">measured</span>');
    else if (k.basis === 'modelled') out.push(`<span class="b modelled">modelled${k.inputs_measured ? ` · inputs measured ${esc(k.inputs_measured.n)}/${esc(k.inputs_measured.of)}` : ''}</span>`);
    else if (k.basis === 'known') out.push('<span class="b">known, no instrument</span>');
    for (const f of k.flags || []) out.push(`<span class="b flag">${esc(f)}</span>`);
    return out.length ? `<div class="kp-basis">${out.join('')}</div>` : '';
  }
  function sparkHtml(k) {
    const s = (k.series || []).map((p, i) => ({ x: i, y: p.value == null ? null : p.value }));
    if (s.filter((p) => p.y != null).length < 2 || !VT.sparkline) return '';
    const tv = k.target && typeof k.target.value === 'number' ? k.target.value : null;
    return `<div class="kp-spark" title="${esc(`${s.length} readings${k.series.some((p) => p.value == null) ? ', gaps are readings not taken' : ''}`)}">${VT.sparkline(s, { w: 200, h: 30, target: tv })}</div>`;
  }
  function tile(k) {
    const dir = k.better === 'lower' ? '↓ lower is better' : k.better === 'higher' ? '↑ higher is better' : '';
    const target = k.target ? `target ${k.target.label || text(k.target.value, k.unit)}` : '';
    const unmeasured = k.value == null || k.basis === 'modelled';
    const rec = unmeasured && k.record ? `<div class="kp-rec"><b>To measure:</b> ${esc(k.record)}</div>` : '';
    const beside = k.beside ? `<div class="kp-beside">${esc(k.beside.label)}: ${k.beside.value == null ? '<span class="nm">not measured yet</span>' : `<b>${esc(text(k.beside.value, k.beside.unit))}</b>`}</div>` : '';
    const note = k.note ? `<div class="kp-beside">${esc(k.note)}</div>` : '';
    const title = [k.definition, k.source ? `source: ${k.source}` : null, k.as_of ? `as of ${k.as_of}` : null].filter(Boolean).join('\n');
    const said = k.value == null ? 'not measured yet' : `${text(k.value, k.unit)}${k.basis === 'modelled' ? ' (modelled)' : ''}`;
    return `<article class="kp-tile${k.north_star ? ' ns' : ''}" data-testid="vt-kpi-tile" data-kpi-id="${esc(k.id)}" data-basis="${esc(k.basis || 'none')}" data-measured="${k.value == null ? 'false' : 'true'}" aria-label="${esc(`${k.label}: ${said}`)}"${title ? ` title="${esc(title)}"` : ''}>
      <div class="kp-l"><span class="t">${esc(k.label)}</span>${k.north_star ? '<span class="kp-tag">north star</span>' : ''}</div>
      ${valueHtml(k)}${basisHtml(k)}${sparkHtml(k)}
      <div class="kp-meta">${target ? `<span>${esc(target)}</span>` : ''}${dir ? `<span class="dir">${esc(dir)}</span>` : ''}</div>${beside}${note}${rec}</article>`;
  }

  /** The panel: a head, then one grid of tiles per group, north star first within its group. */
  function kpiPanel(spec, opts) {
    opts = opts || {};
    if (!spec || !Array.isArray(spec.groups)) return '<div class="kp" data-testid="vt-kpi-panel"><p class="unk">no KPI document</p></div>';
    const groups = spec.groups.map((g) => {
      const list = (g.kpis || []).slice().sort((a, b) => (b.north_star ? 1 : 0) - (a.north_star ? 1 : 0));
      const measured = list.filter((k) => k.basis === 'measured' && k.value != null).length;
      return `<section class="kp-group" data-group="${esc(g.id)}" aria-label="${esc(g.label)}"><h3 class="kp-gh">${esc(g.label)}<small>${measured} of ${list.length} measured${g.note ? ' · ' + esc(g.note) : ''}</small></h3>
        <div class="kp-grid">${list.map(tile).join('')}</div></section>`;
    }).join('');
    const head = opts.head === false ? '' : `<div class="kp-head"><h2>${esc(spec.title || 'Outside view')}</h2>${spec.subtitle ? `<span class="kp-sub">${esc(spec.subtitle)}</span>` : ''}${spec.illustrative ? '<span class="kp-illus" data-testid="vt-kpi-illustrative">Illustrative numbers, not BAM data</span>' : ''}${spec.as_of ? `<span class="kp-asof">as of ${esc(spec.as_of)}</span>` : ''}</div>`;
    return `<div class="kp" data-testid="vt-kpi-panel">${head}${groups}${spec.foot ? `<div class="kp-foot">${esc(spec.foot)}</div>` : ''}</div>`;
  }

  VT.ui = VT.ui || {};
  VT.ui.kpiPanel = kpiPanel;
  VT.ui.kpiText = text;
})();
