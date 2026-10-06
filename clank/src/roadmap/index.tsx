// The roadmap: one widget inside the dashboard (docs/dashboard/VARIANTS.md, "Roadmap widget slot"; Zach: "the roadmap
// is just like one widget that is part of the dashboard, which is more about layout"). Every variant places
// <RoadmapWidget> at L2 directly under its KPI rows, as a first-class "Roadmap" section: its head is density 'calm', ONE
// calm answer (summary.ts: current rung, next, banked) and a thin per-lane strip; expanded it is density 'full', the lens
// bar, the swimlane board and the focus card. Its state lives in the URL hash under `rm` (JSON) and is controlled by the variant (state.ts); its
// view options live on the dashboard's settings page (ROADMAP_SETTINGS_SECTION), never in a toolbar.
// It reads one bam-roadmap/1 document per track (GET /roadmap/doc, vibetracks/roadmap/api.py) and adapts it to the
// board's model (docModel.ts). Ported from the kinsim dashboard's roadmap (clank-kinsim src/roadmap @ 69e91af).
// WHY no React Flow: the kinsim board's layout engine (graph.ts) draws its own SVG and needs none, and this package has
// no @xyflow dependency (package.json belongs to the dashboard lane).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JSX } from 'react'
import type { PluginBackend } from '@clank/api'
import { ApiError } from '../shared/api'
import { type Art, artFor } from './art'
import type { RoadmapDoc } from './doc'
import { cardLine, modelFromDoc } from './docModel'
import { FocusPanel } from './FocusPanel'
import { restoreBoardFocus, viewKey } from './focus'
import { freshness } from './freshness'
import { type RoadmapData, createRoadmapLoader } from './loader'
import { createPoller } from './poll'
import { KEYS_HINT, LENS_CAPTION, Legend, LensBar, RoadmapBoard } from './RoadmapBoard'
import { edgeStyle, type RoadmapSettings } from './settings'
import { type RoadView, type RoadmapWidgetState, resolveView } from './state'
import { SHOWN, calmSentence, calmSummary, phaseToken, stageLabel } from './summary'
import './roadmap.css'

export { ROADMAP_SETTINGS_SECTION, defaultRoadmapSettings, type RoadmapSettings } from './settings'
export type { RoadmapWidgetState } from './state'

export type { RoadmapData } from './loader'

export interface RoadmapWidgetProps {
  /** The track whose roadmap to show (`kinsim`, `rig`, ...). */
  track: string
  /** The roadmap document from useRoadmap; null while loading or when the track has none. */
  doc: unknown | null
  state: RoadmapWidgetState
  onState: (next: RoadmapWidgetState) => void
  /** Go to L3 evidence for that rung's latest judged run (or a rung note if none). */
  onOpenRung: (rungId: string) => void
  /** Go to the L3 file view at that path (and line). */
  onOpenEvidence: (ref: { path: string; line?: number }) => void
  /** True while useRoadmap is still fetching: the empty-state line must not flash on a slow load. */
  loading?: boolean
  /** 'calm' is the section's head (current rung, next, how much is banked); 'full' is the expanded board. */
  density: 'calm' | 'full'
  settings: RoadmapSettings
}

export interface RoadmapDocState {
  doc: unknown | null
  loading: boolean
  error: string | null
  /** Re-project now (`/roadmap/doc?...&refresh=1`): the dashboard's own reload calls this. Stable across renders. */
  reload: () => void
}

/** How often an open roadmap asks the backend for its document. */
export const ROADMAP_POLL_MS = 30_000

const isRoadmapData = (value: unknown): value is RoadmapData =>
  Boolean(value) && typeof value === 'object' && 'document' in (value as object) && 'artNames' in (value as object)

