// node:test checks for the pure draft rules (answerRules.ts) and the copy-out text (exportAnswers.ts).
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/needs/answers.check.mjs
// WHY `.check.mjs` and not `.test.mjs`: a peer's vitest run picks up *.test.* and would run this under its own loader.
// WHY markdown-it as the oracle for the Markdown round trip: it is an independent CommonMark parser, so "the note comes
// back exactly" is measured by something other than the code that wrote it.
// Regressions these pin (Codex audit 2026-10-04): finding 1 (a draft outlived a changed question and a settled item,
// and still exported), finding 7 (notes were trimmed and folded to one line; a note alone exported an unoffered `other`);
// round 2 (2026-10-05) finding 3 (a lone CR let the note escape its fence, CRLF was unrecoverable on Markdown-only
// channels, and the option's words were trimmed). 31 of these fail against b53567e's exporter. Verifier 2026-10-05: an
// item title's edge spaces were lost in the parsed heading; the `exact title:` checks at the end fail against d579e39.

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

// ------------------------------------------------------------------------------------------- round 2, finding 3
// Codex audit 2026-10-05 (round 2) finding 3: the note formatter split on LF only, so "a\rb" put `b` outside the fenced
// block (a CommonMark parser ends a line at a lone CR too); CRLF came back as LF with nothing to recover it from on a
// Markdown-only channel; and the option's words were trim()med. Each check below parses the copy with markdown-it (an
// independent CommonMark parser) AND checks the source lines strictly, so a regression fails here, at the exporter that
// builds the clipboard text, not only in a helper.

const NOTE_PASTE = { kind: 'note_paste', target: 'Projects/Detection/Answers.md', row_schema: null }
const JSONL = {}
const CHANNELS = { chat_paste: CHAT, note_paste: NOTE_PASTE, jsonl_append: JSONL }

/** What any CommonMark parser makes of the text inside a fenced block: CR and CRLF end lines, NUL becomes U+FFFD. */
const commonmarkLiteral = (text) => `${text.replace(/\r\n|\r/g, '\n').replace(/\0/g, '�')}\n`

/** The `exact: …` twins in the copy, decoded: [{label, value}], read from markdown-it's tokens, never by regex on the
 * source, so the line must parse as `label: ` followed by ONE code span holding a JSON string. */
function exactTwins(markdown) {
  const twins = []
  for (const token of md.parse(markdown, {})) {
    if (token.type !== 'inline') continue
    const kids = token.children ?? []
    if (kids.length === 2 && kids[0].type === 'text' && /^exact( option words| title| id| option label| track title)?: $/.test(kids[0].content) && kids[1].type === 'code_inline') {
      twins.push({ label: kids[0].content.slice(0, -2), value: JSON.parse(kids[1].content) })
    }
  }
  return twins
}

/** Strict structure: every line of the copy is a heading, the header comment, a list item, list-item content (two
 * spaces in), a jsonl fence line, or blank. A line that escaped its block starts at column 0 with anything else. */
