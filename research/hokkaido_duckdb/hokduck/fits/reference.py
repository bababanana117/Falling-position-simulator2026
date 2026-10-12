"""Reference implementations, used only by the tests.

The vectorised estimators in this package exist for speed. These are the slow,
obvious versions that scipy or a textbook would give, and the test suite
checks the fast ones against them. Nothing in the build imports this module.

Two of them -- the wrapped normal brute force and the von Mises CDF series --
have no library equivalent at all, so they are written out in full here and
serve as the independent check on the branching implementations in
``circular.py``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy import integrate, special, stats

__all__ = [
    "brute_wrapped_normal_cdf",
    "brute_wrapped_normal_logpdf",
    "scipy_direction_fit",
    "scipy_speed_fits",
    "von_mises_cdf_series",
]


def scipy_speed_fits(x: NDArray[np.float64]) -> dict[str, dict[str, float]]:
    """Fit one sample with scipy's own ``.fit()`` for each speed family."""
    mu, sigma = stats.norm.fit(x)
    c, loc, scale = stats.weibull_min.fit(x, floc=0.0)
    a, width = stats.uniform.fit(x)
    return {
        "normal": {
            "mu_ms": mu,
            "sigma_ms": sigma,
            "loglik": float(stats.norm.logpdf(x, mu, sigma).sum()),
        },
        "weibull_min_loc0": {
            "weibull_shape": c,
            "weibull_scale_ms": scale,
            "loglik": float(stats.weibull_min.logpdf(x, c, loc, scale).sum()),
        },
        "uniform": {
            "uniform_a_ms": a,
            "uniform_b_ms": a + width,
            "loglik": float(stats.uniform.logpdf(x, a, width).sum()),
        },
    }


def scipy_direction_fit(theta: NDArray[np.float64]) -> dict[str, float]:
    """von Mises by scipy, with the scale pinned so only mu and kappa move."""
    kappa, loc, _scale = stats.vonmises.fit(theta, fscale=1)
    return {
        "kappa": kappa,
        "mu_rad": loc,
        "loglik": float(stats.vonmises.logpdf(theta, kappa, loc=loc).sum()),
    }


def brute_wrapped_normal_logpdf(
    delta: NDArray[np.float64], sigma: float, terms: int = 400
) -> NDArray[np.float64]:
    r"""The wrapped normal density by summing many spatial terms.

    Slow and unconditionally correct: no branch, no Fourier form, just
    :math:`\sum_{j=-400}^{400}` of the unwrapped Gaussian. This is what the
    two branches in ``circular.wrapped_normal_logpdf`` are checked against.
    """
    j = np.arange(-terms, terms + 1, dtype=np.float64)
    z = (np.asarray(delta)[..., None] + 2.0 * np.pi * j) / sigma
    return special.logsumexp(-0.5 * z * z, axis=-1) - np.log(sigma) - 0.5 * np.log(2 * np.pi)


def brute_wrapped_normal_cdf(delta: float, sigma: float, terms: int = 400) -> float:
    """The wrapped normal CDF by integrating the brute-force density."""
    f = lambda t: np.exp(brute_wrapped_normal_logpdf(np.array([t]), sigma, terms)[0])  # noqa: E731
    val, _err = integrate.quad(f, -np.pi, delta, limit=200)
    return float(val)


def von_mises_cdf_series(delta: NDArray[np.float64], kappa: float, terms: int = 80) -> NDArray:
    r"""Exact Bessel series for the von Mises CDF.

    .. math::
        F(\Delta) = \frac12 + \frac{\Delta}{2\pi}
                    + \frac1{\pi}\sum_{p\ge1}\frac{I_p(\kappa)}{I_0(\kappa)}
                      \frac{\sin p\Delta}{p}

    ``circular.py`` calls ``scipy.stats.vonmises.cdf`` instead, because it is a
    library routine; this series is the independent check on it and the
    documented fallback should scipy's behaviour ever change. Uses ``ive`` so
    the ratio is computed without overflow.
    """
    p = np.arange(1, terms + 1, dtype=np.float64)
    ratio = special.ive(p, kappa) / special.ive(0, kappa)
    s = (ratio * np.sin(np.asarray(delta)[..., None] * p) / p).sum(axis=-1)
    return 0.5 + np.asarray(delta) / (2.0 * np.pi) + s / np.pi
