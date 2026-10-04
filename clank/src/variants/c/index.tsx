// Variant C: Three panes (Linear / Superhuman / Apple Mail master-detail; Miller columns).
// All three levels sit on screen at once, and one selection drives them: pane 1 picks a track (L1), pane 2 is that
// track's KPI table (L2), pane 3 is the selected KPI's series and, once a point is picked, that point's evidence (L3).
// A thin line above the panes answers the glance.
//
// WHY one shared selection driving every pane (research: "identity colour plus one shared selection drives every
// panel"; intervals.icu header readout): picking an iteration on the chart also turns pane 2's value column into
// "At W2" and rings W2 on every sparkline, so a reader sees what one change did to every KPI without leaving the row.
// WHY Back climbs one level: a deeper level is a pushState (a track from the glance, a point, an item), a sideways
// move (another track, KPI, point or item at the same level) is a replaceState, and Esc steps Back when this page
// pushed the level it leaves, so keyboard and browser Back agree.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { EvidenceItem, Projection, Route, Track, VariantProps } from '../../shared'
import { blockingQuestions, evidenceById, formatDay, formatRoute, kpiById, kpisBySlot, northStar, topLevelTracks, trackById } from '../../shared'
import type { RoadmapWidgetState } from '../../roadmap'
import { useRoadmap } from '../../roadmap'
import { trackView, type TrackView } from './columns'
import { DetailPane, defaultColumn, evidenceLists, type Zone } from './detail'
import { KpiPane, LatestChanges, NeedsAcross, TracksPane } from './panes'
import { evidenceForRung, orderedTracks, upRoute } from './read'
import './c.css'

export const NAME = 'Three panes'

const ZONES: Zone[] = ['tracks', 'kpis', 'chart', 'evidence']

function parseRoadmapState(raw: string | undefined): RoadmapWidgetState {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as RoadmapWidgetState) : {}
  } catch {
    return {}
  }
}

function without(route: Route, ...keys: string[]): Route {
  const next: Route = { ...route }
  for (const key of keys) delete next[key]
  return next
}

