// Two track-page sections a track may carry (the rig, 2026-10-06; Zach, Daily Note - Oct 6 2026: "A key thing here is
// like a table that shows the different deployments, and then the KPIs based in different simulators and with
// different settings ... I want to be able to see the rerun io things that show the playbacks for the various
// trajectories"):
//   KpiTableSection  "KPIs by deployment, backend and settings": the bam_deployments KPI-table export, one row per
//                    export row, one column per KPI in the export's kpi_defs order. It scrolls inside its own box
//                    with the row's identity sticky, so the page never scrolls sideways.
//   PlaybacksSection "Playbacks (Rerun)": one entry per index.json run, grouped by session (collapsed: 57 runs stay
//                    scannable), each with the one-line command that opens it and its mp4 when there is one.
// Both say so when their input is missing, with the command that makes it (never an empty table).
// WHY these two sections exist: src/dev/bam_rig_loop/briefs/KPI-VIEW.md (the rig worktree's brief) turns that Daily Note
// request into the page spec; the tests pin the ids and orders (tests/browser/rig_kpis.mjs).

import { useState } from 'react'
import type { Track } from '../../shared'
import {
  NOT_MEASURED,
  rangeLabel,
  runsLabel,
  settingWords,
  tableCell,
  twinWords,
  type KpiTable,
  type KpiTableRow,
  type Playbacks,
} from './robotKpis'

/** A command as one copyable line: the text itself is selectable, and "copy" puts exactly it on the clipboard. */
export function CopyLine({ text, testid }: { text: string; testid: string }) {
  const [copied, setCopied] = useState<'copied' | 'failed' | null>(null)
  return (
    <span className="vt-a-copyline">
      <code className="vt-a-code" data-testid={testid}>
        {text}
      </code>
      <button
        type="button"
        className="vt-btn vt-a-link vt-a-copybtn"
        aria-label="Copy this command"
        onClick={() => {
          const done = (word: 'copied' | 'failed') => {
            setCopied(word)
            window.setTimeout(() => setCopied(null), 1600)
          }
          try {
            void navigator.clipboard.writeText(text).then(() => done('copied'), () => done('failed'))
          } catch {
            done('failed')
          }
        }}
      >
        {copied ?? 'copy'}
      </button>
    </span>
  )
}

function Missing({ testid, message, command, commandTestid }: { testid: string; message: string | null; command: string | null; commandTestid: string }) {
  return (
    <div className="vt-a-missingbox" data-testid={testid}>
      <p className="vt-small">{message ?? 'Not available.'}</p>
      {command ? (
        <p className="vt-small vt-a-missingcmd">
          <span className="vt-faint">Make it: </span>
          <CopyLine text={command} testid={commandTestid} />
        </p>
      ) : null}
    </div>
  )
}

function shortSha(table: KpiTable): string | null {
  const sha = table.cache?.sha256
  return typeof sha === 'string' && sha ? sha.slice(0, 8) : null
}

