// Named .check.mjs, not .test.mjs, so a whole-tree vitest run does not pick up this node:test file. Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/variants/a/proven.check.mjs
// WHY .mjs: tsc's program (tsconfig "include": ["src"], allowJs false) skips it, so it needs no @types/node, and Node
// strips the types of the .ts it imports.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { provenOf, provenText } from './proven.ts'

const bare = { counts: { by_status: { green: 1, done: 3, claimed: 15 } }, warnings: [] }

test('green + done from the projector counts, bare document', () => {
  assert.equal(provenText(bare), '4 proven')
})

test('the real widget wraps the document as {document, artNames}', () => {
  assert.equal(provenText({ document: bare, artNames: [] }), '4 proven')
})

test('a "stale…" warning marks it not current; other warnings do not', () => {
  assert.equal(provenText({ ...bare, warnings: ["stale: couldn't refresh the roadmap (x)"] }), '4 proven (not current)')
  assert.equal(provenText({ ...bare, warnings: ['planned ladder; no loop has run'] }), '4 proven')
})

test('zero proven is a real zero when both counts are present', () => {
  assert.equal(provenText({ counts: { by_status: { green: 0, done: 0 } } }), '0 proven')
})

test('absent or malformed counts say nothing (never 0)', () => {
  for (const doc of [null, undefined, 'x', [], {}, { counts: {} }, { counts: { by_status: { green: 2 } } }, { counts: { by_status: { green: '2', done: 1 } } }, { counts: { by_status: { green: -1, done: 1 } } }, { counts: { by_status: { green: 1.5, done: 1 } } }]) {
    assert.equal(provenText(doc), null, JSON.stringify(doc))
    assert.equal(provenOf(doc), null)
  }
})

test('rung statuses are never recounted', () => {
  const doc = { counts: { by_status: { green: 1, done: 0 } }, rungs: [{ status: 'green' }, { status: 'green' }, { status: 'done' }] }
  assert.equal(provenText(doc), '1 proven')
})
