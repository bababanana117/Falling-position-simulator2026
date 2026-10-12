"""冬の打ち上げ適地の紹介動画: 描画の道具とタイムライン。

絵は Pillow で 2 倍の大きさに描いてから縮小する（輪郭をなめらかにするため）。
シーンの長さはナレーションで決まる（build/timeline.json、tts.py が書く）。
まだ音声が無いときは、文字数から長さを見積もった仮のタイムラインを使う。

シーンを書く側は、各シーンの関数 ``draw(img, c)`` を作る。``c`` は Ctx で、
``c.t`` がシーンの頭からの秒、``c.line(k)`` が k 番目の文の読み始めの秒。
文に合わせて絵を出すと、ナレーションと画面がずれない。
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
FONT_DIR = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji")
S = 2
W, H = 1920, 1080
FPS = 30
BPM = 118.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT

# ポップな配色（30 秒版と同じ）
NAVY = (22, 27, 58)
WHITE = (255, 255, 255)
YELLOW = (255, 210, 63)
PINK = (238, 66, 102)
TEAL = (59, 206, 172)
PURPLE = (84, 13, 110)
BLUE = (30, 144, 230)
GREEN = (14, 173, 105)
ORANGE = (255, 140, 40)
SEA = (36, 104, 186)
LAND = (245, 240, 225)
GREY = (150, 150, 160)

#: シーン → (背景色, 背景の模様)。模様: rays / stripes / dots / plain
STYLE = {
    "intro": (YELLOW, "rays"), "conditions": (BLUE, "dots"), "method": (PURPLE, "stripes"),
    "drift": (SEA, "plain"), "japan": (NAVY, "plain"), "seto": (SEA, "plain"),
    "ranking": (PINK, "stripes"), "amedas": (TEAL, "dots"), "iki": (YELLOW, "rays"),
    "weekend": (PURPLE, "dots"), "sensitivity": (PINK, "stripes"), "spots": (GREEN, "dots"),
    "outro": (YELLOW, "rays"),
}
#: 画面左上の見出し
CHAPTER = {
    "intro": "", "conditions": "条件", "method": "計算の方法", "drift": "冬の風",
    "japan": "全国の結果", "seto": "なぜ九州北西部？", "ranking": "候補地の比較",
    "amedas": "壱岐の地上の風", "iki": "壱岐の確率", "weekend": "土日に上げたい",
    "sensitivity": "条件で変わる", "spots": "打ち上げ場所", "outro": "まとめ",
}
#: シーン → BGM の区間の種類（mix.py に渡す）
MUSIC = {
    "intro": "intro", "conditions": "verse", "method": "verse", "drift": "build",
    "japan": "drop", "seto": "drop", "ranking": "verse", "amedas": "break", "iki": "drop",
    "weekend": "verse", "sensitivity": "break", "spots": "verse", "outro": "outro",
}


# --- タイムライン ------------------------------------------------------------------

def _stub_timeline() -> dict:
    """音声がまだ無いときの仮のタイムライン（1 秒 7.5 文字で見積もる）。"""
    script = json.loads((BUILD / "script.json").read_text(encoding="utf-8"))
    scenes, t = [], 2 * BAR
    for s in script:
        start = t
        cur = start + 0.6
        lines = []
        for ln in s["lines"]:
            dur = len(ln["say"]) / 7.5
            lines.append({"text": ln["text"], "start": cur, "end": cur + dur})
            cur += dur + 0.35
        end_need = cur - 0.35 + 1.2 + (3 * BAR if s["id"] == "outro" else 0)
        n_bars = math.ceil((end_need - start) / BAR)
        scenes.append({"id": s["id"], "start": start, "end": start + n_bars * BAR,
                       "start_bar": round(start / BAR), "n_bars": n_bars, "lines": lines})
        t = start + n_bars * BAR
    scenes[0]["start"] = 0.0
    scenes[0]["start_bar"] = 0
    return {"bpm": BPM, "bar": BAR, "n_bars": round(t / BAR), "duration": t, "scenes": scenes,
            "stub": True}


def load_timeline() -> dict:
    p = BUILD / "timeline.json"
    if p.exists():
        tl = json.loads(p.read_text(encoding="utf-8"))
        if tl.get("scenes"):
            tl["scenes"][0]["start"] = 0.0          # タイトルは曲の頭から見せる
            return tl
    return _stub_timeline()


TL = load_timeline()
DURATION = TL["duration"]
SCENE_IDS = [s["id"] for s in TL["scenes"]]


@dataclass
class Ctx:
    """シーンを描くときに渡す情報。時刻はすべてシーンの頭からの秒。"""
    id: str
    t: float
    dur: float
    T: float                                  # 動画の頭からの秒
    start: float
    lines: list = field(default_factory=list)  # [(start, end, text)]

    def line(self, k: int, delay: float = 0.0) -> float:
        """k 番目の文の読み始め（シーンの頭から）。k が範囲外なら最後の文の終わり。"""
        if k < len(self.lines):
            return self.lines[k][0] + delay
        return (self.lines[-1][1] if self.lines else 0.0) + delay

    def line_end(self, k: int) -> float:
        return self.lines[min(k, len(self.lines) - 1)][1]

    def p(self, t0: float, dur: float) -> float:
        return prog(self.t, t0, dur)

    @property
    def pulse(self) -> float:
        return beat_pulse(self.T)

    @property
    def out(self) -> float:
        """シーンの最後 0.35 秒で 0→1。退場の動きに使う。"""
        return prog(self.t, self.dur - 0.45, 0.35)


def ctx_at(T: float) -> Ctx:
    for s in TL["scenes"]:
        if s["start"] <= T < s["end"] or s is TL["scenes"][-1]:
            lines = [(ln["start"] - s["start"], ln["end"] - s["start"], ln["text"])
                     for ln in s["lines"]]
            return Ctx(s["id"], T - s["start"], s["end"] - s["start"], T, s["start"], lines)
    raise ValueError(T)


# --- イージング --------------------------------------------------------------------

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, t0, dur):
    return clamp((t - t0) / dur) if dur > 0 else float(t >= t0)


def out_cubic(x):
    return 1 - (1 - clamp(x)) ** 3


def in_cubic(x):
    return clamp(x) ** 3


def in_out_cubic(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out_back(x, s=1.9):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def out_elastic(x):
    x = clamp(x)
    if x in (0.0, 1.0):
        return x
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi) / 3) + 1


def beat_pulse(T):
    """拍の頭で 1、次の拍までに 0 へ減衰。"""
    return math.exp(-((T / BEAT) % 1.0) * 6)


def lerp(a, b, x):
    return a + (b - a) * x


def mix_color(c1, c2, x):
    return tuple(int(lerp(a, b, clamp(x))) for a, b in zip(c1, c2, strict=False))


# --- 描画の道具 ---------------------------------------------------------------------

@lru_cache(maxsize=512)
def font(size: float, weight: str = "Heavy") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"HaranoAjiGothic-{weight}.otf"), max(2, int(size)))


def P(x, y):
    return (x * S, y * S)


def new_frame() -> Image.Image:
    return Image.new("RGBA", (W * S, H * S), (0, 0, 0, 255))


def circle(d, x, y, r, fill=None, outline=None, width=0):
    if r <= 0:
        return
    d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill,
              outline=outline, width=int(width * S))


def rrect(d, x0, y0, x1, y1, r, fill=None, outline=None, width=0):
    if x1 <= x0 or y1 <= y0:
        return
    d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill,
                        outline=outline, width=int(width * S))


def text(img, s, x, y, size, fill=WHITE, stroke=NAVY, stroke_w=6, anchor="mm", scale=1.0,
         shadow=True, weight="Heavy", alpha=1.0, rot=0.0):
    """文字を描く。scale と rot は文字の中心を基準にする。"""
    if scale <= 0.01 or alpha <= 0.01 or not s:
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
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    ax = {"l": 0.0, "m": 0.5, "r": 1.0}[anchor[0]] if anchor[0] in "lmr" else 0.5
    img.alpha_composite(layer, (int(x * S - layer.width * ax), int(y * S - layer.height / 2)))


def text_width(s: str, size: float, weight: str = "Heavy") -> float:
    return font(size * S, weight).getlength(s) / S


def pop_chars(img, s, cx, cy, size, t, t0, step, fill=WHITE, stroke=NAVY):
    """1 文字ずつ弾むように出す。"""
    f = font(size * S)
    widths = [f.getlength(ch) / S for ch in s]
    x = cx - sum(widths) / 2
    for k, ch in enumerate(s):
        p = prog(t, t0 + k * step, 0.35)
        text(img, ch, x + widths[k] / 2, cy + (1 - out_cubic(p)) * 60, size, fill=fill,
             stroke=stroke, scale=out_back(p, 2.6))
        x += widths[k]


def pill(img, s, x, y, size, t, t0, bg=PINK, fg=WHITE, rot=0.0, alpha=1.0):
    """角丸の札を下から弾ませて出す。"""
    p = prog(t, t0, 0.4)
    if p <= 0 or alpha <= 0.01:
        return
    sc = out_back(p, 2.2)
    f = font(size * S, "Heavy")
    w = f.getlength(s) / S + size * 1.4
    h = size * 1.7
    layer = Image.new("RGBA", (int((w + 30) * S), int((h + 30) * S)), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    dl.rounded_rectangle([8 * S, 12 * S, (w + 8) * S, (h + 12) * S], radius=h / 2 * S,
                         fill=(0, 0, 0, 70))
    dl.rounded_rectangle([0, 0, w * S, h * S], radius=h / 2 * S, fill=bg, outline=NAVY,
                         width=5 * S)
    dl.text((w / 2 * S, h / 2 * S), s, font=f, fill=fg, anchor="mm")
    layer = layer.resize((max(1, int(layer.width * sc)), max(1, int(layer.height * sc))),
                         Image.BICUBIC)
    if rot:
        layer = layer.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.99:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    yy = y + (1 - out_cubic(p)) * 80
    img.alpha_composite(layer, (int(x * S - layer.width / 2), int(yy * S - layer.height / 2)))


def card(img, x0, y0, x1, y1, t, t0, fill=WHITE, outline=NAVY, r=28, from_dir="up"):
    """影つきの角丸カードを弾ませて出す。戻り値は出現の進み（0〜1）。"""
    p = prog(t, t0, 0.45)
    if p <= 0:
        return 0.0
    e = out_back(p, 1.6)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sx = (x1 - x0) * e / 2
    sy = (y1 - y0) * e / 2
    dy = (1 - out_cubic(p)) * (80 if from_dir == "up" else -80)
    d = ImageDraw.Draw(img)
    rrect(d, cx - sx + 10, cy - sy + 14 + dy, cx + sx + 10, cy + sy + 14 + dy, r,
          fill=(0, 0, 0, 60))
    rrect(d, cx - sx, cy - sy + dy, cx + sx, cy + sy + dy, r, fill=fill, outline=outline,
          width=5)
    return p


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


def count_up(value: float, p: float, nd: int = 0) -> str:
    """数字を 0 から value まで数え上げる表示（p は 0〜1）。"""
    v = value * out_cubic(p)
    return f"{v:,.{nd}f}"


def big_number(img, value, unit, x, y, size, t, t0, dur=0.9, fill=YELLOW, nd=0,
               unit_size=None):
    """大きな数字をカウントアップしながら弾ませて出す。単位は右に小さく。"""
    p = prog(t, t0, dur)
    if p <= 0:
        return
    s = count_up(value, p, nd)
    sc = out_back(prog(t, t0, 0.35), 2.2)
    us = unit_size or size * 0.45
    wn = text_width(s, size) * sc
    wu = text_width(unit, us) * sc if unit else 0
    x0 = x - (wn + wu + 10) / 2
    text(img, s, x0 + wn / 2, y, size, fill=fill, scale=sc, stroke_w=8)
    if unit:
        text(img, unit, x0 + wn + 10 + wu / 2, y + size * 0.18, us, fill=fill, scale=sc)


def bar_h(img, x, y, w_full, h, frac, t, t0, color, label="", value_text="", size=40,
          label_w=260, dur=0.7):
    """横棒。左にラベル、右端に値。frac は 0〜1。"""
    p = prog(t, t0, dur)
    if p <= 0:
        return
    d = ImageDraw.Draw(img)
    a = out_cubic(prog(t, t0, 0.3))
    if label:
        text(img, label, x + label_w - 20, y + h / 2, size, anchor="rm", alpha=a, stroke_w=5)
    x0 = x + label_w
    rrect(d, x0, y, x0 + w_full, y + h, h / 2, fill=(255, 255, 255, 60))
    ww = max(h, w_full * frac * out_cubic(p))
    rrect(d, x0, y, x0 + ww, y + h, h / 2, fill=color, outline=NAVY, width=4)
    if value_text:
        text(img, value_text, x0 + ww + 20, y + h / 2, size, anchor="lm", alpha=a, stroke_w=5)


# --- 背景 ------------------------------------------------------------------------

def background(img, scene: str, T: float):
    col, kind = STYLE[scene]
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * S, H * S], fill=col)
    lighter = tuple(min(255, int(c + (255 - c) * 0.16)) for c in col)
    darker = tuple(int(c * 0.82) for c in col)
    pulse = beat_pulse(T)
    if kind == "rays":
        cx, cy = W / 2, H / 2
        for k in range(18):
            a0 = T * 0.25 + k * 2 * math.pi / 18
            a1 = a0 + math.pi / 18
            R = 1600
            d.polygon([P(cx, cy), P(cx + R * math.cos(a0), cy + R * math.sin(a0)),
                       P(cx + R * math.cos(a1), cy + R * math.sin(a1))], fill=lighter)
    elif kind == "stripes":
        off = (T * 160) % 160
        for k in range(-4, 22):
            x0 = k * 160 + off - 400
            d.polygon([P(x0, 0), P(x0 + 70, 0), P(x0 + 570, H), P(x0 + 500, H)], fill=lighter)
    elif kind == "dots":
        for i in range(12):
            for j in range(7):
                x = i * 170 + (j % 2) * 85 + (T * 30) % 170 - 80
                y = j * 170 + 40
                circle(d, x, y, 10 + 5 * pulse, fill=lighter)
    if kind != "plain":
        rng = np.random.default_rng(abs(hash(scene)) % 1000)
        for k in range(6):
            bx, by = rng.uniform(0, W), rng.uniform(0, H)
            r = rng.uniform(30, 90) * (1 + 0.08 * pulse)
            x = (bx + T * rng.uniform(-40, 40)) % (W + 200) - 100
            y = by + math.sin(T * 1.3 + k) * 25
            circle(d, x, y, r, outline=darker, width=6)


# --- 地図 ------------------------------------------------------------------------

DATA = json.loads((BUILD / "data.json").read_text(encoding="utf-8")) \
    if (BUILD / "data.json").exists() else {}
NPZ = dict(np.load(BUILD / "data.npz")) if (BUILD / "data.npz").exists() else {}


class MapView:
    """緯度経度 → 画面座標。縦横比は中央の緯度で合わせる。"""

    def __init__(self, south, north, west, east, x0, y0, x1, y1):
        self.s, self.n, self.w, self.e = south, north, west, east
        lat_mid = math.radians((south + north) / 2)
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

    def lerp(self, other: MapView, x: float) -> MapView:
        """2 つの地図の間を補間した地図（ズームの動き）。"""
        m = MapView.__new__(MapView)
        for a in ("kx", "ky", "cx", "cy", "lon_c", "lat_c"):
            setattr(m, a, lerp(getattr(self, a), getattr(other, a), x))
        return m


def clip_ring(pts, x0, y0, x1, y1):
    """Sutherland–Hodgman で多角形を矩形に切る。"""
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


def draw_land(img, mv: MapView, fill=LAND, outline=NAVY, width=3, clip=None,
              japan_only=False):
    """海岸線の陸地を塗る。clip=(x0, y0, x1, y1) で画面の一部に切る（地図を画面の片側に
    置くとき、大陸がはみ出して他の要素を覆わないように）。japan_only は大陸・朝鮮半島を省く。"""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = clip if clip else (-50, -50, W + 50, H + 50)
    for ring in DATA.get("coast", []):
        if japan_only and _is_mainland(ring):
            continue
        pts = clip_ring([mv.xy(la, lo) for lo, la in ring], x0, y0, x1, y1)
        if len(pts) >= 3:
            d.polygon([P(*q) for q in pts], fill=fill, outline=outline, width=width * S)


def _is_mainland(ring) -> bool:
    """ユーラシア大陸（朝鮮半島を含む）の輪か。点の数が多く、西端が東経 128 度より西。"""
    lons = [q[0] for q in ring]
    lats = [q[1] for q in ring]
    return len(ring) > 200 and min(lons) < 127.5 and max(lats) > 38


def grid_layer(mv: MapView, grid: np.ndarray, lat: np.ndarray, lon: np.ndarray, cmap,
               step: float, alpha: int = 255) -> Image.Image:
    """規則格子の値（-1 は欠け）を色の四角で描いた層（画面 2 倍の大きさ）。
    cmap は値 → RGB の関数。"""
    layer = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ii, jj = np.nonzero(grid >= 0)
    for i, j in zip(ii, jj, strict=True):
        x0, y1 = mv.xy(lat[i] - step / 2, lon[j] - step / 2)
        x1, y0 = mv.xy(lat[i] + step / 2, lon[j] + step / 2)
        if x1 < 0 or x0 > W or y1 < 0 or y0 > H:
            continue
        d.rectangle([x0 * S, y0 * S, x1 * S + 1, y1 * S + 1], fill=cmap(grid[i, j]) + (alpha,))
    return layer


def blues(v: float) -> tuple:
    """0〜60 % を白っぽい青から濃い青へ。"""
    x = clamp(v / 60.0)
    stops = [(0.0, (225, 236, 250)), (0.35, (120, 180, 240)), (0.7, (30, 110, 220)),
             (1.0, (10, 40, 120))]
    for (x0, c0), (x1, c1) in itertools.pairwise(stops):
        if x <= x1:
            return mix_color(c0, c1, (x - x0) / (x1 - x0))
    return stops[-1][1]


# --- 字幕・見出し・場面転換 ------------------------------------------------------------

def subtitle(img, c: Ctx):
    """読んでいる文を画面下に出す。長い文は 2 行に折る。"""
    cur = None
    for s0, s1, s in c.lines:
        if s0 - 0.1 <= c.t <= s1 + 0.25:
            cur = (s0, s1, s)
    if cur is None:
        return
    s0, s1, s = cur
    a = min(prog(c.t, s0 - 0.1, 0.15), 1 - prog(c.t, s1 + 0.1, 0.15))
    if a <= 0:
        return
    size = 40
    lines = wrap(s, size, 1500)
    h = 64 * len(lines) + 20
    y1 = H - 36
    y0 = y1 - h
    wmax = max(text_width(ln, size, "Bold") for ln in lines)
    layer = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rrect(d, W / 2 - wmax / 2 - 36, y0, W / 2 + wmax / 2 + 36, y1, 22, fill=(15, 18, 40, 200))
    for k, ln in enumerate(lines):
        text(layer, ln, W / 2, y0 + 42 + 64 * k, size, weight="Bold", stroke_w=0, shadow=False)
    if a < 0.99:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    img.alpha_composite(layer)


def wrap(s: str, size: float, max_w: float) -> list[str]:
    if text_width(s, size, "Bold") <= max_w:
        return [s]
    # 読点・句点で、なるべく真ん中に近いところで折る
    best, best_d = None, 1e9
    for k, ch in enumerate(s):
        if ch in "、。，" and 0 < k < len(s) - 1:
            d = abs(k - len(s) / 2)
            if d < best_d:
                best, best_d = k, d
    k = best + 1 if best is not None else len(s) // 2
    return [s[:k], s[k:]]


def chapter(img, c: Ctx):
    label = CHAPTER.get(c.id, "")
    if not label:
        return
    p = prog(c.t, 0.25, 0.4)
    q = 1 - prog(c.t, c.dur - 0.5, 0.3)
    if p <= 0 or q <= 0:
        return
    x = -300 + 300 * out_back(p, 1.4)
    d = ImageDraw.Draw(img)
    w = text_width(label, 34) + 60
    rrect(d, x + 40, 36, x + 40 + w, 96, 30, fill=NAVY)
    idx = SCENE_IDS.index(c.id)
    text(img, label, x + 40 + w / 2, 66, 34, stroke_w=0, shadow=False, alpha=q)
    # 進み具合の点
    n = len(SCENE_IDS)
    for k in range(1, n):
        cx = W - 60 - (n - 1 - k) * 26
        circle(d, cx, 66, 7 if k != idx else 11, fill=YELLOW if k <= idx else (255, 255, 255, 90),
               outline=NAVY, width=2)


def transition(img, c: Ctx):
    """次のシーンへの円形ワイプ。"""
    k = SCENE_IDS.index(c.id)
    d = ImageDraw.Draw(img)
    if k + 1 < len(SCENE_IDS):
        p = prog(c.t, c.dur - 0.3, 0.3)
        if p > 0:
            col = STYLE[SCENE_IDS[k + 1]][0]
            circle(d, W / 2, H / 2, 1200 * in_out_cubic(p), fill=col, outline=NAVY, width=10)
    if 0 < c.t < 0.22 and k > 0:
        circle(d, W / 2, H / 2, 1150 + 400 * c.t / 0.22, outline=NAVY, width=10)
