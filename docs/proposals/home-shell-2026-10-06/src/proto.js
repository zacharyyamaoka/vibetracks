/* Vibe Tracks home / project / track shell — five clickable proposals over ONE shared fixture.
   Every variant renders the same projects, tracks, KPIs, experiments, audits and sessions; they differ only in
   structure (where the sidebar lives, what the home body is, what the board's columns mean, where live agents
   surface, whether the track page is tabbed). Data is a hand-written fixture modelled on the real registry
   (vibetracks-dashboard/workspace/tracks/*.md) and the Oct 4-6 loop state; numbers are illustrative, not read live.

   Track model (Zach, Oct 6 feedback):
   - several soft KPIs per track (kpis[0] is the summary statistic drawn as the row's sparkline) + separate hard gates;
   - mode: 'discover' (agent proposes / refines KPIs and gates; a track with no KPIs sits here) or 'optimize';
   - state: needs / stalled / ok (computed) or done / archived (set, like a kanban card);
   - experiments: an evo-style frontier tree, each tied to a roadmap rung;
   - audits: LLM-judge rounds (model, verdict, findings open/fixed, time to verdict, audit file). */
window.VTP = (function () {
  'use strict';

  // ------------------------------------------------------------------ fixture helpers
  // K(label, series, target, dir, unit, dec): a soft KPI; now = last point.
  const K = (label, series, target, dir, unit, dec, extra) => Object.assign({ label, series, now: series[series.length - 1], target, dir: dir || 'up', unit: unit || '', dec }, extra || {});
  const G = (name, pass, now) => ({ name, pass, now });
  const MODELS = ['Opus 5.5', 'GPT-6.1 Sol', 'Sonnet 5.5'];
  // E: experiment rows [id, parent, status, score, hypothesis, rung]
  function E(rows, acct) {
    return rows.map(([id, parent, status, score, hyp, rung], i) => ({ id, parent, status, score, hyp, rung,
      model: MODELS[(i * 2 + 1) % 3], tokens: 8000 + ((i * 7919) % 52000), latency: (2 + ((i * 37) % 41)) + ' min', cost: '$' + (0.4 + ((i * 53) % 310) / 100).toFixed(2), author: acct, created: 'Oct ' + Math.min(6, 1 + Math.floor(i / 2)) }));
  }

  // ------------------------------------------------------------------ fixture
  const PROJECTS = [
    { id: 'bam', name: 'BAM Robotics', custom: true, roots: ['~/bam_ws', '~/clank-workbench', '~/viser-3d-viewer'], color: '#8d7cc3',
      north: { label: 'Real-pick gates passed', text: '3 / 7', series: [0, 0, 1, 1, 1, 2, 2, 2, 3, 3], target: 7, note: 'pick one real piece of waste · due Oct 22 (16 d)' },
      tracks: ['rig', 'kinsim', 'grasping', 'detection', 'hyperspectral'] },
    { id: 'ctv', name: 'claude-transcript-viewer', roots: ['~/claude-transcript-viewer'], color: '#6f9fb8',
      north: { label: 'Sessions opened from the GUI', text: '64 %', series: [5, 8, 12, 15, 22, 30, 38, 47, 58, 64], target: 90, note: 'share of his sessions opened in the multi-account GUI' },
      tracks: ['mag'] },
    { id: 'pyblocks', name: 'pyblocks', roots: ['~/pyblocks'], color: '#c08d5a',
      north: { label: 'M1 exit clauses met', text: '6 / 8', series: [2, 3, 3, 4, 4, 5, 5, 6, 6, 6], target: 8, note: 'M1 “One file, verified”' },
      tracks: ['pyblocks-m1'] },
    { id: 'vt', name: 'vibetracks', roots: ['~/vibetracks'], color: '#7fa37a',
      north: { label: 'Tracks reporting live', text: '9 / 12', series: [3, 4, 5, 5, 6, 7, 8, 8, 9, 9], target: 12, note: 'every track has a KPI row today' },
      tracks: ['vt-join', 'vt-exp', 'vt-dash', 'vt-ovk'] },
    { id: 'bbox', name: 'bbox-ui', roots: ['~/bbox-ui'], color: '#b97a95',
      north: { label: 'Images labelled per week', text: '1,840', series: [420, 510, 600, 640, 810, 900, 1100, 1350, 1600, 1840], target: 3000, note: 'feeds the detection track' },
      tracks: ['bbox'] },
    { id: 'bbt', name: 'beautiful-bt', roots: ['~/beautiful-bt'], color: '#8f8f8a',
      north: { label: 'Weekly installs', text: '37', series: [3, 4, 9, 11, 14, 18, 22, 29, 33, 37], target: 100, note: 'PyPI downloads, bots excluded' },
      tracks: ['bbt'] },
  ];

  const T = {
    rig: { project: 'bam', title: 'Sim to Real & Trajectory Tracking', shape: 'ladder', state: 'needs', mode: 'optimize',
      kpis: [K('Highest rung proven', [3, 4, 4, 5, 6, 6, 7, 8, 9, 9], null, 'up', 'rungs', null, { of: 24 }),
        K('Twin replay error', [3.1, 2.8, 2.6, 2.2, 2.0, 1.9, 1.7, 1.6, 1.5, 1.4], 1.0, 'down', '°', 1),
        K('Tracking RMS · CAN 12', [2.4, 2.1, 1.9, 1.6, 1.4, 1.2, 1.1, 0.9, 0.85, 0.8], 0.5, 'down', '°', 2),
        K('Frame budget used', [92, 90, 88, 85, 80, 78, 76, 74, 72, 71], 80, 'down', '%', 0)],
      gates: [G('TWIN gate · replay error ≤ 2.0°', true, '1.4°'), G('SafeServo torque limits', true, '0 trips / 214 runs'), G('E-stop latency < 50 ms', true, '18 ms')],
      sentence: 'H3 w6 frame budget proven in sim · next rung needs powered motion',
      needs: "Fix CAN 12's flash, dump it fresh, then sign the review", asked: '3 h ago', due: 'Oct 22',
      asOf: '6 min ago', ruler: { frozen: true, hash: 'ladder.json · 5be2a07' },
      rung: { current: 'T2 · Powered motion on CAN 12 (waits on you)', next: 'T14 · Five-bar powered sweep', banked: ['H3 w6 · Frame budget (pep 0005)', 'H3 w5 · Arm safety in sim (pep 0003)', 'H3 w4 · SafeServo limits (pep 0002)', 'W0c · Twin replays CAN 12 within TWIN gate'] },
      sessions: [{ acct: 'bam', title: 'Traj Tracking and Sim to Real (AGENT)', age: '1 min' }],
      expMetric: 'Twin replay error (°, lower is better)',
      exps: E([['r01', null, 'kept', 3.1, 'Twin with the identified plant (CAN 12)', 'W0c'], ['r02', 'r01', 'kept', 2.2, 'Add ~130 mNm breakaway friction to the servo model', 'W0c'],
        ['r03', 'r01', 'discarded', 2.9, 'Run the sim at 2 kHz instead of 1 kHz', 'W0c'], ['r04', 'r02', 'kept', 1.9, 'SafeServo torque clamp inside the loop', 'H3 w4'],
        ['r05', 'r04', 'failed', null, 'Gravity comp during homing (circular: needs the pose it is homing to)', 'H3 w4'], ['r06', 'r04', 'kept', 1.6, 'Arm safety envelope in sim', 'H3 w5'],
        ['r07', 'r06', 'kept', 1.4, '1 kHz loop with a 71 % frame budget', 'H3 w6'], ['r08', 'r07', 'discarded', 1.5, 'Async CAN reads on a second thread', 'H3 w6'],
        ['r09', 'r07', 'running', null, 'Powered motion T2 (waiting on your approval)', 'T2']], 'bam'),
      audits: [
        { r: 1, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 27, findings: [['Frame budget measured on the sim clock, not wall clock', false], ['No test pins the 80 % budget line', false], ['Per-field table missing for the pass-through safety layer', false]] },
        { r: 2, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 22, findings: [['Budget overrun path logs but does not stop', false], ['Docs claim 1 kHz; config says 500 Hz', false]] },
        { r: 3, model: 'GPT-6.1 Sol · xhigh', verdict: 'PASS WITH FIXES', mins: 18, findings: [['Jitter percentile reported as a mean', true]] }],
      auditDir: '~/bam_ws/reports/media/audits/2026-10-05-rig-h3w6',
      evalCmd: 'uv run rig-loop judge --ladder ladder.json', file: '~/bam_ws/tracks/rig.md' },
    kinsim: { project: 'bam', title: 'Kinematic Sim', shape: 'ladder', state: 'ok', mode: 'optimize',
      kpis: [K('Rungs proven', [3, 4, 6, 7, 9, 10, 11, 12, 13, 14], null, 'up', 'rungs', null, { of: 62 }),
        K('Sim pick success', [0.31, 0.35, 0.41, 0.44, 0.52, 0.55, 0.58, 0.61, 0.63, 0.66], 0.9, 'up', '', 2),
        K('Picks per hour (sim)', [410, 440, 520, 560, 610, 640, 700, 760, 790, 820], 1200, 'up', '', 0),
        K('Wall-clock per wave', [7.9, 7.1, 6.8, 6.0, 5.4, 4.9, 4.2, 3.8, 3.4, 3.1], 3, 'down', 'h', 1)],
      gates: [G('Regression replay R1–R14', true, '14 / 14 pass'), G('Disk below 91 % stop line', true, '89.7 %')],
      sentence: 'Wave 4 running · climbing R15 belt at 0.3 m/s', asOf: '12 min ago', ruler: { frozen: true, hash: 'curriculum · a41f9c2' },
      rung: { current: 'R15 · Belt at 0.3 m/s', next: 'R16 · Two-robot handoff', banked: ['R14 · Clutter of 12 objects', 'R13 · Overhead RGBD in sim', 'R12 · Suction grasp on flat items'] },
      sessions: [{ acct: 'bam', title: 'Kinematic Sim (AGENT)', age: '4 min' }, { acct: 'personal', title: 'Wave 4 lane: belt speed', age: '9 min' }],
      audits: [{ r: 1, model: 'Fable 5.1 · xhigh', verdict: 'FAIL', mins: 14, findings: [['R13 claimed green without its evidence file', false]] }, { r: 2, model: 'Fable 5.1 · xhigh', verdict: 'PASS', mins: 11, findings: [] }],
      auditDir: '~/bam_ws/reports/media/audits/2026-10-03-kinsim-wave4',
      evalCmd: 'uv run kinsim judge --frozen', file: '~/bam_ws/tracks/kinsim.md' },
    grasping: { project: 'bam', title: 'Grasping', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Stage-3 pick success (Wilson LB)', [0.42, 0.45, 0.51, 0.5, 0.58, 0.61, 0.6, 0.66, 0.69, 0.71], 0.8, 'up', '', 2),
        K('GraspNet-1B AP (seen)', [38, 39, 41, 41, 44, 45, 47, 47, 48, 49], 55, 'up', '', 0),
        K('Inference latency', [210, 205, 190, 180, 182, 170, 160, 150, 148, 141], 100, 'down', 'ms', 0),
        K('Envs beaten (of 9)', [1, 1, 2, 2, 2, 3, 3, 3, 4, 4], 9, 'up', '', 0)],
      gates: [G('Stage 1–2 still beaten', true, '2 / 2'), G('Evaluator OOM-free', true, '40 / 40 runs'), G('Eval protocol frozen', true, 'v3')],
      sentence: 'MuJoCo stage 3 · GraspNet-row model', asOf: '38 min ago', ruler: { frozen: true, hash: 'eval protocol v3 · 7c0de11' },
      sessions: [{ acct: 'personal', title: 'Grasp bench tiers 3–5', age: '12 min' }, { acct: 'dfuture', title: 'GraspNet row eval', age: '31 min' }],
      expMetric: 'Stage-3 pick success, Wilson lower bound (higher is better)',
      exps: E([['g01', null, 'kept', 0.42, 'Baseline: GraspNet-row heatmap model on stage 3', 'Stage 3'], ['g02', 'g01', 'kept', 0.51, 'Add the depth channel to the heatmap input', 'Stage 3'],
        ['g03', 'g01', 'discarded', 0.40, 'Bigger backbone (ResNet-34 → 50)', 'Stage 3'], ['g04', 'g02', 'failed', null, 'Domain-randomise lighting ×4 (evaluator OOM)', 'Stage 3'],
        ['g05', 'g02', 'kept', 0.58, 'Approach-angle head instead of top-down only', 'Stage 3'], ['g06', 'g05', 'discarded', 0.55, 'Mix stage-2 replays into the curriculum', 'Stage 3'],
        ['g07', 'g05', 'kept', 0.66, 'Reject grasps with < 3 mm finger clearance', 'Stage 3'], ['g08', 'g07', 'discarded', 0.61, 'Bandit exploration ε = 0.2', 'Stage 3'],
        ['g09', 'g07', 'kept', 0.69, 'Wall-mask-aware sampling', 'Stage 3'], ['g10', 'g09', 'failed', null, 'Pretrain on GraspClutter6D (string ids broke the loader)', 'Stage 4'],
        ['g11', 'g09', 'kept', 0.71, 'Per-class success-rate calibration', 'Stage 3'], ['g12', 'g11', 'discarded', 0.70, 'Test-time augmentation, 4 rotations', 'Stage 3'],
        ['g13', 'g11', 'running', null, 'Two-stage: coarse heatmap → local refine', 'Stage 3']], 'personal'),
      audits: [{ r: 5, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 34, findings: [['Wilson bound rounded inward, not outward', false], ['Gallery re-implements the bench verdict', false]] },
        { r: 6, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 29, findings: [['Provenance-gap row counted as a record', false]] }, { r: 7, model: 'GPT-6.1 Sol · xhigh', verdict: 'PASS', mins: 31, findings: [] }],
      auditDir: '~/bam_ws/reports/media/audits/2026-10-05-grasp-bench',
      evalCmd: 'uv run grasp-bench gallery --frozen', file: '~/bam_ws/tracks/grasping.md' },
    detection: { project: 'bam', title: 'Object Detection', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Overhead mAP@50 · 288 real scans', [0.41, 0.44, 0.49, 0.52, 0.55, 0.55, 0.58, 0.6, 0.61, 0.62], 0.75, 'up', '', 2),
        K('Recall on small items', [0.22, 0.25, 0.27, 0.33, 0.35, 0.36, 0.40, 0.41, 0.43, 0.44], 0.7, 'up', '', 2),
        K('False positives per scan', [3.4, 3.1, 2.9, 2.6, 2.6, 2.3, 2.1, 2.0, 1.9, 1.8], 0.5, 'down', '', 1)],
      gates: [G('No class with recall < 0.3', true, '0 classes'), G('Scan split frozen', true, '2d81f0b')],
      sentence: 'FiftyOne object DB · GC6D + GraspNet scans', asOf: '1 h ago', ruler: { frozen: true, hash: 'scan split · 2d81f0b' },
      sessions: [{ acct: 'ambience', title: 'Object DB · FiftyOne spike', age: '22 min' }], audits: [],
      evalCmd: 'uv run detect eval --split frozen', file: '~/bam_ws/tracks/detection.md' },
    hyperspectral: { project: 'bam', title: 'Hyperspectral', shape: 'ladder', state: 'stalled', mode: 'optimize',
      kpis: [K('Rungs proven (H0–H9)', [0, 1, 1, 1, 1, 1, 1, 1, 1, 1], null, 'up', 'rungs', null, { of: 10 }),
        K('SpectralWaste configs reproduced', [0, 0, 1, 2, 2, 2, 2, 2, 2, 2], 12, 'up', '', 0),
        K('RGB mIoU vs paper 58.2', [51.0, 54.2, 56.9, 58.0, 58.0, 58.0, 58.0, 58.0, 58.0, 58.0], 58.2, 'up', '', 1)],
      gates: [G('Data drive mounted', false, 'not mounted since Oct 3'), G('RGB baseline still reproduces', true, '58.0 vs 58.2')],
      sentence: 'H1 SpectralWaste repro · 2 of 12 configs', stall: 'No KPI movement in 3 days and no live agent · gate failing: data drive not mounted',
      asOf: '3 d ago', ruler: { frozen: true, hash: 'paper mIoU 58.2 · split e19a' },
      rung: { current: 'H1 · Reproduce SpectralWaste HSI (2 / 12 configs)', next: 'H2 · Mock hyperspectral sensor', banked: ['H0 · Plumbing: loader + metrics'] },
      sessions: [], audits: [], evalCmd: 'uv run hsi eval --paper-split', file: '~/bam_ws/tracks/hyperspectral.md' },
    mag: { project: 'ctv', title: 'Multi-account GUI', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Avg pixel error vs reference', [14.2, 12.9, 11.0, 9.8, 8.1, 7.7, 6.0, 5.2, 4.4, 3.8], 1.0, 'down', 'px', 1),
        K('Worst region error', [61, 58, 52, 47, 40, 41, 33, 30, 27, 24], 8, 'down', 'px', 0),
        K('Cases under 1 px', [0, 0, 1, 1, 2, 2, 3, 4, 5, 6], 21, 'up', '', 0),
        K('Session open time', [2.9, 2.7, 2.6, 2.1, 1.9, 1.8, 1.6, 1.5, 1.4, 1.3], 1, 'down', 's', 1)],
      gates: [G('Every masked region has a reason', false, '8 / 9 reasoned'), G('cases.json unchanged', true, '3f2a9e1')],
      sentence: 'Round 6 · sidebar and message list match', asOf: '9 min ago', ruler: { frozen: true, hash: 'cases.json · 3f2a9e1 · 9 masked regions' },
      sessions: [{ acct: 'bam', title: 'Multi-account agent management interface', age: '2 min' }, { acct: 'personal', title: 'Pixel-error loop r6', age: '7 min' }],
      expMetric: 'Avg pixel error vs the reference app (px, lower is better)',
      exps: E([['m01', null, 'kept', 14.2, 'Baseline: screenshot diff vs the reference app', 'Round 1'], ['m02', 'm01', 'kept', 11.0, 'Copy sidebar spacing tokens from the reference', 'Round 2'],
        ['m03', 'm01', 'discarded', 13.5, 'Swap the font stack to system-ui', 'Round 2'], ['m04', 'm02', 'kept', 8.1, 'Match message-list line height and avatar size', 'Round 3'],
        ['m05', 'm04', 'failed', null, 'Mask the timestamps (rejected: mask without a reason)', 'Round 3'], ['m06', 'm04', 'kept', 6.0, 'Render code blocks with the reference theme', 'Round 4'],
        ['m07', 'm06', 'discarded', 6.4, 'Lazy-load older messages', 'Round 4'], ['m08', 'm06', 'kept', 4.4, 'Scrollbar and header height match', 'Round 5'],
        ['m09', 'm08', 'kept', 3.8, 'Sub-pixel alignment of the composer', 'Round 6'], ['m10', 'm09', 'running', null, 'Match hover states in the session list', 'Round 6']], 'personal'),
      audits: [{ r: 3, model: 'GPT-6.1 Sol · xhigh', verdict: 'PASS', mins: 19, findings: [] },
        { r: 4, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 24, findings: [['Masked region #9 has no reason', true], ['Reference screenshot taken at 125 % zoom', true], ['Pixel metric ignores alpha', false]] }],
      auditDir: '~/claude-transcript-viewer/reports/media/audits/2026-10-06-pixel-loop',
      evalCmd: 'node bin/pixel-error.js --cases cases.json', file: '~/claude-transcript-viewer/tracks/multi-account-gui.md' },
    'pyblocks-m1': { project: 'pyblocks', title: 'Block View · M1 One file, verified', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Runnable goldens', [22, 25, 28, 31, 33, 35, 37, 39, 41, 41], 48, 'up', '', 0, { of: 48 }),
        K('Adversarial goldens', [2, 3, 3, 5, 6, 8, 9, 11, 12, 13], 30, 'up', '', 0, { of: 30 }),
        K('Round-trip edit time', [940, 900, 860, 700, 650, 610, 560, 520, 500, 480], 300, 'down', 'ms', 0)],
      gates: [G('Blocks run on stock CPython', true, 'yes'), G('No golden edited by its own fix', true, '0 touched')],
      sentence: 'Merge window 12 · adversarial goldens next', asOf: '2 h ago', ruler: { frozen: true, hash: 'goldens · 88c1d4e' },
      sessions: [{ acct: 'personal', title: 'pyblocks lanes landing', age: '15 min' }], audits: [],
      evalCmd: 'uv run pyblocks scoreboard', file: '~/pyblocks/tracks/m1.md' },
    'vt-join': { project: 'vt', title: 'Session ↔ track join', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('KPI rows carrying session_id', [0, 0, 0, 2, 4, 6, 9, 12, 15, 18], 100, 'up', '%', 0),
        K('Live sessions resolvable to a track', [0, 0, 5, 9, 14, 20, 26, 31, 36, 41], 95, 'up', '%', 0)],
      gates: [G('No session claims a track without a KPI row', true, '0 orphans')],
      sentence: 'claude-hub resolves session → account → open', asOf: '25 min ago', ruler: { frozen: true, hash: 'join spec · 0e4b771' },
      sessions: [{ acct: 'bam', title: 'Vibe Tracks home proposals', age: 'now' }], audits: [],
      evalCmd: 'uv run vibetracks join-audit', file: '~/vibetracks/tracks/session-join.md' },
    'vt-exp': { project: 'vt', title: 'Experiments view (evo-style)', shape: 'scalar', state: 'ok', mode: 'discover', kpis: [], gates: [],
      proposals: [['KPI', 'Seconds to find the best experiment and why it won', 'lower is better; timed on a frozen task script'], ['KPI', 'Experiments explained without opening a file', '% of nodes whose card states hypothesis + outcome'], ['KPI', 'Frontier freshness', 'minutes since the best score last moved'], ['Gate', 'Every node links to its ledger row', 'pass / fail'], ['Gate', 'Scores come from the evaluator, never the agent', 'pass / fail']],
      sentence: 'Discover: an agent is proposing its KPIs and gates', asOf: '6 min ago', ruler: { frozen: false, moved: 'not set yet' },
      sessions: [{ acct: 'bam', title: 'evo-style dashboard research', age: '6 min' }], audits: [],
      evalCmd: '— (none yet)', file: '~/vibetracks/tracks/experiments-view.md' },
    'vt-dash': { project: 'vt', title: 'Dashboard (Proposal A)', shape: 'scalar', state: 'done', mode: 'optimize',
      kpis: [K('Acceptance journeys passing', [8, 12, 15, 17, 19, 20, 22, 22, 22, 22], 22, 'up', '', 0, { of: 22 })],
      gates: [G('Codex audit passes', true, 'r8 PASS')],
      sentence: 'Done Oct 4 · its gates keep guarding against regression', asOf: '1 d ago', ruler: { frozen: true, hash: 'journeys · 1fcc967' },
      sessions: [], audits: [{ r: 7, model: 'GPT-6.1 Sol · xhigh', verdict: 'FAIL', mins: 26, findings: [['Stale doc keeps a fresh generated_at', false]] }, { r: 8, model: 'GPT-6.1 Sol · xhigh', verdict: 'PASS', mins: 21, findings: [] }],
      auditDir: '~/bam_ws/reports/media/audits/2026-10-04-vibetracks-roadmap',
      evalCmd: 'uv run --no-project --with playwright==1.55.0 docs/roadmap/record_roadmap_widget.py', file: '~/vibetracks/tracks/dashboard.md' },
    'vt-ovk': { project: 'vt', title: 'Obsidian Vibe Kanban', shape: 'scalar', state: 'archived', mode: 'optimize',
      kpis: [K('Boards on stock Bases', [0, 1], 1, 'up', '', 0, { of: 1 })], gates: [], sentence: 'Archived Sep 29 · its cards are plain notes now', asOf: '7 d ago', ruler: { frozen: true, hash: '—' },
      sessions: [], audits: [], evalCmd: '—', file: '~/vibetracks/tracks/obsidian-vibe-kanban.md' },
    bbox: { project: 'bbox', title: 'BBox Studio', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Seconds per label', [31, 29, 27, 24, 22, 20, 18.5, 16.0, 15.1, 14.2], 8, 'down', 's', 1),
        K('Label IoU vs gold', [0.91, 0.92, 0.93, 0.93, 0.94, 0.95, 0.95, 0.96, 0.96, 0.96], 0.95, 'up', '', 2),
        K('Clicks per box', [5.2, 5.0, 4.4, 4.1, 3.8, 3.5, 3.1, 2.9, 2.7, 2.6], 2, 'down', '', 1)],
      gates: [G('Label IoU ≥ 0.95', true, '0.96')],
      sentence: 'Subagent rename to BBox Studio landed', asOf: '50 min ago', ruler: { frozen: false, moved: '2 d ago' },
      sessions: [{ acct: 'bam', title: 'Subagent name change to bbox studio', age: '18 min' }], audits: [],
      evalCmd: 'pnpm bench:label-time', file: '~/bbox-ui/tracks/bbox-studio.md' },
    bbt: { project: 'bbt', title: 'Package status', shape: 'scalar', state: 'ok', mode: 'optimize',
      kpis: [K('Examples rendering', [9, 11, 12, 14, 15, 15, 16, 17, 17, 17], 20, 'up', '', 0, { of: 20 }),
        K('Docs pages with a live example', [4, 5, 5, 7, 8, 9, 9, 10, 10, 10], 14, 'up', '', 0)],
      gates: [G('Wheel builds on 3.11–3.13', true, '3 / 3')],
      sentence: 'Quiet 2 d · inside its 4-day stall rule', asOf: '2 d ago', ruler: { frozen: true, hash: 'examples · 5a0c3f9' },
      sessions: [], audits: [], evalCmd: 'uv run pytest examples/', file: '~/beautiful-bt/tracks/package.md' },
  };
  Object.keys(T).forEach((id) => { const t = T[id]; t.id = id; t.kpi = t.kpis[0] || null; t.series = t.kpi ? t.kpi.series : []; t.exps = t.exps || []; });

  // Stress fixture: 4 synthetic projects × 5 tracks so a variant can be judged at 10 projects.
  const SYN = [
    ['hyper_rgb', ['RGB→HSI upsampler PSNR', 'Band selection', 'Calibration target', 'Dataset ingest', 'Viewer']],
    ['stable_preview_switcher', ['Adoption across apps', 'Rollback time', 'Chip pixel match', 'Dock launcher', 'Lane ports']],
    ['zach_brain', ['Memory budget', 'Link health', 'Daily-log coverage', 'Source imports', 'Codex sync']],
    ['py_dataclass_viewer', ['Value(...) coverage', 'Round-trip edits', 'Preview latency', 'Facility model migration', 'Docs']],
  ];
  const SYN_P = [], SYN_T = {};
  SYN.forEach(([name, titles], pi) => {
    const pid = 'syn' + pi; const tids = [];
    titles.forEach((title, ti) => {
      const id = pid + '-' + ti; tids.push(id);
      const base = 20 + ((pi * 7 + ti * 13) % 50);
      const series = Array.from({ length: 10 }, (_, k) => base + Math.round(k * (1 + ((ti + pi) % 3)) + ((k * 7 + ti) % 4)));
      const state = (pi === 1 && ti === 2) ? 'stalled' : (pi === 2 && ti === 0) ? 'needs' : (ti === 4 ? 'done' : 'ok');
      const kpi = K('Synthetic KPI', series, 100, 'up', '%', 0);
      SYN_T[id] = { id, project: pid, title, shape: 'scalar', state, mode: 'optimize', synthetic: true, kpis: [kpi, K('Second KPI', series.map((v) => 100 - v), 10, 'down', '%', 0)], kpi, series,
        gates: [G('Synthetic gate', true, 'ok')], exps: [], audits: [],
        sentence: 'Synthetic row for the 10-project stress view', stall: 'No KPI movement in 5 days', needs: 'Approve the memory-budget raise',
        asOf: (ti + 1) * 7 + ' min ago', ruler: { frozen: true, hash: 'synthetic' },
        sessions: ti % 2 ? [] : [{ acct: ['bam', 'personal', 'dfuture', 'ambience'][pi], title: title + ' loop', age: ti + 3 + ' min' }], evalCmd: '—', file: '~/' + name + '/tracks/' + ti + '.md' };
    });
    SYN_P.push({ id: pid, name, roots: ['~/' + name], color: '#a3a29f', synthetic: true,
      north: { label: 'Synthetic north star', text: SYN_T[tids[0]].series[9] + '%', series: SYN_T[tids[0]].series, target: 100, note: 'stress fixture' }, tracks: tids });
  });

  const FOLDER_CHOICES = ['~/bam_ws', '~/clank-workbench', '~/viser-3d-viewer', '~/pyblocks', '~/claude-hub', '~/claude-transcript-viewer', '~/beautiful-bt', '~/bbox-ui', '~/hyper_rgb', '~/stable_preview_switcher', '~/vibetracks', '~/zach_brain'];
  const STATE_WORD = { needs: 'Needs you', stalled: 'Stalled', ok: 'On track', done: 'Done', archived: 'Archived' };
  const STATE_RANK = { needs: 0, stalled: 1, ok: 2, done: 3, archived: 4 };
  const SETTABLE = { ok: 1, done: 1, archived: 1 };

  // ------------------------------------------------------------------ state
  // Round 2 (Zach, Oct 6 review): sidebar always shown by default (a setting), four home views, KPI cards/rows,
  // account menu bottom-left, a Review seam. Persisted per viewer (try/catch: storage can be blocked).
  const R2KEY = 'vtp-r2';
  let saved = {}; try { saved = JSON.parse(localStorage.getItem(R2KEY) || '{}') || {}; } catch (e) { saved = {}; }
  const persist = () => { try { localStorage.setItem(R2KEY, JSON.stringify({ homeView: S.settings.rememberView ? S.homeView : null, kpiView: S.kpiView, settings: S.settings })); } catch (e) {} };
  const S = { v: 'r2', page: 'home', id: null, view: 'rows', hl: null, hlMode: 'highlight', collapsed: {}, sideCollapsed: {},
    drawer: false, dlg: null, toast: null, scale: false, pinned: false, group: 'project', sort: 'state', showArchived: false,
    tab: 'overview', exp: null, rungFilter: null,
    settings: Object.assign({ alwaysSidebar: true, rememberView: true, defaultView: 'rows' }, saved.settings || {}),
    homeView: null, kpiView: saved.kpiView || 'cards', acctMenu: false };
  S.homeView = (S.settings.rememberView && saved.homeView) || S.settings.defaultView;
  const HOME_VIEWS = [['rows', 'Rows', 'rows'], ['table', 'Table', 'rows'], ['board', 'Board', 'board'], ['cards', 'Cards', 'board']];
  const hist = { back: [], fwd: [] };
  let root = null, opts = {}, listeners = [], toastTimer = null, dragId = null;

  const projects = () => S.scale ? PROJECTS.concat(SYN_P) : PROJECTS;
  const track = (id) => T[id] || SYN_T[id];
  const proj = (id) => projects().find((p) => p.id === id);
  const projTracks = (p) => p.tracks.map(track).filter(Boolean);
  const activeTracks = (p) => projTracks(p).filter((t) => S.showArchived || t.state !== 'archived');
  const liveTracks = (p) => projTracks(p).filter((t) => t.state !== 'archived' && t.state !== 'done');
  const allTracks = () => projects().flatMap(projTracks);

  // ------------------------------------------------------------------ atoms
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ICONS = {
    chev: '<path d="M4 6l4 4 4-4"/>', home: '<path d="M2.5 7.5L8 3l5.5 4.5V13H10V9.5H6V13H2.5z"/>', plus: '<path d="M8 3v10M3 8h10"/>',
    folder: '<path d="M2 4.5h4l1.5 1.5H14v6.5H2z"/>', lock: '<rect x="3.5" y="7" width="9" height="6" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2"/>',
    unlock: '<rect x="3.5" y="7" width="9" height="6" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 014.8-1"/>', left: '<path d="M10 3L5 8l5 5"/>', right: '<path d="M6 3l5 5-5 5"/>',
    menu: '<path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/>', rows: '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/>', board: '<rect x="2" y="3" width="3.5" height="10" rx=".6"/><rect x="6.3" y="3" width="3.5" height="7" rx=".6"/><rect x="10.6" y="3" width="3.5" height="8.5" rx=".6"/>',
    pin: '<path d="M6 2.5h4l-.6 4 2.1 2H4.5l2.1-2zM8 8.5V14"/>', chat: '<path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/>', x: '<path d="M4 4l8 8M12 4l-8 8"/>',
    gear: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M3.6 12.4L5 11M11 5l1.4-1.4"/>', users: '<circle cx="6" cy="6" r="2.3"/><path d="M2 13c.5-2.3 2-3.4 4-3.4s3.5 1.1 4 3.4M10.5 3.8a2.2 2.2 0 010 4.3M12 9.8c1.2.5 1.8 1.6 2 3.2"/>', kbd: '<rect x="1.8" y="4" width="12.4" height="8" rx="1.2"/><path d="M4.5 6.5h1M7.5 6.5h1M10.5 6.5h1M5 9.5h6"/>', help: '<circle cx="8" cy="8" r="6"/><path d="M6.3 6.3a1.8 1.8 0 113 1.4c-.6.4-1.3.8-1.3 1.7M8 11.4v.1"/>',
    judge: '<path d="M8 2.5v11M4 13.5h8M3 5h10M3 5l-1.5 4h3zM13 5l-1.5 4h3z"/>', check: '<path d="M3.5 8.5l3 3 6-7"/>',
  };
  const icon = (n) => `<svg class="i" viewBox="0 0 16 16" aria-hidden="true">${ICONS[n] || ''}</svg>`;
  const dot = (cls) => `<span class="dot ${cls || ''}"></span>`;
  const stWord = (t) => `<span class="st st-${t.state}">${dot(t.state)}${STATE_WORD[t.state]}</span>`;
  const modeTag = (t) => t.mode === 'discover' ? `<span class="mtag" title="Discover: the agent proposes or refines this track's KPIs and gates">discover</span>` : '';

  const fmtK = (k, v) => { if (v == null) v = k.now; return k.dec != null ? Number(v).toLocaleString('en-US', { minimumFractionDigits: k.dec, maximumFractionDigits: k.dec }) : String(v); };
  const unitK = (k) => (k.unit ? (k.unit === '%' || k.unit === '°' ? k.unit : ' ' + k.unit) : '');
  function kNow(k) { if (k.of != null) return `${k.now} / ${k.of}${k.unit ? ' ' + k.unit : ''}`; return fmtK(k) + unitK(k); }
  function kTarget(k) { if (k.target == null) return k.of != null ? `${k.of - k.now} ${k.unit || ''} to go` : ''; return (k.dir === 'down' ? 'target ≤ ' : 'target ') + fmtK(k, k.target) + unitK(k); }
  const kpiNow = (t) => (t.kpi ? kNow(t.kpi) : 'no KPIs yet');
  const kpiTarget = (t) => (t.kpi ? kTarget(t.kpi) : `agent proposing ${(t.proposals || []).length}`);
  function rulerTag(t, long) {
    if (t.ruler && t.ruler.frozen === false) return `<span class="ruler moved" title="Ruler ${esc(t.ruler.moved)}: values before and after are not comparable">${icon('unlock')}ruler ${t.ruler.moved === 'not set yet' ? 'not set yet' : 'moved ' + esc(t.ruler.moved)}</span>`;
    return `<span class="ruler" title="Ruler frozen: ${esc(t.ruler && t.ruler.hash)}">${icon('lock')}${long ? esc(t.ruler.hash) : 'frozen'}</span>`;
  }
  const lastAudit = (t) => (t.audits && t.audits.length ? t.audits[t.audits.length - 1] : null);
  const openCount = (t) => { const a = lastAudit(t); return a ? a.findings.filter((f) => f[1]).length : 0; };
  // Audit badge: last round + its open findings. Colour only when it failed or something is open.
  function auditBadge(t) {
    const a = lastAudit(t); if (!a) return '';
    const open = openCount(t); const bad = a.verdict === 'FAIL' || open;
    return `<button class="abadge ${bad ? 'bad' : ''}" data-act="tab" data-id="auditor" data-track="${t.id}" title="Last audit round ${a.r}: ${esc(a.verdict)} by ${esc(a.model)} · ${open} open">${icon('judge')}r${a.r} ${a.verdict === 'PASS WITH FIXES' ? 'pass·fix' : a.verdict.toLowerCase()}${open ? ` · ${open} open` : ''}</button>`;
  }
  function kpiCell(t, o) {
    o = o || {};
    if (!t.kpi) return `<span class="kpi"><b class="faint" style="font-weight:500">no KPIs yet</b><small>${esc(kpiTarget(t))} · ${esc(t.asOf)}</small></span>`;
    const more = t.kpis.length > 1 ? ` · +${t.kpis.length - 1} KPIs` : '';
    return `<span class="kpi"><b>${esc(kpiNow(t))}</b><small>${esc(o.short ? t.asOf : kpiTarget(t) + more + ' · ' + t.asOf)}${o.noRuler ? '' : ' · ' + rulerTag(t)}</small></span>`;
  }
  function spark(series, o) {
    o = o || {}; const w = o.w || 96, h = o.h || 26, pad = 3;
    if (!series || series.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
    const vals = series.slice(); if (o.target != null) vals.push(o.target);
    let min = Math.min(...vals), max = Math.max(...vals); if (max === min) { max += 1; min -= 1; }
    const x = (i) => pad + (i * (w - 2 * pad)) / (series.length - 1), y = (v) => h - pad - ((v - min) * (h - 2 * pad)) / (max - min);
    let d = '';
    series.forEach((v, i) => { if (o.step && i) d += `L${x(i).toFixed(1)},${y(series[i - 1]).toFixed(1)}`; d += (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    const last = series.length - 1;
    const tgt = o.target != null ? `<line x1="${pad}" x2="${w - pad}" y1="${y(o.target).toFixed(1)}" y2="${y(o.target).toFixed(1)}" stroke="#d8d7d4" stroke-dasharray="3 3" stroke-width="1" vector-effect="non-scaling-stroke"/>` : '';
    if (o.fluid) return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" aria-hidden="true">${tgt}<path d="${d}" fill="none" stroke="#9b9a97" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${tgt}<path d="${d}" fill="none" stroke="#9b9a97" stroke-width="1.4" stroke-linejoin="round"/><circle cx="${x(last)}" cy="${y(series[last])}" r="2.4" fill="#37352f"/></svg>`;
  }
  const kSpark = (k, ladderish, o) => spark(k.series, Object.assign({ step: ladderish, target: k.target != null ? k.target : null }, o || {}));
  const trackSpark = (t, o) => (t.kpi ? kSpark(t.kpi, t.shape === 'ladder', o) : `<span class="faint" style="font-size:12px">discovering KPIs</span>`);
  function ladder(t, big) {
    const k = t.kpi; let s = '';
    // WHY a bar past 24 rungs: kinsim's 62 rungs wrapped into four rows of glyphs in a 112 px cell.
    if (!big && k.of > 24) return `<span class="lbar" title="${k.now} of ${k.of} rungs proven"><i style="width:${(100 * k.now / k.of).toFixed(1)}%"></i></span>`;
    for (let i = 0; i < k.of; i++) s += `<i class="${i < k.now ? 'p' : i === k.now ? 'c' : ''}"></i>`;
    return `<span class="ladder ${big ? 'big' : ''}" title="${k.now} of ${k.of} rungs proven">${s}</span>`;
  }
  function sessChips(t, max) {
    if (!t.sessions.length) return `<span class="faint" style="font-size:12px">no agent</span>`;
    max = max || 2; const shown = t.sessions.slice(0, max);
    return `<span class="sesslist">${shown.map((s, i) => `<button class="sess" data-act="session" data-id="${t.id}" data-i="${i}" title="Open “${esc(s.title)}” (${esc(s.acct)}) in Claude Hub">${dot('live')}<span class="acct">${esc(s.acct)}</span><span class="ell">${esc(s.title)}</span></button>`).join('')}${t.sessions.length > max ? `<span class="faint" style="font-size:12px">+${t.sessions.length - max}</span>` : ''}</span>`;
  }
  const liveCount = (p) => liveTracks(p).reduce((n, t) => n + t.sessions.length, 0);
  function rollup(p) {
    const ts = projTracks(p); const c = { needs: 0, stalled: 0, ok: 0, done: 0, archived: 0 }; ts.forEach((t) => c[t.state]++);
    const disc = ts.filter((t) => t.mode === 'discover').length; const bits = [];
    if (c.needs) bits.push(`<span class="st-needs">${dot('needs')}${c.needs} needs you</span>`);
    if (c.stalled) bits.push(`<span class="st-stalled">${dot('stalled')}${c.stalled} stalled</span>`);
    if (c.ok) bits.push(`<span>${dot()}${c.ok} on track${disc ? ` (${disc} discovering)` : ''}</span>`);
    if (c.done) bits.push(`<span>${dot('done')}${c.done} done</span>`);
    if (c.archived) bits.push(`<span class="faint">${c.archived} archived</span>`);
    if (!ts.length) bits.push('<span>no tracks yet</span>');
    return `<span class="roll">${bits.join('')}</span>`;
  }
  function summarySentence() {
    const ts = allTracks(); const n = (s) => ts.filter((t) => t.state === s).length; const live = ts.filter((t) => t.state !== 'archived').reduce((a, t) => a + t.sessions.length, 0);
    const parts = [`${ts.filter((t) => t.state !== 'archived' && t.state !== 'done').length} active tracks in ${projects().length} projects`];
    parts.push(n('needs') ? `<span class="st-needs">${n('needs')} needs you</span>` : 'nothing needs you');
    if (n('stalled')) parts.push(`<span class="st-stalled">${n('stalled')} stalled</span>`);
    parts.push(`${live} agents live`);
    return parts.join(' · ');
  }
  const dimCls = (pid) => (S.hl && S.hlMode === 'highlight' && S.hl !== pid ? 'dim' : '');
  const hidden = (pid) => S.hl && S.hlMode === 'filter' && S.hl !== pid;
  const pmark = (p) => `<span class="pmark" style="background:${p.color}"></span>`;

  // ------------------------------------------------------------------ shared pieces
  function toolbar(o) {
    o = o || {};
    const chips = projects().map((p) => `<button class="chip ${S.hl === p.id ? 'on' : ''}" data-act="hl" data-id="${p.id}">${pmark(p)}<span class="ell">${esc(p.name)}</span></button>`).join('');
    const nArch = allTracks().filter((t) => t.state === 'archived').length;
    return `<div class="bar">
      <span class="seg" role="group" aria-label="Home view"><button class="${S.view === 'rows' ? 'on' : ''}" data-act="view" data-id="rows">${icon('rows')} Rows</button><button class="${S.view === 'board' ? 'on' : ''}" data-act="view" data-id="board">${icon('board')} Board</button></span>
      ${o.extra || ''}
      ${S.view === 'rows' ? `<button class="chip ${S.showArchived ? 'on' : ''}" data-act="archived">${S.showArchived ? 'Hide' : 'Show'} archived (${nArch})</button>` : '<span class="lbl">Drag a card to Done or Archived</span>'}
      <span class="spacer"></span>
      <button class="btn" data-act="scale" title="Swap in a 10-project stress fixture (4 synthetic projects)">${S.scale ? '✓ ' : ''}10-project fixture</button>
      <button class="btn primary" data-act="new">${icon('plus')} New project</button>
    </div>
    <div class="bar"><span class="lbl">${o.hlLabel || 'Highlight project'}</span>
      <select class="show-n" id="vtp-hl" aria-label="Highlight project"><option value="">All projects</option>${projects().map((p) => `<option value="${p.id}" ${S.hl === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
      <span class="hide-n" style="display:contents"><button class="chip ${!S.hl ? 'on' : ''}" data-act="hl" data-id="">All</button>${chips}</span>
      <span class="seg" style="margin-left:4px"><button class="${S.hlMode === 'highlight' ? 'on' : ''}" data-act="hlmode" data-id="highlight">Highlight</button><button class="${S.hlMode === 'filter' ? 'on' : ''}" data-act="hlmode" data-id="filter">Filter</button></span>
    </div>`;
  }

  function trackSub(t) {
    return t.state === 'needs' ? `<span class="tsub st-needs" style="font-weight:500">${esc(t.needs)}</span>`
      : t.state === 'stalled' ? `<span class="tsub st-stalled">${esc(t.stall)}</span>` : `<span class="tsub">${esc(t.sentence)}</span>`;
  }
  function trackRow(t, o) {
    o = o || {};
    return `<div class="trow ${dimCls(t.project)} ${t.state === 'archived' || t.state === 'done' ? 'quiet' : ''}" data-act="track" data-id="${t.id}" role="link" tabindex="0">
      <span class="c-chev"></span>
      <span class="c-name"><span class="tname">${esc(t.title)} ${modeTag(t)}${t.synthetic ? ' <span class="synthetic">synthetic</span>' : ''}</span>${trackSub(t)}</span>
      <span class="c-state">${stWord(t)}${auditBadge(t)}</span>
      <span class="c-kpi">${kpiCell(t)}</span>
      <span class="c-spark">${t.kpi && t.shape === 'ladder' && o.ladder ? ladder(t) : trackSpark(t)}</span>
      <span class="c-sess">${o.noSess ? '' : sessChips(t)}</span>
    </div>`;
  }

  function projectHeaderRow(p) {
    const closed = !!S.collapsed[p.id];
    return `<div class="prow ${dimCls(p.id)}">
      <button class="chev ${closed ? 'closed' : ''}" data-act="toggle" data-id="${p.id}" aria-label="${closed ? 'Expand' : 'Collapse'} ${esc(p.name)}" aria-expanded="${!closed}">${icon('chev')}</button>
      <span class="p-name" style="min-width:0"><button class="pname" data-act="project" data-id="${p.id}">${esc(p.name)} <small class="faint" style="font-weight:400">${p.roots.length} folder${p.roots.length > 1 ? 's' : ''}</small></button><br>${rollup(p)}</span>
      <span class="north">${p.north ? `<small>North star · lagging · ${esc(p.north.label)}</small><b>${esc(p.north.text)}</b>` : '<small>No north star yet</small>'}</span>
      <span class="pspark">${p.north ? spark(p.north.series, { w: 110, h: 30, target: p.north.target }) : ''}</span>
      <span class="plive grey" style="font-size:12.5px">${liveCount(p) ? `${dot('live')} ${liveCount(p)} agent${liveCount(p) > 1 ? 's' : ''} live` : '<span class="faint">no agent live</span>'}</span>
    </div>`;
  }

  // Board: a column with `drop` accepts dragged cards (On track / Done / Archived, or a mode); computed columns
  // (Needs you, Stalled) refuse with a reason. A drop writes vibe-status / vibe-mode to the track file (simulated).
  function kanban(columns) {
    return `<div class="board">${columns.map((c) => { const ts = c.tracks.filter((t) => !hidden(t.project));
      return `<div class="col ${c.drop ? 'droppable' : ''} ${c.quiet ? 'qcol' : ''}" data-drop="${c.drop || ''}" data-dropmode="${c.dropMode || ''}" data-refuse="${esc(c.refuse || '')}"><div class="colh">${c.head}<span class="n">${ts.length}</span></div>${c.sub ? `<div class="colsub">${c.sub}</div>` : ''}
      ${ts.map((t) => card(t, c)).join('') || `<div class="faint empty">${c.drop ? 'Drop a card here' : 'Nothing here'}</div>`}</div>`; }).join('')}</div>`;
  }
  function card(t, c) {
    const p = proj(t.project); const hl = S.hl && S.hlMode === 'highlight' && S.hl === t.project;
    return `<div class="card ${dimCls(t.project)} ${hl ? 'hl' : ''} ${t.state === 'archived' ? 'quiet' : ''}" data-act="track" data-id="${t.id}" role="link" tabindex="0" draggable="true" style="cursor:pointer">
      <span class="cp">${pmark(p)}${esc(p.name)} ${modeTag(t)}</span>
      <span class="ct">${esc(t.title)}</span>
      ${t.state === 'needs' ? `<small class="st-needs" style="font-weight:500">${esc(t.needs)}</small>` : t.state === 'stalled' ? `<small class="st-stalled">${esc(t.stall)}</small>` : ''}
      <span class="cm"><span class="kpi"><b>${esc(kpiNow(t))}</b><small>${t.kpi ? esc(t.kpi.label) + (t.kpis.length > 1 ? ` · +${t.kpis.length - 1}` : '') : 'agent proposing KPIs'}</small></span>${trackSpark(t, { w: 80, h: 24 })}</span>
      <span class="cf">${c && c.hideState ? '' : stWord(t)}${auditBadge(t)}<span>${t.sessions.length ? dot('live') + ' ' + t.sessions.length + ' live' : 'no agent'} · ${esc(t.asOf)}</span></span>
    </div>`;
  }

  // Sidebar: the Claude Code desktop / Codex project tree.
  function sidebar(o) {
    o = o || {};
    const cur = S.page === 'track' ? track(S.id) : null; const curP = S.page === 'project' ? S.id : cur ? cur.project : null;
    const navs = `<button class="nav ${S.page === 'home' && S.view === 'rows' ? 'on' : ''}" data-act="home">${icon('home')} ${o.nav ? 'Home' : 'All tracks'}</button>
      ${o.nav ? `<button class="nav ${S.page === 'home' && S.view === 'board' ? 'on' : ''}" data-act="boardnav">${icon('board')} Board</button>` : ''}
      <button class="nav" data-act="new">${icon('plus')} New project</button>`;
    const tree = projects().map((p) => {
      const closed = S.sideCollapsed[p.id] != null ? S.sideCollapsed[p.id] : (!!p.synthetic && p.id !== curP);
      const lt = liveTracks(p);
      const pm = o.rail ? `<span class="mono" style="background:${p.color}">${esc(p.name.replace(/[^A-Za-z]/g, '').slice(0, 2).toUpperCase())}${lt.some((t) => t.state === 'needs') ? '<span class="md" style="background:var(--warn-dot)"></span>' : lt.some((t) => t.state === 'stalled') ? '<span class="md" style="background:var(--stale-dot)"></span>' : ''}</span>` : '';
      let h = `<div class="sp ${curP === p.id ? 'on' : ''}">${o.rail ? pm : `<button class="chev ${closed ? 'closed' : ''}" data-act="side-toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button>`}
        <button class="spn" data-act="project" data-id="${p.id}">${esc(p.name)}</button>${o.north && p.north ? `<span class="nspark">${spark(p.north.series, { w: 44, h: 16 })}</span>` : ''}
        ${o.rail ? `<button class="chev ${closed ? 'closed' : ''}" data-act="side-toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button>` : ''}</div>`;
      if (o.north && p.north && !closed) h += `<span class="ns">${esc(p.north.label)} · <b style="color:var(--grey)">${esc(p.north.text)}</b></span>`;
      if (!closed) {
        lt.forEach((t) => {
          h += `<button class="stk ${cur && cur.id === t.id ? 'on' : ''}" data-act="track" data-id="${t.id}" title="${esc(STATE_WORD[t.state])} · ${esc(kpiNow(t))}">${dot(t.state)}<span class="stn">${esc(t.title)}</span>${t.mode === 'discover' ? '<span class="cnt">disc</span>' : ''}${t.sessions.length && !o.sessions ? `<span class="cnt">${dot('live')}${t.sessions.length}</span>` : ''}</button>`;
          if (o.sessions) t.sessions.forEach((s, i) => { h += `<button class="ss" data-act="session" data-id="${t.id}" data-i="${i}">${icon('chat')}<span class="stn">${esc(s.title)}</span><span class="faint" style="font-size:11px">${esc(s.acct)}</span></button>`; });
        });
        projTracks(p).filter((t) => t.state === 'done' || t.state === 'archived').forEach((t) => { h += `<button class="stk quiet ${cur && cur.id === t.id ? 'on' : ''}" data-act="track" data-id="${t.id}">${dot(t.state)}<span class="stn">${esc(t.title)}</span><span class="cnt">${t.state}</span></button>`; });
      }
      return h;
    }).join('');
    const body = `${navs}<div class="sh"><span>Projects</span>${o.rail ? `<button data-act="pin" title="${S.pinned ? 'Unpin' : 'Pin'} the panel open" class="chev">${icon('pin')}</button>` : ''}</div>${tree}`;
    if (o.rail) return `<div class="railwrap ${S.pinned ? 'pinned' : ''}"><aside class="side rail ${S.pinned ? 'pinned' : ''}" aria-label="Projects and tracks">${body}</aside></div>`;
    return `<aside class="side" aria-label="Projects and tracks">${body}</aside>`;
  }

  function crumb(parts) {
    return `<div class="crumb"><button class="burger" data-act="burger" aria-label="Projects">${icon('menu')}</button>
      <button class="navbtn" data-act="back" title="Back" ${hist.back.length ? '' : 'disabled style="opacity:.35"'}>${icon('left')}</button>
      <button class="navbtn" data-act="fwd" title="Forward" ${hist.fwd.length ? '' : 'disabled style="opacity:.35"'}>${icon('right')}</button>
      ${parts.map((p, i) => i === parts.length - 1 ? `<span style="color:var(--fg)">${esc(p.label)}</span>` : `<button data-act="${p.act}" data-id="${p.id || ''}">${esc(p.label)}</button><span>/</span>`).join('')}</div>`;
  }

  function sessionsList(ts, o) {
    o = o || {}; const rows = [];
    ts.forEach((t) => t.sessions.forEach((s, i) => rows.push(`<button class="ls" data-act="session" data-id="${t.id}" data-i="${i}">${dot('live')}<span style="flex:1;min-width:0"><span style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.title)}</span><small class="faint">${esc(s.acct)} · ${o.withTrack ? esc(t.title) + ' · ' : ''}wrote a KPI row ${esc(s.age)} ago</small></span>${icon('chat')}</button>`)));
    return rows.join('') || `<p class="faint" style="margin:4px 0">No agent is working ${o.withTrack ? 'in this project' : 'this track'} right now.</p>`;
  }

  // ------------------------------------------------------------------ project page: north star (lagging) above the tracks' KPIs (leading)
  function leadLag(p) {
    const ts = liveTracks(p).filter((t) => t.kpi); if (!p.north) return '';
    const W = 900, L = 230, nH = 96, rH = 46, H = nH + 18 + ts.length * rH + 18, n = p.north.series.length;
    const x = (i) => L + (i * (W - L - 12)) / (n - 1);
    const steps = []; p.north.series.forEach((v, i) => { if (i && v > p.north.series[i - 1]) steps.push(i); });
    const nmin = Math.min(...p.north.series, 0), nmax = Math.max(...p.north.series, p.north.target);
    const ny = (v) => 10 + (nH - 20) * (1 - (v - nmin) / (nmax - nmin || 1));
    let d = ''; p.north.series.forEach((v, i) => { if (i) d += `L${x(i)},${ny(p.north.series[i - 1])}`; d += (i ? 'L' : 'M') + x(i) + ',' + ny(v); });
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="North star over the tracks' leading KPIs" style="display:block">`;
    steps.forEach((i) => { s += `<line x1="${x(i)}" x2="${x(i)}" y1="6" y2="${H - 14}" stroke="#ededec" stroke-width="1"/>`; });
    s += `<text x="0" y="22" font-size="12.5" fill="#37352f" font-weight="600">North star · lagging</text><text x="0" y="40" font-size="12" fill="#9b9a97">${esc(p.north.label)}</text><text x="0" y="64" font-size="20" font-weight="700" fill="#37352f">${esc(p.north.text)}</text>`;
    s += `<line x1="${L}" x2="${W - 12}" y1="${ny(p.north.target)}" y2="${ny(p.north.target)}" stroke="#d8d7d4" stroke-dasharray="3 3"/><path d="${d}" fill="none" stroke="#37352f" stroke-width="2"/>`;
    s += `<text x="0" y="${nH + 14}" font-size="11.5" fill="#9b9a97">Track KPIs · leading (each scaled to its own range)</text>`;
    ts.forEach((t, r) => {
      // WHY each line on its own range: the question here is WHEN a track moved relative to the north star, not how far it is from target (that is on the track row).
      const y0 = nH + 18 + r * rH; const raw = t.kpi.series; const lo = Math.min(...raw), hi = Math.max(...raw); const pr = raw.map((v) => (hi === lo ? 0.5 : (t.kpi.dir === 'down' ? hi - v : v - lo) / (hi - lo)));
      let pd = ''; pr.forEach((v, i) => { pd += (i ? 'L' : 'M') + x(i) + ',' + (y0 + rH - 8 - v * (rH - 12)).toFixed(1); });
      s += `<text x="0" y="${y0 + rH / 2 + 4}" font-size="12" fill="${t.state === 'needs' ? '#b35c00' : t.state === 'stalled' ? '#5f7a94' : '#787774'}">${esc(t.title.length > 30 ? t.title.slice(0, 29) + '…' : t.title)}</text><path d="${pd}" fill="none" stroke="#9b9a97" stroke-width="1.4"/>`;
    });
    s += `<text x="${L}" y="${H - 2}" font-size="11" fill="#9b9a97">Sep 27</text><text x="${W - 12}" y="${H - 2}" font-size="11" fill="#9b9a97" text-anchor="end">today</text></svg>`;
    return `<div class="bigchart"><div class="tscroll"><div style="min-width:640px">${s}</div></div><div class="faint" style="font-size:12.5px;margin-top:4px">Grey verticals mark each north-star step. In this fixture the track KPIs climb 1–2 days before each step: leading indicators you optimise directly, rolling up to the lagging north star.</div></div>`;
  }
  function projectPage(p, o) {
    o = o || {}; const ts = activeTracks(p);
    const attn = ts.filter((t) => t.state === 'needs' || t.state === 'stalled');
    const north = p.north ? leadLag(p) : `<div class="bigchart faint">No north star yet: pick the lagging metric these tracks should move.</div>`;
    const attnHtml = attn.map((t) => `<div class="callout ${t.state}">${dot(t.state)}<div class="cb"><b>${esc(t.title)}</b> · <span class="st-${t.state}">${t.state === 'needs' ? esc(t.needs) : esc(t.stall)}</span></div><button class="btn" data-act="track" data-id="${t.id}">Open</button></div>`).join('');
    const tracksHtml = o.aligned ? `<div class="arows">${ts.map(aRowsTrack).join('')}</div>` : o.table ? denseTable(ts, { group: false }) : `<div class="rows">${ts.map((t) => trackRow(t, { ladder: o.ladders })).join('') || '<p class="faint">No tracks yet: add a track file in one of this project\'s folders, or run /vibetracks-discover.</p>'}</div>`;
    const folders = `<div class="folders">${p.roots.map((r) => `<span class="folder">${icon('folder')}${esc(r)}</span>`).join('')}</div>
      <pre class="file"># ${esc(p.roots[0])}/Project.vibetrack\nvibetracks:\n  ${p.custom ? 'name: ' + esc(p.name) : '# name defaults to the folder: ' + esc(p.name)}\n  roots: [${p.roots.map(esc).join(', ')}]\n  north_star: ${p.north ? esc(p.north.label) : '~'}</pre>`;
    const sess = sessionsList(liveTracks(p), { withTrack: true });
    const head = `${crumb([{ act: 'home', label: 'Home' }, { label: p.name }])}
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><h1>${esc(p.name)}</h1><button class="btn" data-act="edit" data-id="${p.id}">Edit project</button></div>
      <p class="sub">${p.roots.length} folder${p.roots.length > 1 ? 's' : ''} · ${liveTracks(p).length} active tracks · ${liveCount(p)} agents live · ${rollup(p)}</p>${attnHtml}`;
    if (o.order === 'sessions') return head + `<h2>Live now</h2>${sess}<h2>North star ← tracks</h2>${north}<h2>Tracks</h2>${tracksHtml}<h2>Folders</h2>${folders}`;
    return head + `${north}<h2>Tracks</h2>${tracksHtml}<div class="grid2"><div><h2>Live now</h2>${sess}</div><div><h2>Folders</h2>${folders}</div></div>`;
  }

  // ------------------------------------------------------------------ track page pieces
  // WHY a fixed table layout: Zach's rule from the Oct 6 review — columns (and so sparklines) never drift row to row.
  function kpiRows(t) {
    return `<div class="tscroll"><table class="t kpit"><colgroup><col><col style="width:150px"><col style="width:150px"><col style="width:140px"><col style="width:110px"></colgroup>
      <thead><tr><th>Soft KPI</th><th>Now</th><th>Target</th><th>Trend</th><th>Δ since Sep 27</th></tr></thead><tbody>${t.kpis.map((k, i) => { const d = k.now - k.series[0]; const good = (k.dir === 'down' ? -d : d) > 0;
      return `<tr><td>${esc(k.label)}${i === 0 ? ' <span class="mtag">summary</span>' : ''}</td><td class="num"><b>${esc(kNow(k))}</b></td><td class="grey num">${esc(kTarget(k))}</td><td>${kSpark(k, k.unit === 'rungs', { w: 110, h: 22 })}</td><td class="num ${good ? 'grey' : 'st-needs'}">${d >= 0 ? '+' : ''}${fmtK(k, d)}${unitK(k)}</td></tr>`; }).join('')}</tbody></table></div>`;
  }
  const kpiToggle = () => `<span class="seg kpiseg" title="Toggle with K"><button class="${S.kpiView === 'cards' ? 'on' : ''}" data-act="kpiview" data-id="cards">Cards</button><button class="${S.kpiView === 'rows' ? 'on' : ''}" data-act="kpiview" data-id="rows">Rows</button></span>`;
  function kpiMultiples(t) {
    if (S.kpiView === 'rows') return kpiRows(t);
    return `<div class="multi">${t.kpis.map((k, i) => `<div class="mcell"><div class="mlab">${esc(k.label)}${i === 0 ? ' <span class="mtag">summary · row sparkline</span>' : ''}</div>
      <div class="mval"><b>${esc(kNow(k))}</b> <span class="faint">${esc(kTarget(k))}</span></div>${kSpark(k, k.unit === 'rungs', { w: 220, h: 54, fluid: true })}</div>`).join('')}</div>`;
  }
  function gatesList(t) {
    if (!t.gates.length) return '<p class="faint">No hard gates yet.</p>';
    return `<div class="gates">${t.gates.map((g) => `<div class="gate ${g.pass ? '' : 'fail'}"><span class="gp">${g.pass ? icon('check') + 'pass' : icon('x') + 'fail'}</span><span style="flex:1">${esc(g.name)}</span><span class="faint">${esc(g.now)}</span></div>`).join('')}</div>`;
  }
  function discoverPanel(t) {
    return `<div class="bigchart"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>Proposed by the agent</b><span class="faint" style="font-size:12.5px">Discover mode: accept the KPIs and gates you agree with; Optimize runs the loop against accepted ones only.</span></div>
      ${(t.proposals || []).map((pr, i) => `<div class="prop"><span class="mtag">${esc(pr[0])}</span><span style="flex:1;min-width:0"><b style="font-weight:500">${esc(pr[1])}</b><br><small class="faint">${esc(pr[2])}</small></span>
        ${pr.done ? `<span class="faint">${pr.done === 'yes' ? 'accepted' : 'rejected'}</span>` : `<button class="btn" data-act="prop" data-id="${t.id}" data-i="${i}" data-v="yes">Accept</button><button class="btn" data-act="prop" data-id="${t.id}" data-i="${i}" data-v="no">Reject</button>`}</div>`).join('')}</div>`;
  }
  function roadmapSection(t) {
    const expsFor = (label) => t.exps.filter((e) => e.rung && label.startsWith(e.rung + ' '));
    const link = (label) => { const xs = expsFor(label); return xs.length ? ` <button class="chip" data-act="rung" data-id="${t.id}" data-r="${esc(xs[0].rung)}">${xs.length} experiment${xs.length > 1 ? 's' : ''} →</button>` : ''; };
    if (t.shape === 'ladder') return `<div class="bigchart" style="padding-bottom:4px">${ladder(t, true)}
        <div class="rung"><span class="k">Current rung</span><span><b>${esc(t.rung.current)}</b>${link(t.rung.current)}</span></div>
        <div class="rung"><span class="k">Next</span><span>${esc(t.rung.next)}</span></div>
        <div class="rung" style="border:0"><span class="k">Banked</span><span class="grey">${t.rung.banked.map((b) => esc(b) + link(b)).join('<br>')}</span></div></div>`;
    if (!t.kpi) return '<p class="faint">No roadmap until KPIs are accepted.</p>';
    const rungs = [...new Set(t.exps.map((e) => e.rung))];
    return `<div class="bigchart"><div class="faint" style="font-size:12.5px">Best so far · ${esc(t.kpi.label)}</div><div style="display:flex;align-items:baseline;gap:10px"><span class="bv">${esc(kpiNow(t))}</span><span class="faint">${esc(kpiTarget(t))}</span></div>
      ${spark(bestSoFar(t.kpi), { w: 600, h: 70, step: true, target: t.kpi.target, fluid: true })}
      ${rungs.length ? `<div class="faint" style="font-size:12.5px;margin-top:6px">Milestones → experiments: ${rungs.map((r) => `<button class="chip" data-act="rung" data-id="${t.id}" data-r="${esc(r)}">${esc(r)} · ${t.exps.filter((e) => e.rung === r).length}</button>`).join(' ')}</div>` : ''}</div>`;
  }
  function bestSoFar(k) { const out = []; let b = null; k.series.forEach((v) => { b = b == null ? v : (k.dir === 'down' ? Math.min(b, v) : Math.max(b, v)); out.push(b); }); return out; }

  // Experiments: evo-style frontier. Top row = the kept chain (the frontier); under each kept node its other children.
  function experiments(t) {
    if (!t.exps.length) return `<p class="faint">No experiment ledger yet: this track logs KPI rows only. <code>/vibetracks-loop</code> would start logging one experiment per attempt.</p>`;
    const dirDown = t.kpi && t.kpi.dir === 'down';
    const kept = t.exps.filter((e) => e.status === 'kept');
    const scored = t.exps.filter((e) => e.score != null);
    const best = scored.reduce((b, e) => (b == null || (dirDown ? e.score < b.score : e.score > b.score) ? e : b), null);
    const c = (s) => t.exps.filter((e) => e.status === s).length;
    const sel = t.exps.find((e) => e.id === S.exp) || best;
    const fs = (v) => (t.kpi && t.kpi.dec != null ? Number(v).toFixed(t.kpi.dec) : String(v));
    const node = (e) => `<button class="xnode x-${e.status} ${sel && sel.id === e.id ? 'on' : ''} ${S.rungFilter && e.rung !== S.rungFilter ? 'dim' : ''}" data-act="exp" data-id="${e.id}"><span class="xh"><span class="xd"></span>${e.id}<span class="xs">${e.score != null ? fs(e.score) : e.status === 'running' ? 'running' : 'err'}</span></span><span class="xt">${esc(e.hyp)}</span></button>`;
    const cols = kept.map((k) => `<div class="xcol">${node(k)}${t.exps.filter((e) => e.parent === k.id && e.status !== 'kept').map(node).join('')}</div>`).join('');
    const W = 640, H = 150, n = t.exps.length; const vals = scored.map((e) => e.score); let mn = Math.min(...vals), mx = Math.max(...vals); if (mx === mn) mx += 1;
    const X = (i) => 30 + i * (W - 50) / Math.max(1, n - 1), Y = (v) => 12 + (H - 34) * (dirDown ? (v - mn) / (mx - mn) : 1 - (v - mn) / (mx - mn));
    let b = null, path = ''; t.exps.forEach((e, i) => { if (e.status === 'kept' && e.score != null) { if (b == null) path = `M${X(i)},${Y(e.score)}`; else path += `L${X(i)},${Y(b)}L${X(i)},${Y(e.score)}`; b = e.score; } }); path += `L${X(n - 1)},${Y(b)}`;
    const dots = t.exps.map((e, i) => e.score == null ? `<circle cx="${X(i)}" cy="${H - 18}" r="4" fill="#fff" stroke="${e.status === 'running' ? '#2383e2' : '#e03e3e'}" stroke-width="1.5"/>` : `<circle cx="${X(i)}" cy="${Y(e.score)}" r="${e.status === 'kept' ? 4 : 3}" fill="${e.status === 'kept' ? '#37352f' : '#c8c7c4'}"/>`).join('');
    const chart = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block"><path d="${path}" fill="none" stroke="#37352f" stroke-width="1.8"/>${dots}<text x="30" y="${H - 2}" font-size="11" fill="#9b9a97">first experiment</text><text x="${W - 20}" y="${H - 2}" font-size="11" fill="#9b9a97" text-anchor="end">latest</text></svg>`;
    const kids = sel ? t.exps.filter((e) => e.parent === sel.id) : []; const parent = sel && t.exps.find((e) => e.id === sel.parent);
    const detail = sel ? `<aside class="xdetail"><div style="display:flex;align-items:center;gap:8px"><b>${sel.id}</b><span class="xstat x-${sel.status}">${sel.status}</span></div>
      <div class="bv" style="margin:6px 0 0">${sel.score != null ? fs(sel.score) : '—'}</div>${parent && sel.score != null && parent.score != null ? `<small class="faint">${(sel.score - parent.score >= 0 ? '+' : '') + (sel.score - parent.score).toFixed(2)} from ${parent.id}</small>` : ''}
      <div class="xk">Hypothesis</div><div>${esc(sel.hyp)}</div>
      <div class="xk">Roadmap rung</div><div>${esc(sel.rung)}</div>
      <div class="xk">Parent · children</div><div>${parent ? `<button class="chip" data-act="exp" data-id="${parent.id}">${parent.id}</button>` : '<span class="faint">root</span>'} ${kids.map((k) => `<button class="chip" data-act="exp" data-id="${k.id}">${k.id} · ${k.score != null ? fs(k.score) : k.status}</button>`).join(' ')}</div>
      <dl class="meta" style="margin-top:10px"><dt>Model</dt><dd>${esc(sel.model)}</dd><dt>Tokens</dt><dd>${sel.tokens.toLocaleString('en-US')}</dd><dt>Latency</dt><dd>${esc(sel.latency)}</dd><dt>Cost</dt><dd>${esc(sel.cost)}</dd><dt>Session</dt><dd>${esc(sel.author)} · ${esc(sel.created)}</dd></dl></aside>` : '';
    const rungs = [...new Set(t.exps.map((e) => e.rung))];
    return `<div class="xstats"><span><small>Best score</small><b>${best ? fs(best.score) : '—'}</b></span><span><small>Experiments</small><b>${n}</b> <small>${c('kept')} kept · ${c('discarded')} discarded · ${c('failed')} failed</small></span><span><small>Frontier</small><b>${kept.length}</b></span><span><small>Running</small><b>${c('running')}</b></span></div>
      <div class="faint" style="font-size:12.5px;margin:4px 0 8px">Scored on: ${esc(t.expMetric || t.kpi.label)} · by the evaluator, never the agent · rung <button class="chip ${!S.rungFilter ? 'on' : ''}" data-act="rung" data-id="${t.id}" data-r="">all</button> ${rungs.map((r) => `<button class="chip ${S.rungFilter === r ? 'on' : ''}" data-act="rung" data-id="${t.id}" data-r="${esc(r)}">${esc(r)}</button>`).join(' ')}</div>
      <div class="xwrap"><div style="min-width:0"><div class="xtree">${cols}</div><div class="bigchart" style="margin-top:12px"><div class="faint" style="font-size:12.5px">Score over time · <b style="color:var(--fg)">—</b> best so far · ● kept · <span style="color:#b5b4b0">●</span> discarded · <span style="color:#e03e3e">○</span> failed · <span style="color:#2383e2">○</span> running</div>${chart}</div></div>${detail}</div>`;
  }

  function auditor(t) {
    if (!t.audits || !t.audits.length) return `<p class="faint">No audit rounds yet. Audits run only when you ask (<code>/llm-judge</code>); each round lands here with its model, verdict, findings and time to verdict.</p>`;
    const open = openCount(t); const last = lastAudit(t); const mins = t.audits.map((a) => a.mins).sort((a, b) => a - b);
    return `<div class="xstats"><span><small>Last verdict</small><b class="${last.verdict === 'FAIL' ? 'st-needs' : ''}">${esc(last.verdict)}</b></span><span><small>Rounds</small><b>${t.audits.length}</b></span><span><small>Open findings</small><b class="${open ? 'st-needs' : ''}">${open}</b></span><span><small>Median time to verdict</small><b>${mins[Math.floor(mins.length / 2)]} min</b></span></div>
      <div class="audits">${t.audits.slice().reverse().map((a) => `<div class="around"><div class="ahead"><b>Round ${a.r}</b><span class="verdict v-${a.verdict.split(' ')[0].toLowerCase()}">${esc(a.verdict)}</span><span class="grey">${esc(a.model)}</span><span class="faint">verdict in ${a.mins} min</span><span class="spacer"></span><button class="chip" data-act="file" data-f="${esc((t.auditDir || '~/audits') + '-r' + a.r + '.md')}">${icon('judge')} audit file</button></div>
        ${a.findings.length ? `<ul class="findings">${a.findings.map((f) => `<li class="${f[1] ? 'open' : 'fixed'}"><span class="fs">${f[1] ? 'open' : 'fixed'}</span>${esc(f[0])}</li>`).join('')}</ul>` : '<div class="faint" style="font-size:13px;padding:2px 0 4px">No findings.</div>'}</div>`).join('')}</div>`;
  }

  const SKILLS = [['/vibetracks', 'open this track as dispatcher'], ['/vibetracks-loop', 'run the optimise loop; creates KPIs first if none'], ['/vibetracks-discover', 'agent proposes or refines KPIs and gates']];
  function trackHead(t, p) {
    const callout = t.state === 'needs' ? `<div class="callout needs">${dot('needs')}<div class="cb"><b class="st-needs">Needs you</b> · ${esc(t.needs)}<br><small class="faint">asked ${esc(t.asked)} by ${esc(t.sessions[0] ? t.sessions[0].title : 'the loop')} · due ${esc(t.due)}</small></div><button class="btn" data-act="session" data-id="${t.id}" data-i="0">${icon('chat')} Answer in chat</button></div>`
      : t.state === 'stalled' ? `<div class="callout stalled">${dot('stalled')}<div class="cb"><b class="st-stalled">Stalled</b> · ${esc(t.stall)}</div><button class="btn" data-act="start" data-id="${t.id}">Start an agent</button></div>`
      : t.state === 'done' ? `<div class="callout">${dot('done')}<div class="cb"><b>Done</b> · target hit; its gates keep guarding and alert only on a regression. Archive it when it no longer matters.</div><button class="btn" data-act="setstate" data-id="${t.id}" data-v="archived">Archive</button></div>`
      : t.state === 'archived' ? `<div class="callout">${dot('archived')}<div class="cb"><b>Archived</b> · kept for history; nothing alerts.</div><button class="btn" data-act="setstate" data-id="${t.id}" data-v="ok">Reopen</button></div>` : '';
    const mode = `<span class="seg" title="Discover = the agent proposes KPIs and gates · Optimize = the loop runs against them"><button class="${t.mode === 'discover' ? 'on' : ''}" data-act="mode" data-id="${t.id}" data-v="discover">Discover</button><button class="${t.mode === 'optimize' ? 'on' : ''}" data-act="mode" data-id="${t.id}" data-v="optimize" ${t.kpis.length ? '' : 'disabled title="Accept at least one KPI first"'}>Optimize</button></span>`;
    const skills = `<span class="skills"><span class="lbl">Suggested skills</span>${SKILLS.map(([s, w]) => `<button class="chip" data-act="skill" data-id="${t.id}" data-s="${s}" title="${esc(w)}">${s}</button>`).join('')}</span>`;
    return `${crumb([{ act: 'home', label: 'Home' }, { act: 'project', id: p.id, label: p.name }, { label: t.title }])}
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h1>${esc(t.title)}</h1>${mode}</div>
      <p class="sub">${stWord(t)} · ${esc(t.sentence)} · as of ${esc(t.asOf)} · ${rulerTag(t)}</p><div class="bar">${skills}</div>${callout}`;
  }
  const TABS = [['overview', 'Overview'], ['experiments', 'Experiments'], ['auditor', 'Auditor'], ['sessions', 'Sessions']];
  function tabLabel(t, k, l) {
    if (k === 'experiments') return `${l} <span class="faint">${t.exps.length || ''}</span>`;
    if (k === 'auditor') { const a = lastAudit(t); return a ? `${l} <span class="${a.verdict === 'FAIL' || openCount(t) ? 'st-needs' : 'faint'}">r${a.r}${openCount(t) ? ' · ' + openCount(t) + ' open' : ''}</span>` : l; }
    if (k === 'review') { const n = zTrackItems(t.id).length; return n ? `${l} <span class="${zOpen(t.id) ? 'st-needs' : 'faint'}">${zOpen(t.id) || n}</span>` : l; }
    if (k === 'sessions') return `${l} <span class="faint">${t.sessions.length || ''}</span>`;
    return l;
  }
  function overview(t) {
    const kp = t.mode === 'discover' || !t.kpis.length ? `<h2>KPIs and gates · discovering</h2>${discoverPanel(t)}${t.kpis.length ? kpiMultiples(t) : ''}`
      : `<h2 class="h2bar">Soft KPIs <small class="faint" style="font-weight:400">· every dimension side by side, so a trade-off shows</small><span class="spacer"></span>${kpiToggle()}</h2>${kpiMultiples(t)}<h2>Hard gates <small class="faint" style="font-weight:400">· pass / fail, never averaged in</small></h2>${gatesList(t)}`;
    return kp + `<h2>Roadmap ${t.shape === 'ladder' ? '<small class="faint" style="font-weight:400">· rung ladder → experiments</small>' : '<small class="faint" style="font-weight:400">· milestones → experiments</small>'}</h2>${roadmapSection(t)}
      <h2>Ruler</h2><dl class="meta"><dt>Ruler</dt><dd>${rulerTag(t, true)}</dd><dt>Eval command</dt><dd><span class="code">${esc(t.evalCmd)}</span></dd><dt>Track file</dt><dd><span class="code">${esc(t.file)}</span></dd><dt>Mode</dt><dd>${t.mode}</dd></dl>`;
  }
  const sessionsTab = (t) => `${sessionsList([t])}${t.sessions.length ? '' : `<button class="btn" data-act="start" data-id="${t.id}" style="margin-top:6px">${icon('plus')} Start an agent on this track</button>`}`;

  // Tabbed L2 by default; o.stack puts everything on one dense page (V3).
  function trackPage(t, o) {
    o = o || {}; const p = proj(t.project); const head = trackHead(t, p);
    if (o.stack) return head + `<div class="grid2"><div>${overview(t)}</div><div><h2>Auditor</h2>${auditor(t)}<h2>Live sessions</h2>${sessionsTab(t)}</div></div><h2 id="vtp-exp">Experiments</h2>${experiments(t)}`;
    const tab = S.tab || 'overview';
    const tabs = o.review ? TABS.concat([['review', 'Review']]) : TABS;
    if (tab === 'review') return head + `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" class="${tab === k ? 'on' : ''}" data-act="tab" data-id="${k}" aria-selected="${tab === k}">${tabLabel(t, k, l)}</button>`).join('')}</div>${reviewSeam(t)}`;
    const body = tab === 'experiments' ? `<div style="margin-top:14px">${experiments(t)}</div>` : tab === 'auditor' ? `<div style="margin-top:14px">${auditor(t)}</div>` : tab === 'sessions' ? `<div style="margin-top:14px">${sessionsTab(t)}</div>` : overview(t);
    return head + `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" class="${tab === k ? 'on' : ''}" data-act="tab" data-id="${k}" aria-selected="${tab === k}">${tabLabel(t, k, l)}</button>`).join('')}</div>${body}`;
  }

  // Review: a reserved seam only — Zach's review-mode feedback ("media rich, really easy to give feedback, like zen mode") is due next.
  const reviewSeam = (t) => `<div class="seam"><b>Review</b> · slot reserved${t ? ` for ${esc(t.title)}` : ''}<br><span class="faint">First-class reviewing lands here next: media-rich, easy to give feedback, zen-mode. Not designed yet, on purpose: Zach's review feedback is on its way.</span></div>`;

  // ------------------------------------------------------------------ V3 dense table
  function denseTable(ts, o) {
    o = o || {};
    const sorters = { state: (a, b) => STATE_RANK[a.state] - STATE_RANK[b.state], name: (a, b) => a.title.localeCompare(b.title), agents: (a, b) => b.sessions.length - a.sessions.length };
    const th = (k, label) => sorters[k] ? `<th><button class="${S.sort === k ? 'on' : ''}" data-act="sort" data-id="${k}">${label}${S.sort === k ? ' ↓' : ''}</button></th>` : `<th>${label}</th>`;
    const row = (t) => `<tr class="click ${dimCls(t.project)} ${t.state === 'archived' || t.state === 'done' ? 'quiet' : ''}" data-act="track" data-id="${t.id}"><td style="padding-left:${o.group ? 26 : 8}px"><b style="font-weight:500">${esc(t.title)}</b> ${modeTag(t)}${t.synthetic ? ' <span class="synthetic">synthetic</span>' : ''}</td><td>${stWord(t)}</td><td class="num"><b>${esc(kpiNow(t))}</b>${t.kpis.length > 1 ? ` <small class="faint">+${t.kpis.length - 1}</small>` : ''}</td><td>${trackSpark(t, { w: 84, h: 22 })}</td><td class="grey num">${esc(kpiTarget(t))}</td><td>${t.gates.length ? (t.gates.every((g) => g.pass) ? `<span class="grey">${t.gates.length}/${t.gates.length}</span>` : `<span class="st-needs">${t.gates.filter((g) => g.pass).length}/${t.gates.length}</span>`) : '<span class="faint">—</span>'}</td><td>${auditBadge(t) || '<span class="faint">—</span>'}</td><td class="grey">${esc(t.asOf)}</td><td>${t.sessions.length ? `<button class="sess" data-act="session" data-id="${t.id}" data-i="0">${dot('live')}${t.sessions.length} · ${esc(t.sessions[0].acct)}${t.sessions.length > 1 ? ' +' + (t.sessions.length - 1) : ''}</button>` : '<span class="faint">—</span>'}</td>
      <td class="grey" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.state === 'needs' ? `<span class="st-needs">${esc(t.needs)}</span>` : t.state === 'stalled' ? `<span class="st-stalled">${esc(t.stall)}</span>` : esc(t.sentence)}</td></tr>`;
    let body = '';
    if (o.group === 'project') {
      projects().filter((p) => !hidden(p.id)).forEach((p) => {
        const closed = !!S.collapsed[p.id];
        body += `<tr class="grp ${dimCls(p.id)}"><td colspan="2"><span style="display:inline-flex;align-items:center;gap:4px"><button class="chev ${closed ? 'closed' : ''}" data-act="toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button><button data-act="project" data-id="${p.id}" style="font-weight:650">${esc(p.name)}</button> <small class="faint" style="font-weight:400">${p.roots.length} folder${p.roots.length > 1 ? 's' : ''}</small></span></td>
          <td class="num">${p.north ? esc(p.north.text) : '—'}</td><td>${p.north ? spark(p.north.series, { w: 84, h: 22, target: p.north.target }) : ''}</td><td class="grey" style="font-weight:400" colspan="4">${p.north ? 'North star · lagging · ' + esc(p.north.label) : ''}</td><td style="font-weight:400" class="grey">${liveCount(p) ? dot('live') + ' ' + liveCount(p) : ''}</td><td style="font-weight:400">${rollup(p)}</td></tr>`;
        if (!closed) body += activeTracks(p).slice().sort(sorters[S.sort]).map(row).join('');
      });
    } else if (o.group === 'state') {
      ['needs', 'stalled', 'ok', 'done', 'archived'].forEach((st) => {
        const rs = ts.filter((t) => t.state === st && !hidden(t.project)); if (!rs.length) return;
        body += `<tr class="grp"><td colspan="10">${stWord({ state: st })} <small class="faint" style="font-weight:400">${rs.length}</small></td></tr>` + rs.map(row).join('');
      });
    } else body = ts.filter((t) => !hidden(t.project)).slice().sort(sorters[S.sort]).map(row).join('');
    return `<div class="tscroll"><table class="t ledger"><thead><tr>${th('name', 'Track')}${th('state', 'State')}<th>Summary KPI</th><th>Trend</th><th>Target</th><th>Gates</th><th>Audit</th><th>As of</th>${th('agents', 'Agents')}<th>Latest</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }

  // ------------------------------------------------------------------ variants
  const healthCols = () => {
    const ts = allTracks();
    return [['needs', 'Needs you', null, 'computed: an agent asked you'], ['stalled', 'Stalled', null, 'computed: no movement, no agent'], ['ok', 'On track', 'ok', 'drop here to reopen'], ['done', 'Done', 'done', 'target hit · gates keep guarding'], ['archived', 'Archived', 'archived', 'kept for history']]
      .map(([k, label, drop, sub]) => ({ head: `${dot(k)}${label}`, tracks: ts.filter((t) => t.state === k), hideState: true, drop, sub, quiet: k === 'archived', refuse: drop ? '' : `${label} is computed from the loop, not set by hand` }));
  };
  const homeHead = (title) => `<h1>${title}</h1><p class="sub">${summarySentence()}</p>`;
  const groupedRows = (o) => `<div class="rows">${projects().filter((p) => !hidden(p.id)).map((p) => projectHeaderRow(p) + (S.collapsed[p.id] ? '' : activeTracks(p).map((t) => trackRow(t, o)).join(''))).join('')}</div>`;

  // ---- Round 2: the consolidated shell
  // WHY fixed px columns shared by project headers and track rows: per-row fr tracks sized to content and the
  // sparkline column drifted row to row (Zach, Oct 6: "quite distracting"). Every row now uses ONE template.
  function aRowsTrack(t) {
    return `<div class="arow atrack ${dimCls(t.project)} ${t.state === 'archived' || t.state === 'done' ? 'quiet' : ''}" data-act="track" data-id="${t.id}" role="link" tabindex="0">
      <span class="c-chev"></span>
      <span class="c-name"><span class="tname">${esc(t.title)} ${modeTag(t)}${t.synthetic ? ' <span class="synthetic">synthetic</span>' : ''}</span>${trackSub(t)}</span>
      <span class="c-state">${zOpen(t.id) && t.state === 'needs' ? `<button class="st st-needs zentry" data-act="zen" data-id="${t.id}" title="Open Review at this track's first decision">${dot('needs')}Needs you · ${zOpen(t.id)}</button>` : stWord(t)}${zOpen(t.id) && t.state !== 'needs' ? `<button class="zchip" data-act="zen" data-id="${t.id}" title="Open Review at this track's first decision">${zOpen(t.id)} to review</button>` : auditBadge(t)}</span>
      <span class="c-kpi">${kpiCell(t)}</span>
      <span class="c-spark">${trackSpark(t, { w: 112, h: 26 })}</span>
      <span class="c-sess">${sessChips(t, 1)}</span></div>`;
  }
  function aRowsProject(p) {
    const closed = !!S.collapsed[p.id];
    return `<div class="arow aproj ${dimCls(p.id)}">
      <button class="chev ${closed ? 'closed' : ''}" data-act="toggle" data-id="${p.id}" aria-label="${closed ? 'Expand' : 'Collapse'} ${esc(p.name)}" aria-expanded="${!closed}">${icon('chev')}</button>
      <span class="c-name"><button class="pname" data-act="project" data-id="${p.id}">${esc(p.name)} <small class="faint" style="font-weight:400">${p.roots.length} folder${p.roots.length > 1 ? 's' : ''}</small></button>${rollup(p)}</span>
      <span class="c-state grey" style="font-size:12.5px">${liveCount(p) ? `<span class="st">${dot('live')}${liveCount(p)} live</span>` : '<span class="faint">no agent</span>'}</span>
      <span class="c-kpi"><span class="kpi"><b>${p.north ? esc(p.north.text) : '—'}</b><small>North star · ${p.north ? esc(p.north.label) : 'not set'}</small></span></span>
      <span class="c-spark">${p.north ? spark(p.north.series, { w: 112, h: 26, target: p.north.target }) : ''}</span>
      <span class="c-sess"></span></div>`;
  }
  const alignedRows = (ps) => `<div class="arows">${ps.filter((p) => !hidden(p.id)).map((p) => aRowsProject(p) + (S.collapsed[p.id] ? '' : activeTracks(p).map(aRowsTrack).join(''))).join('')}</div>`;
  function swimBoard() {
    const ps = projects().filter((p) => !hidden(p.id)); const sts = ['needs', 'stalled', 'ok', 'done', 'archived'];
    return `<div class="tscroll"><div class="swim" style="grid-template-columns: 170px repeat(5, minmax(140px, 1fr))"><div class="sh2"></div>${sts.map((s) => `<div class="sh2">${stWord({ state: s })}</div>`).join('')}
      ${ps.map((p) => `<div class="sh2 ${dimCls(p.id)}"><button data-act="project" data-id="${p.id}" style="font-weight:600">${pmark(p)} ${esc(p.name)}</button></div>${sts.map((s) => `<div class="${dimCls(p.id)} ${SETTABLE[s] ? 'droppable' : ''}" data-drop="${SETTABLE[s] ? s : ''}" data-refuse="${SETTABLE[s] ? '' : esc(STATE_WORD[s] + ' is computed from the loop, not set by hand')}">${projTracks(p).filter((t) => t.state === s).map((t) => `<button class="mini mini2 ${t.state === 'archived' ? 'quiet' : ''}" data-act="track" data-id="${t.id}" draggable="true"><b style="font-weight:500">${esc(t.title)}</b> ${modeTag(t)}<span class="mrow"><span class="mv grey num" title="${esc(kpiNow(t))}">${esc(t.kpi && t.kpi.of != null ? t.kpi.now + '/' + t.kpi.of : kpiNow(t))}</span><span class="ms">${t.kpi ? trackSpark(t, { w: 56, h: 16 }) : ''}</span><span class="ma faint">${t.sessions.length ? `${dot('live')}${t.sessions.length}` : ''}</span></span></button>`).join('')}</div>`).join('')}`).join('')}</div></div>`;
  }
  const cardGrid = () => projects().filter((p) => !hidden(p.id)).map((p) => `<section class="cgrp ${dimCls(p.id)}"><div class="cgh">${pmark(p)}<button data-act="project" data-id="${p.id}" style="font-weight:650">${esc(p.name)}</button>${rollup(p)}<span class="spacer"></span>${p.north ? `<span class="grey" style="font-size:12.5px">${esc(p.north.label)} <b style="color:var(--fg)">${esc(p.north.text)}</b></span>` : ''}</div>
      <div class="cgrid">${activeTracks(p).map((t) => card(t)).join('') || '<div class="faint empty">No tracks yet</div>'}</div></section>`).join('');
  function toolbar2() {
    const chips = projects().map((p) => `<button class="chip ${S.hl === p.id ? 'on' : ''}" data-act="hl" data-id="${p.id}">${pmark(p)}<span class="ell">${esc(p.name)}</span></button>`).join('');
    const nArch = allTracks().filter((t) => t.state === 'archived').length;
    const grp = S.homeView === 'table' ? `<span class="lbl" style="margin-left:6px">Group</span><span class="seg">${['project', 'state', 'none'].map((g) => `<button class="${S.group === g ? 'on' : ''}" data-act="group" data-id="${g}">${g[0].toUpperCase() + g.slice(1)}</button>`).join('')}</span>` : '';
    return `<div class="bar">
      <span class="seg viewseg" role="tablist" aria-label="Home view">${HOME_VIEWS.map(([k, l, ic], i) => `<button role="tab" aria-selected="${S.homeView === k}" class="${S.homeView === k ? 'on' : ''}" data-act="hview" data-id="${k}" title="${l} (${i + 1})">${icon(ic)} ${l} <kbd>${i + 1}</kbd></button>`).join('')}</span>
      ${grp}${S.homeView === 'rows' || S.homeView === 'table' || S.homeView === 'cards' ? `<button class="chip ${S.showArchived ? 'on' : ''}" data-act="archived">${S.showArchived ? 'Hide' : 'Show'} archived (${nArch})</button>` : '<span class="lbl hide-n">Drag a card to Done or Archived</span>'}
      <span class="spacer"></span>
      <button class="btn" data-act="scale" title="Swap in a 10-project stress fixture (4 synthetic projects)">${S.scale ? '✓ ' : ''}10-project fixture</button>
      <button class="btn primary" data-act="new">${icon('plus')} New project</button></div>
    <div class="bar"><span class="lbl">Highlight project</span>
      <select class="show-n" id="vtp-hl" aria-label="Highlight project"><option value="">All projects</option>${projects().map((p) => `<option value="${p.id}" ${S.hl === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
      <span class="hide-n" style="display:contents"><button class="chip ${!S.hl ? 'on' : ''}" data-act="hl" data-id="">All</button>${chips}</span>
      <span class="seg" style="margin-left:4px"><button class="${S.hlMode === 'highlight' ? 'on' : ''}" data-act="hlmode" data-id="highlight">Highlight</button><button class="${S.hlMode === 'filter' ? 'on' : ''}" data-act="hlmode" data-id="filter">Filter</button></span></div>`;
  }
  // Sidebar, round 2: always shown (setting), no sparklines (Zach: "too messy"), Review seam, account button bottom-left.
  function sidebar2(off) {
    const cur = S.page === 'track' ? track(S.id) : null; const curP = S.page === 'project' ? S.id : cur ? cur.project : null;
    const tree = projects().map((p) => {
      const closed = S.sideCollapsed[p.id] != null ? S.sideCollapsed[p.id] : (!!p.synthetic && p.id !== curP);
      const lt = liveTracks(p); const flag = lt.some((t) => t.state === 'needs') ? dot('needs') : lt.some((t) => t.state === 'stalled') ? dot('stalled') : '';
      let h = `<div class="sp ${curP === p.id ? 'on' : ''}"><button class="chev ${closed ? 'closed' : ''}" data-act="side-toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button><button class="spn" data-act="project" data-id="${p.id}">${esc(p.name)}</button>${closed ? flag : ''}</div>`;
      if (!closed) {
        lt.forEach((t) => { h += `<button class="stk ${cur && cur.id === t.id ? 'on' : ''}" data-act="track" data-id="${t.id}" title="${esc(STATE_WORD[t.state])} · ${esc(kpiNow(t))}">${dot(t.state)}<span class="stn">${esc(t.title)}</span>${t.mode === 'discover' ? '<span class="cnt">disc</span>' : ''}${t.sessions.length ? `<span class="cnt">${dot('live')}${t.sessions.length}</span>` : ''}</button>`; });
        projTracks(p).filter((t) => t.state === 'done' || t.state === 'archived').forEach((t) => { h += `<button class="stk quiet ${cur && cur.id === t.id ? 'on' : ''}" data-act="track" data-id="${t.id}">${dot(t.state)}<span class="stn">${esc(t.title)}</span><span class="cnt">${t.state}</span></button>`; });
      }
      return h;
    }).join('');
    return `<aside class="side side2 ${off ? 'side-off' : ''}" aria-label="Projects and tracks"><div class="side-scroll">
      <button class="nav ${S.page === 'home' ? 'on' : ''}" data-act="home">${icon('home')} Home</button>
      <button class="nav ${S.page === 'review' ? 'on' : ''}" data-act="review">${icon('check')} Review ${zOpen() ? `<span class="zbadge" title="${zOpen()} decisions want you">${zOpen()}</span>` : ''}</button>
      <button class="nav" data-act="new">${icon('plus')} New project</button>
      <div class="sh"><span>Projects</span></div>${tree}</div>
      <div class="side-foot"><button class="acctbtn ${S.acctMenu ? 'on' : ''}" data-act="acct" aria-haspopup="menu" aria-expanded="${S.acctMenu}"><span class="avatar">Z</span><span>Zach</span><span class="faint">· 5 accounts</span><span class="spacer"></span>${icon('chev')}</button></div></aside>`;
  }
  function acctMenu() {
    const it = (act, ic, l, k) => `<button role="menuitem" class="mi" data-act="${act}">${icon(ic)}<span>${l}</span>${k ? `<span class="faint" style="margin-left:auto">${k}</span>` : ''}</button>`;
    return `<div class="acctmenu" role="menu"><div class="faint" style="padding:4px 10px 6px;font-size:12.5px">zach@bamrobotics.com</div>
      ${it('settings', 'gear', 'Settings', 'Ctrl+,')}${it('m-accounts', 'users', 'Accounts (5)')}${it('m-keys', 'kbd', 'Keyboard shortcuts', '?')}${it('m-help', 'help', 'Get help')}<div class="msep"></div>
      ${it('m-changelog', 'rows', 'View changelog')}<div class="msep"></div>${it('m-logout', 'left', 'Log out')}</div>`;
  }
  function settingsPage() {
    const sw = (k, label, desc) => `<div class="setrow"><div><b style="font-weight:500">${label}</b><div class="faint" style="font-size:12.5px">${desc}</div></div><button class="switch ${S.settings[k] ? 'on' : ''}" role="switch" aria-checked="${!!S.settings[k]}" data-act="set" data-k="${k}"><span></span></button></div>`;
    const accts = [['bam', 'zach@bamrobotics.com'], ['personal', 'canonical · ~/.claude-personal'], ['ambience', '~/.claude-ambience'], ['dfuture', '~/.claude-dfuture'], ['proprotectives', '~/.claude-proprotectives']];
    return `<div class="page">${crumb([{ act: 'home', label: 'Home' }, { label: 'Settings' }])}<h1>Settings</h1><p class="sub">Per viewer; saved in this browser.</p>
      <h2>Layout</h2>${sw('alwaysSidebar', 'Always show the sidebar', 'On (default): the project tree stays out on every page, home included. Off: home goes full-width and the sidebar appears when you open a project or track.')}
      ${sw('rememberView', 'Remember the last home view', 'Reopen home in the view you used last (Rows, Table, Board or Cards).')}
      <div class="setrow"><div><b style="font-weight:500">Default home view</b><div class="faint" style="font-size:12.5px">Used when “remember” is off.</div></div><span class="seg">${HOME_VIEWS.map(([k, l]) => `<button class="${S.settings.defaultView === k ? 'on' : ''}" data-act="setview" data-id="${k}">${l}</button>`).join('')}</span></div>
      <div class="setrow"><div><b style="font-weight:500">Soft KPIs on the track page</b><div class="faint" style="font-size:12.5px">Cards (small multiples) or Rows (a compact aligned table). Toggle anywhere with K.</div></div>${kpiToggle()}</div>
      <h2>Accounts</h2><div class="faint" style="font-size:12.5px;margin-bottom:6px">Session chips open chats in the multi-account GUI under the account that owns them (read from claude-hub; simulated here).</div>
      ${accts.map(([a, d]) => `<div class="setrow"><div><b style="font-weight:500">${a}</b><div class="faint" style="font-size:12.5px">${esc(d)}</div></div><span class="faint">linked</span></div>`).join('')}
      <h2 id="vtp-keys">Keyboard</h2><dl class="meta"><dt><kbd>1</kbd> – <kbd>4</kbd></dt><dd>Home view: Rows · Table · Board · Cards</dd><dt><kbd>K</kbd></dt><dd>Soft KPIs: cards ↔ rows</dd><dt><kbd>Ctrl</kbd> + <kbd>,</kbd></dt><dd>Settings</dd><dt><kbd>Esc</kbd></dt><dd>Close menu / dialog</dd><dt>Mouse back / forward</dt><dd>History</dd></dl></div>`;
  }
  const T_ = T;
/*ZEN*/
  const reviewPage = () => `<div class="page">${crumb([{ act: 'home', label: 'Home' }, { label: 'Review' }])}<h1>Review</h1>${reviewSeam(null)}</div>`;

  const VARIANTS = {
    r2: {
      name: 'Round 2 · Consolidated', firstTab: 'overview',
      shell: (main) => { const off = !S.settings.alwaysSidebar && S.page === 'home';
        // WHY no sidebar in Zen: Zach, Oct 6 — "for zen mode you really want to hide the amount of information showing at once". Esc brings it back.
        if (S.page === 'review') return `<div class="shell"><main class="main">${main}</main></div>`;
        return `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar2(off)}<main class="main">${main}</main></div>${S.acctMenu ? acctMenu() : ''}`; },
      home() {
        const v = S.homeView; const vis = allTracks().filter((t) => S.showArchived || t.state !== 'archived');
        const body = v === 'table' ? denseTable(vis, { group: S.group === 'none' ? false : S.group }) : v === 'board' ? swimBoard() : v === 'cards' ? cardGrid() : alignedRows(projects());
        return `<div class="page wide r2page">${crumb([{ label: 'Home' }])}<h1>Tracks</h1><p class="sub">${summarySentence()}${S.settings.alwaysSidebar ? '' : ' · <button class="linkish" data-act="settings">Settings</button>'}</p>${toolbar2()}${body}</div>`;
      },
      project: (p) => `<div class="page wide r2page">${projectPage(p, { aligned: true })}</div>`,
      track: (t) => `<div class="page wide r2page">${trackPage(t, { review: true })}</div>`,
      settings: settingsPage, review: () => zenPage(),
    },
    v1: {
      name: 'Calm Rows', firstTab: 'overview',
      shell: (main) => S.page === 'home' ? `<div class="shell"><main class="main">${main}</main></div>` : `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar({})}<main class="main">${main}</main></div>`,
      home: () => `<div class="page">${homeHead('Tracks')}${toolbar()}${S.view === 'board' ? kanban(healthCols()) : groupedRows()}</div>`,
      project: (p) => `<div class="page">${projectPage(p)}</div>`,
      track: (t) => `<div class="page">${trackPage(t)}</div>`,
    },
    v2: {
      name: 'Codex Shell', firstTab: 'overview',
      shell: (main) => `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar({ nav: true })}<main class="main">${main}</main></div>`,
      home() {
        const ts = allTracks();
        const cols = [['Discover', (t) => t.mode === 'discover' && t.state !== 'done' && t.state !== 'archived', 'discover', 'agent proposes KPIs + gates'], ['Optimize', (t) => t.mode === 'optimize' && (t.state === 'ok' || t.state === 'needs' || t.state === 'stalled'), 'optimize', 'the loop runs against them'], ['Done', (t) => t.state === 'done', 'done', 'gates keep guarding'], ['Archived', (t) => t.state === 'archived', 'archived', 'history']]
          .map(([label, f, drop, sub]) => ({ head: label, tracks: ts.filter(f), drop, sub, quiet: drop === 'archived', dropMode: drop === 'discover' || drop === 'optimize' ? 'mode' : '' }));
        const body = S.view === 'board' ? kanban(cols)
          : projects().filter((p) => !hidden(p.id)).map((p) => `<section class="${dimCls(p.id)}" style="margin-bottom:22px">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:6px 0">
                <button class="chev ${S.collapsed[p.id] ? 'closed' : ''}" data-act="toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button>
                <button data-act="project" data-id="${p.id}" style="font-weight:650;font-size:15px">${esc(p.name)}</button>${rollup(p)}<span class="spacer"></span>
                ${p.north ? `<span class="grey" style="font-size:12.5px">${esc(p.north.label)} <b style="color:var(--fg)">${esc(p.north.text)}</b></span>${spark(p.north.series, { w: 80, h: 22, target: p.north.target })}` : ''}</div>
              ${S.collapsed[p.id] ? '' : activeTracks(p).map((t) => trackRow(t, { noSess: true })).join('')}</section>`).join('');
        return `<div class="page">${crumb([{ label: 'Home' }])}${homeHead('Home')}${toolbar()}${body}</div>`;
      },
      project: (p) => `<div class="page">${projectPage(p)}</div>`,
      track: (t) => `<div class="page">${trackPage(t)}</div>`,
    },
    v3: {
      name: 'Ledger Table', firstTab: 'overview',
      shell: (main) => S.page === 'home' ? `<div class="shell"><main class="main">${main}</main></div>` : `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar({ rail: true })}<main class="main">${main}</main></div>`,
      home() {
        const grp = `<span class="lbl" style="margin-left:6px">Group</span><span class="seg">${['project', 'state', 'none'].map((g) => `<button class="${S.group === g ? 'on' : ''}" data-act="group" data-id="${g}">${g[0].toUpperCase() + g.slice(1)}</button>`).join('')}</span>`;
        let body;
        if (S.view === 'board') {
          const ps = projects().filter((p) => !hidden(p.id)); const sts = ['needs', 'stalled', 'ok', 'done', 'archived'];
          body = `<div class="tscroll"><div class="swim" style="grid-template-columns: 170px repeat(5, minmax(140px, 1fr))"><div class="sh2"></div>${sts.map((s) => `<div class="sh2">${stWord({ state: s })}</div>`).join('')}
            ${ps.map((p) => `<div class="sh2 ${dimCls(p.id)}"><button data-act="project" data-id="${p.id}" style="font-weight:600">${pmark(p)} ${esc(p.name)}</button></div>${sts.map((s) => `<div class="${dimCls(p.id)} ${SETTABLE[s] ? 'droppable' : ''}" data-drop="${SETTABLE[s] ? s : ''}" data-refuse="${SETTABLE[s] ? '' : esc(STATE_WORD[s] + ' is computed from the loop, not set by hand')}">${projTracks(p).filter((t) => t.state === s).map((t) => `<button class="mini ${t.state === 'archived' ? 'quiet' : ''}" data-act="track" data-id="${t.id}" draggable="true"><b style="font-weight:500">${esc(t.title)}</b> ${modeTag(t)}<br><span class="grey num">${esc(kpiNow(t))}</span> ${t.kpi ? trackSpark(t, { w: 50, h: 14 }) : ''}${t.sessions.length ? ` <span class="faint">${dot('live')} ${t.sessions.length}</span>` : ''}</button>`).join('')}</div>`).join('')}`).join('')}</div></div>`;
        } else body = denseTable(allTracks().filter((t) => S.showArchived || t.state !== 'archived'), { group: S.group === 'none' ? false : S.group });
        return `<div class="page wide">${homeHead('Tracks')}${toolbar({ extra: S.view === 'rows' ? grp : '' })}${body}</div>`;
      },
      project: (p) => `<div class="page wide">${projectPage(p, { table: true })}</div>`,
      track: (t) => `<div class="page wide">${trackPage(t, { stack: true })}</div>`,
    },
    v4: {
      name: 'Project Boards', firstTab: 'overview',
      shell: (main) => S.page === 'home' ? `<div class="shell"><main class="main">${main}</main></div>` : `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar({ north: true })}<main class="main">${main}</main></div>`,
      home() {
        let body;
        if (S.view === 'board') {
          body = `<div class="board">${projects().filter((p) => !hidden(p.id)).map((p) => { const act = liveTracks(p).sort((a, b) => STATE_RANK[a.state] - STATE_RANK[b.state]); const dn = projTracks(p).filter((t) => t.state === 'done'); const ar = projTracks(p).filter((t) => t.state === 'archived');
            return `<div class="col ${dimCls(p.id)}"><div class="colh">${pmark(p)}<button data-act="project" data-id="${p.id}">${esc(p.name)}</button><span class="n">${act.length}</span></div>
              <div class="droppable shelf" data-drop="ok">${act.map((t) => card(t)).join('') || '<div class="faint empty">No active tracks</div>'}</div>
              <div class="shelfh">Done · ${dn.length}</div><div class="droppable shelf" data-drop="done">${dn.map((t) => card(t)).join('') || '<div class="faint empty">Drop a card here</div>'}</div>
              <div class="shelfh">Archived · ${ar.length}</div><div class="droppable shelf qcol" data-drop="archived">${ar.map((t) => card(t)).join('') || '<div class="faint empty">Drop a card here</div>'}</div></div>`; }).join('')}</div>`;
        } else body = projects().filter((p) => !hidden(p.id)).map((p) => {
          const closed = !!S.collapsed[p.id];
          return `<div class="pcard ${dimCls(p.id)}"><div class="pcard-h"><button class="chev ${closed ? 'closed' : ''}" data-act="toggle" data-id="${p.id}" aria-label="Toggle ${esc(p.name)}">${icon('chev')}</button><button data-act="project" data-id="${p.id}" style="font-weight:650;font-size:15px">${esc(p.name)}</button><small class="faint hide-n">${p.roots.map(esc).join(' · ')}</small><span class="spacer"></span>${rollup(p)}${closed && p.north ? `<b>${esc(p.north.text)}</b>${spark(p.north.series, { w: 70, h: 20, target: p.north.target })}` : ''}</div>
            ${closed ? '' : `<div class="pcard-b"><div class="pcard-n"><div class="faint" style="font-size:12.5px">North star · lagging · ${p.north ? esc(p.north.label) : '—'}</div><div class="bv">${p.north ? esc(p.north.text) : '—'}</div>${p.north ? spark(p.north.series, { w: 228, h: 64, target: p.north.target, fluid: true }) + `<div class="faint" style="font-size:12px">${esc(p.north.note)}</div>` : ''}<div style="margin-top:8px;font-size:12.5px" class="grey">${liveCount(p) ? dot('live') + ' ' + liveCount(p) + ' agents live' : 'no agent live'}</div></div>
            <div class="pcard-t">${activeTracks(p).map((t) => trackRow(t, { ladder: true })).join('') || '<p class="faint" style="padding:12px">No tracks yet.</p>'}</div></div>`}</div>`; }).join('');
        return `<div class="page">${homeHead('Projects')}${toolbar()}${body}</div>`;
      },
      project: (p) => `<div class="page">${projectPage(p, { ladders: true })}</div>`,
      track: (t) => `<div class="page">${trackPage(t)}</div>`,
    },
    v5: {
      name: 'Live Ops', firstTab: 'sessions',
      shell: (main) => S.page === 'home' ? `<div class="shell"><main class="main">${main}</main></div>` : `<div class="shell ${S.drawer ? 'drawer' : ''}">${sidebar({ sessions: true })}<main class="main">${main}</main></div>`,
      home() {
        const ts = allTracks();
        const attn = ts.filter((t) => (t.state === 'needs' || t.state === 'stalled') && !hidden(t.project));
        const band = `<div class="band">${attn.map((t) => `<div class="bi ${t.state} ${dimCls(t.project)}" data-act="track" data-id="${t.id}" role="link" tabindex="0" style="cursor:pointer">${dot(t.state)}<span style="flex:1;min-width:0"><b>${esc(t.title)}</b> <small class="faint">${esc(proj(t.project).name)}</small><br><span class="st-${t.state}" style="font-weight:500">${t.state === 'needs' ? esc(t.needs) : esc(t.stall)}</span></span>${t.state === 'needs' ? `<button class="btn" data-act="session" data-id="${t.id}" data-i="0">${icon('chat')} Answer</button>` : `<button class="btn" data-act="start" data-id="${t.id}">Start agent</button>`}</div>`).join('') || '<div class="bi" style="background:var(--hover)">Nothing needs you. Every track is moving or done.</div>'}</div>`;
        const live = `<aside class="liverail"><h3>${dot('live')} Live now · ${ts.filter((t) => t.state !== 'archived').reduce((a, t) => a + t.sessions.length, 0)} agents</h3>${projects().filter((p) => liveCount(p) && !hidden(p.id)).map((p) => `<div class="lg ${dimCls(p.id)}"><button class="lgt" data-act="project" data-id="${p.id}">${esc(p.name)}</button>${liveTracks(p).filter((t) => t.sessions.length).map((t) => t.sessions.map((s, i) => `<button class="ls" data-act="session" data-id="${t.id}" data-i="${i}">${dot('live')}<span style="flex:1;min-width:0"><span style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.title)}</span><small class="faint">${esc(s.acct)} · ${esc(t.title)} · ${esc(s.age)}</small></span></button>`).join('')).join('')}</div>`).join('')}</aside>`;
        const whoCols = [['You', (t) => t.state === 'needs', 'needs', null, 'an agent asked you'], ['An agent', (t) => t.state === 'ok' && t.sessions.length, 'live', 'ok', 'a session is on it'], ['Nobody', (t) => t.state === 'stalled' || (t.state === 'ok' && !t.sessions.length), 'stalled', null, 'start an agent'], ['Done', (t) => t.state === 'done', 'done', 'done', 'gates keep guarding'], ['Archived', (t) => t.state === 'archived', 'archived', 'archived', 'history']]
          .map(([label, f, d, drop, sub]) => ({ head: `${dot(d)}${label}`, tracks: ts.filter(f), drop, sub, quiet: d === 'archived', refuse: drop ? '' : `“${label}” is computed from the loop and sessions` }));
        return `<div class="page" style="max-width:1400px">${homeHead('Tracks')}${band}<div class="v5grid"><div>${toolbar()}${S.view === 'board' ? kanban(whoCols) : groupedRows({ noSess: true })}</div>${live}</div></div>`;
      },
      project: (p) => `<div class="page">${projectPage(p, { order: 'sessions' })}</div>`,
      track: (t) => `<div class="page">${trackPage(t)}</div>`,
    },
  };

  // ------------------------------------------------------------------ dialog
  function dialog() {
    const d = S.dlg; if (!d) return '';
    const deflt = d.roots.length === 1 ? d.roots[0].replace(/^.*\//, '') : '';
    const ok = d.roots.length >= 1 && (d.name.trim() || d.roots.length === 1);
    const avail = FOLDER_CHOICES.filter((f) => !d.roots.includes(f));
    return `<div class="scrim" data-act="dlg-scrim"><div class="dialog" role="dialog" aria-modal="true" aria-label="${d.mode === 'edit' ? 'Edit project' : 'Create project'}">
      <div style="display:flex;align-items:center"><h3 style="flex:1">${d.mode === 'edit' ? 'Edit project' : 'Create project'}</h3><button class="chev" data-act="dlg-close" aria-label="Close">${icon('x')}</button></div>
      <label class="field">${icon('folder')}<input id="vtp-name" value="${esc(d.name)}" placeholder="${esc(deflt ? deflt + ' (from its folder)' : 'Project name')}" autocomplete="off"></label>
      <div style="margin:14px 0 4px;font-weight:500">Source folders <small class="faint" style="font-weight:400">· 1 or more; with one folder the name defaults to it</small></div>
      <div class="dfold">${d.roots.map((r, i) => `<div class="folder">${icon('folder')}<span>${esc(r)}</span><button class="rm" data-act="dlg-rm" data-i="${i}" aria-label="Remove ${esc(r)}">${icon('x')}</button></div>`).join('')}
        <div class="addrow"><span class="grey">Add a folder on</span><select id="vtp-pick" aria-label="Folder">${avail.map((f) => `<option ${d.pick === f ? 'selected' : ''}>${esc(f)}</option>`).join('')}</select><button class="btn" data-act="dlg-add">${icon('plus')} Add</button></div></div>
      <p class="faint" style="font-size:12.5px;margin:10px 0 0">Saved as <span class="code">${esc((d.roots[0] || '~/<first folder>') + '/Project.vibetrack')}</span> → <span class="code">roots: [${d.roots.map(esc).join(', ')}]</span>${d.name.trim() ? `, <span class="code">name: ${esc(d.name.trim())}</span>` : ''}</p>
      <div class="dlg-foot">${!ok && d.roots.length > 1 ? '<small class="faint">Two or more folders need a name</small>' : ''}<button class="btn" data-act="dlg-close">Cancel</button><button class="btn primary" data-act="dlg-create" ${ok ? '' : 'disabled'}>${d.mode === 'edit' ? 'Save' : 'Create project'}</button></div>
    </div></div>`;
  }

  // ------------------------------------------------------------------ render + events
  function render() {
    if (!root) return;
    const main = root.querySelector('.main'); const keep = main && root.dataset.page === S.page + ':' + S.id ? main.scrollTop : 0;
    const V = VARIANTS[S.v];
    let inner;
    if (S.page === 'project' && proj(S.id)) inner = V.project(proj(S.id));
    else if (S.page === 'track' && track(S.id)) inner = V.track(track(S.id));
    else if ((S.page === 'settings' || S.page === 'review') && V[S.page]) inner = V[S.page]();
    else { S.page = 'home'; inner = V.home(); }
    const vkey = (v) => { const c = root.querySelector('.zcard'); return (c ? c.dataset.zitem : '') + ':' + v.dataset.mi; };
    if (S.zen) root.querySelectorAll('.zmedia video').forEach((v) => { S.zen.vt[vkey(v)] = v.currentTime; });
    root.innerHTML = V.shell(inner) + dialog() + (S.toast ? `<div class="toast" role="status">${S.toast}</div>` : '') + (opts.rec ? '<div class="fcursor" style="left:-40px;top:-40px"></div>' : '');
    root.dataset.page = S.page + ':' + S.id; root.dataset.variant = S.v; root.dataset.tab = S.tab;
    if (S.zen && S.page === 'review') root.querySelectorAll('.zmedia video').forEach((v) => { const t = S.zen.vt[vkey(v)]; if (t) v.currentTime = t; if (S.zen.pinMode || S.zen.pinDraft) v.pause(); });
    const m2 = root.querySelector('.main'); if (m2) m2.scrollTop = keep;
    if (S.dlg) { const inp = root.querySelector('#vtp-name'); if (inp && S.dlg.focus) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); S.dlg.focus = false; } }
    if (opts.standalone && !opts.noHash) { const h = `#${S.v}/${S.page}${S.id ? '/' + S.id : ''}${S.page === 'home' && S.v === 'r2' ? '/' + S.homeView : S.page === 'home' && S.view === 'board' ? '/board' : ''}${S.page === 'track' && S.tab !== V.firstTab ? '/' + S.tab : ''}`; if (location.hash !== h) history.replaceState(null, '', h); }
    listeners.forEach((f) => f(snapshot()));
  }
  const snapshot = () => ({ v: S.v, page: S.page, id: S.id, view: S.v === 'r2' ? S.homeView : S.view, homeView: S.homeView, kpiView: S.kpiView, acctMenu: S.acctMenu, settings: Object.assign({}, S.settings), zi: S.zen ? S.zen.i : 0, zend: S.zen ? S.zen.end : false, zitem: S.zen ? S.zen.queue[S.zen.i] : null, hl: S.hl, hlMode: S.hlMode, collapsed: Object.assign({}, S.collapsed), dlg: !!S.dlg, tab: S.tab });

  function go(page, id, tab) {
    const same = S.page === page && S.id === id;
    if (same && !tab) return;
    if (!same) { hist.back.push({ page: S.page, id: S.id }); hist.fwd.length = 0; }
    S.page = page; S.id = id || null; S.drawer = false;
    if (page === 'track') { S.tab = tab || VARIANTS[S.v].firstTab; S.exp = null; S.rungFilter = null; }
    render();
    const m = root.querySelector('.main'); if (m) m.scrollTop = 0;
  }
  function toast(msg) { S.toast = msg; render(); clearTimeout(toastTimer); toastTimer = setTimeout(() => { S.toast = null; render(); }, 2800); }
  function setState(t, st, how) {
    const was = t.state; t.state = st;
    toast(`${esc(t.title)}: ${STATE_WORD[was]} → <b>${STATE_WORD[st]}</b> ${how || ''}<span style="opacity:.6"> · writes <code>vibe-status: ${st}</code> (simulated)</span>`);
  }

  function onClick(e) {
    if (S.page === 'review' && S.zen && S.zen.pinMode && zMediaClick(e)) return;
    const el = e.target.closest('[data-act]');
    if (S.acctMenu && !(el && (el.dataset.act === 'acct' || el.closest('.acctmenu')))) { S.acctMenu = false; if (!el || !root.contains(el)) { render(); return; } }
    if (!el || !root.contains(el)) return;
    const act = el.dataset.act, id = el.dataset.id;
    if (act === 'dlg-scrim') { if (e.target === el) { S.dlg = null; render(); } return; }
    e.preventDefault(); e.stopPropagation();
    switch (act) {
      case 'home': if (S.v !== 'r2') S.view = 'rows'; if (S.page !== 'home') go('home', null); else render(); break;
      case 'hview': S.homeView = id; persist(); if (S.page !== 'home') go('home', null); else render(); break;
      case 'kpiview': S.kpiView = id; persist(); render(); break;
      case 'acct': S.acctMenu = !S.acctMenu; render(); break;
      case 'settings': S.acctMenu = false; go('settings', null); break;
      case 'review': zStart(null); go('review', null); break;
      case 'zen': zStart(id); go('review', null); break;
      case 'zall': zStart(null); render(); break;
      case 'zleave': go('home', null); break;
      case 'zopt': zChoose(+el.dataset.k); break;
      case 'zenter': zEnter(); break;
      case 'zskip': zSkip(); break;
      case 'zctx': S.zen.ctx = !S.zen.ctx; render(); break;
      case 'znote': S.zen.noteOpen = true; render(); { const n = root.querySelector('#znote'); if (n) n.focus(); } break;
      case 'zpinmode': S.zen.pinMode = !S.zen.pinMode; S.zen.pinDraft = null; render(); break;
      case 'zjump': zGo(+el.dataset.i); break;
      case 'zunpin': { const a = S.zen.ans[S.zen.queue[S.zen.i]]; a.pins.splice(+el.dataset.i, 1); render(); break; }
      case 'zseek': { const v = root.querySelector(`.zmedia[data-mi="${el.dataset.mi}"] video`); if (v) { v.pause(); v.currentTime = +el.dataset.t; } break; }
      case 'zcopy': zCopy(); break;
      case 'set': S.settings[el.dataset.k] = !S.settings[el.dataset.k]; persist(); render(); break;
      case 'setview': S.settings.defaultView = id; persist(); render(); break;
      case 'm-keys': S.acctMenu = false; go('settings', null); { const k = root.querySelector('#vtp-keys'); if (k) k.scrollIntoView({ block: 'start' }); } break;
      case 'm-accounts': case 'm-help': case 'm-changelog': case 'm-logout': S.acctMenu = false; toast(`${esc(el.textContent.trim())} <span style="opacity:.6">(menu item, simulated)</span>`); break;
      case 'boardnav': S.view = 'board'; if (S.page !== 'home') go('home', null); else render(); break;
      case 'project': go('project', id); break;
      case 'track': go('track', id); break;
      case 'tab': if (id === 'review' && S.v === 'r2') { zStart(S.id); go('review', null); break; } if (el.dataset.track && !(S.page === 'track' && S.id === el.dataset.track)) go('track', el.dataset.track, id); else { S.tab = id; render(); } break;
      case 'exp': S.exp = id; render(); break;
      case 'rung': S.rungFilter = el.dataset.r || null; if (S.v !== 'v3') S.tab = 'experiments'; render(); if (S.v === 'v3') { const x = root.querySelector('#vtp-exp'); if (x) x.scrollIntoView({ block: 'start' }); } break;
      case 'mode': { const t = track(id); if (!t.kpis.length && el.dataset.v === 'optimize') break; t.mode = el.dataset.v; toast(`${esc(t.title)} → <b>${t.mode}</b> <span style="opacity:.6">· writes <code>vibe-mode: ${t.mode}</code> (simulated)</span>`); break; }
      case 'prop': { const t = track(id); const pr = t.proposals[+el.dataset.i]; pr.done = el.dataset.v;
        if (pr.done === 'yes' && pr[0] === 'KPI') { t.kpis.push(K(pr[1], [0, 0], null, 'up', '', 0)); t.kpi = t.kpis[0]; t.series = t.kpi.series; }
        if (pr.done === 'yes' && pr[0] === 'Gate') t.gates.push(G(pr[1], true, 'not run yet'));
        render(); break; }
      case 'setstate': setState(track(id), el.dataset.v); break;
      case 'skill': { const t = track(id); toast(`Would start a session in <b>${esc(proj(t.project).roots[0])}</b> running <code>${esc(el.dataset.s)}</code> on ${esc(t.title)} <span style="opacity:.6">(suggested skill, not built)</span>`); break; }
      case 'file': toast(`Opens <code>${esc(el.dataset.f)}</code> <span style="opacity:.6">(simulated)</span>`); break;
      case 'archived': S.showArchived = !S.showArchived; render(); break;
      case 'toggle': S.collapsed[id] = !S.collapsed[id]; render(); break;
      case 'side-toggle': { const p = proj(id); const cur = S.sideCollapsed[id] != null ? S.sideCollapsed[id] : !!(p && p.synthetic); S.sideCollapsed[id] = !cur; render(); break; }
      case 'view': S.view = id; render(); break;
      case 'hl': S.hl = id || null; render(); break;
      case 'hlmode': S.hlMode = id; render(); break;
      case 'group': S.group = id; render(); break;
      case 'sort': S.sort = id; render(); break;
      case 'pin': S.pinned = !S.pinned; render(); break;
      case 'scale': S.scale = !S.scale; render(); break;
      case 'burger': S.drawer = !S.drawer; render(); break;
      case 'back': if (hist.back.length) { hist.fwd.push({ page: S.page, id: S.id }); const b = hist.back.pop(); S.page = b.page; S.id = b.id; render(); } break;
      case 'fwd': if (hist.fwd.length) { hist.back.push({ page: S.page, id: S.id }); const f = hist.fwd.pop(); S.page = f.page; S.id = f.id; render(); } break;
      case 'session': { const t = track(id); const s = t && t.sessions[+el.dataset.i || 0]; if (s) toast(`Opens “${esc(s.title)}” in Claude Hub · account <b>${esc(s.acct)}</b> <span style="opacity:.6">(simulated link: 127.0.0.1:8790/#/s/&lt;session_id&gt;)</span>`); break; }
      case 'start': { const t = track(id); toast(`Starts a session in <b>${esc(proj(t.project).roots[0])}</b> with the track file as its brief <span style="opacity:.6">(simulated)</span>`); break; }
      case 'new': S.dlg = { mode: 'new', name: '', roots: [], pick: FOLDER_CHOICES[0], focus: true }; S.drawer = false; render(); break;
      case 'edit': { const p = proj(id); S.dlg = { mode: 'edit', pid: id, name: p.custom ? p.name : '', roots: p.roots.slice(), pick: FOLDER_CHOICES.find((f) => !p.roots.includes(f)), focus: true }; render(); break; }
      case 'dlg-close': S.dlg = null; render(); break;
      case 'dlg-add': { const sel = root.querySelector('#vtp-pick'); const f = sel && sel.value; if (f && !S.dlg.roots.includes(f)) S.dlg.roots.push(f); S.dlg.pick = FOLDER_CHOICES.find((x) => !S.dlg.roots.includes(x)); render(); break; }
      case 'dlg-rm': S.dlg.roots.splice(+el.dataset.i, 1); render(); break;
      case 'dlg-create': {
        const d = S.dlg; const name = d.name.trim() || d.roots[0].replace(/^.*\//, '');
        if (d.mode === 'edit') { const p = proj(d.pid); p.name = name; p.custom = !!d.name.trim(); p.roots = d.roots.slice(); S.dlg = null; toast(`Saved <b>${esc(name)}</b> · ${p.roots.length} folder${p.roots.length > 1 ? 's' : ''}`); }
        else { PROJECTS.push({ id: 'new-' + Date.now(), name, custom: !!d.name.trim(), roots: d.roots.slice(), color: '#a3a29f', north: null, tracks: [] }); S.dlg = null; toast(`Created <b>${esc(name)}</b> · ${d.roots.length} folder${d.roots.length > 1 ? 's' : ''} · no tracks yet`); }
        break;
      }
    }
  }
  // Drag a card between board columns; settable columns accept it, computed ones refuse with a reason.
  function onDragStart(e) { const c = e.target.closest && e.target.closest('[draggable=true][data-id]'); if (!c) return; dragId = c.dataset.id; e.dataTransfer.setData('text/plain', dragId); e.dataTransfer.effectAllowed = 'move'; c.classList.add('dragging'); }
  function onDragOver(e) { const col = e.target.closest && e.target.closest('[data-drop]'); if (!col || !dragId) return; e.preventDefault(); root.querySelectorAll('.dropping').forEach((x) => x !== col && x.classList.remove('dropping')); col.classList.add('dropping'); }
  function onDrop(e) {
    const col = e.target.closest && e.target.closest('[data-drop]'); if (!col || !dragId) return; e.preventDefault();
    const t = track(dragId); dragId = null; const to = col.dataset.drop;
    if (!to) { toast(esc(col.dataset.refuse || 'This column is computed')); return; }
    if (col.dataset.dropmode === 'mode') {
      if (to === 'optimize' && !t.kpis.length) { toast(`${esc(t.title)} has no KPIs yet: accept some in Discover first (or <code>/vibetracks-loop</code>, which creates them)`); return; }
      t.mode = to; if (t.state === 'done' || t.state === 'archived') t.state = 'ok';
      toast(`${esc(t.title)} → <b>${to}</b> <span style="opacity:.6">· writes <code>vibe-mode: ${to}</code> (simulated)</span>`); return;
    }
    if (t.state === to || (to === 'ok' && (t.state === 'needs' || t.state === 'stalled'))) { render(); return; }
    setState(t, to, 'by drag');
  }
  function onDragEnd() { dragId = null; root.querySelectorAll('.dropping, .dragging').forEach((x) => x.classList.remove('dropping', 'dragging')); }
  function onInput(e) {
    if (S.zen && (e.target.id === 'zother' || e.target.id === 'znote')) { const id = S.zen.queue[S.zen.i]; const a = S.zen.ans[id] = Object.assign({}, S.zen.ans[id] || {}); if (e.target.id === 'zother') { a.other = e.target.value; if (a.other.trim()) a.choice = null; } else a.note = e.target.value; return; } if (e.target.id === 'vtp-name' && S.dlg) { S.dlg.name = e.target.value; const pos = e.target.selectionStart; render(); const i = root.querySelector('#vtp-name'); if (i) { i.focus(); i.setSelectionRange(pos, pos); } } if (e.target.id === 'vtp-pick' && S.dlg) S.dlg.pick = e.target.value; if (e.target.id === 'vtp-hl' && e.type === 'change') { S.hl = e.target.value || null; render(); } }
  // Global shortcuts (round 2). Embedded in the report they fire only while the pointer or focus is inside the prototype.
  function onDocKey(e) {
    if (!root || S.v !== 'r2' || S.dlg) return;
    if (!opts.standalone && !(root.matches(':hover') || root.contains(document.activeElement))) return;
    if (S.page === 'review') { zKey(e); return; }
    if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
    if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); S.acctMenu = false; go('settings', null); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Escape' && S.acctMenu) { S.acctMenu = false; render(); return; }
    const n = '1234'.indexOf(e.key);
    if (n >= 0) { e.preventDefault(); S.homeView = HOME_VIEWS[n][0]; persist(); if (S.page !== 'home') go('home', null); else render(); return; }
    if ((e.key === 'k' || e.key === 'K') && S.page === 'track') { S.kpiView = S.kpiView === 'cards' ? 'rows' : 'cards'; persist(); render(); }
  }
  function onKey(e) {
    if (e.key === 'Escape' && S.dlg) { S.dlg = null; render(); return; }
    if (e.key === 'Enter' && e.target.matches('[role=link][data-act]')) e.target.click();
  }
  function onMouse(e) { const btn = e.button === 3 ? 'back' : e.button === 4 ? 'fwd' : null; if (!btn) return; e.preventDefault(); const b = root.querySelector(`[data-act=${btn}]`); if (b) onClick({ target: b, preventDefault() {}, stopPropagation() {} }); }

  function mount(el, o) {
    root = el; opts = o || {}; root.classList.add('vtp');
    root.addEventListener('click', onClick); root.addEventListener('input', onInput); root.addEventListener('change', onInput); root.addEventListener('keydown', onKey); root.addEventListener('mouseup', onMouse);
    document.addEventListener('keydown', onDocKey);
    root.addEventListener('dragstart', onDragStart); root.addEventListener('dragover', onDragOver); root.addEventListener('drop', onDrop); root.addEventListener('dragend', onDragEnd);
    if (opts.rec) {
      root.addEventListener('mousemove', (e) => { const c = root.querySelector('.fcursor'); const r = root.getBoundingClientRect(); if (c) { c.style.left = (e.clientX - r.left) + 'px'; c.style.top = (e.clientY - r.top) + 'px'; } root._cx = e.clientX - r.left; root._cy = e.clientY - r.top; });
      root.addEventListener('mousedown', () => { const c = root.querySelector('.fcursor'); if (c) c.classList.add('down'); });
      listeners.push(() => { const c = root.querySelector('.fcursor'); if (c && root._cx != null) { c.style.left = root._cx + 'px'; c.style.top = root._cy + 'px'; } });
    }
    if (opts.standalone && location.hash.length > 1) {
      const [v, page, id, extra] = location.hash.slice(1).split('/');
      if (VARIANTS[v]) S.v = v; if (page) S.page = page;
      if (page === 'home' && HOME_VIEWS.some((x) => x[0] === id)) { S.homeView = id; if (id === 'board') S.view = 'board'; } else if (id === 'board') S.view = 'board'; else if (id) S.id = decodeURIComponent(id); if (extra === 'board') S.view = 'board';
      if (S.page === 'review') zStart(id && id !== 'all' ? id : null);
      if (S.page === 'track') S.tab = (extra && extra !== 'board') ? extra : VARIANTS[S.v].firstTab;
    }
    render();
  }
  function set(patch) {
    if (patch.page && (patch.page !== S.page || patch.id !== S.id)) { hist.back.push({ page: S.page, id: S.id }); hist.fwd.length = 0; }
    Object.assign(S, patch); if (patch.collapsed) S.collapsed = Object.assign({}, patch.collapsed);
    if (patch.homeView || patch.kpiView) persist();
    if (patch.page === 'track' && !patch.tab) S.tab = VARIANTS[S.v].firstTab;
    if (patch.page === 'track') { S.exp = patch.exp || null; S.rungFilter = null; }
    render(); const m = root.querySelector('.main'); if (m && patch.page) m.scrollTop = 0;
  }
  // Report walkthrough hook: open Review (optionally one track) at a position, or its summary.
  const zen = (trackId, i, end) => { S.v = 'r2'; zStart(trackId || null); if (S.page !== 'review') { hist.back.push({ page: S.page, id: S.id }); S.page = 'review'; S.id = null; } zGo(end ? S.zen.queue.length : (i || 0)); };
  return { zen, mount, set, state: snapshot, onChange: (f) => listeners.push(f), VARIANTS, PROJECTS, T };
})();
