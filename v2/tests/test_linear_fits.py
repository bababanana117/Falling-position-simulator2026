"""The speed estimators, checked against scipy's own ``.fit()``.

scipy is the oracle throughout. The vectorised versions exist only because
fitting 260,000 cells one at a time takes 24 minutes for the Weibull alone;
they have to give the same answer, and these tests are what says they do.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from jpduck.fits.linear import (
    fit_all_speed,
    fit_normal,
    fit_uniform,
    fit_weibull_loc0,
    weibull_score,
)
from jpduck.fits.reference import scipy_speed_fits


@pytest.fixture(scope="module")
def weibull_block():
    """200 cells spanning the shapes and scales the real data produces."""
    rng = np.random.default_rng(20260922)
    shapes = rng.uniform(0.5, 15.0, 200)
    scales = rng.uniform(0.5, 100.0, 200)
    x = np.array([
        stats.weibull_min.rvs(k, scale=lam, size=600, random_state=int(1000 + i))
        for i, (k, lam) in enumerate(zip(shapes, scales, strict=True))
    ])
    return x, shapes, scales


def test_normal_matches_scipy():
    rng = np.random.default_rng(1)
    x = rng.normal(30.0, 8.0, size=(200, 600))
    fit = fit_normal(x, np.sort(x, axis=1))
    for i in (0, 77, 199):
        ref = scipy_speed_fits(x[i])["normal"]
        assert fit.params["mu_ms"][i] == pytest.approx(ref["mu_ms"], rel=1e-12)
        assert fit.params["sigma_ms"][i] == pytest.approx(ref["sigma_ms"], rel=1e-12)
        assert fit.loglik[i] == pytest.approx(ref["loglik"], rel=1e-12)


def test_uniform_matches_scipy():
    rng = np.random.default_rng(2)
    x = rng.uniform(3.0, 40.0, size=(100, 600))
    fit = fit_uniform(x, np.sort(x, axis=1))
    for i in (0, 50, 99):
        ref = scipy_speed_fits(x[i])["uniform"]
        assert fit.params["uniform_a_ms"][i] == ref["uniform_a_ms"]
        assert fit.params["uniform_b_ms"][i] == pytest.approx(ref["uniform_b_ms"], rel=1e-15)
        assert fit.loglik[i] == pytest.approx(ref["loglik"], rel=1e-12)


def test_weibull_matches_scipy(weibull_block):
    """Parameters to 1e-4 relative, and the likelihood at least as good.

    The likelihood assertion is the stronger of the two: a shape that differs
    in the seventh digit does not matter, but landing on a worse optimum would.
    """
    x, _, _ = weibull_block
    fit = fit_weibull_loc0(x, np.sort(x, axis=1))
    assert fit.converged.all()
    for i in range(0, 200, 17):
        ref = scipy_speed_fits(x[i])["weibull_min_loc0"]
        assert fit.params["weibull_shape"][i] == pytest.approx(ref["weibull_shape"], rel=1e-4)
        assert fit.params["weibull_scale_ms"][i] == pytest.approx(
            ref["weibull_scale_ms"], rel=1e-4
        )
        assert fit.loglik[i] >= ref["loglik"] - 1e-9


def test_weibull_recovers_truth(weibull_block):
    x, shapes, scales = weibull_block
    fit = fit_weibull_loc0(x, np.sort(x, axis=1))
    assert np.allclose(fit.params["weibull_shape"], shapes, rtol=0.15)
    assert np.allclose(fit.params["weibull_scale_ms"], scales, rtol=0.15)


def test_weibull_score_root(weibull_block):
    """The returned shape really is a root of the score, not just close."""
    x, _, _ = weibull_block
    fit = fit_weibull_loc0(x, np.sort(x, axis=1))
    k = fit.params["weibull_shape"]
    m = x.max(axis=1, keepdims=True)
    ly = np.log(x / m)
    assert np.abs(weibull_score(k, ly, ly.mean(axis=1))).max() < 1e-10


def test_weibull_overflow_guard():
    """Large speeds with a large shape must not overflow.

    Without the max-normalisation in ``fit_weibull_loc0`` this raises a
    RuntimeWarning and returns NaN: 1e4**15 is 1e60 per element before the sum.
    """
    x = stats.weibull_min.rvs(15.0, scale=8000.0, size=(10, 600), random_state=7)
    with np.errstate(over="raise"):
        fit = fit_weibull_loc0(x, np.sort(x, axis=1))
    assert fit.converged.all()
    assert np.isfinite(fit.loglik).all()


def test_degenerate_cells_do_not_converge():
    """A constant sample has no distribution to estimate."""
    x = np.full((3, 600), 12.0)
    x[1] += np.linspace(0, 1e-12, 600)          # numerically constant too
    fits = fit_all_speed(x)
    for f in fits:
        assert not f.converged.any(), f.family
        assert np.isnan(f.loglik).all()
        assert np.isnan(f.aic).all()


def test_uniform_wins_on_uniform_data():
    """The regression test for the straw-man bug.

    The upstream pipeline computes the uniform AIC but never lets it
    win -- the choice is ``if aic_n <= aic_w``, two families only. Here all
    three are real candidates, so genuinely uniform data must select uniform.
    """
    rng = np.random.default_rng(3)
    x = rng.uniform(5.0, 25.0, size=(50, 2000))
    fits = fit_all_speed(x)
    by_family = {f.family: f for f in fits}
    assert (by_family["uniform"].aic < by_family["normal"].aic).all()
    assert (by_family["uniform"].aic < by_family["weibull_min_loc0"].aic).all()


def test_weibull_penalty_is_four_not_six(weibull_block):
    """The second bug: ``floc=0`` leaves two free parameters, not three.

    ``windsample.py:148`` adds 6 to the Weibull AIC. Fixing it to 4 shifts
    every Weibull AIC down by exactly 2, which is what this pins.
    """
    x, _, _ = weibull_block
    fit = fit_weibull_loc0(x[:20], np.sort(x[:20], axis=1))
    assert fit.n_params == 2
    assert np.allclose(fit.params["weibull_loc_ms"], 0.0)
    windclim_style = -2.0 * fit.loglik + 6.0
    assert np.allclose(windclim_style - fit.aic, 2.0)


def test_ks_matches_windsample(weibull_block):
    """Our KS is byte-for-byte the one the report used."""
    from windclim.stats.windsample import _ks

    x, _, _ = weibull_block
    fit = fit_weibull_loc0(x, np.sort(x, axis=1))
    for i in (0, 42, 150):
        params = (fit.params["weibull_shape"][i], 0.0, fit.params["weibull_scale_ms"][i])
        assert fit.ks[i] == pytest.approx(_ks(x[i], stats.weibull_min, params), rel=1e-12)


def test_prob_negative_reported():
    """The normal puts mass below zero; the column says how much."""
    rng = np.random.default_rng(4)
    x = np.abs(rng.normal(3.0, 3.0, size=(5, 600)))
    fit = fit_normal(x, np.sort(x, axis=1))
    p = fit.extra["prob_negative"]
    assert (p > 0).all() and (p < 0.5).all()
