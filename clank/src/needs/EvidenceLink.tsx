// One evidence entry, calmly: a link when the file can be opened (the projection's media allowlist first, then the
// /needs/evidence route, which serves only paths the backend itself extracted from that item's text), else the
// absolute path as text with a Copy button. WHY never a dead link: "no fake controls" (G2) - a path the backend
// will not serve (a directory, an unservable suffix) is shown as a path, not as a link that 404s.
//
// WHY a /needs/evidence link checks before it opens (audit 2026-10-05, finding 1): its URL carries the document
// revision Zach was shown, and the backend answers 409 when the evidence changed since. The link says so in place
// ("This changed since you opened it: reload") and waits for him; it never retries silently with a newer revision,
// which would open a file he has not seen listed.

import { useState, type MouseEvent } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from '../shared/model'
import { mediaUrl } from '../shared/api'
import { checkEvidence, evidencePath, evidenceUrl, requestNeedsReload } from './api'
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
  // The refusal for THIS href only: a reloaded doc gives a new href, which clears it.
  const [refused, setRefused] = useState<{ href: string; why: 'changed' | string } | null>(null)
  if (!entry) return null
  const href = evidenceHref(backend, doc, item, index, projection)
  const shown = entry.path ?? entry.value
  if (href) {
    const routePath = evidencePath(doc, item, index)
    const checked = routePath !== null && href === `${backend.baseUrl}${routePath}`
    const onClick = checked
      ? (event: MouseEvent<HTMLAnchorElement>) => {
          event.preventDefault()
          void checkEvidence(backend, routePath).then(
            (verdict) => {
              if (verdict === 'ok') {
                setRefused(null)
                window.open(href, '_blank', 'noopener,noreferrer')
              } else {
                setRefused({ href, why: verdict })
              }
            },
            (error: unknown) => setRefused({ href, why: error instanceof Error ? error.message : String(error) }),
          )
        }
      : undefined
    const refusal = refused && refused.href === href ? refused.why : null
    return (
      // WHY a fragment, not a wrapper: proposals style the link as a direct child/sibling (N6's
      // `.vt-needs-evidence + .vt-needs-evidence`, N5's flex attachment row); with no refusal the DOM is unchanged.
      <>
        <a className="vt-needs-evidence" href={href} target="_blank" rel="noreferrer" title={shown} data-testid="vt-needs-evidence" onClick={onClick}>
          {entry.label}
          {entry.line ? `:${entry.line}` : ''}
        </a>
        {refusal === 'changed' ? (
          <span className="vt-needs-evidence-stale" role="status" data-testid="vt-needs-evidence-stale" style={{ color: 'var(--vt-risk)' }}>
            {' '}This changed since you opened it:{' '}
            <button
              type="button"
              className="vt-btn vt-faint vt-small"
              onClick={() => {
                // The refusal belonged to the document on screen; once Zach reloads, the link is checked afresh on
                // its next click (a reload that yields the same revision must not leave a stale warning behind).
                setRefused(null)
                requestNeedsReload()
              }}
            >
              reload
            </button>
          </span>
        ) : refusal ? (
          <span className="vt-needs-evidence-stale" role="status" data-testid="vt-needs-evidence-refused" style={{ color: 'var(--vt-risk)' }}>
            {' '}Not opened: {refusal}
          </span>
        ) : null}
      </>
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
