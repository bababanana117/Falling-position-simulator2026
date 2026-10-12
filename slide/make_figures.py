#!/usr/bin/env python
"""Figures for the talk, drawn from research/out with the slide palette.

Every figure here is either a report figure re-rendered at slide size, or a
single-panel chart that the report shows in two or more panels. The data are
the same CSV and NetCDF files the report reads; nothing is recomputed.

Why not reuse the report's PDFs directly: their text is 8-9 pt on a
10-inch figure, their categorical colours are four, and their titles repeat
what the slide headline says. Projected, that is unreadable and off-palette.

Palette injection: the report modules bind ``CATEGORICAL``/``CMAP_SPEED`` by
name at import time, so they are rebound per module; ``INK`` and ``GRID_KW``
are shared dicts and are updated in place. Functions that hardcode
``fontsize=`` get a post-pass that scales every Text object.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent / "research"
sys.path.insert(0, str(RESEARCH))
OUT = HERE / "figures"
CSV = RESEARCH / "out" / "csv"
NC = RESEARCH / "out" / "netcdf"

import matplotlib as mpl  # noqa: E402

mpl.use("Agg")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from windclim.figures import fidelity, maps, plots, reanalyses, style, validation  # noqa: E402
from windclim.figures.coast import draw_coastline, set_geographic_aspect  # noqa: E402
from windclim.figures.plots import ROSE_SPEED_EDGES, save  # noqa: E402
from windclim.outputs.summary import SEASONS, summarise  # noqa: E402
from windclim.outputs.validation_out import shared_skill_max  # noqa: E402
from windclim.regions import BBox  # noqa: E402

# ----------------------------------------------------------------- palette
TEXT, SECONDARY, CITE, MUTED, RULE = "#1A1A1A", "#4B5563", "#6B7280", "#9CA3AF", "#E5E7EB"
BLUE, ORANGE, PALE, GREY = "#0072B2", "#D55E00", "#E3EEF8", "#F3F4F6"
REGION = {"hokkaido": "北海道", "wakayama": "和歌山"}
REGION_COLOUR = {"hokkaido": BLUE, "wakayama": ORANGE}
SLIDE_CATEGORICAL = (BLUE, ORANGE, SECONDARY, MUTED)
SLIDE_CMAP = LinearSegmentedColormap.from_list("slide_blue", ["#F4F8FC", "#9DC3E6", BLUE, "#0B3D66"])
FIRA = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/fira")
HARANO = Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji")
FS = 0.66          # inch scale: figures sit at ~0.5-0.6 of native width on the slide
FIGSIZE = (7.6 * FS, 4.2 * FS)


def fsz(w: float, h: float) -> tuple[float, float]:
    return (w * FS, h * FS)
VOISING = (42.182306, 142.850972)
SEASON_ORDER = ("冬", "春", "夏", "秋")
SEASON_KEYS = list(SEASONS)   # e.g. "冬 (12-2月)"


def apply_slide_style() -> str:
    ja = style.apply_style(japanese=True)
    for f in ("FiraSans-Regular.otf", "FiraSans-Medium.otf", "FiraSans-Bold.otf",
              "FiraSans-Italic.otf", "FiraSans-Heavy.otf"):
        font_manager.fontManager.addfont(str(FIRA / f))
    for f in ("HaranoAjiGothic-Medium.otf", "HaranoAjiGothic-Bold.otf"):
        font_manager.fontManager.addfont(str(HARANO / f))
    style.INK.update(primary=TEXT, secondary=SECONDARY, muted=MUTED, grid=RULE, surface="#FFFFFF")
    style.GRID_KW["color"] = RULE
    for mod in (validation, plots, maps, fidelity, reanalyses):
        mod.CATEGORICAL = SLIDE_CATEGORICAL
    validation.CMAP_SPEED = SLIDE_CMAP
    plots.CMAP_SPEED = SLIDE_CMAP
    validation._mark_reference_widths = _mark_widths_grey
    mpl.rcParams.update({
        "font.family": ["Fira Sans", ja or "DejaVu Sans"],
        "font.size": 15, "axes.titlesize": 16, "axes.labelsize": 15,
        "xtick.labelsize": 13, "ytick.labelsize": 13, "legend.fontsize": 13,
        "lines.linewidth": 2.8, "lines.markersize": 7, "axes.linewidth": 0.9,
        "axes.edgecolor": MUTED, "axes.labelcolor": SECONDARY, "axes.titlecolor": TEXT,
        "text.color": TEXT, "xtick.color": SECONDARY, "ytick.color": SECONDARY,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "savefig.dpi": 200, "figure.dpi": 100, "savefig.bbox": "tight", "savefig.pad_inches": 0.04,
        "mathtext.fontset": "custom", "mathtext.rm": "Fira Sans", "mathtext.it": "Fira Sans:italic",
        "mathtext.bf": "Fira Sans:bold",
    })
    return ja


def _mark_widths_grey(ax, *, label: bool = True) -> None:
    for days, text in ((1, "日"), (7, "週"), (30, "月")):
        ax.axvline(days, color=MUTED, linewidth=1.1, linestyle=":", zorder=1)
        if label:
            ax.annotate(text, xy=(days, 0.02), xycoords=("data", "axes fraction"),
                        ha="center", va="bottom", fontsize=12, color=SECONDARY)


def scale_text(fig: Figure, k: float = 1.6) -> None:
    for t in fig.findobj(mpl.text.Text):
        t.set_fontsize(t.get_fontsize() * k)


def strip_titles(fig: Figure) -> None:
    fig.suptitle("")
    for ax in fig.axes:
        ax.set_title("")


def restyle(fig: Figure, *, size=FIGSIZE, k: float = 1.6, titles: bool = False) -> Figure:
    if not titles:
        strip_titles(fig)
    scale_text(fig, k)
    fig.set_size_inches(*size)
    fig.tight_layout()
    return fig


def clean_axes(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    style.recessive_grid(ax)


def season_short(s: str) -> str:
    return s[0]


# ---------------------------------------------------------------- loaders
def bins(r: str) -> pd.DataFrame:
    return pd.read_csv(CSV / f"timescale_{r}.csv")


def harm(r: str) -> pd.DataFrame:
    return pd.read_csv(CSV / f"timescale_harmonic_{r}.csv")


def level(r: str) -> pd.DataFrame:
    return pd.read_csv(CSV / f"timescale_by_level_{r}.csv")


_DS: dict[str, xr.Dataset] = {}


def ds(r: str) -> xr.Dataset:
    if r not in _DS:
        _DS[r] = xr.open_dataset(NC / f"jra3q_windclim_{r}_2016-2025_v1.nc").load()
    return _DS[r]


def season_speeds(level_hpa: float = 200.0) -> dict[str, dict[str, float]]:
    return {r: {s: summarise(ds(r), REGION[r])["levels"][level_hpa][s]["speed_mean"]
                for s in SEASON_KEYS} for r in REGION}


# --------------------------------------------------- 2b: the reanalyses
def fig_reanalyses() -> Figure:
    """Grid spacing against ceiling, with the coverage period as a side strip."""
    products = reanalyses.PRODUCTS
    fig = Figure(figsize=fsz(11.0, 3.9))
    left, right = fig.subplots(1, 2, width_ratios=(1.35, 1.0))

    left.axhspan(0, reanalyses.BURST_KM, color=ORANGE, alpha=0.08, zorder=0)
    left.axhline(reanalyses.BURST_KM, color=ORANGE, linewidth=1.4, linestyle="--", zorder=2)
    left.annotate("破裂高度 30 km に届かない", xy=(0.98, reanalyses.BURST_KM - 1.5),
                  xycoords=("axes fraction", "data"), ha="right", va="top",
                  fontsize=12, color=ORANGE)
    for p in products:
        main = p.name == "JRA-3Q"
        colour = BLUE if main else SECONDARY
        left.scatter(p.km, p.top_km, s=260 if main else 90, color=colour, zorder=4,
                     edgecolor="white", linewidth=1.5)
        if p.name == "NCEP/NCAR R1":
            xy_text, ha = (12, 4), "left"
        elif p.name == "ERA5":
            xy_text, ha = (0, -22), "center"
        else:
            xy_text, ha = (0, 13), "center"
        left.annotate(p.name, xy=(p.km, p.top_km), xytext=xy_text, textcoords="offset points",
                      ha=ha, fontsize=13, fontweight="bold" if main else "normal",
                      color=colour)
        if main:
            left.annotate("本研究", xy=(p.km, p.top_km), xytext=(26, -8),
                          textcoords="offset points", ha="left", va="center", fontsize=13,
                          color="white", fontweight="bold",
                          bbox={"boxstyle": "round,pad=0.35", "facecolor": BLUE, "edgecolor": "none"})
    left.set_xscale("log")
    left.set_xticks([25, 50, 100, 200])
    left.set_xticklabels(["25", "50", "100", "200"])
    left.set_xticks([], minor=True)
    left.set_xlim(260, 16)
    left.set_ylim(0, 100)
    left.set_xlabel("水平格子間隔 [km]（北緯 43 度、細かいほど右）")
    left.set_ylabel("上端の高さ [km]")
    clean_axes(left)

    now = 2026
    for i, p in enumerate(products):
        main = p.name == "JRA-3Q"
        end = p.end_year or now
        right.barh(i, end - p.start_year, left=p.start_year, height=0.55,
                   color=BLUE if main else MUTED, zorder=3)
        tail = "" if p.end_year is None else f"–{p.end_year}"
        right.annotate(f"{p.start_year}{tail}  {p.n_levels} 面  {p.hours:g} h",
                       xy=(end + 1.5, i), va="center", fontsize=11.5, color=SECONDARY)
    right.set_yticks(range(len(products)))
    right.set_yticklabels([p.name for p in products])
    right.set_xlim(1935, now + 52)
    right.set_xticks([1950, 2000])
    right.set_xlabel("対象期間")
    for side in ("top", "right", "left"):
        right.spines[side].set_visible(False)
    right.tick_params(axis="y", length=0)
    style.recessive_grid(right, axis="x")
    fig.tight_layout()
    return fig


# --------------------------------------------- 3a: skill against bin width
def fig_skill_overlay() -> Figure:
    fig = Figure(figsize=fsz(7.4, 3.9))
    ax = fig.subplots()
    for r in ("wakayama", "hokkaido"):
        d = bins(r).sort_values("granularity_days")
        d = d[d["granularity_days"] <= 91]
        c = REGION_COLOUR[r]
        ax.plot(d["granularity_days"], 100 * d["skill"], color=c, marker="o", markersize=6,
                linewidth=2.8, zorder=4)
        best = d.loc[d["test_rmse_km"].idxmin()]
        ax.plot([best["granularity_days"]], [100 * best["skill"]], "o", color=c,
                markersize=15, markerfacecolor="none", markeredgewidth=2.4, zorder=5)
        # Same rule as the report: within 2 SE of the best (timescale.resolved_range).
        ok = d[d["vs_best_sigma"] <= 2.0]
        lo, hi = ok["granularity_days"].min(), ok["granularity_days"].max()
        y = 100 * best["skill"]
        ax.plot([lo, hi], [y + 3.2, y + 3.2], color=c, linewidth=1.2, alpha=0.7)
        ax.annotate(f"区別できない範囲 {lo:.0f}–{hi:.0f} 日", xy=(np.sqrt(lo * hi), y + 3.8),
                    ha="center", va="bottom", fontsize=11, color=c)
        last = d.iloc[-1]
        ax.annotate(REGION[r], xy=(last["granularity_days"], 100 * last["skill"]),
                    xytext=(8, 0), textcoords="offset points", va="center",
                    fontsize=14, color=c, fontweight="bold")
    ax.set_xscale("log")
    ticks = [1, 2, 3, 5, 7, 10, 15, 30, 61, 91]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xticks([], minor=True)
    ax.set_xlim(0.85, 150)
    ax.set_ylim(0, 55)
    ax.set_yticks([0, 15, 30, 45])
    ax.set_xlabel("ビン幅 [日]（対数軸）")
    ax.set_ylabel("誤差の削減 [%]")
    _mark_widths_grey(ax)
    clean_axes(ax)
    fig.tight_layout()
    return fig


# ------------------------------------------- 4a: harmonic regression sweep
def fig_harmonic_overlay() -> Figure:
    fig = Figure(figsize=fsz(7.4, 4.4))
    ax = fig.subplots()
    for r in ("wakayama", "hokkaido"):
        d = harm(r).sort_values("k")
        c = REGION_COLOUR[r]
        ax.plot(d["k"], 100 * d["skill"], color=c, marker="o", markersize=5, linewidth=2.6, zorder=4)
        last = d.iloc[-1]
        ax.annotate(REGION[r], xy=(last["k"], 100 * last["skill"]), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=14, color=c,
                    fontweight="bold")
    ax.axvspan(5, 6, color=BLUE, alpha=0.10, zorder=0)
    ax.annotate("K = 5–6 で頭打ち\n（分解能 30–36 日）", xy=(5.5, 27), ha="center", va="bottom",
                fontsize=12, color=BLUE)
    ax.set_xlim(-0.5, 29)
    ax.set_ylim(0, 55)
    ax.set_yticks([0, 15, 30, 45])
    ax.set_xticks([0, 2, 4, 6, 8, 12, 16, 20, 26])
    ax.set_xlabel("調和の数 K")
    ax.set_ylabel("誤差の削減 [%]")
    top = ax.twiny()
    top.set_xlim(ax.get_xlim())
    ks = [3, 6, 12, 26]
    top.set_xticks(ks)
    top.set_xticklabels([f"{365 / (2 * k):.0f}" for k in ks])
    top.set_xlabel("分解能 τ = 365 / (2K) [日]", color=SECONDARY)
    top.tick_params(axis="x", colors=SECONDARY, length=3)
    for side in ("right",):
        top.spines[side].set_visible(False)
    clean_axes(ax)
    fig.tight_layout()
    return fig


# ------------------------------------------------ 4b: skill by altitude
def fig_level_skill_both() -> Figure:
    lv = {r: level(r).sort_values("level_hpa", ascending=False) for r in REGION}
    alt = {k: v["alt_km"] for k, v in summarise(ds("hokkaido"), "北海道")["levels"].items()}
    levels = list(lv["hokkaido"]["level_hpa"])
    n = len(levels)
    y = np.arange(n)
    fig = Figure(figsize=fsz(7.4, 4.6))
    ax = fig.subplots()
    h = 0.36
    for off, r in ((-h / 2, "hokkaido"), (h / 2, "wakayama")):
        d = lv[r].set_index("level_hpa").loc[levels]
        vals = 100 * d["skill"].values
        ax.barh(y + off, vals, height=h, color=REGION_COLOUR[r], zorder=3)
        for yi, v in zip(y + off, vals):
            ax.annotate(f"{v:.0f} %", xy=(v + 0.8, yi), va="center", fontsize=12,
                        color=REGION_COLOUR[r], fontweight="bold" if r == "hokkaido" else "normal")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{p:.0f} hPa（約 {alt.get(float(p), float('nan')):.0f} km）" for p in levels])
    ax.invert_yaxis()
    ax.set_xlim(0, shared_skill_max(CSV, "by_level") + 6)
    ax.set_xlabel("誤差の削減 [%]（風速、時期を知らない場合との比較）")
    ax.annotate("北海道", xy=(0.99, 0.11), xycoords="axes fraction", ha="right", fontsize=14,
                color=BLUE, fontweight="bold")
    ax.annotate("和歌山", xy=(0.99, 0.04), xycoords="axes fraction", ha="right", fontsize=14,
                color=ORANGE, fontweight="bold")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    clean_axes(ax)
    style.recessive_grid(ax, axis="x")
    fig.tight_layout()
    return fig


# ----------------------------------- 5: altitude x half-month heat maps
def fig_alt_half(kind: str) -> Figure:
    """One panel of the report's F1: ``kind`` is "speed" or "direction"."""
    d = ds("hokkaido")
    alt = plots._alt_axis(d)
    order = np.argsort(alt)
    constancy = plots._flat_bins(d, "constancy")[:, order]
    fig = Figure(figsize=fsz(9.0, 4.4))
    ax = fig.subplots()
    if kind == "speed":
        speed = plots._flat_bins(d, "speed_mean")[:, order]
        mesh = plots._half_altitude_panel(ax, d, speed, alt[order], cmap=SLIDE_CMAP, vmin=0,
                                          vmax=float(np.nanpercentile(speed, 99)), label="風速")
        cb = fig.colorbar(mesh, ax=ax, pad=0.015)
        cb.set_label("平均風速 [m/s]")
    else:
        direction = plots._flat_bins(d, "dir_vector_mean")[:, order]
        mesh = plots._half_altitude_panel(ax, d, direction, alt[order], cmap=plots.CMAP_DIRECTION,
                                          vmin=0, vmax=360, label="風向",
                                          mask=constancy < plots.CONSTANCY_MASK)
        cb = fig.colorbar(mesh, ax=ax, pad=0.015, ticks=[0, 90, 180, 270, 360])
        cb.ax.set_yticklabels(["北", "東", "南", "西", "北"])
        cb.set_label("風向（吹いてくる向き）")
    ax.set_xticks(np.arange(12) * 2 + 0.5)
    ax.set_xticklabels([str(m) for m in range(1, 13)])
    ax.set_xlabel("月（各月 = 前半・後半の 2 ビン）")
    scale_text(fig, 1.45)
    fig.tight_layout()
    return fig


