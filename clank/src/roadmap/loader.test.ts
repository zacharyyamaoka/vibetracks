import { describe, expect, it } from 'vitest'
import type { RoadmapDoc } from './doc'
import { freshness } from './freshness'
import { ROADMAP_ART_DEADLINE_MS, ROADMAP_DOC_DEADLINE_MS, createRoadmapLoader, type RoadmapLoadState } from './loader'
import { createPoller } from './poll'

// A hand-resolved fetch and a recording stand-in for React's setState: the loader's order of events is the whole test.
const GENERATED_AT = '2026-10-04T10:05:00Z'
const docBody = (warnings: string[] = []) => ({ schema: 'bam-roadmap/1', loop: 'grasping', title: 'g', generated_at: GENERATED_AT, warnings, axes: [], rungs: [], edges: [] })
const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

interface Call { path: string; signal: AbortSignal; resolve: (body: unknown) => void; reject: (error: Error) => void }

function rig(deadlines: { art?: number; doc?: number } = {}) {
  const calls: Call[] = []
  let state: RoadmapLoadState = { track: 'grasping', doc: null, loading: true, error: null }
  let publishes = 0
  const load = createRoadmapLoader({
    track: 'grasping',
    artBase: '/art',
    artDeadlineMs: deadlines.art,
    docDeadlineMs: deadlines.doc,
    // Like a real fetch: an aborted signal rejects the request.
    fetchJson: (path, signal) => new Promise((resolve, reject) => {
      calls.push({ path, signal, resolve, reject })
      signal.addEventListener('abort', () => reject(new Error('aborted')))
    }),
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
  it('does not settle while art is pending, and aborting the cycle aborts both requests', async () => {
    const r = rig()
    const cycle = new AbortController()
    let settled = false
    void r.load(false, cycle.signal).then(() => { settled = true })
    r.pending('/roadmap/doc')[0]!.reject(new Error('offline'))
    await tick()
    expect(settled).toBe(false)
    expect(r.pending('/roadmap/art')[0]!.signal.aborted).toBe(false)
    cycle.abort()
    await tick()
    expect(r.pending('/roadmap/art')[0]!.signal.aborted).toBe(true)
    expect(settled).toBe(true)
  })

  it('aborting a cycle with both requests pending aborts both', async () => {
    const r = rig()
    const cycle = new AbortController()
    const settled = r.load(false, cycle.signal)
    cycle.abort()
    await settled
    expect(r.pending('/roadmap/art')[0]!.signal.aborted).toBe(true)
    expect(r.pending('/roadmap/doc')[0]!.signal.aborted).toBe(true)
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
  })
})

describe('optional art never gates the document (Codex X04)', () => {
  it('exports the deadlines: art 10 s, doc 120 s', () => {
    expect(ROADMAP_ART_DEADLINE_MS).toBe(10_000)
    expect(ROADMAP_DOC_DEADLINE_MS).toBe(120_000)
  })

  it('a first successful /doc leaves Loading while /art is still pending', async () => {
    const r = rig()
    void r.load(false, new AbortController().signal)
    r.pending('/roadmap/doc')[0]!.resolve(docBody())
    await tick()
    expect(r.state().loading).toBe(false)
    expect(r.state().doc!.document.generated_at).toBe(GENERATED_AT)
  })

  it('Codex\'s reproduction: art pending, /doc offline: the warning and error show, and the poller schedules once art times out', async () => {
    const r = rig({ art: 40 })
    await r.run(docBody())
    const timers: Array<{ run: () => void; live: boolean }> = []
    const poller = createPoller({
      intervalMs: 30_000,
      schedule: (run) => { const timer = { run, live: true }; timers.push(timer); return timer },
      cancel: (handle) => { (handle as { live: boolean }).live = false },
      load: r.load,
    })
    poller.start()
    r.pending('/roadmap/doc')[1]!.reject(new Error('offline'))
    await tick()
    expect(r.state().error).toBe('offline')
    expect(freshness(r.state().doc!.document).notCurrent!.startsWith("Not current: couldn't refresh")).toBe(true)
    // The cycle is still open (art pending): no next poll yet, and nothing overlaps.
    expect(timers.filter((timer) => timer.live)).toHaveLength(0)
    await new Promise<void>((resolve) => setTimeout(resolve, 80))
    expect(timers.filter((timer) => timer.live)).toHaveLength(1)
    poller.stop()
  })

  it('an art deadline lets the cycle end, silently, and keeps the last art list', async () => {
    const r = rig({ art: 20 })
    await r.run(docBody(), ['a.png'])
    const publishes = r.publishes()
    const cycle = new AbortController()
    let settled = false
    void r.load(true, cycle.signal).then(() => { settled = true })
    r.pending('/roadmap/doc')[1]!.resolve(docBody())
    await tick()
    expect(settled).toBe(false)
    await new Promise<void>((resolve) => setTimeout(resolve, 50))
    expect(settled).toBe(true)
    expect(r.pending('/roadmap/art')[1]!.signal.aborted).toBe(true)
    expect(cycle.signal.aborted).toBe(false)
    expect([...r.state().doc!.artNames]).toEqual(['a.png'])
    expect(r.state().error).toBeNull()
    expect(r.publishes()).toBe(publishes)
  })

  it('a doc deadline is a failure: "Not current: couldn\'t refresh the roadmap (timed out …)"', async () => {
    const r = rig({ doc: 20 })
    await r.run(docBody())
    const settled = r.load(false, new AbortController().signal)
    r.pending('/roadmap/art')[1]!.resolve({ entries: [] })
    await settled
    expect(r.state().error!.startsWith('timed out')).toBe(true)
    expect(freshness(r.state().doc!.document).notCurrent!.startsWith("Not current: couldn't refresh the roadmap (timed out")).toBe(true)
  })

  it('art that arrives after the document updates the names, once, and only when they changed', async () => {
    const r = rig()
    const settled = r.load(false, new AbortController().signal)
    r.pending('/roadmap/doc')[0]!.resolve(docBody())
    await tick()
    expect([...r.state().doc!.artNames]).toEqual([])
    const before = r.publishes()
    r.pending('/roadmap/art')[0]!.resolve({ entries: ['a.png'] })
    await settled
    expect([...r.state().doc!.artNames]).toEqual(['a.png'])
    expect(r.publishes()).toBe(before + 1)
    // The same list next cycle is no news.
    const again = r.load(false, new AbortController().signal)
    r.pending('/roadmap/doc')[1]!.resolve(docBody())
    r.pending('/roadmap/art')[1]!.resolve({ entries: ['a.png'] })
    await again
    expect(r.publishes()).toBe(before + 1)
  })
})