export default function VariantC({ projection, route, navigate, mediaUrl, settings, backend, title }: VariantProps) {
  const xAxis = settings.dashboard.xAxis
  const showDeltas = settings.dashboard.showDeltas
  const views = useMemo(() => {
    const cache = new Map<string, TrackView>()
    return (track: Track) => {
      let view = cache.get(track.id)
      if (!view) {
        view = trackView(track, xAxis)
        cache.set(track.id, view)
      }
      return view
    }
  }, [projection, xAxis])

  const track = trackById(projection, route.track)
  const view = track ? views(track) : null
  const kpi = track ? kpiById(track, route.kpi) ?? northStar(track) ?? track.kpis[0] ?? null : null
  const columnId = view ? view.resolve(route.iteration) : null
  const members = view && columnId ? view.members[columnId] ?? [] : []
  const lists = track && kpi && columnId ? evidenceLists(track, kpi, members) : null
  const item: EvidenceItem | null = track && route.item ? evidenceById(track, [route.item])[0] ?? null : null
  const missingItem = route.item && !item ? route.item : null
  const file = route.file ? { path: route.file, line: route.line ? Number(route.line) : undefined } : null
  const roadmapDoc = useRoadmap(backend, track?.id ?? '')

  const [zone, setZone] = useState<Zone>(route.item ? 'evidence' : route.iteration ? 'chart' : route.track ? 'kpis' : 'tracks')
  const [cursor, setCursor] = useState<string | null>(null)
  const [restOpenFor, setRestOpenFor] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)

  // Routes this page pushed, so Esc can step Back (one history) instead of stacking a new entry.
  const pushed = useRef<string[]>([])
  const routeRef = useRef(route)
  routeRef.current = route
  useEffect(() => {
    const here = formatRoute(route)
    if (pushed.current[pushed.current.length - 1] === here) pushed.current.pop()
  }, [route])
  const go = useCallback(
    (next: Route, mode: 'push' | 'replace' = 'replace') => {
      if (mode === 'push') pushed.current.push(formatRoute(routeRef.current))
      routeRef.current = next
      navigate(next, mode)
    },
    [navigate],
  )
  const up = useCallback(() => {
    const parent = upRoute(routeRef.current)
    const target = formatRoute(parent)
    if (pushed.current[pushed.current.length - 1] === target) {
      history.back()
      return
    }
    go(parent, 'replace')
  }, [go])

  useEffect(() => setCursor(null), [columnId, kpi?.id])

  // ---------------------------------------------------------------------------------------------- actions

  const selectTrack = useCallback(
    (id: string) => {
      setZone('tracks')
      if (id === routeRef.current.track) return
      go({ track: id }, routeRef.current.track ? 'replace' : 'push')
    },
    [go],
  )
  const selectKpi = useCallback(
    (id: string) => {
      setZone('kpis')
      go({ ...without(routeRef.current, 'item', 'file', 'line'), kpi: id }, 'replace')
    },
    [go],
  )
  const selectColumn = useCallback(
    (id: string) => {
      if (!kpi) return
      setZone('chart')
      const current = routeRef.current
      go({ ...without(current, 'item', 'file', 'line'), kpi: kpi.id, iteration: id }, current.iteration ? 'replace' : 'push')
    },
    [go, kpi],
  )
  const openItem = useCallback(
    (target: EvidenceItem) => {
      if (!kpi || !view) return
      setZone('evidence')
      setCursor(target.id)
      const current = routeRef.current
      const iteration = current.iteration ?? view.resolve(target.iteration) ?? target.iteration
      if (!current.iteration) go({ ...without(current, 'item', 'file', 'line'), kpi: kpi.id, iteration }, 'push')
      go({ ...without(routeRef.current, 'file', 'line'), kpi: kpi.id, iteration, item: target.id }, routeRef.current.item ? 'replace' : 'push')
    },
    [go, kpi, view],
  )
  const goUp = useCallback(() => {
    const current = routeRef.current
    setZone(current.item || current.file ? 'evidence' : current.iteration ? 'kpis' : 'tracks')
    up()
  }, [up])

  // Roadmap widget: state under `rm` (JSON) in the route, expanded flag under `rmopen`.
  const roadmapState = parseRoadmapState(route.rm)
  const onRoadmapState = useCallback((next: RoadmapWidgetState) => go({ ...routeRef.current, rm: JSON.stringify(next) }, 'replace'), [go])
  const onOpenRung = useCallback(
    (rungId: string) => {
      if (!track || !kpi || !view) return
      const found = evidenceForRung(track, rungId)
      setZone('evidence')
      const iteration = found ? view.resolve(found.iteration) ?? found.iteration : defaultColumn(view, kpi) ?? undefined
      const base = without(routeRef.current, 'item', 'file', 'line')
      if (!routeRef.current.iteration) go({ ...base, kpi: kpi.id, iteration }, 'push')
      go({ ...without(routeRef.current, 'file', 'line'), kpi: kpi.id, iteration, item: found ? found.id : `rung:${rungId}` }, 'push')
    },
    [go, kpi, track, view],
  )
  const onOpenEvidence = useCallback(
    (ref: { path: string; line?: number }) => {
      if (!kpi || !view) return
      setZone('evidence')
      const iteration = routeRef.current.iteration ?? defaultColumn(view, kpi) ?? undefined
      if (!routeRef.current.iteration) go({ ...without(routeRef.current, 'item'), kpi: kpi.id, iteration }, 'push')
      go({ ...without(routeRef.current, 'item'), kpi: kpi.id, iteration, file: ref.path, line: ref.line ? String(ref.line) : undefined }, 'push')
    },
    [go, kpi, view],
  )

  // ---------------------------------------------------------------------------------------------- keyboard
  // ↑/↓ within a pane, ←/→ between panes, Enter drills, Esc goes up (VARIANTS.md C). The chart counts as its own
  // stop between the KPI table and the evidence list, where ↑/↓ steps the selected point earlier/later.

  const evidenceNav = useMemo(() => {
    if (!lists) return []
    return [...lists.behind, ...(restOpenFor === columnId ? lists.rest : [])]
  }, [lists, restOpenFor, columnId])

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
    const target = event.target as HTMLElement
    if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'VIDEO', 'AUDIO', 'IFRAME'].includes(target.tagName)) return
    const key = event.key
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Escape'].includes(key)) return
    // Enter on a focused button (or chart column) is that control's own click; leave it alone.
    if (key === 'Enter' && (target.tagName === 'BUTTON' || target.getAttribute('role') === 'button')) return
    event.preventDefault()
    // WHY stop here: the dock (dockview) around the panel also acts on arrows and Enter and re-renders the panel,
    // which drops focus out of the dashboard; these keys belong to the panes while the dashboard has focus.
    event.stopPropagation()
    const trackIds = orderedTracks(projection).map((row) => row.track.id)
    if (key === 'Escape') {
      if (route.track || route.iteration || route.item) goUp()
      return
    }
    if (!track || !view || !kpi) {
      // The glance: any arrow or Enter picks a track.
      if (key === 'ArrowDown' || key === 'ArrowRight' || key === 'Enter') selectTrack(trackIds[0])
      else if (key === 'ArrowUp') selectTrack(trackIds[trackIds.length - 1])
      return
    }
    const zoneIndex = ZONES.indexOf(zone)
    if (key === 'ArrowLeft') {
      setZone(ZONES[Math.max(0, zoneIndex - 1)])
      return
    }
    if (key === 'ArrowRight') {
      const nextZone = ZONES[Math.min(ZONES.length - 1, zoneIndex + 1)]
      if (nextZone === 'evidence' && !columnId) {
        const col = defaultColumn(view, kpi)
        if (col) selectColumn(col)
      }
      setZone(nextZone)
      return
    }
    const step = key === 'ArrowDown' ? 1 : key === 'ArrowUp' ? -1 : 0
    if (zone === 'tracks') {
      if (step) {
        const at = trackIds.indexOf(track.id)
        selectTrack(trackIds[Math.max(0, Math.min(trackIds.length - 1, at + step))])
      } else setZone('kpis')
      return
    }
    if (zone === 'kpis') {
      if (step) {
        const ids = kpisBySlot(track).flatMap((group) => group.kpis.map((k) => k.id))
        const at = ids.indexOf(kpi.id)
        selectKpi(ids[Math.max(0, Math.min(ids.length - 1, at + step))])
      } else {
        const col = columnId ?? defaultColumn(view, kpi)
        if (col) selectColumn(col)
        setZone('chart')
      }
      return
    }
    if (zone === 'chart') {
      const ids = view.columns.map((col) => col.id)
      if (step) {
        const at = columnId ? ids.indexOf(columnId) : ids.indexOf(defaultColumn(view, kpi) ?? '')
        const nextCol = ids[Math.max(0, Math.min(ids.length - 1, (at < 0 ? ids.length - 1 : at) + (columnId ? step : 0)))]
        if (nextCol) selectColumn(nextCol)
        setZone('chart')
      } else {
        if (!columnId) {
          const col = defaultColumn(view, kpi)
          if (col) selectColumn(col)
        }
        setZone('evidence')
        setCursor(evidenceNav[0]?.id ?? null)
      }
      return
    }
    // evidence
    if (item) {
      if (step) {
        const siblings = lists ? [...lists.behind, ...lists.rest] : []
        const at = siblings.findIndex((candidate) => candidate.id === item.id)
        const nextItem = siblings[at + step]
        if (nextItem) openItem(nextItem)
      }
      return
    }
    if (step) {
      if (!evidenceNav.length) return
      const at = cursor ? evidenceNav.findIndex((candidate) => candidate.id === cursor) : -1
      const nextItem = evidenceNav[Math.max(0, Math.min(evidenceNav.length - 1, at + step))]
      setCursor(nextItem.id)
      root.current?.querySelector(`[data-item-id="${CSS.escape(nextItem.id)}"]`)?.scrollIntoView({ block: 'nearest' })
    } else if (cursor) {
      const chosen = evidenceNav.find((candidate) => candidate.id === cursor)
      if (chosen) openItem(chosen)
    }
  }

  const keyHandler = useRef(onKeyDown)
  keyHandler.current = onKeyDown
  useEffect(() => {
    const element = root.current
    if (!element) return
    // A native listener on the variant's root runs before the dock's listeners on its ancestors (React's own
    // onKeyDown is delegated to the app root, too late to stop them).
    const listener = (event: KeyboardEvent) => keyHandler.current(event)
    element.addEventListener('keydown', listener)
    // WHY win focus back after a focusout nobody asked for: the dock re-mounts the panel's DOM when it activates the
    // panel (first focus, or a route change), which drops focus to <body> and kills the arrow keys mid-walk. A focus
    // loss with no pointer press just before it is that re-mount, never the reader clicking elsewhere.
    let lastPointer = 0
    const onPointer = () => {
      lastPointer = performance.now()
    }
    const onFocusOut = (event: FocusEvent) => {
      if (event.relatedTarget) return
      window.setTimeout(() => {
        const idle = performance.now() - lastPointer > 400
        if (idle && element.isConnected && (document.activeElement === document.body || document.activeElement === null)) {
          element.focus({ preventScroll: true })
        }
      }, 0)
    }
    window.addEventListener('pointerdown', onPointer, true)
    element.addEventListener('focusout', onFocusOut)
    return () => {
      element.removeEventListener('keydown', listener)
      element.removeEventListener('focusout', onFocusOut)
      window.removeEventListener('pointerdown', onPointer, true)
    }
  }, [])

  // Keep keyboard focus inside the variant after a click on a non-focusable spot, so the arrows keep working.
  const keepFocus = () => {
    // Deferred: a click that opens a level re-renders the pane and removes the button that had focus, which drops
    // focus to <body> without a focusout; checking after the render keeps Esc and the arrows working.
    window.setTimeout(() => {
      const active = document.activeElement
      if (root.current?.isConnected && (!active || active === document.body || !root.current.contains(active))) {
        root.current.focus({ preventScroll: true })
      }
    }, 0)
  }

  const level = !track ? 1 : route.iteration || route.item ? 3 : 2

  return (
    <div
      ref={root}
      className="vt-c"
      data-testid="vt-variant-c"
      data-level={level}
      data-zone={zone}
      tabIndex={-1}
      onClick={keepFocus}
    >
      <Glance projection={projection} title={title} onHome={track ? () => go({}, 'push') : undefined} />
      <div className="vt-c-panes">
        <nav className={`vt-c-pane vt-c-pane-1${zone === 'tracks' ? ' vt-c-zone-active' : ''}`} aria-label="Tracks" onMouseDown={() => setZone('tracks')}>
          <TracksPane projection={projection} views={views} selected={track?.id ?? null} active={zone === 'tracks'} onSelect={selectTrack} />
          <p className="vt-c-keys vt-faint">
            <kbd>↑</kbd>
            <kbd>↓</kbd> move · <kbd>←</kbd>
            <kbd>→</kbd> panes · <kbd>Enter</kbd> open · <kbd>Esc</kbd> up
          </p>
        </nav>
        <section className={`vt-c-pane vt-c-pane-2${zone === 'kpis' ? ' vt-c-zone-active' : ''}`} aria-label="KPIs" onMouseDown={() => track && setZone('kpis')}>
          {track && view && kpi ? (
            <KpiPane
              track={track}
              view={view}
              selectedKpi={kpi.id}
              selectedColumn={columnId}
              active={zone === 'kpis'}
              showDeltas={showDeltas}
              needsOpen={route.needs === '1'}
              onToggleNeeds={() => go(route.needs === '1' ? without(route, 'needs') : { ...route, needs: '1' }, 'replace')}
              onSelectKpi={selectKpi}
              roadmap={{
                track,
                doc: roadmapDoc.doc,
                state: roadmapState,
                open: route.rmopen === '1',
                settings: settings.roadmap,
                onToggle: () => go(route.rmopen === '1' ? without(route, 'rmopen') : { ...route, rmopen: '1' }, 'replace'),
                onState: onRoadmapState,
                onOpenRung,
                onOpenEvidence,
              }}
            />
          ) : (
            <NeedsAcross projection={projection} onOpen={(id) => go({ track: id, needs: '1' }, 'push')} />
          )}
        </section>
        <section
          className={`vt-c-pane vt-c-pane-3${zone === 'chart' || zone === 'evidence' ? ' vt-c-zone-active' : ''}`}
          aria-label="Series and evidence"
          onMouseDown={() => track && setZone(route.iteration ? 'evidence' : 'chart')}
        >
          {track && view && kpi ? (
            <DetailPane
              track={track}
              view={view}
              kpi={kpi}
              columnId={columnId}
              item={item}
              missingItem={missingItem}
              file={file}
              media={projection.media}
              mediaUrl={mediaUrl}
              showDeltas={showDeltas}
              zone={zone}
              cursor={cursor}
              restOpen={restOpenFor === columnId && columnId !== null}
              onToggleRest={() => setRestOpenFor(restOpenFor === columnId ? null : columnId)}
              onSelectColumn={selectColumn}
              onOpenItem={openItem}
              onUp={goUp}
            />
          ) : (
            <LatestChanges
              projection={projection}
              onOpen={(trackId, iterationId) => {
                go({ track: trackId }, 'push')
                go({ track: trackId, iteration: iterationId }, 'push')
                setZone('evidence')
              }}
            />
          )}
        </section>
      </div>
    </div>
  )
}

