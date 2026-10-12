"""Fit a distribution to the observed wind speeds, then fly samples from it.

Chapter 6 says the Wakayama winter has a steady *direction* and a variable
*speed*. This module turns that sentence into a distribution and then into a
cloud of landing points, which is what a launch campaign can actually act on.

Three questions, in order.

**What shape is the speed distribution?** Not one shape. Fitting each pressure
level separately and comparing by AIC, the troposphere and the lower
stratosphere are close to Gaussian while the jet and the upper stratosphere are
better described by a Weibull. A uniform distribution is rejected everywhere by
a wide margin, so "the speed is all over the place" is not the right picture:
the speed has a clear central value and a well-behaved spread.

**Are the levels independent?** No, and this matters more than the choice of
marginal. Sampling each level on its own is the obvious thing to do and it is
wrong: independent errors partly cancel when the flight integrates through
them, so the landing cloud comes out far too tight. The observed speeds at
200 and 100 hPa correlate at 0.64. A Gaussian copula built from the observed
rank correlations keeps that structure while leaving each level's marginal
exactly as fitted, and :func:`sample_speeds` does both versions so the
difference can be shown rather than asserted.

**What does the balloon add?** The web app perturbs three flight parameters and
does not perturb the wind at all (``frontend/src/mc/sampling.ts``): ascent rate
and descent rate get a Gaussian, and the burst altitude gets either a Gaussian
on a percentage or a Weibull with shape 3. :class:`FlightSigma` carries the
app's own defaults so the two sources of spread can be put on one picture.

What this does **not** model
----------------------------
The direction is held at each level's climatological mean. That is the premise
being tested, not an oversight, and it costs something: the layers where the
direction really is steady (500-100 hPa, direction SD 9-17 degrees) carry
148 km of the 264 km mean winter flight, while the layers where it is not
steady (30-10 hPa, SD 58-96 degrees) carry only 25 km. The reference cloud from
the real profiles includes the direction variability, so comparing against it
shows how much is being left out.

The flight model is the frozen one the simulator uses, not the gridded
integrator of :mod:`windclim.stats.trajectory`. That keeps this comparable with
the web app; the frozen-wind error is a separate few kilometres measured in its
own chapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from .drift import FlightProfile, displacements, layer_seconds

__all__ = [
    "FlightSigma",
    "sample_directions",
    "LevelFit",
    "SpeedModel",
    "fit_speeds",
    "sample_flight_params",
    "sample_speeds",
    "simulate_landings",
]


@dataclass(frozen=True)
class LevelFit:
    """The marginal chosen for one pressure level."""

    level_hpa: float
    family: str                      # "norm" or "weibull"
    params: tuple[float, ...]
    aic: float
    aic_norm: float
    aic_weibull: float
    aic_uniform: float
    ks: float
    mean: float
    sd: float

    @property
    def dist(self):
        return stats.norm if self.family == "norm" else stats.weibull_min


@dataclass
class SpeedModel:
    """Per-level marginals plus the correlation that ties them together."""

    fits: list[LevelFit]
    #: Spearman rank correlation of the observed speeds between levels.
    rank_corr: NDArray[np.float64]
    #: Mean direction of each level.
    mean_dir_deg: NDArray[np.float64]
    #: Circular standard deviation of the direction at each level, in degrees.
    #: Kept so the cost of holding the direction fixed can be measured rather
    #: than assumed -- see :func:`sample_directions`.
    dir_sd_deg: NDArray[np.float64] = field(default_factory=lambda: np.array([]))
    levels_hpa: NDArray[np.float64] = field(default_factory=lambda: np.array([]))

    @property
    def n_levels(self) -> int:
        return len(self.fits)


def _ks(x: NDArray, dist, params) -> float:
    """One-sample KS statistic, written out because scipy's kstest is fussy here."""
    n = x.size
    cdf = dist.cdf(np.sort(x), *params)
    e = np.arange(1, n + 1) / n
    return float(max(np.max(np.abs(cdf - e)), np.max(np.abs(cdf - (e - 1 / n)))))


