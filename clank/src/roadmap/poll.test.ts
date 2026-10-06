import { describe, expect, it } from 'vitest'
import { createPoller } from './poll'

// A hand-driven clock and a hand-resolved fetch, so the scheduler's order of events is the whole test.
function rig() {
  const timers: Array<{ run: () => void; ms: number; live: boolean }> = []
  const calls: Array<{ force: boolean; signal: AbortSignal; settle: (failure?: Error) => void }> = []
  let concurrent = 0
  let worst = 0
  const poller = createPoller({
    intervalMs: 30_000,
    schedule: (run, ms) => {
      const timer = { run, ms, live: true }
      timers.push(timer)
      return timer
    },
    cancel: (handle) => {
      (handle as { live: boolean }).live = false
    },
    load: (force, signal) => new Promise<void>((resolve, reject) => {
      concurrent += 1
      worst = Math.max(worst, concurrent)
      calls.push({ force, signal, settle: (failure) => { concurrent -= 1; failure ? reject(failure) : resolve() } })
    }),
  })
  const live = () => timers.filter((timer) => timer.live)
  const fire = () => { const timer = live()[0]!; timer.live = false; timer.run() }
  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))
  return { poller, timers, calls, live, fire, tick, worst: () => worst }
}

describe('createPoller (poll every 30 s, never overlapping, abortable)', () => {
  it('loads at once, then schedules the next poll only after that load settles', async () => {
    const r = rig()
    r.poller.start()
    expect(r.calls.map((call) => call.force)).toEqual([false])
    expect(r.live()).toHaveLength(0)
    r.calls[0]!.settle()
    await r.tick()
    expect(r.live().map((timer) => timer.ms)).toEqual([30_000])
    r.fire()
    expect(r.calls).toHaveLength(2)
    expect(r.calls[1]!.force).toBe(false)
  })

  it('a reload during a load waits for it, then runs once more with force', async () => {
    const r = rig()
    r.poller.start()
    r.poller.reload()
    r.poller.reload()
    expect(r.calls).toHaveLength(1)
    r.calls[0]!.settle()
    await r.tick()
    expect(r.calls.map((call) => call.force)).toEqual([false, true])
    r.calls[1]!.settle()
    await r.tick()
    expect(r.calls).toHaveLength(2)
    expect(r.live()).toHaveLength(1)
    expect(r.worst()).toBe(1)
  })

  it('a reload while idle replaces the pending timer: load now with force, then poll on from there', async () => {
    const r = rig()
    r.poller.start()
    r.calls[0]!.settle()
    await r.tick()
    const waiting = r.live()[0]!
    r.poller.reload()
    expect(waiting.live).toBe(false)
    expect(r.calls.map((call) => call.force)).toEqual([false, true])
    r.calls[1]!.settle()
    await r.tick()
    expect(r.live()).toHaveLength(1)
    expect(r.live()[0]).not.toBe(waiting)
  })

  it('stop aborts the load in flight, cancels the timer, and nothing runs after it', async () => {
    const r = rig()
    r.poller.start()
    r.poller.stop()
    expect(r.calls[0]!.signal.aborted).toBe(true)
    r.calls[0]!.settle()
    await r.tick()
    expect(r.live()).toHaveLength(0)
    r.poller.reload()
    expect(r.calls).toHaveLength(1)

    const idle = rig()
    idle.poller.start()
    idle.calls[0]!.settle()
    await idle.tick()
    idle.poller.stop()
    expect(idle.live()).toHaveLength(0)
  })

  it('a load that rejects does not end the polling', async () => {
    const r = rig()
    r.poller.start()
    r.calls[0]!.settle(new Error('offline'))
    await r.tick()
    expect(r.live()).toHaveLength(1)
    r.fire()
    expect(r.calls).toHaveLength(2)
  })

  it('every load gets its own signal, and the one of a finished load is not aborted by a later reload', async () => {
    const r = rig()
    r.poller.start()
    r.calls[0]!.settle()
    await r.tick()
    r.poller.reload()
    expect(r.calls[1]!.signal).not.toBe(r.calls[0]!.signal)
    expect(r.calls[0]!.signal.aborted).toBe(false)
  })
})
