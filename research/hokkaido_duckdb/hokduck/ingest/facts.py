"""The fact tables that come straight out of the shipped NetCDF.

No statistic is recomputed here. The NetCDF is the canonical product; this
stage reshapes it from a five-dimensional array into rows and attaches the
surrogate keys. The only new numbers are the two derived columns that the
NetCDF happens not to carry (``fact_wind_diurnal.dir_vector_mean_deg`` and
``fact_drift.bearing_from_deg``), and both are noted as derived in
``meta_column``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from windclim.stats.circular import uv_to_met_direction

__all__ = [
    "build_fact_drift",
    "build_fact_wind",
    "build_fact_wind_diurnal",
    "build_fact_wind_rose",
]

#: (month, bin, level, lat, lon), the main group.
_WIND_VARS = [
    "n", "n_eff", "lag1_autocorr",
    "u_mean", "v_mean", "u_var", "v_var", "uv_cov", "u_unit_mean", "v_unit_mean",
    "speed_mean", "speed_vector_mean", "speed_std", "speed_max", "speed_se",
    "speed_p10", "speed_p25", "speed_p50", "speed_p75", "speed_p90", "speed_p95",
    "exceed_gt10", "exceed_gt20", "exceed_gt30", "exceed_gt40",
    "constancy", "dir_vector_mean", "dir_unit_mean", "resultant_length", "circ_sd_deg",
    "ellipse_major", "ellipse_minor", "ellipse_angle_deg",
    "z_mean_gpm", "z_std_gpm", "alt_geom_mean_m", "alt_geom_mean_km", "shear_mag",
]

_RENAME_WIND = {
    "dir_vector_mean": "dir_vector_mean_deg",
    "dir_unit_mean": "dir_unit_mean_deg",
}

_DRIFT_RENAME = {
    "drift_n": "n",
    "drift_east_m": "east_m",
    "drift_north_m": "north_m",
    "drift_east_var": "east_var_m2",
    "drift_north_var": "north_var_m2",
    "drift_cov": "cov_m2",
    "drift_dist_mean_km": "dist_mean_km",
    "drift_dist_p50_km": "dist_p50_km",
    "drift_dist_p90_km": "dist_p90_km",
    "drift_dist_p95_km": "dist_p95_km",
    "drift_dist_max_km": "dist_max_km",
    "drift_bearing_deg": "bearing_deg",
    "drift_flight_time_s": "flight_time_s",
}


def _keys(df: pd.DataFrame, n_lon: int) -> pd.DataFrame:
    """Attach the surrogate keys that every fact row carries."""
    df["timebin_id"] = ((df["month"].astype(int) - 1) * 2 + (df["bin"].astype(int) - 1))
    if "lat_idx" in df and "lon_idx" in df:
        df["cell_id"] = df["lat_idx"] * n_lon + df["lon_idx"]
    return df


def _index_frame(ds: xr.Dataset) -> tuple[pd.Series, pd.Series]:
    """Maps from coordinate value to integer index, for the surrogate keys."""
    lat = pd.Series(np.arange(ds.sizes["lat"]), index=ds["lat"].values.astype(float))
    lon = pd.Series(np.arange(ds.sizes["lon"]), index=ds["lon"].values.astype(float))
    return lat, lon


def build_fact_wind(ds: xr.Dataset) -> pd.DataFrame:
    present = [v for v in _WIND_VARS if v in ds]
    missing = set(_WIND_VARS) - set(present)
    if missing:
        raise ValueError(f"NetCDF is missing expected variables: {sorted(missing)}")

    df = ds[present].to_dataframe().reset_index()
    df = df.rename(columns=_RENAME_WIND | {"level": "level_hpa"})

    lat_idx, lon_idx = _index_frame(ds)
    df["lat_idx"] = df["lat"].map(lat_idx).astype("int16")
    df["lon_idx"] = df["lon"].map(lon_idx).astype("int16")
    df["level_id"] = df["level_hpa"].map(
        pd.Series(np.arange(ds.sizes["level"]), index=ds["level"].values.astype(float))
    ).astype("int16")
    df = _keys(df, ds.sizes["lon"])
    return df


def build_fact_wind_rose(ds: xr.Dataset, cell_id: int) -> pd.DataFrame:
    df = ds[["rose_counts"]].to_dataframe().reset_index()
    df = df.rename(columns={"rose_counts": "count", "level": "level_hpa"})
    df["level_id"] = df["level_hpa"].map(
        pd.Series(np.arange(ds.sizes["level"]), index=ds["level"].values.astype(float))
    ).astype("int16")
    df = _keys(df, ds.sizes["lon"])
    df["cell_id"] = np.int16(cell_id)
    df["count"] = df["count"].astype("int32")
    return df


def build_fact_wind_diurnal(ds: xr.Dataset) -> pd.DataFrame:
    hourly = [v for v in ("hr_n", "hr_u_mean", "hr_v_mean", "hr_speed_mean",
                          "hr_speed_std", "hr_constancy") if v in ds]
    df = ds[hourly].to_dataframe().reset_index()
    df = df.rename(
        columns={
            "hr_n": "n", "hr_u_mean": "u_mean", "hr_v_mean": "v_mean",
            "hr_speed_mean": "speed_mean", "hr_speed_std": "speed_std",
            "hr_constancy": "constancy", "level_low": "level_hpa", "hour": "hour_utc",
        }
    )
    lat_idx, lon_idx = _index_frame(ds)
    df["lat_idx"] = df["lat"].map(lat_idx).astype("int16")
    df["lon_idx"] = df["lon"].map(lon_idx).astype("int16")
    df["level_id"] = df["level_hpa"].map(
        pd.Series(np.arange(ds.sizes["level"]), index=ds["level"].values.astype(float))
    ).astype("int16")
    df = _keys(df, ds.sizes["lon"])
    # The NetCDF carries no direction for this sub-product; derive it the one
    # legal way, from the component means.
    df["dir_vector_mean_deg"] = uv_to_met_direction(
        df["u_mean"].to_numpy(dtype=float), df["v_mean"].to_numpy(dtype=float)
    )
    df["n"] = df["n"].astype("int32")
    return df


def build_fact_drift(ds: xr.Dataset) -> pd.DataFrame:
    present = [v for v in _DRIFT_RENAME if v in ds]
    df = ds[present].to_dataframe().reset_index().rename(columns=_DRIFT_RENAME)
    lat_idx, lon_idx = _index_frame(ds)
    df["lat_idx"] = df["lat"].map(lat_idx).astype("int16")
    df["lon_idx"] = df["lon"].map(lon_idx).astype("int16")
    df = _keys(df, ds.sizes["lon"])
    # bearing_deg is the direction of travel; every other direction column in
    # the database is the direction the wind comes from. Carry both so the
    # mistake cannot be made silently.
    df["bearing_from_deg"] = (df["bearing_deg"] + 180.0) % 360.0
    if "n" in df:
        df["n"] = df["n"].astype("int32")
    return df
