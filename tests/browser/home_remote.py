"""Other machines on the home page (r3, 2026-10-09): what the page draws from the document's ``remote`` block, on a
lane or hub whose share holds another machine (e.g. scripts/remote-demo's win-a).

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_remote.py [URL]

- the summary line counts other machines' sessions apart from "live" and says each machine's "as of";
- a track another machine runs on wears that machine's name;
- with sessions under tracks on, every current remote session is a row labelled with its host, its state reads
  "as of", and its dot is never Claude's blinking "running" (that means live on this machine);
- every current remote session no track matches is its own sidebar row, with its host;
- the account menu lists the other machines with their last sync;
- 390 px: no sideways scroll.

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4484/api/plugins/vibetracks/home/. A SKIP (exit 0, loudly) when
the page is unreachable, the browser is missing, or the document has no other machine.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4484/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
failures = 0


def check(ok: bool, message: str) -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'} {message}", flush=True)
    if not ok:
        failures += 1


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=180_000)
    page.wait_for_timeout(500)


def main(argv: list[str]) -> int:
    url = argv[0] if argv else os.environ.get("VT_HOME_URL", DEFAULT_URL)
    chrome = os.environ.get("CHROME", DEFAULT_CHROME)
    if not Path(chrome).exists():
        print(f"SKIP home_remote: no browser at {chrome}")
        return 0
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:  # noqa: BLE001
        print(f"SKIP home_remote: page not reachable at {url} ({error})")
        return 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True)
        try:
            for scheme in ("dark", "light"):
                tag = f"[{scheme} 1440]"
                page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
                errors: list[str] = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.goto(url, wait_until="domcontentloaded")
                ready(page)
                doc = page.evaluate("window.__vtHomeDoc")
                if not (doc.get("remote") or {}).get("hosts"):
                    print("SKIP home_remote: the document names no other machine (is a share with another host read?)")
                    return 0
                tracks = [t for p in doc["projects"] for t in p["tracks"]]
                current = {s["id"]: (t["id"], s) for t in tracks for s in t["sessions"] if (s.get("remote") or {}).get("current")}
                summary = page.text_content('[data-testid="vt-home-remote-summary"]') or ""
                check(f"{doc['summary']['sessions_remote']} on other machines" in summary
                      and all(h["host"] in summary for h in doc["remote"]["hosts"]) and "as of" in summary,
                      f"{tag} the summary counts other machines apart, each as of its last sync · {summary!r}")
                chips = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('[data-testid="vt-home-track"]')]
                    .map((r) => [r.dataset.trackId, [...r.querySelectorAll('[data-testid="vt-host-chip"]')].map((c) => c.textContent.trim())]))""")
                wrong = [(t["id"], chips.get(t["id"]), [h["host"] for h in t.get("hosts") or []]) for t in tracks
                         if t["id"] in chips and chips[t["id"]] != [h["host"] for h in t.get("hosts") or []]]
                check(not wrong and any(chips.values()), f"{tag} each track wears the names of the machines it runs on {wrong[:3]}")
                page.click('[data-testid="vt-home-display-button"]')
                toggle = '[data-testid="vt-home-display"] [data-act="toggle"][data-id="subs"]'
                if page.get_attribute(toggle, "aria-pressed") != "true":
                    page.click(toggle)
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                rows = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-home-session"][data-host]')].map((r) => ({
                    id: r.dataset.sessionId, host: r.dataset.host, dot: (r.querySelector('.sd') || {dataset: {}}).dataset.dot,
                    state: (r.querySelector('.c-state') || {}).textContent || ''}))""")
                by_id = {r["id"]: r for r in rows}
                missing = [sid for sid in current if sid not in by_id]
                check(current and not missing, f"{tag} every current remote session is a home row ({len(current) - len(missing)} of {len(current)})")
                bad = [(r["id"], r["host"], r["dot"], r["state"]) for r in rows if r["id"] in current and
                       (r["host"] != current[r["id"]][1]["remote"]["host"] or r["dot"] == "running" or "as of" not in r["state"])]
                check(not bad, f"{tag} … labelled with its host, 'as of', never the live blink {bad[:3]}")
                other = [s for s in doc["other_sessions"] if (s.get("remote") or {}).get("current") and not s.get("projects")]
                side = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('[data-group="other"] [data-testid="vt-side-session"]')]
                    .map((r) => [r.dataset.sessionId, (r.querySelector('.host') || {}).textContent || '']))""")
                lost = [s["id"] for s in other if side.get(s["id"]) != s["remote"]["host"]]
                check(not lost, f"{tag} every current remote session on no track is a sidebar row with its host ({len(other)} expected; lost {lost[:3]})")
                page.click('[data-testid="vt-home-account"]')
                page.wait_for_selector('[data-testid="vt-home-settings"]')
                machines = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-machine"]')].map((m) => m.dataset.host)""")
                check(machines == [h["host"] for h in doc["remote"]["hosts"]], f"{tag} the account menu lists the other machines {machines}")
                check(not errors, f"{tag} no page errors {errors[:2] if errors else ''}")
                page.close()
                phone = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme=scheme, is_mobile=True, has_touch=True)
                phone.goto(url, wait_until="domcontentloaded")
                ready(phone)
                widths = phone.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth]")
                check(max(widths) <= 390, f"[{scheme} 390] no sideways scroll {widths}")
                phone.close()
        finally:
            browser.close()
    print(f"home_remote: {'FAIL (' + str(failures) + ')' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
