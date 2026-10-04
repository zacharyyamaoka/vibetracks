// Panes 1 and 2 of Variant C (and what panes 2 and 3 show at the glance, before a track is picked).
// Pane 1 = L1, the tracks list. Pane 2 = L2, the selected track's KPI table (latest · Δ · trend · status, grouped by
// slot) with the Needs-you line on top and the Roadmap section under it.

import { useEffect, useRef, type RefObject } from 'react'
import type { Kpi, Projection, Track } from '../../shared'
import {
  N1_WORD,
  Sparkline,
  StatusWord,
  blockingQuestions,
  deltaTone,
  deltaVsPrevious,
  formatDay,
  formatDelta,
  formatKpiValue,
  formatN,
  kpisBySlot,
  latestIteration,
  measuredValues,
  northStar,
  toneClass,
  valueAt,
} from '../../shared'
import type { RoadmapSettings, RoadmapWidgetState } from '../../roadmap'
import { RoadmapWidget } from '../../roadmap'
import type { TrackView } from './columns'
import { headline, headlineDelta, orderedTracks, plural } from './read'

// ------------------------------------------------------------------------------------------------ pane 1

export function TracksPane({
  projection,
  views,
  selected,
  active,
  onSelect,
}: {
  projection: Projection
  views: (track: Track) => TrackView
  selected: string | null
  active: boolean
  onSelect: (trackId: string) => void
}) {
  const rows = orderedTracks(projection)
  return (
    <ul className="vt-c-tracks" role="listbox" aria-label="Tracks" data-testid="vt-c-tracks">
      {rows.map(({ track, depth }, index) => {
        const star = northStar(track)
        const view = views(track)
        const starView = star ? view.kpi(star) : null
        const head = star ? headline(track, star) : null
        const blocking = blockingQuestions(track).length
        const open = track.needs_you.length
        const latest = latestIteration(track)
        const isSelected = track.id === selected
        const firstChild = depth === 1 && rows[index - 1]?.depth === 0
        return (
          <li key={track.id}>
            {firstChild ? <p className="vt-c-subgroup">Deployments · evidence for {rows[index - 1].track.title}</p> : null}
            <button
              type="button"
              role="option"
              aria-selected={isSelected}
              className={`vt-btn vt-c-track${depth ? ' vt-c-child' : ''}${isSelected ? ' vt-c-sel' : ''}${isSelected && active ? ' vt-c-active' : ''}`}
              data-testid="vt-c-track"
              data-track={track.id}
              title={`${track.title}: ${track.summary}`}
              onClick={() => onSelect(track.id)}
            >
              <span className="vt-c-track-title">{track.title}</span>
              <span className="vt-c-track-line">
                <StatusWord status={track.state} />
                {depth === 0 ? <span className="vt-faint"> · {track.iteration.label}</span> : null}
              </span>
              {star && head && starView ? (
                <span className="vt-c-track-line vt-c-track-star" title={`${star.label}: ${head.text} (${head.label})`}>
                  <span className="vt-strong vt-num">{head.text}</span>
                  <Sparkline
                    values={starView.values.map((value) => (value.measured ? value.value : null))}
                    width={56}
                    height={16}
                    step={star.target?.kind === 'scope'}
                    ariaLabel={`${star.label} over ${view.columns.length} columns`}
                  />
                  </span>
              ) : null}
              {star && head?.aggregate ? (
                <span className="vt-c-track-line vt-faint vt-small" title={star.label}>
                  {shortStar(star)} · {head.label}
                </span>
              ) : null}
              {open || depth === 0 ? (
              <span className="vt-c-track-line vt-small">
                {open ? (
                  <>
                    {blocking ? <span className="vt-tone-warn vt-strong">{blocking} blocking</span> : null}
                    <span className="vt-faint">{blocking ? ' · ' : ''}{open} open</span>
                  </>
                ) : (
                  <span className="vt-faint">{latest ? `last ${track.iteration.unit} ${formatDay(latest.date)}` : 'no iterations'}</span>
                )}
              </span>
              ) : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function shortStar(kpi: Kpi): string {
  return kpi.label.split(' · ')[0].toLowerCase()
}

// ------------------------------------------------------------------------------------------------ pane 2

export function KpiPane({
  track,
  view,
  selectedKpi,
  selectedColumn,
  active,
  showDeltas,
  needsOpen,
  onToggleNeeds,
  onSelectKpi,
  roadmap,
}: {
  track: Track
  view: TrackView
  selectedKpi: string
  selectedColumn: string | null
  active: boolean
  showDeltas: boolean
  needsOpen: boolean
  onToggleNeeds: () => void
  onSelectKpi: (kpiId: string) => void
  roadmap: RoadmapSlotProps
}) {
  const blocking = blockingQuestions(track)
  const column = view.columns.find((it) => it.id === selectedColumn) ?? null
  const columnIndex = column ? view.columns.indexOf(column) : -1
  const first = track.iterations[0]
  const last = latestIteration(track)
  const selectedRow = useRef<HTMLTableRowElement>(null)
  useEffect(() => {
    selectedRow.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selectedKpi])

  return (
    <div data-testid="vt-c-kpi-pane">
      <h2 className="vt-h2">{track.title}</h2>
      <p className="vt-c-state">
        <StatusWord status={track.state} detail={track.state.detail} />
      </p>
      <p className="vt-sub vt-small">{track.summary}</p>
      <p className="vt-faint vt-small vt-num" style={{ marginTop: 4 }}>
        {plural(track.iterations.length, track.iteration.unit)} · {formatDay(first?.date)} → {formatDay(last?.date)}
        {view.mode === 'day' ? ` · ${plural(view.columns.length, 'day column')}` : ''}
      </p>

      {track.needs_you.length ? (
        <div className="vt-c-needs">
          <button type="button" className="vt-btn vt-c-disclosure" aria-expanded={needsOpen} data-testid="vt-c-needs-toggle" onClick={onToggleNeeds}>
            <span className="vt-c-caret" aria-hidden="true">{needsOpen ? '▾' : '▸'}</span>
            Needs you
            {blocking.length ? <span className="vt-tone-warn vt-strong"> · {blocking.length} blocking a rung</span> : null}
            <span className="vt-faint"> · {track.needs_you.length} open</span>
          </button>
          {needsOpen ? (
            <ul className="vt-c-questions">
              {track.needs_you.map((question) => (
                <li key={question.id}>
                  <span>{question.q}</span>
                  <span className="vt-faint vt-small">
                    {question.blocks.length ? <span className="vt-tone-warn">blocks {question.blocks.join(', ')}</span> : 'blocks nothing'}
                    {' · '}
                    {question.default ? `default: ${question.default}` : 'no default recorded'}
                    {question.applies ? ` (${question.applies})` : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="vt-faint vt-small vt-c-needs">Needs you · nothing open</p>
      )}

      <table className="vt-table vt-c-kpis" data-testid="vt-c-kpi-table">
        <colgroup>
          <col />
          <col style={{ width: 84 }} />
          {showDeltas ? <col style={{ width: 96 }} /> : null}
          <col style={{ width: 68 }} />
          <col style={{ width: 114 }} />
        </colgroup>
        <thead>
          <tr>
            <th>KPI</th>
            <th className={column ? 'vt-c-at' : undefined}>{column ? `At ${column.label}` : 'Latest'}</th>
            {showDeltas ? (
              <th title={column ? 'Change vs the previous column' : 'Change vs the pinned baseline when the KPI names one, else vs the previous reading'}>
                {column ? 'Δ vs previous' : 'Δ'}
              </th>
            ) : null}
            <th>Trend</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {kpisBySlot(track).map((group) => (
            <SlotRows
              key={group.slot}
              name={group.name}
              kpis={group.kpis}
              track={track}
              view={view}
              columnId={column?.id ?? null}
              columnIndex={columnIndex}
              selectedKpi={selectedKpi}
              active={active}
              showDeltas={showDeltas}
              onSelectKpi={onSelectKpi}
              selectedRow={selectedRow}
            />
          ))}
        </tbody>
      </table>

      <RoadmapSlot {...roadmap} />
    </div>
  )
}

function SlotRows({
  name,
  kpis,
  track,
  view,
  columnId,
  columnIndex,
  selectedKpi,
  active,
  showDeltas,
  onSelectKpi,
  selectedRow,
}: {
  name: string
  kpis: Kpi[]
  track: Track
  view: TrackView
  columnId: string | null
  columnIndex: number
  selectedKpi: string
  active: boolean
  showDeltas: boolean
  onSelectKpi: (kpiId: string) => void
  selectedRow: RefObject<HTMLTableRowElement | null>
}) {
  return (
    <>
      <tr className="vt-group">
        <td colSpan={showDeltas ? 5 : 4}>{name}</td>
      </tr>
      {kpis.map((kpi) => {
        const viewKpi = view.kpi(kpi)
        const never = measuredValues(kpi).length === 0
        const head = headline(track, kpi)
        const at = columnId ? valueAt(viewKpi, columnId) : null
        const delta = columnId ? (at?.measured ? deltaVsPrevious(viewKpi, at) : null) : headlineDelta(kpi, head)
        const isSelected = kpi.id === selectedKpi
        const latestIt = !columnId && !head.aggregate && head.value ? head.value.iteration : null
        const stale = latestIt !== null && latestIt !== track.iterations[track.iterations.length - 1]?.id
        let valueText: string
        let valueSub: string
        if (columnId) {
          valueText = at?.measured ? formatKpiValue(kpi, at) : '—'
          valueSub = at?.measured ? formatN(at).replace(' = ', ' ') : 'not measured'
        } else if (head.aggregate) {
          valueText = head.text
          valueSub = head.label
        } else if (never) {
          valueText = '—'
          valueSub = 'never measured'
        } else {
          valueText = head.text
          valueSub = stale ? `at ${head.label}` : formatN(head.value).replace(' = ', ' ')
        }
        return (
          <tr
            key={kpi.id}
            ref={isSelected ? selectedRow : undefined}
            className={`vt-row-link${isSelected ? ' vt-c-sel' : ''}${isSelected && active ? ' vt-c-active' : ''}`}
            aria-selected={isSelected}
            data-testid="vt-c-kpi-row"
            data-kpi={kpi.id}
            onClick={() => onSelectKpi(kpi.id)}
          >
            <td className="vt-c-kpi-label">{kpi.label}</td>
            <td className="vt-num">
              <span className={valueText === '—' ? 'vt-gap' : 'vt-latest'}>{valueText}</span>
              {valueSub ? <small className="vt-c-sub">{valueSub}</small> : null}
            </td>
            {showDeltas ? (
              <td className="vt-num">
                {delta ? (
                  <>
                    <span className={toneClass(deltaTone(delta))}>{formatDelta(delta.delta, kpi.unit)}</span>
                    <small className={`vt-c-sub ${delta.unconfirmed && delta.delta !== 0 ? 'vt-tone-warn' : ''}`}>
                      {delta.unconfirmed && delta.delta !== 0 ? N1_WORD : `vs ${delta.against}`}
                    </small>
                  </>
                ) : (
                  <span className="vt-gap" title={kpi.baseline ? undefined : 'no baseline pinned and no earlier reading'}>
                    —
                  </span>
                )}
              </td>
            ) : null}
            <td>
              {never ? (
                <span className="vt-c-nodata" title="no reading at any column" aria-label="no readings" />
              ) : (
                <Sparkline
                  values={viewKpi.values.map((value) => (value.measured ? value.value : null))}
                  target={kpi.target?.band ? { band: kpi.target.band } : kpi.target && kpi.target.kind !== 'scope' && kpi.target.kind !== 'reference' ? { value: kpi.target.value ?? kpi.target.gate } : null}
                  selected={columnIndex >= 0 ? columnIndex : null}
                  step={kpi.target?.kind === 'scope'}
                  ariaLabel={`${kpi.label} over ${view.columns.length} columns`}
                />
              )}
            </td>
            <td className="vt-c-status">
              <StatusWord status={kpi.status} className="vt-small" />
            </td>
          </tr>
        )
      })}
    </>
  )
}

// ------------------------------------------------------------------------------------------------ roadmap slot

export interface RoadmapSlotProps {
  track: Track
  doc: unknown | null
  state: RoadmapWidgetState
  open: boolean
  settings: RoadmapSettings
  onToggle: () => void
  onState: (next: RoadmapWidgetState) => void
  onOpenRung: (rungId: string) => void
  onOpenEvidence: (ref: { path: string; line?: number }) => void
}

/** The Roadmap section under the KPI table (VARIANTS.md "Roadmap widget slot"): collapsed = density 'calm',
 * expanded = 'full', in place. WHY under the table and not a tab: a tab would hide the KPI table, and the slot rule
 * says the roadmap "must not crowd the glance". */
function RoadmapSlot({ track, doc, state, open, settings, onToggle, onState, onOpenRung, onOpenEvidence }: RoadmapSlotProps) {
  return (
    <section className="vt-c-roadmap" data-testid="vt-c-roadmap">
      <button type="button" className="vt-btn vt-c-disclosure" aria-expanded={open} data-testid="vt-c-roadmap-toggle" onClick={onToggle}>
        <span className="vt-c-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
        Roadmap
      </button>
      <div className="vt-c-roadmap-body">
        <RoadmapWidget
          track={track.id}
          doc={doc}
          state={state}
          onState={onState}
          onOpenRung={onOpenRung}
          onOpenEvidence={onOpenEvidence}
          density={open ? 'full' : 'calm'}
          settings={settings}
        />
      </div>
    </section>
  )
}

// ------------------------------------------------------------------------------------------------ the glance (L1)

/** Pane 2 before a track is picked: every question that holds a rung, across tracks (the research's "one Needs-you
 * worklist"). A click opens that track with its Needs-you list expanded. */
export function NeedsAcross({ projection, onOpen }: { projection: Projection; onOpen: (trackId: string) => void }) {
  const tracks = projection.tracks.filter((track) => track.needs_you.length > 0)
  const blockingTotal = tracks.reduce((sum, track) => sum + blockingQuestions(track).length, 0)
  const otherTotal = tracks.reduce((sum, track) => sum + track.needs_you.length - blockingQuestions(track).length, 0)
  return (
    <div data-testid="vt-c-needs-across">
      <h2 className="vt-h2">Needs you</h2>
      <p className="vt-sub vt-small">
        {plural(blockingTotal, 'question')} hold a rung{otherTotal ? ` · ${otherTotal} more block nothing` : ''}. Pick one to open its track.
      </p>
      <ul className="vt-c-glance-list">
        {tracks.flatMap((track) =>
          blockingQuestions(track).map((question) => (
            <li key={`${track.id}-${question.id}`}>
              <button type="button" className="vt-btn vt-c-glance-row" data-testid="vt-c-needs-row" onClick={() => onOpen(track.id)}>
                <span>{question.q}</span>
                <span className="vt-faint vt-small">
                  {track.title} · <span className="vt-tone-warn">blocks {question.blocks.join(', ')}</span> ·{' '}
                  {question.default ? `default: ${question.default}` : 'no default recorded'}
                </span>
              </button>
            </li>
          )),
        )}
      </ul>
    </div>
  )
}

/** Pane 3 before a track is picked: each track's newest change marker (what its last iteration did), one click from
 * that iteration's evidence. */
export function LatestChanges({ projection, onOpen }: { projection: Projection; onOpen: (trackId: string, iterationId: string) => void }) {
  return (
    <div data-testid="vt-c-latest-changes">
      <h2 className="vt-h2">Latest change per track</h2>
      <p className="vt-sub vt-small">What each track's newest iteration did. Pick one to open its evidence.</p>
      <ul className="vt-c-glance-list">
        {orderedTracks(projection).map(({ track }) => {
          const last = latestIteration(track)
          if (!last) return null
          return (
            <li key={track.id}>
              <button type="button" className="vt-btn vt-c-glance-row" data-testid="vt-c-change-row" onClick={() => onOpen(track.id, last.id)}>
                <span>
                  <span className="vt-strong">{track.title}</span>
                  <span className="vt-faint"> · {last.label} · {formatDay(last.date)}</span>
                </span>
                <span className="vt-muted vt-small">{last.marker}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
