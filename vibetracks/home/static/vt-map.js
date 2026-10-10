/* <vt-map> · the one map component of Vibe Tracks (2026-10-10). Zach, Oct 10: "one of the types of visualizations we
   want to support in vibe tracks should be a map … ideally we get the map working once and then we can reuse it".

   A framework-free custom element (an "island": it keeps a WebGL map, so it is not a string part). The same file runs
   in the vanilla home (as <script type="module">), in Storybook (storybook/stories/viz) and in React 19 (Clank),
   which passes an object `spec` to a custom element as a property.

   ENGINE: MapLibre GL JS 6 (BSD-3, no key, no tiles here: a calm thematic map on the card surface). It is loaded
   lazily with import('maplibre-gl'), so the HOST maps that specifier: Vite resolves it (Storybook), the vanilla home
   adds an import map to its vendored copy when the map is wired. The host also loads maplibre-gl.css and viz.css.
   Patterns are taken from mapcn (the shadcn registry's MapLibre map, MIT), its code is not: it is React-only and
   draws missing data as 0. Research: reports/media/vibetracks-storybook-2026-10-10 (maps verdict).

   CONTRACT (the property `spec`; tidy data in, so an agent can write it):
     metric:  { label, unit, decimals, better: 'higher'|'lower', breaks: [b1..b4] | domain+steps, goal?, goalLabel? }
     levels:  [{ id, label, boundary: url (GeoJSON, features carry properties.key / name / parent), metric?: {...},
                 noun?: 'province' }]                  drill order; a deeper level shows the children of `focus`
     values:  [{ level, key, period, value, source?, method?, note? }]   a missing row is "No data", NEVER 0
     points:  [{ id, lon, lat, label, status: 'ok'|'warn'|'fail'|'idle', size?, sizeLabel?, note?, href? }]
     pointsLabel?: 'BAM sites (illustrative)'      shown in the legend beside the status swatches
     view?:   { level, focus, bounds?: [w,s,e,n] }  the starting view (attributes level/focus override it)
     empty?:  { title, hint }                       what to say when nothing at this level is measured yet
     sources?: [string]                             extra footer lines (boundary attributions, licences)
   ATTRIBUTES: level, focus, period (view state; a host may mirror them to its URL), renderer="table" (no WebGL:
     the same values as a table), interactive="false".
   EVENTS (bubbling CustomEvents): vt-map-select {kind: 'region'|'point', level, key, name, value, period, source},
     vt-map-drill {from, to, focus}, vt-map-period {period}.
   STATE (for hosts and tests): data-state loading|ready|error, data-renderer gl|table, data-level, data-focus,
     data-period; el.map (the MapLibre map), el.view, el.whenReady().

   RULES BAKED IN (Zach's truthful-rendering rule; the dataviz method):
     - no row = "No data" in a neutral grey with its own legend swatch, never the lowest class and never 0;
     - one variable per view, stepped classes from explicit breaks, validated tokens (viz.css), dark is its own steps;
     - the tooltip and the table carry the source and method; a view mixing methods says so in the footer;
     - every value is also in the table view (keyboard and screen-reader path; drill-down works from it too);
     - the goal (e.g. 100 % circularity) is in the legend; the period control appears only with more than one period.
   NOT YET (next phases): the with/without-BAM delta view (diverging ramp; needs per-city baselines), clustering,
   an offline street basemap (PMTiles; needs a byte-range route in the home backend). */

