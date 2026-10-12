"""Direction distributions: von Mises, wrapped normal, circular uniform.

A direction is an angle, so the candidate set is not the one used for speed.
A Weibull has support [0, inf) and is not invariant under rotation of the
angular origin: 359 deg and 1 deg are 2 deg apart on a circle but 358 apart on
a line, and a Weibull's fitted shape would change if the origin moved from
north to east. A distribution for an angle must be periodic. That is why
Weibull is excluded here, and ``meta_fit_family`` carries the reason as data
rather than leaving it to prose.

Densities here are per **radian**. Had the fits been done in degrees every
log-likelihood would shift by ``n*ln(180/pi)``, so direction AICs are
comparable with each other and never with the speed AICs in ``linear.py``.
The two live in separate tables for that reason.

Angles arrive as meteorological FROM-directions in radians, wrapped to
(-pi, pi]. The mean direction is never computed by averaging angles: the
mean of 359 and 1 degrees would come out as 180. It is derived from the mean
of the unit vectors instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import special, stats

from ..config import (
    DEGENERATE_SIGMA_RAD,
    KAPPA_MAX,
    NEWTON_MAXITER,
    NEWTON_TOL,
    WN_FOURIER_SWITCH_R,
    WN_FOURIER_TERMS,
    WN_SPATIAL_TERMS,
)
from .linear import newton_array

__all__ = [
    "CircularMoments",
    "DirFit",
    "circular_moments",
    "fit_all_direction",
    "fit_circular_uniform",
    "fit_von_mises",
    "fit_wrapped_normal",
    "kuiper_statistic",
    "von_mises_score",
    "von_mises_score_deriv",
    "wrapped_normal_cdf",
    "wrapped_normal_logpdf",
]

LN_2PI = float(np.log(2.0 * np.pi))
TWO_PI = 2.0 * np.pi


@dataclass(frozen=True)
class CircularMoments:
    """The sufficient statistics all three circular families share."""

    cbar: NDArray[np.float64]   # mean cos
    sbar: NDArray[np.float64]   # mean sin
    rbar: NDArray[np.float64]   # resultant length, hypot(cbar, sbar)
    mu: NDArray[np.float64]     # atan2(sbar, cbar), radians in (-pi, pi]


@dataclass(frozen=True)
class DirFit:
    family: str
    n_params: int
    estimator: str              # 'mle' or 'mom'
    params: dict[str, NDArray[np.float64]]
    loglik: NDArray[np.float64]
    aic: NDArray[np.float64]
    kuiper: NDArray[np.float64]
    converged: NDArray[np.bool_]
    n_iter: NDArray[np.int16]


def _aic(loglik: NDArray, n_params: int) -> NDArray:
    return -2.0 * loglik + 2.0 * n_params


def wrap_pi(a: NDArray) -> NDArray:
    """Wrap to (-pi, pi]."""
    return (a + np.pi) % TWO_PI - np.pi


def circular_moments(theta: NDArray[np.float64]) -> CircularMoments:
    """Trigonometric moments of ``(ncell, n)`` angles in radians."""
    cbar = np.cos(theta).mean(axis=1)
    sbar = np.sin(theta).mean(axis=1)
    return CircularMoments(
        cbar=cbar,
        sbar=sbar,
        rbar=np.clip(np.hypot(cbar, sbar), 0.0, 1.0),
        mu=np.arctan2(sbar, cbar),
    )


def kuiper_statistic(u_sorted: NDArray[np.float64]) -> NDArray[np.float64]:
    r"""Kuiper's :math:`V = D^+ + D^-` from the fitted CDF at sorted angles.

    Kuiper rather than Kolmogorov-Smirnov because it is **invariant to
    rotation of the circle** and KS is not: KS anchors at an arbitrary origin,
    so rotating the data changes the answer. That invariance is also what lets
    each family be anchored at its own estimated mean without biasing the
    comparison between families.
    """
    n = u_sorted.shape[1]
    i = np.arange(1, n + 1, dtype=np.float64)
    d_plus = ((i / n) - u_sorted).max(axis=1)
    d_minus = (u_sorted - ((i - 1.0) / n)).max(axis=1)
    return d_plus + d_minus


# ------------------------------------------------------------ von Mises ----
def _a_ratio(k: NDArray) -> NDArray:
    """:math:`A(\\kappa) = I_1(\\kappa)/I_0(\\kappa)`.

    Uses the exponentially scaled Bessel functions, whose ratio is exact and
    cannot overflow: ``i0e(k) = exp(-|k|) I0(k)``, so the ``exp`` cancels.
    """
    return special.i1e(k) / special.i0e(k)


def von_mises_score(k: NDArray, rbar: NDArray) -> NDArray:
    r"""The concentration score: :math:`A(\kappa) - \bar R = 0`."""
    return _a_ratio(k) - rbar


def von_mises_score_deriv(k: NDArray, rbar: NDArray) -> NDArray:  # noqa: ARG001
    r""":math:`A'(\kappa) = 1 - A^2 - A/\kappa`."""
    a = _a_ratio(k)
    return 1.0 - a * a - a / k


def _kappa_start(rbar: NDArray) -> NDArray:
    """Fisher's piecewise approximation to the concentration (Fisher 1993)."""
    r = np.clip(rbar, 1e-12, 1.0 - 1e-12)
    k = np.empty_like(r)
    lo = r < 0.53
    mid = (r >= 0.53) & (r < 0.85)
    hi = r >= 0.85
    k[lo] = 2.0 * r[lo] + r[lo] ** 3 + 5.0 * r[lo] ** 5 / 6.0
    k[mid] = -0.4 + 1.39 * r[mid] + 0.43 / (1.0 - r[mid])
    k[hi] = 1.0 / (r[hi] ** 3 - 4.0 * r[hi] ** 2 + 3.0 * r[hi])
    return np.clip(k, 1e-6, KAPPA_MAX)


