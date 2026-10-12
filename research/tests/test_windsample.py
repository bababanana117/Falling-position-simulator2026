"""The winter speed model: fitting, coupling and flying.

The module's whole value is that it reproduces an observed landing cloud, so
the tests check the pieces that make that possible: that a known distribution
is recovered, that the copula actually couples, and -- the point of the
appendix -- that independent levels give a tighter cloud than correlated ones.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from windclim.stats import windsample as ws
from windclim.stats.drift import FlightProfile

FLIGHT = FlightProfile()
LEVELS = np.array([10.0, 30.0, 100.0, 200.0, 500.0, 850.0, 1000.0])
ALT = np.array([200.0, 1500.0, 5500.0, 12000.0, 16000.0, 24000.0, 31000.0])


def gaussian_winds(n=4000, seed=0, sd=5.0, mean=30.0, corr=0.0):
    """Westerly wind with a controllable speed spread and level correlation."""
    rng = np.random.default_rng(seed)
    k = LEVELS.size
    if corr:
        c = np.full((k, k), corr)
        np.fill_diagonal(c, 1.0)
        z = rng.multivariate_normal(np.zeros(k), c, size=n)
    else:
        z = rng.standard_normal((n, k))
    speed = mean + sd * z
    return -np.maximum(speed, 0.1), np.zeros((n, k))     # u<0 is an easterly; keep it simple


# --- fitting ----------------------------------------------------------------


def test_a_gaussian_speed_is_fitted_as_gaussian() -> None:
    """The family choice has to survive the easy case before it is trusted."""
    u, v = gaussian_winds(mean=40.0, sd=5.0)
    model = ws.fit_speeds(u, v, LEVELS)
    assert all(f.family == "norm" for f in model.fits)
    for f in model.fits:
        assert f.mean == pytest.approx(40.0, abs=0.5)
        assert f.sd == pytest.approx(5.0, abs=0.4)
        assert f.ks < 0.03


def test_a_weibull_speed_is_fitted_as_weibull() -> None:
    rng = np.random.default_rng(3)
    speed = stats.weibull_min.rvs(1.8, scale=12.0, size=(4000, LEVELS.size),
                                  random_state=rng)
    model = ws.fit_speeds(-speed, np.zeros_like(speed), LEVELS)
    assert all(f.family == "weibull" for f in model.fits)


def test_a_uniform_alternative_is_always_recorded() -> None:
    """The report quotes how badly uniform loses, so the number must be kept."""
    u, v = gaussian_winds()
    model = ws.fit_speeds(u, v, LEVELS)
    assert all(f.aic_uniform > f.aic for f in model.fits)


def test_the_level_count_must_match_the_labels() -> None:
    u, v = gaussian_winds()
    with pytest.raises(ValueError, match="level columns"):
        ws.fit_speeds(u, v, LEVELS[:-1])


def test_the_direction_spread_is_measured_not_assumed() -> None:
    """A steady direction gives a small circular SD; a scattered one, a large."""
    rng = np.random.default_rng(5)
    n, k = 4000, LEVELS.size
    steady = np.radians(rng.normal(0.0, 5.0, (n, k)))
    model = ws.fit_speeds(30 * np.cos(steady), 30 * np.sin(steady), LEVELS)
    assert np.all(model.dir_sd_deg < 8.0)
    wild = rng.uniform(0, 2 * np.pi, (n, k))
    model2 = ws.fit_speeds(30 * np.cos(wild), 30 * np.sin(wild), LEVELS)
    assert np.all(model2.dir_sd_deg > 60.0)


# --- sampling ---------------------------------------------------------------


def test_sampling_reproduces_the_fitted_marginals() -> None:
    u, v = gaussian_winds(mean=40.0, sd=6.0)
    model = ws.fit_speeds(u, v, LEVELS)
    drawn = ws.sample_speeds(model, 8000, correlated=True, seed=1)
    assert drawn.mean(axis=0) == pytest.approx(np.full(LEVELS.size, 40.0), abs=0.6)
    assert drawn.std(axis=0) == pytest.approx(np.full(LEVELS.size, 6.0), abs=0.5)


def test_the_copula_reproduces_the_observed_correlation() -> None:
    """Coupling the levels is the whole reason the copula is there."""
    u, v = gaussian_winds(corr=0.7, seed=2)
    model = ws.fit_speeds(u, v, LEVELS)
    drawn = ws.sample_speeds(model, 8000, correlated=True, seed=1)
    off = np.corrcoef(drawn.T)[np.triu_indices(LEVELS.size, 1)]
    assert off.mean() == pytest.approx(0.7, abs=0.06)


def test_independent_sampling_really_is_independent() -> None:
    u, v = gaussian_winds(corr=0.7, seed=2)
    model = ws.fit_speeds(u, v, LEVELS)
    drawn = ws.sample_speeds(model, 8000, correlated=False, seed=1)
    off = np.corrcoef(drawn.T)[np.triu_indices(LEVELS.size, 1)]
    assert abs(off.mean()) < 0.05


def test_independent_levels_give_a_tighter_cloud_than_correlated_ones() -> None:
    """The appendix's first finding, as a test.

    Independent draws partly cancel when the flight sums them, so the landing
    cloud shrinks. Anyone who samples the levels on their own will get a
    confident-looking answer that is too confident.

    The size of the effect depends on how correlated the levels are and on how
    evenly the layer times weight them. For equal weights and correlation rho
    across k levels the ratio of spreads is sqrt(1 + (k-1) rho), which is 2.3
    here; the layer times are far from equal, so the measured ratio is about
    2.0. On the real winter profiles it is 3.3 (49.2 km against 15.0 km), so
    the threshold below is deliberately looser than what the data shows.
    """
    u, v = gaussian_winds(corr=0.7, seed=2)
    model = ws.fit_speeds(u, v, LEVELS)
    direction = model.mean_dir_deg
    ind = ws.simulate_landings(
        ws.sample_speeds(model, 4000, correlated=False, seed=1), direction, ALT, FLIGHT
    )
    cor = ws.simulate_landings(
        ws.sample_speeds(model, 4000, correlated=True, seed=1), direction, ALT, FLIGHT
    )
    spread_ind = np.std(np.hypot(*ind))
    spread_cor = np.std(np.hypot(*cor))
    assert spread_cor > 1.8 * spread_ind


def test_holding_the_direction_fixed_removes_the_crosswind_spread() -> None:
    """The appendix's second finding: a steady direction is not a fixed one."""
    rng = np.random.default_rng(7)
    n, k = 4000, LEVELS.size
    ang = np.radians(rng.normal(0.0, 12.0, (n, k)))      # 12 deg of wobble
    speed = 40.0 + 4.0 * rng.standard_normal((n, k))
    model = ws.fit_speeds(-speed * np.cos(ang), -speed * np.sin(ang), LEVELS)
    sp = ws.sample_speeds(model, n, correlated=True, seed=1)

    fixed_x, fixed_y = ws.simulate_landings(sp, model.mean_dir_deg, ALT, FLIGHT)
    varied = ws.sample_directions(model, n, correlated=True, seed=2)
    var_x, var_y = ws.simulate_landings(sp, varied, ALT, FLIGHT)

    cross_fixed = min(np.std(fixed_x), np.std(fixed_y))
    cross_varied = min(np.std(var_x), np.std(var_y))
    assert cross_varied > 5.0 * cross_fixed


