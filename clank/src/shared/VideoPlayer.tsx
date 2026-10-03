// A run video from the backend's media route. WHY native <video controls> and preload="metadata": the backend serves
// HTTP Range, so the browser seeks without downloading an 85 MB bench recording first.

export interface VideoPlayerProps {
  src: string
  label?: string
  autoPlay?: boolean
  className?: string
}

export function VideoPlayer({ src, label, autoPlay = false, className }: VideoPlayerProps) {
  return (
    <video
      className={className}
      src={src}
      controls
      preload="metadata"
      playsInline
      muted={autoPlay}
      autoPlay={autoPlay}
      aria-label={label}
      data-testid="vt-video"
    />
  )
}
