// L3 · the Iteration page: what changed (the change marker and its provenance), each KPI's value and its change vs the
// previous iteration (one quiet list), then the evidence grouped by kind. Opened from a scorecard column (the whole
// iteration) or a cell (that KPI highlighted and its evidence first: "every point is a change with provenance, and
// clicking it reaches the evidence").

import { useEffect, useRef } from 'react'
import type { EvidenceItem, Iteration, Kpi, Route, Track } from '../../shared'
import {
  Breadcrumb,
  EvidenceList,
  N1_WORD,
  deltaTone,
  deltaVsPrevious,
  describeDelta,
  evidenceAt,
  evidenceForValue,
  formatDay,
  formatKpiValue,
  formatN,
  formatTargetLabel,
  formatValue,
  iterationById,
  previousValue,
  kpisBySlot,
  targetState,
  toneClass,
  trackById,
  valueAt,
  type Projection,
} from '../../shared'
import { isRulerChange, unitWord } from './columns'
import type { Nav } from './nav'

const KIND_ORDER: Array<{ kind: string; label: string }> = [
  { kind: 'report', label: 'Reports' },
  { kind: 'run', label: 'Runs' },
  { kind: 'video', label: 'Videos' },
  { kind: 'lane', label: 'Lanes' },
  { kind: 'audit', label: 'Audits' },
  { kind: 'gate', label: 'Gates' },
  { kind: 'note', label: 'Notes' },
]

