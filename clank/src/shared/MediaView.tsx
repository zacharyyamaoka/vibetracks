// Opens one media item in place: a video plays, an HTML report renders in a frame, a text write-up (audit) shows as
// text. Every view also offers "Open in new tab" (the same URL), so nothing is a dead end (BRIEF fr5, G2).

import { useEffect, useState } from 'react'
import type { MediaRef } from './model'
import { VideoPlayer } from './VideoPlayer'

export interface MediaViewProps {
  media: MediaRef
  url: string
  onClose?: () => void
}

export function MediaView({ media, url, onClose }: MediaViewProps) {
  return (
    <div className="vt-media-view" data-testid="vt-media-view" data-media-id={media.id} data-media-kind={media.kind}>
      <div className="vt-media-bar">
        <span>{media.label}</span>
        <a href={url} target="_blank" rel="noreferrer">
          Open in new tab
        </a>
        {onClose ? (
          <button type="button" className="vt-btn" onClick={onClose}>
            Close
          </button>
        ) : null}
      </div>
      {media.kind === 'video' ? <VideoPlayer src={url} label={media.label} /> : null}
      {media.kind === 'html' ? <iframe src={url} title={media.label} loading="lazy" /> : null}
      {media.kind === 'image' ? <img src={url} alt={media.label} style={{ maxWidth: '100%' }} /> : null}
      {/* WHY keyed by URL: switching documents must never show the previous one's text or error (audit 2026-10-04 #11:
          A's "HTTP 404" stayed on screen after B loaded). A fresh instance per URL starts at "Loading…". */}
      {media.kind === 'text' ? <TextMedia key={url} url={url} /> : null}
    </div>
  )
}

function TextMedia({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    // Belt and braces beside the key above: any caller that reuses this instance for a new URL still starts clean.
    setText(null)
    setError(null)
    const controller = new AbortController()
    fetch(url, { signal: controller.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`))))
      .then(
        (body) => {
          if (!controller.signal.aborted) setText(body)
        },
        (reason: unknown) => {
          if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
        },
      )
    return () => controller.abort()
  }, [url])
  if (error) return <p className="vt-error" data-testid="vt-media-error">Could not load: {error}</p>
  if (text === null) return <p className="vt-faint" data-testid="vt-media-loading">Loading…</p>
  return <pre data-testid="vt-media-text">{text}</pre>
}