/** The thin line above the panes: the one-sentence glance ("2 loops · 1 paused · 1 at risk · 7 questions block a
 * rung"), colour only on the exceptions, and how fresh the data is. */
function Glance({ projection, title, onHome }: { projection: Projection; title: string; onHome?: () => void }) {
  const loops = topLevelTracks(projection)
  const deployments = projection.tracks.filter((track) => track.parent)
  const words = (tracks: Track[]) => {
    const counts = new Map<string, { count: number; tone: string }>()
    for (const track of tracks) {
      const entry = counts.get(track.state.word) ?? { count: 0, tone: track.state.tone }
      entry.count += 1
      counts.set(track.state.word, entry)
    }
    return [...counts.entries()]
  }
  const blocking = projection.tracks.reduce((sum, track) => sum + blockingQuestions(track).length, 0)
  return (
    <header className="vt-c-glance" data-testid="vt-c-glance">
      {onHome ? (
        <button type="button" className="vt-btn vt-c-title" title="Back to the glance" onClick={onHome}>
          {title}
        </button>
      ) : (
        <span className="vt-c-title">{title}</span>
      )}
      <span className="vt-c-glance-text" title={`${loops.length} loops and ${deployments.length} deployments`}>
        {loops.length} loops
        {words(loops).map(([word, { count, tone }]) => (
          <span key={word} className={`vt-tone-${tone}`}>
            {' · '}
            {count} {word.toLowerCase()}
          </span>
        ))}
        {blocking ? <span className="vt-tone-warn"> · {blocking} questions block a rung</span> : null}
        <span className="vt-c-glance-sep" aria-hidden="true" />
        {deployments.length} deployments
        {words(deployments).map(([word, { count, tone }]) => (
          <span key={word} className={`vt-tone-${tone}`}>
            {' · '}
            {count} {word.toLowerCase()}
          </span>
        ))}
      </span>
      <span className="vt-c-glance-end vt-faint vt-small">
        as of {formatDay(projection.as_of)} · {projection.source.live ? 'live' : 'snapshot, not live'}
      </span>
    </header>
  )
}