export function IterationPage({ projection, track, iteration, title, nav, mediaUrl, showDeltas }: {
  projection: Projection
  track: Track
  iteration: Iteration
  title: string
  nav: Nav
  mediaUrl: (id: string) => string
  showDeltas: boolean
}) {
  const route = nav.route
  const index = track.iterations.findIndex((it) => it.id === iteration.id)
  const previous = track.iterations[index - 1] ?? null
  const next = track.iterations[index + 1] ?? null
  const parent = track.parent ? trackById(projection, track.parent) : null
  const focusKpi = track.kpis.find((kpi) => kpi.id === route.kpi) ?? null
  const all = evidenceAt(track, iteration.id)
  const groups = kpisBySlot(track)
  const measured = groups.flatMap((g) => g.kpis).filter((kpi) => valueAt(kpi, iteration.id)?.measured)
  const unmeasured = groups.flatMap((g) => g.kpis).filter((kpi) => !valueAt(kpi, iteration.id)?.measured)
  const here = (patch: Route) => nav.go({ track: track.id, rm: route.rm, rmopen: route.rmopen, iteration: iteration.id, kpi: route.kpi, media: route.media, ...patch }, 'replace')
  const sideways = (target: Iteration) => nav.go({ track: track.id, rm: route.rm, rmopen: route.rmopen, iteration: target.id, kpi: route.kpi }, 'replace')
  const openItem = (item: EvidenceItem) => nav.item(track.id, item.id, { kpi: route.kpi })
  const table = useRef<HTMLTableElement>(null)

  // "A cell opens L3 scrolled to that KPI" (VARIANTS.md): bring the focused row, and the evidence opened under it, to
  // the top. WHY a frame later: the page-level scroll-to-top runs in the parent's effect, after this one.
  useEffect(() => {
    if (!focusKpi) return
    const frame = requestAnimationFrame(() => {
      table.current?.querySelector(`[data-kpi="${focusKpi.id}"]`)?.scrollIntoView({ block: 'start' })
    })
    return () => cancelAnimationFrame(frame)
  }, [focusKpi?.id, iteration.id])

  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-l3" data-iteration={iteration.id}>
      <Breadcrumb
        items={[
          { label: title, onClick: nav.tracks },
          ...(parent ? [{ label: parent.title, onClick: () => nav.track(parent.id) }] : []),
          { label: track.title, onClick: () => nav.track(track.id, { kpi: route.kpi }) },
          { label: iteration.label },
        ]}
      />
      <div className="vt-a-titlerow">
        <h1 className="vt-h1">{iteration.label}</h1>
        <nav className="vt-a-stepper vt-small" aria-label={`Other ${unitWord(track, 2)}`}>
          {previous ? (
            <button type="button" className="vt-btn vt-a-link" onClick={() => sideways(previous)} data-testid="vt-a-prev" title={previous.marker}>
              ‹ {previous.label}
            </button>
          ) : (
            <span className="vt-faint">first {unitWord(track, 1)}</span>
          )}
          <span className="vt-faint">
            {index + 1} of {track.iterations.length}
          </span>
          {next ? (
            <button type="button" className="vt-btn vt-a-link" onClick={() => sideways(next)} data-testid="vt-a-next" title={next.marker}>
              {next.label} ›
            </button>
          ) : (
            <span className="vt-faint">latest</span>
          )}
        </nav>
      </div>
      <p className="vt-sub">
        {iteration.date ? formatDay(iteration.date) : 'undated: no event dates this ' + unitWord(track, 1)} · {track.title}
      </p>

      <section className="vt-a-section">
        <h2 className="vt-h3">What changed</h2>
        <p className="vt-a-marker" data-testid="vt-a-marker">
          {isRulerChange(iteration.marker) ? <span className="vt-a-ruler">◆ ruler changed · </span> : null}
          {iteration.marker}
        </p>
        <p className="vt-a-prov vt-small vt-faint" title={iteration.provenance.snapshot}>
          from {iteration.provenance.source ?? iteration.provenance.snapshot} · {iteration.provenance.pointer}
          {iteration.provenance.derived ? ` · ${iteration.provenance.derived}` : ''}
        </p>
      </section>

      <section className="vt-a-section">
        <h2 className="vt-h3">
          KPIs at {iteration.label}{' '}
          <span className="vt-a-h-note">
            {previous ? `change vs the previous reading` : `the first ${unitWord(track, 1)}: nothing to compare with`} · a row opens its evidence
          </span>
        </h2>
        <div className="vt-a-tablescroll">
          <table className="vt-table vt-a-deltas" data-testid="vt-a-deltas" ref={table}>
            <colgroup>
              <col style={{ width: '30%' }} />
              <col style={{ width: '23%' }} />
              <col style={{ width: '19%' }} />
              <col style={{ width: '20%' }} />
              <col style={{ width: '8%' }} />
            </colgroup>
            <thead>
              <tr>
                <th>KPI</th>
                <th>Value</th>
                <th>{showDeltas ? 'Change' : ''}</th>
                <th>Against target</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {measured.map((kpi) => (
                <DeltaRow
                  key={kpi.id}
                  kpi={kpi}
                  track={track}
                  iteration={iteration}
                  showDeltas={showDeltas}
                  focused={kpi.id === focusKpi?.id}
                  onFocus={() => here({ kpi: kpi.id === focusKpi?.id ? undefined : kpi.id, media: undefined })}
                  mediaUrl={mediaUrl}
                  openMedia={route.media ?? null}
                  onOpenMedia={(mediaId) => here({ media: mediaId ?? undefined })}
                  onSelectItem={openItem}
                />
              ))}
            </tbody>
          </table>
        </div>
        {unmeasured.length ? (
          <p className="vt-a-unmeasured vt-small" data-testid="vt-a-unmeasured">
            <span className="vt-faint">Not measured at {iteration.label}: </span>
            {unmeasured.map((kpi, i) => (
              <span key={kpi.id} title={valueAt(kpi, iteration.id)?.note ?? 'not measured'} className={kpi.id === focusKpi?.id ? 'vt-strong' : 'vt-muted'}>
                {i > 0 ? ' · ' : ''}
                {kpi.label}
                <span className="vt-faint">{valueAt(kpi, iteration.id)?.note ? ` (${valueAt(kpi, iteration.id)?.note})` : ''}</span>
              </span>
            ))}
          </p>
        ) : null}
      </section>

      <section className="vt-a-section" data-testid="vt-a-evidence">
        <h2 className="vt-h3">
          All evidence <span className="vt-a-h-note">{all.length} item{all.length === 1 ? '' : 's'} at {iteration.label}</span>
        </h2>
        {all.length === 0 ? (
          <p className="vt-faint" data-testid="vt-a-no-evidence">No evidence recorded for {iteration.label}.</p>
        ) : (
          <EvidenceGroups
            items={all}
            mediaUrl={mediaUrl}
            openMedia={focusKpi ? null : route.media ?? null}
            onOpenMedia={(mediaId) => here({ kpi: undefined, media: mediaId ?? undefined })}
            onSelectItem={openItem}
          />
        )}
      </section>
    </div>
  )
}

