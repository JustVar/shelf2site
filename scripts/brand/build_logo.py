"""Build the Shelf2Site logo files from one definition.

The mark is S2S: two Quicksand S's on one baseline, and a 2 between them whose
top runs left into the first S as an arrow and whose flat base runs right
into the second S as an arrow. Where the 2 crosses an S, the S steps back by
a thin gap. Everything is turned into outlines, so no font is needed to show
the logo.

Writes the mark and wordmark SVGs under static/img, the app and tab icons
under static/icons, and app/templates/_brand.html (inline macros whose
letters follow the theme text color).

Development only. Needs fonttools, brotli (to read the .woff2 fonts),
skia-pathops and cairosvg:
    pip install fonttools brotli skia-pathops cairosvg
    python scripts/brand/build_logo.py
The fonts are Quicksand 500 and 700 from @fontsource/quicksand 5.3.0, kept
unmodified in scripts/brand/fonts with their licence.
"""
import math
from pathlib import Path

import cairosvg
import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = Path(__file__).resolve().parent / "fonts"
S_FONT = FONTS / "quicksand-500.woff2"              # the S's and the name
TWO_FONTS = [FONTS / "quicksand-500.woff2", FONTS / "quicksand-700.woff2"]

INK, PAPER, WHITE = "#0F2530", "#EAF2F5", "#FFFFFF"
BLUE, BLUE_BRIGHT = "#1690BC", "#4FC3EA"            # the logo blue; its bright form on ink

# The settings chosen in review
LETTER_GAP = 0.12        # between the first S and the 2, in S widths
SECOND_S_GAP = -0.20     # between the 2 and the second S: it overlaps the 2's base
TIP_IN = 0.38            # how far the arrow tips sit from the S's outer edge, in S widths
HEAD_SIZE = 0.85         # arrowhead size against the room inside the hollow
CUT_GAP = 0.16           # gap the S leaves around the 2, in S strokes
TILE_RX = 14


