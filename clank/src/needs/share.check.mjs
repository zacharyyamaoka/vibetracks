// node:test checks for the shared in-flight request (share.ts) that useNeeds reads /needs through.
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/needs/share.check.mjs
// Pins (verifier, 2026-10-05): /needs?track=kinsim was fetched about four times at once on first load. These fail
// against a per-caller fetch (every `get` would start its own request), and pin the rules that keep sharing truthful:
// no settled answer is reused, a reload never joins a read that began before it, and one caller leaving never cancels
// the others' read. The browser half (tests/browser/needs_once.mjs) counts the real requests on the real page.

import { test } from 'node:test'
import assert from 'node:assert/strict'

const { sharedRequests } = await import('./share.ts')

/** A request the test settles by hand, counting starts and recording aborts. */
function harness() {
  const starts = []
  const start = (key) => (signal) => {
    let resolve
    let reject
    const promise = new Promise((res, rej) => {
      resolve = res
      reject = rej
    })
    const record = { key, signal, resolve, reject }
    signal.addEventListener('abort', () => reject(new Error('aborted')))
    starts.push(record)
    return promise
  }
  // Abort checks run when the test says so, standing in for "a later task".
  const later = []
  const shared = sharedRequests((run) => later.push(run))
  const flush = () => {
    while (later.length) later.shift()()
  }
  return { starts, start, shared, flush }
}

test('callers asking for the same key while it runs share ONE request and its answer', async () => {
  const { starts, start, shared } = harness()
  const callers = [1, 2, 3, 4].map(() => shared.get('track:kinsim', start('track:kinsim')))
  assert.equal(starts.length, 1, 'four callers, one request')
  starts[0].resolve(['doc'])
  for (const caller of callers) assert.deepEqual(await caller.promise, ['doc'])
})

test('different keys are different requests', () => {
  const { starts, start, shared } = harness()
  shared.get('track:kinsim', start('track:kinsim'))
  shared.get('track:rig', start('track:rig'))
  shared.get('all', start('all'))
  assert.deepEqual(starts.map((s) => s.key), ['track:kinsim', 'track:rig', 'all'])
})

test('a settled answer is never reused: the next ask is a new read', async () => {
  const { starts, start, shared } = harness()
  const first = shared.get('track:kinsim', start('track:kinsim'))
  starts[0].resolve(['old'])
  await first.promise
  const second = shared.get('track:kinsim', start('track:kinsim'))
  assert.equal(starts.length, 2)
  starts[1].resolve(['new'])
  assert.deepEqual(await second.promise, ['new'])
})

test('a reload never joins a read that began before it; reloads asked together share one fresh read', async () => {
  const { starts, start, shared } = harness()
  const before = shared.get('track:kinsim', start('track:kinsim'))
  const mark = shared.mark()
  const reloadA = shared.get('track:kinsim', start('track:kinsim'), mark)
  const reloadB = shared.get('track:kinsim', start('track:kinsim'), mark)
  assert.equal(starts.length, 2, 'the running read is refused once; the second reload joins the fresh one')
  starts[0].resolve(['before the reload'])
  starts[1].resolve(['after the reload'])
  assert.deepEqual(await before.promise, ['before the reload'])
  assert.deepEqual(await reloadA.promise, ['after the reload'])
  assert.deepEqual(await reloadB.promise, ['after the reload'])
})

test('one caller leaving never cancels the read the others wait for', async () => {
  const { starts, start, shared, flush } = harness()
  const leaving = shared.get('track:kinsim', start('track:kinsim'))
  const staying = shared.get('track:kinsim', start('track:kinsim'))
  leaving.release()
  flush()
  assert.equal(starts[0].signal.aborted, false)
  starts[0].resolve(['doc'])
  assert.deepEqual(await staying.promise, ['doc'])
})

test("React's unmount-then-remount keeps the one read (no abort, no second request)", async () => {
  const { starts, start, shared, flush } = harness()
  const first = shared.get('track:kinsim', start('track:kinsim'))
  first.release()
  const again = shared.get('track:kinsim', start('track:kinsim'))
  flush()
  assert.equal(starts.length, 1)
  assert.equal(starts[0].signal.aborted, false)
  starts[0].resolve(['doc'])
  assert.deepEqual(await again.promise, ['doc'])
})

test('when nobody waits any more the read is aborted, and the next ask starts afresh', async () => {
  const { starts, start, shared, flush } = harness()
  const only = shared.get('track:kinsim', start('track:kinsim'))
  only.release()
  only.release()
  flush()
  assert.equal(starts[0].signal.aborted, true)
  await assert.rejects(only.promise)
  assert.equal(shared.running(), 0)
  shared.get('track:kinsim', start('track:kinsim'))
  assert.equal(starts.length, 2)
})

test('an error reaches every caller of the shared read, and the key is free again', async () => {
  const { starts, start, shared } = harness()
  const a = shared.get('all', start('all'))
  const b = shared.get('all', start('all'))
  starts[0].reject(new Error('unknown track'))
  await assert.rejects(a.promise, /unknown track/)
  await assert.rejects(b.promise, /unknown track/)
  assert.equal(shared.running(), 0)
})
