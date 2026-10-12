"""Wind moments, ellipses, percentiles and the effective sample size."""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import vector as vec
from windclim.stats.circular import uv_to_met_direction

# --- the two means -----------------------------------------------------------


def test_steady_westerly() -> None:
    u = np.full(280, 10.0)
    v = np.zeros(280)
    m = vec.moments(u, v)
    svm = vec.vector_mean_speed(m.u_mean, m.v_mean)
    sm = vec.scalar_mean_speed(u, v)
    assert float(svm) == pytest.approx(10.0)
    assert float(sm) == pytest.approx(10.0)
    assert float(vec.constancy(svm, sm)) == pytest.approx(1.0)
    assert float(uv_to_met_direction(m.u_mean, m.v_mean)) == pytest.approx(270.0)


def test_wind_that_reverses_half_the_time() -> None:
    """The case that makes a bin's mean direction meaningless."""
    u = np.array([10.0, -10.0] * 140)
    v = np.zeros(280)
    m = vec.moments(u, v)
    svm = vec.vector_mean_speed(m.u_mean, m.v_mean)
    sm = vec.scalar_mean_speed(u, v)
    assert float(svm) == pytest.approx(0.0, abs=1e-12)
    assert float(sm) == pytest.approx(10.0)
    assert float(vec.constancy(svm, sm)) == pytest.approx(0.0, abs=1e-12)


def test_vector_mean_never_exceeds_scalar_mean() -> None:
    """A mathematical identity, so a violation means the aggregation is broken."""
    rng = np.random.default_rng(1)
    u = rng.normal(5.0, 12.0, size=(400, 13))
    v = rng.normal(-2.0, 9.0, size=(400, 13))
    m = vec.moments(u, v)
    svm = vec.vector_mean_speed(m.u_mean, m.v_mean)
    sm = vec.scalar_mean_speed(u, v)
    assert np.all(svm <= sm + 1e-9)


def test_constancy_stays_within_zero_and_one() -> None:
    rng = np.random.default_rng(2)
    u = rng.normal(0.0, 8.0, size=(300, 5))
    v = rng.normal(0.0, 8.0, size=(300, 5))
    m = vec.moments(u, v)
    c = vec.constancy(vec.vector_mean_speed(m.u_mean, m.v_mean), vec.scalar_mean_speed(u, v))
    assert np.all((c >= 0.0) & (c <= 1.0))


def test_constancy_is_nan_for_a_dead_calm() -> None:
    assert np.isnan(vec.constancy(0.0, 0.0))


# --- moments -----------------------------------------------------------------


def test_moments_recover_a_known_covariance() -> None:
    rng = np.random.default_rng(3)
    cov = np.array([[9.0, 3.0], [3.0, 4.0]])
    xy = rng.multivariate_normal([5.0, -1.0], cov, size=200_000)
    m = vec.moments(xy[:, 0], xy[:, 1])
    assert float(m.u_mean) == pytest.approx(5.0, abs=0.05)
    assert float(m.v_mean) == pytest.approx(-1.0, abs=0.05)
    assert float(m.u_var) == pytest.approx(9.0, rel=0.02)
    assert float(m.v_var) == pytest.approx(4.0, rel=0.02)
    assert float(m.uv_cov) == pytest.approx(3.0, rel=0.03)


def test_moments_count_only_finite_samples() -> None:
    u = np.array([1.0, 2.0, np.nan, 4.0])
    v = np.array([1.0, 2.0, 3.0, np.nan])
    m = vec.moments(u, v)
    assert int(m.n) == 2
    assert float(m.u_mean) == pytest.approx(1.5)


def test_moments_variance_is_nan_with_fewer_than_two_samples() -> None:
    m = vec.moments(np.array([np.nan, 5.0]), np.array([1.0, np.nan]))
    assert int(m.n) == 0
    assert np.isnan(m.u_var)


def test_moments_work_along_an_axis() -> None:
    u = np.zeros((280, 4, 6))
    v = np.ones((280, 4, 6))
    m = vec.moments(u, v, axis=0)
    assert m.u_mean.shape == (4, 6)
    assert np.all(m.n == 280)


# --- variance ellipse --------------------------------------------------------


def test_ellipse_of_an_axis_aligned_covariance() -> None:
    major, minor, angle = vec.variance_ellipse(4.0, 1.0, 0.0)
    assert float(major) == pytest.approx(2.0)
    assert float(minor) == pytest.approx(1.0)
    assert float(angle) == pytest.approx(0.0)


