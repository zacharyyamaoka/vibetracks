// The roadmap's swimlane board (Zach picked it Oct 3: "the Lens Bar and the zoom card thing... more compact and fast to
// use"). One set of cards; the lens bar re-arranges them (Ladder · Depth · Now·Next·Later · Waves), the direction and
// the card size change how they are drawn, and the SAME card elements glide to their new places so every lens reads as
// a view of one board. Click a card: its lineage lights and the card grows into the focus panel.
// Ported from the kinsim dashboard (src/roadmap/RoadmapBoard.tsx @ 69e91af) into the calm vt-* language (roadmap.css);
// its state is controlled by the dashboard (state.ts), so every change goes out through `onView`.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { type Art, ArtView } from './art'
import { type Direction, type Geometry, type RoadModel, type RoadRung, buckets, edgeKey, edgePath, firstRung, layout, neighbour, place } from './graph'
import { PANEL_RESERVE, boardContentWidth, scrollToReveal } from './scroll'
import type { EdgeStyle } from './settings'
import type { RoadView } from './state'

const CARD = { compact: { w: 56, h: 22 }, rich: { w: 120, h: 88 } }
const GLIDE_MS = 460

export const KEYS_HINT = ' · arrow keys move between rungs, Esc closes'

export const LENS_CAPTION: Record<RoadView['lens'], string> = {
  ladder: 'Authored rung order, one row per axis: the compact view. Lines appear for the rung you pick.',
  depth: 'x = dependency depth: rungs in one column can be climbed in parallel; a fork opens a second row.',
  board: 'The same lanes by distance from climbable. Ready = every prerequisite proven and no triage block; Next = one promotion or one triage answer away.',
  waves: 'x = the wave the roadmap plans for each rung (only as good as the estimates).',
}

const cx = (...names: Array<string | false | null | undefined>) => names.filter(Boolean).join(' ')

