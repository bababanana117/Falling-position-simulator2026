"""Quantities computed *from* the stored moments, at export time.

Nothing here is accumulated over samples; every function is a pointwise transform
of numbers the aggregation already produced. That split is the whole reason
directions are safe in this pipeline: a direction only ever comes into existence
here, from a mean that was taken in component space, so there is no code path in
which angles could be averaged.

It also means the NetCDF can stay small and lossless -- store ``u_var``,
``v_var``, ``uv_cov`` and reconstruct the ellipse whenever it is wanted.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from ..stats.circular import circular_sd_deg, uv_to_met_direction
from ..stats.vector import variance_ellipse

__all__ = ["DERIVED_VARS", "add_derived", "shear_magnitude"]

DERIVED_VARS = (
    "dir_vector_mean",
    "dir_unit_mean",
    "resultant_length",
    "circ_sd_deg",
    "ellipse_major",
    "ellipse_minor",
    "ellipse_angle_deg",
    "alt_geom_mean_km",
    "shear_mag",
    "speed_se",
)


def shear_magnitude(
    u_mean: xr.DataArray, v_mean: xr.DataArray, alt_m: xr.DataArray
) -> xr.DataArray:
    """Vertical wind shear ``|dV/dz|`` in (m/s)/km, on the level axis.

    Shear, not wind speed, is what spreads a balloon's landing ellipse: a payload
    crossing a sheared layer picks up a different drift depending on exactly when
    and where it crosses. It is computed from the *vector* means, so a layer where
    the wind turns through 90 degrees at constant speed still registers.

    Differences are taken between adjacent levels and then averaged back onto the
    levels, so the result has the same shape as its inputs.
    """
    axis = u_mean.dims.index("level")
    du = np.diff(u_mean.values, axis=axis)
    dv = np.diff(v_mean.values, axis=axis)
    dz = np.diff(alt_m.values, axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        interface = np.hypot(du, dv) / np.abs(dz / 1000.0)
    interface = np.where(np.isfinite(interface), interface, np.nan)

    # Average the two interfaces bracketing each level; edges keep their one side.
    pad_lo = np.take(interface, [0], axis=axis)
    pad_hi = np.take(interface, [-1], axis=axis)
    lower = np.concatenate([pad_lo, interface], axis=axis)
    upper = np.concatenate([interface, pad_hi], axis=axis)
    with np.errstate(invalid="ignore"):
        out = np.nanmean(np.stack([lower, upper]), axis=0)
    return xr.DataArray(out.astype(np.float32), dims=u_mean.dims, coords=u_mean.coords)


def add_derived(ds: xr.Dataset) -> xr.Dataset:
    """Return a copy of ``ds`` with every derived field attached."""
    out = ds.copy()

    out["dir_vector_mean"] = (
        ds["u_mean"].dims,
        uv_to_met_direction(ds["u_mean"].values, ds["v_mean"].values).astype(np.float32),
    )

    if "u_unit_mean" in ds:
        r = np.hypot(ds["u_unit_mean"].values, ds["v_unit_mean"].values)
        out["resultant_length"] = (ds["u_unit_mean"].dims, r.astype(np.float32))
        out["dir_unit_mean"] = (
            ds["u_unit_mean"].dims,
            uv_to_met_direction(
                ds["u_unit_mean"].values, ds["v_unit_mean"].values
            ).astype(np.float32),
        )
        out["circ_sd_deg"] = (ds["u_unit_mean"].dims, circular_sd_deg(r).astype(np.float32))

    major, minor, angle = variance_ellipse(
        ds["u_var"].values, ds["v_var"].values, ds["uv_cov"].values
    )
    out["ellipse_major"] = (ds["u_var"].dims, major.astype(np.float32))
    out["ellipse_minor"] = (ds["u_var"].dims, minor.astype(np.float32))
    out["ellipse_angle_deg"] = (ds["u_var"].dims, angle.astype(np.float32))

    if "alt_geom_mean_m" in ds:
        out["alt_geom_mean_km"] = (ds["alt_geom_mean_m"].dims,
                                   (ds["alt_geom_mean_m"].values / 1000.0).astype(np.float32))
        out["shear_mag"] = shear_magnitude(
            ds["u_mean"], ds["v_mean"], ds["alt_geom_mean_m"]
        )

    if "n_eff" in ds and "speed_std" in ds:
        # Standard error from the *effective* count, not the raw one: 280 six-hourly
        # analyses are typically worth 20-40 independent samples, so using n would
        # overstate confidence roughly threefold.
        with np.errstate(invalid="ignore", divide="ignore"):
            se = ds["speed_std"].values / np.sqrt(np.maximum(ds["n_eff"].values, 1.0))
        out["speed_se"] = (ds["speed_std"].dims, se.astype(np.float32))

    return out
