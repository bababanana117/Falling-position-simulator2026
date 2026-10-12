"""Wind statistics that are safe to average.

Everything in this module operates on the eastward/northward components ``u``
and ``v``. No function here accepts or returns a direction. That is a deliberate
structural choice rather than a stylistic one: if directions cannot enter the
accumulator, the "averaging angles" error (see :mod:`windclim.stats.circular`)
cannot be made. Directions and variance ellipses are *derived* from these
moments later, in :mod:`windclim.outputs`.

Two speeds are computed and they are not the same number:

``vector_mean_speed``
    The length of the average wind vector. This is what actually transports a
    balloon over a half: if the wind blows east half the time and west the other
    half, it is near zero.
``scalar_mean_speed``
    The average of the instantaneous speeds. It ignores direction, so in the
    same example it stays large.

``scalar >= vector`` always, and their ratio is the *constancy*: 1 means the
wind always blows the same way, 0 means the direction is unusable.
"""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "DEFAULT_PERCENTILES",
    "DEFAULT_THRESHOLDS",
    "Moments",
    "constancy",
    "effective_sample_size",
    "exceedance_freq",
    "lag1_autocorr",
    "lag_autocorr",
    "moments",
    "scalar_mean_speed",
    "speed",
    "speed_percentiles",
    "unit_component_means",
    "variance_ellipse",
    "vector_mean_speed",
]

DEFAULT_PERCENTILES: tuple[float, ...] = (10.0, 25.0, 50.0, 75.0, 90.0, 95.0)
DEFAULT_THRESHOLDS: tuple[float, ...] = (10.0, 20.0, 30.0, 40.0)


@contextmanager
def _quiet_empty_slices():
    """An all-NaN bin is a legitimate outcome (no data), not something to warn about."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        yield


@dataclass(frozen=True)
class Moments:
    """First and second moments of the wind vector over a sample axis."""

    n: NDArray[np.int64]
    u_mean: NDArray[np.float64]
    v_mean: NDArray[np.float64]
    u_var: NDArray[np.float64]
    v_var: NDArray[np.float64]
    uv_cov: NDArray[np.float64]


def speed(u: ArrayLike, v: ArrayLike) -> NDArray[np.float64]:
    return np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))


def moments(u: ArrayLike, v: ArrayLike, axis: int = 0) -> Moments:
    """Sample moments along ``axis``, ignoring NaNs.

    Accumulated in float64 even though the cache is float32: summing 400 values
    of order 50 in float32 loses about three significant digits, and the
    covariance is a difference of large numbers.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    valid = np.isfinite(u) & np.isfinite(v)
    u = np.where(valid, u, np.nan)
    v = np.where(valid, v, np.nan)

    n = valid.sum(axis=axis).astype(np.int64)
    with _quiet_empty_slices(), np.errstate(invalid="ignore"):
        um = np.nanmean(u, axis=axis)
        vm = np.nanmean(v, axis=axis)
        du = u - np.expand_dims(um, axis)
        dv = v - np.expand_dims(vm, axis)
        denom = np.maximum(n - 1, 1).astype(np.float64)
        uu = np.nansum(du * du, axis=axis) / denom
        vv = np.nansum(dv * dv, axis=axis) / denom
        uv = np.nansum(du * dv, axis=axis) / denom

    too_few = n < 2
    uu = np.where(too_few, np.nan, uu)
    vv = np.where(too_few, np.nan, vv)
    uv = np.where(too_few, np.nan, uv)
    return Moments(n=n, u_mean=um, v_mean=vm, u_var=uu, v_var=vv, uv_cov=uv)


def vector_mean_speed(u_mean: ArrayLike, v_mean: ArrayLike) -> NDArray[np.float64]:
    """Length of the mean wind vector -- the net transport."""
    return np.hypot(np.asarray(u_mean, dtype=float), np.asarray(v_mean, dtype=float))


def scalar_mean_speed(u: ArrayLike, v: ArrayLike, axis: int = 0) -> NDArray[np.float64]:
    """Mean of the instantaneous speeds -- how strong the wind typically is."""
    with _quiet_empty_slices():
        return np.nanmean(speed(u, v), axis=axis)


