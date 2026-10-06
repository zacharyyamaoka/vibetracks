// A deliberately tiny markdown reader for the loops' verbatim text: paragraphs, "- " bullet lines, `code` and
// **bold**. Copied from N3 (not imported) so N1-N5 stay frozen.
// WHY not a markdown library: the loops write only these four forms, and every other character must stay on screen
// exactly as authored (truthful rendering; rig T2 carries "[SUPERSEDED by round 9: ...]", which a full renderer would
// turn into a link). WHY this exists at all: N1 printed the loops' "**" literally, which the judges flagged.
// React elements only, never innerHTML, so a path or a quote in the text can never become markup.

import type { ReactNode } from 'react'

export function Inline({ text }: { text: string | null | undefined }) {
  if (!text) return null
  // Code spans first, so a "**" inside code stays literal.
  const parts = text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)
  return (
    <>
      {parts.map((part, index) => {
        if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
        if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
        return part ? <span key={index}>{part}</span> : null
      })}
    </>
  )
}

/** Block markdown: one <p> per line, consecutive "- " lines as a list. */
export function Md({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return null
  const blocks: ReactNode[] = []
  let bullets: string[] = []
  const flush = () => {
    if (!bullets.length) return
    const items = bullets
    bullets = []
    blocks.push(
      <ul key={`ul${blocks.length}`}>
        {items.map((item, index) => (
          <li key={index}>
            <Inline text={item} />
          </li>
        ))}
      </ul>,
    )
  }
  for (const line of text.split('\n')) {
    if (/^\s*-\s+/.test(line)) {
      bullets.push(line.replace(/^\s*-\s+/, ''))
      continue
    }
    flush()
    if (!line.trim()) continue
    blocks.push(
      <p key={`p${blocks.length}`}>
        <Inline text={line} />
      </p>,
    )
  }
  flush()
  return <div className={`n6-md ${className ?? ''}`}>{blocks}</div>
}
