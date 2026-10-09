/* Vibe Tracks home · sidebar (B2): always on, in Claude Code's visual language (Zach, Oct 9: "I don't want to
   relearn a new sidebar"): Claude's row height, type, hover and selected fills, muted group headers with the caret
   on hover, the same status dots (amber waits on you, grey blinking works, blue is new since you looked, a hollow
   ring is idle, a warning glyph is an error) and the account button bottom-left.
   NOT Claude's grouping key: Claude groups chats by the repo folder they started in; this groups TRACKS by project,
   a project being a name plus 1..N folders (the Codex model, Zach Oct 6), so each header says how many folders.
   Collapse a project by clicking its header; the arrow beside it opens the project page. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;

  function row(o) {
    const cls = ['srow', o.cls || '', o.sel ? 'sel' : ''].join(' ').trim();
    const attrs = `class="${cls}"${o.testid ? ` data-testid="${o.testid}"` : ''}${o.extra || ''}${o.title ? ` title="${esc(o.title)}"` : ''}`;
    const inner = `${o.lead}<span class="t">${o.text}</span>${o.meta ? `<span class="meta">${o.meta}</span>` : ''}`;
    return o.href ? `<a ${attrs} href="${esc(o.href)}">${inner}</a>` : `<button ${attrs}${o.act ? ` data-act="${o.act}"` : ''}${o.id ? ` data-id="${esc(o.id)}"` : ''}>${inner}</button>`;
  }
  const lead = (k) => `<span class="sd lead">${VT.ic(k)}</span>`;

  function project(p, r) {
    const closed = !!VT.S.side[p.id];
    const roots = p.roots || [];
    const nf = roots.length;
    const folders = nf ? `${nf} folder${nf === 1 ? '' : 's'}` : 'no folders';
    const live = p.sessions_live || 0;
    const head = `<div class="sgh-row"><button class="sgh" data-act="sidefold" data-id="${esc(p.id)}" aria-expanded="${closed ? 'false' : 'true'}" data-testid="vt-side-project" data-project-id="${esc(p.id)}" title="${esc(p.name + ' · ' + (roots.map((x) => x.path).join(', ') || 'no descriptor') + ' · click to ' + (closed ? 'expand' : 'collapse'))}">`
      + `<span class="nm">${esc(p.name)}</span><span class="caret ${closed ? '' : 'open'}">${VT.ic('caret')}</span><span class="fc" data-testid="vt-side-folders">${folders}</span></button>`
      + `<a class="sgh-go${r.name === 'project' && r.id === p.id ? ' sel' : ''}" href="#/project/${encodeURIComponent(p.id)}" title="Open the ${esc(p.name)} project page" aria-label="Open project ${esc(p.name)}">${VT.ic('open')}</a></div>`;
    if (closed) return `<div class="sgroup closed" data-project="${esc(p.id)}">${head}</div>`;
    let h = '';
    for (const t of p.tracks) {
      if (!VT.ACTIVE(t)) continue;
      const n = VT.liveCount(t);
      const age = t.state.word === 'needs_you' ? VT.ageBadge(VT.needAge(t)) : '';
      h += row({ href: `#/track/${encodeURIComponent(t.id)}`, sel: r.name === 'track' && r.id === t.id, testid: 'vt-side-track',
        extra: ` data-track-id="${esc(t.id)}" data-dot="${VT.trackDot(t)}"`, title: VT.dotTitle(t) + (n ? ` · ${n} live session${n === 1 ? '' : 's'}` : ''),
        lead: VT.sd(VT.trackDot(t)), text: esc(t.title), meta: `${age}${n ? `<span class="n" title="${n} live session${n === 1 ? '' : 's'}">${n}</span>` : ''}` });
    }
    const loose = (p.sessions_unpinned || []).length;
    if (loose) {
      const waiting = p.sessions_unpinned.filter((s) => s.state.word === 'needs_you').length;
      h += row({ href: `#/project/${encodeURIComponent(p.id)}`, cls: 'loose', testid: 'vt-side-unpinned',
        title: `Live sessions in ${p.name}'s folders that no track's rule matches (shown under every project that lists the folder)`,
        lead: VT.sd(waiting ? 'awaiting' : 'idle'), text: `${loose} session${loose === 1 ? '' : 's'} on no track`, meta: `<span class="n">${loose}</span>` });
    }
    if (!h) h = `<div class="srow empty"><span class="sd"></span><span class="t">No active tracks · ${live} live</span></div>`;
    return `<div class="sgroup" data-project="${esc(p.id)}">${head}${h}</div>`;
  }

  VT.page('sidebar', {
    render(r) {
      const d = VT.doc;
      let h = `<aside class="side" data-testid="vt-home-sidebar" aria-label="Navigation"><nav class="side-top">`;
      h += row({ href: '#/', sel: r.name === 'home', testid: 'vt-side-home', lead: lead('home'), text: 'Home' });
      if (d) {
        const rv = d.review;
        const meta = rv.open ? `${VT.ageBadge(rv.oldest_age_s != null ? rv.oldest_age_s + (Date.now() - Date.parse(d.generated_at)) / 1000 : null, 'the oldest open question has waited this long')}<span class="count" data-testid="vt-side-review-count">${rv.open}</span>` : '';
        h += row({ href: '#/review', sel: r.name === 'review', testid: 'vt-side-review', lead: lead('review'), text: 'Review', meta,
          title: rv.open ? `${rv.open} open decisions · ${rv.blocking} blocking now` : 'No loop triage file wants an answer' });
      }
      h += row({ act: 'pop', id: 'newproject', testid: 'vt-side-newproject', lead: lead('plus'), text: 'New project' });
      h += '</nav><div class="side-list">';
      if (d) {
        for (const p of d.projects) h += project(p, r);
        const nowhere = d.other_sessions.filter((s) => !(s.projects || []).length);
        if (nowhere.length) {
          const waiting = nowhere.filter((s) => s.state.word === 'needs_you').length;
          h += `<div class="sgroup"><div class="sgh-row"><span class="sgh static"><span class="nm">Other</span></span></div>`
            + row({ href: '#/?other=1', testid: 'vt-side-other', lead: VT.sd(waiting ? 'awaiting' : 'idle'), text: `${nowhere.length} session${nowhere.length === 1 ? '' : 's'} in no project`,
              title: "Live sessions whose folder no project lists", meta: `<span class="n">${nowhere.length}</span>` }) + '</div>';
        }
      }
      h += '</div>';
      const accounts = d ? d.accounts.length : 0;
      h += `<div class="side-foot"><button class="acct" data-act="pop" data-id="acct" data-testid="vt-home-account" aria-haspopup="menu"><span class="av">Z</span><span class="who">Zach</span><span class="plan">· ${accounts} account${accounts === 1 ? '' : 's'}</span>${VT.ic('chev', 'chev')}</button>`
        + `<button class="gear" data-act="pop" data-id="acct" title="Settings" aria-label="Settings">${VT.ic('gear')}</button></div></aside>`;
      return h;
    },
    overlay(pop) {
      if (pop === 'acct') return acctMenu();
      if (pop === 'newproject') return newProject();
      return '';
    },
  });

  function acctMenu() {
    const d = VT.doc, t = VT.S.theme;
    const seg = (k, l) => `<button class="${t === k ? 'on' : ''}" data-act="theme" data-id="${k}" aria-pressed="${t === k}">${l}</button>`;
    return `<div class="menu acctmenu" data-pop data-testid="vt-home-settings" role="menu">
      <div class="mh">Claude Code accounts on this machine</div>
      ${d.accounts.map((a) => `<div class="mi">${VT.sd(a.sessions_live ? 'running' : 'idle')}<span class="ell" title="${esc(a.home)}">${esc(a.id)}</span><span class="r">${a.sessions_live} live</span></div>`).join('')}
      <div class="sep"></div>
      <div class="mh">Settings</div>
      <div class="mi"><span class="sd">${VT.ic('sun')}</span><span>Theme</span><span class="seg r">${seg('system', 'System')}${seg('light', 'Light')}${seg('dark', 'Dark')}</span></div>
      <a class="mi" href="${esc(d.links.workbench)}" title="Clank: the older dashboard, its track pages and files (a deep-dive)"><span class="sd">${VT.ic('grid')}</span><span>Open Clank workbench</span></a>
      <div class="sep"></div>
      <div class="mh">Keys</div>
      <div class="mi keys"><span><kbd>1</kbd>–<kbd>4</kbd> home views · <kbd>K</kbd> KPI cards / rows · <kbd>Esc</kbd> close</span></div>
    </div>`;
  }

  // ------------------------------------------------------------------ New project (Codex-style)
  // WHY print and not write: the backend's mounts are GET-only by contract (clank/backend/mounts.py) and there is
  // no fenced write route for project descriptors yet, so the dialog shows the exact file it would write and copies it.
  const NP = { name: '', folders: [], draft: '' };
  function descriptorText() {
    const roots = NP.folders;
    const base = roots.length === 1 ? roots[0].replace(/\/+$/, '').split('/').pop() : '';
    const name = NP.name.trim();
    const lines = ['vibetracks:', '  version: 1', '  kind: project'];
    if (name && name !== base) lines.push(`  name: ${JSON.stringify(name)}`);
    lines.push(`  roots: [${roots.map((r) => JSON.stringify(r)).join(', ')}]`);
    return lines.join('\n') + '\n';
  }
  function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'project'; }
  function newProject() {
    const roots = NP.folders;
    const base = roots.length === 1 ? roots[0].replace(/\/+$/, '').split('/').pop() : '';
    const name = NP.name.trim() || base;
    const ok = roots.length >= 1 && (name || roots.length === 1);
    const problem = !roots.length ? 'Add at least one folder.' : (!NP.name.trim() && roots.length > 1) ? 'A project with several folders needs a name.' : '';
    return `<div class="dialog-scrim"><div class="dialog" data-pop data-testid="vt-newproject" role="dialog" aria-label="New project">
      <div class="dh"><b>New project</b><button class="btn icon ghost" data-act="pop" data-id="newproject" aria-label="Close">${VT.ic('x')}</button></div>
      <p class="dsub">A project is a name and one or more folders. Sessions started in any of its folders show under it.</p>
      <label class="fl">Name<input data-np="name" value="${esc(NP.name)}" placeholder="${esc(base || 'Defaults to the folder’s name')}" autocomplete="off"></label>
      <div class="fl">Folders</div>
      <div class="folders">${roots.map((f, i) => `<div class="frow">${VT.ic('folder')}<span class="ell" title="${esc(f)}">${esc(f)}</span><button class="btn icon ghost" data-act="npdel" data-id="${i}" aria-label="Remove ${esc(f)}">${VT.ic('x')}</button></div>`).join('') || '<div class="frow none">No folders yet</div>'}</div>
      <div class="addrow"><input data-np="folder" value="${esc(NP.draft)}" placeholder="/home/bam/your-repo" autocomplete="off"><button class="btn" data-act="npadd">${VT.ic('plus')}Add folder</button></div>
      <div class="fl">Descriptor <span class="faint">· it would be written to workspace/projects/${esc(slug(name || 'project'))}.vibetrack</span></div>
      <pre class="desc" data-testid="vt-newproject-descriptor">${esc(descriptorText())}</pre>
      <p class="dnote">${problem ? `<span class="warnword">${esc(problem)}</span> ` : ''}Nothing is written from here: this page's backend is read-only. Copy the descriptor into that file, or ask an agent to.</p>
      <div class="dfoot"><button class="btn" data-act="pop" data-id="newproject">Cancel</button><button class="btn primary" data-act="copy" data-what="the project descriptor" data-text="${esc(descriptorText())}" ${ok ? '' : 'disabled'}>${VT.ic('copy')}Copy descriptor</button></div>
    </div></div>`;
  }
  document.addEventListener('input', (ev) => {
    const k = ev.target.dataset && ev.target.dataset.np;
    if (!k) return;
    if (k === 'name') NP.name = ev.target.value; else NP.draft = ev.target.value;
    const pre = document.querySelector('[data-testid="vt-newproject-descriptor"]');
    if (pre) pre.textContent = descriptorText();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.target.dataset && ev.target.dataset.np === 'folder') { ev.preventDefault(); addFolder(); VT.render(); focusDraft(); }
  });
  function addFolder() {
    const v = NP.draft.trim().replace(/\/+$/, '');
    if (v && !NP.folders.includes(v)) NP.folders.push(v);
    NP.draft = '';
  }
  function focusDraft() { const el = document.querySelector('[data-np="folder"]'); if (el) el.focus(); }
  Object.assign(VT.actions, {
    sidefold(el) { const id = el.dataset.id; VT.S.side[id] = !VT.S.side[id]; },
    theme(el) { VT.S.theme = el.dataset.id; VT.applyTheme(); },
    npadd() { addFolder(); setTimeout(focusDraft, 0); },
    npdel(el) { NP.folders.splice(+el.dataset.id, 1); },
  });
})();
