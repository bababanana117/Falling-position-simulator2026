"""Figures for the winter wind-speed distribution and the landing cloud it implies.

Two figures, answering two questions in order.

The first asks what shape the speed distribution actually has, and shows the
histogram with the fitted curve on top so the reader can judge the fit rather
than take the AIC on trust. A uniform density is drawn alongside because
"uniform or Gaussian?" was the question, and a picture settles it faster than a
number.

The second shows landing points. Points, not ellipses: an ellipse asserts that
the cloud is bivariate normal, and the whole reason this appendix exists is
that the assumptions behind such summaries are worth checking. With a few
thousand samples the scatter shows its own shape.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from scipy import stats

from .style import CATEGORICAL, INK, recessive_grid

__all__ = ["fig_landing_clouds", "fig_landing_map", "fig_speed_fits"]

#: Levels the fit figure draws, top of the flight downwards.
FIT_LEVELS = (10.0, 30.0, 100.0, 200.0, 500.0, 850.0)


def fig_speed_fits(model, u, v, region: str = "和歌山") -> Figure:
    """Histogram of the observed speed at each level, with the fitted curve.

    ``u``/``v`` are the samples the model was fitted to, ``(sample, level)``.
    """
    levels = np.asarray(model.levels_hpa, dtype=float)
    speed = np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))
    picks = [int(np.argmin(np.abs(levels - p))) for p in FIT_LEVELS]

    fig = Figure(figsize=(10.2, 5.6), dpi=160)
    axes = fig.subplots(2, 3)
    for ax, k in zip(axes.ravel(), picks, strict=True):
        fit = model.fits[k]
        x = speed[:, k]
        ax.hist(x, bins=40, density=True, color=INK["grid"], edgecolor="none", zorder=2)
        grid = np.linspace(0.0, x.max() * 1.05, 400)
        # The family differs between panels, so the name goes on the panel.
        # A shared legend would have to pick one and would then be wrong for
        # the others -- which is exactly the kind of quiet mislabelling this
        # figure exists to guard against.
        ax.plot(grid, fit.dist.pdf(grid, *fit.params), color=CATEGORICAL[0],
                linewidth=2.0, zorder=4, label="当てはめた分布")
        lo, w = stats.uniform.fit(x)
        ax.plot(grid, stats.uniform.pdf(grid, lo, w), color=CATEGORICAL[1],
                linewidth=1.4, linestyle="--", zorder=3, label="一様（比較）")
        ax.set_title(f"{fit.level_hpa:g} hPa", fontsize=10, color=INK["secondary"])
        ax.set_ylim(bottom=0.0)
        ax.set_xlabel("風速 [m/s]")
        family_ja = "正規" if fit.family == "norm" else "Weibull"
        ax.annotate(
            f"{family_ja}\nKS={fit.ks:.3f}\n一様とのΔAIC={fit.aic_uniform - fit.aic:,.0f}",
            xy=(0.97, 0.95), xycoords="axes fraction", ha="right", va="top",
            fontsize=8, color=CATEGORICAL[0],
        )
        recessive_grid(ax)
    axes[0, 0].set_ylabel("確率密度")
    axes[1, 0].set_ylabel("確率密度")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, ncol=2,
               loc="lower center", bbox_to_anchor=(0.5, 0.0))
    fig.suptitle(f"{region}の冬：気圧面ごとの風速分布", color=INK["primary"], fontsize=11)
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    return fig


def fig_landing_clouds(clouds: dict[str, tuple], region: str = "和歌山") -> Figure:
    """Landing points for each scenario, on shared axes, as points.

    ``clouds`` maps a label to ``(dx_km, dy_km)``. The first entry is treated
    as the reference and is redrawn faintly behind every other panel, so each
    scenario is compared against reality rather than against the page.
    """
    names = list(clouds)
    ref_x, ref_y = clouds[names[0]]
    n = len(names)
    fig = Figure(figsize=(3.3 * n, 3.9), dpi=160)
    axes = fig.subplots(1, n, sharex=True, sharey=True)
    axes = np.atleast_1d(axes)

    allx = np.concatenate([np.asarray(c[0]) for c in clouds.values()])
    ally = np.concatenate([np.asarray(c[1]) for c in clouds.values()])
    # Include the origin: the launch point is the thing every cloud is measured
    # from, and a scatter whose reference point is off the page is harder to
    # read than one with some empty space in it.
    pad = 0.06 * max(np.ptp(allx), np.ptp(ally))
    lim = (
        min(allx.min(), 0.0) - pad, allx.max() + pad,
        min(ally.min(), 0.0) - pad, max(ally.max(), 0.0) + pad,
    )

    for i, (ax, name) in enumerate(zip(axes, names, strict=True)):
        x, y = clouds[name]
        if i > 0:
            ax.scatter(ref_x, ref_y, s=3, color=INK["grid"], linewidth=0, zorder=2,
                       label=names[0])
        colour = INK["primary"] if i == 0 else CATEGORICAL[i - 1]
        ax.scatter(x, y, s=3, color=colour, alpha=0.35, linewidth=0, zorder=3,
                   label=name)
        ax.scatter([0], [0], marker="*", s=110, color=INK["primary"], zorder=5,
                   edgecolor=INK["surface"], linewidth=0.8)
        if i == 0:
            ax.annotate("打ち上げ", xy=(0, 0), xytext=(6, 8),
                        textcoords="offset points", fontsize=8.5,
                        color=INK["secondary"])
        ax.set_title(
            f"{name}\n東西 SD {np.std(x):.0f} km / 南北 SD {np.std(y):.0f} km",
            fontsize=9.5, color=INK["secondary"],
        )
        ax.set_xlabel("東向き [km]")
        ax.set_xlim(lim[0], lim[1])
        ax.set_ylim(lim[2], lim[3])
        ax.set_aspect("equal", adjustable="box")
        recessive_grid(ax)
    axes[0].set_ylabel("北向き [km]")
    fig.suptitle(
        f"{region}の冬：打ち上げ地点（★）からの落下点",
        color=INK["primary"], fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return fig


#: Scatter colours for use *over the map*. The shared categorical order is
#: designed against a white page; here the background is mostly ocean blue, so
#: its first hue would be the least visible one available. These are warm and
#: light-on-dark instead, chosen to stay separable over both the blue sea and
#: the green-brown land.
_OVER_MAP = ("#ffffff", "#ff2d95", "#ff6b1f", "#ffd400", "#7cff3f", "#00ffd0")

#: Land and sea are two different domains with a real boundary at zero, so
#: they get two ramps rather than one. Within each, colour is a magnitude and
#: runs light to dark in a single direction.
_SEA_STEPS = ("#07203a", "#0d3454", "#14486e", "#1d5d87", "#2a739f", "#3c89b4", "#5aa0c6")
_LAND_STEPS = ("#e8f0d9", "#cfe0b0", "#a9c486", "#8aa96a", "#9e9a5e", "#b08d62",
               "#a87f6a", "#9c8b85", "#c9c4bf", "#f2f0ee")


def _terrain_image(tile, ax, *, sea_floor: float = -8000.0, land_ceiling: float = 3800.0):
    """Draw a hypsometric, hill-shaded map of one tile and return the axes.

    Two colour ramps meeting at the coastline, then a hillshade multiplied over
    the top. The shading is what turns a field of colour into something a
    reader can recognise as terrain; without it the Kii peninsula and the
    Nankai Trough are just two shades of the same thing.
    """
    from matplotlib.colors import LightSource, ListedColormap, Normalize  # noqa: PLC0415

    e = np.asarray(tile.elevation, dtype=float)
    sea = ListedColormap(_SEA_STEPS)
    land = ListedColormap(_LAND_STEPS)

    rgb = np.empty((*e.shape, 3))
    wet = e <= 0
    rgb[wet] = sea(Normalize(sea_floor, 0.0)(e[wet]))[:, :3]
    rgb[~wet] = land(Normalize(0.0, land_ceiling)(e[~wet]))[:, :3]

    # Exaggerate the vertical because a degree is ~100 km and a mountain is
    # ~3 km: at true scale the shading would be invisible.
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(e, vert_exag=60.0, dx=1.0, dy=1.0)
    rgb *= (0.55 + 0.45 * shade)[..., None]

    ax.imshow(np.clip(rgb, 0, 1), extent=tile.extent, origin="upper",
              interpolation="bilinear", zorder=0)
    ax.contour(
        np.linspace(tile.bbox.west, tile.bbox.east, e.shape[1]),
        np.linspace(tile.bbox.north, tile.bbox.south, e.shape[0]),
        e, levels=[0.0], colors=["#1c1c1c"], linewidths=0.6, zorder=2,
    )
    return ax


def fig_landing_map(
    tile,
    clouds: dict[str, tuple],
    launch_lat: float,
    launch_lon: float,
    region: str = "和歌山",
    *,
    reference: str | None = None,
    launch_label: str | None = None,
) -> Figure:
    """One large map with the landing points on it.

    ``clouds`` maps a label to ``(dx_km, dy_km)`` relative to the launch point.
    ``reference`` names the cloud drawn as a pale background behind the others;
    it defaults to the first.

    Points, never ellipses. An ellipse would assert the cloud is bivariate
    normal, which is the assumption this appendix set out to avoid taking on
    trust, and at this scale a few thousand dots show the shape by themselves.
    """
    names = list(clouds)
    reference = reference or names[0]

    fig = Figure(figsize=(12.0, 8.2), dpi=170)
    ax = fig.add_subplot(111)
    _terrain_image(tile, ax)

    km_per_deg_lat = 111.195
    km_per_deg_lon = 111.195 * float(np.cos(np.radians(launch_lat)))

    def to_lonlat(dx_km, dy_km):
        return launch_lon + np.asarray(dx_km) / km_per_deg_lon, \
               launch_lat + np.asarray(dy_km) / km_per_deg_lat

    if len(names) > len(_OVER_MAP):
        raise ValueError(
            f"{len(names)} clouds but only {len(_OVER_MAP)} distinguishable colours; "
            "cycling them would give two clouds the same hue"
        )
    # Colour by position in the caller's order, so the legend matches the
    # narrative, but *draw* widest first: a tight cloud painted underneath a
    # broad one disappears, and the tight ones are the interesting ones here.
    legend_order = [reference, *[m for m in names if m != reference]]
    colour = dict(zip(legend_order, _OVER_MAP, strict=False))
    spread = {n: float(np.hypot(np.std(c[0]), np.std(c[1]))) for n, c in clouds.items()}
    for z, name in enumerate(sorted(names, key=lambda n: -spread[n])):
        lon, lat = to_lonlat(*clouds[name])
        is_ref = name == reference
        ax.scatter(
            lon, lat, s=3.0, color=colour[name],
            alpha=0.55 if is_ref else 0.45, linewidth=0, zorder=3 + z,
            label=f"{name}（背景）" if is_ref else name,
        )

    ax.plot([launch_lon], [launch_lat], "*", markersize=22, color="#ffdd33",
            markeredgecolor="#1c1c1c", markeredgewidth=1.2, zorder=20)
    name = launch_label or f"{region}中央"
    ax.annotate(
        f"打ち上げ地点：{name}\n{launch_lat:.3f}N {launch_lon:.3f}E",
        xy=(launch_lon, launch_lat), xytext=(10, -26),
        textcoords="offset points", fontsize=10, color="#1c1c1c", zorder=21,
        bbox={"facecolor": "#ffffff", "alpha": 0.85, "edgecolor": "none", "pad": 2},
    )

    _scale_bar(ax, tile, km_per_deg_lon)
    ax.set_xlim(tile.bbox.west, tile.bbox.east)
    ax.set_ylim(tile.bbox.south, tile.bbox.north)
    ax.set_aspect(1.0 / max(np.cos(np.radians(launch_lat)), 1e-6))
    ax.set_xlabel("経度 [度]")
    ax.set_ylabel("緯度 [度]")
    # Legend in the caller's order, not the drawing order.
    handles = {h.get_label().replace("（背景）", ""): h
               for h in ax.collections if h.get_label()}
    ordered = [handles[n] for n in legend_order if n in handles]
    leg = ax.legend(handles=ordered, loc="upper right", frameon=True, fontsize=10,
                    markerscale=6, framealpha=0.92)
    leg.set_zorder(30)
    # No title: the caption carries it, and a title here would repeat the
    # caption while stealing height from the map.
    fig.tight_layout()
    return fig


def _scale_bar(ax, tile, km_per_deg_lon: float, km: float = 100.0) -> None:
    """A plain scale bar. A map without one invites the reader to guess."""
    span = tile.bbox.east - tile.bbox.west
    x0 = tile.bbox.west + 0.06 * span
    y0 = tile.bbox.south + 0.06 * (tile.bbox.north - tile.bbox.south)
    dx = km / km_per_deg_lon
    ax.plot([x0, x0 + dx], [y0, y0], color="#1c1c1c", linewidth=3.5,
            solid_capstyle="butt", zorder=25)
    ax.annotate(f"{km:.0f} km", xy=(x0 + dx / 2, y0), xytext=(0, 6),
                textcoords="offset points", ha="center", fontsize=10,
                color="#1c1c1c", zorder=25,
                bbox={"facecolor": "#ffffff", "alpha": 0.8, "edgecolor": "none", "pad": 1})
