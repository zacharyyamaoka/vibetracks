// Truthful clamping for variant A: when geometry forces a stored string short, the cut is an explicit "…" and the whole
// raw value stays one hover away (title). Two tools, chosen by alignment:
//   - left-aligned text uses CSS -webkit-line-clamp (class `vt-a-clamp-N`): Chrome draws the "…" itself;
//   - right-aligned text (scorecard column headers) uses <ClampText>, which cuts the string itself.
// WHY two: Chrome puts a line-clamp's ellipsis past the right edge when the text is right-aligned, so the cut showed no
// mark ("wave closed: 7/9 landed · +3 rungs (RG1," — integration check 2026-10-04; measured scrollWidth 100 > 88 in an
// isolated page). Left-aligning the headers would break the column rule (a header aligns with its numbers), so the
// right-aligned ones measure and cut in JS instead.

import { useLayoutEffect, useRef, useState } from 'react'

export interface ClampTextProps {
  text: string
  lines: number
  className?: string
  /** Shown on hover when the text is cut; defaults to the whole text. Kept when the text is not cut, too. */
  title?: string
  /** A styled run before the text (counted in the measure, never cut): "◆ ruler · ". */
  lead?: { text: string; className: string; title?: string } | null
  /** A styled run after the text (counted in the measure, never cut): " latest". */
  after?: { text: string; className: string } | null
}

// WHY longhands, never the `font` shorthand: Chrome serializes a computed `font` as "" when a longhand it cannot
// express is set (the tables use tabular-nums), and an empty font measured every header in the 16px default.
const STYLE_KEYS = ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'fontStretch', 'fontVariant', 'fontKerning', 'letterSpacing', 'wordSpacing', 'lineHeight', 'whiteSpace', 'overflowWrap', 'wordBreak', 'textTransform', 'fontFeatureSettings', 'fontVariantNumeric'] as const

/** The longest prefix of `text` that, with "…", fits in `lines` lines of `element`'s box; null when the whole fits. */
function measureCut(element: HTMLElement, text: string, lines: number, lead: string, after: string): number | null {
  const width = element.clientWidth
  if (width <= 0) return null
  const style = getComputedStyle(element)
  const probe = document.createElement('div')
  for (const key of STYLE_KEYS) probe.style[key] = style[key]
  Object.assign(probe.style, { position: 'absolute', visibility: 'hidden', left: '-100000px', top: '0', width: `${width}px`, padding: '0', border: '0' })
  document.body.appendChild(probe)
  try {
    const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.2
    const limit = lines * lineHeight + 1
    const fits = (body: string) => {
      probe.textContent = `${lead}${body}${after}`
      return probe.getBoundingClientRect().height <= limit
    }
    if (fits(text)) return null
    let low = 0
    let high = text.length - 1
    while (low < high) {
      const mid = Math.ceil((low + high) / 2)
      if (fits(`${text.slice(0, mid).trimEnd()}…`)) low = mid
      else high = mid - 1
    }
    // Prefer a word boundary when it costs at most a few characters ("+3 rungs…" over "+3 rung…"); a longer word is
    // cut mid-word rather than dropping most of what fits.
    const space = text.slice(0, low).search(/\s\S*$/)
    return space > 0 && low - space <= 4 ? space : low
  } finally {
    probe.remove()
  }
}

export function ClampText({ text, lines, className, title, lead, after }: ClampTextProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [cut, setCut] = useState<number | null>(null)
  const leadText = lead?.text ?? ''
  const afterText = after?.text ?? ''
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => {
      const next = measureCut(element, text, lines, leadText, afterText)
      setCut((previous) => (previous === next ? previous : next))
    }
    measure()
    // The box's width follows the table's layout (fonts, a resize, the column count), so re-measure on every change.
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    void document.fonts?.ready.then(measure)
    return () => observer.disconnect()
  }, [text, lines, leadText, afterText])
  const shown = cut === null ? text : `${text.slice(0, cut).trimEnd()}…`
  return (
    <span ref={ref} className={className} title={title ?? (cut === null ? undefined : text)} data-clamped={cut === null ? undefined : 'true'}>
      {lead ? (
        <span className={lead.className} title={lead.title}>
          {lead.text}
        </span>
      ) : null}
      {shown}
      {after ? <span className={after.className}>{after.text}</span> : null}
    </span>
  )
}
