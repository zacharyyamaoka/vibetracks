// Keyboard focus after the dashboard restores the widget's state from history (Back / Forward). Pure, so it is tested
// with stand-in elements.
//
// WHY (Zach drives this with mouse Back/Forward plus arrow keys): the state comes back (trail, lens, tab, the picked
// rung) but the button that had focus is gone, so document.activeElement is the body and the arrow keys, which the
// board handles on itself, do nothing until a click. The picked card gets focus back so the next arrow press moves on.
// WHY only when focus is on nothing: a restored state must never take focus from an input the user is typing in or from
// another widget, whatever just changed in the URL.

import type { RoadView } from './state'

/** What identifies a view, for telling a state this widget just asked for from one that arrived from outside. */
export const viewKey = (view: RoadView): string => JSON.stringify([view.lens, view.orient, view.card, view.sel, view.tab, view.trail])

interface FocusTarget {
  focus: (options: { preventScroll: boolean }) => void
}

/** True when focus is on nothing: no active element, or only the document body. */
export const focusIsFree = (active: unknown, body: unknown): boolean => active === null || active === undefined || active === body

/** Focus the picked card (without scrolling: the board's own scroll owns the view) when the state was restored from
 * outside, a rung is picked, and focus is free. Returns whether it took focus. */
export function restoreBoardFocus(restored: boolean, sel: string | null, cards: ReadonlyMap<string, FocusTarget>, doc: { activeElement: unknown; body: unknown }): boolean {
  if (!restored || sel === null || !focusIsFree(doc.activeElement, doc.body)) return false
  const card = cards.get(sel)
  if (!card) return false
  card.focus({ preventScroll: true })
  return true
}
