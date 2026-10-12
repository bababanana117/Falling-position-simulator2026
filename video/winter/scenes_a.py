"""シーン 1–4: タイトル、条件、計算の方法、冬の風。"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

import engine as E
from engine import (
    BLUE,
    GREEN,
    NAVY,
    ORANGE,
    PINK,
    TEAL,
    WHITE,
    YELLOW,
    P,
    circle,
    in_out_cubic,
    out_back,
    out_cubic,
    prog,
    text,
)

# --- 1. タイトル ------------------------------------------------------------------

TITLE1 = "冬、どこから上げる？"
TITLE2 = "スペースバルーンの打ち上げ適地を日本全国から探す"


def balloon(d, x, y, r, col=PINK):
    """気球と吊り下げ機体。(x, y) は気球の中心。"""
    d.line([P(x, y + r), P(x, y + r * 2.2)], fill=NAVY, width=3 * E.S)
    E.rrect(d, x - r * 0.28, y + r * 2.2, x + r * 0.28, y + r * 2.6, 6, fill=WHITE, outline=NAVY,
            width=3)
    circle(d, x, y, r, fill=col, outline=NAVY, width=5)
    circle(d, x - r * 0.35, y - r * 0.35, r * 0.22, fill=(255, 255, 255, 170))


def intro(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    # 左右から上がる気球
    for k, (x0, col, spd) in enumerate(((55, PINK, 1.0), (1865, TEAL, 0.8), (135, BLUE, 1.25),
                                        (1785, ORANGE, 1.1))):
        p = prog(c.t, 0.1 * k, 0.8)
        if p <= 0:
            continue
        # 画面の下から上へ抜けていき、下からまた出てくる
        y = 1250 - out_cubic(p) * 350 - (c.t * 70 * spd) % 1500
        if y < -200:
            y += 1500
        balloon(d, x0 + math.sin(c.T * 1.5 + k) * 8, y, 34 + 4 * (k % 2), col)
    pop_t0 = 0.3
    bob = math.sin(c.T * 2.2) * 6
    E.pop_chars(img, TITLE1, E.W / 2, 380 + bob, 150, c.t, pop_t0, 0.06)
    p2 = prog(c.t, 1.3, 0.5)
    if p2 > 0:
        text(img, TITLE2, E.W / 2, 560, 58, scale=out_back(p2, 1.8), fill=WHITE)
    E.pill(img, "JRA-3Q × ERA5 × アメダス　2016–2025 年の冬", E.W / 2, 700, 44, c.t, 1.9,
           bg=PINK)
    # 2 文目で数字の札
    for k, (s_, col) in enumerate((("903 日", TEAL), ("15,324 地点", BLUE), ("確率", ORANGE))):
        E.pill(img, s_, E.W / 2 + (k - 1) * 360, 840, 46, c.t, c.line(1) + 0.25 * k, bg=col)
    p3 = prog(c.t, 2.4, 0.4)
    if p3 > 0:
        E.starburst(img, 1600, 220, 130, 12, WHITE, c.T * 1.2, out_back(p3))
        text(img, "確率で\n比べる", 1600, 220, 44, fill=PINK, stroke=WHITE, stroke_w=4,
             scale=out_back(p3), rot=-8)


def intro_sfx(c):
    ev = [(0.3 + k * 0.06, "pop") for k in range(0, len(TITLE1), 2)]
    ev += [(1.3, "swish"), (1.9, "pop"), (2.4, "ding")]
    return ev


# --- 2. 条件 --------------------------------------------------------------------

COND = [
    ("snow", "打ち上げ場所に\n雪がない", 1),
    ("wind", "地上の風 5 m/s 以下\n雨が降っていない", 2),
    ("target", "落下点が平野・瀬戸内海\n・海岸 3 km 以内の海", 3),
    ("snow2", "落下点にも\n雪がない", 3),
]


def icon(d, img, kind, x, y, s, t):
    """条件のアイコン。(x, y) は中心、s は大きさ。"""
    if kind in ("snow", "snow2"):
        for a in range(6):
            ang = a * math.pi / 3 + t * 0.4
            d.line([P(x, y), P(x + s * math.cos(ang), y + s * math.sin(ang))], fill=BLUE,
                   width=int(9 * E.S))
        circle(d, x, y, s * 0.18, fill=BLUE)
        # 禁止の輪
        circle(d, x, y, s * 1.15, outline=PINK, width=12)
        a = math.radians(-45)
        d.line([P(x - s * 0.8 * math.cos(a), y + s * 0.8 * math.sin(a)),
                P(x + s * 0.8 * math.cos(a), y - s * 0.8 * math.sin(a))], fill=PINK,
               width=int(12 * E.S))
        if kind == "snow2":
            text(img, "↓", x + s * 0.95, y - s * 0.9, s * 0.8, fill=ORANGE, stroke_w=4)
    elif kind == "wind":
        for k in range(3):
            yy = y - s * 0.5 + k * s * 0.5
            pts = [P(x - s + u * s * 2 / 20, yy + math.sin(u / 20 * 2 * math.pi + t * 4 + k)
                     * s * 0.12) for u in range(21)]
            d.line(pts, fill=TEAL, width=int(10 * E.S), joint="curve")
        text(img, "≤5", x + s * 0.7, y + s * 0.85, s * 0.55, fill=YELLOW, stroke_w=5)
    elif kind == "target":
        for k, col in enumerate((PINK, WHITE, PINK, WHITE)):
            circle(d, x, y + s * 0.2, s * (1.0 - 0.24 * k), fill=col, outline=NAVY, width=3)
        # パラシュート
        yy = y - s * 0.9 + (math.sin(t * 2) * s * 0.08)
        d.pieslice([(x - s * 0.5) * E.S, (yy - s * 0.35) * E.S, (x + s * 0.5) * E.S,
                    (yy + s * 0.35) * E.S], 180, 360, fill=ORANGE, outline=NAVY, width=3 * E.S)
        d.line([P(x - s * 0.5, yy), P(x, yy + s * 0.5)], fill=NAVY, width=2 * E.S)
        d.line([P(x + s * 0.5, yy), P(x, yy + s * 0.5)], fill=NAVY, width=2 * E.S)


def conditions(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    # 時計「毎朝 9:00」
    p = prog(c.t, c.line(0), 0.5)
    if p > 0:
        sc = out_back(p, 1.8)
        cx, cy, r = 330, 250, 110 * sc
        circle(d, cx, cy, r, fill=WHITE, outline=NAVY, width=8)
        for k in range(12):
            a = k * math.pi / 6
            circle(d, cx + 0.8 * r * math.sin(a), cy - 0.8 * r * math.cos(a), 5 * sc, fill=NAVY)
        spin = in_out_cubic(prog(c.t, c.line(0), 1.0))
        ah = math.radians(270 * spin)                    # 時針は 9 時へ
        am = math.radians(360 * 3 * spin)
        d.line([P(cx, cy), P(cx + 0.5 * r * math.sin(ah), cy - 0.5 * r * math.cos(ah))],
               fill=NAVY, width=int(12 * E.S))
        d.line([P(cx, cy), P(cx + 0.75 * r * math.sin(am), cy - 0.75 * r * math.cos(am))],
               fill=PINK, width=int(8 * E.S))
        circle(d, cx, cy, 10 * sc, fill=NAVY)
        text(img, "毎朝 9:00 に判断", 820, 250, 76, scale=out_back(prog(c.t, c.line(0, 0.2), 0.4)),
             fill=YELLOW)
    # 4 枚のカード
    cw, ch, gap = 400, 400, 36
    x_start = (E.W - (4 * cw + 3 * gap)) / 2
    for k, (kind, label, li) in enumerate(COND):
        t0 = c.line(li) + (0.9 if k == 3 else 0.0)
        x0 = x_start + k * (cw + gap)
        y0 = 400
        q = E.card(img, x0, y0, x0 + cw, y0 + ch, c.t, t0, fill=WHITE)
        if q <= 0.3:
            continue
        a = prog(c.t, t0 + 0.15, 0.3)
        icon(d, img, kind, x0 + cw / 2, y0 + 140, 80 * out_back(a, 1.5), c.T)
        text(img, label, x0 + cw / 2, y0 + 310, 33, fill=NAVY, stroke=WHITE, stroke_w=0,
             shadow=False, alpha=a)
        # 4 つそろった合図のチェック
        pc = prog(c.t, c.line(4) + 0.15 * k, 0.35)
        if pc > 0:
            circle(d, x0 + cw - 30, y0 + 30, 44 * out_back(pc, 2.5), fill=GREEN, outline=NAVY,
                   width=5)
            text(img, "✓", x0 + cw - 30, y0 + 30, 56, scale=out_back(pc, 2.5), stroke_w=0,
                 shadow=False)
    ps = prog(c.t, c.line(4, 0.9), 0.45)
    if ps > 0:
        text(img, "4 つそろった日 ＝ 実施できる日", E.W / 2, 875, 60, fill=YELLOW,
             scale=out_back(ps, 2.0), rot=-2 * (1 - out_cubic(ps)))


def conditions_sfx(c):
    ev = [(c.line(0), "pop"), (c.line(0, 0.2), "swish")]
    ev += [(c.line(li) + (0.9 if k == 3 else 0.0), "pop") for k, (_, _, li) in enumerate(COND)]
    ev += [(c.line(4) + 0.15 * k, "tick") for k in range(4)]
    ev.append((c.line(4, 0.9), "ding"))
    return ev


# --- 3. 計算の方法 -----------------------------------------------------------------

JP = E.MapView(24.0, 46.0, 122.5, 146.5, 1020, 150, 1860, 930)


@lru_cache(maxsize=1)
def candidate_points() -> np.ndarray:
    g = E.NPZ["ptotal_std"]
    ii, jj = np.nonzero(g >= 0)
    pts = np.column_stack([E.NPZ["lat"][ii], E.NPZ["lon"][jj]])
    rng = np.random.default_rng(1)
    return pts[rng.permutation(len(pts))]


def method(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    # 右: 日本の陸地に打ち上げ点がばらまかれる（カードより先に描く）
    pm = prog(c.t, c.line(1) - 0.3, 0.5)
    if pm > 0:
        E.draw_land(img, JP, fill=(255, 255, 255, int(60 + 60 * pm)), outline=WHITE, width=2,
                    clip=(960, 110, 1900, 950), japan_only=True)
        pts = candidate_points()
        n = int(len(pts) * out_cubic(prog(c.t, c.line(1), 1.6)))
        for la, lo in pts[:n:3]:
            x, y = JP.xy(la, lo)
            d.rectangle([(x - 2) * E.S, (y - 2) * E.S, (x + 2) * E.S, (y + 2) * E.S], fill=YELLOW)
    # 左: 数字のカード
    items = [(0, E.DATA["n_days"], "日", "2016–2025 年の 12–2 月の朝 9 時", YELLOW),
             (1, E.DATA["n_candidates"], "地点", "日本の陸地（約 5 km おき）", TEAL),
             (3, E.DATA["n_members"], "通り", "上昇の速さ・破裂の高さのばらつき", PINK)]
    for row, (li, val, unit, sub, col) in enumerate(items):
        y0 = 190 + row * 245
        q = E.card(img, 90, y0, 900, y0 + 205, c.t, c.line(li), fill=(255, 255, 255, 235))
        if q <= 0:
            continue
        E.big_number(img, val, unit, 470, y0 + 78, 96, c.t, c.line(li, 0.1), fill=col, dur=1.1)
        text(img, sub, 470, y0 + 170, 32, fill=NAVY, stroke_w=0, shadow=False,
             alpha=prog(c.t, c.line(li, 0.3), 0.3))
    # データの札
    E.pill(img, "上空の風: JRA-3Q（気象庁）", 1440, 820, 36, c.t, c.line(2), bg=BLUE)
    E.pill(img, "雪・地上の天気: ERA5", 1440, 910, 36, c.t, c.line(2, 0.6), bg=GREEN)
    # 64 通りの軌道を扇形に
    pf = prog(c.t, c.line(3), 1.0)
    if pf > 0:
        ox, oy = 1150, 560
        for k in range(16):
            a = math.radians(-12 + 24 * k / 15)
            L = 330 * out_cubic(prog(c.t, c.line(3) + 0.03 * k, 0.6))
            d.line([P(ox, oy), P(ox + L * math.cos(a), oy + L * math.sin(a) - 60 * math.sin(
                math.pi * L / 330))], fill=(255, 255, 255, 170), width=int(3 * E.S))
        circle(d, ox, oy, 16, fill=PINK, outline=NAVY, width=4)


def method_sfx(c):
    return [(c.line(0), "pop"), (c.line(1), "swish"), (c.line(2), "pop"), (c.line(2, 0.6), "pop"),
            (c.line(3), "swish"), (c.line(3, 0.1), "pop")]


# --- 4. 冬の風 --------------------------------------------------------------------

DRIFT_MAP = E.MapView(29.5, 46.0, 124.5, 146.0, 240, 120, 1680, 960)
KYUSHU_NW = (33.6, 129.9)


def drift(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    # 最後の文でズームイン（九州北西部と瀬戸内海）
    zoom_to = E.MapView(31.5, 36.5, 128.5, 136.5, 160, 150, 1760, 960)
    z = in_out_cubic(prog(c.t, c.line(2), 1.2))
    mv = DRIFT_MAP.lerp(zoom_to, z)
    E.draw_land(img, mv)
    # ジェット気流の帯（白い流れる破線）
    pj = prog(c.t, c.line(0), 0.8)
    if pj > 0:
        for band in range(3):
            lat0 = 31.5 + band * 1.3
            pts = []
            for u in range(40):
                lon = 124.5 + u * 0.6
                la = lat0 + 1.2 * math.sin((lon - 124) / 7.0) + band * 0.2
                pts.append(mv.xy(la, lon))
            n = int(len(pts) * out_cubic(pj))
            off = (c.T * 3) % 2
            for k in range(n - 1):
                if (k + int(off * 2)) % 3 == 0:
                    continue
                d.line([P(*pts[k]), P(*pts[k + 1])], fill=(255, 255, 255, 200),
                       width=int(10 * E.S))
        text(img, "ジェット気流（西風）", *mv.xy(36.3, 126.0), 44, fill=WHITE,
             alpha=out_cubic(pj) * (1 - z))
    # 平均の流され方の矢印（実寸）
    pa = prog(c.t, c.line(1), 1.2)
    if pa > 0 and z < 0.35:
        for k, (la, lo, e, n) in enumerate(E.DATA["arrows"]):
            q = out_cubic(prog(c.t, c.line(1) + 0.01 * k, 0.8))
            if q <= 0:
                continue
            x0, y0 = mv.xy(la, lo)
            x1, y1 = mv.km(la, lo, e * q, n * q)
            E.arrow(d, x0, y0, x1, y1, PINK, width=5, head=16)
            circle(d, x0, y0, 5, fill=NAVY)
        pb = prog(c.t, c.line(1, 1.0), 0.4)
        if pb > 0:
            E.starburst(img, 1560, 780, 150, 14, YELLOW, c.T, out_back(pb) * (1 - z))
            text(img, "東へ\n約 250 km", 1560, 780, 50, fill=NAVY, stroke=YELLOW, stroke_w=3,
                 scale=out_back(pb) * (1 - z), shadow=False)
    # ズーム後: 九州北西部から東へ 250 km の弧
    if z > 0.05:
        x0, y0 = mv.xy(*KYUSHU_NW)
        x1, y1 = mv.km(*KYUSHU_NW, 250, 20)
        pz = prog(c.t, c.line(2, 0.9), 0.7)
        circle(d, x0, y0, 22 * out_back(prog(c.t, c.line(2, 0.6), 0.4)), fill=YELLOW,
               outline=NAVY, width=5)
        if pz > 0:
            xm, ym = x0 + (x1 - x0) * out_cubic(pz), y0 + (y1 - y0) * out_cubic(pz)
            E.arrow(d, x0, y0, xm, ym, YELLOW, width=12, head=40)
            text(img, "打ち上げ場所の東に何がある？", E.W / 2, 150, 60, fill=YELLOW,
                 scale=out_back(pz, 1.8))


def drift_sfx(c):
    return [(c.line(0), "swish"), (c.line(1), "tick"), (c.line(1, 0.4), "tick"),
            (c.line(1, 1.0), "ding"), (c.line(2), "whoosh"), (c.line(2, 0.9), "swish")]


SCENES = {"intro": intro, "conditions": conditions, "method": method, "drift": drift}
SFX = {"intro": intro_sfx, "conditions": conditions_sfx, "method": method_sfx,
       "drift": drift_sfx}

_ = (Image, GREEN)
