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
      {media.kind === 'text' ? <TextMedia url={url} /> : null}
    </div>
  )
}

function TextMedia({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    fetch(url, { signal: controller.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`))))
      .then(setText, (reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => controller.abort()
  }, [url])
  if (error) return <p className="vt-error">Could not load: {error}</p>
  if (text === null) return <p className="vt-faint">Loading…</p>
  return <pre>{text}</pre>
}