# ------------------------------------------ 5: 200 hPa by season
def fig_season_speed_200() -> Figure:
    sp = season_speeds(200.0)["hokkaido"]
    vals = [sp[k] for k in SEASON_KEYS]
    fig = Figure(figsize=fsz(4.2, 3.6))
    ax = fig.subplots()
    y = np.arange(4)
    colours = [BLUE if v == max(vals) else MUTED for v in vals]
    ax.barh(y, vals, height=0.62, color=colours, zorder=3)
    for yi, v, c in zip(y, vals, colours):
        ax.annotate(f"{v:.1f}", xy=(v + 0.8, yi), va="center", fontsize=15,
                    fontweight="bold" if c == BLUE else "normal",
                    color=BLUE if c == BLUE else SECONDARY)
    ax.set_yticks(y)
    ax.set_yticklabels([season_short(k) for k in SEASON_KEYS], fontsize=15)
    ax.invert_yaxis()
    ax.set_xlim(0, 56)
    ax.set_xticks([0, 20, 40])
    ax.set_xlabel("200 hPa の平均風速 [m/s]")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    clean_axes(ax)
    style.recessive_grid(ax, axis="x")
    fig.tight_layout()
    return fig


# ------------------------------------- 6: constancy of the burst band
def fig_constancy_10hpa() -> Figure:
    d = ds("hokkaido")
    lev = list(d["level"].values)
    con = plots._flat_bins(d, "constancy")
    x = np.arange(con.shape[0])
    fig = Figure(figsize=fsz(9.0, 3.9))
    ax = fig.subplots()
    ax.axhspan(0, plots.CONSTANCY_MASK, color=ORANGE, alpha=0.08, zorder=0)
    ax.axhline(plots.CONSTANCY_MASK, color=ORANGE, linewidth=1.2, linestyle="--", zorder=1)
    ax.annotate("C = 0.3", xy=(47.4, plots.CONSTANCY_MASK + 0.02), ha="right", va="bottom",
                fontsize=11, color=ORANGE)
    for p, colour, label, lw in ((200.0, MUTED, "200 hPa（約 12 km）", 2.2),
                                 (10.0, BLUE, "10 hPa（約 31 km、破裂高度帯）", 3.0)):
        y = con[:, lev.index(p)]
        ax.plot(x, y, color=colour, linewidth=lw, marker="o", markersize=4.5, zorder=4)
        ax.annotate(label, xy=(x[-1], y[-1]), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=13, color=colour, fontweight="bold")
    y10 = con[:, lev.index(10.0)]
    # The two lowest bins, one on each side of summer; a third label collides.
    for i, dy in ((int(np.argmin(y10[:12])), 11), (12 + int(np.argmin(y10[12:])), -12)):
        month, half = i // 2 + 1, "前半" if i % 2 == 0 else "後半"
        ax.annotate(f"{month} 月{half} {y10[i]:.2f}", xy=(x[i], y10[i]), xytext=(10, dy),
                    textcoords="offset points", ha="left", va="center", fontsize=11.5, color=BLUE)
    ax.set_xticks(x[::2] + 0.5)
    ax.set_xticklabels([str(m) for m in range(1, 13)])
    ax.tick_params(axis="x", labelsize=11)
    ax.set_xlim(-0.8, 58)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.3, 0.6, 0.9])
    ax.set_ylabel("定常度 C")
    ax.set_xlabel("月（各月 = 前半・後半の 2 ビン、領域平均）")
    clean_axes(ax)
    fig.tight_layout()
    return fig


