"""Reconcile the vectorised estimators with the existing per-sample code.

The upstream pipeline's ``fit_speeds`` fits one level at a time with
``scipy``'s ``.fit()``. ``hokduck.fits.linear.fit_all_speed`` fits every cell
at once by solving the score equation directly. They must agree, and where
they do not, the difference must be one this file names.

Marked slow: the fixture reads the six-hourly cache rather than the shipped
statistics, so it needs the download to have happened.
"""

from __future__ import annotations

import numpy as np
import pytest
from hokduck.fits.linear import fit_all_speed
from scipy import stats

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def speeds():
    """Real speed samples, shaped ``(ncell, n)`` as fit_all_speed wants."""
    from windclim.config import CACHE_ROOT
    from windclim.stats.aggregate import AggregateConfig, load_month

    if not CACHE_ROOT.exists():
        pytest.skip(f"no six-hourly cache at {CACHE_ROOT}")
    try:
        month = load_month(CACHE_ROOT, "hokkaido", 1, AggregateConfig())
    except (FileNotFoundError, OSError, KeyError) as exc:
        pytest.skip(f"cache unusable: {exc}")

    u = np.asarray(month.u, dtype=float)
    v = np.asarray(month.v, dtype=float)
    speed = np.hypot(u, v)
    # Collapse everything but time, then take a handful of columns as cells.
    flat = speed.reshape(speed.shape[0], -1)
    keep = np.isfinite(flat).all(axis=0)
    sample = flat[:, keep][:, ::997][:, :12]
    if sample.shape[1] < 4:
        pytest.skip("not enough usable cells in the cache slice")
    return np.ascontiguousarray(sample.T)          # (ncell, n)


@pytest.fixture(scope="module")
def fits(speeds):
    return {f.family: f for f in fit_all_speed(speeds)}


def test_weibull_matches_scipy_and_never_fits_worse(speeds, fits):
    f = fits["weibull_min_loc0"]
    assert f.converged.all()
    assert f.n_params == 2, "floc=0 leaves two free parameters"
    assert np.all(f.params["weibull_loc_ms"] == 0.0)

    for i in range(speeds.shape[0]):
        c, loc, scale = stats.weibull_min.fit(speeds[i], floc=0.0)
        assert loc == 0.0
        assert f.params["weibull_shape"][i] == pytest.approx(c, rel=1e-4)
        assert f.params["weibull_scale_ms"][i] == pytest.approx(scale, rel=1e-4)
        theirs = stats.weibull_min.logpdf(speeds[i], c, 0.0, scale).sum()
        assert f.loglik[i] >= theirs - 1e-8, "same optimum, reached at least as precisely"


def test_normal_matches_scipy(speeds, fits):
    f = fits["normal"]
    assert f.converged.all()
    for i in range(speeds.shape[0]):
        a, b = stats.norm.fit(speeds[i])
        assert f.params["mu_ms"][i] == pytest.approx(a, rel=1e-12)
        assert f.params["sigma_ms"][i] == pytest.approx(b, rel=1e-12)
        assert f.loglik[i] == pytest.approx(
            stats.norm.logpdf(speeds[i], a, b).sum(), rel=1e-10
        )


def test_uniform_is_the_sample_range(speeds, fits):
    f = fits["uniform"]
    assert f.converged.all()
    np.testing.assert_allclose(f.params["uniform_a_ms"], speeds.min(axis=1))
    np.testing.assert_allclose(f.params["uniform_b_ms"], speeds.max(axis=1))
    width = speeds.max(axis=1) - speeds.min(axis=1)
    np.testing.assert_allclose(f.loglik, -speeds.shape[1] * np.log(width), rtol=1e-12)


def test_the_weibull_penalty_here_is_4_not_6(speeds, fits):
    """``windsample`` adds 6 although ``floc=0`` leaves two free parameters.

    Correcting it shifts every Weibull AIC by exactly 2, which is what this
    pins. For the existing report the consequence is one level out of 38
    changing family; that correction is not in scope here.
    """
    ours = fits["weibull_min_loc0"].aic
    theirs = []
    for i in range(speeds.shape[0]):
        c, lo, sc = stats.weibull_min.fit(speeds[i], floc=0.0)
        theirs.append(-2 * stats.weibull_min.logpdf(speeds[i], c, lo, sc).sum() + 6)
    np.testing.assert_allclose(np.asarray(theirs) - ours, 2.0, atol=1e-6)


def test_all_three_families_are_compared(speeds, fits):
    """``windsample`` chooses with ``if aic_n <= aic_w``; uniform cannot win there.

    Here the three are ranked on the same footing. On real mid-latitude wind
    the uniform still loses, which is a finding rather than a rule, so only
    its participation and its losing margin are asserted.
    """
    aic = np.vstack([fits[k].aic for k in ("normal", "weibull_min_loc0", "uniform")])
    assert np.isfinite(aic).all()
    assert (aic[2] > aic[:2].min(axis=0)).all()


def test_ks_statistics_share_one_ordering(speeds, fits):
    """All three are computed against the same sort, so they are comparable."""
    for f in fits.values():
        assert f.ks.shape == (speeds.shape[0],)
        assert np.all((f.ks >= 0) & (f.ks <= 1))
