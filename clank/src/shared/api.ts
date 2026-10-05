// The projection and its media, through Clank's plugin proxy (ctx.backend → /api/plugins/vibetracks/<path>).
// WHY fetch-on-open with an explicit reload, and no live stream: the source is a snapshot for now (projection.source.live
// is false); a live adapter can add an event stream later without changing the variants.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import { PROJECTION_SCHEMA, type Projection } from './model'

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** GET /projection (`rebuild: true` reruns the adapter first). Throws on a non-2xx answer or a foreign schema. */
export async function fetchProjection(backend: PluginBackend, options: { rebuild?: boolean; signal?: AbortSignal } = {}): Promise<Projection> {
  const response = await backend.fetch(options.rebuild ? '/projection?rebuild=1' : '/projection', { signal: options.signal })
  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!response.ok) {
    const message = body && typeof body === 'object' && 'error' in body ? String((body as { error: unknown }).error) : `HTTP ${response.status}`
    throw new ApiError(message, response.status)
  }
  const projection = body as Projection
  if (!projection || projection.schema !== PROJECTION_SCHEMA) {
    throw new ApiError(`unexpected projection schema ${JSON.stringify((projection as { schema?: unknown } | null)?.schema)}`, 500)
  }
  return projection
}

/** The media revision a projection answer carries (`media_rev`, added by the backend), or null when it has none. */
export function mediaRevision(projection: Projection | null | undefined): string | null {
  const value = (projection as { media_rev?: unknown } | null | undefined)?.media_rev
  return typeof value === 'string' && value ? value : null
}

// The media revision of the projection on screen, per backend. WHY written while useProjection renders (and not in a
// fetch callback or an effect): every variant gets one `mediaUrl(id)` memoised on the backend alone (Dashboard.tsx),
// and calls it while rendering the projection it was handed; the hook's render runs first in that same pass, so the
// revision read is the one of the projection being drawn - never a newer fetch's, never the last one's.
const shownMediaRevision = new WeakMap<PluginBackend, string | null>()

/** The URL a `<video src>`, `<iframe src>` or `<a href>` uses for one media id. Same origin as the page.
 *
 * WHY it carries the revision (audit 2026-10-05 round 2, sibling of finding 1): the backend serves a media id only
 * from the files recorded under the projection the page was given, so a poll or another tab that sees a retargeted
 * alias cannot change what this page's URL opens. A URL with no revision is refused (409): the page must reload. */
export function mediaUrl(backend: PluginBackend, id: string, revision?: string | null): string {
  const rev = revision === undefined ? shownMediaRevision.get(backend) ?? null : revision
  const base = `${backend.baseUrl}/media/${encodeURIComponent(id)}`
  return rev ? `${base}?rev=${encodeURIComponent(rev)}` : base
}

/** Ask the backend whether a media URL still opens, reading only its status (HEAD): 'ok', 'changed' (409: the
 * projection it came from is no longer held, or its file changed since it was shown), or `HTTP <status>`. */
export async function checkMedia(url: string): Promise<'ok' | 'changed' | string> {
  const response = await fetch(url, { method: 'HEAD' })
  if (response.ok) return 'ok'
  if (response.status === 409) return 'changed'
  return `HTTP ${response.status}`
}

// WHY a module-level signal (as needs/api.ts does for /needs): a media view that the backend refuses with 409 offers
// "reload", and that reload must re-read the projection the page shows, which only the mounted useProjection owns.
const reloadListeners = new Set<() => void>()
const loadedListeners = new Set<() => void>()
let projectionsLoaded = 0

/** Ask every mounted useProjection to re-read /projection (a media view's "reload" after a 409). Never automatic. */
export function requestProjectionReload(): void {
  for (const listener of [...reloadListeners]) listener()
}

/** A number that grows each time a projection answer is accepted for display; a refused media view re-checks on it. */
export function useProjectionsLoaded(): number {
  const [count, setCount] = useState(projectionsLoaded)
  useEffect(() => {
    const listener = () => setCount(projectionsLoaded)
    loadedListeners.add(listener)
    listener()
    return () => {
      loadedListeners.delete(listener)
    }
  }, [])
  return count
}

export interface ProjectionState {
  projection: Projection | null
  error: string | null
  loading: boolean
  /** Re-read projection.json; `rebuild: true` reruns the adapter (python3 -m vibetracks.dashboard.build) first. */
  reload(options?: { rebuild?: boolean }): void
}

export function useProjection(backend: PluginBackend): ProjectionState {
  const [state, setState] = useState<{ projection: Projection | null; error: string | null; loading: boolean }>({
    projection: null,
    error: null,
    loading: true,
  })
  const [request, setRequest] = useState<{ n: number; rebuild: boolean }>({ n: 0, rebuild: false })
  const ticket = useRef(0)

  useEffect(() => {
    const mine = ++ticket.current
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true }))
    fetchProjection(backend, { rebuild: request.rebuild, signal: controller.signal }).then(
      (projection) => {
        if (mine !== ticket.current) return
        setState({ projection, error: null, loading: false })
        projectionsLoaded += 1
        for (const listener of [...loadedListeners]) listener()
      },
      (error: unknown) => {
        if (mine !== ticket.current || controller.signal.aborted) return
        // WHY keep the last good projection on a failed reload: a transient backend restart should not blank the page.
        setState((previous) => ({ projection: previous.projection, error: error instanceof Error ? error.message : String(error), loading: false }))
      },
    )
    return () => controller.abort()
  }, [backend, request])

  const reload = useCallback((options?: { rebuild?: boolean }) => setRequest((previous) => ({ n: previous.n + 1, rebuild: Boolean(options?.rebuild) })), [])
  useEffect(() => {
    const listener = () => reload()
    reloadListeners.add(listener)
    return () => {
      reloadListeners.delete(listener)
    }
  }, [reload])
  shownMediaRevision.set(backend, mediaRevision(state.projection))
  return { ...state, reload }
}
