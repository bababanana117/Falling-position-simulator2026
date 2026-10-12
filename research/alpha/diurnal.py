"""ERA5 の 1 時間値で、北海道上空の風に時間帯（朝・昼・夕・晩）の違いがあるかを見る。

本文の統計は JRA-3Q の 6 時間値（09/15/21/03 JST）から作っていて、時間帯は
区別していない。その判断が正しいかを、1 時間ごとの ERA5 で 1 か月ぶん確かめる。

時間帯は日本時間で 6 時間ずつに切る。

    朝 05–10 時 / 昼 11–16 時 / 夕 17–22 時 / 晩 23–04 時

日々の天気の違いを取り除くため、各日（日本時間の 0–23 時）の平均からの偏差で
比べる。日本時間で 24 時間そろう日だけを使う。

    python alpha/fetch_era5.py --month 2025-07
    python alpha/diurnal.py --month 2025-07
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.figure import Figure
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH))

from windclim.figures.coast import draw_coastline  # noqa: E402
from windclim.figures.plots import save  # noqa: E402
from windclim.figures.style import (  # noqa: E402
    CATEGORICAL,
    CMAP_SPEED,
    INK,
    apply_style,
    recessive_grid,
)
from windclim.regions import REGIONS  # noqa: E402
from windclim.stats.drift import FlightProfile, layer_seconds  # noqa: E402

G0 = 9.80665
JST = 9
#: 時間帯の名前と、その時間帯に入る JST の時
BLOCKS = {
    "朝": (5, 6, 7, 8, 9, 10),
    "昼": (11, 12, 13, 14, 15, 16),
    "夕": (17, 18, 19, 20, 21, 22),
    "晩": (23, 0, 1, 2, 3, 4),
}
BLOCK_LABEL = {
    "朝": "朝 (05–10 時)", "昼": "昼 (11–16 時)",
    "夕": "夕 (17–22 時)", "晩": "晩 (23–04 時)",
}
BLOCK_COLOUR = dict(zip(BLOCKS, CATEGORICAL, strict=True))
#: 本文の北海道の代表地点（VOISING）
SITE = (42.1823, 142.8510)
#: 日変化を 24 時間で描く気圧面
LEVELS_CURVE = (975, 850, 500, 200, 30, 10)
T_95 = 2.045   # t 分布の 97.5 % 点、自由度 29（30 日）

FIG_DIR = RESEARCH / "out" / "figures" / "alpha"
RES_DIR = HERE / "results"


# --- 読み込み ------------------------------------------------------------------

def load_month(year: int, month: int) -> xr.Dataset:
    """1 か月ぶんの u, v, 高度を 1 つにまとめる。気圧面は高度の低い順に並べる。"""
    parts = {}
    for var in ("u", "v", "z"):
        files = sorted((HERE / "data").glob(f"era5_{var}_{year:04d}{month:02d}*.nc"))
        if not files:
            raise SystemExit(f"{var} のファイルがありません。先に fetch_era5.py を実行してください")
        # dask を入れていないので open_mfdataset は使わず、1 日ずつ読んでつなぐ
        days = []
        for f in files:
            with xr.open_dataset(f) as one:
                days.append(one[var].load())
        parts[var] = xr.concat(days, "time")
    ds = xr.Dataset(parts).rename(latitude="lat", longitude="lon")
    ds["alt_km"] = ds["z"] / G0 / 1000.0
    ds = ds.drop_vars("z").sortby("level", ascending=False)
    # 日本時間
    jst = pd.DatetimeIndex(ds["time"].values) + pd.Timedelta(hours=JST)
    ds = ds.assign_coords(jst_hour=("time", jst.hour), jst_date=("time", jst.normalize()))
    # 日本時間で 24 時間そろう日だけを残す
    counts = pd.Series(1, index=jst.normalize()).groupby(level=0).sum()
    full = counts[counts == 24].index
    keep = np.isin(jst.normalize(), full)
    return ds.isel(time=np.flatnonzero(keep))


def area_weights(ds: xr.Dataset) -> xr.DataArray:
    return np.cos(np.deg2rad(ds["lat"])).broadcast_like(ds["lon"] + ds["lat"])


def area_mean(da: xr.DataArray, w: xr.DataArray) -> xr.DataArray:
    return da.weighted(w).mean(("lat", "lon"))


# --- 統計 ----------------------------------------------------------------------

def daily_anomaly(da: xr.DataArray) -> xr.DataArray:
    """各日（日本時間）の平均からの偏差。日々の天気の違いを取り除く。"""
    return da.groupby("jst_date") - da.groupby("jst_date").mean("time")


def by_hour(anom: xr.DataArray) -> xr.Dataset:
    """時（JST）ごとの偏差の平均と 95 % 信頼区間の半幅。標本は日。"""
    g = anom.groupby("jst_hour")
    n = anom.sizes["time"] / 24
    return xr.Dataset({"mean": g.mean("time"),
                       "ci": T_95 * g.std("time", ddof=1) / np.sqrt(n)})


def by_block(anom: xr.DataArray) -> xr.Dataset:
    """時間帯ごとの偏差の平均と 95 % 信頼区間。

    時間帯の中の 6 時間をまず日ごとに平均し、その日ごとの値を標本にする。
    同じ日の 6 時間は互いに独立ではないので、1 時間ずつを標本に数えてはいけない。
    """
    out = []
    for name, hours in BLOCKS.items():
        sel = anom.where(anom["jst_hour"].isin(hours), drop=True)
        per_day = sel.groupby("jst_date").mean("time")
        n = per_day.sizes["jst_date"]
        out.append(xr.Dataset({
            "mean": per_day.mean("jst_date"),
            "ci": T_95 * per_day.std("jst_date", ddof=1) / np.sqrt(n),
        }).expand_dims(block=[name]))
    return xr.concat(out, "block")


# --- 図 ------------------------------------------------------------------------

def _shade_blocks(ax) -> None:
    """時間帯を薄い色で塗る。晩は 0 時をまたぐので 1 時間ずつ塗る。"""
    for name, hours in BLOCKS.items():
        for h in hours:
            ax.axvspan(h - 0.5, h + 0.5, color=BLOCK_COLOUR[name], alpha=0.07, lw=0)


def fig_hourly_curves(hourly: xr.Dataset, alt_km: xr.DataArray, label: str) -> Figure:
    fig = Figure(figsize=(11, 6.4))
    axes = fig.subplots(2, 3, sharex=True).ravel()
    hours = np.arange(24)
    for ax, lev in zip(axes, LEVELS_CURVE, strict=True):
        m = hourly["mean"].sel(level=lev).reindex(jst_hour=hours).values
        c = hourly["ci"].sel(level=lev).reindex(jst_hour=hours).values
        _shade_blocks(ax)
        ax.axhline(0, color=INK["muted"], linewidth=0.8)
        ax.fill_between(hours, m - c, m + c, color=CATEGORICAL[0], alpha=0.25, lw=0)
        ax.plot(hours, m, color=CATEGORICAL[0], linewidth=1.8, marker="o", markersize=3)
        ax.set_title(f"{lev} hPa（約 {float(alt_km.sel(level=lev)):.1f} km）", fontsize=10)
        ax.set_xticks([0, 3, 6, 9, 12, 15, 18, 21])
        ax.set_xlim(-0.5, 23.5)
        recessive_grid(ax)
    for ax in axes[3:]:
        ax.set_xlabel("日本時間 [時]")
    for ax in axes[::3]:
        ax.set_ylabel("日平均からの偏差 [m/s]")
    handles = [Patch(color=BLOCK_COLOUR[b], alpha=0.25, label=BLOCK_LABEL[b]) for b in BLOCKS]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=9)
    fig.suptitle(f"ERA5 {label}: 領域平均風速の 1 日の変化（線は 30 日の平均、帯は 95 % 信頼区間）",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    return fig


def fig_block_profiles(speed_blk: xr.Dataset, vec_blk: xr.DataArray,
                       alt_km: xr.DataArray, label: str) -> Figure:
    fig = Figure(figsize=(10.5, 6.2))
    left, right = fig.subplots(1, 2, sharey=True)
    z = alt_km.values
    for name in BLOCKS:
        m = speed_blk["mean"].sel(block=name).values
        c = speed_blk["ci"].sel(block=name).values
        left.fill_betweenx(z, m - c, m + c, color=BLOCK_COLOUR[name], alpha=0.18, lw=0)
        left.plot(m, z, color=BLOCK_COLOUR[name], linewidth=1.8, label=BLOCK_LABEL[name])
        right.plot(vec_blk.sel(block=name).values, z, color=BLOCK_COLOUR[name], linewidth=1.8)
    left.axvline(0, color=INK["muted"], linewidth=0.8)
    left.set_xlabel("風速の偏差 [m/s]")
    left.set_ylabel("高度 [km]")
    left.set_title("風速（時間帯平均 − 日平均）", fontsize=10)
    right.set_xlabel("風ベクトルの偏差の大きさ [m/s]")
    right.set_title("風ベクトル（向きの変化も含む）", fontsize=10)
    for ax in (left, right):
        ax.axhline(30, color=INK["muted"], linewidth=0.8, linestyle=":")
        recessive_grid(ax)
    left.text(left.get_xlim()[0], 30.4, " 破裂高度 30 km", fontsize=8, color=INK["secondary"])
    left.set_ylim(0, 45)
    handles, labels = left.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=9, frameon=False)
    fig.suptitle(f"ERA5 {label}: 時間帯ごとの偏差の高度分布（帯は 95 % 信頼区間）", fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    return fig


def fig_breeze_map(du: xr.DataArray, dv: xr.DataArray, levels: tuple[int, ...],
                   label: str) -> Figure:
    box = REGIONS["hokkaido"]
    fig = Figure(figsize=(11, 4.9))
    axes = fig.subplots(1, len(levels))
    speed = np.hypot(du, dv)
    vmax = float(np.nanpercentile(speed.sel(level=list(levels)).values, 99))
    mesh = None
    for ax, lev in zip(axes, levels, strict=True):
        a, b = du.sel(level=lev), dv.sel(level=lev)
        mesh = ax.pcolormesh(a["lon"], a["lat"], np.hypot(a, b), cmap=CMAP_SPEED,
                             vmin=0, vmax=vmax, shading="nearest", zorder=1)
        step = 2
        ax.quiver(a["lon"].values[::step], a["lat"].values[::step],
                  a.values[::step, ::step], b.values[::step, ::step],
                  color=INK["primary"], scale=vmax * 9, scale_units="width",
                  width=0.004, zorder=4)
        draw_coastline(ax, box, linewidth=0.8)
        ax.set_xlim(box.west, box.east)
        ax.set_ylim(box.south, box.north)
        ax.set_aspect(1 / np.cos(np.radians(43.2)))
        ax.set_title(f"{lev} hPa", fontsize=10)
        ax.set_xlabel("経度 [度]")
    axes[0].set_ylabel("緯度 [度]")
    bar = fig.colorbar(mesh, ax=list(axes), shrink=0.85, pad=0.02)
    bar.set_label("差のベクトルの大きさ [m/s]")
    fig.suptitle(f"ERA5 {label}: 昼（11–16 時）の平均風 − 晩（23–04 時）の平均風", fontsize=11)
    return fig


def fig_drift(site_blk: pd.DataFrame, hourly_site: pd.DataFrame, label: str) -> Figure:
    fig = Figure(figsize=(11, 4.4))
    left, right = fig.subplots(1, 2, gridspec_kw={"width_ratios": (1.5, 1.0)})
    h = hourly_site.index.to_numpy()
    for col, colour, name in (("east_km", CATEGORICAL[0], "東西（東が正）"),
                              ("north_km", CATEGORICAL[1], "南北（北が正）")):
        m, c = hourly_site[col].to_numpy(), hourly_site[col + "_ci"].to_numpy()
        left.fill_between(h, m - c, m + c, color=colour, alpha=0.2, lw=0)
        left.plot(h, m, color=colour, linewidth=1.8, marker="o", markersize=3, label=name)
    _shade_blocks(left)
    left.axhline(0, color=INK["muted"], linewidth=0.8)
    left.set_xticks([0, 3, 6, 9, 12, 15, 18, 21])
    left.set_xlim(-0.5, 23.5)
    left.set_xlabel("打ち上げ時刻（日本時間）[時]")
    left.set_ylabel("落下点の偏差 [km]")
    left.set_title("打ち上げ時刻ごとの落下点（日平均からの偏差）", fontsize=10)
    left.legend(loc="upper left", fontsize=9, frameon=False)
    recessive_grid(left)

    for name in BLOCKS:
        r = site_blk.loc[name]
        right.errorbar(r["east_km"], r["north_km"], xerr=r["east_km_ci"], yerr=r["north_km_ci"],
                       fmt="o", color=BLOCK_COLOUR[name], markersize=7, capsize=3,
                       label=BLOCK_LABEL[name])
    right.axhline(0, color=INK["muted"], linewidth=0.8)
    right.axvline(0, color=INK["muted"], linewidth=0.8)
    lim = float(np.nanmax(np.abs(site_blk[["east_km", "north_km"]].to_numpy())
                          + site_blk[["east_km_ci", "north_km_ci"]].to_numpy())) * 1.3
    right.set_xlim(-lim, lim)
    right.set_ylim(-lim, lim)
    right.set_aspect("equal")
    right.set_xlabel("東西の偏差 [km]")
    right.set_ylabel("南北の偏差 [km]")
    right.set_title("時間帯ごとの平均（誤差棒は 95 % 信頼区間）", fontsize=10)
    right.legend(loc="upper left", fontsize=8, frameon=False)
    recessive_grid(right)
    fig.suptitle(f"ERA5 {label}: 代表地点から上げた場合の落下点と打ち上げ時刻", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def fig_vs_jra3q(era5_diff: xr.DataArray, era5_ci: xr.DataArray, era5_alt: xr.DataArray,
                 jra_diff: np.ndarray, jra_alt: np.ndarray, label: str) -> Figure:
    fig = Figure(figsize=(6.4, 5.6))
    ax = fig.subplots()
    sel = era5_diff["level"] >= 300
    z = era5_alt.where(sel, drop=True).values
    m = era5_diff.where(sel, drop=True).values
    c = era5_ci.where(sel, drop=True).values
    ax.fill_betweenx(z, m - c, m + c, color=CATEGORICAL[0], alpha=0.2, lw=0)
    ax.plot(m, z, color=CATEGORICAL[0], linewidth=1.8, label=f"ERA5 {label}（1 か月）")
    ax.plot(jra_diff, jra_alt, color=CATEGORICAL[1], linewidth=1.8, linestyle="--",
            label="JRA-3Q 7 月（2016–2025 年）")
    ax.axvline(0, color=INK["muted"], linewidth=0.8)
    ax.set_xlabel("03 時 − 15 時（日本時間）の平均風速差 [m/s]")
    ax.set_ylabel("高度 [km]")
    ax.set_ylim(0, 10)
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    recessive_grid(ax)
    ax.set_title("北海道領域の平均。帯は ERA5 の 95 % 信頼区間", fontsize=10)
    fig.tight_layout()
    return fig


def fig_hourly_jumps(jumps: xr.DataArray, label: str) -> Figure:
    """1 時間ごとの風の変化量を、変化の始まる UTC の時刻ごとに並べる。

    ERA5 は 09–21 UTC と 21–09 UTC の 12 時間ごとに観測を取り込んで解析を作る。
    その境目（09→10 UTC と 21→22 UTC）で風が不自然に跳ぶなら、日変化に見えるものの
    一部は大気ではなく解析の作り方から来ている。
    """
    fig = Figure(figsize=(10, 4.6))
    ax = fig.subplots()
    hours = jumps["utc_hour"].values
    colours = (*CATEGORICAL, INK["secondary"], INK["muted"])
    for lev, colour in zip((975, 850, 500, 200, 30, 10), colours, strict=True):
        y = jumps.sel(level=lev).values
        ax.plot(hours, y / np.median(y), color=colour, linewidth=1.6, marker="o", markersize=3,
                label=f"{lev} hPa")
    for h in (9, 21):
        ax.axvline(h, color=INK["primary"], linewidth=1.0, linestyle=":")
    ax.axhline(1.0, color=INK["muted"], linewidth=0.8)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f"{h:02d}→{(h + 1) % 24:02d}" for h in range(0, 24, 3)])
    ax.set_xlabel("変化の区間（UTC）。点線は ERA5 の 12 時間の解析窓の境目（09→10、21→22 UTC）")
    ax.set_ylabel("1 時間の風の変化量（中央値との比）")
    ax.legend(loc="upper left", ncol=3, fontsize=9, frameon=False)
    recessive_grid(ax)
    ax.set_title(f"ERA5 {label}: 1 時間ごとの風ベクトルの変化量 |V(t+1) − V(t)|（領域平均）",
                 fontsize=11)
    fig.tight_layout()
    return fig


# --- 本体 ----------------------------------------------------------------------

def jra3q_july(level_alt: xr.DataArray) -> tuple[np.ndarray, np.ndarray] | None:
    path = RESEARCH / "out" / "netcdf" / "jra3q_windclim_hokkaido_2016-2025_v1.nc"
    if not path.exists():
        return None
    from windclim.stats.spatial import area_mean as jra_area_mean  # noqa: PLC0415

    with xr.open_dataset(path) as ds:
        hr = jra_area_mean(ds, "hr_speed_mean").sel(month=7).mean("bin")
        # hour は UTC。18 UTC = 03 JST、06 UTC = 15 JST
        diff = (hr.sel(hour=18) - hr.sel(hour=6)).values
        alt = (jra_area_mean(ds, "alt_geom_mean_km").sel(month=7).mean("bin")
               .sel(level=ds["level_low"].values).values)
    order = np.argsort(alt)
    return diff[order], alt[order]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default="2025-07", help="YYYY-MM")
    a = ap.parse_args(argv)
    year, month = (int(x) for x in a.month.split("-"))
    label = f"{year} 年 {month} 月"
    apply_style(japanese=True)

    ds = load_month(year, month)
    n_days = ds.sizes["time"] // 24
    w = area_weights(ds)
    alt_km = area_mean(ds["alt_km"], w).mean("time")

    # 0. 解析窓の境目での跳び: 1 時間ごとの風ベクトルの変化量（格子ごとに求めて領域平均）
    dvec = np.hypot(ds["u"].diff("time"), ds["v"].diff("time"))
    step_h = (ds["time"].diff("time") / np.timedelta64(1, "h")).values
    dvec = dvec.isel(time=np.flatnonzero(step_h == 1))
    start_utc = pd.DatetimeIndex(dvec["time"].values - np.timedelta64(1, "h")).hour
    jumps = (area_mean(dvec, w).assign_coords(utc_hour=("time", start_utc))
             .groupby("utc_hour").mean())
    jump_ratio = {int(lv): {f"{h:02d}-{h + 1:02d}UTC": round(float(
        jumps.sel(level=lv, utc_hour=h) / jumps.sel(level=lv).median()), 2) for h in (9, 21)}
        for lv in (975, 850, 500, 200, 30, 10)}

    # 1. 領域平均の風速と風ベクトル
    speed = area_mean(np.hypot(ds["u"], ds["v"]), w)
    u_m, v_m = area_mean(ds["u"], w), area_mean(ds["v"], w)
    speed_anom = daily_anomaly(speed)
    hourly = by_hour(speed_anom)
    speed_blk = by_block(speed_anom)
    u_blk, v_blk = by_block(daily_anomaly(u_m)), by_block(daily_anomaly(v_m))
    vec_blk = np.hypot(u_blk["mean"], v_blk["mean"])
    # 比べる物差し: 日平均風速そのものの日々のばらつき
    day_sd = speed.groupby("jst_date").mean("time").std("jst_date", ddof=1)

    # 2. 地表付近の海陸風: 昼 − 晩 を格子ごとに
    def block_mean(da, name):
        return da.where(da["jst_hour"].isin(BLOCKS[name]), drop=True).mean("time")

    du = block_mean(ds["u"], "昼") - block_mean(ds["u"], "晩")
    dv = block_mean(ds["v"], "昼") - block_mean(ds["v"], "晩")

    # 3. 落下点（本文と同じ閉形式。風は打ち上げ時刻・地点で固定）
    flight = FlightProfile()
    alt_cell = ds["alt_km"].mean("time").transpose("level", "lat", "lon").values * 1000.0
    weights = xr.DataArray(layer_seconds(alt_cell, flight), dims=("level", "lat", "lon"),
                           coords={"level": ds["level"], "lat": ds["lat"], "lon": ds["lon"]})
    east = (ds["u"] * weights).sum("level") / 1000.0
    north = (ds["v"] * weights).sum("level") / 1000.0
    site = {"lat": ds["lat"].sel(lat=SITE[0], method="nearest").item(),
            "lon": ds["lon"].sel(lon=SITE[1], method="nearest").item()}
    e_site, n_site = east.sel(**site), north.sel(**site)
    e_anom, n_anom = daily_anomaly(e_site), daily_anomaly(n_site)
    eh, nh = by_hour(e_anom), by_hour(n_anom)
    hourly_site = pd.DataFrame({
        "east_km": eh["mean"].values, "east_km_ci": eh["ci"].values,
        "north_km": nh["mean"].values, "north_km_ci": nh["ci"].values,
    }, index=eh["jst_hour"].values)
    eb, nb = by_block(e_anom), by_block(n_anom)
    site_blk = pd.DataFrame({
        "east_km": eb["mean"].values, "east_km_ci": eb["ci"].values,
        "north_km": nb["mean"].values, "north_km_ci": nb["ci"].values,
    }, index=list(BLOCKS))
    dist = np.hypot(e_site, n_site)
    # 物差し: 1 日（24 時間）遅れたときの落下点の移動と、日平均の落下点の日々のばらつき
    slip = np.hypot(e_site.shift(time=-24) - e_site, n_site.shift(time=-24) - n_site)
    # 高度帯ごとの寄与（昼 − 晩 の東西・南北の差）
    bands = {"0–3 km": (0, 3), "3–20 km": (3, 20), "20–30 km": (20, 30.1)}
    contrib = {}
    for bname, (lo, hi) in bands.items():
        mask = xr.DataArray((alt_km.values >= lo) & (alt_km.values < hi), dims="level",
                            coords={"level": ds["level"]})
        eb_ = ((ds["u"] * weights).where(mask).sum("level") / 1000.0).sel(**site)
        nb_ = ((ds["v"] * weights).where(mask).sum("level") / 1000.0).sel(**site)
        de = float(block_mean(eb_, "昼") - block_mean(eb_, "晩"))
        dn = float(block_mean(nb_, "昼") - block_mean(nb_, "晩"))
        contrib[bname] = {"east_km": round(de, 2), "north_km": round(dn, 2)}

    # 4. JRA-3Q との比較（03 時 − 15 時）
    h03 = speed_anom.where(speed_anom["jst_hour"] == 3, drop=True).groupby("jst_date").mean()
    h15 = speed_anom.where(speed_anom["jst_hour"] == 15, drop=True).groupby("jst_date").mean()
    d0315 = h03 - h15
    diff_mean = d0315.mean("jst_date")
    diff_ci = T_95 * d0315.std("jst_date", ddof=1) / np.sqrt(d0315.sizes["jst_date"])
    jra = jra3q_july(alt_km)

    # 図
    tag = f"{year:04d}{month:02d}"
    out = []
    out.append(save(fig_hourly_curves(hourly, alt_km, label), FIG_DIR,
                    f"E1-{tag}", "hourly_curves"))
    out.append(save(fig_block_profiles(speed_blk, vec_blk, alt_km, label), FIG_DIR,
                    f"E2-{tag}", "block_profiles"))
    out.append(save(fig_breeze_map(du, dv, (975, 850), label), FIG_DIR,
                    f"E3-{tag}", "day_night_map"))
    out.append(save(fig_drift(site_blk, hourly_site, label), FIG_DIR,
                    f"E4-{tag}", "drift_by_launch_hour"))
    out.append(save(fig_hourly_jumps(jumps, label), FIG_DIR, f"E6-{tag}", "hourly_jumps"))
    if jra is not None:
        out.append(save(fig_vs_jra3q(diff_mean, diff_ci, alt_km, *jra, label), FIG_DIR,
                        f"E5-{tag}", "vs_jra3q"))

    # 数字
    RES_DIR.mkdir(parents=True, exist_ok=True)
    prof = pd.DataFrame({"level_hpa": alt_km["level"].values, "alt_km": alt_km.values,
                         "day_to_day_sd_ms": day_sd.values})
    for name in BLOCKS:
        prof[f"{name}_speed_anom_ms"] = speed_blk["mean"].sel(block=name).values
        prof[f"{name}_speed_ci_ms"] = speed_blk["ci"].sel(block=name).values
        prof[f"{name}_vector_anom_ms"] = vec_blk.sel(block=name).values
    prof.to_csv(RES_DIR / f"block_profile_{tag}.csv", index=False, float_format="%.3f")
    site_blk.to_csv(RES_DIR / f"site_drift_by_block_{tag}.csv", float_format="%.2f")

    def lev_stats(lev):
        s = speed_blk.sel(level=lev)
        return {b: [round(float(s["mean"].sel(block=b)), 2), round(float(s["ci"].sel(block=b)), 2)]
                for b in BLOCKS} | {"day_to_day_sd": round(float(day_sd.sel(level=lev)), 2),
                                    "alt_km": round(float(alt_km.sel(level=lev)), 2)}

    summary = {
        "month": a.month, "n_days": int(n_days),
        "grid": [int(ds.sizes["lat"]), int(ds.sizes["lon"])],
        "site_cell": site,
        "speed_block_anom_ms[mean,ci95]": {int(lv): lev_stats(lv)
                                           for lv in (1000, 975, 925, 850, 700, 500, 300,
                                                      200, 100, 50, 30, 10, 5, 3, 1)},
        "max_abs_block_speed_anom": {
            "below_3km": round(float(np.abs(speed_blk["mean"].where(alt_km < 3)).max()), 2),
            "3_to_30km": round(float(np.abs(
                speed_blk["mean"].where((alt_km >= 3) & (alt_km < 30))).max()), 2),
            "above_30km": round(float(np.abs(speed_blk["mean"].where(alt_km >= 30)).max()), 2),
        },
        "site_drift": {
            "mean_distance_km": round(float(dist.mean()), 1),
            "block_anom_km": site_blk.round(2).to_dict(orient="index"),
            "noon_minus_night_km": {
                "east": round(float(site_blk.loc["昼", "east_km"]
                                    - site_blk.loc["晩", "east_km"]), 2),
                "north": round(float(site_blk.loc["昼", "north_km"]
                                     - site_blk.loc["晩", "north_km"]), 2),
            },
            "noon_minus_night_by_band_km": contrib,
            "slip_24h_median_km": round(float(slip.median()), 1),
            "daily_mean_distance_sd_km": round(float(
                np.hypot(e_site.groupby("jst_date").mean().std(ddof=1),
                         n_site.groupby("jst_date").mean().std(ddof=1))), 1),
        },
        "breeze_975hPa_max_diff_ms": round(float(np.hypot(du, dv).sel(level=975).max()), 2),
        "breeze_850hPa_max_diff_ms": round(float(np.hypot(du, dv).sel(level=850).max()), 2),
        "diff_03_minus_15_ms": {int(lv): [round(float(diff_mean.sel(level=lv)), 2),
                                          round(float(diff_ci.sel(level=lv)), 2)]
                                for lv in (975, 925, 850, 700, 500, 300)},
        "jump_ratio_at_window_edges": jump_ratio,
        "figures": [str(p[0].relative_to(RESEARCH)) for p in out],
    }
    (RES_DIR / f"summary_{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
