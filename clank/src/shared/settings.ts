// The dashboard's view options: declared as Clank SettingsSections, rendered by SettingsView (the settings page the
// header's gear opens), persisted per browser, and handed to every variant as VariantProps.settings.
//
// WHY settings live on a settings page and never on toolbars (Zach, 2026-10-03, docs/dashboard/VARIANTS.md): "it's
// important that the tool bar is actually usable. This line setting should instead be in a settings page, so that
// eventually, when you deploy in a Clank workbench or something else, you can put access to it in the plugin
// settings page." So a view option (x-axis unit, deltas, density, ...) is an item in DASHBOARD_SETTINGS_SECTION, in
// Clank's own SettingsSection shape, and a header or toolbar carries only navigation and actions.
// WHY localStorage and not the .vtdash file: these are one reader's view preferences, not data; every access is
// wrapped because storage can be blocked (private window, previews), and the page must still work on defaults.
// WHY this file is generic over sections and imports nothing from ../roadmap: Dashboard.tsx composes
// [DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION], so the roadmap widget can import ../shared without a cycle.

import { useCallback, useEffect, useState } from 'react'
import type { SettingsItem, SettingsSection } from '@clank/api'
import type { RoadmapSettings } from '../roadmap'

export type SettingValue = boolean | number | string

export interface DashboardSettings {
  /** What one column is on KPI charts and tables: the track's own iteration (wave, tick, session) or the day. */
  xAxis: 'iteration' | 'day'
  /** Show each KPI's change beside its latest value. */
  showDeltas: boolean
}

export const defaultDashboardSettings: DashboardSettings = { xAxis: 'iteration', showDeltas: true }

export const DASHBOARD_SETTINGS_SECTION: SettingsSection = {
  id: 'dashboard',
  title: 'Dashboard',
  items: [
    {
      key: 'xAxis',
      title: 'X axis',
      description: "One column per iteration (the track's own wave, tick or session), or per calendar day.",
      type: 'enum',
      default: defaultDashboardSettings.xAxis,
      options: [
        { value: 'iteration', label: 'Iteration (wave · tick · session)' },
        { value: 'day', label: 'Day' },
      ],
      scope: 'app',
    },
    {
      key: 'showDeltas',
      title: 'Show deltas',
      description: "Show each KPI's change beside its latest value (against the pinned baseline or the previous iteration).",
      type: 'boolean',
      default: defaultDashboardSettings.showDeltas,
      scope: 'app',
    },
  ],
}

/** Everything a variant reads: VariantProps.settings. */
export interface DashboardSettingsState {
  dashboard: DashboardSettings
  roadmap: RoadmapSettings
}

/** A partial change, merged per section: `setSettings({ dashboard: { xAxis: 'day' } })`. */
export interface SettingsUpdate {
  dashboard?: Partial<DashboardSettings>
  roadmap?: Partial<RoadmapSettings>
}

/** Section id -> item key -> value. */
export type SettingsValues = Record<string, Record<string, SettingValue>>

export const SETTINGS_STORAGE_KEY = 'vibetracks.dashboard.settings'

/** The value an item accepts, or undefined: a boolean for boolean, a listed option for enum, a finite number in
 * [min, max] for number, a string for string. */
export function acceptValue(item: SettingsItem, value: unknown): SettingValue | undefined {
  switch (item.type) {
    case 'boolean':
      return typeof value === 'boolean' ? value : undefined
    case 'enum':
      return typeof value === 'string' && (item.options ?? []).some((option) => option.value === value) ? value : undefined
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
      if ((item.min !== undefined && value < item.min) || (item.max !== undefined && value > item.max)) return undefined
      return value
    case 'string':
      return typeof value === 'string' ? value : undefined
    default:
      return undefined
  }
}

function isSettingValue(value: unknown): value is SettingValue {
  return typeof value === 'boolean' || typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))
}

/** Defaults (the extra map, then each item's `default`) overlaid with the stored values that pass `acceptValue`.
 * A stored key no item declares is kept when it is a plain value, so a section can carry state before it has an
 * item for it; a stored value an item rejects falls back to the default. */
export function resolveSettings(sections: SettingsSection[], defaults: SettingsValues, stored: unknown): SettingsValues {
  const source = stored && typeof stored === 'object' ? (stored as Record<string, unknown>) : {}
  const result: SettingsValues = {}
  for (const section of sections) {
    const values: Record<string, SettingValue> = { ...(defaults[section.id] ?? {}) }
    for (const item of section.items) if (isSettingValue(item.default)) values[item.key] = item.default
    const saved = source[section.id]
    if (saved && typeof saved === 'object') {
      for (const [key, value] of Object.entries(saved as Record<string, unknown>)) {
        const item = section.items.find((candidate) => candidate.key === key)
        const accepted = item ? acceptValue(item, value) : isSettingValue(value) ? value : undefined
        if (accepted !== undefined) values[key] = accepted
      }
    }
    result[section.id] = values
  }
  return result
}

export function readStoredSettings(): unknown {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function writeStoredSettings(values: SettingsValues): void {
  try {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(values))
  } catch {
    // Private window or blocked storage: the change still applies to this page.
  }
}

export function clearStoredSettings(): void {
  try {
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
  } catch {
    // As above.
  }
}

export interface PersistentSettings {
  values: SettingsValues
  /** Merge a partial change into one or more sections, and save. */
  update: (patch: Record<string, Record<string, SettingValue> | undefined>) => void
  /** Back to every default, and forget the stored copy. */
  reset: () => void
}

/** The settings for `sections`, kept in localStorage under SETTINGS_STORAGE_KEY and in step across tabs. */
export function usePersistentSettings(sections: SettingsSection[], defaults: SettingsValues): PersistentSettings {
  const [values, setValues] = useState<SettingsValues>(() => resolveSettings(sections, defaults, readStoredSettings()))

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === SETTINGS_STORAGE_KEY) setValues(resolveSettings(sections, defaults, readStoredSettings()))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [sections, defaults])

  const update = useCallback(
    (patch: Record<string, Record<string, SettingValue> | undefined>) => {
      setValues((previous) => {
        const merged: SettingsValues = { ...previous }
        for (const [sectionId, change] of Object.entries(patch)) {
          if (change) merged[sectionId] = { ...(previous[sectionId] ?? {}), ...change }
        }
        const next = resolveSettings(sections, defaults, merged)
        writeStoredSettings(next)
        return next
      })
    },
    [sections, defaults],
  )

  const reset = useCallback(() => {
    clearStoredSettings()
    setValues(resolveSettings(sections, defaults, null))
  }, [sections, defaults])

  return { values, update, reset }
}
