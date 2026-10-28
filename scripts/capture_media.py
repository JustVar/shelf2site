"""Capture the README screenshots, feature clips and the proof walkthrough.

Needs a running app with freshly seeded demo data (scripts/seed_demo.py),
Playwright with a Chromium build, and ffmpeg on PATH. None of these are app
dependencies:

    pip install playwright && python -m playwright install chromium
    python -m scripts.seed_demo
    python -m scripts.capture_media --what shots      # docs/media/screenshots/
    python -m scripts.capture_media --what clips      # docs/media/clips/
    python -m scripts.capture_media --what proof      # docs/media/proof/

The clips and the proof walkthrough change data (they create and move
orders), so re-seed before each of those runs. Every name, site and serial
on screen comes from the demo data and is invented.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

DEMO_USER, DEMO_PASSWORD = "demo", "harbor-lantern-quilt-42"
DESKTOP = {"width": 1440, "height": 900}
VIDEO = {"width": 1600, "height": 1000}
PHONE = {"width": 390, "height": 844}

# Injected into every page while recording: a caption bar the script writes
# to, and a visible pointer with a click ring, since recordings carry neither.
OVERLAY_JS = r"""
(() => {
  function mount() {
    if (document.getElementById('s2s-cap')) return;
    const st = document.createElement('style');
    st.textContent = `
      #s2s-cap { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
        max-width: 78%; padding: 12px 22px; border-radius: 12px; z-index: 2147483646;
        background: rgba(10, 22, 30, 0.88); color: #fff; font: 600 19px/1.4 Inter, system-ui, sans-serif;
        border-left: 5px solid #1690BC; box-shadow: 0 10px 30px rgba(0,0,0,.35);
        transition: opacity .25s; pointer-events: none; text-align: left; }
      #s2s-cap small { display: block; font-weight: 500; font-size: 14px; opacity: .8; margin-top: 2px; }
      #s2s-cap:empty { opacity: 0; }
      #s2s-ptr { position: fixed; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
        border: 2px solid #fff; background: rgba(22,144,188,.55); box-shadow: 0 0 0 2px rgba(0,0,0,.35);
        z-index: 2147483646; pointer-events: none; transition: transform .12s; left: -50px; top: -50px;
        will-change: left, top; }
      #s2s-ptr.down { transform: scale(.7); background: rgba(79,195,234,.95); }
      #s2s-card { position: fixed; inset: 0; z-index: 2147483647; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 18px; background: #0B1A22; color: #EAF2F5;
        font: 600 22px Inter, system-ui, sans-serif; text-align: center; }
      #s2s-card h1 { font: 700 54px 'Space Grotesk', Inter, sans-serif; margin: 0; letter-spacing: -0.02em; color: #EAF2F5; }
      #s2s-card p { color: #EAF2F5; }
      #s2s-card p { margin: 0; opacity: .8; font-weight: 500; }`;
    document.documentElement.appendChild(st);
    const cap = document.createElement('div'); cap.id = 's2s-cap';
    cap.innerHTML = sessionStorage.getItem('s2s-cap') || '';
    document.documentElement.appendChild(cap);
    const ptr = document.createElement('div'); ptr.id = 's2s-ptr';
    const last = (sessionStorage.getItem('s2s-ptr') || '-50,-50').split(',');
    ptr.style.left = last[0] + 'px'; ptr.style.top = last[1] + 'px';
    document.documentElement.appendChild(ptr);
    addEventListener('mousemove', e => { ptr.style.left = e.clientX + 'px'; ptr.style.top = e.clientY + 'px';
      sessionStorage.setItem('s2s-ptr', e.clientX + ',' + e.clientY); }, true);
    addEventListener('mousedown', () => ptr.classList.add('down'), true);
    addEventListener('mouseup', () => ptr.classList.remove('down'), true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
  window.__s2sCaption = (html) => { sessionStorage.setItem('s2s-cap', html);
    const c = document.getElementById('s2s-cap'); if (c) c.innerHTML = html; };
})();
"""

# Keeps a handle on the map so a recording can find a cluster or a unit on the
# canvas: maplibre draws them as pixels, not as elements a selector can reach.
MAP_HOOK_JS = r"""
(() => {
  let lib;
  Object.defineProperty(window, 'maplibregl', { configurable: true, get() { return lib; }, set(v) {
    if (v && v.Map && !v.__s2s) {
      const Base = v.Map;
      v.Map = class extends Base { constructor(...a) { super(...a); window.__s2sMap = this; } };
      v.__s2s = true;
    }
    lib = v;
  } });
})();
"""


class Driver:
    """A page plus the small vocabulary the recordings are written in."""

    def __init__(self, page, base):
        self.p = page
        self.base = base
        self.x, self.y = 800.0, 520.0          # where the drawn pointer is now

    def glide(self, x, y):
        """Move the pointer to (x, y) the way a hand would: eased, one small
        step per frame. Playwright's own steps all land within a frame or two,
        which the recording shows as a jump or a stutter."""
        import math
        dist = math.hypot(x - self.x, y - self.y)
        if dist < 1:
            return
        frames = max(10, min(42, int(dist / 22)))
        x0, y0 = self.x, self.y
        for i in range(1, frames + 1):
            t = i / frames
            e = t * t * (3 - 2 * t)
            self.p.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.p.wait_for_timeout(16)
        self.x, self.y = x, y

    def go(self, path, wait=1600):
        self.p.goto(self.base + path)
        self.settle(wait)

    def settle(self, ms=1200):
        # The pages hold an open event stream, so "network idle" never comes.
        self.p.wait_for_load_state("load")
        self.p.wait_for_timeout(ms)
        self.p.evaluate("document.querySelectorAll('.tour-overlay,.tour-tooltip,.tour-spotlight').forEach(e => e.remove())")

    def caption(self, title, sub=""):
        html = title + (f"<small>{sub}</small>" if sub else "")
        self.p.evaluate("h => window.__s2sCaption && window.__s2sCaption(h)", html)

    def point(self, selector, nth=0):
        loc = self.p.locator(selector).nth(nth)
        loc.wait_for(state="visible")
        in_view = loc.evaluate("e => { const r = e.getBoundingClientRect();"
                               " return r.top >= 70 && r.bottom <= innerHeight - 110; }")
        if not in_view:   # scroll smoothly first, so the page never jumps under the pointer
            loc.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
            self.p.wait_for_timeout(750)
        box = loc.bounding_box()
        self.glide(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return loc

    def click(self, selector, nth=0, pause=500):
        self.point(selector, nth)
        self.p.wait_for_timeout(220)
        self.press()
        self.p.wait_for_timeout(pause)

    def press(self):
        """Click where the pointer already is, so nothing moves it first."""
        self.p.mouse.down()
        self.p.wait_for_timeout(90)
        self.p.mouse.up()

    # The map --------------------------------------------------------------

    def map_ready(self):
        self.p.wait_for_function("() => window.__s2sMap && window.__s2sMap.loaded()"
                                 " && window.__s2sMap.getSource('units')", timeout=20000)
        self.map_idle()

    def map_idle(self, extra=500):
        self.p.wait_for_function("() => !window.__s2sMap.isMoving() && window.__s2sMap.loaded()",
                                 timeout=20000)
        self.p.wait_for_timeout(extra)

    def map_spot(self, layer, pick="biggest", match=None):
        """Page coordinates of a cluster or unit on the canvas."""
        return self.p.evaluate("""([layer, pick, match]) => {
            const m = window.__s2sMap, c = m.getCanvas(), r = c.getBoundingClientRect();
            // The app zooms the body (main.css), so canvas pixels and page
            // pixels differ by that factor.
            const k = r.width / c.clientWidth, w = c.clientWidth, h = c.clientHeight;
            let fs = m.queryRenderedFeatures({layers: [layer]});
            if (match) fs = fs.filter(f => Object.entries(match).every(([kk, v]) => f.properties[kk] === v));
            fs = fs.map(f => ({f, pt: m.project(f.geometry.coordinates)}))
                   .filter(o => o.pt.x > 40 && o.pt.y > 40 && o.pt.x < w - 40 && o.pt.y < h - 40);
            if (!fs.length) return null;
            if (pick === 'biggest') fs.sort((a, b) => (b.f.properties.point_count || 0) - (a.f.properties.point_count || 0));
            return [r.left + fs[0].pt.x * k, r.top + fs[0].pt.y * k];
        }""", [layer, pick, match])

    def map_click(self, layer, pick="biggest", match=None, pause=900):
        self.map_idle(0)
        spot = self.map_spot(layer, pick, match)
        if not spot:
            raise SystemExit(f"nothing on the map layer {layer} to click")
        self.glide(*spot)
        self.p.wait_for_timeout(260)
        self.map_idle(0)
        self.press()
        self.p.wait_for_timeout(pause)

    def type(self, selector, text):
        self.click(selector, pause=150)
        self.p.locator(selector).fill("")
        self.p.keyboard.type(text, delay=45)

    def scroll_to(self, selector, wait=900):
        self.p.locator(selector).first.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'start'})")
        self.p.wait_for_timeout(wait)

    def scroll_top(self, wait=700):
        self.p.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        self.p.wait_for_timeout(wait)

    def card(self, title, sub, ms=2600):
        self.p.evaluate("""([t, s]) => { const c = document.createElement('div'); c.id = 's2s-card';
            c.innerHTML = '<div style="width:96px;height:96px">' + (document.querySelector('.brand-mark') ?
              document.querySelector('.brand-mark').outerHTML.replace(/width="\\d+"/, 'width="96"').replace(/height="\\d+"/, 'height="96"') : '') +
              '</div><h1>' + t + '</h1><p>' + s + '</p>';
            document.documentElement.appendChild(c); }""", [title, sub])
        self.p.wait_for_timeout(ms)
        self.p.evaluate("document.getElementById('s2s-card') && document.getElementById('s2s-card').remove()")


def login(page, base):
    page.goto(base + "/login")
    page.fill("input[name=username]", DEMO_USER)
    page.fill("input[name=password]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("load")


def dismiss_tours(page, base):
    from app.tours import get_all_tours
    for t in get_all_tours():
        page.request.post(base + "/api/tours/progress", data={"tour_id": t["id"], "dismissed": True})


def order_id(page, base, customer):
    """The newest order for a demo customer, read off the board."""
    page.goto(base + "/fulfillment/")
    page.wait_for_load_state("load")
    loc = page.locator(f".fb-card:has(.fb-card-link:text-is('{customer}'))").first
    return int(loc.get_attribute("data-order"))


def pdf(path, title, lines):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((56, 80), title, fontsize=18)
    for i, line in enumerate(lines):
        pg.insert_text((56, 120 + 18 * i), line, fontsize=11)
    pg.insert_text((56, 740), "Demo document. All names and figures are fictional.", fontsize=8)
    doc.save(path)
    doc.close()
    return path


def tall_shot(page, path):
    """A whole-page shot taken by growing the viewport to the page, so the
    fixed sidebar runs the full height (a full_page shot leaves it short)."""
    h = page.evaluate("document.documentElement.scrollHeight")
    page.set_viewport_size({"width": DESKTOP["width"], "height": max(DESKTOP["height"], h)})
    page.wait_for_timeout(500)
    # Lazy images start loading once the taller viewport shows them.
    page.wait_for_function("[...document.images].every(i => i.complete)", timeout=10000)
    page.screenshot(path=path)
    page.set_viewport_size(DESKTOP)


def browser(p):
    exe = shutil.which("chromium") or None
    for pattern in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-linux64/chrome"):
        for cand in sorted(Path("/opt/pw-browsers").glob(pattern)):
            exe = str(cand)
    kw = {"args": ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"]}
    if exe:
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

SHOTS = [  # name, path, full page
    ("board", "/fulfillment/", False),
    ("dashboard", "/dashboard", False),
    ("map", "/map/", False),
    ("inventory", "/inventory/", False),
    ("c2c", "/fulfillment/c2c", False),
    ("pilots-due-back", "/fulfillment/pilots-due-back", False),
    ("triage", "/triage/", False),
]


def shots(base, out):
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = browser(p)
        for theme in ("dark", "light"):
            ctx = b.new_context(viewport=DESKTOP, device_scale_factor=1)
            ctx.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}') }} catch (e) {{}}")
            page = ctx.new_page()
            login(page, base)
            dismiss_tours(page, base)
            d = Driver(page, base)
            for name, path, full in SHOTS:
                d.go(path, 2200)
                page.screenshot(path=str(out / f"{name}-{theme}.png"), full_page=full)
            vendor = order_id(page, base, "Cedar Valley Schools")
            pilot = order_id(page, base, "Summit Ridge Apartments")
            for name, oid in (("order-vendor", vendor), ("order-pilot", pilot)):
                d.go(f"/orders/{oid}", 1500)
                tall_shot(page, str(out / f"{name}-{theme}.png"))
            item = page.evaluate("""async (b) => { const r = await fetch(b + '/inventory/?q=EBX-EDGE100-0001');
                const t = await r.text(); const m = t.match(/data-id="(\\d+)"/); return m ? m[1] : null; }""", base)
            if item:
                d.go(f"/items/{item}", 1500)
                tall_shot(page, str(out / f"item-{theme}.png"))
            ctx.close()
        ctx = b.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        login(page, base)
        dismiss_tours(page, base)
        d = Driver(page, base)
        d.go("/mobile", 1200)
        page.screenshot(path=str(out / "mobile.png"))
        d.go("/fulfillment/", 1500)
        page.screenshot(path=str(out / "board-mobile.png"))
        ctx.close()
        ctx = b.new_context(viewport=DESKTOP)
        page = ctx.new_page()
        page.goto(base + "/login")
        page.wait_for_timeout(800)
        page.screenshot(path=str(out / "login.png"))
        ctx.close()
        b.close()
    print("screenshots in", out)


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------

def record(base, out, name, script, viewport=VIDEO, theme="dark"):
    """Run a scripted flow in a recording context and keep the video as MP4."""
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    with sync_playwright() as p:
        b = browser(p)
        setup = b.new_context(viewport=viewport)
        sp = setup.new_page()
        login(sp, base)
        dismiss_tours(sp, base)
        state = setup.storage_state()
        setup.close()
        ctx = b.new_context(viewport=viewport, record_video_dir=str(tmp), record_video_size=viewport,
                            storage_state=state)
        ctx.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}') }} catch (e) {{}}")
        ctx.add_init_script(OVERLAY_JS)
        ctx.add_init_script(MAP_HOOK_JS)
        page = ctx.new_page()
        script(Driver(page, base), tmp)
        page.wait_for_timeout(600)
        video = page.video.path()
        ctx.close()
        b.close()
    mp4 = out / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", mp4)
    return mp4


def gif(mp4, out_gif, width=800, fps=8):
    """A small looping GIF for the README, from an MP4."""
    palette = out_gif.with_suffix(".palette.png")
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", vf + ",palettegen=max_colors=96:stats_mode=diff",
                    str(palette)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-i", str(palette), "-lavfi",
                    vf + " [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", str(out_gif)], check=True)
    palette.unlink()
    print("wrote", out_gif)


def clip_board(d, tmp):
    d.go("/fulfillment/", 1200)
    d.caption("One board, two tracks", "Vendor orders and pilots from stock, one card per order")
    d.p.wait_for_timeout(2200)
    d.click(".fb-tab[data-tab='vendor']", pause=1400)
    d.click(".fb-tab[data-tab='stock']", pause=1400)
    d.click(".fb-tab[data-tab='all']", pause=800)
    d.caption("Tiles light up what needs you", "Late, due back within 30 days, docs missing")
    d.click(".fb-tile[data-tile='late']", pause=1800)
    d.click(".fb-tile[data-tile='docs_missing']", pause=1800)
    d.click(".fb-tile[data-tile='docs_missing']", pause=700)
    d.caption("")


def clip_pilot(d, tmp):
    d.go("/fulfillment/", 900)
    d.caption("A pilot from stock", "Create it, assign units, ship it")
    d.click("#new-order-btn", pause=500)
    d.click("#new-order-form input[value='stock']", pause=300)
    d.type("#new-order-form input[name='customer_name']", "Willow Creek Library")
    d.p.locator("#no-return").fill("2026-12-04")
    d.click("#new-order-submit", pause=200)
    d.settle(1000)
    d.caption("Add what it needs", "SKU lines are matched against ready stock")
    d.click("#sku-add-btn", pause=300)
    d.type("#sku-editor-model", "EDGE25-NR")
    d.p.locator("#sku-editor-source").select_option("stock")
    d.click("#sku-editor button:has-text('Save')", pause=200)
    d.settle(900)
    d.caption("Assign from stock")
    d.click("#assign-open-btn", pause=500)
    d.click(".assign-cb", pause=300)
    d.click("button:has-text('Assign selected')", pause=200)
    d.settle(900)
    d.caption("Move it along its track", "The server checks every step")
    d.scroll_top()
    d.click("#advance-btn", pause=200)
    d.settle(1100)
    d.click("#advance-btn", pause=200)
    d.settle(1400)
    d.caption("")


def clip_docs(d, tmp):
    doc = pdf(str(tmp / "ridgeline-certificate-GCM.pdf"), "Certificate of conformance",
              ["Customer order GCM-1042", "1 x EDGE200-Z2 burn-in 48h: pass", "Signed: Ridgeline QA"])
    d.go("/fulfillment/", 900)
    d.caption("Docs missing", "Gulf Coast Marina shipped before the vendor's certificate arrived")
    d.click(".fb-tile[data-tile='docs_missing']", pause=1500)
    d.click(".fb-card-link:text-is('Gulf Coast Marina')", pause=200)
    d.settle(900)
    d.scroll_to("#documents-section")
    d.caption("Attach the vendor's certificate", "Stored as sent, never parsed")
    d.p.set_input_files("#doc-file", doc)
    d.p.locator("#doc-kind").select_option("certification")
    d.type("#doc-note", "Vendor build certificate")
    d.click("#doc-upload-btn", pause=200)
    d.settle(1000)
    d.scroll_to("#documents-section", 1200)
    d.go("/fulfillment/", 900)
    d.caption("The board agrees", "Docs missing is back to zero")
    d.point("#fb-tiles")
    d.p.wait_for_timeout(2200)
    d.caption("")


US_VIEW = "window.__s2sMap.easeTo({center: [-96.5, 38.2], zoom: 3.35, duration: 1400})"


def map_tour(d, full=True):
    """The deployment map: clusters, a unit's popup, the three colourings,
    the filters, a customer, a search, and (in full) hiding a site and
    pinning a unit that has no location yet."""
    d.go("/map/", 1000)
    d.map_ready()
    d.caption("Every deployed unit on a live map", "Units at every customer site, with the totals that matter")
    d.point("#mp-metrics")
    d.p.wait_for_timeout(2400)

    d.caption("Clusters open as you zoom in", "Click one to see the units under it")
    for _ in range(4):        # click into the biggest cluster until single units show
        if d.map_spot("unit-dots", pick="any") or not d.map_spot("clusters"):
            break
        d.map_click("clusters", pause=300)
        d.map_idle(900)
    d.caption("Every unit carries its story", "Customer, site, serial, deal and status, and when a loan is due back")
    d.map_click("unit-dots", pick="any", pause=2800)
    if full:
        d.caption("Curate what the map shows", "Hide a unit, a site or a whole customer, and bring it back")
        d.click(".mp-pop .actions button:has-text('Hide site')", pause=300)
        d.map_idle(1200)
        d.click("#mp-hidden-list .mp-fixbtn", pause=300)
        d.map_idle(1000)
    else:
        d.click(".maplibregl-popup-close-button", pause=400)

    d.p.evaluate(US_VIEW)
    d.map_idle(600)
    d.caption("Colour it three ways", "By deal type, by unit type, or by status")
    d.click("#mp-mode button[data-mode='unit']", pause=1700)
    d.click("#mp-mode button[data-mode='status']", pause=600)
    d.caption("Status shows what needs a look", "Two units at a site but not in service stand out at once")
    d.p.wait_for_timeout(2200)
    d.click("#mp-mode button[data-mode='deal']", pause=700)

    d.caption("Filter by deal type", "Hide purchased units to see only the loans still out")
    d.click("#mp-deal-bars .mp-bar", nth=0, pause=2200)
    d.click("#mp-deal-bars .mp-bar", nth=0, pause=600)
    if full:
        d.caption("Or by unit type", "Here, only the edge servers")
        d.click("#mp-unit-chips .mp-chip", nth=2, pause=2000)
        d.click("#mp-unit-chips .mp-chip", nth=2, pause=600)

    d.caption("Jump to a customer", "Every site of the customer in one view")
    d.click("#mp-top-customers .mp-rank", nth=0, pause=300)
    d.map_idle(1900)

    serial = d.p.evaluate("""base => fetch(base + '/map/data').then(r => r.json()).then(j =>
        (j.features.find(f => f.properties.status === 'Un-deployable') || j.features[0]).properties.serial)""", d.base)
    d.caption("Find any unit", "Search by serial, name, customer or site")
    d.type("#mp-search", serial)
    d.p.wait_for_timeout(700)          # the search waits 300 ms before it flies
    d.map_idle(1200)
    d.map_click("unit-dots", pick="any", match={"serial": serial}, pause=2800)
    d.click(".maplibregl-popup-close-button", pause=300)
    d.p.locator("#mp-search").fill("")
    d.p.evaluate(US_VIEW)
    d.map_idle(500)

    if full:
        d.caption("Units missing a location", "Pin the site once and every unit there appears on the map")
        d.click("#mp-nl-fix-list .mp-fixbtn", nth=0, pause=400)
        d.type("#mp-nl-fix-list .mp-fixform.open input[placeholder='lat']", "25.7617")
        d.type("#mp-nl-fix-list .mp-fixform.open input[placeholder='lng']", "-80.1918")
        d.click("#mp-nl-fix-list .mp-fixform.open .mp-fixbtn", pause=900)
        d.p.evaluate("window.__s2sMap.easeTo({center: [-81.4, 27.2], zoom: 5.6, duration: 1600})")
        d.map_idle(2000)
    d.caption("")


def clip_map(d, tmp):
    map_tour(d, full=False)


def proof(d, tmp):
    """The full walkthrough, end to end, on live demo data."""
    report = pdf(str(tmp / "willow-creek-post-install.pdf"), "Post-install report: Willow Creek Library",
                 ["1 edge server and 2 cameras installed", "Recording verified with the branch manager"])
    cert = pdf(str(tmp / "ridgeline-certificate-GCM.pdf"), "Certificate of conformance",
               ["Customer order GCM-1042", "1 x EDGE200-Z2 burn-in 48h: pass", "Signed: Ridgeline QA"])

    d.go("/dashboard", 600)
    d.card("Shelf2Site", "Hardware inventory and fulfillment, from shelf to site. A proof walkthrough on demo data.", 3400)
    d.caption("Dashboard", "Totals, what is ready to deploy, and pilots due back")
    d.p.wait_for_timeout(3200)

    d.go("/fulfillment/", 1000)
    d.caption("Fulfillment: one board, two tracks",
              "Vendor orders: Ordered, Building, Shipped, Installed. Pilots: Assigned, Shipped, Out at site, Returned")
    d.p.wait_for_timeout(3400)
    d.click(".fb-tab[data-tab='vendor']", pause=1200)
    d.click(".fb-tab[data-tab='stock']", pause=1200)
    d.click(".fb-tab[data-tab='all']", pause=600)
    d.caption("Tiles light up what needs attention", "Two late, two due back soon, one shipped without its certificate")
    d.click(".fb-tile[data-tile='late']", pause=1800)
    d.click(".fb-tile[data-tile='late']", pause=400)

    d.caption("A finished vendor order", "Cedar Valley Schools: built by the vendor, certified, shipped and installed")
    d.click(".fb-card-link:text-is('Cedar Valley Schools')", pause=200)
    d.settle(900)
    d.p.wait_for_timeout(1600)
    d.scroll_to("#documents-section", 1600)
    d.caption("The vendor's documents and the site visit", "Certificate, validation report, and a certified installation")
    d.scroll_to("#deployments-section", 2400)

    d.go("/fulfillment/", 800)
    d.caption("A new pilot, from scratch")
    d.click("#new-order-btn", pause=500)
    d.click("#new-order-form input[value='stock']", pause=300)
    d.type("#new-order-form input[name='customer_name']", "Willow Creek Library")
    d.p.locator("#no-return").fill("2026-12-04")
    d.click("#new-order-submit", pause=200)
    d.settle(900)
    d.caption("What it needs", "An edge server and two cameras, matched against ready stock")
    d.click("#sku-add-btn", pause=300)
    d.type("#sku-editor-model", "EDGE25-NR")
    d.p.locator("#sku-editor-source").select_option("stock")
    d.click("#sku-editor button:has-text('Save')", pause=200)
    d.settle(800)
    d.click("#sku-add-btn", pause=300)
    d.type("#sku-editor-model", "C2C-GEN1-4MP")
    d.p.locator("#sku-editor-qty").fill("2")
    d.p.locator("#sku-editor-source").select_option("stock")
    d.click("#sku-editor button:has-text('Save')", pause=200)
    d.settle(800)
    d.caption("Assign from stock")
    d.click("#assign-open-btn", pause=500)
    for i in range(3):
        d.click(".assign-cb", nth=i, pause=200)
    d.click("button:has-text('Assign selected')", pause=200)
    d.settle(900)
    d.scroll_to("#prov-section", 1500)
    d.scroll_top()
    d.caption("Ship it", "Moving to Shipped marks every unit Deployed")
    d.click("#advance-btn", pause=200)
    d.settle(1200)
    d.caption("Out at site")
    d.click("#advance-btn", pause=200)
    d.settle(1200)

    d.caption("Schedule the install visit")
    d.scroll_to("#deployments-section", 700)
    d.click("button:has-text('+ Schedule visit')", pause=500)
    d.type("#dep-address", "12 Willow Creek Road")
    d.p.locator("#dep-date").fill("2026-10-20")
    d.type("#dep-integrator", "Front Range AV")
    d.click("#deploy-modal button.fl-cta", pause=200)
    d.settle(900)
    d.scroll_to("#deployments-section", 600)
    d.click("#deployments-section button:has-text('Assign Units')", pause=900)
    for i in range(3):
        d.click(".pk-cb:not(:disabled)", nth=i, pause=200)
    d.click("#unit-picker-modal button.fl-cta", pause=200)
    d.settle(900)
    d.scroll_to("#deployments-section", 600)
    d.caption("Certify the installation", "The signed report locks the visit")
    d.click("#deployments-section button:has-text('Certify')", pause=500)
    d.p.set_input_files("#cert-file", report)
    d.type("#cert-installer", "Dana Whitfield")
    d.type("#cert-company", "Front Range AV")
    d.click("#certify-modal button:has-text('Certify')", pause=200)
    d.settle(900)
    d.scroll_to("#deployments-section", 2200)

    d.go("/fulfillment/", 900)
    d.caption("A vendor order shipped without its certificate", "Gulf Coast Marina shows Docs missing")
    d.click(".fb-tile[data-tile='docs_missing']", pause=1400)
    d.click(".fb-card-link:text-is('Gulf Coast Marina')", pause=200)
    d.settle(800)
    d.scroll_to("#documents-section", 600)
    d.caption("Attach the vendor's certificate", "Files are stored as sent, never parsed")
    d.p.set_input_files("#doc-file", cert)
    d.type("#doc-note", "Vendor build certificate")
    d.click("#doc-upload-btn", pause=200)
    d.settle(900)
    d.scroll_to("#documents-section", 1400)
    d.go("/fulfillment/", 900)
    d.caption("The board agrees", "Docs missing is back to zero, and the new pilot is out at site")
    d.point("#fb-tiles")
    d.p.wait_for_timeout(1800)
    d.scroll_to("#lane-stock", 2400)

    map_tour(d, full=True)

    d.go("/inventory/", 1200)
    d.caption("Inventory", "Every item with its category, status and place")
    d.p.wait_for_timeout(2400)
    d.click(".inv-tile", nth=3, pause=1600)
    d.go("/triage/", 1200)
    d.caption("Asset triage", "Items missing the fields a person still has to fill in")
    d.p.wait_for_timeout(2600)
    d.go("/fulfillment/pilots-due-back", 1200)
    d.caption("Pilots due back", "What to collect, and when")
    d.p.wait_for_timeout(2400)

    d.caption("Light and dark themes")
    d.click("button[onclick='toggleTheme()']", pause=1800)
    d.go("/fulfillment/", 1600)
    d.p.wait_for_timeout(1400)
    d.click("button[onclick='toggleTheme()']", pause=900)
    d.caption("")
    d.card("Shelf2Site", "FastAPI, PostgreSQL, Jinja2 and HTMX. Over a thousand contract tests on every change.", 3600)


def clips(base, out):
    for name, fn in (("board", clip_board), ("pilot", clip_pilot), ("docs", clip_docs), ("map", clip_map)):
        mp4 = record(base, out, name, fn, viewport={"width": 1280, "height": 800})
        gif(mp4, out / f"{name}.gif")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--out", default=str(ROOT / "docs" / "media"))
    ap.add_argument("--what", choices=["shots", "clips", "proof"], required=True)
    args = ap.parse_args()
    out = Path(args.out)
    if args.what == "shots":
        shots(args.base, out / "screenshots")
    elif args.what == "clips":
        clips(args.base, out / "clips")
    else:
        record(args.base, out / "proof", "shelf2site-walkthrough", proof)


if __name__ == "__main__":
    main()