export function RoadmapWidget(props: RoadmapWidgetProps): JSX.Element {
  const data = isRoadmapData(props.doc) && props.doc.track === props.track ? props.doc : null
  const built = useMemo(() => {
    if (!data) return null
    try {
      return { model: modelFromDoc(data.document), summary: calmSummary(data.document), error: null }
    } catch (error) {
      return { model: null, summary: null, error: error instanceof Error ? error.message : String(error) }
    }
  }, [data])
  if (!data || !built) {
    // WHY the loading line is the same faint style and not blank: the section is first-class on the track page, and
    // "No roadmap reported yet." must not flash while a slow fetch is still on its way (it would read as a verdict).
    if (props.loading) return <p className="vt-faint vt-small" data-testid="vt-roadmap-loading">Loading roadmap…</p>
    // WHY calm and not an error: a track whose loop writes no roadmap yet is a normal state (the backend's 404).
    return <p className="vt-faint vt-small" data-testid="vt-roadmap-none">No roadmap reported yet.</p>
  }
  if (built.error !== null || !built.model || !built.summary) {
    return <p className="vt-small vt-tone-risk" role="alert" data-testid="vt-roadmap-error">The roadmap could not be drawn: {built.error}</p>
  }
  if (props.density === 'calm') return <CalmAnswer data={data} summary={built.summary} onOpenRung={props.onOpenRung} onOpenEvidence={props.onOpenEvidence} />
  return <FullRoadmap {...props} data={data} model={built.model} />
}

/** When the document was projected, quietly, and, only when the API served an older good document because the
 * projection failed, one calm line saying so. WHY in both densities, in the faint style, with the warning colour only on
 * the failure: a fresh document must not gain a badge (calm UI: colour only for exceptions), but a green "proven" count
 * from a failed projection must never read as current (Codex V05). */
function Freshness({ document }: { document: RoadmapDoc }) {
  const { asOf, notCurrent, notCurrentFull } = freshness(document)
  if (!asOf && !notCurrent) return null
  return (
    <p className="vt-rm-fresh vt-small" data-testid="vt-roadmap-fresh">
      {asOf ? <span className="vt-faint" data-testid="vt-roadmap-asof">{asOf}</span> : null}
      {asOf && notCurrent ? <span className="vt-faint"> · </span> : null}
      {notCurrent ? <span className="vt-tone-warn" role="status" title={notCurrentFull ?? undefined} data-testid="vt-roadmap-not-current">{notCurrent}</span> : null}
    </p>
  )
}

/** The section's head, and its whole body at calm density: one sentence and a thin strip, nothing else
 * (feedback_calm_ui_progressive_disclosure). Current rung(s) first, then what they unlock, then how much is banked.
 * Rung ids open their latest run (onOpenRung); a triage id opens where the question is written, when the document links it. */