const ENGINE = { load: () => import('maplibre-gl') };
const boundaries = new Map();
function boundary(url) {
  if (!boundaries.has(url)) {
    boundaries.set(url, fetch(url, { headers: { Accept: 'application/json' } }).then((r) => {
      if (!r.ok) throw new Error(`boundary ${url}: HTTP ${r.status}`);
      return r.json();
    }).catch((e) => { boundaries.delete(url); throw e; }));
  }
  return boundaries.get(url);
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STATUS = { ok: ['--viz-good', 'running'], warn: ['--viz-warn', 'needs attention'], fail: ['--viz-bad', 'down'], idle: ['--viz-idle', 'idle'] };

/** Class edges: explicit breaks, else equal steps over the domain. */
function breaksOf(m) {
  if (Array.isArray(m.breaks) && m.breaks.length) return m.breaks.slice();
  const [a, b] = m.domain || [0, 1];
  const n = m.steps || 5;
  return Array.from({ length: n - 1 }, (_, i) => a + ((i + 1) * (b - a)) / n);
}
function classOf(v, br) { let i = 0; while (i < br.length && v >= br[i]) i++; return i; }
function fmt(v, m) {
  if (v == null || !isFinite(v)) return null;
  const d = m.decimals != null ? m.decimals : Math.abs(v) >= 100 ? 0 : 1;
  const n = v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  return m.unit === '%' ? `${n}%` : m.unit ? `${n} ${m.unit}` : n;
}

/** [w, s, e, n] of a feature list; across the antimeridian (Alaska's Aleutians) the narrower wrap wins. */
function bboxOf(features) {
  let s = 90, n = -90, w1 = 180, e1 = -180, w2 = 360, e2 = 0;
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      const [x, y] = c;
      if (y < s) s = y; if (y > n) n = y;
      if (x < w1) w1 = x; if (x > e1) e1 = x;
      const x2 = x < 0 ? x + 360 : x;
      if (x2 < w2) w2 = x2; if (x2 > e2) e2 = x2;
      return;
    }
    for (const k of c) walk(k);
  };
  for (const f of features) if (f.geometry) walk(f.geometry.coordinates);
  if (s > n) return null;
  if (e2 - w2 < e1 - w1 - 1) return [w2 - 360, s, e2 - 360, n];
  return [w1, s, e1, n];
}

class VtMap extends HTMLElement {
  static get observedAttributes() { return ['level', 'focus', 'period', 'renderer', 'interactive']; }
  /** Hosts may replace the engine loader (e.g. a vendored path) before the first map is built. */
  static set engine(loader) { ENGINE.load = loader; }

  constructor() {
    super();
    this._spec = null;
    this._map = null;
    this._view = { level: null, focus: null, period: null };
    this._seq = 0;
    this._hover = null;
    this._ready = null;
    this._showTable = false;
  }
  set spec(v) { this._spec = v; this._view = { level: null, focus: null, period: null }; this._queue(); }
  get spec() { return this._spec; }
  get map() { return this._map; }
  get view() { return Object.assign({}, this._view); }
  /** Resolves when the latest change has been drawn (the map is idle, or the table is built). */
  whenReady() { return this._ready ? this._ready.promise : Promise.resolve(); }

  connectedCallback() {
    if (!this._root) this._skeleton();
    this._observeTheme();
    this._queue();
  }
  disconnectedCallback() {
    // WHY a microtask and isConnected: a host that keeps this node across a re-render moves it (remove, then insert),
    // which fires disconnected then connected; tearing the WebGL map down at once would rebuild it on every move.
    queueMicrotask(() => { if (!this.isConnected) this._teardown(); });
  }
  attributeChangedCallback(name, before, after) { if (before !== after && this._root) this._queue(); }

  // ------------------------------------------------------------------ DOM
  _skeleton() {
    this.innerHTML = `<div class="vtm" part="frame">
      <div class="vtm-top"><nav class="vtm-crumb" aria-label="Map level"></nav><div class="vtm-title"></div><div class="vtm-period"></div>
        <button type="button" class="vtm-tbtn" aria-pressed="false">Table</button></div>
      <div class="vtm-stage" role="group"><div class="vtm-canvas"></div><div class="vtm-legend"></div><div class="vtm-tip" hidden></div><div class="vtm-empty" hidden></div></div>
      <div class="vtm-note gl" hidden></div>
      <div class="vtm-tablewrap" hidden></div>
      <div class="vtm-foot"></div></div>`;
    const q = (s) => this.querySelector(s);
    this._root = q('.vtm');
    this._els = { crumb: q('.vtm-crumb'), title: q('.vtm-title'), period: q('.vtm-period'), tbtn: q('.vtm-tbtn'), stage: q('.vtm-stage'),
      canvas: q('.vtm-canvas'), legend: q('.vtm-legend'), tip: q('.vtm-tip'), empty: q('.vtm-empty'), note: q('.vtm-note'),
      table: q('.vtm-tablewrap'), foot: q('.vtm-foot') };
    this._els.tbtn.addEventListener('click', () => { this._showTable = !this._showTable; this._paintTable(); });
    this._els.crumb.addEventListener('click', (ev) => {
      const b = ev.target.closest('button[data-level]');
      if (b) this._goto(+b.dataset.level, b.dataset.focus || null);
    });
    this._els.table.addEventListener('click', (ev) => {
      const b = ev.target.closest('button[data-key]');
      if (b) this._drill(b.dataset.key);
    });
    this._els.period.addEventListener('input', (ev) => {
      const t = ev.target;
      if (t.matches('input[type=range]')) this._setPeriod(this._periods[+t.value]);
    });
    this._els.period.addEventListener('click', (ev) => {
      const b = ev.target.closest('button[data-period]');
      if (b) this._setPeriod(b.dataset.period);
    });
  }

