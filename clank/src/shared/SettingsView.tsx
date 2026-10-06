// The settings page the dashboard header's gear opens: every SettingsSection's items as one calm list, each with a
// native control (checkbox, select, number field, text field). Changes apply at once and persist (shared/settings.ts).
// WHY a page in the dashboard and not Clank's own Settings dialog yet: the sections are already in Clank's
// SettingsSection shape, so moving them into `ctx.registerSettings` later is a wiring change, not a rewrite; today
// Clank would store the values somewhere the dashboard does not read, which would be a control that does nothing.

import { useId } from 'react'
import type { SettingsItem, SettingsSection } from '@clank/api'
import type { SettingValue, SettingsValues } from './settings'

export interface SettingsViewProps {
  sections: SettingsSection[]
  values: SettingsValues
  onChange: (sectionId: string, key: string, value: SettingValue) => void
  /** Back to every default (a real action: it clears the stored copy). */
  onReset: () => void
  onClose: () => void
}

export function SettingsView({ sections, values, onChange, onReset, onClose }: SettingsViewProps) {
  return (
    <div className="vt-page vt-settings" data-testid="vt-settings">
      <p className="vt-small">
        <button type="button" className="vt-btn vt-muted" onClick={onClose} data-testid="vt-settings-close">
          ← Back to the dashboard
        </button>
      </p>
      <h1 className="vt-h1" style={{ marginTop: 14 }}>
        Settings
      </h1>
      <p className="vt-sub" style={{ marginTop: 6 }}>
        View options for this dashboard. They apply at once and are kept in this browser.
      </p>
      {sections.map((section) => (
        <section key={section.id} className="vt-settings-section" data-testid={`vt-settings-section-${section.id}`}>
          <h2 className="vt-h3">{section.title}</h2>
          {section.items.length === 0 ? (
            <p className="vt-faint vt-small vt-settings-empty">No settings yet.</p>
          ) : (
            <ul>
              {section.items.map((item) => (
                <SettingRow
                  key={item.key}
                  item={item}
                  value={values[section.id]?.[item.key]}
                  onChange={(value) => onChange(section.id, item.key, value)}
                />
              ))}
            </ul>
          )}
        </section>
      ))}
      <p className="vt-small" style={{ marginTop: 32 }}>
        <button type="button" className="vt-btn vt-muted" onClick={onReset} data-testid="vt-settings-reset">
          Reset to defaults
        </button>
      </p>
    </div>
  )
}

function SettingRow({ item, value, onChange }: { item: SettingsItem; value: SettingValue | undefined; onChange: (value: SettingValue) => void }) {
  const id = useId()
  const describedBy = item.description ? `${id}-description` : undefined
  return (
    <li className="vt-settings-row" data-testid={`vt-setting-${item.key}`}>
      <div className="vt-settings-text">
        <label htmlFor={id} className="vt-settings-title">
          {item.title}
        </label>
        {item.description ? (
          <p id={describedBy} className="vt-muted vt-small">
            {item.description}
          </p>
        ) : null}
      </div>
      <div className="vt-settings-control">
        <SettingControl id={id} describedBy={describedBy} item={item} value={value} onChange={onChange} />
      </div>
    </li>
  )
}

function SettingControl({
  id,
  describedBy,
  item,
  value,
  onChange,
}: {
  id: string
  describedBy: string | undefined
  item: SettingsItem
  value: SettingValue | undefined
  onChange: (value: SettingValue) => void
}) {
  switch (item.type) {
    case 'boolean':
      return <input id={id} type="checkbox" aria-describedby={describedBy} checked={value === true} onChange={(event) => onChange(event.target.checked)} />
    case 'enum':
      return (
        <select id={id} aria-describedby={describedBy} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)}>
          {(item.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )
    case 'number':
      return (
        <input
          id={id}
          type="number"
          aria-describedby={describedBy}
          min={item.min}
          max={item.max}
          value={typeof value === 'number' ? value : ''}
          onChange={(event) => {
            const next = event.target.valueAsNumber
            // A half-typed or out-of-range number is not saved; the field keeps the last valid value.
            if (Number.isFinite(next) && (item.min === undefined || next >= item.min) && (item.max === undefined || next <= item.max)) onChange(next)
          }}
        />
      )
    case 'string':
      return <input id={id} type="text" aria-describedby={describedBy} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} />
    default:
      return null
  }
}
