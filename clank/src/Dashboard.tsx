// The .vtdash viewer: loads the projection once, then renders the dashboard (variant A, "Drill-down pages").
// Frame (frozen contract, 2026-10-04): a flex column of [slim header][the scrolling content][#vt-review-bar]. The bar
// is a sibling OUTSIDE the scroller, so a pill in it can never cover content; NeedsShell portals its N pill into it.
// WHY a bar and not a pill floating over the corner: the floating pill covered the last row, answer controls and the
// roadmap focus card, and every page had to guess a bottom padding to clear it (120px here, 80px on needs, a 56px
// reserve in the needs kit). A bar takes its height out of the scroller instead, so nothing has to guess. A gear at
// the right end of the slim header opens the settings page (route key `settings=1`, so Back closes it); its values
// reach the variant as VariantProps.settings.
// WHY one variant and no A · B · C switcher (2026-10-05): Zach chose A ("Ok I agree lets please do A"); B (Shared
// timeline) and C (Three panes) were retired and deleted, and git history keeps them. A switcher with one choice would
// be a control with no effect.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Settings as SettingsIcon } from 'lucide-react'
import type { PluginBackend, SettingsSection, ViewerProps } from '@clank/api'
import './shared/calm.css'
import { bindMediaUrl, mediaRevision, useProjection } from './shared/api'
import { KitPreview } from './shared/KitPreview'
import { useRoute, type Route } from './shared/route'
import {
  DASHBOARD_SETTINGS_SECTION,
  defaultDashboardSettings,
  usePersistentSettings,
  type DashboardSettingsState,
  type SettingValue,
  type SettingsUpdate,
  type SettingsValues,
} from './shared/settings'
import { SettingsView } from './shared/SettingsView'
import { ROADMAP_SETTINGS_SECTION, defaultRoadmapSettings } from './roadmap'
import VariantA from './variants/a'
import { NeedsShell } from './needs'

/** The settings page's sections, in order. A new view option is an item in one of these, never a toolbar control. */
const SETTINGS_SECTIONS: SettingsSection[] = [DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION]
const SETTINGS_DEFAULTS: SettingsValues = {
  dashboard: { ...defaultDashboardSettings },
  roadmap: { ...defaultRoadmapSettings },
}

/** Where the retired A · B · C switcher kept its choice. Cleared once on mount so no browser keeps a stale key.
 * WHY clear it rather than leave it: a stored choice that nothing reads is state that says something untrue. */
const RETIRED_VARIANT_KEY = 'vibetracks.dashboard.variant'

function clearRetiredVariantChoice(): void {
  try {
    window.localStorage.removeItem(RETIRED_VARIANT_KEY)
  } catch {
    // Private window or blocked storage: there is nothing stored to clear.
  }
}

