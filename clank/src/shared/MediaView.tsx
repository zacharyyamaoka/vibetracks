// Opens one media item in place: a video plays, an HTML report renders in a frame, a text write-up (audit) shows as
// text. Every view also offers "Open in new tab" (the same URL), so nothing is a dead end (BRIEF fr5, G2).
//
// WHY a refused URL says "This changed since you opened it: reload" (audit 2026-10-05 round 2, sibling of finding 1):
// a media URL carries the revision of the projection on screen, and the backend answers 409 when it no longer holds
// that revision or the listed file now resolves elsewhere. The view then shows the same calm line the needs evidence
// link shows, in place of the player and its "Open in new tab" (a link that would only 409 is a fake control), and
// waits for Zach: it never retries with a newer revision on its own, which would show a file he has not seen listed.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { MediaRef } from './model'
import { checkMedia, requestProjectionReload, useProjectionsLoaded } from './api'
import { VideoPlayer } from './VideoPlayer'

export interface MediaRefusals {
  /** Why the backend refused this url ('changed' for a 409, else its status text), or null while it opens. */
  refusal(url: string): string | null
  /** True when any of the urls answered 409: the view shows StaleMediaLine in place of every player and link. */
  stale: boolean
  /** Record a 409 learnt some other way (a text write-up's own GET). */
  markChanged(url: string): void
}

/** Ask the backend whether each url still opens (HEAD), and re-ask EVERY refused one after each accepted projection.
 * `check` false skips the first HEAD (a text write-up learns its status from its own GET and reports it via
 * markChanged); a refusal recorded that way is still re-asked with HEAD after a reload.
 *
 * WHY one hook for MediaView and the item page's real|sim pair (verifier, 2026-10-05, item c): the pair drew its own
 * <video> elements without asking, so a 409 left two dead players at 0:00 and two "open in new tab" links that would
 * only 409 again. Every view of a media url now learns the backend's answer the same way and shows the same line. */
export function useMediaRefusals(urls: readonly string[], check = true): MediaRefusals {
  // A refusal belongs to one url: a reloaded projection with a new revision gives new urls, which never inherit it.
  const [refused, setRefused] = useState<Record<string, string>>({})
  const loaded = useProjectionsLoaded()
  const key = urls.join('\n')
  const current = (url: string) => (urls.includes(url) ? (refused[url] ?? null) : null)
  const stale = urls.some((url) => refused[url] === 'changed')
  // WHY a ticket per url (the stale-response guard): an url can be asked twice in flight (its first HEAD, then a
  // re-check after a reload). Only the answer to the LATEST question may land, so a slow early 404 can never undo the
  // recovery a later 200 reported, nor a slow early 200 hide a later refusal.
  const asked = useRef(new Map<string, number>())
  const ask = useCallback((url: string, isLive: () => boolean) => {
    const ticket = (asked.current.get(url) ?? 0) + 1
    asked.current.set(url, ticket)
    void checkMedia(url).then(
      (verdict) => {
        if (!isLive() || asked.current.get(url) !== ticket) return
        setRefused((previous) => {
          if (verdict === 'ok' ? !(url in previous) : previous[url] === verdict) return previous
          const next = { ...previous }
          if (verdict === 'ok') delete next[url]
          else next[url] = verdict
          return next
        })
      },
      () => undefined, // the backend unreachable: the page's own banner says so; the player shows its own state
    )
  }, [])

  useEffect(() => {
    // Forget refusals of urls no longer shown, so a url that comes back is asked again, never assumed.
    setRefused((previous) => {
      const kept = Object.fromEntries(Object.entries(previous).filter(([url]) => urls.includes(url)))
      return Object.keys(kept).length === Object.keys(previous).length ? previous : kept
    })
    // A video, frame or image cannot read its own status, so it asks with HEAD. The player renders meanwhile: the
    // common case pays no wait.
    if (!check) return
    let live = true
    for (const url of urls) ask(url, () => live)
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is the url list's identity
  }, [key, check, ask])

  useEffect(() => {
    // After each accepted projection, ask again about EVERY url this view holds a refusal for, whatever the refusal.
    // WHY every one and not only 409s (Codex audit 2026-10-05 round 4, finding 2): a reload that keeps the revision
    // (a restored file, a fixed permission, a restarted backend handing the same revision back) gives the same urls,
    // so nothing else would ever ask again: a 404 or 403 seen once stayed on screen for good, hiding evidence that
    // opens. Only refused urls are asked, so a reload with everything open costs no request.
    let live = true
    for (const url of urls) if (url in refused) ask(url, () => live)
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on each accepted projection only
  }, [loaded])

  const markChanged = useCallback((url: string) => {
    // A refusal learnt from the url's own GET is the newest answer: it outranks any HEAD still in flight.
    asked.current.set(url, (asked.current.get(url) ?? 0) + 1)
    setRefused((previous) => (previous[url] === 'changed' ? previous : { ...previous, [url]: 'changed' }))
  }, [])
  return { refusal: current, stale, markChanged }
}