def constancy(
    speed_vector_mean: ArrayLike, speed_mean: ArrayLike, *, calm_eps: float = 1e-12
) -> NDArray[np.float64]:
    """``vector_mean / scalar_mean`` in [0, 1]. NaN where the scalar mean is calm.

    Low constancy is the signal that the mean direction is not worth reading:
    the wind reverses within the bin rather than blowing steadily.
    """
    vm = np.asarray(speed_vector_mean, dtype=float)
    sm = np.asarray(speed_mean, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = vm / sm
    return np.where(sm < calm_eps, np.nan, np.clip(out, 0.0, 1.0))


def variance_ellipse(
    u_var: ArrayLike, v_var: ArrayLike, uv_cov: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """1-sigma ellipse of the wind-vector scatter.

    Returns ``(major, minor, angle_deg)`` where the semi-axes are in m/s and the
    angle is measured counter-clockwise from east, in [0, 180).

    This is the closed-form eigendecomposition of the symmetric 2x2 covariance
    matrix; the same closed form is used in ``frontend/src/stats/landing.ts`` for
    landing scatter. Note the ellipse assumes the ``(u, v)`` scatter is roughly
    bivariate normal, which fails during the stratospheric reversal seasons when
    the distribution is bimodal -- hence figure F7's wind roses.
    """
    a = np.asarray(u_var, dtype=float)
    c = np.asarray(v_var, dtype=float)
    b = np.asarray(uv_cov, dtype=float)
    half_sum = 0.5 * (a + c)
    root = np.sqrt(np.maximum((0.5 * (a - c)) ** 2 + b**2, 0.0))
    lam_max = half_sum + root
    lam_min = np.maximum(half_sum - root, 0.0)
    angle = np.degrees(0.5 * np.arctan2(2.0 * b, a - c)) % 180.0
    return np.sqrt(np.maximum(lam_max, 0.0)), np.sqrt(lam_min), angle


def speed_percentiles(
    u: ArrayLike, v: ArrayLike, qs: tuple[float, ...] = DEFAULT_PERCENTILES, axis: int = 0
) -> NDArray[np.float64]:
    """Empirical percentiles of the scalar speed, shape ``(len(qs), ...)``.

    Percentiles are taken on the speed, never on the direction: a direction has
    no ordering without an arbitrary branch cut. They cannot be recovered from
    the moments either, which is why the aggregation keeps every sample of a bin
    in memory rather than accumulating running sums.
    """
    s = speed(u, v)
    with _quiet_empty_slices():
        return np.nanpercentile(s, np.asarray(qs, dtype=float), axis=axis)


def exceedance_freq(
    u: ArrayLike, v: ArrayLike, thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS, axis: int = 0
) -> NDArray[np.float64]:
    """Fraction of samples with speed above each threshold, shape ``(len(thresholds), ...)``."""
    s = speed(u, v)
    valid = np.isfinite(s)
    n = valid.sum(axis=axis)
    out = []
    for t in thresholds:
        hits = np.sum(valid & (s > t), axis=axis)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append(np.where(n > 0, hits / n, np.nan))
    return np.asarray(out, dtype=float)


def unit_component_means(
    u: ArrayLike, v: ArrayLike, axis: int = 0, *, calm_eps: float = 1e-12
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Mean of the *unit* wind vectors: every analysis counts the same.

    The plain vector mean is speed-weighted, which is the physically right choice
    for transport -- a strong wind moves a balloon further. But it means one
    storm can outvote a fortnight of light wind from the other direction. Keeping
    the unweighted version too lets the report show the difference instead of
    asserting it, and their ratio is the resultant length R used for the circular
    spread.

    Still expressed in components, so no direction enters the accumulator.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    sp = np.hypot(u, v)
    with np.errstate(invalid="ignore", divide="ignore"):
        uu = np.where(sp > calm_eps, u / sp, np.nan)
        vv = np.where(sp > calm_eps, v / sp, np.nan)
    with _quiet_empty_slices():
        return np.nanmean(uu, axis=axis), np.nanmean(vv, axis=axis)


def lag_autocorr(x: ArrayLike, lag: int = 1, axis: int = 0) -> NDArray[np.float64]:
    """Autocorrelation at ``lag`` steps along ``axis``, ignoring NaNs.

    Lag 1 is what the effective sample size needs, and for a long time that was
    the only lag anyone asked for. The whole curve is a different question: how
    long does it take for the wind to forget what it was doing? That is answered
    by walking the lag out until the correlation falls through ``1/e``, which
    needs every lag, not just the first.
    """
    x = np.asarray(x, dtype=np.float64)
    if lag < 1:
        raise ValueError(f"lag must be at least 1, got {lag}")
    n = x.shape[axis]
    if lag >= n:
        return np.full(np.delete(x.shape, axis), np.nan)
    a = np.take(x, np.arange(0, n - lag), axis=axis)
    b = np.take(x, np.arange(lag, n), axis=axis)
    ok = np.isfinite(a) & np.isfinite(b)
    a = np.where(ok, a, np.nan)
    b = np.where(ok, b, np.nan)
    with np.errstate(invalid="ignore"):
        am = np.nanmean(a, axis=axis, keepdims=True)
        bm = np.nanmean(b, axis=axis, keepdims=True)
        num = np.nansum((a - am) * (b - bm), axis=axis)
        den = np.sqrt(
            np.nansum((a - am) ** 2, axis=axis) * np.nansum((b - bm) ** 2, axis=axis)
        )
        r = np.where(den > 0, num / den, np.nan)
    return np.clip(r, -0.999, 0.999)


def lag1_autocorr(x: ArrayLike, axis: int = 0) -> NDArray[np.float64]:
    """Lag-1 autocorrelation along ``axis``. Kept as the name the aggregation uses."""
    return lag_autocorr(x, 1, axis=axis)


def effective_sample_size(n: ArrayLike, r1: ArrayLike) -> NDArray[np.float64]:
    """``n_eff = n (1 - r1) / (1 + r1)``, clipped to ``[1, n]``.

    280 six-hourly analyses in a half bin are nowhere near 280 independent
    observations: consecutive analyses six hours apart are nearly identical, and
    a synoptic system takes two to five days to pass. The effective count is
    typically 20-40, so a standard error built from ``n`` would overstate
    confidence by about a factor of three. Every uncertainty in the report is
    built from this instead.
    """
    n = np.asarray(n, dtype=float)
    r1 = np.asarray(r1, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = n * (1.0 - r1) / (1.0 + r1)
    out = np.where(np.isfinite(out), out, n)
    return np.clip(out, 1.0, n)