# --- the balloon ------------------------------------------------------------


def test_flight_parameters_follow_the_web_app_defaults() -> None:
    a, b, c = ws.sample_flight_params(FLIGHT, ws.FlightSigma(), 20000, seed=0)
    assert a.std() == pytest.approx(0.5, abs=0.02)
    assert c.std() == pytest.approx(0.5, abs=0.02)
    assert b.std() == pytest.approx(FLIGHT.burst_altitude_m * 0.05, rel=0.05)
    # The app clips each draw; so does this.
    assert a.min() >= 0.1
    assert b.min() >= 1000.0
    assert c.min() >= 0.5


def test_the_weibull_burst_model_perturbs_only_the_burst() -> None:
    sigma = ws.FlightSigma(burst_model="weibull")
    a, b, c = ws.sample_flight_params(FLIGHT, sigma, 2000, seed=0)
    assert np.all(a == FLIGHT.ascent_rate_ms)
    assert np.all(c == FLIGHT.descent_rate_ms)
    assert b.std() > 1000.0


def test_an_unknown_burst_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="burst_model"):
        ws.sample_flight_params(FLIGHT, ws.FlightSigma(burst_model="lognormal"), 10)


def test_perturbing_the_flight_changes_the_landing() -> None:
    u, v = gaussian_winds(corr=0.5, seed=4)
    model = ws.fit_speeds(u, v, LEVELS)
    sp = ws.sample_speeds(model, 1500, correlated=True, seed=1)
    base = ws.simulate_landings(sp, model.mean_dir_deg, ALT, FLIGHT)
    a, b, c = ws.sample_flight_params(FLIGHT, ws.FlightSigma(), 1500, seed=2)
    pert = ws.simulate_landings(
        sp, model.mean_dir_deg, ALT, FLIGHT, ascent_ms=a, burst_m=b, descent_ms=c
    )
    assert np.std(np.hypot(*pert)) > np.std(np.hypot(*base))


def test_a_single_direction_profile_broadcasts_over_samples() -> None:
    """One shared direction and one per sample must both work."""
    u, v = gaussian_winds(seed=6)
    model = ws.fit_speeds(u, v, LEVELS)
    sp = ws.sample_speeds(model, 500, correlated=True, seed=1)
    one = ws.simulate_landings(sp, model.mean_dir_deg, ALT, FLIGHT)
    many = ws.simulate_landings(
        sp, np.tile(model.mean_dir_deg, (500, 1)), ALT, FLIGHT
    )
    assert np.allclose(one[0], many[0])
    assert np.allclose(one[1], many[1])
