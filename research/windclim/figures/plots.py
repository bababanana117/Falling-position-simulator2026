"""The figures.

Two rules run through all of them and both exist to stop the plots from lying.

**Direction gets a cyclic colormap.** A sequential ramp on a circular quantity
puts a false cliff between 359 deg and 1 deg, which are the same wind.

**Direction is masked where the constancy is low.** Drawing a confident arrow at a
place and altitude where the wind reverses from half to half is the most
misleading thing this pipeline could produce, so below a constancy of 0.3 the
direction is hatched out and the caption says so.

Figure F0 is deliberately first: it plots the sample count per bin, and if the
280 / 400 / 292 / 360 pattern is not there then something upstream is broken and
none of the rest is worth looking at.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Patch

from ..stats.aggregate import ROSE_SPEED_EDGES
from ..stats.spatial import area_mean, spatial_range
from .coast import draw_coastline, set_geographic_aspect
from .style import (
    CATEGORICAL,
    CMAP_CONSTANCY,
    CMAP_DIFF,
    CMAP_DIRECTION,
    CMAP_SPEED,
    CONSTANCY_MASK,
    INK,
    recessive_grid,
)

__all__ = [
    "MONTH_LABELS",
    "REFERENCE_ALT_KM",
    "fig_alt_half_constancy",
    "fig_alt_half_speed",
    "fig_diurnal",
    "fig_hodograph",
    "fig_isa_check",
    "fig_map_vectors",
    "fig_profiles_by_month",
    "fig_region_comparison",
    "fig_sample_counts",
    "fig_shear",
    "fig_spatial_spread",
    "fig_wind_roses",
    "save",
]

MONTH_LABELS = ("1月", "2月", "3月", "4月", "5月", "6月",
                "7月", "8月", "9月", "10月", "11月", "12月")

#: Altitudes the report keeps coming back to: boundary layer, mid-troposphere,
#: the jet, the tropopause, float and burst.
REFERENCE_ALT_KM = (2.0, 5.0, 10.0, 16.0, 20.0, 25.0, 30.0)

ALT_LIMIT_KM = 40.0


# --- helpers -----------------------------------------------------------------


def _alt_axis(ds: xr.Dataset) -> np.ndarray:
    """One altitude per level: the mean over every bin, in km.

    The true altitude of a pressure surface moves with the season by a few hundred
    metres. Using one axis for the whole figure keeps the picture readable; the
    exact per-bin altitude is in the NetCDF for anyone who needs it.
    """
    alt = area_mean(ds, "alt_geom_mean_km")
    return np.nanmean(alt.values.reshape(-1, ds.sizes["level"]), axis=0)


def _flat_bins(ds: xr.Dataset, name: str) -> np.ndarray:
    """``(48, level)`` -- every month-half bin in calendar order."""
    da = area_mean(ds, name)
    return da.transpose("month", "bin", "level").values.reshape(-1, ds.sizes["level"])


def _bin_labels(ds: xr.Dataset) -> list[str]:
    """Bin labels as recorded on the dataset, falling back to the short form."""
    labels = ds.attrs.get("bin_labels")
    if labels is None:
        return [f"B{i}" for i in range(1, ds.sizes["bin"] + 1)]
    return [str(x) for x in labels]


def _bin_short(ds: xr.Dataset) -> list[str]:
    short = ds.attrs.get("bin_short")
    if short is None:
        return [lab.split(" ")[0] for lab in _bin_labels(ds)]
    return [str(x) for x in short]


def _bin_words(ds: xr.Dataset) -> tuple[str, str]:
    """What one bin is called in prose, and the matching x-axis label.

    The same drawing code serves the half-month product and the older 7-day
    one. The wording used to be fixed to "week", so the half-month figures in
    the main chapters were labelled as weekly although they are not.
    """
    if ds.sizes["bin"] == 2:
        return "半月", "月（各月 = 前半・後半）"
    return "週", "月と週"


def _half_axis(ds: xr.Dataset, ax) -> None:
    n_bin = ds.sizes["bin"]
    ax.set_xlim(-0.5, ds.sizes["month"] * n_bin - 0.5)
    for m in range(1, ds.sizes["month"]):
        # A month separator must not be the same colour as a masked cell.
        ax.axvline(m * n_bin - 0.5, color=INK["primary"], linewidth=0.8,
                   alpha=0.45, zorder=3)
    ax.set_xticks([m * n_bin + (n_bin - 1) / 2 for m in range(ds.sizes["month"])])
    ax.set_xticklabels(MONTH_LABELS[: ds.sizes["month"]])
    ax.tick_params(axis="x", length=0)


def _altitude_axis(ax, alt_km: np.ndarray) -> None:
    ax.set_ylim(0, min(ALT_LIMIT_KM, float(np.nanmax(alt_km))))
    ax.set_ylabel("幾何高度 [km]")
    ax.set_yticks([0, 5, 10, 16, 20, 25, 30, 35, 40])


def save(fig: Figure, out_dir: Path, figid: str, name: str) -> tuple[Path, Path]:
    """Write PNG (for looking at) and PDF (for the report) and return both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{figid}_{name}.png"
    pdf = out_dir / f"{figid}_{name}.pdf"
    fig.savefig(png)
    fig.savefig(pdf)
    return png, pdf