  // ------------------------------------------------------------------ the update cycle
  _queue() {
    if (this._queued) return;
    this._queued = true;
    if (!this._ready || this._ready.done) {
      let resolve; const promise = new Promise((r) => { resolve = r; });
      this._ready = { promise, resolve, done: false };
    }
    queueMicrotask(() => { this._queued = false; this._update().catch((e) => this._fail(e)); });
  }
  _settle() {
    if (this._ready && !this._ready.done) { this._ready.done = true; this._ready.resolve(); }
  }
  _fail(e) {
    this.dataset.state = 'error';
    this._els.note.hidden = false;
    this._els.note.textContent = `The map could not be drawn: ${e && e.message ? e.message : e}`;
    this._settle();
  }

  async _update() {
    if (!this.isConnected || !this._root) return;
    const spec = this._spec;
    if (!spec || !Array.isArray(spec.levels) || !spec.levels.length) { this.dataset.state = 'loading'; return; }
    const seq = ++this._seq;
    this.dataset.state = 'loading';
    // ---- the view: attributes win, then what the user did, then the spec's starting view
    const ids = spec.levels.map((l) => l.id);
    const attrLevel = this.getAttribute('level');
    let li = ids.indexOf(attrLevel != null ? attrLevel : this._view.level != null ? this._view.level : (spec.view && spec.view.level) || ids[0]);
    if (li < 0) li = 0;
    let focus = this.getAttribute('focus') || this._view.focus || (spec.view && spec.view.focus) || null;
    if (li === 0) focus = null;
    const level = spec.levels[li];
    const metric = Object.assign({}, spec.metric || {}, level.metric || {});
    // ---- features of this view
    const geo = await boundary(level.boundary);
    if (seq !== this._seq) return;
    let features = (geo.features || []).filter((f) => li === 0 || (f.properties && f.properties.parent === focus));
    // ---- values of this level and period
    const rows = (spec.values || []).filter((r) => r.level === level.id);
    const periods = [...new Set(rows.map((r) => String(r.period)))].sort();
    this._periods = periods;
    let period = this.getAttribute('period') || this._view.period;
    if (!periods.includes(period)) period = periods[periods.length - 1] || null;
    const byKey = new Map(rows.filter((r) => String(r.period) === period && r.value != null && isFinite(r.value)).map((r) => [r.key, r]));
    // a row with no value may still say why (e.g. "the source reports 0 t: a missing report"): shown, never drawn as 0
    const gaps = new Map(rows.filter((r) => String(r.period) === period && (r.value == null || !isFinite(r.value))).map((r) => [r.key, r]));
    const br = breaksOf(metric);
    features = features.map((f) => {
      const key = f.properties.key, row = byKey.get(key);
      return { type: 'Feature', geometry: f.geometry, properties: { key, name: f.properties.name || key, v: row ? row.value : null, has: row ? 1 : 0, cls: row ? classOf(row.value, br) : -1 } };
    });
    const nextLevel = spec.levels[li + 1] || null;
    const drillable = new Set();
    if (nextLevel) {
      const child = await boundary(nextLevel.boundary).catch(() => null);
      if (seq !== this._seq) return;
      if (child) for (const f of child.features || []) if (f.properties && f.properties.parent) drillable.add(f.properties.parent);
    }
    // the breadcrumb: walk up from the focus through each parent level's boundary (its features name their parent)
    const trail = [], names = [];
    trail[li] = focus;
    for (let i = li; i >= 1; i--) {
      const up = await boundary(spec.levels[i - 1].boundary).catch(() => null);
      if (seq !== this._seq) return;
      const pf = up && (up.features || []).find((f) => f.properties && f.properties.key === trail[i]);
      names[i] = pf ? pf.properties.name || trail[i] : trail[i];
      if (i - 1 >= 1) trail[i - 1] = pf ? pf.properties.parent || null : null;
    }
    names[0] = spec.levels[0].label || spec.levels[0].id;
    this._view = { level: level.id, focus, period };
    this._ctx = { spec, li, level, metric, br, features, rows, byKey, gaps, period, nextLevel, drillable, trail, names };
    Object.assign(this.dataset, { level: level.id, focus: focus || '', period: period || '' });
    this._paintChrome();
    this._paintTable();
    // ---- draw
    const forced = this.getAttribute('renderer') === 'table';
    if (forced || this._noGL) {
      this._renderer('table');
      this.dataset.state = 'ready';
      this._settle();
      return;
    }
    const ok = await this._ensureMap();
    if (seq !== this._seq) return;
    if (!ok) { this._renderer('table'); this.dataset.state = 'ready'; this._settle(); return; }
    this._renderer('gl');
    this._draw();
    this._map.once('idle', () => { if (seq === this._seq) { this.dataset.state = 'ready'; this._settle(); } });
    this._map.triggerRepaint();
  }