def fig_roses_10hpa() -> Figure:
    """Two roses at 10 hPa: one lobe in July, two lobes in October."""
    d = ds("hokkaido")
    counts = d["rose_counts"]
    sector_deg = d["sector_deg"].values
    width = np.radians(360.0 / len(sector_deg))
    edges = list(ROSE_SPEED_EDGES)
    picks = ((7, "7 月後半", BLUE), (10, "10 月後半", ORANGE))
    fig = Figure(figsize=fsz(5.0, 2.7))
    axes = fig.subplots(1, 2, subplot_kw={"projection": "polar"})
    blocks = []
    for month, _, _ in picks:
        block = counts.sel(month=month, bin=2, level=10.0, method="nearest").values.astype(float)
        block = block / block.sum() * 100.0
        blocks.append(block)
    # Each rose gets its own radial scale. On July's scale October's scattered
    # sectors are a dot; the point of the pair is October's shape, not its size.
    for ax, (month, title, colour), block in zip(axes, picks, blocks):
        row_max = float(block.sum(axis=1).max())
        theta = np.radians(sector_deg)
        base = np.zeros_like(theta)
        ramp = LinearSegmentedColormap.from_list("r", ["#FFFFFF", colour])
        for ci in range(block.shape[1]):
            ax.bar(theta, block[:, ci], width=width, bottom=base,
                   color=ramp((ci + 1.5) / (block.shape[1] + 1)), edgecolor="white",
                   linewidth=0.5)
            base = base + block[:, ci]
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_xticks(np.radians([0, 90, 180, 270]))
        ax.set_xticklabels(["北", "東", "南", "西"], fontsize=12)
        ax.set_ylim(0, row_max * 1.05)
        ax.set_yticks([])
        ax.set_title(f"{title}\n最大 {row_max:.0f} %", fontsize=12, color=colour,
                     fontweight="bold", pad=8)
        ax.spines["polar"].set_color(RULE)
        ax.grid(color=RULE)
    fig.tight_layout()
    return fig


