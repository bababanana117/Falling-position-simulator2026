"""30 秒のモーショングラフィックス動画を描く（After Effects 風のポップな動き）。

絵は Pillow で 2 倍の大きさに描いてから縮小する（輪郭をなめらかにするため）。
数字はすべて data.json（prepare_data.py が研究の出力から作る）から読む。

    python video/music.py
    python video/render.py            # video/build/frames なしで直接 mp4 に書く
    python video/render.py --still 12.3 --out frame.png   # 1 枚だけ確かめる
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import timeline as TL

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
DATA = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
FONT_DIR = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji")
S = 2                      # 描画の倍率
W, H = TL.W, TL.H

# ポップな配色
NAVY = (22, 27, 58)
WHITE = (255, 255, 255)
YELLOW = (255, 210, 63)
PINK = (238, 66, 102)
TEAL = (59, 206, 172)
PURPLE = (84, 13, 110)
BLUE = (30, 144, 230)
GREEN = (14, 173, 105)
ORANGE = (255, 140, 40)
SKY_TOP, SKY_BOTTOM = (40, 120, 220), (120, 210, 255)

BG = {"intro": YELLOW, "balloon": BLUE, "jet": PINK, "season": PURPLE,
      "roses": TEAL, "map": NAVY, "seto": (36, 104, 186), "outro": YELLOW}


# --- イージング -----------------------------------------------------------------

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, t0, dur):
    return clamp((t - t0) / dur)


def out_cubic(x):
    return 1 - (1 - x) ** 3


def in_out_cubic(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out_back(x, s=1.9):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def out_elastic(x):
    x = clamp(x)
    if x in (0.0, 1.0):
        return x
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi) / 3) + 1


def beat_pulse(t):
    """拍の頭で 1、次の拍までに 0 へ減衰。"""
    ph = (t / TL.BEAT) % 1.0
    return math.exp(-ph * 6)


# --- 描画の道具 ------------------------------------------------------------------

@lru_cache(maxsize=256)
def font(size: int, weight: str = "Heavy") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"HaranoAjiGothic-{weight}.otf"), max(2, int(size)))


def P(x, y):
    return (x * S, y * S)


def circle(d: ImageDraw.ImageDraw, x, y, r, fill=None, outline=None, width=0):
    if r <= 0:
        return
    d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill,
              outline=outline, width=int(width * S))


def text(img: Image.Image, s: str, x, y, size, fill=WHITE, stroke=NAVY, stroke_w=6,
         anchor="mm", scale=1.0, shadow=True, weight="Heavy", alpha=1.0, rot=0.0):
    """文字を描く。scale と rot は文字の中心を基準にする。"""
    if scale <= 0.01 or alpha <= 0.01:
        return
    f = font(size * scale * S, weight)
    sw = int(stroke_w * scale * S)
    if rot == 0 and alpha >= 0.99 and "\n" not in s:
        d = ImageDraw.Draw(img)
        if shadow:
            d.text(((x + 5 * scale) * S, (y + 7 * scale) * S), s, font=f, fill=(0, 0, 0, 90),
                   anchor=anchor, stroke_width=sw, stroke_fill=(0, 0, 0, 90))
        d.text(P(x, y), s, font=f, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=stroke)
        return
    # 回転や半透明は別の層に描いて貼る
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.multiline_textbbox((0, 0), s, font=f, anchor="mm", stroke_width=sw,
                                    align="center")
    wl, hl = bbox[2] - bbox[0] + 60, bbox[3] - bbox[1] + 60
    layer = Image.new("RGBA", (int(wl), int(hl)), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    c = (wl / 2, hl / 2)
    if shadow:
        dl.multiline_text((c[0] + 5 * scale * S, c[1] + 7 * scale * S), s, font=f,
                          fill=(0, 0, 0, 90), anchor="mm", stroke_width=sw,
                          stroke_fill=(0, 0, 0, 90), align="center")
    dl.multiline_text(c, s, font=f, fill=fill, anchor="mm", stroke_width=sw,
                      stroke_fill=stroke, align="center")
    if rot:
        layer = layer.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.99:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    img.alpha_composite(layer, (int(x * S - layer.width / 2), int(y * S - layer.height / 2)))


def pop_chars(img, s: str, cx, cy, size, t, t0, step, fill=WHITE, stroke=NAVY):
    """1 文字ずつ弾むように出す。"""
    f = font(size * S)
    widths = [f.getlength(ch) / S for ch in s]
    total = sum(widths)
    x = cx - total / 2
    for k, ch in enumerate(s):
        p = prog(t, t0 + k * step, 0.35)
        sc = out_back(p, 2.6)
        yy = cy + (1 - out_cubic(p)) * 60
        text(img, ch, x + widths[k] / 2, yy, size, fill=fill, stroke=stroke, scale=sc)
        x += widths[k]


def pill(img, s, x, y, size, t, t0, bg=PINK, fg=WHITE, rot=0.0):
    """角丸の札を下から弾ませて出す。"""
    p = prog(t, t0, 0.4)
    if p <= 0:
        return
    sc = out_back(p, 2.2)
    f = font(size * S, "Heavy")
    w = f.getlength(s) / S + size * 1.4
    h = size * 1.7
    layer = Image.new("RGBA", (int((w + 30) * S), int((h + 30) * S)), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    dl.rounded_rectangle([8 * S, 12 * S, (w + 8) * S, (h + 12) * S], radius=h / 2 * S,
                         fill=(0, 0, 0, 70))
    dl.rounded_rectangle([0, 0, w * S, h * S], radius=h / 2 * S, fill=bg,
                         outline=NAVY, width=5 * S)
    dl.text((w / 2 * S, h / 2 * S), s, font=f, fill=fg, anchor="mm")
    layer = layer.resize((max(1, int(layer.width * sc)), max(1, int(layer.height * sc))),
                         Image.BICUBIC)
    if rot:
        layer = layer.rotate(rot, resample=Image.BICUBIC, expand=True)
    yy = y + (1 - out_cubic(p)) * 80
    img.alpha_composite(layer, (int(x * S - layer.width / 2), int(yy * S - layer.height / 2)))


def starburst(img, x, y, r, n, color, rot, sc=1.0):
    if sc <= 0.01:
        return
    d = ImageDraw.Draw(img)
    pts = []
    for k in range(2 * n):
        a = rot + k * math.pi / n
        rr = r * sc * (1.0 if k % 2 == 0 else 0.72)
        pts.append(P(x + rr * math.cos(a), y + rr * math.sin(a)))
    d.polygon(pts, fill=color, outline=NAVY, width=5 * S)


def arrow(d, x0, y0, x1, y1, color, width=8, head=26):
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    hb = min(head, L * 0.6)
    bx, by = x1 - ux * hb, y1 - uy * hb
    d.line([P(x0, y0), P(bx, by)], fill=color, width=int(width * S))
    px, py = -uy, ux
    d.polygon([P(x1, y1), P(bx + px * hb * 0.55, by + py * hb * 0.55),
               P(bx - px * hb * 0.55, by - py * hb * 0.55)], fill=color)


# --- 背景 ----------------------------------------------------------------------

def background(img, name, t):
    d = ImageDraw.Draw(img)
    col = BG[name]
    d.rectangle([0, 0, W * S, H * S], fill=col)
    lighter = tuple(min(255, int(c + (255 - c) * 0.18)) for c in col)
    darker = tuple(int(c * 0.85) for c in col)
    pulse = beat_pulse(t)
    if name in ("intro", "outro"):
        # 回る放射線
        cx, cy = W / 2, H / 2
        for k in range(18):
            a0 = t * 0.35 + k * 2 * math.pi / 18
            a1 = a0 + math.pi / 18
            R = 1600
            d.polygon([P(cx, cy), P(cx + R * math.cos(a0), cy + R * math.sin(a0)),
                       P(cx + R * math.cos(a1), cy + R * math.sin(a1))], fill=lighter)
    elif name in ("jet", "roses", "seto"):
        # 斜めの縞が流れる
        off = (t * 220) % 160
        for k in range(-4, 22):
            x0 = k * 160 + off - 400
            d.polygon([P(x0, 0), P(x0 + 70, 0), P(x0 + 70 + 500, H), P(x0 + 500, H)], fill=lighter)
    elif name == "season":
        # 水玉
        for i in range(0, 12):
            for j in range(0, 7):
                x = i * 170 + (j % 2) * 85 + (t * 30) % 170 - 80
                y = j * 170 + 40
                circle(d, x, y, 10 + 5 * pulse, fill=lighter)
    # 漂う円（奥行き）
    rng = np.random.default_rng(abs(hash(name)) % 1000)
    for k in range(7):
        bx, by = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(30, 90) * (1 + 0.08 * pulse)
        x = (bx + t * rng.uniform(-40, 40)) % (W + 200) - 100
        y = (by + math.sin(t * 1.3 + k) * 25)
        circle(d, x, y, r, outline=darker if name != "map" else (40, 60, 110), width=6)


def sky_gradient(img):
    arr = np.linspace(0, 1, H * S)[:, None]
    top, bot = np.array(SKY_TOP), np.array(SKY_BOTTOM)
    rows = (top[None, :] * (1 - arr) + bot[None, :] * arr).astype(np.uint8)
    grad = np.repeat(rows[:, None, :], W * S, axis=1)
    alpha = np.full((H * S, W * S, 1), 255, dtype=np.uint8)
    img.alpha_composite(Image.fromarray(np.concatenate([grad, alpha], axis=2), "RGBA"))


# --- 地図 ----------------------------------------------------------------------

class MapView:
    def __init__(self, south, north, west, east, x0, y0, x1, y1):
        self.s, self.n, self.w, self.e = south, north, west, east
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        lat_mid = math.radians((south + north) / 2)
        # 縦横比を地理に合わせる
        span_x = (east - west) * math.cos(lat_mid)
        span_y = north - south
        k = min((x1 - x0) / span_x, (y1 - y0) / span_y)
        self.kx, self.ky = k * math.cos(lat_mid), k
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.lon_c, self.lat_c = (west + east) / 2, (south + north) / 2

    def xy(self, lat, lon):
        return (self.cx + (lon - self.lon_c) * self.kx, self.cy - (lat - self.lat_c) * self.ky)

    def km(self, lat, lon, east_km, north_km):
        dlat = north_km / 111.195
        dlon = east_km / (111.195 * math.cos(math.radians(lat)))
        return self.xy(lat + dlat, lon + dlon)


def clip_ring(pts, x0, y0, x1, y1):
    """Sutherland–Hodgman で多角形を矩形に切る。大陸の輪は地球を半周するので、
    切らずに塗ると画面の外で折り返して海まで塗ってしまう。"""
    def cut(poly, inside, inter):
        out = []
        for k in range(len(poly)):
            a, b = poly[k - 1], poly[k]
            if inside(b):
                if not inside(a):
                    out.append(inter(a, b))
                out.append(b)
            elif inside(a):
                out.append(inter(a, b))
        return out

    def ix(a, b, x):
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def iy(a, b, y):
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    for inside, inter in (
        (lambda p: p[0] >= x0, lambda a, b: ix(a, b, x0)),
        (lambda p: p[0] <= x1, lambda a, b: ix(a, b, x1)),
        (lambda p: p[1] >= y0, lambda a, b: iy(a, b, y0)),
        (lambda p: p[1] <= y1, lambda a, b: iy(a, b, y1)),
    ):
        if not pts:
            break
        pts = cut(pts, inside, inter)
    return pts


def draw_land(img, mv: MapView, fill=(245, 240, 225), outline=NAVY):
    d = ImageDraw.Draw(img)
    for ring in DATA["coast"]:
        pts = clip_ring([mv.xy(la, lo) for lo, la in ring], -50, -50, W + 50, H + 50)
        if len(pts) >= 3:
            d.polygon([P(*q) for q in pts], fill=fill, outline=outline, width=3 * S)


# --- シーン ----------------------------------------------------------------------

def scene_intro(img, t):
    t0 = TL.SCENES["intro"][0]
    background(img, "intro", t)
    d = ImageDraw.Draw(img)
    # 弾ける円
    for k, (col, ang) in enumerate(((PINK, 0.3), (TEAL, 2.0), (BLUE, 3.6), (PURPLE, 5.0))):
        p = prog(t, t0 + 0.05 * k, 0.6)
        r = out_back(p) * 140
        x = W / 2 + math.cos(ang) * 620 * out_cubic(p)
        y = H / 2 + math.sin(ang) * 330 * out_cubic(p)
        circle(d, x, y, r * (1 + 0.1 * beat_pulse(t)), fill=col, outline=NAVY, width=6)
    line1, line2 = TL.TITLE_CHARS[:5], TL.TITLE_CHARS[5:]
    pop_chars(img, line1, W / 2, 400, 150, t, TL.TITLE_T0, TL.TITLE_STEP)
    pop_chars(img, line2, W / 2, 580, 150, t, TL.TITLE_T0 + len(line1) * TL.TITLE_STEP,
              TL.TITLE_STEP)
    pill(img, "JRA-3Q 再解析  2016–2025", W / 2, 760, 54, t, TL.beat(4), bg=PINK)
    p = prog(t, TL.beat(6), 0.4)
    if p > 0:
        starburst(img, 1560, 190, 150, 12, WHITE, t * 1.5, out_back(p))
        text(img, "スペース\nバルーンの\nために", 1560, 190, 34, fill=NAVY, stroke=WHITE,
             stroke_w=0, scale=out_back(p), rot=-12, shadow=False)


def scene_balloon(img, t):
    t0, t1 = TL.SCENES["balloon"]
    sky_gradient(img)
    d = ImageDraw.Draw(img)
    # 高度の帯と風の矢印（ジェットの層が最も速い）
    layers = [(930, "地上", 0.25), (760, "5 km", 0.5), (560, "12 km  ジェット気流", 1.0),
              (360, "20 km", 0.35), (180, "30 km", 0.45)]
    for y, label, spd in layers:
        d.line([P(0, y), P(W, y)], fill=(255, 255, 255, 90), width=2 * S)
        text(img, label, 60, y - 26, 30, anchor="lm", stroke_w=4, weight="Bold")
        for k in range(6):
            x = ((t - t0) * 420 * spd + k * 360) % (W + 300) - 150
            L = 60 + 170 * spd
            arrow(d, x, y + 20, x + L, y + 20, (255, 255, 255), width=6 + 6 * spd, head=24)
    # 気球の軌道
    p_up = prog(t, TL.BALLOON_LAUNCH, TL.BALLOON_BURST - TL.BALLOON_LAUNCH)
    e_up = in_out_cubic(p_up)
    def up_pos(e):
        y = 1000 - e * 830
        x = 260 + 520 * e ** 1.3
        return x, y
    bx, by = up_pos(e_up)
    # 軌跡（点線）
    for s in np.linspace(0, e_up, 40):
        x, y = up_pos(s)
        circle(d, x, y, 5, fill=WHITE)
    burst = t >= TL.BALLOON_BURST
    if not burst:
        wob = math.sin(t * 9) * 4
        d.line([P(bx, by + 60), P(bx + wob, by + 120)], fill=NAVY, width=3 * S)
        d.rectangle([(bx + wob - 18) * S, (by + 120) * S, (bx + wob + 18) * S, (by + 150) * S],
                    fill=ORANGE, outline=NAVY, width=4 * S)
        sc = 1 + 0.35 * e_up
        d.ellipse([(bx - 50 * sc) * S, (by - 60 * sc) * S, (bx + 50 * sc) * S, (by + 60 * sc) * S],
                  fill=PINK, outline=NAVY, width=5 * S)
        circle(d, bx - 18 * sc, by - 25 * sc, 12 * sc, fill=(255, 190, 205))
    else:
        # 破裂の粒とパラシュート
        pb = prog(t, TL.BALLOON_BURST, 0.5)
        x_b, y_b = up_pos(1.0)
        for k in range(14):
            a = k * 2 * math.pi / 14
            r = 30 + 170 * out_cubic(pb)
            circle(d, x_b + r * math.cos(a), y_b + r * math.sin(a), 14 * (1 - pb) + 2,
                   fill=YELLOW if k % 2 else PINK)
        pd_ = prog(t, TL.BALLOON_BURST + 0.1, t1 - TL.BALLOON_BURST - 0.1)
        px = x_b + 750 * out_cubic(pd_)
        py = y_b + 800 * pd_
        for s in np.linspace(0, pd_, 25):
            circle(d, x_b + 750 * out_cubic(s), y_b + 800 * s, 5, fill=YELLOW)
        d.pieslice([(px - 70) * S, (py - 60) * S, (px + 70) * S, (py + 60) * S], 180, 360,
                   fill=YELLOW, outline=NAVY, width=5 * S)
        d.line([P(px - 70, py), P(px, py + 70)], fill=NAVY, width=3 * S)
        d.line([P(px + 70, py), P(px, py + 70)], fill=NAVY, width=3 * S)
        d.rectangle([(px - 16) * S, (py + 70) * S, (px + 16) * S, (py + 98) * S], fill=ORANGE,
                    outline=NAVY, width=4 * S)
        text(img, "パン！", x_b + 20, y_b - 30, 80, fill=YELLOW, scale=out_back(pb, 3), rot=10)
    pill(img, "落下点 ＝ 全高度の風の足し算", 1350, 110, 50, t, t0 + TL.beat(1), bg=PINK)


def scene_jet(img, t):
    t0, _ = TL.SCENES["jet"]
    background(img, "jet", t)
    d = ImageDraw.Draw(img)
    # 速度線
    rng = np.random.default_rng(5)
    for k in range(26):
        y = rng.uniform(0, H)
        x = (rng.uniform(0, W) + (t - t0) * 1800 * rng.uniform(0.6, 1.4)) % (W + 600) - 300
        d.line([P(x, y), P(x + 180, y)], fill=(255, 255, 255, 110), width=3 * S)
    pop_chars(img, "冬の上空 12 km の風", W / 2, 150, 84, t, t0 + 0.05, 0.04)
    vals = DATA["jet_winter_200hpa"]
    names = list(vals)
    cols = [BLUE, YELLOW, TEAL]
    vmax = 95.0
    for k, name in enumerate(names):
        y = 360 + k * 190
        p = prog(t, TL.JET_T[k], 0.6)
        w = (1300 * vals[name] / vmax) * out_back(p, 1.4)
        text(img, name, 260, y, 64, anchor="rm", scale=out_back(prog(t, TL.JET_T[k] - 0.1, 0.3)))
        if w > 0:
            d.rounded_rectangle([300 * S, (y - 60) * S, (300 + w) * S, (y + 60) * S], radius=30 * S,
                                fill=cols[k], outline=NAVY, width=6 * S)
            v = vals[name] * out_cubic(p)
            text(img, f"{v:.0f}", 300 + w - 20, y, 76, anchor="rm", fill=WHITE, stroke=NAVY)
            text(img, "m/s", 300 + w + 20, y + 10, 40, anchor="lm", stroke_w=5,
                 alpha=clamp(p * 2))
    pb = prog(t, TL.JET_BADGE, 0.45)
    if pb > 0:
        starburst(img, 1680, 560, 170, 14, YELLOW, t * 1.2, out_elastic(pb))
        text(img, "約2倍！", 1680, 560, 74, fill=PINK, stroke=NAVY, scale=out_elastic(pb), rot=-8)


def scene_season(img, t):
    t0, _ = TL.SCENES["season"]
    background(img, "season", t)
    d = ImageDraw.Draw(img)
    pop_chars(img, "北海道・上空 12 km の 1 年", W / 2, 130, 72, t, t0 + 0.05, 0.035)
    vals = DATA["jet_hokkaido_200hpa"]
    x0, x1, y0, y1 = 200, 1720, 880, 300
    vmin, vmax = 20.0, 60.0
    def xy(i, v):
        return x0 + (x1 - x0) * i / 23, y0 - (y0 - y1) * (v - vmin) / (vmax - vmin)
    # 季節の帯
    bands = [(0, 3, "冬", BLUE), (4, 9, "春", GREEN), (10, 15, "夏", ORANGE),
             (16, 21, "秋", PINK), (22, 23, "冬", BLUE)]
    for a, b, name, col in bands:
        xa, xb = xy(a - 0.5, 0)[0], xy(b + 0.5, 0)[0]
        d.rectangle([max(xa, x0 - 20) * S, (y0 + 20) * S, min(xb, x1 + 20) * S, (y0 + 70) * S],
                    fill=col)
        text(img, name, (xa + xb) / 2, y0 + 45, 34, stroke_w=4, weight="Bold")
    for m in range(12):
        text(img, f"{m + 1}", xy(2 * m + 0.5, 0)[0], y0 + 105, 30, stroke_w=3, weight="Bold",
             shadow=False)
    for v in (20, 40, 60):
        yy = xy(0, v)[1]
        d.line([P(x0 - 20, yy), P(x1 + 20, yy)], fill=(255, 255, 255, 60), width=2 * S)
        text(img, f"{v}", x0 - 40, yy, 30, anchor="rm", stroke_w=3, weight="Bold", shadow=False)
    text(img, "m/s", x0 - 40, y1 - 50, 28, anchor="rm", stroke_w=3, weight="Bold", shadow=False)
    p = prog(t, TL.SEASON_DRAW[0], TL.SEASON_DRAW[1] - TL.SEASON_DRAW[0])
    upto = 23 * in_out_cubic(p)
    pts = [xy(i, vals[i]) for i in range(24) if i <= upto]
    if upto > 0:
        i0 = int(upto)
        if i0 < 23:
            f = upto - i0
            pts.append(xy(upto, vals[i0] * (1 - f) + vals[i0 + 1] * f))
        if len(pts) >= 2:
            d.line([P(*q) for q in pts], fill=YELLOW, width=12 * S, joint="curve")
        for q in pts[:-1]:
            circle(d, *q, 9, fill=WHITE, outline=NAVY, width=3)
        hx, hy = pts[-1]
        circle(d, hx, hy, 22 + 8 * beat_pulse(t), fill=YELLOW, outline=NAVY, width=5)
    k = int(np.argmax(vals))
    pb = prog(t, TL.SEASON_BADGE, 0.4)
    if pb > 0:
        mx, my = xy(k, vals[k])
        circle(d, mx, my, 40 * out_back(pb), outline=WHITE, width=8)
        pill(img, f"いちばん強いのは秋！ {vals[k]:.0f} m/s", mx - 380, my - 110, 46, t,
             TL.SEASON_BADGE, bg=PINK)


def draw_rose(img, cx, cy, fracs, t, t_in, color, label, note):
    d = ImageDraw.Draw(img)
    p = prog(t, t_in, 0.7)
    if p <= 0:
        return
    sc = out_back(p, 1.6)
    spin = (1 - out_cubic(p)) * 240
    R = 250 * sc
    circle(d, cx, cy, R + 20, fill=WHITE, outline=NAVY, width=6)
    for rr in (0.33, 0.66, 1.0):
        circle(d, cx, cy, R * rr, outline=(210, 210, 210), width=2)
    fmax = 0.95
    for k, f in enumerate(fracs):
        # 風配図の扇は「吹いてくる向き」。北が上、時計回り
        a_mid = math.radians(k * 22.5 + spin) - math.pi / 2
        r = R * min(f / fmax, 1.0) ** 0.5
        a0, a1 = a_mid - math.radians(10), a_mid + math.radians(10)
        d.polygon([P(cx, cy), P(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                   P(cx + r * math.cos(a_mid), cy + r * math.sin(a_mid)),
                   P(cx + r * math.cos(a1), cy + r * math.sin(a1))], fill=color,
                  outline=NAVY, width=2 * S)
    for ang, lab in ((0, "北"), (90, "東"), (180, "南"), (270, "西")):
        a = math.radians(ang) - math.pi / 2
        text(img, lab, cx + (R + 55) * math.cos(a), cy + (R + 55) * math.sin(a), 34,
             stroke_w=4, weight="Bold", scale=sc)
    pill(img, f"{label}：{note}", cx, cy + R + 140, 44, t, t_in + 0.5, bg=NAVY)


def scene_roses(img, t):
    t0, _ = TL.SCENES["roses"]
    background(img, "roses", t)
    pop_chars(img, "上空 31 km（破裂高度）の風向き", W / 2, 95, 64, t, t0 + 0.05, 0.03)
    ro = DATA["roses_10hpa"]
    top_jul = max(ro["jul"])
    top_oct = max(ro["oct"])
    draw_rose(img, 470, 520, ro["jul"], t, TL.ROSE_T[0], PINK, "7月後半",
              f"ほぼ一方向！ {100 * top_jul:.0f}%")
    draw_rose(img, 1450, 520, ro["oct"], t, TL.ROSE_T[1], PURPLE, "10月後半",
              f"バラバラ… 最多でも {100 * top_oct:.0f}%")
    pb = prog(t, TL.ROSE_TEXT, 0.4)
    if pb > 0:
        starburst(img, 960, 520, 130, 12, YELLOW, t, out_elastic(pb))
        text(img, "秋は\n向きが\n定まらない", 960, 520, 32, fill=NAVY, stroke=WHITE, stroke_w=0,
             scale=out_elastic(pb), shadow=False)


def lerp(a, b, x):
    return a + (b - a) * x


def scene_map(img, t):
    t0, t1 = TL.SCENES["map"]
    background(img, "map", t)
    # カメラ: 1 月は日本全体、7 月は西日本へズームイン
    z = in_out_cubic(prog(t, TL.MAP_SUMMER - 0.35, 0.55))
    s, n, w, e = DATA["map_box"]
    box = (lerp(s, 31.9, z), lerp(n, 35.5, z), lerp(w, 130.6, z), lerp(e, 138.0, z))
    mv = MapView(*box, 60, 170, 1860, 1050)
    draw_land(img, mv)
    d = ImageDraw.Draw(img)
    pw = prog(t, TL.MAP_WINTER, 0.8)
    fade_w = 1 - prog(t, TL.MAP_SUMMER - 0.45, 0.2)
    if pw > 0 and fade_w > 0:
        col = tuple(int(c * fade_w + NAVY[i] * (1 - fade_w)) for i, c in enumerate(PINK))
        for k, a in enumerate(DATA["winter_arrows"]):
            q = out_cubic(prog(t, TL.MAP_WINTER + 0.02 * k, 0.6))
            x0, y0 = mv.xy(a["lat"], a["lon"])
            x1, y1 = mv.km(a["lat"], a["lon"], a["e"] * q, a["n"] * q)
            circle(d, x0, y0, 9, fill=YELLOW, outline=NAVY, width=3)
            arrow(d, x0, y0, x1, y1, col, width=10, head=30)
        if fade_w > 0.5:
            pill(img, "1月：どこから上げても東へ約 250 km！", W / 2, 95, 50, t,
                 TL.MAP_WINTER + TL.beat(1), bg=PINK)
    if t >= TL.MAP_SUMMER:
        names = {"wakayama": "和歌山", "ehime": "愛媛"}
        for k, a in enumerate(x for x in DATA["summer_arrows"] if x["region"] in names):
            q = out_back(prog(t, TL.MAP_SUMMER + 0.15 * k, 0.6), 1.5)
            x0, y0 = mv.xy(a["lat"], a["lon"])
            x1, y1 = mv.km(a["lat"], a["lon"], a["e"] * q, a["n"] * q)
            circle(d, x0, y0, 16, fill=YELLOW, outline=NAVY, width=4)
            arrow(d, x0, y0, x1, y1, TEAL, width=14, head=36)
            text(img, names[a["region"]], x0 + 20, y0 + 58, 42, stroke_w=5, scale=q)
        pill(img, "7月：南は向きがくるっと西へ！", W / 2, 95, 50, t, TL.MAP_SUMMER + TL.beat(1),
             bg=TEAL, fg=NAVY)
    text(img, "矢印は実寸（矢先が平均の落下点）", W - 40, H - 36, 26, anchor="rm", stroke_w=3,
         weight="Bold", shadow=False)


def scene_seto(img, t):
    t0, _ = TL.SCENES["seto"]
    background(img, "seto", t)
    iki = DATA["iki"]
    mv = MapView(32.4, 35.1, 128.9, 134.6, 80, 190, 1840, 1050)
    d = ImageDraw.Draw(img)
    # 瀬戸内海を先に塗り、陸を重ねる（陸の下に隠れた部分は見えない）
    d.polygon([P(*mv.xy(la, lo)) for lo, la in iki["seto_polygon"]], fill=(125, 225, 255))
    draw_land(img, mv)
    d = ImageDraw.Draw(img)
    lx, ly = mv.xy(*iki["launch"])
    pr = prog(t, TL.SETO_RAIN[0], TL.SETO_RAIN[1] - TL.SETO_RAIN[0])
    pts = iki["points"]
    n_show = int(len(pts) * pr)
    for k, (la, lo, ok) in enumerate(pts[:n_show]):
        age = prog(t, TL.SETO_RAIN[0] + (TL.SETO_RAIN[1] - TL.SETO_RAIN[0]) * k / len(pts), 0.35)
        x1, y1 = mv.xy(la, lo)
        x = lx + (x1 - lx) * out_cubic(age)
        y = ly + (y1 - ly) * out_cubic(age) - math.sin(math.pi * age) * 120
        circle(d, x, y, 7 if ok else 5, fill=PINK if ok else (150, 150, 150),
               outline=NAVY if ok else None, width=1.5)
    ps = prog(t, TL.SETO_STAR, 0.4)
    if ps > 0:
        starburst(img, lx, ly, 34, 5, YELLOW, -math.pi / 2, out_back(ps, 3))
        text(img, "壱岐", lx, ly + 62, 40, scale=out_back(ps))
    pill(img, "冬に壱岐から上げると…", 520, 110, 50, t, t0 + TL.beat(0.5), bg=NAVY)
    p1 = prog(t, TL.SETO_P1, 0.5)
    if p1 > 0:
        # 数字は下の帯にまとめる（落下点の上に重ねない）
        sc = out_back(prog(t, TL.SETO_P1, 0.35), 2)
        panel = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dp = ImageDraw.Draw(panel)
        dp.rounded_rectangle([60 * S, (H - 250 - 60 * (1 - sc)) * S, 1100 * S, (H - 40) * S],
                             radius=40 * S, fill=(22, 27, 58, 230), outline=WHITE, width=5 * S)
        img.alpha_composite(panel)
        pct = 100 * iki["p_iki_standard_table"] * out_cubic(p1)
        text(img, f"{pct:.0f}%", 330, H - 150, 170, fill=YELLOW, scale=sc)
        text(img, "瀬戸内海 か\n雪のない平野 へ", 800, H - 150, 46, scale=sc)
    p2 = prog(t, TL.SETO_P2, 0.5)
    if p2 > 0:
        pill(img, f"速く上げれば {100 * iki['p_best']:.0f}%！", 1450, H - 150, 56, t, TL.SETO_P2,
             bg=PINK, rot=-4)


def scene_outro(img, t):
    t0, _ = TL.SCENES["outro"]
    background(img, "outro", t)
    pop_chars(img, "予報は 7 日先まで。", W / 2, 380, 110, t, TL.OUTRO_TEXT, 0.05)
    pop_chars(img, "計画は、統計風で。", W / 2, 560, 140, t, TL.OUTRO_TEXT + TL.beat(1), 0.06,
              fill=PINK)
    p = prog(t, TL.OUTRO_TEXT + TL.beat(3), 0.5)
    if p > 0:
        text(img, "データ: JRA-3Q（気象庁・NSF NCAR GDEX）／ ERA5 ／ 国土数値情報", W / 2, 900, 30,
             stroke_w=4, weight="Bold", alpha=p, shadow=False)
        text(img, "図は JRA-3Q の派生物（CC BY-NC-SA 4.0・非商用）", W / 2, 950, 28, stroke_w=4,
             weight="Bold", alpha=p, shadow=False)
    # 最後の一撃で白く光る
    pf = prog(t, TL.OUTRO_END, 0.35)
    if 0 < pf < 1:
        flash = Image.new("RGBA", img.size, (255, 255, 255, int(200 * (1 - pf))))
        img.alpha_composite(flash)


SCENE_FUNCS = {"intro": scene_intro, "balloon": scene_balloon, "jet": scene_jet,
               "season": scene_season, "roses": scene_roses, "map": scene_map,
               "seto": scene_seto, "outro": scene_outro}
ORDER = list(TL.SCENES)


def scene_at(t: float) -> str:
    for name, (a, b) in TL.SCENES.items():
        if a <= t < b:
            return name
    return ORDER[-1]


def shake(t: float) -> tuple[float, float]:
    """破裂と ding の瞬間だけ画面を揺らす。"""
    amp = 0.0
    for tt, kind in TL.SFX:
        if kind in ("burst", "ding", "crash") and 0 <= t - tt < 0.3:
            amp = max(amp, (1 - (t - tt) / 0.3) * (22 if kind == "burst" else 10))
    return amp * math.sin(t * 90), amp * math.cos(t * 77)


def frame(t: float) -> Image.Image:
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 255))
    name = scene_at(t)
    SCENE_FUNCS[name](img, t)
    # 次のシーンへの円形ワイプ（次の背景色の円が広がる）
    k = ORDER.index(name)
    if k + 1 < len(ORDER):
        t_next = TL.SCENES[ORDER[k + 1]][0]
        p = prog(t, t_next - 0.25, 0.25)
        if p > 0:
            d = ImageDraw.Draw(img)
            col = BG[ORDER[k + 1]]
            circle(d, W / 2, H / 2, 1200 * in_out_cubic(p), fill=col, outline=NAVY, width=10)
    # 新しいシーンの最初は、円の縁が画面外へ抜けていく
    t_start = TL.SCENES[name][0]
    if 0 < t - t_start < 0.2 and k > 0:
        d = ImageDraw.Draw(img)
        r = 1150 + 400 * (t - t_start) / 0.2
        circle(d, W / 2, H / 2, r, outline=NAVY, width=10)
    dx, dy = shake(t)
    out = img.resize((W, H), Image.LANCZOS).convert("RGB")
    if dx or dy:
        out = out.transform(out.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                            resample=Image.BILINEAR, fillcolor=NAVY)
    return out


def _render_bytes(i: int) -> bytes:
    return frame(i / TL.FPS).tobytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--still", type=float, help="この時刻の 1 枚だけを PNG に書く")
    ap.add_argument("--out", type=Path, default=BUILD / "still.png")
    ap.add_argument("--workers", type=int, default=14)
    a = ap.parse_args(argv)
    BUILD.mkdir(parents=True, exist_ok=True)
    if a.still is not None:
        frame(a.still).save(a.out)
        print(a.out)
        return 0
    n = int(round(TL.DURATION * TL.FPS))
    silent = BUILD / "video_silent.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(TL.FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p", str(silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(a.workers) as pool:
        for k, buf in enumerate(pool.imap(_render_bytes, range(n), chunksize=4)):
            proc.stdin.write(buf)
            if k % 150 == 0:
                print(f"frame {k}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    final = HERE / "wind_climatology_30s.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
                    "-i", str(BUILD / "audio.wav"), "-c:v", "copy",
                    # 動画サイトの基準（約 -14 LUFS）にそろえる
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=7", "-ar", "44100",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", str(final)], check=True)
    print(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
