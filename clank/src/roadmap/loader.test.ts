import { describe, expect, it } from 'vitest'
import type { RoadmapDoc } from './doc'
import { freshness } from './freshness'
import { createRoadmapLoader, type RoadmapLoadState } from './loader'
import { createPoller } from './poll'

// A hand-resolved fetch and a recording stand-in for React's setState: the loader's order of events is the whole test.
const GENERATED_AT = '2026-10-04T10:05:00Z'
const docBody = (warnings: string[] = []) => ({ schema: 'bam-roadmap/1', loop: 'grasping', title: 'g', generated_at: GENERATED_AT, warnings, axes: [], rungs: [], edges: [] })
const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

interface Call { path: string; signal: AbortSignal; resolve: (body: unknown) => void; reject: (error: Error) => void }

function rig() {
  const calls: Call[] = []
  let state: RoadmapLoadState = { track: 'grasping', doc: null, loading: true, error: null }
  let publishes = 0
  const load = createRoadmapLoader({
    track: 'grasping',
    artBase: '/art',
    fetchJson: (path, signal) => new Promise((resolve, reject) => { calls.push({ path, signal, resolve, reject }) }),
    publish: (next) => {
      publishes += 1
      state = typeof next === 'function' ? next(state) : next
    },
  })
  const pending = (prefix: string) => calls.filter((call) => call.path.startsWith(prefix))
  /** One load, with /art answering `entries` and /doc answering `doc` (an Error rejects it). */
  const run = async (doc: unknown | Error, entries: string[] = [], force = false) => {
    const before = calls.length
    const settled = load(force, new AbortController().signal)
    const art = calls.slice(before).find((call) => call.path.startsWith('/roadmap/art'))!
    const docCall = calls.slice(before).find((call) => call.path.startsWith('/roadmap/doc'))!
    art.resolve({ entries })
    if (doc instanceof Error) docCall.reject(doc)
    else docCall.resolve(doc)
    await settled
  }
  return { calls, pending, run, load, state: () => state, publishes: () => publishes }
}

const refreshWarnings = (doc: RoadmapDoc) => doc.warnings.filter((warning) => warning.startsWith("stale: couldn't refresh"))

describe('a failed refresh does not look current (Codex W03)', () => {
  it('carries one "stale: couldn\'t refresh" warning, keeps generated_at, and never touches the cached document', async () => {
    const r = rig()
    await r.run(docBody())
    const good = r.state().doc!
    expect(freshness(good.document).notCurrent).toBeNull()

    await r.run(new Error('offline'))
    const shown = r.state().doc!
    expect(r.state().error).toBe('offline')
    expect(refreshWarnings(shown.document)).toHaveLength(1)
    expect(shown.document.generated_at).toBe(GENERATED_AT)
    expect(freshness(shown.document).notCurrent!.startsWith("Not current: couldn't refresh")).toBe(true)
    expect(freshness(shown.document).notCurrent!).toMatch(/offline/)
    // The cached document is a copy source, never mutated.
    expect(good.document.warnings).toEqual([])
    expect(shown.document === good.document).toBe(false)
  })

  it('a second failure does not duplicate the warning, and an identical one does not set state again', async () => {
    const r = rig()
    await r.run(docBody())
    await r.run(new Error('offline'))
    const before = r.publishes()
    await r.run(new Error('offline'))
    expect(r.publishes()).toBe(before)
    expect(refreshWarnings(r.state().doc!.document)).toHaveLength(1)
    await r.run(new Error('HTTP 502'))
    expect(refreshWarnings(r.state().doc!.document)).toHaveLength(1)
    expect(freshness(r.state().doc!.document).notCurrent!).toMatch(/HTTP 502/)
  })

  it('keeps the server\'s own stale warning and its own order beside the client one', async () => {
    const r = rig()
    await r.run(docBody(['stale: projection failed']))
    await r.run(new Error('offline'))
    expect(r.state().doc!.document.warnings[0]).toBe('stale: projection failed')
    expect(refreshWarnings(r.state().doc!.document)).toHaveLength(1)
  })

  it('the next successful load clears it, whether or not the body changed', async () => {
    const r = rig()
    await r.run(docBody())
    await r.run(new Error('offline'))
    await r.run(docBody())
    expect(r.state().error).toBeNull()
    expect(freshness(r.state().doc!.document).notCurrent).toBeNull()
    expect(r.state().doc!.document.warnings).toEqual([])
    await r.run(new Error('offline'))
    await r.run(docBody([]))
    expect(refreshWarnings(r.state().doc!.document)).toHaveLength(0)
  })

  it('a 404 still clears the document, and a first-load failure has none to mark', async () => {
    const r = rig()
    await r.run(new Error('offline'))
    expect(r.state().doc).toBeNull()
    expect(r.state().error).toBe('offline')
    await r.run(docBody())
    await r.run(Object.assign(new Error('no roadmap'), { status: 404 }))
    expect(r.state().doc).toBeNull()
    expect(r.state().error).toBeNull()
  })
})

describe('art requests belong to the poll cycle (Codex W07)', () => {
  it('uses the cycle\'s own signal for /art and does not settle while art is pending', async () => {
    const r = rig()
    const signal = new AbortController().signal
    let settled = false
    void r.load(false, signal).then(() => { settled = true })
    expect(r.pending('/roadmap/art')[0]!.signal === signal).toBe(true)
    expect(r.pending('/roadmap/doc')[0]!.signal === signal).toBe(true)
    r.pending('/roadmap/doc')[0]!.reject(new Error('offline'))
    await tick()
    expect(settled).toBe(false)
    r.pending('/roadmap/art')[0]!.resolve({ entries: [] })
    await tick()
    expect(settled).toBe(true)
  })

  it('a failed art fetch keeps the last art list', async () => {
    const r = rig()
    await r.run(docBody(), ['a.png'])
    const settled = r.load(true, new AbortController().signal)
    r.pending('/roadmap/art')[1]!.reject(new Error('art down'))
    r.pending('/roadmap/doc')[1]!.resolve(docBody())
    await settled
    expect([...r.state().doc!.artNames]).toEqual(['a.png'])
  })

  it('under the poller: no new cycle while art is pending, and stop aborts both requests', async () => {
    const r = rig()
    const timers: Array<{ run: () => void; live: boolean }> = []
    const poller = createPoller({
      intervalMs: 30_000,
      schedule: (run) => { const timer = { run, live: true }; timers.push(timer); return timer },
      cancel: (handle) => { (handle as { live: boolean }).live = false },
      load: r.load,
    })
    poller.start()
    r.pending('/roadmap/doc')[0]!.reject(new Error('offline'))
    await tick()
    poller.reload()
    await tick()
    // The doc settled but art has not: the cycle is still open, so nothing else was requested and no timer is set.
    expect(r.calls).toHaveLength(2)
    expect(timers.filter((timer) => timer.live)).toHaveLength(0)
    const art = r.pending('/roadmap/art')[0]!
    expect(art.signal.aborted).toBe(false)
    poller.stop()
    expect(art.signal.aborted).toBe(true)
    expect(r.pending('/roadmap/doc')[0]!.signal.aborted).toBe(true)
  })
})
