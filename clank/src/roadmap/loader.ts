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

export function createRoadmapLoader({ track, artBase, fetchJson, publish }: RoadmapLoaderOptions) {
  // The last good document of THIS track, and what it was built from: an unchanged poll must not re-render the board.
  let last: { key: string; doc: RoadmapData } | null = null
  // The failure message already on screen: the same failure on the next poll must not call setState again.
  let failureShown: string | null = null
  return async (force: boolean, signal: AbortSignal): Promise<void> => {
    // WHY art never fails the roadmap: a missing art dir only means icons instead of renders. A failed art poll
    // keeps the last art list, so the renders do not flicker away with a hiccup.
    // WHY art shares the cycle's signal and the cycle waits for it (Codex W07): the poller's cancellation and its
    // one-at-a-time rule must cover every request of a cycle, or a pending /art outlives unmount and overlaps the next.
    const art = fetchJson('/roadmap/art', signal).then(
      (body) => new Set(Array.isArray((body as { entries?: unknown } | null)?.entries) ? ((body as { entries: unknown[] }).entries.filter((name): name is string => typeof name === 'string')) : []),
      () => null,
    )
    const [docResult, artNames] = await Promise.all([
      fetchJson(`/roadmap/doc?track=${encodeURIComponent(track)}${force ? '&refresh=1' : ''}`, signal).then(
        (body) => ({ body }),
        (error: unknown) => ({ error }),
      ),
      art,
    ])
    if (signal.aborted) return
    try {
      if ('error' in docResult) throw docResult.error
      const document = parseRoadmapDoc(docResult.body)
      const names: ReadonlySet<string> = artNames ?? last?.doc.artNames ?? new Set<string>()
      const key = JSON.stringify([docResult.body, [...names]])
      if (last?.key === key) {
        if (failureShown !== null) {
          failureShown = null
          publish({ track, doc: last.doc, loading: false, error: null })
        } else {
          publish((now) => (now.error ? { ...now, error: null } : now))
        }
        return
      }
      last = { key, doc: { track, document, artBase, artNames: names } }
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
}
