"""Figures for the time-resolution study.

The first figure is the answer: training and validation error against bin width,
on one pair of axes. The gap between the two curves is the overfitting, and the
minimum of the validation curve is the finest unit the data supports. Everything
else here breaks that answer down by altitude, by season and by region.

The shaded band on the validation curve is the **paired** uncertainty, not the
year-to-year spread. The same ten years score every bin width, so the comparison
between widths is far more precise than either width's own error bar, and using
the unpaired spread would hide a real difference inside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .style import CATEGORICAL, CMAP_SPEED, INK, recessive_grid

__all__ = [
    "fig_by_level",
    "fig_by_season",
    "fig_harmonic_curve",
    "fig_region_comparison",
    "fig_skill_curve",
    "fig_variance_decomposition",
]

WEEK_DAYS = 7.0
MONTH_DAYS = 30.0
DAY = 1.0


def _mark_reference_widths(ax, *, label: bool = True) -> None:
    """Mark day, half and month so they can be found without counting ticks.

    Labels go at the bottom of the axes: the interesting part of this curve is
    its rise on the right, so the top is where the legend has to live.
    """
    for days, text, colour in (
        (DAY, "日", CATEGORICAL[3]),
        (WEEK_DAYS, "週", CATEGORICAL[1]),
        (MONTH_DAYS, "月", CATEGORICAL[2]),
    ):
        ax.axvline(days, color=colour, linewidth=1.2, linestyle=":", zorder=1)
        if label:
            ax.annotate(text, xy=(days, 0.012), xycoords=("data", "axes fraction"),
                        ha="center", va="bottom", fontsize=9, color=colour)


def fig_skill_curve(bins: pd.DataFrame, region: str, *, placebo: float) -> Figure:
    """Training and validation error against bin width. The headline figure.

    Two panels rather than one with an inset: the curve rises steeply towards a
    single annual bin, so anything laid over the axes ends up covering the rise,
    and the flat bottom where the answer lives is only a fifth of the full range.
    """
    d = bins.sort_values("granularity_days")
    best = d.loc[d["test_rmse_km"].idxmin()]

    fig = Figure(figsize=(11.5, 5.2))
    full, zoom = fig.subplots(1, 2, width_ratios=(1.25, 1.0))

    def draw(ax, frame, *, legend: bool):
        ax.plot(frame["granularity_days"], frame["train_rmse_km"], color=INK["muted"],
                linewidth=1.8, linestyle="--", marker="o", markersize=4,
                label="訓練誤差（同じ年で当てる）")
        ax.plot(frame["granularity_days"], frame["test_rmse_km"], color=CATEGORICAL[0],
                linewidth=2.2, marker="o", markersize=5,
                label="検証誤差（除いた年を当てる）")
        ax.fill_between(
            frame["granularity_days"],
            frame["test_rmse_km"] - 2 * frame["vs_best_sem_km"],
            frame["test_rmse_km"] + 2 * frame["vs_best_sem_km"],
            color=CATEGORICAL[0], alpha=0.18, linewidth=0,
            label="最良との差の $\\pm 2$ 標準誤差",
        )
        marker, = ax.plot([best["granularity_days"]], [best["test_rmse_km"]], "o",
                          color=CATEGORICAL[0], markersize=11,
                          markerfacecolor="none", markeredgewidth=2, zorder=5)
        marker.set_gid("best")
        ax.set_xscale("log")
        ticks = [t for t in (1, 2, 3, 5, 7, 10, 15, 30, 61, 91, 365)
                 if t <= frame["granularity_days"].max()]
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(t) for t in ticks])
        ax.set_xlabel("ビン幅 [日]（対数軸）")
        recessive_grid(ax)
        _mark_reference_widths(ax)
        if legend:
            handles, _ = ax.get_legend_handles_labels()
            handles.append(Line2D([], [], linestyle="none",
                                  label=f"曜日プラセボ: skill = {placebo:+.4f}"))
            ax.legend(handles=handles, loc="upper left", fontsize=9)

    draw(full, d, legend=True)
    full.set_ylabel("落下位置の誤差 RMSE [km]")
    full.set_title("全範囲", fontsize=10)

    draw(zoom, d[d["granularity_days"] <= 61], legend=False)
    zoom.set_title("61 日以下を拡大", fontsize=10)

    fig.suptitle(
        f"{region}: 時間解像度と予測誤差"
        f"（最良はビン幅 {best['granularity_days']:.0f} 日）",
        y=0.99,
    )
    fig.text(
        0.01, 0.01,
        "訓練誤差が下がり続けるのに検証誤差が底を打つのが過適合。"
        "検証誤差の最小点より細かいビンは、信号ではなくノイズを塗り分けている。",
        fontsize=8, color=INK["secondary"],
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    return fig


def fig_harmonic_curve(harmonics: pd.DataFrame, region: str) -> Figure:
    """The same question with a smooth basis, which has no bin edges to argue about."""
    fig = Figure(figsize=(8.2, 5.0))
    ax = fig.subplots()
    ax.plot(harmonics["k"], harmonics["train_rmse_km"], color=INK["muted"],
            linewidth=1.6, linestyle="--", label="訓練誤差")
    ax.plot(harmonics["k"], harmonics["test_rmse_km"], color=CATEGORICAL[0],
            linewidth=2.2, marker="o", markersize=4, label="検証誤差")
    best = harmonics.loc[harmonics["test_rmse_km"].idxmin()]
    marker, = ax.plot([best["k"]], [best["test_rmse_km"]], "o", color=CATEGORICAL[0],
                      markersize=11, markerfacecolor="none", markeredgewidth=2, zorder=5)
    marker.set_gid("best")

    # A twin axis with explicit ticks rather than secondary_xaxis: the resolution
    # of K = 0 is infinite, and a transform that returns inf makes matplotlib
    # refuse to set the limits at all.
    ax.set_xlabel("調和の次数 $K$")
    top = ax.twiny()
    top.set_xlim(ax.get_xlim())
    ticks = [k for k in (1, 2, 3, 6, 12, 18, 26) if k <= harmonics["k"].max()]
    top.set_xticks(ticks)
    top.set_xticklabels([f"{365 / (2 * k):.0f}" for k in ticks])
    top.set_xlabel("分解できる時間スケール [日]")
    ax.set_ylabel("落下位置の誤差 RMSE [km]")
    recessive_grid(ax)
    ax.legend(fontsize=9)
    ax.set_title(
        f"{region}: 何次の季節変化まで支えられるか"
        f"（最良 $K$ = {best['k']:.0f}、分解能 {best['resolution_days']:.0f} 日）"
    )
    fig.tight_layout()
    return fig


def fig_by_level(
    by_level: pd.DataFrame, region: str, *, skill_max: float | None = None
) -> Figure:
    """Does the answer depend on altitude? The skill does, a great deal.

    ``skill_max`` fixes the left panel's axis in percent. Pass the same value for
    both regions: left to scale itself, Hokkaido's best level (24 %) would fill
    the panel exactly as Wakayama's best (49 %) does, and the two figures would
    read as equal when one is twice the other.
    """
    d = by_level.sort_values("level_hpa", ascending=False)
    y = np.arange(len(d))
    fig = Figure(figsize=(9.5, 4.6))
    left, right = fig.subplots(1, 2, sharey=True)

    left.barh(y, 100 * d["skill"], color=CMAP_SPEED(0.6), height=0.6)
    left.set_yticks(y)
    left.set_yticklabels([f"{p:.0f} hPa" for p in d["level_hpa"]])
    left.set_xlabel("誤差の削減 [%]")
    left.set_title("気候値がどれだけ効くか", fontsize=10)
    if skill_max is not None:
        left.set_xlim(0, skill_max)
    recessive_grid(left, axis="x")

    for i, (_, row) in enumerate(d.iterrows()):
        right.plot([row["resolved_lo_days"], row["resolved_hi_days"]], [i, i],
                   color=INK["muted"], linewidth=4, solid_capstyle="round")
        right.plot([row["best_days"]], [i], "o", color=CATEGORICAL[0], markersize=7)
    for days, colour in ((DAY, CATEGORICAL[3]), (WEEK_DAYS, CATEGORICAL[1]),
                         (MONTH_DAYS, CATEGORICAL[2])):
        right.axvline(days, color=colour, linewidth=1.2, linestyle=":")
    right.set_xscale("log")
    right.set_xticks([1, 3, 7, 15, 30, 91, 365])
    right.set_xticklabels(["1", "3", "7", "15", "30", "91", "365"])
    right.set_xlabel("支えられるビン幅 [日]（帯は区別できない範囲）")
    right.set_title("どこまで細かく見てよいか", fontsize=10)
    recessive_grid(right, axis="x")

    fig.suptitle(f"{region}: 高度ごとの答え", y=0.99)
    fig.tight_layout()
    return fig


def fig_by_season(
    by_season: pd.DataFrame, region: str, *, skill_max: float | None = None
) -> Figure:
    """Does the answer depend on the season? More than on anything else.

    ``skill_max`` fixes the left panel's axis in percent, for the same reason as
    :func:`fig_by_level`. Here the gap is wider still -- Wakayama's autumn
    reaches 34 % and Hokkaido's best season 5 % -- so an auto-scaled axis
    would be actively misleading.
    """
    d = by_season
    y = np.arange(len(d))
    fig = Figure(figsize=(9.5, 4.0))
    left, right = fig.subplots(1, 2, sharey=True)

    left.barh(y, 100 * d["skill"], color=CMAP_SPEED(0.6), height=0.6)
    left.set_yticks(y)
    left.set_yticklabels(d["season"])
    left.set_xlabel("季節の中での誤差の削減 [%]")
    left.set_title("その季節の中で、時期を知る価値", fontsize=10)
    if skill_max is not None:
        left.set_xlim(0, skill_max)
    recessive_grid(left, axis="x")

    for i, (_, row) in enumerate(d.iterrows()):
        right.plot([row["resolved_lo_days"], row["resolved_hi_days"]], [i, i],
                   color=INK["muted"], linewidth=4, solid_capstyle="round")
        right.plot([row["best_days"]], [i], "o", color=CATEGORICAL[0], markersize=7)
    for days, colour in ((DAY, CATEGORICAL[3]), (WEEK_DAYS, CATEGORICAL[1]),
                         (MONTH_DAYS, CATEGORICAL[2])):
        right.axvline(days, color=colour, linewidth=1.2, linestyle=":")
    right.set_xscale("log")
    right.set_xticks([1, 3, 7, 15, 30, 91, 365])
    right.set_xticklabels(["1", "3", "7", "15", "30", "91", "365"])
    right.set_xlabel("支えられるビン幅 [日]")
    right.set_title("どこまで細かく見てよいか", fontsize=10)
    recessive_grid(right, axis="x")

    fig.suptitle(f"{region}: 季節ごとの答え", y=0.99)
    fig.tight_layout()
    return fig


def fig_variance_decomposition(variance: pd.DataFrame, region: str) -> Figure:
    """What fraction of the landing scatter a climatology can reach at all."""
    d = variance[variance["eta_squared"].notna()]
    y = np.arange(len(d))
    fig = Figure(figsize=(8.5, 3.8))
    ax = fig.subplots()
    between = 100 * d["eta_squared"]
    ax.barh(y, between, color=CMAP_SPEED(0.7), height=0.55, label="気候値が説明する分")
    ax.barh(y, 100 - between, left=between, color=INK["grid"], height=0.55,
            label="当日の天気（気候値には届かない分）")
    for i, val in enumerate(between):
        ax.text(val + 1.5, i, f"{val:.0f} %", va="center", fontsize=9,
                color=INK["primary"])
    ax.set_yticks(y)
    ax.set_yticklabels(d["grouping"])
    ax.set_xlim(0, 100)
    ax.set_xlabel("落下位置の分散に占める割合 [%]")
    ax.set_title(f"{region}: 気候値が説明できる範囲")
    # Below the axes: inside, it sits on top of the bar ends and their labels.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2,
              fontsize=8, frameon=False)
    recessive_grid(ax, axis="x")
    fig.tight_layout()
    return fig


def fig_region_comparison(curves: dict[str, pd.DataFrame]) -> Figure:
    """Both regions on one pair of axes, in absolute error and in skill.

    The two panels say different things. In kilometres Wakayama looks worse at
    the coarse end and better at the fine end; as a fraction of what there was
    to gain, the difference between the regions is larger still.
    """
    fig = Figure(figsize=(11, 4.8))
    left, right = fig.subplots(1, 2)
    for (region, d), colour in zip(curves.items(), CATEGORICAL, strict=False):
        d = d.sort_values("granularity_days")
        left.plot(d["granularity_days"], d["test_rmse_km"], color=colour,
                  linewidth=2.2, marker="o", markersize=4, label=region)
        best = d.loc[d["test_rmse_km"].idxmin()]
        left.plot([best["granularity_days"]], [best["test_rmse_km"]], "o", color=colour,
                  markersize=11, markerfacecolor="none", markeredgewidth=2)
        right.plot(d["granularity_days"], 100 * d["skill"], color=colour,
                   linewidth=2.2, marker="o", markersize=4, label=region)
    for ax, ylabel, title in (
        (left, "落下位置の誤差 RMSE [km]", "絶対誤差"),
        (right, "誤差の削減 [%]", "季節情報なしと比べた改善"),
    ):
        ax.set_xscale("log")
        ax.set_xticks([1, 3, 7, 15, 30, 91, 365])
        ax.set_xticklabels(["1", "3", "7", "15", "30", "91", "365"])
        ax.set_xlabel("ビン幅 [日]")
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=10, pad=16)
        recessive_grid(ax)
        # Grey, not categorical: the hues belong to the regions.
        for days, word in ((DAY, "1 日"), (WEEK_DAYS, "週"), (MONTH_DAYS, "月")):
            ax.axvline(days, color=INK["muted"], linewidth=1.0, linestyle=":")
            ax.text(days, 1.0, word, transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=8, color=INK["secondary"])
        ax.legend(fontsize=9)
    fig.suptitle(f"{len(curves)} 領域の比較: どの時間単位まで信号があるか", y=0.99)
    fig.tight_layout()
    return fig
