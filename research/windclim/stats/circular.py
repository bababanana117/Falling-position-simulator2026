"""Direction arithmetic.

Wind direction is an angle on a circle, and almost every ordinary statistic is
wrong for it. The canonical trap:

    mean([359 deg, 1 deg]) = 180 deg

-- two winds from almost due north average to a wind from due south. The fix is
never to average angles: resolve them into eastward/northward components,
average those, and convert back at the very end. That is why this module has no
"mean direction of a sample" entry point that takes angles; direction is only
ever *derived*, in :mod:`windclim.outputs`, from means computed by
:mod:`windclim.stats.vector`. The functions here exist for the unit-vector
comparison and for converting at the boundaries.

Direction convention is meteorological throughout: the compass bearing the wind
blows *from*, north = 0, increasing clockwise. A westerly (blowing towards the
east, ``u > 0``) is 270 deg. This matches ``met_to_uv`` in
``backend/bfps/core/wind.py:45``, and the two must stay in agreement.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "circular_mean_deg",
    "circular_sd_deg",
    "met_direction_to_uv",
    "resultant_length",
    "unit_vector_mean",
    "uv_to_met_direction",
]

#: Below this resultant length the direction distribution is close to uniform or
#: is bimodal, and a "spread" is not meaningful. Reported as NaN instead.
MIN_RESULTANT_LENGTH = 0.1


def uv_to_met_direction(
    u: ArrayLike, v: ArrayLike, *, calm_eps: float = 1e-12
) -> NDArray[np.float64]:
    """Components [m/s] -> meteorological direction [deg]. Calm gives NaN.

    NaN for calm is deliberate: a zero wind has no direction, and returning 0 deg
    would silently add a northerly to every average that touches it.
    """
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    out = (np.degrees(np.arctan2(u, v)) + 180.0) % 360.0
    return np.where(np.hypot(u, v) < calm_eps, np.nan, out)


def met_direction_to_uv(
    speed: ArrayLike, direction_deg: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Meteorological direction [deg] + speed [m/s] -> ``(u, v)``.

    Identical to ``met_to_uv`` in ``backend/bfps/core/wind.py:45``.
    """
    s = np.asarray(speed, dtype=float)
    rad = np.radians(np.asarray(direction_deg, dtype=float))
    return -s * np.sin(rad), -s * np.cos(rad)


def unit_vector_mean(
    direction_deg: ArrayLike, axis: int | None = 0
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Mean of the unit vectors pointing along each direction.

    Unlike the vector mean of the wind itself, this weights every observation
    equally regardless of how strong it was. Keeping both lets the report show
    what speed-weighting actually does.
    """
    rad = np.radians(np.asarray(direction_deg, dtype=float))
    return np.nanmean(np.sin(rad), axis=axis), np.nanmean(np.cos(rad), axis=axis)


def resultant_length(direction_deg: ArrayLike, axis: int | None = 0) -> NDArray[np.float64]:
    """Mean resultant length ``R`` in [0, 1]: 1 = identical, 0 = uniform."""
    sx, cx = unit_vector_mean(direction_deg, axis=axis)
    return np.hypot(sx, cx)


def circular_mean_deg(direction_deg: ArrayLike, axis: int | None = 0) -> NDArray[np.float64]:
    """Unit-vector circular mean direction [deg]."""
    sx, cx = unit_vector_mean(direction_deg, axis=axis)
    out = np.degrees(np.arctan2(sx, cx)) % 360.0
    return np.where(np.hypot(sx, cx) < 1e-12, np.nan, out)


def circular_sd_deg(
    r: ArrayLike, *, min_r: float = MIN_RESULTANT_LENGTH
) -> NDArray[np.float64]:
    """Mardia's circular standard deviation [deg] from the resultant length.

    ``sigma = sqrt(-2 ln R)`` radians. It grows without bound as ``R -> 0``, and
    for a bimodal distribution -- exactly what the stratosphere does at the
    seasonal reversals -- it is not describing anything real. Below ``min_r`` the
    answer is NaN rather than a large number that invites over-reading.
    """
    r = np.asarray(r, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sd = np.degrees(np.sqrt(-2.0 * np.log(np.clip(r, 1e-300, 1.0))))
    return np.where(r < min_r, np.nan, sd)
