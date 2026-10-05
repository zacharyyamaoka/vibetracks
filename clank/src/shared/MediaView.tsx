// Opens one media item in place: a video plays, an HTML report renders in a frame, a text write-up (audit) shows as
// text. Every view also offers "Open in new tab" (the same URL), so nothing is a dead end (BRIEF fr5, G2).
//
// WHY a refused URL says "This changed since you opened it: reload" (audit 2026-10-05 round 2, sibling of finding 1):
// a media URL carries the revision of the projection on screen, and the backend answers 409 when it no longer holds
// that revision or the listed file now resolves elsewhere. The view then shows the same calm line the needs evidence
// link shows, in place of the player and its "Open in new tab" (a link that would only 409 is a fake control), and
// waits for Zach: it never retries with a newer revision on its own, which would show a file he has not seen listed.

import { useCallback, useEffect, useState } from 'react'
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

/** Ask the backend whether each url still opens (HEAD), and re-ask a refused one after each accepted projection.
 * `check` false skips the HEAD (a text write-up learns its status from its own GET and reports it via markChanged).
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
  const settle = useCallback((url: string, verdict: string) => {
    setRefused((previous) => {
      if (verdict === 'ok' && !(url in previous)) return previous
      const next = { ...previous }
      if (verdict === 'ok') delete next[url]
      else next[url] = verdict
      return next
    })
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
    for (const url of urls) {
      void checkMedia(url).then(
        (verdict) => live && settle(url, verdict),
        () => undefined, // the backend unreachable: the page's own banner says so; the player shows its own state
      )
    }
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is the url list's identity
  }, [key, check, settle])

  useEffect(() => {
    // After a reload that kept the same revision (a restarted backend hands the same one back), check again: the
    // projection that was re-read is what the backend holds now. Only while refused, so a poll costs nothing.
    if (!stale) return
    let live = true
    for (const url of urls) {
      if (refused[url] !== 'changed') continue
      void checkMedia(url).then(
        (verdict) => live && verdict !== 'changed' && settle(url, verdict),
        () => undefined,
      )
    }
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on each accepted projection, not on `stale` flips
  }, [loaded])

  const markChanged = useCallback((url: string) => settle(url, 'changed'), [settle])
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
          {refusal ? <p className="vt-error" data-testid="vt-media-error">Could not load: {refusal}</p> : null}
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `onChanged` is a fresh closure each render; the url is the input
  }, [url])
  if (error) return <p className="vt-error" data-testid="vt-media-error">Could not load: {error}</p>
  if (text === null) return <p className="vt-faint" data-testid="vt-media-loading">Loading…</p>
  return <pre data-testid="vt-media-text">{text}</pre>
}