  _renderer(kind) {
    this.dataset.renderer = kind;
    this._root.dataset.renderer = kind;
    this._els.tbtn.hidden = kind === 'table';
    if (kind === 'table') { this._showTable = true; this._paintTable(); }
  }

  // ------------------------------------------------------------------ chrome: crumb, title, period, legend, footer
  _paintChrome() {
    const c = this._ctx, spec = c.spec, m = c.metric;
    // breadcrumb: one entry per level above, each a button back up
    const crumbs = [];
    for (let i = 0; i <= c.li; i++) {
      if (i === c.li) crumbs.push(`<span aria-current="location">${esc(c.names[i])}</span>`);
      else crumbs.push(`<button type="button" data-level="${i}" data-focus="${esc(c.trail[i] || '')}">${esc(c.names[i])}</button>`);
    }
    this._els.crumb.innerHTML = crumbs.join('<span aria-hidden="true">/</span>');
    const noun = c.level.noun || c.level.label || c.level.id;
    this._els.title.innerHTML = `<b>${esc(m.label || 'Value')}</b><span>by ${esc(noun)}${c.period ? ` · ${esc(c.period)}` : ''}</span>`;
    // period: a segmented control for a few periods, a slider for many, nothing for one
    const ps = this._periods;
    if (ps.length > 1 && ps.length <= 4) {
      this._els.period.innerHTML = `<span>Period</span><span class="vtm-seg" role="group" aria-label="Period">${ps.map((p) => `<button type="button" data-period="${esc(p)}" aria-pressed="${p === c.period}">${esc(p)}</button>`).join('')}</span>`;
    } else if (ps.length > 4) {
      const i = ps.indexOf(c.period);
      this._els.period.innerHTML = `<label for="vtm-p-${this._uid()}">Period</label><input id="vtm-p-${this._uid()}" type="range" min="0" max="${ps.length - 1}" step="1" value="${i}" aria-valuetext="${esc(c.period)}"><output>${esc(c.period)}</output>`;
    } else this._els.period.innerHTML = '';
    // legend: stepped classes, No data, the goal, the sites
    const br = c.br, n = br.length + 1;
    const edges = [null].concat(br).concat([null]);
    const bm = Object.assign({}, m, { decimals: br.every(Number.isInteger) ? 0 : m.decimals, unit: m.unit === '%' ? '%' : '' });
    const lab = (i) => (i === 0 ? `< ${fmt(br[0], bm)}` : i === n - 1 ? `≥ ${fmt(br[n - 2], bm)}` : `${fmt(edges[i], Object.assign({}, bm, { unit: '' }))}–${fmt(edges[i + 1], bm)}`);
    const used = new Set(c.features.filter((f) => f.properties.has).map((f) => f.properties.cls));
    const steps = Array.from({ length: n }, (_, i) => `<span class="vtm-step" data-class="${i}"${used.has(i) ? ' data-used="1"' : ''}><i style="background:var(--viz-seq-${Math.min(5, i + 1)})"></i><span>${esc(lab(i))}</span></span>`).join('');
    const better = m.better === 'lower' ? 'lower is better' : m.better === 'higher' ? 'higher is better' : '';
    const sitesIn = (spec.points || []).length;
    const sites = sitesIn ? `<div class="vtm-sites"><b>${esc(spec.pointsLabel || 'Sites')}</b>${[...new Set(spec.points.map((p) => p.status || 'idle'))]
      .map((s) => `<span><i class="vtm-dot" style="background:var(${(STATUS[s] || STATUS.idle)[0]})"></i>${esc((STATUS[s] || STATUS.idle)[1])}</span>`).join('')}</div>` : '';
    this._els.legend.innerHTML = `<div class="lt">${esc(m.label || 'Value')}${m.unit && m.unit !== '%' ? ` <small>(${esc(m.unit)})</small>` : ''}${better ? ` <small>· ${better}</small>` : ''}</div>
      <div class="vtm-steps">${steps}<span class="vtm-step vtm-nd" data-class="nodata"><i></i><span>No data</span></span></div>
      ${m.goal != null ? `<div class="vtm-goal">goal: ${esc(m.goalLabel || fmt(m.goal, bm))}</div>` : ''}${sites}`;
    // empty: nothing at this level measured, in any period
    const measured = c.rows.some((r) => r.value != null && isFinite(r.value));
    const e = spec.empty || {};
    this._els.empty.hidden = measured;
    this._els.empty.innerHTML = measured ? '' : `<div><b>${esc(e.title || 'Not measured yet')}</b><small>${esc(e.hint || 'No region at this level has a recorded value.')}</small></div>`;
    this.dataset.empty = measured ? '' : '1';
    this._els.stage.setAttribute('aria-label', `Map of ${m.label || 'values'} by ${noun}${c.period ? ', ' + c.period : ''}. Every value is in the table (Table button).`);
    // footer: where the numbers come from, and whether they are comparable
    const srcs = [...new Set(c.rows.filter((r) => String(r.period) === c.period).map((r) => r.source).filter(Boolean))];
    const methods = [...new Set([...c.byKey.values()].map((r) => r.method).filter(Boolean))];
    const lines = srcs.map((s) => `<span>Source: ${esc(s)}</span>`);
    if (methods.length > 1) lines.push(`<span class="warn">Methods differ between regions in this view (${esc(methods.join('; '))}): compare with care.</span>`);
    if (c.level.metric && spec.metric && c.level.metric.label && c.level.metric.label !== spec.metric.label) lines.push(`<span class="warn">A different measure at this level: ${esc(c.level.metric.label)}, not ${esc(spec.metric.label)}.</span>`);
    for (const s of (c.level.sources || []).concat(spec.sources || [])) lines.push(`<span>${esc(s)}</span>`);
    if (spec.pointsNote && sitesIn) lines.push(`<span>${esc(spec.pointsNote)}</span>`);
    this._els.foot.innerHTML = lines.join('');
  }
  _uid() { return this._id || (this._id = Math.random().toString(36).slice(2, 8)); }

