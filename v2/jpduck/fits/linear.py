"""Speed distributions: normal, Weibull (loc fixed at 0) and uniform.

All three are fitted to every cell at once. Two of them have closed-form
maximum-likelihood estimators, so they are numpy one-liners. The Weibull shape
needs a root find, and that root find is ``scipy.optimize.newton`` with an
array starting point -- scipy iterates, we only supply the score function.

That score function is the one piece of numerics written here rather than
called from a library, and it is written out in the documentation as part of
the deliverable: a reader is meant to be able to reproduce the fit. No library
offers batched maximum-likelihood estimation for these families -- reliability,
lifelines, statsmodels, distfit and scipy.stats.fit all fit one sample at a
time, which measures at 24 minutes for the Weibull alone across this grid
against 1.3 seconds for the vectorised route.

Every family sees exactly the same observations, and every density is per
metre per second, so the three AICs are on one scale. They are NOT on the same
scale as the direction AICs in ``circular.py``; see that module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy import optimize, stats

from ..config import (
    DEGENERATE_RANGE_MS,
    DEGENERATE_SIGMA_MS,
    NEWTON_MAXITER,
    NEWTON_TOL,
    SPEED_FLOOR_MS,
)

__all__ = [
    "SpeedFit",
    "fit_all_speed",
    "fit_normal",
    "fit_uniform",
    "fit_weibull_loc0",
    "ks_statistic",
    "newton_array",
    "weibull_score",
    "weibull_score_deriv",
]

LN_2PI = float(np.log(2.0 * np.pi))


def newton_array(func, x0, **kwargs):
    """``scipy.optimize.newton`` with a return arity that does not depend on size.

    With ``full_output=True`` scipy returns ``(root, converged, zero_der)`` for
    an array of two or more elements but ``(root, RootResults)`` for a single
    one, because a one-element array takes its scalar code path. A block of one
    cell is perfectly legal here -- the last block of a grid, or a unit test --
    so both shapes are normalised to ``(root, converged)``.
    """
    out = optimize.newton(func, x0, full_output=True, **kwargs)
    root = np.atleast_1d(out[0])
    if len(out) == 3:
        return root, np.atleast_1d(out[1])
    return root, np.atleast_1d(out[1].converged)


@dataclass(frozen=True)
class SpeedFit:
    """One family fitted to every cell in a block.

    Arrays are all ``(ncell,)``. ``params`` holds the family's own parameter
    names, so a caller writes them straight into their own columns rather than
    unpacking a positional tuple.
    """

    family: str
    n_params: int
    params: dict[str, NDArray[np.float64]]
    loglik: NDArray[np.float64]
    aic: NDArray[np.float64]
    ks: NDArray[np.float64]
    converged: NDArray[np.bool_]
    n_iter: NDArray[np.int16]
    extra: dict[str, NDArray[np.float64]] = field(default_factory=dict)


def _aic(loglik: NDArray, n_params: int) -> NDArray:
    return -2.0 * loglik + 2.0 * n_params


def ks_statistic(cdf_sorted: NDArray[np.float64]) -> NDArray[np.float64]:
    """One-sample Kolmogorov-Smirnov statistic from the fitted CDF.

    ``cdf_sorted`` is ``(ncell, n)``, the fitted CDF evaluated at that cell's
    sorted observations. Identical in form to the upstream pipeline's own
    one-at-a-time version, which the tests use as the oracle.

    No p-value accompanies it. The parameters were estimated from the same
    sample, so the standard KS null distribution does not apply, and there is
    no tabulated Lilliefors test for a two-parameter Weibull. The statistic
    still ranks families against each other, which is what it is stored for.
    """
    n = cdf_sorted.shape[1]
    i = np.arange(1, n + 1, dtype=np.float64)
    upper = (i / n) - cdf_sorted
    lower = cdf_sorted - ((i - 1.0) / n)
    return np.maximum(upper.max(axis=1), lower.max(axis=1))


# --------------------------------------------------------------- normal ----
def fit_normal(x: NDArray[np.float64], x_sorted: NDArray[np.float64]) -> SpeedFit:
    r"""Normal, by closed-form maximum likelihood.

    :math:`\hat\mu = \bar x`, :math:`\hat\sigma^2 = \frac1n\sum(x_i-\bar x)^2`
    -- note ``ddof=0``: that is the MLE. ``fact_wind.speed_std`` uses ddof=1
    and will differ slightly, which ``meta_column`` records.

    :math:`\ell = -\frac n2\left[\ln(2\pi\hat\sigma^2) + 1\right]`
    """
    n = x.shape[1]
    mu = x.mean(axis=1)
    sigma = x.std(axis=1, ddof=0)
    ok = sigma > DEGENERATE_SIGMA_MS

    loglik = np.full(mu.shape, np.nan)
    loglik[ok] = -0.5 * n * (LN_2PI + 2.0 * np.log(sigma[ok]) + 1.0)

    cdf = np.full(x_sorted.shape, np.nan)
    cdf[ok] = stats.norm.cdf(x_sorted[ok], mu[ok, None], sigma[ok, None])
    ks = np.full(mu.shape, np.nan)
    ks[ok] = ks_statistic(cdf[ok])

    # How much probability the fitted normal puts on an impossible negative
    # speed. Quantifies whether the lower bound at zero actually bites.
    prob_negative = np.full(mu.shape, np.nan)
    prob_negative[ok] = stats.norm.cdf(0.0, mu[ok], sigma[ok])

    return SpeedFit(
        family="normal",
        n_params=2,
        params={"mu_ms": mu, "sigma_ms": sigma},
        loglik=loglik,
        aic=_aic(loglik, 2),
        ks=ks,
        converged=ok,
        n_iter=np.zeros(mu.shape, dtype=np.int16),
        extra={"prob_negative": prob_negative},
    )


# -------------------------------------------------------------- uniform ----
def fit_uniform(x: NDArray[np.float64], x_sorted: NDArray[np.float64]) -> SpeedFit:
    r"""Uniform, by closed-form maximum likelihood.

    :math:`\hat a = \min x`, :math:`\hat b = \max x`,
    :math:`\ell = -n\ln(\hat b - \hat a)`.

    The estimate sits on the boundary of the parameter space, so AIC's
    regularity conditions do not strictly hold for this family. It is kept as
    a genuine candidate because the brief asks for it, and the caveat is
    recorded in ``meta_fit_family``; in practice it loses by thousands of AIC
    units, so nothing hinges on the technicality.
    """
    n = x.shape[1]
    a = x_sorted[:, 0].copy()
    b = x_sorted[:, -1].copy()
    width = b - a
    ok = width > DEGENERATE_RANGE_MS

    loglik = np.full(a.shape, np.nan)
    loglik[ok] = -n * np.log(width[ok])

    ks = np.full(a.shape, np.nan)
    cdf = (x_sorted[ok] - a[ok, None]) / width[ok, None]
    ks[ok] = ks_statistic(np.clip(cdf, 0.0, 1.0))

    return SpeedFit(
        family="uniform",
        n_params=2,
        params={"uniform_a_ms": a, "uniform_b_ms": b},
        loglik=loglik,
        aic=_aic(loglik, 2),
        ks=ks,
        converged=ok,
        n_iter=np.zeros(a.shape, dtype=np.int16),
    )


# -------------------------------------------------------------- Weibull ----
def weibull_score(k: NDArray, ly: NDArray, mly: NDArray) -> NDArray:
    r"""The Weibull shape score: :math:`\partial\ell/\partial k = 0`.

    .. math::
        g(k) = \frac{\sum_i y_i^k \ln y_i}{\sum_i y_i^k}
               - \frac1k - \overline{\ln y}

    ``ly`` is ``log(x / max(x))`` per cell and ``mly`` its row mean. Working on
    the rescaled ``y = x/max(x) <= 1`` is what keeps ``y**k`` from overflowing:
    speeds reach 118 m/s and the shape reaches ~15, and ``118**15`` is 1e31
    before the sum even starts. The score is invariant under the rescaling
    because :math:`\ln x = \ln M + \ln y` and the :math:`\ln M` cancels between
    the ratio and the mean. It also guarantees :math:`\sum y^k \ge 1`, since the
    maximum contributes exactly 1, so the denominator cannot underflow.

    ``g`` is monotone increasing in ``k``, so the root is unique and Newton
    from any positive start converges.
    """
    yk = np.exp(k[:, None] * ly)
    return (yk * ly).sum(axis=1) / yk.sum(axis=1) - 1.0 / k - mly


def weibull_score_deriv(k: NDArray, ly: NDArray, mly: NDArray) -> NDArray:  # noqa: ARG001
    r"""``d(weibull_score)/dk``.

    .. math::
        g'(k) = \frac{\sum y^k (\ln y)^2}{\sum y^k}
                - \left(\frac{\sum y^k \ln y}{\sum y^k}\right)^2 + \frac1{k^2}

    The first two terms are a variance of :math:`\ln y` under the weights
    :math:`y^k`, hence non-negative, so :math:`g' > 0` everywhere.
    """
    yk = np.exp(k[:, None] * ly)
    s0 = yk.sum(axis=1)
    a = (yk * ly).sum(axis=1) / s0
    return (yk * ly * ly).sum(axis=1) / s0 - a * a + 1.0 / (k * k)


def fit_weibull_loc0(x: NDArray[np.float64], x_sorted: NDArray[np.float64]) -> SpeedFit:
    r"""Two-parameter Weibull, location fixed at zero.

    .. math::
        f(x) = \frac k\lambda\left(\frac x\lambda\right)^{k-1}
               e^{-(x/\lambda)^k}, \qquad x \ge 0

    Free parameters are :math:`k` and :math:`\lambda` -- **two**, not three.
    The upstream pipeline charges this family for three, which penalises it by
    2 AIC units it does not owe; that is corrected here and the difference is
    recorded in ``meta_dataset``.

    Shape from the score root, then
    :math:`\lambda = \left(\frac1n\sum x_i^k\right)^{1/k}` and
    :math:`\ell = n\ln k - nk\ln\lambda + (k-1)\sum\ln x_i - n`
    (the final term is exactly ``n`` at the optimum, where
    :math:`\sum (x/\hat\lambda)^{\hat k} = n`).
    """
    n = x.shape[1]
    xf = np.maximum(x, SPEED_FLOOR_MS)
    m = xf.max(axis=1, keepdims=True)
    ly = np.log(xf / m)
    mly = ly.mean(axis=1)
    sly = ly.std(axis=1)

    ncell = xf.shape[0]
    shape = np.full(ncell, np.nan)
    scale = np.full(ncell, np.nan)
    loglik = np.full(ncell, np.nan)
    ks = np.full(ncell, np.nan)
    converged = np.zeros(ncell, dtype=bool)
    n_iter = np.zeros(ncell, dtype=np.int16)

    # A cell whose speeds are all identical has no shape to estimate.
    ok = sly > 1e-12
    if ok.any():
        # Cohen's whitening start, k0 ~ 0.9874 / sd(ln x); equivalent to
        # Menon's 1.2825/sd. Newton needs only a positive start because the
        # score is monotone, but a good one keeps it to ~5 iterations.
        k0 = np.clip(0.9874 / sly[ok], 1e-2, 1e3)
        k, conv = newton_array(
            weibull_score,
            k0,
            fprime=weibull_score_deriv,
            args=(ly[ok], mly[ok]),
            tol=NEWTON_TOL,
            maxiter=NEWTON_MAXITER,
        )
        good = conv & np.isfinite(k) & (k > 0)

        idx = np.flatnonzero(ok)[good]
        kk = k[good]
        shape[idx] = kk
        # lambda back on the original scale: M * (mean(y^k))^(1/k)
        lam = m[idx, 0] * np.exp(np.log(np.exp(kk[:, None] * ly[idx]).mean(axis=1)) / kk)
        scale[idx] = lam
        loglik[idx] = (
            n * np.log(kk)
            - n * kk * np.log(lam)
            + (kk - 1.0) * np.log(xf[idx]).sum(axis=1)
            - n
        )
        cdf = -np.expm1(-((x_sorted[idx] / lam[:, None]) ** kk[:, None]))
        ks[idx] = ks_statistic(np.clip(cdf, 0.0, 1.0))
        converged[idx] = True

    return SpeedFit(
        family="weibull_min_loc0",
        n_params=2,
        params={
            "weibull_shape": shape,
            "weibull_scale_ms": scale,
            "weibull_loc_ms": np.where(converged, 0.0, np.nan),
        },
        loglik=loglik,
        aic=_aic(loglik, 2),
        ks=ks,
        converged=converged,
        n_iter=n_iter,
    )


def fit_all_speed(x: NDArray[np.float64]) -> list[SpeedFit]:
    """Fit all three speed families to ``x`` of shape ``(ncell, n)``.

    Sorting once here rather than inside each family saves two thirds of the
    sort cost, and guarantees the three KS statistics are computed against the
    identical ordering.
    """
    if x.ndim != 2:
        raise ValueError(f"expected (ncell, n), got {x.shape}")
    x = np.ascontiguousarray(x, dtype=np.float64)
    x_sorted = np.sort(x, axis=1)
    return [
        fit_normal(x, x_sorted),
        fit_weibull_loc0(x, x_sorted),
        fit_uniform(x, x_sorted),
    ]
