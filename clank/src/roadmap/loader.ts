// One refresh of a track's roadmap, apart from React so its order of events and its failure presentation are tested
// with a hand-resolved fetch (loader.test.ts). useRoadmap (index.tsx) owns the state and the poller; this owns what a
// load, a failed load and a 404 each leave on screen.

import type { RoadmapDoc } from './doc'
import { parseRoadmapDoc } from './docModel'

/** What useRoadmap hands the dashboard as `doc` (opaque to it): the track's document and where its art lives. */
export interface RoadmapData {
  track: string
  document: RoadmapDoc
  /** `${backend.baseUrl}/roadmap/art`; one image is `${artBase}/<name>.png`. */
  artBase: string
  /** The art file names the backend serves (GET /roadmap/art). */
  artNames: ReadonlySet<string>
}

export interface RoadmapLoadState {
  track: string
  doc: RoadmapData | null
  loading: boolean
  error: string | null
}

export interface RoadmapLoaderOptions {
  track: string
  artBase: string
  /** GET one JSON body; a non-2xx answer rejects with an error carrying the HTTP `status`. */
  fetchJson: (path: string, signal: AbortSignal) => Promise<unknown>
  /** React's setState: a whole state, or an updater of the current one. */
  /** Per-request deadlines; the exported constants unless a test shortens them. */
  artDeadlineMs?: number
  docDeadlineMs?: number
  publish: (next: RoadmapLoadState | ((now: RoadmapLoadState) => RoadmapLoadState)) => void
}

/** The retained document with the failed refresh folded into its `warnings`, on a copy: the cached one stays pristine,
 * so the next success (or the next, different failure) starts from the truth. `generated_at` is the retained one. */
function markRefreshFailed(data: RoadmapData, message: string): RoadmapData {
  return { ...data, document: { ...data.document, warnings: [...data.document.warnings, `${REFRESH_STALE_PREFIX}${message})`] } }
}

/** WHY the failure is a "stale: " warning and not a prop: freshness() already turns that entry into "Not current: ..."
 * in both densities, so every variant shows a failed refresh without any wiring (Codex W03). */
const REFRESH_STALE_PREFIX = "stale: couldn't refresh the roadmap ("

/** WHY deadlines at all: the host backend client has none, and a request that never settles holds its poll cycle open
 * for good (the cycle ends only when every request has settled, so cancellation and one-at-a-time still cover all).
 * Art is decoration, so it gets a short one; a cold projection takes ~9 s (kinsim), so the document gets a long one. */
export const ROADMAP_ART_DEADLINE_MS = 10_000
export const ROADMAP_DOC_DEADLINE_MS = 120_000

/** A request signal that aborts when the cycle's does or when `ms` pass; `timedOut()` tells the two apart. */
function withDeadline(cycle: AbortSignal, ms: number) {
  const request = new AbortController()
  let expired = false
  const abort = () => request.abort()
  if (cycle.aborted) request.abort()
  cycle.addEventListener('abort', abort)
  const timer = setTimeout(() => { expired = true; request.abort() }, ms)
  return {
    signal: request.signal,
    timedOut: () => expired,
    dispose: () => {
      clearTimeout(timer)
      cycle.removeEventListener('abort', abort)
    },
  }
}

const sameNames = (a: ReadonlySet<string>, b: ReadonlySet<string>) => a.size === b.size && [...a].every((name) => b.has(name))

export function createRoadmapLoader({ track, artBase, fetchJson, publish, artDeadlineMs = ROADMAP_ART_DEADLINE_MS, docDeadlineMs = ROADMAP_DOC_DEADLINE_MS }: RoadmapLoaderOptions) {
  // The last good document of THIS track, and what it was built from: an unchanged poll must not re-render the board.
  let last: { key: string; doc: RoadmapData } | null = null
  // The failure message already on screen: the same failure on the next poll must not call setState again.
  let failureShown: string | null = null
  // The last art list the backend gave; a failed or timed-out art poll keeps it.
  let artNames: ReadonlySet<string> = new Set<string>()

  const loadArt = async (cycle: AbortSignal): Promise<void> => {
    const request = withDeadline(cycle, artDeadlineMs)
    try {
      const body = await fetchJson('/roadmap/art', request.signal)
      const entries = (body as { entries?: unknown } | null)?.entries
      const names = new Set(Array.isArray(entries) ? entries.filter((name): name is string => typeof name === 'string') : [])
      if (cycle.aborted || sameNames(names, artNames)) return
      artNames = names
      if (last) last = { ...last, doc: { ...last.doc, artNames: names } }
      // The document on screen may be the not-current copy, so the names are folded into what is shown, not rebuilt.
      publish((now) => (now.track === track && now.doc ? { ...now, doc: { ...now.doc, artNames: names } } : now))
    } catch {
      // WHY art never fails the roadmap: a missing art dir only means icons instead of renders, and a failed or
      // timed-out poll keeps the last list so the renders do not flicker away with a hiccup.
    } finally {
      request.dispose()
    }
  }

  const loadDoc = async (force: boolean, cycle: AbortSignal): Promise<void> => {
    const request = withDeadline(cycle, docDeadlineMs)
    let result: { body: unknown } | { error: unknown }
    try {
      result = { body: await fetchJson(`/roadmap/doc?track=${encodeURIComponent(track)}${force ? '&refresh=1' : ''}`, request.signal) }
    } catch (error) {
      result = { error: request.timedOut() && !cycle.aborted ? new Error(`timed out after ${docDeadlineMs / 1000} s`) : error }
    } finally {
      request.dispose()
    }
    if (cycle.aborted) return
    try {
      if ('error' in result) throw result.error
      const document = parseRoadmapDoc(result.body)
      const key = JSON.stringify(result.body)
      if (last?.key === key) {
        // Nothing changed: only a failure still on screen needs clearing, otherwise no setState at all.
        if (failureShown !== null) {
          failureShown = null
          publish({ track, doc: last.doc, loading: false, error: null })
        }
        return
      }
      last = { key, doc: { track, document, artBase, artNames } }
      failureShown = null
      publish({ track, doc: last.doc, loading: false, error: null })
    } catch (error) {
      // WHY a 404 is not an error: the track's loop has not written a roadmap yet, and the widget says so calmly.
      if ((error as { status?: unknown } | null)?.status === 404) {
        last = null
        failureShown = null
        publish({ track, doc: null, loading: false, error: null })
        return
      }
      const message = error instanceof Error ? error.message : String(error)
      if (message === failureShown) return
      failureShown = message
      // A failed refresh keeps the document already on screen, marked not current; the failure also rides in `error`.
      publish({ track, doc: last ? markRefreshFailed(last.doc, message) : null, loading: false, error: message })
    }
  }

  // WHY the document and the art publish independently, and the cycle waits for both (Codex X04, W07): optional art
  // must never hold the document, or a failure, back from the screen; but the poller's cancellation and its
  // one-at-a-time rule must still cover every request of a cycle, or a pending /art outlives unmount and overlaps the next.
  return async (force: boolean, signal: AbortSignal): Promise<void> => {
    await Promise.all([loadDoc(force, signal), loadArt(signal)])
  }
}
