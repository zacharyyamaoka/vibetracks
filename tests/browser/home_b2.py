"""B2 acceptance, written before the code it checks (2026-10-09): the real home on a running lane, in headless
Chromium, dark and light, 1440 and 390 px. Every check is a measurement (getBoundingClientRect / getComputedStyle)
against Claude Desktop's own values (vibetracks/home/static/tokens.css cites where each came from) or against the
document the page itself fetched; never DOM presence alone.

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_b2.py [URL] [--shots DIR] [--json OUT]

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4392/api/plugins/vibetracks/home/. An unreachable URL or a
missing browser is a SKIP (exit 0, said loudly), never a pass.

Sidebar (Claude's language, Zach Oct 9): a track row is 26 px tall on a 28 px pitch, 13 px anthropic-sans at weight
400 in text-secondary; a group header is 12 px text-muted; the status dots are Claude's (awaiting = #fab219,
running = #898781 blinking 1.2 s, idle = a hollow ring at 50 %, error = a glyph); each project header says its
folder count; clicking it collapses the project; the Review count equals the document's; the account button sits
bottom-left and its Settings menu switches the theme.
Home: keys 1-4 switch Rows / Table / Board / Cards and the choice survives a reload; the Board puts every card in
its project's lane and its state's column; in Rows every column starts at one x on every row (project, track,
session). Every area renders without page errors and without sideways scroll at 390 px.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4392/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
CLAUDE = {  # Claude Desktop's values (tokens.css); dark = the "darker" variant Zach's Desktop renders
    "row_h": 26.0, "pitch": 28.0, "row_font": "13px", "group_font": "12px", "weight": "400",
    "ink2": {"dark": "rgb(195, 194, 183)", "light": "rgb(82, 81, 78)"},
    "muted": "rgb(137, 135, 129)",
    "side_bg": {"dark": "rgb(18, 18, 18)", "light": "rgb(255, 255, 255)"},
    "awaiting": "rgb(250, 178, 25)", "ready": "rgb(42, 120, 214)", "running": "rgb(137, 135, 129)",
}
results: list[dict] = []
failures = 0


def check(ok: bool, name: str, detail: str = "") -> None:
    global failures
    results.append({"ok": bool(ok), "name": name, "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}{(' · ' + detail) if detail else ''}", flush=True)
    if not ok:
        failures += 1


def skip(reason: str) -> None:
    print(f"SKIP home_b2: {reason}")
    raise SystemExit(0)


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=120_000)
    page.wait_for_timeout(600)


SIDEBAR_JS = """() => {
  const rows = [...document.querySelectorAll('[data-testid="vt-side-track"]')];
  const box = (e) => { const r = e.getBoundingClientRect(); return {top: r.top, left: r.left, h: r.height, w: r.width, bottom: r.bottom}; };
  const cs = (e) => getComputedStyle(e);
  const dot = (row) => { const d = row.querySelector('.sd'); const i = d && d.querySelector('i'); const s = i ? cs(i) : null;
    return {kind: d ? d.dataset.dot : null, bg: s && s.backgroundColor, border: s && s.borderTopWidth, bstyle: s && s.borderTopStyle,
            opacity: s && s.opacity, anim: s && s.animationName, dur: s && s.animationDuration, w: i ? i.getBoundingClientRect().width : null,
            glyph: !!(d && d.querySelector('svg')), glyphColor: d ? cs(d).color : null}; };
  const side = document.querySelector('[data-testid="vt-home-sidebar"]');
  const heads = [...document.querySelectorAll('[data-testid="vt-side-project"]')];
  return {
    side: side ? {box: box(side), bg: cs(side).backgroundColor} : null,
    rows: rows.map((r) => ({id: r.dataset.trackId, box: box(r), font: cs(r).fontSize, family: cs(r).fontFamily, weight: cs(r).fontWeight,
                            color: cs(r).color, mb: cs(r).marginBottom, dot: dot(r)})),
    heads: heads.map((h) => ({id: h.dataset.projectId, font: cs(h).fontSize, color: cs(h).color,
                              folders: (h.querySelector('[data-testid="vt-side-folders"]') || {}).textContent})),
    review: (document.querySelector('[data-testid="vt-side-review-count"]') || {}).textContent || null,
    acct: (() => { const a = document.querySelector('[data-testid="vt-home-account"]'); return a ? box(a) : null; })(),
    vh: innerHeight,
  };
}"""


def sidebar_checks(page, scheme: str, doc: dict) -> dict:
    m = page.evaluate(SIDEBAR_JS)
    tag = f"[{scheme} 1440]"
    check(m["side"] is not None and m["side"]["box"]["left"] >= -0.5 and m["side"]["box"]["w"] > 200, f"{tag} the sidebar is always on")
    check(m["side"]["bg"] == CLAUDE["side_bg"][scheme], f"{tag} sidebar background is Claude's", m["side"]["bg"])
    rows = m["rows"]
    active = [t for p in doc["projects"] for t in p["tracks"] if t["state"]["word"] not in ("done", "archived")]
    check({r["id"] for r in rows} == {t["id"] for t in active}, f"{tag} one sidebar row per active track", f"{len(rows)} rows")
    heights = sorted({round(r["box"]["h"], 2) for r in rows})
    check(heights == [CLAUDE["row_h"]], f"{tag} row height {CLAUDE['row_h']} px", f"measured {heights}")
    pitches = sorted({round(b["box"]["top"] - a["box"]["top"], 2) for a, b in zip(rows, rows[1:])
                      if 0 < b["box"]["top"] - a["box"]["top"] < 40})
    check(pitches == [CLAUDE["pitch"]], f"{tag} row pitch {CLAUDE['pitch']} px within a project", f"measured {pitches}")
    check({r["font"] for r in rows} == {CLAUDE["row_font"]}, f"{tag} row font {CLAUDE['row_font']}", str({r["font"] for r in rows}))
    check(all(r["family"].lower().startswith('anthropic-sans') or r["family"].startswith('"anthropic-sans"') for r in rows),
          f"{tag} rows use anthropic-sans first", rows[0]["family"] if rows else "")
    check({r["weight"] for r in rows} == {CLAUDE["weight"]}, f"{tag} row weight 400", str({r["weight"] for r in rows}))
    unselected = {r["color"] for r in rows}
    check(unselected == {CLAUDE["ink2"][scheme]}, f"{tag} row text is text-secondary", str(unselected))
    check({h["font"] for h in m["heads"]} == {CLAUDE["group_font"]} and {h["color"] for h in m["heads"]} == {CLAUDE["muted"]},
          f"{tag} group headers 12 px text-muted", str({(h["font"], h["color"]) for h in m["heads"]}))
    by_id = {t["id"]: t for t in active}
    wrong = []
    for r in rows:
        d, word = r["dot"], by_id[r["id"]]["state"]["word"]
        want = {"needs_you": "awaiting", "error": "error", "working": "running"}.get(word)
        if want and d["kind"] != want:
            wrong.append((r["id"], word, d["kind"]))
        if d["kind"] == "awaiting" and (d["bg"] != CLAUDE["awaiting"] or round(d["w"]) != 6):
            wrong.append((r["id"], "awaiting colour/size", d["bg"], d["w"]))
        if d["kind"] == "running" and (d["bg"] != CLAUDE["running"] or d["anim"] != "dframe-dot-blink" or d["dur"] != "1.2s"):
            wrong.append((r["id"], "running", d["bg"], d["anim"], d["dur"]))
        if d["kind"] == "ready" and d["bg"] != CLAUDE["ready"]:
            wrong.append((r["id"], "ready", d["bg"]))
        if d["kind"] == "idle" and (d["border"] != "1px" or d["opacity"] != "0.5" or d["bg"] not in ("rgba(0, 0, 0, 0)", "transparent")):
            wrong.append((r["id"], "idle ring", d["border"], d["opacity"], d["bg"]))
        if d["kind"] == "error" and not d["glyph"]:
            wrong.append((r["id"], "error glyph missing"))
    check(not wrong, f"{tag} every dot is Claude's for its derived state", str(wrong))
    folders = {p["id"]: len(p.get("roots") or []) for p in doc["projects"]}
    bad = [(h["id"], h["folders"]) for h in m["heads"]
           if h["folders"] != f"{folders[h['id']]} folder{'' if folders[h['id']] == 1 else 's'}"]
    check(len(m["heads"]) == len(doc["projects"]) and not bad, f"{tag} each project header shows its folder count", str(bad))
    check(folders.get("bam-robotics") == 3, f"{tag} BAM Robotics has 3 folders", str(folders.get("bam-robotics")))
    check(m["review"] == (str(doc["review"]["open"]) if doc["review"]["open"] else None), f"{tag} Review count equals the document's",
          f"{m['review']} vs {doc['review']['open']}")
    a = m["acct"]
    check(a is not None and a["left"] < 24 and m["vh"] - a["bottom"] < 24, f"{tag} the account button sits bottom-left", str(a))
    return m


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else None
    out_json = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    args = [a for a in args if a not in {str(shots), str(out_json)}]
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    url = args[0] if args else os.environ.get("VT_HOME_URL", DEFAULT_URL)
    chrome = os.environ.get("CHROME", DEFAULT_CHROME)
    if not Path(chrome).exists():
        skip(f"no browser at {chrome}")
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:  # noqa: BLE001
        skip(f"page not reachable at {url} ({error})")
    from playwright.sync_api import sync_playwright

    measured: dict = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True)
        try:
            for scheme in ("dark", "light"):
                ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.goto(url, wait_until="domcontentloaded")
                ready(page)
                doc = page.evaluate("window.__vtHomeDoc")
                measured[scheme] = sidebar_checks(page, scheme, doc)
                if shots:
                    page.screenshot(path=str(shots / f"b2-home-{scheme}-1440.png"))
                tag = f"[{scheme} 1440]"
                # collapse a project by clicking its header, and back
                pid = doc["projects"][0]["id"]
                n0 = page.locator(f'[data-project="{pid}"] [data-testid="vt-side-track"]').count()
                page.click(f'[data-testid="vt-side-project"][data-project-id="{pid}"]')
                page.wait_for_timeout(200)
                n1 = page.locator(f'[data-project="{pid}"] [data-testid="vt-side-track"]').count()
                page.click(f'[data-testid="vt-side-project"][data-project-id="{pid}"]')
                page.wait_for_timeout(200)
                n2 = page.locator(f'[data-project="{pid}"] [data-testid="vt-side-track"]').count()
                check(n0 > 0 and n1 == 0 and n2 == n0, f"{tag} clicking a project header collapses and restores it", f"{n0} -> {n1} -> {n2}")
                if scheme == "dark":
                    # keys 1-4, remembered across a reload
                    seen = {}
                    for key, view in (("2", "table"), ("3", "board"), ("4", "cards"), ("1", "rows")):
                        page.keyboard.press(key)
                        page.wait_for_timeout(150)
                        seen[key] = page.get_attribute('[data-testid="vt-home-page"]', "data-view")
                    check(seen == {"2": "table", "3": "board", "4": "cards", "1": "rows"}, f"{tag} keys 1-4 switch the four views", str(seen))
                    page.keyboard.press("3")
                    page.reload(wait_until="domcontentloaded")
                    ready(page)
                    check(page.get_attribute('[data-testid="vt-home-page"]', "data-view") == "board", f"{tag} the last view survives a reload")
                    cards = page.evaluate("""() => [...document.querySelectorAll('[data-testid="vt-home-card"]')].map((c) => {
                        const cell = c.closest('.cell'); const lane = cell.previousElementSibling; let l = cell; while (l && !l.classList.contains('lane')) l = l.previousElementSibling;
                        return {id: c.dataset.trackId, state: c.dataset.state, col: cell.dataset.col, lane: l ? l.dataset.projectId : null}; })""")
                    tracks = {t["id"]: (p["id"], t["state"]["word"]) for p in doc["projects"] for t in p["tracks"]}
                    bad = [c for c in cards if (c["lane"], c["col"]) != tracks.get(c["id"], (None, None))]
                    active = [t for t, (_p, w) in tracks.items() if w not in ("done", "archived")]
                    check(cards and not bad and {c["id"] for c in cards} == set(active),
                          f"{tag} the Board puts each card in its project's lane and its state's column", str(bad[:3]))
                    if shots:
                        page.screenshot(path=str(shots / "b2-board-dark-1440.png"))
                    page.keyboard.press("1")
                    page.wait_for_timeout(200)
                    cols = page.evaluate("""() => { const out = {}; for (const el of document.querySelectorAll('.tree .tr > div[class^="c-"]')) {
                        const k = el.className; (out[k] = out[k] || new Set()).add(Math.round(el.getBoundingClientRect().left * 10) / 10); }
                        return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, [...v]])); }""")
                    check(cols and all(len(v) == 1 for v in cols.values()), f"{tag} every Rows column starts at one x on every row", json.dumps(cols))
                    measured["columns"] = cols
                    # the account menu switches the theme
                    page.click('[data-testid="vt-home-account"]')
                    page.wait_for_selector('[data-testid="vt-home-settings"]')
                    page.click('[data-testid="vt-home-settings"] [data-act="theme"][data-id="light"]')
                    page.wait_for_timeout(200)
                    bg = page.evaluate("getComputedStyle(document.querySelector('[data-testid=vt-home-sidebar]')).backgroundColor")
                    check(page.evaluate("document.documentElement.dataset.theme") == "light" and bg == CLAUDE["side_bg"]["light"],
                          f"{tag} Settings > Theme > Light pins the light theme", bg)
                    page.evaluate("localStorage.clear()")
                # every area renders on real data
                for route, sel in (("#/review", "vt-review"), (f"#/project/{doc['projects'][0]['id']}", "vt-project-page"),
                                   ("#/track/rig", "vt-track-page")):
                    page.goto(url + route, wait_until="domcontentloaded")
                    ready(page)
                    ok = page.locator(f'[data-testid="{sel}"]').count() == 1
                    check(ok, f"{tag} {route} renders its area")
                    if route == "#/review":
                        page.wait_for_selector('[data-testid="vt-review-item"], .empty-state', timeout=60_000)
                        needs = json.loads(urllib.request.urlopen(url.rstrip('/').rsplit('/', 1)[0] + "/needs", timeout=60).read())
                        want = sum(1 for d in needs["tracks"] for it in d.get("items") or []
                                   if it["group"] in ("blocking", "no_default", "waiting", "defaulting"))
                        got = page.locator('[data-testid="vt-review-item"]').count()
                        check(got == want, f"{tag} Review lists every open decision from /needs, grouped by project", f"{got} vs {want}")
                        check(page.locator('[data-testid="vt-review-placeholder"]').count() == 1, f"{tag} Review says it is a placeholder")
                    if shots:
                        page.wait_for_timeout(1500)
                        page.screenshot(path=str(shots / f"b2-{route.strip('#/').replace('/', '-')}-{scheme}-1440.png"))
                check(not errors, f"{tag} no page errors", str(errors[:3]))
                ctx.close()

                # phone
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme, is_mobile=True, has_touch=True)
                phone = ctx.new_page()
                perr: list[str] = []
                phone.on("pageerror", lambda e, perr=perr: perr.append(str(e)))
                for route in ("", "#/review", f"#/project/{doc['projects'][0]['id']}", "#/track/rig"):
                    for view in (("rows", "board", "cards") if route == "" else ("",)):
                        phone.goto(url + route, wait_until="domcontentloaded")
                        if view:
                            phone.evaluate(f"(() => {{ const s = JSON.parse(localStorage.getItem('vt-home-ui-v1') || '{{}}'); s.view = '{view}'; localStorage.setItem('vt-home-ui-v1', JSON.stringify(s)); }})()")
                            phone.reload(wait_until="domcontentloaded")
                        ready(phone)
                        phone.wait_for_timeout(1200)
                        widths = phone.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth]")
                        check(max(widths) <= 390, f"[{scheme} 390] no sideways scroll on {route or 'home'} {view}", str(widths))
                        if shots:
                            phone.screenshot(path=str(shots / f"b2-{(route.strip('#/').replace('/', '-') or 'home')}{'-' + view if view else ''}-{scheme}-390.png"))
                check(not perr, f"[{scheme} 390] no page errors", str(perr[:3]))
                ctx.close()
        finally:
            browser.close()
    if out_json:
        out_json.write_text(json.dumps({"results": results, "measured": measured}, indent=1, default=str))
    print(f"home_b2: {'FAIL (' + str(failures) + ')' if failures else 'PASS'} · {len(results)} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
