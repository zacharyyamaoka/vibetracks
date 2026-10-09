/* Vibe Tracks home · Project page (B2, 2026-10-09): GET project?id= (vibetracks-home-project/1) beside the home doc.
   One chart card puts the project's lagging north star over its tracks' leading KPIs on ONE shared date axis, so
   "did a track move before the goal did" reads straight down a week line. Then the tracks, the sessions and the
   folders that decide which sessions belong here. Nothing is filled in: a north star or KPI the backend could not
   observe says "unknown" and why, never 0. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;
  const DAY = 86400000;

  // Plot widths, measured after each render so the SVG draws at real pixels (text and strokes stay crisp on a phone).
  const W = { plot: 640 };
  const dayStart = (date) => new Date(String(date).slice(0, 10) + 'T00:00:00').getTime();
  const fmtNum = (v) => (typeof v === 'number' ? String(+v.toPrecision(6)) : String(v));
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  function lastMeasured(kpi) {
    const pts = (kpi && kpi.series) || [];
    for (let i = pts.length - 1; i >= 0; i--) if (pts[i].measured !== false && pts[i].value != null) return pts[i];
    return null;
  }
  function kpiValue(kpi) {
    const pt = lastMeasured(kpi);
    if (!pt) return null;
    if (pt.of != null) return `${fmtNum(pt.value)} of ${fmtNum(pt.of)}`;
    return `${fmtNum(pt.value)}${kpi.unit ? ' ' + kpi.unit : ''}`;
  }
  function progressCell(t) {
    const p = t.progress || {};
    if (p.value == null) return `<span class="unk" title="${esc(p.unknown || '')}">${esc(p.unknown || 'unknown')}</span>`;
    const frac = p.of ? Math.max(0, Math.min(1, p.value / p.of)) : null;
    const text = p.of != null ? `${p.value} / ${p.of}` : `${p.value}${p.unit ? ' ' + p.unit : ''}`;
    return `<span class="prog" title="${esc((p.label || '') + (p.iteration ? ' · ' + p.iteration : '') + (p.source ? ' · ' + p.source : ''))}">${frac != null ? `<span class="meter"><b style="width:${Math.round(frac * 100)}%"></b></span>` : ''}<span class="num">${esc(text)}</span></span>`;
  }

  // ------------------------------------------------------------------ the shared time axis
  function domain(doc, due) {
    const xs = [];
    // Only a reading that was taken places the axis: a dated point with no value is a gap, not a start.
    const add = (series) => (series || []).forEach((pt) => { if (pt.date && pt.measured !== false && pt.value != null) xs.push(dayStart(pt.date)); });
    (doc.leading || []).forEach((l) => { if (l.kpi) add(l.kpi.series); });
    if (doc.north_star && doc.north_star.kpi) add(doc.north_star.kpi.series);
    if (doc.days && doc.days.length) xs.push(dayStart(doc.days[0]));
    const last = doc.days && doc.days.length ? dayStart(doc.days[doc.days.length - 1]) + DAY : Date.now();
    const x0 = xs.length ? Math.min(...xs) : last - 7 * DAY;
    const x1 = Math.max(Date.now(), last, due ? dayStart(due) + DAY : 0);
    return { x0, x1 };
  }
  function axis(dom, w) {
    const pad = 8;
    const X = (t) => pad + ((t - dom.x0) / (dom.x1 - dom.x0 || 1)) * (w - 2 * pad);
    const weeks = [];
    const d = new Date(dom.x0);
    d.setHours(0, 0, 0, 0);
    while (d.getDay() !== 1) d.setDate(d.getDate() + 1);
    for (; d.getTime() <= dom.x1; d.setDate(d.getDate() + 7)) weeks.push(d.getTime());
    return { X, weeks, w };
  }
  function frame(ax, h, dueT, inner, cls) {
    let s = `<svg class="pg-plot ${cls || ''}" width="${ax.w}" height="${h}" viewBox="0 0 ${ax.w} ${h}" aria-hidden="true">`;
    for (const t of ax.weeks) s += `<line class="pg-wk" x1="${ax.X(t).toFixed(1)}" x2="${ax.X(t).toFixed(1)}" y1="0" y2="${h}"/>`;
    const now = ax.X(Date.now()).toFixed(1);
    s += `<line class="pg-today" x1="${now}" x2="${now}" y1="0" y2="${h}"/>`;
    if (dueT != null) s += `<line class="pg-due" x1="${ax.X(dueT).toFixed(1)}" x2="${ax.X(dueT).toFixed(1)}" y1="0" y2="${h}"/>`;
    return s + inner + '</svg>';
  }
  /** A series on its own range; a point with no date or no measured value breaks the line (a gap, never a zero). */
  function line(ax, series, h, opts) {
    opts = opts || {};
    const pts = (series || []).filter((p) => p.date && p.measured !== false && p.value != null && isFinite(p.value));
    if (!pts.length) return '';
    const ys = pts.map((p) => p.value).concat(opts.target != null ? [opts.target] : []);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const Y = (v) => h - 6 - ((v - y0) / (y1 - y0)) * (h - 12);
    let d = '', pen = false, dots = '';
    for (const p of series) {
      if (!p.date || p.measured === false || p.value == null || !isFinite(p.value)) { pen = false; continue; }
      const x = ax.X(dayStart(p.date) + DAY / 2).toFixed(1), y = Y(p.value).toFixed(1);
      d += `${pen ? 'L' : 'M'}${x} ${y} `; pen = true;
      dots += `<circle cx="${x}" cy="${y}" r="${opts.big ? 2.4 : 1.8}"><title>${esc((p.iteration ? p.iteration + ' · ' : '') + VT.fmtDate(p.date) + ': ' + fmtNum(p.value) + (p.of != null ? ' of ' + fmtNum(p.of) : ''))}</title></circle>`;
    }
    const tgt = opts.target != null ? `<line class="pg-target" x1="0" x2="${ax.w}" y1="${Y(opts.target).toFixed(1)}" y2="${Y(opts.target).toFixed(1)}"/>` : '';
    return `${tgt}<path class="pg-line${opts.big ? ' big' : ''}" d="${d}"/>${dots}`;
  }
  function bars(ax, daily, h) {
    let s = '';
    for (const d of daily || []) {
      if (!d.s) continue;
      const a = ax.X(dayStart(d.date)), b = ax.X(dayStart(d.date) + DAY);
      const bh = Math.max(1, Math.min(1, d.s / 86400) * (h - 8));
      s += `<rect class="pg-bar" x="${(a + 0.5).toFixed(1)}" y="${(h - 2 - bh).toFixed(1)}" width="${Math.max(1, b - a - 1).toFixed(1)}" height="${bh.toFixed(1)}"><title>${esc(VT.fmtDate(d.date) + ': ' + (d.s / 3600).toFixed(1) + ' h of agent work')}</title></rect>`;
    }
    return s;
  }
  function axisRow(ax, dueT) {
    const h = 22;
    const step = Math.max(1, Math.ceil(52 / Math.max(1, ax.X(DAY * 7) - ax.X(0))));
    let s = '';
    const now = ax.X(Date.now());
    const marks = [now].concat(dueT != null ? [ax.X(dueT)] : []);
    ax.weeks.forEach((t, i) => {
      const x = ax.X(t);
      if (i % step === 0 && marks.every((m) => Math.abs(m - x) > 44)) s += `<text class="pg-ax" x="${x.toFixed(1)}" y="15" text-anchor="middle">${esc(VT.fmtDate(new Date(t).toISOString()))}</text>`;
    });
    s += `<text class="pg-ax now" x="${now.toFixed(1)}" y="15" text-anchor="${now > ax.w - 30 ? 'end' : 'middle'}">today</text>`;
    if (dueT != null) s += `<text class="pg-ax due" x="${ax.X(dueT).toFixed(1)}" y="15" text-anchor="${ax.X(dueT) > ax.w - 40 ? 'end' : 'middle'}">due</text>`;
    return `<svg class="pg-plot" width="${ax.w}" height="${h}" viewBox="0 0 ${ax.w} ${h}" aria-hidden="true">${s}</svg>`;
  }

  // ------------------------------------------------------------------ the chart card
  function lagging(doc, ax, dueT, road) {
    const ns = doc.north_star || {};
    const decl = ns.declared;
    const H = 72;
    let label = '', plot = '';
    if (!decl) {
      label = `<div class="pg-big unk-big">unknown</div><small class="unk pg-wrap">${esc(ns.unknown || 'no north star declared')} (${esc(doc.project.descriptor || 'no descriptor path')})</small>`;
      plot = frame(ax, H, null, `<line class="pg-none" x1="0" x2="${ax.w}" y1="${H / 2}" y2="${H / 2}"/>`);
    } else if (decl.kind === 'kpi') {
      const k = ns.kpi;
      if (!k) {
        label = `<div class="pg-big unk-big">unknown</div><small class="unk pg-wrap">${esc(ns.unknown || 'the KPI is not reported')}</small>`;
        plot = frame(ax, H, null, `<line class="pg-none" x1="0" x2="${ax.w}" y1="${H / 2}" y2="${H / 2}"/>`);
      } else {
        const v = kpiValue(k);
        label = `<div class="pg-sm">${esc(k.label)} <span class="faint">· from <a href="#/track/${encodeURIComponent(decl.track)}">${esc(decl.track)}</a></span></div>
          <div class="pg-big">${v ? esc(v) : '<span class="unk-big">not measured yet</span>'}</div>
          <small class="faint">${esc(k.target && k.target.label ? 'target ' + k.target.label : 'no target')}${k.status ? ' · ' + esc(k.status.word) : ''}</small>`;
        const tv = k.target && typeof k.target.value === 'number' ? k.target.value : null;
        plot = frame(ax, H, null, line(ax, k.series, H, { target: tv, big: true }) || `<line class="pg-none" x1="0" x2="${ax.w}" y1="${H / 2}" y2="${H / 2}"/>`);
      }
    } else {
      const track = decl.track;
      const m = road && road.data && road.data.summary ? road.data.summary.milestone : null;
      if (road && road.data && m) {
        const left = Math.ceil((dayStart(m.due) + DAY - Date.now()) / DAY);
        label = `<div class="pg-sm">Milestone <span class="faint">· from <a href="#/track/${encodeURIComponent(track)}">${esc(track)}</a>'s roadmap</span></div>
          <div class="pg-big pg-wrap">${esc(m.title)}</div>
          <small class="faint">${m.due ? `due ${esc(VT.fmtDate(m.due))} · ${left >= 0 ? plural(left, 'day') + ' left' : plural(-left, 'day') + ' overdue'}` : 'no due date'}${m.state ? ' · ' + esc(m.state) : ''}</small>
          <small class="unk pg-wrap">not measured yet: no lagging measurement is recorded for this milestone, only its due date</small>`;
      } else if (road && road.data) {
        label = `<div class="pg-big unk-big">unknown</div><small class="unk pg-wrap">${esc(track)}'s roadmap declares no milestone</small>`;
      } else if (road && road.error) {
        label = `<div class="pg-big unk-big">unknown</div><small class="unk pg-wrap">milestone from ${esc(track)}'s roadmap: ${esc(road.error)}</small>`;
      } else {
        label = `<div class="pg-sm faint">Reading ${esc(track)}'s roadmap…</div>`;
      }
      plot = frame(ax, H, dueT, `<line class="pg-none" x1="0" x2="${ax.w}" y1="${H / 2}" y2="${H / 2}"/>`
        + (dueT != null ? `<text class="pg-ax due" x="${(ax.X(dueT) - 4).toFixed(1)}" y="14" text-anchor="end">${esc(VT.fmtDate(m && m.due))}</text>` : ''));
    }
    return `<div class="pg-crow lag" data-testid="vt-project-lagging"><div class="pg-lab"><div class="pg-h">North star <span class="faint">· lagging</span></div>${label}</div><div class="pg-pc" data-pgw="plot">${plot}</div></div>`;
  }
  function leadingRow(l, ax, dueT) {
    const H = 40;
    const t = VT.findTrack(l.track);
    const dot = t ? VT.sd(VT.trackDot(t), VT.dotTitle(t)) : VT.sd('idle');
    const name = `<a class="pg-tn" href="#/track/${encodeURIComponent(l.track)}">${dot}<span class="ell">${esc(l.title)}</span></a>`;
    let sub, inner;
    if (l.kpi) {
      const v = kpiValue(l.kpi);
      sub = `<small class="pg-k" title="${esc(l.kpi.note || '')}">${esc(l.kpi.label)} · <b>${v ? esc(v) : 'not measured yet'}</b>${l.kpi.target && l.kpi.target.label && !(lastMeasured(l.kpi) && lastMeasured(l.kpi).of != null) ? ` <span class="faint">· target ${esc(l.kpi.target.label)}</span>` : ''}</small>`;
      inner = line(ax, l.kpi.series, H) || `<line class="pg-none" x1="0" x2="${ax.w}" y1="${H / 2}" y2="${H / 2}"/>`;
    } else {
      const total = (l.worked_daily || []).reduce((a, d) => a + (d.s || 0), 0);
      sub = `<small class="unk" title="${esc(l.unknown || '')}">${esc(l.unknown || 'unknown')}</small><small class="pg-k faint">bars: agent hours/day, not a KPI · ${(total / 3600).toFixed(1)} h in 7 d</small>`;
      inner = bars(ax, l.worked_daily, H);
    }
    return `<div class="pg-crow" data-testid="vt-project-leading-row" data-track-id="${esc(l.track)}" data-state="${esc(l.state ? l.state.word : '')}"><div class="pg-lab">${name}${sub}</div><div class="pg-pc">${frame(ax, H, dueT, inner)}</div></div>`;
  }
  function chart(doc) {
    const ns = doc.north_star || {};
    const decl = ns.declared;
    let road = null, due = null;
    if (decl && decl.kind === 'milestone') {
      road = VT.load(ns.roadmap || `../roadmap/doc?track=${encodeURIComponent(decl.track)}`, 60000);
      const m = road.data && road.data.summary ? road.data.summary.milestone : null;
      if (m && m.due) due = m.due;
    }
    const dom = domain(doc, due);
    const ax = axis(dom, W.plot);
    const dueT = due ? dayStart(due) + DAY / 2 : null;
    const rows = (doc.leading || []).map((l) => leadingRow(l, ax, dueT)).join('');
    return `<div class="pg-card pg-chart" data-testid="vt-project-chart">${lagging(doc, ax, dueT, road)}
      <div class="pg-crow head"><div class="pg-lab"><div class="pg-h">Track KPIs <span class="faint">· leading, each on its own range</span></div></div><div></div></div>
      ${rows || '<div class="pg-crow"><div class="pg-lab faint">No tracks in this project.</div><div></div></div>'}
      <div class="pg-crow axis"><div class="pg-lab"></div><div class="pg-pc">${axisRow(ax, dueT)}</div></div>
      <div class="pg-note">One time axis: week lines, the blue line is today${dueT != null ? ', the solid line the milestone due date' : ''}. A gap in a line is a reading that was not taken, never a zero.</div></div>`;
  }

  // ------------------------------------------------------------------ tracks, sessions, folders
  function trackRows(p) {
    const list = p.tracks.slice().sort((a, b) => (VT.ACTIVE(b) - VT.ACTIVE(a)) || VT.RANK[a.state.word] - VT.RANK[b.state.word]);
    if (!list.length) return '<div class="empty-state">No tracks in this project yet.</div>';
    return `<div class="pg-tbl pg-trk"><div class="pg-th"><div>Track</div><div>State</div><div class="pg-x">North star</div><div class="pg-x">Live</div><div class="pg-x">Last action</div></div>
      ${list.map((t) => { const n = VT.liveCount(t); return `<div class="pg-tr${VT.ACTIVE(t) ? '' : ' muted'}" data-testid="vt-project-track" data-track-id="${esc(t.id)}">
        <div class="nm"><span class="t2"><a class="t" href="#/track/${encodeURIComponent(t.id)}">${esc(t.title)}</a><small title="${esc(t.state.why)}">${esc(t.state.why)}</small></span></div>
        <div>${VT.stateWord(t)}</div><div class="pg-x">${progressCell(t)}</div>
        <div class="pg-x num">${n ? `<span title="${n} live session${n === 1 ? '' : 's'}">${VT.ic('terminal')} ${n}</span>` : '<span class="faint">—</span>'}</div>
        <div class="pg-x"><span class="wk"><span>${t.last_action ? VT.ago(t.last_action.ts) : '<span class="unk">no agent entry in 7 d</span>'}</span><small>${t.worked && t.worked.h24_s ? 'worked ' + VT.dur(t.worked.h24_s) + ' today' : 'no work today'}</small></span></div></div>`; }).join('')}</div>`;
  }
  function sessionRow(s, where) {
    const title = s.title || s.id.slice(0, 8);
    const st = `<span class="stw ${esc(s.state.word)}" title="${esc(s.live ? 'live · ' + (s.status || 'unknown status') : 'ended')}">${esc(VT.WORD[s.state.word] || s.state.word)}</span>`;
    return `<div class="pg-tr pg-ses" data-testid="vt-project-session" data-session-id="${esc(s.id)}">
      <div class="nm">${VT.sd(VT.sessionDot(s), s.live ? 'live · ' + (s.status || 'unknown status') : 'ended')}<span class="chip"><b>${esc(s.account)}</b></span><span class="t2"><span class="t" title="${esc(title + ' · ' + (s.cwd || ''))}">${esc(title)}</span><small title="${esc(s.cwd || '')}">${where} · ${esc(s.branch || 'no branch')}</small></span></div>
      <div>${st}</div><div class="pg-x"><span class="wk"><span>${s.last_action ? VT.ago(s.last_action.ts) : 'unknown'}</span><small>${s.worked && s.worked.h24_s ? 'worked ' + VT.dur(s.worked.h24_s) + ' today' : 'no work today'}</small></span></div>
      <div class="pg-open">${VT.openLinks(s)}</div></div>`;
  }
  function sessions(p) {
    const byLive = (a, b) => (b.live - a.live) || ((b.last_action ? Date.parse(b.last_action.ts) : 0) - (a.last_action ? Date.parse(a.last_action.ts) : 0));
    const onTracks = [];
    for (const t of p.tracks) for (const s of t.sessions) if (s.live) onTracks.push([s, t]);
    onTracks.sort((a, b) => byLive(a[0], b[0]));
    const loose = (p.sessions_unpinned || []).slice().sort(byLive);
    let h = `<div class="pg-tbl pg-sess" data-testid="vt-project-sessions"><div class="pg-th"><div>Session</div><div>State</div><div class="pg-x">Last action</div><div class="pg-x">Open</div></div>`;
    h += `<div class="pg-sh">On this project's tracks <span class="faint">${onTracks.length} live</span></div>`;
    h += onTracks.length ? onTracks.map(([s, t]) => sessionRow(s, `<a href="#/track/${encodeURIComponent(t.id)}">${esc(t.title)}</a>`)).join('') : '<div class="pg-tr pg-none-row faint">No live session on any of its tracks.</div>';
    h += `<div class="pg-sh">In this project's folders, no track <span class="faint">${loose.length}</span></div>`;
    h += loose.length ? loose.map((s) => sessionRow(s, '<span class="faint">no track rule matches</span>')).join('') : '<div class="pg-tr pg-none-row faint">None.</div>';
    return h + '</div>';
  }
  function folders(p) {
    const roots = p.roots || [];
    return `<div class="pg-card pg-folders" data-testid="vt-project-folders">
      ${roots.length ? roots.map((r) => `<div class="pg-frow" data-exists="${r.exists ? 'true' : 'false'}">${VT.ic('folder')}<span class="pg-path">${esc(r.path)}</span>${r.exists ? '' : '<span class="errword">missing on disk</span>'}</div>`).join('') : '<div class="pg-frow unk">no folders listed: unknown</div>'}
      <div class="pg-frow pg-desc"><span class="faint">descriptor</span><span class="pg-path">${esc(p.descriptor || 'unknown')}</span></div>
      <div class="pg-note">A session belongs here when its working directory is under any of these folders; a track rule (branch, cwd or title) then pins it to one track.</div></div>`;
  }

  // ------------------------------------------------------------------ the page
  function rollup(p) {
    const active = p.tracks.filter(VT.ACTIVE);
    const c = (w) => active.filter((t) => t.state.word === w).length;
    const parts = [];
    if (c('needs_you')) parts.push(`<b class="warnword">${c('needs_you')} need${c('needs_you') > 1 ? '' : 's'} you</b>`);
    if (c('error')) parts.push(`<span class="errword">${c('error')} error</span>`);
    if (c('stale')) parts.push(`${c('stale')} stale`);
    return parts.length ? parts.join(' · ') : 'nothing needs you';
  }
  function callouts(p) {
    let h = '';
    for (const t of p.tracks.filter((x) => x.state.word === 'needs_you')) {
      h += `<a class="pg-callout warn" href="#/review?track=${encodeURIComponent(t.id)}" data-testid="vt-project-callout" data-track-id="${esc(t.id)}">${VT.sd('awaiting')}<span class="pg-cb"><b>${esc(t.title)}</b> · <span class="warnword">Needs you</span> · ${esc(t.state.why)} ${VT.ageBadge(VT.needAge(t))}</span><span class="btn small">Review</span></a>`;
    }
    for (const t of p.tracks.filter((x) => x.state.word === 'error')) {
      h += `<a class="pg-callout err" href="#/track/${encodeURIComponent(t.id)}" data-testid="vt-project-callout" data-track-id="${esc(t.id)}">${VT.sd('error')}<span class="pg-cb"><b>${esc(t.title)}</b> · <span class="errword">Error</span> · ${esc(t.state.why)}</span><span class="btn small">Open</span></a>`;
    }
    return h;
  }

  VT.page('project', {
    title: (r) => (VT.findProject(r.id) || {}).name || 'Project',
    render(r) {
      const p0 = VT.findProject(r.id);
      const e = VT.load('project?id=' + encodeURIComponent(r.id), 15000);
      if (!p0 && !e.data) {
        return `<div class="page pg" data-testid="vt-project-page"><div class="crumb"><a href="#/">Home</a> / ${esc(r.id)}</div><h1>${esc(r.id)}</h1>
          ${e.error ? `<div class="banner">No project "${esc(r.id)}": ${esc(e.error)}</div>` : '<p class="sub">Reading the project…</p>'}</div>`;
      }
      // The home doc's copy is the fresher (10 s poll); the project doc adds nothing to it but the chart's inputs.
      const p = Object.assign({}, e.data ? e.data.project : {}, p0 || {});
      const active = p.tracks.filter(VT.ACTIVE).length;
      const nf = (p.roots || []).length;
      const sub = `${plural(nf, 'folder')} · ${active} active track${active === 1 ? '' : 's'} · ${p.sessions_live != null ? plural(p.sessions_live, 'agent') + ' live' : 'agents live unknown'} · ${rollup(p)}`;
      const body = e.data ? chart(e.data)
        : `<div class="pg-card pg-chart" data-testid="vt-project-chart">${e.error ? `<div class="banner">The project document could not be read: ${esc(e.error)}</div>` : '<p class="faint">Reading the north star and the tracks\' KPIs…</p>'}</div>`;
      return `<div class="page pg" data-testid="vt-project-page" data-project-id="${esc(p.id)}">
        <div class="crumb"><a href="#/">Home</a> / <span>${esc(p.name)}</span></div>
        <h1 class="pg-h1"><span class="pico" style="background:${esc(p.color)}">${esc((p.name || '?')[0].toUpperCase())}</span>${esc(p.name)}</h1>
        <p class="sub">${sub}</p>
        ${callouts(p)}${body}
        <h2 class="pg-h2">Tracks <span class="faint">${p.tracks.length}</span></h2>${trackRows(p)}
        <h2 class="pg-h2">Sessions</h2>${sessions(p)}
        <h2 class="pg-h2">Folders</h2>${folders(p)}
        <div class="foot">Derived on the backend from the project's descriptor, Claude Code's transcripts and each track's loop files${e.data ? ` · project document generated ${esc(e.data.generated_at)}` : ''}.</div></div>`;
    },
    after(main) {
      let changed = false;
      const el = main.querySelector('[data-pgw="plot"]');
      if (el) {
        const w = Math.floor(el.clientWidth);
        if (w > 40 && Math.abs(w - W.plot) > 1) { W.plot = w; changed = true; }
      }
      if (changed) requestAnimationFrame(() => VT.render());
    },
  });

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (VT.route && VT.route.name === 'project' && VT.doc) VT.render(); }, 120);
  });
})();
