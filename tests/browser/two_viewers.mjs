// Two dashboards of ONE .vtdash in one Clank window (a split), on the REAL page of a running lane: each must open its
// evidence under the media revision of the projection IT shows, never the other viewer's.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/two_viewers.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (Codex audit 2026-10-05 round 4, finding 1): every Dashboard's `mediaUrl` read one mutable, backend-wide
// "latest revision". Both viewers of one plugin share one backend, so the viewer that rendered last decided the
// revision of the other's links: an older viewer, retaining projection OLD, handed out /media/<id>?rev=NEW for a file
// it never listed (or ?rev=<none> while the newer one was still loading).
//   1. viewer A shows the item page at rev-one; the alias is retargeted (/projection now answers rev-two); a second
//      viewer B of the same file opens beside it. A's links must stay rev-one, B's must be rev-two.
//   2. B alone reloads after another retarget (rev-three): A stays rev-one, B moves to rev-three.
//   3. A alone reloads (rev-four): A moves to rev-four, B stays rev-three.
// Why one window and not two browser tabs: two tabs are two JavaScript worlds with two backends, which never share the
// mutable value this pins. Clank's split ("open to the side") is the real way Zach gets two viewers on one backend.
// Every answer is made up in the browser: /projection is the lane's real answer with `media_rev` replaced, and /media
// answers 200 to everything, so the lane's files are never read through a made-up revision.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'two_viewers'
const { browser, page } = await openLane(NAME, { width: 1600, height: 900 })

try {
  let revision = 'rev-one'
  await page.route('**/api/plugins/vibetracks/projection*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.media_rev = revision
    await route.fulfill({ response, json: body })
  })
  await page.route('**/api/plugins/vibetracks/media/**', (route) =>
    route.fulfill({ status: 200, contentType: route.request().method() === 'HEAD' ? 'video/mp4' : 'text/plain', body: '' }).catch(() => {}),
  )

  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  const target = await page.evaluate(async () => {
    const body = await (await fetch('/api/plugins/vibetracks/projection')).json()
    for (const track of body.tracks) {
      for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
        for (const item of items) {
          const videos = (item.media ?? []).filter((media) => media.kind === 'video')
          if (videos.some((m) => /^real\b/i.test(m.label)) && videos.some((m) => /^sim\b/i.test(m.label))) return { track: track.id, item: item.id }
        }
      }
    }
    return null
  })
  if (!target) throw new Error('the projection has no item with a real|sim video pair')
  const itemHash = `vt?track=${encodeURIComponent(target.track)}&item=${encodeURIComponent(target.item)}`
  console.log(`item ${target.track}/${target.item}`)

  await page.goto(at(itemHash), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-a-pair] video').first().waitFor({ timeout: 8000 })
  // Tag viewer A's root. React leaves attributes it does not manage alone, so the tag survives every re-render.
  const tagged = await page.evaluate(() => {
    const dashes = document.querySelectorAll('[data-testid=vt-dashboard]')
    if (dashes.length !== 1) return dashes.length
    dashes[0].setAttribute('data-two-viewers', 'A')
    return 1
  })
  if (tagged !== 1) throw new Error(`expected one dashboard before the split, saw ${tagged}`)

  // The revision every /media link or source in one viewer carries ('<none>' for a URL without one).
  const revisionsOf = (which) =>
    page.evaluate((which) => {
      const dashes = [...document.querySelectorAll('[data-testid=vt-dashboard]')]
      const dash = which === 'A' ? dashes.find((d) => d.getAttribute('data-two-viewers') === 'A') : dashes.find((d) => d.getAttribute('data-two-viewers') !== 'A')
      if (!dash) return null
      const seen = new Set()
      for (const element of dash.querySelectorAll('[href*="/media/"], [src*="/media/"]')) {
        const raw = element.getAttribute('href') ?? element.getAttribute('src')
        seen.add(new URL(raw, location.href).searchParams.get('rev') ?? '<none>')
      }
      return [...seen].sort()
    }, which)
  const expectOnly = async (which, want, label) => {
    const got = await revisionsOf(which)
    check(Array.isArray(got) && got.length === 1 && got[0] === want, `${label}: viewer ${which}'s media links all carry ${want} (${JSON.stringify(got)})`)
  }
  const settle = () => page.waitForTimeout(1200)

  await expectOnly('A', 'rev-one', 'before the split')

  // 1. Retarget, then open viewer B of the same file beside A (Clank's "open to the side": a #2 panel).
  revision = 'rev-two'
  const opened = await page.evaluate(() => {
    const api = window.__clank?.dockviewApi
    const base = api?.panels.find((panel) => panel.params?.viewerId === 'vibetracks.dashboard' && !panel.id.includes('#'))
    if (!api || !base) return null
    const id = `${base.id}#2`
    api.addPanel({
      id,
      component: base.params.viewerId,
      title: base.title ?? base.params.path,
      params: { ...base.params, __loc: 'main', preview: false },
      position: { referencePanel: base.id, direction: 'right' },
    })
    return id
  })
  if (!opened) throw new Error('could not open a second dashboard panel (window.__clank.dockviewApi)')
  await page.waitForFunction(() => document.querySelectorAll('[data-testid=vt-dashboard] [data-testid=vt-a-pair] video').length >= 4, null, { timeout: 10000 }).catch(() => {})
  await settle()
  check((await page.locator('[data-testid=vt-dashboard]').count()) === 2, 'two dashboards of the same file are mounted')
  await expectOnly('A', 'rev-one', '1. B opened after a retarget')
  await expectOnly('B', 'rev-two', '1. B opened after a retarget')

  // 2. B alone reloads after another retarget. The reload control lives on the tracks page.
  const reloadIn = (which) =>
    page.evaluate((which) => {
      const dashes = [...document.querySelectorAll('[data-testid=vt-dashboard]')]
      const dash = which === 'A' ? dashes.find((d) => d.getAttribute('data-two-viewers') === 'A') : dashes.find((d) => d.getAttribute('data-two-viewers') !== 'A')
      const button = dash?.querySelector('[data-testid=vt-a-reload]')
      if (!(button instanceof HTMLElement)) return false
      button.click()
      return true
    }, which)
  const backToItem = async () => {
    await page.goto(at(itemHash), { waitUntil: 'networkidle' })
    await page.waitForFunction(() => document.querySelectorAll('[data-testid=vt-dashboard] [data-testid=vt-a-pair] video').length >= 4, null, { timeout: 8000 }).catch(() => {})
    await settle()
  }
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-a-reload]').nth(1).waitFor({ timeout: 8000 })
  revision = 'rev-three'
  check(await reloadIn('B'), "B's reload control is there")
  await settle()
  await backToItem()
  await expectOnly('A', 'rev-one', '2. B reloaded alone')
  await expectOnly('B', 'rev-three', '2. B reloaded alone')

  // 3. A alone reloads.
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-a-reload]').nth(1).waitFor({ timeout: 8000 })
  revision = 'rev-four'
  check(await reloadIn('A'), "A's reload control is there")
  await settle()
  await backToItem()
  await expectOnly('A', 'rev-four', '3. A reloaded alone')
  await expectOnly('B', 'rev-three', '3. A reloaded alone')
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
