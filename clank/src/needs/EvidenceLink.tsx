// One evidence entry, calmly: a link when the file can be opened (the projection's media allowlist first, then the
// /needs/evidence route, which serves only paths the backend itself extracted from that item's text), else the
// absolute path as text with a Copy button. WHY never a dead link: "no fake controls" (G2) - a path the backend
// will not serve (a directory, an unservable suffix) is shown as a path, not as a link that 404s.

import { useState } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from '../shared/model'
import { mediaUrl } from '../shared/api'
import { evidenceUrl } from './api'
import type { NeedsDoc, NeedsItem } from './types'

const SERVED = /\.(html|png|jpe?g|webp|gif|svg|mp4|webm|md|txt|json|jsonl|py|toml|ya?ml|csv|log|tsx?)$/i

export interface EvidenceLinkProps {
  backend: PluginBackend
  doc: NeedsDoc
  item: NeedsItem
  index: number
  /** When given, a path that is also in projection.media opens through the media route (video seek, report frame). */
  projection?: Projection | null
}

/** The href this entry opens, or null when it can only be shown as a path. */
export function evidenceHref(backend: PluginBackend, doc: NeedsDoc, item: NeedsItem, index: number, projection?: Projection | null): string | null {
  const entry = item.evidence[index]
  if (!entry) return null
  if (entry.kind === 'url') return entry.value
  if (entry.path && projection) {
    const media = Object.values(projection.media).find((candidate) => candidate.path === entry.path)
    if (media) return mediaUrl(backend, media.id)
  }
  if (!entry.path || entry.is_dir || !SERVED.test(entry.path)) return null
  return evidenceUrl(backend, doc, item, index)
}

export function EvidenceLink({ backend, doc, item, index, projection }: EvidenceLinkProps) {
  const entry = item.evidence[index]
  const [copied, setCopied] = useState(false)
  if (!entry) return null
  const href = evidenceHref(backend, doc, item, index, projection)
  const shown = entry.path ?? entry.value
  if (href) {
    return (
      <a className="vt-needs-evidence" href={href} target="_blank" rel="noreferrer" title={shown} data-testid="vt-needs-evidence">
        {entry.label}
        {entry.line ? `:${entry.line}` : ''}
      </a>
    )
  }
  return (
    <span className="vt-needs-evidence vt-needs-evidence-path" title={shown} data-testid="vt-needs-evidence">
      <code>{shown}</code>
      <button
        type="button"
        className="vt-btn vt-faint vt-small"
        onClick={() => {
          try {
            void navigator.clipboard?.writeText(shown).then(() => setCopied(true), () => setCopied(false))
          } catch {
            setCopied(false)
          }
        }}
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </span>
  )
}
