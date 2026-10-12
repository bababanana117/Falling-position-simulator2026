"""The numbers the report quotes, printed so a reader can re-derive them.

Every figure in the text that is not read off a plot comes from here. Keeping
them in one function means the report and the data cannot drift apart silently:
re-run ``windclim summary`` and the values in the prose are checkable.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from ..stats.spatial import area_mean, spatial_range

__all__ = ["REFERENCE_LEVELS", "summarise"]

#: Levels the report keeps referring to, with the flight phase each one names.
REFERENCE_LEVELS: tuple[tuple[float, str], ...] = (
    (850.0, "下層 (約1.5 km)"),
    (500.0, "中層 (約5.5 km)"),
    (200.0, "ジェット (約12 km)"),
    (100.0, "圏界面上 (約16 km)"),
    (30.0, "成層圏 (約24 km)"),
    (10.0, "破裂高度帯 (約31 km)"),
    (3.0, "上端 (約40 km)"),
)

SEASONS = {"冬 (12-2月)": (12, 1, 2), "春 (3-5月)": (3, 4, 5),
           "夏 (6-8月)": (6, 7, 8), "秋 (9-11月)": (9, 10, 11)}


def _months_present(ds: xr.Dataset, months: tuple[int, ...]) -> list[int]:
    have = set(int(m) for m in ds["month"].values)
    return [m for m in months if m in have]


def summarise(ds: xr.Dataset, region: str) -> dict:
    """Collect the quotable numbers for one region."""
    out: dict = {
        "region": region,
        "period": ds.attrs.get("period", ""),
        # The formatter must not invent bin names; it prints what the data says.
        "bin_labels": [str(x) for x in ds.attrs.get("bin_labels", [])],
    }

    # Guarded by month, so a partial dataset (one month, a smoke run) still
    # summarises instead of raising on a month it does not have.
    n = ds["n"].isel(level=0, lat=0, lon=0)
    have = {int(m) for m in ds["month"].values}
    # Every (month, bin) the dataset holds, named by the label the data itself
    # records. The old version listed four fixed week labels, which quietly
    # reported nothing once the binning changed.
    labels = [str(x) for x in ds.attrs.get("bin_labels", [])]
    counts = {}
    for month in sorted(have):
        for bi, index in enumerate(int(b) for b in ds["bin"].values):
            name = labels[bi] if bi < len(labels) else f"ビン {index}"
            counts[f"{month}月 {name}"] = int(n.sel(month=month, bin=index))
    out["n"] = counts
    out["n_max"] = int(ds["n"].max())
    out["n_eff_ratio_median"] = float((ds["n_eff"] / ds["n"]).median())
    out["n_eff_median"] = float(ds["n_eff"].median())

    alt = area_mean(ds, "alt_geom_mean_km")
    out["levels"] = {}
    for lv, label in REFERENCE_LEVELS:
        if lv not in set(float(x) for x in ds["level"].values):
            continue
        row = {"label": label, "alt_km": float(alt.sel(level=lv).mean())}
        for sname, months in SEASONS.items():
            ms = _months_present(ds, months)
            if not ms:
                continue
            sub = ds.sel(month=ms)
            row[sname] = {
                "speed_mean": float(area_mean(sub, "speed_mean").sel(level=lv).mean()),
                "speed_p90": float(area_mean(sub, "speed_p90").sel(level=lv).mean()),
                "u_mean": float(area_mean(sub, "u_mean").sel(level=lv).mean()),
                "constancy": float(area_mean(sub, "constancy").sel(level=lv).mean()),
                "dir": float(
                    (np.degrees(np.arctan2(
                        float(area_mean(sub, "u_mean").sel(level=lv).mean()),
                        float(area_mean(sub, "v_mean").sel(level=lv).mean()),
                    )) + 180.0) % 360.0
                ),
            }
        out["levels"][lv] = row

    # Where and when the column is calmest / roughest, 0-30 km.
    a = alt.values
    spd = area_mean(ds, "speed_mean").values
    con = area_mean(ds, "constancy").values
    band = (a >= 0.0) & (a <= 30.0)
    col = np.where(band, spd, np.nan)
    colmean = np.nanmean(col, axis=-1)
    mi, wi = np.unravel_index(np.nanargmin(colmean), colmean.shape)
    Mi, Wi = np.unravel_index(np.nanargmax(colmean), colmean.shape)
    out["column_0_30km"] = {
        "calmest": {"month": int(ds["month"].values[mi]), "bin": int(ds["bin"].values[wi]),
                    "mean_speed": float(colmean[mi, wi])},
        "roughest": {"month": int(ds["month"].values[Mi]), "bin": int(ds["bin"].values[Wi]),
                     "mean_speed": float(colmean[Mi, Wi])},
    }

    # The halves where the mean direction stops meaning anything.
    worst = np.nanmin(np.where(band, con, np.nan), axis=-1)
    out["lowest_constancy_bins"] = [
        {"month": int(ds["month"].values[i]), "bin": int(ds["bin"].values[j]),
         "constancy": float(worst[i, j])}
        for i, j in sorted(
            np.ndindex(worst.shape), key=lambda ij: (np.inf if np.isnan(worst[ij]) else worst[ij])
        )[:5]
    ]

    # Is one column enough to describe the region?
    out["max_spatial_range_speed"] = float(
        np.nanmax(spatial_range(ds, "speed_mean").values)
    )

    # How far the simulator's ISA assumption is from the real thing.
    from ..stats.altitude import isa_altitude_from_pressure

    isa_km = isa_altitude_from_pressure(ds["level"].values) / 1000.0
    diff_m = (alt.values - isa_km) * 1000.0
    months_axis = [int(m) for m in ds["month"].values]

    def _season_max_abs(months: tuple[int, ...]) -> float:
        # Index by position in the month axis, not by month number: a dataset
        # that starts somewhere other than January would otherwise pick the
        # wrong rows, and one missing the season entirely would reduce over an
        # empty array.
        idx = [months_axis.index(m) for m in months if m in months_axis]
        if not idx:
            return float("nan")
        return float(np.nanmax(np.abs(diff_m[idx])))

    out["isa_error_m"] = {
        "max_abs": float(np.nanmax(np.abs(diff_m))),
        "winter_max_abs": _season_max_abs((12, 1, 2)),
        "summer_max_abs": _season_max_abs((6, 7, 8)),
    }
    if "drift_east_m" in ds and "alt_geom_mean_m" in ds:
        out["ceiling_share"] = ceiling_share(ds)

    if "shear_mag" in ds:
        sh = area_mean(ds, "shear_mag").values

        def _peak(mask):
            if not mask.any():
                return None
            k = np.unravel_index(np.nanargmax(np.where(mask, sh, np.nan)), sh.shape)
            return {
                "value": float(sh[k]),
                "month": int(ds["month"].values[k[0]]),
                "bin": int(ds["bin"].values[k[1]]),
                "alt_km": float(a[k[0], k[1], k[2]]),
            }

        # The surface layer almost always wins on shear -- friction against the
        # ground makes it so -- but the payload crosses it in a couple of minutes.
        # The free-atmosphere peak is the one that matters for the flight.
        out["max_shear"] = _peak(band)
        out["max_shear_free_air"] = _peak(band & (a >= 2.0))
    return out


#: The top of Open-Meteo's pressure levels, which is where the existing
#: simulator stops having real wind and starts extrapolating.
OPEN_METEO_CEILING_M = 23800.0


def ceiling_share(ds: xr.Dataset, ceiling_m: float = OPEN_METEO_CEILING_M) -> dict:
    """How much of the horizontal displacement comes from above a given altitude.

    Each level is weighted by the time the payload spends in it, so this measures
    what the existing simulator actually loses by extrapolating above its top
    pressure level -- rather than what the altitude range alone suggests.

    The ratio can exceed 1. The denominator is the *net* displacement, so when an
    upper easterly partly cancels the flow beneath it, the net shrinks while the
    upper contribution does not. A value above 1 means ignoring the upper layer
    gets the direction wrong, not merely the distance.
    """
    from ..stats.drift import FlightProfile, layer_seconds

    flight = FlightProfile(
        ascent_rate_ms=float(ds.attrs.get("flight_ascent_rate_ms", 5.0)),
        burst_altitude_m=float(ds.attrs.get("flight_burst_altitude_m", 30000.0)),
        descent_rate_ms=float(ds.attrs.get("flight_descent_rate_ms", 6.0)),
    )
    alt = np.nanmean(ds["alt_geom_mean_m"].values, axis=(3, 4))
    u = np.nanmean(ds["u_mean"].values, axis=(3, 4))
    v = np.nanmean(ds["v_mean"].values, axis=(3, 4))

    by_month: dict[int, float] = {}
    worst = {"month": None, "bin": None, "share": 0.0}
    for mi, month in enumerate(ds["month"].values):
        shares = []
        for wi, half in enumerate(ds["bin"].values):
            order = np.argsort(alt[mi, wi])
            a = alt[mi, wi][order][:, None, None]
            if not np.isfinite(a).all():
                continue
            w = layer_seconds(a, flight)
            uu = u[mi, wi][order][:, None, None]
            vv = v[mi, wi][order][:, None, None]
            high = a[:, 0, 0] >= ceiling_m
            net = np.hypot(float((uu * w).sum()), float((vv * w).sum()))
            top = np.hypot(float((uu * w)[high].sum()), float((vv * w)[high].sum()))
            share = top / max(net, 1e-9)
            shares.append(share)
            if share > worst["share"]:
                worst = {"month": int(month), "bin": int(half), "share": float(share)}
        if shares:
            by_month[int(month)] = float(np.mean(shares))
    return {"ceiling_m": ceiling_m, "by_month": by_month, "worst": worst,
            "annual_mean": float(np.mean(list(by_month.values()))) if by_month else float("nan")}


def _bin_name(s: dict, index: int | None) -> str:
    """The label the dataset recorded for a bin, e.g. "前半 (1-15日)".

    ``index`` is ``None`` when the statistic found nothing to report -- the
    ceiling share on a dataset with no altitudes above the ceiling, say -- so
    that case gets a dash rather than a crash.
    """
    if index is None:
        return "--"
    labels = s.get("bin_labels") or []
    return labels[index - 1] if 1 <= index <= len(labels) else f"ビン {index}"


def format_summary(s: dict) -> str:
    counts = "  ".join(f"{k}={v}" for k, v in s["n"].items())
    lines = [f"=== {s['region']} ({s['period']}) ===",
             f"標本数 {counts}",
             f"有効標本数 中央値={s['n_eff_median']:.1f} (n の {s['n_eff_ratio_median']:.0%})",
             "",
             "気圧面ごとの季節別 平均風速 [m/s] / 定常度",
             f"{'hPa':>6} {'高度km':>7}  " + "  ".join(f"{k:>18}" for k in SEASONS)]
    for lv, row in s["levels"].items():
        cells = []
        for k in SEASONS:
            if k in row:
                cells.append(f"{row[k]['speed_mean']:6.1f} / {row[k]['constancy']:.2f}   ")
            else:
                cells.append(" " * 18)
        lines.append(f"{lv:6.0f} {row['alt_km']:7.1f}  " + "  ".join(cells))
    c = s["column_0_30km"]
    lines += [
        "",
        f"0-30 km 積算が最も穏やか: {c['calmest']['month']}月 {_bin_name(s, c['calmest']['bin'])} "
        f"({c['calmest']['mean_speed']:.1f} m/s)",
        f"0-30 km 積算が最も荒い  : {c['roughest']['month']}月 "
        f"{_bin_name(s, c['roughest']['bin'])} "
        f"({c['roughest']['mean_speed']:.1f} m/s)",
        "",
        "定常度が最も低いビン (風向が読めない時期):",
    ]
    for b in s["lowest_constancy_bins"]:
        lines.append(
            f"  {b['month']:2d}月 {_bin_name(s, b['bin'])}  "
            f"constancy={b['constancy']:.2f}"
        )
    lines += [
        "",
        f"領域内の風速差 最大: {s['max_spatial_range_speed']:.1f} m/s",
        f"ISA からのずれ 最大: {s['isa_error_m']['max_abs']:.0f} m "
        f"(冬 {s['isa_error_m']['winter_max_abs']:.0f} m, "
        f"夏 {s['isa_error_m']['summer_max_abs']:.0f} m)",
    ]
    if "ceiling_share" in s:
        c = s["ceiling_share"]
        lines += [
            "",
            f"Open-Meteo の上限 ({c['ceiling_m'] / 1000:.1f} km) より上が水平移動に占める割合:",
            "  " + "  ".join(f"{m:2d}月 {100 * v:5.1f}%" for m, v in
                             sorted(c["by_month"].items())[:6]),
            "  " + "  ".join(f"{m:2d}月 {100 * v:5.1f}%" for m, v in
                             sorted(c["by_month"].items())[6:]),
            f"  年平均 {100 * c['annual_mean']:.1f}%、"
            f"最大 {100 * c['worst']['share']:.0f}% "
            f"({c['worst']['month']}月 {_bin_name(s, c['worst']['bin'])})",
        ]
    for key, label in (("max_shear", "最大シアー"),
                       ("max_shear_free_air", "  うち 2 km 以上")):
        m = s.get(key)
        if m:
            lines.append(
                f"{label}: {m['value']:.1f} (m/s)/km  {m['month']}月 {_bin_name(s, m['bin'])} "
                f"高度 {m['alt_km']:.1f} km"
            )
    return "\n".join(lines)
