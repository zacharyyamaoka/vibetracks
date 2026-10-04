// Level 2 of Variant B: the KPI wall. One row per KPI (grouped by the research's slots), every row drawn on the SAME
// aligned x-axis of the track's columns, change-marker hairlines running through every row, the latest column washed,
// and one cursor: hover (or ←/→) a column and every row prints its value there.
//
// WHY one cursor through all rows and not a tooltip per chart (Rerun's time cursor, intervals.icu's shared readout):
// the question at L2 is "what moved together in this wave?", and a per-chart tooltip answers it one chart at a time.
// WHY the hairlines, the wash and the cursor are one overlay and not drawn inside each row's SVG: a line drawn per row
// breaks at every row gap; one absolutely placed line reads as one event crossing every KPI.
// WHY the value column shows the honest headline until the cursor moves (latest-vs-baseline for a loop, the day summary
// for a deployment): the wall must answer "where are we" before it answers "what was it at W2".

import { useEffect, useRef, useState } from 'react'
import type { Kpi, Track } from '../../shared'
import {
  N1_WORD,
  StatusWord,
  deltaTone,
  deltaVsBaseline,
  deltaVsPrevious,
  formatDelta,
  formatKpiValue,
  formatN,
  formatValue,
  kpisBySlot,
  latestValue,
  toneClass,
  type Delta,
  type Tone,
} from '../../shared'
import { shortDay } from '../../shared'
import { cellAt, isRulerChange, rowDomain, shortMarker, unitPlural, type Cell, type Column } from './columns'

export const LABEL_W = 224
export const VALUE_W = 212
export const STATUS_W = 180
const STRIP_H = 40
const PAD = 6

export interface WallProps {
  track: Track
  columns: Column[]
  /** The column the cursor sits on (hover or keyboard); null = no cursor, rows show their headline. */
  cursor: number | null
  /** The column whose evidence the drawer shows. */
  selected: number | null
  selectedKpi: string | null
  onCursor: (index: number | null) => void
  onOpen: (columnIndex: number, kpiId?: string) => void
  showDeltas: boolean
}

