// Everything a proposal needs, WITHOUT the shell: proposals import from '../kit' (not '../'), so n<k> -> index ->
// NeedsShell -> n<k> never forms an import cycle.
import { useCallback, useLayoutEffect, useState, type RefObject } from 'react'
import { formatLocal } from '../shared/time'
import type { NeedsDoc, NeedsGroup, NeedsItem } from './types'

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
export { StaleDraftNotice } from './StaleDraftNotice'
export { IncludeDefaultingPointer, INCLUDE_DEFAULTING_TITLE } from './SettingsPointer'
export type { StaleDraftNoticeProps } from './StaleDraftNotice'

// ------------------------------------------------------------------------------------------- times

/** A stamp for a hover title: local time with the year and the zone ("2026-10-03 21:25 PDT"), or undefined (no
 * title) when there is none. WHY: hover titles carried the raw ISO ("2026-10-03T04:25:43+00:00"), a second way to
 * read the same moment beside the local stamp it explains, in UTC; every time Zach sees goes through formatLocal. */
export function hoverTime(iso: string | null | undefined): string | undefined {
  return iso ? formatLocal(iso, { year: true }) : undefined
}

// ------------------------------------------------------------------------------------------- the question's words

/** Markdown markup a one-line row cannot draw, rendered to its text: `**bold**` -> bold, `[[target|shown]]` -> shown,
 * `[[target]]` -> target. Every other character is kept. */
export function plainInline(markdown: string): string {
  return markdown
    .replace(/\[\[([^\]|]*)\|([^\]]*)\]\]/g, '$2')
    .replace(/\[\[([^\]]*)\]\]/g, '$1')
    .replace(/\*\*/g, '')
}

/** True when the item's title is only the bold lead of its ask (detection: title "Data.", ask "**Data.** The Seagate
 * ... run `udisksctl mount -b /dev/sdb` yourself."): the title alone then drops the actual question. */
export function askExtendsTitle(item: NeedsItem): boolean {
  const ask = plainInline(item.ask ?? '').trim()
  const title = plainInline(item.title).trim()
  return ask.length > title.length && ask.startsWith(title)
}

/** The question as one row of plain text: the whole ask when the title is only its lead, else the title. Rows clamp it
 * with a visible ellipsis and put it whole in the hover title; the card shows it whole. WHY: detection's rows in N2,
 * N3 and N5 read just "Data." as the question, with the ask itself (mount the Seagate) nowhere in the list. */
export function questionText(item: NeedsItem): string {
  return askExtendsTitle(item) ? plainInline(item.ask) : item.title
}

/** The question as markdown, for a heading that would otherwise show the title alone. */
export function questionMd(item: NeedsItem): string {
  return askExtendsTitle(item) ? item.ask : item.title
}

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

/** Pixels the needs shell keeps free under a framed proposal while the N-chooser pill FLOATS over the frame's
 * bottom-right corner (needs.css): nothing a proposal draws may sit under it. */
export const CHOOSER_RESERVE = 56

/** The reserve once the pill is docked in the dashboard's review bar (`#vt-review-bar`, below the scroll area): the
 * pill covers nothing, so only a calm end margin is kept. */
export const DOCKED_RESERVE = 12

/** The id of the dashboard's review bar (Dashboard.tsx): the strip under the scroll area that holds the pills. */
export const REVIEW_BAR_ID = 'vt-review-bar'

/** The review bar of the dashboard that holds `within`, or null when that dashboard renders none.
 * WHY scoped to the element's own `.vt-dash` and not `document.getElementById`: Clank keeps a second viewer of the same
 * file mounted (a hidden tab, a split), each with its own `#vt-review-bar`; a global lookup portalled BOTH needs pills
 * into the first one, two identical pills side by side in the visible bar. */
export function reviewBarFor(within: Element | null | undefined): HTMLElement | null {
  const dash = within?.closest('.vt-dash')
  return dash ? dash.querySelector<HTMLElement>(`#${REVIEW_BAR_ID}`) : null
}

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
    // WHY re-read on every fit: the bar can mount after the page (a peer's Dashboard.tsx, HMR); the shell re-renders
    // the proposal when it docks, and the scroll area's resize also lands here.
    const keep = reviewBarFor(element) ? Math.min(reserve, DOCKED_RESERVE) : reserve
    const next = Math.max(min, Math.floor(scroller.clientHeight - top - keep))
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