function Segmented<T extends string>({ value, options, onChange, testid, label }: { value: T; options: Array<[T, string, string?]>; onChange: (next: T) => void; testid: string; label: string }) {
  return (
    <div role="group" aria-label={label} data-testid={testid} className="vt-rm-seg">
      {options.map(([key, text, title]) => (
        <button key={key} type="button" className="vt-btn" title={title} aria-pressed={value === key} data-value={key} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  )
}

/** Lens, direction and card size: navigation, not settings (the line style lives on the settings page). */
export function LensBar({ view, onView, hasWaves }: { view: RoadView; onView: (next: Partial<RoadView>) => void; hasWaves: boolean }) {
  return (
    <div className="vt-rm-lensbar">
      <Segmented testid="vt-roadmap-lens" label="Lens" value={view.lens} onChange={(lens) => onView({ lens })} options={[
        ['ladder', 'Ladder', 'authored rung order: the compact view'],
        ['depth', 'Depth', 'dependency depth: parallel rungs share a column'],
        ['board', 'Now · Next · Later', 'distance from climbable'],
        ...(hasWaves ? [['waves', 'Waves', 'the planned wave of each rung'] as ['waves', string, string]] : []),
      ]} />
      <Segmented testid="vt-roadmap-orient" label="Direction" value={view.orient} onChange={(orient) => onView({ orient })} options={[['lr', '→', 'left to right'], ['td', '↓', 'top down']]} />
      <Segmented testid="vt-roadmap-card" label="Card size" value={view.card} onChange={(card) => onView({ card })} options={[['compact', 'Compact'], ['rich', 'Rich']]} />
    </div>
  )
}

/** The word each status reads as; `claimed` says whose word it is. */
export const STATUS_WORD: Record<string, string> = {
  green: 'green', done: 'done', claimed: 'claimed', partial: 'partial', stale: 'stale', missing: 'missing', unknown: 'unknown',
}

export function Legend() {
  return (
    <span className="vt-rm-legend" data-testid="vt-roadmap-legend">
      {(['green', 'done', 'claimed', 'partial', 'stale', 'missing'] as const).map((status) => (
        <span key={status} title={status === 'claimed' ? 'the loop says green; its evidence does not prove it' : status === 'stale' ? 'proven once; something it rests on has changed since' : undefined}>
          <Dot status={status} />{STATUS_WORD[status]}
        </span>
      ))}
      <span><span className="vt-rm-legend-frontier" />frontier</span>
      <span><span className="vt-rm-legend-triage" />triage</span>
      <span className="vt-rm-needs">needs</span>
      <span className="vt-rm-unlocks">unlocks</span>
    </span>
  )
}

/** One status mark. WHY these shapes (colour only for exceptions): proven green is a filled green dot and the loop's
 * unproven green (claimed) the same green hollow, so the difference reads at a glance without a new colour; done is
 * filled ink, partial half-filled ink, stale the calm stale tone, missing a faint ring. */
export function Dot({ status }: { status: string }) {
  return <span aria-hidden className="vt-rm-dot" data-status={status in STATUS_WORD ? status : 'unknown'} />
}

function geometryFor(model: RoadModel, view: RoadView): Geometry {
  const size = CARD[view.card]
  const rich = view.card === 'rich'
  return place(model, layout(model, view.lens === 'waves' && !model.hasWaves ? 'depth' : view.lens), view.orient === 'td'
    ? { orient: 'td', cellW: size.w, cellH: size.h, gapAcross: rich ? 26 : 14, gapWithin: rich ? 10 : 6, laneGap: 6, label: 58, head: 44, pad: 6 }
    : { orient: 'lr', cellW: size.w, cellH: size.h, gapAcross: rich ? 30 : 12, gapWithin: rich ? 8 : 5, laneGap: 4, label: 168, head: 24, pad: 6 })
}

export function RoadmapBoard({ model, view, edges, onPick, onStep, art, artBase, cardLine, cardRef }: {
  model: RoadModel
  view: RoadView
  edges: EdgeStyle
  onPick: (id: string | null) => void
  onStep: (id: string) => void
  art: (id: string) => Art
  artBase: string
  cardLine: (rung: RoadRung) => string
  cardRef: (id: string, element: HTMLElement | null) => void
}) {
  const geo = useMemo(() => geometryFor(model, view), [model, view.lens, view.orient, view.card])
  const quiet = view.lens === 'ladder' || view.lens === 'board'
  // WHY edges wait for the glide: lines drawn for the new layout point at where cards are going, not where they are.
  const [moving, setMoving] = useState(false)
  const layoutKey = `${view.lens}|${view.orient}|${view.card}`
  const firstLayout = useRef(true)
  useEffect(() => {
    if (firstLayout.current) { firstLayout.current = false; return }
    setMoving(true)
    const timer = window.setTimeout(() => setMoving(false), GLIDE_MS)
    return () => window.clearTimeout(timer)
  }, [layoutKey])

  const sel = view.sel && model.byId.has(view.sel) ? view.sel : null
  const up = sel ? model.up.get(sel)! : null
  const down = sel ? model.down.get(sel)! : null
  const scroller = useRef<HTMLDivElement>(null)
  // Drag to pan (Zach, Oct 3: "more natural sometimes than side to side scrolling"). A press that moves more than a
  // few pixels pans the board and swallows the click it would have been, so dragging from a card never picks it.
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean; pointer: number } | null>(null)
  const [panning, setPanning] = useState(false)
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !scroller.current) return
    drag.current = { x: event.clientX, y: event.clientY, left: scroller.current.scrollLeft, top: scroller.current.scrollTop, moved: false, pointer: event.pointerId }
  }
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current
    if (!state || !scroller.current || event.pointerId !== state.pointer) return
    // WHY (Codex B05): a press that left the board before the 5 px threshold and was released outside never reaches
    // pointerup here, so the pending drag outlived it and re-entering with no button held panned. The button state on
    // the move is the truth; trust it over the missed release.
    if ((event.buttons & 1) === 0) {
      drag.current = null
      setPanning(false)
      return
    }
    const dx = event.clientX - state.x
    const dy = event.clientY - state.y
    if (!state.moved && Math.abs(dx) + Math.abs(dy) < 5) return
    if (!state.moved) {
      state.moved = true
      setPanning(true)
      scroller.current.setPointerCapture(event.pointerId)
    }
    scroller.current.scrollLeft = state.left - dx
    scroller.current.scrollTop = state.top - dy
  }
  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (drag.current?.moved && scroller.current?.hasPointerCapture(event.pointerId)) scroller.current.releasePointerCapture(event.pointerId)
    setPanning(false)
    // Keep `moved` until the click that ends this press has been swallowed below.
    window.setTimeout(() => { drag.current = null }, 0)
  }

  // WHY arrow keys (Zach, Oct 3: "arrow keys between rungs: the selection moves and the view follows"): the selection
  // moves through graph.neighbour and the selection-scroll below carries the view; DOM focus follows the card so the
  // next press starts from it, without scrolling by itself (preventScroll) because the smooth scroll owns the view.
  const ARROWS: Record<string, Direction> = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return
    if (event.key === 'Escape') {
      if (!sel) return
      event.preventDefault()
      onPick(null)
      return
    }
    const dir = ARROWS[event.key]
    if (!dir) return
    event.preventDefault()
    const next = sel ? neighbour(model, geo, sel, dir) : firstRung(model, geo)
    if (!next) return
    onStep(next)
    scroller.current?.querySelector<HTMLElement>(`[data-rung="${CSS.escape(next)}"]`)?.focus({ preventScroll: true })
  }

  // Focus: bring the picked card clear of the focus panel (not merely into view). WHY (Codex I02, and Zach's arrow-key
  // ask "the selection moves and the view follows"): the panel overlays the board's right PANEL_RESERVE px and the
  // content used to be only as wide as the board, so a card near the right edge had no scroll room and stayed under
  // it; the content now carries PANEL_RESERVE of trailing space while a rung is picked (see the inner div's width).
  useLayoutEffect(() => {
    if (!sel || !scroller.current) return
    const box = geo.nodes.get(sel)
    if (!box) return
    const element = scroller.current
    const target = scrollToReveal(box, { left: element.scrollLeft, top: element.scrollTop, width: element.clientWidth, height: element.clientHeight }, PANEL_RESERVE)
    if (target.left !== element.scrollLeft || target.top !== element.scrollTop) element.scrollTo({ ...target, behavior: 'smooth' })
  }, [sel, geo])

  return (
    <div
      ref={scroller}
      data-testid="vt-roadmap-canvas"
      data-panning={panning || undefined}
      className={cx('vt-rm-canvas', panning && 'vt-rm-panning')}
      tabIndex={0}
      aria-label="Roadmap rungs"
      aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Escape"
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onClickCapture={(event) => { if (drag.current?.moved) { event.stopPropagation(); event.preventDefault() } }}
      onClick={(event) => { if (event.target === event.currentTarget || (event.target as Element).closest('[data-roadmap-bg]')) onPick(null) }}
    >
      <div className="vt-rm-content" style={{ width: boardContentWidth(geo.width, Boolean(sel)), height: geo.height }}>
        <svg data-roadmap-bg className="vt-rm-svg" width={geo.width} height={geo.height} aria-hidden>
          {geo.lanes.map((lane, i) => {
            const rungs = model.rungs.filter((r) => r.axis === lane.axis.id)
            const proven = rungs.filter((r) => r.status === 'green' || r.status === 'done').length
            const band = geo.orient === 'lr' ? { x: 0, y: lane.start, width: geo.width, height: lane.size } : { x: lane.start, y: 0, width: lane.size, height: geo.height }
            return (
              <g key={lane.axis.id}>
                {i % 2 === 0 ? <rect {...band} className="vt-rm-band" /> : null}
                {geo.orient === 'lr' ? (
                  <>
                    <text x={10} y={lane.start + 17} className="vt-rm-lane-title"><title>{lane.axis.title}</title>{fitText(lane.axis.title, 150 / 6.6)}</text>
                    <text x={10} y={lane.start + 30} className="vt-rm-lane-sub">{proven} of {rungs.length} proven</text>
                  </>
                ) : (
                  <>
                    <text x={lane.start + 6} y={16} className="vt-rm-lane-title"><title>{lane.axis.title}</title>{fitText(lane.axis.title, lane.size / 6.6)}</text>
                    <text x={lane.start + 6} y={30} className="vt-rm-lane-sub">{proven}/{rungs.length}</text>
                  </>
                )}
              </g>
            )
          })}
          {geo.heads.map((head) => geo.orient === 'lr'
            ? <text key={head.at} x={head.a + head.len / 2} y={15} textAnchor="middle" className={cx('vt-rm-head', head.bucket === 'ready' && 'vt-rm-head-ready')}>{head.label}</text>
            : <text key={head.at} x={52} y={head.a + (head.span > 1 ? head.len / 2 : CARD[view.card].h / 2)} textAnchor="end" dominantBaseline="middle" className="vt-rm-head">{head.bucket ? head.label.split(' · ')[0] : head.label}</text>)}
          <g className={cx('vt-rm-edges', moving && 'vt-rm-moving')}>
            {model.edges.map((edge) => {
              const key = edgeKey(edge)
              const isUp = Boolean(sel && up && (edge.to === sel || up.has(edge.to)) && up.has(edge.from))
              const isDown = Boolean(sel && down && (edge.from === sel || down.has(edge.from)) && down.has(edge.to))
              if (quiet && !isUp && !isDown) return null
              const cycle = model.feedback.has(key)
              const sameAxis = model.byId.get(edge.from)!.axis === model.byId.get(edge.to)!.axis
              return (
                <path
                  key={key}
                  data-edge={key}
                  d={edgePath(geo, edge, edges)}
                  fill="none"
                  strokeDasharray={edge.kind === 'same' ? '2 3' : cycle ? '5 3' : undefined}
                  data-role={isUp ? 'up' : isDown ? 'down' : cycle ? 'cycle' : sameAxis ? 'lane' : 'across'}
                  className={cx('vt-rm-edge', sel && !isUp && !isDown && 'vt-rm-edge-dim')}
                >
                  {cycle ? <title>{`cycle: ${edge.from} → ${edge.to} closes a loop; dropped from layering`}</title> : null}
                </path>
              )
            })}
          </g>
        </svg>
        {model.rungs.map((rung) => {
          const box = geo.nodes.get(rung.id)!
          const role = rung.id === sel ? 'sel' : up?.has(rung.id) ? 'up' : down?.has(rung.id) ? 'down' : sel ? 'dim' : 'rest'
          const proven = rung.status === 'green' || rung.status === 'done'
          return (
            <button
              key={rung.id}
              ref={(element) => cardRef(rung.id, element)}
              type="button"
              data-testid={`vt-rung-${rung.id}`}
              data-rung={rung.id}
              data-role={role}
              data-status={rung.status}
              title={`${rung.id} · ${rung.title} — ${rung.status}${rung.status === 'claimed' ? ` (the loop says ${rung.rung.claimed_status})` : ''}${rung.frontier ? ' · frontier' : ''}${rung.triage.length ? ` · blocked by triage ${rung.triage.join(', ')}` : ''}`}
              onClick={(event) => { event.stopPropagation(); onPick(rung.id === sel ? null : rung.id) }}
              className={cx('vt-btn vt-rm-card', proven && 'vt-rm-card-proven', rung.frontier && 'vt-rm-card-frontier')}
              style={{ width: box.w, height: box.h, transform: `translate(${box.x}px, ${box.y}px)${role === 'sel' ? ' scale(1.1)' : ''}` }}
            >
              {rung.triage.length ? <span aria-hidden className="vt-rm-triage" /> : null}
              {view.card === 'compact' ? (
                <span className="vt-rm-card-compact"><Dot status={rung.status} />{rung.id}</span>
              ) : (
                <span className="vt-rm-card-rich">
                  <ArtView art={art(rung.id)} size={52} artBase={artBase} className="vt-rm-card-art" />
                  <span className="vt-rm-card-name"><b>{rung.id}</b><span>{rung.title}</span></span>
                  <span className="vt-rm-card-line"><Dot status={rung.status} /><span title={rung.rung.status_reason}>{cardLine(rung)}</span></span>
                </span>
              )}
            </button>
          )
        })}
      </div>
      <span className="vt-rm-sr">{`${[...buckets(model).values()].filter((b) => b === 'ready').length} rungs are ready now`}</span>
    </div>
  )
}

/** Constrained geometry abbreviates with an explicit ellipsis; the full text stays one hover away (title). */
export function fitText(text: string, chars: number): string {
  return text.length <= chars ? text : `${text.slice(0, Math.max(1, Math.floor(chars) - 1))}…`
}