def fit_speeds(
    u: NDArray[np.float64], v: NDArray[np.float64], levels_hpa: NDArray[np.float64]
) -> SpeedModel:
    """Fit a marginal to each level's speed and record how the levels co-vary.

    ``u``/``v`` are ``(sample, level)``. The family is chosen per level by AIC
    between a normal and a two-parameter Weibull; a uniform is fitted too, not
    as a candidate but so the report can quote how badly it loses.
    """
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    if u.shape != v.shape:
        raise ValueError(f"u {u.shape} and v {v.shape} differ")
    if u.shape[1] != len(levels_hpa):
        raise ValueError(
            f"{u.shape[1]} level columns but {len(levels_hpa)} level labels"
        )
    speed = np.hypot(u, v)

    fits: list[LevelFit] = []
    for k, level in enumerate(np.asarray(levels_hpa, dtype=float)):
        x = speed[:, k]
        x = x[np.isfinite(x)]
        a, b = stats.norm.fit(x)
        aic_n = -2 * stats.norm.logpdf(x, a, b).sum() + 4
        c, lo, sc = stats.weibull_min.fit(x, floc=0.0)
        aic_w = -2 * stats.weibull_min.logpdf(x, c, lo, sc).sum() + 6
        l0, w0 = stats.uniform.fit(x)
        aic_u = -2 * stats.uniform.logpdf(x, l0, w0).sum() + 4

        if aic_n <= aic_w:
            family, params, aic = "norm", (a, b), aic_n
        else:
            family, params, aic = "weibull", (c, lo, sc), aic_w
        dist = stats.norm if family == "norm" else stats.weibull_min
        fits.append(LevelFit(
            level_hpa=float(level), family=family, params=params, aic=aic,
            aic_norm=aic_n, aic_weibull=aic_w, aic_uniform=aic_u,
            ks=_ks(x, dist, params), mean=float(x.mean()), sd=float(x.std(ddof=1)),
        ))

    rank = stats.spearmanr(speed).statistic
    rank = np.atleast_2d(np.asarray(rank, dtype=float))
    # A level with no variation gives NaN; treat it as uncorrelated rather than
    # letting the NaN poison the whole matrix.
    rank = np.nan_to_num(rank, nan=0.0)
    np.fill_diagonal(rank, 1.0)

    with np.errstate(invalid="ignore"):
        mean_dir = (np.degrees(np.arctan2(u.mean(axis=0), v.mean(axis=0))) + 180.0) % 360.0
        # Mardia's circular SD from the unit-vector resultant. Angles are never
        # averaged directly; see windclim.stats.circular for why.
        sp_safe = np.where(speed > 1e-12, speed, np.nan)
        rbar = np.hypot(np.nanmean(u / sp_safe, axis=0), np.nanmean(v / sp_safe, axis=0))
        dir_sd = np.degrees(np.sqrt(-2.0 * np.log(np.clip(rbar, 1e-12, 1.0))))

    return SpeedModel(
        fits=fits, rank_corr=rank, mean_dir_deg=mean_dir, dir_sd_deg=dir_sd,
        levels_hpa=np.asarray(levels_hpa, dtype=float),
    )


def _gaussian_copula_correlation(rank: NDArray[np.float64]) -> NDArray[np.float64]:
    """Turn Spearman rho into the Gaussian correlation that reproduces it.

    ``rho_Pearson = 2 sin(pi rho_Spearman / 6)`` for a Gaussian copula. Using
    the rank correlation directly would be close but slightly wrong, and the
    conversion costs one line.
    """
    corr = 2.0 * np.sin(np.pi * np.clip(rank, -1.0, 1.0) / 6.0)
    np.fill_diagonal(corr, 1.0)
    # Nearest positive-definite via eigenvalue clipping: the pairwise estimates
    # need not form a valid correlation matrix, and the Cholesky below needs one.
    w, q = np.linalg.eigh((corr + corr.T) / 2.0)
    corr = q @ np.diag(np.maximum(w, 1e-8)) @ q.T
    d = np.sqrt(np.diag(corr))
    return corr / np.outer(d, d)


def sample_speeds(
    model: SpeedModel, n: int, *, correlated: bool = True, seed: int = 0
) -> NDArray[np.float64]:
    """Draw ``n`` speed profiles, shaped ``(n, level)``.

    ``correlated=False`` samples each level on its own. That is the version
    worth drawing precisely because it is wrong: the flight sums the levels, so
    independent draws cancel and the landing cloud shrinks.
    """
    rng = np.random.default_rng(seed)
    k = model.n_levels
    if correlated:
        corr = _gaussian_copula_correlation(model.rank_corr)
        z = rng.multivariate_normal(np.zeros(k), corr, size=n, method="cholesky")
        uni = stats.norm.cdf(z)
    else:
        uni = rng.random((n, k))

    out = np.empty((n, k))
    for j, fit in enumerate(model.fits):
        out[:, j] = fit.dist.ppf(np.clip(uni[:, j], 1e-9, 1 - 1e-9), *fit.params)
    return np.maximum(out, 0.0)