function assertContained(markdown) {
  let inRows = false
  for (const line of markdown.split('\n')) {
    if (line === '```jsonl') inRows = true
    else if (inRows && line === '```') inRows = false
    else if (inRows) assert.ok(line.startsWith('{'), `jsonl fence holds only rows: ${JSON.stringify(line)}`)
    else assert.match(line, /^(# |## |<!-- |- \*\*|  |$)/, `line escaped its block: ${JSON.stringify(line)}`)
  }
  assert.ok(!markdown.includes('\r'), 'the copy holds no raw CR: every line ending is LF')
}

const CR_NOTES = {
  lone_cr: 'a\rb',
  crlf: 'a\r\nb',
  mixed: 'x\r\n\r\ny\rz\n',
  only_cr: '\r',
  cr_then_fence: 'a\r```\r# not a heading',
  nul: 'a\u0000b',
}

for (const [name, note] of Object.entries(CR_NOTES)) {
  for (const [channelName, channel] of Object.entries(CHANNELS)) {
    test(`note "${name}" on ${channelName}: stays inside its block, and the copy can give it back exactly`, () => {
      const item = makeItem()
      const result = exporter.exportTrack(makeDoc([item], channel), lookup(rules.boundDraft(item, 'use_default', note, NOW)), NOW)
      assert.deepEqual(result.exported, ['kinsim:T47'])
      assertContained(result.markdown)
      const tokens = md.parse(result.markdown, {})
      assert.equal(tokens.filter((token) => token.type === 'heading_open' && token.tag === 'h2').length, 1)
      const noteBlocks = fences(result.markdown).filter((token) => token.info === 'text')
      assert.equal(noteBlocks.length, 1)
      assert.equal(noteBlocks[0].content, commonmarkLiteral(note), 'the whole note, and nothing else, is in the block')
      // Nothing of the note became a paragraph of its own (b escaping the fence did exactly that).
      const paragraphs = tokens.filter((token) => token.type === 'inline' && !token.content.startsWith('exact')).map((token) => token.content)
      assert.ok(!paragraphs.some((text) => text === 'b' || text.startsWith('b') || text.includes('not a heading')), JSON.stringify(paragraphs))
      const twins = exactTwins(result.markdown)
      if (channelName === 'jsonl_append') {
        // The row carries the raw string; no twin is added.
        assert.deepEqual(twins, [])
        const rows = fences(result.markdown).find((token) => token.info === 'jsonl').content.trimEnd().split('\n').map((line) => JSON.parse(line))
        assert.equal(rows[0].note, note)
      } else {
        assert.deepEqual(twins, [{ label: 'exact', value: note }], 'a Markdown-only channel carries the exact twin')
      }
    })
  }
}

test('a note Markdown carries exactly gets no exact twin (ordinary answers stay compact)', () => {
  const item = makeItem()
  for (const note of Object.values(NASTY_NOTES)) {
    const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, 'use_default', note, NOW)), NOW)
    assert.deepEqual(exactTwins(result.markdown), [], JSON.stringify(note))
  }
})

test('a note-only draft with a CR on a chat channel keeps its twin', () => {
  const item = approveOnly()
  const note = 'only after\r\nthe licence check'
  const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, null, note, NOW)), NOW)
  assertContained(result.markdown)
  assert.deepEqual(exactTwins(result.markdown), [{ label: 'exact', value: note }])
})

const OPTION_WORDS = {
  edge_spaces_crlf: '  first\r\n\r\nlast  ',
  edge_spaces: '  keep my spaces  ',
  lone_cr: 'Run at 44 V.\rThen log it.',
  whitespace_only: '   ',
  plain_multiline: 'Run at 44 V.\n\n- then log it\n- and stop',
}

for (const [name, words] of Object.entries(OPTION_WORDS)) {
  for (const [channelName, channel] of Object.entries(CHANNELS)) {
    test(`option words "${name}" on ${channelName}: quoted untrimmed, line for line, inside the quote`, () => {
      const item = makeItem({ options: [option('accept_recommendation', 'Go with the recommendation', words), ...makeItem().options.slice(1)] })
      const note = 'my note'
      const result = exporter.exportTrack(makeDoc([item], channel), lookup(rules.boundDraft(item, 'accept_recommendation', note, NOW)), NOW)
      assert.deepEqual(result.exported, ['kinsim:T47'])
      assertContained(result.markdown)
      // Source level: the quote lines, prefix removed, are the option's lines exactly (no trim, no dropped spaces).
      const section = result.markdown.split('\n')
      const start = section.findIndex((line) => line.startsWith('- **Answer:**')) + 1
      const quoted = []
      for (let i = start; i < section.length && section[i].startsWith('  >'); i++) quoted.push(section[i].replace(/^  >(?: |$)/, ''))
      assert.deepEqual(quoted, words.split(/\r\n|\r|\n/))
      // Parse level: one blockquote, the note's fence after it, and nothing of the twin inside the quote.
      const tokens = md.parse(result.markdown, {})
      assert.equal(tokens.filter((token) => token.type === 'blockquote_open').length, 1)
      const quoteEnd = tokens.findIndex((token) => token.type === 'blockquote_close')
      const inside = tokens.slice(0, quoteEnd).filter((token) => token.type === 'inline').map((token) => token.content).join('\n')
      assert.doesNotMatch(inside, /exact/)
      assert.equal(fences(result.markdown).find((token) => token.info === 'text').content, `${note}\n`)
      const lossy = /\r/.test(words) || words !== words.trim()
      assert.deepEqual(exactTwins(result.markdown), lossy ? [{ label: 'exact option words', value: words }] : [])
    })
  }
}

