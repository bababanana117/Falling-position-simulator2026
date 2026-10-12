"""シーン 5–9: 全国の結果、瀬戸内海、候補地の比較、壱岐の地上の風、壱岐の確率。"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

import engine as E
from engine import (
    GREEN,
    GREY,
    NAVY,
    ORANGE,
    PINK,
    TEAL,
    WHITE,
    YELLOW,
    P,
    circle,
    out_back,
    out_cubic,
    prog,
    text,
)

BLUE = E.BLUE

# --- 共通の小さな道具 ----------------------------------------------------------------


def snowflake(d, x, y, s, color=WHITE, rot=0.0):
    for a in range(6):
        ang = a * math.pi / 3 + rot
        d.line([P(x - s * math.cos(ang), y - s * math.sin(ang)),
                P(x + s * math.cos(ang), y + s * math.sin(ang))], fill=color, width=int(6 * E.S))
        for sign in (-1, 1):
            mx, my = x + 0.6 * s * math.cos(ang), y + 0.6 * s * math.sin(ang)
            d.line([P(mx, my), P(mx + sign * s * 0.22 * math.cos(ang + 1.0),
                                 my + sign * s * 0.22 * math.sin(ang + 1.0))], fill=color,
                   width=int(5 * E.S))


def wave_icon(d, x, y, s, color=TEAL, t=0.0):
    for row in range(2):
        yy = y - s * 0.3 + row * s * 0.55
        pts = [P(x - s + u * s * 2 / 24, yy + math.sin(u / 24 * 2 * math.pi + t * 3 + row) * s * 0.22)
               for u in range(25)]
        d.line(pts, fill=color, width=int(9 * E.S), joint="curve")


def stat_card(img, c: E.Ctx, x, y, t0, label, value, icon_kind, bg=WHITE, anchor_lat_lon=None,
              mv=None, fade_out_t0=None):
    """アイコン＋短い文の小さな札。地図上の地点から引き出し線を伸ばす。"""
    p = prog(c.t, t0, 0.4)
    if p <= 0:
        return
    alpha = 1.0
    if fade_out_t0 is not None:
        alpha = 1 - out_cubic(prog(c.t, fade_out_t0, 0.35))
        if alpha <= 0.01:
            return
    if anchor_lat_lon and mv is not None:
        ax, ay = mv.xy(*anchor_lat_lon)
        lp = prog(c.t, t0, 0.3)
        line_layer = Image.new("RGBA", (E.W * E.S, E.H * E.S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(line_layer)
        ld.line([P(ax, ay), P(x - 120 + 120 * lp, y + 40 - 40 * lp)], fill=(255, 255, 255, 200),
                width=int(3 * E.S))
        circle(ld, ax, ay, 8, fill=YELLOW, outline=NAVY, width=3)
        if alpha < 0.99:
            line_layer.putalpha(line_layer.getchannel("A").point(lambda v: int(v * alpha)))
        img.alpha_composite(line_layer)
    sc = out_back(p, 2.2)
    w, h = 300, 92
    pad = 40
    layer = Image.new("RGBA", (int((w + pad) * E.S), int((h + pad) * E.S)), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    E.rrect(dl, pad / 2 + 6, pad / 2 + 10, pad / 2 + w + 6, pad / 2 + h + 10, h / 2, fill=(0, 0, 0, 70))
    E.rrect(dl, pad / 2, pad / 2, pad / 2 + w, pad / 2 + h, h / 2, fill=bg, outline=NAVY, width=5)
    icx, icy = pad / 2 + 58, pad / 2 + h / 2
    if icon_kind == "snow":
        snowflake(dl, icx, icy, 30, color=BLUE, rot=c.T * 0.5)
    elif icon_kind == "wave":
        wave_icon(dl, icx, icy, 32, color=TEAL, t=c.T)
    text(layer, label, pad / 2 + 118, pad / 2 + h / 2 - 20, 26, fill=NAVY, stroke_w=0,
         shadow=False, anchor="lm")
    text(layer, value, pad / 2 + 118, pad / 2 + h / 2 + 24, 40, fill=PINK, stroke_w=0,
         shadow=False, anchor="lm")
    layer = layer.resize((max(1, int(layer.width * sc)), max(1, int(layer.height * sc))),
                         Image.BICUBIC)
    if alpha < 0.99:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    yy = y + (1 - out_cubic(p)) * 60
    img.alpha_composite(layer, (int(x * E.S - layer.width // 2), int(yy * E.S - layer.height // 2)))


def donut(img, cx, cy, r_out, r_in, segs, t, t0, dur=0.7):
    """segs: [(key, label, value, color)]。value の合計は 100 でなくてよい（自動で正規化）。
    戻り値: 各 key の (mid_angle_deg, frac) の辞書（強調表示に使う）。"""
    p = prog(t, t0, dur)
    info = {}
    total = sum(v for _, _, v, _ in segs)
    a0 = -90.0
    for key, _label, v, _col in segs:
        frac = v / total
        info[key] = (a0 + frac * 180.0, frac)
        a0 += frac * 360.0
    if p <= 0.01:
        return info
    sc = out_back(p, 1.7)
    ro, ri = r_out * sc, r_in * sc
    layer = Image.new("RGBA", (int(2 * (r_out + 40) * E.S), int(2 * (r_out + 40) * E.S)), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    lx, ly = layer.width / 2 / E.S, layer.height / 2 / E.S
    a0 = -90.0
    for key, _label, v, col in segs:
        frac = v / total
        a1 = a0 + frac * 360.0
        dl.pieslice([(lx - ro) * E.S, (ly - ro) * E.S, (lx + ro) * E.S, (ly + ro) * E.S], a0, a1,
                    fill=col, outline=NAVY, width=int(4 * E.S))
        a0 = a1
    circle(dl, lx, ly, ri, fill=(0, 0, 0, 0))
    circle(dl, lx, ly, ri, outline=NAVY, width=4)
    img.alpha_composite(layer, (int(cx * E.S - layer.width / 2), int(cy * E.S - layer.height / 2)))
    return info


def donut_callout(img, cx, cy, r_out, mid_deg, label, value_text, col, t, t0):
    p = prog(t, t0, 0.4)
    if p <= 0:
        return
    a = math.radians(mid_deg)
    ex, ey = cx + (r_out + 18) * math.cos(a), cy + (r_out + 18) * math.sin(a)
    side = 1 if math.cos(a) >= 0 else -1
    lx = ex + side * 170 * out_cubic(p)
    ly = ey - 90 * out_cubic(p)
    d = ImageDraw.Draw(img)
    d.line([P(ex, ey), P(lx, ly)], fill=col, width=int(6 * E.S))
    circle(d, ex, ey, 10, fill=col, outline=NAVY, width=3)
    E.pill(img, f"{label} {value_text}", lx + side * 30, ly, 34, t, t0, bg=col)


# === 5. japan ======================================================================

JAPAN_MV = E.MapView(24.0, 46.0, 122.0, 146.5, 300, 110, 1650, 940)
ZOOM_MV = E.MapView(31.0, 37.2, 128.3, 134.0, 260, 110, 1660, 945)
REGION_CALLOUTS = [
    ("北海道", "snow", (1690, 260)),
    ("東北", "snow", (1690, 430)),
    ("関東", "wave", (1690, 600)),
]
LEGEND_BOX = (1560, 872, 1850, 912)


@lru_cache(maxsize=1)
def _japan_grid_layer() -> Image.Image:
    return E.grid_layer(JAPAN_MV, E.NPZ["ptotal_std"], E.NPZ["lat"], E.NPZ["lon"], E.blues, 0.05)


@lru_cache(maxsize=1)
def _zoom_grid_layer() -> Image.Image:
    return E.grid_layer(ZOOM_MV, E.NPZ["ptotal_std"], E.NPZ["lat"], E.NPZ["lon"], E.blues, 0.05)


def _legend(img, c: E.Ctx, t0):
    a = out_cubic(prog(c.t, t0, 0.5))
    if a <= 0.01:
        return
    x0, y0, x1, y1 = LEGEND_BOX
    layer = Image.new("RGBA", (E.W * E.S, E.H * E.S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    n = 120
    for k in range(n):
        v = 60.0 * k / (n - 1)
        xa = x0 + (x1 - x0) * k / n
        xb = x0 + (x1 - x0) * (k + 1) / n
        ld.rectangle([xa * E.S, y0 * E.S, (xb + 1) * E.S, y1 * E.S], fill=E.blues(v) + (255,))
    E.rrect(ld, x0, y0, x1, y1, 6, outline=WHITE, width=3)
    if a < 0.99:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    img.alpha_composite(layer)
    text(img, "実施できる確率", (x0 + x1) / 2, y0 - 24, 24, fill=WHITE, alpha=a)
    text(img, "0 %", x0, y1 + 20, 24, fill=WHITE, alpha=a)
    text(img, "60 %", x1, y1 + 20, 24, fill=WHITE, alpha=a)


def japan(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    z = out_cubic(prog(c.t, c.line(2), 1.3))
    mv = JAPAN_MV.lerp(ZOOM_MV, z)
    E.draw_land(img, mv, fill=E.LAND, outline=None, width=0, japan_only=True)
    reveal = out_cubic(prog(c.t, c.line(0), 2.2))
    if reveal > 0.02:
        base = _japan_grid_layer()
        xw = max(1, int(E.W * E.S * reveal))
        crop = base.crop((0, 0, xw, base.height))
        if z < 0.995:
            fade1 = crop
            if z > 0:
                fade1 = fade1.copy()
                fade1.putalpha(fade1.getchannel("A").point(lambda v: int(v * (1 - z))))
            img.alpha_composite(fade1, (0, 0))
        if z > 0.005:
            zoom_layer = _zoom_grid_layer()
            fade2 = zoom_layer
            if z < 0.995:
                fade2 = fade2.copy()
                fade2.putalpha(fade2.getchannel("A").point(lambda v: int(v * z)))
            img.alpha_composite(fade2, (0, 0))
    E.draw_land(img, mv, fill=None, outline=WHITE, width=2, japan_only=True)
    _legend(img, c, c.line(0) + 0.3)
    if z > 0.02:
        rx, ry = mv.xy(33.5, 129.55)
        pulse = 1.0 + 0.12 * math.sin(c.T * 5.0)
        circle(d, rx, ry, 46 * pulse * z, outline=YELLOW, width=10)
        circle(d, rx, ry, 46 * pulse * z * 0.6, outline=YELLOW, width=6)
        circle(d, rx, ry, 9 * z, fill=YELLOW, outline=NAVY, width=3)
        bp = prog(c.t, c.line(2, 0.3), 0.5)
        if bp > 0:
            E.starburst(img, 1490, 290, 150, 13, YELLOW, c.T, out_back(bp))
            np_ = prog(c.t, c.line(2, 0.35), 0.9)
            num = E.count_up(E.DATA["region"]["九州北西"]["std"][2], np_)
            text(img, "最大", 1490, 195, 32, fill=NAVY, stroke=WHITE, stroke_w=5, shadow=False,
                 alpha=bp, scale=out_back(bp, 2.0))
            text(img, f"{num} %", 1490, 300, 92, fill=NAVY, stroke=WHITE, stroke_w=7,
                 shadow=False, scale=out_back(bp, 2.0))
            text(img, "九州北西部〜山口県西部", 1490, 420, 34, fill=WHITE,
                 alpha=prog(c.t, c.line(2, 0.5), 0.4))
    fade0 = c.line(2) - 0.4
    if c.t < fade0 + 0.4:
        for k, (name, icon_kind, (x, y)) in enumerate(REGION_CALLOUTS):
            la, lo, pct = E.DATA["region"][name]["std"]
            stat_card(img, c, x, y, c.line(1) + 0.12 * k, name, f"{pct} %", icon_kind,
                      anchor_lat_lon=(la, lo), mv=JAPAN_MV, fade_out_t0=fade0)


def japan_sfx(c):
    ev = [(c.line(0), "whoosh")]
    ev += [(c.line(1) + 0.12 * k, "pop") for k in range(3)]
    ev += [(c.line(2), "swish"), (c.line(2, 0.35), "ding")]
    return ev


# === 6. seto ========================================================================

SETO_MV = E.MapView(31.5, 36.2, 128.5, 136.5, 220, 150, 1720, 945)
IKI_SITE = next(s for s in E.DATA["sites"] if s["name"] == "壱岐（島の中央）")
CLS_STYLE = {0: ("瀬戸内海", GREEN), 1: ("平野", TEAL), 2: ("海岸近くの海", BLUE), 3: ("山地", ORANGE),
             4: ("沖", PINK), 5: ("市街地", GREY)}


@lru_cache(maxsize=1)
def _iki_member_order() -> np.ndarray:
    n = len(E.DATA["iki_members"]["pts"])
    rng = np.random.default_rng(3)
    return rng.permutation(n)


def seto(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    mv = SETO_MV
    E.draw_land(img, mv, japan_only=True)
    p0 = prog(c.t, c.line(0), 0.7)
    seto_pts = [mv.xy(la, lo) for lo, la in E.DATA["seto_polygon"]]
    if p0 > 0:
        glow = 0.5 + 0.5 * math.sin(c.T * 3.0)
        a = out_cubic(p0)
        glow_layer = Image.new("RGBA", (E.W * E.S, E.H * E.S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        for width, alpha in ((22, 60), (12, 130), (5, 255)):
            gd.polygon([P(*q) for q in seto_pts], outline=(*YELLOW, int(alpha * a)),
                       width=int(width * E.S * (0.7 + 0.3 * glow)))
        img.alpha_composite(glow_layer)
    pts = E.DATA["iki_members"]["pts"]
    order = _iki_member_order()
    n = len(pts)
    p1 = prog(c.t, c.line(1), 3.0)
    if p1 > 0:
        sx, sy = mv.xy(IKI_SITE["lat"], IKI_SITE["lon"])
        E.starburst(img, sx, sy, 30, 8, WHITE, c.T * 1.5, out_back(prog(c.t, c.line(1), 0.4)))
        n_show = int(n * out_cubic(p1))
        for rank, idx in enumerate(order[:n_show]):
            la, lo, _cls, ok = pts[idx]
            x, y = mv.xy(la, lo)
            fresh = 1.0 if n_show - rank < 40 else 0.0
            r = (4.5 if ok else 3.2) + 2.0 * fresh
            col = YELLOW if ok else GREY
            circle(d, x, y, r, fill=col)
        text(img, "壱岐から見た落下点（再現計算）", 960, 140, 38, fill=WHITE,
             alpha=out_cubic(prog(c.t, c.line(1), 0.5)) * (1 - out_cubic(prog(c.t, c.line(2), 0.3))))
    if p0 > 0:
        cx = sum(q[0] for q in seto_pts) / len(seto_pts)
        cy = sum(q[1] for q in seto_pts) / len(seto_pts)
        E.pill(img, "瀬戸内海", cx, cy - 40, 42, c.t, c.line(0, 0.15), bg=YELLOW, fg=NAVY)
    p2 = prog(c.t, c.line(2), 0.5)
    if p2 > 0:
        q = E.card(img, 1290, 150, 1870, 620, c.t, c.line(2), fill=(255, 255, 255, 240))
        if q > 0.2:
            text(img, "上位 5 地点の成功のうち\n瀬戸内海への着水の割合", 1580, 230, 30, fill=NAVY,
                 stroke_w=0, shadow=False, alpha=prog(c.t, c.line(2, 0.1), 0.3))
            top5 = [t[0] for t in E.DATA["top_std"]]
            shares = E.DATA["seto_share"]
            for k, (name, share) in enumerate(zip(top5, shares, strict=True)):
                y0 = 300 + k * 58
                E.bar_h(img, 1310, y0, 300, 34, share / 100, c.t, c.line(2, 0.25 + 0.06 * k),
                        YELLOW, label=name, value_text=f"{share} %", size=24, label_w=170, dur=0.6)
            lo, hi = min(shares), max(shares)
            text(img, f"{lo} 〜 {hi} %", 1580, 590, 46, fill=PINK, stroke_w=0, shadow=False,
                 scale=out_back(prog(c.t, c.line(2, 0.9), 0.4), 2.0))


def seto_sfx(c):
    ev = [(c.line(0), "swish"), (c.line(0, 0.15), "ding"), (c.line(1), "whoosh")]
    ev += [(c.line(1) + 0.4 + 0.4 * k, "tick") for k in range(6)]
    ev += [(c.line(2), "pop")]
    ev += [(c.line(2, 0.25 + 0.06 * k), "tick") for k in range(5)]
    ev += [(c.line(2, 0.9), "ding")]
    return ev


# === 7. ranking =====================================================================

RANK_SCALE = 55.0
RANK_X0, RANK_Y0, RANK_W, RANK_H, RANK_GAP, RANK_LABEL_W = 220, 310, 900, 74, 30, 300


@lru_cache(maxsize=1)
def _ci_by_name() -> dict:
    return {r["name"]: r["ci"] for r in E.DATA["ranking_std"]}


def _crown(d, x, y, s, p):
    if p <= 0.01:
        return
    e = out_back(p, 2.2)
    pts = [(x - s, y + s * 0.5), (x - s, y - s * 0.1), (x - s * 0.5, y + s * 0.25),
           (x - s * 0.2, y - s * 0.55), (x, y + s * 0.1), (x + s * 0.2, y - s * 0.55),
           (x + s * 0.5, y + s * 0.25), (x + s, y - s * 0.1), (x + s, y + s * 0.5)]
    cx = sum(q[0] for q in pts) / len(pts)
    cy = sum(q[1] for q in pts) / len(pts)
    scaled = [(cx + (px - cx) * e, cy + (py - cy) * e) for px, py in pts]
    d.polygon([P(*q) for q in scaled], fill=YELLOW, outline=NAVY, width=int(4 * E.S))


def _rank_rows(img, c: E.Ctx, rows, t0, color, crown_first=False):
    d = ImageDraw.Draw(img)
    for k, (name, val) in enumerate(rows):
        y0 = RANK_Y0 + k * (RANK_H + RANK_GAP)
        E.bar_h(img, RANK_X0, y0, RANK_W, RANK_H, val / RANK_SCALE, c.t, t0 + 0.08 * k, color,
                label=name, value_text=f"{val} %", size=34, label_w=RANK_LABEL_W, dur=0.7)
        if crown_first and k == 0:
            p = prog(c.t, t0 + 0.08 * k + 0.55, 0.4)
            if p > 0:
                bx = RANK_X0 + RANK_LABEL_W + RANK_W * val / RANK_SCALE
                tw = E.text_width(f"{val} %", 34)
                cx = bx + 20 + tw + 90
                E.starburst(img, cx, y0 + RANK_H / 2, 60, 10, YELLOW, c.T, out_back(p) * 0.7)
                _crown(d, cx, y0 + RANK_H / 2 - 10, 34, p)


def ranking(img, c: E.Ctx):
    switch = c.t >= c.line(2)
    if not switch:
        _rank_rows(img, c, E.DATA["top_std"], c.line(0), PINK)
        p1 = prog(c.t, c.line(1), 0.5)
        if p1 > 0:
            names = [n for n, _ in E.DATA["top_std"]]
            ci = _ci_by_name()
            los = [ci[n][0] for n in names if n in ci]
            his = [ci[n][1] for n in names if n in ci]
            lo, hi = min(los), max(his)
            x0 = RANK_X0 + RANK_LABEL_W + RANK_W * lo / RANK_SCALE
            x1 = RANK_X0 + RANK_LABEL_W + RANK_W * hi / RANK_SCALE
            y0 = RANK_Y0 - 30
            y1 = RANK_Y0 + 4 * (RANK_H + RANK_GAP) + RANK_H + 20
            a = out_cubic(p1)
            band = Image.new("RGBA", (E.W * E.S, E.H * E.S), (0, 0, 0, 0))
            bd = ImageDraw.Draw(band)
            E.rrect(bd, x0, y0, x1, y1, 20, fill=(255, 255, 255, int(80 * a)),
                    outline=(*WHITE, int(255 * a)), width=4)
            img.alpha_composite(band)
            text(img, "誤差の範囲", (x0 + x1) / 2, y0 - 34, 34, fill=WHITE, alpha=a)
            text(img, "どこも約 3 割", (x0 + x1) / 2, y1 + 50, 54, fill=YELLOW,
                 scale=out_back(prog(c.t, c.line(1, 0.2), 0.4), 1.8))
        text(img, "標準の飛行（破裂高度 約 30 km）", 960, 170, 38, fill=WHITE,
             alpha=prog(c.t, 0.1, 0.4))
    else:
        _rank_rows(img, c, E.DATA["top_short"], c.line(2), TEAL, crown_first=True)
        text(img, "破裂高度を 20 km に下げた短い飛行", 960, 170, 38, fill=WHITE,
             alpha=prog(c.t, c.line(2), 0.4))


def ranking_sfx(c):
    ev = [(c.line(0) + 0.08 * k, "pop") for k in range(5)]
    ev += [(c.line(1), "swish"), (c.line(1, 0.2), "ding")]
    ev += [(c.line(2), "whoosh")]
    ev += [(c.line(2) + 0.08 * k, "pop") for k in range(5)]
    ev += [(c.line(2, 0.63), "burst")]
    return ev


# === 8. amedas ======================================================================

GRID_BOX = (170, 220, 740, 790)
IKI_CENTER = (33.78, 129.72)


def _iki_sea_frac() -> float:
    """ERA5 が壱岐の格子を何 % 海として扱っているか（ERA5 の陸海マスクから、prepare_data.py）。"""
    return float(E.DATA["iki_cell_sea_pct"])


def _grid_island(img, c: E.Ctx, t0):
    p = prog(c.t, t0, 0.5)
    if p <= 0:
        return
    x0, y0, x1, y1 = GRID_BOX
    d = ImageDraw.Draw(img)
    sc = out_back(p, 1.6)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2 * sc, (y1 - y0) / 2 * sc
    gx0, gy0, gx1, gy1 = cx - hx, cy - hy, cx + hx, cy + hy
    E.rrect(d, gx0, gy0, gx1, gy1, 14, fill=(50, 110, 200, 230), outline=WHITE, width=5)
    for k in range(-8, 18):
        xa, ya = gx0 + k * 55, gy0
        xb, yb = gx0 + k * 55 - (gy1 - gy0), gy1
        d.line([P(max(gx0, min(gx1, xa)), ya), P(max(gx0, min(gx1, xb)), yb)],
               fill=(80, 150, 230, 140), width=int(6 * E.S))
    d.rectangle([gx0 * E.S, gy0 * E.S, gx1 * E.S, gy1 * E.S], outline=NAVY, width=int(5 * E.S))
    a = out_cubic(prog(c.t, t0 + 0.2, 0.4))
    isc = a * sc
    d.polygon([P(cx + 30 * isc, cy - 55 * isc), P(cx + 80 * isc, cy - 5 * isc),
               P(cx + 40 * isc, cy + 50 * isc), P(cx - 40 * isc, cy + 35 * isc),
               P(cx - 60 * isc, cy - 15 * isc)], fill=E.LAND, outline=NAVY, width=3)
    text(img, "ERA5 の 0.25° 格子 1 マス", cx, gy0 - 34, 32, fill=WHITE, alpha=a)
    if prog(c.t, t0 + 0.5, 0.3) > 0:
        frac = _iki_sea_frac()
        E.pill(img, f"再解析ではこの 1 マスの {round(frac)} % が海", cx, gy1 + 60, 32, c.t, t0 + 0.5,
               bg=YELLOW, fg=NAVY)


ANEMO_XY = (1470, 195)
ANEMO_LABEL_Y = 335
BAR_CAPTION_Y = 400
BAR_HEADER_Y = 455
BAR_NUMBER_Y = 515
BAR_TOP, BAR_BOTTOM, BAR_W = 575, 930, 220
BAR_CX = (1300, 1650)


def _anemometer(img, c: E.Ctx, x, y, t0, label_y):
    p = prog(c.t, t0, 0.5)
    if p <= 0:
        return
    d = ImageDraw.Draw(img)
    sc = out_back(p, 1.8)
    r = 70 * sc
    d.line([P(x, y + r * 0.2), P(x, y + r * 1.5)], fill=NAVY, width=int(10 * E.S))
    spin = c.T * 4.0
    for k in range(3):
        a = spin + k * 2 * math.pi / 3
        ex, ey = x + r * math.cos(a), y + r * math.sin(a) * 0.6 - r * 0.1
        d.line([P(x, y), P(ex, ey)], fill=NAVY, width=int(7 * E.S))
        circle(d, ex, ey, 16 * sc, fill=WHITE, outline=NAVY, width=4)
    circle(d, x, y, 12 * sc, fill=ORANGE, outline=NAVY, width=4)
    text(img, "アメダス 芦辺", x, label_y, 38, fill=WHITE, alpha=out_cubic(p))


def amedas(img, c: E.Ctx):
    p0 = prog(c.t, c.line(0), 0.5)
    if p0 > 0 and c.t < c.line(1) + 1.2:
        E.text(img, "では、壱岐は？", 960, 190, 94, fill=WHITE, scale=out_back(p0, 1.8))
    _grid_island(img, c, c.line(1))
    _anemometer(img, c, *ANEMO_XY, c.line(2), ANEMO_LABEL_Y)
    p3 = prog(c.t, c.line(3), 0.5)
    if p3 > 0:
        text(img, "壱岐（島の中央）9 時に打ち上げに向く日", (BAR_CX[0] + BAR_CX[1]) / 2,
             BAR_CAPTION_Y, 32, fill=WHITE, alpha=out_cubic(p3))
        d = E.DATA["amedas"]["壱岐（島の中央）"]
        bh_max = BAR_BOTTOM - BAR_TOP
        for k, (label, key, col) in enumerate((("再解析", "era5", GREY), ("観測", "obs", YELLOW))):
            x0 = BAR_CX[k] - BAR_W / 2
            v = d[key]
            q = prog(c.t, c.line(3) + 0.15 * k, 0.8)
            h = bh_max * (v / 100) * out_cubic(q)
            dd = ImageDraw.Draw(img)
            E.rrect(dd, x0, BAR_TOP, x0 + BAR_W, BAR_BOTTOM, 16, fill=(255, 255, 255, 50))
            E.rrect(dd, x0, BAR_BOTTOM - h, x0 + BAR_W, BAR_BOTTOM, 16, fill=col, outline=NAVY,
                    width=5)
            text(img, label, x0 + BAR_W / 2, BAR_HEADER_Y, 34, fill=WHITE,
                 alpha=out_cubic(prog(c.t, c.line(3) + 0.15 * k, 0.3)))
            E.big_number(img, v, "%", x0 + BAR_W / 2, BAR_NUMBER_Y, 52, c.t,
                         c.line(3) + 0.15 * k + 0.1, fill=col if col != GREY else WHITE, dur=0.7)


def amedas_sfx(c):
    return [(c.line(0), "pop"), (c.line(1), "swish"), (c.line(1, 0.2), "tick"),
            (c.line(2), "whoosh"), (c.line(3), "pop"), (c.line(3, 0.15), "pop"),
            (c.line(3, 0.9), "ding")]


# === 9. iki =========================================================================

WHY = E.DATA["iki"]["why"]
DONUT_SEGS = [
    ("success", "成功",
     WHY["success_seto"] + WHY["success_plain_ok"] + WHY["success_near_sea"], GREEN),
    ("mountain", "山地に着地", WHY["landing_mountain"], ORANGE),
    ("weather", "地上の風・雨", WHY["surface_weather"], BLUE),
    ("snow", "打ち上げ地の雪", WHY["launch_snow"], TEAL),
    ("rest", "その他", WHY["landing_far_sea"] + WHY["landing_urban"] + WHY["landing_snow"], GREY),
]
DONUT_CENTER = (960, 660)
DONUT_R = (300, 165)


def iki(img, c: E.Ctx):
    shrink = out_cubic(prog(c.t, c.line(2) - 0.3, 0.5))
    y_top = 300 - shrink * 130
    scale_top = 1.0 - shrink * 0.42
    p0 = prog(c.t, c.line(0), 0.9)
    if p0 > 0:
        cx = 620 - shrink * 260
        E.starburst(img, cx, y_top, 210 * scale_top, 14, YELLOW, c.T * 0.6, out_back(p0))
        numv = E.count_up(E.DATA["iki"]["p_std"], prog(c.t, c.line(0), 1.0))
        text(img, f"{numv} %", cx, y_top, 150 * scale_top, fill=NAVY, stroke=WHITE, stroke_w=7,
             shadow=False, scale=out_back(prog(c.t, c.line(0), 0.35), 2.2))
        if shrink < 0.5:
            ci = E.DATA["iki"]["ci_std"]
            E.pill(img, f"標準の飛行（{ci[0]}〜{ci[1]} %）", cx, y_top + 190 * scale_top,
                   26 * scale_top, c.t, c.line(0, 0.5), bg=WHITE, fg=NAVY)
    p1 = prog(c.t, c.line(1), 0.9)
    if p1 > 0:
        cx = 1300 - shrink * 260
        E.starburst(img, cx, y_top, 210 * scale_top, 14, TEAL, -c.T * 0.6, out_back(p1))
        numv = E.count_up(E.DATA["iki"]["p_short"], prog(c.t, c.line(1), 1.0))
        text(img, f"{numv} %", cx, y_top, 150 * scale_top, fill=NAVY, stroke=WHITE, stroke_w=7,
             shadow=False, scale=out_back(prog(c.t, c.line(1), 0.35), 2.2))
        if shrink < 0.5:
            ci = E.DATA["iki"]["ci_short"]
            E.pill(img, f"短い飛行（{ci[0]}〜{ci[1]} %）", cx, y_top + 190 * scale_top,
                   26 * scale_top, c.t, c.line(1, 0.5), bg=WHITE, fg=NAVY)
        p2r = prog(c.t, c.line(1, 0.9), 0.5)
        if p2r > 0 and shrink < 0.5:
            E.pill(img, "最有力候補のひとつ", 960, 560, 40, c.t, c.line(1, 0.9), bg=PINK)
    if shrink > 0.02:
        cx, cy = DONUT_CENTER
        ro, ri = DONUT_R
        info = donut(img, cx, cy, ro, ri, DONUT_SEGS, c.t, c.line(2) - 0.3)
        text(img, "9 時の判断の内訳", cx, cy, 32, fill=NAVY, stroke=WHITE, stroke_w=0,
             shadow=False, alpha=shrink)
        mid_s, frac_s = info["success"]
        donut_callout(img, cx, cy, ro, mid_s, "実施できる", f"{round(frac_s * 100)} %", GREEN, c.t,
                      c.line(2, 0.1))
        mid, frac = info["mountain"]
        donut_callout(img, cx, cy, ro, mid, "山地に着地", f"{round(frac * 100)} %", ORANGE, c.t,
                      c.line(2, 0.5))
        mid2, frac2 = info["weather"]
        donut_callout(img, cx, cy, ro, mid2, "地上の風・雨", f"{round(frac2 * 100)} %", BLUE, c.t,
                      c.line(3, 0.2))


def iki_sfx(c):
    return [(c.line(0), "burst"), (c.line(0, 0.5), "pop"), (c.line(1), "burst"),
            (c.line(1, 0.5), "pop"), (c.line(1, 0.9), "ding"), (c.line(2) - 0.3, "whoosh"),
            (c.line(2, 0.5), "pop"), (c.line(3, 0.2), "pop"), (c.line(3, 0.6), "ding")]


SCENES = {"japan": japan, "seto": seto, "ranking": ranking, "amedas": amedas, "iki": iki}
SFX = {"japan": japan_sfx, "seto": seto_sfx, "ranking": ranking_sfx, "amedas": amedas_sfx,
       "iki": iki_sfx}

_ = (Image, GREEN)
