"""Geopotential/geometric conversion and the ISA fallback."""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import altitude as alt

LEVELS_HPA = np.array(
    [3, 5, 7, 10, 20, 30, 40, 50, 60, 70, 85, 100, 125, 150, 175, 200, 225, 250,
     300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800, 825, 850, 875,
     900, 925, 950, 975, 1000],
    dtype=float,
)


# --- gravity and radius ------------------------------------------------------


def test_gravity_increases_towards_the_pole() -> None:
    g = alt.gravity_at_latitude([0.0, 45.0, 90.0])
    assert g[0] < g[1] < g[2]
    assert g[0] == pytest.approx(9.7803, abs=1e-3)
    assert g[2] == pytest.approx(9.8322, abs=1e-3)


def test_gravity_at_45_north_is_close_to_standard() -> None:
    assert float(alt.gravity_at_latitude(45.0)) == pytest.approx(alt.G0, abs=0.01)


def test_effective_radius_grows_towards_the_pole() -> None:
    r = alt.earth_radius_effective([0.0, 45.0, 90.0])
    # List (1968) is an *effective* radius for the gravity variation, not the
    # geometric one, so it runs the opposite way to the Earth's actual shape.
    assert r[0] < r[1] < r[2]
    assert 6.33e6 < r[0] < 6.34e6
    assert 6.37e6 < r[2] < 6.38e6


# --- geopotential <-> geometric ---------------------------------------------


def test_zero_maps_to_zero() -> None:
    assert float(alt.geopotential_to_geometric(0.0, 45.0)) == pytest.approx(0.0)


def test_conversion_is_monotone_in_height() -> None:
    z = np.array([0.0, 5e3, 1e4, 2e4, 3e4, 4e4])
    out = alt.geopotential_to_geometric(z, 45.0)
    assert np.all(np.diff(out) > 0)


def test_geometric_exceeds_geopotential_and_the_gap_grows() -> None:
    """Gravity weakens with height, so a geopotential metre is shorter than a
    real metre and the geometric altitude runs ahead."""
    z = np.array([1e4, 2e4, 3e4, 4e4])
    d = alt.geopotential_to_geometric(z, 45.0) - z
    assert np.all(d > 0)
    assert np.all(np.diff(d) > 0)


def test_correction_magnitude_at_30km_45north() -> None:
    d = float(alt.geopotential_to_geometric(30000.0, 45.0)) - 30000.0
    assert 100.0 < d < 200.0


def test_correction_is_larger_at_the_equator_than_at_the_pole() -> None:
    """Weaker gravity and a larger radius at the equator both push the same way."""
    d_eq = float(alt.geopotential_to_geometric(30000.0, 0.0)) - 30000.0
    d_pole = float(alt.geopotential_to_geometric(30000.0, 90.0)) - 30000.0
    assert d_eq > d_pole
    assert 100.0 < d_eq - d_pole < 250.0


def test_round_trip() -> None:
    z = np.array([0.0, 1e3, 1e4, 3e4, 4e4])
    for lat in (0.0, 33.0, 43.0, 60.0):
        back = alt.geometric_to_geopotential(alt.geopotential_to_geometric(z, lat), lat)
        assert np.allclose(back, z, atol=1e-6)


# --- ISA fallback ------------------------------------------------------------


def test_isa_round_trip_against_pressure_isa() -> None:
    h = np.array([0.0, 5e3, 11e3, 15e3, 20e3, 25e3, 32e3, 40e3])
    p_hpa = alt.pressure_isa(h) / 100.0
    assert np.allclose(alt.isa_altitude_from_pressure(p_hpa), h, atol=1e-3)


def test_isa_sea_level() -> None:
    assert float(alt.isa_altitude_from_pressure(1013.25)) == pytest.approx(0.0, abs=1e-3)


def test_isa_is_monotone_decreasing_in_pressure() -> None:
    h = alt.isa_altitude_from_pressure(LEVELS_HPA)
    assert np.all(np.diff(h) < 0)  # LEVELS_HPA ascends, so altitude descends


def test_isa_covers_the_levels_we_use() -> None:
    """1000 hPa is near the ground and 3 hPa is about 40 km."""
    h = alt.isa_altitude_from_pressure(LEVELS_HPA)
    assert h[-1] == pytest.approx(110.0, abs=10.0)   # 1000 hPa
    assert 38e3 < h[0] < 42e3                        # 3 hPa


def test_isa_matches_the_backend_bisection_implementation() -> None:
    """Same answer as backend/bfps/core/atmosphere.py:82, which bisects."""

    def backend_style(p_hpa: float) -> float:
        p_pa = p_hpa * 100.0
        lo, hi = 0.0, 50000.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if float(alt.pressure_isa(mid)) > p_pa:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    for p in (1000.0, 500.0, 200.0, 50.0, 10.0, 3.0):
        assert float(alt.isa_altitude_from_pressure(p)) == pytest.approx(
            backend_style(p), abs=1e-3
        )
