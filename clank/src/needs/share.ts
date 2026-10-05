// One in-flight request per key, shared by every caller that asks for it while it runs. Pure (no React), so
// share.check.mjs runs it under plain node.
//
// WHY (verifier, 2026-10-05): the needs page fetched /needs?track=kinsim about four times at once on first load:
// React's development double effect, and every mounted dashboard viewer (Clank keeps a second one in a hidden tab),
// each started its own read of the same loop files. Now the second caller joins the first caller's request.
//
// The rules that keep it truthful:
// - Join only a request that is still running. A settled answer is never reused: the next read is a new read.
// - A reload joins only a request that STARTED after the reload was asked for (`notBefore`), so "reload" can never be
//   answered by a read that began before Zach asked to re-read; several listeners reloading at once still share one.
// - A caller leaving (unmount, route change) never cancels the request for the others. The request is aborted only
//   when nobody waits for it any more, checked on a later task so React's unmount-then-remount does not abort it.

export interface Shared<T> {
  /** Settles with the shared request's answer (or its error). */
  promise: Promise<T>
  /** This caller no longer waits. The request is aborted once no caller waits (on a later task). */
  release(): void
}

interface Entry<T> {
  seq: number
  promise: Promise<T>
  controller: AbortController
  waiters: number
  settled: boolean
}

export interface SharedRequests<T> {
  /** Join the running request for `key`, or start one with `start(signal)`. `notBefore` (a `mark()` value) refuses a
   * running request that started at or before it. */
  get(key: string, start: (signal: AbortSignal) => Promise<T>, notBefore?: number): Shared<T>
  /** The current sequence point: pass it later as `notBefore` to require a request that starts after now. */
  mark(): number
  /** Requests running now (for checks). */
  running(): number
}

export function sharedRequests<T>(schedule: (run: () => void) => void = (run) => void setTimeout(run, 0)): SharedRequests<T> {
  const entries = new Map<string, Entry<T>>()
  let seq = 0
  return {
    mark: () => seq,
    running: () => entries.size,
    get(key, start, notBefore = -1) {
      let entry = entries.get(key)
      if (!entry || entry.settled || entry.seq <= notBefore) {
        const controller = new AbortController()
        const fresh: Entry<T> = { seq: ++seq, controller, waiters: 0, settled: false, promise: Promise.resolve() as Promise<T> }
        const done = () => {
          fresh.settled = true
          if (entries.get(key) === fresh) entries.delete(key)
        }
        fresh.promise = start(controller.signal).then(
          (value) => {
            done()
            return value
          },
          (error: unknown) => {
            done()
            throw error
          },
        )
        // A caller that leaves before the answer must not see an unhandled rejection from the shared promise.
        fresh.promise.catch(() => undefined)
        entries.set(key, fresh)
        entry = fresh
      }
      const joined = entry
      joined.waiters++
      let released = false
      return {
        promise: joined.promise,
        release() {
          if (released) return
          released = true
          joined.waiters--
          if (joined.waiters > 0 || joined.settled) return
          schedule(() => {
            if (joined.waiters > 0 || joined.settled) return
            joined.controller.abort()
            if (entries.get(key) === joined) entries.delete(key)
          })
        },
      }
    },
  }
}
