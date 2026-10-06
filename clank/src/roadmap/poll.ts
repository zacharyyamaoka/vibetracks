// The roadmap's refresh loop, apart from React so its order of events is tested with a hand-driven clock.
//
// WHY polling and not a stream: the backend has no event stream yet (vibetracks/roadmap/api.py serves GET /doc only),
// and it caches each projection server-side, so a poll that finds nothing new is a cache hit, not a re-projection.
// WHY the next poll is scheduled when the load SETTLES and not on a fixed interval: a slow projection must never
// stack a second fetch behind itself, and the gap between two loads is then always at least one interval.

export interface PollerOptions {
  intervalMs: number
  /** One refresh. `force` asks the backend to re-project instead of answering from its cache. A rejection is the
   * loader's to report; the loop only survives it. */
  load: (force: boolean, signal: AbortSignal) => Promise<void>
  schedule?: (run: () => void, ms: number) => unknown
  cancel?: (handle: unknown) => void
}

export interface Poller {
  /** Load now, then keep polling. */
  start: () => void
  /** Load now, forced. Waits for a load in flight (never overlaps), then runs once more. */
  reload: () => void
  /** Abort the load in flight, drop the timer; the poller is finished. */
  stop: () => void
}

export function createPoller({ intervalMs, load, schedule = (run, ms) => setTimeout(run, ms), cancel = (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>) }: PollerOptions): Poller {
  const lifetime = new AbortController()
  let timer: unknown = null
  let busy = false
  // The one load that arrived while another was in flight: forced if any of the arrivals asked for it.
  let queued: { force: boolean } | null = null

  const clearTimer = () => {
    if (timer !== null) cancel(timer)
    timer = null
  }

  const run = async (force: boolean): Promise<void> => {
    if (lifetime.signal.aborted) return
    clearTimer()
    if (busy) {
      queued = { force: force || (queued?.force ?? false) }
      return
    }
    busy = true
    const request = new AbortController()
    const abortRequest = () => request.abort()
    lifetime.signal.addEventListener('abort', abortRequest)
    try {
      await load(force, request.signal)
    } catch {
      // The loader reports its own failure; an offline poll must not end the polling.
    } finally {
      lifetime.signal.removeEventListener('abort', abortRequest)
      busy = false
    }
    if (lifetime.signal.aborted) return
    if (queued) {
      const next = queued
      queued = null
      void run(next.force)
    } else {
      timer = schedule(() => { timer = null; void run(false) }, intervalMs)
    }
  }

  return {
    start: () => void run(false),
    reload: () => void run(true),
    stop: () => {
      lifetime.abort()
      clearTimer()
    },
  }
}
