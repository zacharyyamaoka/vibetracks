// L2's centrepiece: the KPI × iteration scorecard matrix (research pattern "entity × period scorecard": Antioch release
// regression suite, SRE compliance report, PyTorch HUD).
//   rows    = KPIs grouped by slot, north star first (one template, KPIs bound as data: every track renders here);
//   columns = the track's iterations (or days, from the settings page), the LATEST emphasised (bold + a faint wash);
//   header  = each column's change marker on a grey second line, a ruler change marked on its own;
//   cell    = the value, n under it when it is a sample, "—" grey when not measured, colour only when a gate or limit
//             is missed; every cell is the provenance click (opens that iteration's evidence for that KPI);
//   tail    = trend sparkline on the same columns · target or band · status word (+ delta vs the pinned baseline).
// WHY a horizontal scroll with a sticky KPI column, scrolled to the latest column on open: CAN 12 has 17 sessions;
// squeezing them would clip every label, and the latest column is the one the reader opens the page for.

import { useEffect, useMemo, useRef } from 'react'
import type { Kpi, Track } from '../../shared'
import {
  N1_WORD,
  SLOT_NAMES,
  Sparkline,
  StatusWord,
  deltaVsBaseline,
  describeDelta,
  formatTargetLabel,
  formatValue,
  kpisBySlot,
  measuredValues,
  northStar,
} from '../../shared'
import { buildColumns, cellFor, isRulerChange, missesTarget, trendDomain, unitWord, type Cell, type Column } from './columns'
import { ClampText } from './clamp'

export interface ScorecardProps {
  track: Track
  xAxis: 'iteration' | 'day'
  showDeltas: boolean
  /** A KPI to ring (the reader came back from its evidence). */
  selectedKpi?: string | null
  onOpenColumn: (column: Column) => void
  onOpenCell: (kpi: Kpi, column: Column) => void
}

const WIDE = 108
const NARROW = 92
/** Set per scorecard by the fit in Scorecard's effect; WIDE until it runs. */
const COLUMN_WIDTH = `var(--vt-a-colw, ${WIDE}px)`