# --------------------------------- 7: January at 10 hPa, easterlies
def fig_map_10hpa_jan() -> Figure:
    """January mean at 10 hPa: both half-months, weighted by their sample counts.

    That weighting is what the report's -3.8 m/s is (the two halves alone are
    -6.2 and -1.6 m/s); a plain average of the halves would print -3.9.
    """
    d = ds("hokkaido")
    jan = d.sel(month=1, level=10.0)
    n = jan["n"]
    u = ((jan["u_mean"] * n).sum("bin") / n.sum("bin")).values
    v = ((jan["v_mean"] * n).sum("bin") / n.sum("bin")).values
    lon, lat = d["lon"].values, d["lat"].values
    box = BBox(south=39.5, north=47.0, west=137.5, east=149.5)
    fig = Figure(figsize=fsz(7.6, 4.6))
    ax = fig.subplots()
    cmap = LinearSegmentedColormap.from_list("uv", [ORANGE, "#FFFFFF", BLUE])
    lim = float(np.nanmax(np.abs(u)))
    mesh = ax.pcolormesh(lon, lat, u, cmap=cmap, vmin=-lim, vmax=lim, shading="nearest",
                         alpha=0.55, zorder=1)
    draw_coastline(ax, box, linewidth=1.0, color=SECONDARY, zorder=3)
    step = 2
    ax.quiver(lon[::step], lat[::step], u[::step, ::step], v[::step, ::step], color=TEXT,
              scale=120, width=0.004, zorder=4)
    ax.plot(VOISING[1], VOISING[0], "*", color=TEXT, markersize=14, zorder=6)
    ax.annotate("VOISING", xy=(VOISING[1], VOISING[0]), xytext=(6, -14),
                textcoords="offset points", fontsize=11, color=TEXT)
    ax.set_xlim(box.west, box.east)
    ax.set_ylim(box.south, box.north)
    set_geographic_aspect(ax, 43.0)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    cb = fig.colorbar(mesh, ax=ax, pad=0.02, ticks=[-lim, 0, lim], format="%.0f")
    cb.set_label("東西風 u [m/s]（負 = 東風）")
    gw = d["gauss_weight"]
    gw = gw.mean([dim for dim in gw.dims if dim != "lat"]).values     # one weight per latitude
    w2 = np.broadcast_to(gw[:, None], u.shape)
    mean_u = float(np.nansum(u * w2) / np.nansum(w2))
    ax.annotate(f"1 月の領域平均 u = {mean_u:+.1f} m/s", xy=(0.02, 0.04), xycoords="axes fraction",
                fontsize=12, color=ORANGE, fontweight="bold",
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": "none", "alpha": 0.85})
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


# --------------------------------------------- 2a: where the region is
def fig_region_map() -> Figure:
    box = BBox(south=40.0, north=46.5, west=138.0, east=149.0)
    frame = BBox(south=37.5, north=48.5, west=135.0, east=152.0)
    fig = Figure(figsize=fsz(4.6, 3.6))
    ax = fig.subplots()
    draw_coastline(ax, frame, linewidth=0.8, color=SECONDARY, fill=True, fill_zorder=0)
    ax.add_patch(FancyBboxPatch((box.west, box.south), box.east - box.west, box.north - box.south,
                                boxstyle="square,pad=0", facecolor=PALE, edgecolor=BLUE,
                                linewidth=2.0, alpha=0.55, zorder=2))
    ax.plot(VOISING[1], VOISING[0], "*", color=ORANGE, markersize=16, zorder=6)
    ax.annotate("VOISING", xy=(VOISING[1], VOISING[0]), xytext=(6, -16),
                textcoords="offset points", fontsize=12, color=ORANGE, fontweight="bold")
    ax.annotate("40–46.5°N\n138–149°E\n570 格子点", xy=(box.east - 0.3, box.north - 0.3),
                ha="right", va="top", fontsize=11, color=BLUE)
    ax.set_xlim(frame.west, frame.east)
    ax.set_ylim(frame.south, frame.north)
    set_geographic_aspect(ax, 43.0)
    ax.set_xticks([136, 140, 144, 148, 152])
    ax.set_yticks([38, 42, 46])
    ax.tick_params(labelsize=11)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


# --------------------------------------- 8: flight distance per bin
def fig_drift_by_bin() -> Figure:
    d = pd.read_csv(CSV / "drift_hokkaido.csv").sort_values(["month", "bin"])
    x = np.arange(len(d))
    vals = d["dist_mean_km"].values
    imin, imax = int(np.argmin(vals)), int(np.argmax(vals))
    colours = [MUTED] * len(d)
    colours[imin] = BLUE
    colours[imax] = ORANGE
    fig = Figure(figsize=fsz(9.0, 4.0))
    ax = fig.subplots()
    ax.bar(x, vals, width=0.78, color=colours, zorder=3)
    ax.plot(x, d["dist_p90_km"].values, linestyle="none", marker="_", markersize=11,
            markeredgewidth=1.6, color=SECONDARY, zorder=4)
    ax.annotate("p90", xy=(x[-1] + 0.6, d["dist_p90_km"].values[-1]), va="center",
                fontsize=11, color=SECONDARY)
    for i, c, dx in ((imin, BLUE, 0), (imax, ORANGE, -40)):
        row = d.iloc[i]
        ax.annotate(f"{int(row['month'])} 月{'前半' if row['bin'] == 1 else '後半'}\n{vals[i]:.0f} km",
                    xy=(x[i], vals[i]), xytext=(dx, 32), textcoords="offset points",
                    ha="center", fontsize=12, color=c, fontweight="bold")
    ax.set_xticks(x[::2] + 0.5)
    ax.set_xticklabels([f"{m} 月" for m in range(1, 13)])
    ax.set_xlim(-0.8, len(d) + 1.2)
    ax.set_ylim(0, 320)
    ax.set_yticks([0, 100, 200, 300])
    ax.set_ylabel("平均飛行距離 [km]")
    ax.set_xlabel("月（前半・後半の 24 ビン、領域平均）")
    clean_axes(ax)
    style.recessive_grid(ax, axis="y")
    fig.tight_layout()
    return fig


# --------------------------------------------- 9, 10: VOISING landings
def _landing(months: tuple[int, ...], colours: tuple[str, ...], *, size) -> Figure:
    maps.CATEGORICAL = colours
    try:
        fig = maps.fig_landing_ellipse_map(ds("hokkaido"), "hokkaido", "北海道",
                                           VOISING[0], VOISING[1], "VOISING",
                                           months=months, bin_index=2)
    finally:
        maps.CATEGORICAL = SLIDE_CATEGORICAL
    ax = fig.axes[0]
    # On the slide the frame is small: axis titles go, tick labels stay, and
    # the legend moves onto the empty land in the upper left with short labels.
    ax.set_xlabel("")
    ax.set_ylabel("")
    leg = ax.get_legend()
    if leg is not None:
        handles, labels = ax.get_legend_handles_labels()
        labels = [t.replace(" 後半 (16日-月末)", "後半").replace(" 前半 (1-15日)", "前半")
                  for t in labels]
        ax.legend(handles=handles, labels=labels, loc="upper left", fontsize=9,
                  frameon=True, framealpha=0.9, edgecolor="none", handletextpad=0.4)
    return restyle(fig, size=size, k=1.5)


def fig_voising_landing_seasons() -> Figure:
    return _landing((1, 4, 7, 10), (SECONDARY, MUTED, ORANGE, BLUE), size=fsz(6.4, 5.6))


def fig_voising_landing_oct() -> Figure:
    return _landing((10,), (BLUE,), size=fsz(5.6, 5.0))


# Distance from the mean landing point to the nearest coast, from the report's
# table tab:voising-offshore (research/report/sections/04_hokkaido.tex). The
# pipeline does not write these to CSV.
OFFSHORE_KM = {(1, 1): 80, (1, 2): 75, (4, 1): 67, (4, 2): 74,
               (7, 1): 4, (7, 2): 2, (10, 1): 59, (10, 2): 55}


def fig_offshore_bars() -> Figure:
    keys = list(OFFSHORE_KM)
    vals = [OFFSHORE_KM[k] for k in keys]
    x = np.arange(len(keys))
    colours = [ORANGE if k[0] == 7 else (BLUE if k[0] == 10 else MUTED) for k in keys]
    fig = Figure(figsize=fsz(4.6, 3.8))
    ax = fig.subplots()
    ax.bar(x, vals, width=0.8, color=colours, zorder=3)
    for xi, v, c in zip(x, vals, colours):
        ax.annotate(f"{v}", xy=(xi, v + 1.5), ha="center", va="bottom", fontsize=12, color=c,
                    fontweight="bold" if c != MUTED else "normal")
    ax.set_xticks(x[::2] + 0.5)
    ax.set_xticklabels([f"{k[0]} 月" for k in keys[::2]])
    ax.set_ylim(0, 95)
    ax.set_yticks([0, 40, 80])
    ax.set_ylabel("平均落下点から岸まで [km]")
    ax.tick_params(axis="x", length=0)
    clean_axes(ax)
    style.recessive_grid(ax, axis="y")
    fig.tight_layout()
    return fig


# ------------------------------------- 10: late-October profile at VOISING
def fig_oct_profile() -> Figure:
    d = pd.read_csv(CSV / "site_profile_hokkaido.csv")
    d = d[(d["month"] == 10) & (d["bin"] == 2)].sort_values("alt_km")
    fig = Figure(figsize=fsz(5.2, 4.6))
    ax = fig.subplots()
    ax.fill_betweenx(d["alt_km"], 0, d["speed_p90"], color=PALE, zorder=1)
    ax.plot(d["speed_mean"], d["alt_km"], color=BLUE, linewidth=3.0, zorder=3)
    ax.annotate("p90", xy=(d["speed_p90"].max() + 1, d.loc[d["speed_p90"].idxmax(), "alt_km"]),
                fontsize=11, color=SECONDARY, va="center")
    # One arrow per selected level: where the payload is carried, coloured by
    # how much the mean direction can be trusted.
    picks = (850, 500, 300, 200, 150, 100, 70, 50, 30, 20, 10)
    xa = 78.0
    for p in picks:
        row = d[d["level_hpa"] == p]
        if row.empty:
            continue
        row = row.iloc[0]
        c = row["constancy"]
        colour = BLUE if c >= 0.9 else (SECONDARY if c >= 0.3 else ORANGE)
        bearing = (row["dir_vector_mean"] + 180.0) % 360.0   # meteorological "from" -> "to"
        ang = np.radians(90.0 - bearing)                     # compass -> maths angle
        L = 6.0
        ax.annotate("", xy=(xa + L * np.cos(ang), row["alt_km"] + 1.0 * L * np.sin(ang)),
                    xytext=(xa, row["alt_km"]),
                    arrowprops={"arrowstyle": "-|>", "color": colour, "linewidth": 2.2,
                                "mutation_scale": 14}, zorder=5)
        ax.annotate(f"{c:.2f}", xy=(xa + 8.5, row["alt_km"]), va="center", fontsize=10.5,
                    color=colour)
    ax.axhspan(26.0, 32.0, color=ORANGE, alpha=0.08, zorder=0)
    ax.annotate("破裂高度帯", xy=(2, 29.0), va="center", fontsize=12, color=ORANGE)
    ax.axhspan(6.0, 20.0, color=BLUE, alpha=0.06, zorder=0)
    ax.annotate("6–20 km", xy=(2, 18.5), va="center", fontsize=12, color=BLUE)
    ax.annotate("200 hPa\n47.7 m/s", xy=(47.7, 11.9), xytext=(30, 3.5), fontsize=12,
                color=BLUE, fontweight="bold",
                arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8})
    ax.text(xa, 41.5, "進行方位・定常度", ha="center", fontsize=11, color=SECONDARY)
    ax.set_xlim(0, 96)
    ax.set_ylim(0, 41)
    ax.set_xticks([0, 20, 40, 60])
    ax.set_yticks([0, 10, 20, 30, 40])
    ax.set_xlabel("平均風速 [m/s]")
    ax.set_ylabel("高度 [km]")
    clean_axes(ax)
    fig.tight_layout()
    return fig


