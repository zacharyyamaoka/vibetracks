// The rename fence, checked in the REAL consumer: useRenamer + TrackName on the home table of a running lane.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/rename_fence.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (Codex audit 2026-10-04 #6, and 2026-10-05 round 2 finding 5: renameFence.check.mjs tests only the pure
// helper, so restoring the old consumer, which read the revision from the projection at SUBMIT time, left it green):
//   1. The projection refreshes mid-edit (another writer bumps the note's revision R1 -> R2): the POST still carries R1,
//      the revision on screen when editing STARTED.
//   2. The server answers 409: the edit stays open with the reader's text and shows the other title; Enter does not
//      save over it.
//   3. Only "Save mine anyway" re-fences, on the revision the other title was read at (R2).
// Every POST is answered here in the browser and never reaches the backend: no note is renamed by this check.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'rename_fence'
const TRACK = process.env.VT_RENAME_TRACK ?? 'kinsim'
const { browser, page } = await openLane(NAME)
// What the projection says about TRACK: null until the first real read, then overridden per step.
let served = null
let projectionReads = 0

try {
  await page.route('**/api/plugins/vibetracks/projection*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const track = body.tracks.find((candidate) => candidate.id === TRACK)
    if (track && served) {
      track.registry = { ...track.registry, revision: served.revision }
      track.title = served.title
    }
    projectionReads++
    await route.fulfill({ response, json: body })
  })
  const posts = []
  let answer = null
  await page.route(`**/api/plugins/vibetracks/tracks/${TRACK}/title`, async (route) => {
    if (route.request().method() !== 'POST') return route.abort()
    posts.push(JSON.parse(route.request().postData() ?? 'null'))
    const reply = answer?.(posts.at(-1)) ?? { status: 500, json: { error: 'unexpected POST in rename_fence' } }
    await route.fulfill(reply)
  })

  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  const row = page.locator('[data-testid=vt-a-track-name]').filter({ hasText: /\S/ })
  await row.first().waitFor({ timeout: 20000 })
  const real = await page.evaluate(async (track) => {
    const response = await fetch('/api/plugins/vibetracks/projection')
    const body = await response.json()
    const found = body.tracks.find((candidate) => candidate.id === track)
    return found ? { title: found.title, revision: found.registry?.revision ?? null } : null
  }, TRACK)
  if (!real?.revision) {
    check(false, `track ${TRACK} has a registry revision to rename against`)
    finish(NAME)
  }
  const R1 = 'R1-rename-fence'
  const R2 = 'R2-rename-fence'
  served = { revision: R1, title: real.title }
  // Re-read so the page shows R1 (through the same Reload control a reader uses).
  let reads = projectionReads
  await page.locator('[data-testid=vt-a-reload]').click()
  await waitForRead(reads)

  const exact = new RegExp(`^${real.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`)
  const name = page.locator('[data-testid=vt-a-track-name]').filter({ hasText: exact }).first()
  await name.dblclick()
  const input = page.locator('[data-testid=vt-a-rename-input]')
  await input.waitFor({ timeout: 5000 })
  await input.press('End')
  await input.type(' (mine)')

  // 1. Another writer renames the note while the edit is open; the page re-reads the projection. WHY element.click()
  //    in the page: a real pointer click would blur the input, and blur saves; a scripted click keeps the focus, so
  //    the edit is still open when the refreshed projection arrives, exactly as with a background reload.
  served = { revision: R2, title: 'Renamed elsewhere' }
  reads = projectionReads
  await page.evaluate(() => document.querySelector('[data-testid=vt-a-reload]').click())
  await waitForRead(reads)
  await page.waitForTimeout(300)
  check(await input.isVisible(), 'the edit stays open across a projection refresh')
  check((await input.inputValue()) === `${real.title} (mine)`, 'the draft is untouched by the refresh')
  await input.type('!')
  answer = (body) => ({ status: 409, json: { error: 'the note changed since you opened it', revision: R2 } })
  await input.press('Enter')
  await page.waitForTimeout(400)
  check(posts.length === 1, `one POST on Enter (got ${posts.length})`)
  check(posts[0]?.revision === R1, `the POST carries the revision captured at edit start (${R1}), got ${posts[0]?.revision}`)
  check(posts[0]?.title === `${real.title} (mine)!`, 'the POST carries the title exactly as typed')

  // 2. The 409: the edit stays open with the reader's words and shows the other title once the page has re-read it.
  const theirs = page.locator('[data-testid=vt-a-rename-theirs]')
  await theirs.waitFor({ timeout: 5000 })
  check((await theirs.textContent())?.includes('Renamed elsewhere'), 'the conflict shows the other title')
  check((await input.inputValue()) === `${real.title} (mine)!`, "the reader's draft survives the 409")
  await input.press('Enter')
  await page.waitForTimeout(300)
  check(posts.length === 1, 'Enter in a conflict saves nothing')

  // 3. "Save mine anyway": the only path that re-fences, on the revision the other title was read at.
  answer = (body) => ({ status: 200, json: { title: body.title, revision: 'R3-rename-fence' } })
  await page.locator('[data-testid=vt-a-rename-save-mine]').click()
  await page.waitForTimeout(400)
  check(posts.length === 2, `"Save mine anyway" sends one POST (got ${posts.length} in all)`)
  check(posts[1]?.revision === R2, `it re-fences on the revision shown to the reader (${R2}), got ${posts[1]?.revision}`)
  check(posts[1]?.title === `${real.title} (mine)!`, 'and sends the same draft')
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)

async function waitForRead(before) {
  const started = Date.now()
  while (projectionReads <= before) {
    if (Date.now() - started > 10000) throw new Error('the projection was not re-read')
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  await page.waitForLoadState('networkidle')
}
