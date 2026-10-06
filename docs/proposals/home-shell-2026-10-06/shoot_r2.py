#!/usr/bin/env python3
"""Round 2: stills, alignment measurement, interaction proof and hero video for the consolidated shell.

    uv run --no-project --with playwright==1.55.0 python /home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/shoot_r2.py

Writes media/r2-*.webp, media/r2-hero.webm and media/r2-proof.json; run build.py afterwards.
"""
import json
import pathlib
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
MEDIA = HERE / "media"
APP = f"file://{HERE / 'app.html'}"
CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="vt-r2-"))

# Sparkline lefts, per set. Rounded to 0.1 px; "spread" = max - min within the set.
MEASURE = """(sel) => { const out = {}; for (const [k, q] of Object.entries(sel)) {
  const xs = [...document.querySelectorAll(q)].map(e => Math.round(e.getBoundingClientRect().left * 10) / 10);
  out[k] = { n: xs.length, lefts: xs, spread: xs.length ? Math.round((Math.max(...xs) - Math.min(...xs)) * 10) / 10 : null }; } return out; }"""
# Draw a thin red tick at each sparkline's left edge so the before/after stills show the drift.
MARK = """(q) => { document.querySelectorAll(q).forEach(e => { const r = e.getBoundingClientRect(); const m = document.createElement('div');
  m.style.cssText = `position:fixed;left:${r.left - 1}px;top:${r.top - 4}px;width:2px;height:${r.height + 8}px;background:#e03e3e;z-index:99;pointer-events:none`;
  document.body.appendChild(m); }); }"""


def webp(png, name, width=1100, q=62):
    vf = ["-vf", f"scale={width}:-1:flags=lanczos"] if width else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), *vf, "-c:v", "libwebp", "-quality", str(q), str(MEDIA / name)], check=True)


def shot(page, name, width=1100, q=62, clip=None):
    png = TMP / (name + ".png")
    page.screenshot(path=str(png), clip=clip)
    webp(png, name + ".webp", width, q)


def open_page(browser, state, w=1440, h=900, rec=False):
    page = browser.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{APP}{'?rec=1' if rec else ''}#{state}")
    page.wait_for_timeout(200)
    return page, errors