def write_manifest(out_dir: Path, entries: list[dict]) -> Path:
    path = Path(out_dir) / "manifest.json"
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False, default=str))
    return path


# --- F0: the sanity gate -----------------------------------------------------


def fig_sample_counts(ds: xr.Dataset, region: str) -> Figure:
    """Analyses per (month, half). Check this before believing anything else.

    Weeks 1-3 are seven days; half 4 runs to the end of the month, so it is longer
    and holds proportionally more analyses. February's half 4 is the short one and
    it also varies with leap years. Anything that does not follow that pattern is
    missing data.
    """
    n = ds["n"].isel(level=0, lat=0, lon=0).transpose("bin", "month").values
    fig = Figure(figsize=(9, 3.0))
    ax = fig.subplots()
    im = ax.imshow(n, cmap=CMAP_SPEED, aspect="auto", origin="lower")
    for wi in range(n.shape[0]):
        for mi in range(n.shape[1]):
            value = int(n[wi, mi])
            ax.text(
                mi, wi, f"{value}",
                ha="center", va="center", fontsize=7,
                color="#ffffff" if value > n.max() * 0.6 else INK["primary"],
            )
    ax.set_xticks(range(n.shape[1]))
    ax.set_xticklabels(MONTH_LABELS[: n.shape[1]])
    ax.set_yticks(range(n.shape[0]))
    ax.set_yticklabels(_bin_short(ds)[: n.shape[0]])
    ax.set_title(f"{region}: 各ビンの解析数")
    fig.colorbar(im, ax=ax, label="解析数", pad=0.02)
    fig.tight_layout()
    return fig


# --- F1 / F2: half x altitude ------------------------------------------------


def _half_altitude_panel(ax, ds, values, alt_km, *, cmap, vmin, vmax, label, mask=None):
    grid = values.T                                  # (level, bin)
    if mask is not None:
        grid = np.where(mask.T, np.nan, grid)
    x = np.arange(grid.shape[1] + 1) - 0.5
    edges = np.concatenate([[0.0], (alt_km[:-1] + alt_km[1:]) / 2.0, [alt_km[-1]]])
    mesh = ax.pcolormesh(x, edges, grid, cmap=cmap, vmin=vmin, vmax=vmax, shading="flat")
    _half_axis(ds, ax)
    _altitude_axis(ax, alt_km)
    return mesh


