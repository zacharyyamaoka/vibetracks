/* Vibe Tracks home · inline rename (r3, 2026-10-09). Zach: "I want to be able to double click to rename", like
   Claude's sidebar (Sources/Images/Pasted image 20261009111915.png: the name turns into its own text, selected).

   Double-click a track or project name, in the sidebar or the page title: the name becomes an input holding the
   name exactly, all of it selected. Enter or clicking away saves, Esc cancels and sends nothing. A save is one
   fenced write: POST ../tracks/<id>/title {title, revision} or ../projects/<id>/name {name, revision}, fenced on
   the revision the home document carried (409 when the note or descriptor changed since; the page then re-reads).
   What was typed is sent as typed, never trimmed (the backend refuses only empty or multi-line text).
   Sessions are never renamed: their titles belong to Claude.

   Elements opt in with data-rename="<track|project>:<id>:<where>"; an area renders VT.rnInput() in place of the
   name while VT.isRenaming(kind, id, where). While the input has focus, app.js holds the 10 s re-render back. */
(function () {
  'use strict';
  const VT = window.VT;
  const esc = VT.esc;
  VT.editing = null;

  VT.isRenaming = (kind, id, where) => !!(VT.editing && VT.editing.kind === kind && VT.editing.id === id && VT.editing.where === where);
  VT.rnInput = (cls) => `<input class="rn${cls ? ' ' + cls : ''}" data-testid="vt-rename" value="${esc(VT.editing.original)}" aria-label="Rename ${esc(VT.editing.kind)}" spellcheck="false" autocomplete="off">`;
  VT.canRename = () => !(VT.doc && VT.doc.capabilities && VT.doc.capabilities.rename === false);

  function current(kind, id) {
    if (kind === 'track') { const t = VT.findTrack(id); return t ? { name: t.title, revision: t.revision } : null; }
    const p = VT.findProject(id);
    return p ? { name: p.name, revision: p.revision } : null;
  }

  function end(rerender) {
    VT.editing = null;
    if (rerender !== false) VT.render();
  }

  async function save() {
    const e = VT.editing;
    if (!e || e.saving || e.cancelled) return;
    const input = document.querySelector('[data-testid="vt-rename"]');
    const value = input ? input.value : e.original;
    if (value === e.original) { end(); return; }
    e.saving = true;
    const url = e.kind === 'track' ? `../tracks/${encodeURIComponent(e.id)}/title` : `../projects/${encodeURIComponent(e.id)}/name`;
    const body = e.kind === 'track' ? { title: value, revision: e.revision } : { name: value, revision: e.revision };
    let message = null;
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) });
      const answer = await r.json().catch(() => ({}));
      if (r.ok) {
        // Show the new name at once; the next document confirms it from the file.
        if (e.kind === 'track') { const t = VT.findTrack(e.id); if (t) { t.title = answer.title; t.revision = answer.revision; } }
        else {
          // A project's id is the slug of its name, so it moves with the rename; carry the fold state and the page.
          const p = VT.findProject(e.id);
          if (p) { p.name = answer.name; p.revision = answer.revision; p.id = answer.id || p.id; }
          if (answer.id && answer.id !== e.id) {
            if (VT.S.side[e.id] != null) { VT.S.side[answer.id] = VT.S.side[e.id]; delete VT.S.side[e.id]; VT.save(); }
            if (VT.route.name === 'project' && VT.route.id === e.id) VT.go('#/project/' + encodeURIComponent(answer.id));
          }
        }
      } else if (r.status === 409) {
        message = `Not renamed: the ${e.kind === 'track' ? 'note' : 'project file'} changed since this page read it. Reloaded; try again.`;
      } else {
        message = `Not renamed: ${answer.error || 'HTTP ' + r.status}`;
      }
    } catch (err) {
      message = `Not renamed: ${err && err.message ? err.message : err}`;
    }
    end();
    VT.invalidate('track?');
    VT.invalidate('project?');
    if (message) VT.toast(message);
    VT.refresh();
  }

  function start(kind, id, where) {
    if (!VT.doc || !VT.canRename()) return;
    const now = current(kind, id);
    if (!now) return;
    if (!now.revision) { VT.toast(kind === 'project' ? 'This group has no project file to rename (New project makes one).' : 'This track has no note revision to rename against.'); return; }
    VT.editing = { kind, id, where, original: now.name, revision: now.revision };
    VT.pop = null;
    VT.render();
    const input = document.querySelector('[data-testid="vt-rename"]');
    if (!input) { VT.editing = null; return; }
    input.focus();
    input.setSelectionRange(0, input.value.length);
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); save(); }
      else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); VT.editing.cancelled = true; end(); }
      else ev.stopPropagation(); // typing 1-4 or k must not switch views
    });
    input.addEventListener('blur', () => { if (VT.editing && !VT.editing.cancelled && !VT.editing.saving) save(); });
    // A click inside the input must not reach the row's own action (navigate, fold).
    ['click', 'mousedown', 'dblclick'].forEach((type) => input.addEventListener(type, (ev) => ev.stopPropagation()));
  }

  document.addEventListener('dblclick', (ev) => {
    const el = ev.target.closest && ev.target.closest('[data-rename]');
    if (!el || ev.target.closest('[data-testid="vt-rename"]')) return;
    const [kind, id, where] = el.dataset.rename.split(':');
    if (kind === 'project' && where === 'side') {
      // The double-click's first click folded the header (the second is ignored, sidebar.js); undo that fold.
      VT.S.side[id] = !VT.S.side[id];
      VT.save();
    }
    ev.preventDefault();
    const sel = window.getSelection && window.getSelection();
    if (sel) sel.removeAllRanges();
    start(kind, decodeURIComponent(id), where);
  });
})();