function CalmAnswer({ data, summary, onOpenRung, onOpenEvidence }: {
  data: RoadmapData
  summary: ReturnType<typeof calmSummary>
  onOpenRung: (rungId: string) => void
  onOpenEvidence: (ref: { path: string; line?: number }) => void
}) {
  const rungLink = (id: string) => (
    <button key={id} type="button" className="vt-btn vt-rm-textlink" data-testid={`vt-roadmap-calm-rung-${id}`} title={`${id}: open its latest run`} onClick={() => onOpenRung(id)}>{id}</button>
  )
  const join = (items: JSX.Element[]) => items.flatMap((item, i) => (i ? [', ', item] : [item]))
  const rungs = (ids: string[], shown: number) => <>{join(ids.slice(0, shown).map(rungLink))}{ids.length > shown ? <span className="vt-faint"> +{ids.length - shown}</span> : null}</>
  const sources = new Map(data.document.rungs.flatMap((rung) => rung.blockers.map((blocker) => [blocker.id, blocker.source] as const)))
  const needsShown = summary.needs.slice(0, SHOWN.needs)
  const stage = stageLabel(summary)
  // WHY each clause is its own part: the sentence is "current · next · banked · needs you", and a clause with nothing to
  // say (no next, no claimed, no blocker) is left out whole instead of reading "next: none".
  const parts: Array<{ key: string; node: JSX.Element }> = []
  if (stage || summary.current.length) {
    parts.push({
      key: 'current',
      node: (
        <span className="vt-rm-lead" data-testid="vt-roadmap-current" title={phaseToken(summary) ? `phase: ${phaseToken(summary)}` : undefined}>
          {stage}{stage && summary.current.length ? <span className="vt-faint"> · </span> : null}
          {summary.current.length ? <>climbing {rungs(summary.current, SHOWN.current)}</> : null}
        </span>
      ),
    })
  }
  if (summary.next.length) parts.push({ key: 'next', node: <span data-testid="vt-roadmap-next">next {rungs(summary.next, SHOWN.next)}</span> })
  parts.push({ key: 'proven', node: <span className="vt-num">{summary.proven} of {summary.total} proven</span> })
  if (summary.claimed) parts.push({ key: 'claimed', node: <span className="vt-num" title="the loop says green; its evidence does not prove it">{summary.claimed} claimed</span> })
  if (summary.stale) parts.push({ key: 'stale', node: <span className="vt-num vt-tone-stale">{summary.stale} stale</span> })
  if (needsShown.length) {
    parts.push({
      key: 'needs',
      node: (
        <>
          <span className="vt-tone-warn">needs you: {join(needsShown.map((need) => {
            const source = sources.get(need.id)
            return (
              <span key={need.id}>
                {source?.abs
                  ? <button type="button" className="vt-btn vt-rm-textlink" title={need.title} onClick={() => onOpenEvidence(source.line ? { path: source.abs!, line: source.line } : { path: source.abs! })}>{need.id}</button>
                  : <span title={need.title}>{need.id}</span>}
                {' '}(blocks {join(need.blocks.map(rungLink))})
              </span>
            )
          }))}</span>
          {summary.needs.length > SHOWN.needs ? <span className="vt-faint"> +{summary.needs.length - SHOWN.needs}</span> : null}
        </>
      ),
    })
  }
  return (
    <div className="vt-rm-calm" data-testid="vt-roadmap-calm">
      {/* The sentence's words are calmSentence's, so the tested string and the rendered one cannot drift apart. */}
      <p className="vt-rm-answer" data-testid="vt-roadmap-answer" data-sentence={calmSentence(summary)}>
        {parts.map((part, i) => <span key={part.key}>{i ? <span className="vt-faint"> · </span> : null}{part.node}</span>)}
      </p>
      <Freshness document={data.document} />
      <div className="vt-rm-strip" role="img" aria-label={summary.lanes.map((lane) => `${lane.title}: ${lane.proven} of ${lane.total} proven, ${lane.claimed} claimed`).join('; ')} data-testid="vt-roadmap-strip">
        {summary.lanes.map((lane) => (
          <span key={lane.axis} className="vt-rm-strip-lane" style={{ flexGrow: Math.max(1, lane.total) }} title={`${lane.title} · ${lane.proven} of ${lane.total} proven · ${lane.claimed} claimed`}>
            <i className="vt-rm-strip-proven" style={{ width: `${lane.total ? (100 * lane.proven) / lane.total : 0}%` }} />
            <i className="vt-rm-strip-claimed" style={{ width: `${lane.total ? (100 * lane.claimed) / lane.total : 0}%` }} />
          </span>
        ))}
      </div>
    </div>
  )
}