# ---------------------------------------- 11: decorrelation at 200 hPa
def fig_decorrelation_200() -> Figure:
    fig = Figure(figsize=fsz(6.6, 3.8))
    ax = fig.subplots()
    x = np.arange(4)
    w = 0.38
    for off, r in ((-w / 2, "hokkaido"), (w / 2, "wakayama")):
        d = pd.read_csv(CSV / f"variability_decorrelation_{r}.csv")
        d = d[d["plevel"] == 200]
        vals = [float(d[d["season"].str.startswith(s)]["decorrelation_days"].iloc[0])
                for s in SEASON_ORDER]
        vals = [min(v, 20.0) for v in vals]
        ax.bar(x + off, vals, width=w, color=REGION_COLOUR[r], zorder=3)
        for xi, v in zip(x + off, vals):
            ax.annotate(f"{v:.1f}", xy=(xi, v + 0.3), ha="center", va="bottom", fontsize=12,
                        color=REGION_COLOUR[r], fontweight="bold" if r == "hokkaido" else "normal")
    ax.set_xticks(x)
    ax.set_xticklabels(SEASON_ORDER, fontsize=14)
    ax.set_ylim(0, 19)
    ax.set_yticks([0, 5, 10, 15])
    ax.set_ylabel("記憶が消えるまで [日]")
    ax.annotate("北海道", xy=(0.02, 0.92), xycoords="axes fraction", fontsize=14, color=BLUE,
                fontweight="bold")
    ax.annotate("和歌山", xy=(0.02, 0.82), xycoords="axes fraction", fontsize=14, color=ORANGE,
                fontweight="bold")
    ax.tick_params(axis="x", length=0)
    clean_axes(ax)
    style.recessive_grid(ax, axis="y")
    fig.tight_layout()
    return fig


