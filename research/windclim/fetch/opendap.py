"""Fetch one subset over OPeNDAP.

Subsetting happens *server-side*: we send a hyperslab constraint and GDEX sends
back only the box we asked for. That is the whole reason this path was chosen
over reading the archive's kerchunk references. The files are chunked
``(1, 23, 240, 480)``, so a client-side byte-range read of even a tiny box would
pull two whole chunks -- about 9 MB compressed -- for every one of the 14 610
analyses, roughly 260 GB in total. Letting the server decompress and cut turns
that into about 7 MB per five-day file.

Measured on 2026-09-18: one ``anl_p`` chunk-variable took 13.7 s end to end.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import xarray as xr

from ..grid import bbox_slices
from .cache import FetchTask
from .normalize import CANON, normalize, validate_slab

__all__ = ["OpendapFetcher", "open_and_subset"]

log = logging.getLogger(__name__)


def open_and_subset(task: FetchTask) -> tuple[xr.Dataset, dict]:
    """Download, normalise and validate one task's slab.

    Everything the server sends is pulled into memory with ``.load()`` before the
    connection is closed. No lazy arrays escape this function: a lazy array that
    fails later fails with a graph traceback instead of a URL, which is no use at
    three in the morning.
    """
    started = time.perf_counter()
    ds = xr.open_dataset(
        task.url, engine="netcdf4", decode_times=True, mask_and_scale=True
    )
    try:
        lat_sl, lon_sl = bbox_slices(ds["lat"].values, ds["lon"].values, task.bbox)
        levels = np.asarray(ds["pressure_level"].values, dtype=float)
        keep = levels >= task.level_min_hpa
        sub = ds.isel(lat=lat_sl, lon=lon_sl, pressure_level=keep)
        if task.time_stride > 1:
            sub = sub.isel(time=slice(None, None, task.time_stride))
        sub = sub.load()
    finally:
        ds.close()

    out = normalize(sub, task.var, task.product)
    checks = validate_slab(
        out,
        var=task.var,
        bbox=task.bbox,
        n_times=task.n_times_expected,
        n_levels=task.n_levels_expected,
    )
    checks["elapsed_s"] = round(time.perf_counter() - started, 2)
    checks["engine"] = "netcdf4-opendap"
    checks["index_ranges"] = {
        "lat": [lat_sl.start, lat_sl.stop],
        "lon": [lon_sl.start, lon_sl.stop],
        "level_min_hpa": task.level_min_hpa,
        "time_stride": task.time_stride,
    }
    checks["nc_varname"] = task.nc_varname
    checks["canonical_name"] = CANON[task.var]
    checks["time_min"] = str(np.datetime_as_string(out["time"].values[0], unit="h"))
    checks["time_max"] = str(np.datetime_as_string(out["time"].values[-1], unit="h"))
    checks["n_times"] = int(out.sizes["time"])
    return out, checks


@dataclass(frozen=True)
class OpendapFetcher:
    """Default fetcher. Kept behind a tiny interface so NCSS can replace it."""

    name: str = "opendap"

    def fetch(self, task: FetchTask) -> tuple[xr.Dataset, dict]:
        return open_and_subset(task)
