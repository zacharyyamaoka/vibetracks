// Every live title through the REAL copy-out exporter, read back by markdown-it: twins exactly where Markdown loses text.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/export_twins_live.mjs   (SKIPs cleanly without a lane or markdown-it)
//
// What it pins (verifier, 2026-10-05, item f): the copy's lossiness test flagged every "&" and "_", so live text such as
// "Sim to Real & Trajectory Tracking" and ids like "M5.contact_graspnet" got a redundant `exact …:` twin on every copy
// although a CommonMark parser reads them back unchanged. Here every live track title, item id, item title and option
// label (from /needs, plus every track and evidence item title in /projection) is put in its own line of a real export
// (exportTrack, the function Copy answers calls), the copy is parsed with markdown-it (an independent CommonMark
// parser), and each text is judged by what the parser reads back:
//   - read back exactly  -> must have NO twin   (a twin there is redundant)
//   - read back changed  -> must have its twin, and the twin must decode to the text exactly
// No browser is needed; nothing is written. Needs the lane only to read the live text.

import { existsSync } from 'node:fs'
import { createRequire, register } from 'node:module'
import { LANE, check, finish, skip } from './_lane.mjs'

const NAME = 'export_twins_live'
const MARKDOWN_IT_FROM = process.env.MARKDOWN_IT_FROM ?? '/home/bam/claude-transcript-viewer/package.json'
const NEEDS_DIR = new URL('../../clank/src/needs/', import.meta.url)

if (!existsSync(MARKDOWN_IT_FROM)) skip(NAME, `no markdown-it next to ${MARKDOWN_IT_FROM}`)
let MarkdownIt
try {
  MarkdownIt = createRequire(MARKDOWN_IT_FROM)('markdown-it')
} catch (error) {
  skip(NAME, `markdown-it not resolvable from ${MARKDOWN_IT_FROM} (${error instanceof Error ? error.message : error})`)
}
const md = new MarkdownIt()

// The app imports siblings without an extension (Vite resolves them); plain node needs `.ts`.
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
const rules = await import(new URL('answerRules.ts', NEEDS_DIR).href)
const exporter = await import(new URL('exportAnswers.ts', NEEDS_DIR).href)

const origin = new URL(LANE).origin
async function getJson(path) {
  try {
    const response = await fetch(`${origin}/api/plugins/vibetracks${path}`, { signal: AbortSignal.timeout(60000) })
    if (!response.ok) skip(NAME, `${path} answered HTTP ${response.status}`)
    return await response.json()
  } catch (error) {
    skip(NAME, `lane not reachable at ${origin} (${error instanceof Error ? error.message : error})`)
  }
}

const needs = await getJson('/needs')
const projection = await getJson('/projection')

// ------------------------------------------------------------------------------------------- the live texts
const texts = { 'track title': new Set(), id: new Set(), title: new Set(), 'option label': new Set() }
for (const doc of needs.tracks ?? []) {
  texts['track title'].add(doc.track_title)
  for (const item of doc.items ?? []) {
    texts.id.add(item.local_id)
    texts.title.add(item.title)
    for (const option of item.options ?? []) if (option.key !== 'other') texts['option label'].add(option.label)
  }
}
for (const track of projection.tracks ?? []) {
  texts['track title'].add(track.title)
  texts.id.add(track.id)
  for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
    for (const item of items) {
      texts.title.add(item.title)
      texts.id.add(item.id)
    }
  }
}

// ------------------------------------------------------------------------------------------- one export per text
const NOW = new Date('2026-10-05T12:00:00-07:00')
const CHAT = { kind: 'chat_paste', target: null, row_schema: null, read_back: null }

function makeItem({ id = 'T47', title = 'Plain title', label = 'Approve' } = {}) {
  return {
    id: `t:${id}`,
    local_id: id,
    kind: 'decision',
    title,
    ask: title,
    context_md: 'c',
    context_summary: null,
    context_base_md: 'c',
    context_lead_md: null,
    provenance_md: null,
    updates: [],
    options: [{ key: 'approve', label, detail_md: 'Do it.', recommended: false, is_default: false, source: 'dashboard' }],
    recommendation_md: null,
    default: { text_md: 'Wait.', applies: { unit: 'wave', after: 5 }, state: 'pending' },
    status: 'open',
    blocking: false,
    group: 'wants_you',
    evidence: [],
  }
}

