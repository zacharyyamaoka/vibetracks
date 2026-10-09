"""r3 acceptance, written before the code it checks (2026-10-09): Zach's Oct 9 feedback on the live home, measured
in headless Chromium on a running lane (dark and light, 1440 and 390 px). Each check is a measurement
(getBoundingClientRect / getComputedStyle / the document the page fetched), never DOM presence alone.

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_r3.py [URL] [--rename] [--shots DIR] [--json OUT]

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4481/api/plugins/vibetracks/home/. An unreachable URL or a
missing browser is a SKIP (exit 0, said loudly), never a pass. ``--rename`` also saves renames through the page (only
against a backend serving a SCRATCH copy of the workspace: it writes the notes, then renames them back).

What Zach asked (Daily Note, Oct 9, "# Vibe tracks feedback"):
- "I should be able to resize the side bar": drag its right edge (clamped), the width is remembered, double-click resets.
- "No need for the switching icons on the left as we already have the thing on the right": no Rows/Table/Board/Cards
  switcher in the toolbar; Display and keys 1-4 still switch; Active / Done / All tracks stay.
- "Other sessions should not be collapsed … like in claude": every session under "Other" (and a project's sessions
  on no track) is its own sidebar row, a dot and a title, no account chip; the Other header has a +; headers collapse.
- "double click to rename": a track or project name in the sidebar or the page title becomes an input with the text
  selected; Esc cancels (nothing is sent), Enter saves through the fenced write.
- "vibe tracks doesn't care about the different agent accounts … you have made agents too primary. Agents work on
  tracks": no account chips on the home or the sidebar; sessions under tracks are off by default; each track row says
  how many agents work on it; no "Sessions on no track" section on the home; the track page's tab is "Agents".
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4481/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
SIDE_DEFAULT, SIDE_MIN, SIDE_MAX = 288.0, 220.0, 480.0
results: list[dict] = []
failures = 0


def check(ok: bool, name: str, detail: str = "") -> None:
    global failures
    results.append({"ok": bool(ok), "name": name, "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}{(' · ' + detail) if detail else ''}", flush=True)
    if not ok:
        failures += 1


def skip(reason: str) -> None:
    print(f"SKIP home_r3: {reason}")
    raise SystemExit(0)


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=120_000)
    page.wait_for_timeout(500)


def side_width(page) -> float:
    return page.evaluate("document.querySelector('[data-testid=vt-home-sidebar]').getBoundingClientRect().width")


def handle_box(page) -> dict | None:
    return page.evaluate("""() => { const h = document.querySelector('[data-testid="vt-side-resize"]'); if (!h) return null;
        const r = h.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height,
        cursor: getComputedStyle(h).cursor, display: getComputedStyle(h).display}; }""")


def drag_to(page, x: float) -> None:
    box = handle_box(page)
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    for step in range(1, 9):
        page.mouse.move(box["x"] + (x - box["x"]) * step / 8, box["y"])
    page.mouse.up()
    page.wait_for_timeout(150)


def agents_text(track: dict) -> str:
    """What a track row must say about its agents: the live ones (and other machines' current ones), how many work."""

    mine = [s for s in track["sessions"] if s["live"] or (s.get("remote") or {}).get("current")]
    if not mine:
        return "no agents"
    working = sum(1 for s in mine if s["state"]["word"] == "working")
    waiting = sum(1 for s in mine if s["state"]["word"] == "needs_you")
    text = f"{len(mine)} agent{'' if len(mine) == 1 else 's'}"
    if working:
        text += f" · {working} working"
    if waiting:
        text += f" · {waiting} waiting"
    return text


def rename_input(page) -> dict | None:
    return page.evaluate("""() => { const el = document.querySelector('[data-testid="vt-rename"]'); if (!el) return null;
        return {value: el.value, start: el.selectionStart, end: el.selectionEnd, focused: document.activeElement === el,
                tag: el.tagName}; }""")


def desktop(browser, url: str, scheme: str, shots: Path | None, do_rename: bool) -> None:
    tag = f"[{scheme} 1440]"
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
    page = ctx.new_page()
    page.set_default_timeout(10_000)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(url, wait_until="domcontentloaded")
    ready(page)
    doc = page.evaluate("window.__vtHomeDoc")
    accounts = {a["id"] for a in doc["accounts"]}

    # ---------------------------------------------------------------- the toolbar: one view switcher, on the right
    try:
        stray = page.evaluate("""() => [...document.querySelectorAll('[data-act="view"]')]
            .filter((el) => !el.closest('[data-testid="vt-home-display"]')).length""")
        check(stray == 0 and page.locator(".vseg").count() == 0, f"{tag} no view switcher outside Display", f"{stray} stray view buttons")
        pills = page.evaluate("""() => [...document.querySelectorAll('[data-act="tabset"]')].map((el) => el.textContent.trim())""")
        check(pills == ["Active", "Done", "All tracks"], f"{tag} Active / Done / All tracks stay", str(pills))
        page.click('[data-testid="vt-home-display-button"]')
        page.wait_for_selector('[data-testid="vt-home-display"]')
        views = page.locator('[data-testid="vt-home-display"] [data-act="view"]').count()
        subs = page.get_attribute('[data-testid="vt-home-display"] [data-act="toggle"][data-id="subs"]', "aria-pressed")
        check(views == 4, f"{tag} Display still offers the four views", str(views))
        check(subs == "false", f"{tag} 'Show sessions under tracks' is off by default", str(subs))
        page.keyboard.press("Escape")
        seen = {}
        for key, view in (("2", "table"), ("3", "board"), ("4", "cards"), ("1", "rows")):
            page.keyboard.press(key)
            page.wait_for_timeout(120)
            seen[key] = page.get_attribute('[data-testid="vt-home-page"]', "data-view")
        check(seen == {"2": "table", "3": "board", "4": "cards", "1": "rows"}, f"{tag} keys 1-4 still switch", str(seen))

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} the toolbar: one view switcher, on the right: could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- tracks primary, agents detail
    try:
        check(page.locator('[data-testid="vt-home-session"]').count() == 0, f"{tag} no session rows under tracks by default")
        check(page.locator('[data-testid="vt-home-other-toggle"], #row-other').count() == 0,
              f"{tag} no 'Sessions on no track' section on the home")
        rows = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-home-track"]')].map((r) => ({id: r.dataset.trackId,
            agents: ((r.querySelector('[data-testid="vt-home-agents"]') || {}).textContent || '').replace(/\\s+/g, ' ').trim()}))""")
        tracks = {t["id"]: t for p in doc["projects"] for t in p["tracks"]}
        wrong = [(r["id"], r["agents"], agents_text(tracks[r["id"]])) for r in rows if r["agents"] != agents_text(tracks[r["id"]])]
        check(rows and not wrong, f"{tag} every track row says how many agents work on it", str(wrong[:3]))
        if shots:
            page.screenshot(path=str(shots / f"r3-home-{scheme}-1440.png"))

        def account_chips() -> list[str]:
            return page.evaluate("""(accounts) => [...document.querySelectorAll('[data-testid="vt-home-page"] .chip, [data-testid="vt-home-sidebar"] .chip')]
                .map((c) => c.textContent.trim()).filter((t) => accounts.includes(t))""", sorted(accounts))
        def set_subs(on: bool) -> None:
            page.click('[data-testid="vt-home-display-button"]')
            toggle = '[data-testid="vt-home-display"] [data-act="toggle"][data-id="subs"]'
            if (page.get_attribute(toggle, "aria-pressed") == "true") != on:
                page.click(toggle)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        set_subs(True)
        shown = page.locator('[data-testid="vt-home-session"]').count()
        check(shown > 0 and not account_chips(), f"{tag} no account chip on the home or the sidebar, sessions shown or not",
              f"{account_chips()[:5]} · {shown} session rows shown")
        set_subs(False)

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} tracks primary, agents detail: could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- the sidebar lists sessions like Claude
    try:
        side = page.evaluate("""() => { const out = {}; for (const el of document.querySelectorAll('[data-testid="vt-side-session"]')) {
            const g = el.closest('[data-project]') ? el.closest('[data-project]').dataset.project : (el.closest('[data-group]') || {dataset: {}}).dataset.group;
            const r = el.getBoundingClientRect(); (out[g] = out[g] || []).push({id: el.dataset.sessionId, top: r.top, h: r.height,
            color: getComputedStyle(el).color, text: el.textContent.trim(), chip: !!el.querySelector('.chip')}); } return out; }""")
        nowhere = [s["id"] for s in doc["other_sessions"] if not s.get("projects")]
        listed = {s["id"] for s in side.get("other", [])}
        check(set(nowhere) <= listed, f"{tag} every session in no project is its own row under Other",
              f"{len(set(nowhere) & listed)} of {len(nowhere)}")
        summary = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-home-sidebar"] .srow')].map((r) => r.textContent.trim())
            .filter((t) => /\\d+ sessions? (in no project|on no track)/.test(t))""")
        check(not summary, f"{tag} no folded 'N sessions …' summary row in the sidebar", str(summary[:2]))
        check(page.locator('[data-testid="vt-side-other-add"]').count() == (1 if nowhere else 0), f"{tag} the Other header carries a +")
        bad_order, missing = [], []
        for project in doc["projects"]:
            loose = [s["id"] for s in project.get("sessions_unpinned") or []]
            rows_here = {s["id"]: s for s in side.get(project["id"], [])}
            missing += [(project["id"], sid) for sid in loose if sid not in rows_here]
            last_track = page.evaluate("""(pid) => { const rows = [...document.querySelectorAll(`[data-project="${pid}"] [data-testid="vt-side-track"]`)];
                return rows.length ? rows[rows.length - 1].getBoundingClientRect().top : -1; }""", project["id"])
            bad_order += [(project["id"], sid) for sid, s in rows_here.items() if s["top"] <= last_track]
        check(not missing, f"{tag} each project's sessions on no track are listed under it", str(missing[:3]))
        check(not bad_order, f"{tag} … after its tracks", str(bad_order[:3]))
        chips = [s["id"] for g in side.values() for s in g if s["chip"]]
        heights = sorted({round(s["h"], 1) for g in side.values() for s in g})
        check(not chips and heights in ([], [26.0]), f"{tag} a session row is a dot and a title (26 px, no chip)", f"{chips[:3]} {heights}")
        track_color = page.evaluate("(document.querySelector('[data-testid=vt-side-track]') ? getComputedStyle(document.querySelector('[data-testid=vt-side-track]')).color : null)")
        loose_colors = {s["color"] for pid, g in side.items() if pid != "other" for s in g}
        check(not loose_colors or track_color not in loose_colors, f"{tag} a project's loose sessions read secondary to its tracks",
              f"track {track_color} vs loose {loose_colors}")
        if nowhere:
            page.click('[data-testid="vt-side-other"]')
            page.wait_for_timeout(150)
            closed = page.locator('[data-group="other"] [data-testid="vt-side-session"]').count()
            page.click('[data-testid="vt-side-other"]')
            page.wait_for_timeout(150)
            opened = page.locator('[data-group="other"] [data-testid="vt-side-session"]').count()
            check(closed == 0 and opened == len(listed) >= len(nowhere) > 0, f"{tag} the Other header collapses and restores",
                  f"{len(listed)} -> {closed} -> {opened}")

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} the sidebar lists sessions like Claude: could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- resize the sidebar
    try:
        box = handle_box(page)
        right = page.evaluate("document.querySelector('[data-testid=vt-home-sidebar]').getBoundingClientRect().right")
        check(box is not None and abs(box["x"] - right) <= 4 and box["cursor"] == "col-resize",
              f"{tag} a col-resize handle sits on the sidebar's right edge", str(box))
        w0 = side_width(page)
        check(abs(w0 - SIDE_DEFAULT) < 1, f"{tag} default width {SIDE_DEFAULT:g} px", f"{w0}")
        drag_to(page, box["x"] + 120)
        w1 = side_width(page)
        main_left = page.evaluate("document.querySelector('main.main').getBoundingClientRect().left")
        check(abs(w1 - (SIDE_DEFAULT + 120)) <= 2 and abs(main_left - w1) <= 2, f"{tag} dragging the edge 120 px widens it, the page follows",
              f"{w1}, main at {main_left}")
        if shots:
            page.screenshot(path=str(shots / f"r3-resized-{scheme}-1440.png"))
        page.reload(wait_until="domcontentloaded")
        ready(page)
        check(abs(side_width(page) - w1) <= 1, f"{tag} the width survives a reload", f"{side_width(page)}")
        drag_to(page, 30)
        check(abs(side_width(page) - SIDE_MIN) <= 1, f"{tag} clamped at the minimum {SIDE_MIN:g}", f"{side_width(page)}")
        drag_to(page, 1400)
        check(abs(side_width(page) - SIDE_MAX) <= 1, f"{tag} clamped at the maximum {SIDE_MAX:g}", f"{side_width(page)}")
        box = handle_box(page)
        page.mouse.dblclick(box["x"], box["y"])
        page.wait_for_timeout(150)
        check(abs(side_width(page) - SIDE_DEFAULT) < 1, f"{tag} double-click resets to {SIDE_DEFAULT:g}", f"{side_width(page)}")
        page.reload(wait_until="domcontentloaded")
        ready(page)
        check(abs(side_width(page) - SIDE_DEFAULT) < 1, f"{tag} … and the reset is remembered", f"{side_width(page)}")

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} resize the sidebar: could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- double-click to rename (Esc never writes)
    try:
        first = page.locator('[data-testid="vt-side-track"]').first
        track_id = first.get_attribute("data-track-id")
        title = tracks[track_id]["title"]
        first.dblclick()
        page.wait_for_timeout(200)
        inp = rename_input(page)
        check(inp is not None and inp["value"] == title and inp["focused"] and inp["start"] == 0 and inp["end"] == len(title),
              f"{tag} double-clicking a sidebar track opens an inline rename with the title selected", str(inp))
        if shots and inp:
            page.screenshot(path=str(shots / f"r3-rename-sidebar-{scheme}-1440.png"), clip={"x": 0, "y": 0, "width": 420, "height": 520})
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check(rename_input(page) is None and not posts, f"{tag} Esc cancels and sends nothing", f"{posts}")
        pid = doc["projects"][0]["id"]
        page.dblclick(f'[data-testid="vt-side-project"][data-project-id="{pid}"] .nm')
        page.wait_for_timeout(200)
        inp = rename_input(page)
        still_open = page.locator(f'[data-project="{pid}"] [data-testid="vt-side-track"]').count()
        check(inp is not None and inp["value"] == doc["projects"][0]["name"] and inp["start"] == 0 and inp["end"] == len(inp["value"]),
              f"{tag} double-clicking a project header renames inline", str(inp))
        check(still_open > 0, f"{tag} … without leaving the project collapsed", str(still_open))
        page.keyboard.press("Escape")
        page.goto(url + f"#/track/{track_id}", wait_until="domcontentloaded")
        ready(page)
        page.wait_for_selector('[data-testid="vt-track-page"] h1')
        page.dblclick('[data-testid="vt-track-page"] h1')
        page.wait_for_timeout(200)
        inp = rename_input(page)
        check(inp is not None and inp["value"] == title, f"{tag} double-clicking the track page title renames inline", str(inp))
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        check(not posts, f"{tag} no write was sent by any cancelled rename", str(posts))

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} double-click to rename (Esc never writes): could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- the track page's Agents tab
    try:
        label = (page.text_content('[data-testid="vt-track-tab-agents"]') or "").strip()
        check(label.startswith("Agents") and page.locator('[data-testid="vt-track-tab-sessions"]').count() == 0,
              f"{tag} the track page's tab is 'Agents'", label)
        page.click('[data-testid="vt-track-tab-agents"]')
        page.wait_for_timeout(400)
        heads = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-track-agents"] .pg-th > div')].map((d) => d.textContent.trim())""")
        want = ["Provider", "Account", "Model", "Joined by", "State", "Worked"]
        check(all(any(h.startswith(w) for h in heads) for w in want), f"{tag} the Agents tab carries the agent detail", str(heads))
        n = page.locator('[data-testid="vt-track-agent"]').count()
        check(n == len(tracks[track_id]["sessions"]), f"{tag} one Agents row per session of the track", f"{n} vs {len(tracks[track_id]['sessions'])}")
        if shots:
            page.screenshot(path=str(shots / f"r3-agents-{scheme}-1440.png"))

    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} the track page's Agents tab: could not run", f"{type(error).__name__}: {str(error)[:240]}")
    # ---------------------------------------------------------------- a real rename round trip (scratch workspace only)
    try:
        if do_rename:
            new = title + " (renamed)"
            page.dblclick('[data-testid="vt-track-page"] h1')
            page.keyboard.press("End")
            page.keyboard.type(" (renamed)")
            page.keyboard.press("Enter")
            page.wait_for_function("(t) => document.querySelector('[data-testid=vt-track-page] h1').textContent.trim() === t", arg=new, timeout=15000)
            page.wait_for_function("(a) => [...document.querySelectorAll('[data-testid=vt-side-track]')].some((r) => r.dataset.trackId === a[0] && r.textContent.includes(a[1]))",
                                   arg=[track_id, new], timeout=15000)
            check(True, f"{tag} Enter saves a track rename through the fence; the title and the sidebar follow")
            page.dblclick('[data-testid="vt-track-page"] h1')
            page.keyboard.press("Control+A")
            page.keyboard.type(title)
            page.keyboard.press("Enter")
            page.wait_for_function("(t) => document.querySelector('[data-testid=vt-track-page] h1').textContent.trim() === t", arg=title, timeout=15000)
            name = doc["projects"][0]["name"]
            page.dblclick(f'[data-testid="vt-side-project"][data-project-id="{pid}"] .nm')
            page.keyboard.press("Control+A")
            page.keyboard.type(name + " lab")
            page.keyboard.press("Enter")
            page.wait_for_function("(a) => (document.querySelector(`[data-testid=vt-side-project][data-project-id=\"${a[0]}\"] .nm`) || {}).textContent === a[1]",
                                   arg=[pid, name + " lab"], timeout=15000)
            check(True, f"{tag} Enter saves a project rename; the id stays {pid}")
            page.dblclick(f'[data-testid="vt-side-project"][data-project-id="{pid}"] .nm')
            page.keyboard.press("Control+A")
            page.keyboard.type(name)
            page.keyboard.press("Enter")
            page.wait_for_function("(a) => (document.querySelector(`[data-testid=vt-side-project][data-project-id=\"${a[0]}\"] .nm`) || {}).textContent === a[1]",
                                   arg=[pid, name], timeout=15000)
            check(len([p for p in posts if "/title" in p or "/name" in p]) == 4, f"{tag} four renames, four writes", str(posts))
    except Exception as error:  # noqa: BLE001 - a section that cannot run is a FAIL, said once
        check(False, f"{tag} a real rename round trip (scratch workspace only): could not run", f"{type(error).__name__}: {str(error)[:240]}")
    check(not errors, f"{tag} no page errors", str(errors[:3]))
    ctx.close()


