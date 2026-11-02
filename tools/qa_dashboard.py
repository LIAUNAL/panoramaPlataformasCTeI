"""Visual and functional QA of the CTeI landscape dashboard (Playwright + system Chrome).

Usage (with the dashboard running, e.g. `panoramaCTeI ui --no-open`):
    uv run --no-project --with playwright --with pillow python tools/qa_dashboard.py [http://localhost:8000/]
Checks, at 1440x900, 1280x720 and 390x844: the 3D constellation (centred graph, no tooltip at rest, hover label
inside the sky, panel with the top 5, controls, search and cluster filter), the map by scope, the matrix
heatmap, the search and filters, the agent runs view and the absence of JavaScript errors.
Screenshots go to a temporary folder printed at the end. Exit 1 if any check fails.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/"
OUT = Path(tempfile.mkdtemp(prefix="ctei-landscape-qa-"))
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def bright_stats(png):
    im = Image.open(io.BytesIO(png)).convert("L")
    w, h = im.size
    px = im.load()
    xs = ys = n = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            if px[x, y] > 90:
                xs += x; ys += y; n += 1
    tot = (w // 3 + 1) * (h // 3 + 1)
    return n / tot, (xs / n / w if n else -1), (ys / n / h if n else -1)


OVERLAP_JS = """(sel) => { const els=[...document.querySelectorAll(sel)].filter(e=>e.offsetParent!==null);
  const r=els.map(e=>[e.textContent.trim().slice(0,30), e.getBoundingClientRect()]); const bad=[];
  for(let i=0;i<r.length;i++)for(let j=i+1;j<r.length;j++){const a=r[i][1],b=r[j][1];
    if(a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1) bad.push(r[i][0]+' x '+r[j][0]);}
  return bad; }"""
CLIP_JS = """(sel) => [...document.querySelectorAll(sel)].filter(e=>e.offsetParent!==null && (e.scrollWidth>e.clientWidth+1))
  .map(e=>e.tagName+':'+e.textContent.trim().slice(0,30))"""


def find_sun(page, frame_el, f):
    """Hover the screen position of a sun with a top 5; return (x, y, tooltip text)."""
    box = frame_el.bounding_box()
    sb = f.evaluate("() => { const r=document.getElementById('sky').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; }")
    ox, oy = box["x"] + sb[0], box["y"] + sb[1]
    cands = f.evaluate("""() => { const ks=ATLAS.systems.filter(s=>(s.meta.top5||[]).length).map(s=>s.id+'.sun');
      const ps=viewer.project(ks); return ks.map((k,i)=>[k,ps[i]]).filter(([k,p])=>p&&p.on)
        .sort((a,b)=>Math.hypot(a[1].x-%f,a[1].y-%f)-Math.hypot(b[1].x-%f,b[1].y-%f)).slice(0,25); }"""
                       % (sb[2] / 2, sb[3] / 2, sb[2] / 2, sb[3] / 2))
    for key, p in cands:
        for dx, dy in ((0, 0), (1, 1), (-1, -1), (2, 0), (0, 2)):
            page.mouse.move(ox + p["x"] + dx, oy + p["y"] + dy)
            page.wait_for_timeout(60)
            vis = f.evaluate("() => { const t=document.querySelector('.atlas-tip'); return t && t.style.display==='block' ? t.textContent : null; }")
            if vis:
                return ox + p["x"] + dx, oy + p["y"] + dy, vis
    return None


def tab(page, name, wait=600):
    page.click(f"nav button[data-view='{name}']")
    page.wait_for_timeout(wait)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=False, args=["--window-position=4000,4000"])
    for vw, vh in [(1440, 900), (1280, 720), (390, 844)]:
        tag = f"{vw}x{vh}"
        page = b.new_page(viewport={"width": vw, "height": vh})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(BASE + "#constelacion")
        page.wait_for_timeout(3500)
        land = page.evaluate("() => ({n: ITEMS.length, ids: ITEMS.map(i => i.id), scopes: SCOPES})")
        check(f"{tag} landscape has entries", land["n"] > 1, str(land["n"]))
        # -- constellation
        frame_el = page.locator("#frame3d")
        f = page.frames[1]
        fb = frame_el.bounding_box()
        check(f"{tag} constellation visible in first screen", fb and fb["y"] < vh * .45 and fb["height"] > 360,
              f"y={fb and round(fb['y'])} h={fb and round(fb['height'])}")
        sb = f.evaluate("() => { const r=document.getElementById('sky').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; }")
        check(f"{tag} sky taller than 280px", sb[3] > 280, str(round(sb[3])))
        f.evaluate("() => viewer.rotate(false)")
        page.wait_for_timeout(400)
        frac, cx, cy = bright_stats(f.locator("#sky").screenshot())
        check(f"{tag} graph drawn (bright pixels)", frac > 0.005, f"{frac:.3f}")
        check(f"{tag} graph centred", .3 < cx < .7 and .25 < cy < .75, f"cx={cx:.2f} cy={cy:.2f}")
        frame_el.screenshot(path=OUT / f"sky_{tag}.png")
        tipvis = f.evaluate("() => { const t=document.querySelector('.atlas-tip'); return t ? t.style.display + ' ' + t.textContent : 'none'; }")
        check(f"{tag} no tooltip at rest", tipvis.split(" ")[0] in ("none", ""), tipvis)
        names = f.evaluate("() => [...document.querySelectorAll('.atlas-names div')].filter(d => d.style.display !== 'none').length")
        check(f"{tag} no labels at rest", names == 0, str(names))
        check(f"{tag} toolbar controls do not overlap", not f.evaluate(OVERLAP_JS, "#toolbar > *"), str(f.evaluate(OVERLAP_JS, "#toolbar > *")))
        check(f"{tag} toolbar text not clipped", not f.evaluate(CLIP_JS, "#toolbar button, #toolbar select"), str(f.evaluate(CLIP_JS, "#toolbar button, #toolbar select")))
        check(f"{tag} no horizontal scroll in frame", f.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
        hit = find_sun(page, frame_el, f)
        check(f"{tag} hover shows short label", hit and 3 < len(hit[2]) <= 90, hit and hit[2])
        if hit:
            tb = f.evaluate("() => { const t=document.querySelector('.atlas-tip').getBoundingClientRect(), s=document.getElementById('sky').getBoundingClientRect(); return [t.left-s.left, s.right-t.right, t.top-s.top]; }")
            check(f"{tag} hover label inside sky", min(tb) >= 0, str([round(v) for v in tb]))
            page.mouse.click(hit[0], hit[1])
            page.wait_for_timeout(600)
            side = f.evaluate("""() => { const s=document.getElementById('side');
              return {open:s.classList.contains('open'), h3:(s.querySelector('h3')||{}).textContent,
                      top:s.querySelectorAll('ol.top5 li').length, want: selected && (SYSTEMS.get(selected.split('.')[0]).meta.top5||[]).length,
                      sel: selected, keep: selectedKeep && selectedKeep.size, sx:s.scrollWidth-s.clientWidth}; }""")
            check(f"{tag} click opens panel with main info", side["open"] and side["h3"], json.dumps(side, ensure_ascii=False)[:160])
            check(f"{tag} panel lists the top 5", side["top"] == side["want"] and 1 <= side["top"] <= 5, f"{side['top']} of {side['want']}")
            check(f"{tag} click lights node and connections", side["keep"] and side["keep"] > 5, str(side["keep"]))
            check(f"{tag} panel has no horizontal overflow", side["sx"] <= 1, str(side["sx"]))
            check(f"{tag} panel sections do not overlap", not f.evaluate(OVERLAP_JS, "#side h3, #side h4, #side p, #side li"), "")
            page.screenshot(path=OUT / f"selected_{tag}.png")
            f.locator("#side ol.top5 li button").first.click()
            page.wait_for_timeout(1200)
            sel2 = f.evaluate("() => selected")
            check(f"{tag} top-5 entry selects that system", sel2 and sel2.endswith(".sun") and sel2 != side["sel"], str(sel2))
            page.keyboard.press("Escape")
            check(f"{tag} Escape closes panel", not f.evaluate("() => document.getElementById('side').classList.contains('open')"))
        f.locator("#autorotate").click(); on1 = f.evaluate("() => viewer.rotating()")
        f.locator("#autorotate").click(); on2 = f.evaluate("() => viewer.rotating()")
        check(f"{tag} rotation toggles", on1 != on2, f"{on1}->{on2}")
        f.locator("#grouplayout").click(); page.wait_for_timeout(1200)
        check(f"{tag} group layout on", f.evaluate("() => viewer.layout()") == "groups")
        f.locator("#grouplayout").click(); page.wait_for_timeout(1200)
        f.select_option("#famselect", index=1)
        check(f"{tag} cluster filter applies", f.evaluate("() => activeFam") is not None)
        target = land["ids"][len(land["ids"]) // 2]
        f.fill("#find", target); f.press("#find", "Enter"); page.wait_for_timeout(300)
        check(f"{tag} constellation search selects {target}", f.evaluate("() => selected") == target + ".sun")
        f.locator("#zoomreset").click()
        check(f"{tag} reset clears selection and filter", f.evaluate("() => selected === null && activeFam === null"))
        for bid in ["zoomin", "zoomout", "spinleft", "spinright", "tiltup", "tiltdown"]:
            f.locator("#" + bid).click()
        # -- map by scope
        tab(page, "mapa")
        regions = page.evaluate("""() => [...document.querySelectorAll('#map .region')].map(r => ({scope: r.dataset.scope,
            n: +r.querySelector('h3 .n').textContent, cards: r.querySelectorAll('.mini').length,
            w: r.getBoundingClientRect().width}))""")
        check(f"{tag} map has the four scopes", [r["scope"] for r in regions] == land["scopes"], str([r["scope"] for r in regions]))
        check(f"{tag} map counts add up to the entries", sum(r["n"] for r in regions) == land["n"] and all(r["n"] == r["cards"] for r in regions),
              str([(r["scope"], r["n"], r["cards"]) for r in regions]))
        check(f"{tag} map columns readable (>= 220px)", all(r["w"] >= 220 for r in regions), str([round(r["w"]) for r in regions]))
        check(f"{tag} map has no horizontal scroll", page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
        page.click("#maptype button[data-t='plataforma']"); page.wait_for_timeout(200)
        plat = page.evaluate("() => [...document.querySelectorAll('#map .mini')].length")
        want = page.evaluate("() => ITEMS.filter(i => i.tipo === 'plataforma').length")
        check(f"{tag} map type filter", plat == want, f"{plat} vs {want}")
        page.click("#maptype button[data-t='']")
        page.screenshot(path=OUT / f"map_{tag}.png", full_page=False)
        page.locator("#map .mini").first.click(); page.wait_for_timeout(200)
        check(f"{tag} map card opens the ficha", page.evaluate("() => !document.getElementById('drawer').hidden"))
        page.keyboard.press("Escape")
        # -- matrix
        tab(page, "matriz")
        mat = page.evaluate("""() => ({rows: document.querySelectorAll('#matrix tbody td.l').length,
            groups: document.querySelectorAll('#matrix th.group').length, filled: document.querySelectorAll('#matrix td.c:not(.z)').length})""")
        check(f"{tag} matrix renders actor, service and interaction rows", mat["groups"] == 3 and mat["rows"] > 3 and mat["filled"] > 3, str(mat))
        page.locator("#matrix td.c:not(.z)").first.click(); page.wait_for_timeout(200)
        check(f"{tag} matrix cell lists its fichas", page.evaluate("() => document.querySelectorAll('#cellinfo li').length") >= 1)
        page.screenshot(path=OUT / f"matrix_{tag}.png")
        # -- search and filters
        tab(page, "explorar")
        total = page.evaluate("() => document.querySelectorAll('#list .row').length")
        page.fill("#q", "convocatorias"); page.wait_for_timeout(200)
        hits = page.evaluate("() => document.querySelectorAll('#list .row').length")
        check(f"{tag} search narrows the list", 0 < hits < total, f"{hits} of {total}")
        page.fill("#q", "")
        page.select_option("#fscope", "bogota"); page.wait_for_timeout(200)
        bog = page.evaluate("() => document.querySelectorAll('#list .row').length")
        check(f"{tag} scope filter", bog == next(r["n"] for r in regions if r["scope"] == "bogota"), str(bog))
        page.select_option("#fscope", "")
        # -- other views draw without errors
        for name in ("ideas", "sistema", "tiempo", "corridas"):
            tab(page, name, 900)
        check(f"{tag} cluster cards render", page.evaluate("() => document.querySelectorAll('#cards .card').length") >= 1)
        check(f"{tag} runs view renders", page.evaluate("() => document.querySelector('#runs').childElementCount") >= 1)
        check(f"{tag} no JS errors", not errors, "; ".join(errors)[:200])
        page.close()
    b.close()

fails = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - len(fails)}/{len(results)} passed · screenshots in {OUT}")
sys.exit(1 if fails else 0)
