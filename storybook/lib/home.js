// The story harness for the Vibe Tracks home's REAL parts (vibetracks/home/static, loaded unchanged by preview.js).
//
// A home page is a function of documents: GET doc (the home), project?id=, track?id=, ../roadmap/doc?track=,
// ../needs. A story picks a fixture set (real captures from Zach's Stable, gitignored; or the committed synthetic set
// built by the home's own code), answers those GETs from it, and renders the page the way app.js does. Nothing is
// re-implemented: every byte of markup comes from the home's own render functions.
//
// WHY render() and wire() mirror app.js instead of loading it: app.js boots once per page load (it grabs #vt-home,
// starts a 10 s poll of GET doc and installs document listeners), and a story must mount many times in one iframe.
// The two functions below copy app.js's VT.render body and its click delegation, nothing else; if app.js changes
// either, change them here too (tests/browser/home_b2.py and home_r3.py stay the ruler for the live page).
import MockDate from 'mockdate';

const load = (mods) => Object.fromEntries(Object.entries(mods).map(([path, body]) => [path.split('/').pop(), body]));
const SETS = {
  real: load(import.meta.glob('../fixtures/real/*.json', { eager: true, import: 'default' })),
  synthetic: load(import.meta.glob('../fixtures/synthetic/*.json', { eager: true, import: 'default' })),
};

/** The fixture set a story uses: the toolbar's choice, falling back to synthetic when no real capture exists. */
export function fixtureSet(globals) {
  // VITE_VT_SB_DATA=synthetic runs everything on the committed set, as a fresh clone would (no real capture).
  const forced = import.meta.env && import.meta.env.VITE_VT_SB_DATA;
  const want = forced || (globals && globals.data) || 'real';
  const name = want === 'real' && SETS.real['home.json'] ? 'real' : 'synthetic';
  const files = SETS[name];
  return {
    name,
    wanted: want,
    files,
    doc: files['home.json'],
    get: (file) => files[file] || null,
    label: name === 'real'
      ? `real capture · Stable · ${files['home.json'].generated_at}`
      : `synthetic fixture (compose.build_home over tests/fixtures/home)${want === 'real' ? ' · no real capture: run npm run capture' : ''}`,
  };
}
export const hasReal = () => !!SETS.real['home.json'];

// ------------------------------------------------------------------ GETs answered from the fixture set
const realFetch = window.fetch.bind(window);
let current = null;                 // the fixture set the mounted story reads
export const fetchLog = [];         // every call the home made, for interaction stories (a write must never leave)
function answer(status, body, type) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return Promise.resolve(new Response(text, { status, headers: { 'Content-Type': type || 'application/json' } }));
}
const ROUTES = [
  [/^doc$/, () => 'home.json'],
  [/^project\?id=(.+)$/, (m) => `project.${decodeURIComponent(m[1])}.json`],
  [/^track\?id=(.+)$/, (m) => `track.${decodeURIComponent(m[1])}.json`],
  [/^\.\.\/roadmap\/doc\?track=(.+)$/, (m) => `roadmap.${decodeURIComponent(m[1])}.json`],
  [/^\.\.\/needs$/, () => 'needs.json'],
];
window.fetch = (input, init) => {
  const url = typeof input === 'string' ? input : input && input.url;
  const method = ((init && init.method) || 'GET').toUpperCase();
  const route = ROUTES.find(([re]) => re.test(url));
  const homeCall = route || /^(audit\?|\.\.\/(tracks|projects)\/)/.test(url || '');
  if (!homeCall || !current) return realFetch(input, init);
  fetchLog.push({ url, method });
  if (method !== 'GET') return answer(501, { detail: 'storybook: the home\'s writes are never sent from a story' });
  if (!route) return answer(404, { detail: `no fixture for ${url} in the ${current.name} set` });
  const file = route[1](url.match(route[0]));
  const body = current.get(file);
  return body ? answer(200, body) : answer(404, { detail: `no ${file} in the ${current.name} fixture set` });
};

// ------------------------------------------------------------------ mount
let mounted = null;   // { root, opts }