function FullRoadmap({ state, onState, onOpenRung, onOpenEvidence, settings, data, model }: RoadmapWidgetProps & { data: RoadmapData; model: ReturnType<typeof modelFromDoc> }) {
  const view = resolveView(state, (id) => model.byId.has(id), model.hasWaves)
  // Every change goes out through onState, merged over the state as given, so keys the variant keeps survive.
  // The view this widget last asked for: a view that differs from it arrived from outside (history Back/Forward).
  const asked = useRef<string | null>(null)
  const onView = useCallback((next: Partial<RoadView>) => {
    asked.current = viewKey(resolveView({ ...state, ...next }, (id) => model.byId.has(id), model.hasWaves))
    onState({ ...state, ...next })
  }, [onState, state, model])
  const art = useMemo(() => {
    const cache = new Map<string, Art>()
    return (id: string) => {
      if (!cache.has(id)) cache.set(id, artFor(model.byId.get(id)!, data.artNames))
      return cache.get(id)!
    }
  }, [model, data.artNames])
  const cards = useRef(new Map<string, HTMLElement>())
  const sel = view.sel
  // WHY a re-render when the selected rung's card attaches (Codex B12/C06): the board mounts its cards in the same
  // commit as the focus panel, so the panel's one grow can find no card, and a ref landing in a map tells nobody. Only
  // a NEW element for the selected rung counts: card refs are inline callbacks that fire on every render, and
  // re-rendering on each would never stop.
  const [, cardArrived] = useState(0)
  const selected = useRef(sel)
  selected.current = sel
  const announced = useRef<HTMLElement | null>(null)
  const cardRef = useCallback((id: string, element: HTMLElement | null) => {
    if (!element) {
      cards.current.delete(id)
      return
    }
    cards.current.set(id, element)
    if (id === selected.current && element !== announced.current) {
      announced.current = element
      cardArrived((count) => count + 1)
    }
  }, [])
  // WHY the picked card gets focus back after history Back/Forward (focus.ts): the restored state has no focused button,
  // and the board's arrow keys only work from one. A mount counts as restored too: Back can bring the whole board back.
  const shownKey = viewKey(view)
  useEffect(() => {
    const restored = asked.current !== shownKey
    asked.current = null
    restoreBoardFocus(restored, sel, cards.current, document)
  }, [shownKey])
  // WHY Proof first on every fresh pick (Zach: "when it says it's done I want to see proof"); a hop inside the panel keeps its tab.
  const pick = (id: string | null) => onView({ sel: id, trail: [], tab: 'proof' })

  return (
    <section className="vt-rm-full" data-testid="vt-roadmap">
      <Freshness document={data.document} />
      <div className="vt-rm-toprow">
        <LensBar view={view} onView={onView} hasWaves={model.hasWaves} />
        <Legend />
      </div>
      <p className="vt-faint vt-rm-xs">{LENS_CAPTION[view.lens]}{KEYS_HINT}</p>
      <div className="vt-rm-stage" style={{ minHeight: sel ? 640 : undefined }}>
        <RoadmapBoard
          model={model}
          view={view}
          edges={edgeStyle(settings)}
          onPick={pick}
          onStep={(id) => onView({ sel: id, trail: [] })}
          art={art}
          artBase={data.artBase}
          cardLine={cardLine}
          cardRef={cardRef}
        />
        {sel ? (
          <FocusPanel
            model={model}
            view={view}
            onView={onView}
            art={art}
            artNames={data.artNames}
            artBase={data.artBase}
            // The card the panel grows out of, looked up when the panel lays out (Codex A12/B12).
            anchorFor={() => cards.current.get(sel) ?? null}
            onOpenEvidence={onOpenEvidence}
            onOpenRung={onOpenRung}
          />
        ) : null}
      </div>
    </section>
  )
}

/** GET one JSON body through the plugin proxy; a non-2xx answer throws ApiError with the body's `error`. */
async function fetchJson(backend: PluginBackend, path: string, signal: AbortSignal): Promise<unknown> {
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
    throw new ApiError(message, response.status)
  }
  return body
}

/** Loads one track's roadmap document through the plugin backend (the `/roadmap` mount, backend/mounts.py), then keeps
 * it current: a poll every ROADMAP_POLL_MS while mounted, one at a time, aborted on unmount and on a track change.
 * A refresh keeps the previous document on screen (loading is true only for a track's first load); `reload()` forces a
 * re-projection. WHY polling and not a stream: the backend has no event stream yet, and projection is cached
 * server-side, so a poll that finds nothing new is cheap (poll.ts). */
export function useRoadmap(backend: PluginBackend, track: string): RoadmapDocState {
  const [state, setState] = useState<{ track: string; doc: RoadmapData | null; loading: boolean; error: string | null }>({ track, doc: null, loading: true, error: null })
  const poller = useRef<{ reload: () => void } | null>(null)

  useEffect(() => {
    setState({ track, doc: null, loading: true, error: null })
    const artBase = `${backend.baseUrl}/roadmap/art`
    const instance = createPoller({
      intervalMs: ROADMAP_POLL_MS,
      load: createRoadmapLoader({ track, artBase, fetchJson: (path, signal) => fetchJson(backend, path, signal), publish: setState }),
    })
    poller.current = instance
    instance.start()
    return () => {
      instance.stop()
      if (poller.current === instance) poller.current = null
    }
  }, [backend, track])

  const reload = useCallback(() => poller.current?.reload(), [])
  // A track switch shows nothing of the previous track's roadmap while the new one loads.
  return state.track === track ? { doc: state.doc, loading: state.loading, error: state.error, reload } : { doc: null, loading: true, error: null, reload }
}