def fig_alt_half_speed(ds: xr.Dataset, region: str) -> Figure:
    """The headline figure: wind speed and direction against altitude and half."""
    alt = _alt_axis(ds)
    order = np.argsort(alt)
    speed = _flat_bins(ds, "speed_mean")[:, order]
    direction = _flat_bins(ds, "dir_vector_mean")[:, order]
    constancy = _flat_bins(ds, "constancy")[:, order]

    fig = Figure(figsize=(11, 7))
    top, bottom = fig.subplots(2, 1, sharex=True)

    mesh = _half_altitude_panel(
        top, ds, speed, alt[order], cmap=CMAP_SPEED, vmin=0,
        vmax=float(np.nanpercentile(speed, 99)), label="風速",
    )
    unit, xlabel = _bin_words(ds)
    top.set_title(f"{region}: {unit}別・高度別の平均風速と風向（{ds.attrs.get('period', '')}）")
    fig.colorbar(mesh, ax=top, label="平均風速 [m/s]", pad=0.01)

    masked = constancy < CONSTANCY_MASK
    mesh2 = _half_altitude_panel(
        bottom, ds, direction, alt[order], cmap=CMAP_DIRECTION, vmin=0, vmax=360,
        label="風向", mask=masked,
    )
    cb = fig.colorbar(mesh2, ax=bottom, label="風向（吹いてくる向き）[度]", pad=0.01,
                      ticks=[0, 90, 180, 270, 360])
    cb.ax.set_yticklabels(["北", "東", "南", "西", "北"])
    bottom.set_xlabel(xlabel)
    bottom.text(
        0.0, -0.22,
        f"灰色は定常度が {CONSTANCY_MASK} 未満で塗りつぶしを外した領域。"
        f"その{unit}は風向が定まっておらず、平均風向を描くと誤解を招く。",
        transform=bottom.transAxes, fontsize=8, color=INK["secondary"],
    )
    fig.tight_layout()
    return fig


def fig_alt_half_constancy(ds: xr.Dataset, region: str) -> Figure:
    """Where and when the wind direction is steady enough to plan around."""
    alt = _alt_axis(ds)
    order = np.argsort(alt)
    constancy = _flat_bins(ds, "constancy")[:, order]

    fig = Figure(figsize=(11, 4.2))
    ax = fig.subplots()
    mesh = _half_altitude_panel(
        ax, ds, constancy, alt[order], cmap=CMAP_CONSTANCY, vmin=0, vmax=1, label="定常度"
    )
    ax.set_title(f"{region}: 定常度（1 = いつも同じ向き、0 = 向きが定まらない）")
    ax.set_xlabel(_bin_words(ds)[1])
    fig.colorbar(mesh, ax=ax, label="定常度", pad=0.01)
    fig.tight_layout()
    return fig


# --- F3: profiles ------------------------------------------------------------


def fig_profiles_by_month(ds: xr.Dataset, region: str) -> Figure:
    """Twelve panels: how the speed profile evolves through the year."""
    alt = _alt_axis(ds)
    order = np.argsort(alt)
    p50 = area_mean(ds, "speed_p50").transpose("month", "bin", "level").values[..., order]
    p10 = area_mean(ds, "speed_p10").transpose("month", "bin", "level").values[..., order]
    p90 = area_mean(ds, "speed_p90").transpose("month", "bin", "level").values[..., order]
    y = alt[order]

    n_month = ds.sizes["month"]
    fig = Figure(figsize=(12, 9))
    axes = fig.subplots(3, 4, sharex=True, sharey=True).ravel()
    for mi in range(len(axes)):
        ax = axes[mi]
        if mi >= n_month:
            ax.set_visible(False)
            continue
        ax.fill_betweenx(
            y, np.nanmin(p10[mi], axis=0), np.nanmax(p90[mi], axis=0),
            color=INK["grid"], zorder=1, label="月内の p10-p90 の幅",
        )
        lines = []
        for wi in range(ds.sizes["bin"]):
            (ln,) = ax.plot(p50[mi, wi], y, color=CATEGORICAL[wi], linewidth=1.6, zorder=2)
            lines.append(ln)
        recessive_grid(ax)
        ax.set_title(MONTH_LABELS[mi], fontsize=10)
        ax.set_ylim(0, ALT_LIMIT_KM)
        if mi % 4 == 0:
            ax.set_ylabel("幾何高度 [km]")
        if mi >= n_month - 4:
            ax.set_xlabel("風速の中央値 [m/s]")

    handles = [
        Line2D([], [], color=CATEGORICAL[i], label=lab)
        for i, lab in enumerate(_bin_labels(ds))
    ]
    handles.append(Patch(color=INK["grid"], label="月内の p10-p90 の幅"))
    fig.legend(handles=handles, loc="lower center", ncols=5, frameon=False)
    fig.suptitle(f"{region}: 月ごとの高度別 風速プロファイル", y=0.995)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