function freshUI(prefs, theme) {
  const VT = window.VT;
  const d = JSON.parse(JSON.stringify(VT.DEFAULTS));
  for (const k of Object.keys(VT.S)) delete VT.S[k];
  // WHY in place: views.js and track.js captured `const S = VT.S` when they loaded.
  Object.assign(VT.S, d, prefs || {}, { theme: theme || 'dark' });
}

/** app.js's VT.render, into a story root (see the WHY at the top). */
function render() {
  if (!mounted) return;
  const VT = window.VT;
  const { root, opts } = mounted;
  const focused = document.activeElement;
  if (VT.editing && focused && focused.dataset && focused.dataset.testid === 'vt-rename') return;
  const r = VT.route;
  const area = VT.pages[r.name] || VT.pages.home;
  if (opts.part === 'sidebar') {
    root.innerHTML = VT.pages.sidebar.render(r);
    return;
  }
  const title = area.title && VT.doc ? area.title(r) : 'Tracks';
  const sidebar = opts.sidebar === false ? '' : VT.pages.sidebar.render(r);
  root.className = 'vlm' + (VT.drawer ? ' drawer' : '');
  root.dataset.route = r.name;
  root.innerHTML = `${sidebar}<div class="scrim" data-act="drawer"></div><main class="main" data-area="${VT.esc(r.name)}">`
    + `<div class="topbar"><button class="btn icon" data-testid="vt-home-menu" data-act="drawer" aria-label="Open the sidebar">${VT.ic('menu')}</button><b class="ell">${VT.esc(title)}</b></div>`
    + `${area.render(r)}${VT.doc && VT.pop && area.popover ? area.popover(VT.pop, r) : ''}</main>`
    + `${VT.doc && VT.pages.sidebar && VT.pages.sidebar.overlay ? VT.pages.sidebar.overlay(VT.pop) : ''}`
    + `${VT.toastMsg ? `<div class="toast" role="status">${VT.esc(VT.toastMsg)}</div>` : ''}`;
  root.dataset.ready = '1';
  if (area.after) area.after(root.querySelector('main'), r);
  if (opts.focus) isolate(root, opts.focus, r);
}

/** A part story: the page rendered for real, then only the part kept, at the width it had on the page. */
function isolate(root, selector, r) {
  const node = root.querySelector(selector);
  const page = root.querySelector('.page');
  if (!node) {
    root.dataset.part = 'missing';
    root.innerHTML = `<main class="main"><div class="page"><p class="sub">This fixture's page has no <code>${window.VT.esc(selector)}</code>.</p></div></main>`;
    return;
  }
  const width = Math.round(node.getBoundingClientRect().width);
  root.dataset.part = 'found';
  root.className = 'vlm sb-part';
  root.innerHTML = `<main class="main" data-area="${window.VT.esc(r.name)}"><div class="${page ? page.className : 'page'}" style="margin:0;max-width:none">`
    + `<div data-testid="sb-part" style="${width > 0 ? `width:${width}px;` : ''}max-width:100%">${node.outerHTML}</div></div></main>`;
}

/** app.js's click delegation (see the WHY at the top). */
function wire(root) {
  root.addEventListener('click', (ev) => {
    const VT = window.VT;
    const el = ev.target.closest('[data-act]');
    if (el && root.contains(el)) {
      if (el.tagName === 'A' && el.getAttribute('href') && !el.dataset.force) { VT.drawer = false; return; }
      const link = ev.target.closest('a[href]');
      if (link && link !== el && el.contains(link)) { VT.drawer = false; VT.pop = null; return; }
      const fn = VT.actions[el.dataset.act];
      const keepPop = el.closest('[data-pop]') || el.dataset.act === 'pop';
      if (!keepPop) VT.pop = null;
      if (fn) {
        const again = fn(el, ev);
        ev.stopPropagation();
        if (el.tagName === 'A' || el.tagName === 'BUTTON') ev.preventDefault();
        if (again !== false) VT.render();
      }
      return;
    }
    const a = ev.target.closest('a[href^="#"]');
    if (a) { ev.preventDefault(); VT.drawer = false; VT.pop = null; go(a.getAttribute('href')); return; }
    if (VT.pop && !ev.target.closest('[data-pop]')) { VT.pop = null; VT.render(); }
  });
}
/** A link inside a story navigates the story's page (the iframe's own hash is Storybook's). */
function go(hash) {
  const VT = window.VT;
  const raw = hash.slice(1);
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  const query = {};
  new URLSearchParams(qs || '').forEach((v, k) => { query[k] = v; });
  VT.route = !parts.length ? { name: 'home', id: null, query }
    : parts[0] === 'review' ? { name: 'review', id: null, query }
      : { name: parts[0], id: parts[1] || null, query };
  const area = VT.pages[VT.route.name];
  if (area && area.enter) area.enter(VT.route);
  VT.render();
}
document.addEventListener('keydown', (ev) => {
  const VT = window.VT;
  if (!mounted || !VT.doc) return;
  if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable]')) return;
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (ev.key === 'Escape' && (VT.pop || VT.drawer)) { VT.pop = null; VT.drawer = false; ev.preventDefault(); VT.render(); return; }
  const area = VT.pages[VT.route.name];
  if (area && area.key && area.key(ev, VT.route) === true) { ev.preventDefault(); VT.render(); }
});

