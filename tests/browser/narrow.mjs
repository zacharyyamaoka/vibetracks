// No page of the dashboard scrolls sideways, at a phone and at a desktop, with Clank's left panel open or closed.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/narrow.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (verifier, 2026-10-05): with Clank's left panel open at a 390x844 window the dashboard is 152 px wide,
// and 6 of 14 item/iteration pages scrolled sideways (property rows ~474 px, evidence titles 206 px, a status line that
// would not wrap pushed a 390 px page to 499 px). The fix is one root rule (calm.css: every text may wrap, flex and
// grid children may shrink, property rows stack); this check walks the pages that broke and their siblings.
//
// Pages, in each panel state: home, the five top-level track pages, CAN 12 and CAN 16, and for every track (CAN 12/16
// included) its latest iteration and its "hardest" item (the longest title + status + metrics text, so the widest
// status line or property row the projection holds is the one measured, whichever item that is on the day).
// Per page:
//   1. the page itself does not scroll sideways: .vt-scroll scrollWidth == clientWidth. A wide table scrolling inside
//      its own box (the scorecard, the KPI-changes table) is deliberate and is not the page scrolling;
//   2. nothing in the frame outside the scroller (header, review bar) reaches past the dashboard's edge, where
//      .vt-dash's overflow: hidden would clip it;
//   3. the review bar takes no height off a page that puts nothing in it (the retired A · B · C pill left an empty
//      40 px strip), and no A · B · C switcher exists any more.
// The left panel's state is MEASURED first (where the dashboard starts), then flipped with Clank's own toggle
// (`Toggle left panel`), and flipped back at the end so the lane is left as found. Clank's layout writes are refused
// by _lane.mjs anyway. Then the same walk at 1440x900.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'narrow'
const PHONE = { width: 390, height: 844 }
const DESKTOP = { width: 1440, height: 900 }

const { browser, page } = await openLane(NAME, PHONE)

