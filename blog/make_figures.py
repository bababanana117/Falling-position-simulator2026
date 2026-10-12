"""記事用のデータ図を描く。

スライドの図はプレゼン用に文字を大きくしてあるので、ブログの幅に置くと
ラベルどうしが重なる。ここでは同じ数字から、ブログの幅（約 1100 px）で
読める大きさに描き直す。

元データは `research/out/csv/` の CSV と、配布用の DuckDB。図を描くために
再解析の生データを読み直す必要はない。

    python make_figures.py                    # 全部
    python make_figures.py --only jet-cycle

概念図は `make_diagrams.py` のほう。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from make_diagrams import (
    ARTICLE,
    BLUE,
    MUTED,
    ORANGE,
    PALE,
    RULE,
    SECONDARY,
    TEXT,
    apply_style,
)

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent / "research"
CSV = RESEARCH / "out" / "csv"
DB = RESEARCH / "hokkaido_duckdb" / "jra3q_hokkaido_wind_2016-2025_v1.duckdb"
OUT = HERE / "images"

A2 = "balloon-wind-2-building-climatology"
A3 = "balloon-wind-3-duckdb-distribution"

MONTHS = [f"{m}月" for m in range(1, 13)]
SEASON_COLOUR = {"冬": "#0072B2", "春": "#1BA39C", "夏": "#D55E00", "秋": "#8C5FB0"}
#: 3 つ目の領域の色。青・朱と並べて色覚の検査を通してある。
GREEN = "#009E73"
#: 領域の並びと色。どの図でも同じ順・同じ色にする。
REGIONS = (("北海道", "hokkaido", BLUE), ("和歌山", "wakayama", ORANGE),
           ("愛媛", "ehime", GREEN))

#: 大きさには青 1 色の濃淡。0 が「弱い」で、色が濃いほど強い。
SEQ = LinearSegmentedColormap.from_list("blues", (
    "#F2F7FC", "#D7E7F6", "#B4D3EF", "#8ABCE6", "#5BA1DA",
    "#3585C9", "#1E6AAE", "#12508A", "#0B3A66",
))
#: 正負のある量は、灰色をはさんだ青と朱。
DIV = LinearSegmentedColormap.from_list("div", (
    "#0B3A66", "#2E7AB8", "#9EC9E8", "#EFEFEC", "#F0B49A", "#D55E00", "#7A2E00",
))


LAND_JSON = HERE.parent / "frontend" / "public" / "geo" / "land.json"


def coastline_rings() -> list[np.ndarray]:
    """海岸線。web アプリが使っている GeoJSON をそのまま読む。

    cartopy を入れると描画時に Natural Earth を取りに行くので、リポジトリに
    既にある座標を使う。アプリと同じ海岸線になるという副産物もある。
    """
    import json

    raw = json.loads(LAND_JSON.read_text(encoding="utf-8"))
    rings: list[np.ndarray] = []

    def walk(coords, depth):
        if depth == 1:
            rings.append(np.asarray(coords, dtype=float))
            return
        for part in coords:
            walk(part, depth - 1)

    for feature in raw.get("features", [raw]):
        geom = feature.get("geometry", feature)
        kind = geom.get("type")
        if kind == "Polygon":
            walk(geom["coordinates"], 2)
        elif kind == "MultiPolygon":
            walk(geom["coordinates"], 3)
    return rings


def draw_coast(ax, bbox) -> None:
    west, east, south, north = bbox
    for ring in coastline_rings():
        lon, lat = ring[:, 0], ring[:, 1]
        if lon.max() < west - 2 or lon.min() > east + 2:
            continue
        if lat.max() < south - 2 or lat.min() > north + 2:
            continue
        ax.fill(lon, lat, facecolor="#ECEAE4", edgecolor="none", zorder=1)
        ax.plot(lon, lat, color="#9A968C", linewidth=0.8, zorder=2)
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect(1 / np.cos(np.radians((south + north) / 2)))


def save(fig, name: str, article: str) -> None:
    folder = OUT / article
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / f"{name}.png")
    plt.close(fig)
    ARTICLE[name] = article
    print(f"  images/{article}/{name}.png")


def blog_style() -> None:
    """記事の幅で読めるようにする。スライドより文字を小さく、余白を広く。"""
    apply_style()
    mpl.rcParams.update({
        "font.size": 10.5,
        "axes.labelsize": 10.5,
        "axes.titlesize": 11,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.fontsize": 9.5,
        "lines.linewidth": 1.8,
        "savefig.dpi": 170,
        "savefig.pad_inches": 0.12,
    })


def site_profile() -> pd.DataFrame:
    """打ち上げ地点の 24 ビン × 38 面。"""
    df = pd.read_csv(CSV / "site_profile_hokkaido.csv")
    df["bin_index"] = (df["month"] - 1) * 2 + (df["bin"] - 1)
    return df


def bin_axis(ax, *, label: bool = True) -> None:
    """24 ビンの横軸。月ごとに目盛、名前は 1 つおき。"""
    ax.set_xticks(np.arange(12) * 2 + 1.0)
    ax.set_xticklabels([m if i % 2 == 0 else "" for i, m in enumerate(MONTHS)])
    ax.set_xticks(np.arange(25), minor=True)
    ax.tick_params(axis="x", which="minor", length=2.5, color=MUTED)
    ax.set_xlim(0, 24)
    if label:
        ax.set_xlabel("時期（各月 = 前半・後半の 2 ビン）")


def grid_to_bins(df: pd.DataFrame, value: str) -> tuple[np.ndarray, np.ndarray]:
    """(高度, ビン) の格子にする。

    幾何高度は時期によって数百 m 動くので、そのままでは格子にならない。
    気圧面で並べ、縦軸にはその面の年平均高度を使う。
    """
    wide = df.pivot(index="level_hpa", columns="bin_index", values=value)
    alt = df.groupby("level_hpa")["alt_km"].mean().reindex(wide.index)
    order = np.argsort(alt.to_numpy())
    return alt.to_numpy()[order], wide.to_numpy()[order]


# ==================================================================== 記事 2 ==
def fig_speed_altitude_season() -> None:
    """高度 × 時期の平均風速。この記事の主役。"""
    df = site_profile()
    alt, grid = grid_to_bins(df, "speed_mean")

    fig, ax = plt.subplots(figsize=(9.2, 4.2))
    mesh = ax.pcolormesh(np.arange(24) + 0.5, alt, grid, cmap=SEQ,
                         shading="nearest", rasterized=True)
    bin_axis(ax)
    ax.set_ylabel("幾何高度 [km]")
    ax.set_yticks([0, 5, 10, 15, 20, 25, 30, 35, 40])
    ax.set_ylim(0, 40)
    ax.grid(False)

    # 読者が気にする 2 つの高度に目印を置く
    for y, label in ((11.9, "ジェット 約 12 km"), (30.0, "破裂高度 約 30 km")):
        ax.axhline(y, color="white", linewidth=1.0, linestyle=(0, (4, 3)),
                   alpha=0.85, zorder=3)
        ax.text(0.35, y + 0.7, label, fontsize=9, color="white", zorder=4)

    bar = fig.colorbar(mesh, ax=ax, pad=0.015, aspect=26)
    bar.set_label("平均風速 [m/s]")
    bar.outline.set_visible(False)
    save(fig, "speed-altitude-season", A2)


def fig_direction_altitude_season() -> None:
    """高度 × 時期の風向。向きが定まらないところは灰色で伏せる。"""
    df = site_profile()
    alt, direction = grid_to_bins(df, "dir_vector_mean")
    _, constancy = grid_to_bins(df, "constancy")
    masked = np.where(constancy >= 0.3, direction, np.nan)

    cyclic = LinearSegmentedColormap.from_list("cyclic", (
        "#3585C9", "#7A9E3A", "#D8A213", "#D55E00",
        "#A8437A", "#6B5BB5", "#3585C9",
    ))
    fig, ax = plt.subplots(figsize=(9.2, 4.2))
    ax.set_facecolor("#E9E9E6")
    mesh = ax.pcolormesh(np.arange(24) + 0.5, alt, masked, cmap=cyclic,
                         vmin=0, vmax=360, shading="nearest", rasterized=True)
    bin_axis(ax)
    ax.set_ylabel("幾何高度 [km]")
    ax.set_yticks([0, 5, 10, 15, 20, 25, 30, 35, 40])
    ax.set_ylim(0, 40)
    ax.grid(False)
    ax.text(0.35, 36.8, "灰色 = 定常度 0.3 未満。向きが定まらない",
            fontsize=9, color=TEXT, zorder=4,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 2})

    bar = fig.colorbar(mesh, ax=ax, pad=0.015, aspect=26,
                       ticks=[0, 90, 180, 270, 360])
    bar.ax.set_yticklabels(["北", "東", "南", "西", "北"])
    bar.set_label("風が吹いてくる向き")
    bar.outline.set_visible(False)
    save(fig, "direction-altitude-season", A2)


def fig_constancy_cycle() -> None:
    """定常度の年変化。2 つの高度を比べる。"""
    df = site_profile()
    fig, ax = plt.subplots(figsize=(9.2, 3.6))

    ax.axhspan(0, 0.3, color="#FBEDE5", zorder=0)
    ax.axhline(0.3, color=ORANGE, linewidth=1.2, linestyle=(0, (5, 3)), zorder=1)
    ax.text(0.3, 0.245, "この下では平均風向に意味がない", fontsize=9,
            color=ORANGE, ha="left", va="top", zorder=4)

    for level, colour, width, label in (
        (200.0, MUTED, 1.6, "200 hPa（約 12 km）"),
        (10.0, BLUE, 2.2, "10 hPa（約 31 km・破裂高度帯）"),
    ):
        sub = df[df["level_hpa"] == level].sort_values("bin_index")
        x = sub["bin_index"].to_numpy() + 0.5
        ax.plot(x, sub["constancy"], color=colour, linewidth=width,
                marker="o", markersize=3.4, zorder=3)
        ax.text(x[-1] + 0.35, sub["constancy"].iloc[-1], label, fontsize=9.5,
                color=colour, va="center")

    # 最小のビンだけ名指しする。軸ラベルにかぶらないよう上へ出す。
    worst = df[df["level_hpa"] == 10.0].nsmallest(1, "constancy").iloc[0]
    ax.annotate(f"最小 {worst.constancy:.2f}"
                f"（{int(worst.month)}月{'前半' if worst.bin == 1 else '後半'}）",
                xy=(worst.bin_index + 0.5, worst.constancy),
                xytext=(worst.bin_index - 1.4, worst.constancy + 0.17),
                ha="right", fontsize=9.5, color=BLUE,
                arrowprops={"arrowstyle": "-|>", "color": BLUE, "linewidth": 1.1})

    bin_axis(ax)
    ax.set_xlim(0, 30.5)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("定常度 C")
    save(fig, "constancy-cycle", A2)


def fig_profiles_4seasons() -> None:
    """4 季節の鉛直プロファイル。強さ・向き・揃い方。"""
    df = site_profile()
    seasons = (("冬", 1, 1), ("春", 4, 1), ("夏", 7, 1), ("秋", 10, 2))

    fig, axes = plt.subplots(1, 3, figsize=(9.6, 4.6), sharey=True)
    for name, month, half in seasons:
        sub = df[(df["month"] == month) & (df["bin"] == half)].sort_values("alt_km")
        colour = SEASON_COLOUR[name]
        label = f"{name}（{month}月{'前半' if half == 1 else '後半'}）"
        axes[0].plot(sub["speed_mean"], sub["alt_km"], color=colour, label=label)
        axes[0].plot(sub["speed_p90"], sub["alt_km"], color=colour,
                     linewidth=1.0, linestyle=(0, (3, 2)), alpha=0.75)

        deg = sub["dir_vector_mean"].to_numpy(dtype=float).copy()
        deg[sub["constancy"].to_numpy() < 0.3] = np.nan
        deg[1:][np.abs(np.diff(deg)) > 180] = np.nan
        axes[1].plot(deg, sub["alt_km"], color=colour)
        axes[2].plot(sub["constancy"], sub["alt_km"], color=colour)

    for ax in axes:
        ax.set_ylim(0, 40)
        ax.set_yticks([0, 5, 10, 15, 20, 25, 30, 35, 40])
        ax.axhspan(26, 32, color=PALE, zorder=0)
    axes[0].set_ylabel("幾何高度 [km]")
    axes[0].set_xlabel("風速 [m/s]")
    # 帯のラベルは線が来ない右上の空きに置く
    axes[0].text(0.97, 29, "破裂高度帯", fontsize=9, color=SECONDARY,
                 zorder=2, ha="right", transform=axes[0].get_yaxis_transform())
    axes[1].set_xlabel("吹いてくる向き")
    axes[1].set_xlim(0, 360)
    axes[1].set_xticks([0, 90, 180, 270, 360])
    axes[1].set_xticklabels(["北", "東", "南", "西", "北"])
    axes[2].set_xlabel("定常度")
    axes[2].set_xlim(0, 1.05)
    axes[2].axvline(0.3, color=ORANGE, linewidth=1.0, linestyle=(0, (4, 3)))

    axes[0].text(0.97, 0.03, "実線 平均・破線 p90", transform=axes[0].transAxes,
                 fontsize=9, color=SECONDARY, va="bottom", ha="right")
    axes[1].text(0.03, 0.03, "定常度 0.3 未満は描かない",
                 transform=axes[1].transAxes, fontsize=9, color=SECONDARY,
                 va="bottom")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=4,
               bbox_to_anchor=(0.5, -0.06))
    save(fig, "profiles-4seasons", A2)


def fig_layer_summary() -> None:
    """層ごとの風速と定常度の年変化。どの層が読めてどの層が読めないか。"""
    df = pd.read_csv(CSV / "layer_summary_hokkaido.csv")
    df["bin_index"] = (df["month"] - 1) * 2 + (df["bin"] - 1)
    order = [
        ("0-2 km surface/boundary layer", "0--2 km 地表"),
        ("2-6 km lower troposphere", "2--6 km 下部対流圏"),
        ("6-12 km jet", "6--12 km ジェット"),
        ("12-20 km lower stratosphere", "12--20 km 下部成層圏"),
        ("20-30 km float/burst", "20--30 km 破裂高度帯"),
        ("30-40 km upper stratosphere", "30--40 km 上部成層圏"),
    ]
    # 層は高度の順なので 1 色の濃淡で表す。ただし薄すぎる側は白地に埋もれる
    # ので下限を上げ、読者がいちばん気にする破裂高度帯だけ線を太くする。
    shades = [SEQ(x) for x in np.linspace(0.38, 1.0, len(order))]

    fig, axes = plt.subplots(2, 1, figsize=(9.2, 5.6), sharex=True)
    for (key, label), colour in zip(order, shades, strict=True):
        sub = df[df["layer"] == key].sort_values("bin_index")
        x = sub["bin_index"].to_numpy() + 0.5
        width = 2.6 if "破裂" in label else 1.5
        axes[0].plot(x, sub["speed_mean"], color=colour, label=label,
                     linewidth=width)
        axes[1].plot(x, sub["constancy"], color=colour, linewidth=width)

    axes[0].set_ylabel("層の平均風速 [m/s]")
    axes[1].set_ylabel("層の定常度")
    axes[1].set_ylim(0, 1.05)
    axes[1].axhspan(0, 0.3, color="#FBEDE5", zorder=0)
    axes[1].axhline(0.3, color=ORANGE, linewidth=1.0, linestyle=(0, (5, 3)))
    bin_axis(axes[1])
    axes[0].legend(loc="upper center", ncols=3, bbox_to_anchor=(0.5, 1.30),
                   columnspacing=1.4)
    save(fig, "layer-summary", A2)


def fig_jet_cycle() -> None:
    """ジェット高度の風速の年変化。秋が最大であることを 1 枚で。"""
    df = site_profile()
    sub = df[df["level_hpa"] == 200.0].sort_values("bin_index")
    x = sub["bin_index"].to_numpy()
    mean = sub["speed_mean"].to_numpy()
    p90 = sub["speed_p90"].to_numpy()

    fig, ax = plt.subplots(figsize=(9.2, 3.6))
    ax.bar(x + 0.5, p90, width=0.82, color=PALE, zorder=1, label="p90")
    ax.bar(x + 0.5, mean, width=0.82, color=BLUE, zorder=2, label="平均")

    top = int(np.argmax(mean))
    ax.bar(x[top] + 0.5, mean[top], width=0.82, color=ORANGE, zorder=3)
    ax.annotate(f"{int(sub.month.iloc[top])}月"
                f"{'前半' if sub.bin.iloc[top] == 1 else '後半'}  "
                f"{mean[top]:.1f} m/s",
                xy=(x[top] + 0.5, mean[top]), xytext=(x[top] + 0.5, mean[top] + 17),
                ha="center", fontsize=10, color=ORANGE,
                arrowprops={"arrowstyle": "-|>", "color": ORANGE, "linewidth": 1.4})

    winter = int(np.argmax((sub.month == 1) & (sub.bin == 1)))
    ax.annotate(f"1月前半  {mean[winter]:.1f} m/s",
                xy=(x[winter] + 0.5, mean[winter]),
                xytext=(x[winter] + 1.6, mean[winter] + 24),
                ha="left", fontsize=10, color=SECONDARY,
                arrowprops={"arrowstyle": "-|>", "color": SECONDARY,
                            "linewidth": 1.2})

    bin_axis(ax)
    ax.set_ylabel("200 hPa の風速 [m/s]")
    ax.set_ylim(0, max(p90) * 1.18)
    ax.legend(loc="upper right", ncols=2)
    save(fig, "jet-cycle", A2)


# ==================================================================== 記事 3 ==
def fig_drift_cycle_ja() -> None:
    """飛行距離と方位の年変化。打ち上げ計画に直結する 1 枚。"""
    df = pd.read_csv(CSV / "drift_hokkaido.csv")
    df["bin_index"] = (df["month"] - 1) * 2 + (df["bin"] - 1)
    df = df.sort_values("bin_index")
    x = df["bin_index"].to_numpy() + 0.5

    fig, axes = plt.subplots(2, 1, figsize=(9.2, 5.4), sharex=True,
                             gridspec_kw={"height_ratios": [2.2, 1]})
    axes[0].fill_between(x, df["dist_p50_km"], df["dist_p90_km"],
                         color=PALE, zorder=1, label="p50〜p90")
    axes[0].plot(x, df["dist_mean_km"], color=BLUE, zorder=3, label="平均")

    for kind, colour, offset in (("idxmin", BLUE, 26), ("idxmax", ORANGE, 26)):
        row = df.loc[getattr(df["dist_mean_km"], kind)()]
        axes[0].plot(row.bin_index + 0.5, row.dist_mean_km, marker="o",
                     markersize=7, color=colour, zorder=4)
        axes[0].annotate(
            f"{int(row.month)}月{'前半' if row.bin == 1 else '後半'}  "
            f"{row.dist_mean_km:.0f} km",
            xy=(row.bin_index + 0.5, row.dist_mean_km),
            xytext=(row.bin_index + 0.5, row.dist_mean_km + offset),
            ha="center", fontsize=10, color=colour,
            arrowprops={"arrowstyle": "-", "color": colour, "linewidth": 1.0})
    axes[0].set_ylabel("水平移動距離 [km]")
    axes[0].set_ylim(0, df["dist_p90_km"].max() * 1.25)
    axes[0].legend(loc="upper center", ncols=2, bbox_to_anchor=(0.5, 1.16))

    axes[1].plot(x, df["bearing_deg"], color="#1BA39C", marker="o",
                 markersize=3.6, linewidth=1.6)
    axes[1].set_ylim(45, 145)
    axes[1].set_yticks([45, 90, 135])
    axes[1].set_yticklabels(["北東", "東", "南東"])
    axes[1].set_ylabel("進む向き")
    bin_axis(axes[1])
    save(fig, "drift-cycle-ja", A3)


def fig_launch_windows() -> None:
    """打ち上げ好機のランキング。地上から 30 km までの平均風速で並べる。"""
    df = pd.read_csv(CSV / "best_launch_halves_hokkaido.csv").sort_values("rank")
    df["label"] = df.apply(
        lambda r: f"{int(r.month)}月{'前半' if r.bin == 1 else '後半'}", axis=1)
    top = df.head(8).iloc[::-1]
    bottom = df.tail(4).iloc[::-1]
    shown = pd.concat([bottom, top])
    colours = [ORANGE] * len(bottom) + [MUTED] * (len(top) - 3) + [BLUE] * 3

    fig, ax = plt.subplots(figsize=(9.0, 4.4))
    y = np.arange(len(shown))
    ax.barh(y, shown["mean_speed_0_30km"], color=colours, height=0.7, zorder=2)
    for yi, (_, r), c in zip(y, shown.iterrows(), colours, strict=True):
        ax.text(r.mean_speed_0_30km + 0.4, yi,
                f"{r.mean_speed_0_30km:.1f} m/s　定常度 {r.mean_constancy_0_30km:.2f}",
                va="center", fontsize=9.5, color=c)
    ax.set_yticks(y)
    ax.set_yticklabels(shown["label"])
    ax.set_xlabel("地上〜30 km の平均風速 [m/s]")
    ax.set_xlim(0, shown["mean_speed_0_30km"].max() * 1.5)
    # 上が穏やかな 8 ビン、下が荒れる 4 ビン。間は 12 ビンぶん飛ばしてある。
    ax.axhline(len(bottom) - 0.5, color=MUTED, linewidth=1.0,
               linestyle=(0, (5, 3)))
    right = ax.get_xlim()[1]
    ax.text(right, len(bottom) - 0.3, "↑ 穏やかな 8 ビン（青は上位 3）",
            ha="right", va="bottom", fontsize=9.5, color=BLUE)
    ax.text(right, len(bottom) - 0.7, "↓ 荒れる 4 ビン",
            ha="right", va="top", fontsize=9.5, color=ORANGE)
    ax.grid(axis="y", visible=False)
    save(fig, "launch-windows", A3)


def fig_slip_vs_frozen() -> None:
    """1 日ずれ と 風を固定する近似 の桁の違い。記事 1 の結論そのもの。"""
    slip = pd.read_csv(CSV / "fidelity_slip_hokkaido.csv")
    err = pd.read_csv(CSV / "fidelity_error_hokkaido.csv")
    seasons = ["冬", "春", "夏", "秋"]

    slip = slip[slip["lag_hours"] == 24].copy()
    slip["key"] = slip["season"].str[0]
    slip = slip.set_index("key").reindex(seasons)
    frozen = err[err["variant"] == "both_frozen"].copy()
    frozen["key"] = frozen["season"].str[0]
    frozen = frozen.set_index("key").reindex(seasons)

    fig, ax = plt.subplots(figsize=(8.8, 4.2))
    x = np.arange(len(seasons))
    a = ax.bar(x - 0.19, slip["median"], width=0.36, color=BLUE)
    b = ax.bar(x + 0.19, frozen["median_km"], width=0.36, color=MUTED)

    for xi, (s_val, f_val) in enumerate(
        zip(slip["median"], frozen["median_km"], strict=True)
    ):
        ax.text(xi - 0.19, s_val + 1.6, f"{s_val:.0f} km", ha="center",
                fontsize=10.5, color=BLUE)
        ax.text(xi + 0.19, f_val + 1.6, f"{f_val:.1f} km", ha="center",
                fontsize=10.5, color=SECONDARY)
        ax.text(xi, max(s_val, f_val) + 8.5, f"×{s_val / f_val:.0f}",
                ha="center", fontsize=11, color=TEXT)

    ax.set_xticks(x)
    ax.set_xticklabels(seasons)
    ax.set_ylabel("落下点のずれ（中央値）[km]")
    ax.set_ylim(0, 80)
    ax.legend([a, b], ["打ち上げが 1 日ずれる", "風を打ち上げ時刻・地点で固定する近似"],
              loc="upper center", ncols=2, bbox_to_anchor=(0.5, 1.16))
    save(fig, "slip-vs-frozen-ja", "balloon-wind-1-forecast-limit")


def fig_upper_share() -> None:
    """23.8 km より上が水平移動に占める割合。自前エンジンの天井の話。

    値は research の summary（ceiling_share.by_month、各月 2 ビンの平均）。
    """
    months = [1, 4, 6, 7, 8, 11]
    values = {
        "北海道": [4.6, 4.8, 18.4, 53.5, 20.5, 7.1],
        "和歌山": [1.1, 3.6, 20.0, 110.8, 101.1, 1.9],
        "愛媛": [1.0, 3.4, 21.7, 139.5, 85.5, 2.0],
    }
    colours = {name: colour for name, _key, colour in REGIONS}

    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    x = np.arange(len(months))
    for (name, vals), off in zip(values.items(), (-0.27, 0.0, 0.27), strict=True):
        ax.bar(x + off, vals, width=0.25, color=colours[name], label=name)
        for xi, v in zip(x, vals, strict=True):
            ax.text(xi + off, v + 3, f"{v:.0f}", ha="center", fontsize=9,
                    color=colours[name])

    ax.axhline(100, color=MUTED, linewidth=1.0, linestyle=(0, (5, 3)))
    # 注記は棒の無い左側に置く。右側は 7・8 月の棒が 100 % 線を越える。
    ax.text(-0.42, 104, "100 % = 上層だけで正味の移動と同じ長さ",
            ha="left", fontsize=9, color=SECONDARY)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{m}月" for m in months])
    ax.set_ylabel("23.8 km より上の寄与 [%]")
    ax.set_ylim(0, 160)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.9), ncols=3)
    save(fig, "upper-level-share", "balloon-wind-1-forecast-limit")


def fig_january_easterly() -> None:
    """1 月・10 hPa の東西風。冬の成層圏が東風であることを地図で示す。"""
    import duckdb

    con = duckdb.connect(str(DB), read_only=True)
    # 1 月の前半と後半を、標本数で重み付けして 1 枚にする
    df = con.execute("""
        SELECT w.lat, w.lon,
               sum(w.u_mean * t.n_analyses_expected)
                 / sum(t.n_analyses_expected) AS u_mean,
               sum(w.v_mean * t.n_analyses_expected)
                 / sum(t.n_analyses_expected) AS v_mean
        FROM fact_wind w JOIN dim_timebin t USING (timebin_id)
        WHERE w.month = 1 AND w.level_hpa = 10
        GROUP BY w.lat, w.lon ORDER BY w.lat, w.lon
    """).fetchdf()
    mean_u = float(con.execute("""
        SELECT sum(w.u_mean * g.gauss_weight * t.n_analyses_expected)
             / sum(g.gauss_weight * t.n_analyses_expected)
        FROM fact_wind w JOIN dim_grid g USING (cell_id)
                         JOIN dim_timebin t USING (timebin_id)
        WHERE w.month = 1 AND w.level_hpa = 10
    """).fetchone()[0])
    con.close()

    lats = np.sort(df["lat"].unique())
    lons = np.sort(df["lon"].unique())
    u = df.pivot(index="lat", columns="lon", values="u_mean").to_numpy()
    v = df.pivot(index="lat", columns="lon", values="v_mean").to_numpy()
    span = float(np.abs(u).max())

    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    mesh = ax.pcolormesh(lons, lats, u, cmap=DIV.reversed(),
                         vmin=-span, vmax=span,
                         shading="nearest", zorder=0, rasterized=True)
    draw_coast(ax, (lons.min(), lons.max(), lats.min(), lats.max()))
    step = 3
    ax.quiver(lons[::step], lats[::step], u[::step, ::step], v[::step, ::step],
              color="#2A2A2A", width=0.006, scale=110,
              headwidth=4, headlength=4.5, zorder=3)
    ax.plot(142.851, 42.182, marker="*", markersize=15, color=ORANGE,
            markeredgecolor="white", markeredgewidth=0.9, zorder=4)
    ax.annotate("打ち上げ地点", (142.851, 42.182), textcoords="offset points",
                xytext=(0, -16), ha="center", fontsize=9.5, color=TEXT, zorder=5,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.8, "pad": 1.5})
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    ax.grid(False)
    ax.text(0.015, 0.045, f"領域平均 u = {mean_u:+.1f} m/s（東風）",
            transform=ax.transAxes, fontsize=10.5, color=ORANGE, zorder=5,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85,
                  "pad": 3})

    bar = fig.colorbar(mesh, ax=ax, pad=0.015, aspect=22)
    bar.set_label("東西風 u [m/s]　朱 = 東風 / 青 = 西風")
    bar.outline.set_visible(False)
    save(fig, "january-easterly", A2)


def _regions(stem: str) -> dict[str, tuple[pd.DataFrame, str]]:
    """領域名 → (CSV, 色)。"""
    return {name: (pd.read_csv(CSV / f"{stem}_{key}.csv"), colour)
            for name, key, colour in REGIONS}


#: 再解析の仕様。JRA-3Q だけ手元のファイルから測った値で、残りは各機関の
#: 仕様書から書き写したもの。（windclim.figures.reanalyses と同じ表）
REANALYSES = (
    # 名前, 機関, 格子 [度], 上端 [hPa], 面数, 開始年, 終了年, 間隔 [h]
    ("NCEP/NCAR R1", "NCEP", 2.5, 10.0, 17, 1948, None, 6.0),
    ("JRA-55", "気象庁", 1.25, 1.0, 37, 1958, 2023, 6.0),
    ("MERRA-2", "NASA", 0.625, 0.1, 42, 1980, None, 3.0),
    ("ERA5", "ECMWF", 0.25, 1.0, 37, 1940, None, 1.0),
    ("JRA-3Q", "気象庁", 0.375, 0.01, 45, 1947, None, 6.0),
)
BURST_KM = 30.0


def _pressure_to_km(hpa: float) -> float:
    """気圧から高度へのおおよその換算。図の縦軸の目安にだけ使う。

    このデータベース自身の値（10 hPa = 31.1 km、3 hPa = 39.5 km）で
    合わせてある。1 hPa で 47 km、0.01 hPa で 79 km となり、各機関が
    公表している値とも揃う。
    """
    return float(31.1 + 7.0 * np.log(10.0 / hpa))


def fig_region_map() -> None:
    """解析した箱と代表地点。どこの話をしているかを最初に示す。"""
    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    draw_coast(ax, (135.0, 152.0, 37.0, 48.0))

    west, east, south, north = 138.0, 149.0, 40.0, 46.5
    ax.add_patch(plt.Rectangle((west, south), east - west, north - south,
                               facecolor="#0072B2", alpha=0.10,
                               edgecolor=BLUE, linewidth=1.8, zorder=3))
    ax.plot(142.851, 42.182, marker="*", markersize=17, color=ORANGE,
            markeredgecolor="white", markeredgewidth=1.0, zorder=5)
    ax.annotate("打ち上げ地点", (142.851, 42.182), textcoords="offset points",
                xytext=(12, -4), fontsize=11, color=ORANGE, zorder=6)

    # 箱の説明は箱の外に置く
    ax.annotate("北緯 40.0〜46.5 度\n東経 138.0〜149.0 度\n570 格子点（0.375 度）",
                xy=(west, north), xytext=(135.4, 47.6), fontsize=10.5,
                color=BLUE, va="top", zorder=6,
                bbox={"facecolor": "white", "edgecolor": RULE,
                      "boxstyle": "round,pad=0.4"})
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    ax.set_xticks([136, 140, 144, 148, 152])
    ax.set_yticks([38, 40, 42, 44, 46, 48])
    ax.grid(False)
    save(fig, "region-map-ja", A2)


def fig_reanalyses() -> None:
    """どの再解析なら破裂高度に届くか。JRA-3Q を選んだ理由。"""
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.2),
                             gridspec_kw={"width_ratios": (1.15, 1.0)})
    left, right = axes

    # 左: 水平の細かさ × 届く高さ
    offsets = {"NCEP/NCAR R1": (0, 14), "JRA-55": (0, 14),
               "MERRA-2": (0, -20), "ERA5": (0, -20), "JRA-3Q": (0, 16)}
    for name, _org, deg, top_hpa, *_ in REANALYSES:
        km = deg * 111.0 * np.cos(np.radians(43.0))
        top = _pressure_to_km(top_hpa)
        chosen = name == "JRA-3Q"
        left.plot(km, top, marker="o", markersize=13 if chosen else 8,
                  color=BLUE if chosen else MUTED, zorder=3)
        left.annotate(name, (km, top), textcoords="offset points",
                      xytext=offsets[name], ha="center", fontsize=10,
                      color=BLUE if chosen else SECONDARY,
                      fontweight="bold" if chosen else "normal")
    left.axhspan(0, BURST_KM, color="#FBEDE5", zorder=0)
    left.axhline(BURST_KM, color=ORANGE, linewidth=1.2, linestyle=(0, (5, 3)))
    left.text(300, BURST_KM - 3, "破裂高度 30 km", fontsize=9.5,
              color=ORANGE, ha="left", va="top")
    left.set_xscale("log")
    left.invert_xaxis()
    left.set_xticks([200, 100, 50, 25])
    left.set_xticklabels(["200", "100", "50", "25"])
    left.minorticks_off()
    left.set_xlim(330, 15)
    left.set_ylim(0, 105)
    left.set_xlabel("水平格子間隔 [km]（細かいほど右）")
    left.set_ylabel("気圧面の上端 [km]")

    # 右: 対象期間
    y = np.arange(len(REANALYSES))
    for yi, (name, _org, _deg, _top, n_lv, start, end, hours) in zip(
        y, REANALYSES, strict=True
    ):
        stop = end or 2026
        chosen = name == "JRA-3Q"
        right.barh(yi, stop - start, left=start, height=0.55,
                   color=BLUE if chosen else MUTED)
        span = f"{start}–{end}" if end else f"{start}–"
        right.text(stop + 3, yi, f"{span}　{n_lv} 面　{hours:.0f} h",
                   va="center", fontsize=9.5,
                   color=BLUE if chosen else SECONDARY)
    right.set_yticks(y)
    right.set_yticklabels([r[0] for r in REANALYSES])
    right.set_xlim(1935, 2090)
    right.set_xticks([1950, 1980, 2010])
    right.set_xlabel("対象期間")
    right.grid(axis="y", visible=False)
    save(fig, "reanalyses-ja", A2)


def fig_skill_bin_width() -> None:
    """区間幅を変えたときの誤差の削減。どこまで細かく切れるかの答え。"""
    data = _regions("timescale")
    fig, ax = plt.subplots(figsize=(8.8, 4.0))
    # 直接ラベルは曲線の左端に置く。和歌山と愛媛は 2 ポイントしか離れて
    # いないので、上側の愛媛は線の上、和歌山は線の下に書く。
    label_dy = {"北海道": 2.4, "和歌山": -4.6, "愛媛": 2.4}
    for name, (df, colour) in data.items():
        df = df.sort_values("granularity_days")
        x, y = df["granularity_days"], df["skill"] * 100
        ax.plot(x, y, color=colour, marker="o", markersize=4.5)
        best = df.loc[df["skill"].idxmax()]
        ax.plot(best.granularity_days, best.skill * 100, marker="o",
                markersize=11, markerfacecolor="none", markeredgewidth=2.0,
                color=colour, zorder=4)
        ax.text(x.iloc[0], y.iloc[0] + label_dy[name], name, color=colour,
                fontsize=11, ha="left")
    for days, label in ((1, "日"), (7, "週"), (30, "月")):
        ax.axvline(days, color=RULE, linewidth=1.0, linestyle=(0, (2, 3)), zorder=0)
        ax.text(days, -3.2, label, ha="center", fontsize=9.5, color=MUTED)

    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 7, 10, 15, 30, 61, 91])
    ax.set_xticklabels(["1", "2", "3", "5", "7", "10", "15", "30", "61", "91"])
    ax.minorticks_off()
    ax.set_xlim(0.85, 110)
    ax.set_ylim(-5, 55)
    ax.set_xlabel("ビン幅 [日]（対数軸）")
    ax.set_ylabel("誤差の削減 [%]")
    ax.text(95, 51, "丸が最良点", fontsize=9.5, color=SECONDARY, ha="right")
    save(fig, "skill-bin-width", A2)


def fig_best_bin_width() -> None:
    """最良点からの差を標準誤差で測る。15 日が谷底だと目で見える。

    誤差の削減率をそのまま描くと曲線が平らで、どこが最良か分からない。
    最良点との差を、その差の標準誤差で割った値にすると谷ができる。
    2 標準誤差を「区別できない」の線として引く。
    """
    data = _regions("timescale")
    fig, ax = plt.subplots(figsize=(8.8, 4.6))

    ax.axhspan(0, 2, color=PALE, zorder=0)
    ax.axhline(2, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)), zorder=1)
    ax.text(1.02, 2.2, "2 標準誤差", fontsize=9.5, color=SECONDARY, va="bottom")

    # 最良点の丸は 3 つとも同じ位置に来るので、半径を変えて重ねる
    for ring, (name, (df, colour)) in zip((21, 15, 9), data.items(), strict=True):
        df = df[df["granularity_days"] <= 61].sort_values("granularity_days")
        x = df["granularity_days"].to_numpy()
        y = df["vs_best_sigma"].to_numpy()
        ax.plot(x, y, color=colour, marker="o", markersize=5, label=name)
        ax.plot(x[np.argmin(y)], 0, marker="o", markersize=ring,
                markerfacecolor="none", markeredgewidth=2.0, color=colour,
                zorder=4)

    # 2 SE 以内に収まる幅の範囲。3 本を上下に分けて置く
    for row, (name, (df, colour)) in zip((-0.6, -1.2, -1.8), data.items(),
                                         strict=True):
        df = df[df["granularity_days"] <= 61]
        inside = df.loc[df["vs_best_sigma"] <= 2.0, "granularity_days"].to_numpy()
        ax.plot([inside.min(), inside.max()], [row, row], color=colour,
                linewidth=3.0, solid_capstyle="butt", zorder=3)
        # 右に余白が無い帯は、説明を帯の左に置く
        right = inside.max() < 30
        ax.text(inside.max() * 1.18 if right else inside.min() / 1.18, row,
                f"{name} は {inside.min():.0f}〜{inside.max():.0f} 日なら同じ",
                fontsize=9.5, color=colour, va="center",
                ha="left" if right else "right")

    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 7, 10, 15, 30, 61])
    ax.set_xticklabels(["1", "2", "3", "5", "7", "10", "15", "30", "61"])
    ax.minorticks_off()
    ax.set_xlim(0.85, 75)
    ax.set_ylim(-2.3, 8.4)
    ax.set_yticks([0, 2, 4, 6, 8])
    ax.set_xlabel("ビン幅 [日]（対数軸）")
    ax.set_ylabel("最良点との差 [標準誤差]")
    ax.annotate("3 領域とも 15 日が谷底", xy=(16.5, 0.15), xytext=(31, 1.35),
                fontsize=10.5, color=TEXT, ha="left",
                arrowprops={"arrowstyle": "-|>", "color": SECONDARY,
                            "linewidth": 1.2})
    ax.legend(loc="upper center", ncols=3)
    save(fig, "best-bin-width", A2)


def fig_harmonic() -> None:
    """調和の数を増やしても頭打ちになる。実在する季節変化の細かさ。"""
    data = _regions("timescale_harmonic")
    fig, ax = plt.subplots(figsize=(8.8, 4.0))
    # 右端のラベル。和歌山と愛媛は近いので上下にずらす
    label_dy = {"北海道": 0.0, "和歌山": -2.2, "愛媛": 2.2}
    for name, (df, colour) in data.items():
        df = df[df["k"] > 0].sort_values("k")
        ax.plot(df["k"], df["skill"] * 100, color=colour, marker="o",
                markersize=4.0)
        ax.text(df["k"].iloc[-1] + 0.8, df["skill"].iloc[-1] * 100 + label_dy[name],
                name, color=colour, fontsize=11, va="center")
    ax.axvspan(5, 6, color=PALE, zorder=0)
    ax.annotate("K = 5〜6 で頭打ち\n（表せる細かさ 30〜36 日）",
                xy=(5.5, 8), xytext=(10.5, 8), fontsize=10, color=TEXT,
                va="center",
                arrowprops={"arrowstyle": "-|>", "color": SECONDARY,
                            "linewidth": 1.2})
    ax.set_xlim(0, 29)
    ax.set_ylim(0, 52)
    ax.set_xlabel("調和の数 K")
    ax.set_ylabel("誤差の削減 [%]")

    upper = ax.secondary_xaxis("top")
    ticks = [1, 3, 6, 12, 26]
    upper.set_xticks(ticks)
    upper.set_xticklabels([f"{365 / (2 * k):.0f}" for k in ticks])
    upper.set_xlabel("表せる細かさ τ = 365 / (2K) [日]")
    save(fig, "harmonic", A2)


def fig_decorrelation() -> None:
    """風の偏差が続く時間。北海道で時期から予測しにくい理由。"""
    data = _regions("variability_decorrelation")
    fig, ax = plt.subplots(figsize=(8.8, 3.8))
    seasons = ["冬", "春", "夏", "秋"]
    x = np.arange(len(seasons))
    for (name, (df, colour)), off in zip(data.items(), (-0.27, 0.0, 0.27),
                                         strict=True):
        sub = df[df["plevel"] == 200].copy()
        sub["key"] = sub["season"].str[0]
        sub = sub.set_index("key").reindex(seasons)
        days = sub["decorrelation_days"].to_numpy()
        ax.bar(x + off, days, width=0.25, color=colour, label=name)
        for xi, d in zip(x, days, strict=True):
            ax.text(xi + off, d + 0.35, f"{d:.1f}", ha="center", fontsize=9,
                    color=colour)
    ax.set_xticks(x)
    ax.set_xticklabels(seasons)
    ax.set_ylabel("相関が 1/e を切るまで [日]")
    ax.set_ylim(0, 19)
    ax.legend(loc="upper left", ncols=3)
    ax.set_title("200 hPa（約 12 km）", fontsize=10, color=SECONDARY)
    save(fig, "decorrelation", A2)


def fig_skill_by_level() -> None:
    """暦がどの高度で効くか。効くのは成層圏側だけ。"""
    data = _regions("timescale_by_level")
    levels = [850, 500, 200, 100, 30, 10]
    alt = {850: "約 1 km", 500: "約 6 km", 200: "約 12 km",
           100: "約 16 km", 30: "約 24 km", 10: "約 31 km"}
    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    y = np.arange(len(levels))[::-1]
    for (name, (df, colour)), off in zip(data.items(), (0.27, 0.0, -0.27),
                                         strict=True):
        sub = df.set_index("level_hpa").reindex(levels)
        vals = sub["skill"].to_numpy() * 100
        ax.barh(y + off, vals, height=0.25, color=colour, label=name)
        for yi, v in zip(y, vals, strict=True):
            ax.text(v + 0.8, yi + off, f"{v:.0f} %", va="center",
                    fontsize=9, color=colour)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{lv} hPa（{alt[lv]}）" for lv in levels])
    ax.set_xlabel("誤差の削減 [%]")
    ax.set_xlim(0, 58)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", ncols=3)
    save(fig, "skill-by-level-ja", A2)


NETCDF = RESEARCH / "out" / "netcdf"
#: 愛南町の代表地点（sites.json の「南レク御荘公園」）
AINAN = (32.96417, 132.55206)


def fig_ainan_landing() -> None:
    """愛南町から上げたときの平均落下点と 90 % の範囲。

    夏は半月で向きが入れ替わるので、7 月は前半と後半を両方描く。
    楕円は解析時刻ごとの落下点の共分散から描いたもので、散らばりが
    2 変量正規に従うという仮定は残る。
    """
    import xarray as xr

    ds = xr.open_dataset(NETCDF / "jra3q_windclim_ehime_2016-2025_v1.nc")
    cell = ds.sel(lat=AINAN[0], lon=AINAN[1], method="nearest")
    cases = (
        (1, 2, "1月後半", SEASON_COLOUR["冬"], "-"),
        (4, 2, "4月後半", SEASON_COLOUR["春"], "-"),
        (7, 1, "7月前半", SEASON_COLOUR["夏"], "-"),
        (7, 2, "7月後半", SEASON_COLOUR["夏"], (0, (4, 2))),
        (10, 2, "10月後半", SEASON_COLOUR["秋"], "-"),
    )
    lat0 = AINAN[0]
    km_lon = 111.195 * np.cos(np.radians(lat0))
    k90 = np.sqrt(-2.0 * np.log(0.10))  # 2 変量正規の 90 % 楕円

    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    draw_coast(ax, (130.9, 137.2, 31.2, 34.6))
    for month, half, label, colour, dash in cases:
        c = cell.sel(month=month, bin=half)
        east = float(c["drift_east_m"]) / 1000.0
        north = float(c["drift_north_m"]) / 1000.0
        lon = AINAN[1] + east / km_lon
        lat = lat0 + north / 111.195
        var_e = float(c["drift_east_var"]) / 1e6
        var_n = float(c["drift_north_var"]) / 1e6
        cov = float(c["drift_cov"]) / 1e6
        vals, vecs = np.linalg.eigh(np.array([[var_e, cov], [cov, var_n]]))
        t = np.linspace(0, 2 * np.pi, 200)
        circle = np.stack([np.cos(t), np.sin(t)])
        pts = vecs @ (np.sqrt(np.maximum(vals, 0))[:, None] * circle) * k90
        ax.plot(lon + pts[0] / km_lon, lat + pts[1] / 111.195, color=colour,
                linewidth=1.6, linestyle=dash, zorder=3)
        ax.annotate("", xy=(lon, lat), xytext=(AINAN[1], lat0),
                    arrowprops={"arrowstyle": "-|>", "color": colour,
                                "linewidth": 1.8, "linestyle": dash}, zorder=4)
        ax.plot(lon, lat, marker="o", markersize=6, color=colour, zorder=5)
    # 7 月前半の平均落下点は打ち上げ地点のすぐ東で、星に隠れやすいので名前を添える
    c = cell.sel(month=7, bin=1)
    ax.annotate("7月前半", (AINAN[1] + float(c["drift_east_m"]) / 1000.0 / km_lon,
                           lat0 + float(c["drift_north_m"]) / 1000.0 / 111.195),
                textcoords="offset points", xytext=(6, -18), fontsize=9.5,
                color=SEASON_COLOUR["夏"], zorder=7,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85,
                      "pad": 1.0})
    ax.plot(AINAN[1], lat0, marker="*", markersize=17, color=TEXT,
            markeredgecolor="white", markeredgewidth=1.0, zorder=6)
    ax.annotate("打ち上げ地点\n（愛南町）", (AINAN[1], lat0), textcoords="offset points",
                xytext=(-14, 12), ha="right", fontsize=10, color=TEXT, zorder=7,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85,
                      "pad": 1.5})
    handles = [plt.Line2D([], [], color=c, linestyle=d, linewidth=2.0, label=lbl)
               for _m, _h, lbl, c, d in cases]
    ax.legend(handles=handles, loc="lower right", ncols=1, fontsize=9.5,
              title="平均落下点と 90 % の範囲", title_fontsize=9.5)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    ax.grid(False)
    save(fig, "ainan-landing", A2)


FIGURES = {
    "speed-altitude-season": fig_speed_altitude_season,
    "region-map-ja": fig_region_map,
    "reanalyses-ja": fig_reanalyses,
    "skill-bin-width": fig_skill_bin_width,
    "best-bin-width": fig_best_bin_width,
    "harmonic": fig_harmonic,
    "decorrelation": fig_decorrelation,
    "skill-by-level-ja": fig_skill_by_level,
    "january-easterly": fig_january_easterly,
    "direction-altitude-season": fig_direction_altitude_season,
    "constancy-cycle": fig_constancy_cycle,
    "profiles-4seasons": fig_profiles_4seasons,
    "layer-summary": fig_layer_summary,
    "jet-cycle": fig_jet_cycle,
    "drift-cycle-ja": fig_drift_cycle_ja,
    "launch-windows": fig_launch_windows,
    "slip-vs-frozen-ja": fig_slip_vs_frozen,
    "upper-level-share": fig_upper_share,
    "ainan-landing": fig_ainan_landing,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", choices=sorted(FIGURES))
    a = ap.parse_args(argv)
    if not CSV.exists():
        raise SystemExit(f"CSV が見つかりません: {CSV}")
    blog_style()
    wanted = a.only or list(FIGURES)
    print(f"{OUT} に書き出します")
    for name in wanted:
        FIGURES[name]()
    print(f"{len(wanted)} 枚できました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
