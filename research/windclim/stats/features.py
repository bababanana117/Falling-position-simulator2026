"""One pass over the cache, producing one value per analysis.

Every question in :mod:`windclim.stats.timescale` and
:mod:`windclim.stats.significance` is a reduction over "the value at each
analysis time". Computing that once and storing it turns 110 cross-validation
fits from 110 re-aggregations into 110 cheap reductions over an array that fits
in memory.

The main product is the **landing displacement of a nominal flight launched at
each analysis time from each grid cell**. That is the quantity the project
actually cares about, and because horizontal advection is linear in the wind
profile (see :mod:`windclim.stats.drift`) it can be computed exactly per
analysis rather than estimated from a climatology.

A handful of diagnostic pressure levels are kept alongside it, so the same
questions can be asked of the wind itself and the answer can be broken down by
altitude.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import xarray as xr

from ..regions import to_signed_lon
from .aggregate import AggregateConfig, load_month
from .altitude import geopotential_to_geometric
from .drift import displacements

__all__ = ["DIAGNOSTIC_LEVELS_HPA", "build_features", "features_path", "open_features"]

#: Boundary layer, mid-troposphere, the jet, just above the tropopause, and two
#: stratospheric levels bracketing the burst altitude.
DIAGNOSTIC_LEVELS_HPA: tuple[float, ...] = (850.0, 500.0, 200.0, 100.0, 30.0, 10.0)

log = logging.getLogger(__name__)


def features_path(out_root: Path, region: str, years: Sequence[int]) -> Path:
    years = list(years)
    return Path(out_root) / "features" / f"features_{region}_{years[0]}-{years[-1]}.nc"


def _month_altitude(samples) -> np.ndarray:
    """Month-mean geometric altitude per level, shape ``(level, lat, lon)``.

    Geopotential height is sampled once per cached file rather than at every
    analysis, and it varies by only a few hundred metres through a month, so one
    profile per month is enough to set the layer thicknesses the flight model
    needs. The aggregation does the same thing per half.
    """
    with np.errstate(invalid="ignore"):
        z = np.nanmean(samples.z, axis=0)
    lat3 = samples.lat[None, :, None]
    return geopotential_to_geometric(z, np.broadcast_to(lat3, z.shape))


def build_features(
    cache_root: Path,
    region: str,
    cfg: AggregateConfig,
    *,
    out_path: Path | None = None,
    months: Sequence[int] = tuple(range(1, 13)),
    levels_hpa: Sequence[float] = DIAGNOSTIC_LEVELS_HPA,
) -> xr.Dataset:
    """Build the per-analysis feature table for one region.

    Returns the dataset and, when ``out_path`` is given, writes it there.
    """
    dx_parts: list[np.ndarray] = []
    dy_parts: list[np.ndarray] = []
    u_parts: list[np.ndarray] = []
    v_parts: list[np.ndarray] = []
    t_parts: list[np.ndarray] = []
    lat = lon = level_idx = None

    for month in months:
        log.info("features: %s month %02d", region, month)
        samples = load_month(Path(cache_root), region, month, cfg)
        if samples.z is None or not samples.z.size:
            raise ValueError(f"month {month} has no geopotential height in the cache")

        if lat is None:
            lat, lon = samples.lat, samples.lon
            level_idx = [
                int(np.argmin(np.abs(samples.level - p))) for p in levels_hpa
            ]

        alt = _month_altitude(samples)            # (level, lat, lon), pressure order
        order = np.argsort(alt[:, alt.shape[1] // 2, alt.shape[2] // 2])
        dx, dy = displacements(
            samples.u[:, order], samples.v[:, order], alt[order], cfg.flight
        )
        dx_parts.append(dx.astype(np.float32))
        dy_parts.append(dy.astype(np.float32))
        u_parts.append(samples.u[:, level_idx].astype(np.float32))
        v_parts.append(samples.v[:, level_idx].astype(np.float32))
        t_parts.append(samples.times)
        del samples

    times = np.concatenate(t_parts)
    sort = np.argsort(times)
    ds = xr.Dataset(
        {
            "dx_east_m": (("time", "lat", "lon"), np.concatenate(dx_parts)[sort]),
            "dy_north_m": (("time", "lat", "lon"), np.concatenate(dy_parts)[sort]),
            "u": (("time", "plevel", "lat", "lon"), np.concatenate(u_parts)[sort]),
            "v": (("time", "plevel", "lat", "lon"), np.concatenate(v_parts)[sort]),
        },
        coords={
            "time": times[sort],
            "plevel": np.asarray(levels_hpa, dtype=np.float32),
            "lat": lat.astype(np.float32),
            "lon": np.asarray([to_signed_lon(x) for x in lon], dtype=np.float32),
        },
        attrs={
            "title": f"Per-analysis landing displacement and diagnostic winds ({region})",
            "summary": (
                "One value per 6-hourly analysis, so that cross-validation over "
                "time granularity is a reduction rather than a re-aggregation."
            ),
            "flight_ascent_rate_ms": cfg.flight.ascent_rate_ms,
            "flight_burst_altitude_m": cfg.flight.burst_altitude_m,
            "flight_descent_rate_ms": cfg.flight.descent_rate_ms,
            "flight_description": cfg.flight.label(),
            "region": region,
        },
    )
    ds["dx_east_m"].attrs = {"long_name": "Eastward landing displacement", "units": "m"}
    ds["dy_north_m"].attrs = {"long_name": "Northward landing displacement", "units": "m"}
    ds["u"].attrs = {"long_name": "Eastward wind", "units": "m s-1"}
    ds["v"].attrs = {"long_name": "Northward wind", "units": "m s-1"}
    ds["plevel"].attrs = {"long_name": "diagnostic pressure level", "units": "hPa"}

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        enc = {
            n: {"zlib": True, "complevel": 1, "dtype": "float32"}
            for n in ("dx_east_m", "dy_north_m", "u", "v")
        }
        tmp = out_path.with_suffix(".nc.part")
        ds.to_netcdf(tmp, engine="netcdf4", encoding=enc)
        tmp.replace(out_path)
        log.info("wrote %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    return ds


def open_features(path: Path) -> xr.Dataset:
    return xr.open_dataset(path, engine="netcdf4")
