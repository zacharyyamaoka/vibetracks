// node:test checks for the pure draft rules (answerRules.ts) and the copy-out text (exportAnswers.ts).
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/needs/answers.check.mjs
// WHY `.check.mjs` and not `.test.mjs`: a peer's vitest run picks up *.test.* and would run this under its own loader.
// WHY markdown-it as the oracle for the Markdown round trip: it is an independent CommonMark parser, so "the note comes
// back exactly" is measured by something other than the code that wrote it.
// Regressions these pin (Codex audit 2026-10-04): finding 1 (a draft outlived a changed question and a settled item,
// and still exported), finding 7 (notes were trimmed and folded to one line; a note alone exported an unoffered `other`).

import { register, createRequire } from 'node:module'
import { test } from 'node:test'
import assert from 'node:assert/strict'

// The app imports siblings without an extension (Vite resolves them); plain node needs `.ts`. Only relative,
// extensionless specifiers are rewritten.
register(
  'data:text/javascript,' +
    encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if ((specifier.startsWith('./') || specifier.startsWith('../')) && !/\\.[cm]?[jt]sx?$/.test(specifier)) {
    try { return await next(specifier + '.ts', context) } catch {}
  }
  return next(specifier, context)
}`),
  import.meta.url,
)

const rules = await import('./answerRules.ts')
const exporter = await import('./exportAnswers.ts')
const MarkdownIt = createRequire('/home/bam/claude-transcript-viewer/package.json')('markdown-it')
const md = new MarkdownIt()

const NOW = new Date('2026-10-04T19:20:11-07:00')

function option(key, label, detail = null, extra = {}) {
  return { key, label, detail_md: detail, recommended: key === 'accept_recommendation', is_default: key === 'use_default', source: 'dashboard', ...extra }
}

function makeItem(overrides = {}) {
  return {
    id: 'kinsim:T47',
    local_id: 'T47',
    kind: 'decision',
    title: 'Bus voltage for the bench?',
    ask: 'Bus voltage for the bench?',
    context_md: 'The bench browns out at 40 V.',
    context_summary: null,
    context_base_md: 'The bench browns out at 40 V.',
    context_lead_md: null,
    provenance_md: null,
    updates: [],
    options: [
      option('accept_recommendation', 'Go with the recommendation', 'Run the bench at 44 V.'),
      option('use_default', 'Let the default apply', 'Stay at 40 V.'),
      option('other', 'Something else (write it)', null, { needs_note: true }),
    ],
    recommendation_md: 'Run the bench at 44 V.',
    default: { text_md: 'Stay at 40 V.', applies: { unit: 'wave', after: 5 }, state: 'pending' },
    blocks: [],
    blocking_now: false,
    group: 'waiting',
    evidence: [],
    asked_by: { agent: null, session: null, account: null },
    created: { iteration: 3, ts: null },
    updated: { ts: null, note: null },
    status: 'open',
    raw_status: 'open',
    answer: null,
    effort: null,
    ...overrides,
  }
}

function makeDoc(items, channel = {}) {
  return {
    schema: 'vibetracks-needs/1',
    track: 'kinsim',
    track_title: 'Kinematic Sim',
    generated_at: '2026-10-04T19:00:00-07:00',
    iteration: { unit: 'wave', n: 4, phase: 'running', finished: 3 },
    source: { adapter: 'kinsim', paths: ['/x/triage.json'], commit: null, live: true, note: null },
    answer_channel: { kind: 'jsonl_append', target: '/x/triage_answers.jsonl', row_schema: 'bam-triage-answer/1', read_back: null, ...channel },
    counts: { open: 1, blocking_now: 0, wants_you: 1, no_default: 0, waiting: 1, defaulting: 0, answered: 0, defaulted: 0, closed: 0, total: 1 },
    items,
  }
}

const CHAT = { kind: 'chat_paste', target: 'the rig chat', row_schema: null }
const lookup = (draft) => () => draft

function fences(markdown) {
  return md.parse(markdown, {}).filter((token) => token.type === 'fence')
}

// ------------------------------------------------------------------------------------------- finding 1: stale drafts

test('a draft bound to the question as reviewed is live and exports', () => {
  const item = makeItem()
  const draft = rules.boundDraft(item, 'accept_recommendation', '', NOW)
  assert.equal(rules.draftState(draft, item).stale, null)
  const result = exporter.exportTrack(makeDoc([item]), lookup(draft), NOW)
  assert.deepEqual(result.exported, ['kinsim:T47'])
  assert.match(result.markdown, /> Run the bench at 44 V\./)
})

test('a changed recommendation makes the draft stale: never live, never exported, named as left out', () => {
  const reviewed = makeItem()
  const draft = rules.boundDraft(reviewed, 'accept_recommendation', 'ok', NOW)
  // The audit's probe: the same item's recommendation moves from 44 V to 46 V after Zach drafted.
  const changed = makeItem({
    recommendation_md: 'Run the bench at 46 V.',
    options: [option('accept_recommendation', 'Go with the recommendation', 'Run the bench at 46 V.'), ...reviewed.options.slice(1)],
  })
  const state = rules.draftState(draft, changed)
  assert.equal(state.live, null)
  assert.equal(state.stale.reason, 'changed')
  assert.equal(state.stale.reconfirmable, true)
  assert.equal(rules.liveDraft(draft, changed), null)
  assert.equal(rules.isComplete(rules.liveDraft(draft, changed)), false)
  const result = exporter.exportTrack(makeDoc([changed]), lookup(draft), NOW)
  assert.deepEqual(result.exported, [])
  assert.equal(result.markdown, '')
  assert.doesNotMatch(result.markdown, /46 V/)
  assert.equal(result.skipped.length, 1)
  assert.match(result.skipped[0].reason, /question changed/)
})

test('any reviewed field changing makes the draft stale; computed fields do not', () => {
  const item = makeItem()
  const draft = rules.boundDraft(item, 'use_default', '', NOW)
  const reviewedChanges = {
    title: { title: 'Bus voltage?' },
    ask: { ask: 'Which bus voltage?' },
    context: { context_md: 'The bench browns out at 40 V.\n\nUPDATE wave 4: it also trips at 42 V.' },
    option_words: { options: [item.options[0], option('use_default', 'Let the default apply', 'Stay at 38 V.'), item.options[2]] },
    option_set: { options: item.options.filter((candidate) => candidate.key !== 'accept_recommendation') },
    default_text: { default: { ...item.default, text_md: 'Stay at 38 V.' } },
    default_when: { default: { ...item.default, applies: { unit: 'wave', after: 6 } } },
  }
  for (const [name, change] of Object.entries(reviewedChanges)) {
    assert.equal(rules.draftState(draft, makeItem(change)).stale?.reason, 'changed', name)
  }
  const computedChanges = {
    group: { group: 'defaulting' },
    state: { default: { ...item.default, state: 'in_effect' } },
    blocking: { blocking_now: true, group: 'blocking' },
    updated: { updated: { ts: '2026-10-05T01:00:00Z', note: 'touched' } },
  }
  for (const [name, change] of Object.entries(computedChanges)) {
    assert.equal(rules.draftState(draft, makeItem(change)).stale, null, name)
  }
})

test('a tampered stored fingerprint (what the in-app probe does) reads as changed', () => {
  const item = makeItem()
  const stored = JSON.stringify({ ...rules.boundDraft(item, 'accept_recommendation', 'x', NOW), fingerprint: 'v1:tampered' })
  const draft = rules.parseStoredDraft(stored)
  assert.equal(rules.draftState(draft, item).stale.reason, 'changed')
})

test('a settled item makes the draft stale, whatever the fingerprint: answered, closed, superseded, defaulted', () => {
  const open = makeItem()
  const draft = rules.boundDraft(open, 'accept_recommendation', 'yes', NOW)
  for (const status of ['answered', 'closed', 'superseded', 'defaulted']) {
    const settled = makeItem({ status, group: status === 'answered' ? 'answered' : 'done' })
    const state = rules.draftState(draft, settled)
    assert.equal(state.live, null, status)
    assert.equal(state.stale.reason, 'settled', status)
    assert.equal(state.stale.reconfirmable, false, status)
    assert.equal(rules.isAnswerable(settled), false, status)
    const result = exporter.exportTrack(makeDoc([settled]), lookup(draft), NOW)
    assert.deepEqual(result.exported, [], status)
    assert.match(result.skipped[0].reason, new RegExp(`settled this \\(${status}\\)`), status)
  }
})

test('a draft saved before binding (no fingerprint) is stale "unbound" until reconfirmed', () => {
  const item = makeItem()
  const legacy = rules.parseStoredDraft(JSON.stringify({ choice: 'accept_recommendation', note: '', updated: '2026-10-03T00:00:00Z' }))
  assert.equal(legacy.fingerprint, null)
  assert.equal(rules.draftState(legacy, item).stale.reason, 'unbound')
  assert.deepEqual(exporter.exportTrack(makeDoc([item]), lookup(legacy), NOW).exported, [])
})

test('Reconfirm re-binds to the question as it reads now, and the copy then quotes the CURRENT words', () => {
  const reviewed = makeItem()
  const draft = rules.boundDraft(reviewed, 'accept_recommendation', 'ok', NOW)
  const changed = makeItem({ options: [option('accept_recommendation', 'Go with the recommendation', 'Run the bench at 46 V.'), ...reviewed.options.slice(1)] })
  assert.ok(rules.draftState(draft, changed).stale)
  // What the store's reconfirm() writes.
  const reconfirmed = rules.boundDraft(changed, draft.choice, draft.note, NOW)
  assert.equal(rules.draftState(reconfirmed, changed).stale, null)
  const result = exporter.exportTrack(makeDoc([changed]), lookup(reconfirmed), NOW)
  assert.deepEqual(result.exported, ['kinsim:T47'])
  assert.match(result.markdown, /> Run the bench at 46 V\./)
})

test('a stale draft whose option is gone cannot be reconfirmed', () => {
  const reviewed = makeItem()
  const draft = rules.boundDraft(reviewed, 'accept_recommendation', '', NOW)
  const changed = makeItem({ options: reviewed.options.slice(1) })
  const stale = rules.draftState(draft, changed).stale
  assert.equal(stale.reason, 'changed')
  assert.equal(stale.reconfirmable, false)
})

// ------------------------------------------------------------------------------------------- finding 7: exact notes

const NASTY_NOTES = {
  audit: '  Keep 44 V.\nRun:\n```python\nprint(44)\n```\n\n  trailing spaces   \n',
  four_backticks: 'a ```` b\n````\nend',
  heading_like: '# not a heading\n- not a list\n> not a quote',
  inline_markup: '*not italic* and **not bold** and <b>not html</b>',
  only_space_edges: '\n\nmiddle\n\n',
  tabs: '\tindented with a tab\n    four spaces',
}

for (const [name, note] of Object.entries(NASTY_NOTES)) {
  test(`note "${name}" round-trips exactly through Markdown (CommonMark oracle) and JSONL`, () => {
    const item = makeItem()
    const draft = rules.boundDraft(item, 'use_default', note, NOW)
    const result = exporter.exportTrack(makeDoc([item]), lookup(draft), NOW)
    assert.deepEqual(result.exported, ['kinsim:T47'])
    const blocks = fences(result.markdown)
    const noteBlocks = blocks.filter((token) => token.info === 'text')
    assert.equal(noteBlocks.length, 1)
    // CommonMark gives a fenced block's literal with one final newline: the note is everything before it.
    assert.equal(noteBlocks[0].content, `${note}\n`)
    const rowBlocks = blocks.filter((token) => token.info === 'jsonl')
    assert.equal(rowBlocks.length, 1)
    const rows = rowBlocks[0].content.trimEnd().split('\n').map((line) => JSON.parse(line))
    assert.deepEqual(rows, [{ ts: '2026-10-04T19:20:11-07:00', triage_id: 'T47', choice: 'use_default', note }])
    // Nothing in the note broke the surrounding structure: still one item heading.
    assert.equal(md.parse(result.markdown, {}).filter((token) => token.type === 'heading_open' && token.tag === 'h2').length, 1)
  })
}

test('two answers with nasty notes stay two sections, each note exact', () => {
  const first = makeItem()
  const second = makeItem({ id: 'kinsim:T48', local_id: 'T48', title: 'Second?' })
  const notes = { T47: NASTY_NOTES.audit, T48: NASTY_NOTES.four_backticks }
  const result = exporter.exportTrack(makeDoc([first, second]), (_track, localId) => rules.boundDraft(localId === 'T47' ? first : second, 'other', notes[localId], NOW), NOW)
  assert.deepEqual(result.exported, ['kinsim:T47', 'kinsim:T48'])
  assert.deepEqual(fences(result.markdown).filter((token) => token.info === 'text').map((token) => token.content), [`${notes.T47}\n`, `${notes.T48}\n`])
})

test('a stored note keeps its edge whitespace and line breaks through parseStoredDraft', () => {
  const note = NASTY_NOTES.audit
  assert.equal(rules.parseStoredDraft(JSON.stringify({ choice: null, note, updated: '' })).note, note)
})

// ------------------------------------------------------------------------------------------- finding 7: offered choices

function approveOnly(overrides = {}) {
  // grasping's download approvals offer `approve` and the dashboard's implicit options; this fixture drops `other`.
  return makeItem({ id: 'grasping:M5.ggcnn', local_id: 'M5.ggcnn', options: [option('approve', 'Approve the download', null)], ...overrides })
}

test('a note alone on an item without "other" never becomes other', () => {
  const item = approveOnly()
  const draft = rules.liveDraft(rules.boundDraft(item, null, 'Only after the licence check.', NOW), item)
  assert.equal(draft.offersOther, false)
  assert.equal(rules.effectiveChoice(draft), null)
  assert.equal(rules.isComplete(draft), false)
  assert.equal(rules.isNoteOnly(draft), true)
})

test('a note-only draft exports as a note with no option where the channel carries that (markdown only)', () => {
  const item = approveOnly()
  const note = 'Only after the licence check.\n  (keep the indent)'
  const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, null, note, NOW)), NOW)
  assert.deepEqual(result.exported, ['grasping:M5.ggcnn'])
  assert.match(result.markdown, /- \*\*Answer:\*\* no option chosen \(note only\)/)
  assert.doesNotMatch(result.markdown, /\bother\b|Something else/)
  assert.equal(fences(result.markdown).find((token) => token.info === 'text').content, `${note}\n`)
  assert.equal(fences(result.markdown).some((token) => token.info === 'jsonl'), false)
})

test('a note-only draft on a channel whose rows need an option is left out and named, never exported as other', () => {
  const item = approveOnly()
  const result = exporter.exportTrack(makeDoc([item]), lookup(rules.boundDraft(item, null, 'words', NOW)), NOW)
  assert.deepEqual(result.exported, [])
  assert.deepEqual(result.skipped, [{ id: 'grasping:M5.ggcnn', reason: exporter.NOTE_ONLY_NEEDS_OPTION }])
  assert.doesNotMatch(result.markdown, /other/)
})

test('a stored choice the item does not offer is dropped; the note is kept and never re-labelled other', () => {
  const item = approveOnly()
  const forged = { ...rules.boundDraft(item, null, 'my words', NOW), choice: 'other' }
  const live = rules.liveDraft(forged, item)
  assert.equal(live.choice, null)
  assert.equal(live.note, 'my words')
  assert.equal(rules.effectiveChoice(live), null)
  for (const doc of [makeDoc([item]), makeDoc([item], CHAT)]) {
    const result = exporter.exportTrack(doc, lookup(forged), NOW)
    assert.doesNotMatch(result.markdown, /\(other\)|"choice":"other"/)
  }
})

test('every exported choice is one the item offers', () => {
  const items = [makeItem(), approveOnly(), makeItem({ id: 'kinsim:T9', local_id: 'T9', options: [option('use_default', 'Keep waiting (no default)', null)] })]
  const choices = ['accept_recommendation', 'approve', 'use_default', 'other', null]
  for (const item of items) {
    for (const choice of choices) {
      for (const note of ['', 'n']) {
        const draft = { ...rules.boundDraft(item, null, note, NOW), choice }
        for (const doc of [makeDoc([item]), makeDoc([item], CHAT)]) {
          const result = exporter.exportTrack(doc, lookup(draft), NOW)
          const offered = new Set(item.options.map((candidate) => candidate.key))
          for (const match of (result?.markdown ?? '').matchAll(/- \*\*Answer:\*\* .*\((\w+)\)$/gm)) {
            if (match[1] !== 'note') assert.ok(offered.has(match[1]), `${item.local_id} exported unoffered ${match[1]}`)
          }
          for (const token of fences(result?.markdown ?? '').filter((candidate) => candidate.info === 'jsonl')) {
            for (const line of token.content.trimEnd().split('\n')) assert.ok(offered.has(JSON.parse(line).choice))
          }
        }
      }
    }
  }
})
