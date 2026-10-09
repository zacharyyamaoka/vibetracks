/* Vibe Tracks home · Track page (B2, 2026-10-09): GET track?id= (vibetracks-home-track/1) beside the home doc, the
   roadmap projector's document (../roadmap/doc?track=, 404 when the track has none) and one audit file at a time
   (audit?track=&name=, text/plain). Four tabs: Overview (every soft KPI side by side, hard gates, the rung ladder),
   Activity (a read-only timeline), Sessions (every session the join matched, with its Open links) and Auditor (each
   audit round, its file one click away). A reading the backend could not take says "unknown" or the document's own
   reason, never 0 and never "fine". K toggles KPI Cards / Rows. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;
  const S = VT.S;
  const TABS = ['overview', 'activity', 'sessions', 'auditor'];
  const W = { kcard: 200 };                 // the KPI card sparkline width, measured after each render
  const openAudits = new Set();             // audit rounds expanded on this visit (by file name)

  const fmtNum = (v) => (typeof v === 'number' ? String(+v.toPrecision(6)) : String(v));
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  // The audit body is text/plain, which VT.load (JSON) cannot read: the same cache shape, one level down.
  const texts = {};
  function loadText(url) {
    const e = texts[url] || (texts[url] = { data: null, error: null, inflight: false, at: 0 });
    if (!e.inflight && !e.at) {
      e.inflight = true;
      fetch(url, { cache: 'no-store' })
        .then(async (r) => { const body = await r.text(); if (!r.ok) throw new Error(body || `HTTP ${r.status}`); e.data = body; e.error = null; })
        .catch((err) => { e.error = err && err.message ? err.message : String(err); })
        .finally(() => { e.inflight = false; e.at = Date.now(); VT.render(); });
    }
    return e;
  }

  // ------------------------------------------------------------------ KPI words
  function lastMeasured(k) {
    const pts = k.series || [];
    for (let i = pts.length - 1; i >= 0; i--) if (pts[i].measured !== false && pts[i].value != null) return pts[i];
    return null;
  }
  function valueHtml(k) {
    const pt = lastMeasured(k);
    if (!pt) return '<span class="unk-big">not measured yet</span>';
    const unit = pt.of != null ? `<span class="pg-of">of ${esc(fmtNum(pt.of))}</span>` : k.unit ? `<span class="pg-of">${esc(k.unit)}</span>` : '';
    return `<b class="num">${esc(fmtNum(pt.value))}</b>${unit}`;
  }
  const targetText = (k) => (k.target && k.target.label ? k.target.label : k.target && k.target.value != null ? `target ${fmtNum(k.target.value)}` : 'no target');
  const targetVal = (k) => (k.target && typeof k.target.value === 'number' ? k.target.value : null);
  function kTitle(k) {
    const pt = lastMeasured(k);
    return [k.label, pt ? `last measured ${pt.iteration || ''}${pt.date ? ' · ' + VT.fmtDate(pt.date) : ''}` : 'not measured yet',
      k.baseline ? `baseline ${k.baseline.label}: ${fmtNum(k.baseline.value)}` : null, k.note].filter(Boolean).join('\n');
  }
  const spark = (k, w, h) => VT.sparkline((k.series || []).map((p, i) => ({ x: i, y: p.measured === false ? null : p.value })), { w, h, target: targetVal(k) });
  const nsTag = '<span class="pg-tag" title="the track\'s north-star KPI">north star</span>';
  const tone = (k) => (k.status && k.status.tone === 'warn' ? ' warn' : '');

  function kpiCards(soft) {
    return `<div class="pg-kcards">${soft.map((k) => `<div class="pg-kcard${k.north_star ? ' ns' : ''}" data-testid="vt-kpi-card" data-kpi-id="${esc(k.id)}" title="${esc(kTitle(k))}">
      <div class="pg-kl"><span class="ell">${esc(k.label)}</span>${k.north_star ? nsTag : ''}</div>
      <div class="pg-kv">${valueHtml(k)}</div>
      <div class="pg-kt"><span class="faint ell">${esc(targetText(k))}</span></div>
      <div class="pg-ks" data-pgw="kcard">${spark(k, W.kcard, 40)}</div>
      <div class="pg-kst${tone(k)}">${esc(k.status ? k.status.word : 'status unknown')}</div></div>`).join('')}</div>`;
  }
  function kpiRows(soft) {
    return `<div class="pg-tbl pg-krows"><div class="pg-th"><div>Soft KPI</div><div>Now</div><div class="pg-x">Target</div><div class="pg-x">Trend</div><div class="pg-x">Status</div></div>
      ${soft.map((k) => `<div class="pg-tr${k.north_star ? ' ns' : ''}" data-testid="vt-kpi-row" data-kpi-id="${esc(k.id)}" title="${esc(kTitle(k))}">
        <div class="nm"><span class="t">${esc(k.label)}</span>${k.north_star ? nsTag : ''}</div><div class="pg-kv sm">${valueHtml(k)}</div>
        <div class="pg-x faint pg-cut">${esc(targetText(k))}</div><div class="pg-x">${spark(k, 112, 22)}</div><div class="pg-x pg-kst pg-cut${tone(k)}">${esc(k.status ? k.status.word : 'status unknown')}</div></div>`).join('')}</div>`;
  }
  function gates(list) {
    if (!list.length) return '<p class="faint pg-p">No hard gates reported.</p>';
    return `<div class="pg-card pg-gates">${list.map((g) => {
      const v = g.gate || {};
      const pass = v.pass === true ? 'true' : v.pass === false ? 'false' : 'unknown';
      const mark = pass === 'true' ? '✓ pass' : pass === 'false' ? '✗ fail' : '○ unknown';
      const now = v.value != null ? `${fmtNum(v.value)}${v.of != null ? ' of ' + fmtNum(v.of) : g.unit ? ' ' + g.unit : ''}` : null;
      return `<div class="pg-gate" data-testid="vt-gate" data-kpi-id="${esc(g.id)}" data-pass="${pass}" title="${esc(kTitle(g))}">
        <span class="pg-gp p-${pass}">${mark}</span>
        <span class="pg-gl"><span class="t">${esc(g.label)}${g.north_star ? ' ' + nsTag : ''}</span><small class="faint">${esc(targetText(g))}</small></span>
        <span class="pg-gw"><span class="${pass === 'false' ? 'errword' : pass === 'unknown' ? 'unk' : ''}">${esc(v.why || 'unknown')}</span><small class="faint">${now ? 'now ' + esc(now) + (v.iteration ? ' · ' + esc(v.iteration) : '') : 'no measured value'}</small></span></div>`;
    }).join('')}</div>`;
  }

  // ------------------------------------------------------------------ roadmap: the rung ladder
  const RUNG_WORD = { green: 'green: proven', done: 'done: proven', claimed: 'claimed, not proven', partial: 'partial', missing: 'missing', stale: 'stale' };
  function roadmap(t, d) {
    const href = (d.roadmap && d.roadmap.href) || `../roadmap/doc?track=${encodeURIComponent(t.id)}`;
    const e = VT.load(href, 60000);
    const k = d.kpis || {};
    if (!e.data) {
      if (!e.error) return '<p class="faint pg-p">Reading the roadmap…</p>';
      const rung = k.rung ? `<div class="pg-kvl"><span class="faint">Current</span><span>${esc(k.rung.current || 'unknown')}</span><span class="faint">Next</span><span>${esc(k.rung.next || 'unknown')}</span><span class="faint">Source</span><span class="faint">${esc(k.rung.source || 'unknown')}</span></div>` : '';
      return `<div class="pg-card"><div class="pg-p">${e.status === 404 ? 'No roadmap projector for this track' : 'The roadmap could not be read'} <span class="faint">(${esc(e.error)})</span>.${k.rung ? ' The loop\'s own rung line:' : ''}</div>${rung}</div>`;
    }
    const doc = e.data;
    const axes = (doc.axes || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
    const where = {};
    (doc.where || []).forEach((w) => { where[w.axis] = w; });
    const sum = doc.summary || {};
    const frontier = new Set(sum.frontier || []);
    const rows = axes.map((a) => {
      const rungs = (doc.rungs || []).filter((r) => r.axis === a.id).sort((x, y) => (x.order || 0) - (y.order || 0));
      const w = where[a.id] || {};
      const sq = rungs.map((r) => {
        const front = r.frontier || frontier.has(r.id);
        return `<i class="pg-rung s-${esc(r.status)}${front ? ' front' : ''}" data-testid="vt-rung" data-rung-id="${esc(r.id)}" data-status="${esc(r.status)}" title="${esc(`${r.id} · ${r.title} · ${RUNG_WORD[r.status] || r.status}${front ? ' · frontier' : ''}\n${r.status_reason || ''}`)}"></i>`;
      }).join('');
      const at = `${w.here ? `proven <b>${esc(w.here)}</b>` : 'proven <span class="faint">none</span>'}${w.here_claimed && w.here_claimed !== w.here ? ` · claimed ${esc(w.here_claimed)}` : ''}${w.next ? ` · next <b>${esc(w.next)}</b>` : ''}`;
      return `<div class="pg-axis"><div class="pg-an" title="${esc(a.id)}">${esc(a.title || a.id)}</div><div class="pg-rungs">${sq || '<span class="faint">no rungs</span>'}</div><div class="pg-aw">${at}</div></div>`;
    }).join('');
    const c = (doc.counts && doc.counts.by_status) || {};
    const legend = ['green', 'done', 'claimed', 'partial', 'missing', 'stale'].map((s) => `<span><i class="pg-rung s-${s}"></i>${RUNG_WORD[s]} ${c[s] != null ? c[s] : 0}</span>`).join('') + '<span><i class="pg-rung s-missing front"></i>frontier</span>';
    const m = sum.milestone;
    const meta = [
      sum.frontier && sum.frontier.length ? `<span class="faint">Frontier</span><span>${esc(sum.frontier.join(', '))}</span>` : '',
      `<span class="faint">Milestone</span><span>${m ? `<b>${esc(m.title)}</b>${m.due ? ' · due ' + esc(VT.fmtDate(m.due)) : ''}${m.state ? ' · ' + esc(m.state) : ''}` : '<span class="faint">none declared</span>'}</span>`,
      sum.wave != null || sum.phase ? `<span class="faint">Phase</span><span>${sum.wave != null ? 'wave ' + esc(sum.wave) + ' · ' : ''}${esc(sum.phase || '')}</span>` : '',
      (sum.blockers || []).length ? `<span class="faint">Blockers</span><span class="warnword">${esc(sum.blockers.join(' · '))}</span>` : '',
    ].join('');
    const warn = (doc.warnings || []).length ? `<div class="pg-note">${doc.warnings.map(esc).join(' · ')}</div>` : '';
    return `<div class="pg-card pg-road"><div class="pg-ladder">${rows}</div><div class="pg-legend">${legend}</div><div class="pg-kvl">${meta}</div>${warn}
      <div class="pg-note">${esc(doc.title || '')} · as of ${esc((doc.as_of && doc.as_of.branch) || 'unknown branch')} ${esc(((doc.as_of && doc.as_of.head) || '').slice(0, 8))} · generated ${esc(VT.ago(doc.generated_at))}</div></div>`;
  }

  function overview(t, d) {
    const k = d.kpis || {};
    const soft = (k.soft || []).slice().sort((a, b) => (b.north_star ? 1 : 0) - (a.north_star ? 1 : 0));
    const gl = (k.gates || []).slice().sort((a, b) => (b.north_star ? 1 : 0) - (a.north_star ? 1 : 0));
    const nsGate = gl.find((g) => g.north_star);
    const toggle = `<span class="seg" data-testid="vt-kpi-toggle" title="Cards or Rows (K)"><button class="${S.kpiView === 'cards' ? 'on' : ''}" data-act="kpiview" data-id="cards">Cards</button><button class="${S.kpiView === 'rows' ? 'on' : ''}" data-act="kpiview" data-id="rows">Rows</button></span>`;
    let softHtml;
    if (soft.length) softHtml = S.kpiView === 'rows' ? kpiRows(soft) : kpiCards(soft);
    else softHtml = `<p class="pg-p"><span class="unk pg-wrap">unknown: ${esc(k.unknown || (gl.length ? 'the loop reports only hard gates' : 'the loop reports no KPI'))}</span></p>`;
    const summary = k.summary ? `<div class="pg-summary"><span class="faint">Loop says</span> ${esc(k.summary)}</div>` : '';
    return `${summary}
      <h2 class="pg-h2 bar2">Soft KPIs <span class="faint pg-hs">· every dimension side by side, so a trade-off shows</span><span class="spacer"></span>${soft.length ? toggle : ''}</h2>
      ${nsGate ? `<p class="pg-p faint">The north star, ${esc(nsGate.label)}, is a hard gate below.</p>` : ''}${softHtml}
      <h2 class="pg-h2">Hard gates <span class="faint pg-hs">· pass / fail, never averaged in</span></h2>${gates(gl)}
      <h2 class="pg-h2">Roadmap <span class="faint pg-hs">· rung ladder</span></h2>${roadmap(t, d)}`;
  }

  // ------------------------------------------------------------------ activity
  const KIND = { action: 'agent', session: 'session', error: 'error', iteration: 'iteration', loop: 'loop', need: 'needs you', audit: 'audit' };
  const DAYMAX = 86400;
  function worked(daily) {
    const max = DAYMAX;
    return `<div class="pg-days" title="hours of agent work per day (gaps up to 15 min between agent entries, overlap counted once); not a KPI">${(daily || []).map((x) => {
      const dt = new Date(x.date + 'T12:00:00');
      return `<div class="pg-day"><div class="pg-dbar"><b style="height:${Math.min(100, (x.s / max) * 100).toFixed(1)}%"></b></div><span class="num">${x.s ? (x.s / 3600).toFixed(1) + ' h' : '—'}</span><small>${esc(dt.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }))}</small></div>`;
    }).join('')}</div>`;
  }
  function activity(t, d) {
    const evs = (d.timeline || []).slice().sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
    let h = `<p class="pg-p faint">Read-only: derived from Claude Code's transcripts, the loop's files, the needs documents and the audit files. Nothing here is editable; hover an event for its source file.</p>
      <h2 class="pg-h2">Agent hours per day <span class="faint pg-hs">· last 7 days, not a KPI</span></h2>${worked(d.worked_daily)}
      <h2 class="pg-h2">Timeline <span class="faint pg-hs">· newest first · ${evs.length} events</span></h2>`;
    if (!evs.length) return h + '<div class="empty-state">No events recorded for this track.</div>';
    let day = null;
    h += '<div class="pg-tl">';
    for (const ev of evs) {
      const dt = new Date(ev.ts);
      const key = isNaN(dt) ? 'unknown date' : dt.toDateString();
      if (key !== day) {
        day = key;
        h += `<div class="pg-tld">${isNaN(dt) ? 'unknown date' : esc(dt.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' }))}</div>`;
      }
      h += `<div class="pg-ev k-${esc(ev.kind)}" data-testid="vt-timeline-event" data-kind="${esc(ev.kind)}" title="${esc(ev.source || 'no source recorded')}">
        <span class="pg-et num">${ev.date_only ? '<span class="faint" title="the source records a date only">day</span>' : esc(VT.fmtTime(ev.ts))}</span>
        <span class="pg-ek"><i></i>${esc(KIND[ev.kind] || ev.kind)}</span>
        <span class="pg-ex"><span class="pg-etl">${esc(ev.title)}</span>${ev.detail ? `<small>${esc(ev.detail)}</small>` : ''}</span></div>`;
    }
    return h + '</div>';
  }

  // ------------------------------------------------------------------ sessions
  function sessionsTab(t) {
    const list = t.sessions.slice().sort((a, b) => (b.live - a.live) || ((b.last_action ? Date.parse(b.last_action.ts) : 0) - (a.last_action ? Date.parse(a.last_action.ts) : 0)));
    if (!list.length) return '<div class="empty-state">No session matched this track in the last 7 days.</div>';
    return `<div class="pg-tbl pg-tses"><div class="pg-th"><div>Session</div><div class="pg-x">Joined by</div><div>State</div><div class="pg-x">Worked · last action</div><div class="pg-x">Open</div></div>
      ${list.map((s) => {
        const title = s.title || s.id.slice(0, 8);
        const join = s.join && s.join.by ? `<span>${esc(s.join.by)}</span><small title="${esc(s.join.value || '')}">${esc(s.join.value || '')}</small>` : '<span class="unk">no rule matched</span>';
        const status = s.live ? `live · ${s.status || 'unknown status'}${s.waiting_for ? ' (' + s.waiting_for + ')' : ''}` : 'ended (no live process)';
        const w = s.worked || {};
        return `<div class="pg-tr${s.live ? '' : ' ended'}" data-testid="vt-track-session" data-session-id="${esc(s.id)}" data-live="${s.live ? 'true' : 'false'}">
          <div class="nm">${VT.sd(VT.sessionDot(s), status)}<span class="chip"><b>${esc(s.account)}</b></span><span class="t2"><span class="t" title="${esc(title + ' · ' + (s.cwd || ''))}">${esc(title)}</span><small title="${esc(s.cwd || '')}">${esc(s.branch || 'no branch')}${s.subagent_files ? ' · ' + plural(s.subagent_files, 'subagent file') : ''}</small></span></div>
          <div class="pg-x wk">${join}</div>
          <div><span class="stw ${esc(s.state.word)}" title="${esc(status)}">${esc(VT.WORD[s.state.word] || s.state.word)}</span>${s.live || s.state.word === 'ended' ? '' : '<small class="faint pg-blk">ended</small>'}</div>
          <div class="pg-x"><span class="wk" title="${esc(`worked ${VT.dur(w.h24_s)} in 24 h, ${VT.dur(w.d7_s)} in 7 d`)}"><span>${w.h24_s ? 'worked ' + VT.dur(w.h24_s) : 'no work today'}</span><small>${s.last_action ? 'last action ' + VT.ago(s.last_action.ts) : 'no agent entry'}</small></span></div>
          <div class="pg-open">${VT.openLinks(s)}</div></div>`;
      }).join('')}</div>`;
  }

  // ------------------------------------------------------------------ auditor
  function auditorTab(t, d) {
    const a = d.audits || {};
    const rounds = (a.rounds || []).slice().sort((x, y) => Date.parse(y.ts) - Date.parse(x.ts));
    if (!rounds.length) return `<p class="pg-p"><span class="unk pg-wrap">${esc(a.unknown || 'no audit rounds')}</span></p>${(a.globs || []).length ? `<div class="pg-note">globs: ${esc(a.globs.join(' · '))}</div>` : ''}`;
    const tones = { green: 0, yellow: 0, red: 0, none: 0 };
    rounds.forEach((r) => { tones[r.tone in tones ? r.tone : 'none']++; });
    const took = rounds.map((r) => r.took_s).filter((s) => s != null).sort((x, y) => x - y);
    const median = took.length ? took[Math.floor(took.length / 2)] : null;
    const last = rounds[0];
    const stats = `<div class="pg-stats">
      <span><small>Last verdict</small><b class="v-${esc(last.tone)}">${esc(last.verdict || 'no verdict')}</b></span>
      <span><small>Rounds</small><b class="num">${rounds.length}</b></span>
      <span><small>By verdict</small><b class="pg-tones">${tones.green ? `<span class="v-green">${tones.green} pass</span>` : ''}${tones.yellow ? `<span class="v-yellow">${tones.yellow} with fixes</span>` : ''}${tones.red ? `<span class="v-red">${tones.red} fail</span>` : ''}${tones.none ? `<span class="v-none">${tones.none} no verdict</span>` : ''}</b></span>
      <span><small>Median time to verdict</small><b class="num">${median != null ? VT.dur(median) : 'unknown'}</b><small>${took.length} of ${rounds.length} timed</small></span></div>`;
    const rows = rounds.map((r) => {
      const open = openAudits.has(r.name);
      const url = `audit?track=${encodeURIComponent(t.id)}&name=${encodeURIComponent(r.name)}`;
      let body = '';
      if (open) {
        const e = loadText(url);
        body = `<pre class="pg-pre" data-testid="vt-audit-body">${e.data != null ? esc(e.data) : e.error ? 'Could not read the file: ' + esc(e.error) : 'Reading…'}</pre>`;
      }
      return `<div class="pg-au${open ? ' open' : ''}" data-testid="vt-audit-round" data-name="${esc(r.name)}">
        <button class="pg-auh" data-act="audit" data-id="${esc(r.name)}" aria-expanded="${open}" title="${esc(r.path)}">
          <span class="chev ${open ? '' : 'closed'}">${VT.ic('chev')}</span>
          <span class="pg-verdict v-${esc(r.tone)}">${esc(r.verdict || 'no verdict')}</span>
          <span class="pg-aun"><span class="t">${esc(r.name)}</span><small>${esc(r.headline || '')}</small></span>
          <span class="pg-x num faint">${esc(VT.fmtDate(r.ts))} ${esc(VT.fmtTime(r.ts))}</span>
          <span class="pg-x pg-cut">${r.model ? esc(r.model) + (r.effort ? ' · ' + esc(r.effort) : '') : '<span class="unk">model unknown</span>'}</span>
          <span class="pg-x num">${r.took_s != null ? esc(VT.dur(r.took_s)) : '<span class="unk">unknown</span>'}</span></button>${body}</div>`;
    }).join('');
    return `${stats}<div class="pg-tbl pg-aus"><div class="pg-th"><div></div><div>Verdict</div><div>Round</div><div class="pg-x">Written</div><div class="pg-x">Model · effort</div><div class="pg-x">Took</div></div>${rows}</div>
      <div class="pg-note">Audit files matched by ${esc((a.globs || []).join(' · ') || 'unknown globs')}; verdict read from each file's first lines, model and effort from the .log beside it, time to verdict from its prompt file's mtime.</div>`;
  }

  // ------------------------------------------------------------------ the page
  function header(t, d, tab) {
    const p = VT.projectOf(t) || (d && d.project) || {};
    const mode = t.mode ? `<span class="pg-mode m-${esc(t.mode.word)}" data-testid="vt-track-mode" title="${esc(t.mode.why || '')}">${esc(t.mode.word === 'optimize' ? 'Optimize' : t.mode.word === 'discover' ? 'Discover' : t.mode.word)}</span>`
      : '<span class="pg-mode" data-testid="vt-track-mode" title="the backend reported no mode">mode unknown</span>';
    const clank = t.links && t.links.track ? `<a class="openag pg-in" href="${esc(t.links.track)}" target="_blank" rel="noopener" title="the track's deep-dive dashboard">${VT.ic('open')}Open in Clank</a>` : '';
    const sub = [VT.stateWord(t), esc(t.state.why), VT.health(t.health.color), t.last_action ? `last action ${esc(VT.ago(t.last_action.ts))}` : '<span class="unk pg-in">no agent entry in 7 d</span>'].join(' <span class="faint">·</span> ') + (clank ? ' <span class="faint">·</span> ' + clank : '');
    const n = t.needs_you || {};
    const callout = t.state.word === 'needs_you' ? `<a class="pg-callout warn" href="#/review?track=${encodeURIComponent(t.id)}" data-testid="vt-track-needs">${VT.sd('awaiting')}<span class="pg-cb"><b class="warnword">Needs you</b> · ${[
      n.blocking ? `<b>${n.blocking} blocking</b>` : '', n.open ? `${n.open} open` : '', (n.open_questions || []).length ? plural(n.open_questions.length, 'open question') : '',
      n.waiting_sessions ? `${plural(n.waiting_sessions, 'session')} waiting` : ''].filter(Boolean).join(' · ') || esc(t.state.why)} ${VT.ageBadge(VT.needAge(t))}${n.unknown_ages ? ` <small class="faint">${n.unknown_ages} with no recorded ask time</small>` : ''}</span><span class="btn small">Open Review</span></a>` : '';
    const live = VT.liveCount(t);
    const rounds = d && d.audits ? (d.audits.rounds || []).length : null;
    const label = { overview: 'Overview', activity: 'Activity', sessions: `Sessions <span class="faint">${live} live</span>`, auditor: `Auditor <span class="faint">${rounds == null ? '' : plural(rounds, 'round')}</span>` };
    const tabs = `<div class="bar pg-tabs" role="tablist">${TABS.map((k) => `<button class="pill ${tab === k ? 'on' : ''}" role="tab" aria-selected="${tab === k}" data-act="pgtab" data-id="${k}" data-testid="vt-track-tab-${k}">${label[k]}</button>`).join('')}</div>`;
    return `<div class="crumb"><a href="#/">Home</a> / ${p.id ? `<a href="#/project/${encodeURIComponent(p.id)}">${esc(p.name)}</a>` : '<span class="faint">no project</span>'} / <span>${esc(t.title)}</span></div>
      <div class="pg-titlerow"><h1>${esc(t.title)}</h1>${mode}</div>
      <p class="sub pg-tsub">${sub}</p>${t.purpose ? `<p class="pg-purpose">${esc(t.purpose)}</p>` : ''}${callout}${tabs}`;
  }
  const tabOf = (r) => (TABS.includes(r.query.tab) ? r.query.tab : TABS.includes(S.trackTab) ? S.trackTab : 'overview');

  VT.page('track', {
    title: (r) => (VT.findTrack(r.id) || {}).title || 'Track',
    enter(r) {
      if (r.id) VT.markSeen(r.id);
      if (TABS.includes(r.query.tab)) { S.trackTab = r.query.tab; VT.save(); }
    },
    render(r) {
      const t0 = VT.findTrack(r.id);
      const e = VT.load('track?id=' + encodeURIComponent(r.id), 15000);
      const d = e.data;
      if (!t0 && !d) {
        return `<div class="page pg" data-testid="vt-track-page"><div class="crumb"><a href="#/">Home</a> / ${esc(r.id)}</div><h1>${esc(r.id)}</h1>
          ${e.error ? `<div class="banner">No track "${esc(r.id)}": ${esc(e.error)}</div>` : '<p class="sub">Reading the track…</p>'}</div>`;
      }
      // The home doc's copy is the fresher (10 s poll); the track doc's copy fills anything it lacks.
      const t = Object.assign({}, d ? d.track : {}, t0 || {});
      const tab = tabOf(r);
      let body;
      if (!d) body = e.error ? `<div class="banner">The track document could not be read: ${esc(e.error)}</div>` : '<p class="faint pg-p">Reading KPIs, activity and audits…</p>';
      else if (tab === 'activity') body = activity(t, d);
      else if (tab === 'sessions') body = sessionsTab(t);
      else if (tab === 'auditor') body = auditorTab(t, d);
      else body = overview(t, d);
      return `<div class="page pg" data-testid="vt-track-page" data-track-id="${esc(t.id)}" data-tab="${tab}">${header(t, d, tab)}<div class="pg-body">${body}</div>
        <div class="foot">Derived on the backend from the track note, its loop's files and Claude Code's transcripts${d ? ` · track document generated ${esc(d.generated_at)}` : ''}${t.provenance && t.provenance.note ? ` · note ${esc(t.provenance.note)}` : ''}.</div></div>`;
    },
    after(main) {
      const el = main.querySelector('[data-pgw="kcard"]');
      if (el) {
        const w = Math.floor(el.clientWidth);
        if (w > 40 && Math.abs(w - W.kcard) > 1) { W.kcard = w; requestAnimationFrame(() => VT.render()); }
      }
    },
    key(ev) {
      if (ev.key === 'k' || ev.key === 'K') { S.kpiView = S.kpiView === 'rows' ? 'cards' : 'rows'; return true; }
      return false;
    },
  });

  Object.assign(VT.actions, {
    kpiview(el) { S.kpiView = el.dataset.id; },
    pgtab(el) {
      // WHY replaceState: switching a tab is not a navigation, so it neither scrolls to the top nor fills Back.
      const tab = el.dataset.id, r = VT.route;
      S.trackTab = tab;
      r.query.tab = tab;
      try { history.replaceState(null, '', `#/track/${encodeURIComponent(r.id)}?tab=${tab}`); } catch (e) { /* file:// */ }
    },
    audit(el) { const n = el.dataset.id; if (openAudits.has(n)) openAudits.delete(n); else openAudits.add(n); },
  });

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (VT.route && VT.route.name === 'track' && VT.doc) VT.render(); }, 120);
  });
})();
