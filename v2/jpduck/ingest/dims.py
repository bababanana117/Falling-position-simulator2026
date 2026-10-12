"""The dimension tables.

Every value here comes from the aggregation pipeline rather than from a
literal, so the
database cannot describe a grid, a level set or a bin scheme that the
statistics were not computed under.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from windclim.config import YEARS, kept_levels
from windclim.regions import to_0_360
from windclim.stats.aggregate import ROSE_SECTORS, ROSE_SPEED_EDGES
from windclim.stats.altitude import isa_altitude_from_pressure
from windclim.timebins import HALF_MONTH, SEASON_ORDER, SEASONS

__all__ = [
    "COMPASS_16",
    "build_dim_grid",
    "build_dim_hour",
    "build_dim_level",
    "build_dim_sector",
    "build_dim_speed_class",
    "build_dim_timebin",
]

COMPASS_16 = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)

#: The month a season starts in, used to label each bin.
_SEASON_OF_MONTH = {
    month: name for name, months in SEASONS.items() for month in months
}
_SEASON_CODE = {
    "冬 (12-2月)": "DJF", "春 (3-5月)": "MAM",
    "夏 (6-8月)": "JJA", "秋 (9-11月)": "SON",
}


def build_dim_grid(ds: xr.Dataset, rose_lat: float, rose_lon: float) -> pd.DataFrame:
    lat = ds["lat"].values.astype(float)
    lon = ds["lon"].values.astype(float)
    # gauss_weight is stored as (month, lat) but is a function of latitude
    # alone; the month axis is an artefact of how the months were concatenated.
    weight = np.asarray(ds["gauss_weight"].values, dtype=float)
    if weight.ndim == 2:
        weight = weight[0]

    lat_idx, lon_idx = np.meshgrid(
        np.arange(lat.size), np.arange(lon.size), indexing="ij"
    )
    lat_idx = lat_idx.ravel()
    lon_idx = lon_idx.ravel()
    rows = pd.DataFrame(
        {
            "cell_id": (lat_idx * lon.size + lon_idx).astype("int16"),
            "lat_idx": lat_idx.astype("int16"),
            "lon_idx": lon_idx.astype("int16"),
            "lat": lat[lat_idx],
            "lon": lon[lon_idx],
            "lon_0_360": to_0_360(lon[lon_idx]),
            "gauss_weight": weight[lat_idx],
        }
    )
    near = (
        (rows["lat"] - rose_lat).abs() + (rows["lon"] - rose_lon).abs()
    ).idxmin()
    rows["is_rose_cell"] = False
    rows.loc[near, "is_rose_cell"] = True
    return rows.sort_values("cell_id").reset_index(drop=True)


def build_dim_level(ds: xr.Dataset) -> pd.DataFrame:
    """Levels, with a region-wide summary of the geometric altitude.

    The altitude of a pressure surface moves with the season and the place, so
    the exact value belongs on the fact row. These four columns exist so that
    someone reading the level list can see roughly where 30 hPa is without a
    join; ``alt_geom_mean_m`` is weighted by ``gauss_weight``, which is the
    correct weight for an area mean.
    """
    levels = np.asarray(ds["level"].values, dtype=float)
    expected = np.asarray(kept_levels(), dtype=float)
    if not np.allclose(np.sort(levels), np.sort(expected)):
        raise ValueError("NetCDF levels do not match the pipeline's kept_levels()")

    alt = ds["alt_geom_mean_m"]
    weight = ds["gauss_weight"]
    if "month" in weight.dims:
        weight = weight.isel(month=0)
    w = weight.broadcast_like(alt.isel(month=0, bin=0, level=0))
    mean_m = (
        (alt * w).sum(("lat", "lon")) / w.sum(("lat", "lon"))
    ).mean(("month", "bin")).values

    return pd.DataFrame(
        {
            "level_id": np.arange(levels.size, dtype="int16"),
            "level_hpa": levels,
            "alt_geom_mean_m": mean_m,
            "alt_geom_mean_km": mean_m / 1000.0,
            "alt_geom_min_m": alt.min(("month", "bin", "lat", "lon")).values,
            "alt_geom_max_m": alt.max(("month", "bin", "lat", "lon")).values,
            "z_mean_gpm": ds["z_mean_gpm"].mean(("month", "bin", "lat", "lon")).values,
            "isa_alt_m": isa_altitude_from_pressure(levels),
            "is_diurnal_level": np.isin(levels, np.asarray(ds["level_low"].values, dtype=float)),
        }
    )


def build_dim_timebin(ds: xr.Dataset) -> pd.DataFrame:
    """The 24 half-month bins, straight out of ``HALF_MONTH.calendar_rows``."""
    labels = [str(x) for x in ds.attrs["bin_labels"]]
    shorts = [str(x) for x in ds.attrs["bin_short"]]
    english = {
        1: "first half (days 1-15)",
        2: "second half (day 16 to end of month)",
    }
    rows = []
    for r in HALF_MONTH.calendar_rows(YEARS):
        month, index = r["month"], r["bin"]
        season = _SEASON_OF_MONTH[month]
        rows.append(
            {
                "timebin_id": (month - 1) * 2 + (index - 1),
                "month": month,
                "bin": index,
                "bin_short": shorts[index - 1],
                "bin_label_ja": labels[index - 1],
                "bin_label_en": english[index],
                "start_day": r["start_day"],
                "end_day_min": r["end_day_min"],
                "end_day_max": r["end_day_max"],
                "n_days_total": r["n_days"],
                "n_analyses_expected": r["n_analyses"],
                "season": _SEASON_CODE[season],
                "season_ja": season,
                "season_order": SEASON_ORDER.index(season),
            }
        )
    df = pd.DataFrame(rows)
    for c in ("timebin_id", "month", "bin", "start_day", "end_day_min", "end_day_max",
              "season_order"):
        df[c] = df[c].astype("int16")
    return df.sort_values("timebin_id").reset_index(drop=True)


def build_dim_hour(ds: xr.Dataset) -> pd.DataFrame:
    hours = np.asarray(ds["hour"].values, dtype=int)
    jst = (hours + 9) % 24
    return pd.DataFrame(
        {
            "hour_utc": hours.astype("int16"),
            "hour_jst": jst.astype("int16"),
            "jst_next_day": (hours + 9) >= 24,
        }
    )


def build_dim_sector(ds: xr.Dataset) -> pd.DataFrame:
    centre = np.asarray(ds["sector_deg"].values, dtype=float)
    half = 360.0 / ROSE_SECTORS / 2.0
    lo = (centre - half) % 360.0
    hi = centre + half
    return pd.DataFrame(
        {
            "sector": np.arange(centre.size, dtype="int16"),
            "centre_deg": centre,
            "lo_deg": lo,
            "hi_deg": hi,
            # Only the northern sector straddles 0/360, so only it has lo > hi.
            "wraps_north": lo > hi,
            "compass_16": list(COMPASS_16[: centre.size]),
        }
    )


def build_dim_speed_class(ds: xr.Dataset) -> pd.DataFrame:
    lo = np.asarray(ds["speed_class_lo"].values, dtype=float)
    edges = list(ROSE_SPEED_EDGES)
    hi = [edges[i + 1] for i in range(len(lo))]
    hi_col = [None if not np.isfinite(h) else float(h) for h in hi]
    labels = [
        f"{a:.0f}+" if b is None else f"{a:.0f}-{b:.0f}" for a, b in zip(lo, hi_col, strict=True)
    ]
    return pd.DataFrame(
        {
            "speed_class": np.arange(lo.size, dtype="int16"),
            "lo_ms": lo,
            "hi_ms": hi_col,
            "label": labels,
        }
    )
