// Card art (Zach, Oct 3: "show icons or something like Factorio... if it's multi robot show the rendering of the
// multi robot"). A render only where the rung's `cell` (kinsim's `x.cell` in the roadmap document) names a catalog
// asset the backend serves from its art dir (GET /roadmap/art); everything else is an illustrative lucide icon, never a
// picture that claims to show something the data does not name. Ported from the kinsim dashboard (src/roadmap/art.tsx).

import {
  Activity, Aperture, Bot, Box, Boxes, BrainCircuit, Camera, ChartLine, ChevronsRight, ClipboardList, Cpu, Crosshair,
  Cylinder, Database, Factory, Film, Gauge, GitCommitHorizontal, GitCompare, Layers, LayoutDashboard, LayoutGrid, List,
  Lock, type LucideIcon, Moon, MoveHorizontal, NotebookTabs, Orbit, PencilRuler, Recycle, Repeat, Rotate3d, RotateCcw,
  Ruler, Scale, Scan, ScanEye, Shapes, ShieldCheck, Sigma, Target, Timer, Users,
} from 'lucide-react'
import { badgeFontSize } from './artBadge'
import type { RoadRung } from './graph'

const AXIS_ICON: Record<string, LucideIcon> = {
  robots: Bot, objects: Box, scene: Factory, grasping: Crosshair, multi_robot: Users, belt: Gauge, eval: Ruler,
  regression: Repeat, visualization: ChartLine,
}
const RUNG_ICON: Record<string, LucideIcon> = {
  OB1: Box, OB2: Cylinder, OB3: Shapes, OB4: Boxes, OB5: Recycle, SN2: ChevronsRight, SN3: LayoutGrid, SN4: Factory,
  SN5: Layers, SN6: Gauge, GP0: Crosshair, GP1: Rotate3d, GP7: Target, GP2: MoveHorizontal, GP3: Scan, GP4: ScanEye,
  GP5: BrainCircuit, GP6: Camera, MR0: Bot, MR2: Bot, MR3: Scale, MR4: Timer, BT5: Gauge, EV0: List, EV1: ClipboardList,
  EV2: Timer, EV3: ShieldCheck, EV4: Ruler, EV5: Sigma, EV6: Cpu, EV7: Database, RG0: PencilRuler,
  RG1: GitCommitHorizontal, RG2: NotebookTabs, RG3: Layers, RG4: Lock, RG5: Moon, VZ0: RotateCcw, VZ1: LayoutDashboard,
  VZ2: Film, VZ3: ChartLine, VZ4: Orbit, VZ5: GitCompare, VZ6: ScanEye, CS2: Activity, CM2: Aperture,
}

export interface Art {
  renders: string[]
  count: number
  badge: string | null
  Icon: LucideIcon
  caption: string
}

const CATALOG_ROBOTS = new Set(['cartesian_linear', 'ur5e_robotiq', 'ur5e_crab_claw', 'bam_fb_crab_claw'])

/** What a rung's card shows; `available` = the art files the backend lists (GET /roadmap/art). */
export function artFor(rung: RoadRung, available: ReadonlySet<string>): Art {
  const cell = (rung.rung.x?.cell ?? {}) as { robot?: string; robot_count?: number; scene?: string; belt_speed_m_s?: number | null }
  const Icon = RUNG_ICON[rung.id] ?? AXIS_ICON[rung.axis] ?? Box
  const has = (name: string) => available.has(`${name}.png`)
  const robot = typeof cell.robot === 'string' ? /^(?:(\d+)x\s+)?([a-z0-9_]+)$/.exec(cell.robot) : null
  if (rung.axis === 'belt' && cell.scene && typeof cell.belt_speed_m_s === 'number' && has('scene_v9_workcell')) {
    return { renders: ['scene_v9_workcell'], count: 1, badge: cell.belt_speed_m_s === 0 ? 'static' : `${cell.belt_speed_m_s} m/s`, Icon, caption: 'v9 workcell (catalog render); badge = the cell’s belt speed' }
  }
  if (robot && CATALOG_ROBOTS.has(robot[2]) && (rung.axis === 'robots' || rung.axis === 'multi_robot') && has(`robot_${robot[2]}`)) {
    const count = Number(robot[1] ?? 1)
    return { renders: [`robot_${robot[2]}`], count, badge: count > 1 ? `×${count}` : null, Icon, caption: `${robot[2]} (catalog render)${count > 1 ? `, drawn ${count}× for a ${count}-robot cell: composed, not simulated together` : ''}` }
  }
  if (cell.robot === 'any mix' && has('robot_ur5e_robotiq') && has('robot_bam_fb_crab_claw')) {
    return { renders: ['robot_ur5e_robotiq', 'robot_bam_fb_crab_claw'], count: 3, badge: 'N×', Icon, caption: 'UR5e and BAM FB catalog renders composed: any mix of N stations' }
  }
  if (rung.axis === 'scene' && typeof cell.scene === 'string' && cell.scene.startsWith('v9_workcell') && has('scene_v9_workcell')) {
    return { renders: ['scene_v9_workcell'], count: 1, badge: null, Icon, caption: 'v9 workcell (catalog render)' }
  }
  if (rung.id === 'OB0' && has('parcels')) return { renders: ['parcels'], count: 1, badge: null, Icon, caption: 'the four catalog parcels (real sizes, viewer colours)' }
  const count = typeof cell.robot_count === 'number' ? cell.robot_count : 1
  return { renders: [], count: 1, badge: count > 1 ? `×${count}` : null, Icon, caption: 'illustrative icon' }
}

/** The URL of one art file, `name` with its `.png` (GET /roadmap/art/<name>). */
export const artUrl = (artBase: string, name: string) => `${artBase}/${encodeURIComponent(name)}`

/** The art itself: overlapping renders for an N-robot cell, else the icon. */
export function ArtView({ art, size, artBase, className }: { art: Art; size: number; artBase: string; className?: string }) {
  const n = Math.min(art.renders.length ? art.count : 1, 4)
  const step = n > 1 ? (size * 0.42) / (1 + (n - 1) * 0.42) : 0
  const imageWidth = n > 1 ? size / (1 + (n - 1) * 0.42) : size
  // WHY the badge is sized to the box, and dropped (into the title) when it cannot fit: see artBadge.ts.
  const badgeSize = art.badge ? badgeFontSize(art.badge, size) : null
  const dropped = art.badge !== null && badgeSize === null
  const title = art.badge ? `${art.caption} · ${art.badge}` : undefined
  return (
    <span
      className={`vt-rm-art ${className ?? ''}`}
      style={{ width: size, height: size * 0.75 }}
      title={title}
      {...(dropped ? { role: 'img', 'aria-label': title } : {})}
    >
      {art.renders.length
        ? Array.from({ length: n }, (_, i) => (
            <img
              key={i}
              alt=""
              draggable={false}
              src={artUrl(artBase, `${art.renders[i % art.renders.length]}.png`)}
              style={{ width: imageWidth, left: i * step, top: i * 3 }}
            />
          ))
        : <art.Icon aria-hidden className="vt-rm-art-icon" style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={1.7} />}
      {art.badge && badgeSize !== null ? <b className="vt-rm-art-badge" style={{ fontSize: badgeSize, lineHeight: `${Math.ceil(badgeSize + 3)}px` }}>{art.badge}</b> : null}
    </span>
  )
}
