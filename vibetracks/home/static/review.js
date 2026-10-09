/* Vibe Tracks home · Review (B2) — a PLACEHOLDER pending the review proposals (Oct 9: the Review design is open
   again; five proposals are being built separately). It does the minimum on real data: every open decision the
   loops hold (GET ../needs, needs.py's own triage), grouped by project, in triage order (blocking now -> waiting for
   you, no default -> defaulting without you), each with its age and what happens if you stay silent.
   Answers: no loop has an answer channel this page can write to (needs.py says chat_paste / note_paste), so each
   decision copies as Markdown for you to paste where its loop reads answers, and the page says so. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;
  const GROUPS = [['blocking', 'Blocking now'], ['no_default', 'Waiting for you · no default'], ['waiting', 'Waiting for you'],
    ['defaulting', 'Defaulting without you · optional']];
  const GROUP = Object.fromEntries(GROUPS);
  const RANK = Object.fromEntries(GROUPS.map(([k], i) => [k, i]));
  const CHANNEL = { chat_paste: 'paste into the loop\'s chat session', note_paste: 'paste into the loop\'s note', none: 'no answer channel recorded' };

  function itemAge(item) {
    const c = item.created && item.created.ts, u = item.updated && item.updated.ts;
    if (c) return { s: VT.secondsSince(c), label: 'asked' };
    if (u) return { s: VT.secondsSince(u), label: 'updated' };
    return { s: null, label: 'no recorded time' };
  }
  function markdown(item, doc) {
    const rec = (item.options || []).find((o) => o.recommended);
    const lines = [`**${doc.track_title || doc.track} · ${item.local_id || item.id}: ${item.title}**`, ''];
    if (item.ask && item.ask !== item.title) lines.push(item.ask, '');
    lines.push(`My answer: ${rec ? rec.label + (rec.detail_md ? ' — ' + rec.detail_md : '') : '(write it)'}`);
    return lines.join('\n');
  }
  function itemCard(item, doc, project) {
    const age = itemAge(item);
    const options = item.options || [];
    const rec = options.find((o) => o.recommended);
    const def = item.default || {};
    const blocks = (item.blocks || []).map((b) => b.label || b.id).filter(Boolean);
    const channel = (doc.answer_channel || {}).kind || 'none';
    return `<div class="ritem ${esc(item.group)}" data-testid="vt-review-item" data-item-id="${esc(item.id)}" data-group="${esc(item.group)}" data-project-id="${esc(project ? project.id : '')}">
      <div class="rhead">${VT.sd(item.group === 'defaulting' ? 'idle' : 'awaiting')}<span class="rgroup ${esc(item.group)}">${esc(GROUP[item.group] || item.group)}</span>
        <a class="rtrack" href="#/track/${encodeURIComponent(doc.track)}">${esc(doc.track_title || doc.track)}</a>
        <span class="spacer"></span><span class="rage" title="${esc(age.label)}">${age.s != null ? `${esc(age.label)} ${VT.ageBadge(age.s)}` : '<span class="unk">age unknown</span>'}</span></div>
      <div class="rtitle">${esc(item.title)}</div>
      ${blocks.length ? `<div class="rmeta">Blocks ${esc(blocks.join(', '))}</div>` : ''}
      ${rec ? `<div class="rrec"><b>Recommended:</b> ${esc(rec.label)}${rec.detail_md ? ` <span class="grey">— ${esc(rec.detail_md)}</span>` : ''}</div>` : ''}
      <div class="rdef"><b>If you stay silent:</b> ${esc((def.text_md || 'no default recorded').slice(0, 280))}</div>
      <div class="ractions"><button class="btn small" data-act="copy" data-what="the decision as Markdown (${esc(CHANNEL[channel] || channel)})" data-text="${esc(markdown(item, doc))}">${VT.ic('copy')}Copy as Markdown</button>
        <span class="faint">Nothing is sent from here: ${esc(CHANNEL[channel] || channel)}.</span></div>
    </div>`;
  }

  VT.page('review', {
    title: () => 'Review',
    render(r) {
      const e = VT.load('../needs', 20000);
      const filter = r.query.track || null;
      let h = `<div class="page" data-testid="vt-review"><div class="crumb"><a href="#/">Home</a> / Review${filter ? ` / ${esc((VT.findTrack(filter) || {}).title || filter)}` : ''}</div>
        <h1>Review</h1><div class="placeholder" data-testid="vt-review-placeholder">Placeholder pending the review proposals: the Review design is open again. This is the minimum on real data.</div>`;
      if (!e.data) return h + (e.error ? `<div class="banner">The needs could not be read: ${esc(e.error)}</div>` : '<p class="sub">Reading the loops\' triage files…</p>') + '</div>';
      const docs = (e.data.tracks || []).filter((d) => !filter || d.track === filter);
      const items = [];
      for (const d of docs) for (const it of d.items || []) if (RANK[it.group] != null) items.push({ it, d });
      const wants = items.filter((x) => x.it.group !== 'defaulting');
      const blocking = items.filter((x) => x.it.group === 'blocking').length;
      h += `<p class="sub">${wants.length} open decision${wants.length === 1 ? '' : 's'} want you · ${blocking} blocking now · ${items.length - wants.length} defaulting without you${filter ? ` · filtered to one track <a href="#/review">show all</a>` : ''}</p>`;
      const byProject = new Map();
      for (const x of items) {
        const t = VT.findTrack(x.d.track), p = t ? VT.projectOf(t) : null;
        const key = p ? p.id : '';
        if (!byProject.has(key)) byProject.set(key, { p, list: [] });
        byProject.get(key).list.push(x);
      }
      if (!items.length) h += '<div class="empty-state">Nothing waits on you.</div>';
      const order = [...byProject.values()].sort((a, b) => Math.min(...a.list.map((x) => RANK[x.it.group])) - Math.min(...b.list.map((x) => RANK[x.it.group])));
      for (const { p, list } of order) {
        list.sort((a, b) => RANK[a.it.group] - RANK[b.it.group] || (itemAge(b.it).s || 0) - (itemAge(a.it).s || 0));
        const nf = p ? (p.roots || []).length : 0;
        h += `<section class="rproject" data-testid="vt-review-project" data-project-id="${esc(p ? p.id : '')}"><h2>${p ? `<span class="pico sm" style="background:${esc(p.color)}">${esc(p.name[0].toUpperCase())}</span><a href="#/project/${encodeURIComponent(p.id)}">${esc(p.name)}</a><span class="faint">· ${nf} folder${nf === 1 ? '' : 's'}</span>` : 'No project'}<span class="faint">${list.length}</span></h2>`;
        h += list.map((x) => itemCard(x.it, x.d, p)).join('') + '</section>';
      }
      const silent = (e.data.tracks || []).filter((d) => !(d.items || []).length && (!filter || d.track === filter));
      if (silent.length) h += `<div class="foot">No structured triage file (counts unknown, not zero): ${esc(silent.map((d) => d.track).join(', '))}.</div>`;
      return h + '</div>';
    },
  });
})();