function DeltaRow({ kpi, track, iteration, showDeltas, focused, onFocus, mediaUrl, openMedia, onOpenMedia, onSelectItem }: {
  kpi: Kpi
  track: Track
  iteration: Iteration
  showDeltas: boolean
  focused: boolean
  onFocus: () => void
  mediaUrl: (id: string) => string
  openMedia: string | null
  onOpenMedia: (mediaId: string | null) => void
  onSelectItem: (item: EvidenceItem) => void
}) {
  const value = valueAt(kpi, iteration.id)
  const raw = deltaVsPrevious(kpi, value)
  // Name the reading it is compared with ("vs W2"), not the kit's generic "previous".
  const before = previousValue(kpi, iteration.id)
  const delta = raw && before ? { ...raw, against: iterationById(track, before.iteration)?.label ?? raw.against } : raw
  const state = targetState(kpi, value)
  const items = evidenceForValue(track, kpi, iteration.id)
  const descriptive = kpi.target?.kind === 'descriptive'
  const stateText = !kpi.target ? 'no target set' : state ? `${descriptive ? 'describes · ' : ''}${state} · ${formatTargetLabel(kpi)}` : formatTargetLabel(kpi)
  const stateTone = state === 'not met' && !descriptive ? 'warn' : 'muted'
  return (
    <>
      <tr className={`vt-row-link${focused ? ' vt-a-selected' : ''}`} onClick={onFocus} data-kpi={kpi.id} data-testid="vt-a-delta-row" aria-expanded={focused}>
        <td>
          <button type="button" className="vt-btn vt-a-kpilabel" onClick={(event) => { event.stopPropagation(); onFocus() }} title={focused ? 'Close its evidence' : 'Open its evidence'}>
            {kpi.label}
          </button>
        </td>
        <td className="vt-num">
          <span className="vt-strong">{formatKpiValue(kpi, value)}</span>
          {value?.n !== null && value?.n !== undefined && value.of === null ? (
            <small className="vt-a-under">
              {formatN(value)}
              {value.n <= 1 ? ` · ${N1_WORD}` : ''}
              {value.spread !== null ? ` · spread ${formatValue(value.spread, kpi.unit)}` : ''}
            </small>
          ) : null}
        </td>
        <td className={`vt-small ${toneClass(deltaTone(delta))}`}>{showDeltas ? (delta ? describeDelta(kpi, delta) : <span className="vt-faint">no earlier reading</span>) : null}</td>
        <td className={`vt-small ${toneClass(stateTone)}`}>{stateText}</td>
        <td className="vt-small vt-faint vt-num vt-a-evcount">
          {items.length ? `${items.length}` : '—'} <span className="vt-a-caret" aria-hidden="true">{focused ? '⌄' : '›'}</span>
        </td>
      </tr>
      {focused ? (
        <tr className="vt-a-inline" data-testid="vt-a-inline-evidence">
          <td colSpan={5}>
            {items.length ? (
              <EvidenceGroups items={items} mediaUrl={mediaUrl} openMedia={openMedia} onOpenMedia={onOpenMedia} onSelectItem={onSelectItem} />
            ) : (
              <p className="vt-faint vt-small">
                No evidence item is linked to {kpi.label} at {iteration.label}
                {value?.note ? `: ${value.note}` : ''}.
              </p>
            )}
          </td>
        </tr>
      ) : null}
    </>
  )
}

/** The evidence list split by kind (reports first, then runs, lanes, audits, gates, notes), each a shared EvidenceList.
 * WHY grouped: W3 alone has 33 items; a flat list of mixed kinds reads as clutter, a heading per kind reads as a page. */
export function EvidenceGroups({ items, mediaUrl, openMedia, onOpenMedia, onSelectItem }: {
  items: EvidenceItem[]
  mediaUrl: (id: string) => string
  openMedia: string | null
  onOpenMedia: (mediaId: string | null) => void
  onSelectItem: (item: EvidenceItem) => void
}) {
  const known = new Set(KIND_ORDER.map((entry) => entry.kind))
  const groups = [
    ...KIND_ORDER.map((entry) => ({ label: entry.label, items: items.filter((item) => item.kind === entry.kind) })),
    { label: 'Other', items: items.filter((item) => !known.has(item.kind)) },
  ].filter((group) => group.items.length > 0)
  return (
    <div className="vt-a-evgroups">
      {groups.map((group) => (
        <div key={group.label} className="vt-a-evgroup">
          <p className="vt-label">
            {group.label} · {group.items.length}
          </p>
          <EvidenceList items={group.items} mediaUrl={mediaUrl} openMedia={openMedia} onOpenMedia={(id) => onOpenMedia(id)} onSelectItem={onSelectItem} />
        </div>
      ))}
    </div>
  )
}
