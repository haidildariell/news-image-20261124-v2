"""The Day in World News - Tuesday 24 November 2026.

One-page news image for the make.fun news-image-20261124 bounty.
Pure Python 3 standard library: a small TrueType rasteriser, a
scanline polygon filler and a PNG encoder. No network, no PIL.
Deterministic: same input data, same bytes out.
"""
import math
import os
import struct
import zlib

OUT_PATH = "/output/entry.png"
W = 1024
H = 1024
SS = 2                      # canvas supersample factor
GW = W * SS
GH = H * SS

PAPER = (247, 242, 231)
NAVY = (22, 40, 63)
INK = (22, 24, 29)
RED = (176, 42, 33)
GOLD = (201, 162, 39)
WHITE = (255, 255, 255)
CARD = (252, 250, 244)
CHIP = (233, 227, 211)
TEAL = (24, 84, 92)
BROWN = (122, 72, 32)

# ---------------------------------------------------------------- PNG


def write_png(path, w, h, rgb):
    """rgb: bytearray of w*h*3 bytes, rows top to bottom."""
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# ---------------------------------------------------------------- TTF


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


class Font:
    """Minimal TrueType reader: cmap (fmt 4/12), glyf, hmtx."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            self.data = fh.read()
        b = self.data
        self.tables = {}
        n = _u16(b, 4)
        for i in range(n):
            off = 12 + i * 16
            tag = b[off:off + 4].decode("latin1")
            self.tables[tag] = (_u32(b, off + 8), _u32(b, off + 12))
        ho, _ = self.tables["head"]
        self.upem = _u16(b, ho + 18)
        self.loc_fmt = _i16(b, ho + 50)
        mo, _ = self.tables["maxp"]
        self.num_glyphs = _u16(b, mo + 4)
        eo, _ = self.tables["hhea"]
        self.num_hmtx = _u16(b, eo + 34)
        self._cmap = self._pick_cmap()
        self._glyph_cache = {}
        self._raw_cache = {}

    def _pick_cmap(self):
        b = self.data
        co, _ = self.tables["cmap"]
        best = None
        n = _u16(b, co + 2)
        for i in range(n):
            plat = _u16(b, co + 4 + i * 8)
            enc = _u16(b, co + 6 + i * 8)
            sub = _u32(b, co + 8 + i * 8)
            fmt = _u16(b, co + sub)
            score = -1
            if fmt == 12:
                score = 30 if (plat, enc) in ((3, 10), (0, 4)) else 20
            elif fmt == 4:
                score = 15 if (plat, enc) == (3, 1) else 10
            if score > 0 and (best is None or score > best[0]):
                best = (score, co + sub, fmt)
        return best[1], best[2]

    def glyph_id(self, codepoint):
        b = self.data
        off, fmt = self._cmap
        if fmt == 12:
            ngroups = _u32(b, off + 12)
            lo, hi = 0, ngroups - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                go = off + 16 + mid * 12
                start, end, base = _u32(b, go), _u32(b, go + 4), _u32(b, go + 8)
                if codepoint < start:
                    hi = mid - 1
                elif codepoint > end:
                    lo = mid + 1
                else:
                    return base + (codepoint - start)
            return 0
        # format 4
        seg2 = _u16(b, off + 6)
        seg = seg2 // 2
        end_off = off + 14
        start_off = end_off + seg2 + 2
        delta_off = start_off + seg2
        range_off = delta_off + seg2
        for i in range(seg):
            end_c = _u16(b, end_off + i * 2)
            if codepoint <= end_c:
                start_c = _u16(b, start_off + i * 2)
                if codepoint < start_c:
                    return 0
                delta = _i16(b, delta_off + i * 2)
                ro = _u16(b, range_off + i * 2)
                if ro == 0:
                    return (codepoint + delta) & 0xFFFF
                addr = range_off + i * 2 + ro + 2 * (codepoint - start_c)
                gid = _u16(b, addr)
                return (gid + delta) & 0xFFFF if gid else 0
        return 0

    def advance(self, gid):
        b = self.data
        ho, _ = self.tables["hmtx"]
        if gid >= self.num_hmtx:
            gid = self.num_hmtx - 1
        return _u16(b, ho + gid * 4)

    def _loca(self, gid):
        b = self.data
        lo, _ = self.tables["loca"]
        if self.loc_fmt == 0:
            return _u16(b, lo + gid * 2) * 2, _u16(b, lo + gid * 2 + 2) * 2
        return _u32(b, lo + gid * 4), _u32(b, lo + gid * 4 + 4)

    def raw_contours(self, gid):
        """List of contours; each a list of [x, y, on_curve] (font units)."""
        if gid in self._raw_cache:
            return self._raw_cache[gid]
        b = self.data
        go, _ = self.tables["glyf"]
        a, z = self._loca(gid)
        if a == z:
            self._raw_cache[gid] = []
            return []
        off = go + a
        ncont = _i16(b, off)
        if ncont >= 0:
            res = self._simple(off, ncont)
        else:
            res = self._composite(off)
        self._raw_cache[gid] = res
        return res

    def _simple(self, off, ncont):
        b = self.data
        ends = [_u16(b, off + 10 + i * 2) for i in range(ncont)]
        total = ends[-1] + 1
        p = off + 10 + ncont * 2
        ilen = _u16(b, p)
        p += 2 + ilen
        flags = []
        while len(flags) < total:
            f = b[p]
            p += 1
            flags.append(f)
            if f & 0x08:
                rep = b[p]
                p += 1
                flags.extend([f] * rep)
        xs = []
        x = 0
        for f in flags:
            if f & 0x02:
                v = b[p]
                p += 1
                x += v if (f & 0x10) else -v
            elif not (f & 0x10):
                x += _i16(b, p)
                p += 2
            xs.append(x)
        ys = []
        y = 0
        for f in flags:
            if f & 0x04:
                v = b[p]
                p += 1
                y += v if (f & 0x20) else -v
            elif not (f & 0x20):
                y += _i16(b, p)
                p += 2
            ys.append(y)
        contours = []
        start = 0
        for end in ends:
            contour = []
            for i in range(start, end + 1):
                contour.append([xs[i], ys[i], bool(flags[i] & 0x01)])
            contours.append(contour)
            start = end + 1
        return contours

    def _composite(self, off):
        b = self.data
        p = off + 10
        result = []
        flat_so_far = []
        while True:
            flags = _u16(b, p)
            comp_gid = _u16(b, p + 2)
            p += 4
            if flags & 0x0001:
                arg1 = _i16(b, p)
                arg2 = _i16(b, p + 2)
                p += 4
            else:
                arg1 = struct.unpack_from(">b", b, p)[0]
                arg2 = struct.unpack_from(">b", b, p + 1)[0]
                p += 2
            ma, mb, mc, md = 1.0, 0.0, 0.0, 1.0
            if flags & 0x0008:
                v = _i16(b, p) / 16384.0
                p += 2
                ma = md = v
            elif flags & 0x0040:
                ma = _i16(b, p) / 16384.0
                md = _i16(b, p + 2) / 16384.0
                p += 4
            elif flags & 0x0080:
                ma = _i16(b, p) / 16384.0
                mb = _i16(b, p + 2) / 16384.0
                mc = _i16(b, p + 4) / 16384.0
                md = _i16(b, p + 6) / 16384.0
                p += 8
            comp = self.raw_contours(comp_gid)
            comp_flat = [pt for cont in comp for pt in cont]
            if flags & 0x0002:
                dx, dy = arg1, arg2
            else:
                anchor = flat_so_far[arg1]
                mine = comp_flat[arg2]
                dx = anchor[0] - mine[0]
                dy = anchor[1] - mine[1]
            for cont in comp:
                moved = []
                for (x, y, on) in cont:
                    moved.append([x * ma + y * mb + dx,
                                  x * mc + y * md + dy, on])
                result.append(moved)
                flat_so_far.extend(moved)
            if not (flags & 0x0020):
                break
        return result


# ------------------------------------------------------- rasterising


def _flatten_contour(contour):
    """Turn one raw contour into a polygon (list of (x, y) floats)."""
    n = len(contour)
    start_idx = None
    for i in range(n):
        if contour[i][2]:
            start_idx = i
            break
    if start_idx is None:
        # all points off-curve: start at midpoint of last and first
        x = (contour[-1][0] + contour[0][0]) / 2.0
        y = (contour[-1][1] + contour[0][1]) / 2.0
        order = list(range(n))
        out = [(x, y)]
        prev_on = (x, y)
        pending = None
        seq = order
    else:
        out = [(contour[start_idx][0], contour[start_idx][1])]
        prev_on = out[0]
        pending = None
        seq = [(start_idx + k) % n for k in range(1, n)]
    steps = 6
    for idx in seq:
        x, y, on = contour[idx]
        if on:
            if pending is not None:
                cx, cy = pending
                for s in range(1, steps + 1):
                    t = s / steps
                    u = 1 - t
                    out.append((u * u * prev_on[0] + 2 * u * t * cx + t * t * x,
                                u * u * prev_on[1] + 2 * u * t * cy + t * t * y))
                pending = None
            else:
                out.append((x, y))
            prev_on = (x, y)
        else:
            if pending is not None:
                mx = (pending[0] + x) / 2.0
                my = (pending[1] + y) / 2.0
                cx, cy = pending
                for s in range(1, steps + 1):
                    t = s / steps
                    u = 1 - t
                    out.append((u * u * prev_on[0] + 2 * u * t * cx + t * t * mx,
                                u * u * prev_on[1] + 2 * u * t * cy + t * t * my))
                prev_on = (mx, my)
            pending = (x, y)
    if pending is not None:
        cx, cy = pending
        x, y = out[0]
        for s in range(1, steps + 1):
            t = s / steps
            u = 1 - t
            out.append((u * u * prev_on[0] + 2 * u * t * cx + t * t * x,
                        u * u * prev_on[1] + 2 * u * t * cy + t * t * y))
    return out


def _fill_polys(polys, w, h):
    """Nonzero-winding scanline fill into a 0/1 bytearray of w*h."""
    bmp = bytearray(w * h)
    edges = []
    for poly in polys:
        m = len(poly)
        for i in range(m):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % m]
            if y0 != y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0),
                              1 if y1 > y0 else -1))
    for yy in range(h):
        yc = yy + 0.5
        hits = []
        for (y0, y1, x0, slope, sgn) in edges:
            if (y0 <= yc < y1) or (y1 <= yc < y0):
                hits.append((x0 + (yc - y0) * slope, sgn))
        if not hits:
            continue
        hits.sort()
        wind = 0
        prev_x = None
        base = yy * w
        for (x, sgn) in hits:
            if wind != 0 and prev_x is not None:
                xa = int(math.ceil(prev_x - 0.5))
                xb = int(math.ceil(x - 0.5)) - 1
                if xa < 0:
                    xa = 0
                if xb >= w:
                    xb = w - 1
                for xx in range(xa, xb + 1):
                    bmp[base + xx] = 1
            wind += sgn
            prev_x = x
    return bmp


SUB = 4  # glyph subpixels per final pixel (canvas SS is 2 of these)


class GlyphSet:
    """Renders and caches glyph coverage bitmaps for one font."""

    def __init__(self, font):
        self.font = font
        self.cache = {}

    def glyph(self, ch, size):
        """Return (cov, w, h, left, top, adv) on the canvas grid (SS=2).

        cov holds bytes 0..4 (coverage quarters), w/h in canvas px,
        left/top: canvas-px offset from pen position / baseline.
        adv: advance in canvas px (float).
        """
        key = (ch, int(round(size * 2)))
        if key in self.cache:
            return self.cache[key]
        font = self.font
        gid = font.glyph_id(ord(ch))
        adv = font.advance(gid) * size / font.upem * SS
        if gid == 0 or not font.raw_contours(gid):
            res = (None, 0, 0, 0, 0, adv)
            self.cache[key] = res
            return res
        scale = size * SUB / font.upem
        polys = []
        minx = miny = float("inf")
        maxx = maxy = float("-inf")
        for contour in font.raw_contours(gid):
            poly = _flatten_contour(contour)
            scaled = [(x * scale, -y * scale) for (x, y) in poly]
            polys.append(scaled)
            for (x, y) in scaled:
                minx = min(minx, x)
                maxx = max(maxx, x)
                miny = min(miny, y)
                maxy = max(maxy, y)
        ox = int(math.floor(minx))
        oy = int(math.floor(miny))
        if ox & 1:
            ox -= 1
        if oy & 1:
            oy -= 1
        wsub = int(math.ceil(maxx)) - ox
        hsub = int(math.ceil(maxy)) - oy
        if wsub & 1:
            wsub += 1
        if hsub & 1:
            hsub += 1
        shifted = [[(x - ox, y - oy) for (x, y) in poly] for poly in polys]
        bmp = _fill_polys(shifted, wsub, hsub)
        # downsample 2x2 -> coverage quarters on the canvas grid
        w = wsub // 2
        h = hsub // 2
        cov = bytearray(w * h)
        for yy in range(h):
            for xx in range(w):
                s = (bmp[(2 * yy) * wsub + 2 * xx] +
                     bmp[(2 * yy) * wsub + 2 * xx + 1] +
                     bmp[(2 * yy + 1) * wsub + 2 * xx] +
                     bmp[(2 * yy + 1) * wsub + 2 * xx + 1])
                cov[yy * w + xx] = s
        left = ox // 2
        top = oy // 2
        res = (cov, w, h, left, top, adv)
        self.cache[key] = res
        return res


# ------------------------------------------------------------- canvas


class Canvas:
    def __init__(self):
        self.px = bytearray(GW * GH * 3)
        self.set_rect(0, 0, GW, GH, PAPER)

    def set_rect(self, x, y, w, h, color):
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > GW:
            w = GW - x
        if y + h > GH:
            h = GH - y
        if w <= 0 or h <= 0:
            return
        row = bytes(color) * w
        n = w * 3
        for yy in range(y, y + h):
            off = (yy * GW + x) * 3
            self.px[off:off + n] = row

    def rect(self, x, y, w, h, color):
        """Rect in final-pixel coordinates (floats ok)."""
        self.set_rect(int(round(x * SS)), int(round(y * SS)),
                      int(round(w * SS)), int(round(h * SS)), color)

    def blend_px(self, x, y, color, a255):
        if 0 <= x < GW and 0 <= y < GH and a255:
            off = (y * GW + x) * 3
            if a255 >= 255:
                self.px[off] = color[0]
                self.px[off + 1] = color[1]
                self.px[off + 2] = color[2]
            else:
                ia = 255 - a255
                self.px[off] = (color[0] * a255 + self.px[off] * ia) // 255
                self.px[off + 1] = (color[1] * a255 + self.px[off + 1] * ia) // 255
                self.px[off + 2] = (color[2] * a255 + self.px[off + 2] * ia) // 255

    def circle(self, cx, cy, r, color):
        cx2, cy2, r2 = cx * SS, cy * SS, r * SS
        x0 = int(math.floor(cx2 - r2))
        x1 = int(math.ceil(cx2 + r2))
        y0 = int(math.floor(cy2 - r2))
        y1 = int(math.ceil(cy2 + r2))
        rr = r2 * r2
        for yy in range(y0, y1 + 1):
            dy = yy + 0.5 - cy2
            for xx in range(x0, x1 + 1):
                dx = xx + 0.5 - cx2
                if dx * dx + dy * dy <= rr:
                    off = (yy * GW + xx) * 3
                    if 0 <= xx < GW and 0 <= yy < GH:
                        self.px[off] = color[0]
                        self.px[off + 1] = color[1]
                        self.px[off + 2] = color[2]

    def polygon(self, pts, color):
        """Even-odd fill of one polygon, pts in final-px coords."""
        scaled = [(x * SS, y * SS) for (x, y) in pts]
        miny = int(math.floor(min(p[1] for p in scaled)))
        maxy = int(math.ceil(max(p[1] for p in scaled)))
        edges = []
        m = len(scaled)
        for i in range(m):
            x0, y0 = scaled[i]
            x1, y1 = scaled[(i + 1) % m]
            if y0 != y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0)))
        for yy in range(max(0, miny), min(GH - 1, maxy) + 1):
            yc = yy + 0.5
            hits = []
            for (y0, y1, x0, slope) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    hits.append(x0 + (yc - y0) * slope)
            hits.sort()
            for k in range(0, len(hits) - 1, 2):
                xa = int(math.ceil(hits[k] - 0.5))
                xb = int(math.ceil(hits[k + 1] - 0.5)) - 1
                if xa < 0:
                    xa = 0
                if xb >= GW:
                    xb = GW - 1
                row = bytes(color) * (xb - xa + 1)
                off = (yy * GW + xa) * 3
                self.px[off:off + len(row)] = row

    def text(self, gs, s, x, y, size, color, tracking=0.0):
        """Draw s with pen at (x, baseline y) in final px. Returns width."""
        pen = x * SS
        base = y * SS
        for ch in s:
            cov, w, h, left, top, adv = gs.glyph(ch, size)
            if cov is not None:
                bx = int(round(pen)) + left
                by = int(round(base)) + top
                for yy in range(h):
                    cy = by + yy
                    if cy < 0 or cy >= GH:
                        continue
                    rowbase = yy * w
                    for xx in range(w):
                        v = cov[rowbase + xx]
                        if v:
                            self.blend_px(bx + xx, cy, color, v * 255 // 4)
            pen += adv + tracking * SS
        return (pen - x * SS) / SS - (tracking if s else 0)

    def text_width(self, gs, s, size, tracking=0.0):
        total = 0.0
        for ch in s:
            total += gs.glyph(ch, size)[5] / SS + tracking
        return total - (tracking if s else 0)

    def text_centered(self, gs, s, cx, y, size, color, tracking=0.0):
        w = self.text_width(gs, s, size, tracking)
        return self.text(gs, s, cx - w / 2, y, size, color, tracking)

    def text_fit(self, gs, s, x, y, size, color, max_w, tracking=0.0):
        """Draw, shrinking the font until the string fits max_w."""
        while size > 8.0 and self.text_width(gs, s, size, tracking) > max_w:
            size -= 0.5
        return self.text(gs, s, x, y, size, color, tracking)

    def finish(self):
        """Downsample the SS canvas to W x H RGB bytes."""
        out = bytearray(W * H * 3)
        for yy in range(H):
            rows = []
            for k in range(SS):
                src = ((yy * SS + k) * GW) * 3
                rows.append(self.px[src:src + GW * 3])
            for xx in range(W):
                r = g = bl = 0
                for k in range(SS):
                    row = rows[k]
                    base = xx * SS * 3
                    for j in range(SS):
                        o = base + j * 3
                        r += row[o]
                        g += row[o + 1]
                        bl += row[o + 2]
                n = SS * SS
                off = (yy * W + xx) * 3
                out[off] = r // n
                out[off + 1] = g // n
                out[off + 2] = bl // n
        return out


# ------------------------------------------------------------- fonts


def _load_font(candidates):
    for path in candidates:
        if os.path.exists(path):
            return GlyphSet(Font(path))
    raise RuntimeError("no font found: " + candidates[0])


LIB = "/usr/share/fonts/truetype/liberation/"
DJV = "/usr/share/fonts/truetype/dejavu/"
SERIF_B = _load_font([LIB + "LiberationSerif-Bold.ttf",
                      DJV + "DejaVuSerif-Bold.ttf"])
SERIF = _load_font([LIB + "LiberationSerif-Regular.ttf",
                    DJV + "DejaVuSerif.ttf"])
SERIF_I = _load_font([LIB + "LiberationSerif-Italic.ttf",
                      DJV + "DejaVuSerif-Italic.ttf"])
SANS_B = _load_font([LIB + "LiberationSans-Bold.ttf",
                     DJV + "DejaVuSans-Bold.ttf"])
SANS = _load_font([LIB + "LiberationSans-Regular.ttf",
                   DJV + "DejaVuSans.ttf"])

# ------------------------------------------------------------- stories
# Every item below was reported on Tuesday 24 November 2026 by the
# named outlet or wire. 34 stories, 6 continents.

LEADS = [
    dict(banner="90+", bg=NAVY, fg=WHITE, cat="CLIMATE - ANTALYA, TURKIYE",
         head="COP31 talks collapse as 90+ nations reject the draft",
         desc="Fifty hours into overtime, the Antalya summit ends with "
              "no deal: the draft text never once named fossil fuels.",
         src="GRIST", status="TALKS OVER"),
    dict(banner="+9%", bg=RED, fg=WHITE, cat="MARKETS - TAIPEI",
         head="Asia markets rocket as Huang returns to Nvidia",
         desc="Taipei jumped 9% and Seoul 6% as chip suppliers cheered "
              "Jensen Huang's reinstatement at the helm of Nvidia.",
         src="REUTERS", status="RALLY"),
    dict(banner="7 DRONES", bg=TEAL, fg=WHITE, cat="WAR AT SEA - BENGHAZI",
         head="Ukraine says drones sank a Russian corvette in Libya",
         desc="Seven naval drones struck the Merkury at Benghazi, "
              "carrying the Black Sea fight into the Mediterranean.",
         src="MIDDLE EAST EYE", status="KYIV CLAIMS"),
    dict(banner="6 DEAD", bg=GOLD, fg=INK, cat="DISASTER - HANOI",
         head="Explosion in a Hanoi food shop kills six people",
         desc="The 8 a.m. blast on Dong Da Street injured ten more and "
              "shattered windows across a crowded residential block.",
         src="REUTERS", status="PROBE"),
]

MIDS = [
    dict(cat="WAR - UKRAINE", src="REUTERS",
         head="Russian strike on Zaporizhzhia kills 2, wounds 22"),
    dict(cat="BUSINESS - US", src="REUTERS",
         head="SpaceX and Tesla name five directors for merger talks"),
    dict(cat="CYBER - US", src="REUTERS",
         head="CrowdStrike snaps up Zscaler in a $44 billion deal"),
    dict(cat="POLITICS - DHAKA", src="REUTERS",
         head="Hasina to end two years of exile, fly home Dec 16"),
    dict(cat="PACIFIC - HONIARA", src="REUTERS",
         head="Solomons to drop China pact for Australia treaty"),
    dict(cat="COLOMBIA - META", src="TRT WORLD",
         head="Car bomb hits government complex in Meta province"),
    dict(cat="IRAQ - BAGHDAD", src="REUTERS",
         head="Iraq PM orders takeover of Kurdistan border crossings"),
    dict(cat="GULF - HORMUZ", src="TRT WORLD",
         head="US probes possible Iran role in attacks on shipping"),
]

ALSO = [
    "NATO logs 25 Russian airspace violations - CONVERSATION",
    "EU Commission confirms data breach - EURONEWS",
    "Putin open to Article 5-style Ukraine deal - WAPO",
    "Fourteen nations back ICJ Rohingya ruling - HORIZON",
    "Japan pays ICC dues early amid US sanctions - REUTERS",
    "Pakistan astronaut to fly to Tiangong - AL JAZEERA",
    "Malaysia-Myanmar refugee talks continue - REUTERS",
    "Nepal: 5.6 quake near China border - HORIZON",
    "Gaza strikes kill 3, incl. UNRWA worker - AL JAZEERA",
    "Singer Parastoo Ahmadi lashed 74 times - HORIZON",
    "Iran sets 7 conditions for US talks - HORIZON",
    "South Sudan strike kills 24, incl. 7 children - AFP",
    "Somalia, Uganda step up Shabaab fight - AFP",
    "Borno school enrolment doubles - AL JAZEERA",
    "Oregon, Virginia sue SpaceX over Grok images - AP",
    "Pennsylvania measles death toll reaches nine - AP",
    "Canada and Qatar sign investment pact - REUTERS",
    "Mexico to try 'El Chapo Isidro' at home - AP",
    "Guterres seeks AI risk pact in a year - UN NEWS",
    "Galapagos floods raise El Nino fears - EURONEWS",
    "Canberra urged to reject coalmine plan - GUARDIAN",
    "WFP: war chokes food aid for 7.3m - AL JAZEERA",
]

# Simplified continent silhouettes as (lon, lat) polygons for the map.
CONTINENTS = [
    [(-166, 68), (-140, 70), (-128, 70), (-115, 72), (-100, 79),
     (-88, 80), (-82, 72), (-78, 69), (-68, 62), (-60, 55), (-64, 48),
     (-70, 44), (-74, 39), (-77, 35), (-81, 31), (-80, 26), (-84, 29),
     (-90, 29), (-97, 26), (-97, 20), (-92, 15), (-86, 13), (-80, 8),
     (-84, 15), (-90, 20), (-97, 24), (-105, 22), (-110, 24),
     (-114, 30), (-120, 36), (-124, 44), (-126, 50), (-135, 58),
     (-152, 60), (-166, 62)],
    [(-79, 9), (-72, 12), (-64, 10), (-55, 6), (-50, 0), (-44, -3),
     (-38, -6), (-35, -9), (-40, -16), (-40, -22), (-48, -26),
     (-54, -33), (-58, -39), (-64, -42), (-65, -47), (-68, -52),
     (-70, -54), (-73, -50), (-73, -42), (-73, -33), (-70, -22),
     (-70, -18), (-75, -15), (-79, -8), (-81, -4), (-80, 1), (-77, 4)],
    [(-9, 43), (-2, 44), (-9, 37), (-9, 48), (-2, 50), (0, 46),
     (3, 43), (7, 44), (10, 44), (12, 42), (16, 40), (19, 42),
     (19, 46), (14, 48), (16, 50), (20, 52), (24, 56), (22, 58),
     (25, 60), (21, 62), (18, 61), (18, 56), (12, 55), (8, 54),
     (8, 50), (4, 48), (0, 46), (-2, 44), (-9, 43)],
    [(-6, 35), (0, 36), (10, 37), (11, 34), (20, 32), (30, 31),
     (34, 28), (38, 22), (42, 15), (45, 12), (51, 11), (51, 15),
     (48, 20), (43, 28), (40, 31), (36, 36), (30, 36), (22, 37),
     (15, 38), (10, 37), (0, 36), (-6, 35), (-10, 31), (-15, 27),
     (-17, 21), (-17, 15), (-13, 8), (-8, 5), (2, 6), (6, 4),
     (9, -1), (13, -12), (12, -18), (14, -24), (17, -30), (19, -34),
     (26, -34), (31, -29), (35, -24), (36, -20), (38, -16),
     (40, -12), (40, -6), (41, -1), (48, 5), (51, 10), (48, 11),
     (44, 11), (42, 14), (40, 20), (38, 26), (34, 28)],
    [(36, 36), (44, 38), (48, 40), (50, 44), (48, 48), (55, 52),
     (60, 55), (68, 58), (75, 62), (85, 66), (95, 70), (105, 72),
     (115, 73), (125, 72), (135, 71), (150, 70), (162, 68),
     (172, 66), (178, 65), (170, 60), (162, 56), (158, 52),
     (156, 48), (150, 45), (142, 46), (140, 40), (138, 36),
     (135, 34), (130, 33), (127, 34), (126, 38), (122, 38),
     (121, 34), (120, 28), (118, 25), (112, 22), (108, 18),
     (106, 9), (104, 2), (100, 6), (98, 10), (97, 16), (92, 16),
     (89, 22), (86, 20), (82, 16), (80, 13), (77, 8), (73, 16),
     (70, 21), (66, 25), (61, 25), (57, 26), (52, 26), (50, 28),
     (48, 30), (50, 26), (54, 24), (56, 26), (58, 23), (59, 22),
     (55, 17), (52, 15), (48, 14), (44, 12), (43, 16), (42, 20),
     (40, 28), (38, 30), (36, 32)],
    [(112, -22), (114, -28), (115, -34), (118, -35), (124, -33),
     (129, -32), (132, -32), (135, -35), (138, -36), (140, -38),
     (145, -38), (147, -39), (150, -37), (153, -31), (153, -27),
     (151, -24), (149, -20), (146, -19), (145, -15), (142, -11),
     (142, -14), (141, -18), (140, -22), (139, -26), (136, -28),
     (136, -32), (134, -33), (130, -32), (126, -32), (122, -30),
     (118, -28), (114, -24), (113, -20), (114, -16), (117, -14),
     (122, -14), (126, -12), (130, -12), (134, -12), (136, -15),
     (138, -18), (140, -20), (142, -22), (143, -26), (142, -30),
     (140, -33), (137, -35), (134, -34), (130, -33), (124, -33),
     (118, -35), (115, -32), (112, -26)],
]

PINS = [
    (30.7, 36.9, "ANTALYA"),
    (-121.9, 37.4, "NVIDIA"),
    (20.1, 32.1, "BENGHAZI"),
    (105.8, 21.0, "HANOI"),
    (35.2, 47.8, "ZAPORIZHZHIA"),
    (-73.6, 4.1, "COLOMBIA"),
    (159.9, -9.6, "SOLOMONS"),
    (44.4, 33.3, "BAGHDAD"),
]


# ------------------------------------------------------------- layout

MARGIN = 36
CW = W - 2 * MARGIN          # 952 content width
LINE_SOFT = (198, 188, 164)
GREY = (112, 105, 90)
LAND = (206, 192, 158)


def wrap(gs, text, size, max_w):
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if cur and _measure(gs, trial, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _measure(gs, s, size):
    total = 0.0
    for ch in s:
        total += gs.glyph(ch, size)[5] / SS
    return total


def border(cv, x, y, w, h, color=LINE_SOFT, t=1.4):
    cv.rect(x, y, w, t, color)
    cv.rect(x, y + h - t, w, t, color)
    cv.rect(x, y, t, h, color)
    cv.rect(x + w - t, y, t, h, color)


def draw_lead(cv, x, y, w, h, num, lead):
    cv.rect(x, y, w, h, CARD)
    border(cv, x, y, w, h)
    cv.rect(x, y, w, 56, lead["bg"])
    cv.text(SANS_B, lead["banner"], x + 16, y + 41, 37, lead["fg"])
    st = lead["status"]
    tw = _measure(SANS_B, st, 12)
    cv.text(SANS_B, st, x + w - 16 - tw, y + 36, 12, lead["fg"], tracking=1.2)
    cv.circle(x + 27, y + 82, 13.5, RED)
    cv.text_centered(SERIF_B, str(num), x + 27, y + 87.5, 15, WHITE)
    cv.text(SANS_B, lead["cat"], x + 50, y + 87, 12.5, RED, tracking=0.6)
    src = lead["src"]
    sw = _measure(SANS_B, src, 11)
    chip_w = sw + 16
    cv.rect(x + w - 14 - chip_w, y + 68, chip_w, 19, CHIP)
    cv.text(SANS_B, src, x + w - 14 - chip_w + 8, y + 81.5, 11, INK)
    lines = wrap(SERIF_B, lead["head"], 21.5, w - 32)
    for i, ln in enumerate(lines[:2]):
        cv.text(SERIF_B, ln, x + 16, y + 110 + i * 24, 21.5, INK)
    dlines = wrap(SANS, lead["desc"], 13.5, w - 32)
    for i, ln in enumerate(dlines[:2]):
        cv.text(SANS, ln, x + 16, y + 154 + i * 16.5, 13.5, INK)


def draw_mid(cv, x, y, w, h, num, mid):
    cv.rect(x, y, w, h, CARD)
    border(cv, x, y, w, h)
    cv.circle(x + 15, y + 17, 9.5, RED)
    cv.text_centered(SANS_B, str(num), x + 15, y + 20.5, 10.5, WHITE)
    cv.text(SANS_B, mid["cat"], x + 30, y + 21, 10, RED, tracking=0.4)
    lines = wrap(SERIF_B, mid["head"], 15.5, w - 20)
    for i, ln in enumerate(lines[:3]):
        cv.text(SERIF_B, ln, x + 10, y + 42 + i * 17.5, 15.5, INK)
    cv.text(SANS, mid["src"], x + 10, y + h - 6, 10, GREY, tracking=0.8)


def draw_map(cv, x, y, w, h):
    cv.rect(x, y, w, h, NAVY)
    cv.text(SANS_B, "WHERE IT HAPPENED", x + 14, y + 25, 14, GOLD,
            tracking=1.2)
    mx, my = x + 12, y + 38
    mw, mh = w - 24, h - 48

    def proj(lon, lat):
        return (mx + (lon + 180) / 360.0 * mw,
                my + (85 - lat) / 143.0 * mh)

    for poly in CONTINENTS:
        cv.polygon([proj(lon, lat) for (lon, lat) in poly], LAND)
    for (lon, lat, label) in PINS:
        px, py = proj(lon, lat)
        cv.circle(px, py, 4.6, RED)
        cv.circle(px, py, 1.9, WHITE)
        lw_ = _measure(SANS_B, label, 8.5)
        if px + 8 + lw_ <= mx + mw:
            cv.text(SANS_B, label, px + 8, py + 3, 8.5, WHITE)
        else:
            cv.text(SANS_B, label, px - 8 - lw_, py + 3, 8.5, WHITE)


def draw_also(cv, x, y, w, h):
    cv.rect(x, y, w, h, CARD)
    border(cv, x, y, w, h)
    cv.text(SANS_B, "ALSO ON TUESDAY", x + 14, y + 25, 14, NAVY,
            tracking=1.2)
    cv.rect(x + 14, y + 33, 42, 2.6, GOLD)
    col_w = (w - 28 - 16) / 2
    for i, item in enumerate(ALSO):
        col = i // 11
        row = i % 11
        ix = x + 14 + col * (col_w + 16)
        iy = y + 50 + row * 15.4
        cv.text(SANS_B, str(13 + i), ix, iy, 10.5, RED)
        cv.text_fit(SANS, item, ix + 24, iy, 11, INK, col_w - 24)


def build():
    cv = Canvas()
    # masthead
    cv.rect(0, 0, W, 136, NAVY)
    cv.text_centered(SANS_B, "THE DAY IN WORLD NEWS", W / 2, 42, 23, GOLD,
                     tracking=7)
    cv.rect(W / 2 - 100, 54, 200, 2.4, GOLD)
    cv.text_centered(SERIF_B, "Tuesday 24 November 2026", W / 2, 103, 57,
                     WHITE)
    cv.text_centered(SANS, "34 STORIES - 6 CONTINENTS - ONE PAGE", W / 2,
                     126, 14.5, (222, 200, 140), tracking=3)
    # subline
    cv.text_centered(SERIF_I,
                     "Climate talks collapse in Antalya, markets rocket "
                     "on Nvidia's return, and drones reach the "
                     "Mediterranean.", W / 2, 163, 18.5, INK)
    cv.rect(MARGIN, 174, CW, 1.3, LINE_SOFT)
    # leads: 2 x 2
    lw = (CW - 14) / 2
    for i, lead in enumerate(LEADS):
        lx = MARGIN + (i % 2) * (lw + 14)
        ly = 186 + (i // 2) * (176 + 10)
        draw_lead(cv, lx, ly, lw, 176, i + 1, lead)
    # mids: 2 rows of 4
    mw = (CW - 3 * 12) / 4
    for i, mid in enumerate(MIDS):
        mx = MARGIN + (i % 4) * (mw + 12)
        my = 560 + (i // 4) * (96 + 8)
        draw_mid(cv, mx, my, mw, 96, i + 5, mid)
    # bottom panels
    draw_map(cv, MARGIN, 770, 372, 206)
    draw_also(cv, MARGIN + 372 + 14, 770, CW - 372 - 14, 206)
    # footer
    srcs = ("WIRES AND SOURCES - REUTERS - AP - AFP - AL JAZEERA - "
            "TRT WORLD - EURONEWS - THE GUARDIAN - THE CONVERSATION - "
            "MIDDLE EAST EYE - GRIST - HORIZON - WAPO - UN NEWS")
    for i, ln in enumerate(wrap(SANS, srcs, 10, 596)):
        cv.text(SANS, ln, MARGIN, 997 + i * 14, 10, GREY)
    bx, bw = 648, 340
    cv.rect(bx, 984, bw, 34, NAVY)
    check = ("DATE CHECK - All 34 items carry a Tue 24 Nov dateline. "
             "Held back as off-day: Banten factory fire; Monday "
             "market records.")
    for i, ln in enumerate(wrap(SANS, check, 9, bw - 20)):
        cv.text(SANS, ln, bx + 10, 995 + i * 10.5, 9, WHITE)
    return cv.finish()


def main():
    rgb = build()
    os.makedirs("/output", exist_ok=True)
    write_png(OUT_PATH, W, H, rgb)


if __name__ == "__main__":
    main()
