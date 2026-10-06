// The thin hosts the stories mount the real components in. Each one does only what the component's real host does
// (Dashboard.tsx for variant A, variant A's RoadmapSection for the widget): load through the real hooks against the
// fixture backend, keep the controlled state, and hand the callbacks to Storybook's actions.

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  RoadmapWidget,
  ROADMAP_SETTINGS_SECTION,
  defaultRoadmapSettings,
  useRoadmap,
  type RoadmapSettings,
  type RoadmapWidgetState,
} from '../src/roadmap'
import { mediaUrl as buildMediaUrl, useProjection } from '../src/shared/api'
import type { Route } from '../src/shared/route'
import { DASHBOARD_SETTINGS_SECTION, defaultDashboardSettings, type DashboardSettingsState, type SettingsUpdate, type SettingsValues } from '../src/shared/settings'
import { SettingsView } from '../src/shared/SettingsView'
import VariantA from '../src/variants/a'
import { useStoryBackend } from './decorators'

export interface RoadmapHarnessProps {
  track: string
  /** 'calm', 'full', or both stacked (the calm head over the expanded board, one document for both). */
  density: 'calm' | 'full' | 'both'
  initialState?: RoadmapWidgetState
  settings?: RoadmapSettings
  /** Call the roadmap's reload() once the first document is on screen: the second request is the one a
   * 'refresh-fails' backend rejects, so this is how a story reaches the failed-refresh state without a 30 s poll. */
  reloadAfterFirst?: boolean
  onOpenRung: (rungId: string) => void
  onOpenEvidence: (ref: { path: string; line?: number }) => void
}

/** RoadmapWidget on useRoadmap, as a variant mounts it, inside a page's padding. */
export function RoadmapHarness({ track, density, initialState = {}, settings = defaultRoadmapSettings, reloadAfterFirst, onOpenRung, onOpenEvidence }: RoadmapHarnessProps) {
  const backend = useStoryBackend()
  const roadmap = useRoadmap(backend, track)
  const [state, setState] = useState<RoadmapWidgetState>(initialState)
  const reloaded = useRef(false)
  useEffect(() => {
    if (!reloadAfterFirst || reloaded.current || !roadmap.doc) return
    reloaded.current = true
    roadmap.reload()
  }, [reloadAfterFirst, roadmap.doc, roadmap.reload])
  const widget = (shown: 'calm' | 'full') => (
    <RoadmapWidget
      track={track}
      doc={roadmap.doc}
      loading={roadmap.loading}
      state={state}
      onState={setState}
      onOpenRung={onOpenRung}
      onOpenEvidence={onOpenEvidence}
      density={shown}
      settings={settings}
    />
  )
  return (
    <div className="vt-page" data-testid="story-roadmap" data-track={track}>
      {density === 'full' ? widget('full') : widget('calm')}
      {density === 'both' ? <div style={{ marginTop: 28 }}>{widget('full')}</div> : null}
    </div>
  )
}

/** The Roadmap section of the settings page (shared/SettingsView.tsx), live, above the board it governs. */
export function RoadmapSettingsHarness({ track, initialEdges, initialState, onOpenRung, onOpenEvidence }: {
  track: string
  initialEdges: 'curve' | 'elbow'
  initialState: RoadmapWidgetState
  onOpenRung: (rungId: string) => void
  onOpenEvidence: (ref: { path: string; line?: number }) => void
}) {
  const [values, setValues] = useState<SettingsValues>({ roadmap: { ...defaultRoadmapSettings, edges: initialEdges } })
  return (
    <>
      <SettingsView
        sections={[ROADMAP_SETTINGS_SECTION]}
        values={values}
        onChange={(sectionId, key, value) => setValues((now) => ({ ...now, [sectionId]: { ...now[sectionId], [key]: value } }))}
        onReset={() => setValues({ roadmap: { ...defaultRoadmapSettings } })}
        onClose={() => {}}
      />
      <RoadmapHarness
        track={track}
        density="full"
        initialState={initialState}
        settings={values.roadmap}
        onOpenRung={onOpenRung}
        onOpenEvidence={onOpenEvidence}
      />
    </>
  )
}

/** Variant A as Dashboard.tsx mounts it, with the route kept in story state instead of the URL hash. */
export function VariantAHarness({ initialRoute, title = 'Agent work' }: { initialRoute: Route; title?: string }) {
  const backend = useStoryBackend()
  const { projection, error, loading, reload } = useProjection(backend)
  const [route, setRoute] = useState<Route>(initialRoute)
  const [settings, setSettingsState] = useState<DashboardSettingsState>({
    dashboard: { ...defaultDashboardSettings },
    roadmap: { ...defaultRoadmapSettings },
  })
  const mediaUrl = useMemo(() => (id: string) => buildMediaUrl(backend, id), [backend])
  const setSettings = (change: SettingsUpdate) =>
    setSettingsState((now) => ({
      dashboard: { ...now.dashboard, ...(change.dashboard ?? {}) },
      // A Partial<RoadmapSettings> may carry undefined values, so the merge is cast back (Dashboard.tsx casts its update too).
      roadmap: { ...now.roadmap, ...(change.roadmap ?? {}) } as RoadmapSettings,
    }))
  if (error) return <p className="vt-error" role="alert">{error}</p>
  if (!projection) return <p className="vt-empty">{loading ? 'Loading the projection…' : 'No projection.'}</p>
  return (
    <VariantA
      projection={projection}
      mediaUrl={mediaUrl}
      route={route}
      navigate={(next) => setRoute(next)}
      reload={reload}
      title={title}
      backend={backend}
      settings={settings}
      setSettings={setSettings}
    />
  )
}

/** The whole settings page (both sections), as the dashboard header's gear opens it. */
export function SettingsPageHarness() {
  const defaults: SettingsValues = { dashboard: { ...defaultDashboardSettings }, roadmap: { ...defaultRoadmapSettings } }
  const [values, setValues] = useState<SettingsValues>(defaults)
  return (
    <SettingsView
      sections={[DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION]}
      values={values}
      onChange={(sectionId, key, value) => setValues((now) => ({ ...now, [sectionId]: { ...now[sectionId], [key]: value } }))}
      onReset={() => setValues(defaults)}
      onClose={() => {}}
    />
  )
}
