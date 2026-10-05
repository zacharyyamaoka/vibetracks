// /needs through Clank's plugin proxy. Fetch on open plus an explicit reload, like the projection (shared/api.ts).

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import { NEEDS_ALL_SCHEMA, NEEDS_SCHEMA, type NeedsAll, type NeedsDoc, type NeedsEvidence, type NeedsItem } from './types'

async function getJson(backend: PluginBackend, path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await backend.fetch(path, { signal })
  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!response.ok) {
    const message = body && typeof body === 'object' && 'error' in body ? String((body as { error: unknown }).error) : `HTTP ${response.status}`
    throw new Error(message)
  }
  return body
}

/** One track's doc (`track` given) or every track's (`track` null), always as an array of docs. */
export async function fetchNeeds(backend: PluginBackend, track: string | null, signal?: AbortSignal): Promise<NeedsDoc[]> {
  if (track) {
    const doc = (await getJson(backend, `/needs?track=${encodeURIComponent(track)}`, signal)) as NeedsDoc
    if (!doc || doc.schema !== NEEDS_SCHEMA) throw new Error(`unexpected needs schema ${JSON.stringify((doc as { schema?: unknown })?.schema)}`)
    return [doc]
  }
  const all = (await getJson(backend, '/needs', signal)) as NeedsAll
  if (!all || all.schema !== NEEDS_ALL_SCHEMA) throw new Error(`unexpected needs schema ${JSON.stringify((all as { schema?: unknown })?.schema)}`)
  return all.tracks
}

export interface NeedsState {
  /** `[doc]` for one track, every track's doc when `track` is null. Kept across a failed reload. */
  docs: NeedsDoc[]
  /** The one track's doc when a track was asked for. */
  doc: NeedsDoc | null
  loading: boolean
  error: string | null
  reload(): void
}

/** Fetch /needs for `track` (null = all tracks); `reload()` re-reads the loops' live files. */
export function useNeeds(backend: PluginBackend, track: string | null): NeedsState {
  const [state, setState] = useState<{ docs: NeedsDoc[]; loading: boolean; error: string | null }>({ docs: [], loading: true, error: null })
  const [tick, setTick] = useState(0)
  const ticket = useRef(0)
  useEffect(() => {
    const mine = ++ticket.current
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true }))
    fetchNeeds(backend, track, controller.signal).then(
      (docs) => mine === ticket.current && setState({ docs, loading: false, error: null }),
      (error: unknown) => {
        if (mine !== ticket.current || controller.signal.aborted) return
        setState((previous) => ({ docs: previous.docs, loading: false, error: error instanceof Error ? error.message : String(error) }))
      },
    )
    return () => controller.abort()
  }, [backend, track, tick])
  const reload = useCallback(() => setTick((n) => n + 1), [])
  return { ...state, doc: track ? (state.docs.find((doc) => doc.track === track) ?? null) : null, reload }
}

/** Same-origin URL serving one evidence entry's file, or null when the backend will not serve it (URL, directory). */
export function evidenceUrl(backend: PluginBackend, doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry: NeedsEvidence | undefined = item.evidence[index]
  if (!entry) return null
  if (entry.kind === 'url') return entry.value
  if (!entry.path || entry.is_dir) return null
  const query = new URLSearchParams({ track: doc.track, item: item.local_id, n: String(index) })
  return `${backend.baseUrl}/needs/evidence?${query.toString()}`
}
