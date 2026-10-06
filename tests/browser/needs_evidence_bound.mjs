// A Needs page's evidence links stay bound to the document on screen, on the REAL page of a running lane.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/needs_evidence_bound.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (Codex audit 2026-10-05 round 3, finding 1): a path that also appeared in projection.media opened as
// /media/<id>?rev=<the PROJECTION's revision>, so an OLD Needs document beside a NEWER projection (a retargeted alias)
// opened the NEW file, and skipped the document's 409 refusal and reload line. Here the page holds an old /needs
// document while the projection it loads lists every one of that document's evidence files as media, under a newer
// revision; then:
//   1. every evidence link points at /needs/evidence with the DOCUMENT's evidence_rev and the entry's eid, none at /media
//   2. the backend refuses the link (409: the alias was retargeted) -> "This changed since you opened it: reload",
//      no tab opens, and no /media request is ever made
//   3. the backend serves it (nothing changed) -> exactly one tab opens, on the old-document URL, answered 200
//   4. "reload" re-reads /needs (a real request), never /media
// On e0bd8e5 step 1 fails: the links were /media/<id>?rev=<newer projection rev>.
// The 409 is made up in the browser (route interception); the lane's files are not touched and nothing is written.

import { LANE, at, check, finish, openLane } from './_lane.mjs'

const NAME = 'needs_evidence_bound'
const { browser, page } = await openLane(NAME, { width: 1440, height: 900 })
const context = page.context()
const NEW_MEDIA_REV = 'f'.repeat(32)

try {
  // The OLD document: read once from the real backend, then served unchanged to the page for the whole check.
  const real = await page.request.get(`${new URL(LANE).origin}/api/plugins/vibetracks/needs?track=kinsim`)
  const oldDoc = await real.json()
  const files = oldDoc.items.flatMap((item) => item.evidence.filter((entry) => entry.path && !entry.is_dir && entry.kind !== 'url').map((entry) => ({ item: item.local_id, entry })))
  console.log(`old doc: evidence_rev=${oldDoc.evidence_rev}, ${files.length} file evidence entries`)
  check(files.length > 0, 'the kinsim document lists file evidence')
  const isOldDocRead = (url) => url.pathname.endsWith('/api/plugins/vibetracks/needs') && url.searchParams.get('track') === 'kinsim'
  await page.route(isOldDocRead, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(oldDoc) }),
  )
  // The NEWER projection: the real one, plus every evidence file listed as media under a new revision.
  await page.route('**/api/plugins/vibetracks/projection*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    files.forEach(({ entry }, index) => {
      body.media[`needs-bound-${index}`] = { id: `needs-bound-${index}`, kind: 'video', label: entry.label, path: entry.path }
    })
    body.media_rev = NEW_MEDIA_REV
    await route.fulfill({ response, json: body })
  })
  const mediaRequests = []
  const needsReads = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.includes('/api/plugins/vibetracks/media/')) mediaRequests.push(url.pathname + url.search)
    if (/\/api\/plugins\/vibetracks\/needs$/.test(url.pathname)) needsReads.push(url.search)
  })
  const opened = []
  context.on('page', (tab) => opened.push(tab))

  await page.goto(at('vt?track=kinsim&needs=1'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-needs]').first().waitFor({ timeout: 15000 })
  await page.locator('a[data-testid=vt-needs-evidence]').first().waitFor({ timeout: 15000 })

  // 1. Every link on the page, bound to the old document.
  const links = await page.$$eval('a[data-testid=vt-needs-evidence]', (anchors) => anchors.map((a) => a.getAttribute('href') ?? ''))
  const fileLinks = links.filter((href) => !/^https?:\/\//.test(href))
  console.log(`links on the page: ${links.length} (${fileLinks.length} to files)`)
  check(fileLinks.length > 0, 'the page shows at least one evidence link to a file')
  const eids = new Set(files.map(({ entry }) => entry.eid))
  const bound = fileLinks.every((href) => {
    const url = new URL(href, 'http://lane')
    return url.pathname.endsWith('/needs/evidence') && url.searchParams.get('rev') === oldDoc.evidence_rev && eids.has(url.searchParams.get('eid'))
  })
  check(bound, `every file link is /needs/evidence?…&eid=<entry>&rev=${oldDoc.evidence_rev} (got ${fileLinks.slice(0, 2).join(' , ')})`)
  check(!fileLinks.some((href) => href.includes('/media/') || href.includes(NEW_MEDIA_REV)), 'no link opens /media or carries the newer projection revision')

  const link = page.locator('a[data-testid=vt-needs-evidence][href*="/needs/evidence"]').first()
  const href = await link.getAttribute('href')

  // 2. The alias was retargeted since the document was read: the backend answers 409.
  await page.route('**/api/plugins/vibetracks/needs/evidence*', (route) =>
    route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'the document changed; reload' }) }),
  )
  await link.click()
  const stale = page.locator('[data-testid=vt-needs-evidence-stale]').first()
  await stale.waitFor({ timeout: 5000 }).catch(() => {})
  check(await stale.isVisible(), 'a 409 shows the reload line in place')
  check(/This changed since you opened it/.test((await stale.textContent()) ?? ''), 'the line reads "This changed since you opened it: reload"')
  await page.waitForTimeout(500)
  check(opened.length === 0, `no tab opens on a 409 (${opened.length})`)

  // 4. "reload" re-reads the document, never /media.
  const readsBefore = needsReads.length
  await stale.getByRole('button', { name: 'reload' }).click()
  await page.waitForTimeout(1500)
  check(needsReads.length > readsBefore, `"reload" re-reads /needs (${needsReads.length - readsBefore} read(s))`)
  check(!(await page.locator('[data-testid=vt-needs-evidence-stale]').first().isVisible().catch(() => false)), 'the reload clears the line')

  // 3. Nothing changed (the real route answers): one tab opens, on the old-document URL, and it is served.
  await page.unroute('**/api/plugins/vibetracks/needs/evidence*')
  const tabPromise = context.waitForEvent('page', { timeout: 8000 }).catch(() => null)
  await page.locator(`a[data-testid=vt-needs-evidence][href="${href}"]`).first().click()
  const tab = await tabPromise
  check(tab !== null, 'a served link opens one tab')
  if (tab) {
    await tab.waitForLoadState('domcontentloaded').catch(() => {})
    const tabUrl = new URL(tab.url())
    check(tabUrl.pathname.endsWith('/needs/evidence') && tabUrl.searchParams.get('rev') === oldDoc.evidence_rev, `the tab is the old-document URL (${tabUrl.pathname}?rev=${tabUrl.searchParams.get('rev')})`)
    await tab.close()
    // The same URL, asked again outside the page: the real backend serves it (200) from the reviewed document.
    const served = await page.request.get(`${new URL(LANE).origin}${href}`)
    check(served.status() === 200, `the old-document URL is served by the real backend (${served.status()} ${served.headers()['content-type']})`)
  }
  check(mediaRequests.length === 0, `the Needs page never requested /media (${mediaRequests.slice(0, 2).join(' , ')})`)
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
