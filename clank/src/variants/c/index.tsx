// Variant C: Three panes. PLACEHOLDER: the variant builder replaces this file (and adds siblings in this folder).
// Contract: export default a component taking VariantProps (../../shared/types.ts); render all three levels from
// props.projection, keep place through props.route / props.navigate, open media through props.mediaUrl.

import type { VariantProps } from '../../shared'

export const NAME = 'Three panes'

export default function VariantC({ projection, navigate }: VariantProps) {
  const kpis = projection.tracks.reduce((sum, track) => sum + track.kpis.length, 0)
  return (
    <div className="vt-page" data-testid="vt-variant-c">
      <h1 className="vt-h2">Variant C: Three panes (being built)</h1>
      <p className="vt-sub vt-num" data-testid="vt-data-proof">
        Data loaded: {projection.tracks.length} tracks · {kpis} KPIs · {Object.keys(projection.media).length} media · as of {projection.as_of}
      </p>
      <p className="vt-small" style={{ marginTop: 12 }}>
        <button type="button" className="vt-btn vt-muted" onClick={() => navigate({ kit: '1' })}>
          See the shared kit on this data →
        </button>
      </p>
    </div>
  )
}