export function KpiTableSection({ track, table, docs }: { track: Track; table: KpiTable; docs: { label: string; href: string | null; path: string | null } | null }) {
  const title = (
    <div className="vt-a-section-head">
      <h2 className="vt-h3">KPIs by deployment, backend and settings</h2>
      {table.state === 'ok' ? (
        <span className="vt-a-h-note">
          {table.rows.length} rows · one per deployment × backend × settings
        </span>
      ) : null}
    </div>
  )
  if (table.state !== 'ok') {
    return (
      <section className="vt-a-section" data-testid="vt-a-kpi-table" data-state={table.state}>
        {title}
        <Missing testid="vt-a-kpi-table-missing" message={table.message} command={table.command} commandTestid="vt-a-kpi-table-command" />
      </section>
    )
  }
  const defs = table.kpi_defs
  const headline = table.headline
  const sha = shortSha(table)
  return (
    <section className="vt-a-section" data-testid="vt-a-kpi-table" data-state="ok" data-track={track.id}>
      {title}
      <p className="vt-small vt-faint vt-a-kt-stamp" data-testid="vt-a-kpi-table-stamp">
        bam_deployments contract {table.contract ?? '?'} · computed {table.generated_label ?? 'time not recorded'}
        {sha ? (
          <>
            {' '}· cache <span title={table.cache?.sha256}>{sha}</span>
          </>
        ) : null}
        {typeof table.cache?.runs === 'number' ? ` · ${table.cache.runs} cached runs` : ''}
        {table.csv ? (
          <>
            {' '}· CSV <code className="vt-a-code" data-testid="vt-a-kpi-table-csv">{table.csv}</code>
          </>
        ) : null}
        {docs ? (
          <>
            {' '}·{' '}
            {docs.href ? (
              <a className="vt-a-link" data-testid="vt-a-kpi-doc" href={docs.href} target="_blank" rel="noreferrer">
                {docs.label}
              </a>
            ) : (
              <span data-testid="vt-a-kpi-doc" title={docs.path ?? undefined}>
                {docs.label}
              </span>
            )}
          </>
        ) : null}
      </p>
      <div className="vt-a-tablescroll vt-a-kt-scroll" data-testid="vt-a-kpi-table-scroll">
        <table className="vt-table vt-a-kt" aria-label="KPIs by deployment, backend and settings">
          <thead>
            <tr>
              <th className="vt-a-sticky vt-a-kt-id">Deployment · backend</th>
              <th className="vt-a-kt-runs">Runs</th>
              {defs.map((def) => (
                <th key={def.key} className="vt-a-kt-num" data-kpi={def.key}>
                  <span className="vt-a-kt-head">{def.label}</span>
                  <small>{def.unit === 'deg' ? '°' : def.unit || 'count'}</small>
                </th>
              ))}
              <th className="vt-a-kt-settings">Settings</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <KpiTableRowView
                key={`${row.deployment_id}|${row.period}|${index}`}
                row={row}
                index={index}
                table={table}
                headline={headline?.real_row === index ? 'real' : headline?.twin_row === index ? 'twin' : null}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function KpiTableRowView({ row, index, table, headline }: { row: KpiTableRow; index: number; table: KpiTable; headline: 'real' | 'twin' | null }) {
  const deployment = table.deployments[row.deployment_id] ?? row.deployment_id
  const settings = isRecord(row.settings) ? row.settings : {}
  const words = settingWords(row, table.settings_keys)
  const identity = [row.control_mode, settings.mounting, settings.torque_cap_nm !== null && settings.torque_cap_nm !== undefined ? `cap ${String(settings.torque_cap_nm)} N·m` : null]
    .filter((part) => part !== null && part !== undefined && part !== '')
    .map(String)
  const plant = typeof settings.plant === 'string' ? settings.plant : null
  return (
    <tr
      className={headline ? 'vt-a-kt-headline' : undefined}
      data-testid="vt-a-kpi-table-row"
      data-index={index}
      data-deployment={row.deployment_id}
      data-period={row.period}
      data-backend={row.backend ?? ''}
      data-headline={headline ?? undefined}
    >
      <td className="vt-a-sticky vt-a-kt-id" title={row.period}>
        <span className="vt-a-kt-name">
          <b>{deployment}</b> · {row.backend ?? '?'}
          {row.twin_version ? ` ${row.twin_version}` : ''}
        </span>
        <small className="vt-a-kt-sub">
          {identity.length ? identity.join(' · ') : row.na_reason ? '' : '—'}
          {headline ? <span className="vt-a-kt-tag"> · headline {headline === 'real' ? 'real row' : 'twin'}</span> : null}
        </small>
        {row.na_reason ? (
          <small className="vt-a-kt-na" data-testid="vt-a-kpi-table-na">
            {row.na_reason}
          </small>
        ) : null}
      </td>
      <td className="vt-a-kt-runs">
        <span className="vt-a-kt-name">{runsLabel(row)}</span>
        <small className="vt-a-kt-sub">{rangeLabel(row.start, row.end)}</small>
      </td>
      {table.kpi_defs.map((def) => {
        const cell = tableCell(row, def)
        return (
          <td key={def.key} className={`vt-a-kt-num${cell.measured ? ' vt-num' : ' vt-gap vt-a-kt-gap'}`} data-kpi={def.key} title={cell.title ?? undefined}>
            {cell.text}
          </td>
        )
      })}
      <td className="vt-a-kt-settings">
        <span className="vt-a-kt-words">{words.length ? words.map((word) => word.text).join(' · ') : row.na_reason ? '—' : NOT_MEASURED}</span>
        {plant ? (
          <small className="vt-a-kt-plant vt-a-oneline" title={plant}>
            {plant}
          </small>
        ) : null}
      </td>
    </tr>
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function PlaybacksSection({ playbacks, mediaUrl }: { playbacks: Playbacks; mediaUrl: (id: string) => string }) {
  const twinRuns = playbacks.groups.reduce((sum, group) => sum + (group.twin_runs || 0), 0)
  const title = (
    <div className="vt-a-section-head">
      <h2 className="vt-h3">Playbacks (Rerun)</h2>
      {playbacks.state === 'ok' ? (
        <span className="vt-a-h-note">
          {playbacks.count} runs · {playbacks.groups.length} sessions · {twinRuns} with twin re-runs
        </span>
      ) : null}
    </div>
  )
  if (playbacks.state !== 'ok') {
    return (
      <section className="vt-a-section" data-testid="vt-a-playbacks" data-state={playbacks.state}>
        {title}
        <Missing testid="vt-a-playbacks-missing" message={playbacks.message} command={playbacks.command} commandTestid="vt-a-playbacks-command" />
      </section>
    )
  }
  return (
    <section className="vt-a-section" data-testid="vt-a-playbacks" data-state="ok">
      {title}
      <p className="vt-small vt-faint vt-a-pb-intro">
        Each line opens one real run in the Rerun viewer: the commanded target, the real trace and every twin version
        that re-ran it. Copy it into a terminal.
        {playbacks.message ? <span className="vt-tone-warn"> {playbacks.message}</span> : null}
      </p>
      <div className="vt-a-pb-groups">
        {playbacks.groups.map((group) => (
          <details key={group.id} className="vt-a-pb-group" data-testid="vt-a-playback-group" data-session={group.id}>
            <summary className="vt-a-pb-summary">
              <span className="vt-a-pb-label">{group.label}</span>
              <span className="vt-faint vt-small">
                {' '}· {group.count} run{group.count === 1 ? '' : 's'}
                {group.twin_runs ? ` · ${group.twin_runs} with twin re-runs` : ''}
              </span>
            </summary>
            <div className="vt-a-pb-list">
              {group.runs.map((entry) => (
                <div key={entry.run_id} className="vt-a-pb-entry" data-testid="vt-a-playback" data-run={entry.run_id}>
                  <div className="vt-a-pb-traj">
                    <span className="vt-a-kt-name">{entry.trajectory ?? entry.run_id}</span>
                    <small className="vt-a-kt-sub">
                      {entry.started_label ?? 'time not recorded'}
                      {entry.control_mode ? ` · ${entry.control_mode}` : ''}
                    </small>
                  </div>
                  <div className="vt-a-pb-twins vt-small" title="each twin version's re-run against the real run, RMS">
                    {entry.twin_versions.length ? <span className="vt-faint">twin vs real </span> : null}
                    <span className={entry.twin_versions.length ? 'vt-num' : 'vt-faint'}>{twinWords(entry)}</span>
                  </div>
                  <div className="vt-a-pb-video vt-small">
                    {entry.video ? (
                      <a className="vt-a-link" data-testid="vt-a-playback-video" href={mediaUrl(entry.video)} target="_blank" rel="noreferrer" title={entry.video_path ?? undefined}>
                        mp4
                      </a>
                    ) : (
                      <span className="vt-faint">{entry.video_path ? 'mp4 missing' : 'no video'}</span>
                    )}
                  </div>
                  <div className="vt-a-pb-cmd">
                    {entry.command ? <CopyLine text={entry.command} testid="vt-a-playback-command" /> : <span className="vt-faint vt-small">no viewer or .rrd named</span>}
                    {!entry.rrd_exists ? <small className="vt-tone-warn"> · .rrd missing</small> : null}
                  </div>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  )
}
