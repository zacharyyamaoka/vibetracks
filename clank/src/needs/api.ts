// /needs through Clank's plugin proxy. Fetch on open plus an explicit reload, like the projection (shared/api.ts).

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import { sharedRequests, type SharedRequests } from './share'
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
// WHY a module-level reload signal: an evidence link that the backend refuses with 409 ("the document changed") offers
// "reload", and that reload must re-read the same document the page shows, which only the mounted useNeeds owns.
const reloadListeners = new Set<() => void>()

/** Ask every mounted useNeeds to re-read /needs (the evidence link's "reload" after a 409). Never automatic. */
export function requestNeedsReload(): void {
  for (const listener of [...reloadListeners]) listener()
}

/** Every useNeeds of one backend shares one in-flight /needs read per key (one track, or all tracks). See share.ts. */
const sharedByBackend = new WeakMap<PluginBackend, SharedRequests<NeedsDoc[]>>()
function needsRequests(backend: PluginBackend): SharedRequests<NeedsDoc[]> {
  let shared = sharedByBackend.get(backend)
  if (!shared) {
    shared = sharedRequests<NeedsDoc[]>()
    sharedByBackend.set(backend, shared)
  }
  return shared
}

/** The share key: one track's doc, or every track's. */
export function needsKey(track: string | null): string {
  return track === null ? 'all' : `track:${track}`
}

export function useNeeds(backend: PluginBackend, track: string | null): NeedsState {
  // `key` is the track the docs were read for. WHY: a failed read keeps the last docs (a reload hiccup must not blank
  // the page), but only for the SAME track; moving from kinsim to a track /needs does not know must never leave
  // kinsim's questions on screen under the other track's route.
  const [state, setState] = useState<{ key: string | null; docs: NeedsDoc[]; loading: boolean; error: string | null }>({ key: track, docs: [], loading: true, error: null })
  const [tick, setTick] = useState(0)
  // The share point a reload was asked at: a reload joins only a read that started after it (share.ts).
  const reloadMark = useRef(-1)
  useEffect(() => {
    let live = true
    setState((previous) => (previous.key === track ? { ...previous, loading: true } : { key: track, docs: [], loading: true, error: null }))
    // WHY shared and not one fetch per hook: every mounted viewer and React's double effect each asked for the same
    // doc at once (four /needs?track=kinsim on first load); they now share one read of the loop's files.
    const shared = needsRequests(backend).get(needsKey(track), (signal) => fetchNeeds(backend, track, signal), tick === 0 ? -1 : reloadMark.current)
    shared.promise.then(
      (docs) => live && setState({ key: track, docs, loading: false, error: null }),
      (error: unknown) => {
        if (!live) return
        const message = error instanceof Error ? error.message : String(error)
        setState((previous) => ({ key: track, docs: previous.key === track ? previous.docs : [], loading: false, error: message }))
      },
    )
    return () => {
      live = false
      shared.release()
    }
  }, [backend, track, tick])
  const reload = useCallback(() => {
    reloadMark.current = needsRequests(backend).mark()
    setTick((n) => n + 1)
  }, [backend])
  useEffect(() => {
    reloadListeners.add(reload)
    return () => {
      reloadListeners.delete(reload)
    }
  }, [reload])
  const docs = state.key === track ? state.docs : []
  return { docs, loading: state.key === track ? state.loading : true, error: state.key === track ? state.error : null, doc: track ? (docs.find((doc) => doc.track === track) ?? null) : null, reload }
}

/** True for the error /needs answers for a track it has no source for (`404 {"error": "unknown track 'can16'"}`). */
export function isUnknownTrackError(error: string | null): boolean {
  return Boolean(error && /^unknown track\b/.test(error))
}

/** A doc for a track /needs has no source for (a rig deployment such as can16), built from what the dashboard does
 * know: its title. Every count is null ("not reported", never 0), exactly like needs.py's own empty doc, so every
 * proposal renders it with the same not-reported path. The note is the dashboard's words, not a loop's. */
export function unreportedDoc(track: string, title: string, note: string): NeedsDoc {
  const nulls = { open: null, blocking_now: null, wants_you: null, no_default: null, waiting: null, defaulting: null, answered: null, defaulted: null, closed: null, total: null }
  return {
    schema: NEEDS_SCHEMA,
    track,
    track_title: title,
    generated_at: new Date().toISOString(),
    iteration: null,
    source: { adapter: 'none (dashboard: /needs has no source for this track)', paths: [], commit: null, live: false, note },
    answer_channel: { kind: 'none', target: null, row_schema: null, read_back: null },
    counts: nulls,
    items: [],
  }
}

/** needs.py stamps these on every doc and evidence entry (`bind_evidence`); read here without widening types.ts. */
type BoundDoc = NeedsDoc & { evidence_rev?: string }
type BoundEvidence = NeedsEvidence & { eid?: string }

/** The backend path (`/needs/evidence?track&item&eid&rev`) for one evidence entry's file, or null when the backend
 * will not serve it (a URL, a directory, or a doc/entry without the identity needs.py binds).
 *
 * WHY eid + rev and never the list index (audit 2026-10-05, finding 1): the link must open the file Zach reviewed.
 * `eid` names the evidence as written (stable under reordering); `rev` is the document revision he was shown, and
 * the backend answers 409 instead of serving when the document's evidence, or what it resolves to, changed since. */
export function evidencePath(doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry: BoundEvidence | undefined = item.evidence[index]
  const rev = (doc as BoundDoc).evidence_rev
  if (!entry || entry.kind === 'url' || !entry.path || entry.is_dir) return null
  if (typeof entry.eid !== 'string' || !entry.eid || typeof rev !== 'string' || !rev) return null
  const query = new URLSearchParams({ track: doc.track, item: item.local_id, eid: entry.eid, rev })
  return `/needs/evidence?${query.toString()}`
}

/** Same-origin URL serving one evidence entry's file (a URL entry is itself), or null when it cannot be opened. */
export function evidenceUrl(backend: PluginBackend, doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry: NeedsEvidence | undefined = item.evidence[index]
  if (!entry) return null
  if (entry.kind === 'url') return entry.value
  const path = evidencePath(doc, item, index)
  return path ? `${backend.baseUrl}${path}` : null
}

/** Ask the backend whether an evidence path still opens, reading only its status: 'ok', 'changed' (409: the document
 * changed since it was shown), or the backend's refusal text. The body is never read (the abort drops it). */
export async function checkEvidence(backend: PluginBackend, path: string): Promise<'ok' | 'changed' | string> {
  const controller = new AbortController()
  try {
    const response = await backend.fetch(path, { signal: controller.signal })
    if (response.ok) return 'ok'
    if (response.status === 409) return 'changed'
    let message = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { error?: unknown }
      if (body && typeof body.error === 'string') message = body.error
    } catch {
      // not JSON: the status line is the message
    }
    return message
  } finally {
    controller.abort()
  }
}
