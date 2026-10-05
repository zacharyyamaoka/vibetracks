// The .vtdash viewer: loads the projection once, then hands it to the chosen variant. A quiet switcher in the
// bottom-right corner picks the variant (A · B · C); keys 1/2/3 do the same while the dashboard has focus. A gear at
// the right end of the slim header opens the settings page (route key `settings=1`, so Back closes it); its values
// reach every variant as VariantProps.settings.
// WHY a switcher inside the app and not a URL flag: Zach's rule "prototype switch in app: a temporary drop-down in
// the app, bottom-right, that switches variants live and remembers the choice" (rated Bad 2026-09-09 when a URL flag
// was the only way in). WHY localStorage for the choice: it is a per-viewer convenience, not data.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Settings as SettingsIcon } from 'lucide-react'
import type { PluginBackend, SettingsSection, ViewerProps } from '@clank/api'
import './shared/calm.css'
import { mediaUrl as buildMediaUrl, useProjection } from './shared/api'
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
import { VARIANTS } from './variants'
import { NeedsShell } from './needs'

/** The settings page's sections, in order. A new view option is an item in one of these, never a toolbar control. */
const SETTINGS_SECTIONS: SettingsSection[] = [DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION]
const SETTINGS_DEFAULTS: SettingsValues = {
  dashboard: { ...defaultDashboardSettings },
  roadmap: { ...defaultRoadmapSettings },
}

const STORAGE_KEY = 'vibetracks.dashboard.variant'

function readStoredVariant(): string {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return VARIANTS.some((variant) => variant.key === value) ? (value as string) : VARIANTS[0].key
  } catch {
    return VARIANTS[0].key
  }
}

function storeVariant(key: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, key)
  } catch {
    // Private window or blocked storage: the switch still works for this page.
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
  const [variantKey, setVariantKey] = useState<string>(readStoredVariant)
  const root = useRef<HTMLDivElement>(null)
  const panelRef = useRef(panel)
  panelRef.current = panel

  const choose = useCallback((key: string) => {
    setVariantKey(key)
    storeVariant(key)
  }, [])

  // WHY these guards on 1/2/3: the listener is on window (a click on the chart leaves focus on <body>), so it must not
  // fire while the reader types in another Clank panel, an input, or CodeMirror, nor while this panel is in the back.
  // Esc on the settings page goes back to the dashboard, under the same focus guards as the 1/2/3 keys.
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

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      const index = ['1', '2', '3'].indexOf(event.key)
      if (index < 0 || index >= VARIANTS.length || isEditable(event.target)) return
      const inside = event.target instanceof Node && root.current?.contains(event.target)
      const onBody = event.target === document.body || event.target === document.documentElement
      if (!inside && !(onBody && panelRef.current.isActive)) return
      event.preventDefault()
      choose(VARIANTS[index].key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [choose])

  const mediaUrl = useMemo(() => (id: string) => buildMediaUrl(backend, id), [backend])
  const variant = VARIANTS.find((item) => item.key === variantKey) ?? VARIANTS[0]
  const Variant = variant.component

  return (
    <div ref={root} className="vt-dash" data-testid="vt-dashboard" data-variant={variant.key} tabIndex={-1}>
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
          // The "Needs you" page (`#vt?track=<id>&needs=1`), whichever of A · B · C is chosen; it fetches /needs itself.
          <NeedsShell backend={backend} route={route} navigate={navigate} projection={projection} />
        ) : projection && route.kit ? (
          <KitPreview projection={projection} mediaUrl={mediaUrl} route={route} navigate={navigate} />
        ) : projection ? (
          <Variant
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
      <div className="vt-switcher" role="group" aria-label="Proposal" data-testid="vt-switcher" title="Switch proposal (keys 1, 2, 3)">
        <span className="vt-switch-label">Proposal</span>
        {VARIANTS.map((item, index) => (
          <button
            key={item.key}
            type="button"
            className="vt-btn"
            aria-pressed={item.key === variant.key}
            data-testid={`vt-switch-${item.key}`}
            title={`${item.letter} · ${item.name} (key ${index + 1})`}
            onClick={() => choose(item.key)}
          >
            {item.letter} · {item.name}
          </button>
        ))}
      </div>
    </div>
  )
}

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
