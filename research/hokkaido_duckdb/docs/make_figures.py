"""Draw every figure in the manual straight from the database.

Each figure answers one question and is built from one query, so the picture
and the numbers cannot disagree. Nothing here reads the source NetCDF or the
six-hourly cache: if the database is present, the figures can be redrawn.

    python make_figures.py                # into _figures/
    python make_figures.py --only rose    # one figure while iterating

Both a PDF and a PNG are written for every figure. Sphinx picks the PDF for
LaTeX and the PNG for HTML through the ``figure:: name.*`` wildcard.

Colour follows one rule per job: a single blue ramp for magnitude, a fixed
categorical order that is never cycled, and blue-to-red through a grey middle
only where the quantity really has two opposite directions. The categorical
order was checked for colour-vision separation; the two lighter slots sit
below 3:1 against white, so every series is also labelled where it is drawn
rather than relying on its colour.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import matplotlib as mpl
import numpy as np

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.font_manager import FontProperties, fontManager  # noqa: E402

log = logging.getLogger("make_figures")

HERE = Path(__file__).resolve().parent
DB_PATH = HERE.parent / "jra3q_hokkaido_wind_2016-2025_v1.duckdb"
OUT = HERE / "_figures"

# Taiki, Hokkaido. The launch site every site-specific figure is drawn for.
SITE_LAT, SITE_LON = 42.506, 143.440
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SITE_NAME = "Taiki"

# ------------------------------------------------------------------ colour --
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
BLUE_STEPS = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)
NEUTRAL = "#f0efec"
RED_POLE = "#8c1f1f"
INK = {
    "primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7", "surface": "#ffffff",
}
SEQ = LinearSegmentedColormap.from_list("hokblue", BLUE_STEPS)
DIV = LinearSegmentedColormap.from_list(
    "hokdiv", (BLUE_STEPS[-1], BLUE_STEPS[6], NEUTRAL, "#d47a7a", RED_POLE)
)

FONT_CANDIDATES = (
    Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji/"
         "HaranoAjiGothic-Regular.otf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
)


def apply_style() -> None:
    """One Japanese-capable font and a recessive frame, set once."""
    family = None
    for path in FONT_CANDIDATES:
        if path.exists():
            fontManager.addfont(str(path))
            family = FontProperties(fname=str(path)).get_name()
            break
    if family is None:
        log.warning("no Japanese font found; labels will show as boxes")

    mpl.rcParams.update({
        "figure.facecolor": INK["surface"],
        "axes.facecolor": INK["surface"],
        "savefig.facecolor": INK["surface"],
        "font.family": [family, "DejaVu Sans"] if family else ["DejaVu Sans"],
        "font.size": 8.5,
        "axes.titlesize": 9.5,
        "axes.labelsize": 8.5,
        "axes.labelcolor": INK["secondary"],
        "axes.edgecolor": INK["axis"],
        "axes.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": INK["grid"],
        "grid.linewidth": 0.5,
        "xtick.color": INK["muted"],
        "ytick.color": INK["muted"],
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.frameon": False,
        "legend.fontsize": 7.5,
        "lines.linewidth": 1.6,
        "figure.dpi": 150,
        "axes.unicode_minus": False,
    })


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{suffix}", bbox_inches="tight",
                    dpi=150 if suffix == "png" else None)
    plt.close(fig)
    log.info("  %s", name)


def bin_ticks(ax) -> None:
    """24 half-month bins along x.

    A tick sits at every month; only every other one is named, because twelve
    three-letter labels do not fit across a panel this wide.
    """
    ax.set_xticks(np.arange(12) * 2 + 1.0)
    ax.set_xticklabels([_MONTHS[m] if m % 2 == 0 else "" for m in range(12)])
    ax.set_xticks(np.arange(25), minor=True)
    ax.tick_params(axis="x", which="minor", length=2)
    ax.set_xlabel("half-month bin")


def level_axis(ax, levels) -> None:
    """Pressure on a log axis, labelled in hPa.

    The inversion is deliberately NOT done here. With ``sharey=True`` every
    call would flip the one shared axis again, so an even number of panels
    would come out upside down. The caller inverts once, after the loop.
    """
    ax.set_yscale("log")
    ticks = [1000, 500, 300, 200, 100, 50, 10, 3]
    ticks = [t for t in ticks if levels.min() <= t <= levels.max()]
    ax.set_yticks(ticks)
    ax.set_yticklabels([str(t) for t in ticks])
    ax.minorticks_off()


def panel_label(ax, text: str, *, inside: bool = True, colour: str | None = None) -> None:
    """Name a panel without giving the figure a title.

    The caption carries the message; a panel only needs to say which slice of
    the data it is. Placed inside the axes so it cannot be mistaken for one.
    """
    if inside:
        ax.text(0.03, 0.95, text, transform=ax.transAxes, ha="left", va="top",
                fontsize=7.5, color=colour or INK["primary"],
                bbox={"facecolor": INK["surface"], "edgecolor": "none",
                      "alpha": 0.0 if colour == INK["surface"] else 0.75,
                      "pad": 1.5})
    else:
        ax.text(0.0, 1.06, text, transform=ax.transAxes, ha="left", va="bottom",
                fontsize=7.5, color=colour or INK["primary"])


def site_cell(con) -> int:
    return con.execute(
        "SELECT cell_id FROM nearest_cell(?, ?)", [SITE_LAT, SITE_LON]
    ).fetchone()[0]


# ======================================================================== 1 --
def fig_seasonal_heatmap(con) -> None:
    """Where and when the wind is strong: the whole database in one panel."""
    df = con.execute("""
        SELECT timebin_id, level_hpa, speed_mean
        FROM v_area_mean ORDER BY timebin_id, level_hpa
    """).fetchdf()
    levels = np.sort(df["level_hpa"].unique())[::-1]
    grid = df.pivot(index="level_hpa", columns="timebin_id",
                    values="speed_mean").reindex(levels).to_numpy()

    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    mesh = ax.pcolormesh(np.arange(25), np.arange(len(levels) + 1), grid,
                         cmap=SEQ, shading="flat", rasterized=True)
    ax.set_yticks(np.arange(len(levels)) + 0.5)
    ax.set_yticklabels([f"{int(v)}" if v >= 10 else f"{v:g}" for v in levels],
                       fontsize=5.2)
    for label in ax.get_yticklabels()[1::2]:
        label.set_visible(False)
    ax.set_ylabel("pressure (hPa)")
    ax.invert_yaxis()
    bin_ticks(ax)
    ax.grid(False)
    bar = fig.colorbar(mesh, ax=ax, pad=0.02, aspect=28)
    bar.set_label("area-mean speed (m/s)")
    bar.outline.set_visible(False)
    save(fig, "seasonal_heatmap")


# ======================================================================== 2 --
def fig_speed_map(con) -> None:
    """Why the area mean peaks in October: the jet is a place, not a number.

    In January the jet is stronger but its core sits south of the region, so
    the domain only catches its northern flank and the area mean is diluted.
    In October the core lies across the whole domain.
    """
    fig, axes = plt.subplots(1, 3, figsize=(6.2, 2.9), sharey=True)
    panels = [(1, 1, "Jan H1"), (7, 1, "Jul H1"), (10, 1, "Oct H1")]

    frames = [
        con.execute("""
            SELECT lat, lon, speed_mean, u_mean, v_mean FROM fact_wind
            WHERE month = ? AND bin = ? AND level_hpa = 300 ORDER BY lat, lon
        """, [m, b]).fetchdf() for m, b, _ in panels
    ]
    # Zero is not a meaningful reference for a jet-level mean, and anchoring
    # the ramp there would push all three panels into the same dark blue.
    # The ramp spans the data instead, and the bar says so.
    lo = min(float(f["speed_mean"].min()) for f in frames)
    hi = max(float(f["speed_mean"].max()) for f in frames)
    vmin, vmax = 5 * np.floor(lo / 5), 5 * np.ceil(hi / 5)

    for ax, frame, (_, _, title) in zip(axes, frames, panels, strict=True):
        lats = np.sort(frame["lat"].unique())
        lons = np.sort(frame["lon"].unique())
        grid = frame.pivot(index="lat", columns="lon", values="speed_mean").to_numpy()
        mesh = ax.pcolormesh(lons, lats, grid, cmap=SEQ, vmin=vmin, vmax=vmax,
                             shading="nearest", rasterized=True)
        step = 4
        u = frame.pivot(index="lat", columns="lon", values="u_mean").to_numpy()
        v = frame.pivot(index="lat", columns="lon", values="v_mean").to_numpy()
        ax.quiver(lons[::step], lats[::step], u[::step, ::step], v[::step, ::step],
                  color=INK["surface"], width=0.010, scale=430,
                  headwidth=4, headlength=4.5)
        ax.plot(SITE_LON, SITE_LAT, marker="*", markersize=11,
                color=CATEGORICAL[1], markeredgecolor=INK["surface"],
                markeredgewidth=0.8, zorder=5)
        ax.annotate(SITE_NAME, (SITE_LON, SITE_LAT), textcoords="offset points",
                    xytext=(0, -16), ha="center", fontsize=7,
                    color=INK["primary"],
                    bbox={"facecolor": INK["surface"], "edgecolor": "none",
                          "alpha": 0.75, "pad": 1.0})
        panel_label(ax, title)
        ax.set_xlabel("longitude (deg E)")
        ax.grid(False)
        ax.set_aspect(1 / np.cos(np.radians(43.0)))
    axes[0].set_ylabel("latitude (deg N)")

    bar = fig.colorbar(mesh, ax=axes, pad=0.02, aspect=26)
    bar.set_label("mean speed (m/s)")
    bar.outline.set_visible(False)
    save(fig, "speed_map")


# ======================================================================== 3 --
def fig_profile_seasons(con) -> None:
    """What a balloon from one site flies through, by season."""
    cell = site_cell(con)
    seasons = [(1, 1, "Jan H1"), (4, 1, "Apr H1"), (7, 1, "Jul H1"), (10, 2, "Oct H2")]

    fig, axes = plt.subplots(1, 3, figsize=(6.2, 3.6), sharey=True)
    for colour, (month, half, label) in zip(CATEGORICAL, seasons, strict=True):
        df = con.execute("""
            SELECT level_hpa, alt_geom_mean_km, speed_mean, speed_p90,
                   dir_vector_mean_deg, constancy
            FROM fact_wind WHERE cell_id = ? AND month = ? AND bin = ?
            ORDER BY level_hpa DESC
        """, [cell, month, half]).fetchdf()
        axes[0].plot(df["speed_mean"], df["level_hpa"], color=colour, label=label)
        axes[0].plot(df["speed_p90"], df["level_hpa"], color=colour,
                     linewidth=0.9, linestyle=(0, (3, 2)), alpha=0.8)
        # A direction crossing north would draw a line straight across the
        # panel, so the series is broken wherever it wraps.
        deg = df["dir_vector_mean_deg"].to_numpy(dtype=float).copy()
        jump = np.abs(np.diff(deg)) > 180
        deg[1:][jump] = np.nan
        axes[1].plot(deg, df["level_hpa"], color=colour)
        axes[2].plot(df["constancy"], df["level_hpa"], color=colour, label=label)

    for ax in axes:
        level_axis(ax, df["level_hpa"])
    axes[0].invert_yaxis()                      # shared axis: invert once
    axes[0].set_ylabel("pressure (hPa)")
    axes[0].set_xlabel("mean speed (m/s)")
    axes[1].set_xlabel("direction wind is from")
    axes[1].set_xlim(0, 360)
    axes[1].set_xticks([0, 90, 180, 270, 360])
    axes[1].set_xticklabels(["N", "E", "S", "W", "N"])
    axes[2].set_xlabel("constancy")
    axes[2].set_xlim(0, 1.02)
    # Four curves of the same shape cannot be labelled where they are drawn
    # without the labels colliding at the jet, so the legend carries identity.
    # Two of the four hues sit below 3:1 on white, which is why a legend is
    # present rather than colour alone.
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=4,
               bbox_to_anchor=(0.5, -0.11))
    save(fig, "profile_seasons")


# ======================================================================== 4 --
def fig_hodograph(con) -> None:
    """How the wind turns with height, which a speed profile cannot show."""
    cell = site_cell(con)
    fig, ax = plt.subplots(figsize=(6.2, 2.5))

    for colour, (month, half, label) in zip(
        CATEGORICAL, [(1, 1, "Jan H1"), (7, 1, "Jul H1")], strict=False
    ):
        df = con.execute("""
            SELECT level_hpa, alt_geom_mean_km, u_mean, v_mean FROM fact_wind
            WHERE cell_id = ? AND month = ? AND bin = ? ORDER BY level_hpa DESC
        """, [cell, month, half]).fetchdf()
        ax.plot(df["u_mean"], df["v_mean"], color=colour, label=label, zorder=3)
        for mark in (850, 300, 100, 30, 10):
            row = df[df["level_hpa"] == mark]
            if row.empty:
                continue
            ax.plot(row["u_mean"], row["v_mean"], "o", markersize=3.4,
                    color=colour, markeredgecolor=INK["surface"],
                    markeredgewidth=0.7, zorder=4)
            ax.annotate(f"{mark}", (float(row["u_mean"].iloc[0]),
                                    float(row["v_mean"].iloc[0])),
                        textcoords="offset points",
                        xytext=(0, 6 if label.startswith("1 ") else -11),
                        ha="center", fontsize=6.2, color=colour)

    # The mean wind is almost purely zonal, so a square panel would be mostly
    # empty. Equal aspect is kept -- a hodograph with unequal axes would
    # misrepresent how much the wind turns -- and the panel is cropped instead.
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    ax.set_xlim(x0 - 3, x1 + 3)
    ax.set_ylim(min(y0 - 3, -6), max(y1 + 3, 6))
    ax.axhline(0, color=INK["axis"], linewidth=0.6, zorder=1)
    ax.axvline(0, color=INK["axis"], linewidth=0.6, zorder=1)
    ax.set_aspect("equal")
    ax.set_xlabel("eastward u (m/s)")
    ax.set_ylabel("northward v (m/s)")
    ax.legend(loc="lower right", ncols=2)
    save(fig, "hodograph")


# ======================================================================== 5 --
def fig_wind_rose(con) -> None:
    """The distribution of direction, which a mean direction hides."""
    classes = con.execute(
        "SELECT speed_class, label FROM dim_speed_class ORDER BY speed_class"
    ).fetchall()
    sectors = con.execute(
        "SELECT sector, centre_deg, compass_16 FROM dim_sector ORDER BY sector"
    ).fetchall()
    # set_theta_zero_location("N") with set_theta_direction(-1) already makes
    # the polar angle a clockwise-from-north bearing, which is exactly the
    # convention centre_deg is stored in. Converting to a maths angle as well
    # would rotate the whole rose.
    centres = np.radians([s[1] for s in sectors])
    width = 2 * np.pi / len(sectors) * 0.92
    ramp = [SEQ(x) for x in np.linspace(0.25, 0.95, len(classes))]

    fig, axes = plt.subplots(1, 2, figsize=(6.2, 3.4),
                             subplot_kw={"projection": "polar"})
    for ax, (month, half, title) in zip(
        axes, [(1, 1, "Jan H1"), (7, 1, "Jul H1")], strict=True
    ):
        bottom = np.zeros(len(sectors))
        for (klass, label), colour in zip(classes, ramp, strict=True):
            counts = con.execute("""
                SELECT s.sector, coalesce(r.count, 0) AS count
                FROM dim_sector s
                LEFT JOIN fact_wind_rose r
                  ON r.sector = s.sector AND r.speed_class = ?
                 AND r.month = ? AND r.bin = ? AND r.level_hpa = 300
                ORDER BY s.sector
            """, [klass, month, half]).fetchdf()
            pct = 100.0 * counts["count"].to_numpy() / 600.0
            ax.bar(centres, pct, width=width, bottom=bottom, color=colour,
                   edgecolor=INK["surface"], linewidth=0.7,
                   label=f"{label} m/s" if ax is axes[0] else None)
            bottom += pct
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_xticks(np.radians(np.arange(0, 360, 45)))
        ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"], fontsize=7)
        ax.tick_params(axis="y", labelsize=6)
        ax.set_rlabel_position(157.5)
        ax.tick_params(axis="x", pad=-1)
        ax.grid(color=INK["grid"], linewidth=0.5)
        panel_label(ax, title, inside=False)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=6, fontsize=6.5,
               bbox_to_anchor=(0.5, -0.06), title="speed class",
               title_fontsize=6.5)
    save(fig, "wind_rose")


# ======================================================================== 6 --
def fig_fitted_pdf(con) -> None:
    """The fitted families against the percentiles the database stores."""
    cell = site_cell(con)
    row = con.execute("""
        SELECT f.timebin_id, f.level_id, f.level_hpa, w.speed_p10, w.speed_p25,
               w.speed_p50, w.speed_p75, w.speed_p90, w.speed_p95, w.speed_max
        FROM fact_speed_fit f
        JOIN fact_wind w USING (timebin_id, level_id, cell_id)
        WHERE f.cell_id = ? AND f.month = 10 AND f.bin = 2 AND f.level_hpa = 300
          AND f.is_selected
    """, [cell]).fetchdf().iloc[0]

    fits = con.execute("""
        SELECT family, mu_ms, sigma_ms, weibull_shape, weibull_scale_ms,
               uniform_a_ms, uniform_b_ms, is_selected, delta_aic
        FROM fact_speed_fit
        WHERE cell_id = ? AND timebin_id = ? AND level_id = ?
        ORDER BY delta_aic
    """, [cell, int(row["timebin_id"]), int(row["level_id"])]).fetchdf()

    x = np.linspace(0.0, float(row["speed_max"]) * 1.15, 800)
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    names = {"normal": "normal", "weibull_min_loc0": "Weibull", "uniform": "uniform"}

    for colour, (_, f) in zip(CATEGORICAL, fits.iterrows(), strict=False):
        if f["family"] == "normal":
            y = np.exp(-((x - f["mu_ms"]) ** 2) / (2 * f["sigma_ms"] ** 2))
            y /= f["sigma_ms"] * np.sqrt(2 * np.pi)
        elif f["family"] == "weibull_min_loc0":
            k, lam = f["weibull_shape"], f["weibull_scale_ms"]
            with np.errstate(divide="ignore", invalid="ignore"):
                y = (k / lam) * (x / lam) ** (k - 1) * np.exp(-((x / lam) ** k))
            y = np.nan_to_num(y)
        else:
            a, b = f["uniform_a_ms"], f["uniform_b_ms"]
            y = np.where((x >= a) & (x <= b), 1.0 / (b - a), 0.0)
        style = "-" if f["is_selected"] else (0, (4, 2))
        ax.plot(x, y, color=colour, linestyle=style,
                label=f"{names[f['family']]}  ΔAIC {f['delta_aic']:.0f}")

    for key in ("p10", "p50", "p90", "p95"):
        value = float(row[f"speed_{key}"])
        ax.axvline(value, color=INK["axis"], linewidth=0.7, zorder=0)
        ax.annotate(key, (value, ax.get_ylim()[1]), textcoords="offset points",
                    xytext=(2, -9), fontsize=6.5, color=INK["muted"])

    ax.set_xlabel("wind speed (m/s)")
    ax.set_ylabel("probability density (m/s)$^{-1}$")
    ax.legend(loc="upper right")
    save(fig, "fitted_pdf")


# ======================================================================== 7 --
def fig_family_map(con) -> None:
    """Which family won where. Three colours, no ordering implied."""
    specs = [
        ("fact_speed_fit", "speed",
         ["weibull_min_loc0", "normal", "uniform"], ["Weibull", "normal", "uniform"]),
        ("fact_dir_fit", "direction",
         ["von_mises", "wrapped_normal", "circular_uniform"],
         ["von Mises", "wrapped normal", "circular uniform"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(6.2, 3.2), sharey=True)

    for ax, (table, what, families, labels) in zip(axes, specs, strict=True):
        # The majority family per (time bin, level) across the 570 grid points.
        df = con.execute(f"""
            SELECT timebin_id, level_hpa, family, count(*) AS cells
            FROM {table} WHERE is_selected
            GROUP BY timebin_id, level_hpa, family
            QUALIFY row_number() OVER (
                PARTITION BY timebin_id, level_hpa ORDER BY cells DESC, family
            ) = 1
        """).fetchdf()
        codes = {f: i for i, f in enumerate(families)}
        df["code"] = df["family"].map(codes).astype(float)
        levels = np.sort(df["level_hpa"].unique())[::-1]
        grid = (df.pivot(index="level_hpa", columns="timebin_id", values="code")
                  .reindex(levels).to_numpy(dtype=float))

        cmap = mpl.colors.ListedColormap(CATEGORICAL[:len(families)])
        ax.pcolormesh(np.arange(25), np.arange(len(levels) + 1), grid,
                      cmap=cmap, vmin=-0.5, vmax=len(families) - 0.5,
                      shading="flat", rasterized=True)
        ax.set_yticks(np.arange(len(levels)) + 0.5)
        ax.set_yticklabels([f"{int(v)}" if v >= 10 else f"{v:g}" for v in levels],
                           fontsize=5.2)
        for label in ax.get_yticklabels()[1::2]:
            label.set_visible(False)
        ax.invert_yaxis()
        bin_ticks(ax)
        ax.grid(False)
        handles = [mpl.patches.Patch(facecolor=c, label=name)
                   for c, name in zip(CATEGORICAL[:len(labels)], labels, strict=True)]
        ax.legend(handles=handles, loc="upper center", ncols=2,
                  bbox_to_anchor=(0.5, -0.24), fontsize=6.8,
                  title=f"{what} family", title_fontsize=6.8)
    axes[0].set_ylabel("pressure (hPa)")
    save(fig, "family_map")


# ======================================================================== 8 --
def fig_ambiguity(con) -> None:
    """How often the winner is not really a winner."""
    fig, axes = plt.subplots(1, 2, figsize=(6.2, 3.0), sharey=True)
    for ax, (table, what) in zip(
        axes, [("fact_speed_fit", "speed"), ("fact_dir_fit", "direction")], strict=True
    ):
        df = con.execute(f"""
            SELECT timebin_id, level_hpa,
                   100.0 * avg(CASE WHEN is_ambiguous THEN 1 ELSE 0 END) AS pct
            FROM {table} WHERE is_selected GROUP BY ALL
        """).fetchdf()
        levels = np.sort(df["level_hpa"].unique())[::-1]
        grid = df.pivot(index="level_hpa", columns="timebin_id",
                        values="pct").reindex(levels).to_numpy()
        mesh = ax.pcolormesh(np.arange(25), np.arange(len(levels) + 1), grid,
                             cmap=SEQ, vmin=0, vmax=100, shading="flat",
                             rasterized=True)
        ax.set_yticks(np.arange(len(levels)) + 0.5)
        ax.set_yticklabels([f"{int(v)}" if v >= 10 else f"{v:g}" for v in levels],
                           fontsize=5.2)
        for label in ax.get_yticklabels()[1::2]:
            label.set_visible(False)
        ax.invert_yaxis()
        bin_ticks(ax)
        ax.grid(False)
        panel_label(ax, what, colour=INK["primary"])
    axes[0].set_ylabel("pressure (hPa)")
    bar = fig.colorbar(mesh, ax=axes, pad=0.02, aspect=26)
    bar.set_label("grid points flagged ambiguous (%)")
    bar.outline.set_visible(False)
    save(fig, "ambiguity")


# ======================================================================== 9 --
def fig_effective_sample(con) -> None:
    """Why the AIC differences must be deflated before they are read."""
    df = con.execute("""
        SELECT level_hpa, avg(n_eff) AS n_eff, min(n_eff) AS lo, max(n_eff) AS hi,
               avg(lag1_autocorr) AS r1, avg(n) AS n
        FROM fact_wind GROUP BY ALL ORDER BY level_hpa DESC
    """).fetchdf()

    fig, axes = plt.subplots(1, 2, figsize=(6.2, 3.2), sharey=True)
    axes[0].fill_betweenx(df["level_hpa"], df["lo"], df["hi"],
                          color=BLUE_STEPS[1], linewidth=0)
    axes[0].plot(df["n_eff"], df["level_hpa"], color=CATEGORICAL[0], label="mean")
    axes[0].axvline(float(df["n"].mean()), color=CATEGORICAL[1],
                    linestyle=(0, (4, 2)), linewidth=1.2)
    axes[0].annotate("nominal n = 600", (float(df["n"].mean()), 7.0),
                     textcoords="offset points", xytext=(-5, 0), ha="right",
                     va="center", fontsize=7, color=CATEGORICAL[1])
    tip = df.loc[df["n_eff"].idxmin()]
    axes[0].annotate(f"effective n\n(min {tip['n_eff']:.0f})",
                     (float(tip["n_eff"]), float(tip["level_hpa"])),
                     textcoords="offset points", xytext=(-6, 0), ha="right",
                     va="center", fontsize=7, color=CATEGORICAL[0])
    axes[0].set_xlabel("sample size (band: range over grid points)")
    axes[0].set_xscale("log")
    axes[0].set_xlim(8, 900)

    axes[1].plot(df["r1"], df["level_hpa"], color=CATEGORICAL[0])
    axes[1].set_xlabel("lag-1 autocorrelation")
    axes[1].set_xlim(0, 1)
    for ax in axes:
        level_axis(ax, df["level_hpa"])
    axes[0].invert_yaxis()                      # shared axis: invert once
    axes[0].set_ylabel("pressure (hPa)")
    save(fig, "effective_sample")


# ======================================================================= 10 --
def fig_drift_cycle(con) -> None:
    """The quantity a launch actually cares about, through the year."""
    cell = site_cell(con)
    df = con.execute("""
        SELECT d.timebin_id, d.month, d.bin, d.dist_mean_km, d.dist_p50_km,
               d.dist_p90_km, d.dist_p95_km, d.dist_max_km, d.bearing_deg
        FROM fact_drift d WHERE d.cell_id = ? ORDER BY d.timebin_id
    """, [cell]).fetchdf()

    fig, axes = plt.subplots(2, 1, figsize=(6.2, 4.0), sharex=True,
                             gridspec_kw={"height_ratios": [2.1, 1]})
    x = df["timebin_id"] + 0.5
    axes[0].fill_between(x, df["dist_p50_km"], df["dist_p95_km"],
                         color=BLUE_STEPS[1], linewidth=0, label="p50 to p95")
    axes[0].plot(x, df["dist_mean_km"], color=CATEGORICAL[0], label="mean")
    axes[0].plot(x, df["dist_max_km"], color=CATEGORICAL[1], linewidth=1.0,
                 linestyle=(0, (4, 2)), label="max")
    worst = df.loc[df["dist_p95_km"].idxmax()]
    tag = f"{_MONTHS[int(worst['month']) - 1]} H{int(worst['bin'])}"
    axes[0].annotate(f"{tag}  p95 {worst['dist_p95_km']:.0f} km",
                     (worst["timebin_id"] + 0.5, worst["dist_p95_km"]),
                     textcoords="offset points", xytext=(-6, 6), ha="right",
                     fontsize=7, color=INK["primary"])
    axes[0].set_ylabel("horizontal drift (km)")
    axes[0].legend(loc="upper center", ncols=3, bbox_to_anchor=(0.5, 1.22))

    axes[1].plot(x, df["bearing_deg"], color=CATEGORICAL[2], marker="o",
                 markersize=3, linewidth=1.2)
    axes[1].set_ylim(0, 360)
    axes[1].set_yticks([0, 90, 180, 270, 360])
    axes[1].set_yticklabels(["N", "E", "S", "W", "N"])
    axes[1].set_ylabel("travel bearing")
    bin_ticks(axes[1])
    save(fig, "drift_cycle")


# ======================================================================= 11 --
def fig_diurnal(con) -> None:
    """The one table with a time of day in it, and how small the signal is."""
    cell = site_cell(con)
    df = con.execute("""
        SELECT d.hour_utc, h.hour_jst, h.jst_next_day, d.month, d.level_hpa,
               d.speed_mean
        FROM fact_wind_diurnal d JOIN dim_hour h USING (hour_utc)
        WHERE d.cell_id = ? AND d.bin = 1 AND d.level_hpa IN (1000, 850, 500, 300)
        ORDER BY d.level_hpa DESC, d.month, d.hour_utc
    """, [cell]).fetchdf()

    hours = sorted(df["hour_utc"].unique())
    labels = []
    for hour in hours:
        row = df[df["hour_utc"] == hour].iloc[0]
        suffix = "+1d" if row["jst_next_day"] else ""
        labels.append(f"{int(row['hour_jst']):02d}{suffix}")

    levels = [1000, 850, 500, 300]
    anomalies = {}
    for level in levels:
        sub = df[df["level_hpa"] == level]
        anomalies[level] = (
            sub.pivot(index="month", columns="hour_utc", values="speed_mean")
               .apply(lambda r: r - r.mean(), axis=1)
        )
    # One shared scale, so the four panels can be compared to each other.
    span = max(float(np.nanmax(np.abs(a.to_numpy()))) for a in anomalies.values())

    fig, axes = plt.subplots(1, 4, figsize=(6.2, 2.6), sharey=True)
    for ax, level in zip(axes, levels, strict=True):
        mesh = ax.pcolormesh(np.arange(len(hours) + 1), np.arange(13),
                             anomalies[level].to_numpy(), cmap=DIV,
                             vmin=-span, vmax=span, shading="flat",
                             rasterized=True)
        ax.set_xticks(np.arange(len(hours)) + 0.5)
        ax.set_xticklabels(labels, fontsize=6)
        ax.set_yticks(np.arange(12) + 0.5)
        ax.set_yticklabels(_MONTHS, fontsize=6)
        ax.grid(False)
        panel_label(ax, f"{level} hPa", inside=False)
        ax.set_xlabel("hour (JST)")
    axes[0].invert_yaxis()                      # shared axis: invert once
    axes[0].set_ylabel("month")
    bar = fig.colorbar(mesh, ax=axes, pad=0.02, aspect=22)
    bar.set_label("departure from the daily mean (m/s)")
    bar.outline.set_visible(False)
    save(fig, "diurnal")


FIGURES = {
    "seasonal_heatmap": fig_seasonal_heatmap,
    "speed_map": fig_speed_map,
    "profile_seasons": fig_profile_seasons,
    "hodograph": fig_hodograph,
    "wind_rose": fig_wind_rose,
    "fitted_pdf": fig_fitted_pdf,
    "family_map": fig_family_map,
    "ambiguity": fig_ambiguity,
    "effective_sample": fig_effective_sample,
    "drift_cycle": fig_drift_cycle,
    "diurnal": fig_diurnal,
}


def main(argv: list[str] | None = None) -> int:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", action="append", choices=sorted(FIGURES))
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not a.db.exists():
        raise SystemExit(f"データベースがありません: {a.db}")

    OUT = a.out
    apply_style()
    wanted = a.only or list(FIGURES)
    log.info("図を %s に書き出します", OUT)
    with duckdb.connect(str(a.db), read_only=True) as con:
        for name in wanted:
            FIGURES[name](con)
    log.info("%d 枚できました", len(wanted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