export function Scorecard({ track, xAxis, showDeltas, selectedKpi, onOpenColumn, onOpenCell }: ScorecardProps) {
  const columns = useMemo(() => buildColumns(track, xAxis), [track, xAxis])
  const groups = kpisBySlot(track)
  const star = northStar(track)
  const scroller = useRef<HTMLDivElement>(null)
  const endSpacer = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const latestIndex = columns.length - 1
  // WHY the column width is fitted, between WIDE and NARROW: kinsim's 4 waves get room for their change markers when the
  // page is wide, every column shows without a scroll when narrowing them to at least NARROW fits (kinsim at 1440 px
  // overflowed by 24 px, which hid its first column), and CAN 12's 17 sessions stay compact and scroll.
  const fitKey = useRef('')

  // Open scrolled to the latest column, and stay pinned there while the table settles (fonts, CSS, HMR) until the
  // reader scrolls away themselves.
  // WHY snap plus an end spacer: the sticky KPI column covers whatever scrolls under it, so a free scroll left the
  // leftmost visible header half hidden (Detection's 8 columns, integration check 2026-10-04). Snapping every header's
  // start to the sticky column's edge keeps each visible header whole; the spacer makes the far end of the scroll land
  // on a column edge too, or the last position (the one the page opens at) would still cut a header.
  useEffect(() => {
    const element = scroller.current
    const spacer = endSpacer.current
    if (!element || !spacer) return
    pinned.current = true
    const setColumnWidth = (width: number) => element.style.setProperty('--vt-a-colw', `${width}px`)
    const columnWidth = () => Number.parseFloat(element.style.getPropertyValue('--vt-a-colw')) || WIDE
    const align = () => {
      const table = element.querySelector('table')
      const heads = Array.from(element.querySelectorAll<HTMLElement>('thead th:not(.vt-a-sticky)'))
      const columnHeads = Array.from(element.querySelectorAll<HTMLElement>('thead th.vt-a-colhead'))
      if (!table || heads.length === 0) return
      // Fit: on a new width or column count start from WIDE, then narrow just enough to fit, never below NARROW. Each
      // read below forces a synchronous layout, so the whole fit settles inside this one call.
      const key = `${element.clientWidth}:${columnHeads.length}`
      if (key !== fitKey.current) {
        fitKey.current = key
        setColumnWidth(WIDE)
      }
      if (columnHeads.length && table.getBoundingClientRect().width - element.clientWidth > 0.5) {
        const columnsTotal = columnHeads.reduce((sum, th) => sum + th.getBoundingClientRect().width, 0)
        const rest = table.getBoundingClientRect().width - columnsTotal
        const fit = Math.max(NARROW, Math.min(WIDE, Math.floor((element.clientWidth - rest) / columnHeads.length)))
        if (fit < columnWidth()) setColumnWidth(fit)
      }
      const tableLeft = table.getBoundingClientRect().left
      const stops = heads.map((th) => th.getBoundingClientRect().left - tableLeft)
      const stickyWidth = stops[0]
      element.style.scrollPaddingLeft = `${stickyWidth}px`
      element.style.setProperty('--vt-a-stickyw', `${stickyWidth}px`)
      const overflow = table.getBoundingClientRect().width - element.clientWidth
      let pad = 0
      if (overflow > 0.5) {
        const stop = stops.map((left) => left - stickyWidth).find((left) => left >= overflow - 0.5)
        pad = stop === undefined ? 0 : Math.max(0, Math.ceil(stop - overflow))
      }
      if (Math.abs((Number.parseFloat(spacer.style.width) || 0) - pad) > 0.5) spacer.style.width = `${pad}px`
      if (pinned.current) element.scrollLeft = element.scrollWidth
      markMore(element)
    }
    align()
    const table = element.querySelector('table')
    // WHY a frame later: align resizes the table it observes; doing that inside the observer's own callback is what
    // raises "ResizeObserver loop completed with undelivered notifications".
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(align)
    })
    if (table) observer.observe(table)
    observer.observe(element)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [track.id, xAxis])

  const tailColumns = 3
  return (
    <div
      className="vt-a-scroller"
      ref={scroller}
      data-testid="vt-a-scorecard"
      data-columns={columns.length}
      onScroll={(event) => {
        const element = event.currentTarget
        pinned.current = element.scrollLeft + element.clientWidth >= element.scrollWidth - 4
        markMore(element)
      }}
    >
      <table className="vt-table vt-a-score" aria-label={`${track.title}: KPIs by ${xAxis === 'day' ? 'day' : track.iteration.unit}`}>
        <thead>
          <tr>
            <th className="vt-a-sticky vt-a-kpicol">KPI</th>
            {columns.map((column, index) => (
              // WHY a fixed width (not only a min): a header's text is cut to fit its box, so the box must not size
              // itself from that text, or the cut and the column width chase each other.
              <th key={column.key} className={`vt-a-colhead${index === latestIndex ? ' vt-a-latest' : ''}`} style={{ width: COLUMN_WIDTH, minWidth: COLUMN_WIDTH }}>
                <button
                  type="button"
                  className="vt-btn vt-a-colbtn"
                  onClick={() => onOpenColumn(column)}
                  title={`${column.label} · ${column.marker}\nOpen what changed and its evidence`}
                  aria-label={`${column.label}${index === latestIndex ? ' (latest)' : ''} · ${column.sub} · ${column.marker} · open what changed`}
                  data-testid="vt-a-colhead"
                  data-column={column.key}
                >
                  <ClampText
                    className="vt-a-collabel"
                    text={column.label}
                    lines={2}
                    after={index === latestIndex ? { text: ' latest', className: 'vt-a-latesttag' } : null}
                  />
                  <span className="vt-a-colsub">{column.sub}</span>
                  <ClampText
                    className="vt-a-colmarker"
                    text={column.marker}
                    lines={3}
                    title={column.marker}
                    lead={isRulerChange(column.marker) ? { text: '◆ ruler · ', className: 'vt-a-ruler', title: 'the measuring ruler changed here' } : null}
                  />
                </button>
              </th>
            ))}
            <th className="vt-a-trendcol">Trend</th>
            <th className="vt-a-targetcol">Target</th>
            <th className="vt-a-statuscol">Status</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <GroupRows
              key={group.slot}
              name={group.slot === 'S1' ? `${SLOT_NAMES.S1}` : group.name}
              kpis={group.kpis}
              track={track}
              columns={columns}
              latestIndex={latestIndex}
              star={star?.id ?? null}
              showDeltas={showDeltas}
              selectedKpi={selectedKpi ?? null}
              onOpenCell={onOpenCell}
              span={columns.length + tailColumns}
            />
          ))}
        </tbody>
      </table>
      <div className="vt-a-scroll-end" ref={endSpacer} aria-hidden="true" />
    </div>
  )
}

