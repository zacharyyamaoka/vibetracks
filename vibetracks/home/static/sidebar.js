/* Vibe Tracks home · sidebar (B2): always on, in Claude Code's visual language (Zach, Oct 9: "I don't want to
   relearn a new sidebar"): Claude's row height, type, hover and selected fills, muted group headers with the caret
   on hover, the same status dots (amber waits on you, grey blinking works, blue is new since you looked, a hollow
   ring is idle, a warning glyph is an error) and the account button bottom-left.
   NOT Claude's grouping key: Claude groups chats by the repo folder they started in; this groups TRACKS by project,
   a project being a name plus 1..N folders (the Codex model, Zach Oct 6), so each header says how many folders.
   Collapse a project by clicking its header; the arrow beside it opens the project page.
   r3 (Zach, Oct 9: "Other sessions should not be collapsed … like in claude"): a session no track's rule matches is
   its own row, a dot and its title like Claude's, under its project after the tracks (quieter: agents are detail),
   or under "Other" when no project lists its folder. No account chip anywhere. */
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

  /** Where a session row goes: the session itself in Claude (Desktop's link, else Remote Control), like Claude's
   *  sidebar opens a chat; with neither, the project page that lists it. */
  function sessionHref(s, p) {
    const o = s.open || {};
    return o.desktop || o.remote_control || (p ? `#/project/${encodeURIComponent(p.id)}` : '#/');
  }
  function sessionRows(list, p, cls) {
    const rank = { needs_you: 0, error: 1, working: 2 };
    const at = (s) => Math.max(s.last_action ? Date.parse(s.last_action.ts) : 0, s.remote && s.remote.last_event_ts ? Date.parse(s.remote.last_event_ts) : 0);
    return list.slice().sort((a, b) => (rank[a.state.word] ?? 3) - (rank[b.state.word] ?? 3) || at(b) - at(a)).map((s) => {
      const title = s.title || s.branch || s.id.slice(0, 8);
      const host = s.remote ? `<span class="host" title="on ${esc(s.remote.host)}, as of ${esc(VT.ago(s.remote.as_of))}">${esc(s.remote.host)}</span>` : '';
      const where = s.remote ? `on ${s.remote.host} · as of ${VT.ago(s.remote.as_of)}` : (s.live ? `live · ${s.status || 'unknown status'}` : 'ended');
      return row({ href: sessionHref(s, p), cls, testid: 'vt-side-session', extra: ` data-session-id="${esc(s.id)}"${(s.open || {}).remote_control && !(s.open || {}).desktop ? ' target="_blank" rel="noopener"' : ''}`,
        title: `${title} · ${VT.WORD[s.state.word] || s.state.word} · ${where} · no track rule matches${s.cwd ? ' · ' + s.cwd : ''}`,
        lead: VT.sd(VT.sessionDot(s)), text: esc(title), meta: host });
    }).join('');
  }

  function project(p, r) {
    const closed = !!VT.S.side[p.id];
    const roots = p.roots || [];
    const nf = roots.length;
    const folders = nf ? `${nf} folder${nf === 1 ? '' : 's'}` : 'no folders';
    const live = p.sessions_live || 0;
    const head = VT.isRenaming('project', p.id, 'side')
      ? `<div class="sgh-row"><div class="sgh editing" data-testid="vt-side-project" data-project-id="${esc(p.id)}">${VT.rnInput()}<span class="fc" data-testid="vt-side-folders">${folders}</span></div>`
      : `<div class="sgh-row"><button class="sgh" data-act="sidefold" data-id="${esc(p.id)}" aria-expanded="${closed ? 'false' : 'true'}" data-testid="vt-side-project" data-project-id="${esc(p.id)}" data-rename="project:${encodeURIComponent(p.id)}:side" title="${esc(p.name + ' · ' + (roots.map((x) => x.path).join(', ') || 'no descriptor') + ' · click to ' + (closed ? 'expand' : 'collapse') + ', double-click to rename')}">`
      + `<span class="nm">${esc(p.name)}</span><span class="caret ${closed ? '' : 'open'}">${VT.ic('caret')}</span><span class="fc" data-testid="vt-side-folders">${folders}</span></button>`
      + `<a class="sgh-go${r.name === 'project' && r.id === p.id ? ' sel' : ''}" href="#/project/${encodeURIComponent(p.id)}" title="Open the ${esc(p.name)} project page" aria-label="Open project ${esc(p.name)}">${VT.ic('open')}</a></div>`;
    if (closed) return `<div class="sgroup closed" data-project="${esc(p.id)}">${head}</div>`;
    let h = '';
    for (const t of p.tracks) {
      if (!VT.ACTIVE(t)) continue;
      const n = VT.liveCount(t);
      const age = t.state.word === 'needs_you' ? VT.ageBadge(VT.needAge(t)) : '';
      if (VT.isRenaming('track', t.id, 'side')) {
        h += `<div class="srow sel editing" data-testid="vt-side-track" data-track-id="${esc(t.id)}" data-dot="${VT.trackDot(t)}">${VT.sd(VT.trackDot(t))}${VT.rnInput()}</div>`;
        continue;
      }
      h += row({ href: `#/track/${encodeURIComponent(t.id)}`, sel: r.name === 'track' && r.id === t.id, testid: 'vt-side-track',
        extra: ` data-track-id="${esc(t.id)}" data-dot="${VT.trackDot(t)}" data-rename="track:${encodeURIComponent(t.id)}:side"`,
        title: VT.dotTitle(t) + (n ? ` · ${n} live session${n === 1 ? '' : 's'}` : '') + ' · double-click to rename',
        lead: VT.sd(VT.trackDot(t)), text: esc(t.title), meta: `${age}${n ? `<span class="n" title="${n} live session${n === 1 ? '' : 's'}">${n}</span>` : ''}` });
    }
    h += sessionRows(p.sessions_unpinned || [], p, 'loose');
    if (!h) h = `<div class="srow empty"><span class="sd"></span><span class="t">No active tracks · ${live} live</span></div>`;
    return `<div class="sgroup" data-project="${esc(p.id)}">${head}${h}</div>`;
  }

  VT.page('sidebar', {
    render(r) {
      const d = VT.doc;
      const w = VT.clampSide(VT.S.sideW || VT.SIDE.def);
      // WHY a handle on the edge and not a splitter control (Zach, Oct 9: "I should be able to resize the side bar"):
      // Claude Desktop's own sidebar resizes by dragging its right edge; double-click puts it back.
      let h = `<aside class="side" data-testid="vt-home-sidebar" aria-label="Navigation"><div class="side-resize" data-testid="vt-side-resize" role="separator" aria-orientation="vertical" aria-label="Resize the sidebar" aria-valuemin="${VT.SIDE.min}" aria-valuemax="${VT.SIDE.max}" aria-valuenow="${w}" tabindex="0" title="Drag to resize · double-click to reset"></div><nav class="side-top">`;
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
          // Claude's "Other" group: a header that folds, a + on it, one row per session.
          const closed = !!VT.S.side.__other;
          h += `<div class="sgroup${closed ? ' closed' : ''}" data-group="other"><div class="sgh-row"><button class="sgh" data-act="sidefold" data-id="__other" data-testid="vt-side-other" aria-expanded="${closed ? 'false' : 'true'}" title="Sessions whose folder no project lists · click to ${closed ? 'expand' : 'collapse'}"><span class="nm">Other</span><span class="caret ${closed ? '' : 'open'}">${VT.ic('caret')}</span><span class="fc">${nowhere.length}</span></button>`
            + `<button class="sgh-go" data-act="pop" data-id="newproject" data-testid="vt-side-other-add" title="New project: give these sessions' folders a home" aria-label="New project">${VT.ic('plus')}</button></div>`
            + (closed ? '' : sessionRows(nowhere, null, '')) + '</div>';
        }
      }
      h += '</div>';
      h += `<div class="side-foot"><button class="acct" data-act="pop" data-id="acct" data-testid="vt-home-account" aria-haspopup="menu"><span class="av">Z</span><span class="who">Zach</span>${VT.ic('chev', 'chev')}</button>`
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
      ${machines(d)}<div class="mh">Claude Code accounts on this machine</div>
      ${d.accounts.map((a) => `<div class="mi">${VT.sd(a.sessions_live ? 'running' : 'idle')}<span class="ell" title="${esc(a.home)}">${esc(a.id)}</span><span class="r">${a.sessions_live} live</span></div>`).join('')}
      <div class="sep"></div>
      <div class="mh">Settings</div>
      <div class="mi"><span class="sd">${VT.ic('sun')}</span><span>Theme</span><span class="seg r">${seg('system', 'System')}${seg('light', 'Light')}${seg('dark', 'Dark')}</span></div>
      ${d.links.workbench ? `<a class="mi" href="${esc(d.links.workbench)}" title="Clank: the older dashboard, its track pages and files (a deep-dive)"><span class="sd">${VT.ic('grid')}</span><span>Open Clank workbench</span></a>` : ''}
      ${d.links.machines ? `<a class="mi" href="${esc(d.links.machines)}" title="The hub's machine view: every machine's sync and session cards"><span class="sd">${VT.ic('grid')}</span><span>Open the machine view</span></a>` : ''}
      <div class="sep"></div>
      <div class="mh">Keys</div>
      <div class="mi keys"><span><kbd>1</kbd>–<kbd>4</kbd> home views · <kbd>K</kbd> KPI cards / rows · <kbd>Esc</kbd> close</span></div>
    </div>`;
  }

  // Other machines (r3): each one's status as of its own last sync; never "live".
  function machines(d) {
    if (!d.remote) return '';
    const rows = d.remote.hosts.map((h) => `<div class="mi" data-testid="vt-machine" data-host="${esc(h.host)}">${VT.sd(h.status === 'online' ? 'ready' : 'idle')}<span class="ell" title="${esc(`${h.host}: ${h.status}; last sync ${h.last_sync || 'never'}${h.platform ? ' · ' + h.platform : ''}${h.error ? ' · error: ' + h.error : ''}`)}">${esc(h.host)}</span><span class="r">${h.sessions_current} · ${h.last_sync ? esc(VT.ago(h.last_sync)) : 'never'}</span></div>`).join('');
    return `<div class="mh">Other machines in the share</div>${rows || '<div class="mi faint">None has synced yet</div>'}<div class="sep"></div>`;
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
    // WHY skip a click with detail > 1: the second click of a double-click (a rename, rename.js) must not fold back.
    sidefold(el, ev) { if (ev && ev.detail > 1) return false; const id = el.dataset.id; VT.S.side[id] = !VT.S.side[id]; },
    theme(el) { VT.S.theme = el.dataset.id; VT.applyTheme(); },
    npadd() { addFolder(); setTimeout(focusDraft, 0); },
    npdel(el) { NP.folders.splice(+el.dataset.id, 1); },
  });
  // ------------------------------------------------------------------ resize (drag the right edge, like Claude)
  // Document-level listeners: the poll re-renders the sidebar every 10 s, so a drag never depends on the handle element
  // it started on; the width lives on #vt-home (--side-w), which re-renders keep.
  let drag = null;
  const handleOf = (ev) => ev.target && ev.target.closest && ev.target.closest('[data-testid="vt-side-resize"]');
  function setWidth(w, persist) {
    VT.S.sideW = VT.clampSide(w);
    VT.applySideWidth();
    const handle = document.querySelector('[data-testid="vt-side-resize"]');
    if (handle) handle.setAttribute('aria-valuenow', String(VT.S.sideW));
    if (persist) VT.save();
  }
  document.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0 || !handleOf(ev)) return;
    const side = document.querySelector('[data-testid="vt-home-sidebar"]');
    drag = { x: ev.clientX, w: side ? side.getBoundingClientRect().width : VT.SIDE.def };
    document.documentElement.classList.add('vt-resizing');
    ev.preventDefault();
  });
  document.addEventListener('pointermove', (ev) => { if (drag) setWidth(drag.w + ev.clientX - drag.x, false); });
  const end = () => {
    if (!drag) return;
    drag = null;
    document.documentElement.classList.remove('vt-resizing');
    VT.save();
  };
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
  document.addEventListener('dblclick', (ev) => {
    if (!handleOf(ev)) return;
    VT.S.sideW = null;
    VT.applySideWidth();
    VT.save();
    ev.preventDefault();
  });
  document.addEventListener('keydown', (ev) => {
    if (!handleOf(ev) || (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight')) return;
    setWidth((VT.S.sideW || VT.SIDE.def) + (ev.key === 'ArrowRight' ? 16 : -16), true);
    ev.preventDefault();
    ev.stopImmediatePropagation();
  });
})();
