// Pure scroll arithmetic for the lens board, kept out of RoadmapBoard.tsx so it can be unit-tested without React.

/** Width the focus panel covers on the board's right edge: its 460 px plus the 8 px it sits in from the border, rounded up. */
export const PANEL_RESERVE = 470
/** Clear space kept between a revealed card and the panel (or the viewport's other edges). */
export const REVEAL_MARGIN = 12

export type RevealBox = { x: number; y: number; w: number; h: number }
export type RevealView = { left: number; top: number; width: number; height: number }

/**
 * Where to scroll so `box` sits fully clear of the focus panel, which covers the right `reserve` px of the viewport
 * for its whole height. A box already clear (with a margin) keeps the current position; otherwise it is centred in the
 * clear area. WHY (Codex I02, for Zach's arrow-key ask "the selection moves and the view follows"): "in view" is not
 * enough, a card under the panel is invisible, so the test is against the area LEFT of the panel and the board adds
 * `reserve` px of trailing scroll space while a rung is picked, which is what makes that area reachable at the right edge.
 */
export function scrollToReveal(box: RevealBox, view: RevealView, reserve: number, margin = REVEAL_MARGIN): { left: number; top: number } {
  // WHY the actual clear width and no floor (Codex J01): the old 200 px floor centred a card in a clear area a ~600 px
  // pane does not have (130 px left of the panel), and a 120 px card ended 28 px under the panel though it would fit.
  const clearWidth = Math.max(0, view.width - reserve - margin)
  const clearX = view.left <= Math.max(0, box.x - margin) && box.x + box.w <= view.left + clearWidth
  const clearY = view.top <= Math.max(0, box.y - margin) && box.y + box.h + margin <= view.top + view.height
  // A card wider than the clear area cannot be centred in it: its left edge goes to the view's left edge, so as much of
  // it as possible shows left of the panel.
  const left = box.w > clearWidth ? box.x : box.x + box.w / 2 - clearWidth / 2
  return {
    left: clearX ? view.left : Math.max(0, left),
    top: clearY ? view.top : Math.max(0, box.y + box.h / 2 - view.height / 2),
  }
}

/**
 * The scrollable content width: the board, plus (while a rung is picked) enough trailing room for the focus panel to
 * sit beside the last column, so scrollToReveal can always bring a card at the right edge clear of it. WHY (Codex I02):
 * with the content only as wide as the board, a 786 px board in a 978 px viewport had zero scroll and its last card
 * stayed under the panel.
 */
export function boardContentWidth(boardWidth: number, picked: boolean, reserve = PANEL_RESERVE, margin = REVEAL_MARGIN): number {
  return picked ? boardWidth + reserve + margin : boardWidth
}