def fit_von_mises(theta_sorted: NDArray, m: CircularMoments) -> DirFit:
    r"""von Mises, by maximum likelihood.

    .. math::
        f(\theta) = \frac{e^{\kappa\cos(\theta-\mu)}}{2\pi I_0(\kappa)}

    :math:`\hat\mu = \operatorname{atan2}(\bar S, \bar C)` in closed form;
    :math:`\hat\kappa` solves :math:`I_1(\kappa)/I_0(\kappa) = \bar R`, found
    with ``scipy.optimize.newton`` over the whole block at once.

    The log-likelihood is written with the scaled Bessel function so that it
    stays finite at large concentration:

    .. math::
        \ell = n\left[\kappa\bar R - \kappa - \ln 2\pi - \ln i_{0e}(\kappa)\right]

    using :math:`\ln I_0(\kappa) = \ln i_{0e}(\kappa) + \kappa`.
    """
    n = theta_sorted.shape[1]
    ncell = m.rbar.shape[0]
    kappa = np.full(ncell, np.nan)
    loglik = np.full(ncell, np.nan)
    kuiper = np.full(ncell, np.nan)
    converged = np.zeros(ncell, dtype=bool)

    k, conv = newton_array(
        von_mises_score,
        _kappa_start(m.rbar),
        fprime=von_mises_score_deriv,
        args=(m.rbar,),
        tol=NEWTON_TOL,
        maxiter=NEWTON_MAXITER,
    )
    conv = conv & np.isfinite(k) & (k >= 0) & (k < KAPPA_MAX)

    idx = np.flatnonzero(conv)
    if idx.size:
        kk = k[idx]
        kappa[idx] = kk
        loglik[idx] = n * (
            kk * m.rbar[idx] - kk - LN_2PI - np.log(special.i0e(kk))
        )
        # scipy's own CDF: a library call, and the test suite checks it against
        # the exact Bessel series in reference.py.
        delta = wrap_pi(theta_sorted[idx] - m.mu[idx, None])
        u = stats.vonmises.cdf(delta, kk[:, None])
        kuiper[idx] = kuiper_statistic(np.clip(np.sort(u, axis=1), 0.0, 1.0))
        converged[idx] = True

    return DirFit(
        family="von_mises",
        n_params=2,
        estimator="mle",
        params={"mu_rad": m.mu, "kappa": kappa},
        loglik=loglik,
        aic=_aic(loglik, 2),
        kuiper=kuiper,
        converged=converged,
        n_iter=np.zeros(ncell, dtype=np.int16),
    )