  _paintTable() {
    const c = this._ctx;
    if (!c) return;
    this._els.tbtn.setAttribute('aria-pressed', String(this._showTable));
    this._els.table.hidden = !this._showTable;
    if (!this._showTable) return;
    const m = c.metric;
    const list = c.features.map((f) => f.properties).sort((a, b) => (b.has - a.has) || (a.has ? (m.better === 'lower' ? a.v - b.v : b.v - a.v) : 0) || a.name.localeCompare(b.name));
    const noun = c.level.noun || c.level.label || c.level.id;
    const srcs = [...new Set([...c.byKey.values()].map((r) => r.source).filter(Boolean))];
    const notes = list.some((p) => (c.byKey.get(p.key) || c.gaps.get(p.key) || {}).note);
    const rows = list.map((p) => {
      const r = c.byKey.get(p.key), gap = c.gaps.get(p.key);
      const name = c.drillable.has(p.key) && c.nextLevel ? `<button type="button" data-key="${esc(p.key)}" title="Show its ${esc(c.nextLevel.noun || c.nextLevel.label)}">${esc(p.name)}</button>` : esc(p.name);
      const note = (r && r.note) || (gap && gap.note) || '';
      return `<tr data-key="${esc(p.key)}"><td>${name}</td><td class="n">${p.has ? esc(fmt(p.v, m)) : '<span class="nd">No data</span>'}</td>${srcs.length > 1 ? `<td>${r ? esc(r.source || '') : ''}</td>` : ''}${notes ? `<td>${esc(note)}</td>` : ''}</tr>`;
    }).join('');
    const cap = `${m.label || 'Value'} by ${noun}${c.period ? `, ${c.period}` : ''}${srcs.length === 1 ? `. Source: ${srcs[0]}` : ''}`;
    // WHY tabindex and a label: the table scrolls, so a keyboard user must be able to reach it (axe: scrollable-region-focusable)
    this._els.table.tabIndex = 0;
    this._els.table.setAttribute('role', 'region');
    this._els.table.setAttribute('aria-label', `${m.label || 'Values'} table`);
    this._els.table.innerHTML = `<table class="vtm-table"><caption>${esc(cap)}</caption>
      <thead><tr><th scope="col">${esc(noun.charAt(0).toUpperCase() + noun.slice(1))}</th><th scope="col" class="n">${esc(m.unit ? `${m.label} (${m.unit})` : m.label || 'Value')}</th>${srcs.length > 1 ? '<th scope="col">Source</th>' : ''}${notes ? '<th scope="col">Note</th>' : ''}</tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ------------------------------------------------------------------ the WebGL map
  _colors() {
    const cs = getComputedStyle(this);
    const v = (n, d) => (cs.getPropertyValue(n) || '').trim() || d;
    return {
      seq: [1, 2, 3, 4, 5].map((i) => v(`--viz-seq-${i}`, '#2a78d6')), nodata: v('--viz-nodata', '#e3e2dc'), edge: v('--viz-edge', '#ffffff'),
      surface: v('--surface', '#ffffff'), ink: v('--ink', '#0b0b0b'),
      status: { ok: v('--viz-good', '#0ca30c'), warn: v('--viz-warn', '#fab219'), fail: v('--viz-bad', '#d03b3b'), idle: v('--viz-idle', '#898781') },
    };
  }
  async _ensureMap() {
    if (this._map) return true;
    if (this._noGL) return false;
    let ml;
    try { ml = await ENGINE.load(); } catch (e) { this._glNote(`the map engine did not load (${e.message || e})`); return false; }
    if (this._map) return true;
    if (!this.isConnected) return false;
    const col = this._colors();
    this._palette = col;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._reduce = reduce;
    try {
      this._map = new ml.Map({
        container: this._els.canvas,
        style: { version: 8, sources: {}, layers: [{ id: 'vtm-bg', type: 'background', paint: { 'background-color': col.surface } }] },
        center: [0, 20], zoom: 0, minZoom: -2, maxZoom: 10,
        attributionControl: false, renderWorldCopies: false,
        // WHY no scroll or double-click zoom: on a dashboard the wheel scrolls the page, and a click drills down.
        scrollZoom: false, doubleClickZoom: false, dragRotate: false, pitchWithRotate: false, touchPitch: false, boxZoom: false,
        // WHY preserveDrawingBuffer: the canvas can be read back (a PNG for a static report, a pixel test).
        canvasContextAttributes: { preserveDrawingBuffer: true, antialias: true },
      });
    } catch (e) {
      // MapLibre 6.7+ throws GPUInitializationError when there is no WebGL2: the table is the same data.
      this._noGL = true;
      this._glNote(`this browser gave no WebGL2 context (${e && e.name ? e.name : 'error'})`);
      return false;
    }
    if (this.getAttribute('interactive') !== 'false') this._map.addControl(new ml.NavigationControl({ showCompass: false }), 'top-right');
    await new Promise((r) => (this._map.loaded() ? r() : this._map.once('load', r)));
    const map = this._map;
    map.addSource('vtm-regions', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'key' });
    map.addSource('vtm-points', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'id' });
    map.addLayer({ id: 'vtm-fill', type: 'fill', source: 'vtm-regions', paint: { 'fill-color': this._fillExpr(col), 'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.82, 1] } });
    map.addLayer({ id: 'vtm-edge', type: 'line', source: 'vtm-regions', paint: { 'line-color': col.edge, 'line-width': 1 } });
    map.addLayer({ id: 'vtm-hover', type: 'line', source: 'vtm-regions', paint: { 'line-color': col.ink, 'line-width': 1.5, 'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 1, 0] } });
    map.addLayer({ id: 'vtm-pt', type: 'circle', source: 'vtm-points', paint: {
      'circle-radius': ['case', ['has', 'size'], ['interpolate', ['linear'], ['sqrt', ['get', 'size']], 0, 4, 10, 14], 6],
      'circle-color': ['match', ['get', 'status'], 'ok', col.status.ok, 'warn', col.status.warn, 'fail', col.status.fail, col.status.idle],
      'circle-stroke-color': col.surface, 'circle-stroke-width': 2 } });
    if (this.getAttribute('interactive') !== 'false') this._wireMap();
    this._resize = new ResizeObserver(() => {
      if (!this._map) return;
      this._map.resize();
      if (this._ctx && this._fitted && !this._userMoved) this._fit(0, this._fitted);
    });
    map.on('movestart', (e) => { if (e && e.originalEvent) this._userMoved = true; });
    this._resize.observe(this._els.stage);
    return true;
  }
  _fillExpr(col) {
    return ['case', ['==', ['get', 'has'], 1], ['match', ['get', 'cls'], 0, col.seq[0], 1, col.seq[1], 2, col.seq[2], 3, col.seq[3], col.seq[4]], col.nodata];
  }
  _glNote(why) {
    this._els.note.hidden = false;
    this._els.note.textContent = `Map not drawn: ${why}. Every value is in the table below.`;
  }
  _draw() {
    const c = this._ctx, map = this._map;
    this._hover = null;
    map.getSource('vtm-regions').setData({ type: 'FeatureCollection', features: c.features });
    const pts = (c.spec.points || []).filter((p) => isFinite(p.lon) && isFinite(p.lat));
    map.getSource('vtm-points').setData({ type: 'FeatureCollection', features: pts.map((p) => ({ type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] }, properties: Object.assign({ id: p.id, status: p.status || 'idle' }, p.size != null ? { size: p.size } : {}) })) });
    // WHY world copies only below the world level: with copies off MapLibre pins the centre to 0° whenever the world is
    // narrower than the canvas (Canada fitted at zoom ~0.9 sat at the left edge); with copies on at the world level,
    // the continents repeat at the sides.
    map.setRenderWorldCopies(c.li > 0);
    this._fit(this._moved && !this._reduce ? 450 : 0);
    this._moved = true;
    this._userMoved = false;
  }
  /** Fits the view's regions (or the spec's starting bounds), clamped to 60° S – 76° N: Mercator's poles would
   *  otherwise shrink everything (Canada's Arctic islands reach 83° N). */
  _fit(duration, again) {
    const c = this._ctx, map = this._map;
    const first = !this._moved && c.spec.view && c.spec.view.bounds;
    const bb = again || first || (c.level.bounds && c.level.bounds[this._view.focus || '*']) || bboxOf(c.features);
    if (!bb) return;
    const s = Math.max(bb[1], -60), n = Math.min(bb[3], 76);
    this._fitted = [bb[0], s, bb[2], n];
    map.fitBounds([[bb[0], s], [bb[2], n]], { padding: { top: 24, bottom: 96, left: 24, right: 52 }, duration });
  }
  _repaint() {
    const map = this._map;
    if (!map || !map.getLayer('vtm-fill')) return;
    const col = this._colors();
    if (JSON.stringify(col) === JSON.stringify(this._palette)) return;
    this._palette = col;
    map.setPaintProperty('vtm-bg', 'background-color', col.surface);
    map.setPaintProperty('vtm-fill', 'fill-color', this._fillExpr(col));
    map.setPaintProperty('vtm-edge', 'line-color', col.edge);
    map.setPaintProperty('vtm-hover', 'line-color', col.ink);
    map.setPaintProperty('vtm-pt', 'circle-color', ['match', ['get', 'status'], 'ok', col.status.ok, 'warn', col.status.warn, 'fail', col.status.fail, col.status.idle]);
    map.setPaintProperty('vtm-pt', 'circle-stroke-color', col.surface);
  }
  _observeTheme() {
    if (this._themeObs) return;
    const again = () => requestAnimationFrame(() => this._repaint());
    this._themeObs = new MutationObserver(again);
    this._themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    this._mq = window.matchMedia('(prefers-color-scheme: dark)');
    this._mqFn = again;
    this._mq.addEventListener('change', again);
  }

  _wireMap() {
    const map = this._map, tip = this._els.tip;
    const setHover = (key) => {
      if (this._hover === key) return;
      if (this._hover != null) map.setFeatureState({ source: 'vtm-regions', id: this._hover }, { hover: false });
      this._hover = key;
      if (key != null) map.setFeatureState({ source: 'vtm-regions', id: key }, { hover: true });
    };
    map.on('mousemove', (e) => {
      const c = this._ctx;
      if (!c) return;
      const pt = map.queryRenderedFeatures(e.point, { layers: ['vtm-pt'] })[0];
      const reg = pt ? null : map.queryRenderedFeatures(e.point, { layers: ['vtm-fill'] })[0];
      setHover(reg ? reg.properties.key : null);
      if (!pt && !reg) { tip.hidden = true; this._els.canvas.style.cursor = ''; map.getCanvas().style.cursor = ''; return; }
      tip.innerHTML = pt ? this._pointTip(pt.properties.id) : this._regionTip(reg.properties.key);
      tip.hidden = false;
      const w = this._els.stage.clientWidth;
      tip.style.left = `${Math.min(e.point.x, w - 290)}px`;
      tip.style.top = `${e.point.y}px`;
      map.getCanvas().style.cursor = pt || (reg && c.drillable.has(reg.properties.key)) ? 'pointer' : '';
    });
    map.on('mouseout', () => { setHover(null); tip.hidden = true; });
    map.on('click', (e) => {
      const c = this._ctx;
      if (!c) return;
      const pt = map.queryRenderedFeatures(e.point, { layers: ['vtm-pt'] })[0];
      if (pt) {
        const p = (c.spec.points || []).find((x) => String(x.id) === String(pt.properties.id));
        this.dispatchEvent(new CustomEvent('vt-map-select', { bubbles: true, detail: { kind: 'point', id: p.id, name: p.label, status: p.status, href: p.href || null } }));
        return;
      }
      const reg = map.queryRenderedFeatures(e.point, { layers: ['vtm-fill'] })[0];
      if (!reg) return;
      const key = reg.properties.key, row = c.byKey.get(key);
      this.dispatchEvent(new CustomEvent('vt-map-select', { bubbles: true, detail: { kind: 'region', level: c.level.id, key, name: reg.properties.name, value: row ? row.value : null, period: c.period, source: row ? row.source || null : null } }));
      this._drill(key);
    });
  }
  _regionTip(key) {
    const c = this._ctx, f = c.features.find((x) => x.properties.key === key);
    const row = c.byKey.get(key), m = c.metric;
    const name = f ? f.properties.name : key;
    const val = row ? `<span class="v">${esc(fmt(row.value, m))}</span>` : '<span class="nd">No data</span>';
    const gap = c.gaps.get(key);
    const meta = row ? [c.period, row.source, row.method, row.note].filter(Boolean).map((s) => `<small>${esc(s)}</small>`).join('')
      : `<small>${esc(gap && gap.note ? `${c.period}: ${gap.note}` : c.period ? `nothing recorded for ${c.period}` : 'nothing recorded')}</small>`;
    const more = c.drillable.has(key) && c.nextLevel ? `<small>Click to see its ${esc(c.nextLevel.noun || c.nextLevel.label)}</small>` : '';
    return `<b>${esc(name)}</b>${val}${meta}${more}`;
  }
  _pointTip(id) {
    const p = (this._ctx.spec.points || []).find((x) => String(x.id) === String(id));
    if (!p) return '';
    const st = STATUS[p.status] || STATUS.idle;
    return `<b>${esc(p.label)}</b><small><i class="vtm-dot" style="background:var(${st[0]})"></i>${esc(st[1])}</small>${p.size != null ? `<small>${esc(p.size)} ${esc(p.sizeLabel || '')}</small>` : ''}${p.note ? `<small>${esc(p.note)}</small>` : ''}`;
  }

  // ------------------------------------------------------------------ navigation
  _drill(key) {
    const c = this._ctx;
    if (!c || !c.nextLevel || !c.drillable.has(key)) return;
    const from = c.level.id;
    this.removeAttribute('level'); this.removeAttribute('focus'); this.removeAttribute('period');
    this._view = { level: c.nextLevel.id, focus: key, period: null };
    this.dispatchEvent(new CustomEvent('vt-map-drill', { bubbles: true, detail: { from, to: c.nextLevel.id, focus: key } }));
    this._queue();
  }
  _goto(li, focus) {
    const c = this._ctx;
    if (!c) return;
    const lvl = c.spec.levels[li];
    this.removeAttribute('level'); this.removeAttribute('focus'); this.removeAttribute('period');
    this._view = { level: lvl.id, focus: li === 0 ? null : focus, period: null };
    this.dispatchEvent(new CustomEvent('vt-map-drill', { bubbles: true, detail: { from: c.level.id, to: lvl.id, focus: this._view.focus } }));
    this._queue();
  }
  _setPeriod(p) {
    if (!p || p === this._view.period) return;
    this.removeAttribute('period');
    this._view.period = p;
    this.dispatchEvent(new CustomEvent('vt-map-period', { bubbles: true, detail: { period: p } }));
    this._queue();
  }

  _teardown() {
    if (this._resize) { this._resize.disconnect(); this._resize = null; }
    if (this._themeObs) { this._themeObs.disconnect(); this._themeObs = null; }
    if (this._mq && this._mqFn) { this._mq.removeEventListener('change', this._mqFn); this._mq = null; }
    if (this._map) { this._map.remove(); this._map = null; }
    this._moved = false;
  }
}

if (!customElements.get('vt-map')) customElements.define('vt-map', VtMap);
export { VtMap };