def num(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")


class Face:
    def __init__(self, path):
        self.font = TTFont(path)
        self.gs, self.cmap = self.font.getGlyphSet(), self.font.getBestCmap()
        self.hmtx, self.cap = self.font["hmtx"], self.font["OS/2"].sCapHeight

    def path(self, ch, dx=0.0, dy=0.0, k=1.0):
        """A glyph as a pathops Path in y-up font units, scaled by k then moved."""
        p = pathops.Path()
        self.gs[self.cmap[ord(ch)]].draw(TransformPen(p.getPen(glyphSet=self.gs), (k, 0, 0, k, dx, dy)))
        return p

    def adv(self, ch):
        return self.hmtx[self.cmap[ord(ch)]][0]


def poly(pts):
    p = pathops.Path()
    pen = p.getPen()
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.closePath()
    return p


def rect(x0, y0, x1, y1):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def union(*ps):
    out = pathops.Path()
    for p in ps:
        out = pathops.op(out, p, pathops.PathOp.UNION)
    return out


def minus(a, b):
    return pathops.op(a, b, pathops.PathOp.DIFFERENCE)


def bounds(p):
    bp = BoundsPen(None)
    p.draw(bp)
    return bp.bounds


def shifted(p, dx, dy):
    q = pathops.Path()
    p.draw(TransformPen(q.getPen(), (1, 0, 0, 1, dx, dy)))
    return q


def grown(p, c, n=16):
    """p made fatter by c on every side (a union of shifted copies)."""
    return union(p, *[shifted(p, c * math.cos(2 * math.pi * i / n), c * math.sin(2 * math.pi * i / n)) for i in range(n)])


def runs_vertical(p, x):
    """Solid runs, bottom to top, where a thin vertical line at x crosses p."""
    cut = pathops.op(p, rect(x - 1, -5000, x + 1, 5000), pathops.PathOp.INTERSECTION)
    rec = RecordingPen()
    cut.draw(rec)
    out, pts = [], []
    for name, args in rec.value:
        if name == "moveTo":
            pts = [args[0]]
        elif name in ("lineTo", "qCurveTo", "curveTo"):
            pts += list(args)
        elif name in ("closePath", "endPath") and pts:
            ys = [q[1] for q in pts]
            out.append((min(ys), max(ys)))
            pts = []
    return sorted(out)


def gap_at(p, x, lo, hi):
    """The largest empty vertical interval inside (lo, hi) along x."""
    runs = [r for r in runs_vertical(p, x) if r[1] > lo and r[0] < hi]
    edges = [lo] + [v for r in runs for v in r] + [hi]
    gaps = [(edges[i], edges[i + 1]) for i in range(0, len(edges) - 1, 2) if edges[i + 1] > edges[i]]
    return max(gaps, key=lambda g: g[1] - g[0])


def bar(a, b, t):
    """A bar of thickness t from point a to point b, flat ends."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    nx, ny = -dy / d * t / 2, dx / d * t / 2
    return poly([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)])


def arrow_head(tip, frm, length, half):
    """A solid head at tip pointing away from frm; returns the head and the middle of its back."""
    dx, dy = tip[0] - frm[0], tip[1] - frm[1]
    d = math.hypot(dx, dy)
    ux, uy = dx / d, dy / d
    bx, by = tip[0] - ux * length, tip[1] - uy * length
    return poly([tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]), (bx, by)


def two_bands(F, k):
    """The 2 at scale k, its bounds, and the solid runs of its base and top bands."""
    T = F.path("2", k=k)
    x0, y0, x1, y1 = bounds(T)
    runs = runs_vertical(T, (x0 + x1) / 2 + (x1 - x0) * 0.05)
    return (x0, y0, x1, y1), runs[0], runs[-1]


def build_mark():
    """Returns (letters, route, bounds, s_stroke) in y-up font units."""
    FS = Face(S_FONT)
    S = FS.path("S")
    sx0, sy0, sx1, sy1 = bounds(S)
    w = sx1 - sx0
    mid = (sy0 + sy1) / 2
    stroke = runs_vertical(S, (sx0 + sx1) / 2)[-1]
    s_w = stroke[1] - stroke[0]
    up_c = sum(gap_at(S, sx1 - w * 0.10, mid, sy1)) / 2      # the upper hollow's opening, right side
    low_c = sum(gap_at(S, sx0 + w * 0.10, sy0, mid)) / 2     # the lower hollow's opening, left side

    # The 2 reaches from the S's top to the lower opening; pick the weight whose stroke matches the S
    best = None
    for f in TWO_FONTS:
        F2 = Face(f)
        _, base0, top0 = two_bands(F2, 1.0)
        k = (sy1 - low_c) / (top0[1] - sum(base0) / 2)
        score = abs((base0[1] - base0[0]) * k - s_w)
        if best is None or score < best[0]:
            best = (score, F2, k)
    _, F2, k = best
    (tx0, _, tx1, _), base, top = two_bands(F2, k)
    band = base[1] - base[0]
    dy2 = low_c - sum(base) / 2
    x2 = sx1 + w * LETTER_GAP - tx0
    two = F2.path("2", dx=x2, dy=dy2, k=k)
    x3 = x2 + tx1 + w * SECOND_S_GAP - sx0
    S2 = FS.path("S", dx=x3)

    hb, ht = top[0] + dy2, top[1] + dy2
    bb, bt = base[0] + dy2, base[1] + dy2
    hc, bc = (hb + ht) / 2, (bb + bt) / 2
    cut_x = x2 + tx0 + (tx1 - tx0) * 0.40
    two = minus(two, rect(-9000, -9000, cut_x, hb - 0.5))                # drop the 2's starting hook
    join_x = x2 + tx0 + (tx1 - tx0) * 0.62
    two = minus(two, rect(join_x, bb - 50, 9000, bt + 0.5))              # the base bar carries on from here

    # Bottom arrow: the base, flat and level, straight into the second S's lower hollow
    tip2 = (x3 + sx1 - w * TIP_IN, bc)
    room2 = gap_at(S2, tip2[0] - band * 2, sy0, mid)
    half2 = min(band * 1.35, (room2[1] - room2[0]) * 0.40) * HEAD_SIZE
    head2, back2 = arrow_head(tip2, (x2 + tx1, bc), half2 * 1.75, half2)
    base_bar = rect(join_x - 2, bb, back2[0] + 2, bt)
    # Top arrow: from the 2's top, sloping down into the first S's upper hollow
    tip1 = (sx0 + w * TIP_IN, up_c)
    room1 = gap_at(S, tip1[0] + band * 2, mid, sy1)
    half1 = min(band * 1.35, (room1[1] - room1[0]) * 0.40) * HEAD_SIZE
    start1 = (cut_x + band * 0.3, hc)
    head1, back1 = arrow_head(tip1, start1, half1 * 1.75, half1)

    route = union(two, bar(start1, back1, band), head1, base_bar, head2)
    letters = minus(union(S, S2), grown(route, s_w * CUT_GAP))
    return letters, route, bounds(union(route, letters)), s_w


LETTERS, ROUTE, BOX, S_STROKE = build_mark()


def placed(p, w, h, ox=0.0, oy=0.0, box=None):
    """Path data for p fitted inside a w x h box whose top left is (ox, oy)."""
    x0, y0, x1, y1 = box or BOX
    k = min(w / (x1 - x0), h / (y1 - y0))
    dx = ox + (w - (x1 - x0) * k) / 2
    dy = oy + (h - (y1 - y0) * k) / 2
    pen = SVGPathPen(None, ntos=num)
    p.draw(TransformPen(pen, (k, 0, 0, -k, dx - x0 * k, dy + y1 * k)))
    return pen.getCommands()


def tile(pad=0.0, full_bleed=False):
    """The mark on its ink tile, 64 x 64; pad shrinks the mark for maskable icons."""
    bg = (f'<rect width="64" height="64" fill="{INK}"/>' if full_bleed
          else f'<rect width="64" height="64" rx="{TILE_RX}" fill="{INK}"/>')
    s = 1 - 2 * pad
    w, h = 54 * s, 44 * s
    return (bg + f'<path d="{placed(LETTERS, w, h, 32 - w / 2, 32 - h / 2)}" fill="{WHITE}"/>'
            f'<path d="{placed(ROUTE, w, h, 32 - w / 2, 32 - h / 2)}" fill="{BLUE_BRIGHT}"/>')


def tab_tile():
    """For 16 and 32 px: only the 2 and its arrows, drawn heavier so it holds up."""
    fat = grown(ROUTE, S_STROKE * 0.45, n=24)
    return (f'<rect width="64" height="64" rx="{TILE_RX}" fill="{INK}"/>'
            f'<path d="{placed(fat, 54, 50, 5, 7, bounds(fat))}" fill="{BLUE_BRIGHT}"/>')


def wordmark():
    """('Shelf', '2', 'Site') outlines in font units (y down), and the total advance."""
    F = Face(S_FONT)
    parts, x = [], 0
    for chunk in ("Shelf", "2", "Site"):
        pen = SVGPathPen(F.gs, ntos=num)
        for ch in chunk:
            F.gs[F.cmap[ord(ch)]].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
            x += F.adv(ch)
        parts.append(pen.getCommands())
    return parts, x, F.cap


def horizontal(ink, accent):
    """The bare mark beside the name, 64 units tall; returns (svg body, width)."""
    x0, y0, x1, y1 = BOX
    mh = 52
    mw = (x1 - x0) * mh / (y1 - y0)
    mark = (f'<path d="{placed(LETTERS, mw, mh, 0, 6)}" fill="{ink}"/>'
            f'<path d="{placed(ROUTE, mw, mh, 0, 6)}" fill="{accent}"/>')
    (shelf, two, site), adv, cap = wordmark()
    k = 28 / cap
    gap = 22
    words = (f'<g transform="translate({num(mw + gap)} 46) scale({k:.5f})">'
             f'<path d="{shelf}" fill="{ink}"/><path d="{two}" fill="{accent}"/>'
             f'<path d="{site}" fill="{ink}"/></g>')
    return mark + words, mw + gap + adv * k + 2


def svg(body, w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {num(w)} {h}" '
            f'role="img" aria-label="Shelf2Site">{body}</svg>\n')


def main():
    img = ROOT / "static/img"
    icons = ROOT / "static/icons"
    (img / "logo-mark.svg").write_text(svg(tile(), 64, 64))
    for name, ink, accent in (("logo-horizontal-light.svg", INK, BLUE), ("logo-horizontal-dark.svg", PAPER, BLUE_BRIGHT)):
        body, w = horizontal(ink, accent)
        (img / name).write_text(svg(body, w, 64))

    def png(body, size, name):
        cairosvg.svg2png(bytestring=svg(body, 64, 64).encode(), write_to=str(icons / name),
                         output_width=size, output_height=size)

    for size in (72, 96, 128, 144, 152, 192, 384, 512):
        png(tile(), size, f"icon-{size}.png")
    for size in (192, 512):
        png(tile(pad=0.12, full_bleed=True), size, f"icon-{size}-maskable.png")
    for size in (16, 32):
        png(tab_tile(), size, f"icon-{size}.png")

    # Inline macros: the letters take the text color and the route the theme's
    # --brand-accent, so one logo serves both themes.
    body, w = horizontal("currentColor", f"var(--brand-accent, {BLUE})")
    macros = (
        "{# Generated by scripts/brand/build_logo.py; edit that, not this. #}\n"
        "{% macro brand_logo(height=36) -%}\n"
        f'<svg class="brand-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {num(w)} 64" '
        f'height="{{{{ height }}}}" role="img" aria-label="Shelf2Site">{body}</svg>\n'
        "{%- endmacro %}\n"
        "{% macro brand_mark(size=34) -%}\n"
        '<svg class="brand-mark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        f'width="{{{{ size }}}}" height="{{{{ size }}}}" role="img" aria-label="Shelf2Site">{tile()}</svg>\n'
        "{%- endmacro %}\n"
    )
    (ROOT / "app/templates/_brand.html").write_text(macros)
    print("wrote logo files; mark box", [round(v) for v in BOX], "S stroke", round(S_STROKE))


if __name__ == "__main__":
    main()
