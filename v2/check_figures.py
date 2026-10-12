"""出来上がった DuckDB だけを読んで、確認用の地図を描く。

上流のパイプラインにも NetCDF にも頼らないので、配った先でも同じ図が描ける。

    python v2/check_figures.py            # v2/check/*.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import matplotlib as mpl
import numpy as np

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "research"))

import os  # noqa: E402

from jpduck.config import DB_PATH as _DB  # noqa: E402

DB_PATH = Path(os.environ.get("JPDUCK_DB", _DB))

from windclim.figures.coast import draw_coastline  # noqa: E402
from windclim.figures.style import apply_style  # noqa: E402
from windclim.regions import JAPAN  # noqa: E402

OUT = HERE / "check"
KM_PER_DEG = 111.195


def _map(ax):
    draw_coastline(ax, JAPAN, linewidth=0.6)
    ax.set_xlim(JAPAN.west, JAPAN.east)
    ax.set_ylim(JAPAN.south, JAPAN.north)
    ax.set_aspect(1 / np.cos(np.radians(35)))
    ax.tick_params(labelsize=8)


def fig_speed(con) -> Path:
    """1 月前半と 7 月後半、3 つの高さの平均風速と平均風向。"""
    fig, axes = plt.subplots(2, 3, figsize=(15, 9.6))
    for r, (month, half, name) in enumerate(((1, 1, "1月前半"), (7, 2, "7月後半"))):
        for c, level in enumerate((850, 200, 10)):
            df = con.execute("""
                SELECT lat, lon, speed_mean, u_mean, v_mean
                FROM fact_wind WHERE month = ? AND bin = ? AND level_hpa = ?
            """, [month, half, level]).fetchdf()
            lat = np.sort(df["lat"].unique())
            lon = np.sort(df["lon"].unique())
            grid = df.pivot(index="lat", columns="lon", values="speed_mean").loc[lat, lon]
            ax = axes[r, c]
            mesh = ax.pcolormesh(lon, lat, grid.values, cmap="viridis", shading="nearest",
                                 vmin=0, vmax={850: 20, 200: 80, 10: 30}[level])
            sub = df[(np.isin(df["lat"], lat[::5])) & (np.isin(df["lon"], lon[::5]))]
            ax.quiver(sub["lon"], sub["lat"], sub["u_mean"], sub["v_mean"], color="white",
                      scale={850: 250, 200: 900, 10: 350}[level], width=0.004)
            _map(ax)
            ax.set_title(f"{name}・{level} hPa の平均風", fontsize=11)
            fig.colorbar(mesh, ax=ax, shrink=0.75, label="m/s")
    fig.suptitle("日本全国 v2：平均風速（色）と平均風（矢印、風が向かう向き）", fontsize=13)
    fig.tight_layout()
    out = OUT / "speed_maps.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def fig_drift(con) -> Path:
    """12 か月の平均落下位置（前半）。矢印は実寸。"""
    fig, axes = plt.subplots(3, 4, figsize=(16, 12.5))
    df = con.execute("""
        SELECT month, lat, lon, east_m / 1000 AS east_km, north_m / 1000 AS north_km,
               dist_mean_km
        FROM fact_drift WHERE bin = 1
    """).fetchdf()
    lat_all = np.sort(df["lat"].unique())
    lon_all = np.sort(df["lon"].unique())
    for k, ax in enumerate(axes.ravel()):
        m = df[df["month"] == k + 1]
        grid = m.pivot(index="lat", columns="lon", values="dist_mean_km").loc[lat_all, lon_all]
        mesh = ax.pcolormesh(lon_all, lat_all, grid.values, cmap="magma_r", vmin=0, vmax=300,
                             shading="nearest")
        sub = m[np.isin(m["lat"], lat_all[2::8]) & np.isin(m["lon"], lon_all[2::10])]
        dlon = sub["east_km"] / (KM_PER_DEG * np.cos(np.radians(sub["lat"])))
        dlat = sub["north_km"] / KM_PER_DEG
        ax.quiver(sub["lon"], sub["lat"], dlon, dlat, angles="xy", scale_units="xy", scale=1,
                  color="#0072B2", width=0.004)
        _map(ax)
        ax.set_title(f"{k + 1} 月前半", fontsize=11)
    fig.colorbar(mesh, ax=list(axes.ravel()), shrink=0.6, label="平均の飛行距離 [km]")
    fig.suptitle("日本全国 v2：平均落下位置（矢印は実寸、矢先が平均落下点）", fontsize=13)
    out = OUT / "drift_maps.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def fig_sites(con) -> Path:
    """各地の 1 年：200 hPa の平均風速と 10 hPa の定常度。"""
    sites = {"稚内": (45.415, 141.673), "大樹町": (42.506, 143.440), "仙台": (38.268, 140.870),
             "東京": (35.681, 139.767), "潮岬": (33.437, 135.762), "福岡": (33.590, 130.402),
             "那覇": (26.212, 127.679), "父島": (27.094, 142.192)}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 5.4))
    for name, (la, lo) in sites.items():
        cell = con.execute("SELECT cell_id, distance_km FROM nearest_cell(?, ?)",
                           [la, lo]).fetchone()
        df = con.execute("""
            SELECT month, bin, level_hpa, speed_mean, constancy FROM fact_wind
            WHERE cell_id = ? AND level_hpa IN (200, 10) ORDER BY month, bin
        """, [cell[0]]).fetchdf()
        x = (df["month"] - 1) * 2 + df["bin"] - 1
        s = df[df["level_hpa"] == 200]
        c = df[df["level_hpa"] == 10]
        a1.plot(x[s.index], s["speed_mean"], marker="o", ms=3, label=f"{name}（{cell[1]:.0f} km）")
        a2.plot(x[c.index], c["constancy"], marker="o", ms=3, label=name)
    for ax, title in ((a1, "200 hPa（約 12 km）の平均風速 [m/s]"),
                      (a2, "10 hPa（約 31 km）の定常度（1 = 風向が一定）")):
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels([f"{m}月" for m in range(1, 13)])
        ax.set_title(title, fontsize=11)
        ax.grid(alpha=0.3)
    a1.legend(fontsize=8, ncol=2, title="地点（最寄り格子点までの距離）", title_fontsize=8)
    fig.suptitle("日本全国 v2：各地の最寄り格子点の 1 年", fontsize=13)
    fig.tight_layout()
    out = OUT / "sites.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def main() -> int:
    apply_style(japanese=True)
    OUT.mkdir(exist_ok=True)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for f in (fig_speed, fig_drift, fig_sites):
            print(f(con))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
