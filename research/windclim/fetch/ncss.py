"""Fallback fetcher: the THREDDS NetcdfSubset service.

Same idea as the OPeNDAP path -- the server does the subsetting -- but it returns
a single prepared netCDF4 file over plain HTTPS instead of a DAP hyperslab. Kept
behind the same tiny interface so a switch is one config flag, for the day
OPeNDAP is slow, throttled or simply down.

NCSS cannot express a level stride, so the ``hgt`` time stride is applied after
download rather than before. That costs a little transfer and nothing else.
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import xarray as xr

from ..urls import ncss_url
from .cache import FetchTask
from .normalize import CANON, normalize, validate_slab

__all__ = ["NcssFetcher"]

log = logging.getLogger(__name__)

USER_AGENT = "windclim/0.1 (+https://github.com/ddd3h/Falling-position-simulator)"


@dataclass(frozen=True)
class NcssFetcher:
    name: str = "ncss"
    timeout_s: float = 600.0

    def fetch(self, task: FetchTask) -> tuple[xr.Dataset, dict]:
        started = time.perf_counter()
        url = ncss_url(
            task.var,
            task.product,
            task.year,
            task.month,
            task.day0,
            task.day1,
            north=task.bbox.north,
            south=task.bbox.south,
            west=task.bbox.west,
            east=task.bbox.east,
        )
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "ncss.nc"
            with httpx.stream(
                "GET",
                url,
                timeout=self.timeout_s,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                resp.raise_for_status()
                with open(local, "wb") as fh:
                    for block in resp.iter_bytes(1 << 20):
                        fh.write(block)
            ds = xr.open_dataset(local, engine="netcdf4", mask_and_scale=True)
            try:
                levels = np.asarray(ds["pressure_level"].values, dtype=float)
                sub = ds.isel(pressure_level=levels >= task.level_min_hpa)
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
        checks["engine"] = "ncss"
        checks["nc_varname"] = task.nc_varname
        checks["canonical_name"] = CANON[task.var]
        checks["index_ranges"] = {
            "bbox": [task.bbox.south, task.bbox.north, task.bbox.west, task.bbox.east],
            "level_min_hpa": task.level_min_hpa,
            "time_stride": task.time_stride,
        }
        checks["time_min"] = str(np.datetime_as_string(out["time"].values[0], unit="h"))
        checks["time_max"] = str(np.datetime_as_string(out["time"].values[-1], unit="h"))
        checks["n_times"] = int(out.sizes["time"])
        return out, checks
