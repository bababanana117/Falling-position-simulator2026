"""The flight model that turns a wind profile into a landing displacement."""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats.drift import (
    FlightProfile,
    descent_rate_ms,
    displacements,
    flight_seconds,
    layer_seconds,
    travel_bearing_deg,
)

# 38 levels spread over the flight column, ascending in altitude as the module wants.
ALT = np.linspace(100.0, 40000.0, 38)[:, None, None]
FLIGHT = FlightProfile()


# --- descent law -------------------------------------------------------------


def test_descent_is_fastest_where_the_air_is_thinnest() -> None:
    v = descent_rate_ms(np.array([0.0, 10000.0, 20000.0, 30000.0]), 6.0)
    assert np.all(np.diff(v) > 0)


def test_descent_at_sea_level_is_the_quoted_rate() -> None:
    assert float(descent_rate_ms(0.0, 6.0)) == pytest.approx(6.0, rel=0.01)


def test_descent_at_30km_is_several_times_faster() -> None:
    """Why the descent leg contributes far less drift than its altitude range."""
    ratio = float(descent_rate_ms(30000.0, 6.0)) / 6.0
    assert 5.0 < ratio < 15.0


def test_descent_matches_the_backend_formula() -> None:
    from windclim.stats.drift import RHO0_ISA, _density_isa

    for z in (0.0, 5000.0, 20000.0, 30000.0):
        expected = 6.0 * np.sqrt(RHO0_ISA / float(_density_isa(np.array([z]))[0]))
        assert float(descent_rate_ms(z, 6.0)) == pytest.approx(expected, rel=1e-9)


# --- layer weights -----------------------------------------------------------


def test_layer_weights_have_the_level_shape() -> None:
    assert layer_seconds(ALT, FLIGHT).shape == ALT.shape


def test_levels_above_burst_contribute_nothing() -> None:
    w = layer_seconds(ALT, FLIGHT)
    above = ALT[:, 0, 0] > FLIGHT.burst_altitude_m + 600.0
    assert np.allclose(w[above], 0.0)


def test_total_flight_time_is_a_plausible_sounding() -> None:
    """30 km at 5 m/s is 100 minutes up; the fall is quicker. About 2-2.5 hours."""
    minutes = float(flight_seconds(ALT, FLIGHT).squeeze()) / 60.0
    assert 110.0 < minutes < 170.0


def test_ascent_time_alone_matches_the_arithmetic() -> None:
    no_descent = FlightProfile(descent_rate_ms=1e9)
    minutes = float(flight_seconds(ALT, no_descent).squeeze()) / 60.0
    expected = (FLIGHT.burst_altitude_m - FLIGHT.launch_altitude_m) / 5.0 / 60.0
    assert minutes == pytest.approx(expected, rel=0.02)


def test_a_slower_ascent_means_a_longer_flight() -> None:
    slow = FlightProfile(ascent_rate_ms=3.0)
    assert float(flight_seconds(ALT, slow).squeeze()) > float(
        flight_seconds(ALT, FLIGHT).squeeze()
    )


def test_a_lower_burst_altitude_means_a_shorter_flight() -> None:
    low = FlightProfile(burst_altitude_m=20000.0)
    assert float(flight_seconds(ALT, low).squeeze()) < float(
        flight_seconds(ALT, FLIGHT).squeeze()
    )


def test_one_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="two levels"):
        layer_seconds(ALT[:1], FLIGHT)


# --- displacement ------------------------------------------------------------


def test_a_uniform_wind_drifts_by_speed_times_flight_time() -> None:
    u = np.full((4, 38, 1, 1), 10.0)
    v = np.zeros_like(u)
    dx, dy = displacements(u, v, ALT, FLIGHT)
    expected_km = 10.0 * float(flight_seconds(ALT, FLIGHT).squeeze()) / 1000.0
    assert float(dx[0, 0, 0]) / 1000.0 == pytest.approx(expected_km, rel=1e-9)
    assert np.allclose(dy, 0.0)


