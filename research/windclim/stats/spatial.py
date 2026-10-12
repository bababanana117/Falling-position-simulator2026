"""Region-wide reductions.

Averaging a latitude-longitude grid without weighting over-counts the poleward
rows, because the cells there are narrower on the ground. The JRA-3Q files carry
their own Gaussian quadrature weights, which is exactly the right weighting for
this grid, so those are used when present and ``cos(lat)`` stands in when they
are not.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

__all__ = ["area_mean", "area_weights", "spatial_range"]


def area_weights(ds: xr.Dataset) -> xr.DataArray:
    if "gauss_weight" in ds:
        return ds["gauss_weight"].fillna(0.0)
    return np.cos(np.radians(ds["lat"]))


def area_mean(ds: xr.Dataset, name: str) -> xr.DataArray:
    """Latitude-weighted mean of one variable over lat and lon."""
    return ds[name].weighted(area_weights(ds)).mean(dim=("lat", "lon"), skipna=True)


def spatial_range(ds: xr.Dataset, name: str) -> xr.DataArray:
    """Max minus min across the region.

    Answers a question the area mean cannot: is one representative column enough
    to describe this region, or does the answer depend on where you stand?
    """
    da = ds[name]
    return da.max(dim=("lat", "lon"), skipna=True) - da.min(dim=("lat", "lon"), skipna=True)
