"""The single boundary where raw JRA-3Q files become the pipeline's own shape.

Everything odd about the archive is dealt with exactly once, here:

* The data variable's name contains hyphens (``ugrd-pres-an-gauss``), which a raw
  DAP DDS escapes as ``ugrd%2Dpres%2Dan%2Dgauss``. After this module runs, the
  variable is called ``u``, ``v`` or ``z`` and no hyphenated name appears
  anywhere else in the codebase.
* Latitude runs from 89.7 N down to 89.7 S. It is sorted ascending here, so every
  downstream consumer -- CF conventions, matplotlib, the aggregation -- sees the
  ordering it expects and nothing has to remember the flip.
* ``pressure_level`` is renamed ``level``.

:func:`validate_slab` then checks that what came back really is what was asked
for. That check is the only defence against the worst failure mode this pipeline
has: a hyperslab that is silently off by one, or taken from the wrong hemisphere,
producing a complete, plausible-looking, wrong dataset.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import xarray as xr

from ..config import FILL_VALUE
from ..regions import BBox
from ..urls import dap_escaped, nc_varname
from .retry import PermanentFetchError

__all__ = ["CANON", "SlabValidationError", "find_source_var", "normalize", "validate_slab"]


class SlabValidationError(PermanentFetchError, ValueError):
    """A downloaded slab is not what was asked for.

    Deliberately permanent: the same request would produce the same bad slab, so
    retrying wastes minutes proving it. It is also not a *missing* file, so the
    driver records it under its own status -- a validation failure means either
    the archive changed or this code is wrong, and both need a human.

    Also a ``ValueError``, because from a caller's point of view that is exactly
    what it is: the data does not match its contract.
    """


log = logging.getLogger(__name__)

CANON = {"ugrd": "u", "vgrd": "v", "hgt": "z"}

#: Physically impossible values, used as a tripwire rather than a filter.
MAX_WIND_MS = 200.0
MAX_HEIGHT_GPM = 60000.0
#: The 1000 hPa surface sits *below* sea level inside a deep low, so geopotential
#: height is legitimately negative there. Observed -73 gpm over the Kuril low in
#: January 2016; -1000 gpm is a tripwire, not a physical limit.
MIN_HEIGHT_GPM = -1000.0
MAX_NAN_FRACTION = 0.01


def find_source_var(ds: xr.Dataset, var: str, product: str) -> str:
    """Locate the wind/height variable inside a raw dataset.

    Three strategies in order, because the DAP layer may or may not have
    unescaped the name for us, and because a silent ``KeyError`` here would be
    hard to read at 3 am.
    """
    expected = nc_varname(var, product)
    if expected in ds.variables:
        return expected
    escaped = dap_escaped(expected)
    if escaped in ds.variables:
        log.warning("variable name arrived DAP-escaped: %s", escaped)
        return escaped
    four_d = [n for n, da in ds.variables.items() if da.ndim == 4]
    if len(four_d) == 1:
        log.warning(
            "expected variable %r not present; falling back to the only 4-D variable %r",
            expected,
            four_d[0],
        )
        return str(four_d[0])
    raise KeyError(
        f"cannot find {expected!r} in dataset; 4-D candidates were {four_d}, "
        f"all variables {sorted(map(str, ds.variables))}"
    )


def normalize(ds: xr.Dataset, var: str, product: str) -> xr.Dataset:
    """Rename, re-order and clean one raw dataset into the pipeline's convention."""
    src = find_source_var(ds, var, product)
    target = CANON[var]

    keep = [src]
    if "weight" in ds.variables:
        keep.append("weight")  # Gaussian quadrature weights: the right area weighting
    out = ds[keep].rename({src: target})

    renames = {}
    if "pressure_level" in out.dims or "pressure_level" in out.coords:
        renames["pressure_level"] = "level"
    if "latitude" in out.dims or "latitude" in out.coords:
        renames["latitude"] = "lat"
    if "longitude" in out.dims or "longitude" in out.coords:
        renames["longitude"] = "lon"
    if renames:
        out = out.rename(renames)

    # JMA's fill value survives as a literal in some paths; make it NaN.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out[target] = out[target].where(np.abs(out[target]) < FILL_VALUE * 0.5)

    if out.sizes.get("lat", 0) > 1 and float(out["lat"][0]) > float(out["lat"][-1]):
        out = out.sortby("lat")

    out[target] = out[target].astype("float32")
    out[target].attrs = dict(ds[src].attrs)
    out[target].attrs.pop("_FillValue", None)
    out[target].attrs.pop("missing_value", None)
    return out