def test_displacement_is_linear_in_the_wind() -> None:
    """The property the whole approach rests on: it lets the landing spread be
    measured per analysis instead of guessed from level correlations."""
    rng = np.random.default_rng(0)
    u1 = rng.normal(0, 20, (1, 38, 1, 1))
    u2 = rng.normal(0, 20, (1, 38, 1, 1))
    z = np.zeros_like(u1)
    d1 = displacements(u1, z, ALT, FLIGHT)[0]
    d2 = displacements(u2, z, ALT, FLIGHT)[0]
    both = displacements(u1 + u2, z, ALT, FLIGHT)[0]
    assert np.allclose(both, d1 + d2)


def test_the_mean_drift_equals_the_drift_of_the_mean_wind() -> None:
    rng = np.random.default_rng(1)
    u = rng.normal(15, 20, (200, 38, 2, 2))
    v = rng.normal(0, 10, (200, 38, 2, 2))
    dx, _ = displacements(u, v, np.broadcast_to(ALT, (38, 2, 2)), FLIGHT)
    mean_of_drifts = dx.mean(axis=0)
    drift_of_mean = displacements(
        u.mean(axis=0, keepdims=True), v.mean(axis=0, keepdims=True),
        np.broadcast_to(ALT, (38, 2, 2)), FLIGHT,
    )[0][0]
    assert np.allclose(mean_of_drifts, drift_of_mean, rtol=1e-9)


def test_wind_above_burst_does_not_move_the_payload() -> None:
    """A balloon that bursts at 30 km cannot be pushed by the wind at 38 km."""
    u = np.zeros((1, 38, 1, 1))
    u[:, ALT[:, 0, 0] > 33000.0] = 100.0
    dx, _ = displacements(u, np.zeros_like(u), ALT, FLIGHT)
    assert abs(float(dx[0, 0, 0])) < 1.0


def test_a_column_with_no_wind_data_gives_nan() -> None:
    u = np.full((1, 38, 1, 1), np.nan)
    dx, dy = displacements(u, u, ALT, FLIGHT)
    assert np.isnan(dx).all() and np.isnan(dy).all()


def test_jet_dominates_the_drift() -> None:
    """A 70 m/s jet in a 2 km layer moves the payload further than a 10 m/s wind
    through the whole stratosphere, because the ascent is slow and steady."""
    alt = ALT[:, 0, 0]
    jet = np.zeros((1, 38, 1, 1))
    jet[:, (alt > 11000) & (alt < 13000)] = 70.0
    strato = np.zeros((1, 38, 1, 1))
    strato[:, (alt > 20000) & (alt < 30000)] = 10.0
    d_jet = abs(float(displacements(jet, np.zeros_like(jet), ALT, FLIGHT)[0][0, 0, 0]))
    d_str = abs(float(displacements(strato, np.zeros_like(strato), ALT, FLIGHT)[0][0, 0, 0]))
    assert d_jet > 0 and d_str > 0
    assert d_jet / d_str > 0.5          # comparable despite a fifth the depth


# --- bearing conventions -----------------------------------------------------


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [(1.0, 0.0, 90.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 270.0), (0.0, -1.0, 180.0)],
)
def test_travel_bearing_is_the_direction_of_travel(dx, dy, expected) -> None:
    assert float(travel_bearing_deg(dx, dy)) == pytest.approx(expected)


def test_travel_bearing_is_opposite_to_the_meteorological_wind_direction() -> None:
    """A westerly (270 deg, from the west) carries the payload towards 90 deg.
    Confusing the two would put every landing site on the wrong side."""
    from windclim.stats.circular import uv_to_met_direction

    u, v = 10.0, 0.0
    assert float(uv_to_met_direction(u, v)) == pytest.approx(270.0)
    assert float(travel_bearing_deg(u, v)) == pytest.approx(90.0)
    assert abs(float(uv_to_met_direction(u, v)) - float(travel_bearing_deg(u, v))) == 180.0
