// Shared setup for the headless consumer checks in this folder (rename_fence.mjs, media_switch.mjs).
// Each check drives the REAL dashboard component on a running dev lane, so a regression in the consumer (not only in a
// pure helper) fails it (Codex audit 2026-10-05, round 2 finding 5). Nothing here writes: every request that would
// change the lane (Clank's own layout writes, a rename POST) is intercepted and answered or refused in the browser.
//
// Environment:
//   VT_LANE          the lane URL (default http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash)
//   PLAYWRIGHT_CORE  playwright-core's index.js (default the copy under /home/bam/claude-transcript-viewer)
//   CHROME           the browser binary (default /usr/bin/google-chrome)
// A missing lane, playwright-core or browser is a SKIP (exit 0, with the reason), never a pass and never a crash.

import { existsSync } from 'node:fs'

export const LANE = process.env.VT_LANE ?? 'http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash'
const PLAYWRIGHT = process.env.PLAYWRIGHT_CORE ?? '/home/bam/claude-transcript-viewer/node_modules/playwright-core/index.js'
const CHROME = process.env.CHROME ?? '/usr/bin/google-chrome'

export function skip(name, reason) {
  console.log(`SKIP ${name}: ${reason}`)
  process.exit(0)
}

/** A headless page on the lane, or a SKIP. Clank's own filesystem writes are refused so the check leaves the lane's
 * workspace (layout, panel state) exactly as it found it. */
export async function openLane(name, { width = 1280, height = 900 } = {}) {
  if (!existsSync(PLAYWRIGHT)) skip(name, `playwright-core not found at ${PLAYWRIGHT}`)
  if (!existsSync(CHROME)) skip(name, `no browser at ${CHROME}`)
  try {
    const response = await fetch(LANE, { signal: AbortSignal.timeout(4000) })
    if (!response.ok) skip(name, `lane answered HTTP ${response.status} at ${LANE}`)
  } catch (error) {
    skip(name, `lane not reachable at ${LANE} (${error instanceof Error ? error.message : error})`)
  }
  const { default: pw } = await import(PLAYWRIGHT)
  const browser = await pw.chromium.launch({ executablePath: CHROME, headless: true })
  const context = await browser.newContext({ viewport: { width, height } })
  const page = await context.newPage()
  await page.route('**/api/fs/**', (route) => (route.request().method() === 'GET' ? route.continue() : route.abort()))
  return { browser, page }
}

/** The lane URL with a dashboard hash route. */
export function at(hash) {
  return `${LANE.split('#')[0]}#${hash}`
}

let failures = 0
export function check(ok, message) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${message}`)
  if (!ok) failures++
}
export function finish(name) {
  console.log(failures ? `${name}: FAIL (${failures})` : `${name}: PASS`)
  process.exit(failures ? 1 : 0)
}
