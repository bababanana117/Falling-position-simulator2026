"""Figures for the day-to-day variability and the simulator's fidelity.

Two questions, and each gets figures that answer it directly rather than
figures that show the data and leave the reading to the reader.

*Does the wind change faster in some seasons?* A curve of change against lag,
one line per season. The seasons separate or they do not, and the figure is
readable at a glance either way.

*Which season does the simulation match best?* Two numbers per season that
disagree -- absolute error in kilometres and error as a share of the flight --
so they are drawn side by side rather than combined into one score. Picking one
of them would be a judgement disguised as a measurement.

Season keeps the same colour in every figure here, assigned by slot from the
shared categorical order and never cycled, so a reader who learns the colours
once can read the rest without checking the legend.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from ..timebins import SEASON_ORDER
from .style import CATEGORICAL, INK, recessive_grid

__all__ = [
    "SEASON_COLOR",
    "fig_change_curve",
    "fig_decorrelation",
    "fig_direction_change",
    "fig_error_breakdown",
    "fig_slip_curve",
    "fig_trajectory_map",
    "fig_variance_split",
]

#: Fixed by slot: winter, spring, summer, autumn. Never cycled, never reordered.
SEASON_COLOR = dict(zip(SEASON_ORDER, CATEGORICAL, strict=True))

#: Order the pressure levels top-of-atmosphere first, the way a profile is read.
LEVEL_ORDER = (10.0, 30.0, 100.0, 200.0, 500.0, 850.0)

VARIANT_COLOR = {
    "time_frozen": CATEGORICAL[0],
    "place_frozen": CATEGORICAL[1],
    "both_frozen": INK["primary"],
}
VARIANT_LABEL = {
    "time_frozen": "時刻のみ固定",
    "place_frozen": "地点のみ固定",
    "both_frozen": "両方固定（現行）",
}


def _lag_axis(ax, lags) -> None:
    """A log lag axis labelled in the units people think in.

    The lags span six hours to twenty days. On a linear axis everything shorter
    than three days piles up against the left edge, and that is the part where
    the seasons differ most.
    """
    ax.set_xscale("log")
    ticks = [6, 12, 24, 48, 72, 120, 240, 480]
    ticks = [t for t in ticks if min(lags) <= t <= max(lags)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t}h" if t < 48 else f"{t // 24}日" for t in ticks])
    ax.set_xlabel("遅れ")
    recessive_grid(ax)


def fig_change_curve(lag_wind: pd.DataFrame, region: str) -> Figure:
    """How far the wind vector moves in a given time, by season and level.

    The quantity is the length of ``V(t+L) - V(t)``, not the change in speed. A
    wind that holds its strength and swings ninety degrees has changed
    completely, and a figure built on speed alone would show that as a flat line.
    """
    levels = [p for p in LEVEL_ORDER if p in set(lag_wind["plevel"])]
    fig, axes = _grid(len(levels), region, "風の変化量 |V(t+L) − V(t)|")
    for ax, level in zip(axes, levels, strict=False):
        sub = lag_wind[lag_wind["plevel"] == level]
        for season in SEASON_ORDER:
            s = sub[sub["season"] == season].sort_values("lag_hours")
            if s.empty:
                continue
            ax.plot(s["lag_hours"], s["median"], color=SEASON_COLOR[season],
                    linewidth=2.0, label=season, zorder=3)
            ax.fill_between(s["lag_hours"], s["median"], s["p90"],
                            color=SEASON_COLOR[season], alpha=0.08, linewidth=0,
                            zorder=2)
        _lag_axis(ax, lag_wind["lag_hours"])
        ax.set_title(f"{level:g} hPa", fontsize=10, color=INK["secondary"])
        ax.set_ylabel("m/s")
    _shared_legend(fig, axes, "帯は中央値から p90 まで")
    return fig


def fig_decorrelation(decorrelation: pd.DataFrame, region: str) -> Figure:
    """How long the wind keeps its memory: the 1/e crossing, by season and level.

    One bar per season at each level. A missing bar means the correlation had not
    fallen through ``1/e`` within the longest lag looked at -- twenty days -- and
    that absence is itself the finding, so it is labelled rather than left blank.
    """
    fig = Figure(figsize=(8.0, 4.6), dpi=160)
    ax = fig.add_subplot(111)
    levels = [p for p in LEVEL_ORDER if p in set(decorrelation["plevel"])]
    width = 0.8 / len(SEASON_ORDER)
    base = np.arange(len(levels))

    for i, season in enumerate(SEASON_ORDER):
        sub = decorrelation[decorrelation["season"] == season].set_index("plevel")
        days = [
            float(sub.loc[p, "decorrelation_days"]) if p in sub.index else np.nan
            for p in levels
        ]
        x = base + (i - (len(SEASON_ORDER) - 1) / 2) * width
        ax.bar(x, np.nan_to_num(days), width=width * 0.92,
               color=SEASON_COLOR[season], label=season, zorder=3)
        for xi, d in zip(x, days, strict=True):
            if not np.isfinite(d):
                ax.annotate("20日超", xy=(xi, 0.5), rotation=90, fontsize=8.5,
                            ha="center", va="bottom", fontweight="bold",
                            color=SEASON_COLOR[season])

    ax.set_xticks(base)
    ax.set_xticklabels([f"{p:g}" for p in levels])
    ax.set_xlabel("気圧面 (hPa)")
    ax.set_ylabel("相関が 1/e を切るまで (日)")
    ax.set_title(f"{region}: 風が入れ替わるのにかかる時間", color=INK["primary"], pad=28)
    recessive_grid(ax, axis="y")
    # Above the axes: the tallest bars reach the top right, where a legend
    # inside would sit on top of the summer stratospheric result.
    ax.legend(frameon=False, ncol=4, fontsize=9, loc="lower center",
              bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    return fig


def fig_direction_change(direction: pd.DataFrame, region: str) -> Figure:
    """Day-to-day swing in the daily-mean wind direction, by season and level.

    Read alongside the decorrelation figure, which often points the other way:
    a season whose *anomalies* persist can still have a direction that wanders,
    because when the mean wind is weak a small anomaly turns it a long way.
    """
    fig = Figure(figsize=(8.0, 4.6), dpi=160)
    ax = fig.add_subplot(111)
    levels = [p for p in LEVEL_ORDER if p in set(direction["plevel"])]
    for season in SEASON_ORDER:
        sub = direction[direction["season"] == season].set_index("plevel")
        med = [float(sub.loc[p, "median"]) if p in sub.index else np.nan for p in levels]
        p90 = [float(sub.loc[p, "p90"]) if p in sub.index else np.nan for p in levels]
        ax.plot(med, levels, "o-", color=SEASON_COLOR[season], linewidth=2.0,
                markersize=5, label=season, zorder=3)
        ax.fill_betweenx(levels, med, p90, color=SEASON_COLOR[season], alpha=0.12,
                         linewidth=0, zorder=2)
    ax.set_yscale("log")
    ax.invert_yaxis()
    ax.set_yticks(levels)
    ax.set_yticklabels([f"{p:g}" for p in levels])
    ax.set_ylabel("気圧面 (hPa)")
    ax.set_xlabel("日平均風向の前日差 (度)")
    ax.set_title(f"{region}: 風向は日ごとにどれだけ振れるか", color=INK["primary"])
    recessive_grid(ax)
    ax.legend(frameon=False, fontsize=9)
    fig.text(0.99, 0.01, "帯は中央値から p90 まで", ha="right", va="bottom",
             fontsize=8, color=INK["muted"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def fig_slip_curve(slip: pd.DataFrame, region: str) -> Figure:
    """How far the predicted landing point moves if the launch slips.

    This is not an error in the simulator -- it would have been right about both
    launches. It is how much slack a schedule needs, which is a separate thing
    the same data answers.
    """
    fig = Figure(figsize=(7.2, 4.4), dpi=160)
    ax = fig.add_subplot(111)
    for season in SEASON_ORDER:
        s = slip[slip["season"] == season].sort_values("lag_hours")
        if s.empty:
            continue
        ax.plot(s["lag_hours"], s["median"], "o-", color=SEASON_COLOR[season],
                linewidth=2.0, markersize=4, label=season, zorder=3)
        ax.fill_between(s["lag_hours"], s["median"], s["p90"],
                        color=SEASON_COLOR[season], alpha=0.12, linewidth=0, zorder=2)
    _lag_axis(ax, slip["lag_hours"])
    ax.set_ylabel("落下点の移動 (km)")
    ax.set_title(f"{region}: 打ち上げが遅れると落下点はどれだけ動くか",
                 color=INK["primary"])
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.text(0.99, 0.01, "帯は中央値から p90 まで", ha="right", va="bottom",
             fontsize=8, color=INK["muted"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def fig_error_breakdown(error: pd.DataFrame, region: str) -> Figure:
    """The simulator's approximation error: absolute and relative, side by side.

    Two panels rather than one. Winter flies six times as far as summer, so the
    absolute error is almost bound to be largest in winter whatever the
    atmosphere is doing; the share of the flight is the figure that says whether
    the prediction is *proportionally* trustworthy. Combining them into a single
    score would be choosing an answer rather than reporting one.
    """
    fig = Figure(figsize=(9.4, 4.4), dpi=160)
    left, right = fig.subplots(1, 2)
    seasons = [s for s in SEASON_ORDER if s in set(error["season"])]
    variants = [v for v in ("time_frozen", "place_frozen", "both_frozen")
                if v in set(error["variant"])]
    base = np.arange(len(seasons))
    width = 0.8 / max(len(variants), 1)

    for i, variant in enumerate(variants):
        sub = error[error["variant"] == variant].set_index("season")
        x = base + (i - (len(variants) - 1) / 2) * width
        med = [float(sub.loc[s, "median_km"]) for s in seasons]
        p90 = [float(sub.loc[s, "p90_km"]) for s in seasons]
        rel = [100 * float(sub.loc[s, "relative_median"]) for s in seasons]
        rel90 = [100 * float(sub.loc[s, "relative_p90"]) for s in seasons]
        for ax, low, high in ((left, med, p90), (right, rel, rel90)):
            ax.bar(x, low, width=width * 0.9, color=VARIANT_COLOR[variant],
                   label=VARIANT_LABEL[variant] if ax is left else None, zorder=3)
            ax.vlines(x, low, high, color=INK["surface"], linewidth=1.4, zorder=4)
            ax.vlines(x, low, high, color=VARIANT_COLOR[variant], linewidth=0.9,
                      zorder=5, alpha=0.75)

    for ax, label in ((left, "着地点のずれ (km)"), (right, "飛行距離に対する割合 (%)")):
        ax.set_xticks(base)
        ax.set_xticklabels([s.split(" ")[0] for s in seasons])
        ax.set_ylabel(label)
        recessive_grid(ax, axis="y")
    handles, labels = left.get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, ncol=3,
               loc="lower center", bbox_to_anchor=(0.5, 0.0))
    fig.suptitle(
        f"{region}: 風を固定したことによる誤差（棒は中央値、細線は p90 まで）",
        color=INK["primary"], fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    return fig


def fig_variance_split(variance: pd.DataFrame, region: str) -> Figure:
    """Where the wind's variance lives: within a day, day to day, season to season.

    Only the seasonal slice is what a climatology can predict. Seeing how thin
    that slice is next to the day-to-day one is the whole argument for why a
    half-by-half table is a planning aid and not a forecast.
    """
    fig = Figure(figsize=(7.2, 3.8), dpi=160)
    ax = fig.add_subplot(111)
    overall = variance[variance["scope"] == "全体"]
    if overall.empty:
        return fig
    row = overall.iloc[0]
    parts = [
        ("季節（気候値が説明できる分）", float(row["seasonal"]), CATEGORICAL[2]),
        ("日々（季節内の天気）", float(row["day_to_day"]), CATEGORICAL[1]),
        ("日内（日変化）", float(row["within_day"]), CATEGORICAL[0]),
    ]
    total = sum(p[1] for p in parts)
    x = 0.0
    for label, value, colour in parts:
        ax.barh(0, value, left=x, height=0.55, color=colour, zorder=3)
        text = f"{label}\n{100 * value / total:.0f}%"
        if value / total > 0.2:
            ax.annotate(text, xy=(x + value / 2, 0), ha="center", va="center",
                        fontsize=9, color=INK["surface"], zorder=4)
        else:
            # Too thin to hold its label: write it above the bar, flush with
            # whichever end of the bar keeps it inside the axes.
            first = x == 0.0
            ax.annotate(text, xy=(x if first else x + value, 0.3),
                        ha="left" if first else "right", va="bottom",
                        fontsize=9, color=INK["primary"], zorder=4)
        x += value
    ax.set_xlim(0, total)
    ax.set_ylim(-0.5, 0.5)
    ax.set_yticks([])
    ax.set_xlabel("分散 (m²/s²)")
    ax.set_title(f"{region}: 風の分散はどこにあるか", color=INK["primary"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


def fig_trajectory_map(
    tracks: dict[str, tuple[np.ndarray, np.ndarray]],
    launch: tuple[float, float],
    region: str,
    subtitle: str,
    *,
    margin_deg: float = 0.8,
) -> Figure:
    """One flight drawn four ways: the whole track, and the landing points close up.

    A single case, not a statistic. The tables say how large the error usually
    is; this says what it looks like.

    Two panels are needed because the two scales are three hundred kilometres
    apart. On a map wide enough to hold a winter flight, a five-kilometre
    difference between the variants is a fraction of the line width, and the
    figure would show four tracks lying exactly on top of each other -- which
    reads as "no difference" rather than "the difference is small". The right
    panel is the same landing points at a scale where the difference is the
    whole picture.
    """
    from ..regions import BBox  # noqa: PLC0415
    from .coast import draw_coastline, set_geographic_aspect  # noqa: PLC0415

    fig = Figure(figsize=(10.4, 4.8), dpi=160)
    wide, zoom = fig.subplots(1, 2, width_ratios=(1.55, 1.0))

    lons = np.concatenate([lo for lo, _ in tracks.values()])
    lats = np.concatenate([la for _, la in tracks.values()])
    bbox = BBox(
        south=float(lats.min()) - margin_deg,
        north=float(lats.max()) + margin_deg,
        west=float(lons.min()) - margin_deg,
        east=float(lons.max()) + margin_deg,
    )
    draw_coastline(wide, bbox, fill=True)

    styles = {
        "reference": (INK["primary"], "-", 2.2, "基準（固定なし）"),
        "time_frozen": (CATEGORICAL[0], "--", 1.6, "時刻のみ固定"),
        "place_frozen": (CATEGORICAL[1], "--", 1.6, "地点のみ固定"),
        "both_frozen": (CATEGORICAL[3], "-", 1.8, "両方固定（現行）"),
    }
    for ax in (wide, zoom):
        for name, (lon, lat) in tracks.items():
            colour, dash, lw, label = styles[name]
            ax.plot(lon, lat, color=colour, linestyle=dash, linewidth=lw,
                    label=label if ax is wide else None, zorder=6)
            ax.plot(lon[-1], lat[-1], "o", color=colour, markersize=8,
                    markeredgecolor=INK["surface"], markeredgewidth=1.2, zorder=7)

    wide.plot(launch[1], launch[0], "*", color=INK["primary"], markersize=15,
              markeredgecolor=INK["surface"], markeredgewidth=1.0, zorder=8)
    wide.annotate("打ち上げ", xy=(launch[1], launch[0]), xytext=(9, 5),
                  textcoords="offset points", fontsize=9, color=INK["primary"],
                  bbox={"facecolor": INK["surface"], "edgecolor": "none",
                        "pad": 1.5, "alpha": 0.85})
    wide.set_xlim(bbox.west, bbox.east)
    wide.set_ylim(bbox.south, bbox.north)
    set_geographic_aspect(wide, launch[0])
    wide.set_xlabel("経度 [度]")
    wide.set_ylabel("緯度 [度]")
    wide.set_title("飛行経路の全体", fontsize=10, color=INK["secondary"])
    recessive_grid(wide)

    # The landing cluster, with a scale bar so the zoom level is readable.
    ends_lon = np.array([lo[-1] for lo, _ in tracks.values()])
    ends_lat = np.array([la[-1] for _, la in tracks.values()])
    span = max(np.ptp(ends_lon), np.ptp(ends_lat), 0.02) * 1.9
    cx, cy = ends_lon.mean(), ends_lat.mean()
    zoom.set_xlim(cx - span, cx + span)
    zoom.set_ylim(cy - span, cy + span)
    set_geographic_aspect(zoom, launch[0])
    km_per_deg_lon = 111.195 * np.cos(np.radians(launch[0]))
    bar_km = max(round(span * km_per_deg_lon / 2), 1)
    bar_deg = bar_km / km_per_deg_lon
    # A track that loops back can pass through any corner, so put the bar in
    # whichever corner the tracks leave empty.
    pts_lon = np.concatenate([lo for lo, _ in tracks.values()])
    pts_lat = np.concatenate([la for _, la in tracks.values()])

    def _crowding(x0: float, y0: float) -> int:
        inside = ((pts_lon > x0 - 0.05 * span) & (pts_lon < x0 + bar_deg + 0.05 * span)
                  & (pts_lat > y0 - 0.08 * span) & (pts_lat < y0 + 0.15 * span))
        return int(inside.sum())

    corners = [(cx - span * 0.85, cy - span * 0.82), (cx + span * 0.85 - bar_deg, cy - span * 0.82),
               (cx - span * 0.85, cy + span * 0.75), (cx + span * 0.85 - bar_deg, cy + span * 0.75)]
    x0, y = min(corners, key=lambda c: _crowding(*c))
    zoom.plot([x0, x0 + bar_deg], [y, y],
              color=INK["primary"], linewidth=2.5, solid_capstyle="butt", zorder=9)
    zoom.annotate(f"{bar_km:g} km", xy=(x0 + bar_deg / 2, y),
                  xytext=(0, 4), textcoords="offset points", ha="center",
                  fontsize=9, color=INK["primary"])
    zoom.set_xticks([])
    zoom.set_yticks([])
    zoom.set_title("着地点の拡大", fontsize=10, color=INK["secondary"])

    handles, labels = wide.get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, ncol=4,
               loc="lower center", bbox_to_anchor=(0.5, 0.0))
    fig.suptitle(f"{region}: {subtitle}", color=INK["primary"], fontsize=11)
    fig.tight_layout(rect=(0, 0.11, 1, 0.94))
    return fig


def _grid(n: int, region: str, title: str) -> tuple[Figure, list]:
    cols = 3
    rows = int(np.ceil(n / cols))
    fig = Figure(figsize=(3.4 * cols, 2.7 * rows + 0.8), dpi=160)
    axes = [fig.add_subplot(rows, cols, i + 1) for i in range(n)]
    fig.suptitle(f"{region}: {title}", color=INK["primary"], fontsize=11)
    return fig, axes


def _shared_legend(fig: Figure, axes: list, note: str) -> None:
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, ncol=4,
               loc="lower center", bbox_to_anchor=(0.5, 0.0))
    fig.text(0.99, 0.005, note, ha="right", va="bottom", fontsize=8,
             color=INK["muted"])
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
