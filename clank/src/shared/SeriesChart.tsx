// One KPI over its iterations on an aligned x-axis: the target line or band, change markers as hairlines, a
// hover/selected cursor, n annotations, never-measured iterations drawn as gaps, and a click per iteration.
//
// The research principles this encodes (BRIEF): shared aligned x-axis (fixed margins, so stacked charts of one track
// line up column for column), change markers through every chart, provenance (each column is a button that hands its
// iteration to onSelectIteration, the way to the evidence), explicit missing data (a gap and a faint tick, never 0),
// uncertainty with the number (n ≤ 1 points are hollow and labelled), target or band on the same scale.
// WHY hand SVG: the plugin ships no chart library and this needs exact control of gaps and markers.
// WHY grey ink with the latest point in near-black, never the accent blue: ordinary data is not an exception (audit
// 2026-10-04 #13); colour stays free for warn/risk/stale.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { Iteration, Kpi, KpiValue } from './model'
import { formatKpiValue, formatN, formatValue, valueAt, valueDomain } from './model'

export interface SeriesChartProps {
  kpi: Kpi
  iterations: Iteration[]
  /** The iteration the cursor sits on (the reader's selection). */
  selected?: string | null
  onSelectIteration?: (iterationId: string) => void
  height?: number
  /** Small-multiple mode: no marker text, no n labels, two y ticks. */
  compact?: boolean
  /** Draw as steps (a burn-up against scope). Default: true for a scope target. */
  step?: boolean
  /** Override the y-domain (to share one scale across several charts). */
  domain?: [number, number]
  /** The line under the chart that reads out the hovered (else selected, else latest) iteration. Default true. */
  readout?: boolean
  /** Fixed left margin in px; keep it equal across stacked charts so their columns align. */
  leftMargin?: number
  className?: string
}

const RIGHT = 14
const TOP = 10
const BOTTOM = 22

