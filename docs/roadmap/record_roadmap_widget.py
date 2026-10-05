"""Record the roadmap widget's hero clip, its stills and their acceptance checks from a REAL running Vibe Tracks lane.

Drives an already-running Clank + Vibe Tracks dashboard lane (never starts or stops one) in its own headless Chrome,
on variant A (drill-down pages): the tracks page → kinsim's track page → the Roadmap section's calm head → Expand →
the Depth lens → arrow keys along a lane → a click on RB0 grows the focus card with its proof → its named run opens its
own record → history back (what the mouse's back button does) restores the card → back to the tracks → pyblocks says
"No roadmap reported yet". Then the stills, each in a fresh browser context with its own predicate: the calm head per
track, the full board, the focus card, the settings page's Roadmap section and the board in elbow lines, pyblocks, and
a 390 px phone-width calm head. Read-only: the line-style change lives in this browser context's localStorage.

    cd ~/vibetracks-roadmap
    uv run --no-project --with playwright==1.55.0 python3 docs/roadmap/record_roadmap_widget.py --url http://127.0.0.1:4400/ --out <dir>

WHY --no-project: this checkout's pyproject.toml would otherwise make uv create .venv and uv.lock inside it.

Writes <dir>/raw.webm, <dir>/hero.mp4 (H.264, muted, trimmed to the journey), <dir>/hero.gif, <dir>/stills/*.png and
<dir>/hero.json (every step's offset in hero.mp4 and the values its predicate measured).
WHY assertions beside the video: a clip shows the flow; the JSON proves each state really happened (selected rung, the
proven count against the live document, path geometry, scroll widths), measured in the page, never read off the video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import Page, async_playwright

# Zach's own dashboard (4380/4381) and the Dashboard lane (4390/4391): never driven by a recorder, even headlessly.
PORTS_NEVER_DRIVEN = {4380, 4381, 4390, 4391}
DASHBOARD = "?vtdash=Agent%20work.vtdash"
TRACKS = ["kinsim", "rig", "grasping", "detection"]
API = "/api/plugins/vibetracks/roadmap/doc?track="

# A visible pointer: headless Chrome draws no cursor, and a clip whose clicks come from nowhere does not read.
POINTER = """(() => {
  const install = () => {
    if (document.getElementById('__rec-pointer')) return
    const dot = document.createElement('div')
    dot.id = '__rec-pointer'
    dot.style.cssText = 'position:fixed;left:-40px;top:-40px;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;'
      + 'background:rgba(37,99,235,.55);border:2px solid #fff;box-shadow:0 0 0 1px rgba(37,99,235,.9);z-index:2147483647;'
      + 'pointer-events:none;transition:transform .12s'
    document.documentElement.appendChild(dot)
    addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px' }, true)
    addEventListener('mousedown', () => { dot.style.transform = 'scale(.7)' }, true)
    addEventListener('mouseup', () => { dot.style.transform = '' }, true)
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', install); else install()
})()"""

# The route lives in the hash (#vt?track=…&rmopen=1&rm=<json>); the widget's state is `rm`.
ROUTE = """(() => { const q = new URLSearchParams((location.hash.split('?')[1]) || ''); let rm = {};
  try { rm = JSON.parse(q.get('rm') || '{}') } catch (e) {}
  return { track: q.get('track'), rmopen: q.get('rmopen'), file: q.get('file'), rm } })()"""

# WHY dense sampling (Codex J02 on the kinsim board): one sample every 4px of path length (screen space) cannot jump a card.
CROSSINGS = """(() => {
  const cards = [...document.querySelectorAll('[data-rung]')].filter((el) => el.offsetParent !== null)
    .map((el) => ({ id: el.dataset.rung, r: el.getBoundingClientRect() }))
  const lines = [...document.querySelectorAll('[data-testid="vt-roadmap-canvas"] path[data-edge]')]
  let checked = 0, crossings = 0; const examples = []
  for (const path of lines) {
    const key = path.dataset.edge || ''
    const [from, to] = key.split('>')
    if (!from || !to || from === to) continue
    const total = path.getTotalLength(), ctm = path.getScreenCTM()
    if (!total || !ctm) continue
    checked += 1
    const steps = Math.max(60, Math.ceil((total * Math.hypot(ctm.a, ctm.b)) / 4))
    for (let s = 0; s <= steps; s += 1) {
      const p = path.getPointAtLength((total * s) / steps), x = ctm.a * p.x + ctm.c * p.y + ctm.e, y = ctm.b * p.x + ctm.d * p.y + ctm.f
      const hit = cards.find((c) => c.id !== from && c.id !== to && x > c.r.left + 1 && x < c.r.right - 1 && y > c.r.top + 1 && y < c.r.bottom - 1)
      if (hit) { crossings += 1; if (examples.length < 3) examples.push(`${key} through ${hit.id}`); break }
    }
  }
  return { checked, crossings, examples }
})()"""

# Dependency lines only, keyed by edge. An alias tie (dashed 2 3) keeps its own shape in every style, so `curves`
# counts the ordinary lines that still carry a cubic (C) segment.
LINES = """(() => { const ps = [...document.querySelectorAll('[data-testid="vt-roadmap-canvas"] path[data-edge]')];
  const ordinary = ps.filter((p) => p.getAttribute('stroke-dasharray') !== '2 3');
  return { paths: ps.length, ordinary: ordinary.length, curves: ordinary.filter((p) => (p.getAttribute('d') || '').includes('C')).length,
           d: Object.fromEntries(ps.map((p) => [p.dataset.edge, p.getAttribute('d')])) } })()"""

# The calm head against the live document the API serves: an independent count, never the widget's own summary.
# formatAsOf's two forms are re-derived here from generated_at ("as of HH:MM", or "as of D Mon HH:MM" on another day).
CALM = """async (track) => {
  const doc = await (await fetch('""" + API + """' + track)).json()
  const answer = document.querySelector('[data-testid="vt-roadmap-answer"]')
  const sentence = answer ? answer.dataset.sentence : null
  const at = new Date(doc.generated_at), now = new Date()
  const hm = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(at)
  const sameDay = at.toDateString() === now.toDateString()
  const expectAsOf = sameDay ? `as of ${hm}` : `as of ${new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(at)} ${hm}`
  const m = /(\\d+) of (\\d+) proven/.exec(sentence || ''), c = /(\\d+) claimed/.exec(sentence || '')
  return {
    track, sentence, text: answer ? answer.textContent : null,
    asOf: document.querySelector('[data-testid="vt-roadmap-asof"]')?.textContent ?? null, expectAsOf,
    notCurrent: document.querySelector('[data-testid="vt-roadmap-not-current"]')?.textContent ?? null,
    shownProven: m ? +m[1] : null, shownTotal: m ? +m[2] : null, shownClaimed: c ? +c[1] : 0,
    docProven: doc.rungs.filter((r) => r.status === 'green' || r.status === 'done').length,
    docTotal: doc.rungs.length, docClaimed: doc.rungs.filter((r) => r.status === 'claimed').length,
    stripLanes: document.querySelectorAll('[data-testid="vt-roadmap-strip"] .vt-rm-strip-lane').length,
    generatedAt: doc.generated_at,
  }
}"""

SELECTED = ("(() => { const t = document.querySelector('[data-testid=\"vt-roadmap-focus-trail\"]');"
            " const route = " + ROUTE + ";"
            " return { sel: route.rm.sel || null, trail: t ? t.textContent.trim() : null,"
            " focused: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.rung || null : null,"
            " lens: document.querySelector('[data-testid=\"vt-roadmap-lens\"] [aria-pressed=\"true\"]')?.dataset.value || null } })()")


def calm_ok(m: dict) -> bool:
    return (bool(m["sentence"]) and m["asOf"] == m["expectAsOf"] and m["shownTotal"] == m["docTotal"]
            and m["shownProven"] == m["docProven"] and m["shownClaimed"] == m["docClaimed"] and m["stripLanes"] > 0)


EXPECT = {
    "Tracks page": lambda m: m["rows"][:5] == ["kinsim", "rig", "grasping", "detection", "pyblocks"],
    "Open kinsim's track page": lambda m: m["page"] == "kinsim" and m["route"]["track"] == "kinsim",
    "Roadmap calm head": lambda m: calm_ok(m) and m["inView"],
    "Expand: the full lens board": lambda m: m["route"]["rmopen"] == "1" and m["rungs"] == m["docTotal"] and m["lens"] == "ladder",
    "Depth lens: the same cards glide": lambda m: m["lens"] == "depth" and m["moved"] > 0 and m["route"]["rm"].get("lens") == "depth",
    # Zach, Oct 3: arrow keys move the selection between rungs and the view follows.
    "Arrow keys walk the robots lane": lambda m: len(m["sels"]) == 3 and len(set(m["sels"])) == 3
        and all(m["axis"].get(s) == "robots" for s in m["sels"]) and m["focused"] == m["sels"][-1],
    "Click RB0: the focus card with its proof": lambda m: m["trail"] == "RB0" and m["proof"] and m["runs"] >= 1 and m["firstRun"].startswith("rb0-"),
    "A named run opens its own record": lambda m: m["page"] and m["shownPath"] == m["clickedPath"] and m["route"]["file"] == m["clickedPath"],
    "History back restores the focus card": lambda m: m["trail"] == "RB0" and m["proof"] and m["lens"] == "depth" and m["route"]["rmopen"] == "1",
    "Back to the tracks": lambda m: m["l1"],
    "Pyblocks: No roadmap reported yet": lambda m: m["none"] == "No roadmap reported yet." and not m["loading"] and not m["calm"],
}


async def glide_to(page: Page, locator, pause: int = 0) -> None:
    """Move the visible pointer to the element in steps, so a click in the clip has somewhere to come from."""
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=14)
    if pause:
        await page.wait_for_timeout(pause)


async def smooth_into_view(page: Page, selector: str, block: str = "start", pause: int = 900) -> None:
    await page.evaluate("([s, b]) => document.querySelector(s).scrollIntoView({ behavior: 'smooth', block: b })", [selector, block])
    await page.wait_for_timeout(pause)


async def settled_box(page: Page, selector: str) -> dict:
    """Scroll the element to the middle and wait until its box holds still for three samples in a row.
    WHY: on a first load the KPI rows and the projection arrive after the roadmap section does, and the dashboard's
    inner scroller moves under a crop measured too early (the kinsim and pyblocks stills came out as KPI rows)."""
    last, still = None, 0
    for _ in range(60):
        await page.evaluate("(s) => document.querySelector(s).scrollIntoView({ block: 'center' })", selector)
        await page.wait_for_timeout(250)
        box = await page.locator(selector).bounding_box()
        still = still + 1 if last and abs(box["y"] - last["y"]) < 0.5 and abs(box["height"] - last["height"]) < 0.5 else 0
        if still >= 3:
            return box
        last = box
    raise AssertionError(f"{selector} never held still")


async def open_dashboard(page: Page, url: str, hash_: str = "") -> None:
    await page.goto(url.rstrip("/") + "/" + DASHBOARD + hash_, wait_until="load")
    await page.wait_for_selector('[data-testid="vt-variant-a"]', timeout=60000)


async def record_hero(browser, url: str, out: Path, width: int, height: int) -> dict:
    stills = out / "stills"
    context = await browser.new_context(viewport={"width": width, "height": height},
                                        record_video_dir=str(out), record_video_size={"width": width, "height": height})
    await context.add_init_script(POINTER)
    started = time.monotonic()
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)[:300]))
    await open_dashboard(page, url)
    await page.wait_for_selector('[data-testid="vt-a-l1"]', timeout=60000)
    await page.wait_for_selector('[data-testid="vt-a-track-row"][data-track="kinsim"]', timeout=60000)
    await page.evaluate(f"fetch('{API}kinsim').then((r) => r.json()).then((d) => {{ window.__axis = Object.fromEntries(d.rungs.map((r) => [r.id, r.axis])); window.__total = d.rungs.length }})")
    await page.mouse.move(width / 2, height / 2)
    await page.wait_for_timeout(1000)
    offset = time.monotonic() - started
    steps: list[dict] = []

    async def step(label: str, action, check: str, arg=None) -> None:
        at = round(time.monotonic() - started - offset, 2)
        await action()
        measured = await (page.evaluate(check, arg) if arg is not None else page.evaluate(check))
        name = f"hero-{len(steps) + 1:02d}"
        await page.screenshot(path=str(stills / f"{name}.png"))
        ok = bool(EXPECT[label](measured))
        steps.append({"label": label, "t_s": at, "measured": measured, "ok": ok, "still": f"stills/{name}.png"})

    async def nothing() -> None:
        await page.wait_for_timeout(700)

    async def open_kinsim() -> None:
        row = page.locator('[data-testid="vt-a-track-row"][data-track="kinsim"]')
        await glide_to(page, row, 250)
        await row.click()
        await page.wait_for_selector('[data-testid="vt-a-l2"][data-track="kinsim"]')
        await page.wait_for_timeout(900)

    async def calm_head() -> None:
        await page.wait_for_selector('[data-testid="vt-roadmap-calm"]', timeout=30000)
        await smooth_into_view(page, '[data-testid="vt-a-roadmap"]', "center", 1600)

    async def expand() -> None:
        button = page.locator('[data-testid="vt-a-roadmap-expand"]')
        await glide_to(page, button, 200)
        await button.click()
        await page.wait_for_selector('[data-testid="vt-roadmap-canvas"] [data-rung]')
        await page.wait_for_timeout(500)
        await smooth_into_view(page, '[data-testid="vt-a-roadmap"]', "start", 1100)

    async def depth() -> None:
        await page.evaluate("window.__pos = Object.fromEntries([...document.querySelectorAll('[data-rung]')].map((b) => [b.dataset.rung, b.style.transform]))")
        button = page.locator('[data-testid="vt-roadmap-lens"] [data-value="depth"]')
        await glide_to(page, button, 150)
        await button.click()
        await page.wait_for_timeout(1500)

    async def arrows() -> None:
        await page.evaluate("document.querySelector('[data-testid=\"vt-roadmap-canvas\"]').focus({ preventScroll: true })")
        sels = []
        for _ in range(3):
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(750)
            sels.append((await page.evaluate(SELECTED))["sel"])
        await page.evaluate("(s) => { window.__sels = s }", sels)

    async def click_rb0() -> None:
        card = page.locator('[data-testid="vt-rung-RB0"]')
        await glide_to(page, card, 200)
        await card.click()
        await page.wait_for_selector('[data-testid="vt-roadmap-proof"]')
        await page.wait_for_timeout(900)
        await smooth_into_view(page, '[data-testid="vt-roadmap-focus"] [data-testid="vt-roadmap-open-run"]', "center", 1000)

    async def open_run() -> None:
        run = page.locator('[data-testid="vt-roadmap-focus"] [data-testid="vt-roadmap-open-run"]').first
        await page.evaluate("(p) => { window.__clicked = p }", await run.get_attribute("data-path"))
        await glide_to(page, run, 250)
        await run.click()
        await page.wait_for_selector('[data-testid="vt-a-file"]')
        await page.wait_for_timeout(1300)

    async def history_back() -> None:
        # What the mouse's back button does: the browser's history.back(), which fires popstate.
        await page.evaluate("history.back()")
        await page.wait_for_selector('[data-testid="vt-roadmap-proof"]')
        await page.wait_for_timeout(400)
        await page.evaluate("""window.__inView = (() => { const r = document.querySelector('[data-testid="vt-roadmap-focus"]').getBoundingClientRect();
          return r.bottom > 0 && r.top < innerHeight })()""")
        # WHY scroll after measuring: the clip should show the restored card; whether the page restored the reader's
        # scroll by itself is recorded as inViewAfterBack, not hidden.
        await smooth_into_view(page, '[data-testid="vt-a-roadmap"]', "start", 1100)

    async def to_tracks() -> None:
        crumb = page.locator('[data-testid="vt-breadcrumb"] button').first
        await smooth_into_view(page, '[data-testid="vt-breadcrumb"]', "start", 500)
        await glide_to(page, crumb, 200)
        await crumb.click()
        await page.wait_for_selector('[data-testid="vt-a-l1"]')
        await page.wait_for_timeout(700)

    async def open_pyblocks() -> None:
        row = page.locator('[data-testid="vt-a-track-row"][data-track="pyblocks"]')
        await glide_to(page, row, 200)
        await row.click()
        await page.wait_for_selector('[data-testid="vt-roadmap-none"], [data-testid="vt-roadmap-calm"]', timeout=30000)
        await smooth_into_view(page, '[data-testid="vt-a-roadmap"]', "center", 1800)

    focus = ("(() => { const p = document.querySelector('[data-testid=\"vt-roadmap-focus\"]'); const runs = p ? [...p.querySelectorAll('[data-testid=\"vt-roadmap-open-run\"]')] : [];"
             " return { ...(" + SELECTED + "), proof: Boolean(p && p.querySelector('[data-testid=\"vt-roadmap-proof\"]')), runs: runs.length,"
             " firstRun: runs[0] ? runs[0].textContent.trim() : '', firstRunPath: runs[0] ? runs[0].dataset.path : null,"
             " verdict: p?.querySelector('.vt-rm-verdict b')?.textContent ?? null, route: " + ROUTE + " } })()")

    await step("Tracks page", nothing, "({ rows: [...document.querySelectorAll('[data-testid=\"vt-a-track-row\"]')].map((r) => r.dataset.track) })")
    await step("Open kinsim's track page", open_kinsim,
               "({ page: document.querySelector('[data-testid=\"vt-a-l2\"]')?.dataset.track, route: " + ROUTE + " })")
    await step("Roadmap calm head", calm_head,
               "async () => { const m = await (" + CALM + ")('kinsim'); const r = document.querySelector('[data-testid=\"vt-roadmap-calm\"]').getBoundingClientRect();"
               " return { ...m, inView: r.top >= 0 && r.bottom <= innerHeight } }")
    await step("Expand: the full lens board", expand,
               "({ route: " + ROUTE + ", rungs: document.querySelectorAll('[data-testid=\"vt-roadmap-canvas\"] [data-rung]').length, docTotal: window.__total,"
               " lens: document.querySelector('[data-testid=\"vt-roadmap-lens\"] [aria-pressed=\"true\"]')?.dataset.value })")
    await step("Depth lens: the same cards glide", depth,
               "({ route: " + ROUTE + ", lens: document.querySelector('[data-testid=\"vt-roadmap-lens\"] [aria-pressed=\"true\"]')?.dataset.value,"
               " moved: [...document.querySelectorAll('[data-rung]')].filter((b) => window.__pos[b.dataset.rung] !== b.style.transform).length })")
    await step("Arrow keys walk the robots lane", arrows,
               "({ sels: window.__sels, axis: Object.fromEntries((window.__sels || []).map((s) => [s, window.__axis[s]])),"
               " focused: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.rung || null : null })")
    await step("Click RB0: the focus card with its proof", click_rb0, focus)
    await step("A named run opens its own record", open_run,
               "({ page: Boolean(document.querySelector('[data-testid=\"vt-a-file\"]')), clickedPath: window.__clicked,"
               " shownPath: document.querySelector('[data-testid=\"vt-a-file\"] code')?.textContent ?? null, route: " + ROUTE + ","
               " allowlisted: !/not in the projection's media allowlist/.test(document.querySelector('[data-testid=\"vt-a-file\"]')?.textContent || '') })")
    await step("History back restores the focus card", history_back, f"(() => ({{ ...{focus}, inViewAfterBack: window.__inView }}))()")
    await step("Back to the tracks", to_tracks, "({ l1: Boolean(document.querySelector('[data-testid=\"vt-a-l1\"]')), route: " + ROUTE + " })")
    await step("Pyblocks: No roadmap reported yet", open_pyblocks,
               "({ none: document.querySelector('[data-testid=\"vt-roadmap-none\"]')?.textContent ?? null,"
               " loading: Boolean(document.querySelector('[data-testid=\"vt-roadmap-loading\"]')), calm: Boolean(document.querySelector('[data-testid=\"vt-roadmap-calm\"]')) })")
    journey_s = round(time.monotonic() - started - offset, 2)
    await page.close()
    await context.close()
    videos = sorted(out.glob("*.webm"), key=lambda path: path.stat().st_mtime)
    videos[-1].replace(out / "raw.webm")
    return {"journey_offset_s": round(offset, 2), "journey_s": journey_s, "steps": steps, "page_errors": errors}


async def record_stills(browser, url: str, out: Path, width: int, height: int) -> dict:
    stills = out / "stills"
    shots: list[dict] = []
    errors: list[str] = []

    async def fresh(viewport=(width, height), **kw):
        context = await browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, **kw)
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)[:300]))
        return context, page

    async def shoot(page: Page, name: str, label: str, measured: dict, ok: bool, clip_selector: str | None = None) -> None:
        path = stills / f"{name}.png"
        if clip_selector:
            # WHY a viewport shot cropped by ffmpeg, not Playwright's clip or element screenshot: both capture beyond the
            # viewport, Clank's 100vh shell re-lays out for that capture, the dashboard's inner scroller moves, and the
            # "calm head" still came out as the KPI rows above it. A plain viewport shot is what the reader sees.
            box = await settled_box(page, clip_selector)
            vw = page.viewport_size
            pad = 16
            x0, y0 = int(max(0, box["x"] - pad)), int(max(0, box["y"] - pad))
            x1, y1 = int(min(vw["width"], box["x"] + box["width"] + pad)), int(min(vw["height"], box["y"] + box["height"] + pad))
            assert x1 > x0 and y1 > y0, f"{name}: {clip_selector} is outside the viewport ({box})"
            full = stills / f"{name}.full.png"
            await page.screenshot(path=str(full))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(full), "-vf", f"crop={x1 - x0}:{y1 - y0}:{x0}:{y0}", str(path)], check=True)
            full.unlink()
            after = await page.locator(clip_selector).bounding_box()
            assert abs(after["y"] - box["y"]) < 1, f"{name}: {clip_selector} moved while it was shot ({box['y']} → {after['y']})"
        else:
            await page.screenshot(path=str(path))
        shots.append({"name": name, "label": label, "still": f"stills/{name}.png", "measured": measured, "ok": bool(ok)})

    # 1. The calm head on each track that reports a roadmap.
    context, page = await fresh()
    for track in TRACKS:
        await open_dashboard(page, url, f"#vt?track={track}")
        # WHY wait for this track's page: a hash-only goto is a same-document navigation, so the previous track's calm
        # head is still in the DOM for a moment and would satisfy a bare wait.
        await page.wait_for_selector(f'[data-testid="vt-a-l2"][data-track="{track}"] [data-testid="vt-roadmap-calm"]', timeout=60000)
        await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'center' })")
        await page.wait_for_timeout(500)
        m = await page.evaluate(CALM, track)
        await shoot(page, f"calm-{track}", f"{track}: the calm head", m, calm_ok(m), '[data-testid="vt-a-roadmap"]')

    # 2. The full board, kinsim, Ladder.
    await open_dashboard(page, url, "#vt?track=kinsim&rmopen=1")
    await page.wait_for_selector('[data-testid="vt-roadmap-canvas"] [data-rung]', timeout=60000)
    await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'start' })")
    await page.wait_for_timeout(700)
    m = await page.evaluate("async () => { const d = await (await fetch('" + API + "kinsim')).json();"
                            " return { rungs: document.querySelectorAll('[data-testid=\"vt-roadmap-canvas\"] [data-rung]').length, docTotal: d.rungs.length,"
                            " lanes: document.querySelectorAll('[data-testid=\"vt-roadmap-canvas\"] .vt-rm-lane-title').length, docAxes: new Set(d.rungs.map((r) => r.axis)).size,"
                            " lens: document.querySelector('[data-testid=\"vt-roadmap-lens\"] [aria-pressed=\"true\"]')?.dataset.value } }")
    await shoot(page, "full-kinsim", "kinsim: the full board (Ladder)", m, m["rungs"] == m["docTotal"] and m["lanes"] == m["docAxes"] and m["lens"] == "ladder")

    # 3. The focus card with its proof (BT1: a claimed rung with named promotion and regression runs).
    rm = json.dumps({"lens": "depth", "sel": "BT1", "tab": "proof"}, separators=(",", ":"))
    await open_dashboard(page, url, "#vt?track=kinsim&rmopen=1&rm=" + quote(rm))
    await page.wait_for_selector('[data-testid="vt-roadmap-proof"]', timeout=60000)
    await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'start' })")
    await page.wait_for_timeout(1200)
    m = await page.evaluate("(() => { const p = document.querySelector('[data-testid=\"vt-roadmap-focus\"]'); const runs = [...p.querySelectorAll('[data-testid=\"vt-roadmap-open-run\"]')];"
                            " return { trail: p.querySelector('[data-testid=\"vt-roadmap-focus-trail\"]').textContent.trim(), runs: runs.map((r) => r.textContent.trim()).slice(0, 6),"
                            " evidenceRows: p.querySelectorAll('[data-testid=\"vt-roadmap-evidence\"]').length, verdict: p.querySelector('.vt-rm-verdict b')?.textContent,"
                            " reason: p.querySelector('.vt-rm-verdict .vt-muted.vt-rm-sm')?.textContent ?? null } })()")
    await shoot(page, "focus-bt1", "BT1's focus card: the proof tab", m, m["trail"] == "BT1" and len(m["runs"]) >= 1 and m["evidenceRows"] >= 1)

    # 4. The settings page's Roadmap section, then Elbow lines on the Depth board (every line drawn).
    await open_dashboard(page, url, "#vt?track=kinsim&rmopen=1&rm=" + quote(json.dumps({"lens": "depth"})))
    await page.wait_for_selector('[data-testid="vt-roadmap-canvas"] path[data-edge]', timeout=60000)
    await page.wait_for_timeout(800)
    curved = await page.evaluate(LINES)
    toolbar = await page.evaluate("({ toolbarControls: [...document.querySelectorAll('[data-testid=\"vt-roadmap\"] .vt-rm-lensbar [role=group]')].map((g) => g.dataset.testid),"
                                  " lineControlOnBoard: /Elbow|Curved/.test(document.querySelector('[data-testid=\"vt-roadmap\"] .vt-rm-lensbar').textContent) })")
    await page.click('[data-testid="vt-settings-gear"]')
    await page.wait_for_selector('[data-testid="vt-settings-section-roadmap"]')
    select = page.locator('[data-testid="vt-settings-section-roadmap"] [data-testid="vt-setting-edges"] select')
    await select.select_option("elbow")
    await page.wait_for_timeout(400)
    m = await page.evaluate("(() => { const s = document.querySelector('[data-testid=\"vt-settings-section-roadmap\"] [data-testid=\"vt-setting-edges\"] select');"
                            " return { value: s.value, options: [...s.options].map((o) => o.value + ':' + o.textContent),"
                            " title: document.querySelector('[data-testid=\"vt-settings-section-roadmap\"] h2').textContent } })()")
    m.update(toolbar)
    await shoot(page, "settings-roadmap", "The settings page: the Roadmap section's Lines", m,
                m["value"] == "elbow" and m["title"] == "Roadmap" and not m["lineControlOnBoard"])
    await page.click('[data-testid="vt-settings-close"]')
    await page.wait_for_selector('[data-testid="vt-roadmap-canvas"] path[data-edge]', timeout=30000)
    await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'start' })")
    await page.wait_for_timeout(1000)
    elbow = await page.evaluate(LINES)
    cross = await page.evaluate(CROSSINGS)
    changed = sum(1 for key, d in elbow["d"].items() if curved["d"].get(key) != d)
    m = {"paths": elbow["paths"], "ordinary": elbow["ordinary"], "curvesBefore": curved["curves"], "curvesAfter": elbow["curves"],
         "changed": changed, **cross}
    await shoot(page, "board-elbow", "kinsim's Depth board in Elbow lines", m,
                m["paths"] > 5 and m["curvesBefore"] > 0 and m["curvesAfter"] == 0 and m["changed"] > 0 and m["checked"] > 5 and m["crossings"] == 0)
    await context.close()

    # 5. Pyblocks: the backend has no roadmap for it (404), and the widget says so calmly.
    context, page = await fresh()
    await open_dashboard(page, url, "#vt?track=pyblocks")
    await page.wait_for_selector('[data-testid="vt-roadmap-none"], [data-testid="vt-roadmap-calm"]', timeout=60000)
    await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'center' })")
    await page.wait_for_timeout(500)
    m = await page.evaluate("async () => ({ none: document.querySelector('[data-testid=\"vt-roadmap-none\"]')?.textContent ?? null,"
                            " api: (await fetch('" + API + "pyblocks')).status })")
    await shoot(page, "none-pyblocks", "pyblocks: No roadmap reported yet", m, m["none"] == "No roadmap reported yet." and m["api"] == 404,
                '[data-testid="vt-a-roadmap"]')
    await context.close()

    # 6. Phone width (390 px): Clank's left panel is hidden first, as a phone reader would, and shown again afterwards
    # because Clank saves its layout into the lane's workspace.
    context, page = await fresh((390, 844), device_scale_factor=2, is_mobile=True, has_touch=True)
    await open_dashboard(page, url, "#vt?track=kinsim")
    await page.wait_for_selector('[data-testid="vt-roadmap-calm"]', timeout=60000)
    toggled = False
    if await page.locator('[data-testid="status-toggle-left"]').count():
        await page.click('[data-testid="status-toggle-left"]')
        toggled = True
        await page.wait_for_timeout(800)
    await page.evaluate("document.querySelector('[data-testid=\"vt-a-roadmap\"]').scrollIntoView({ block: 'center' })")
    await page.wait_for_timeout(600)
    m = await page.evaluate(CALM, "kinsim")
    m.update(await page.evaluate("""(() => { const d = document.documentElement, s = document.querySelector('.vt-scroll'), c = document.querySelector('[data-testid="vt-roadmap-calm"]').getBoundingClientRect();
      return { docScroll: [d.scrollWidth, d.clientWidth], dashScroll: s ? [s.scrollWidth, s.clientWidth] : null, calmBox: [Math.round(c.left), Math.round(c.right)], viewport: innerWidth } })()"""))
    m["leftPanelHidden"] = toggled
    await shoot(page, "phone-kinsim", "kinsim's calm head at 390 px", m,
                calm_ok(m) and m["docScroll"][0] <= m["docScroll"][1] and (m["dashScroll"] is None or m["dashScroll"][0] <= m["dashScroll"][1])
                and m["calmBox"][0] >= 0 and m["calmBox"][1] <= m["viewport"])
    if toggled:
        await page.click('[data-testid="status-toggle-left"]')
        await page.wait_for_timeout(1500)
    await context.close()
    return {"stills": shots, "page_errors": errors}


# WHY 1.25x: the journey takes ~24 s in real time (every step waits for its glide and its measurement); the clip should
# be the 12-20 s a reader watches. Every step's clip_t_s is its offset in hero.mp4 after this speed-up.
SPEED = 1.25


def encode(out: Path, offset: float, duration: float) -> dict:
    """raw.webm → hero.mp4 (H.264, muted, trimmed to the journey, SPEED×), a small hero.gif fallback, and a .webp of
    every still (what the report inlines; the .png stays as the lossless original)."""
    raw, mp4, gif = out / "raw.webm", out / "hero.mp4", out / "hero.gif"
    trim = ["-ss", f"{offset:.2f}", "-t", f"{duration + 0.8:.2f}"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *trim, "-i", str(raw), "-an", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "30", "-pix_fmt", "yuv420p", "-vf", f"setpts=PTS/{SPEED},scale=1280:-2", "-movflags", "+faststart", str(mp4)], check=True)
    # WHY 5 fps at 480 px, 32 colours, diff-rectangle frames: the GIF only covers a viewer that cannot play H.264, and it
    # is inlined, so it is kept near 1 MB rather than sharp (6 fps / 560 px / 48 colours was 2.5 MB).
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *trim, "-i", str(raw), "-vf",
                    f"setpts=PTS/{SPEED},fps=5,scale=480:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=32:stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    str(gif)], check=True)
    for png in sorted((out / "stills").glob("*.png")):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-c:v", "libwebp", "-quality", "82", str(png.with_suffix(".webp"))], check=True)
    return {"mp4": mp4.name, "mp4_bytes": mp4.stat().st_size, "gif": gif.name, "gif_bytes": gif.stat().st_size, "speed": SPEED,
            "clip_s": round((duration + 0.8) / SPEED, 2)}


async def record(url: str, out: Path, width: int, height: int) -> dict:
    (out / "stills").mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        hero = await record_hero(browser, url, out, width, height)
        stills = await record_stills(browser, url, out, width, height)
        await browser.close()
    media = encode(out, hero["journey_offset_s"], hero["journey_s"])
    for item in hero["steps"]:
        item["clip_t_s"] = round(item["t_s"] / SPEED, 2)
    failed = [s["label"] for s in hero["steps"] if not s["ok"]] + [s["label"] for s in stills["stills"] if not s["ok"]]
    errors = hero["page_errors"] + stills["page_errors"]
    return {"url": url, "viewport": [width, height], **{k: hero[k] for k in ("journey_offset_s", "journey_s")},
            "steps": hero["steps"], "stills": stills["stills"], "media": media, "page_errors": errors,
            "failed": failed, "passed": not failed and not errors, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()
    port = int(args.url.rstrip("/").rsplit(":", 1)[1].split("/")[0])
    if port in PORTS_NEVER_DRIVEN:
        raise SystemExit(f"refusing port {port}: that is Zach's own dashboard or the Dashboard lane's")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = asyncio.run(record(args.url, out, args.width, args.height))
    (out / "hero.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in ("journey_s", "media", "failed", "passed", "page_errors")}, indent=2))
    for item in summary["steps"] + summary["stills"]:
        print(f"{'PASS' if item['ok'] else 'FAIL'}  {item.get('t_s', '-')!s:>6}  {item['label']}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