def phone(browser, url: str, scheme: str, shots: Path | None) -> None:
    tag = f"[{scheme} 390]"
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url, wait_until="domcontentloaded")
    ready(page)
    widths = page.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth]")
    check(max(widths) <= 390, f"{tag} no sideways scroll", str(widths))
    page.click('[data-testid="vt-home-menu"]')
    page.wait_for_timeout(400)
    box = handle_box(page)
    check(box is None or box["display"] == "none" or box["w"] == 0, f"{tag} the drawer has no resize handle", str(box))
    if shots:
        page.screenshot(path=str(shots / f"r3-drawer-{scheme}-390.png"))
    check(not errors, f"{tag} no page errors", str(errors[:3]))
    ctx.close()


def main(argv: list[str]) -> int:
    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else None
    out_json = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    args = [a for a in argv if not a.startswith("--") and a not in {str(shots), str(out_json)}]
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    url = args[0] if args else os.environ.get("VT_HOME_URL", DEFAULT_URL)
    chrome = os.environ.get("CHROME", DEFAULT_CHROME)
    if not Path(chrome).exists():
        skip(f"no browser at {chrome}")
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:  # noqa: BLE001 - any failure to reach the lane is a skip, said loudly
        skip(f"page not reachable at {url} ({error})")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True)
        try:
            for scheme in ("dark", "light"):
                desktop(browser, url, scheme, shots, "--rename" in argv and scheme == "dark")
                phone(browser, url, scheme, shots)
        finally:
            browser.close()
    if out_json:
        out_json.write_text(json.dumps({"results": results}, indent=1))
    print(f"home_r3: {'FAIL (' + str(failures) + ')' if failures else 'PASS'} · {len(results)} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
