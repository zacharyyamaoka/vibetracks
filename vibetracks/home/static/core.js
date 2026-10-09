/* Vibe Tracks home · core (B2, 2026-10-09): the shared state, router, fetch cache and helpers every area uses.
   Areas register themselves with VT.page(name, {...}) in their own file (sidebar.js, views.js, review.js,
   project.js, track.js); app.js boots. The page renders documents the backend derived and nothing else: a field
   the backend could not observe is null and reads "unknown" here, never 0 and never "fine".

   Routes (the hash, so every view is a link and Back works):
     #/                 home (Rows / Table / Board / Cards over GET doc)
     #/review[?track=]  review (GET ../needs)
     #/project/<id>     project page (GET project?id=)
     #/track/<id>       track page (GET track?id=)
   Hooks for checks: window.__vtHomeDoc, #vt-home[data-ready="1"], #vt-home[data-route]. */
(function () {
  'use strict';
  const VT = (window.VT = window.VT || {});
  const STORE = 'vt-home-ui-v1';
  const SEEN = 'vt-home-seen-v1';
  VT.POLL_MS = 10000;
  VT.DEFAULTS = { view: 'rows', group: 'project', order: 'attention', tabset: 'active', subs: true, ended: false,
    props: { target: 1, health: 1, prog: 1, state: 1, work: 1 }, collapsed: {}, otherOpen: false,
    theme: 'system', side: {}, kpiView: 'cards', trackTab: 'overview' };

  // ------------------------------------------------------------------ persisted preferences (per viewer)
  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
      return Object.assign({}, VT.DEFAULTS, saved, { props: Object.assign({}, VT.DEFAULTS.props, saved.props || {}),
        collapsed: Object.assign({}, saved.collapsed || {}), side: Object.assign({}, saved.side || {}) });
    } catch (e) { return JSON.parse(JSON.stringify(VT.DEFAULTS)); }
  }
  VT.S = load();
  VT.save = () => { try { localStorage.setItem(STORE, JSON.stringify(VT.S)); } catch (e) { /* private window */ } };
  VT.applyTheme = () => {
    const t = VT.S.theme;
    if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
  };
  VT.applyTheme();

  // "New since you last looked" (Claude's blue dot): per viewer, the time each track page was last opened. A first
  // visit takes everything as seen, so the sidebar does not open all blue.
  let seen = {};
  try { seen = JSON.parse(localStorage.getItem(SEEN) || '{}'); } catch (e) { seen = {}; }
  VT.seenAt = (id) => seen[id] || seen.__first || null;
  VT.markSeen = (id) => { seen[id] = Date.now(); try { localStorage.setItem(SEEN, JSON.stringify(seen)); } catch (e) { /* ok */ } };
  if (!seen.__first) { seen.__first = Date.now(); try { localStorage.setItem(SEEN, JSON.stringify(seen)); } catch (e) { /* ok */ } }

  // ------------------------------------------------------------------ small helpers
  VT.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const P = {
    home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>', review: '<path d="M4 12l5 5L20 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', chev: '<path d="M6 9l6 6 6-6"/>', caret: '<path d="M9 6l6 6-6 6"/>',
    display: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    rows: '<path d="M4 6h16M4 12h16M4 18h16"/>', table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
    board: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="13" rx="1"/>',
    cards: '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>',
    green: '<circle cx="12" cy="12" r="9"/><path d="M7.5 13.5l3-3 2.5 2.5 3.5-4"/>', yellow: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
    red: '<circle cx="12" cy="12" r="9"/><path d="M7.5 9.5l3 3 2.5-2.5 3.5 4"/>', none: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>', grid: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 4v16"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>', folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>', back: '<path d="M15 6l-6 6 6 6"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>', terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  };
  VT.P = P;
  VT.ic = (k, cls) => `<svg class="i${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" aria-hidden="true">${P[k] || ''}</svg>`;
  // Phosphor-style warning triangle, Claude's error glyph in the status slot.
  const WARN = '<svg viewBox="0 0 256 256" aria-hidden="true"><path d="M236.8 188.09 149.35 36.22a24.76 24.76 0 0 0-42.7 0L19.2 188.09a23.51 23.51 0 0 0 0 23.72A24.35 24.35 0 0 0 40.55 224h174.9a24.35 24.35 0 0 0 21.33-12.19 23.51 23.51 0 0 0 .02-23.72ZM120 104a8 8 0 0 1 16 0v40a8 8 0 0 1-16 0Zm8 88a12 12 0 1 1 12-12 12 12 0 0 1-12 12Z"/></svg>';

  /** Claude's status slot: kind is awaiting | running | ready | idle | error | done. */
  VT.sd = (kind, title) => `<span class="sd ${kind}" data-dot="${kind}"${title ? ` title="${VT.esc(title)}"` : ''}>${kind === 'error' ? WARN : '<i></i>'}</span>`;

  VT.secondsSince = (iso) => (iso ? Math.max(0, (Date.now() - Date.parse(iso)) / 1000) : null);
  VT.dur = (s) => {
    if (s == null) return 'unknown';
    const m = Math.floor(s / 60);
    if (m < 1) return `${Math.round(s)}s`;
    if (m < 60) return `${m}m`;
    if (m < 2880) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
    return `${(m / 1440).toFixed(1)}d`;
  };
  VT.ago = (iso) => {
    const s = VT.secondsSince(iso);
    if (s == null) return 'unknown';
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 172800) return `${Math.floor(s / 3600)} h ago`;
    return `${(s / 86400).toFixed(1)} d ago`;
  };
  VT.short = (s) => (s == null ? '' : s < 3600 ? `${Math.max(1, Math.floor(s / 60))}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`);
  VT.fmtDate = (value) => {
    if (!value) return '';
    const d = new Date(String(value).length <= 10 ? value + 'T12:00:00' : value);
    return isNaN(d) ? String(value) : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };
  VT.fmtTime = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };
  VT.ageBadge = (s, title) => {
    if (s == null) return '';
    const cls = s >= 86400 ? 'a2' : s >= 7200 ? 'a1' : '';
    return `<span class="age ${cls}" title="${VT.esc(title || 'waiting ' + VT.dur(s))}">${VT.ic('clock')}${VT.short(s)}</span>`;
  };

  // ------------------------------------------------------------------ the document's words
  VT.RANK = { needs_you: 0, error: 1, stale: 2, working: 3, idle: 4, done: 5, archived: 6 };
  VT.HRANK = { red: 0, yellow: 1, green: 2, none: 3 };
  VT.WORD = { needs_you: 'Needs you', error: 'Error', stale: 'Stale', working: 'Working', idle: 'Idle', done: 'Done', archived: 'Archived', ended: 'Ended' };
  VT.HEALTH = { green: 'On track', yellow: 'At risk', red: 'Off track', none: '—' };
  VT.ACTIVE = (t) => t.state.word !== 'done' && t.state.word !== 'archived';
  VT.tracks = () => (VT.doc ? VT.doc.projects.flatMap((p) => p.tracks) : []);
  VT.findTrack = (id) => VT.tracks().find((t) => t.id === id) || null;
  VT.findProject = (id) => (VT.doc ? VT.doc.projects.find((p) => p.id === id) : null) || null;
  VT.projectOf = (t) => (VT.doc ? VT.doc.projects.find((p) => p.tracks.includes(t)) : null);
  VT.needAge = (t) => {
    const n = t.needs_you, parts = [];
    if (n.oldest_age_s != null) parts.push(n.oldest_age_s + (Date.now() - Date.parse(VT.doc.generated_at)) / 1000);
    for (const q of n.open_questions || []) parts.push(VT.secondsSince(q.ts));
    for (const s of t.sessions) if (s.live && s.status === 'waiting' && s.status_since) parts.push(VT.secondsSince(s.status_since));
    return parts.length ? Math.max(...parts) : null;
  };
  VT.needCount = (t) => (t.needs_you.open || 0) + (t.needs_you.open_questions || []).length + (t.needs_you.waiting_sessions || 0);
  VT.liveCount = (t) => t.sessions.filter((s) => s.live).length;

  /** The dot a track wears in the sidebar and lists, Claude's meanings: awaiting > error > running > ready > idle. */
  VT.trackDot = (t) => {
    const w = t.state.word;
    if (w === 'needs_you') return 'awaiting';
    if (w === 'error') return 'error';
    if (w === 'working') return 'running';
    if (w === 'done' || w === 'archived') return 'done';
    const last = t.last_action ? Date.parse(t.last_action.ts) : 0, at = VT.seenAt(t.id);
    if (last && at && last > at) return 'ready';
    return 'idle';
  };
  VT.sessionDot = (s) => {
    const w = s.state.word;
    if (w === 'needs_you') return 'awaiting';
    if (w === 'error') return 'error';
    if (w === 'working') return 'running';
    return 'idle';
  };
  VT.dotTitle = (t) => `${VT.WORD[t.state.word] || t.state.word}: ${t.state.why}`;
  VT.health = (c) => `<span class="hl ${c}">${VT.ic(c)}${VT.HEALTH[c]}</span>`;
  VT.stateWord = (t, opts) => {
    const w = t.state.word;
    if (w === 'needs_you') {
      const inner = `${VT.sd('awaiting')}${VT.WORD[w]} · ${VT.needCount(t)}`;
      const href = `#/review?track=${encodeURIComponent(t.id)}`;
      const word = (opts && opts.plain) ? `<span class="stw needs_you">${inner}</span>`
        : `<a class="stw needs_you needs" href="${href}" title="${VT.esc(t.state.why)} · open Review">${inner}</a>`;
      return word + ' ' + VT.ageBadge(VT.needAge(t), t.needs_you.unknown_ages ? `${t.needs_you.unknown_ages} question(s) have no recorded ask time` : null);
    }
    return `<span class="stw ${w}" title="${VT.esc(t.state.why)}">${VT.sd(VT.trackDot(t))}${VT.WORD[w]}</span>`;
  };

  /** How to open a session: Claude Desktop's own deep link (the handoff URI), Remote Control, or the resume command. */
  VT.openLinks = (s) => {
    const out = [];
    if (s.open && s.open.desktop) out.push(`<a class="openag" data-testid="vt-open-desktop" href="${VT.esc(s.open.desktop)}" title="Claude Desktop's own link for this session (${VT.esc(s.open.desktop)}). The system handler gives claude:// links to your primary Desktop profile; this session is on ${VT.esc(s.account)}.">${VT.ic('open')}Open</a>`);
    if (s.open && s.open.remote_control) out.push(`<a class="openag" href="${VT.esc(s.open.remote_control)}" target="_blank" rel="noopener" title="Remote Control: this session on claude.ai">${VT.ic('open')}Web</a>`);
    if (s.open && s.open.resume && !s.live) out.push(`<button class="openag" data-act="copy" data-text="${VT.esc(s.open.resume)}" title="${VT.esc(s.open.resume)}">${VT.ic('copy')}Resume</button>`);
    if (!out.length) out.push(`<span class="openag none" title="live in ${VT.esc(s.entrypoint || 'Claude Code')} with no Desktop id or Remote Control link; resuming a live session could fork it">no link</span>`);
    return out.join('');
  };

  /** The one Open a dense row has room for: the Desktop's deep link, else Remote Control, else the resume command. */
  VT.openPrimary = (s) => {
    const o = s.open || {};
    if (o.desktop) return `<a class="openag" data-testid="vt-open-desktop" href="${VT.esc(o.desktop)}" title="Open in Claude Desktop (${VT.esc(o.desktop)}); claude:// links go to your primary Desktop profile, this session is on ${VT.esc(s.account)}">${VT.ic('open')}Open</a>`;
    if (o.remote_control) return `<a class="openag" href="${VT.esc(o.remote_control)}" target="_blank" rel="noopener" title="Remote Control: this session on claude.ai">${VT.ic('open')}Open</a>`;
    return VT.openLinks(s);
  };

  /** An inline SVG sparkline over points [{x: number, y: number|null}], y may be null (unmeasured: a gap). */
  VT.sparkline = (points, o) => {
    o = Object.assign({ w: 120, h: 28, pad: 2, target: null, xmin: null, xmax: null, cls: '' }, o || {});
    const pts = points.filter((p) => p.y != null && isFinite(p.y));
    if (!pts.length) return `<svg class="spark ${o.cls}" width="${o.w}" height="${o.h}" viewBox="0 0 ${o.w} ${o.h}" aria-hidden="true"><line x1="0" x2="${o.w}" y1="${o.h / 2}" y2="${o.h / 2}" class="spark-none"/></svg>`;
    const xs = points.map((p) => p.x), ys = pts.map((p) => p.y).concat(o.target != null ? [o.target] : []);
    const x0 = o.xmin != null ? o.xmin : Math.min(...xs), x1 = o.xmax != null ? o.xmax : Math.max(...xs);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const X = (x) => o.pad + (x1 === x0 ? (o.w - 2 * o.pad) / 2 : ((x - x0) / (x1 - x0)) * (o.w - 2 * o.pad));
    const Y = (y) => o.h - o.pad - ((y - y0) / (y1 - y0)) * (o.h - 2 * o.pad);
    let d = '', pen = false;
    for (const p of points) {
      if (p.y == null || !isFinite(p.y)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)} `; pen = true;
    }
    const last = pts[pts.length - 1];
    const tgt = o.target != null ? `<line class="spark-target" x1="0" x2="${o.w}" y1="${Y(o.target).toFixed(1)}" y2="${Y(o.target).toFixed(1)}"/>` : '';
    return `<svg class="spark ${o.cls}" width="${o.w}" height="${o.h}" viewBox="0 0 ${o.w} ${o.h}" aria-hidden="true">${tgt}<path d="${d}"/><circle cx="${X(last.x).toFixed(1)}" cy="${Y(last.y).toFixed(1)}" r="2"/></svg>`;
  };

  // ------------------------------------------------------------------ fetch cache (detail documents, needs, roadmap)
  const cache = {};
  /** The cached JSON at url, fetching it when missing or older than ttl ms; re-renders when it arrives. */
  VT.load = (url, ttl) => {
    const e = cache[url] || (cache[url] = { data: null, error: null, at: 0, inflight: false, status: null });
    if (!e.inflight && (!e.at || Date.now() - e.at > (ttl == null ? 15000 : ttl))) {
      e.inflight = true;
      fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' })
        .then(async (r) => {
          e.status = r.status;
          const body = await r.json().catch(() => null);
          if (!r.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${r.status}`);
          e.data = body; e.error = null;
        })
        .catch((err) => { e.error = err && err.message ? err.message : String(err); })
        .finally(() => { e.inflight = false; e.at = Date.now(); VT.render(); });
    }
    return e;
  };
  VT.invalidate = (prefix) => { for (const k of Object.keys(cache)) if (k.startsWith(prefix)) cache[k].at = 0; };

  // ------------------------------------------------------------------ routing + areas
  VT.pages = {};
  VT.page = (name, spec) => { VT.pages[name] = spec; };
  VT.actions = {};
  VT.parseRoute = () => {
    const raw = (location.hash || '#/').slice(1);
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const query = {};
    new URLSearchParams(qs || '').forEach((v, k) => { query[k] = v; });
    if (!parts.length) return { name: 'home', id: null, query };
    if (parts[0] === 'review') return { name: 'review', id: null, query };
    if ((parts[0] === 'project' || parts[0] === 'track') && parts[1]) return { name: parts[0], id: parts[1], query };
    return { name: 'home', id: null, query };
  };
  VT.route = VT.parseRoute();
  VT.go = (hash) => { if (location.hash !== hash) location.hash = hash; else VT.render(); };

  // ------------------------------------------------------------------ toast + copy
  VT.toastMsg = null;
  let toastTimer = null;
  VT.toast = (msg) => { VT.toastMsg = msg; clearTimeout(toastTimer); toastTimer = setTimeout(() => { VT.toastMsg = null; VT.render(); }, 3200); VT.render(); };
  VT.copy = async (text, what) => {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const area = document.createElement('textarea'); area.value = text; document.body.appendChild(area); area.select();
      try { document.execCommand('copy'); } finally { area.remove(); }
    }
    VT.toast(what ? `Copied ${what}` : 'Copied: ' + (text.length > 120 ? text.slice(0, 117) + '…' : text));
  };
})();