def sample_directions(
    model: SpeedModel, n: int, *, correlated: bool = True, seed: int = 0
) -> NDArray[np.float64]:
    """Draw ``n`` direction profiles about each level's mean, in degrees.

    A wrapped normal with the level's own circular SD, coupled across levels by
    the same copula the speeds use. This exists to answer one question: holding
    the direction fixed is the premise of the whole exercise, and the only
    honest way to report what that premise costs is to relax it and look.

    Note that "the direction is steady" and "the direction does not move the
    landing point" are different statements. A constancy of 0.98 still leaves a
    circular SD of about 11 degrees, and 11 degrees across a 264 km flight is
    50 km of cross-track spread.
    """
    rng = np.random.default_rng(seed)
    k = model.n_levels
    if correlated:
        corr = _gaussian_copula_correlation(model.rank_corr)
        z = rng.multivariate_normal(np.zeros(k), corr, size=n, method="cholesky")
    else:
        z = rng.standard_normal((n, k))
    sd = np.nan_to_num(np.asarray(model.dir_sd_deg, dtype=float), nan=0.0)
    return model.mean_dir_deg[None, :] + z * sd[None, :]


@dataclass(frozen=True)
class FlightSigma:
    """The web app's own perturbation sizes (``frontend/src/mc/sampling.ts``).

    The defaults are the ones the Monte Carlo panel opens with. The app clips
    each draw the same way, so the clips are reproduced here rather than
    tidied away: they are part of what the app actually samples.
    """

    ascent_ms: float = 0.5
    burst_pct: float = 5.0
    descent_ms: float = 0.5
    burst_model: str = "gaussian"     # or "weibull", shape 3.0
    weibull_shape: float = 3.0


def sample_flight_params(
    base: FlightProfile, sigma: FlightSigma, n: int, *, seed: int = 0
) -> tuple[NDArray, NDArray, NDArray]:
    """Draw ``n`` (ascent, burst, descent) triples the way the web app does."""
    rng = np.random.default_rng(seed)
    if sigma.burst_model == "weibull":
        ascent = np.full(n, base.ascent_rate_ms)
        descent = np.full(n, base.descent_rate_ms)
        burst = base.burst_altitude_m * rng.weibull(sigma.weibull_shape, n)
    elif sigma.burst_model == "gaussian":
        ascent = rng.normal(base.ascent_rate_ms, sigma.ascent_ms, n)
        descent = rng.normal(base.descent_rate_ms, sigma.descent_ms, n)
        burst = rng.normal(
            base.burst_altitude_m, base.burst_altitude_m * sigma.burst_pct / 100.0, n
        )
    else:
        raise ValueError(f"burst_model must be 'gaussian' or 'weibull', got {sigma.burst_model!r}")
    return (
        np.maximum(ascent, 0.1),
        np.maximum(burst, 1000.0),
        np.maximum(descent, 0.5),
    )


def simulate_landings(
    speeds: NDArray[np.float64],
    direction_deg: NDArray[np.float64],
    alt_m: NDArray[np.float64],
    flight: FlightProfile,
    *,
    ascent_ms: NDArray | None = None,
    burst_m: NDArray | None = None,
    descent_ms: NDArray | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Landing displacement in km for each sampled profile.

    ``speeds`` is ``(sample, level)`` ascending in altitude, ``direction_deg``
    is the meteorological direction per level. The three optional arrays
    perturb the flight itself; leaving them out flies every sample with the
    nominal profile, which isolates the wind.
    """
    speeds = np.asarray(speeds, dtype=float)
    rad = np.radians(np.asarray(direction_deg, dtype=float))
    # direction_deg is either one profile shared by every sample, or one per
    # sample; broadcasting handles both without the caller saying which.
    if rad.ndim == 1:
        rad = rad[None, :]
    u = -speeds * np.sin(rad)
    v = -speeds * np.cos(rad)

    if ascent_ms is None and burst_m is None and descent_ms is None:
        dx, dy = displacements(
            u[:, :, None, None], v[:, :, None, None], np.asarray(alt_m)[:, None, None],
            flight,
        )
        return dx[:, 0, 0] / 1000.0, dy[:, 0, 0] / 1000.0

    n = speeds.shape[0]
    ascent = np.full(n, flight.ascent_rate_ms) if ascent_ms is None else np.asarray(ascent_ms)
    burst = np.full(n, flight.burst_altitude_m) if burst_m is None else np.asarray(burst_m)
    descent = np.full(n, flight.descent_rate_ms) if descent_ms is None else np.asarray(descent_ms)

    alt = np.asarray(alt_m, dtype=float)
    dx = np.empty(n)
    dy = np.empty(n)
    for i in range(n):
        # Each sample gets its own layer times, because the flight parameters
        # are what set them. This is the slow path and is only taken when the
        # caller asked for the balloon to be perturbed too.
        f = FlightProfile(
            ascent_rate_ms=float(ascent[i]),
            burst_altitude_m=float(burst[i]),
            descent_rate_ms=float(descent[i]),
            launch_altitude_m=flight.launch_altitude_m,
        )
        t = layer_seconds(alt, f)
        dx[i] = float(np.nansum(u[i] * t)) / 1000.0
        dy[i] = float(np.nansum(v[i] * t)) / 1000.0
    return dx, dy
