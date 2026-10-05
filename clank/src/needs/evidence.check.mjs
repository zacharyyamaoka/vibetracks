// node:test checks for where a Needs evidence link opens (evidence.ts), and that no Needs file reaches for /media.
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/needs/evidence.check.mjs
// Pins Codex audit 2026-10-05 round 3, finding 1: with an OLD Needs document and a NEW projection whose media listed
// the same path, e0bd8e5's evidenceHref() returned `/media/clip?rev=NEW` (the projection's revision), bypassing the
// document's eid + evidence_rev binding and its 409 reload line. On e0bd8e5 evidence.ts does not exist, and its
// evidenceHref (EvidenceLink.tsx) took the projection and returned /media for these entries. The browser half, on the
// real page, is tests/browser/needs_evidence_bound.mjs; the route half is tests/test_dashboard_needs_evidence_bound.py.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const { evidenceHref, evidencePath, evidenceUrl } = await import('./evidence.ts')

const backend = { baseUrl: '/api/plugins/vibetracks' }
const OLD_REV = 'old0000000000000000000000000000a'
const NEW_MEDIA_REV = 'new0000000000000000000000000000b'

function entry(path, extra = {}) {
  return { label: path.split('/').pop(), kind: 'path', value: path, path, target: path, line: null, is_dir: false, eid: `eid-${path.split('/').pop()}`, ...extra }
}

const evidence = [
  entry('/home/bam/bam_ws/reports/media/run/clip.mp4'),
  entry('/home/bam/bam_ws/reports/media/run/still.png'),
  entry('/home/bam/bam_ws/reports/run-2026-10-05.html', { kind: 'report' }),
  entry('/home/bam/bam_ws/reports/media/audits/r1.md'),
  { label: 'https://example.org/x', kind: 'url', value: 'https://example.org/x' },
  entry('/home/bam/bam_ws/reports/media', { is_dir: true }),
  entry('/archive/datasets/trash.tar'),
]
const item = { id: 'kinsim:T70', local_id: 'T70', evidence }
/** The Needs document the page holds: the one Zach reviewed. */
const oldDoc = { schema: 'vibetracks-needs/1', track: 'kinsim', evidence_rev: OLD_REV, items: [item] }
/** A projection loaded LATER, listing the same paths as media under a newer revision (a retargeted alias). */
const newProjection = {
  media_rev: NEW_MEDIA_REV,
  media: Object.fromEntries(evidence.filter((e) => e.path).map((e, i) => [`m${i}`, { id: `m${i}`, kind: 'video', label: e.label, path: e.path }])),
}

function expectedHref(index) {
  const query = new URLSearchParams({ track: 'kinsim', item: 'T70', eid: evidence[index].eid, rev: OLD_REV })
  return `${backend.baseUrl}/needs/evidence?${query}`
}

test('every served file opens through /needs/evidence under the OLD document revision, even beside a newer projection', () => {
  for (const index of [0, 1, 2, 3]) {
    // The extra argument is what e0bd8e5's evidenceHref(backend, doc, item, index, projection) accepted; it must not matter.
    const href = evidenceHref(backend, oldDoc, item, index, newProjection)
    assert.equal(href, expectedHref(index), `entry ${index} (${evidence[index].path})`)
    assert.ok(!href.includes('/media/'), `entry ${index} must never open through /media: ${href}`)
    assert.ok(!href.includes(NEW_MEDIA_REV), `entry ${index} must not carry the projection's revision`)
    assert.equal(evidenceUrl(backend, oldDoc, item, index), href)
    assert.equal(`${backend.baseUrl}${evidencePath(oldDoc, item, index)}`, href)
  }
})

test('a URL opens as itself; a directory or an unserved suffix is shown as a path, not a link', () => {
  assert.equal(evidenceHref(backend, oldDoc, item, 4), 'https://example.org/x')
  assert.equal(evidenceHref(backend, oldDoc, item, 5), null)
  assert.equal(evidenceHref(backend, oldDoc, item, 6), null)
  assert.equal(evidenceHref(backend, oldDoc, item, 99), null)
})

test('without the identity needs.py binds (eid on the entry, evidence_rev on the doc) there is no link at all', () => {
  const unbound = { ...oldDoc, evidence_rev: undefined }
  assert.equal(evidenceHref(backend, unbound, item, 0), null)
  const noEid = { ...item, evidence: [{ ...evidence[0], eid: undefined }] }
  assert.equal(evidenceHref(backend, oldDoc, noEid, 0), null)
})

/** Every .ts/.tsx source under clank/src/needs, with comments removed (a WHY that names /media is fine). */
function needsSources() {
  const root = fileURLToPath(new URL('.', import.meta.url))
  const files = []
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) walk(path)
      else if (/\.tsx?$/.test(name)) files.push(path)
    }
  }
  walk(root)
  return files.map((path) => [path, readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')])
}

test('no Needs source reaches for /media: mediaUrl, checkMedia and a "/media/" URL are absent from clank/src/needs', () => {
  const offenders = []
  for (const [path, code] of needsSources()) {
    if (/\bmediaUrl\b|\bcheckMedia\b|['"`]\/media\//.test(code)) offenders.push(path)
  }
  assert.deepEqual(offenders, [])
})

test('EvidenceLink takes no projection: its href comes from evidence.ts alone', () => {
  const link = needsSources().find(([path]) => path.endsWith('EvidenceLink.tsx'))[1]
  assert.ok(!/\bprojection\b/.test(link), 'EvidenceLink.tsx still mentions a projection')
  assert.match(link, /evidenceHref\(backend, doc, item, index\)/)
})
