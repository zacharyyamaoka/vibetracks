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

/** The URL a `<video src>`, `<iframe src>` or `<a href>` uses for one media id. Same origin as the page. */
export function mediaUrl(backend: PluginBackend, id: string): string {
  return `${backend.baseUrl}/media/${encodeURIComponent(id)}`
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
      (projection) => mine === ticket.current && setState({ projection, error: null, loading: false }),
      (error: unknown) => {
        if (mine !== ticket.current || controller.signal.aborted) return
        // WHY keep the last good projection on a failed reload: a transient backend restart should not blank the page.
        setState((previous) => ({ projection: previous.projection, error: error instanceof Error ? error.message : String(error), loading: false }))
      },
    )
    return () => controller.abort()
  }, [backend, request])

  const reload = useCallback((options?: { rebuild?: boolean }) => setRequest((previous) => ({ n: previous.n + 1, rebuild: Boolean(options?.rebuild) })), [])
  return { ...state, reload }
}