# --- F4: hodograph -----------------------------------------------------------


def fig_hodograph(ds: xr.Dataset, region: str, month: int, bin_index: int) -> Figure:
    """The mean wind vector from the ground to 40 km, drawn as a path.

    Every point is one pressure level; the colour is its altitude. The shape of
    the path is the thing a trajectory person wants: how far the wind turns as the
    balloon climbs, and where it turns fastest. The ellipses show the spread at a
    few levels -- with the caveat that they assume a bivariate-normal scatter,
    which the reversal seasons violate.
    """
    cell = ds.sel(month=month, bin=bin_index)
    u = area_mean(cell, "u_mean").values
    v = area_mean(cell, "v_mean").values
    alt = area_mean(cell, "alt_geom_mean_km").values
    keep = np.isfinite(u) & np.isfinite(v) & np.isfinite(alt) & (alt <= ALT_LIMIT_KM)
    u, v, alt = u[keep], v[keep], alt[keep]
    order = np.argsort(alt)
    u, v, alt = u[order], v[order], alt[order]

    fig = Figure(figsize=(7.2, 5.0))
    ax = fig.subplots()
    ax.plot(u, v, color=INK["muted"], linewidth=1.0, zorder=1)
    sc = ax.scatter(u, v, c=alt, cmap=CMAP_SPEED, s=26, zorder=3,
                    edgecolor=INK["surface"], linewidth=0.5)

    major = area_mean(cell, "ellipse_major").values[keep][order]
    minor = area_mean(cell, "ellipse_minor").values[keep][order]
    angle = area_mean(cell, "ellipse_angle_deg").values[keep][order]
    for target in REFERENCE_ALT_KM:
        idx = int(np.argmin(np.abs(alt - target)))
        if not np.isfinite(major[idx]):
            continue
        ax.add_patch(
            Ellipse(
                (u[idx], v[idx]), 2 * major[idx], 2 * minor[idx], angle=angle[idx],
                facecolor="none", edgecolor=INK["muted"], linewidth=0.8, zorder=2,
            )
        )
        ax.annotate(f"{target:.0f} km", (u[idx], v[idx]), textcoords="offset points",
                    xytext=(6, 6), fontsize=7, color=INK["secondary"])

    # Equal aspect is non-negotiable on a hodograph -- the angle *is* the wind
    # direction, so distorting it distorts the message. But the axes need not be
    # square: over Japan the wind is overwhelmingly zonal, and a square frame
    # would spend most of the page on empty sky. The vertical range is kept to at
    # least 45 % of the horizontal so the flatness still reads as a fact about
    # the wind rather than as a cropped plot.
    xlim = float(np.nanmax(np.abs(u))) * 1.25 + 1.0
    ylim = max(float(np.nanmax(np.abs(v))) * 1.35 + 1.0, xlim * 0.45)
    ax.set_xlim(-xlim, xlim)
    ax.set_ylim(-ylim, ylim)
    ax.set_aspect("equal")
    ax.axhline(0, color=INK["grid"], linewidth=0.8, zorder=0)
    ax.axvline(0, color=INK["grid"], linewidth=0.8, zorder=0)
    ax.set_xlabel("東向き成分 u [m/s]")
    ax.set_ylabel("北向き成分 v [m/s]")
    ax.set_title(
        f"{region}: {MONTH_LABELS[month - 1]} {_bin_labels(ds)[bin_index - 1]} のホドグラフ"
    )
    fig.colorbar(sc, ax=ax, label="幾何高度 [km]", pad=0.02)
    fig.tight_layout()
    return fig