/** The right edge always cuts some column while there is more to scroll to; fading that edge says "more this way"
 * instead of showing a half header as if it were whole. */
function markMore(element: HTMLElement): void {
  element.classList.toggle('vt-a-more-right', element.scrollLeft + element.clientWidth < element.scrollWidth - 1)
}

function GroupRows({ name, kpis, track, columns, latestIndex, star, showDeltas, selectedKpi, onOpenCell, span }: {
  name: string
  kpis: Kpi[]
  track: Track
  columns: Column[]
  latestIndex: number
  star: string | null
  showDeltas: boolean
  selectedKpi: string | null
  onOpenCell: (kpi: Kpi, column: Column) => void
  span: number
}) {
  return (
    <>
      <tr className="vt-group vt-a-grouprow">
        <td className="vt-a-sticky">{name}</td>
        <td colSpan={span} />
      </tr>
      {kpis.map((kpi) => (
        <KpiRow
          key={kpi.id}
          kpi={kpi}
          track={track}
          columns={columns}
          latestIndex={latestIndex}
          isStar={kpi.id === star}
          showDeltas={showDeltas}
          selected={kpi.id === selectedKpi}
          onOpenCell={onOpenCell}
        />
      ))}
    </>
  )
}

function KpiRow({ kpi, track, columns, latestIndex, isStar, showDeltas, selected, onOpenCell }: {
  kpi: Kpi
  track: Track
  columns: Column[]
  latestIndex: number
  isStar: boolean
  showDeltas: boolean
  selected: boolean
  onOpenCell: (kpi: Kpi, column: Column) => void
}) {
  const cells = columns.map((column) => cellFor(track, kpi, column))
  const never = measuredValues(kpi).length === 0
  // WHY only against the pinned baseline here: a row's delta must name what it is measured against (research: "a
  // directional delta against a named baseline"); wave-to-wave changes live on the iteration page.
  const delta = deltaVsBaseline(kpi)
  const deltaText = showDeltas ? describeDelta(kpi, delta) : ''
  const aggregate = kpi.aggregate && kpi.aggregate.value !== null ? kpi.aggregate : null
  return (
    <tr className={`vt-a-kpirow${selected ? ' vt-a-selected' : ''}${isStar ? ' vt-a-star' : ''}`} data-kpi={kpi.id} data-testid="vt-a-kpi-row">
      <td className="vt-a-sticky vt-a-kpicell" title={kpi.note ?? undefined}>
        <span className="vt-a-kpilabel">{kpi.label}</span>
        <small className="vt-a-kpimeta">
          {aggregate ? `${aggregate.label} ${formatValue(aggregate.value, kpi.unit)}${aggregate.n !== null ? ` · n ${aggregate.n}` : ''}` : kpi.unit}
        </small>
      </td>
      {never ? (
        <td colSpan={columns.length} className="vt-a-never" data-testid="vt-a-never">
          {/* WHY sticky: this one sentence spans every column; scrolled, it slid under the KPI column and read as a cut
              string ("nvalid · NaN loss…"). Pinned beside the KPI column, it stays whole at every scroll position. */}
          <span className="vt-faint vt-a-never-text">
            Not measured in any {unitWord(track, 1)}
            {kpi.values.find((v) => v.note)?.note ? ` · ${kpi.values.find((v) => v.note)?.note}` : ''}
          </span>
        </td>
      ) : (
        cells.map((cell, index) => (
          <td key={columns[index].key} className={`vt-a-cell${index === latestIndex ? ' vt-a-latest' : ''}`}>
            <CellButton kpi={kpi} cell={cell} column={columns[index]} onOpen={() => onOpenCell(kpi, columns[index])} />
          </td>
        ))
      )}
      <td className="vt-a-trend">
        {never ? (
          <span className="vt-faint">—</span>
        ) : (
          <Sparkline
            values={cells.map((cell) => (cell.measured ? cell.value : null))}
            step={kpi.target?.kind === 'scope'}
            domain={trendDomain(kpi)}
            target={kpi.target?.band ? { band: kpi.target.band } : kpi.target?.kind === 'gate' || kpi.target?.kind === 'limit' ? { value: kpi.target.value ?? kpi.target.gate } : null}
            width={72}
            ariaLabel={`${kpi.label} trend`}
          />
        )}
      </td>
      <td className={`vt-a-target vt-small ${kpi.target ? 'vt-muted' : 'vt-faint'}`}>{formatTargetLabel(kpi)}</td>
      <td className="vt-a-status">
        <StatusWord status={kpi.status} />
        {deltaText ? <small className="vt-a-delta">{deltaText}</small> : null}
      </td>
    </tr>
  )
}

