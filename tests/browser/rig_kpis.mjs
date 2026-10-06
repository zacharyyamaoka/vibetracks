// The rig track page leads with Zach's robot KPIs, folds the loop's own numbers, and shows the KPI table and the Rerun
// playbacks, measured on the REAL dashboard of a running lane (KPI-VIEW brief, "Rig track page acceptance", 2026-10-06).
// Run: node /home/bam/vibetracks-dashboard/tests/browser/rig_kpis.mjs   (SKIPs cleanly without a lane or browser)
//      VT_LANE=http://127.0.0.1:<port>/?vtdash=Agent%20work.vtdash  picks the lane; VT_EXPECT_INPUTS=ok makes a
//      missing KPI table or playback batch a FAIL instead of a checked degraded state; VT_SHOTS=<dir> saves screenshots.
//
// What it pins, at 1440x900 (every number is read from the projection the page itself loaded, so the check holds for
// whatever export the lane reads; the adapter tests pin those numbers against the export fixture):
//   1. Key KPIs: the first six visible rows are the robot KPIs in Zach's order; the north star is real tracking RMS;
//      each robot row's latest cell shows the projection's value through the shared formatter; the loop's six KPIs
//      sit in a "Loop health" group that is collapsed (no row visible), opens on one click (route key kg) and closes.
//   2. "KPIs by deployment, backend and settings": one row per kpi_table row, in order; every KPI cell in kpi_defs
//      order shows value x scale with its unit, "not measured" for a null, "n/a" on a row with an na_reason (whose
//      reason the row shows); each row says its run counts and date range; the stamp names the cache sha and when it
//      was computed; the table scrolls inside its own box, which sits inside the viewport, and the page itself does
//      not scroll sideways.
//   3. "Playbacks (Rerun)": one entry per index.json run (count and order), grouped by session, closed by default;
//      opening a group shows its entries inside the viewport, each with the one-line "<viewer> <rrd>" command and an
//      mp4 link exactly when the projection lists the video.
//   4. Missing inputs: a section whose input is missing says so and shows the command that makes it.
//   5. Links: the KPI doc, the KPI table CSV (when there is one) and the living report.

import { mkdirSync } from 'node:fs'
import { at, check, finish, openLane } from './_lane.mjs'
import { formatValue } from '../../clank/src/shared/model.ts'

const NAME = 'rig_kpis'
const ROBOT = ['real_tracking_rms', 'real_tracking_p95', 'feedback_torque_proxy', 'twin_fidelity_gap', 'floor_real_vs_real', 'days_since_real_run']
const LOOP = ['rungs_green', 'packages_landed', 'audits', 'elapsed_h', 'disk_pct', 'open_questions']
const EXPECT_OK = process.env.VT_EXPECT_INPUTS === 'ok'
const SHOTS = process.env.VT_SHOTS ?? null
const WIDTH = 1440

const { browser, page } = await openLane(NAME, { width: WIDTH, height: 900 })

/** The visible scorecard rows' KPI ids, top to bottom. */
async function visibleKpiRows() {
  return page.$$eval('[data-testid=vt-a-kpis] [data-testid=vt-a-kpi-row]', (rows) =>
    rows.filter((row) => row.checkVisibility() && row.getBoundingClientRect().height > 0).map((row) => row.getAttribute('data-kpi')),
  )
}

async function shot(name) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** The page's own scroller does not scroll sideways (a table scrolling inside its own box is not the page). */
async function pageScroll() {
  return page.evaluate(() => {
    const scroll = document.querySelector('[data-testid=vt-dashboard] .vt-scroll')
    return { scrollWidth: scroll?.scrollWidth ?? -1, clientWidth: scroll?.clientWidth ?? -1 }
  })
}

function expectedCell(row, def) {
  const raw = row.kpis && typeof row.kpis === 'object' ? row.kpis[def.key] : null
  if (typeof raw !== 'number') return row.na_reason ? 'n/a' : 'not measured'
  return formatValue(raw * (typeof def.scale === 'number' ? def.scale : 1), def.unit)
}

