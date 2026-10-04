// Variant B: Shared timeline (Grafana annotations + intervals.icu's shared readout + Rerun's single cursor + Tufte's
// small multiples), in the calm language of "The Table".
//
//   L1  the loop tabs across the top (deployments as secondary tabs under the rig) and, with no tab chosen, the
//       glance: one quiet row per track.
//   L2  the KPI wall: one row per KPI, every row on ONE aligned x-axis of the track's iterations, change markers as
//       hairlines through every row, one cursor that makes every row print its value at that iteration.
//   L3  a bottom drawer for one iteration: its marker and provenance, its evidence, a run's metrics and video inline.
//
// Place lives in the shared URL hash (track · iteration · item · kpi), so Back climbs one level. B adds: `d` (how many
// Back steps the open drawer is deep, so × and Esc close it in one go), `ny` (the Needs-you list open), `rm`/`rmx`
// (the roadmap widget's state and whether it is expanded), `file`/`line`/`rung` (the roadmap widget's L3 requests).
// WHY no view option is a control here: x-axis and deltas come from the settings page (props.settings.dashboard), per
// Zach 2026-10-03 "the tool bar is actually usable … this line setting should instead be in a settings page".

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Kpi, Route, Track, VariantProps } from '../../shared'
import {
  Sparkline,
  StatusWord,
  allEvidence,
  blockingQuestions,
  childrenOf,
  deltaVsBaseline,
  describeDelta,
  evidenceAt,
  formatDay,
  formatKpiValue,
  formatValue,
  latestIteration,
  latestValue,
  northStar,
  toneClass,
  topLevelTracks,
  trackById,
} from '../../shared'
import { RoadmapWidget, useRoadmap, type RoadmapWidgetState } from '../../roadmap'
import { buildColumns, columnIndexOfIteration, shortMarker, type XAxis } from './columns'
import { Drawer } from './Drawer'
import { Wall } from './Wall'
import './shared-timeline.css'

export const NAME = 'Shared timeline'

/** Hashes this page pushed for a drawer, so closing it may step Back over them (never past a pasted link). */
const pushedDrawerHashes = new Set<string>()

const DRAWER_KEYS = ['iteration', 'item', 'kpi', 'd', 'file', 'line', 'rung']