def validate_slab(ds: xr.Dataset, *, var: str, bbox: BBox, n_times: int, n_levels: int) -> dict:
    """Assert a downloaded slab is the one we asked for. Returns the check results.

    The results are stored in the sidecar so that a later audit can prove the
    check ran on every file, not just that it existed in the source.
    """
    name = CANON[var]
    checks: dict[str, object] = {}

    if name not in ds:
        raise SlabValidationError(f"normalised dataset has no {name!r}")

    shape = tuple(ds[name].shape)
    checks["shape"] = list(shape)
    if shape[0] != n_times:
        raise SlabValidationError(f"expected {n_times} analyses, got {shape[0]}")
    if shape[1] != n_levels:
        raise SlabValidationError(f"expected {n_levels} levels, got {shape[1]}")

    lat = ds["lat"].values
    lon = ds["lon"].values
    if lat.size < 2 or lon.size < 2:
        raise SlabValidationError(f"degenerate spatial slab: lat={lat.size}, lon={lon.size}")
    if not np.all(np.diff(lat) > 0):
        raise SlabValidationError("latitude is not ascending after normalisation")

    # Allow one grid cell of slack: index_range snaps outward to the nearest point.
    dlat = float(np.max(np.abs(np.diff(lat))))
    dlon = float(np.max(np.abs(np.diff(lon))))
    if lat.min() < bbox.south - dlat or lat.max() > bbox.north + dlat:
        raise SlabValidationError(
            f"latitudes {lat.min():.3f}..{lat.max():.3f} fall outside {bbox}"
        )
    if lon.min() < bbox.west - dlon or lon.max() > bbox.east + dlon:
        raise SlabValidationError(
            f"longitudes {lon.min():.3f}..{lon.max():.3f} fall outside {bbox}"
        )
    checks["lat_range"] = [float(lat.min()), float(lat.max())]
    checks["lon_range"] = [float(lon.min()), float(lon.max())]

    if "time" in ds.dims and ds.sizes["time"] > 1:
        steps = np.diff(ds["time"].values).astype("timedelta64[h]").astype(int)
        checks["time_step_hours"] = sorted({int(s) for s in steps})
        if len(set(steps)) != 1:
            raise SlabValidationError(
                f"time axis is not evenly spaced: steps {sorted(set(steps))} h"
            )

    values = ds[name].values
    finite = np.isfinite(values)
    nan_fraction = 1.0 - float(finite.mean())
    checks["nan_fraction"] = nan_fraction
    if not finite.any():
        raise SlabValidationError(f"{name} is entirely missing")
    if nan_fraction > MAX_NAN_FRACTION:
        raise SlabValidationError(
            f"{name} is {nan_fraction:.1%} missing, above the {MAX_NAN_FRACTION:.1%} limit"
        )

    vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
    checks["value_range"] = [vmin, vmax]
    limit = MAX_HEIGHT_GPM if var == "hgt" else MAX_WIND_MS
    lower = MIN_HEIGHT_GPM if var == "hgt" else -limit
    if vmin < lower or vmax > limit:
        raise SlabValidationError(
            f"{name} range {vmin:.1f}..{vmax:.1f} is outside [{lower}, {limit}]"
        )

    checks["ok"] = True
    return checks