/** Every page to walk, from the projection the page itself reads. */
async function pagesToWalk() {
  const projection = await page.evaluate(async () => (await fetch('/api/plugins/vibetracks/projection')).json())
  const textOf = (item) =>
    `${item.title ?? ''} ${item.status ?? ''} ${Object.entries(item.metrics ?? {})
      .map(([key, value]) => `${key} ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
      .join(' ')}`
  const pages = [{ label: 'home', hash: 'vt', ready: '[data-testid=vt-a-l1]' }]
  const topLevel = projection.tracks.filter((track) => !track.parent).slice(0, 5)
  const deployments = projection.tracks.filter((track) => ['can12', 'can16'].includes(track.id))
  for (const track of [...topLevel, ...deployments]) {
    const id = encodeURIComponent(track.id)
    pages.push({ label: `track ${track.id}`, hash: `vt?track=${id}`, ready: `[data-testid=vt-a-l2][data-track="${track.id}"]` })
  }
  for (const track of projection.tracks) {
    const id = encodeURIComponent(track.id)
    const latest = track.iterations.at(-1)
    if (latest) {
      pages.push({
        label: `${track.id} iteration ${latest.id}`,
        hash: `vt?track=${id}&iteration=${encodeURIComponent(latest.id)}`,
        ready: `[data-testid=vt-a-l3][data-iteration="${CSS_escape(latest.id)}"]`,
      })
    }
    const items = Object.values(track.evidence?.by_iteration ?? {}).flat()
    const hardest = items.reduce((best, item) => (best && textOf(best).length >= textOf(item).length ? best : item), null)
    if (hardest) {
      pages.push({
        label: `${track.id} item ${hardest.id}`,
        hash: `vt?track=${id}&item=${encodeURIComponent(hardest.id)}`,
        ready: `[data-testid=vt-a-item][data-item="${CSS_escape(hardest.id)}"]`,
      })
    }
  }
  return { pages, topLevel: topLevel.length, deployments: deployments.length }
}

/** CSS.escape for an attribute value in double quotes (Node has no CSS global). */
function CSS_escape(value) {
  return String(value).replace(/["\\]/g, '\\$&')
}

/** Where the dashboard starts: Clank's left panel is open when it takes room to the dashboard's left. */
async function leftPanelOpen() {
  const left = await page.evaluate(() => document.querySelector('[data-testid=vt-dashboard]')?.getBoundingClientRect().left ?? null)
  return { open: left !== null && left > 1, left }
}

async function toggleLeftPanel() {
  await page.getByRole('button', { name: 'Toggle left panel' }).first().click()
  await page.waitForTimeout(400)
}

/** Measure one page once it shows, after its late content (the roadmap) has settled. */
async function measure(entry) {
  await page.evaluate((hash) => {
    location.hash = hash
  }, entry.hash)
  await page.locator(entry.ready).first().waitFor({ timeout: 10000 })
  let previous = -1
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(150)
    const width = await page.evaluate(() => document.querySelector('[data-testid=vt-dashboard] .vt-scroll')?.scrollWidth ?? -1)
    if (width === previous) break
    previous = width
  }
  return page.evaluate(() => {
    const dash = document.querySelector('[data-testid=vt-dashboard]')
    const scroll = dash.querySelector('.vt-scroll')
    const box = dash.getBoundingClientRect()
    const edge = scroll.getBoundingClientRect().right + 0.5
    // The innermost elements that reach past the page's right edge, outside any box that scrolls on its own.
    const ownScroller = (element) => {
      for (let node = element.parentElement; node && node !== scroll; node = node.parentElement) {
        if (/auto|scroll|hidden|clip/.test(getComputedStyle(node).overflowX)) return true
      }
      return false
    }
    const culprits = []
    for (const element of scroll.querySelectorAll('*')) {
      if (ownScroller(element)) continue
      const rect = element.getBoundingClientRect()
      if (!rect.width || rect.right <= edge) continue
      if ([...element.children].some((child) => child.getBoundingClientRect().right > edge)) continue
      culprits.push(`${element.tagName.toLowerCase()}.${String(element.className).trim().replace(/\s+/g, '.')} ${Math.round(rect.width)}px "${(element.textContent ?? '').slice(0, 48)}"`)
    }
    const frameClipped = [...dash.querySelectorAll('.vt-dash-header *, .vt-review-bar *')]
      .filter((element) => {
        const rect = element.getBoundingClientRect()
        return rect.width && (rect.right > box.right + 0.5 || rect.left < box.left - 0.5)
      })
      .map((element) => `${element.tagName.toLowerCase()} "${(element.textContent ?? '').slice(0, 40)}"`)
    const bar = dash.querySelector('[data-testid=vt-review-bar]')
    return {
      scrollWidth: scroll.scrollWidth,
      clientWidth: scroll.clientWidth,
      dashWidth: Math.round(box.width),
      culprits: culprits.slice(0, 4),
      frameClipped,
      barHeight: bar ? bar.getBoundingClientRect().height : null,
      scrollerReachesBottom: Math.abs(scroll.getBoundingClientRect().bottom - box.bottom) < 1,
      switchers: dash.querySelectorAll('[data-testid=vt-switcher], [data-testid=vt-switch-pill]').length,
    }
  })
}

async function walk(pages, state) {
  for (const entry of pages) {
    let result
    try {
      result = await measure(entry)
    } catch (error) {
      check(false, `${state} · ${entry.label}: the page showed (${error instanceof Error ? error.message.split('\n')[0] : error})`)
      continue
    }
    const where = `${state} (dashboard ${result.dashWidth} px) · ${entry.label}`
    check(
      result.scrollWidth === result.clientWidth,
      `${where}: no sideways scroll (scrollWidth ${result.scrollWidth} == clientWidth ${result.clientWidth})${result.culprits.length ? ` past the edge: ${result.culprits.join('; ')}` : ''}`,
    )
    if (result.frameClipped.length) check(false, `${where}: header / review bar inside the dashboard (clipped: ${result.frameClipped.join('; ')})`)
    if (result.barHeight !== 0 || !result.scrollerReachesBottom || result.switchers !== 0) {
      check(false, `${where}: no empty review bar and no A · B · C switcher (bar ${result.barHeight} px, scroller to the bottom ${result.scrollerReachesBottom}, switchers ${result.switchers})`)
    }
  }
}

let initial = null
try {
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-a-l1]').waitFor({ timeout: 15000 })
  const { pages, topLevel, deployments } = await pagesToWalk()
  check(topLevel === 5 && deployments === 2, `the projection has the five track pages and CAN 12/16 to walk (${topLevel} + ${deployments})`)
  console.log(`walking ${pages.length} pages per state`)

  initial = await leftPanelOpen()
  console.log(`measured at 390x844: the dashboard starts at x=${initial.left}, so Clank's left panel is ${initial.open ? 'open' : 'closed'}`)
  await walk(pages, `390 · panel ${initial.open ? 'open' : 'closed'}`)

  await toggleLeftPanel()
  const flipped = await leftPanelOpen()
  check(flipped.open !== initial.open, `Clank's own toggle flipped the left panel (${initial.open ? 'open' : 'closed'} -> ${flipped.open ? 'open' : 'closed'})`)
  if (flipped.open !== initial.open) await walk(pages, `390 · panel ${flipped.open ? 'open' : 'closed'}`)
  // Restore the panel as found before anything else can fail.
  if ((await leftPanelOpen()).open !== initial.open) await toggleLeftPanel()
  check((await leftPanelOpen()).open === initial.open, `the left panel is back as found (${initial.open ? 'open' : 'closed'})`)

  await page.setViewportSize(DESKTOP)
  await page.waitForTimeout(400)
  await walk(pages, `1440 · panel ${initial.open ? 'open' : 'closed'}`)

  // The needs page is the one page that puts a pill in the review bar: the bar keeps its height there.
  await page.setViewportSize(PHONE)
  await page.evaluate(() => {
    location.hash = 'vt?track=kinsim&needs=1'
  })
  await page.locator('[data-testid=vt-needs-switcher]').first().waitFor({ timeout: 10000 })
  const needsBar = await page.evaluate(() => {
    const bar = document.querySelector('[data-testid=vt-dashboard] [data-testid=vt-review-bar]')
    return { height: bar?.getBoundingClientRect().height ?? null, pill: Boolean(bar?.querySelector('[data-testid=vt-needs-switcher]')) }
  })
  check(needsBar.height > 0 && needsBar.pill, `the needs page keeps the review bar for its pill (${needsBar.height} px, pill docked ${needsBar.pill})`)
} catch (error) {
  check(false, `the walk ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  try {
    if (initial && (await page.viewportSize())?.width !== PHONE.width) await page.setViewportSize(PHONE)
    if (initial && (await leftPanelOpen()).open !== initial.open) await toggleLeftPanel()
  } catch {
    // The browser is closing anyway; the lane's saved layout was never written (Clank's writes are refused).
  }
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
