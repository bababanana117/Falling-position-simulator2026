"""記事用の概念図を描く。

データの図は `slide/figures/` と `research/out/figures/` から持ってくる。
ここで描くのは、そこに無い「説明のための絵」だけ。

    python make_diagrams.py              # 6 枚すべて
    python make_diagrams.py --only flight-stages

配色とフォントはスライド (`slide/make_figures.py`) に合わせてある。同じ
プロジェクトの図が記事の中で急に別の見た目になると、読者は別々のものだと
思ってしまう。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
OUT = HERE / "images"

# スライドと同じ色。青が主役、朱が警告、灰は後退させたいもの。
TEXT, SECONDARY, MUTED, RULE = "#1A1A1A", "#4B5563", "#9CA3AF", "#E5E7EB"
BLUE, ORANGE, PALE, GREY = "#0072B2", "#D55E00", "#E3EEF8", "#F3F4F6"

HARANO = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji")
FIRA = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/fira")

#: どの記事の images/ に置くか。Zenn は /images/<slug>/... で解決する。
ARTICLE = {
    "flight-stages": "balloon-wind-1-forecast-limit",
    "forecast-horizon": "balloon-wind-1-forecast-limit",
    "what-is-perturbed": "balloon-wind-1-forecast-limit",
    "half-month-bins": "balloon-wind-2-building-climatology",
    "why-not-average-angles": "balloon-wind-2-building-climatology",
    "gaussian-grid": "balloon-wind-3-duckdb-distribution",
}


def apply_style() -> None:
    families = []
    for path, names in (
        (FIRA, ("FiraSans-Regular.otf", "FiraSans-Medium.otf", "FiraSans-Bold.otf")),
        (HARANO, ("HaranoAjiGothic-Medium.otf", "HaranoAjiGothic-Bold.otf")),
    ):
        for name in names:
            if (path / name).exists():
                font_manager.fontManager.addfont(str(path / name))
        if (path / names[0]).exists():
            families.append(
                font_manager.FontProperties(fname=str(path / names[0])).get_name()
            )
    mpl.rcParams.update({
        "font.family": families or ["DejaVu Sans"],
        "font.size": 12,
        "axes.labelsize": 12,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "text.color": TEXT,
        "axes.labelcolor": SECONDARY,
        "axes.edgecolor": MUTED,
        "xtick.color": SECONDARY,
        "ytick.color": SECONDARY,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.06,
        "axes.unicode_minus": False,
    })


def save(fig, name: str) -> None:
    folder = OUT / ARTICLE[name]
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / f"{name}.png")
    plt.close(fig)
    print(f"  images/{ARTICLE[name]}/{name}.png")


def bare(ax) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_visible(False)


def card(ax, x, y, w, h, *, face=GREY, edge="none") -> FancyBboxPatch:
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.02",
        facecolor=face, edgecolor=edge, linewidth=1.2, zorder=1,
    )
    ax.add_patch(box)
    return box


# ===================================================================== 1 ===
def fig_flight_stages() -> None:
    """落下点は全高度の風の足し算だ、という一枚。"""
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    bare(ax)
    ax.set_xlim(-0.2, 11.6)
    ax.set_ylim(-2.0, 10.6)

    # 高度の目盛だけ左に置く
    levels = [(0.4, "地上"), (3.0, "5 km"), (5.6, "12 km ジェット"),
              (8.0, "23.8 km"), (9.4, "30 km")]
    for y, label in levels:
        ax.plot([1.7, 9.6], [y, y], color=RULE, linewidth=0.9, zorder=0)
        ax.text(1.6, y, label, ha="right", va="center",
                fontsize=10, color=SECONDARY)

    # 上昇と降下の道筋
    up_x = [2.0, 2.5, 3.6, 4.6, 5.2]
    up_y = [0.4, 3.0, 5.6, 8.0, 9.4]
    ax.plot(up_x, up_y, color=BLUE, linewidth=2.6, zorder=3)
    down_x = [5.2, 6.4, 7.4, 7.9, 8.1]
    down_y = [9.4, 8.0, 5.6, 3.0, 0.4]
    ax.plot(down_x, down_y, color=BLUE, linewidth=2.6,
            linestyle=(0, (5, 2)), zorder=3)
    ax.plot(5.2, 9.4, marker="*", markersize=17, color=ORANGE, zorder=4)
    ax.text(5.05, 9.95, "破裂", fontsize=11, color=ORANGE, ha="right")
    ax.plot(8.1, 0.4, marker="o", markersize=9, color=BLUE, zorder=4)
    ax.text(8.35, 0.75, "落下点", fontsize=11, color=BLUE)
    ax.plot(2.0, 0.4, marker="^", markersize=10, color=BLUE, zorder=4)
    ax.text(2.0, -0.25, "打ち上げ", fontsize=11, color=BLUE, ha="center")

    # 各層の風。矢印の長さがその層の寄与
    winds = [(0.4, 0.5), (3.0, 1.0), (5.6, 2.2), (8.0, 1.1), (9.4, 0.6)]
    for y, length in winds:
        ax.add_patch(FancyArrowPatch(
            (2.6, y + 0.36), (2.6 + length, y + 0.36),
            arrowstyle="-|>", mutation_scale=13,
            color=MUTED, linewidth=1.6, zorder=2,
        ))
    ax.text(2.6, 10.35, "灰色の矢印 = その高度の風", fontsize=10, color=MUTED)

    card(ax, 9.75, 7.4, 1.8, 2.3, face=PALE)
    for i, (label, value) in enumerate(
        (("上昇", "99 分"), ("降下", "38 分"), ("合計", "137 分"))
    ):
        ax.text(9.95, 9.05 - i * 0.62, label, fontsize=10.5, color=SECONDARY)
        ax.text(11.4, 9.05 - i * 0.62, value, fontsize=10.5,
                color=TEXT, ha="right")

    ax.text(5.7, -0.9, r"$\Delta x=\sum_k u_k\,T_k$",
            fontsize=15, color=TEXT, ha="center", va="center")
    ax.text(5.7, -1.8, "通った層の風を、その層にいた時間だけ足す",
            fontsize=11, color=SECONDARY, ha="center", va="center")
    save(fig, "flight-stages")


# ===================================================================== 2 ===
def fig_forecast_horizon() -> None:
    """予報の窓と、計画が要る時間スケールの落差。"""
    fig, ax = plt.subplots(figsize=(8.2, 3.2))
    bare(ax)
    ax.set_xlim(-0.6, 10.4)
    ax.set_ylim(0, 4.4)

    ax.plot([0, 10], [2.4, 2.4], color=MUTED, linewidth=1.2, zorder=2)
    for x, label in ((0.0, "今日"), (1.4, "1 週間"), (4.2, "1 か月"),
                     (7.0, "3 か月"), (9.6, "半年")):
        ax.plot([x, x], [2.25, 2.55], color=MUTED, linewidth=1.2, zorder=2)
        ax.text(x, 2.0, label, ha="center", fontsize=10.5, color=SECONDARY)

    card(ax, 0.0, 2.75, 1.4, 0.85, face=PALE)
    card(ax, 1.4, 2.75, 8.6, 0.85, face=GREY)
    ax.text(5.7, 3.17, "予報では何も言えない", ha="center",
            fontsize=11.5, color=MUTED)

    # 青い帯は 1 週間ぶんしかないので、ラベルは帯の上に出す
    ax.text(0.0, 3.72, "予報が届く範囲　−12 時間 〜 +7 日",
            ha="left", fontsize=11, color=BLUE)
    ax.add_patch(FancyArrowPatch(
        (0.7, 3.66), (0.7, 3.32), arrowstyle="-|>", mutation_scale=11,
        color=BLUE, linewidth=1.4,
    ))

    card(ax, 4.2, 0.85, 5.8, 0.85, face="#FBEDE5")
    ax.text(7.1, 1.27, "機材の手配・申請・人の予定を決める時期",
            ha="center", fontsize=11.5, color=ORANGE)
    # 目盛のラベルを避けて矢印を立てる
    ax.add_patch(FancyArrowPatch(
        (5.6, 1.75), (5.6, 2.3), arrowstyle="-|>", mutation_scale=14,
        color=ORANGE, linewidth=1.8,
    ))
    ax.text(5.0, 0.3, "ここを埋めるのが統計風（気候値）",
            ha="center", fontsize=12, color=TEXT)
    save(fig, "forecast-horizon")


# ===================================================================== 3 ===
def fig_what_is_perturbed() -> None:
    """機体は振っているのに風は 1 本、という非対称。"""
    fig, ax = plt.subplots(figsize=(8.2, 4.0))
    bare(ax)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.2)

    ax.text(2.4, 5.8, "振っているもの", ha="center", fontsize=12.5, color=BLUE)
    ax.text(7.4, 5.8, "振っていないもの", ha="center", fontsize=12.5, color=ORANGE)

    for i, (name, spread) in enumerate(
        (("上昇速度", "個体差・気温で変わる"), ("破裂高度", "風船のばらつき"),
         ("降下速度", "傘の開き方で変わる"))
    ):
        y = 4.5 - i * 1.15
        card(ax, 0.4, y, 4.0, 0.85, face=PALE)
        ax.text(0.75, y + 0.53, name, fontsize=11.5, color=TEXT)
        ax.text(0.75, y + 0.18, spread, fontsize=9.5, color=SECONDARY)
        for k in range(7):
            ax.plot(3.35 + 0.13 * k, y + 0.42, marker="o", markersize=3.6,
                    color=BLUE, alpha=0.75, zorder=3)

    card(ax, 5.4, 2.2, 4.2, 3.15, face="#FBEDE5")
    ax.text(5.75, 4.85, "風", fontsize=12.5, color=TEXT)
    ax.text(5.75, 4.35, "予報 1 本をそのまま使う", fontsize=11, color=SECONDARY)
    ax.text(5.75, 3.95, "高度 38 層ぶん、すべて固定", fontsize=11, color=SECONDARY)
    ax.plot([7.5], [3.1], marker="o", markersize=7, color=ORANGE, zorder=3)
    ax.text(7.75, 3.05, "1 通りだけ", fontsize=10.5, color=ORANGE, va="center")

    ax.text(5.0, 1.55, "結果: 落下点の散らばりは約 5 km",
            ha="center", fontsize=12, color=SECONDARY)
    ax.text(5.0, 1.0, "実測した本当の散らばりは 東西 54.5 km / 南北 48.6 km",
            ha="center", fontsize=12, color=ORANGE)
    ax.text(5.0, 0.35, "出ているのは 1 割ほど", ha="center",
            fontsize=13, color=TEXT)
    save(fig, "what-is-perturbed")


# ===================================================================== 4 ===
def fig_half_month_bins() -> None:
    """1 年を 24 に切る。境界が毎年同じ日付に来ることが要点。"""
    fig, ax = plt.subplots(figsize=(8.6, 2.9))
    bare(ax)
    ax.set_xlim(-0.4, 12.4)
    ax.set_ylim(-1.5, 2.3)

    for month in range(12):
        for half in range(2):
            x = month + half * 0.5
            face = PALE if half == 0 else "#F7FAFD"
            card(ax, x + 0.03, 0.55, 0.44, 0.9, face=face)
            ax.text(x + 0.25, 1.0, "前" if half == 0 else "後",
                    ha="center", va="center", fontsize=8.5, color=BLUE)
        ax.text(month + 0.5, 0.25, f"{month + 1}", ha="center",
                fontsize=10, color=SECONDARY)
    ax.text(6.0, -0.15, "月", ha="center", fontsize=10.5, color=SECONDARY)

    ax.text(0.25, 1.75, "前半 = 1〜15 日（常に 15 日間）",
            fontsize=11, color=TEXT)
    ax.text(6.4, 1.75, "後半 = 16 日〜月末（13〜16 日間）",
            fontsize=11, color=TEXT)

    ax.text(6.0, -0.75, "24 ビン × 10 年。前半は毎回 600 標本、後半は 532〜640",
            ha="center", fontsize=11, color=SECONDARY)
    ax.text(6.0, -1.25, "週で切らないのは、週の境界が年ごとに日付をまたぐから",
            ha="center", fontsize=11, color=MUTED)
    save(fig, "half-month-bins")


# ===================================================================== 5 ===
def fig_why_not_average_angles() -> None:
    """359° と 1° の算術平均が 180° になる。"""
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 4.0),
                             subplot_kw={"projection": "polar"})
    fig.subplots_adjust(wspace=0.45)
    for ax in axes:
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_xticks(np.radians([0, 90, 180, 270]))
        ax.set_xticklabels(["北", "東", "南", "西"], fontsize=10.5)
        ax.set_yticks([])
        ax.set_ylim(0, 1.15)
        ax.grid(color=RULE, linewidth=0.8)
        ax.spines["polar"].set_color(RULE)

    for ax in axes:
        for deg in (350, 10):
            ax.annotate("", xy=(np.radians(deg), 1.0), xytext=(0, 0),
                        arrowprops={"arrowstyle": "-|>", "color": MUTED,
                                    "linewidth": 2.0})

    axes[0].annotate("", xy=(np.radians(180), 1.0), xytext=(0, 0),
                     arrowprops={"arrowstyle": "-|>", "color": ORANGE,
                                 "linewidth": 2.8})
    axes[0].text(np.radians(200), 0.72, "180°", color=ORANGE, fontsize=12)
    axes[0].set_title("角度をそのまま平均する\n(350 + 10) / 2 = 180°",
                      fontsize=11.5, color=ORANGE, pad=16)

    axes[1].annotate("", xy=(np.radians(0), 1.0), xytext=(0, 0),
                     arrowprops={"arrowstyle": "-|>", "color": BLUE,
                                 "linewidth": 2.8})
    axes[1].text(np.radians(20), 0.72, "0°", color=BLUE, fontsize=12)
    axes[1].set_title("成分を平均してから向きに戻す\n"
                      r"$\hat\mu=\mathrm{atan2}(\bar v,\ \bar u)$",
                      fontsize=11.5, color=BLUE, pad=16)

    fig.text(0.5, -0.02,
             "灰色の 2 本が元の風向（350° と 10°）。左は真逆を向いてしまう",
             ha="center", fontsize=11, color=SECONDARY)
    save(fig, "why-not-average-angles")


# ===================================================================== 6 ===
def fig_gaussian_grid() -> None:
    """緯度が半端な値なので lat = 42.5 という行は存在しない。"""
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    bare(ax)
    ax.set_xlim(0, 10)
    ax.set_ylim(41.35, 43.55)

    # 実際のガウス格子の緯度。北海道の箱から 42.5 をまたぐ範囲を抜き出す
    lats = [41.770496, 42.145412, 42.518181, 42.895244, 43.270160]
    for lat in lats:
        ax.plot([1.0, 6.4], [lat, lat], color=RULE, linewidth=1.0, zorder=1)
        ax.plot(1.0, lat, marker="o", markersize=6, color=BLUE, zorder=3)
        ax.text(0.85, lat, f"{lat:.6f}", ha="right", va="center",
                fontsize=11, color=TEXT)

    ax.plot([1.0, 9.9], [42.5, 42.5], color=ORANGE, linewidth=2.0,
            linestyle=(0, (5, 3)), zorder=2)
    ax.text(6.6, 42.56, "lat = 42.5", color=ORANGE, va="bottom",
            fontsize=12, zorder=4)
    ax.text(6.6, 42.72, "ここに格子点は無い → 0 行", color=ORANGE,
            va="bottom", fontsize=11, zorder=4)

    # 42.5 をまたぐ 2 点だけ強調
    for lat in (42.145412, 42.518181):
        ax.plot(1.0, lat, marker="o", markersize=9, color=BLUE,
                markeredgecolor="white", markeredgewidth=1.4, zorder=4)
    ax.text(1.25, 42.55, "最寄りはここ（0.018° 上）", fontsize=10.5,
            color=SECONDARY, va="bottom")

    ax.text(0.0, 43.48, "JRA-3Q はガウス格子。緯度は求積の分点に置かれる",
            fontsize=12.5, color=TEXT, ha="left", va="top")
    ax.text(0.0, 41.42,
            "WHERE lat = 42.5 はエラーにならない。黙って 0 行を返す",
            fontsize=11.5, color=TEXT, ha="left", va="bottom")
    save(fig, "gaussian-grid")


FIGURES = {
    "flight-stages": fig_flight_stages,
    "forecast-horizon": fig_forecast_horizon,
    "what-is-perturbed": fig_what_is_perturbed,
    "half-month-bins": fig_half_month_bins,
    "why-not-average-angles": fig_why_not_average_angles,
    "gaussian-grid": fig_gaussian_grid,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", choices=sorted(FIGURES))
    a = ap.parse_args(argv)
    apply_style()
    wanted = a.only or list(FIGURES)
    print(f"{OUT} に書き出します")
    for name in wanted:
        FIGURES[name]()
    print(f"{len(wanted)} 枚できました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
