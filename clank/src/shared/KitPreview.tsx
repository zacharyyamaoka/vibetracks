// The shared kit on real data, for the variant builders: `#vt?kit=1` renders every shared component once, so a
// builder sees what each part looks like and does before composing it. Not one of the three proposals.

import { Breadcrumb } from './Breadcrumb'
import { EvidenceList } from './EvidenceList'
import {
  deltaVsBaseline,
  describeDelta,
  evidenceForValue,
  formatKpiValue,
  latestValue,
  northStar,
  type Projection,
  topLevelTracks,
} from './model'
import type { Route } from './route'
import { SeriesChart } from './SeriesChart'
import { Sparkline } from './Sparkline'
import { StatusWord } from './StatusWord'

export function KitPreview({ projection, mediaUrl, route, navigate }: {
  projection: Projection
  mediaUrl: (id: string) => string
  route: Route
  navigate: (route: Route, mode?: 'push' | 'replace') => void
}) {
  const track = projection.tracks.find((t) => t.id === (route.track ?? 'kinsim')) ?? projection.tracks[0]
  const kpi = track.kpis.find((k) => k.id === route.kpi) ?? northStar(track) ?? track.kpis[0]
  const selected = route.iteration ?? latestValue(kpi)?.iteration ?? track.iterations[track.iterations.length - 1].id
  const items = evidenceForValue(track, kpi, selected)
  const keep = { kit: '1' }
  return (
    <div className="vt-page" data-testid="vt-kit-preview">
      <Breadcrumb
        items={[
          { label: 'Proposals', onClick: () => navigate({}) },
          { label: 'Shared kit', onClick: () => navigate(keep) },
          { label: track.title, onClick: () => navigate({ ...keep, track: track.id }) },
          { label: kpi.label },
        ]}
      />
      <h1 className="vt-h1">Shared kit</h1>
      <p className="vt-sub">Every shared part once, on the real projection. Click a track, a KPI or a chart column.</p>

      <h2 className="vt-h3" style={{ marginTop: 28 }}>StatusWord · Sparkline (level 1 row parts)</h2>
      <table className="vt-table" style={{ marginTop: 8 }}>
        <thead>
          <tr>
            <th>Track</th>
            <th>Status</th>
            <th>North star</th>
            <th>vs baseline</th>
          </tr>
        </thead>
        <tbody>
          {[...topLevelTracks(projection), ...projection.tracks.filter((t) => t.parent)].map((t) => {
            const star = northStar(t)
            const latest = star ? latestValue(star) : null
            return (
              <tr key={t.id} className="vt-row-link" onClick={() => navigate({ ...keep, track: t.id }, 'replace')} aria-selected={t.id === track.id}>
                <td className="vt-strong">{t.parent ? `↳ ${t.title}` : t.title}</td>
                <td>
                  <StatusWord status={t.state} detail={t.state.detail} />
                </td>
                <td>
                  <span style={{ display: 'inline-flex', gap: 12, alignItems: 'center' }}>
                    <span className="vt-strong vt-num">{star ? formatKpiValue(star, latest) : '—'}</span>
                    {star ? <Sparkline values={star.values.map((v) => v.value)} target={star.target?.band ? { band: star.target.band } : null} step={star.target?.kind === 'scope'} /> : null}
                  </span>
                </td>
                <td className="vt-muted vt-small">{star ? describeDelta(star, deltaVsBaseline(star)) : ''}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <h2 className="vt-h3" style={{ marginTop: 32 }}>KPIs of {track.title}</h2>
      <p className="vt-small vt-faint" style={{ marginBottom: 6 }}>
        {track.kpis.map((k, index) => (
          <span key={k.id}>
            {index > 0 ? ' · ' : ''}
            <button type="button" className="vt-btn" style={k.id === kpi.id ? { color: 'var(--vt-fg)', fontWeight: 600 } : undefined} onClick={() => navigate({ ...keep, track: track.id, kpi: k.id }, 'replace')}>
              {k.label}
            </button>
          </span>
        ))}
      </p>
      <h2 className="vt-h3" style={{ marginTop: 16 }}>SeriesChart · {kpi.label}</h2>
      <p className="vt-small vt-muted">
        <StatusWord status={kpi.status} /> · {kpi.target?.label ?? 'no target set'} · {kpi.note}
      </p>
      <SeriesChart kpi={kpi} iterations={track.iterations} selected={selected} onSelectIteration={(id) => navigate({ ...keep, track: track.id, kpi: kpi.id, iteration: id })} />

      <h2 className="vt-h3" style={{ marginTop: 28 }}>EvidenceList · {kpi.label} at {track.iterations.find((it) => it.id === selected)?.label}</h2>
      <div style={{ marginTop: 8 }}>
        <EvidenceList items={items} mediaUrl={mediaUrl} empty="No evidence item is linked to this point; the readout above says why." />
      </div>
    </div>
  )
}