def main():
    proof = {"alignment": {}, "checks": {}, "widths": {}, "errors": []}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        # ---- alignment: before (round-1 V1) and after (round 2)
        page, err = open_page(b, "v1/home")
        proof["alignment"]["before_v1_rows"] = page.evaluate(MEASURE, {"track_rows": ".trow .c-spark svg", "project_headers": ".prow .pspark svg", "all": ".trow .c-spark svg, .prow .pspark svg"})
        page.evaluate(MARK, ".trow .c-spark svg, .prow .pspark svg")
        shot(page, "r2-align-before", clip={"x": 120, "y": 180, "width": 1200, "height": 560})
        page.close()
        page, err = open_page(b, "r2/home/rows")
        sel = {"track_rows": ".atrack .c-spark svg", "project_headers": ".aproj .c-spark svg", "all": ".arow .c-spark svg"}
        proof["alignment"]["after_r2_rows"] = page.evaluate(MEASURE, sel)
        page.evaluate(MARK, ".arow .c-spark svg")
        shot(page, "r2-align-after", clip={"x": 290, "y": 220, "width": 1150, "height": 560})
        page.click("[data-act=scale]"); page.wait_for_timeout(150)
        proof["alignment"]["after_r2_rows_10_projects"] = page.evaluate(MEASURE, sel)
        page.close()
        page, err = open_page(b, "r2/project/bam")
        proof["alignment"]["after_r2_project_page"] = page.evaluate(MEASURE, {"track_rows": ".atrack .c-spark svg"})
        page.close()
        page, err = open_page(b, "r2/home/rows", w=1180, h=800)
        proof["alignment"]["after_r2_rows_at_1180px"] = page.evaluate(MEASURE, sel)
        page.close()

        # ---- stills
        for v in ["rows", "table", "board", "cards"]:
            page, err = open_page(b, f"r2/home/{v}")
            shot(page, f"r2-{v}")
            proof["errors"] += err
            page.close()
        page, err = open_page(b, "r2/track/grasping")
        page.locator("h2.h2bar").scroll_into_view_if_needed()
        page.evaluate("document.querySelector('.main').scrollTop = document.querySelector('h2.h2bar').offsetTop - 20")
        page.wait_for_timeout(100)
        shot(page, "r2-kpi-cards", clip={"x": 290, "y": 0, "width": 1130, "height": 330})
        page.click("[data-act=kpiview][data-id=rows]"); page.wait_for_timeout(100)
        page.evaluate("document.querySelector('.main').scrollTop = document.querySelector('h2.h2bar').offsetTop - 20")
        shot(page, "r2-kpi-rows", clip={"x": 290, "y": 0, "width": 1130, "height": 330})
        page.close()
        page, err = open_page(b, "r2/track/rig")
        page.click("[data-act=acct]"); page.wait_for_timeout(100)
        shot(page, "r2-acctmenu")
        page.close()
        page, err = open_page(b, "r2/settings")
        shot(page, "r2-settings")
        page.close()
        for name, state in [("r2-phone-home", "r2/home/rows"), ("r2-phone-track", "r2/track/grasping"), ("r2-phone-board", "r2/home/board")]:
            page, err = open_page(b, state, 390, 844)
            shot(page, name, width=None, q=60)
            page.close()
        page, err = open_page(b, "r2/home/rows", 390, 844)
        page.click("[data-act=burger]"); page.wait_for_timeout(250)
        shot(page, "r2-phone-drawer", width=None, q=60)
        page.close()

        # ---- interaction proof (real keys / clicks, read back from the DOM)
        c = proof["checks"]
        page, err = open_page(b, "r2/home/rows")
        c["sidebar_on_home_by_default"] = page.locator(".side2:not(.side-off)").count() == 1 and page.locator(".side2").is_visible()
        c["no_sparklines_in_sidebar"] = page.locator(".side2 svg path[stroke='#9b9a97']").count() == 0
        page.mouse.move(800, 400)
        for key, v in zip("2341", ["table", "board", "cards", "rows"]):
            page.keyboard.press(key); page.wait_for_timeout(80)
            c[f"key_{key}_{v}"] = page.evaluate("VTP.state().homeView") == v and page.locator(f"[data-act=hview][data-id={v}].on").count() == 1
        page.click("[data-act=hview][data-id=board]")
        page.reload(); page.wait_for_timeout(150)
        page.goto(f"{APP}"); page.wait_for_timeout(150)
        c["remembers_last_view_after_reload"] = page.evaluate("VTP.state().homeView") == "board"
        c["board_is_state_x_project_swimlanes"] = page.locator(".swim").count() == 1 and page.locator(".swim .sh2").count() == 5 + 1 + 6
        page.click("[data-act=acct]"); page.wait_for_timeout(80)
        c["account_menu_opens_bottom_left"] = page.locator(".acctmenu").count() == 1 and page.evaluate("(() => { const r = document.querySelector('.acctbtn').getBoundingClientRect(); return r.left < 40 && r.bottom > innerHeight - 60; })()")
        page.mouse.click(900, 120); page.wait_for_timeout(80)
        c["account_menu_closes_on_outside_click"] = page.locator(".acctmenu").count() == 0
        page.click("[data-act=acct]"); page.click(".acctmenu [data-act=settings]"); page.wait_for_timeout(80)
        c["menu_settings_opens_settings"] = page.evaluate("VTP.state().page") == "settings"
        page.click("[data-act=home]"); page.wait_for_timeout(80)
        page.keyboard.press("Control+Comma"); page.wait_for_timeout(80)
        c["ctrl_comma_opens_settings"] = page.evaluate("VTP.state().page") == "settings"
        page.click("[data-act=set][data-k=alwaysSidebar]"); page.click("[data-act=home]"); page.wait_for_timeout(80)
        c["setting_off_hides_sidebar_on_home"] = not page.locator(".side2").is_visible()
        page.locator("main [data-act=project][data-id=bam]").first.click(); page.wait_for_timeout(80)
        c["setting_off_sidebar_back_on_drill_in"] = page.locator(".side2").is_visible()
        page.keyboard.press("Control+Comma"); page.click("[data-act=set][data-k=alwaysSidebar]")
        page.locator(".side2 [data-act=track][data-id=grasping]").click(); page.wait_for_timeout(80)
        c["kpi_cards_default"] = page.locator(".multi .mcell").count() == 4
        page.keyboard.press("k"); page.wait_for_timeout(80)
        c["key_k_kpi_rows"] = page.locator("table.kpit tbody tr").count() == 4
        c["kpi_rows_trend_column_aligned"] = page.evaluate("new Set([...document.querySelectorAll('table.kpit td:nth-child(4) svg')].map(e => Math.round(e.getBoundingClientRect().left))).size") == 1
        page.click("[data-act=kpiview][data-id=cards]"); page.wait_for_timeout(80)
        c["kpi_toggle_click_back_to_cards"] = page.locator(".multi .mcell").count() == 4
        c["review_seam_tab"] = page.locator("[data-act=tab][data-id=review]").count() == 1
        page.click("[data-act=tab][data-id=review]"); page.wait_for_timeout(80)
        c["review_seam_tab_body"] = page.locator(".seam").count() == 1
        page.click(".side2 [data-act=review]"); page.wait_for_timeout(80)
        c["review_seam_sidebar_page"] = page.evaluate("VTP.state().page") == "review" and page.locator(".seam").count() == 1
        proof["errors"] += err
        page.close()
        for label, state in [("rows", "r2/home/rows"), ("table", "r2/home/table"), ("board", "r2/home/board"), ("cards", "r2/home/cards"), ("project", "r2/project/bam"), ("track", "r2/track/grasping"), ("settings", "r2/settings")]:
            for w, h in [(390, 844), (1440, 900)]:
                page, err = open_page(b, state, w, h)
                o = page.evaluate("(() => { const m = document.querySelector('.main'); return { doc: document.documentElement.scrollWidth, vw: innerWidth, main: m.scrollWidth - m.clientWidth }; })()")
                proof["widths"][f"{label}@{w}"] = {"ok": o["doc"] <= o["vw"] and o["main"] <= 1, **o}
                proof["errors"] += err
                page.close()

        # ---- hero: rows → table → board → cards → project → track → KPI rows → account menu → Settings
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(TMP / "vid"), record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(f"{APP}?rec=1#r2/home/rows"); page.wait_for_timeout(300)

        def glide(sel, pause=700, nth=0):
            box = page.locator(sel).nth(nth).bounding_box()
            page.mouse.move(box["x"] + min(box["width"] / 2, 50), box["y"] + box["height"] / 2, steps=16)
            page.wait_for_timeout(110); page.mouse.down(); page.mouse.up(); page.wait_for_timeout(pause)

        page.mouse.move(700, 420); page.wait_for_timeout(1300)
        glide("[data-act=hview][data-id=table]", 1300)
        glide("[data-act=hview][data-id=board]", 1500)
        glide("[data-act=hview][data-id=cards]", 1300)
        glide("[data-act=hview][data-id=rows]", 700)
        glide("main [data-act=project][data-id=bam]", 1600)
        glide(".side2 [data-act=track][data-id=grasping]", 1100)
        glide("[data-act=kpiview][data-id=rows]", 1200)
        glide("[data-act=kpiview][data-id=cards]", 600)
        glide("[data-act=acct]", 1300)
        glide(".acctmenu [data-act=settings]", 1800)
        raw = page.video.path(); ctx.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf", "scale=1024:-2:flags=lanczos", "-c:v", "libvpx-vp9", "-crf", "47", "-b:v", "0", "-row-mt", "1", "-an", str(MEDIA / "r2-hero.webm")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf",
                        "fps=4,scale=560:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=32:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        str(MEDIA / "r2-hero.gif")], check=True)
        b.close()
    (MEDIA / "r2-proof.json").write_text(json.dumps(proof, indent=1))
    a = proof["alignment"]
    for k, v in a.items():
        print(k, {s: (x["n"], x["spread"], sorted(set(x["lefts"]))[:6]) for s, x in v.items()})
    print("checks FAIL:", [k for k, x in proof["checks"].items() if x is not True])
    print("widths FAIL:", [k for k, x in proof["widths"].items() if not x["ok"]], "errors:", proof["errors"])
    print("tmp:", TMP)


if __name__ == "__main__":
    main()