# --- F5: maps ----------------------------------------------------------------


def fig_map_vectors(ds: xr.Dataset, region: str, month: int, bin_index: int,
                    levels_hpa: tuple[float, ...] = (850.0, 500.0, 200.0, 50.0, 10.0),
                    *, label: str | None = None) -> Figure:
    """Where the wind differs across the region, at five levels.

    Every panel shares one colour scale *and* one arrow scale. Letting the arrows
    autoscale per panel would be the worse kind of wrong: the surface panel would
    grow arrows as long as the jet's, and the reader would take the two winds for
    comparable.
    """
    from ..regions import REGIONS

    box = REGIONS[region]
    label = label or region
    cell = ds.sel(month=month, bin=bin_index)
    lon = cell["lon"].values
    lat = cell["lat"].values

    fig = Figure(figsize=(4.0 * len(levels_hpa), 4.6))
    axes = fig.subplots(1, len(levels_hpa), sharey=True)
    axes = np.atleast_1d(axes)
    speed_max = float(np.nanpercentile(cell["speed_mean"].values, 99))
    # One arrow scale for every panel: the strongest wind spans about 1.5 cells.
    span = float(lon.max() - lon.min())
    quiver_scale = speed_max / max(span * 0.08, 1e-6)

    quiver = None
    for ax, level in zip(axes, levels_hpa, strict=True):
        at = cell.sel(level=level, method="nearest")
        mesh = ax.pcolormesh(lon, lat, at["speed_mean"].values, cmap=CMAP_SPEED,
                             vmin=0, vmax=speed_max, shading="nearest", zorder=1)
        step = max(1, len(lon) // 12)
        quiver = ax.quiver(
            lon[::step], lat[::step],
            at["u_mean"].values[::step, ::step], at["v_mean"].values[::step, ::step],
            color=INK["primary"], scale_units="xy", scale=quiver_scale,
            width=0.006, zorder=4,
        )
        draw_coastline(ax, box)
        set_geographic_aspect(ax, box.lat_mid)
        ax.set_xlim(lon.min(), lon.max())
        ax.set_ylim(lat.min(), lat.max())
        alt = float(np.nanmean(area_mean(cell, "alt_geom_mean_km").sel(
            level=level, method="nearest").values))
        ax.set_title(f"{float(at['level']):.0f} hPa（約 {alt:.0f} km）", fontsize=10)
        ax.set_xlabel("経度 [度]")
    axes[0].set_ylabel("緯度 [度]")
    if quiver is not None:
        ref = max(10.0, round(speed_max / 2 / 10) * 10)
        axes[-1].quiverkey(quiver, 0.82, -0.16, ref, f"{ref:.0f} m/s",
                           labelpos="E", coordinates="axes", fontproperties={"size": 8})
    fig.colorbar(mesh, ax=axes, label="平均風速 [m/s]", pad=0.01)
    fig.suptitle(f"{label}: {MONTH_LABELS[month - 1]} {_bin_labels(ds)[bin_index - 1]}"
        f" の平均風（矢印は全図同一縮尺）",
                 y=0.99)
    return fig


# --- F6: is one column enough? ----------------------------------------------


def fig_spatial_spread(ds: xr.Dataset, region: str) -> Figure:
    """How much the answer depends on where in the region you stand.

    If this is small, a single representative column describes the whole region
    and the site tables mean something. Where it is large, they do not.
    """
    alt = _alt_axis(ds)
    order = np.argsort(alt)
    spread = (
        spatial_range(ds, "speed_mean")
        .transpose("month", "bin", "level")
        .values.reshape(-1, ds.sizes["level"])[:, order]
    )
    fig = Figure(figsize=(11, 4.2))
    ax = fig.subplots()
    mesh = _half_altitude_panel(
        ax, ds, spread, alt[order], cmap=CMAP_SPEED, vmin=0,
        vmax=float(np.nanpercentile(spread, 99)), label="幅",
    )
    ax.set_title(f"{region}: 領域内での平均風速の幅（最大 − 最小）")
    ax.set_xlabel(_bin_words(ds)[1])
    fig.colorbar(mesh, ax=ax, label="領域内の風速差 [m/s]", pad=0.01)
    fig.tight_layout()
    return fig


# --- F7: wind roses ----------------------------------------------------------


def fig_wind_roses(ds: xr.Dataset, region: str, *, bin_index: int = 2,
                   months: tuple[int, ...] = (1, 4, 7, 10),
                   levels_hpa: tuple[float, ...] = (850.0, 500.0, 200.0, 30.0)) -> Figure:
    """The distribution behind the mean.

    A mean and an ellipse cannot show two lobes. In the stratosphere at the spring
    and autumn reversals there really are two, and the rose is the only display
    here that admits it.
    """
    counts = ds["rose_counts"]
    sector_deg = ds["sector_deg"].values
    width = np.radians(360.0 / len(sector_deg))
    edges = list(ROSE_SPEED_EDGES)

    fig = Figure(figsize=(3.2 * len(months), 3.5 * len(levels_hpa)))
    axes = fig.subplots(len(levels_hpa), len(months), subplot_kw={"projection": "polar"})
    axes = np.atleast_2d(axes)
    for li, level in enumerate(levels_hpa):
        row_max = 0.0
        for mi, month in enumerate(months):
            ax = axes[li, mi]
            block = counts.sel(month=month, bin=bin_index, level=level,
                               method="nearest").values.astype(float)
            total = block.sum()
            if total > 0:
                block = block / total * 100.0
            theta = np.radians(sector_deg)
            base = np.zeros_like(theta)
            for ci in range(block.shape[1]):
                hi = edges[ci + 1]
                label = f"{edges[ci]:.0f}-{hi:.0f}" if np.isfinite(hi) else f">{edges[ci]:.0f}"
                ax.bar(theta, block[:, ci], width=width, bottom=base,
                       color=CMAP_SPEED((ci + 1) / block.shape[1]),
                       edgecolor=INK["surface"], linewidth=0.5,
                       label=label if (li == 0 and mi == 0) else None)
                base = base + block[:, ci]
            row_max = max(row_max, float(base.max()))
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)
            ax.set_xticks(np.radians([0, 90, 180, 270]))
            ax.set_xticklabels(["北", "東", "南", "西"], fontsize=7)
            ax.tick_params(axis="y", labelsize=6)
            if li == 0:
                ax.set_title(MONTH_LABELS[month - 1], fontsize=10, pad=14)
            if mi == 0:
                ax.text(-0.35, 0.5, f"{level:.0f} hPa", transform=ax.transAxes,
                        rotation=90, va="center", fontsize=9, color=INK["secondary"])
        # One radial scale per altitude, so the seasons can be compared by eye.
        # Scales still differ between rows: at 200 hPa in January the wind sits in
        # a single sector, and forcing that onto the same axis as a scattered
        # boundary-layer rose would flatten every other panel to nothing.
        for mi in range(len(months)):
            axes[li, mi].set_ylim(0, max(row_max * 1.05, 1.0))

    lat = ds.attrs.get("rose_cell_lat")
    lon = ds.attrs.get("rose_cell_lon")
    where = "" if lat is None else f"、{lat:.2f}N {lon:.2f}E の格子点、頻度 %"
    fig.suptitle(
        f"{region}: 風配図（{_bin_labels(ds)[bin_index - 1]}{where}）",
        y=0.995,
    )
    fig.tight_layout(rect=(0.02, 0.05, 1, 0.99))
    return fig


