// node:test checks for the media URL binding (mediaBinding.ts) and its one consumer seam (Dashboard.tsx).
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/shared/mediaBinding.check.mjs
// Pins (Codex audit 2026-10-05 round 4, finding 1): two viewers of one .vtdash share one backend, and each Dashboard's
// mediaUrl read a mutable backend-wide "latest revision", so the viewer that rendered last decided the other's links.
// Each binding must carry its own projection's revision whatever any other binding of the same backend does, and the
// Dashboard must key its binding on its own projection's revision. The browser half (tests/browser/two_viewers.mjs)
// drives two real viewers in one Clank window.

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const { bindMediaUrl, mediaRevision, mediaUrl } = await import('./mediaBinding.ts')

const backend = { baseUrl: '/api/plugins/vibetracks' }
const projection = (rev) => ({ schema: 'vibetracks-dashboard/1', media_rev: rev })
const revOf = (url) => new URL(url, 'http://x').searchParams.get('rev')

test('two viewers on ONE backend: each binding keeps its own projection revision, in any call order', () => {
  const older = bindMediaUrl(backend, mediaRevision(projection('OLD')))
  const newer = bindMediaUrl(backend, mediaRevision(projection('NEW')))
  // Interleaved as two viewers render: the newer one rendering must not move the older one, nor the reverse.
  assert.equal(revOf(older('clip')), 'OLD')
  assert.equal(revOf(newer('clip')), 'NEW')
  assert.equal(revOf(older('clip')), 'OLD', 'the older viewer still opens what it listed after the newer one rendered')
  const loading = bindMediaUrl(backend, mediaRevision(null))
  assert.equal(revOf(loading('clip')), null)
  assert.equal(revOf(older('clip')), 'OLD', 'a third viewer still loading (no projection yet) changes nothing either')
  assert.equal(revOf(newer('clip')), 'NEW')
})

test('the same backend object is never a revision store: binding never mutates the backend', () => {
  const frozen = Object.freeze({ baseUrl: '/b' })
  const bound = bindMediaUrl(frozen, 'R1')
  assert.equal(bound('a:b'), '/b/media/a%3Ab?rev=R1')
  assert.deepEqual(Object.keys(frozen), ['baseUrl'])
})

test('mediaUrl takes the revision it is given and nothing else; null gives the bare URL the backend refuses (409)', () => {
  assert.equal(mediaUrl(backend, 'run/1 clip', 'r e'), '/api/plugins/vibetracks/media/run%2F1%20clip?rev=r%20e')
  assert.equal(mediaUrl(backend, 'clip', null), '/api/plugins/vibetracks/media/clip')
})

test('mediaRevision reads only a non-empty string media_rev', () => {
  assert.equal(mediaRevision(projection('abc')), 'abc')
  for (const value of [undefined, null, '', 7, {}, []]) assert.equal(mediaRevision({ media_rev: value }), null, JSON.stringify(value))
  assert.equal(mediaRevision(null), null)
  assert.equal(mediaRevision(undefined), null)
})

// The consumer seam, read from source: these fail against 611ad59, where Dashboard memoised on the backend alone and
// api.ts kept a backend-wide WeakMap the hook wrote while rendering.
const here = new URL('.', import.meta.url)
const dashboard = readFileSync(new URL('../Dashboard.tsx', here), 'utf8')
const api = readFileSync(new URL('./api.ts', here), 'utf8')

test("Dashboard binds mediaUrl to its own projection's revision, with that revision in the memo key", () => {
  const revisionLine = dashboard.match(/const (\w+) = mediaRevision\(projection\)/)
  assert.ok(revisionLine, 'Dashboard reads the revision from the projection it renders')
  const name = revisionLine[1]
  assert.match(dashboard, new RegExp(`useMemo\\(\\(\\) => bindMediaUrl\\(backend, ${name}\\), \\[backend, ${name}\\]\\)`))
})

test('no backend-wide mutable media revision remains in the projection API', () => {
  assert.doesNotMatch(api, /WeakMap<PluginBackend,\s*string/)
  assert.doesNotMatch(api, /shownMediaRevision/)
})