function without(route: Route, keys: string[]): Route {
  const next: Route = { ...route }
  for (const key of keys) delete next[key]
  return next
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'VIDEO'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

export default function VariantB(props: VariantProps) {
  const { projection, route, navigate, settings, mediaUrl } = props
  const root = useRef<HTMLDivElement>(null)
  const track = trackById(projection, route.track)
  const xAxis: XAxis = settings.dashboard.xAxis === 'day' ? 'day' : 'iteration'
  const showDeltas = settings.dashboard.showDeltas !== false
  const columns = useMemo(() => (track ? buildColumns(track, xAxis) : []), [track, xAxis])
  const drawerOpen = Boolean(track && (route.iteration || route.item))
  const drawerIteration = track ? route.iteration ?? (route.item ? allEvidence(track).find((it) => it.id === route.item)?.iteration : undefined) ?? null : null
  const selectedColumn = drawerIteration ? columnIndexOfIteration(columns, drawerIteration) : -1
  const [hover, setHover] = useState<number | null>(null)
  const [keyCursor, setKeyCursor] = useState<number | null>(null)
  useEffect(() => {
    setHover(null)
    setKeyCursor(null)
  }, [route.track, xAxis])
  const cursor = hover ?? keyCursor ?? (selectedColumn >= 0 ? selectedColumn : null)

  const go = useCallback((next: Route, mode: 'push' | 'replace') => navigate(next, mode), [navigate])

  // WHY scroll the wall up under the drawer: the drawer's point is to read the evidence WITH the wall's cursor parked
  // on the same column; left where it was, the drawer would cover the very rows that column belongs to.
  useEffect(() => {
    if (!drawerOpen) return
    const frame = requestAnimationFrame(() => {
      const scroller = root.current?.closest('.vt-scroll') as HTMLElement | null
      const wall = root.current?.querySelector('[data-testid="vt-b-wall"]') as HTMLElement | null
      const drawer = root.current?.querySelector('[data-testid="vt-b-drawer"]') as HTMLElement | null
      if (!scroller || !wall) return
      const base = scroller.getBoundingClientRect().top - scroller.scrollTop
      let target = wall.getBoundingClientRect().top - base - 4
      const visible = scroller.clientHeight - (drawer?.getBoundingClientRect().height ?? 0)
      const row = route.kpi ? (wall.querySelector(`[data-kpi="${CSS.escape(route.kpi)}"]`) as HTMLElement | null) : null
      if (row) {
        const rowBottom = row.getBoundingClientRect().bottom - base
        if (rowBottom - target > visible - 8) target = rowBottom - visible + 8
      }
      scroller.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(frame)
  }, [drawerOpen, route.kpi, route.track])

  const openColumn = useCallback(
    (index: number, kpiId?: string) => {
      if (!track) return
      const column = columns[index]
      if (!column) return
      const iteration = column.iterations[column.iterations.length - 1].id
      const base = without(route, DRAWER_KEYS)
      const next: Route = { ...base, track: track.id, iteration, ...(kpiId ? { kpi: kpiId } : {}) }
      if (drawerOpen) {
        go({ ...next, d: route.d ?? '1' }, 'replace')
      } else {
        go({ ...next, d: '1' }, 'push')
        pushedDrawerHashes.add(location.hash)
      }
    },
    [track, columns, route, drawerOpen, go],
  )

  const closeDrawer = useCallback(() => {
    const depth = Number(route.d ?? 0)
    // WHY step Back rather than replace: a replace would leave the drawer's entries behind the wall, so the next Back
    // would reopen the drawer instead of climbing to L1.
    if (depth > 0 && pushedDrawerHashes.has(location.hash)) {
      history.go(-depth)
      return
    }
    go(without(route, DRAWER_KEYS), 'replace')
  }, [route, go])

  const setIteration = useCallback(
    (iterationId: string) => go({ ...without(route, ['item', 'file', 'line', 'rung']), iteration: iterationId }, 'replace'),
    [route, go],
  )

  const setItem = useCallback(
    (itemId: string) => {
      const base = without(route, ['file', 'line', 'rung'])
      if (route.item) {
        go({ ...base, item: itemId }, 'replace')
        return
      }
      go({ ...base, item: itemId, d: String(Number(route.d ?? 0) + 1) }, 'push')
      pushedDrawerHashes.add(location.hash)
    },
    [route, go],
  )

  const setKpi = useCallback(
    (kpiId: string | null) => {
      const next = without(route, ['kpi'])
      go(kpiId ? { ...next, kpi: kpiId } : next, 'replace')
    },
    [route, go],
  )

  // Keys while the dashboard has focus: ←/→ move the cursor (or the drawer's iteration), Enter opens the cursor's
  // iteration, Esc closes the drawer. Same focus guards as the shell's 1/2/3 keys.
  useEffect(() => {
    if (!track) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || isEditable(event.target)) return
      const frame = root.current?.closest('.vt-dash') ?? root.current
      const inside = event.target instanceof Node && Boolean(frame?.contains(event.target))
      const onBody = event.target === document.body || event.target === document.documentElement
      if (!inside && !onBody) return
      if (event.target instanceof HTMLElement && event.target.closest('.vt-switcher')) return
      const n = columns.length
      if (event.key === 'Escape') {
        if (drawerOpen) {
          event.preventDefault()
          closeDrawer()
        } else if (keyCursor !== null) {
          event.preventDefault()
          setKeyCursor(null)
        }
        return
      }
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault()
        const step = event.key === 'ArrowLeft' ? -1 : 1
        if (drawerOpen && drawerIteration) {
          const at = track.iterations.findIndex((it) => it.id === drawerIteration)
          const next = track.iterations[at + step]
          if (next) setIteration(next.id)
          return
        }
        const from = keyCursor ?? hover ?? n
        setHover(null)
        setKeyCursor(Math.min(n - 1, Math.max(0, from + step)))
        return
      }
      if (event.key === 'Enter' && !drawerOpen && keyCursor !== null && !(event.target instanceof HTMLButtonElement)) {
        event.preventDefault()
        openColumn(keyCursor)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [track, columns, drawerOpen, drawerIteration, keyCursor, hover, closeDrawer, setIteration, openColumn])

  return (
    <div ref={root} className={`vt-b${drawerOpen ? ' has-drawer' : ''}`} data-testid="vt-variant-b">
      <Tabs projection={projection} track={track} title={props.title} route={route} go={go} />
      {track ? (
        <TrackView
          {...props}
          track={track}
          columns={columns}
          cursor={cursor}
          selectedColumn={selectedColumn >= 0 ? selectedColumn : null}
          onCursor={(index) => {
            setHover(index)
            if (index !== null) setKeyCursor(null)
          }}
          onOpen={openColumn}
          showDeltas={showDeltas}
        />
      ) : (
        <Glance projection={projection} go={go} route={route} />
      )}
      {track && drawerOpen && drawerIteration ? (
        <Drawer
          projection={projection}
          track={track}
          columns={columns}
          iterationId={drawerIteration}
          itemId={route.item ?? null}
          kpiId={route.kpi ?? null}
          file={route.file ? { path: route.file, line: route.line ? Number(route.line) : undefined } : null}
          rung={route.rung ?? null}
          mediaUrl={mediaUrl}
          showDeltas={showDeltas}
          onClose={closeDrawer}
          onIteration={setIteration}
          onItem={setItem}
          onKpi={setKpi}
        />
      ) : null}
      <DataProof projection={projection} />
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ L1: tabs + glance

function Dot({ tone }: { tone: Track['state']['tone'] }) {
  return (
    <span className={`vt-status ${toneClass(tone)}`} aria-hidden="true">
      <span className="vt-dot" />
    </span>
  )
}

function Tabs({ projection, track, title, route, go }: { projection: VariantProps['projection']; track: Track | null; title: string; route: Route; go: (r: Route, mode: 'push' | 'replace') => void }) {
  const loops = topLevelTracks(projection)
  const activeLoop = track ? (track.parent ? trackById(projection, track.parent) : track) : null
  const deployments = activeLoop ? childrenOf(projection, activeLoop.id) : []
  const pick = (id: string) => {
    if (route.track === id) return
    // WHY push from the glance but replace between tabs: entering a track is a level (Back returns to the glance);
    // moving between tabs is sideways, and Back should not replay every tab the reader looked at.
    go({ track: id }, route.track ? 'replace' : 'push')
  }
  return (
    <nav className="vt-b-tabs" aria-label="Loops" data-testid="vt-b-tabs">
      <div className="vt-b-tabrow">
        <button type="button" className={`vt-btn vt-b-home${track ? '' : ' is-active'}`} aria-current={track ? undefined : 'page'} onClick={() => track && go({}, 'push')} data-testid="vt-b-home">
          {title}
        </button>
        {loops.map((loop) => (
          <button
            key={loop.id}
            type="button"
            className={`vt-btn vt-b-tab${activeLoop?.id === loop.id ? ' is-active' : ''}`}
            aria-current={activeLoop?.id === loop.id ? 'page' : undefined}
            onClick={() => pick(loop.id)}
            title={`${loop.state.word} · ${loop.state.detail}`}
            data-testid="vt-b-tab"
            data-track={loop.id}
          >
            <Dot tone={loop.state.tone} />
            {loop.title}
          </button>
        ))}
      </div>
      {deployments.length && activeLoop ? (
        <div className="vt-b-subrow" data-testid="vt-b-subtabs">
          <button
            type="button"
            className={`vt-btn vt-b-subtab${track?.id === activeLoop.id ? ' is-active' : ''}`}
            onClick={() => pick(activeLoop.id)}
            data-testid="vt-b-subtab"
            data-track={activeLoop.id}
          >
            Loop
          </button>
          <span className="vt-faint vt-small vt-b-subsep">Deployments</span>
          {deployments.map((deployment) => (
            <button
              key={deployment.id}
              type="button"
              className={`vt-btn vt-b-subtab${track?.id === deployment.id ? ' is-active' : ''}`}
              onClick={() => pick(deployment.id)}
              title={`${deployment.state.word} · ${deployment.state.detail}`}
              data-testid="vt-b-subtab"
              data-track={deployment.id}
            >
              <Dot tone={deployment.state.tone} />
              {deployment.title}
            </button>
          ))}
        </div>
      ) : null}
    </nav>
  )
}

/** The headline number of a track's north star: the day summary for a deployment, the latest value for a loop. */
function headline(track: Track, kpi: Kpi): { value: string; sub: string } {
  const aggregate = kpi.aggregate
  if (track.kind === 'deployment' && aggregate && aggregate.value !== null) {
    return { value: formatValue(aggregate.value, kpi.unit), sub: `${aggregate.label}${aggregate.n !== null ? ` · n = ${aggregate.n}` : ''}` }
  }
  const latest = latestValue(kpi)
  const delta = deltaVsBaseline(kpi)
  return { value: formatKpiValue(kpi, latest), sub: delta ? describeDelta(kpi, delta) : kpi.target?.label ?? '' }
}

function Glance({ projection, go, route }: { projection: VariantProps['projection']; go: (r: Route, mode: 'push' | 'replace') => void; route: Route }) {
  const loops = topLevelTracks(projection)
  const rows = loops.flatMap((loop) => [loop, ...childrenOf(projection, loop.id)])
  const blocking = projection.tracks.reduce((sum, track) => sum + blockingQuestions(track).length, 0)
  const counts = new Map<string, number>()
  for (const loop of loops) counts.set(loop.state.word.toLowerCase(), (counts.get(loop.state.word.toLowerCase()) ?? 0) + 1)
  const stateText = [...counts.entries()].map(([word, count]) => `${count} ${count === 1 ? 'loop' : 'loops'} ${word}`).join(', ')
  return (
    <div className="vt-b-page" data-testid="vt-b-glance">
      <p className="vt-b-state">
        {formatDay(projection.as_of)} {projection.as_of.slice(0, 4)} · {stateText} · {blocking} {blocking === 1 ? 'question blocks' : 'questions block'} a rung. Pick a
        loop to see every KPI on one timeline.
      </p>
      <table className="vt-table vt-b-glance">
        <thead>
          <tr>
            <th style={{ width: '27%' }}>Track</th>
            <th style={{ width: '24%' }}>Status</th>
            <th style={{ width: '22%' }}>North star</th>
            <th style={{ width: '15%' }}>Last moved</th>
            <th>Needs you</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((track) => {
            const star = northStar(track)
            const head = star ? headline(track, star) : null
            const last = latestIteration(track)
            const blocks = blockingQuestions(track).length
            const values = star ? star.values.map((value) => (value.measured ? value.value : null)) : []
            const scope = star?.target?.kind === 'scope' && star.target.value !== undefined ? star.target.value : null
            return (
              <tr
                key={track.id}
                className="vt-row-link"
                onClick={() => go({ ...route, track: track.id }, 'push')}
                data-testid="vt-b-glance-row"
                data-track={track.id}
              >
                <td>
                  <button type="button" className={`vt-btn vt-b-glance-name${track.parent ? ' is-child' : ''}`} onClick={(event) => {
                    event.stopPropagation()
                    go({ ...route, track: track.id }, 'push')
                  }}>
                    {track.parent ? <span className="vt-faint">↳ </span> : null}
                    {track.title}
                  </button>
                </td>
                <td>
                  <StatusWord status={track.state} detail={track.state.detail} />
                </td>
                <td>
                  {star && head ? (
                    <span className="vt-b-star">
                      <span className="vt-status-stack">
                        <span className="vt-strong vt-num">{head.value}</span>
                        <small style={{ paddingLeft: 0 }}>{star.label}</small>
                      </span>
                      <Sparkline values={values} step={scope !== null} domain={scope !== null ? [0, scope] : undefined} ariaLabel={`${star.label} over ${values.length} ${track.iteration.unit}s`} />
                    </span>
                  ) : (
                    <span className="vt-faint">no north star</span>
                  )}
                </td>
                <td>
                  {last ? (
                    <span className="vt-status-stack">
                      <span>{last.date ? formatDay(last.date) : 'no date recorded'}</span>
                      <small style={{ paddingLeft: 0 }} title={last.marker}>
                        {last.label} · {shortMarker(last.marker, 22)}
                      </small>
                    </span>
                  ) : (
                    <span className="vt-faint">—</span>
                  )}
                </td>
                <td>
                  {track.needs_you.length ? (
                    <span className="vt-status-stack">
                      <span className={blocks ? 'vt-tone-warn vt-strong' : ''}>{blocks ? `${blocks} blocking` : 'none blocking'}</span>
                      <small style={{ paddingLeft: 0 }}>{track.needs_you.length} open</small>
                    </span>
                  ) : (
                    <span className="vt-faint">none open</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ L2: the track

interface TrackViewProps extends VariantProps {
  track: Track
  columns: ReturnType<typeof buildColumns>
  cursor: number | null
  selectedColumn: number | null
  onCursor: (index: number | null) => void
  onOpen: (index: number, kpiId?: string) => void
  showDeltas: boolean
}

function TrackView({ projection, track, columns, cursor, selectedColumn, onCursor, onOpen, showDeltas, route, navigate, backend, settings, mediaUrl }: TrackViewProps) {
  const star = northStar(track)
  const head = star ? headline(track, star) : null
  const last = latestIteration(track)
  const blocking = blockingQuestions(track)
  const needsOpen = route.ny === '1'
  const cursorColumn = cursor !== null ? columns[cursor] : null
  const readColumn = cursorColumn ?? columns[columns.length - 1] ?? null
  const evidenceCount = readColumn ? readColumn.iterations.reduce((sum, it) => sum + evidenceAt(track, it.id).length, 0) : 0
  const roadmap = useRoadmap(backend, track.id)
  const rmState = useMemo<RoadmapWidgetState>(() => {
    try {
      return route.rm ? (JSON.parse(route.rm) as RoadmapWidgetState) : {}
    } catch {
      return {}
    }
  }, [route.rm])
  const rmOpen = route.rmx === '1'
  const [copied, setCopied] = useState<string | null>(null)

  const openRung = (rungId: string) => {
    // onOpenRung: the rung's latest judged run, else a note that names the rung, else the latest iteration saying so.
    const items = allEvidence(track)
    const runs = items.filter((item) => item.kind === 'run' && item.title.startsWith(`${rungId} ·`))
    runs.sort((a, b) => (a.when ?? '').localeCompare(b.when ?? ''))
    const run = runs[runs.length - 1] ?? [...items].reverse().find((item) => item.kind === 'note' && rungId in item.metrics)
    const base = without(route, DRAWER_KEYS)
    if (run) navigate({ ...base, iteration: run.iteration, item: run.id, d: '1' }, 'push')
    else navigate({ ...base, iteration: last?.id ?? '', rung: rungId, d: '1' }, 'push')
    pushedDrawerHashes.add(location.hash)
  }
  const openEvidence = (ref: { path: string; line?: number }) => {
    const base = without(route, DRAWER_KEYS)
    navigate({ ...base, iteration: route.iteration ?? last?.id ?? '', file: ref.path, ...(ref.line ? { line: String(ref.line) } : {}), d: '1' }, 'push')
    pushedDrawerHashes.add(location.hash)
  }

  return (
    <div className="vt-b-page" data-testid="vt-b-track" data-track={track.id}>
      <p className="vt-b-state" data-testid="vt-b-state" title={track.summary}>
        <StatusWord status={track.state} />
        <span> · {track.state.detail}</span>
        {star && head ? (
          <span>
            {' '}
            · north star {star.label} <b className="vt-num">{head.value}</b>
            {head.sub ? ` (${head.sub})` : ''}
          </span>
        ) : null}
      </p>
      {track.needs_you.length ? (
        <div className="vt-b-needs">
          <button
            type="button"
            className="vt-btn vt-b-needs-btn"
            aria-expanded={needsOpen}
            onClick={() => navigate(needsOpen ? without(route, ['ny']) : { ...route, ny: '1' }, 'replace')}
            data-testid="vt-b-needs"
          >
            <span className="vt-b-caret" aria-hidden="true">
              {needsOpen ? '▾' : '▸'}
            </span>
            Needs you · {blocking.length ? <span className="vt-tone-warn vt-strong">{blocking.length} block a rung</span> : 'none blocking'} · {track.needs_you.length} open
          </button>
          {needsOpen ? (
            <ul className="vt-b-needs-list">
              {[...blocking, ...track.needs_you.filter((question) => question.blocks.length === 0)].map((question) => (
                <li key={question.id} className={question.blocks.length ? '' : 'is-quiet'}>
                  <span className="vt-faint vt-num">{question.id}</span>
                  <span>{question.q}</span>
                  <span className="vt-faint vt-small">
                    {question.blocks.length ? `blocks ${question.blocks.join(', ')}` : 'blocks nothing'} · {question.default ? `default: ${question.default}` : 'no default recorded'}
                    {question.applies ? ` · ${question.applies}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="vt-b-needs vt-faint vt-small">No open questions.</p>
      )}

      <p className="vt-b-readout" data-testid="vt-b-readout">
        {readColumn ? (
          <>
            <span className="vt-faint">{cursorColumn ? 'Cursor' : 'Latest'}</span> <b>{readColumn.title}</b>
            <span className="vt-b-readout-marker"> · {readColumn.marker}</span>
            <span className="vt-faint">
              {' '}
              · {evidenceCount} {evidenceCount === 1 ? 'item' : 'items'} of evidence ·{' '}
              {cursorColumn ? (selectedColumn === cursor ? 'open below' : 'click or Enter to open') : 'hover a column to read every KPI there, click it for the evidence'}
            </span>
          </>
        ) : (
          <span className="vt-faint">No iterations recorded.</span>
        )}
      </p>

      <Wall track={track} columns={columns} cursor={cursor} selected={selectedColumn} selectedKpi={route.kpi ?? null} onCursor={onCursor} onOpen={onOpen} showDeltas={showDeltas} />

      <section className="vt-b-section" data-testid="vt-b-roadmap">
        <button
          type="button"
          className="vt-btn vt-b-sechead"
          aria-expanded={rmOpen}
          onClick={() => navigate(rmOpen ? without(route, ['rmx']) : { ...route, rmx: '1' }, 'replace')}
        >
          <span className="vt-b-caret" aria-hidden="true">
            {rmOpen ? '▾' : '▸'}
          </span>
          Roadmap
        </button>
        <div className="vt-b-secbody">
          <RoadmapWidget
            track={track.id}
            doc={roadmap.doc}
            state={rmState}
            onState={(next) => navigate({ ...route, rm: JSON.stringify(next) }, 'replace')}
            onOpenRung={openRung}
            onOpenEvidence={openEvidence}
            density={rmOpen ? 'full' : 'calm'}
            settings={settings.roadmap}
          />
        </div>
      </section>

      {track.links.length ? (
        <section className="vt-b-section vt-b-sources">
          <span className="vt-label">Sources</span>
          {track.links.map((link) =>
            link.kind === 'media' && link.media ? (
              <a key={link.label} href={mediaUrl(link.media)} target="_blank" rel="noreferrer">
                {link.label}
              </a>
            ) : (
              <span key={link.label} className="vt-b-pathlink">
                {link.label}{' '}
                <button
                  type="button"
                  className="vt-btn vt-b-link"
                  title={link.value}
                  onClick={() => void navigator.clipboard?.writeText(link.value ?? '').then(() => setCopied(link.label), () => setCopied(null))}
                >
                  {copied === link.label ? 'path copied' : '· copy path'}
                </button>
              </span>
            ),
          )}
        </section>
      ) : null}
      <p className="vt-b-prov vt-b-trackprov" title={track.provenance.source ?? undefined}>
        {projection.source.live ? 'live' : 'snapshot'} of {projection.source.snapshot_generated_at?.replace('T', ' ').slice(0, 16) ?? projection.as_of} · adapter {projection.source.adapter}
        {projection.source.live ? '' : ' · not live yet'}
      </p>
    </div>
  )
}

function DataProof({ projection }: { projection: VariantProps['projection'] }) {
  const kpis = projection.tracks.reduce((sum, track) => sum + track.kpis.length, 0)
  return (
    <p className="vt-b-proof" data-testid="vt-data-proof">
      {projection.tracks.length} tracks · {kpis} KPIs · {Object.keys(projection.media).length} media · as of {projection.as_of}
    </p>
  )
}
