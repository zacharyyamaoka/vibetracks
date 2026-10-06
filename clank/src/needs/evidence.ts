// Where one Needs evidence entry opens, as pure functions (no React, no fetch): api.ts re-exports them, EvidenceLink
// renders them, and evidence.check.mjs runs them under plain node.
//
// WHY every file link on a Needs page goes through /needs/evidence, and never /media (audit 2026-10-05 round 3,
// finding 1): a path that also appeared in projection.media used to open as /media/<id>?rev=<projection rev>. The
// projection is loaded separately from the Needs document, so with an OLD document on screen and a NEWER projection
// (a retargeted alias, a rebuilt snapshot) that link opened the NEW file under the old question, and skipped the
// document's own 409 refusal and reload line. The Needs document is what Zach reviewed, so its recorded evidence
// capability (`evidence_rev` + the entry's `eid`) is the only thing a link may carry; the route serves video, images
// and HTML with Range like /media (needs.py serve_evidence), so nothing is lost by not using /media.

import type { PluginBackend } from '@clank/api'
import type { NeedsDoc, NeedsEvidence, NeedsItem } from './types'

/** Suffixes needs.py SERVABLE answers for. A path with any other suffix is shown as text with Copy, never as a link
 * that would only fail ("no fake controls", G2). */
export const SERVED_EVIDENCE = /\.(html|png|jpe?g|webp|gif|svg|mp4|webm|md|txt|json|jsonl|py|toml|ya?ml|csv|log|tsx?)$/i

/** needs.py stamps these on every doc and evidence entry (`bind_evidence`); read here without widening types.ts. */
type BoundDoc = NeedsDoc & { evidence_rev?: string }
type BoundEvidence = NeedsEvidence & { eid?: string }

/** The backend path (`/needs/evidence?track&item&eid&rev`) for one evidence entry's file, or null when the backend
 * will not serve it (a URL, a directory, or a doc/entry without the identity needs.py binds).
 *
 * WHY eid + rev and never the list index (audit 2026-10-05, finding 1): the link must open the file Zach reviewed.
 * `eid` names the evidence as written (stable under reordering); `rev` is the document revision he was shown, and
 * the backend answers 409 instead of serving when the document's evidence, or what it resolves to, changed since.
 * Both come from the document passed in, explicitly: no module or backend-wide "current revision" is consulted. */
export function evidencePath(doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry: BoundEvidence | undefined = item.evidence[index]
  const rev = (doc as BoundDoc).evidence_rev
  if (!entry || entry.kind === 'url' || !entry.path || entry.is_dir) return null
  if (typeof entry.eid !== 'string' || !entry.eid || typeof rev !== 'string' || !rev) return null
  const query = new URLSearchParams({ track: doc.track, item: item.local_id, eid: entry.eid, rev })
  return `/needs/evidence?${query.toString()}`
}

/** Same-origin URL serving one evidence entry's file (a URL entry is itself), or null when it cannot be opened. */
export function evidenceUrl(backend: Pick<PluginBackend, 'baseUrl'>, doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry: NeedsEvidence | undefined = item.evidence[index]
  if (!entry) return null
  if (entry.kind === 'url') return entry.value
  const path = evidencePath(doc, item, index)
  return path ? `${backend.baseUrl}${path}` : null
}

/** The href one evidence entry opens on a Needs page, or null when it can only be shown as a path (a directory, an
 * unserved suffix, an entry without its bound identity). Only the document decides: there is deliberately no
 * projection parameter (see the WHY at the top of this file). */
export function evidenceHref(backend: Pick<PluginBackend, 'baseUrl'>, doc: NeedsDoc, item: NeedsItem, index: number): string | null {
  const entry = item.evidence[index]
  if (!entry) return null
  if (entry.kind === 'url') return entry.value
  if (!entry.path || entry.is_dir || !SERVED_EVIDENCE.test(entry.path)) return null
  return evidenceUrl(backend, doc, item, index)
}
