import numpy as np
import pytest

from bfps.climatology.model import (
    STANDARD_FLIGHT,
    FlightSettings,
    LevelStats,
    drift_covariance,
    layer_seconds,
    mean_drift,
    offset_to_latlon,
    sample_offsets,
    solve_rho,
)

ALT = np.array([100.0, 1500.0, 5000.0, 10000.0, 16000.0, 24000.0, 31000.0, 40000.0])


def levels(u=10.0, v=0.0, su=3.0, sv=2.0, c=0.0):
    n = ALT.size
    return LevelStats(
        alt_m=ALT,
        u_mean=np.full(n, u),
        v_mean=np.full(n, v),
        u_var=np.full(n, su**2),
        v_var=np.full(n, sv**2),
        uv_cov=np.full(n, c),
    )


def test_layer_seconds_ascent_only_matches_rise_time():
    # 降下を非常に速くすると、滞在時間の合計は上昇時間 (破裂高度 - 打ち上げ高度) / 上昇速度 に近づく
    f = FlightSettings(ascent_rate=5.0, burst_altitude=30000.0, descent_rate=1e6)
    T = layer_seconds(ALT, f)
    assert T.shape == ALT.shape
    assert T.sum() == pytest.approx(30000.0 / 5.0, rel=1e-3)
    assert T[-1] == 0.0  # 40 km の層は破裂高度より上


def test_layer_seconds_respects_launch_altitude():
    f = FlightSettings(ascent_rate=5.0, burst_altitude=30000.0, descent_rate=1e6,
                       launch_altitude=2000.0)
    T = layer_seconds(ALT, f)
    assert T.sum() == pytest.approx((30000.0 - 2000.0) / 5.0, rel=1e-3)


def test_mean_drift_constant_wind():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    e, n = mean_drift(levels(u=10.0, v=-2.0), T)
    assert e == pytest.approx(10.0 * T.sum())
    assert n == pytest.approx(-2.0 * T.sum())


def test_covariance_limits():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels(su=3.0, sv=2.0)
    indep = drift_covariance(lv, T, 0.0)
    full = drift_covariance(lv, T, 1.0)
    assert indep[0, 0] == pytest.approx((T**2).sum() * 9.0)
    assert full[0, 0] == pytest.approx((T.sum() * 3.0) ** 2)
    assert full[1, 1] == pytest.approx((T.sum() * 2.0) ** 2)
    assert indep[0, 1] == pytest.approx(0.0, abs=1e-6)


def test_solve_rho_recovers_known_value():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels(su=4.0, sv=3.0, c=1.5)
    cov = drift_covariance(lv, T, 0.42)
    assert solve_rho(lv, T, cov[0, 0], cov[1, 1]) == pytest.approx(0.42, abs=1e-9)


def test_solve_rho_is_clipped():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels()
    assert solve_rho(lv, T, 0.0, 0.0) == 0.0
    assert solve_rho(lv, T, 1e20, 1e20) == 1.0


def test_sample_offsets_moments():
    cov = np.array([[4.0e8, 1.0e8], [1.0e8, 2.0e8]])
    s = sample_offsets((1.0e5, -2.0e4), cov, 20000, seed=1)
    assert s.shape == (20000, 2)
    assert s.mean(axis=0) == pytest.approx([1.0e5, -2.0e4], rel=0.02, abs=500)
    assert np.cov(s.T) == pytest.approx(cov, rel=0.05)


def test_offset_to_latlon_one_degree_north():
    lat, lon = offset_to_latlon(33.0, 130.0, np.array([0.0]), np.array([111195.0]))
    assert lat[0] == pytest.approx(34.0, abs=1e-3)
    assert lon[0] == pytest.approx(130.0, abs=1e-9)