# ------------------------------------------------------- wrapped normal ----
def wrapped_normal_logpdf(delta: NDArray, sigma: NDArray, rbar: NDArray) -> NDArray:
    r"""Log density of the wrapped normal at ``delta = wrap(theta - mu)``.

    .. math::
        f(\theta) = \frac1{\sigma\sqrt{2\pi}}
                    \sum_{j=-\infty}^{\infty} e^{-(\theta-\mu+2\pi j)^2/2\sigma^2}

    Two representations, switched on :math:`\bar R`:

    * **Narrow** (:math:`\bar R > 0.5`, i.e. :math:`\sigma \le 1.177`): the
      spatial sum above, truncated at :math:`|j| \le 3`. The neglected term is
      bounded by :math:`e^{-(2\pi J-\pi)^2/2\sigma^2} \le e^{-89}`.
    * **Broad** (:math:`\bar R \le 0.5`): the Fourier form
      :math:`f = \frac1{2\pi}\bigl(1 + 2\sum_{p\ge1}\bar R^{p^2}\cos p\Delta\bigr)`,
      truncated at :math:`p \le 12`, where :math:`\bar R^{p^2}` is 1e-43.

    Each form converges fast exactly where the other does not. Both were
    checked against an 801-term brute force and agree to 8.9e-16 or better.
    """
    out = np.empty_like(delta)
    narrow = rbar > WN_FOURIER_SWITCH_R

    if narrow.any():
        d = delta[narrow]
        s = sigma[narrow][:, None]
        j = np.arange(-WN_SPATIAL_TERMS, WN_SPATIAL_TERMS + 1, dtype=np.float64)
        z = (d[..., None] + TWO_PI * j) / s[..., None]
        terms = -0.5 * z * z
        out[narrow] = special.logsumexp(terms, axis=-1) - np.log(s) - 0.5 * LN_2PI

    broad = ~narrow
    if broad.any():
        d = delta[broad]
        r = rbar[broad][:, None]
        p = np.arange(1, WN_FOURIER_TERMS + 1, dtype=np.float64)
        # r**(p*p) underflows to 0 harmlessly for small r and large p.
        coef = r[..., None] ** (p * p)
        series = 1.0 + 2.0 * (coef * np.cos(p * d[..., None])).sum(axis=-1)
        # Positive throughout for r <= 0.5 (minimum 0.121 at delta = pi), but a
        # silent negative would poison the log, so clamp and let the caller see
        # it as a finite number rather than a NaN.
        out[broad] = np.log(np.maximum(series, 1e-300)) - LN_2PI

    return out


def wrapped_normal_cdf(delta: NDArray, sigma: NDArray, rbar: NDArray) -> NDArray:
    """CDF of the wrapped normal on (-pi, pi], same branching as the density.

    No library implements the wrapped normal, so this is written out here and
    verified in the tests against numerical integration of the density.
    """
    out = np.empty_like(delta)
    narrow = rbar > WN_FOURIER_SWITCH_R

    if narrow.any():
        d = delta[narrow]
        s = sigma[narrow][:, None]
        j = np.arange(-WN_SPATIAL_TERMS, WN_SPATIAL_TERMS + 1, dtype=np.float64)
        hi = special.ndtr((d[..., None] + TWO_PI * j) / s[..., None])
        lo = special.ndtr((-np.pi + TWO_PI * j) / s[..., None])
        out[narrow] = (hi - lo).sum(axis=-1)

    broad = ~narrow
    if broad.any():
        d = delta[broad]
        r = rbar[broad][:, None]
        p = np.arange(1, WN_FOURIER_TERMS + 1, dtype=np.float64)
        coef = r[..., None] ** (p * p)
        series = (coef * np.sin(p * d[..., None]) / p).sum(axis=-1)
        out[broad] = 0.5 + d / TWO_PI + series / np.pi

    return np.clip(out, 0.0, 1.0)