# --- F8: the diurnal cycle ---------------------------------------------------


def fig_diurnal(ds: xr.Dataset, region: str) -> Figure:
    """03 JST minus 15 JST wind speed against altitude, by season.

    This is the evidence for marginalising over analysis hour: if the difference is
    small everywhere, the main product loses nothing by ignoring the hour. Note the
    axis scale before reading shape into the curves -- on this grid the differences
    turn out to be under about 1 m/s, which is small next to the day-to-day spread
    of tens of m/s. A 40 km reanalysis grid does not resolve a sea breeze, and what
    a sea breeze mostly changes is direction rather than speed.
    """
    if "hr_speed_mean" not in ds:
        raise KeyError("no by-hour product in this dataset; aggregate with by_hour=True")
    alt = area_mean(ds, "alt_geom_mean_km")
    hr = area_mean(ds, "hr_speed_mean")
    # hour index 3 is 18 UTC = 03 JST; index 1 is 06 UTC = 15 JST.
    diff = hr.isel(hour=3) - hr.isel(hour=1)

    seasons = {"冬 (12-2月)": (12, 1, 2), "春 (3-5月)": (3, 4, 5),
               "夏 (6-8月)": (6, 7, 8), "秋 (9-11月)": (9, 10, 11)}
    fig = Figure(figsize=(6.2, 5.4))
    ax = fig.subplots()
    lines, labels = [], []
    for (name, months), colour in zip(seasons.items(), CATEGORICAL, strict=True):
        months = [m for m in months if m in set(ds["month"].values.tolist())]
        if not months:
            continue
        d = diff.sel(month=months).mean(("month", "bin")).values
        y = (
            alt.sel(month=months, level=ds["level_low"].values)
            .mean(("month", "bin"))
            .values
        )
        order = np.argsort(y)
        (ln,) = ax.plot(d[order], y[order], color=colour, linewidth=1.8)
        lines.append(ln)
        labels.append(name)
    ax.axvline(0, color=INK["grid"], linewidth=1.0, zorder=0)
    recessive_grid(ax)
    ax.set_xlabel("03 JST − 15 JST の平均風速差 [m/s]")
    ax.set_ylabel("幾何高度 [km]")
    ax.set_title(f"{region}: 風速の日変化")
    if lines:
        # Legend only: the lines converge at the top of the profile, so end-labels
        # would pile up there. The per-level values are in the CSV tables.
        # Outside the axes: near the ground the four lines fan out to the
        # right, exactly where a legend inside would sit.
        ax.legend(lines, labels, loc="upper left", bbox_to_anchor=(1.01, 1.0),
                  frameon=False)
        biggest = float(np.nanmax(np.abs(np.asarray([ln.get_xdata() for ln in lines]))))
        ax.set_title(
            f"{region}: 風速の日変化（最大でも {biggest:.1f} m/s）"
        )
    fig.tight_layout()
    return fig