export function SeriesChart({
  kpi,
  iterations,
  selected = null,
  onSelectIteration,
  height = 168,
  compact = false,
  step,
  domain,
  readout = true,
  leftMargin = 52,
  className,
}: SeriesChartProps) {
  const wrapper = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(560)
  const [hover, setHover] = useState<string | null>(null)

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const measure = () => setWidth(Math.max(160, Math.floor(element.getBoundingClientRect().width)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const [low, high] = domain ?? valueDomain(kpi)
  const drawStep = step ?? kpi.target?.kind === 'scope'
  const plotWidth = Math.max(10, width - leftMargin - RIGHT)
  const plotHeight = Math.max(10, height - TOP - BOTTOM)
  const n = iterations.length
  const colWidth = n > 0 ? plotWidth / n : plotWidth
  const x = (index: number) => leftMargin + colWidth * (index + 0.5)
  const y = (value: number) => TOP + plotHeight - ((value - low) / (high - low || 1)) * plotHeight

  const points = useMemo(
    () => iterations.map((it, index) => ({ it, index, value: valueAt(kpi, it.id) })),
    [iterations, kpi],
  )
  const measured = points.filter((p) => p.value?.measured && p.value.value !== null)
  const latest = measured[measured.length - 1]

  // Line segments between consecutive measured iterations; a never-measured iteration between them breaks the line.
  const segments: string[] = []
  let run: Array<{ px: number; py: number }> = []
  const flush = () => {
    if (run.length > 1) {
      segments.push(
        run
          .map((p, i) => (i === 0 ? `M${p.px.toFixed(1)},${p.py.toFixed(1)}` : drawStep ? `H${p.px.toFixed(1)}V${p.py.toFixed(1)}` : `L${p.px.toFixed(1)},${p.py.toFixed(1)}`))
          .join(''),
      )
    }
    run = []
  }
  for (const p of points) {
    if (p.value?.measured && p.value.value !== null) run.push({ px: x(p.index), py: y(p.value.value) })
    else flush()
  }
  flush()

  const target = kpi.target
  const goal = target?.value ?? target?.gate
  const ticks = compact ? [low, high] : [low, (low + high) / 2, high]
  const showN = !compact && n <= 8
  const readoutId = hover ?? selected ?? latest?.it.id ?? null
  const readoutIteration = iterations.find((it) => it.id === readoutId) ?? null
  const readoutValue: KpiValue | null = readoutIteration ? valueAt(kpi, readoutIteration.id) : null
  const labelEvery = Math.max(1, Math.ceil((n * 46) / plotWidth))

  return (
    <div ref={wrapper} className={`vt-chart ${className ?? ''}`} data-testid="vt-series-chart" data-kpi={kpi.id}>
      <svg width={width} height={height} role="img" aria-label={`${kpi.label} over ${n} iterations`} onMouseLeave={() => setHover(null)}>
        {/* y ticks */}
        {ticks.map((tick, i) => (
          <g key={`tick-${i}`}>
            <line x1={leftMargin} x2={leftMargin + plotWidth} y1={y(tick)} y2={y(tick)} stroke="var(--vt-line)" strokeWidth={1} />
            <text x={leftMargin - 6} y={y(tick) + 3.5} textAnchor="end">
              {formatValue(tick, kpi.unit)}
            </text>
          </g>
        ))}
        {/* target band / line */}
        {target?.band ? (
          <rect
            x={leftMargin}
            width={plotWidth}
            y={y(Math.min(high, target.band[1]))}
            height={Math.max(1, y(Math.max(low, target.band[0])) - y(Math.min(high, target.band[1])))}
            fill="var(--vt-band)"
          >
            <title>{target.label}</title>
          </rect>
        ) : null}
        {goal !== undefined && goal >= low && goal <= high ? (
          <g>
            <line x1={leftMargin} x2={leftMargin + plotWidth} y1={y(goal)} y2={y(goal)} stroke="var(--vt-grey)" strokeWidth={1} strokeDasharray="4 3" />
            {!compact ? (
              <text x={leftMargin + plotWidth} y={y(goal) - 4} textAnchor="end">
                {target?.label}
              </text>
            ) : null}
          </g>
        ) : null}
        {/* columns: change-marker hairline, hit area, iteration label */}
        {points.map((p) => {
          const isSelected = p.it.id === selected
          const label = p.index % labelEvery === 0 || p.index === n - 1 || isSelected
          return (
            <g
              key={p.it.id}
              className="vt-chart-col"
              role={onSelectIteration ? 'button' : undefined}
              tabIndex={onSelectIteration ? 0 : undefined}
              aria-label={`${p.it.label}: ${formatKpiValue(kpi, p.value)}${p.value?.measured ? '' : ' (not measured)'}`}
              aria-pressed={onSelectIteration ? isSelected : undefined}
              data-iteration={p.it.id}
              onMouseEnter={() => setHover(p.it.id)}
              onFocus={() => setHover(p.it.id)}
              onBlur={() => setHover(null)}
              onClick={onSelectIteration ? () => onSelectIteration(p.it.id) : undefined}
              onKeyDown={
                onSelectIteration
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onSelectIteration(p.it.id)
                      }
                    }
                  : undefined
              }
              style={{ cursor: onSelectIteration ? 'pointer' : 'default' }}
            >
              <rect className="vt-chart-hit" x={x(p.index) - colWidth / 2} y={TOP} width={colWidth} height={plotHeight} fill={isSelected ? 'var(--vt-hover)' : 'transparent'} />
              <line x1={x(p.index)} x2={x(p.index)} y1={TOP} y2={TOP + plotHeight} stroke={isSelected || hover === p.it.id ? 'var(--vt-grey)' : 'var(--vt-line)'} strokeWidth={1}>
                <title>{p.it.marker}</title>
              </line>
              {label ? (
                <text x={x(p.index)} y={height - 6} textAnchor="middle" style={isSelected ? { fill: 'var(--vt-fg)', fontWeight: 600 } : undefined}>
                  {shorten(p.it.label, Math.max(4, Math.floor(colWidth * labelEvery / 6.2)))}
                  <title>{p.it.label}</title>
                </text>
              ) : null}
              {!p.value?.measured ? (
                <line x1={x(p.index) - 3} x2={x(p.index) + 3} y1={TOP + plotHeight - 1} y2={TOP + plotHeight - 1} stroke="var(--vt-faint)" strokeWidth={1.5}>
                  <title>{p.value?.note ?? 'not measured'}</title>
                </line>
              ) : null}
            </g>
          )
        })}
        {/* series */}
        {segments.map((d, i) => (
          <path key={`seg-${i}`} d={d} fill="none" stroke="var(--vt-ink)" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" pointerEvents="none" />
        ))}
        {measured.map((p) => {
          const value = p.value as KpiValue
          const isLatest = p === latest
          const thin = value.n !== null && value.n <= 1
          return (
            <g key={`pt-${p.it.id}`} pointerEvents="none">
              <circle
                cx={x(p.index)}
                cy={y(value.value as number)}
                r={isLatest ? 4 : 3}
                fill={thin ? 'var(--vt-bg)' : isLatest ? 'var(--vt-fg)' : 'var(--vt-ink)'}
                stroke={isLatest ? 'var(--vt-fg)' : 'var(--vt-ink)'}
                strokeWidth={thin ? 1.5 : 0}
              />
              {showN && value.n !== null ? (
                <text x={x(p.index)} y={y(value.value as number) - 8} textAnchor="middle">
                  {`n ${value.n}`}
                </text>
              ) : null}
            </g>
          )
        })}
      </svg>
      {readout ? (
        <div className="vt-chart-readout" data-testid="vt-chart-readout">
          {readoutIteration ? (
            <>
              <span className="vt-strong" style={{ color: 'var(--vt-fg)' }}>
                {readoutIteration.label}
              </span>
              {' · '}
              <span className="vt-num">{readoutValue?.measured ? formatKpiValue(kpi, readoutValue) : 'not measured'}</span>
              {formatN(readoutValue) ? ` · ${formatN(readoutValue)}` : ''}
              {readoutValue?.spread !== null && readoutValue?.spread !== undefined ? ` · spread ${formatValue(readoutValue.spread, kpi.unit)}` : ''}
              {' · '}
              <span className="vt-faint">{readoutIteration.marker}</span>
              {readoutValue?.note ? <span className="vt-faint">{` · ${readoutValue.note}`}</span> : null}
            </>
          ) : (
            <span className="vt-faint">no iterations</span>
          )}
        </div>
      ) : null}
    </div>
  )
}

function shorten(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(1, max - 1))}…`
}
