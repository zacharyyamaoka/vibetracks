# bam_roadmap: one roadmap + proof-of-done format for every BAM agent loop

Moved from bam_ws `src/dev/bam_roadmap` @ 553a66f0 to `vibetracks/roadmap/projector/`; the dashboard's
`/roadmap/doc` (`vibetracks/roadmap/api.py`) now projects each loop live with it. The loops' paths come
from vibetracks' sources map (`kinsim_curriculum_dir`, `kinsim_home`, `rig_loop_dir`).

`bam-roadmap/1` is what a click on a rung opens: the loop's roadmap (axes, rungs, dependency edges)
and, for every rung, `done_when` as typed criteria resolved to evidence links that open (a test's
file and line, a JUnit record, a ledger run, an audit's verdict line, a log), with a status
**derived** from that evidence. `loop-status/1` (P1, at most 2 KB) stays the one-screen summary;
this is its drill-down, and its `where` rows are recomputed here from evidence.

It is a projection, never a rewrite: it reads the files the loops already write and writes nothing
back. Runtime is the standard library only; `pytest` and `jsonschema` are test-only.

## The one rule

A rung is `green` only when every criterion of its `done_when` is met by a **record** or a **log**,
at a commit in the projected history, with nothing relevant changed since. A loop can always hold
a rung below green; it can never lift one to green by saying so.

| `status` | meaning |
|---|---|
| `green` | every criterion met by recorded evidence, fresh |
| `done` | existed before the loop; the code its baseline cites exists (an inspection) |
| `stale` | was proven, but something in the proof's scope changed after it, or the ruler did, or the inputs its run recorded are not what the gate asks for now, or its commit is not in this history. A test's scope is its package, the path dependencies it declares, its import closure and a declared write set; a measured reading's is the producer command's execution path plus the scorer its judge calls, and its run manifest's corpus must be the gate's corpus as defined now; a review's is the code it cites |
| `claimed` | the loop says green, but some criterion rests on the loop's word (a sentence, a log that never shows the whole file run, a run on a dirty tree, a commit that only an agent's event names) or is a condition stated only in prose that this format does not recognise |
| `partial` | the loop holds it below green, or its evidence contradicts the loop's green |
| `missing` | nothing yet |

Evidence strength: `record` (result and coverage read from a machine-readable artifact: every JUnit
testcase of the file in a run whose own collection is on record, parameters kept, none skipped, none
counted twice; a ledger row consistent with itself, its batch and its run manifest; a gate report whose
counts, exit codes, expected and unexpected sets, `then` commands and reopened JUnit files all agree, with
the tier declared at its commit; an audit's verdict), `log` (a log's own per-test record of the whole file:
selected whole by the run's recorded command, one outcome per test, every one a pass, its summary in
agreement), and either needs a record the run itself wrote to bind it to a commit and a clean tree (a log's
`HEAD <sha>;` line, a run manifest's or ledger row's `git`, a gate report's `git`, an audit's `candidate`
line). `claim` is the loop's word: a sentence, a log that never shows the whole file run, a run on a dirty
or unrecorded tree, a commit that only an agent's event names. A file time or git's reflog binds nothing
(Codex H02). Results use the
in-toto test-result words, lowercased: `passed`, `warned`, `failed` (plus JUnit's `error`, `skipped`).
Criteria carry the NASA SP-2016-6105 verification `method`: `test`, `analysis`, `demonstration`, `inspection`.

## One rung's proof, exactly (what a viewer reads)

```text
rung      {id, axis, title, order, depends_on[], alias_of,
           status, claimed_status, status_reason,
           claimed_by {source: Link+pointer, event: EventRef|null},
           done_when {rule: all|alias|none, text, source: Link+pointer},
           criteria[Criterion], support Support, evidence[Evidence], history[History],
           blockers[], kpis[], notes[], x{}}
Criterion {id, kind: test|gate_run|audit|inspection|demonstration|package|prerequisites|alias|stated,
           method, title, text, source, targets[Target], verdict: met|stale|unknown|unmet,
           strength: record|log|claim|null, reason, evidence[eid], at[commit]}
Target    Link + {verdict, strength, evidence[eid] (exactly what this verdict rests on),
                  commit, note, changed_since[],
                  scope[] (paths whose change makes it stale; "dir/" = a folder; "@producer" =
                           the document's scopes.producer, a measured reading's execution path),
                  context{} (kinsim: ruler_sha256), spec{}|null (a gate's bar or tier; a measured
                  window's spec.inputs is the corpus as defined now, which each run's manifest must match)}
Support   {evidence[eid], runs[run_id], events[EventRef], commits[sha], rungs[rung id]}
Evidence  Link + {id, result, strength, commit, commit_source: artifact|artifact-dirty|citation|null,
                  ts, origin, facts{},
                  as_cited (the path exactly as the loop wrote it, or null), event: EventRef|null,
                  role: supports|superseded|context, superseded_by: eid|null,
                  run_id? (kind run), cases[{node_id, line, outcome}]? (kind test, one per JUnit
                  testcase, parameters kept), via? (eid of the JUnit file), witnesses[]?}
History   {ts, wave, kind, status, commit, detail, evidence_text, evidence[eid],
           event: EventRef, superseded_by: line|null}
Link      {kind, label, path, base: repo|data_home|abs, abs, line, end_line, exists, why_unresolved}
EventRef  {path, base, abs, line, kind, subject, status, ts, commit}
```

- A path and its line are always separate fields; nothing ever needs `path:N` split apart.
  `abs` is set only when the file exists now; otherwise `why_unresolved` says why.
- `support` is what the derived status was computed from, by exact id: the evidence ids its
  criteria's targets rest on, the ledger `run_id`s among them, the events that cited them (by
  their physical line in `loop_events.jsonl`), and the rungs an alias or prerequisite rests on.
  Nothing in it is inferred from prose; the validator rejects a document where it is not exact.