# --------------------------------------- 12: slip against frozen wind
def fig_slip_vs_frozen() -> Figure:
    slip = pd.read_csv(CSV / "fidelity_slip_hokkaido.csv")
    slip = slip[slip["lag_hours"] == 24]
    if "unit" in slip and slip["unit"].nunique() > 1:
        slip = slip[slip["unit"].str.contains("km")]
    err = pd.read_csv(CSV / "fidelity_error_hokkaido.csv")
    variants = set(err["variant"])
    both = next(v for v in ("both_frozen", "both", "frozen") if v in variants)
    err = err[err["variant"] == both]

    def pick(frame, col, s):
        return float(frame[frame["season"].str.startswith(s)][col].iloc[0])

    a = [pick(slip, "median", s) for s in SEASON_ORDER]
    b = [pick(err, "median_km", s) for s in SEASON_ORDER]
    fig = Figure(figsize=fsz(7.6, 3.3))
    ax = fig.subplots()
    x = np.arange(4)
    w = 0.38
    ax.bar(x - w / 2, a, width=w, color=BLUE, zorder=3)
    ax.bar(x + w / 2, b, width=w, color=MUTED, zorder=3)
    for xi, va, vb in zip(x, a, b):
        ax.annotate(f"{va:.0f}", xy=(xi - w / 2, va + 1), ha="center", va="bottom", fontsize=13,
                    color=BLUE, fontweight="bold")
        ax.annotate(f"{vb:.1f}", xy=(xi + w / 2, vb + 1), ha="center", va="bottom", fontsize=12,
                    color=SECONDARY)
        ax.annotate(f"×{va / vb:.0f}", xy=(xi, max(va, vb) + 9), ha="center", fontsize=12,
                    color=SECONDARY)
    ax.set_xticks(x)
    ax.set_xticklabels(SEASON_ORDER, fontsize=14)
    ax.set_ylim(0, 96)
    ax.set_yticks([0, 20, 40, 60, 80])
    ax.set_ylabel("落下点のずれ（中央値）[km]")
    ax.annotate("打ち上げが 1 日ずれる", xy=(0.98, 0.93), xycoords="axes fraction", ha="right",
                fontsize=13, color=BLUE, fontweight="bold")
    ax.annotate("風を打ち上げ時刻・地点で固定する近似", xy=(0.98, 0.84), xycoords="axes fraction",
                ha="right", fontsize=13, color=SECONDARY)
    ax.tick_params(axis="x", length=0)
    clean_axes(ax)
    style.recessive_grid(ax, axis="y")
    fig.tight_layout()
    return fig