function CellButton({ kpi, cell, column, onOpen }: { kpi: Kpi; cell: Cell; column: Column; onOpen: () => void }) {
  const thin = cell.n !== null && cell.n <= 1
  const miss = cell.measured && missesTarget(kpi, cell.value)
  const text = cell.measured ? formatValue(cell.value, kpi.unit, cell.of) : '—'
  const title = [
    `${kpi.label} · ${column.label}: ${cell.measured ? text : 'not measured'}`,
    cell.how,
    cell.n !== null ? `n = ${cell.n}${thin ? ` · ${N1_WORD}` : ''}` : null,
    cell.spread !== null ? `spread ${formatValue(cell.spread, kpi.unit)}` : null,
    cell.note,
    miss ? `misses ${kpi.target?.label}` : null,
    cell.evidence.length ? `${cell.evidence.length} evidence item${cell.evidence.length === 1 ? '' : 's'} · click to open` : 'click to open this iteration',
  ]
    .filter(Boolean)
    .join('\n')
  // WHY an aria-label naming the KPI, the column and the value: the visible text is only "0.83 · n 4", which a screen
  // reader or a probe hears as a bare number with no row or column. WHY role and tabIndex spelled out on a native
  // <button> (whose Enter/Space activation is the browser's own): `.vt-btn` unsets every style, and the scorecard's
  // keyboard contract should be legible in the markup rather than depend on knowing that `all: unset` keeps focus.
  const ariaLabel = `${kpi.label} · ${column.label}: ${cell.measured ? text : 'not measured'}${cell.n !== null && cell.of === null ? ` (n ${cell.n})` : ''} · open evidence`
  return (
    <button
      type="button"
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
      className={`vt-btn vt-a-cellbtn${cell.measured ? '' : ' vt-gap'}${miss ? ' vt-tone-warn' : ''}`}
      onClick={onOpen}
      title={title}
      data-testid="vt-a-cell"
      data-measured={cell.measured}
    >
      <span className="vt-a-val vt-num">{text}</span>
      {cell.measured && (cell.how || (cell.n !== null && cell.of === null)) ? (
        <span className="vt-a-n">{[cell.how, cell.n !== null && cell.of === null ? `n ${cell.n}` : null].filter(Boolean).join(' · ')}</span>
      ) : null}
    </button>
  )
}