- `claimed_by` names where the loop's own word comes from (the `status.json` or `ladder.json`
  row by JSON Pointer, and, for a rung that follows status events, the latest one). A later
  `partial` event supersedes an earlier `green` one in `history` (`superseded_by` = its line).
- Every evidence item has a `role`: `supports` (in `support.evidence`), `superseded` (an older
  status event's citation, or a run outside the gate's window; `superseded_by` names the newer
  item when there is one), or `context` (cited, shown, not part of the verdict).
- `commit_source` says where `commit` came from: a record the run itself wrote (`artifact`: a gate
  log's `HEAD <sha>;` line, named in `facts.console` and re-read; a gate report's `git`; a run
  manifest's or ledger row's `git`; an audit's `candidate` line), the same record saying its tree was
  dirty or not saying it was clean (`artifact-dirty`, always a claim), or only the loop's event
  (`citation`, a claim).

## What `validate` checks

Three verdicts: **valid** (exactly what the loop gives now), **outdated** (the loop moved since the
document was projected, a new head or a changed source file, and projecting again gives every rung the
same status and the same claim: what it shows still holds, its details are not checked; project it
again), **invalid** (anything else, including a moved loop under which any status or claim changed).

1. The JSON Schema. 2. What the document shows on its own: ids, no cycle through prerequisites or
aliases, every criterion's verdict and strength from its targets, structural criteria from the rungs
they name, every status re-derived, every source link opens and agrees with its own roots (Codex H06).
3. By default, the loop itself: it is projected again from the sources the document names (its
curriculum or ladder, data home and checkout, at the checkout's HEAD), and every field must equal the
re-projection, source links included, so nothing the document supplies is trusted: a required target
left out, a scope or context narrowed, a claim event rewritten, an evidence item moved to another
commit. `--no-sources` checks only 1, 2 and that every link opens, which verifies no evidence. What it
cannot see: a defect the projector shares with its own re-projection (the tests carry that), and a
whole loop forged consistently at another path that the document names as its sources.

## Recognised conditions

An infra gate's sentence is matched against shapes this loop writes, each a predicate over data it
records: `no in_domain Codex blocker or major left on X` is an `audit` resting on the audit report the
rung's status event cites (its `VERDICT:` line, at the commit its own `candidate` line names, stale when
the code it cites changes); `identical verdict_hash over N judged MODE-mode runs at V m/s` rests on
those ledger rows (the runs the event names, else the newest N of one corpus, commit and ruler). The rest
of the sentence must name only acceptance suites, or it becomes a `stated` criterion, unknown until the
loop declares it (`"text_is_covered": true` on the gate).

## Commands

Run the tests (the real-data ones skip unless the loops are on this machine):

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV uv run --isolated --with pytest --with jsonschema python -m pytest -q -p no:cacheprovider vibetracks/roadmap/projector/tests
```

The rig loop lives in its own worktree, so name it for the real-data tests:

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV BAM_RIG_LOOP_DIR=$HOME/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop uv run --isolated --with pytest --with jsonschema python -m pytest -q -p no:cacheprovider vibetracks/roadmap/projector/tests
```

Project the kinsim loop from its own checkout (the loop is judged at that checkout's HEAD; data home
`$BAM_CURRICULUM_HOME` or `~/.local/share/bam_curriculum`); it validates its own output and refuses to
write an invalid one:

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector project kinsim --curriculum-dir ~/bam_ws/.claude/worktrees/wave-3-handoff-af2b9b/src/dev/bam_curriculum --out ~/bam_ws/reports/media/bam-roadmap-format-2026-10-03/kinsim.json
```

Project the rig loop:

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector project rig --rig-dir ~/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop --out ~/bam_ws/reports/media/bam-roadmap-format-2026-10-03/rig.json
```

Validate any `bam-roadmap/1` document against its loop now; exit 0 valid, 1 invalid, 2 unreadable loop
files, 3 outdated (`--details` lists what moved):

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector validate ~/bam_ws/reports/media/bam-roadmap-format-2026-10-03/kinsim.json ~/bam_ws/reports/media/bam-roadmap-format-2026-10-03/rig.json
```

Print one rung's proof as text:

```bash
cd ~/vibetracks
env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector show ~/bam_ws/reports/media/bam-roadmap-format-2026-10-03/kinsim.json EV1
```

## Files

| File | What it is |
|---|---|
| `schemas/bam-roadmap-1.schema.json` | the format, JSON Schema Draft 2020-12 |
| `model.py` | the vocabulary and the pure status rule (`derive_status`) |
| `kinsim.py`, `rig.py` | the two projectors (read-only) |
| `evaluate.py` | the one evaluator: what a piece of evidence earns now, and which commit it is bound to |
| `scope.py` | freshness scopes: a test's package, dependencies and import closure; a command's execution path |
| `proof.py` | events by line, choosing a target's evidence, the loop-wide test index, `support` and roles |
| `links.py`, `artifacts.py` | the one tested place free text is parsed (bam-citation-corpus/1, shared with the dashboard); readers that take results from the artifact, one run at a time |
| `validate.py`, `schema_check.py` | the validator: a stdlib subset of JSON Schema plus what a schema cannot say |
| `tests/` | fixtures in throwaway git repos for every rule, the `jsonschema` oracle, the real loops |

## What it cannot see yet (and the one loop-side change that fixes each)

- A gate run records no commit of its own, so its JUnit is a claim (a file time or git's reflog binds
  nothing, Codex H02). Fix: the gate writes `HEAD <sha>[ + dirty];` first in its console log (the loop's
  wrappers did at 658dabff and 3b8b85c2), or `"git": {"sha": ..., "dirty": false}` in `bam-gate-report/1`.
- An acceptance log with no `HEAD` line is a claim, whatever it shows. Fix: the same header.
- A log proves a file only when its own recorded command selected the file whole and it printed one
  outcome per test (pytest's per-file progress lines at default verbosity, or `-v`), all passes, agreeing
  with its summary (Codex H01). `pytest -q` prints no per-file outcome, so a `-q` run is at most a claim;
  a run of one node proves that node, not the file.
- The fast gate deselects `test_fast_tier_is_green_on_head` (it runs the gate itself), so no gate record
  covers all of `test_loop_tools_acceptance.py`. Fix: cite a full run of that file with its own header.
- A condition written in a sentence this format does not recognise is `stated` and stays unknown: kinsim
  RG1, VZ1, VZ4; every rig package's `acceptance`. Fix: `"text_is_covered": true` (kinsim) or
  `"acceptance_is_tests": true` (rig) when the acceptance files are the sentence.

The decision report with the options, the stock-part mapping and the worked examples is
`~/bam_ws/reports/bam-roadmap-format-2026-10-03.html`.
