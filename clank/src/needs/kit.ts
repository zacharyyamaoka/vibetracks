// Everything a proposal needs, WITHOUT the shell: proposals import from '../kit' (not '../'), so n<k> -> index ->
// NeedsShell -> n<k> never forms an import cycle.
import { useCallback, useLayoutEffect, useState, type RefObject } from 'react'
import type { NeedsDoc, NeedsGroup } from './types'

export * from './types'
export * from './api'
export * from './answers'
export * from './exportAnswers'
export type { NeedsProposalProps, NeedsProposalDefinition } from './proposal'
export { CopyOut } from './CopyOut'
export type { CopyOutProps } from './CopyOut'
export { EvidenceLink, evidenceHref } from './EvidenceLink'
export type { EvidenceLinkProps } from './EvidenceLink'
export { PlaceholderList } from './PlaceholderList'

// ------------------------------------------------------------------------------------------- the header's numbers

/** One track's (or the sum of several tracks') header numbers, from the ONE source (vibetracks/dashboard/needs.py). */
export interface HeaderCounts {
  /** `counts.blocking_now`: the B of "B blocking · M open". */
  blocking: number
  /** `counts.wants_you`: the M of "B blocking · M open" (groups blocking + no_default + waiting). */
  open: number
  /** `open` split so every item is counted exactly once, by its group: blocking now, then waiting with no default,
   * then default pending. The three always sum to `open`. */
  parts: { blocking: number; noDefault: number; waiting: number }
  /** Open, but the default is already in effect: not part of `open`. */
  defaulting: number
}

function groupCount(doc: NeedsDoc, group: NeedsGroup): number {
  return doc.items.filter((item) => item.group === group).length
}

/** A track's header numbers, or null when its doc reports none ("not reported", never 0: show notReportedText).
 *
 * WHY the parts come from the item groups and never from `counts.no_default`: needs.py's `no_default` also counts
 * blocking items that have no default (rig T2 and T14), so "2 blocking now · 4 no default · 2 default pending" summed
 * to 8 against 6 open. The groups are disjoint by construction, so the parts always sum to `wants_you`. */
export function headerCounts(doc: NeedsDoc): HeaderCounts | null {
  const counts = doc.counts
  if (typeof counts.blocking_now !== 'number' || counts.wants_you === null) return null
  const parts = { blocking: groupCount(doc, 'blocking'), noDefault: groupCount(doc, 'no_default'), waiting: groupCount(doc, 'waiting') }
  // `wants_you` is the contract field; only a backend from before it existed omits it, and then the same groups count.
  const open = typeof counts.wants_you === 'number' ? counts.wants_you : parts.blocking + parts.noDefault + parts.waiting
  return { blocking: counts.blocking_now, open, parts, defaulting: groupCount(doc, 'defaulting') }
}

export interface HeaderSummary {
  /** The sum over the reported tracks, or null when none of them reports numbers. */
  counts: HeaderCounts | null
  reported: NeedsDoc[]
  /** Tracks with no structured source: name them, never add them in as 0. */
  notReported: NeedsDoc[]
}

/** Several tracks' header numbers (the every-track page): reported ones summed, the rest listed as not reported. */
export function headerSummary(docs: NeedsDoc[]): HeaderSummary {
  const reported: NeedsDoc[] = []
  const notReported: NeedsDoc[] = []
  let sum: HeaderCounts | null = null
  for (const doc of docs) {
    const counts = headerCounts(doc)
    if (!counts) {
      notReported.push(doc)
      continue
    }
    reported.push(doc)
    sum = sum
      ? {
          blocking: sum.blocking + counts.blocking,
          open: sum.open + counts.open,
          parts: {
            blocking: sum.parts.blocking + counts.parts.blocking,
            noDefault: sum.parts.noDefault + counts.parts.noDefault,
            waiting: sum.parts.waiting + counts.parts.waiting,
          },
          defaulting: sum.defaulting + counts.defaulting,
        }
      : counts
  }
  return { counts: sum, reported, notReported }
}

/** "Not reported: <the doc's own note>". WHY the note verbatim: it says where the questions actually live (pyblocks:
 * "No loop running ..."); a bare "nothing waiting" would claim an all-clear nobody measured. */
export function notReportedText(doc: NeedsDoc): string {
  return `Not reported: ${doc.source.note ?? 'This track has no needs-you source.'}`
}

// ------------------------------------------------------------------------------------------- layout

/** Pixels the needs shell keeps free under a framed proposal: the N-chooser pill floats over the frame's bottom-right
 * corner (needs.css), and nothing a proposal draws may sit under it. */
export const CHOOSER_RESERVE = 56

/** Fit `root` to the rest of the dashboard's scroll area (`.vt-scroll`), less `reserve` px at the bottom, so its own
 * panes scroll inside it. Returns the height to set, or null before the first measure.
 *
 * WHY proposals frame themselves instead of using `position: sticky`: a sticky bar on the page's scroller covers the
 * card that scrolls under it (measured at max scroll, 1440x900: N3's review bar over kinsim T54's head, N4's stack
 * over option 1). A bar outside the pane that scrolls never overlaps anything. */
export function useFitToScroller(root: RefObject<HTMLElement | null>, reserve: number = CHOOSER_RESERVE, min = 360): number | null {
  const [height, setHeight] = useState<number | null>(null)
  // Reads root.current on every call: a proposal swaps its root element (loading -> page), and a measure of the
  // detached one would read 0.
  const fit = useCallback(() => {
    const element = root.current
    const scroller = element?.closest('.vt-scroll') as HTMLElement | null
    if (!element || !scroller) return
    const top = element.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
    const next = Math.max(min, Math.floor(scroller.clientHeight - top - reserve))
    setHeight((previous) => (previous === next ? previous : next))
  }, [root, reserve, min])
  // After every render (cheap; an unchanged height sets nothing), plus whenever the scroll area resizes.
  useLayoutEffect(() => fit())
  useLayoutEffect(() => {
    const scroller = root.current?.closest('.vt-scroll') as HTMLElement | null
    if (!scroller) return
    const observer = new ResizeObserver(fit)
    observer.observe(scroller)
    return () => observer.disconnect()
  }, [root, fit])
  return height
}