/** The calm line a refused (409) media view shows in place of its players and links. Its reload re-reads the
 * projection the page shows; it never retries with a newer revision on its own. */
export function StaleMediaLine() {
  return (
    <p className="vt-media-stale" role="status" data-testid="vt-media-stale" style={{ color: 'var(--vt-risk)' }}>
      This changed since you opened it:{' '}
      <button type="button" className="vt-btn vt-faint vt-small" onClick={() => requestProjectionReload()}>
        reload
      </button>
    </p>
  )
}

/** The line a view shows when the backend refused its media for another reason (404, 403, …), in place of the player.
 * WHY it offers "reload" too (Codex audit 2026-10-05 round 4, finding 2): a restored file or a fixed permission keeps
 * the same revision, and only a re-read of the projection makes every view ask again (useMediaRefusals, TextMedia).
 * Without it the item page had no way back short of leaving it. Like StaleMediaLine, it never retries on its own. */
export function MediaErrorLine({ refusal }: { refusal: string }) {
  return (
    <p className="vt-error" data-testid="vt-media-error">
      Could not load: {refusal}
      {' · '}
      <button type="button" className="vt-btn vt-faint vt-small" data-testid="vt-media-reload" onClick={() => requestProjectionReload()}>
        reload
      </button>
    </p>
  )
}

export interface MediaViewProps {
  media: MediaRef
  url: string
  onClose?: () => void
}

export function MediaView({ media, url, onClose }: MediaViewProps) {
  const checks = useMediaRefusals([url], media.kind !== 'text')
  const refusal = checks.refusal(url)
  const stale = checks.stale

  return (
    <div className="vt-media-view" data-testid="vt-media-view" data-media-id={media.id} data-media-kind={media.kind}>
      <div className="vt-media-bar">
        <span>{media.label}</span>
        {stale ? null : (
          <a href={url} target="_blank" rel="noreferrer">
            Open in new tab
          </a>
        )}
        {onClose ? (
          <button type="button" className="vt-btn" onClick={onClose}>
            Close
          </button>
        ) : null}
      </div>
      {stale ? (
        <StaleMediaLine />
      ) : (
        <>
          {refusal ? <MediaErrorLine refusal={refusal} /> : null}
          {media.kind === 'video' && !refusal ? <VideoPlayer src={url} label={media.label} /> : null}
          {media.kind === 'html' && !refusal ? <iframe src={url} title={media.label} loading="lazy" /> : null}
          {media.kind === 'image' && !refusal ? <img src={url} alt={media.label} style={{ maxWidth: '100%' }} /> : null}
          {/* WHY keyed by URL: switching documents must never show the previous one's text or error (audit 2026-10-04
              #11: A's "HTTP 404" stayed on screen after B loaded). A fresh instance per URL starts at "Loading…". */}
          {media.kind === 'text' ? <TextMedia key={url} url={url} onChanged={() => checks.markChanged(url)} /> : null}
        </>
      )}
    </div>
  )
}

function TextMedia({ url, onChanged }: { url: string; onChanged: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // WHY a retry on each accepted projection while failed (Codex audit 2026-10-05 round 4, finding 2, the text sibling):
  // a write-up reads its status from its own GET, keyed by its url; a reload that keeps the revision keeps the url, so
  // a 404 seen once would never be asked again. A write-up that loaded is left alone: a reload costs it nothing.
  const loaded = useProjectionsLoaded()
  const [attempt, setAttempt] = useState(0)
  const failed = useRef(false)
  failed.current = error !== null
  useEffect(() => {
    if (failed.current) setAttempt((previous) => previous + 1)
  }, [loaded])
  useEffect(() => {
    // Belt and braces beside the key above: any caller that reuses this instance for a new URL still starts clean.
    setText(null)
    setError(null)
    const controller = new AbortController()
    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (response.status === 409) {
          if (!controller.signal.aborted) onChanged()
          return null
        }
        return response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`))
      })
      .then(
        (body) => {
          if (!controller.signal.aborted && body !== null) setText(body)
        },
        (reason: unknown) => {
          if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
        },
      )
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `onChanged` is a fresh closure each render; url + attempt are the input
  }, [url, attempt])
  if (error) return <MediaErrorLine refusal={error} />
  if (text === null) return <p className="vt-faint" data-testid="vt-media-loading">Loading…</p>
  return <pre data-testid="vt-media-text">{text}</pre>
}