function exportWith(field, text) {
  const item = makeItem(field === 'id' ? { id: text } : field === 'title' ? { title: text } : field === 'option label' ? { label: text } : {})
  const doc = {
    schema: 'vibetracks-needs/1',
    track: 't',
    track_title: field === 'track title' ? text : 'Track',
    generated_at: NOW.toISOString(),
    iteration: null,
    source: { adapter: 'check', paths: [], commit: null, live: false, note: null },
    answer_channel: CHAT,
    counts: {},
    items: [item],
  }
  const draft = rules.boundDraft(item, 'approve', '', NOW)
  const result = exporter.exportTrack(doc, (track, localId) => (track === 't' && localId === item.local_id ? draft : null), NOW)
  if (!result || !result.exported.length) throw new Error(`nothing exported for ${field} ${JSON.stringify(text)}`)
  return result.markdown
}

/** What markdown-it reads back from an inline token: text and code spans as written, markup markers dropped. */
function parsedText(inline) {
  return (inline.children ?? []).map((child) => (child.type === 'text' || child.type === 'code_inline' ? child.content : child.type === 'softbreak' ? '\n' : '')).join('')
}

/** [{label, value}] of the copy's `exact …:` lines, decoded from markdown-it's tokens. */
function twins(tokens) {
  const found = []
  for (const token of tokens) {
    if (token.type !== 'inline') continue
    const kids = token.children ?? []
    if (kids.length === 2 && kids[0].type === 'text' && /^exact( [a-z ]+)?: $/.test(kids[0].content) && kids[1].type === 'code_inline') {
      found.push({ label: kids[0].content.slice(0, -2), value: JSON.parse(kids[1].content) })
    }
  }
  return found
}

/** What the parser reads back for `text` in its own line, and the expected reading when nothing is lost. */
function readBack(field, tokens) {
  const inlineAfter = (type, tag) => tokens[tokens.findIndex((token) => token.type === type && token.tag === tag) + 1]
  if (field === 'track title') return parsedText(inlineAfter('heading_open', 'h1'))
  if (field === 'id' || field === 'title') return parsedText(inlineAfter('heading_open', 'h2'))
  const answer = tokens.find((token) => token.type === 'inline' && token.content.startsWith('**Answer:**'))
  return parsedText(answer)
}
function expected(field, text) {
  if (field === 'track title') return `Answers · ${text} · `
  if (field === 'id') return `${text} · Plain title`
  if (field === 'title') return `T47 · ${text}`
  return `Answer: ${text} (approve)`
}

let total = 0
let twinned = 0
const redundant = []
const missing = []
const wrong = []
for (const [field, set] of Object.entries(texts)) {
  for (const text of set) {
    if (typeof text !== 'string') continue
    // inlineExact writes a text with a line ending, CR or NUL as JSON on its own line: no twin by design, not judged here.
    if (/[\r\n\0]/.test(text) || rules.markdownIsLossy(text)) continue
    total++
    const tokens = md.parse(exportWith(field, text), {})
    const read = readBack(field, tokens)
    const exact = field === 'track title' ? read.startsWith(expected(field, text)) : read === expected(field, text)
    const twin = twins(tokens).filter((entry) => entry.label === `exact ${field}`)
    if (twin.length) twinned++
    if (exact && twin.length) redundant.push(`${field} ${JSON.stringify(text)}`)
    if (!exact && !twin.length) missing.push(`${field} ${JSON.stringify(text)} reads ${JSON.stringify(read)}`)
    if (twin.length && twin[0].value !== text) wrong.push(`${field} ${JSON.stringify(text)} twin ${JSON.stringify(twin[0].value)}`)
  }
}
console.log(`live texts judged: ${total}, with a twin: ${twinned} (${Object.entries(texts).map(([field, set]) => `${set.size} ${field}`).join(', ')})`)
for (const line of redundant.slice(0, 12)) console.log(`  redundant twin: ${line}`)
for (const line of missing.slice(0, 12)) console.log(`  lossy, no twin: ${line}`)
check(total > 0, `the lane has live titles to judge (${total})`)
check(redundant.length === 0, `no live text gets a redundant twin (${redundant.length})`)
check(missing.length === 0, `no live text Markdown changes is left without a twin (${missing.length})`)
check(wrong.length === 0, `every twin decodes to its text exactly (${wrong.length})`)
finish(NAME)
