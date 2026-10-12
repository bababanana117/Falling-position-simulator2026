"""シーン 10–13: 土日に上げたい、条件で変わる、打ち上げ場所、まとめ。"""

from __future__ import annotations

import datetime as dt
import math
from functools import lru_cache

from PIL import Image, ImageDraw

import engine as E
from engine import (
    BLUE,
    GREEN,
    GREY,
    NAVY,
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

#: エンディングの credit 表示（変更したいときはここだけ直せばよい）
VOICE_CREDIT = "ナレーション: VOICEVOX:四国めたん"
DATA_CREDIT = ("データ: JRA-3Q（気象庁）/ ERA5（Copernicus）/ アメダス（気象庁）/ "
               "国土数値情報 / © OpenStreetMap contributors")
LICENSE_CREDIT = "CC BY-NC-SA 4.0（非商用）"

IKI = E.DATA["iki"]
WITHIN = IKI["within"]
WEEKS = ["1", "2", "3", "4", "6", "8"]


# ============================== 9. weekend ==========================================

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def _season_weekend_tiles() -> list[tuple[dt.date, bool]]:
    """壱岐の 2020/21 年の冬（実データ）の土日。点灯 = 打ち上げに向く確率 0.5 以上。"""
    daily = E.DATA["iki_members"]["daily"]
    out = []
    for s, p in zip(daily["dates"], daily["p"], strict=True):
        d = dt.date.fromisoformat(s)
        if dt.date(2020, 12, 1) <= d < dt.date(2021, 3, 1) and d.weekday() >= 5:
            out.append((d, p >= 0.5))
    return out


WEEKEND_TILES = _season_weekend_tiles()

CAL = (110, 150, 650, 420)
CARD1 = (690, 150, 1240, 420)
CARD2 = (1270, 150, 1810, 420)
TILES = (110, 440, 1810, 555)
STAIR = (110, 570, 1810, 945)


def _calendar_icon(d, img, x0, y0, x1, y1, t, t0):
    q = E.card(img, x0, y0, x1, y1, t, t0, fill=WHITE)
    if q <= 0.15:
        return
    cols = 7
    colw = (x1 - x0) / cols
    head_h = 52
    for i, lab in enumerate(WEEKDAY_LABELS):
        cx = x0 + i * colw + colw / 2
        hot = i >= 5
        col = BLUE if i == 5 else (PINK if i == 6 else NAVY)
        if hot:
            a = out_cubic(prog(t, t0 + 0.15, 0.4))
            if a > 0.01:
                bot = y1 - 10
                top = y0 + head_h + (bot - (y0 + head_h)) * (1 - a)
                tint = E.mix_color(WHITE, col, 0.3)
                E.rrect(d, x0 + i * colw + 4, top, x0 + (i + 1) * colw - 4, bot, 8, fill=tint)
        text(img, lab, cx, y0 + head_h / 2, 32, fill=col, stroke_w=0, shadow=False)
    rows = 4
    row_h = (y1 - y0 - head_h - 14) / rows
    for k in range(rows * cols):
        r, i = divmod(k, cols)
        cx = x0 + i * colw + colw / 2
        cy = y0 + head_h + 10 + r * row_h + row_h / 2
        p = out_back(prog(t, t0 + 0.35 + 0.018 * k, 0.3), 2.2)
        if p <= 0.01:
            continue
        hot = i >= 5
        fill = (BLUE if i == 5 else PINK) if hot else (222, 222, 232)
        circle(d, cx, cy, row_h * 0.3 * p, fill=fill, outline=NAVY, width=3)


def _stat_card(img, x0, y0, x1, y1, t, t0, label, value, unit, color):
    q = E.card(img, x0, y0, x1, y1, t, t0, fill=WHITE)
    if q <= 0.15:
        return
    h = y1 - y0
    a = prog(t, t0 + 0.15, 0.3)
    text(img, label, (x0 + x1) / 2, y0 + h * 0.24, 36, fill=NAVY, stroke_w=0, shadow=False,
         alpha=a)
    E.big_number(img, value, unit, (x0 + x1) / 2, y0 + h * 0.64, 118, t, t0 + 0.12, fill=color,
                 dur=1.0)


def _weekend_row(img, d, t, t0, x0, y0, x1, y1):
    a = out_cubic(prog(t, t0, 0.3))
    text(img, "ひと冬に実施できる土日", x0 + 10, y0 + 22, 36, anchor="lm", fill=WHITE,
         stroke_w=4, alpha=a)
    E.big_number(img, IKI["ok_weekend_days"], "日", x1 - 120, y0 + 22, 56, t, t0 + 0.25,
                 fill=YELLOW, nd=1, unit_size=34)
    groups: list[tuple[int, list[bool]]] = []
    cur_month, cur = None, []
    for day, ok in WEEKEND_TILES:
        if day.month != cur_month:
            if cur:
                groups.append((cur_month, cur))
            cur_month, cur = day.month, []
        cur.append(ok)
    if cur:
        groups.append((cur_month, cur))
    n_total = len(WEEKEND_TILES)
    gap_group, gap_tile = 22, 4
    n_gaps = len(groups) - 1
    usable = (x1 - x0) - n_gaps * gap_group - (n_total - len(groups)) * gap_tile
    tile_w = usable / n_total
    grid_top = y0 + 54
    grid_bot = y1 - 26
    tile_h = grid_bot - grid_top
    month_name = {12: "12月", 1: "1月", 2: "2月"}
    x = x0
    idx = 0
    for m, oks in groups:
        gx0 = x
        for ok in oks:
            p = out_cubic(prog(t, t0 + 0.035 * idx, 0.3))
            if p > 0.01:
                top = grid_top + tile_h * (1 - p)
                fill = TEAL if ok else (255, 255, 255, 70)
                E.rrect(d, x, top, x + tile_w - gap_tile, grid_bot, 6, fill=fill, outline=NAVY,
                        width=3)
            x += tile_w + gap_tile
            idx += 1
        gx1 = x - gap_tile
        pm = out_cubic(prog(t, t0 + 0.035 * (idx - len(oks)), 0.3))
        text(img, month_name[m], (gx0 + gx1) / 2, grid_bot + 18, 26, fill=WHITE, stroke_w=4,
             alpha=pm)
        x += gap_group - gap_tile


def _staircase(img, d, t, t0, x0, y0, x1, y1):
    if t < t0:
        return
    a = out_cubic(prog(t, t0, 0.3))
    text(img, "毎週末挑戦すると、N 週以内に上げられる確率", x0 + 10, y0 + 22, 36, anchor="lm",
         fill=WHITE, stroke_w=4, alpha=a)
    n = len(WEEKS)
    gap = 26
    bars_top, bars_bot = y0 + 55, y1 - 45  # 例: y ≈ 625–900（棒の面積を広く取る）
    bar_area = bars_bot - bars_top
    label_reserve = 60
    bw = (x1 - x0 - (n - 1) * gap) / n
    d.line([P(x0, bars_bot), P(x1, bars_bot)], fill=(255, 255, 255, 150), width=int(3 * E.S))
    for i, wk in enumerate(WEEKS):
        pct = WITHIN[wk]
        bx0 = x0 + i * (bw + gap)
        emph = wk in ("2", "4")
        ti = t0 + 0.16 * i
        p = out_cubic(prog(t, ti, 0.5))
        h = (bar_area - label_reserve) * (pct / 100) * p
        color = YELLOW if emph else TEAL
        E.rrect(d, bx0, bars_bot - h, bx0 + bw, bars_bot, 10, fill=color, outline=NAVY, width=4)
        aw = out_cubic(prog(t, ti, 0.3))
        text(img, f"{wk}週", bx0 + bw / 2, bars_bot + 28, 32, fill=WHITE, stroke_w=0,
             shadow=False, alpha=aw)
        if h <= 4:
            continue
        if emph:
            # 強調する週は、数字をスターバーストのバッジに乗せて目立たせる
            sp = prog(t, ti + 0.22, 0.4)
            if sp > 0:
                by = bars_bot - h - 58
                E.starburst(img, bx0 + bw / 2, by, 48, 9, YELLOW, t * 2, out_back(sp))
                sc = out_back(prog(t, ti + 0.3, 0.35), 2.0)
                text(img, f"{pct}%", bx0 + bw / 2, by, 40, fill=NAVY, stroke=YELLOW,
                     stroke_w=0, shadow=False, scale=sc)
        else:
            text(img, f"{pct}%", bx0 + bw / 2, bars_bot - h - 34, 34, fill=NAVY, stroke=WHITE,
                 stroke_w=0, shadow=False)


def weekend(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    t = c.t
    # 見出しはカードが出る前に縮んで消す（カードと重なるため）
    p0 = out_back(prog(t, c.line(0), 0.5), 2.0) * (1 - out_cubic(prog(t, c.line(1) - 0.35, 0.3)))
    if p0 > 0.01:
        text(img, "土日に上げたい", E.W / 2, 130, 60, fill=YELLOW, scale=p0)
    _calendar_icon(d, img, *CAL, t, c.line(0) + 0.2)
    _stat_card(img, *CARD1, t, c.line(1), "土日の 1 日を選ぶと", IKI["weekend_day"], "%", BLUE)
    _stat_card(img, *CARD2, t, c.line(1) + 0.5, "土曜か日曜のどちらか", IKI["weekend_either"], "%",
              PINK)
    _weekend_row(img, d, t, c.line(2), *TILES)
    _staircase(img, d, t, c.line(3), *STAIR)


def weekend_sfx(c):
    ev = [(c.line(0), "swish"), (c.line(0) + 0.2, "pop")]
    ev += [(c.line(1), "pop"), (c.line(1) + 0.5, "pop")]
    ev += [(c.line(2), "whoosh"), (c.line(2) + 0.25 + 0.035 * len(WEEKEND_TILES), "ding")]
    ev += [(c.line(3) + 0.16 * i, "tick") for i in range(len(WEEKS))]
    ev += [(c.line(3) + 0.16 * WEEKS.index("2") + 0.22, "ding"),
           (c.line(3) + 0.16 * WEEKS.index("4") + 0.22, "ding")]
    return ev


# ============================== 10. sensitivity =====================================

SENS_WIND = E.DATA["sens_wind"]
NO_SETO = E.DATA["no_seto_range"]
WIND_LO, WIND_HI, PCT_MAX = 3.0, 10.0, 50.0

CHART = (220, 210, 1720, 640)
SW_LO = SENS_WIND[0][1]
SW_HI = next(p for w, p in SENS_WIND if w == 5.0)


def _sens_xy(x0, y0, x1, y1, w, pct):
    x = x0 + (w - WIND_LO) / (WIND_HI - WIND_LO) * (x1 - x0)
    y = y1 - pct / PCT_MAX * (y1 - y0)
    return x, y


def _wind_chart(img, d, t, t0, x0, y0, x1, y1):
    a = out_cubic(prog(t, t0, 0.3))
    text(img, "地上の風の上限 (m/s) → 実施できる確率 (%)", (x0 + x1) / 2, y0 - 26, 32,
         fill=WHITE, stroke_w=4, alpha=a)
    pts = [_sens_xy(x0, y0, x1, y1, w, p) for w, p in SENS_WIND]
    nseg = out_cubic(prog(t, t0 + 0.15, 0.8)) * (len(pts) - 1)
    revealed = [pts[0]]
    for i in range(len(pts) - 1):
        f = E.clamp(nseg - i)
        if f <= 0:
            break
        ex = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
        ey = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
        revealed.append((ex, ey))
    # 線の下を白いカード風に塗って、他のカードと同じデザイン言語にそろえる
    if len(revealed) >= 2:
        poly = [(x0, y1), *revealed, (revealed[-1][0], y1)]
        d.polygon([P(*q) for q in poly], fill=WHITE, outline=NAVY, width=int(4 * E.S))
    else:
        d.line([P(x0, y1), P(x1, y1)], fill=WHITE, width=int(4 * E.S))
        d.line([P(x0, y0), P(x0, y1)], fill=WHITE, width=int(4 * E.S))
    if len(revealed) >= 2:
        d.line([P(*q) for q in revealed], fill=PINK, width=int(7 * E.S), joint="curve")
    for i, (w, p) in enumerate(SENS_WIND):
        pp = out_back(prog(t, t0 + 0.12 * i, 0.35), 2.2)
        if pp <= 0.01:
            continue
        x, y = _sens_xy(x0, y0, x1, y1, w, p)
        circle(d, x, y, 12 * pp, fill=YELLOW, outline=NAVY, width=4)
        text(img, f"{w:.0f}", x, y1 + 26, 26, fill=WHITE, stroke_w=4, alpha=pp)
        text(img, f"{p}%", x, y - 34, 28, fill=YELLOW, stroke_w=5, alpha=pp)
    ts = t0 + 1.1
    ps = prog(t, ts, 1.2)
    if ps <= 0:
        return
    e = out_cubic(ps)
    w_now = 5.0 + (3.0 - 5.0) * e
    pct_now = SW_HI + (SW_LO - SW_HI) * e
    x, y = _sens_xy(x0, y0, x1, y1, w_now, pct_now)
    d.line([P(x, y0 - 6), P(x, y1)], fill=(255, 255, 255, 170), width=int(3 * E.S))
    circle(d, x, y, 20, fill=PINK, outline=NAVY, width=5)
    # 数字は固定の場所に出す（ノブの位置は左端に寄っていくため）＆はっきり大きく
    rx = 380
    E.big_number(img, pct_now, "%", rx, 175, 96, 1.0, 0.0, dur=0.01, fill=YELLOW, unit_size=40)
    text(img, f"風 ≤{w_now:.1f} m/s", rx, 240, 38, fill=WHITE, stroke_w=5)


def _toggle(d, x, y, t, t0):
    w, h = 150, 66
    p = prog(t, t0, 0.5)
    off = out_cubic(p)
    col = E.mix_color(GREEN, GREY, off)
    E.rrect(d, x, y, x + w, y + h, h / 2, fill=col, outline=NAVY, width=5)
    kx = x + h / 2 + (w - h) * (1 - off)
    circle(d, kx, y + h / 2, h / 2 - 8, fill=WHITE, outline=NAVY, width=4)


def _seto_bar(img, d, t, t0, x0, y0, x1, y1):
    h = y1 - y0
    p = out_cubic(prog(t, t0 + 0.5, 1.0))
    frac0, frac1 = IKI["p_std"] / PCT_MAX, NO_SETO[1] / PCT_MAX
    frac = frac0 + (frac1 - frac0) * p
    E.rrect(d, x0, y0, x1, y1, h / 2, fill=(255, 255, 255, 60))
    ww = max(h, (x1 - x0) * frac)
    E.rrect(d, x0, y0, x0 + ww, y1, h / 2, fill=BLUE, outline=NAVY, width=4)
    p2 = prog(t, t0 + 1.1, 0.4)
    if p2 > 0:
        mx = x0 + (x1 - x0) * (NO_SETO[0] / PCT_MAX)
        d.line([P(mx, y0 - 12), P(mx, y1 + 12)], fill=YELLOW, width=int(6 * E.S))
    p3 = prog(t, t0 + 1.3, 0.4)
    if p3 > 0:
        text(img, f"{NO_SETO[0]}〜{NO_SETO[1]} %", x0 + ww + 110, (y0 + y1) / 2, 44, fill=YELLOW,
             scale=out_back(p3, 2.0))


def sensitivity(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    t = c.t
    # 見出しはカードが出る前に縮んで消す（カードと重なるため）
    p0 = out_back(prog(t, c.line(0), 0.5), 2.0) * (1 - out_cubic(prog(t, c.line(1) - 0.35, 0.3)))
    if p0 > 0.01:
        text(img, "条件の決め方で数字が動く", E.W / 2, 130, 58, fill=YELLOW, scale=p0)
    if p0 > 0.01 and t < c.line(1):
        cx, cy = 1650, 130
        for k in range(3):
            pw = prog(t, c.line(0) + 0.2, 0.5) * (1 - prog(t, c.line(1) - 0.3, 0.3))
            if pw > 0:
                knob_x = cx - 60 + 120 * (0.5 + 0.5 * math.sin(t * 2.0 + k))
                circle(d, cx - 80, cy, 8, fill=WHITE, outline=NAVY, width=3)
                circle(d, cx + 80, cy, 8, fill=WHITE, outline=NAVY, width=3)
                d.line([P(cx - 80, cy), P(cx + 80, cy)], fill=WHITE, width=int(6 * E.S))
                circle(d, knob_x, cy, 18 * out_back(pw, 2.0), fill=YELLOW, outline=NAVY, width=5)
    if t >= c.line(1):
        _wind_chart(img, d, t, c.line(1), *CHART)
    if t >= c.line(2):
        a = out_cubic(prog(t, c.line(2), 0.3))
        text(img, "瀬戸内海への着水を認めないと", 220, 738, 34, anchor="lm", fill=WHITE,
             stroke_w=4, alpha=a)
        _toggle(d, 220, 786, t, c.line(2) + 0.25)
        text(img, "瀬戸内海OK", 220 + 75, 786 + 66 + 30, 26, fill=WHITE, stroke_w=4, alpha=a)
        text(img, f"標準 {IKI['p_std']} %", 900, 738, 30, anchor="lm", fill=WHITE, stroke_w=4,
             alpha=a)
        _seto_bar(img, d, t, c.line(2), 900, 786, 1720, 852)


def sensitivity_sfx(c):
    ev = [(c.line(0), "swish"), (c.line(0) + 0.2, "pop")]
    ev += [(c.line(1) + 0.12 * i, "tick") for i in range(len(SENS_WIND))]
    ev += [(c.line(1) + 1.1, "whoosh"), (c.line(1) + 2.3, "ding")]
    ev += [(c.line(2) + 0.25, "pop"), (c.line(2) + 1.1, "tick"), (c.line(2) + 1.7, "crash")]
    return ev


# ============================== 11. spots ===========================================

# 右側に壱岐島の地図（OpenStreetMap の海岸線）と、島の打ち上げ候補地を出す。
SP = E.DATA["spots"]
IKI_MAP = E.MapView(33.695, 33.885, 129.605, 129.835, 800, 160, 1860, 870)
IKI_BOX = (790, 140, 1870, 885)
# 名前を出すのは距離（電線・建物・林まで）の大きい 3 か所
LABEL_TOP = 3
# 良い例・悪い例は画面左側（40 %）に縦に並べる。
GOOD_C = (400, 300)
BAD_C = (400, 690)
GB_SCALE = 0.72


def _good_bad(img, d, t, t0, t_exit):
    """良い例・悪い例のアイコン。t_exit に向けて中心へ縮んで消える（PIL は直描画の alpha を
    合成しないので、フェードは拡大縮小で表す）。"""
    enter = out_cubic(prog(t, t0, 0.4))
    leave = 1 - out_cubic(prog(t, t_exit, 0.35))
    grp = enter * leave
    if grp <= 0.01:
        return
    ta = grp  # 文字は本物の alpha 合成ができるので、そのままフェードに使う
    sc = GB_SCALE
    # 良い例: 広い空き地（背景が緑なので、はっきり見えるよう明るい色にする）
    gx, gy = GOOD_C
    field = E.mix_color(GREEN, WHITE, 0.55)
    E.rrect(d, gx - 260 * sc * grp, gy + 40 * sc * grp, gx + 260 * sc * grp,
            gy + 220 * sc * grp, 20, fill=field, outline=NAVY, width=5)
    circle(d, gx - 150 * sc * grp, gy - 130 * sc * grp,
           60 * sc * grp * out_back(prog(t, t0 + 0.05, 0.4), 2.0), fill=YELLOW)
    bp = grp * out_back(prog(t, t0 + 0.15, 0.4), 2.0)
    if bp > 0:
        bx, by, r = gx + 60 * sc * grp, gy - 30 * sc * grp, 55 * sc * bp
        d.line([P(bx, by + r), P(bx, by + r * 2.1)], fill=NAVY, width=int(3 * E.S))
        circle(d, bx, by, r, fill=PINK, outline=NAVY, width=5)
    text(img, "広い空き地", gx, gy + 270 * sc, 32, fill=NAVY, stroke=WHITE, stroke_w=0,
         shadow=False, alpha=ta)
    pc = grp * out_back(prog(t, t0 + 0.3, 0.35), 2.4)
    if pc > 0:
        circle(d, gx + 220 * sc * grp, gy + 60 * sc * grp, 36 * pc, fill=GREEN, outline=NAVY,
               width=5)
        text(img, "✓", gx + 220 * sc * grp, gy + 60 * sc * grp, 40, scale=pc, stroke_w=0,
             shadow=False, alpha=ta)
    # 悪い例: 電柱・電線・建物
    bx0, by0 = BAD_C
    E.rrect(d, bx0 - 260 * sc * grp, by0 + 40 * sc * grp, bx0 + 260 * sc * grp,
            by0 + 220 * sc * grp, 20, fill=(200, 200, 205), outline=NAVY, width=5)
    px = grp * out_cubic(prog(t, t0 + 0.1, 0.4))
    if px > 0:
        polex, poley = bx0 - 40 * sc * grp, by0 - 170 * sc * grp
        d.line([P(polex, poley), P(polex, by0 + 60 * sc * grp)], fill=(90, 70, 60),
               width=max(1, int(14 * E.S * px)))
        for k in range(3):
            yy = poley + (20 + k * 36) * sc * grp
            d.line([P(polex - 130 * sc * grp, yy - 20 * sc * grp),
                    P(polex + 150 * sc * grp, yy + 10 * sc * grp)],
                   fill=(60, 60, 70), width=max(1, int(6 * E.S * px)))
        for k in range(3):
            E.rrect(d, bx0 + 60 * sc * grp, by0 + (-150 + k * 55) * sc * grp,
                    bx0 + 220 * sc * grp, by0 + (-105 + k * 55) * sc * grp, 6,
                    fill=(120, 130, 150))
    fpo = grp * out_back(prog(t, t0 + 0.35, 0.4), 1.6)
    if fpo > 0:
        circle(d, bx0, by0 - 10 * sc * grp, 150 * sc * fpo, outline=PINK, width=14)
        ang = math.radians(-45)
        rr = 106 * sc * fpo
        d.line([P(bx0 - rr * math.cos(ang), by0 - 10 * sc * grp + rr * math.sin(ang)),
                P(bx0 + rr * math.cos(ang), by0 - 10 * sc * grp - rr * math.sin(ang))],
               fill=PINK, width=14)
    text(img, "電柱・電線あり", bx0, by0 + 270 * sc, 32, fill=NAVY, stroke=WHITE, stroke_w=0,
         shadow=False, alpha=ta)


@lru_cache(maxsize=1)
def _iki_layer() -> Image.Image:
    """壱岐島の地図の層（海の四角と陸）。1 回だけ描いて使い回す。"""
    layer = Image.new("RGBA", (E.W * E.S, E.H * E.S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = IKI_BOX
    E.rrect(d, x0 + 10, y0 + 14, x1 + 10, y1 + 14, 26, fill=(0, 0, 0, 70))
    E.rrect(d, x0, y0, x1, y1, 26, fill=E.SEA, outline=NAVY, width=5)
    for ring in SP["iki_coast"]:
        pts = E.clip_ring([IKI_MAP.xy(la, lo) for lo, la in ring], x0 + 6, y0 + 6, x1 - 6, y1 - 6)
        if len(pts) >= 3:
            d.polygon([P(*q) for q in pts], fill=E.LAND, outline=NAVY, width=2 * E.S)
    return layer


def _spots_map(img, d, t, t0, t1):
    """line(1): 地図と候補地が弾んで出る。line(2): 確率の札。"""
    a = out_back(prog(t, t0, 0.5), 1.4)
    if a <= 0.01:
        return
    lay = _iki_layer()
    if a < 0.999:
        cx, cy = (IKI_BOX[0] + IKI_BOX[2]) / 2, (IKI_BOX[1] + IKI_BOX[3]) / 2
        w, h = max(1, int(lay.width * a)), max(1, int(lay.height * a))
        small = lay.resize((w, h), Image.BILINEAR)
        img.alpha_composite(small, (int(cx * E.S * (1 - a)), int(cy * E.S * (1 - a))))
        return
    img.alpha_composite(lay)
    # 34 か所の点
    for i, (la, lo, clr, _name) in enumerate(SP["iki"]):
        p = out_back(prog(t, t0 + 0.5 + 0.05 * i, 0.3), 2.4)
        if p <= 0.01:
            continue
        x, y = IKI_MAP.xy(la, lo)
        col = YELLOW if clr >= 60 else WHITE
        circle(d, x, y, 11 * p, fill=col, outline=NAVY, width=4)
    # 空港（除外）
    pa = prog(t, t0 + 0.8, 0.4)
    if pa > 0:
        ax_, ay_ = IKI_MAP.xy(33.7493, 129.7853)
        r = (IKI_MAP.xy(33.7493 + 3 / 111, 129.7853)[1] - ay_)
        circle(d, ax_, ay_, abs(r) * out_cubic(pa), outline=PINK, width=4)
        text(img, "空港（除外）", ax_, ay_ + abs(r) + 26, 26, fill=PINK, stroke=WHITE, stroke_w=4,
             alpha=out_cubic(pa))
    # 名前のある所のうち距離の大きい 3 か所に名前。島の外の海に、西の点は左、東の点は右に並べる
    named = [r for r in SP["iki"] if not r[3].startswith("（")][:LABEL_TOP]
    left = sorted([r for r in named if r[1] < 129.72], key=lambda r: -r[0])
    right = sorted([r for r in named if r[1] >= 129.72], key=lambda r: -r[0])
    slots = [(r, 985, 330 + 150 * k) for k, r in enumerate(left)] + \
            [(r, 1690, 330 + 150 * k) for k, r in enumerate(right)]
    for k, ((la, lo, clr, name), lx, ly) in enumerate(slots):
        t_k = t0 + 2.2 + 0.25 * k
        q = out_cubic(prog(t, t_k, 0.35))
        if q <= 0.01:
            continue
        x, y = IKI_MAP.xy(la, lo)
        nm = name.replace("壱岐市立", "").replace("県立", "")
        d.line([P(x, y), P(x + (lx - x) * q, y + (ly - y) * q)], fill=NAVY, width=int(3 * E.S))
        circle(d, x, y, 14, fill=YELLOW, outline=NAVY, width=4)
        E.pill(img, f"{nm} {clr} m", lx, ly, 26, t, t_k + 0.1, bg=WHITE, fg=NAVY)
    # 左上の数字の札（地図の外、左側）
    E.pill(img, f"北部九州・山口 {SP['n_total']} か所", 420, 250, 40, t, t0 + 0.4, bg=BLUE)
    E.pill(img, f"壱岐島 {SP['n_iki']} か所", 420, 360, 52, t, t0 + 1.4, bg=PINK)
    text(img, "● 電線・建物・林から 60 m 以上", 420, 450, 28, fill=YELLOW, stroke=NAVY,
         stroke_w=5, alpha=out_cubic(prog(t, t0 + 1.8, 0.3)))
    # line(2): 島のどこでも同じ確率
    pp = prog(t, t1, 0.45)
    if pp > 0:
        lo_, hi_ = SP["iki_p_std"]
        E.starburst(img, 420, 640, 170, 16, YELLOW, E.beat_pulse(t) * 0.1 + t * 0.3,
                    out_back(pp, 1.8))
        text(img, f"{lo_}〜{hi_} %", 420, 625, 78, fill=NAVY, stroke=WHITE, stroke_w=6,
             scale=out_back(pp, 1.8))
        text(img, "島のどこでも", 420, 700, 32, fill=NAVY, stroke=WHITE, stroke_w=5,
             scale=out_back(pp, 1.8))


def _caution(img, d, t, t0):
    a = out_cubic(prog(t, t0, 0.4))
    if a <= 0.01:
        return
    cx, cy, s = 400, 450, 130
    p = out_back(prog(t, t0, 0.5), 2.2)
    pts = [(cx, cy - s * p), (cx - s * 0.9 * p, cy + s * 0.75 * p),
           (cx + s * 0.9 * p, cy + s * 0.75 * p)]
    d.polygon([P(*q) for q in pts], fill=YELLOW, outline=NAVY, width=8)
    text(img, "！", cx, cy + s * 0.18 * p, 90 * p, fill=NAVY, stroke_w=0, shadow=False)
    text(img, "現地で電線・立ち入りを\n確認", cx, cy + 230, 38, fill=WHITE, stroke_w=5,
         alpha=out_cubic(prog(t, t0 + 0.25, 0.35)))


def spots(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    t = c.t
    _good_bad(img, d, t, c.line(0), c.line(1) + 0.15)
    # 注意の札が出たら、左の数字は消して入れ替える
    if t < c.line(3):
        _spots_map(img, d, t, c.line(1), c.line(2))
    else:
        img.alpha_composite(_iki_layer())
        for la, lo, clr, _ in SP["iki"]:
            x, y = IKI_MAP.xy(la, lo)
            circle(d, x, y, 11, fill=YELLOW if clr >= 60 else WHITE, outline=NAVY, width=4)
        _caution(img, d, t, c.line(3))


def spots_sfx(c):
    ev = [(c.line(0), "pop"), (c.line(0) + 0.15, "pop"), (c.line(0) + 0.35, "crash")]
    ev += [(c.line(1), "whoosh"), (c.line(1) + 0.4, "pop"), (c.line(1) + 1.4, "pop")]
    ev += [(c.line(1) + 0.5 + 0.05 * i, "tick") for i in range(0, len(SP["iki"]), 3)]
    ev += [(c.line(2), "ding"), (c.line(3), "pop")]
    return ev


# ============================== 12. outro ===========================================

P_STD, P_SHORT = IKI["p_std"], IKI["p_short"]
DAYS_LIT = round(P_STD / 10)

CARD_A = (140, 160, 940, 480)
CARD_B = (980, 160, 1780, 480)


def _day_icons(img, d, t, t0, x0, y0, n, lit):
    for i in range(n):
        cx = x0 + i * 86
        p = out_back(prog(t, t0 + 0.06 * i, 0.35), 2.4)
        if p <= 0.01:
            continue
        on = i < lit
        fill = YELLOW if on else (255, 255, 255, 90)
        E.rrect(d, cx - 30 * p, y0 - 34 * p, cx + 30 * p, y0 + 34 * p, 10, fill=fill,
                outline=NAVY, width=4)
        if on:
            text(img, "✓", cx, y0, 30 * p, fill=NAVY, stroke_w=0, shadow=False)


def _mini_calendar(img, d, x, y, t, t0, done):
    p = out_back(prog(t, t0, 0.4), 2.4)
    if p <= 0.01:
        return
    r = 55 * p
    E.rrect(d, x - r, y - r, x + r, y + r, 14, fill=WHITE, outline=NAVY, width=5)
    d.line([P(x - r, y - r * 0.15), P(x + r, y - r * 0.15)], fill=NAVY, width=int(4 * E.S))
    if done:
        pc = out_back(prog(t, t0 + 0.2, 0.35), 2.4)
        if pc > 0:
            circle(d, x, y + r * 0.35, 26 * pc, fill=GREEN, outline=NAVY, width=4)
            text(img, "✓", x, y + r * 0.35, 30 * pc, stroke_w=0, shadow=False)


def outro(img, c: E.Ctx):
    d = ImageDraw.Draw(img)
    t = c.t
    E.card(img, *CARD_A, t, c.line(0), fill=WHITE)
    if t >= c.line(0):
        a = prog(t, c.line(0) + 0.15, 0.3)
        text(img, "冬の最適地", (CARD_A[0] + CARD_A[2]) / 2, CARD_A[1] + 90, 40, fill=NAVY,
             stroke_w=0, shadow=False, alpha=a)
        text(img, "九州北西部〜山口県", (CARD_A[0] + CARD_A[2]) / 2, CARD_A[1] + 190, 52,
             fill=PINK, stroke=WHITE, stroke_w=0, shadow=False, alpha=a,
             scale=out_back(prog(t, c.line(0) + 0.2, 0.4), 1.8))
    E.card(img, *CARD_B, t, c.line(0) + 0.3, fill=WHITE)
    if t >= c.line(0) + 0.3:
        a = prog(t, c.line(0) + 0.45, 0.3)
        cx = (CARD_B[0] + CARD_B[2]) / 2
        text(img, "壱岐の確率", cx, CARD_B[1] + 60, 36, fill=NAVY, stroke_w=0, shadow=False,
             alpha=a)
        E.big_number(img, P_STD, "% 標準", cx - 190, CARD_B[1] + 200, 88, t,
                     c.line(0) + 0.5, fill=BLUE, unit_size=28)
        E.big_number(img, P_SHORT, "% 短い飛行", cx + 190, CARD_B[1] + 200, 88, t,
                     c.line(0) + 0.7, fill=PINK, unit_size=28)
    if t >= c.line(1):
        a = prog(t, c.line(1), 0.3)
        text(img, "10 日のうち 4 日ほど", 560, 550, 40, fill=WHITE, stroke_w=5, alpha=a)
        _day_icons(img, d, t, c.line(1) + 0.15, 220, 640, 10, DAYS_LIT)
        text(img, "予備の週末を 3 回", 1380, 550, 40, fill=WHITE, stroke_w=5, alpha=a)
        for k in range(3):
            _mini_calendar(img, d, 1220 + k * 170, 700, t, c.line(1) + 0.3 + 0.25 * k, True)
    t_end = c.line_end(1)
    t_panel = t_end + 0.4
    if t >= t_panel:
        E.card(img, 60, 60, 1860, 1020, t, t_panel, fill=NAVY)
        t_title = t_panel + 0.35
        p = out_cubic(prog(t, t_title, 0.5))
        if p > 0.01:
            E.pop_chars(img, "冬、どこから上げる？", E.W / 2, 340, 100, t, t_title, 0.05)
            pa = out_back(prog(t, t_title + 1.0, 0.5), 1.9)
            if pa > 0:
                text(img, "→ 九州北西部・壱岐", E.W / 2, 480, 80, fill=YELLOW, scale=pa)
        t_credits = c.dur - 4.2
        credit_lines = ((VOICE_CREDIT, 38, YELLOW), (DATA_CREDIT, 30, WHITE),
                        (LICENSE_CREDIT, 30, WHITE))
        for i, (s, size, col) in enumerate(credit_lines):
            a = out_cubic(prog(t, t_credits + 0.5 * i, 0.4))
            if a > 0.01:
                text(img, s, E.W / 2, 700 + i * 68, size, fill=col, stroke_w=0, shadow=True,
                     alpha=a)
    fp = prog(t, c.dur - 0.5, 0.5)
    if fp > 0.01:
        # PIL は直描画に alpha を合成しないので、layer を作って合成する。
        veil = Image.new("RGBA", (E.W * E.S, E.H * E.S), (*NAVY, int(255 * fp)))
        img.alpha_composite(veil)


def outro_sfx(c):
    ev = [(c.line(0), "pop"), (c.line(0) + 0.3, "pop")]
    ev += [(c.line(1), "swish"), (c.line(1) + 0.15, "tick"), (c.line(1) + 0.75, "tick"),
           (c.line(1) + 1.0, "tick")]
    t_end = c.line_end(1)
    ev += [(t_end + 0.4, "whoosh"), (t_end + 0.75, "ding")]
    t_credits = c.dur - 4.2
    ev += [(t_credits + 0.5 * i, "tick") for i in range(3)]
    ev.append((c.dur - 0.5, "crash"))
    return ev


SCENES = {"weekend": weekend, "sensitivity": sensitivity, "spots": spots, "outro": outro}
SFX = {"weekend": weekend_sfx, "sensitivity": sensitivity_sfx, "spots": spots_sfx,
       "outro": outro_sfx}