def fit_wrapped_normal(theta_sorted: NDArray, m: CircularMoments) -> DirFit:
    r"""Wrapped normal, by moment matching.

    :math:`\hat\mu` is the circular mean and
    :math:`\hat\sigma = \sqrt{-2\ln\bar R}` -- Mardia's circular standard
    deviation, which matches the first trigonometric moment exactly.

    This is a **method-of-moments** estimator, not maximum likelihood: the
    wrapped normal has no closed-form MLE for sigma and no library fits one.
    The AIC is therefore a quasi-AIC evaluated at moment-matched parameters,
    and ``estimator = 'mom'`` on every row says so. A von Mises versus
    wrapped-normal comparison is indicative rather than formal; the two agree
    closely for :math:`\bar R > 0.7` in any case.

    ``wn_sigma_deg`` equals ``fact_wind.circ_sd_deg`` except that it is
    populated everywhere, including where the resultant length falls below the
    0.1 presentation threshold -- the AIC comparison has to be complete.
    """
    ncell = m.rbar.shape[0]
    sigma = np.full(ncell, np.nan)
    loglik = np.full(ncell, np.nan)
    kuiper = np.full(ncell, np.nan)
    converged = np.zeros(ncell, dtype=bool)

    r = np.clip(m.rbar, 1e-300, 1.0 - 1e-15)
    s = np.sqrt(-2.0 * np.log(r))
    ok = np.isfinite(s) & (s > DEGENERATE_SIGMA_RAD)

    idx = np.flatnonzero(ok)
    if idx.size:
        sigma[idx] = s[idx]
        delta = wrap_pi(theta_sorted[idx] - m.mu[idx, None])
        loglik[idx] = wrapped_normal_logpdf(delta, s[idx], m.rbar[idx]).sum(axis=1)
        u = wrapped_normal_cdf(delta, s[idx], m.rbar[idx])
        kuiper[idx] = kuiper_statistic(np.sort(u, axis=1))
        converged[idx] = True

    return DirFit(
        family="wrapped_normal",
        n_params=2,
        estimator="mom",
        params={"mu_rad": m.mu, "wn_sigma_rad": sigma},
        loglik=loglik,
        aic=_aic(loglik, 2),
        kuiper=kuiper,
        converged=converged,
        n_iter=np.zeros(ncell, dtype=np.int16),
    )


# ------------------------------------------------------ circular uniform ---
def fit_circular_uniform(theta_sorted: NDArray, m: CircularMoments) -> DirFit:
    r"""Circular uniform: no parameters at all.

    :math:`f(\theta) = 1/2\pi`, :math:`\ell = -n\ln 2\pi`, :math:`k = 0`.

    This is the null model -- "the direction has no preferred value". Unlike
    the *linear* uniform it is perfectly regular, with no boundary problem, so
    its AIC is fully legitimate. When the resultant length approaches zero the
    von Mises concentration goes to zero too and loses to this by exactly 4
    AIC units, which is the correct answer and needs no special-casing.
    """
    n = theta_sorted.shape[1]
    ncell = m.rbar.shape[0]
    loglik = np.full(ncell, -n * LN_2PI)
    u = (theta_sorted + np.pi) / TWO_PI
    kuiper = kuiper_statistic(np.clip(np.sort(u, axis=1), 0.0, 1.0))
    return DirFit(
        family="circular_uniform",
        n_params=0,
        estimator="mle",
        params={},
        loglik=loglik,
        aic=_aic(loglik, 0),
        kuiper=kuiper,
        converged=np.ones(ncell, dtype=bool),
        n_iter=np.zeros(ncell, dtype=np.int16),
    )


def fit_all_direction(theta: NDArray[np.float64]) -> list[DirFit]:
    """Fit all three circular families to ``(ncell, n)`` angles in radians."""
    if theta.ndim != 2:
        raise ValueError(f"expected (ncell, n), got {theta.shape}")
    theta = np.ascontiguousarray(wrap_pi(np.asarray(theta, dtype=np.float64)))
    m = circular_moments(theta)
    theta_sorted = np.sort(theta, axis=1)
    return [
        fit_von_mises(theta_sorted, m),
        fit_wrapped_normal(theta_sorted, m),
        fit_circular_uniform(theta_sorted, m),
    ]
