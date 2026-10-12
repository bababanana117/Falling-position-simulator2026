"""Map figures.

Everything here is drawn on a real coastline so a reader can see *where* rather
than infer it from a latitude number. The coastline is the repository's own
``frontend/public/geo/land.json``, the same outline the web app draws, so a figure
in this report and the map in the app agree.

Projection: plate carree with the aspect corrected by ``1/cos(lat)``. Over a box
ten degrees wide that is honest to a few percent, and no projection choice
changes what the figures say about wind and drift.

The drift maps are the ones worth reading first. They answer the question the
project exists for -- launch here, in this half, and the payload lands *there* --
and they are drawn **to scale**: the arrow tip is the predicted landing point, not
a symbol whose length means something arbitrary.
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Rectangle

from ..grid import EARTH_RADIUS_M, nearest_cell
from ..regions import MASTER, REGIONS, BBox
from ..stats.spatial import area_mean
from .coast import draw_coastline, set_geographic_aspect
from .plots import MONTH_LABELS
from .style import CATEGORICAL, CMAP_CONSTANCY, CMAP_DIRECTION, CMAP_SPEED, INK

__all__ = [
    "fig_constancy_map",
    "fig_drift_map",
    "fig_drift_month_grid",
    "fig_drift_percentile_map",
    "fig_landing_ellipse_map",
    "fig_month_grid_map",
    "fig_overview_map",
    "fig_wind_ellipse_map",
]

#: Probability contours for a landing ellipse, matching the k = sqrt(-2 ln(1-p))
#: convention already used in ``frontend/src/stats/landing.ts``.
ELLIPSE_LEVELS = ((0.5, "50%"), (0.9, "90%"), (0.95, "95%"))


def _k_for(p: float) -> float:
    return float(np.sqrt(-2.0 * np.log(1.0 - p)))


def _m_to_deg(dx_m, dy_m, lat_deg):
    """Metres east/north -> degrees of longitude/latitude at a given latitude."""
    dlat = np.degrees(np.asarray(dy_m, dtype=float) / EARTH_RADIUS_M)
    dlon = np.degrees(
        np.asarray(dx_m, dtype=float)
        / (EARTH_RADIUS_M * np.cos(np.radians(np.asarray(lat_deg, dtype=float))))
    )
    return dlon, dlat


def _frame(ax, bbox: BBox, *, pad: float = 0.0) -> None:
    west = bbox.west - 360.0 if bbox.west > 180.0 else bbox.west
    east = bbox.east - 360.0 if bbox.east > 180.0 else bbox.east
    ax.set_xlim(west - pad, east + pad)
    ax.set_ylim(bbox.south - pad, bbox.north + pad)
    set_geographic_aspect(ax, bbox.lat_mid)


def _region_box(ax, bbox: BBox, colour: str, label: str | None = None) -> None:
    west = bbox.west - 360.0 if bbox.west > 180.0 else bbox.west
    east = bbox.east - 360.0 if bbox.east > 180.0 else bbox.east
    ax.add_patch(
        Rectangle(
            (west, bbox.south), east - west, bbox.north - bbox.south,
            fill=False, edgecolor=colour, linewidth=1.8, zorder=6, label=label,
        )
    )
    if label:
        # Above the box, on a backing: inside, the arrows run over it, and
        # boxes that overlap would put one label on top of the other box.
        ax.text(west + 0.1, bbox.north + 0.15, label, color=colour, fontsize=10,
                va="bottom", zorder=7,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5, "alpha": 0.85})


# --- context -----------------------------------------------------------------


def bin_label(ds: xr.Dataset, bin_index: int) -> str:
    """The label the dataset records for a bin, e.g. "前半 (1-15日)".

    Read from the data rather than built from a constant, so a figure drawn
    from the seven-day product says "W2" and one drawn from the half-month
    product says "後半" without either being told which it is.
    """
    labels = ds.attrs.get("bin_labels")
    if labels is None or not 1 <= bin_index <= len(labels):
        return f"ビン {bin_index}"
    return str(labels[bin_index - 1])


def fig_overview_map(datasets: dict[str, xr.Dataset], month: int = 1, bin_index: int = 2,
                     level_hpa: float = 200.0,
                     labels: dict[str, str] | None = None) -> Figure:
    """Where the regions are, and what the wind is doing across them."""
    fig = Figure(figsize=(9.5, 8.0))
    ax = fig.subplots()
    draw_coastline(ax, MASTER, linewidth=0.9, fill=True, fill_zorder=0)

    speed_max = 0.0
    for ds in datasets.values():
        at = ds.sel(month=month, bin=bin_index, level=level_hpa, method="nearest")
        speed_max = max(speed_max, float(np.nanpercentile(at["speed_mean"].values, 99)))

    mesh = None
    arrows: dict[tuple[float, float], tuple[float, float]] = {}
    for (name, ds), colour in zip(datasets.items(), CATEGORICAL, strict=False):
        at = ds.sel(month=month, bin=bin_index, level=level_hpa, method="nearest")
        lon, lat = at["lon"].values, at["lat"].values
        mesh = ax.pcolormesh(lon, lat, at["speed_mean"].values, cmap=CMAP_SPEED,
                             vmin=0, vmax=speed_max, shading="nearest", zorder=1, alpha=0.95)
        u, v = at["u_mean"].values, at["v_mean"].values
        for i, la in enumerate(lat):
            for j, lo in enumerate(lon):
                arrows[(round(float(la), 3), round(float(lo), 3))] = (u[i, j], v[i, j])
        _region_box(ax, REGIONS[name], colour, label=(labels or {}).get(name, name))

    # The regions share one grid and may overlap, so arrows are thinned on
    # that common grid and drawn in one call: one length scale for every
    # region, and no doubled arrows where two boxes cover the same cells.
    if arrows:
        lats = sorted({k[0] for k in arrows})
        lons = sorted({k[1] for k in arrows})
        keep = [k for k in arrows
                if lats.index(k[0]) % 3 == 0 and lons.index(k[1]) % 3 == 0]
        ax.quiver([k[1] for k in keep], [k[0] for k in keep],
                  [arrows[k][0] for k in keep], [arrows[k][1] for k in keep],
                  color=INK["primary"], edgecolor="white", linewidth=0.6,
                  width=0.004, zorder=4, scale=speed_max * 20, scale_units="width")

    _frame(ax, MASTER)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    ax.set_title(
        f"対象領域と {MONTH_LABELS[month - 1]} {bin_label(ds, bin_index)}"
        f"の {level_hpa:.0f} hPa の平均風"
    )
    if mesh is not None:
        fig.colorbar(mesh, ax=ax, label="平均風速 [m/s]", shrink=0.8, pad=0.02)
    fig.tight_layout()
    return fig


# --- seasonal maps -----------------------------------------------------------


def fig_month_grid_map(ds: xr.Dataset, region: str, label: str, level_hpa: float,
                       *, bin_index: int = 2) -> Figure:
    """Twelve maps, one per month, at a single level. The annual cycle in space."""
    box = REGIONS[region]
    at_all = ds.sel(level=level_hpa, method="nearest").sel(bin=bin_index)
    lon, lat = ds["lon"].values, ds["lat"].values
    vmax = float(np.nanpercentile(at_all["speed_mean"].values, 99))
    alt = float(np.nanmean(area_mean(ds, "alt_geom_mean_km")
                           .sel(level=level_hpa, method="nearest").values))

    fig = Figure(figsize=(13, 10))
    axes = fig.subplots(3, 4, sharex=True, sharey=True).ravel()
    mesh = None
    for i, ax in enumerate(axes):
        if i >= ds.sizes["month"]:
            ax.set_visible(False)
            continue
        at = at_all.isel(month=i)
        mesh = ax.pcolormesh(lon, lat, at["speed_mean"].values, cmap=CMAP_SPEED,
                             vmin=0, vmax=vmax, shading="nearest", zorder=1)
        step = max(1, len(lon) // 8)
        ax.quiver(lon[::step], lat[::step],
                  at["u_mean"].values[::step, ::step], at["v_mean"].values[::step, ::step],
                  color=INK["primary"], width=0.007, zorder=4)
        draw_coastline(ax, box)
        _frame(ax, box)
        ax.set_title(MONTH_LABELS[i], fontsize=10)
    fig.colorbar(mesh, ax=axes.tolist(), label="平均風速 [m/s]", shrink=0.7, pad=0.01)
    fig.suptitle(
        f"{label}: {level_hpa:.0f} hPa（約 {alt:.0f} km）の平均風、"
        f"{bin_label(ds, bin_index)}、月別",
        y=0.98,
    )
    return fig


def fig_constancy_map(ds: xr.Dataset, region: str, label: str,
                      levels_hpa: tuple[float, ...] = (850.0, 200.0, 30.0, 10.0),
                      *, bin_index: int = 2,
                      months: tuple[int, ...] = (1, 4, 7, 10)) -> Figure:
    """Where and when the mean direction is worth reading off a map."""
    box = REGIONS[region]
    lon, lat = ds["lon"].values, ds["lat"].values
    fig = Figure(figsize=(3.4 * len(months), 3.2 * len(levels_hpa)))
    axes = np.atleast_2d(fig.subplots(len(levels_hpa), len(months), sharex=True, sharey=True))
    mesh = None
    for li, level in enumerate(levels_hpa):
        for mi, month in enumerate(months):
            ax = axes[li, mi]
            at = ds.sel(month=month, bin=bin_index, level=level, method="nearest")
            mesh = ax.pcolormesh(lon, lat, at["constancy"].values, cmap=CMAP_CONSTANCY,
                                 vmin=0, vmax=1, shading="nearest", zorder=1)
            draw_coastline(ax, box)
            _frame(ax, box)
            if li == 0:
                ax.set_title(MONTH_LABELS[month - 1], fontsize=10)
            if mi == 0:
                ax.set_ylabel(f"{level:.0f} hPa", fontsize=9)
    fig.colorbar(mesh, ax=axes.ravel().tolist(), label="定常度", shrink=0.6, pad=0.01)
    fig.suptitle(f"{label}: 定常度の分布（{bin_label(ds, bin_index)}）", y=0.99)
    return fig


def fig_wind_ellipse_map(ds: xr.Dataset, region: str, label: str, level_hpa: float,
                         month: int, bin_index: int) -> Figure:
    """Per-cell scatter ellipses of the wind, drawn on the map.

    The arrow is the mean wind; the ellipse around its tip is the 1-sigma spread
    of the individual analyses. A round ellipse means the wind varies in every
    direction; a flat one means it varies mostly in strength.
    """
    box = REGIONS[region]
    at = ds.sel(month=month, bin=bin_index, level=level_hpa, method="nearest")
    lon, lat = ds["lon"].values, ds["lat"].values
    alt = float(np.nanmean(area_mean(ds, "alt_geom_mean_km")
                           .sel(level=level_hpa, method="nearest").values))

    fig = Figure(figsize=(9, 7.5))
    ax = fig.subplots()
    mesh = ax.pcolormesh(lon, lat, at["speed_mean"].values, cmap=CMAP_SPEED,
                         vmin=0, shading="nearest", zorder=1)
    draw_coastline(ax, box)

    # One degree of longitude per this many m/s, shared by arrows and ellipses.
    # The longest arrow is kept to 70 % of the spacing between drawn cells, so
    # neighbours never run into each other however few cells the region has.
    span = float(lon.max() - lon.min())
    step = max(1, int(np.ceil(len(lon) / 9)))
    spacing = span / max(len(lon) - 1, 1) * step
    scale = float(np.nanmax(at["speed_mean"].values)) / max(spacing * 0.7, 1e-6)
    head = spacing * 0.22
    for j in range(0, len(lon), step):
        for i in range(0, len(lat), step):
            u = float(at["u_mean"].values[i, j])
            v = float(at["v_mean"].values[i, j])
            if not (np.isfinite(u) and np.isfinite(v)):
                continue
            ax.arrow(lon[j], lat[i], u / scale, v / scale, color=INK["primary"],
                     width=head * 0.15, head_width=head, head_length=head * 0.9,
                     length_includes_head=True, zorder=5)
            maj = float(at["ellipse_major"].values[i, j])
            mnr = float(at["ellipse_minor"].values[i, j])
            ang = float(at["ellipse_angle_deg"].values[i, j])
            if np.isfinite(maj):
                ax.add_patch(
                    Ellipse((lon[j] + u / scale, lat[i] + v / scale),
                            2 * maj / scale, 2 * mnr / scale, angle=ang,
                            facecolor="none", edgecolor="white",
                            linewidth=1.1, alpha=0.9, zorder=6)
                )
    _frame(ax, box)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    ax.set_title(
        f"{label}: {MONTH_LABELS[month - 1]} {bin_label(ds, bin_index)}、{level_hpa:.0f} hPa"
        f"（約 {alt:.0f} km）の平均風と $1\\sigma$ の散らばり"
    )
    fig.colorbar(mesh, ax=ax, label="平均風速 [m/s]", shrink=0.8, pad=0.02)
    fig.tight_layout()
    return fig


# --- drift -------------------------------------------------------------------


def _drift_frame(ds: xr.Dataset, region: str, month=None, bin_index=None) -> BBox:
    """A frame wide enough to contain the launch box and every landing point.

    ``month``/``half`` of ``None`` means "over all of them", which is what the
    twelve-panel figure needs: panels drawn on different frames cannot be compared
    by eye, and comparing the months is the entire point of that figure.
    """
    box = REGIONS[region]
    sub = ds if month is None else ds.sel(month=month, bin=bin_index)
    lat2 = ds["lat"].values[:, None]
    if month is None:
        east = sub["drift_east_m"].values
        north = sub["drift_north_m"].values
        lat2 = lat2[None, None, :, :] if east.ndim == 4 else lat2
    else:
        east, north = sub["drift_east_m"].values, sub["drift_north_m"].values
    dlon, dlat = _m_to_deg(east, north, lat2)
    lon_end = ds["lon"].values + dlon
    lat_end = lat2 + dlat
    west = min(float(np.nanmin(lon_end)), box.west) - 0.6
    east_deg = max(float(np.nanmax(lon_end)), box.east) + 0.6
    south = min(float(np.nanmin(lat_end)), box.south) - 0.6
    north_deg = max(float(np.nanmax(lat_end)), box.north) + 0.6
    return BBox(south=south, north=north_deg, west=west % 360.0, east=east_deg % 360.0)


def _draw_drift(ax, ds: xr.Dataset, region: str, month: int, bin_index: int, *,
                step: int | None = None, vmax: float | None = None,
                frame: BBox | None = None, norm=None):
    """Launch points, landing points, and the coastline underneath both.

    Deliberately no shaded field: a filled mesh over the launch box hides exactly
    the coastline a reader is checking the landing point against. The distance is
    carried by the arrow colour instead, and the arrow length is already to scale.
    """
    box = REGIONS[region]
    sub = ds.sel(month=month, bin=bin_index)
    lon, lat = ds["lon"].values, ds["lat"].values
    frame = frame or _drift_frame(ds, region, month, bin_index)

    draw_coastline(ax, frame, fill=True, fill_zorder=0, linewidth=0.7)
    norm = norm or Normalize(
        vmin=0.0,
        vmax=vmax or float(np.nanpercentile(ds["drift_dist_mean_km"].values, 99)),
    )
    step = step or max(1, len(lon) // 8)
    for j in range(0, len(lon), step):
        for i in range(0, len(lat), step):
            dx = float(sub["drift_east_m"].values[i, j])
            dy = float(sub["drift_north_m"].values[i, j])
            if not (np.isfinite(dx) and np.isfinite(dy)):
                continue
            dist = float(sub["drift_dist_mean_km"].values[i, j])
            colour = CMAP_SPEED(norm(dist))
            dlon, dlat = _m_to_deg(dx, dy, lat[i])
            ax.annotate(
                "", xy=(lon[j] + dlon, lat[i] + dlat), xytext=(lon[j], lat[i]),
                arrowprops={"arrowstyle": "-|>", "color": colour,
                            "linewidth": 1.3, "shrinkA": 0, "shrinkB": 0},
                zorder=5,
            )
            ax.plot(lon[j], lat[i], "o", color=INK["secondary"], markersize=2.2, zorder=6)
    _region_box(ax, box, INK["secondary"])
    _frame(ax, frame)
    return ScalarMappable(norm=norm, cmap=CMAP_SPEED)


def fig_drift_map(ds: xr.Dataset, region: str, label: str, month: int, bin_index: int) -> Figure:
    """Where a payload launched from each grid cell would land, on average.

    Drawn to scale: each arrow starts at a launch point and its tip is the mean
    landing point. The shading is the mean distance travelled -- note that is the
    mean of the distances, which is larger than the distance of the mean landing
    point whenever the direction varies.
    """
    fig = Figure(figsize=(9.5, 8.0))
    ax = fig.subplots()
    mesh = _draw_drift(ax, ds, region, month, bin_index)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    flight = ds.attrs.get("flight_description", "")
    ax.set_title(
        f"{label}: {MONTH_LABELS[month - 1]} {bin_label(ds, bin_index)}に上げた場合の平均落下位置\n"
        f"（{flight}、矢印は実寸）", fontsize=11
    )
    fig.colorbar(mesh, ax=ax, label="平均の飛行距離 [km]", shrink=0.8, pad=0.02)
    fig.tight_layout()
    return fig


def fig_drift_month_grid(ds: xr.Dataset, region: str, label: str, *, bin_index: int = 2) -> Figure:
    """The same drift map for all twelve months, on one shared scale."""
    vmax = float(np.nanpercentile(ds["drift_dist_mean_km"].values, 99))
    norm = Normalize(vmin=0.0, vmax=vmax)
    frame = _drift_frame(ds, region)          # one frame for all twelve panels
    # Height from the frame's shape on the ground: a fixed height leaves wide,
    # flat frames floating in white space.
    mid = np.radians((frame.south + frame.north) / 2)
    aspect = (frame.north - frame.south) / (((frame.east - frame.west) % 360.0) * np.cos(mid))
    panel_w = 13 * 0.75 / 4
    fig = Figure(figsize=(13, min(10.5, 3 * (panel_w * aspect + 0.5) + 0.9)))
    axes = fig.subplots(3, 4, sharex=True, sharey=True).ravel()
    mesh = None
    for i, ax in enumerate(axes):
        if i >= ds.sizes["month"]:
            ax.set_visible(False)
            continue
        month = int(ds["month"].values[i])
        mesh = _draw_drift(ax, ds, region, month, bin_index,
                           step=max(1, ds.sizes["lon"] // 5), frame=frame, norm=norm)
        ax.set_title(MONTH_LABELS[month - 1], fontsize=10)
        ax.tick_params(labelsize=7)
    fig.colorbar(mesh, ax=axes.tolist(), label="平均の飛行距離 [km]", shrink=0.7, pad=0.01)
    flight = ds.attrs.get("flight_description", "")
    fig.suptitle(f"{label}: 月別の平均落下位置（{bin_label(ds, bin_index)}、{flight}）", y=0.98)
    return fig


def fig_drift_percentile_map(ds: xr.Dataset, region: str, label: str,
                             *, bin_index: int = 2,
                             months: tuple[int, ...] = (1, 4, 7, 10)) -> Figure:
    """The bad days: the 90th percentile of flight distance.

    A mean of 150 km and a p90 of 400 km are very different operational problems,
    and the mean alone hides the difference.
    """
    box = REGIONS[region]
    lon, lat = ds["lon"].values, ds["lat"].values
    vmax = float(np.nanpercentile(ds["drift_dist_p90_km"].values, 99))
    fig = Figure(figsize=(3.6 * len(months), 4.2))
    axes = np.atleast_1d(fig.subplots(1, len(months), sharey=True))
    mesh = None
    for ax, month in zip(axes, months, strict=True):
        at = ds.sel(month=month, bin=bin_index)
        mesh = ax.pcolormesh(lon, lat, at["drift_dist_p90_km"].values, cmap=CMAP_SPEED,
                             vmin=0, vmax=vmax, shading="nearest", zorder=1)
        draw_coastline(ax, box)
        _frame(ax, box)
        ax.set_title(MONTH_LABELS[month - 1], fontsize=10)
        ax.set_xlabel("経度 [度]")
    axes[0].set_ylabel("緯度 [度]")
    fig.colorbar(mesh, ax=axes.tolist(), label="飛行距離の p90 [km]", shrink=0.8, pad=0.01)
    fig.suptitle(f"{label}: 荒れた日の飛行距離（{bin_label(ds, bin_index)}）", y=0.99)
    return fig


def fig_landing_ellipse_map(ds: xr.Dataset, region: str, label: str,
                            site_lat: float, site_lon: float, site_name: str,
                            months: tuple[int, ...] = (1, 4, 7, 10),
                            *, bin_index: int = 2) -> Figure:
    """One launch point, four seasons: the landing scatter drawn on the coastline.

    The ellipses come from the covariance of the landing points computed per
    analysis, so they describe the real spread of this decade's weather rather
    than an assumed one. They do still assume the scatter is bivariate normal,
    which is the same caveat the wind ellipses carry.
    """
    lon, lat = ds["lon"].values, ds["lat"].values
    i, j, offset_km = nearest_cell(lat, lon, site_lat, site_lon)

    ends = []
    for month in months:
        cell = ds.sel(month=month, bin=bin_index).isel(lat=i, lon=j)
        dlon, dlat = _m_to_deg(float(cell["drift_east_m"]), float(cell["drift_north_m"]),
                               site_lat)
        spread = np.sqrt(max(float(cell["drift_east_var"]), 0.0)) / 1000.0
        ends.append((site_lon + dlon, site_lat + dlat, spread))
    lons = [site_lon] + [e[0] for e in ends]
    lats = [site_lat] + [e[1] for e in ends]
    pad = 2.0
    frame = BBox(south=min(lats) - pad, north=max(lats) + pad,
                 west=(min(lons) - pad) % 360.0, east=(max(lons) + pad) % 360.0)

    fig = Figure(figsize=(9.5, 8.5))
    ax = fig.subplots()
    draw_coastline(ax, frame, linewidth=0.9, fill=True, fill_zorder=0)

    for (month, colour) in zip(months, CATEGORICAL, strict=True):
        cell = ds.sel(month=month, bin=bin_index).isel(lat=i, lon=j)
        dx, dy = float(cell["drift_east_m"]), float(cell["drift_north_m"])
        dlon, dlat = _m_to_deg(dx, dy, site_lat)
        cx, cy = site_lon + dlon, site_lat + dlat

        var_e = float(cell["drift_east_var"])
        var_n = float(cell["drift_north_var"])
        cov = float(cell["drift_cov"])
        if np.isfinite(var_e) and np.isfinite(var_n):
            half = 0.5 * (var_e + var_n)
            root = np.sqrt(max((0.5 * (var_e - var_n)) ** 2 + cov**2, 0.0))
            major_m, minor_m = np.sqrt(max(half + root, 0.0)), np.sqrt(max(half - root, 0.0))
            angle = np.degrees(0.5 * np.arctan2(2 * cov, var_e - var_n))
            for p, _name in ELLIPSE_LEVELS:
                k = _k_for(p)
                w_deg, _ = _m_to_deg(2 * k * major_m, 0.0, site_lat)
                _, h_deg = _m_to_deg(0.0, 2 * k * minor_m, site_lat)
                ax.add_patch(
                    Ellipse((cx, cy), w_deg, h_deg, angle=angle, facecolor=colour,
                            alpha=0.10, edgecolor=colour, linewidth=1.0, zorder=4)
                )
        ax.annotate("", xy=(cx, cy), xytext=(site_lon, site_lat),
                    arrowprops={"arrowstyle": "-|>", "color": colour, "linewidth": 1.6},
                    zorder=5)
        ax.plot(cx, cy, "o", color=colour, markersize=6, zorder=6,
                label=f"{MONTH_LABELS[month - 1]} {bin_label(ds, bin_index)}")

    ax.plot(site_lon, site_lat, "*", color=INK["primary"], markersize=16, zorder=8)
    ax.annotate(site_name, (site_lon, site_lat), textcoords="offset points",
                xytext=(10, -14), fontsize=9, color=INK["primary"], zorder=8)
    _frame(ax, frame)
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    flight = ds.attrs.get("flight_description", "")
    ax.set_title(
        f"{label}: {site_name} から上げた場合の落下位置\n"
        f"（{flight}、楕円は 50 / 90 / 95 %、最寄り格子まで {offset_km:.0f} km）",
        fontsize=11,
    )
    handles = ax.get_legend_handles_labels()[0] + [
        Line2D([], [], marker="*", color=INK["primary"], linestyle="none",
               markersize=12, label="打ち上げ地点")
    ]
    ax.legend(handles=handles, loc="best", fontsize=8)
    fig.tight_layout()
    return fig


def fig_direction_map(ds: xr.Dataset, region: str, label: str, level_hpa: float,
                      *, bin_index: int = 2,
                      months: tuple[int, ...] = (1, 4, 7, 10),
                      constancy_min: float = 0.3) -> Figure:
    """Mean wind direction on the map, masked where it is not meaningful."""
    box = REGIONS[region]
    lon, lat = ds["lon"].values, ds["lat"].values
    fig = Figure(figsize=(3.6 * len(months), 4.2))
    axes = np.atleast_1d(fig.subplots(1, len(months), sharey=True))
    mesh = None
    for ax, month in zip(axes, months, strict=True):
        at = ds.sel(month=month, bin=bin_index, level=level_hpa, method="nearest")
        field = np.where(at["constancy"].values < constancy_min, np.nan,
                         at["dir_vector_mean"].values)
        mesh = ax.pcolormesh(lon, lat, field, cmap=CMAP_DIRECTION, vmin=0, vmax=360,
                             shading="nearest", zorder=1)
        draw_coastline(ax, box)
        _frame(ax, box)
        ax.set_title(MONTH_LABELS[month - 1], fontsize=10)
        ax.set_xlabel("経度 [度]")
    axes[0].set_ylabel("緯度 [度]")
    cb = fig.colorbar(mesh, ax=axes.tolist(), label="風向（吹いてくる向き）",
                      shrink=0.8, pad=0.01, ticks=[0, 90, 180, 270, 360])
    cb.ax.set_yticklabels(["北", "東", "南", "西", "北"])
    fig.suptitle(
        f"{label}: {level_hpa:.0f} hPa の平均風向（{bin_label(ds, bin_index)}、"
        f"定常度 {constancy_min} 未満は灰色）", y=0.99, fontsize=11
    )
    return fig