# --- F9: shear ---------------------------------------------------------------


def fig_shear(ds: xr.Dataset, region: str) -> Figure:
    """Vertical shear against altitude, one line per month.

    Shear is what actually spreads a landing ellipse: the payload crosses each
    sheared layer at a slightly different time and place on every flight.
    """
    alt = _alt_axis(ds)
    order = np.argsort(alt)
    shear = area_mean(ds, "shear_mag").mean("bin").values[:, order]

    fig = Figure(figsize=(6.6, 5.6))
    ax = fig.subplots()
    for mi in range(ds.sizes["month"]):
        frac = mi / max(ds.sizes["month"] - 1, 1)
        ax.plot(shear[mi], alt[order], color=CMAP_SPEED(0.15 + 0.8 * frac),
                linewidth=1.5, label=MONTH_LABELS[mi])
    recessive_grid(ax)
    ax.set_ylim(0, ALT_LIMIT_KM)
    ax.set_xlabel("鉛直シアー |dV/dz| [(m/s)/km]")
    ax.set_ylabel("幾何高度 [km]")
    ax.set_title(f"{region}: 月別の鉛直シアー")
    ax.legend(ncols=2, fontsize=7)
    fig.tight_layout()
    return fig


# --- F10: is the simulator's ISA assumption good enough? ---------------------