try {
  await page.goto(at('vt?track=rig'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-a-l2][data-track="rig"]').waitFor({ timeout: 30000 })
  await page.waitForTimeout(1500)
  const projection = await page.evaluate(async () => (await fetch('/api/plugins/vibetracks/projection')).json())
  const rig = projection.tracks.find((track) => track.id === 'rig')
  check(Boolean(rig), 'the projection has the rig track')

  // ---- 1. Key KPIs: robot first, loop health folded
  check(rig.north_star === 'real_tracking_rms', `the north star is real tracking RMS (${rig.north_star})`)
  const rows = await visibleKpiRows()
  check(JSON.stringify(rows.slice(0, 6)) === JSON.stringify(ROBOT), `the first six visible KPI rows are the robot KPIs in order (${rows.slice(0, 6).join(', ')})`)
  check(!rows.some((id) => LOOP.includes(id)), `no loop KPI row shows while Loop health is folded (visible: ${rows.join(', ')})`)
  const latest = rig.iterations.at(-1)?.id
  for (const id of ROBOT) {
    const kpi = rig.kpis.find((k) => k.id === id)
    const row = page.locator(`[data-testid=vt-a-kpis] [data-testid=vt-a-kpi-row][data-kpi="${id}"]`)
    if (kpi && !kpi.values.some((v) => v.measured)) {
      // Missing input: the row says so in words (the scorecard's one spanning "Not measured in any tick · <why>").
      const never = ((await row.locator('[data-testid=vt-a-never]').textContent({ timeout: 5000 }).catch(() => null)) ?? '').trim()
      const why = kpi.values.find((v) => v.note)?.note ?? '\u0000'
      check(never.includes('Not measured') && never.includes(why), `${id}: with no reading the row says why (${never.slice(0, 120)})`)
      continue
    }
    const value = kpi?.values.find((v) => v.iteration === latest)
    const text = await row.locator('td.vt-a-cell.vt-a-latest .vt-a-val').first().textContent({ timeout: 5000 }).catch(() => null)
    const expected = value && value.measured ? formatValue(value.value, kpi.unit, value.of) : '—'
    check(text?.trim() === expected, `${id}: the latest cell reads the projection's value (${text?.trim()} == ${expected})`)
  }
  const group = page.locator('[data-testid=vt-a-kpi-group][data-group="loop_health"]')
  const toggle = group.locator('[data-testid=vt-a-kpi-group-toggle]')
  const hasToggle = (await group.count()) === 1 && (await toggle.count()) === 1
  check(hasToggle && (await toggle.getAttribute('aria-expanded')) === 'false', 'Loop health is a group that starts folded (aria-expanded false)')
  await shot('rig-kpis-folded')
  if (hasToggle) {
    await toggle.click()
    await page.waitForTimeout(400)
    const opened = await visibleKpiRows()
    check(LOOP.every((id) => opened.includes(id)) && (await toggle.getAttribute('aria-expanded')) === 'true', `one click opens Loop health with its six KPIs (${opened.filter((id) => LOOP.includes(id)).join(', ')})`)
    check(/[?&]kg=loop_health\b/.test(await page.evaluate(() => location.hash)), 'the open group is kept in the route (kg=loop_health)')
    await shot('rig-kpis-loop-health-open')
    await toggle.click()
    await page.waitForTimeout(300)
    check(!(await visibleKpiRows()).some((id) => LOOP.includes(id)), 'a second click folds it again')
  }

  // ---- 2. the KPI table
  const table = rig.kpi_table
  const section = page.locator('[data-testid=vt-a-kpi-table]')
  const hasTable = (await section.count()) === 1
  check(hasTable, 'the page has a "KPIs by deployment, backend and settings" section')
  check(hasTable && (await section.getAttribute('data-state')) === table?.state, `the section shows the projection's state (${table?.state})`)
  if (EXPECT_OK) check(table?.state === 'ok', `VT_EXPECT_INPUTS=ok: the KPI table export is there (${table?.state}: ${table?.message})`)
  if (hasTable && table?.state === 'ok') {
    await section.scrollIntoViewIfNeeded()
    const box = await section.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      const scroller = element.querySelector('[data-testid=vt-a-kpi-table-scroll]')
      const inner = scroller?.getBoundingClientRect()
      return {
        left: rect.left, right: rect.right, width: rect.width, height: rect.height,
        scrollerLeft: inner?.left ?? null, scrollerRight: inner?.right ?? null,
        scrollerOverflow: scroller ? getComputedStyle(scroller).overflowX : null,
        innerWidth: window.innerWidth,
      }
    })
    check(box.width > 0 && box.height > 0, `the table section is visible (${Math.round(box.width)} x ${Math.round(box.height)} px)`)
    check(box.left >= 0 && box.right <= box.innerWidth && box.scrollerRight !== null && box.scrollerRight <= box.innerWidth,
      `the table and its scroll box sit inside the ${box.innerWidth} px viewport (section ${Math.round(box.left)}-${Math.round(box.right)}, box right ${Math.round(box.scrollerRight ?? -1)})`)
    check(box.scrollerOverflow === 'auto' || box.scrollerOverflow === 'scroll', `the table scrolls inside its own box (overflow-x ${box.scrollerOverflow})`)
    const domRows = await page.$$eval('[data-testid=vt-a-kpi-table-row]', (trs) => trs.map((tr) => ({
      period: tr.getAttribute('data-period'),
      deployment: tr.getAttribute('data-deployment'),
      text: tr.textContent ?? '',
      cells: Object.fromEntries([...tr.querySelectorAll('td[data-kpi]')].map((td) => [td.getAttribute('data-kpi'), (td.textContent ?? '').trim()])),
      order: [...tr.querySelectorAll('td[data-kpi]')].map((td) => td.getAttribute('data-kpi')),
    })))
    check(domRows.length === table.rows.length, `one table row per export row (${domRows.length} == ${table.rows.length})`)
    const keys = table.kpi_defs.map((def) => def.key)
    let cellMismatches = []
    let orderMismatches = 0
    table.rows.forEach((row, index) => {
      const dom = domRows[index]
      if (!dom || dom.period !== row.period || dom.deployment !== row.deployment_id) {
        cellMismatches.push(`row ${index}: ${dom?.deployment}/${dom?.period} is not ${row.deployment_id}/${row.period}`)
        return
      }
      if (JSON.stringify(dom.order) !== JSON.stringify(keys)) orderMismatches++
      for (const def of table.kpi_defs) {
        const want = expectedCell(row, def)
        if (dom.cells[def.key] !== want) cellMismatches.push(`${row.period} ${def.key}: ${dom.cells[def.key]} != ${want}`)
      }
      const counts = row.counts ?? {}
      for (const [kind, n] of [['real', counts.real], ['sim', counts.sim]]) {
        if (typeof n === 'number' && n > 0 && !dom.text.includes(`${n} ${kind}`)) cellMismatches.push(`${row.period}: no "${n} ${kind}" run count`)
      }
      if (row.start && !/\d\d-\d\d \d\d:\d\d/.test(dom.text)) cellMismatches.push(`${row.period}: no date range`)
      if (row.na_reason && !dom.text.includes(row.na_reason)) cellMismatches.push(`${row.period}: its na_reason is not shown`)
    })
    const headers = await page.$$eval('[data-testid=vt-a-kpi-table] thead th[data-kpi]', (ths) => ths.map((th) => th.getAttribute('data-kpi')))
    check(JSON.stringify(headers) === JSON.stringify(keys), `the KPI column headers follow kpi_defs order (${headers.join(', ')})`)
    check(orderMismatches === 0, `every row's KPI columns follow kpi_defs order (${keys.length} columns, ${orderMismatches} rows out of order)`)
    check(cellMismatches.length === 0, `every cell is the export's value x scale, "not measured" or "n/a", with run counts, dates and na_reason (${cellMismatches.length} mismatches${cellMismatches.length ? `: ${cellMismatches.slice(0, 4).join('; ')}` : ''})`)
    const naRows = table.rows.filter((row) => row.na_reason).length
    check(naRows > 0 ? (await page.locator('[data-testid=vt-a-kpi-table-na]').count()) === naRows : true, `each na_reason row shows its reason (${naRows})`)
    const stamp = (await page.locator('[data-testid=vt-a-kpi-table-stamp]').textContent()) ?? ''
    const sha = String(table.cache?.sha256 ?? '').slice(0, 8)
    check(Boolean(sha) && stamp.includes(sha) && Boolean(table.generated_label) && stamp.includes(table.generated_label),
      `the stamp names the cache (${sha}) and when it was computed (${table.generated_label})`)
    await shot('rig-kpi-table')
  } else if (hasTable && table) {
    const missing = page.locator('[data-testid=vt-a-kpi-table-missing]')
    check((await missing.count()) === 1 && ((await missing.textContent()) ?? '').includes(table.message ?? '\u0000'), `the missing table says why (${table.message})`)
    if (table.command) check(((await page.locator('[data-testid=vt-a-kpi-table-command]').textContent()) ?? '') === table.command, 'and shows the command that makes it')
  }

  // ---- 3. the playbacks
  const playbacks = rig.playbacks
  const pbSection = page.locator('[data-testid=vt-a-playbacks]')
  const hasPlaybacks = (await pbSection.count()) === 1
  check(hasPlaybacks, 'the page has a "Playbacks (Rerun)" section')
  check(hasPlaybacks && (await pbSection.getAttribute('data-state')) === playbacks?.state, `the section shows the projection's state (${playbacks?.state})`)
  if (EXPECT_OK) check(playbacks?.state === 'ok', `VT_EXPECT_INPUTS=ok: the playback batch is there (${playbacks?.state}: ${playbacks?.message})`)
  if (hasPlaybacks && playbacks?.state === 'ok') {
    const runs = playbacks.groups.flatMap((g) => g.runs)
    const domRuns = await page.$$eval('[data-testid=vt-a-playback]', (trs) => trs.map((tr) => tr.getAttribute('data-run')))
    check(domRuns.length === playbacks.count && runs.length === playbacks.count, `one entry per index.json run (${domRuns.length} == ${playbacks.count})`)
    check(JSON.stringify(domRuns) === JSON.stringify(runs.map((r) => r.run_id)), 'the entries keep the projection order, grouped by session')
    const groups = await page.$$eval('[data-testid=vt-a-playback-group]', (els) => els.map((el) => ({ session: el.getAttribute('data-session'), open: el.open })))
    check(JSON.stringify(groups.map((g) => g.session)) === JSON.stringify(playbacks.groups.map((g) => g.id)), `one group per session (${groups.length})`)
    // WHY checkVisibility and not a box: Chrome lays out a closed <details>' content (content-visibility: hidden), so its
    // rows have boxes while nobody can see them.
    const shownBefore = await page.$$eval('[data-testid=vt-a-playback]', (els) => els.filter((el) => el.checkVisibility()).length)
    check(groups.every((g) => !g.open) && shownBefore === 0, `every group starts closed, no entry shown (57 entries stay scannable; ${shownBefore} shown)`)
    const target = playbacks.groups.find((g) => g.twin_runs > 0) ?? playbacks.groups[0]
    const details = page.locator(`[data-testid=vt-a-playback-group][data-session="${target.id}"]`)
    await details.locator('summary').click()
    await page.waitForTimeout(400)
    await details.scrollIntoViewIfNeeded()
    check(await details.evaluate((el) => el.open === true), `a click opens "${target.label}"`)
    const entries = await details.evaluate((el) => [...el.querySelectorAll('[data-testid=vt-a-playback]')].map((tr) => {
      const rect = tr.getBoundingClientRect()
      return {
        run: tr.getAttribute('data-run'),
        visible: tr.checkVisibility() && rect.height > 0 && rect.width > 0,
        right: rect.right,
        command: tr.querySelector('[data-testid=vt-a-playback-command]')?.textContent ?? null,
        video: Boolean(tr.querySelector('[data-testid=vt-a-playback-video]')),
      }
    }))
    const innerWidth = await page.evaluate(() => window.innerWidth)
    check(entries.length === target.runs.length && entries.every((e) => e.visible && e.right <= innerWidth),
      `opening "${target.label}" shows its ${target.runs.length} entries inside the viewport (${entries.filter((e) => e.visible).length} visible)`)
    const bad = target.runs.filter((run, i) => {
      const dom = entries[i]
      if (!dom || dom.run !== run.run_id) return true
      if (dom.command !== run.command || !run.command?.startsWith(`${playbacks.viewer} `) || !run.command.endsWith(run.rrd)) return true
      return dom.video !== Boolean(run.video)
    })
    check(bad.length === 0, `each entry shows "<viewer> <rrd>" as one line and an mp4 link exactly when the video is listed (${bad.length} wrong)`)
    await shot('rig-playbacks-open')
  } else if (hasPlaybacks && playbacks) {
    const missing = page.locator('[data-testid=vt-a-playbacks-missing]')
    check((await missing.count()) === 1 && ((await missing.textContent()) ?? '').includes(playbacks.message ?? '\u0000'), `the missing playbacks say why (${playbacks.message})`)
    if (playbacks.command) check(((await page.locator('[data-testid=vt-a-playbacks-command]').textContent()) ?? '') === playbacks.command, 'and show the command that makes them')
  }

  // ---- 4. links and the page width
  const links = (await page.locator('.vt-a-links').textContent().catch(() => '')) ?? ''
  check(links.includes('KPI doc') && links.includes('Living report') && (table?.state !== 'ok' || !table.csv || links.includes('KPI table CSV')),
    'the links name the KPI doc, the KPI table CSV and the living report')
  const width = await pageScroll()
  check(width.scrollWidth <= width.clientWidth, `the page itself does not scroll sideways at ${WIDTH} px (scrollWidth ${width.scrollWidth} <= clientWidth ${width.clientWidth})`)
} catch (error) {
  check(false, `the check ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
