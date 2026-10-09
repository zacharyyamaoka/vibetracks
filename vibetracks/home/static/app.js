/* Vibe Tracks home · app (B2): boots the page, polls GET doc (vibetracks-home/1) every 10 s, and renders the
   sidebar plus the routed area. One document, no fixture. Area files register with VT.page(); their buttons use
   data-act="<name>" handled by VT.actions[<name>](el, ev) (return false to skip the re-render). */
(function () {
  'use strict';
  const VT = window.VT;
  const root = document.getElementById('vt-home');
  const DOC_URL = 'doc';
  let inflight = false;
  VT.pop = null;          // the open popover: 'display' | 'acct' | 'newproject' | null
  VT.drawer = false;      // the phone drawer

  function main() {
    const r = VT.route;
    const area = VT.pages[r.name] || VT.pages.home;
    if (!VT.doc) {
      return `<div class="page"><h1>Tracks</h1>${VT.error ? `<div class="banner">The home could not be read: ${VT.esc(VT.error)}. Retrying every ${VT.POLL_MS / 1000} s.</div>` : '<p class="sub">Reading sessions and transcripts… the first read after a restart takes about 15 s.</p>'}</div>`;
    }
    return area.render(r);
  }
  function title() {
    const r = VT.route, area = VT.pages[r.name];
    return (area && area.title && VT.doc) ? area.title(r) : 'Tracks';
  }

  VT.render = function render() {
    const y = window.scrollY;
    const r = VT.route;
    root.className = 'vlm' + (VT.drawer ? ' drawer' : '');
    root.dataset.route = r.name;
    const area = VT.pages[r.name] || VT.pages.home;
    const sidebar = VT.pages.sidebar ? VT.pages.sidebar.render(r) : '';
    root.innerHTML = `${sidebar}<div class="scrim" data-act="drawer"></div><main class="main" data-area="${VT.esc(r.name)}">`
      + `<div class="topbar"><button class="btn icon" data-testid="vt-home-menu" data-act="drawer" aria-label="Open the sidebar">${VT.ic('menu')}</button><b class="ell">${VT.esc(title())}</b></div>`
      + `${main()}${VT.doc && VT.pop && area.popover ? area.popover(VT.pop, r) : ''}</main>`
      + `${VT.doc && VT.pages.sidebar && VT.pages.sidebar.overlay ? VT.pages.sidebar.overlay(VT.pop) : ''}`
      + `${VT.toastMsg ? `<div class="toast" role="status">${VT.esc(VT.toastMsg)}</div>` : ''}`;
    if (!VT._keepScroll) window.scrollTo(0, y);
    VT._keepScroll = false;
    if (VT.doc) {
      root.dataset.ready = '1';
      if (area.after) area.after(root.querySelector('main'), r);
    }
  };

  async function refresh() {
    if (inflight) return;
    inflight = true;
    try {
      const response = await fetch(DOC_URL, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${response.status}`);
      if (!body || body.schema !== 'vibetracks-home/1') throw new Error('not a vibetracks-home/1 document');
      VT.doc = body; window.__vtHomeDoc = body; VT.error = null; VT.fetchedAt = Date.now();
    } catch (e) {
      VT.error = e && e.message ? e.message : String(e);
    } finally {
      inflight = false;
    }
    VT.render();
  }
  VT.refresh = refresh;

  // ------------------------------------------------------------------ shared actions
  Object.assign(VT.actions, {
    drawer() { VT.drawer = !VT.drawer; },
    refresh() { VT.invalidate(''); refresh(); return false; },
    copy(el) { VT.copy(el.dataset.text, el.dataset.what); return false; },
    pop(el) { VT.pop = VT.pop === el.dataset.id ? null : el.dataset.id; },
    go(el) { VT.drawer = false; VT.pop = null; VT.go(el.dataset.href); return false; },
  });

  root.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-act]');
    if (el && root.contains(el)) {
      if (el.tagName === 'A' && el.getAttribute('href') && !el.dataset.force) { VT.drawer = false; return; }
      // A link inside an actionable row (a project or track name) navigates by itself; the row's action stays put.
      const link = ev.target.closest('a[href]');
      if (link && link !== el && el.contains(link)) { VT.drawer = false; VT.pop = null; return; }
      const fn = VT.actions[el.dataset.act];
      const keepPop = el.closest('[data-pop]') || el.dataset.act === 'pop';
      if (!keepPop) VT.pop = null;
      if (fn) {
        const again = fn(el, ev);
        ev.stopPropagation();
        if (el.tagName === 'A' || el.tagName === 'BUTTON') ev.preventDefault();
        VT.save();
        if (again !== false) VT.render();
      }
      return;
    }
    const a = ev.target.closest('a[href^="#"]');
    if (a) { VT.drawer = false; VT.pop = null; return; }
    if (VT.pop && !ev.target.closest('[data-pop]')) { VT.pop = null; VT.render(); }
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable]')) {
      if (ev.key === 'Escape') ev.target.blur();
      return;
    }
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === 'Escape' && (VT.pop || VT.drawer)) { VT.pop = null; VT.drawer = false; ev.preventDefault(); VT.render(); return; }
    const area = VT.pages[VT.route.name];
    if (area && area.key && VT.doc && area.key(ev, VT.route) === true) { ev.preventDefault(); VT.save(); VT.render(); }
  });
  window.addEventListener('hashchange', () => {
    VT.route = VT.parseRoute(); VT.pop = null; VT.drawer = false; VT._keepScroll = true;
    window.scrollTo(0, 0);
    const area = VT.pages[VT.route.name];
    if (area && area.enter) area.enter(VT.route);
    VT.render();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => VT.render());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  const first = VT.pages[VT.route.name];
  if (first && first.enter) first.enter(VT.route);
  VT.render();
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, VT.POLL_MS);
})();