/**
 * Mounts a home page (or one part of it) over a fixture set.
 *   route: { name: 'home'|'project'|'track'|'review', id, query }   prefs: VT.S overrides (view, kpiView, …)
 *   focus: a selector to isolate one part of the rendered page      part: 'sidebar' for the sidebar alone
 *   pop:   an open popover ('display' | 'acct' | 'newproject')
 */
export function mountPage(set, opts) {
  const VT = window.VT;
  current = set;
  fetchLog.length = 0;
  const doc = set.doc;
  MockDate.set(Date.parse(doc.generated_at) + 1000);   // "26 h ago" never drifts: the clock is the fixture's
  freshUI(opts.prefs, opts.theme);
  VT.applyTheme();
  VT.doc = doc;
  window.__vtHomeDoc = doc;
  VT.error = null;
  VT.fetchedAt = Date.parse(doc.generated_at);
  VT.route = Object.assign({ id: null, query: {} }, opts.route || { name: 'home' });
  VT.pop = opts.pop || null;
  VT.drawer = false;
  VT.toastMsg = null;
  VT.editing = null;
  VT.invalidate('');
  const root = document.createElement('div');
  root.id = 'vt-home';
  root.className = 'vlm';
  root.dataset.testid = 'vt-home';
  root.dataset.fixture = set.name;
  mounted = { root, opts };
  VT.render = render;
  const area = VT.pages[VT.route.name];
  if (area && area.enter) area.enter(VT.route);
  wire(root);
  render();
  return root;
}

/** For a story that calls core.js helpers directly: the fixture's document and clock, no page. */
export function useFixture(set) {
  current = set;
  MockDate.set(Date.parse(set.doc.generated_at) + 1000);
  window.VT.doc = set.doc;
  window.VT.fetchedAt = Date.parse(set.doc.generated_at);
}

/** Leaves the clock alone for stories that are not home pages (the map animates on real time). */
export function releaseClock() {
  MockDate.reset();
  mounted = null;
  current = null;
}

/** Resolves once fn() is truthy (polling a frame at a time), or rejects with what it last saw. */
export async function until(fn, what, ms = 8000) {
  const t0 = performance.now();
  for (;;) {
    let v;
    try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    if (performance.now() - t0 > ms) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 30));
  }
}

/** The track a page story shows: the one with the most to look at in this set (KPIs, gates, roadmap, audits). */
export function richestTrack(set, want) {
  let best = null, score = -1;
  for (const p of set.doc.projects) for (const t of p.tracks) {
    const d = set.get(`track.${t.id}.json`);
    if (!d || (want && !want(d, set))) continue;
    const k = d.kpis || {};
    const s = (k.soft || []).length * 2 + (k.gates || []).length * 2 + (set.get(`roadmap.${t.id}.json`) ? 6 : 0)
      + Math.min(4, ((d.audits || {}).rounds || []).length) + Math.min(4, (d.timeline || []).length / 10);
    if (s > score) { score = s; best = t.id; }
  }
  return best;
}
/** The project a page story shows: the one with the most tracks. */
export function biggestProject(set) {
  return set.doc.projects.slice().sort((a, b) => b.tracks.length - a.tracks.length)[0].id;
}
