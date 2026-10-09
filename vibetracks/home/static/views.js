/* Vibe Tracks home · Home (B2): the accepted Linear initiatives table (Oct 6 mock, B1), restyled to Claude's tokens,
   over ONE document (GET doc) in four views: 1 Rows (project -> track -> live sessions on one grid), 2 Table (a flat
   ledger), 3 Board (state x project swimlanes, round 2's "respects each project"), 4 Cards (one card per project).
   Keys 1-4 switch views; the last view, grouping, ordering and columns are remembered per viewer.
   Every column of every row sits on ONE grid template so they align at every depth (Zach, Oct 6; measured by
   tests/browser/home_b2.py). A track row opens the track page; "Needs you" opens Review filtered to that track. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;
  const S = VT.S;

  // ------------------------------------------------------------------ cells
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
    const loop = isTrack && item.last_loop_write ? ` · loop write ${VT.ago(item.last_loop_write.ts)}` : isTrack ? ' · loop write unknown' : '';
    const title = `worked ${VT.dur(w.h24_s)} in 24 h, ${VT.dur(w.d7_s)} in 7 d (gaps up to 15 min between agent entries, overlap counted once)${loop}`;
    return `<span class="wk" title="${esc(title)}"><span>${w.h24_s ? 'worked ' + VT.dur(w.h24_s) : 'no work today'}</span><small>${last ? 'last action ' + VT.ago(last.ts) : 'no agent entry in 7 d'}</small></span>`;
  }
  const COLS = [['target', 'Target'], ['health', 'Health'], ['prog', 'Progress'], ['state', 'State'], ['work', 'Worked · last action']];
  const WIDTH = { target: '72px', health: '100px', prog: '128px', state: '172px', work: '156px' };
  const colStyle = () => '--cols: minmax(220px,1fr) ' + COLS.filter(([k]) => S.props[k]).map(([k]) => WIDTH[k]).join(' ');
  const cells = (o) => COLS.filter(([k]) => S.props[k]).map(([k]) => `<div class="c-${k}">${o[k] || ''}</div>`).join('');
  function indent(depth) {
    if (!depth) return '';
    let s = `<span class="ind" style="width:calc(var(--ind) * ${depth})">`;
    for (let i = 0; i < depth; i++) s += `<i class="${i === depth - 1 ? 'el' : ''}" style="left:calc(var(--ind) * ${i + 0.5} - 1px)"></i>`;
    return s + '</span>';
  }
  function visible(t) {
    if (S.tabset === 'active') return VT.ACTIVE(t);
    if (S.tabset === 'done') return !VT.ACTIVE(t);
    return true;
  }
  function sorted(list) {
    const out = list.slice();
    const lastTs = (t) => (t.last_action ? Date.parse(t.last_action.ts) : 0);
    if (S.order === 'attention') out.sort((a, b) => VT.RANK[a.state.word] - VT.RANK[b.state.word] || (VT.needAge(b) || 0) - (VT.needAge(a) || 0) || (a.priority || 999) - (b.priority || 999));
    else if (S.order === 'recent') out.sort((a, b) => lastTs(b) - lastTs(a));
    else out.sort((a, b) => a.title.localeCompare(b.title));
    return out;
  }
  function kids(t) {
    if (!S.subs) return [];
    return t.sessions.filter((s) => s.live || (S.ended && s.last_action && VT.secondsSince(s.last_action.ts) < 86400));
  }
  function sessionRow(s, depth, trackId) {
    const title = s.title || s.id.slice(0, 8);
    const join = s.join.by ? `matched by ${s.join.by}: ${s.join.value}` : (s.projects && s.projects.length ? `in this project's folders · no track rule matches` : 'no track rule matches');
    return `<div class="tr sess" data-testid="vt-home-session" data-session-id="${esc(s.id)}" data-track="${esc(trackId || '')}">
      <div class="nm">${indent(depth)}${VT.sd(VT.sessionDot(s), s.live ? 'live · ' + (s.status || 'unknown status') : 'ended')}<span class="chip"><b>${esc(s.account)}</b></span>
        <span class="t2" style="flex:1"><span class="t" title="${esc(title + ' · ' + (s.branch || 'no branch') + ' · ' + (s.cwd || ''))}">${esc(title)}</span><small title="${esc(join)}"><span class="ph">${esc(s.account)} · </span>${esc(join)}${s.subagent_files ? ' · ' + s.subagent_files + ' subagent file' + (s.subagent_files > 1 ? 's' : '') : ''}</small></span><span class="opens">${VT.openPrimary(s)}</span></div>
      ${cells({ state: `<span class="stw ${s.state.word}" title="${esc(s.live ? 'live · ' + (s.status || 'unknown status') + (s.waiting_for ? ' (' + s.waiting_for + ')' : '') : 'ended (no live process)')}">${VT.WORD[s.state.word] || s.state.word}${s.live && s.status && s.status !== (VT.WORD[s.state.word] || '').toLowerCase() ? ' · ' + esc(s.status) : ''}</span>`, work: workCell(s, false) })}</div>`;
  }
  function trackRow(t, depth) {
    const ks = kids(t);
    const open = ks.length && !S.collapsed['t:' + t.id];
    const href = `#/track/${encodeURIComponent(t.id)}`;
    let h = `<div class="tr ${VT.ACTIVE(t) ? '' : 'muted'}" id="row-${esc(t.id)}" data-testid="vt-home-track" data-track-id="${esc(t.id)}" data-state="${esc(t.state.word)}" data-act="track" data-id="${esc(t.id)}">
      <div class="nm">${indent(depth)}${ks.length ? `<button class="chev ${open ? '' : 'closed'}" data-act="fold" data-id="t:${esc(t.id)}" aria-label="Show sessions">${VT.ic('chev')}</button>` : '<span class="chev-sp"></span>'}
        <span class="t2"><a class="t" href="${href}" title="Open the ${esc(t.title)} track page">${esc(t.title)}</a><small title="${esc(t.state.why)}">${esc(t.state.why)}</small></span></div>
      ${cells({ target: t.target ? `<span class="num" title="from the note's vibe-target">${esc(VT.fmtDate(t.target))}</span>` : '<span class="faint" title="no target written in the note">—</span>',
        health: VT.health(t.health.color), prog: progressCell(t), state: VT.stateWord(t), work: workCell(t, true) })}</div>`;
    if (open) for (const s of ks) h += sessionRow(s, depth + 1, t.id);
    return h;
  }
  function rollup(list) {
    const c = { green: 0, yellow: 0, red: 0 };
    list.forEach((t) => { if (c[t.health.color] != null) c[t.health.color]++; });
    return `<span class="roll">${c.green ? `<span><span class="hdot green"></span>${c.green}</span>` : ''}${c.yellow ? `<span><span class="hdot yellow"></span>${c.yellow}</span>` : ''}${c.red ? `<span><span class="hdot red"></span>${c.red}</span>` : ''}</span>`;
  }
  function projectRow(p, list) {
    let w = 0, need = 0;
    list.forEach((t) => { w += t.worked.h24_s; if (t.state.word === 'needs_you') need++; });
    const worst = list.length ? list.map((t) => t.health.color).sort((a, b) => VT.HRANK[a] - VT.HRANK[b])[0] : 'none';
    const open = !S.collapsed['p:' + p.id];
    const live = p.sessions_live || 0, loose = (p.sessions_unpinned || []).length, nf = (p.roots || []).length;
    const sub = `${list.length} track${list.length === 1 ? '' : 's'} · ${nf} folder${nf === 1 ? '' : 's'} · ${live} live${loose ? ` (${loose} on no track)` : ''}`;
    return `<div class="tr proj" id="row-p-${esc(p.id)}" data-testid="vt-home-project" data-project-id="${esc(p.id)}" data-act="fold" data-id="p:${esc(p.id)}"><div class="nm"><button class="chev ${open ? '' : 'closed'}" data-act="fold" data-id="p:${esc(p.id)}" aria-label="Fold project">${VT.ic('chev')}</button><span class="pico" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span>
      <span class="t2"><a class="t" href="#/project/${encodeURIComponent(p.id)}" title="Open the ${esc(p.name)} project page">${esc(p.name)}</a><small title="${esc((p.roots || []).map((r) => r.path).join(' · '))}">${esc(sub)}</small></span></div>
      ${cells({ target: p.target ? `<span class="num" title="earliest track target (${esc(p.target_from)})">${esc(VT.fmtDate(p.target))}</span>` : '<span class="faint">—</span>',
        health: VT.health(worst), prog: '', state: need ? `<span class="stw needs_you">${VT.sd('awaiting')}${need} need${need > 1 ? '' : 's'} you</span>` : rollup(list),
        work: `<span class="wk"><span>${w ? 'worked ' + VT.dur(w) : 'no work today'}</span><small>${rollup(list)}</small></span>` })}</div>`;
  }
  // Sessions no track's rule matches, grouped by the project whose folders hold them (Codex model): a session in a
  // folder two projects list shows under both; the rest are "in no project". Every one is listed (B1's contract).
  function otherRows() {
    const d = VT.doc;
    if (S.tabset === 'done' || !d.other_sessions.length) return '';
    const n = d.other_sessions.length;
    const waiting = d.other_sessions.filter((s) => s.state.word === 'needs_you').length;
    const state = waiting ? `<span class="stw needs_you">${VT.sd('awaiting')}${waiting} waiting</span>` : '';
    let h = `<div class="tr proj other" id="row-other" data-testid="vt-home-other-toggle" data-act="other"><div class="nm"><button class="chev ${S.otherOpen ? '' : 'closed'}" data-act="other" aria-label="Show sessions on no track">${VT.ic('chev')}</button><span class="pico muted">·</span>
      <span class="t2"><span class="t">Sessions on no track (${n})</span><small>live sessions no track's rule matches, under the project whose folders hold them · none disappears</small></span></div>${cells({ state })}</div>`;
    if (S.otherOpen) {
      for (const p of d.projects) {
        const list = p.sessions_unpinned || [];
        if (!list.length) continue;
        h += `<div class="tr sub" data-testid="vt-home-other-project" data-project-id="${esc(p.id)}"><div class="nm">${indent(1)}<span class="pico sm" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span><span class="t">${esc(p.name)}</span><span class="faint">${list.length}</span></div>${cells({})}</div>`;
        for (const s of list) h += sessionRow(s, 2, '');
      }
      const nowhere = d.other_sessions.filter((s) => !(s.projects || []).length);
      if (nowhere.length) {
        h += `<div class="tr sub" data-testid="vt-home-other-project" data-project-id=""><div class="nm">${indent(1)}<span class="pico sm muted">·</span><span class="t">In no project's folders</span><span class="faint">${nowhere.length}</span></div>${cells({})}</div>`;
        for (const s of nowhere) h += sessionRow(s, 2, '');
      }
    }
    return h;
  }
  function tree() {
    const d = VT.doc;
    let h = `<div class="tree" data-testid="vt-home-tree" style="${colStyle()}"><div class="thead"><div>Name</div>${COLS.filter(([k]) => S.props[k]).map(([k, l]) => `<div class="c-${k}">${l}</div>`).join('')}</div>`;
    const all = VT.tracks().filter(visible);
    if (S.view === 'table' || S.group === 'none') {
      h += sorted(all).map((t) => trackRow(t, 0)).join('');
    } else if (S.group === 'health' || S.group === 'state') {
      const key = S.group;
      const groups = key === 'health' ? ['red', 'yellow', 'green', 'none'] : Object.keys(VT.RANK);
      for (const g of groups) {
        const list = all.filter((t) => (key === 'health' ? t.health.color : t.state.word) === g);
        if (!list.length) continue;
        h += `<div class="tr proj" style="cursor:default"><div class="nm">${key === 'health' ? VT.health(g) : `<span class="stw ${g}">${VT.WORD[g]}</span>`}<span class="faint">${list.length}</span></div>${cells({})}</div>` + sorted(list).map((t) => trackRow(t, 1)).join('');
      }
    } else {
      for (const p of d.projects) {
        const list = p.tracks.filter(visible);
        if (!list.length) continue;
        h += projectRow(p, list);
        if (!S.collapsed['p:' + p.id]) h += sorted(list).map((t) => trackRow(t, 1)).join('');
      }
    }
    if (!all.length) h += `<div class="tr" style="cursor:default"><div class="nm faint">No ${S.tabset === 'done' ? 'done or archived' : ''} tracks.</div></div>`;
    return h + otherRows() + '</div>';
  }

  // ------------------------------------------------------------------ board: state x project swimlanes
  function card(t) {
    const p = t.progress, n = VT.liveCount(t);
    const prog = p.value != null ? `<span class="num">${esc(p.of != null ? `${p.value} / ${p.of}` : `${p.value}${p.unit ? ' ' + p.unit : ''}`)}</span>` : `<span class="unk">${esc(p.unknown || 'unknown')}</span>`;
    return `<a class="card" href="#/track/${encodeURIComponent(t.id)}" data-testid="vt-home-card" data-track-id="${esc(t.id)}" data-state="${esc(t.state.word)}" title="${esc(t.state.why)}">
      <div class="ct">${VT.sd(VT.trackDot(t))}<span class="ell">${esc(t.title)}</span></div>
      <div class="cw">${esc(t.state.why)}</div>
      <div class="cm"><span class="prog">${prog}</span><span class="cmr">${t.state.word === 'needs_you' ? VT.ageBadge(VT.needAge(t)) : ''}${n ? `<span class="n" title="${n} live session${n === 1 ? '' : 's'}">${VT.ic('terminal')}${n}</span>` : ''}</span></div></a>`;
  }
  function board() {
    const d = VT.doc;
    const cols = ['needs_you', 'error', 'stale', 'working', 'idle'].concat(S.tabset === 'active' ? [] : ['done', 'archived']);
    const projects = d.projects.filter((p) => p.tracks.some(visible));
    let h = `<div class="board" data-testid="vt-home-board" style="--bcols:${cols.length}"><div class="bh corner"></div>`;
    for (const c of cols) {
      const count = VT.tracks().filter((t) => visible(t) && t.state.word === c).length;
      h += `<div class="bh" data-col="${c}"><span class="stw ${c}">${VT.sd(c === 'needs_you' ? 'awaiting' : c === 'error' ? 'error' : c === 'working' ? 'running' : c === 'done' || c === 'archived' ? 'done' : 'idle')}${VT.WORD[c]}</span><span class="faint">${count}</span></div>`;
    }
    for (const p of projects) {
      const nf = (p.roots || []).length;
      h += `<div class="lane" data-testid="vt-home-lane" data-project-id="${esc(p.id)}"><a href="#/project/${encodeURIComponent(p.id)}" class="lname"><span class="pico sm" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span><span class="ell">${esc(p.name)}</span></a><small>${nf} folder${nf === 1 ? '' : 's'} · ${p.sessions_live || 0} live</small></div>`;
      for (const c of cols) {
        const list = sorted(p.tracks.filter((t) => visible(t) && t.state.word === c));
        h += `<div class="cell" data-col="${c}">${list.map(card).join('')}</div>`;
      }
    }
    if (!projects.length) h += `<div class="cell empty" style="grid-column:1/-1">No tracks.</div>`;
    return h + '</div>';
  }
  function cards() {
    const d = VT.doc;
    return `<div class="pcards" data-testid="vt-home-cards">${d.projects.map((p) => { const list = sorted(p.tracks.filter(visible)); if (!list.length) return '';
      const nf = (p.roots || []).length;
      return `<div class="pcard"><h3><span class="pico" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span><a class="ell" href="#/project/${encodeURIComponent(p.id)}">${esc(p.name)}</a><span class="faint num">${esc(VT.fmtDate(p.target))}</span></h3>
        <div class="psub">${nf} folder${nf === 1 ? '' : 's'} · ${p.sessions_live || 0} live · ${rollup(list)}</div>
        ${list.map((t) => `<a class="li" href="#/track/${encodeURIComponent(t.id)}" data-testid="vt-home-card" data-track-id="${esc(t.id)}">${VT.sd(VT.trackDot(t))}<span class="ell">${esc(t.title)}</span>${VT.health(t.health.color)}<span class="lis">${VT.stateWord(t, { plain: true })}</span></a>`).join('')}</div>`; }).join('')}</div>`;
  }
  function summary() {
    const s = VT.doc.summary;
    const parts = [`${s.tracks} active track${s.tracks === 1 ? '' : 's'}`];
    if (s.needs_you) parts.push(`<b class="warnword">${s.needs_you} need${s.needs_you > 1 ? '' : 's'} you</b>`);
    if (s.error) parts.push(`<span class="errword">${s.error} error</span>`);
    if (s.stale) parts.push(`${s.stale} stale`);
    if (s.working) parts.push(`${s.working} working`);
    parts.push(`${s.sessions_live} agent${s.sessions_live === 1 ? '' : 's'} live (${s.sessions_matched} on tracks, ${s.sessions_other} on no track)`);
    return parts.join(' · ');
  }
  function displayPop() {
    const GROUPS = [['project', 'Project'], ['health', 'Health'], ['state', 'State'], ['none', 'No grouping']];
    const ORDERS = [['attention', 'Needs you first'], ['recent', 'Last action'], ['name', 'Name']];
    const sel = (k, opts) => `<button class="sel" data-act="cycle" data-id="${k}">${opts.find((o) => o[0] === S[k])[1]}${VT.ic('chev')}</button>`;
    const tog = (k, l) => `<div class="row"><span>${l}</span><button class="tog ${S[k] ? 'on' : ''}" data-act="toggle" data-id="${k}" aria-label="${l}" aria-pressed="${S[k] ? 'true' : 'false'}"></button></div>`;
    return `<div class="pop displaypop" data-pop data-testid="vt-home-display">
      <div class="views">${[['rows', 'Rows', 1], ['table', 'Table', 2], ['board', 'Board', 3], ['cards', 'Cards', 4]].map(([k, l, n]) => `<button class="${S.view === k ? 'on' : ''}" data-act="view" data-id="${k}" data-testid="vt-view-${k}">${VT.ic(k)}<span>${l}</span><kbd>${n}</kbd></button>`).join('')}</div>
      <div class="row"><span>${VT.ic('rows')} Grouping</span>${sel('group', GROUPS)}</div>
      <div class="row"><span>${VT.ic('display')} Ordering</span>${sel('order', ORDERS)}</div>
      <hr>${tog('subs', 'Show sessions under tracks')}${tog('ended', 'Include sessions ended in the last 24 h')}
      <hr><div class="lab">Display properties</div>
      <div class="props">${COLS.map(([k, l]) => `<button class="${S.props[k] ? 'on' : ''}" data-act="prop" data-id="${k}">${l}</button>`).join('')}</div></div>`;
  }
  function joinCounts() {
    const c = { branch: 0, cwd: 0, title: 0 };
    for (const t of VT.tracks()) for (const s of t.sessions) if (s.live && c[s.join.by] != null) c[s.join.by]++;
    return `branch ${c.branch} · cwd ${c.cwd} · title ${c.title} (live)`;
  }

  VT.page('home', {
    title: () => 'Tracks',
    enter(r) { if (r.query.other) { S.otherOpen = true; VT.save(); } },
    render(r) {
      const d = VT.doc;
      const body = S.view === 'board' ? board() : S.view === 'cards' ? cards() : tree();
      const fresh = VT.fetchedAt ? `<span class="fresh" title="generated ${esc(d.generated_at)}">updated ${VT.ago(new Date(VT.fetchedAt).toISOString())}</span>` : '';
      const t = d.sources.transcripts;
      const VIEWS = [['rows', 'Rows', 1], ['table', 'Table', 2], ['board', 'Board', 3], ['cards', 'Cards', 4]];
      return `<div class="page wide" data-testid="vt-home-page" data-view="${esc(S.view)}"><div class="crumb">Home</div><h1>Tracks</h1><p class="sub">${summary()}</p>
        ${VT.error ? `<div class="banner">Last refresh failed (${esc(VT.error)}); showing the document from ${esc(VT.ago(new Date(VT.fetchedAt).toISOString()))}.</div>` : ''}
        <div class="bar">${[['active', 'Active'], ['done', 'Done'], ['all', 'All tracks']].map(([k, l]) => `<button class="pill ${S.tabset === k ? 'on' : ''}" data-act="tabset" data-id="${k}">${l}</button>`).join('')}
          <span class="vseg" role="tablist" aria-label="View">${VIEWS.map(([k, l, n]) => `<button class="${S.view === k ? 'on' : ''}" data-act="view" data-id="${k}" title="${l} (${n})" aria-label="${l}">${VT.ic(k)}<span class="vl">${l}</span></button>`).join('')}</span>
          <span class="spacer"></span>${fresh}<button class="btn icon" data-act="refresh" title="Refresh now" aria-label="Refresh">${VT.ic('refresh')}</button><button class="btn ${VT.pop === 'display' ? 'on' : ''}" data-act="pop" data-id="display" data-testid="vt-home-display-button">${VT.ic('display')}Display</button></div>
        ${body}
        <div class="foot">Derived from Claude Code's own files and the loops' files, never from what an agent says: ${t.recent} transcripts from the last 7 days (${t.subagent_files} of them subagents) of ${t.files} on disk · sessions matched by ${joinCounts()} · generated ${esc(d.generated_at)}${d.problems.length ? ` · ${d.problems.length} problem${d.problems.length > 1 ? 's' : ''}: ${esc(d.problems.map((p) => p.path + ': ' + p.error).join('; '))}` : ''}</div></div>`;
    },
    popover(pop) { return pop === 'display' ? displayPop() : ''; },
    after(main, r) {
      if (r.query.other && S.otherOpen && !VT._otherScrolled) {
        VT._otherScrolled = true;
        const row = document.getElementById('row-other');
        if (row) row.scrollIntoView({ block: 'start' });
      }
    },
    key(ev) {
      if (/^[1-4]$/.test(ev.key)) { S.view = ['rows', 'table', 'board', 'cards'][+ev.key - 1]; return true; }
      return false;
    },
  });

  Object.assign(VT.actions, {
    track(el, ev) {
      if (ev.target.closest('a,button')) return false;
      VT.go('#/track/' + encodeURIComponent(el.dataset.id)); return false;
    },
    fold(el) { S.collapsed[el.dataset.id] = !S.collapsed[el.dataset.id]; },
    other() { S.otherOpen = !S.otherOpen; },
    view(el) { S.view = el.dataset.id; },
    cycle(el) {
      const id = el.dataset.id;
      const L = id === 'group' ? ['project', 'health', 'state', 'none'] : ['attention', 'recent', 'name'];
      S[id] = L[(L.indexOf(S[id]) + 1) % L.length];
    },
    toggle(el) { S[el.dataset.id] = !S[el.dataset.id]; },
    prop(el) { S.props[el.dataset.id] = S.props[el.dataset.id] ? 0 : 1; },
    tabset(el) { S.tabset = el.dataset.id; },
  });
})();
