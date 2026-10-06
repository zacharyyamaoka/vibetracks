  // ================================================================== Round 3 · Review (Zen)
  // Ported from the Oct 4 "Needs you" N1 Zen mode (vibetracks-dashboard clank/src/needs/n1/index.tsx) and its N6
  // "lane + context" splice: the page opens ON item 1, one decision fills the screen, ↵ takes the recommendation,
  // 1–3 pick an option and advance after a 220 ms visible confirm, N writes a note, S leaves it (the default applies),
  // J/K move, A opens the full context, Esc leaves, and a key rail beside the card lists every live key.
  // What round 3 changes (Zach, Oct 6 "Feedback on review mode"):
  // - media FIRST ("an image is a thousand words"): every card leads with a screenshot / video / chart / diff, text after;
  // - triaged order: blocking now → waiting for you (no default) → defaulting without you (optional);
  // - options laid out like Claude's AskUserQuestion: numbered, recommended first and labelled "(Recommended)", then
  //   a free-text "Other";
  // - a richer top bar: no T47/T12 ids, each step shows its state by icon + colour, its title in the tooltip;
  // - comment ON the media: M (or the button) drops a numbered pin on a spot of the image / chart / diff, or on the
  //   current frame of a video (with its timestamp);
  // - no inbox list (he rejected scanning one). Answers are drafts that leave through one Copy, as in N1: nothing here
  //   pretends to send.
  const ZM = {
    bt1: '{{media:z-bt1.webm}}', bt1Poster: '{{media:z-bt1-poster.webp}}', sn2: '{{media:z-sn2-belt.webp}}', pixel: '{{media:z-pixel.webp}}',
    clank: '{{media:z-clank-kinsim.webp}}', audits: '{{media:z-audits.webp}}', scans: '{{media:z-scans.webp}}',
  };
  const ZGROUP = { blocking: 'Blocking now', waiting: 'Waiting for you · no default', defaulting: 'Defaulting without you · optional' };
  const ZITEMS = [
    { id: 'kinsim-T47', track: 'kinsim', group: 'blocking', title: 'Pick at 1.0 m/s and above?', ask: 'Should this robot be expected to pick at 1.0 m/s and above?',
      blocks: 'BT3 · 0.5–1.0 m/s, BT4 · 1.5–2.0 m/s', agent: 'Kinematic Sim (AGENT) · bam', opened: 'opened wave 4',
      why: 'BT1 (0.1 m/s) is banked. The wave-5 builders need a target belt speed before they start BT3 and BT4; real MRF belts run 0.3–2 m/s.',
      media: [
        { kind: 'video', src: ZM.bt1, poster: ZM.bt1Poster, real: 'kinsim wave 4 report · hero-bt1 (stored-tape replay)', caption: 'BT1 banked at 0.1 m/s: the cartesian pick on the moving belt, replayed from its stored tape.' },
        { kind: 'chart', chart: 'speed', caption: 'Expected picks per hour vs belt speed, with the two candidate caps.', illustrative: true },
      ],
      options: [
        { label: 'Yes, as a stretch: BT3 required, BT4 optional', detail: 'Keeps the curriculum honest about real belts without blocking wave 5 on a speed the gripper may never reach.', rec: true },
        { label: 'No: cap the belt rungs at 0.5 m/s for now', detail: 'What happens if you stay silent: applies after wave 5 (loop: wave 4 finished).', def: true },
        { label: 'Yes, required: 1.0 m/s must pass before arm work', detail: 'Wave 5 builds BT3 first; arm rungs wait for it.' },
      ], defaultText: 'Belt rungs capped at 0.5 m/s after wave 5' },
    { id: 'rig-T2', track: 'rig', group: 'blocking', title: "Fix CAN 12's flash, dump it fresh, then sign the review", ask: "Fix CAN 12's flash, dump it fresh, then sign the review?",
      blocks: 'BN1 · powered motion on the pendulum', agent: 'Traj Tracking and Sim to Real (AGENT) · bam', opened: 'opened Oct 4 · 5 updates',
      why: 'SafeServo refuses the draft config and refuses commissioning on a lagging estimator, so powered motion stays closed until you review a fresh dump.',
      media: [
        { kind: 'diff', file: 'src/deployments/can12-pendulum-10to1/moteus_config_reviewed.json', illustrative: 'target values from the T2 text; the “before” values are illustrative',
          lines: [[' ', '"firmware": "v1.0.0 (git 6f063a90a9, clean)",'], ['-', '"servo.bemf_feedforward": 1.0,'], ['+', '"servo.bemf_feedforward": 0,'], ['-', '"motor_position.sources.0.pll_filter_hz": 200,'], ['+', '"motor_position.sources.0.pll_filter_hz": 400,'], [' ', '"servo.pid_dq.hz": 150,           // stays inside 100–200 Hz'], [' ', '"controller": "192551cb",'], ['+', '"reviewed_by": "zach",'], ['+', '"reviewed_at": "<first bench window>"']],
          caption: 'The diff you would sign: back-EMF feedforward to 0, estimator to 400 Hz (never toward 7 kHz).' },
        { kind: 'chart', chart: 'twin', caption: 'Twin replay error per rung (fixture series), under the 2.0° TWIN gate.', illustrative: true },
      ],
      options: [
        { label: 'Approve the diff at the first bench window', detail: 'Until then RAM-only config with readback; the signed dump must show the values on the left.', rec: true },
        { label: 'Not yet: keep CAN 12 unpowered', detail: 'No default: nothing is ever flashed until you answer.', def: true },
        { label: 'Approve now and flash immediately', detail: 'Skips the fresh dump; SafeServo still checks the estimator.' },
      ], defaultText: 'Nothing is flashed; powered motion stays closed' },
    { id: 'mag-masks', track: 'mag', group: 'waiting', title: 'Accept the two masked regions as reasoned?', ask: 'Accept masks M1 (window buttons) and M2 (caret blink) as reasoned?',
      blocks: 'the frozen ruler for round 7', agent: 'Pixel-error loop r6 · personal', opened: 'opened round 6',
      why: 'cases.json is frozen and a mask without a reason fails the gate. These two carry reasons, but a mask only counts once you sign it.',
      media: [{ kind: 'image', src: ZM.pixel, real: 'claude-transcript-viewer · pixel-kpi report, case session-solder', caption: 'Native | clone | max-channel diff for session-solder (MAE 3.63 %). M1 = Electron window buttons, M2 = composer caret.' }],
      options: [
        { label: 'Accept both: each names a cause outside the clone', detail: 'M1 is the browser tab having no native window chrome; M2 is the caret blink phase at capture time.', rec: true },
        { label: 'Accept M2 only; re-shoot M1 with a framed native window', detail: 'Costs one capture run; M1 stops being a mask.' },
        { label: 'Reject both: re-shoot natively', detail: 'The KPI rises until both regions are reproduced.' },
      ], defaultText: 'Waits for you; round 7 cannot freeze its ruler' },
    { id: 'kinsim-T12', track: 'kinsim', group: 'waiting', title: 'Land the integration branch on main?', ask: 'Land the integration branch on main?',
      blocks: 'nothing on the roadmap; keeps main 76 commits behind', agent: 'Kinematic Sim (AGENT) · bam', opened: 'opened wave 3',
      why: 'Waves 1–4 live on claude/kinematic-simulator-waste-sorting-cc14d6. Landing is your call, never the loop’s.',
      media: [{ kind: 'diff', file: 'git diff --stat main...claude/kinematic-simulator-waste-sorting-cc14d6', real: 'bam_ws, read 2026-10-06',
        lines: [[' ', '76 commits · 351 files changed, 74,087 insertions(+), 362 deletions(-)'], ['+', 'src/dev/bam_curriculum/            schemas, fixtures, research (36 files)'], ['+', 'src/core/mdp/env/sim/bam_eval/     episode_log_v2 fixtures + tests'], ['+', 'bam_traj_gen/src/tests/            14 files'], ['+', 'bam_kinsim_dashboard/tests/api/test_server_shell.py   | 1915 +++'], ['+', 'bam_kinsim_dashboard/tests/acceptance/clank_journey.mjs | 680 +++'], ['+', 'bam_kinsim_dashboard/vite.kinsim.config.mjs           |  79 +'], ['-', '362 deletions, all inside files the branch also edits']],
        caption: 'What landing brings to main, summarised by directory.' }],
      options: [
        { label: 'Land after wave 5 closes green; I merge by hand', detail: 'A merge commit on main once wave 5’s freeze is green, then the lane keeps going from main.', rec: true },
        { label: 'Land now (merge commit)', detail: 'Main gets waves 1–4 today; wave 5 rebases.' },
        { label: 'Keep it on the branch until Oct 22', detail: 'Main stays behind until the real pick.' },
      ], defaultText: 'Stays on the branch' },
    { id: 'kinsim-T33', track: 'kinsim', group: 'waiting', title: 'Disk at 89.7 %: remove merged worktrees and empty the trash?', ask: 'Disk at 89.7 %: remove merged worktrees and empty VS Code’s trash?',
      blocks: 'every wave, once the 91 % stop line trips', agent: 'Kinematic Sim (AGENT) · bam', opened: 'opened wave 4',
      why: 'The loop pauses waves at 91 %. Merged worktrees are the largest thing it may delete without losing unmerged work.',
      media: [{ kind: 'chart', chart: 'disk', caption: 'Root disk by area against the 91 % stop line (89.7 % from the kinsim gate; the split by area is illustrative).', illustrative: true }],
      options: [
        { label: 'Remove merged worktrees only', detail: 'Keeps every unmerged lane and the trash; frees about 4 %.', rec: true },
        { label: 'Do nothing; let the stop line pause waves', detail: 'No default: the loop keeps asking each wave.' },
        { label: 'Remove merged worktrees and empty VS Code’s trash', detail: 'Frees about 6 %; the trash cannot be restored.' },
      ], defaultText: 'Waits for you' },
    { id: 'kinsim-T11', track: 'kinsim', group: 'defaulting', title: 'Add clank-kinsim to your everyday Clank Preview?', ask: 'Add clank-kinsim to your everyday Clank Preview?',
      blocks: 'nothing', agent: 'Kinematic Sim (AGENT) · bam', opened: 'opened wave 1',
      why: 'The kinsim dashboard is a Clank plugin that you open from its own lane today.',
      media: [{ kind: 'image', src: ZM.clank, real: 'kinsim roadmap lens-bar report · flow 5', caption: 'The kinsim dashboard inside Clank: the roadmap lens board on dashboard.kinsim.' }],
      options: [
        { label: 'Add it to Clank Preview', detail: 'One more plugin in your daily Clank; it reads the curriculum home live.', rec: true },
        { label: 'Keep it separate', detail: 'Default, in effect since wave 1.', def: true },
        { label: 'Add it after the lens-bar lane lands', detail: 'Waits for the queued merge.' },
      ], defaultText: 'Kept separate (in effect since wave 1)' },
    { id: 'grasp-g07', track: 'grasping', group: 'defaulting', title: 'Promote the finger-clearance filter (g07) into the default pipeline?', ask: 'Promote the finger-clearance filter (g07) into the default grasp pipeline?',
      blocks: 'nothing; stage 4 starts either way', agent: 'Grasp bench tiers 3–5 · personal', opened: 'opened today',
      why: 'g07 rejects grasps with < 3 mm finger clearance and moved stage-3 success from 0.58 to 0.66; every kept experiment since builds on it.',
      media: [
        { kind: 'chart', chart: 'grasp', caption: 'Best-so-far stage-3 pick success by experiment; g07 is the step at 0.66.', illustrative: true },
        { kind: 'image', src: ZM.scans, real: 'object-database report · GraspNet + GC6D scan thumbnails', caption: 'Objects in the stage-4 set the filter would run on.' },
      ],
      options: [
        { label: 'Promote it now', detail: 'Stage 4 runs with the filter from its first experiment.', rec: true },
        { label: 'Promote at the end of this round', detail: 'Default: applies tonight if you stay silent.', def: true },
        { label: 'Keep it experimental', detail: 'Stage 4 starts without it.' },
      ], defaultText: 'Promoted at the end of this round (tonight)' },
    { id: 'rig-audits', track: 'rig', group: 'defaulting', title: 'Keep audits manual-only on the rig loop?', ask: 'Keep Codex audits manual-only on the rig loop?',
      blocks: 'nothing', agent: 'Traj Tracking and Sim to Real (AGENT) · bam', opened: 'opened Oct 5',
      why: '51 Codex audits ran Oct 3–5, most unasked. Since Oct 5 they run only when you ask (/llm-judge).',
      media: [{ kind: 'image', src: ZM.audits, real: 'rig-loop living report · “Every Codex audit” strip', caption: 'Every Codex audit Oct 3–5 by package, coloured by verdict.' }],
      options: [
        { label: 'Yes, manual only', detail: 'Your Oct 5 rule; the loop names a risky change in one line instead.', rec: true, def: true },
        { label: 'Audit every freeze automatically', detail: 'About 20–30 min per round on Codex xhigh.' },
        { label: 'Audit H-series rungs only', detail: 'Hardware-facing rungs get a judge; sim rungs do not.' },
      ], defaultText: 'Manual only (in effect since Oct 5)' },
  ];
  const zItem = (id) => ZITEMS.find((z) => z.id === id);
  const zTrackItems = (tid) => ZITEMS.filter((z) => z.track === tid);
  S.zen = { queue: ZITEMS.map((z) => z.id), i: 0, end: false, track: null, ans: {}, seen: {}, pinMode: false, pinDraft: null, noteOpen: false, ctx: false, flash: null, vt: {}, copied: false };
  // A track row's / sidebar's count: what still wants you (blocking + waiting), unanswered.
  // WHY answered vs done: skipping a no-default question settles nothing (it still waits for you); skipping a defaulting one lets its default apply.
  const zAnswered = (id) => { const a = S.zen.ans[id]; return !!(a && !a.skipped && (a.choice != null || (a.other && a.other.trim()))); };
  const zOpen = (tid) => ZITEMS.filter((z) => (!tid || z.track === tid) && z.group !== 'defaulting' && !zAnswered(z.id)).length;
  const zDone = (id) => { const a = S.zen.ans[id]; return !!(a && (a.choice != null || a.skipped || (a.other && a.other.trim()))); };
  // The five top-bar states Zach named.
  function zState(id, pos) {
    const z = zItem(id); const a = S.zen.ans[id] || {};
    if (!S.zen.end && pos === S.zen.i) return 'current';
    if (a.skipped) return z.group === 'defaulting' ? 'skipped' : 'skippedwait';
    if (a.choice != null || (a.other && a.other.trim())) {
      const rec = z.options.findIndex((o) => o.rec);
      return a.choice === rec && !(a.note && a.note.trim()) && !(a.pins && a.pins.length) && !(a.other && a.other.trim()) ? 'rec' : 'diff';
    }
    return z.group === 'defaulting' ? 'defaulting' : 'open';
  }
  const ZSTATE = { rec: ['✓', 'answered with the recommendation'], diff: ['✎', 'answered differently or with a comment'], skipped: ['↷', 'skipped: the default applies'], skippedwait: ['↷', 'skipped: still waits for you (no default)'], defaulting: ['◌', 'defaulting without you (not seen yet)'], open: ['', 'waiting for you'], current: ['●', 'current'] };

  function zStart(track, itemId) {
    const ids = (track ? zTrackItems(track) : ZITEMS).map((z) => z.id);
    S.zen.queue = ids; S.zen.track = track || null; S.zen.end = false; S.zen.pinMode = false; S.zen.pinDraft = null; S.zen.noteOpen = false; S.zen.ctx = false;
    const first = itemId ? ids.indexOf(itemId) : ids.findIndex((id) => !zDone(id));
    S.zen.i = Math.max(0, first);
  }
  function zGo(i) {
    S.zen.pinMode = false; S.zen.pinDraft = null; S.zen.noteOpen = false; S.zen.ctx = false; S.zen.flash = null;
    if (i >= S.zen.queue.length) { S.zen.end = true; S.zen.i = S.zen.queue.length; } else { S.zen.end = false; S.zen.i = Math.max(0, i); }
    render(); const m = root.querySelector('.main'); if (m) m.scrollTop = 0;
  }
  let zTimer = null;
  function zChoose(k) {
    const id = S.zen.queue[S.zen.i]; if (!id) return;
    const a = S.zen.ans[id] = Object.assign({}, S.zen.ans[id] || {}, { choice: k, skipped: false });
    S.zen.flash = k; render();
    clearTimeout(zTimer); zTimer = setTimeout(() => zGo(S.zen.i + 1), 220); // N1's visible confirm before the card peels off
    return a;
  }
  function zEnter() {
    const id = S.zen.queue[S.zen.i]; if (!id) return; const z = zItem(id); const a = S.zen.ans[id] || {};
    if (a.choice != null || (a.other && a.other.trim())) return zGo(S.zen.i + 1);
    zChoose(z.options.findIndex((o) => o.rec));
  }
  function zSkip() { const id = S.zen.queue[S.zen.i]; if (!id) return; S.zen.ans[id] = Object.assign({}, S.zen.ans[id] || {}, { skipped: true, choice: null }); zGo(S.zen.i + 1); }

  // ---- media
  function zChart(kind) {
    const W = 640, H = 230, L = 46, B = 30, T = 14, R = 14;
    const ax = (xs, ys, xl, yl) => `<line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="#d8d7d4"/><line x1="${L}" y1="${T}" x2="${L}" y2="${H - B}" stroke="#d8d7d4"/>${xs}${ys}<text x="${W - R}" y="${H - 4}" font-size="11" fill="#9b9a97" text-anchor="end">${xl}</text><text x="6" y="${T + 4}" font-size="11" fill="#9b9a97">${yl}</text>`;
    const sx = (v, a, b) => L + (v - a) / (b - a) * (W - L - R), sy = (v, a, b) => H - B - (v - a) / (b - a) * (H - B - T);
    let s = '';
    if (kind === 'speed') {
      const pts = [[0.1, 410], [0.3, 760], [0.5, 980], [0.75, 1080], [1.0, 1120], [1.5, 1010], [2.0, 820]];
      s += ax([0.1, 0.5, 1, 1.5, 2].map((v) => `<text x="${sx(v, 0, 2.1)}" y="${H - B + 16}" font-size="11" fill="#9b9a97" text-anchor="middle">${v}</text>`).join(''), [400, 800, 1200].map((v) => `<text x="${L - 6}" y="${sy(v, 300, 1300) + 4}" font-size="11" fill="#9b9a97" text-anchor="end">${v}</text>`).join(''), 'belt speed (m/s)', 'picks / h');
      s += `<rect x="${sx(0.5, 0, 2.1)}" y="${T}" width="${sx(1.0, 0, 2.1) - sx(0.5, 0, 2.1)}" height="${H - B - T}" fill="rgba(55,53,47,.05)"/><text x="${(sx(0.5, 0, 2.1) + sx(1.0, 0, 2.1)) / 2}" y="${T + 12}" font-size="11" fill="#787774" text-anchor="middle">BT3</text><rect x="${sx(1.5, 0, 2.1)}" y="${T}" width="${sx(2.0, 0, 2.1) - sx(1.5, 0, 2.1)}" height="${H - B - T}" fill="rgba(55,53,47,.05)"/><text x="${(sx(1.5, 0, 2.1) + sx(2.0, 0, 2.1)) / 2}" y="${T + 12}" font-size="11" fill="#787774" text-anchor="middle">BT4</text>`;
      s += `<path d="${pts.map(([x, y], i) => (i ? 'L' : 'M') + sx(x, 0, 2.1) + ',' + sy(y, 300, 1300)).join('')}" fill="none" stroke="#37352f" stroke-width="2"/>${pts.map(([x, y]) => `<circle cx="${sx(x, 0, 2.1)}" cy="${sy(y, 300, 1300)}" r="3" fill="${x === 0.1 ? '#37352f' : '#fff'}" stroke="#37352f"/>`).join('')}<text x="${sx(0.1, 0, 2.1) + 6}" y="${sy(410, 300, 1300) + 16}" font-size="11" fill="#37352f">BT1 banked</text>`;
    } else if (kind === 'twin') {
      const ys = T_.rig.kpis[1].series;
      s += ax(ys.map((v, i) => i % 3 === 0 ? `<text x="${sx(i, 0, ys.length - 1)}" y="${H - B + 16}" font-size="11" fill="#9b9a97" text-anchor="middle">${i + 1}</text>` : '').join(''), [1, 2, 3].map((v) => `<text x="${L - 6}" y="${sy(v, 0.5, 3.5) + 4}" font-size="11" fill="#9b9a97" text-anchor="end">${v}°</text>`).join(''), 'rung attempt', 'replay error');
      s += `<line x1="${L}" x2="${W - R}" y1="${sy(2, 0.5, 3.5)}" y2="${sy(2, 0.5, 3.5)}" stroke="#d9730d" stroke-dasharray="4 4"/><text x="${W - R}" y="${sy(2, 0.5, 3.5) - 6}" font-size="11" fill="#b35c00" text-anchor="end">TWIN gate 2.0°</text>`;
      s += `<path d="${ys.map((v, i) => (i ? 'L' : 'M') + sx(i, 0, ys.length - 1) + ',' + sy(v, 0.5, 3.5)).join('')}" fill="none" stroke="#37352f" stroke-width="2"/>`;
    } else if (kind === 'disk') {
      const parts = [['Worktrees (merged)', 4.1], ['Worktrees (unmerged)', 9.3], ['Datasets', 38.0], ['Caches', 11.6], ['VS Code trash', 2.2], ['Everything else', 24.5]];
      let x = L; const scale = (W - L - R) / 100;
      s += `<text x="${L}" y="${T + 10}" font-size="12" fill="#37352f" font-weight="600">Root disk · 89.7 % used</text>`;
      parts.forEach(([n, v], i) => { const w = v * scale; s += `<rect x="${x}" y="${T + 24}" width="${w - 1}" height="44" fill="${i === 0 || i === 4 ? '#787774' : '#d8d7d4'}"/>`; x += w; });
      s += `<line x1="${L + 91 * scale}" x2="${L + 91 * scale}" y1="${T + 16}" y2="${T + 76}" stroke="#d9730d" stroke-width="2"/><text x="${L + 91 * scale}" y="${T + 92}" font-size="11" fill="#b35c00" text-anchor="middle">stop line 91 %</text>`;
      parts.forEach(([n, v], i) => { s += `<rect x="${L + (i % 3) * 190}" y="${T + 112 + Math.floor(i / 3) * 22}" width="10" height="10" fill="${i === 0 || i === 4 ? '#787774' : '#d8d7d4'}"/><text x="${L + (i % 3) * 190 + 16}" y="${T + 121 + Math.floor(i / 3) * 22}" font-size="11.5" fill="#37352f">${n} · ${v} %</text>`; });
      s += `<text x="${L}" y="${H - 6}" font-size="11" fill="#9b9a97">dark = what option 1 / option 3 would remove</text>`;
    } else if (kind === 'grasp') {
      const ex = T_.grasping.exps; const sc = ex.filter((e) => e.score != null);
      s += ax(ex.map((e, i) => i % 2 === 0 ? `<text x="${sx(i, 0, ex.length - 1)}" y="${H - B + 16}" font-size="10.5" fill="#9b9a97" text-anchor="middle">${e.id}</text>` : '').join(''), [0.4, 0.6, 0.8].map((v) => `<text x="${L - 6}" y="${sy(v, 0.35, 0.82) + 4}" font-size="11" fill="#9b9a97" text-anchor="end">${v}</text>`).join(''), 'experiment', 'success (LB)');
      s += `<line x1="${L}" x2="${W - R}" y1="${sy(0.8, 0.35, 0.82)}" y2="${sy(0.8, 0.35, 0.82)}" stroke="#d8d7d4" stroke-dasharray="4 4"/><text x="${W - R}" y="${sy(0.8, 0.35, 0.82) - 5}" font-size="11" fill="#9b9a97" text-anchor="end">target 0.80</text>`;
      let b = null, d = ''; ex.forEach((e, i) => { if (e.status === 'kept') { if (b == null) d = `M${sx(i, 0, ex.length - 1)},${sy(e.score, 0.35, 0.82)}`; else d += `L${sx(i, 0, ex.length - 1)},${sy(b, 0.35, 0.82)}L${sx(i, 0, ex.length - 1)},${sy(e.score, 0.35, 0.82)}`; b = e.score; } }); d += `L${W - R},${sy(b, 0.35, 0.82)}`;
      s += `<path d="${d}" fill="none" stroke="#37352f" stroke-width="2"/>${sc.map((e) => { const i = ex.indexOf(e); return `<circle cx="${sx(i, 0, ex.length - 1)}" cy="${sy(e.score, 0.35, 0.82)}" r="${e.id === 'g07' ? 6 : 3}" fill="${e.status === 'kept' ? '#37352f' : '#c8c7c4'}" ${e.id === 'g07' ? 'stroke="#d9730d" stroke-width="2.5"' : ''}/>`; }).join('')}`;
      const gi = ex.findIndex((e) => e.id === 'g07'); s += `<text x="${sx(gi, 0, ex.length - 1) + 9}" y="${sy(0.66, 0.35, 0.82) + 18}" font-size="11.5" fill="#b35c00">g07 · finger clearance</text>`;
    }
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="chart" style="display:block">${s}</svg>`;
  }
  const fmtT = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  function zMedia(z, m, mi, lead) {
    const a = S.zen.ans[z.id] || {}; const pins = (a.pins || []).filter((p) => p.m === mi);
    const src = m.real ? `<span class="zsrc real" title="Real media from the repos">real · ${esc(m.real)}</span>` : `<span class="zsrc illus" title="Mocked for the prototype">illustrative${typeof m.illustrative === 'string' ? ' · ' + esc(m.illustrative) : ''}</span>`;
    let body;
    if (m.kind === 'video') body = `<video src="${m.src}" poster="${m.poster || ''}" ${S.zen.pinMode ? '' : 'autoplay'} muted loop playsinline controls data-mi="${mi}"></video>`;
    else if (m.kind === 'image') body = `<img src="${m.src}" alt="${esc(m.caption)}" draggable="false">`;
    else if (m.kind === 'chart') body = `<div class="zchart">${zChart(m.chart)}</div>`;
    else body = `<div class="zdiff"><div class="zdiff-h">${esc(m.file)}</div>${m.lines.map(([k, t]) => `<div class="dl d${k === '+' ? 'add' : k === '-' ? 'del' : 'ctx'}"><span class="dk">${k === ' ' ? '' : k}</span><span>${esc(t)}</span></div>`).join('')}</div>`;
    const pinDots = pins.map((p, n) => `<span class="zpin" style="left:${p.x}%;top:${p.y}%" title="${esc(p.text)}">${(a.pins || []).indexOf(p) + 1}</span>`).join('');
    const draft = S.zen.pinDraft && S.zen.pinDraft.m === mi ? `<span class="zpin draft" style="left:${S.zen.pinDraft.x}%;top:${S.zen.pinDraft.y}%">${(a.pins || []).length + 1}</span>
      <div class="zpinbox" style="left:${Math.min(S.zen.pinDraft.x, 62)}%;top:${Math.min(S.zen.pinDraft.y + 4, 80)}%"><div class="faint" style="font-size:11.5px">${m.kind === 'video' ? `Comment at ${fmtT(S.zen.pinDraft.t || 0)}` : 'Comment on this spot'}</div><input id="zpin-text" placeholder="What should the agent look at here?" autocomplete="off"><div class="faint" style="font-size:11px">↵ save · Esc cancel</div></div>` : '';
    const vmarks = m.kind === 'video' && pins.length ? `<div class="zvmarks">${pins.map((p) => `<button class="zvm" data-act="zseek" data-mi="${mi}" data-t="${p.t}" style="left:${Math.min(98, p.t / 14.05 * 100)}%" title="${esc(p.text)}">${(a.pins || []).indexOf(p) + 1} · ${fmtT(p.t)}</button>`).join('')}</div>` : '';
    return `<figure class="zfig ${lead ? 'lead' : ''} k-${m.kind}"><div class="zmedia ${S.zen.pinMode ? 'pinning' : ''}" data-mi="${mi}">${body}${pinDots}${draft}</div>${vmarks}
      <figcaption><span>${esc(m.caption)}</span>${src}</figcaption></figure>`;
  }

  // ---- top bar: triaged groups, one step per item, state by icon + colour, title in the tooltip
  function zBar() {
    const q = S.zen.queue; const groups = ['blocking', 'waiting', 'defaulting'].map((g) => [g, q.map((id, pos) => [id, pos]).filter(([id]) => zItem(id).group === g)]).filter(([, xs]) => xs.length);
        return `<div class="zbar">${groups.map(([g, xs]) => `<div class="zgrp"><div class="zgl ${g === 'blocking' ? 'st-needs' : ''}">${ZGROUP[g]} <span class="faint">${xs.length}</span></div><div class="zsteps">${xs.map(([id, pos]) => { const st = zState(id, pos); const z = zItem(id);
        return `<button class="zstep s-${st}" data-act="zjump" data-i="${pos}" title="${esc(z.title)} — ${ZSTATE[st][1]}" aria-label="${esc(z.title)}: ${ZSTATE[st][1]}" ${st === 'current' ? 'aria-current="step"' : ''}><span>${ZSTATE[st][0]}</span><i>${esc(z.title)}</i></button>`; }).join('')}</div></div>`).join('')}
      <div class="zgrp zend"><div class="zgl">&nbsp;</div><button class="zstep s-endbtn ${S.zen.end ? 's-current' : ''}" data-act="zjump" data-i="${q.length}" title="Summary">Done</button></div></div>
      <div class="zmeter faint">${q.filter(zAnswered).length} of ${q.length} answered · ${q.filter((id) => zItem(id).group !== 'defaulting' && !zAnswered(id)).length} still want you</div>`;
  }
  function zDock() {
    const keys = S.zen.end ? [['K', 'back'], ['C', 'copy answers'], ['Esc', 'leave']] : S.zen.pinDraft ? [['↵', 'save comment'], ['Esc', 'cancel']] : [['↵', 'take recommendation'], ['1–3', 'pick an option'], ['4', 'other (your words)'], ['N', 'note'], ['M', 'comment on media'], ['S', 'skip · default applies'], ['A', 'context'], ['J / K', 'next / previous'], ['Esc', 'leave']];
    return `<aside class="zrail"><div class="lbl" style="margin-bottom:6px">Keys</div>${keys.map(([k, l]) => `<div class="zkey"><kbd>${k}</kbd> ${l}</div>`).join('')}</aside>`;
  }
  function zCard() {
    const id = S.zen.queue[S.zen.i]; const z = zItem(id); const t = track(z.track); const p = proj(t.project); const a = S.zen.ans[id] || {};
    const picked = S.zen.flash != null ? S.zen.flash : a.choice;
    const media = z.media.map((m, mi) => zMedia(z, m, mi, mi === 0)).join('');
    const pinsList = (a.pins || []).length ? `<ol class="zpins">${a.pins.map((pp, n) => `<li><b>${n + 1}</b> ${z.media[pp.m].kind === 'video' ? `<span class="faint">at ${fmtT(pp.t)}</span> ` : `<span class="faint">on the ${z.media[pp.m].kind}</span> `}“${esc(pp.text)}” <button class="linkish" data-act="zunpin" data-i="${n}">remove</button></li>`).join('')}</ol>` : '';
    return `<article class="zcard" data-zitem="${id}">
      <p class="zeye"><span class="${z.group === 'blocking' ? 'st-needs' : ''}">${ZGROUP[z.group]}</span> · ${esc(t.title)} · ${esc(p.name)} · blocks ${esc(z.blocks)}</p>
      <h1 class="zq">${esc(z.ask)}</h1>
      <div class="zmediaset n${z.media.length}">${media}</div>
      <div class="zmbar"><button class="btn ${S.zen.pinMode ? 'primary' : ''}" data-act="zpinmode">${icon('chat')} ${S.zen.pinMode ? 'Click a spot on the media…' : 'Comment on this media'} <kbd>M</kbd></button>${pinsList ? '' : '<span class="faint" style="font-size:12.5px">Pin a comment to a spot, or to the paused video frame.</span>'}</div>${pinsList}
      <p class="zwhy">${esc(z.why)} <span class="faint">· ${esc(z.agent)} · ${esc(z.opened)}</span></p>
      <div class="ask" role="radiogroup" aria-label="Your answer">
        ${z.options.map((o, k) => `<button class="aopt ${picked === k ? 'on' : ''}" role="radio" aria-checked="${picked === k}" data-act="zopt" data-k="${k}"><span class="an">${k + 1}.</span><span class="at"><span class="al">${esc(o.label)}${o.rec ? ' <span class="arec">(Recommended)</span>' : ''}${o.def ? ` <span class="adef">${z.group === 'blocking' || z.group === 'waiting' ? 'what happens now' : 'default'}</span>` : ''}</span><span class="ad">${esc(o.detail)}</span></span></button>`).join('')}
        <label class="aopt other ${a.other && a.other.trim() ? 'on' : ''}"><span class="an">4.</span><span class="at"><input id="zother" placeholder="Other: type your own answer…" value="${esc(a.other || '')}" autocomplete="off"></span></label>
      </div>
      ${S.zen.noteOpen || (a.note && a.note.trim()) ? `<textarea id="znote" class="znote" rows="2" placeholder="A note for the agent, sent with your answer (↵ saves and goes on · Esc closes)">${esc(a.note || '')}</textarea>` : `<button class="linkish" data-act="znote" style="margin-top:8px;font-size:13px">+ Add a note <kbd>N</kbd></button>`}
      <div class="zfoot"><button class="btn" data-act="zskip">Skip · ${esc(z.defaultText)} <kbd>S</kbd></button><button class="btn" data-act="zctx">${S.zen.ctx ? 'Hide' : 'Full'} context <kbd>A</kbd></button><span class="spacer"></span><button class="btn primary" data-act="zenter">${a.choice != null || (a.other && a.other.trim()) ? 'Next' : 'Take recommendation'} <kbd>↵</kbd></button></div>
      ${S.zen.ctx ? `<dl class="meta zctx"><dt>Track</dt><dd>${esc(t.title)} · ${esc(t.file)}</dd><dt>Asked by</dt><dd>${esc(z.agent)}</dd><dt>Blocks</dt><dd>${esc(z.blocks)}</dd><dt>If you stay silent</dt><dd>${esc(z.defaultText)}</dd><dt>Answers reach</dt><dd>${z.track === 'kinsim' ? 'triage_answers.jsonl (jsonl append)' : 'the agent’s chat (paste)'}</dd></dl>` : ''}
    </article>`;
  }
  function zEnd() {
    const q = S.zen.queue; const decided = q.filter((id) => { const a = S.zen.ans[id]; return a && !a.skipped && (a.choice != null || (a.other && a.other.trim())); });
    const defaulting = q.filter((id) => !decided.includes(id) && zItem(id).group === 'defaulting');
    const waiting = q.filter((id) => !decided.includes(id) && !defaulting.includes(id));
    const ansText = (id) => { const z = zItem(id); const a = S.zen.ans[id]; const o = a.choice != null ? z.options[a.choice].label : 'Other'; return `${esc(o)}${a.other && a.other.trim() ? ` — “${esc(a.other)}”` : ''}${a.note && a.note.trim() ? ` · note “${esc(a.note)}”` : ''}${a.pins && a.pins.length ? ` · ${a.pins.length} comment${a.pins.length > 1 ? 's' : ''} on the media` : ''}`; };
    const byAgent = {}; decided.forEach((id) => { const ag = zItem(id).agent; (byAgent[ag] = byAgent[ag] || []).push(id); });
    return `<article class="zcard zendcard"><p class="zeye">Review${S.zen.track ? ' · ' + esc(track(S.zen.track).title) : ''} · done</p><h1 class="zq">${decided.length} decided · ${defaulting.length} defaulting${waiting.length ? ` · ${waiting.length} still waiting` : ''}</h1>
      <h2>You decided</h2>${decided.length ? `<ul class="zsum">${decided.map((id) => `<li><button class="linkish" data-act="zjump" data-i="${q.indexOf(id)}">${esc(zItem(id).title)}</button><br><span class="grey">${ansText(id)}</span></li>`).join('')}</ul>` : '<p class="faint">Nothing yet.</p>'}
      <h2>Defaulting without you</h2>${defaulting.length ? `<ul class="zsum">${defaulting.map((id) => `<li>${esc(zItem(id).title)}<br><span class="faint">${esc(zItem(id).defaultText)}${(S.zen.ans[id] || {}).skipped ? ' · you skipped it' : ' · not opened'}</span></li>`).join('')}</ul>` : '<p class="faint">Nothing.</p>'}
      ${waiting.length ? `<h2>Still waiting for you</h2><ul class="zsum">${waiting.map((id) => `<li><button class="linkish" data-act="zjump" data-i="${q.indexOf(id)}">${esc(zItem(id).title)}</button><br><span class="faint">no default · ${(S.zen.ans[id] || {}).skipped ? 'you skipped it' : 'not answered'}</span></li>`).join('')}</ul>` : ''}
      <h2>Back to the agents</h2>${Object.keys(byAgent).length ? `<ul class="zsum">${Object.entries(byAgent).map(([ag, ids]) => `<li>${dot('live')} <b style="font-weight:500">${esc(ag)}</b><br><span class="grey">${ids.length} answer${ids.length > 1 ? 's' : ''}${ids.some((id) => (S.zen.ans[id].pins || []).length || (S.zen.ans[id].note || '').trim()) ? ' with comments' : ''} · ${ids.map((id) => esc(zItem(id).title)).join(' · ')}</span></li>`).join('')}</ul>` : '<p class="faint">Nothing to send.</p>'}
      <div class="zfoot"><button class="btn primary" data-act="zcopy">${S.zen.copied ? '✓ Copied' : 'Copy all answers'} <kbd>C</kbd></button><button class="btn" data-act="home">Back to home</button><span class="faint" style="font-size:12.5px">Nothing is sent from here: paste where each agent reads answers (as in the Oct 4 lane).</span></div></article>`;
  }
  function zenPage() {
    const t = S.zen.track ? track(S.zen.track) : null;
    return `<div class="zen"><div class="ztop"><button class="btn" data-act="zleave">${icon('left')} Leave <kbd>Esc</kbd></button><span class="zt"><b>Review</b>${t ? ' · ' + esc(t.title) : ' · all tracks'}</span>${t ? '<button class="linkish" data-act="zall" style="font-size:12.5px">review all tracks</button>' : ''}</div>
      ${zBar()}<div class="zlayout">${zDock()}<div class="zstage">${S.zen.end ? zEnd() : zCard()}</div></div></div>`;
  }
  function zBrief() {
    return S.zen.queue.filter(zDone).map((id) => { const z = zItem(id); const a = S.zen.ans[id];
      return `## ${z.title} (${track(z.track).title})\n- Answer: ${a.skipped ? 'skipped — default applies: ' + z.defaultText : a.choice != null ? z.options[a.choice].label : 'Other: ' + a.other}${a.note ? `\n- Note: ${a.note}` : ''}${(a.pins || []).map((p, n) => `\n- Comment ${n + 1} (${z.media[p.m].kind}${z.media[p.m].kind === 'video' ? ' at ' + fmtT(p.t) : ` at ${p.x.toFixed(0)}%,${p.y.toFixed(0)}%`}): ${p.text}`).join('')}`; }).join('\n\n');
  }
  // Zen keys (N1's map, plus 4 = other and M = comment on media). Returns true when handled.
  function zKey(e) {
    const tgt = e.target; const k = e.key;
    if (tgt && tgt.id === 'zpin-text') { if (k === 'Enter') { e.preventDefault(); zPinSave(tgt.value); } else if (k === 'Escape') { e.preventDefault(); S.zen.pinDraft = null; render(); } return true; }
    if (tgt && (tgt.id === 'znote' || tgt.id === 'zother')) { if (k === 'Enter' && !e.shiftKey) { e.preventDefault(); zEnter(); } else if (k === 'Escape') { e.preventDefault(); tgt.blur(); } return true; }
    if (tgt && tgt.closest && tgt.closest('input, textarea, select')) return false;
    if (e.ctrlKey || e.metaKey || e.altKey) return false;
    const h = (f) => { e.preventDefault(); f(); return true; };
    if (k === 'Escape') return h(() => { if (S.zen.pinMode || S.zen.pinDraft) { S.zen.pinMode = false; S.zen.pinDraft = null; render(); } else go('home', null); });
    if (k === 'j' || k === 'ArrowRight') return h(() => zGo(S.zen.i + 1));
    if (k === 'k' || k === 'ArrowLeft') return h(() => zGo(S.zen.i - 1));
    if (S.zen.end) { if (k === 'c') return h(zCopy); return false; }
    if (k === 'Enter') return h(zEnter);
    if (k === 's') return h(zSkip);
    if (k === 'a') return h(() => { S.zen.ctx = !S.zen.ctx; render(); });
    if (k === 'm') return h(() => { S.zen.pinMode = !S.zen.pinMode; S.zen.pinDraft = null; render(); });
    if (k === 'n') return h(() => { S.zen.noteOpen = true; render(); const n = root.querySelector('#znote'); if (n) n.focus(); });
    if (k === '4' || k === 'o') return h(() => { const o = root.querySelector('#zother'); if (o) o.focus(); });
    const n = '123'.indexOf(k); if (n >= 0) return h(() => zChoose(n));
    return false;
  }
  function zPinSave(text) {
    const id = S.zen.queue[S.zen.i]; const d = S.zen.pinDraft; if (!d) return;
    if (text && text.trim()) { const a = S.zen.ans[id] = Object.assign({ pins: [] }, S.zen.ans[id] || {}); a.pins = (a.pins || []).concat([{ m: d.m, x: d.x, y: d.y, t: d.t, text: text.trim() }]); }
    S.zen.pinDraft = null; S.zen.pinMode = false; render();
  }
  function zCopy() {
    const txt = zBrief(); S.zen.copied = true;
    try { navigator.clipboard && navigator.clipboard.writeText(txt); } catch (e) { /* clipboard refused: the summary still lists every answer */ }
    render();
  }
  // Pin placement: a click on the media while pin mode is on. Video: pause and use the current frame's time.
  function zMediaClick(e) {
    const box = e.target.closest('.zmedia'); if (!box || !S.zen.pinMode || S.page !== 'review') return false;
    e.preventDefault(); e.stopPropagation();
    const r = box.getBoundingClientRect(); const v = box.querySelector('video'); let t = 0;
    if (v) { v.pause(); t = v.currentTime; S.zen.vt[S.zen.queue[S.zen.i] + ':' + box.dataset.mi] = t; }
    S.zen.pinDraft = { m: +box.dataset.mi, x: (e.clientX - r.left) / r.width * 100, y: (e.clientY - r.top) / r.height * 100, t };
    render(); const inp = root.querySelector('#zpin-text'); if (inp) inp.focus();
    return true;
  }
