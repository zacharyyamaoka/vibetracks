#!/usr/bin/env python3
"""Round 3 (Review · Zen): stills, interaction proof and hero video.

    uv run --no-project --with playwright==1.55.0 python /home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/shoot_r3.py

Writes media/r3-*.webp, media/r3-hero.webm (+ .gif sibling) and media/r3-proof.json; run build.py afterwards.
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
TMP = pathlib.Path(tempfile.mkdtemp(prefix="vt-r3-"))


def webp(png, name, width=1100, q=64):
    vf = ["-vf", f"scale={width}:-1:flags=lanczos"] if width else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), *vf, "-c:v", "libwebp", "-quality", str(q), str(MEDIA / name)], check=True)


def shot(page, name, width=1100, q=64, clip=None, full=False):
    png = TMP / (name + ".png")
    page.screenshot(path=str(png), clip=clip, full_page=full)
    webp(png, name + ".webp", width, q)


def open_page(b, state, w=1440, h=900):
    page = b.new_page(viewport={"width": w, "height": h})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{APP}#{state}")
    page.wait_for_timeout(250)
    return page, errs


def state(page):
    return page.evaluate("VTP.state()")


def cur(page):
    return page.evaluate("document.querySelector('.zcard') && document.querySelector('.zcard').dataset.zitem")


def steps(page):
    return page.evaluate("[...document.querySelectorAll('.zstep')].map(b => b.className.replace('zstep ', '').trim())")


def pin(page, fx=0.55, fy=0.4, text="look here"):
    page.keyboard.press("m"); page.wait_for_timeout(80)
    box = page.locator(".zfig.lead .zmedia").bounding_box()
    page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy); page.wait_for_timeout(80)
    page.fill("#zpin-text", text); page.keyboard.press("Enter"); page.wait_for_timeout(80)


def scroll_card(page, y):
    page.evaluate(f"document.querySelector('.main').scrollTop = {y}")
    page.wait_for_timeout(80)


def main():
    proof = {"checks": {}, "widths": {}, "errors": [], "topbar": None}
    c = proof["checks"]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        # ---- entry points
        page, err = open_page(b, "r2/home/rows")
        c["sidebar_review_badge_5"] = page.locator(".side2 .zbadge").inner_text() == "5"
        shot(page, "r3-entry-home", clip={"x": 0, "y": 0, "width": 1440, "height": 560})
        page.locator("[data-act=zen][data-id=rig]").first.click(); page.wait_for_timeout(120)
        c["needs_you_row_opens_track_first_item"] = state(page)["page"] == "review" and cur(page) == "rig-T2" and page.evaluate("document.querySelectorAll('.zstep:not(.s-endbtn)').length") == 2
        c["no_sidebar_in_zen"] = page.locator(".side2").count() == 0
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        c["esc_leaves_to_home"] = state(page)["page"] == "home"
        page.locator("[data-act=zen][data-id=kinsim]").first.click(); page.wait_for_timeout(100)
        c["review_chip_opens_kinsim_first_item"] = cur(page) == "kinsim-T47"
        page.goto(f"{APP}#r2/track/grasping"); page.reload(); page.wait_for_timeout(150)
        page.click("[data-act=tab][data-id=review]"); page.wait_for_timeout(100)
        c["track_review_tab_filters_to_track"] = cur(page) == "grasp-g07" and page.evaluate("document.querySelectorAll('.zstep:not(.s-endbtn)').length") == 1
        proof["errors"] += err; page.close()

        # ---- media-first cards, triage order, options, every item (all-tracks lane)
        page, err = open_page(b, "r2/review")
        order = page.evaluate("[...document.querySelectorAll('.zgl')].map(e => e.textContent.replace(/\\s+\\d+$/, '').trim()).filter(Boolean)")
        c["triaged_order"] = order[:3] == ["Blocking now", "Waiting for you · no default", "Defaulting without you · optional"]
        c["no_ids_in_top_bar"] = page.evaluate("!/T\\d\\d/.test(document.querySelector('.zbar').innerText)")
        kinds, media_first, rec_first, labelled = [], True, True, True
        for i in range(8):
            page.evaluate(f"VTP.set({{}})"); page.click(f"[data-act=zjump][data-i='{i}']"); page.wait_for_timeout(260)
            info = page.evaluate("""(() => { const c = document.querySelector('.zcard'); const kids = [...c.children].map(e => e.className.split(' ')[0]);
              return { kids, kinds: [...c.querySelectorAll('.zfig')].map(f => [...f.classList].find(x => x.startsWith('k-'))), labels: [...c.querySelectorAll('.zfig .zsrc')].map(s => s.className.split(' ')[1]),
                first: c.querySelector('.aopt .al').textContent, recCount: c.querySelectorAll('.arec').length }; })()""")
            kinds += info["kinds"]
            media_first &= info["kids"].index("zmediaset") == 2  # eyebrow, question, then media
            rec_first &= "(Recommended)" in info["first"]
            labelled &= len(info["labels"]) == len(info["kinds"])
        c["every_card_leads_with_media"] = bool(media_first)
        c["recommended_first_and_labelled"] = bool(rec_first)
        c["every_media_labelled_real_or_illustrative"] = bool(labelled)
        c["media_kinds_image_video_chart_diff"] = all(k in kinds for k in ["k-image", "k-video", "k-chart", "k-diff"])
        proof["media_kinds"] = kinds
        for i, name in [(0, "r3-card-video"), (2, "r3-card-image"), (4, "r3-card-chart"), (3, "r3-card-diff")]:
            page.click(f"[data-act=zjump][data-i='{i}']"); page.wait_for_timeout(1300 if i == 0 else 300)
            shot(page, name)
        proof["errors"] += err; page.close()

        # ---- the flow by keys: ↵ rec, 3 other option, pin on video + image, S skip → top bar states, summary, copy
        page, err = open_page(b, "r2/review")
        page.wait_for_timeout(1500)  # let the BT1 video play so the pin lands on a real frame
        pin(page, 0.35, 0.45, "the gripper hesitates here at the belt edge")
        a = page.evaluate("VTP.state()")
        vt = page.evaluate("(() => { const s = document.querySelector('.zpins'); return s ? s.innerText : '' })()")
        c["video_pin_has_timestamp"] = " at 0:0" in vt or " at 0:1" in vt
        page.keyboard.press("Enter"); page.wait_for_timeout(400)          # T47: recommendation + a pin → "diff"
        page.keyboard.press("3"); page.wait_for_timeout(400)              # rig T2: a different option
        pin(page, 0.82, 0.55, "this diff column is the one to trust")   # mag: comment on the image
        shot(page, "r3-card-image-pinned")
        page.keyboard.press("1"); page.wait_for_timeout(400)              # mag: option 1 + pin → diff
        page.keyboard.press("Enter"); page.wait_for_timeout(400)          # T12: the recommendation → rec
        page.keyboard.press("s"); page.wait_for_timeout(300)              # T33: skipped (no default: still waits)
        page.keyboard.press("s"); page.wait_for_timeout(300)              # T11: skipped (its default applies)
        st = steps(page)
        proof["topbar"] = st
        c["topbar_shows_five_states"] = all(("s-" + k) in st for k in ["rec", "diff", "skipped", "skippedwait", "defaulting", "current"])
        c["topbar_tooltips_are_titles"] = page.evaluate("[...document.querySelectorAll('.zstep[data-i]')].slice(0, 8).every(b => b.title && !/^T\\d/.test(b.title))")
        shot(page, "r3-topbar", width=1240, clip={"x": 100, "y": 40, "width": 1240, "height": 170})
        page.click(".zstep.s-endbtn"); page.wait_for_timeout(250)
        txt = page.locator(".zendcard").inner_text()
        c["summary_decided_defaulting_back_to_agents"] = all(x in txt for x in ["You decided", "Defaulting without you", "Back to the agents"])
        page.keyboard.press("c"); page.wait_for_timeout(100)
        c["copy_all_answers"] = "Copied" in page.locator("[data-act=zcopy]").inner_text()
        shot(page, "r3-summary")
        proof["brief"] = page.evaluate("(() => { try { return null } catch (e) { return null } })()")
        proof["errors"] += err; page.close()

        # ---- board minis aligned, agent count not wrapping
        page, err = open_page(b, "r2/home/board")
        m = page.evaluate("""(() => { const s = [...document.querySelectorAll('.mini2 .ms svg')].map(e => Math.round(e.getBoundingClientRect().left)); const a = [...document.querySelectorAll('.mini2 .ma')];
          const byCol = {}; document.querySelectorAll('.mini2').forEach(m => { const k = Math.round(m.getBoundingClientRect().left); const sv = m.querySelector('.ms svg'); if (sv) (byCol[k] = byCol[k] || new Set()).add(Math.round(sv.getBoundingClientRect().left - k)); });
          return { offsets: Object.values(byCol).map(x => [...x]), wrap: a.filter(x => x.getBoundingClientRect().height > 22).length }; })()""")
        c["board_sparks_same_offset_in_every_card"] = all(len(x) == 1 for x in m["offsets"]) and len(set(x[0] for x in m["offsets"])) == 1
        c["board_agent_count_no_wrap"] = m["wrap"] == 0
        proof["board"] = m
        shot(page, "r3-board-fixed", clip={"x": 300, "y": 225, "width": 1110, "height": 420})
        proof["errors"] += err; page.close()

        # ---- phone
        for name, st_ in [("r3-phone-card", "r2/review"), ("r3-phone-image", "r2/review/mag")]:
            page, err = open_page(b, st_, 390, 844)
            page.wait_for_timeout(600)
            shot(page, name, width=None, q=62)
            proof["errors"] += err; page.close()
        page, err = open_page(b, "r2/review", 390, 844)
        page.evaluate("document.querySelector('.main').scrollTop = 620"); page.wait_for_timeout(150)
        shot(page, "r3-phone-options", width=None, q=62)
        page.close()
        for label, st_ in [("zen", "r2/review"), ("zen-rig", "r2/review/rig")]:
            for w, h in [(390, 844), (1440, 900)]:
                page, err = open_page(b, st_, w, h)
                o = page.evaluate("(() => { const m = document.querySelector('.main'); return { doc: document.documentElement.scrollWidth, vw: innerWidth, main: m.scrollWidth - m.clientWidth }; })()")
                proof["widths"][f"{label}@{w}"] = {"ok": o["doc"] <= o["vw"] and o["main"] <= 1, **o}
                page.close()
        page, err = open_page(b, "r2/review", 390, 844)
        page.click(".zstep.s-endbtn"); page.wait_for_timeout(200)
        o = page.evaluate("(() => { const m = document.querySelector('.main'); return { doc: document.documentElement.scrollWidth, vw: innerWidth, main: m.scrollWidth - m.clientWidth }; })()")
        proof["widths"]["summary@390"] = {"ok": o["doc"] <= o["vw"] and o["main"] <= 1, **o}
        page.close()

        # ---- hero: home → Review badge → Zen: ↵ rec · pick another · comment on an image · skip → summary
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(TMP / "vid"), record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(f"{APP}?rec=1#r2/home/rows"); page.wait_for_timeout(300)

        def glide(sel, pause=600, click=True, fx=None, fy=None):
            loc = page.locator(sel).first
            if page.evaluate("(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.bottom > innerHeight - 10 || r.top < 0; }", sel):
                page.evaluate("(s) => document.querySelector(s).scrollIntoView({ block: 'center', behavior: 'smooth' })", sel); page.wait_for_timeout(600)
            box = loc.bounding_box()
            x = box["x"] + (box["width"] * fx if fx is not None else min(box["width"] / 2, 50)); y = box["y"] + (box["height"] * fy if fy is not None else box["height"] / 2)
            page.mouse.move(x, y, steps=16); page.wait_for_timeout(120)
            if click:
                page.mouse.down(); page.mouse.up()
            page.wait_for_timeout(pause)

        page.mouse.move(640, 380); page.wait_for_timeout(1200)
        glide(".side2 [data-act=review]", 1800)                       # Review badge → Zen on the first blocking decision
        glide(".aopt[data-k='0']", 200, click=False)
        page.keyboard.press("Enter"); page.wait_for_timeout(1300)      # ↵ takes the recommendation
        page.wait_for_timeout(300)
        glide(".zfig.lead .zmedia", 700, click=False)                   # rig: look at the diff first
        glide(".aopt[data-k='2']", 1300)                              # rig: pick a different option
        glide("[data-act=zpinmode]", 500)                             # mag: comment on the image
        glide(".zfig.lead .zmedia", 400, fx=0.82, fy=0.5)
        page.keyboard.type("this diff column is the one to trust", delay=25); page.wait_for_timeout(300)
        page.keyboard.press("Enter"); page.wait_for_timeout(900)
        glide(".aopt[data-k='0']", 1300)                              # accept option 1 with the pin
        page.mouse.move(700, 160, steps=10); page.wait_for_timeout(500)
        glide("[data-act=zskip]", 1300)                               # T12: skip
        glide(".zstep.s-endbtn", 2400)                                # summary
        raw = page.video.path(); ctx.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf", "scale=1024:-2:flags=lanczos", "-c:v", "libvpx-vp9", "-crf", "46", "-b:v", "0", "-row-mt", "1", "-an", str(MEDIA / "r3-hero.webm")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf",
                        "fps=4,scale=560:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=48:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        str(MEDIA / "r3-hero.gif")], check=True)
        b.close()
    (MEDIA / "r3-proof.json").write_text(json.dumps(proof, indent=1))
    print("checks FAIL:", [k for k, v in c.items() if v is not True])
    print("widths FAIL:", [k for k, v in proof["widths"].items() if not v["ok"]], "errors:", proof["errors"])
    print("topbar:", proof["topbar"]); print("board:", proof["board"]); print("kinds:", proof["media_kinds"])
    print("tmp:", TMP)


if __name__ == "__main__":
    main()
