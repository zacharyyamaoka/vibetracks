// A tiny SVG series: the shape of a KPI over its iterations, the latest point emphasised, an optional target line or
// band. Gaps (null, never measured) break the line instead of dropping to zero (research: "missing data is an
// explicit state"). WHY a hand SVG and no chart library: a 64 × 18 glyph needs no axes, and the plugin ships no deps.
// WHY grey ink and a near-black latest dot, never the accent blue: ordinary data is not an exception, and a blue line on
// every row spent the page's only colour on nothing (audit 2026-10-04 #13). Exceptions are the status word's job.

export interface SparklineProps {
  values: Array<number | null>
  width?: number
  height?: number
  /** A target value (dashed line) or band (shaded) drawn behind the series, on the same scale. */
  target?: { value?: number; band?: [number, number] } | null
  /** Fix the y-domain (e.g. [0, 62] for a burn-up against scope); default: fit the values and target. */
  domain?: [number, number]
  /** Index of a point to ring (a selected iteration); default none. */
  selected?: number | null
  /** Draw the line as steps (a burn-up). */
  step?: boolean
  ariaLabel?: string
  className?: string
}

export function Sparkline({ values, width = 64, height = 18, target, domain, selected = null, step = false, ariaLabel, className }: SparklineProps) {
  const numbers = values.filter((v): v is number => v !== null && Number.isFinite(v))
  const extra: number[] = []
  if (target?.value !== undefined) extra.push(target.value)
  if (target?.band) extra.push(...target.band)
  let [low, high] = domain ?? [Math.min(...numbers, ...extra), Math.max(...numbers, ...extra)]
  if (!Number.isFinite(low) || !Number.isFinite(high)) [low, high] = [0, 1]
  if (low === high) [low, high] = [low - 1, high + 1]
  const pad = 2
  const n = values.length
  const x = (i: number) => (n <= 1 ? width / 2 : pad + (i * (width - 2 * pad)) / (n - 1))
  const y = (v: number) => height - pad - ((v - low) / (high - low)) * (height - 2 * pad)

  // Split into runs of measured points so a gap breaks the line.
  const runs: Array<Array<[number, number]>> = []
  let current: Array<[number, number]> = []
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (current.length) runs.push(current)
      current = []
    } else current.push([x(i), y(v)])
  })
  if (current.length) runs.push(current)
  const path = (run: Array<[number, number]>) =>
    run
      .map(([px, py], i) => {
        if (i === 0) return `M${px.toFixed(1)},${py.toFixed(1)}`
        return step ? `H${px.toFixed(1)}V${py.toFixed(1)}` : `L${px.toFixed(1)},${py.toFixed(1)}`
      })
      .join('')
  let lastIndex = -1
  values.forEach((v, i) => {
    if (v !== null && Number.isFinite(v)) lastIndex = i
  })

  return (
    <svg className={`vt-spark ${className ?? ''}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
      {target?.band ? (
        <rect x={0} width={width} y={y(Math.min(high, target.band[1]))} height={Math.max(1, Math.abs(y(Math.max(low, target.band[0])) - y(Math.min(high, target.band[1]))))} fill="var(--vt-band)" />
      ) : null}
      {target?.value !== undefined ? (
        <line x1={0} x2={width} y1={y(target.value)} y2={y(target.value)} stroke="var(--vt-faint)" strokeWidth={1} strokeDasharray="2 2" />
      ) : null}
      {runs.map((run, i) =>
        run.length === 1 ? null : <path key={i} d={path(run)} fill="none" stroke="var(--vt-ink)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />,
      )}
      {runs.filter((run) => run.length === 1).map((run, i) => (
        <circle key={`solo-${i}`} cx={run[0][0]} cy={run[0][1]} r={1.6} fill="var(--vt-ink)" />
      ))}
      {lastIndex >= 0 ? <circle cx={x(lastIndex)} cy={y(values[lastIndex] as number)} r={2.4} fill="var(--vt-fg)" /> : null}
      {selected !== null && selected >= 0 && selected < n && values[selected] !== null ? (
        <circle cx={x(selected)} cy={y(values[selected] as number)} r={4} fill="none" stroke="var(--vt-fg)" strokeWidth={1} />
      ) : null}
    </svg>
  )
}