test('an empty note exports no note block and no twin; "other" with an empty note is left out and named', () => {
  const item = makeItem()
  for (const [channelName, channel] of Object.entries(CHANNELS)) {
    const result = exporter.exportTrack(makeDoc([item], channel), lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
    assert.deepEqual(result.exported, ['kinsim:T47'], channelName)
    assertContained(result.markdown)
    assert.doesNotMatch(result.markdown, /\*\*Note:\*\*/, channelName)
    assert.equal(fences(result.markdown).filter((token) => token.info === 'text').length, 0, channelName)
    assert.deepEqual(exactTwins(result.markdown), [], channelName)
    if (channelName === 'jsonl_append') {
      const row = JSON.parse(fences(result.markdown).find((token) => token.info === 'jsonl').content.trimEnd())
      assert.equal(row.note, '')
    }
    const other = exporter.exportTrack(makeDoc([item], channel), lookup(rules.boundDraft(item, 'other', '', NOW)), NOW)
    assert.deepEqual(other.exported, [], channelName)
    assert.deepEqual(other.skipped, [{ id: 'kinsim:T47', reason: '"Something else" needs a note' }], channelName)
  }
})

test("the loop's title, id and option label can never break their one line: a line ending is shown as JSON", () => {
  const title = 'Bus voltage?\n# injected heading\r\n- injected item'
  const item = makeItem({ title, options: [option('use_default', 'Keep\rwaiting', 'Stay at 40 V.'), ...makeItem().options.slice(2)] })
  const doc = { ...makeDoc([item], CHAT), track_title: 'Kinematic\nSim', source: { adapter: 'kinsim', paths: ['/x/a-->b.json'], commit: null, live: true, note: null } }
  const result = exporter.exportTrack(doc, lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
  assertContained(result.markdown)
  const tokens = md.parse(result.markdown, {})
  assert.equal(tokens.filter((token) => token.type === 'heading_open').length, 2, 'the H1 and one H2, nothing injected')
  assert.equal(tokens.filter((token) => token.type === 'bullet_list_open').length, 1)
  const h2 = tokens[tokens.findIndex((token) => token.type === 'heading_open' && token.tag === 'h2') + 1]
  assert.equal(JSON.parse(h2.children.find((child) => child.type === 'code_inline').content), title)
  // With raw HTML on (as a chat renderer may have it), the header comment is one html block that ends where it should.
  const comment = new MarkdownIt({ html: true }).parse(result.markdown, {}).find((token) => token.type === 'html_block')
  assert.ok(comment.content.trimEnd().endsWith('-->') && comment.content.indexOf('-->') === comment.content.lastIndexOf('-->'), comment.content)
  assert.match(result.markdown, /`"Keep\\rwaiting"` \(use_default\)/)
})

test('plain titles and labels are left exactly as written (no code span, no trimming)', () => {
  const item = makeItem({ title: '  Bus *voltage*?  ' })
  const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
  assert.ok(result.markdown.includes('## T47 ·   Bus *voltage*?  \n'))
  assert.ok(result.markdown.includes('- **Answer:** Let the default apply (use_default)'))
})

// ------------------------------------------------------------------------------------------- verifier 2026-10-05: titles

/** What a CommonMark reader gets back from a heading or paragraph: its inline text, markup markers dropped. */
function parsedText(inlineToken) {
  return (inlineToken.children ?? []).map((child) => (child.type === 'text' || child.type === 'code_inline' ? child.content : child.type === 'softbreak' ? '\n' : '')).join('')
}

const EDGE_TITLES = {
  trailing: 'Bus voltage?  ',
  leading: '  Bus voltage?',
  both: '  Bus voltage?  ',
  tab: 'Bus voltage?\t',
  whitespace_only: '   ',
  nbsp: 'Bus voltage?\u00a0',
}

for (const [name, title] of Object.entries(EDGE_TITLES)) {
  for (const [channelName, channel] of Object.entries(CHANNELS)) {
    test(`title "${name}" on ${channelName}: the heading keeps it as written, and an exact title twin gives it back`, () => {
      const item = makeItem({ title })
      const result = exporter.exportTrack(makeDoc([item], channel), lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
      assert.deepEqual(result.exported, ['kinsim:T47'])
      assertContained(result.markdown)
      // Source level: the heading line holds every character of the title, untrimmed.
      assert.ok(result.markdown.split('\n').includes(`## T47 · ${title}`), JSON.stringify(result.markdown))
      // Parse level: still one H2, one answer list, and the twin is the title exactly.
      const tokens = md.parse(result.markdown, {})
      assert.equal(tokens.filter((token) => token.type === 'heading_open' && token.tag === 'h2').length, 1)
      assert.equal(tokens.filter((token) => token.type === 'bullet_list_open').length, 1)
      assert.deepEqual(exactTwins(result.markdown), [{ label: 'exact title', value: title }])
    })
  }
}

// The oracle: whatever the title, a reader of the parsed copy can recover it exactly, from the heading itself or from
// its twin; and a title the heading already carries exactly gets no twin.
const ANY_TITLES = [
  'Bus voltage for the bench?',
  'Run slow_step_045deg_slow at 44 V',
  'Is *this* the gate?',
  '_why_ not',
  'Use `uv run` here?',
  'Link [the report](x.html)?',
  'a <b>bold</b> ask',
  'Tom &amp; Jerry',
  'C:\\path\\to',
  'Issue #',
  'Issue #12',
  '~~struck~~ ask',
  'two  spaces inside',
]

test('any title: the parsed heading or its exact title twin gives the title back exactly; plain titles get no twin', () => {
  for (const title of ANY_TITLES) {
    const item = makeItem({ title })
    const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
    assertContained(result.markdown)
    const tokens = md.parse(result.markdown, {})
    const h2 = tokens[tokens.findIndex((token) => token.type === 'heading_open' && token.tag === 'h2') + 1]
    const heading = parsedText(h2)
    const twins = exactTwins(result.markdown).filter((twin) => twin.label === 'exact title')
    if (heading === `T47 · ${title}`) {
      // Carried exactly: a twin would only be noise, and must at least agree.
      assert.ok(twins.length === 0 || twins[0].value === title, JSON.stringify(title))
    } else {
      assert.deepEqual(twins, [{ label: 'exact title', value: title }], `the heading reads ${JSON.stringify(heading)} for ${JSON.stringify(title)}`)
    }
  }
  for (const title of ['Bus voltage for the bench?', 'two  spaces inside', 'Issue #12']) {
    const item = makeItem({ title })
    const result = exporter.exportTrack(makeDoc([item], CHAT), lookup(rules.boundDraft(item, 'use_default', '', NOW)), NOW)
    assert.deepEqual(exactTwins(result.markdown), [], JSON.stringify(title))
  }
})

test("an option label or track title Markdown would change gets its twin; the answer list and quote stay intact", () => {
  const label = '  Keep *waiting*  '
  const item = makeItem({ options: [option('use_default', label, 'Stay at 40 V.'), ...makeItem().options.slice(2)] })
  for (const [channelName, channel] of Object.entries(CHANNELS)) {
    const doc = { ...makeDoc([item], channel), track_title: 'Kinematic_Sim ' }
    const result = exporter.exportTrack(doc, lookup(rules.boundDraft(item, 'use_default', 'n', NOW)), NOW)
    assertContained(result.markdown)
    assert.ok(result.markdown.includes(`- **Answer:** ${label} (use_default)`), channelName)
    const twins = exactTwins(result.markdown)
    assert.deepEqual(twins.find((twin) => twin.label === 'exact option label'), { label: 'exact option label', value: label }, channelName)
    assert.deepEqual(twins.find((twin) => twin.label === 'exact track title'), { label: 'exact track title', value: 'Kinematic_Sim ' }, channelName)
    const tokens = md.parse(result.markdown, {})
    assert.equal(tokens.filter((token) => token.type === 'bullet_list_open').length, 1, channelName)
    assert.equal(tokens.filter((token) => token.type === 'blockquote_open').length, 1, channelName)
    assert.equal(fences(result.markdown).find((token) => token.info === 'text').content, 'n\n', channelName)
    const comment = new MarkdownIt({ html: true }).parse(result.markdown, {}).find((token) => token.type === 'html_block')
    assert.ok(comment && comment.content.startsWith('<!-- vibetracks-needs/1'), channelName)
  }
})