export function Wall({ track, columns, cursor, selected, selectedKpi, onCursor, onOpen, showDeltas }: WallProps) {
  const stripRef = useRef<HTMLDivElement>(null)
  const [stripWidth, setStripWidth] = useState(480)
  useEffect(() => {
    const element = stripRef.current
    if (!element) return
    const measure = () => setStripWidth(Math.max(120, Math.floor(element.getBoundingClientRect().width)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const n = columns.length
  const colWidth = n > 0 ? stripWidth / n : stripWidth
  const latest = n - 1
  const groups = kpisBySlot(track)
  const markerChars = Math.floor((colWidth - 8) / 6.4)
  const showMarkers = markerChars >= 14
  const labelChars = Math.floor((colWidth - 4) / 6.6)
  const dense = colWidth < 64 && columns.filter((column) => column.label.length > labelChars).length > n / 2

  const columnAt = (clientX: number): number | null => {
    const box = stripRef.current?.getBoundingClientRect()
    if (!box || n === 0) return null
    const x = clientX - box.left
    if (x < 0 || x >= box.width) return null
    return Math.min(n - 1, Math.max(0, Math.floor(x / colWidth)))
  }

  const valueHeader = cursor !== null ? `At ${columns[cursor]?.label ?? ''}` : track.kind === 'deployment' ? 'Day summary · latest' : 'Latest'

  return (
    <div
      className="vt-b-wall"
      data-testid="vt-b-wall"
      style={{ ['--b-label' as string]: `${LABEL_W}px`, ['--b-value' as string]: `${VALUE_W}px`, ['--b-status' as string]: `${STATUS_W}px` }}
      onMouseMove={(event) => {
        // WHY the cursor stays when the pointer leaves the strip for the value column: the reader moves left to read
        // the values the cursor printed; clearing it there would erase the answer they came for.
        const index = columnAt(event.clientX)
        if (index !== null && index !== cursor) onCursor(index)
      }}
      onMouseLeave={() => onCursor(null)}
    >
      <div className="vt-b-axis vt-b-grid">
        <span className="vt-label vt-b-axis-first">KPI</span>
        <span className="vt-label" data-testid="vt-b-value-header">
          {valueHeader}
        </span>
        <div className="vt-b-axis-strip" ref={stripRef} style={{ height: dense || showMarkers ? 40 : 24 }}>
          {/* WHY date spans on a dense axis (17 CAN 12 sessions in ~500 px): no session name fits a 28 px column, and
              clipped stubs ("07…") read as noise; the day span names the group, the readout names the cursor's session. */}
          {dense
            ? dateSpans(track, columns).map((span) => (
                <span
                  key={span.key}
                  className="vt-b-span"
                  style={{ left: span.start * colWidth, width: span.count * colWidth }}
                  title={span.label}
                >
                  {fitText(span.label, Math.floor((span.count * colWidth - 8) / 6.4))}
                </span>
              ))
            : null}
          {columns.map((column, index) => {
            const isLatest = index === latest
            const isCursor = index === cursor || index === selected
            return (
              <button
                key={column.id}
                type="button"
                className={`vt-btn vt-b-tick${dense ? ' is-dense' : ''}${isLatest ? ' is-latest' : ''}${isCursor ? ' is-cursor' : ''}`}
                style={{ left: index * colWidth, width: colWidth }}
                title={`${column.title}\n${column.marker}\nClick to open its evidence`}
                aria-label={`${column.title}: open its evidence`}
                data-testid="vt-b-tick"
                data-column={column.id}
                onClick={() => onOpen(index)}
                onFocus={() => onCursor(index)}
              >
                {dense ? (
                  <span className="vt-b-tick-mark" />
                ) : (
                  <>
                    <span className="vt-b-tick-label">{fitText(column.label, labelChars)}</span>
                    {showMarkers ? <small>{shortMarker(column.marker, markerChars)}</small> : null}
                  </>
                )}
              </button>
            )
          })}
        </div>
        <span className="vt-label">Status</span>
      </div>

      {/* One overlay through every row: change-marker hairlines, the latest column's wash, the selected column, the cursor. */}
      <div className="vt-b-overlay" aria-hidden="true" style={{ left: LABEL_W + VALUE_W, right: STATUS_W }}>
        <div className="vt-b-wash" style={{ left: latest * colWidth, width: colWidth }} />
        {selected !== null ? <div className="vt-b-selwash" style={{ left: selected * colWidth, width: colWidth }} /> : null}
        {columns.map((column, index) => (
          <div key={column.id} className={`vt-b-hair${isRulerChange(column.marker) ? ' is-ruler' : ''}`} style={{ left: (index + 0.5) * colWidth }} />
        ))}
        {cursor !== null ? <div className="vt-b-cursor" data-testid="vt-b-cursor" style={{ left: (cursor + 0.5) * colWidth }} /> : null}
      </div>

      {groups.map((group) => (
        <div key={group.slot} className="vt-b-groupwrap">
          <div className="vt-b-group">{group.name}</div>
          {group.kpis.map((kpi) => (
            <Row
              key={kpi.id}
              track={track}
              kpi={kpi}
              columns={columns}
              width={stripWidth}
              colWidth={colWidth}
              cursor={cursor}
              selected={selected}
              highlighted={selectedKpi === kpi.id}
              showDeltas={showDeltas}
              onOpen={(index) => onOpen(index, kpi.id)}
              columnAt={columnAt}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

interface DateSpan {
  key: string
  start: number
  count: number
  label: string
}

/** Runs of consecutive columns that share a date: the dense axis's labels ("07-29 · 15 sessions"). */
function dateSpans(track: Track, columns: Column[]): DateSpan[] {
  const spans: DateSpan[] = []
  columns.forEach((column, index) => {
    const key = column.date ?? `undated:${column.id}`
    const last = spans[spans.length - 1]
    if (last && last.key === key) last.count += 1
    else spans.push({ key, start: index, count: 1, label: '' })
  })
  for (const span of spans) {
    const first = columns[span.start]
    span.label = first.date ? `${shortDay(first.date)} · ${span.count} ${unitPlural(track, span.count)}` : `${first.label} · no date`
  }
  return spans
}

function fitText(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(1, max - 1))}…`
}

interface RowProps {
  track: Track
  kpi: Kpi
  columns: Column[]
  width: number
  colWidth: number
  cursor: number | null
  selected: number | null
  highlighted: boolean
  showDeltas: boolean
  onOpen: (columnIndex: number) => void
  columnAt: (clientX: number) => number | null
}

function Row({ track, kpi, columns, width, colWidth, cursor, selected, highlighted, showDeltas, onOpen, columnAt }: RowProps) {
  const cells = columns.map((column) => cellAt(track, kpi, column))
  const reading = readValue(track, kpi, columns, cells, cursor, showDeltas)
  const target = kpi.target
  return (
    <div className={`vt-b-row vt-b-grid${highlighted ? ' is-highlighted' : ''}`} data-testid="vt-b-row" data-kpi={kpi.id}>
      <div className="vt-b-label">
        <span className="vt-b-name">{kpi.label}</span>
        <small title={target ? target.label : kpi.note ?? 'no target set'}>{target ? target.label : 'no target set'}</small>
      </div>
      <div className="vt-b-value" title={[reading.main, reading.sub, reading.flag, reading.title].filter(Boolean).join('\n')} data-testid="vt-b-value">
        <span className={`vt-num${reading.emphasis ? ' vt-strong' : ''}${reading.missing ? ' vt-faint' : ''}`}>{reading.main}</span>
        {reading.sub ? <small className={toneClass(reading.subTone)}>{reading.sub}</small> : null}
        {reading.flag ? <small className="vt-tone-warn">{reading.flag}</small> : null}
      </div>
      <div
        className="vt-b-strip"
        role="button"
        tabIndex={-1}
        aria-label={`${kpi.label}: click a column to open the evidence behind that point`}
        onClick={(event) => {
          const index = columnAt(event.clientX)
          if (index !== null) onOpen(index)
        }}
      >
        <Strip kpi={kpi} track={track} cells={cells} width={width} colWidth={colWidth} cursor={cursor} selected={selected} />
      </div>
      <div className="vt-b-status">
        <StatusWord status={kpi.status} />
      </div>
    </div>
  )
}

interface Reading {
  main: string
  sub: string
  subTone: Tone
  /** The n = 1 rule's words, set apart in the exception colour so the delta itself can stay grey. */
  flag?: string
  title: string | null
  emphasis: boolean
  missing: boolean
}

/** What the value column prints: the headline with no cursor, else the value at the cursor with how it compares. */
function readValue(track: Track, kpi: Kpi, columns: Column[], cells: Cell[], cursor: number | null, showDeltas: boolean): Reading {
  if (cursor === null) {
    const aggregate = kpi.aggregate
    if (track.kind === 'deployment' && aggregate && aggregate.value !== null) {
      return {
        main: formatValue(aggregate.value, kpi.unit),
        sub: `${aggregate.label}${aggregate.n !== null ? ` · n = ${aggregate.n}` : ''}`,
        subTone: 'muted',
        title: kpi.note,
        emphasis: true,
        missing: false,
      }
    }
    const latest = latestValue(kpi)
    if (!latest) {
      return { main: '—', sub: 'never measured', subTone: 'muted', title: kpi.note ?? kpi.values.find((value) => value.note)?.note ?? null, emphasis: false, missing: true }
    }
    const parts: string[] = []
    const lastColumn = columns[columns.length - 1]
    // WHY only on a loop: a loop's few columns make "at T1" short and necessary; a deployment's latest session is
    // visible on its strip, and its long session name would push the delta onto a third line.
    if (track.kind === 'loop' && lastColumn && !lastColumn.iterations.some((it) => it.id === latest.iteration)) {
      parts.push(`at ${track.iterations.find((it) => it.id === latest.iteration)?.label ?? latest.iteration}`)
    }
    const delta = kpi.baseline ? deltaVsBaseline(kpi, latest) : deltaVsPrevious(kpi, latest)
    let tone: Tone = 'muted'
    let flag: string | undefined
    if (showDeltas && delta) {
      const split = splitDelta(kpi, delta)
      parts.push(split.text)
      tone = split.tone
      flag = split.flag
    } else if (latest.n !== null) parts.push(nWords(latest.n))
    const at = track.iterations.find((it) => it.id === latest.iteration)?.label ?? latest.iteration
    return { main: formatKpiValue(kpi, latest), sub: parts.join(' · '), subTone: tone, flag, title: `latest reading at ${at}${latest.note ? ` · ${latest.note}` : ''}`, emphasis: true, missing: false }
  }
  const cell = cells[cursor]
  if (!cell || !cell.measured) {
    return { main: '—', sub: 'not measured', subTone: 'muted', title: cell?.note ?? null, emphasis: false, missing: true }
  }
  const parts: string[] = []
  let tone: Tone = 'muted'
  let flag: string | undefined
  if (cell.rule) parts.push(cell.rule)
  else if (cell.raw && kpi.baseline && cell.raw.iteration === kpi.baseline.iteration) parts.push(`pinned baseline (${kpi.baseline.label})`)
  else if (showDeltas && cell.raw) {
    const delta = kpi.baseline ? deltaVsBaseline(kpi, cell.raw) : deltaVsPrevious(kpi, cell.raw)
    if (delta) {
      const split = splitDelta(kpi, delta)
      parts.push(split.text)
      tone = split.tone
      flag = split.flag
    }
  }
  if (cell.n !== null && (parts.length === 0 || cell.rule)) parts.push(nWords(cell.n))
  if (cell.spread !== null) parts.push(`spread ${formatValue(cell.spread, kpi.unit)}`)
  return {
    main: formatValue(cell.value, kpi.unit, cell.of),
    sub: parts.join(' · '),
    subTone: tone,
    flag,
    title: cell.note,
    emphasis: cursor === columns.length - 1,
    missing: false,
  }
}

/** The kit's delta wording ("+6.25° vs first reading"), with the n = 1 rule's words split off as their own flag.
 * WHY split: describeDelta writes one string, so a whole wall of deltas against a single first reading turned orange;
 * only the exception ("unconfirmed · repeat needed") earns colour, the change itself stays grey unless it is a
 * confirmed move the wrong way (kit deltaTone). */
export function splitDelta(kpi: Kpi, delta: Delta): { text: string; tone: Tone; flag: string | undefined } {
  const unconfirmed = delta.unconfirmed && delta.delta !== 0
  return {
    text: `${formatDelta(delta.delta, kpi.unit)} vs ${delta.against}`,
    tone: unconfirmed ? 'muted' : deltaTone(delta),
    flag: unconfirmed ? N1_WORD : undefined,
  }
}

/** "n = 15", or the n = 1 rule's words for a single reading. */
export function nWords(n: number): string {
  return n <= 1 ? `n = ${n} · single reading` : `n = ${n}`
}

interface StripProps {
  kpi: Kpi
  track: Track
  cells: Cell[]
  width: number
  colWidth: number
  cursor: number | null
  selected: number | null
}

/** One row's series on the shared x-axis: target band or line, the series (steps for a burn-up), hollow points for
 * n ≤ 1, a faint dash where nothing was measured, and a ring where the cursor crosses the row. */
function Strip({ kpi, track, cells, width, colWidth, cursor, selected }: StripProps) {
  const [low, high] = rowDomain(kpi, cells)
  const x = (index: number) => (index + 0.5) * colWidth
  const y = (value: number) => PAD + (1 - (value - low) / (high - low || 1)) * (STRIP_H - 2 * PAD)
  const step = kpi.target?.kind === 'scope'
  const target = kpi.target
  const goal = target?.value ?? target?.gate
  const measured = cells.map((cell, index) => ({ cell, index })).filter((point) => point.cell.measured && point.cell.value !== null)
  const lastMeasured = measured[measured.length - 1]
  const never = measured.length === 0

  const segments: string[] = []
  let run: Array<[number, number]> = []
  const flush = () => {
    if (run.length > 1) segments.push(run.map(([px, py], i) => (i === 0 ? `M${px.toFixed(1)},${py.toFixed(1)}` : step ? `H${px.toFixed(1)}V${py.toFixed(1)}` : `L${px.toFixed(1)},${py.toFixed(1)}`)).join(''))
    run = []
  }
  cells.forEach((cell, index) => {
    if (cell.measured && cell.value !== null) run.push([x(index), y(cell.value)])
    else flush()
  })
  flush()

  const aggregate = kpi.aggregate
  return (
    <svg width={width} height={STRIP_H} role="img" aria-label={`${kpi.label} over ${cells.length} ${unitPlural(track, cells.length)}`}>
      {target?.band ? (
        <rect x={0} width={width} y={y(Math.min(high, target.band[1]))} height={Math.max(1, y(Math.max(low, target.band[0])) - y(Math.min(high, target.band[1])))} fill="var(--vt-band)">
          <title>{target.label}</title>
        </rect>
      ) : null}
      {!never && goal !== undefined && goal >= low && goal <= high ? (
        <line x1={0} x2={width} y1={y(goal)} y2={y(goal)} stroke="var(--vt-faint)" strokeWidth={1} strokeDasharray="3 3">
          <title>{target?.label}</title>
        </line>
      ) : null}
      {never ? (
        <text x={8} y={STRIP_H / 2 + 4} className="vt-b-never">
          {`not measured in any ${track.iteration.unit}${aggregate && aggregate.value !== null ? ` · ${aggregate.label}: ${formatValue(aggregate.value, kpi.unit)}` : ''}`}
        </text>
      ) : null}
      {!never
        ? cells.map((cell, index) =>
            cell.measured ? null : (
              <line key={`gap-${index}`} x1={x(index) - 3} x2={x(index) + 3} y1={STRIP_H / 2} y2={STRIP_H / 2} stroke="var(--vt-faint)" strokeWidth={1.5}>
                <title>{cell.note ?? 'not measured'}</title>
              </line>
            ),
          )
        : null}
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="var(--vt-accent)" strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {measured.map(({ cell, index }) => {
        const thin = cell.n !== null && cell.n <= 1
        const big = lastMeasured?.index === index
        return (
          <circle
            key={`pt-${index}`}
            cx={x(index)}
            cy={y(cell.value as number)}
            r={big ? 3.4 : 2.6}
            fill={thin ? 'var(--vt-bg)' : 'var(--vt-accent)'}
            stroke="var(--vt-accent)"
            strokeWidth={thin ? 1.4 : 0}
          >
            <title>{thin ? `n = ${cell.n}: a change resting on it is ${N1_WORD}` : formatN(cell.raw) || ''}</title>
          </circle>
        )
      })}
      {[cursor, selected].map((index, i) => {
        if (index === null || i === 1 && index === cursor) return null
        const cell = cells[index]
        if (!cell?.measured || cell.value === null) return null
        return <circle key={`ring-${i}`} cx={x(index)} cy={y(cell.value)} r={5.5} fill="none" stroke="var(--vt-fg)" strokeWidth={1} opacity={i === 0 ? 0.75 : 0.45} />
      })}
    </svg>
  )
}
