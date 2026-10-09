"""B1 acceptance, frozen before the build (check 6, and the page half of check 1): the real home page on a running
lane, driven in headless Chromium.

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_page.py [URL] [--shots DIR]

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4392/api/plugins/vibetracks/home/ (the page through Clank's
plugin proxy on a lane). The browser is $CHROME, else the cached Playwright Chromium 1243 (Playwright 1.55's own build
is not installed on this machine). An unreachable URL or a missing browser is a SKIP (exit 0, said loudly), never a pass.

Checks, each a measurement:
- 1440 x 900: the page renders the document it fetched itself (``window.__vtHomeDoc``, schema vibetracks-home/1,
  generated within the last 5 minutes, so never a fixture); one row per active track with its derived state word
  (``data-state``); every live session in that document is on the page (``[data-session-id]``) once "Other
  sessions" is opened.
- 390 x 844 (check 6): nothing scrolls sideways (``scrollWidth <= 390``), the sidebar is off-screen, and the menu
  button opens it as a drawer inside the viewport; Escape closes it.

WHY read-only to the builder: the ruler (dispatch discipline, 2026-09-16).
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4392/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
ACTIVE = {"needs_you", "error", "stale", "working", "idle"}

failures = 0


def check(ok: bool, message: str) -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'} {message}", flush=True)
    if not ok:
        failures += 1


def skip(reason: str) -> None:
    print(f"SKIP home_page: {reason}")
    raise SystemExit(0)


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=120_000)


def rect(page, selector: str) -> dict | None:
    return page.evaluate("""(sel) => { const el = document.querySelector(sel); if (!el) return null;
        const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
        return {left: r.left, right: r.right, width: r.width, height: r.height, display: cs.display,
                visibility: cs.visibility}; }""", selector)


def visible_in_viewport(box: dict | None, width: int) -> bool:
    return bool(box) and box["display"] != "none" and box["visibility"] != "hidden" and box["width"] > 0 \
        and box["left"] >= -0.5 and box["right"] <= width + 0.5


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    shots = None
    if "--shots" in argv:
        shots = Path(argv[argv.index("--shots") + 1])
        args = [a for a in args if a != str(shots)]
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
            # ------------------------------------------------------------------ desktop
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url, wait_until="domcontentloaded")
            ready(page)
            doc = page.evaluate("window.__vtHomeDoc")
            check(isinstance(doc, dict) and doc.get("schema") == "vibetracks-home/1", "the page holds a vibetracks-home/1 document")
            age = time.time() - datetime.fromisoformat(doc["generated_at"]).timestamp()
            check(-60 < age < 300, f"the document is live, generated {age:.0f} s ago (not a fixture)")
            tracks = {t["id"]: t for p in doc["projects"] for t in p["tracks"]}
            active = {tid for tid, t in tracks.items() if t["state"]["word"] in ACTIVE}
            rows = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-home-track"]')]
                .map((el) => [el.dataset.trackId, el.dataset.state])""")
            shown = {tid: state for tid, state in rows}
            check(set(shown) == active, f"one row per active track: page {sorted(shown)} vs doc {sorted(active)}")
            wrong = {tid: (shown[tid], tracks[tid]["state"]["word"]) for tid in set(shown) & set(tracks)
                     if shown[tid] != tracks[tid]["state"]["word"]}
            check(not wrong, f"every row shows its derived state word {wrong or ''}")
            if shots:
                page.screenshot(path=str(shots / "home-1440.png"), full_page=False)
            toggle = page.query_selector('[data-testid="vt-home-other-toggle"]')
            live = {s["id"] for t in tracks.values() for s in t["sessions"] if s["live"]}
            live |= {s["id"] for s in doc["other_sessions"] if s["live"]}
            if doc["other_sessions"]:
                check(toggle is not None, "an 'Other sessions' toggle is on the page")
                if toggle is not None:
                    toggle.click()
            on_page = set(page.evaluate("() => [...document.querySelectorAll('[data-session-id]')].map((el) => el.dataset.sessionId)"))
            check(live <= on_page, f"every live session is on the page ({len(live & on_page)} of {len(live)}; missing {sorted(live - on_page)[:5]})")
            check(not errors, f"no page errors {errors[:3] if errors else ''}")
            page.close()

            # ------------------------------------------------------------------ phone (check 6)
            phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            phone.goto(url, wait_until="domcontentloaded")
            ready(phone)
            widths = phone.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth]")
            check(max(widths) <= 390, f"no sideways scroll at 390 px (scrollWidth {widths})")
            side = '[data-testid="vt-home-sidebar"]'
            check(not visible_in_viewport(rect(phone, side), 390), "the sidebar is off-screen at 390 px")
            if shots:
                phone.screenshot(path=str(shots / "home-390.png"), full_page=False)
            phone.click('[data-testid="vt-home-menu"]')
            phone.wait_for_timeout(400)
            check(visible_in_viewport(rect(phone, side), 390), f"the menu opens the sidebar as a drawer inside the viewport {rect(phone, side)}")
            widths = phone.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth]")
            check(max(widths) <= 390, f"still no sideways scroll with the drawer open (scrollWidth {widths})")
            if shots:
                phone.screenshot(path=str(shots / "home-390-drawer.png"), full_page=False)
            phone.keyboard.press("Escape")
            phone.wait_for_timeout(400)
            check(not visible_in_viewport(rect(phone, side), 390), "Escape closes the drawer")
            phone.close()
        finally:
            browser.close()
    print(f"home_page: {'FAIL (' + str(failures) + ')' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
