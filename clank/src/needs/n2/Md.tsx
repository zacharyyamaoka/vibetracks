// Inline markdown, rendered truthfully: `code` spans and **bold** only. Every other character of the loop's text is
// shown as written. WHY not a markdown library: the loops write one-paragraph prose with code spans; a full renderer
// would reinterpret their `*`, `_` and `[x]` characters (rig T2 has "[SUPERSEDED by round 9: ...]") and hide them.

import { Fragment, type ReactNode } from 'react'

export function Md({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return null
  const parts: ReactNode[] = []
  // Split on code spans first so ** inside code stays literal.
  text.split(/(`[^`\n]+`)/g).forEach((chunk, index) => {
    if (chunk.length > 2 && chunk.startsWith('`') && chunk.endsWith('`')) {
      parts.push(<code key={index}>{chunk.slice(1, -1)}</code>)
      return
    }
    chunk.split(/(\*\*[^*\n]+\*\*)/g).forEach((piece, inner) => {
      if (piece.length > 4 && piece.startsWith('**') && piece.endsWith('**')) parts.push(<strong key={`${index}.${inner}`}>{piece.slice(2, -2)}</strong>)
      else if (piece) parts.push(<Fragment key={`${index}.${inner}`}>{piece}</Fragment>)
    })
  })
  return <span className={className}>{parts}</span>
}