def fig_isa_check(ds: xr.Dataset, region: str) -> Figure:
    """JRA-3Q's real pressure-to-altitude relation against the ISA used in the app.

    ``backend/bfps/core/atmosphere.py`` converts pressure to altitude with the
    International Standard Atmosphere, which knows nothing about season, latitude
    or weather. This says how far off that is here, which is a direct check on the
    existing simulator rather than a new result.
    """
    from ..stats.altitude import isa_altitude_from_pressure

    levels = ds["level"].values
    isa_km = isa_altitude_from_pressure(levels) / 1000.0
    alt = area_mean(ds, "alt_geom_mean_km")

    fig = Figure(figsize=(10, 4.6))
    left, right = fig.subplots(1, 2)

    seasons = {"冬 (12-2月)": (12, 1, 2), "夏 (6-8月)": (6, 7, 8)}
    for (name, months), colour in zip(seasons.items(), CATEGORICAL[: len(seasons)], strict=True):
        months = [m for m in months if m in set(ds["month"].values.tolist())]
        if not months:
            continue
        real = alt.sel(month=months).mean(("month", "bin")).values
        left.plot(levels, real, color=colour, linewidth=1.8, label=f"JRA-3Q {name}")
        right.plot(levels, (real - isa_km) * 1000.0, color=colour, linewidth=1.8, label=name)

    left.plot(levels, isa_km, color=INK["muted"], linewidth=1.6, linestyle="--",
              label="ISA（既存実装）")
    for ax in (left, right):
        ax.set_xscale("log")
        ax.set_xlabel("気圧 [hPa]")
        ax.invert_xaxis()
        recessive_grid(ax)
    left.set_ylabel("幾何高度 [km]")
    left.set_title("気圧面の高度")
    left.legend(fontsize=8)
    right.axhline(0, color=INK["grid"], linewidth=1.0, zorder=0)
    right.set_ylabel("JRA-3Q − ISA [m]")
    right.set_title("ISA からのずれ")
    right.legend(fontsize=8)
    fig.suptitle(f"{region}: 気圧から高度への換算", y=0.99)
    fig.tight_layout()
    return fig


# --- F11: the two regions side by side --------------------------------------


def fig_region_comparison(ds_a: xr.Dataset, ds_b: xr.Dataset,
                          name_a: str, name_b: str) -> Figure:
    """Same scale for both regions, then their difference."""
    alt = _alt_axis(ds_a)
    order = np.argsort(alt)
    a = _flat_bins(ds_a, "speed_mean")[:, order]
    b = _flat_bins(ds_b, "speed_mean")[:, order]
    vmax = float(np.nanpercentile(np.concatenate([a, b]), 99))

    fig = Figure(figsize=(11, 10))
    ax1, ax2, ax3 = fig.subplots(3, 1, sharex=True)
    m1 = _half_altitude_panel(ax1, ds_a, a, alt[order], cmap=CMAP_SPEED,
                              vmin=0, vmax=vmax, label="")
    ax1.set_title(f"{name_a}: 平均風速")
    fig.colorbar(m1, ax=ax1, label="[m/s]", pad=0.01)

    m2 = _half_altitude_panel(ax2, ds_b, b, alt[order], cmap=CMAP_SPEED,
                              vmin=0, vmax=vmax, label="")
    ax2.set_title(f"{name_b}: 平均風速（同じスケール）")
    fig.colorbar(m2, ax=ax2, label="[m/s]", pad=0.01)

    diff = a - b
    lim = float(np.nanpercentile(np.abs(diff), 99))
    m3 = _half_altitude_panel(ax3, ds_a, diff, alt[order], cmap=CMAP_DIFF,
                              vmin=-lim, vmax=lim, label="")
    ax3.set_title(f"差（{name_a} − {name_b}）")
    ax3.set_xlabel(_bin_words(ds_a)[1])
    fig.colorbar(m3, ax=ax3, label="[m/s]", pad=0.01)
    fig.tight_layout()
    return fig