def test_ellipse_of_an_equal_variance_correlated_covariance() -> None:
    major, minor, angle = vec.variance_ellipse(1.0, 1.0, 0.5)
    assert float(angle) == pytest.approx(45.0)
    assert float(major) == pytest.approx(np.sqrt(1.5))
    assert float(minor) == pytest.approx(np.sqrt(0.5))


def test_ellipse_of_an_anticorrelated_covariance() -> None:
    _, _, angle = vec.variance_ellipse(1.0, 1.0, -0.5)
    assert float(angle) == pytest.approx(135.0)


def test_ellipse_matches_a_numpy_eigendecomposition() -> None:
    rng = np.random.default_rng(4)
    for _ in range(20):
        a, c = rng.uniform(0.5, 20.0, size=2)
        b = rng.uniform(-1, 1) * np.sqrt(a * c) * 0.9
        major, minor, _ = vec.variance_ellipse(a, c, b)
        lam = np.linalg.eigvalsh(np.array([[a, b], [b, c]]))
        assert float(major) == pytest.approx(np.sqrt(lam[1]))
        assert float(minor) == pytest.approx(np.sqrt(lam[0]))


def test_ellipse_angle_is_in_zero_to_one_eighty() -> None:
    rng = np.random.default_rng(5)
    a, c = rng.uniform(0.5, 9.0, size=(2, 50))
    b = rng.uniform(-2, 2, size=50)
    _, _, angle = vec.variance_ellipse(a, c, b)
    assert np.all((angle >= 0.0) & (angle < 180.0))


# --- percentiles and exceedance ---------------------------------------------


def test_speed_percentiles_on_a_known_ramp() -> None:
    u = np.arange(101, dtype=float)
    v = np.zeros(101)
    p = vec.speed_percentiles(u, v, qs=(10.0, 50.0, 90.0))
    assert p.shape == (3,)
    assert float(p[1]) == pytest.approx(50.0)
    assert float(p[0]) == pytest.approx(10.0)
    assert float(p[2]) == pytest.approx(90.0)


def test_speed_percentiles_keep_the_trailing_shape() -> None:
    u = np.zeros((280, 3, 5))
    v = np.ones((280, 3, 5))
    p = vec.speed_percentiles(u, v)
    assert p.shape == (len(vec.DEFAULT_PERCENTILES), 3, 5)


def test_exceedance_frequency() -> None:
    u = np.array([5.0, 15.0, 25.0, 35.0, 45.0])
    v = np.zeros(5)
    f = vec.exceedance_freq(u, v, thresholds=(10.0, 20.0, 30.0, 40.0))
    assert np.allclose(f, [0.8, 0.6, 0.4, 0.2])


def test_exceedance_frequency_is_a_fraction() -> None:
    rng = np.random.default_rng(6)
    u = rng.normal(0, 20, size=(200, 4))
    v = rng.normal(0, 20, size=(200, 4))
    f = vec.exceedance_freq(u, v)
    assert np.all((f >= 0.0) & (f <= 1.0))
    assert np.all(np.diff(f, axis=0) <= 1e-12)  # monotone in the threshold


# --- autocorrelation and effective sample size -------------------------------


def test_lag1_autocorr_of_white_noise_is_near_zero() -> None:
    rng = np.random.default_rng(7)
    assert abs(float(vec.lag1_autocorr(rng.normal(size=20_000)))) < 0.03


def test_lag1_autocorr_of_a_smooth_series_is_near_one() -> None:
    x = np.sin(np.linspace(0, 4 * np.pi, 2000))
    assert float(vec.lag1_autocorr(x)) > 0.99


def test_effective_sample_size_shrinks_with_correlation() -> None:
    assert float(vec.effective_sample_size(280, 0.0)) == pytest.approx(280.0)
    assert float(vec.effective_sample_size(280, 0.9)) == pytest.approx(280 * 0.1 / 1.9)
    assert float(vec.effective_sample_size(280, 0.9)) < 20.0


def test_effective_sample_size_is_clipped_to_the_raw_count() -> None:
    """Negative correlation must not manufacture more information than we have."""
    assert float(vec.effective_sample_size(280, -0.5)) == pytest.approx(280.0)
    assert float(vec.effective_sample_size(280, 0.999)) >= 1.0


def test_realistic_six_hourly_series_loses_most_of_its_samples() -> None:
    """An AR(1) with a ~2-day decorrelation time at 6-hourly sampling."""
    rng = np.random.default_rng(8)
    r = 0.85
    x = np.zeros(280)
    for i in range(1, 280):
        x[i] = r * x[i - 1] + rng.normal(0, 1)
    n_eff = float(vec.effective_sample_size(280, float(vec.lag1_autocorr(x))))
    assert 10.0 < n_eff < 60.0