/** The .vtdash file is a tiny JSON: {"schema": "vibetracks-dashboard-file/1", "title": "...", "data_home": "..."}. */
export function vtdashTitle(text: string, fallback: string): string {
  try {
    const parsed = JSON.parse(text) as { title?: unknown }
    return typeof parsed.title === 'string' && parsed.title.trim() ? parsed.title : fallback
  } catch {
    return fallback
  }
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

export function Dashboard({ session, panel, backend }: ViewerProps & { backend: PluginBackend }) {
  const fallbackTitle = session.path.replace(/\.vtdash$/, '').split('/').pop() ?? session.path
  const title = vtdashTitle(typeof session.model === 'string' ? session.model : '', fallbackTitle)
  const { projection, error, loading, reload } = useProjection(backend)
  const [route, navigate] = useRoute()
  const persistent = usePersistentSettings(SETTINGS_SECTIONS, SETTINGS_DEFAULTS)
  const settings = persistent.values as unknown as DashboardSettingsState
  const { update: updateSettings } = persistent
  const setSettings = useCallback(
    (change: SettingsUpdate) => updateSettings(change as Record<string, Record<string, SettingValue> | undefined>),
    [updateSettings],
  )
  const settingsOpen = route.settings === '1'
  // WHY remember whether this page pushed the settings entry: closing then steps Back (no dead history entry); a
  // settings page reached by reload or a pasted link has nothing of ours behind it, so it replaces instead.
  const pushedSettings = useRef(false)
  const openSettings = useCallback(() => {
    pushedSettings.current = true
    navigate({ ...route, settings: '1' }, 'push')
  }, [navigate, route])
  const closeSettings = useCallback(() => {
    if (pushedSettings.current) {
      pushedSettings.current = false
      history.back()
      return
    }
    const rest: Route = { ...route }
    delete rest.settings
    navigate(rest, 'replace')
  }, [navigate, route])
  const root = useRef<HTMLDivElement>(null)
  const panelRef = useRef(panel)
  panelRef.current = panel
  useEffect(clearRetiredVariantChoice, [])

  // Esc on the settings page goes back to the dashboard.
  // WHY these guards: the listener is on window (a click on the chart leaves focus on <body>), so it must not fire
  // while the reader types in another Clank panel, an input, or CodeMirror, nor while this panel is in the back.
  useEffect(() => {
    if (!settingsOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || isEditable(event.target)) return
      const inside = event.target instanceof Node && root.current?.contains(event.target)
      const onBody = event.target === document.body || event.target === document.documentElement
      if (!inside && !(onBody && panelRef.current.isActive)) return
      event.preventDefault()
      closeSettings()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [settingsOpen, closeSettings])

  // WHY bound to THIS viewer's projection, with its revision in the memo key (Codex audit 2026-10-05 round 4, finding 1):
  // a Clank split shows two viewers of one .vtdash on one backend, each with the projection it last accepted. A link
  // must open the file this viewer listed, so its revision comes from the projection object this viewer renders, never
  // from a value shared with the other viewer. A reload that brings a new revision rebinds; one that keeps it does not.
  const shownRevision = mediaRevision(projection)
  const mediaUrl = useMemo(() => bindMediaUrl(backend, shownRevision), [backend, shownRevision])
  const needsPage = route.needs === '1' && !settingsOpen

  return (
    <div ref={root} className="vt-dash" data-testid="vt-dashboard" tabIndex={-1}>
      <header className="vt-dash-header">
        <button
          type="button"
          className="vt-btn vt-gear"
          aria-label="Settings"
          aria-pressed={settingsOpen}
          title="Settings"
          data-testid="vt-settings-gear"
          onClick={settingsOpen ? closeSettings : openSettings}
        >
          <SettingsIcon size={15} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      <div className="vt-scroll">
        {settingsOpen ? (
          <SettingsView
            sections={SETTINGS_SECTIONS}
            values={persistent.values}
            onChange={(sectionId, key, value) => updateSettings({ [sectionId]: { [key]: value } })}
            onReset={persistent.reset}
            onClose={closeSettings}
          />
        ) : route.needs === '1' ? (
          // The "Needs you" page (`#vt?track=<id>&needs=1`); it fetches /needs itself.
          <NeedsShell backend={backend} route={route} navigate={navigate} projection={projection} />
        ) : projection && route.kit ? (
          <KitPreview projection={projection} mediaUrl={mediaUrl} route={route} navigate={navigate} />
        ) : projection ? (
          <VariantA
            projection={projection}
            mediaUrl={mediaUrl}
            route={route}
            navigate={navigate}
            reload={reload}
            title={title}
            backend={backend}
            settings={settings}
            setSettings={setSettings}
          />
        ) : loading ? (
          <p className="vt-empty">Loading the projection…</p>
        ) : null}
        {error && !settingsOpen ? <BackendProblem error={error} backend={backend} onRetry={() => reload()} /> : null}
      </div>
      {/* The review bar: only the needs page puts anything in it (NeedsShell portals its pill in), so it reserves its
          height there, from the first render, and nowhere else.
          WHY reserved on the needs page before the pill arrives: the scroller's height never jumps when it does.
          WHY no height anywhere else (2026-10-05): with the A · B · C pill retired, an always-on bar was an empty 40 px
          strip under every other page. It stays in the DOM (hidden) so the element NeedsShell looks up always exists. */}
      <div id={REVIEW_BAR_ID} className="vt-review-bar" data-testid="vt-review-bar" hidden={!needsPage} />
    </div>
  )
}

/** The review bar's element id; NeedsShell portals its pill into `document.getElementById(REVIEW_BAR_ID)`. */
const REVIEW_BAR_ID = 'vt-review-bar'

/** The backend is not answering: say so, with its state, and offer Retry and Restart (both real actions). */
function BackendProblem({ error, backend, onRetry }: { error: string; backend: PluginBackend; onRetry: () => void }) {
  const [state, setState] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    backend.status().then((status) => live && setState(status.state ?? null), () => {})
    return () => {
      live = false
    }
  }, [backend, error])
  return (
    <div className="vt-error" role="alert" data-testid="vt-backend-problem">
      <p>The dashboard backend did not answer: {error}</p>
      {state ? <p className="vt-faint vt-small">backend {state}</p> : null}
      <p style={{ marginTop: 6, display: 'flex', gap: 16 }}>
        <button type="button" className="vt-btn vt-muted" onClick={onRetry}>
          Retry
        </button>
        <button
          type="button"
          className="vt-btn vt-muted"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            void backend.restart().finally(() => {
              setBusy(false)
              onRetry()
            })
          }}
        >
          {busy ? 'Restarting…' : 'Restart backend'}
        </button>
      </p>
    </div>
  )
}