JOBS = {
    "region_map": fig_region_map,
    "reanalyses": fig_reanalyses,
    "skill_overlay": fig_skill_overlay,
    "harmonic_overlay": fig_harmonic_overlay,
    "level_skill_both": fig_level_skill_both,
    "alt_half_speed": lambda: fig_alt_half("speed"),
    "alt_half_direction": lambda: fig_alt_half("direction"),
    "season_speed_200": fig_season_speed_200,
    "constancy_10hpa": fig_constancy_10hpa,
    "roses_10hpa": fig_roses_10hpa,
    "map_10hpa_jan": fig_map_10hpa_jan,
    "drift_by_bin": fig_drift_by_bin,
    "voising_landing_seasons": fig_voising_landing_seasons,
    "voising_landing_oct": fig_voising_landing_oct,
    "offshore_bars": fig_offshore_bars,
    "oct_profile": fig_oct_profile,
    "decorrelation_200": fig_decorrelation_200,
    "slip_vs_frozen": fig_slip_vs_frozen,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print("\n".join(JOBS))
        return
    apply_slide_style()
    OUT.mkdir(exist_ok=True)
    failed = []
    for name in (a.only or JOBS):
        try:
            _, pdf = save(JOBS[name](), OUT, "S", name)
            print("drew", pdf.name)
        except Exception as exc:  # noqa: BLE001 -- report every failure, then exit non-zero
            failed.append(name)
            print(f"FAILED {name}: {type(exc).__name__}: {exc}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
