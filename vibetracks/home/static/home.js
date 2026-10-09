/* The Vibe Tracks home page (docs/peps/0001), ported from the accepted Linear mock
   (reports/media/vibetracks-linear-proposals-2026-10-06/src/mock.js): initiatives-style rows (project -> track ->
   session), aligned ledger columns, the always-on sidebar with the account button bottom-left, a Display popover
   (Rows / Table / Board / Cards), age badges on needs-you, and no inbox list.

   It renders ONE document, vibetracks-home/1 from `doc` (beside this page), polled every 10 s, and nothing else:
   no fixture, no state of its own beyond view preferences. A field the backend could not observe is null and reads
   "unknown" (or says what is missing), never 0 and never "fine". Rows click through to Clank's track pages and
   review, which stay where they are. Hooks for checks: window.__vtHomeDoc, #vt-home[data-ready="1"]. */
(function () {
  'use strict';
  const root = document.getElementById('vt-home');
  const DOC_URL = 'doc';
  const POLL_MS = 10000;
  const STORE = 'vt-home-ui-v1';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const DEFAULTS = { view: 'rows', group: 'project', order: 'attention', tabset: 'active', subs: true, ended: false,
    props: { target: 1, health: 1, prog: 1, state: 1, work: 1 }, collapsed: {}, otherOpen: false };
  const S = load();
  let doc = null, error = null, fetchedAt = 0, pop = null, drawer = false, toastMsg = null, toastTimer = null, inflight = false;

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
      return Object.assign({}, DEFAULTS, saved, { props: Object.assign({}, DEFAULTS.props, saved.props || {}), collapsed: Object.assign({}, saved.collapsed || {}) });
    } catch (e) { return JSON.parse(JSON.stringify(DEFAULTS)); }
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (e) { /* private window: preferences just do not stick */ } }

  // ------------------------------------------------------------------ icons (the mock's)
  const P = {
    home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>', review: '<path d="M4 12l5 5L20 6"/>',
    chev: '<path d="M6 9l6 6 6-6"/>', display: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    rows: '<path d="M4 6h16M4 12h16M4 18h16"/>', table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
    board: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="13" rx="1"/>',
    cards: '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>',
    green: '<circle cx="12" cy="12" r="9"/><path d="M7.5 13.5l3-3 2.5 2.5 3.5-4"/>', yellow: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
    red: '<circle cx="12" cy="12" r="9"/><path d="M7.5 9.5l3 3 2.5-2.5 3.5 4"/>', none: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>', grid: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 4v16"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
  };
  const ic = (k) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${P[k] || ''}</svg>`;

  // ------------------------------------------------------------------ formatting (relative to now, so ages tick between polls)
  const secondsSince = (iso) => (iso ? Math.max(0, (Date.now() - Date.parse(iso)) / 1000) : null);
  function dur(s) {
    if (s == null) return 'unknown';
    const m = Math.floor(s / 60);
    if (m < 1) return `${Math.round(s)}s`;
    if (m < 60) return `${m}m`;
    if (m < 2880) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
    return `${(m / 1440).toFixed(1)}d`;
  }
  function ago(iso) {
    const s = secondsSince(iso);
    if (s == null) return 'unknown';
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 172800) return `${Math.floor(s / 3600)} h ago`;
    return `${(s / 86400).toFixed(1)} d ago`;
  }
  const short = (s) => (s < 3600 ? `${Math.max(1, Math.floor(s / 60))}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`);
  function fmtDate(value) {
    if (!value) return '';
    const d = new Date(value + 'T12:00:00');
    return isNaN(d) ? value : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  function ageBadge(s, title) {
    if (s == null) return '';
    const cls = s >= 86400 ? 'a2' : s >= 7200 ? 'a1' : '';
    const frac = Math.min(1, s / 86400), a = frac * 2 * Math.PI, x = 12 + 8 * Math.sin(a), y = 12 - 8 * Math.cos(a);
    const pie = frac >= 1 ? '<circle cx="12" cy="12" r="8" fill="currentColor" stroke="none"/>' : `<path d="M12 12V4A8 8 0 ${frac > 0.5 ? 1 : 0} 1 ${x.toFixed(2)} ${y.toFixed(2)}Z" fill="currentColor" stroke="none"/>`;
    return `<span class="age ${cls}" title="${esc(title || 'sitting ' + dur(s))}"><svg viewBox="0 0 24 24" class="i"><circle cx="12" cy="12" r="9.5"/>${pie}</svg>${short(s)}</span>`;
  }

  // ------------------------------------------------------------------ the document's words
  const RANK = { needs_you: 0, error: 1, stale: 2, working: 3, idle: 4, done: 5, archived: 6 };
  const HRANK = { red: 0, yellow: 1, green: 2, none: 3 };
  const WORD = { needs_you: 'Needs you', error: 'Error', stale: 'Stale', working: 'Working', idle: 'Idle', done: 'Done', archived: 'Archived', ended: 'Ended' };
  const HEALTH = { green: 'On track', yellow: 'At risk', red: 'Off track', none: '—' };
  const ACTIVE = (t) => t.state.word !== 'done' && t.state.word !== 'archived';
  const tracks = () => (doc ? doc.projects.flatMap((p) => p.tracks) : []);
  const projectOf = (t) => doc.projects.find((p) => p.tracks.includes(t));
  // How long the track's need has been sitting: the oldest triage question with a known ask time, else the oldest
  // unanswered question in a transcript, else how long a waiting session has been waiting. null when unobserved.
  function needAge(t) {
    const n = t.needs_you;
    const parts = [];
    if (n.oldest_age_s != null) parts.push(n.oldest_age_s + (Date.now() - Date.parse(doc.generated_at)) / 1000);
    for (const q of n.open_questions || []) parts.push(secondsSince(q.ts));
    for (const s of t.sessions) if (s.live && s.status === 'waiting' && s.status_since) parts.push(secondsSince(s.status_since));
    return parts.length ? Math.max(...parts) : null;
  }
  function needCount(t) {
    const n = t.needs_you;
    return (n.open || 0) + (n.open_questions || []).length + (n.waiting_sessions || 0);
  }
  const health = (c) => `<span class="hl ${c}">${ic(c)}${HEALTH[c]}</span>`;
  function stateCell(t) {
    const w = t.state.word;
    if (w === 'needs_you') {
      const href = t.links.review;
      const inner = `<span class="dot"></span>${WORD[w]} · ${needCount(t)}`;
      const word = href ? `<a class="stw needs_you needs" href="${esc(href)}" title="${esc(t.state.why)} · open Review">${inner}</a>` : `<span class="stw needs_you" title="${esc(t.state.why)}">${inner}</span>`;
      return word + ' ' + ageBadge(needAge(t), t.needs_you.unknown_ages ? `${t.needs_you.unknown_ages} question(s) have no recorded ask time` : null);
    }
    return `<span class="stw ${w}" title="${esc(t.state.why)}"><span class="dot"></span>${WORD[w]}</span>`;
  }
  function progressCell(t) {
    const p = t.progress;
    if (p.value == null) return `<span class="unk" title="${esc(p.unknown || '')}">${esc(p.unknown || 'unknown')}</span>`;
    const of = p.of != null ? p.of : null;
    const frac = of ? Math.max(0, Math.min(1, p.value / of)) : null;
    const text = of != null ? `${p.value} / ${of}` : `${p.value}${p.unit ? ' ' + p.unit : ''}`;
    return `<span class="prog" title="${esc((p.label || '') + (p.iteration ? ' · ' + p.iteration : '') + (p.source ? ' · ' + p.source : ''))}">${frac != null ? `<span class="meter"><b style="width:${Math.round(frac * 100)}%"></b></span>` : ''}<span class="num">${esc(text)}</span></span>`;
  }
  function workCell(item, isTrack) {
    const w = item.worked || {}, last = item.last_action;
    const loop = isTrack && item.last_loop_write ? ` · loop write ${ago(item.last_loop_write.ts)}` : isTrack ? ' · loop write unknown' : '';
    const title = `worked ${dur(w.h24_s)} in 24 h, ${dur(w.d7_s)} in 7 d (gaps up to 15 min between agent entries, overlap counted once)${loop}`;
    return `<span class="wk" title="${esc(title)}"><span>${w.h24_s ? 'worked ' + dur(w.h24_s) : 'no work today'}</span><small>${last ? 'last action ' + ago(last.ts) : 'no agent entry in 7 d'}</small></span>`;
  }
  function openAgent(s) {
    if (s.open.remote_control) return `<a class="openag" href="${esc(s.open.remote_control)}" target="_blank" rel="noopener" title="Open this session's Remote Control link">${ic('open')}Open</a>`;
    if (!s.live) return `<button class="openag" data-act="copy" data-text="${esc(s.open.resume)}" title="${esc(s.open.resume)}">${ic('copy')}Resume</button>`;
    return `<span class="openag none" title="live in ${esc(s.entrypoint || 'Claude Code')}; it has no Remote Control link, and resuming a live session could fork it">no link</span>`;
  }

  // ------------------------------------------------------------------ layout pieces
  const COLS = [['target', 'Target'], ['health', 'Health'], ['prog', 'Progress'], ['state', 'State'], ['work', 'Worked · last action']];
  const WIDTH = { target: '78px', health: '104px', prog: '132px', state: '168px', work: '160px' };
  const colStyle = () => '--cols: minmax(220px,1fr) ' + COLS.filter(([k]) => S.props[k]).map(([k]) => WIDTH[k]).join(' ');
  const cells = (o) => COLS.filter(([k]) => S.props[k]).map(([k]) => `<div class="c-${k}">${o[k] || ''}</div>`).join('');
  function indent(depth) {
    if (!depth) return '';
    // WHY a CSS variable: 22 px a level on a desktop, 12 px on a phone, where the name column is all there is.
    let s = `<span class="ind" style="width:calc(var(--ind) * ${depth})">`;
    for (let i = 0; i < depth; i++) s += `<i class="${i === depth - 1 ? 'el' : ''}" style="left:calc(var(--ind) * ${i + 0.5} - 1px)"></i>`;
    return s + '</span>';
  }
  function visible(t) {
    if (S.tabset === 'active') return ACTIVE(t);
    if (S.tabset === 'done') return !ACTIVE(t);
    return true;
  }
  function sorted(list) {
    const out = list.slice();
    const lastTs = (t) => (t.last_action ? Date.parse(t.last_action.ts) : 0);
    if (S.order === 'attention') out.sort((a, b) => RANK[a.state.word] - RANK[b.state.word] || (needAge(b) || 0) - (needAge(a) || 0) || (a.priority || 999) - (b.priority || 999));
    else if (S.order === 'recent') out.sort((a, b) => lastTs(b) - lastTs(a));
    else out.sort((a, b) => a.title.localeCompare(b.title));
    return out;
  }
  function kids(t) {
    if (!S.subs) return [];
    return t.sessions.filter((s) => s.live || (S.ended && s.last_action && secondsSince(s.last_action.ts) < 86400));
  }
  function sessionRow(s, depth, trackId) {
    const title = s.title || s.id.slice(0, 8);
    const join = s.join.by ? `matched by ${s.join.by}: ${s.join.value}` : 'no track rule matches';
    return `<div class="tr sess" data-testid="vt-home-session" data-session-id="${esc(s.id)}" data-track="${esc(trackId || '')}">
      <div class="nm">${indent(depth)}<span style="width:18px;flex:none"></span><span class="chip"><b>${esc(s.account)}</b></span>
        <span class="t2" style="flex:1"><span class="t" title="${esc(title + ' · ' + (s.branch || 'no branch') + ' · ' + (s.cwd || ''))}">${esc(title)}</span><small title="${esc(join)}"><span class="ph">${esc(s.account)} · </span>${esc(join)}${s.subagent_files ? ' · ' + s.subagent_files + ' subagent file' + (s.subagent_files > 1 ? 's' : '') : ''}</small></span>${openAgent(s)}</div>
      ${cells({ state: `<span class="stw ${s.state.word}" title="${esc(s.live ? 'live · ' + (s.status || 'unknown status') + (s.waiting_for ? ' (' + s.waiting_for + ')' : '') : 'ended (no live process)')}"><span class="dot"></span>${WORD[s.state.word] || s.state.word}${s.live && s.status ? ' · ' + esc(s.status) : ''}</span>`, work: workCell(s, false) })}</div>`;
  }
  function trackRow(t, depth) {
    const ks = kids(t);
    const open = ks.length && !S.collapsed['t:' + t.id];
    const link = t.links.track;
    const name = link ? `<a class="t" href="${esc(link)}" title="Open ${esc(t.title)} in Clank">${esc(t.title)}</a>` : `<span class="t" title="${esc(t.title)} · no KPI adapter yet, so no track page">${esc(t.title)}</span>`;
    let h = `<div class="tr ${ACTIVE(t) ? '' : 'muted'}" id="row-${esc(t.id)}" data-testid="vt-home-track" data-track-id="${esc(t.id)}" data-state="${esc(t.state.word)}" data-act="track" data-id="${esc(t.id)}">
      <div class="nm">${indent(depth)}${ks.length ? `<button class="chev ${open ? '' : 'closed'}" data-act="fold" data-id="t:${esc(t.id)}" aria-label="Show sessions">${ic('chev')}</button>` : '<span style="width:18px;flex:none"></span>'}
        <span class="t2">${name}<small title="${esc(t.state.why)}">${esc(t.state.why)}</small></span></div>
      ${cells({ target: t.target ? `<span class="num" title="from the note's vibe-target">${esc(fmtDate(t.target))}</span>` : '<span class="faint" title="no target written in the note">—</span>',
        health: health(t.health.color), prog: progressCell(t), state: stateCell(t), work: workCell(t, true) })}</div>`;
    if (open) for (const s of ks) h += sessionRow(s, depth + 1, t.id);
    return h;
  }
  function projectRow(p, list) {
    const c = { green: 0, yellow: 0, red: 0 };
    let w = 0, need = 0;
    list.forEach((t) => { if (c[t.health.color] != null) c[t.health.color]++; w += t.worked.h24_s; if (t.state.word === 'needs_you') need++; });
    const worst = list.length ? list.map((t) => t.health.color).sort((a, b) => HRANK[a] - HRANK[b])[0] : 'none';
    const open = !S.collapsed['p:' + p.id];
    const roll = `<span class="roll">${c.green ? `<span><span class="dot green"></span>${c.green}</span>` : ''}${c.yellow ? `<span><span class="dot yellow"></span>${c.yellow}</span>` : ''}${c.red ? `<span><span class="dot red"></span>${c.red}</span>` : ''}</span>`;
    const live = list.reduce((a, t) => a + t.sessions.filter((s) => s.live).length, 0);
    return `<div class="tr proj" id="row-p-${esc(p.id)}" data-act="fold" data-id="p:${esc(p.id)}"><div class="nm"><button class="chev ${open ? '' : 'closed'}" data-act="fold" data-id="p:${esc(p.id)}" aria-label="Fold project">${ic('chev')}</button><span class="pico" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span>
      <span class="t2"><span class="t">${esc(p.name)}</span><small>${list.length} track${list.length === 1 ? '' : 's'} · ${live} live session${live === 1 ? '' : 's'}</small></span></div>
      ${cells({ target: p.target ? `<span class="num" title="earliest track target (${esc(p.target_from)})">${esc(fmtDate(p.target))}</span>` : '<span class="faint">—</span>',
        health: health(worst), prog: '', state: need ? `<span class="stw needs_you"><span class="dot"></span>${need} need${need > 1 ? '' : 's'} you</span>` : roll,
        work: `<span class="wk"><span>${w ? 'worked ' + dur(w) : 'no work today'}</span><small>${roll}</small></span>` })}</div>`;
  }
  function otherRows() {
    if (S.tabset === 'done' || !doc.other_sessions.length) return '';
    const n = doc.other_sessions.length;
    // WHY say how many wait: a waiting session with no track is still a person-blocked agent; the row stays folded
    // (Zach's default: nothing distracts) but never hides that someone is waiting.
    const waiting = doc.other_sessions.filter((s) => s.state.word === 'needs_you').length;
    const state = waiting ? `<span class="stw needs_you"><span class="dot"></span>${waiting} waiting</span>` : '';
    let h = `<div class="tr proj other" data-testid="vt-home-other-toggle" data-act="other"><div class="nm"><button class="chev ${S.otherOpen ? '' : 'closed'}" data-act="other" aria-label="Show other sessions">${ic('chev')}</button><span class="pico" style="background:#b9b8b4">·</span>
      <span class="t2"><span class="t">Other sessions (${n})</span><small>live sessions no track's vibe-sessions rule matches · shown so none disappears</small></span></div>${cells({ state })}</div>`;
    if (S.otherOpen) for (const s of doc.other_sessions) h += sessionRow(s, 1, '');
    return h;
  }
  function tree() {
    let h = `<div class="tree" style="${colStyle()}"><div class="thead"><div>Name</div>${COLS.filter(([k]) => S.props[k]).map(([k, l]) => `<div class="c-${k}">${l}</div>`).join('')}</div>`;
    const all = tracks().filter(visible);
    if (S.view === 'table' || S.group === 'none') {
      h += sorted(all).map((t) => trackRow(t, 0)).join('');
    } else if (S.group === 'health' || S.group === 'state') {
      const key = S.group;
      const groups = key === 'health' ? ['red', 'yellow', 'green', 'none'] : Object.keys(RANK);
      for (const g of groups) {
        const list = all.filter((t) => (key === 'health' ? t.health.color : t.state.word) === g);
        if (!list.length) continue;
        h += `<div class="tr proj" style="cursor:default"><div class="nm">${key === 'health' ? health(g) : `<span class="stw ${g}"><span class="dot"></span>${WORD[g]}</span>`}<span class="faint">${list.length}</span></div>${cells({})}</div>` + sorted(list).map((t) => trackRow(t, 1)).join('');
      }
    } else {
      for (const p of doc.projects) {
        const list = p.tracks.filter(visible);
        if (!list.length) continue;
        h += projectRow(p, list);
        if (!S.collapsed['p:' + p.id]) h += sorted(list).map((t) => trackRow(t, 1)).join('');
      }
    }
    if (!all.length) h += `<div class="tr" style="cursor:default"><div class="nm faint">No ${S.tabset === 'done' ? 'done or archived' : ''} tracks.</div></div>`;
    return h + otherRows() + '</div>';
  }
  function board() {
    const all = sorted(tracks().filter(visible));
    const cols = ['needs_you', 'error', 'stale', 'working', 'idle'];
    return `<div class="board">${cols.map((c) => { const list = all.filter((t) => t.state.word === c);
      return `<div class="col"><h4><span class="stw ${c}"><span class="dot"></span>${WORD[c]}</span><span class="faint">${list.length}</span></h4>
        ${list.map((t) => `<a class="card" ${t.links.track ? `href="${esc(t.links.track)}"` : ''} data-testid="vt-home-card" data-track-id="${esc(t.id)}"><div class="ct">${esc(t.title)}</div><div class="cw">${esc(t.state.why)}</div><div class="cm">${health(t.health.color)}${c === 'needs_you' ? ageBadge(needAge(t)) : `<span class="age">${t.last_action ? short(secondsSince(t.last_action.ts)) : ''}</span>`}</div></a>`).join('')}</div>`; }).join('')}</div>`;
  }
  function cards() {
    return `<div class="pcards">${doc.projects.map((p) => { const list = sorted(p.tracks.filter(visible)); if (!list.length) return '';
      return `<div class="pcard"><h3><span class="pico" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span><span class="ell">${esc(p.name)}</span><span class="faint num" style="font-size:12px">${esc(fmtDate(p.target))}</span></h3>
        ${list.map((t) => `<div class="li" data-act="track" data-id="${esc(t.id)}"><span class="ell">${esc(t.title)}</span>${health(t.health.color)}<span>${stateCell(t)}</span></div>`).join('')}</div>`; }).join('')}</div>`;
  }
  function summary() {
    const s = doc.summary;
    const parts = [`${s.tracks} active track${s.tracks === 1 ? '' : 's'}`];
    if (s.needs_you) parts.push(`<b style="color:var(--warn)">${s.needs_you} need${s.needs_you > 1 ? '' : 's'} you</b>`);
    if (s.error) parts.push(`<span style="color:var(--err)">${s.error} error</span>`);
    if (s.stale) parts.push(`${s.stale} stale`);
    if (s.working) parts.push(`${s.working} working`);
    parts.push(`${s.sessions_live} agent${s.sessions_live === 1 ? '' : 's'} live (${s.sessions_matched} on tracks, ${s.sessions_other} other)`);
    return parts.join(' · ');
  }
  function displayPop() {
    const GROUPS = [['project', 'Project'], ['health', 'Health'], ['state', 'State'], ['none', 'No grouping']];
    const ORDERS = [['attention', 'Needs you first'], ['recent', 'Last action'], ['name', 'Name']];
    const sel = (k, opts) => `<button class="sel" data-act="cycle" data-id="${k}">${opts.find((o) => o[0] === S[k])[1]}${ic('chev')}</button>`;
    const tog = (k, l) => `<div class="row"><span>${l}</span><button class="tog ${S[k] ? 'on' : ''}" data-act="toggle" data-id="${k}" aria-label="${l}" aria-pressed="${S[k] ? 'true' : 'false'}"></button></div>`;
    return `<div class="pop" style="right:36px;top:118px" data-pop data-testid="vt-home-display">
      <div class="views">${[['rows', 'Rows', 1], ['table', 'Table', 2], ['board', 'Board', 3], ['cards', 'Cards', 4]].map(([k, l, n]) => `<button class="${S.view === k ? 'on' : ''}" data-act="view" data-id="${k}">${ic(k)}<span>${l}</span><kbd>${n}</kbd></button>`).join('')}</div>
      <div class="row"><span>${ic('rows')} Grouping</span>${sel('group', GROUPS)}</div>
      <div class="row"><span>${ic('display')} Ordering</span>${sel('order', ORDERS)}</div>
      <hr>${tog('subs', 'Show sessions under tracks')}${tog('ended', 'Include sessions ended in the last 24 h')}
      <hr><div class="lab">Display properties</div>
      <div class="props">${COLS.map(([k, l]) => `<button class="${S.props[k] ? 'on' : ''}" data-act="prop" data-id="${k}">${l}</button>`).join('')}</div></div>`;
  }
  function sidebar() {
    const r = doc ? doc.review : null;
    let h = `<aside class="side" data-testid="vt-home-sidebar" aria-label="Navigation">
      <a class="nav on" href="./">${ic('home')}<span class="ell">Home</span></a>`;
    if (r) {
      h += r.href ? `<a class="nav" href="${esc(r.href)}" title="Open Review on the track that has waited longest: ${esc(r.tracks.map((t) => t.title + ' ' + t.blocking + ' blocking · ' + t.open + ' open').join('; '))}">${ic('review')}<span class="ell">Review</span>${ageBadge(r.oldest_age_s)}${r.open ? `<span class="badge">${r.open}</span>` : ''}</a>`
        : `<span class="nav faint" title="no loop triage file wants an answer">${ic('review')}<span class="ell">Review</span></span>`;
      h += `<a class="nav" href="${esc(doc.links.workbench)}" title="Clank: the dashboard, track pages and files">${ic('grid')}<span class="ell">Workbench</span></a><div class="hd">Projects</div>`;
      for (const p of doc.projects) {
        h += `<button class="nav" data-act="jump" data-id="p-${esc(p.id)}"><span class="pico" style="background:${esc(p.color)};width:16px;height:16px;font-size:9px">${esc(p.name[0].toUpperCase())}</span><span class="ell">${esc(p.name)}</span></button>`;
        for (const t of p.tracks) {
          if (!ACTIVE(t)) continue;
          h += `<button class="nav tk" data-act="jump" data-id="${esc(t.id)}" title="${esc(t.state.label + ': ' + t.state.why)}"><span class="dot ${t.health.color}"></span><span class="ell">${esc(t.title)}</span>${t.state.word === 'needs_you' ? ageBadge(needAge(t)) : ''}</button>`;
        }
      }
      const n = doc.accounts.length;
      h += `<button class="acct" data-act="acct" data-testid="vt-home-account"><span class="av">Z</span>Zach <span class="faint">· ${n} account${n === 1 ? '' : 's'}</span></button>`;
      if (pop === 'acct') h += `<div class="pop acctpop" data-pop><div class="lab">Claude Code accounts on this machine</div>${doc.accounts.map((a) => `<div class="row"><span class="ell" title="${esc(a.home)}">${esc(a.id)}</span><span class="faint">${a.sessions_live} live</span></div>`).join('')}</div>`;
    }
    return h + '</aside>';
  }
  function page() {
    if (!doc) {
      return `<div class="page"><h1>Tracks</h1>${error ? `<div class="banner">The home could not be read: ${esc(error)}. Retrying every ${POLL_MS / 1000} s.</div>` : '<p class="sub">Reading sessions and transcripts… the first read after a restart takes about 15 s.</p>'}</div>`;
    }
    const body = S.view === 'board' ? board() : S.view === 'cards' ? cards() : tree();
    const fresh = fetchedAt ? `<span class="fresh" title="generated ${esc(doc.generated_at)}">updated ${ago(new Date(fetchedAt).toISOString())}</span>` : '';
    const t = doc.sources.transcripts, j = joinCounts();
    return `<div class="page"><div class="crumb">Home</div><h1>Tracks</h1><p class="sub">${summary()}</p>
      ${error ? `<div class="banner">Last refresh failed (${esc(error)}); showing the document from ${esc(ago(new Date(fetchedAt).toISOString()))}.</div>` : ''}
      <div class="bar">${[['active', 'Active'], ['done', 'Done'], ['all', 'All tracks']].map(([k, l]) => `<button class="pill ${S.tabset === k ? 'on' : ''}" data-act="tabset" data-id="${k}">${l}</button>`).join('')}
        <span class="spacer"></span>${fresh}<button class="btn" data-act="refresh" title="Refresh now">${ic('refresh')}</button><button class="btn ${pop === 'display' ? 'on' : ''}" data-act="display" data-testid="vt-home-display-button">${ic('display')}Display</button></div>
      ${body}
      <div class="foot">Derived from Claude Code's own files and the loops' files, never from what an agent says: ${t.recent} transcripts from the last 7 days (${t.subagent_files} of them subagents) of ${t.files} on disk · sessions matched by ${j} · generated ${esc(doc.generated_at)}${doc.problems.length ? ` · ${doc.problems.length} problem${doc.problems.length > 1 ? 's' : ''}: ${esc(doc.problems.map((p) => p.path + ': ' + p.error).join('; '))}` : ''}</div></div>`;
  }
  function joinCounts() {
    const c = { branch: 0, cwd: 0, title: 0 };
    for (const t of tracks()) for (const s of t.sessions) if (s.live && c[s.join.by] != null) c[s.join.by]++;
    return `branch ${c.branch} · cwd ${c.cwd} · title ${c.title} (live)`;
  }

  // ------------------------------------------------------------------ render + events
  function render() {
    const y = window.scrollY;
    root.className = 'vlm' + (drawer ? ' drawer' : '');
    root.innerHTML = `${sidebar()}<div class="scrim" data-act="drawer"></div><main class="main"><div class="topbar"><button class="btn" data-testid="vt-home-menu" data-act="drawer" aria-label="Open the sidebar">${ic('menu')}</button><b>Tracks</b></div>${page()}${pop === 'display' && doc ? displayPop() : ''}</main>${toastMsg ? `<div class="toast" role="status">${esc(toastMsg)}</div>` : ''}`;
    window.scrollTo(0, y);
    if (doc) root.dataset.ready = '1';
  }
  async function refresh() {
    if (inflight) return;
    inflight = true;
    try {
      const response = await fetch(DOC_URL, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${response.status}`);
      if (!body || body.schema !== 'vibetracks-home/1') throw new Error('not a vibetracks-home/1 document');
      doc = body; window.__vtHomeDoc = body; error = null; fetchedAt = Date.now();
    } catch (e) {
      error = e && e.message ? e.message : String(e);
    } finally {
      inflight = false;
    }
    render();
  }
  function toast(msg) { toastMsg = msg; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastMsg = null; render(); }, 3200); }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const area = document.createElement('textarea'); area.value = text; document.body.appendChild(area); area.select();
      try { document.execCommand('copy'); } finally { area.remove(); }
    }
    toast('Copied: ' + text);
  }
  function act(el, ev) {
    const a = el.dataset.act, id = el.dataset.id;
    if (a !== 'display' && a !== 'acct' && !el.closest('[data-pop]')) pop = null;
    switch (a) {
      case 'track': {
        const t = tracks().find((x) => x.id === id);
        if (ev.target.closest('a')) return; // a link inside the row navigates by itself
        if (t && t.links.track) { location.href = t.links.track; return; }
        if (t && kids(t).length) S.collapsed['t:' + id] = !S.collapsed['t:' + id];
        break;
      }
      case 'fold': S.collapsed[id] = !S.collapsed[id]; break;
      case 'other': S.otherOpen = !S.otherOpen; break;
      case 'display': pop = pop === 'display' ? null : 'display'; break;
      case 'acct': pop = pop === 'acct' ? null : 'acct'; break;
      case 'view': S.view = id; break;
      case 'cycle': {
        const L = id === 'group' ? ['project', 'health', 'state', 'none'] : ['attention', 'recent', 'name'];
        S[id] = L[(L.indexOf(S[id]) + 1) % L.length]; break;
      }
      case 'toggle': S[id] = !S[id]; break;
      case 'prop': S.props[id] = S.props[id] ? 0 : 1; break;
      case 'tabset': S.tabset = id; break;
      case 'drawer': drawer = !drawer; break;
      case 'refresh': refresh(); break;
      case 'copy': copy(el.dataset.text); break;
      case 'jump': {
        drawer = false;
        S.collapsed['p:' + (id.startsWith('p-') ? id.slice(2) : (projectOf(tracks().find((t) => t.id === id)) || {}).id)] = false;
        if (S.view === 'board' || S.view === 'cards') S.view = 'rows';
        save(); render();
        const row = document.getElementById('row-' + id);
        if (row) { row.scrollIntoView({ block: 'center' }); row.style.background = 'var(--accent-soft)'; setTimeout(() => { row.style.background = ''; }, 1200); }
        ev.preventDefault(); ev.stopPropagation(); return;
      }
    }
    save(); ev.stopPropagation(); render();
  }
  root.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-act]');
    if (el && root.contains(el)) {
      if (el.tagName === 'A' && el.getAttribute('href')) return;
      return act(el, ev);
    }
    if (pop && !ev.target.closest('[data-pop]')) { pop = null; render(); }
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.target.closest && ev.target.closest('input, textarea, select')) return;
    if (ev.key === 'Escape') { if (!pop && !drawer) return; pop = null; drawer = false; }
    else if (/^[1-4]$/.test(ev.key) && !ev.metaKey && !ev.ctrlKey && !ev.altKey) { S.view = ['rows', 'table', 'board', 'cards'][+ev.key - 1]; save(); }
    else return;
    ev.preventDefault(); render();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  render();
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
})();
