"""Direction conventions and the traps that come with a circular variable."""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import circular as circ

# --- convention --------------------------------------------------------------


@pytest.mark.parametrize(
    ("u", "v", "expected"),
    [
        (10.0, 0.0, 270.0),    # blowing east -> comes from the west
        (-10.0, 0.0, 90.0),    # blowing west -> comes from the east
        (0.0, 10.0, 180.0),    # blowing north -> comes from the south
        (0.0, -10.0, 0.0),     # blowing south -> comes from the north
        (10.0, 10.0, 225.0),   # from the southwest
    ],
)
def test_uv_to_met_direction(u: float, v: float, expected: float) -> None:
    assert float(circ.uv_to_met_direction(u, v)) == pytest.approx(expected)


def test_calm_has_no_direction() -> None:
    assert np.isnan(circ.uv_to_met_direction(0.0, 0.0))


def test_round_trip_through_met_direction_to_uv() -> None:
    for d in range(0, 360, 45):
        u, v = circ.met_direction_to_uv(12.0, d)
        assert float(circ.uv_to_met_direction(u, v)) == pytest.approx(d % 360.0, abs=1e-9)


def test_matches_the_backend_met_to_uv_formula() -> None:
    """Must agree with backend/bfps/core/wind.py:45 exactly."""
    import math

    for speed in (1.0, 17.5):
        for d in (0.0, 30.0, 123.4, 270.0, 359.9):
            rad = math.radians(d)
            assert circ.met_direction_to_uv(speed, d)[0] == pytest.approx(-speed * math.sin(rad))
            assert circ.met_direction_to_uv(speed, d)[1] == pytest.approx(-speed * math.cos(rad))


# --- the wrap-around trap ----------------------------------------------------


def test_circular_mean_of_350_and_10_is_zero_not_180() -> None:
    """The headline pitfall: the naive arithmetic mean gives the opposite direction."""
    got = float(circ.circular_mean_deg(np.array([350.0, 10.0])))
    assert got == pytest.approx(0.0, abs=1e-9) or got == pytest.approx(360.0, abs=1e-9)
    naive = float(np.mean([350.0, 10.0]))
    assert naive == pytest.approx(180.0)
    assert abs(((got - naive + 180.0) % 360.0) - 180.0) > 170.0


def test_circular_mean_of_359_and_1() -> None:
    got = float(circ.circular_mean_deg(np.array([359.0, 1.0])))
    assert min(got, 360.0 - got) == pytest.approx(0.0, abs=1e-9)


def test_circular_mean_of_a_simple_spread() -> None:
    assert float(circ.circular_mean_deg(np.array([80.0, 100.0]))) == pytest.approx(90.0)


# --- resultant length --------------------------------------------------------


def test_resultant_length_is_one_for_identical_directions() -> None:
    assert float(circ.resultant_length(np.full(20, 42.0))) == pytest.approx(1.0)


def test_resultant_length_is_zero_for_opposing_directions() -> None:
    assert float(circ.resultant_length(np.array([0.0, 180.0]))) == pytest.approx(0.0, abs=1e-12)


def test_resultant_length_is_small_for_a_uniform_spread() -> None:
    angles = np.arange(0.0, 360.0, 1.0)
    assert float(circ.resultant_length(angles)) < 1e-10


def test_resultant_length_is_bounded() -> None:
    rng = np.random.default_rng(0)
    r = circ.resultant_length(rng.uniform(0, 360, size=(500, 7)))
    assert np.all((r >= 0.0) & (r <= 1.0))


# --- circular standard deviation ---------------------------------------------


def test_circular_sd_is_zero_for_a_perfect_resultant() -> None:
    assert float(circ.circular_sd_deg(1.0)) == pytest.approx(0.0)


def test_circular_sd_grows_as_the_resultant_shrinks() -> None:
    sd = circ.circular_sd_deg(np.array([0.99, 0.8, 0.5, 0.2]))
    assert np.all(np.diff(sd) > 0)


def test_circular_sd_is_nan_below_the_resultant_floor() -> None:
    """Bimodal or near-uniform directions have no meaningful spread."""
    sd = circ.circular_sd_deg(np.array([0.0, 0.05, 0.099, 0.101]))
    assert np.all(np.isnan(sd[:3]))
    assert np.isfinite(sd[3])


def test_circular_sd_never_returns_a_complex_number_or_raises() -> None:
    out = circ.circular_sd_deg(np.array([0.0, 1e-300, 1.0]))
    assert out.dtype.kind == "f"


# --- speed weighting ---------------------------------------------------------


def test_unit_vector_mean_ignores_speed_but_the_vector_mean_does_not() -> None:
    """One strong easterly against many weak westerlies: the two means disagree.

    The vector mean of the wind follows the strong event, because that is what
    actually moves a balloon. The unit-vector mean follows the count.
    """
    dirs = np.array([270.0] * 9 + [90.0])
    speeds = np.array([1.0] * 9 + [50.0])
    unit_dir = float(circ.circular_mean_deg(dirs))
    u, v = circ.met_direction_to_uv(speeds, dirs)
    weighted_dir = float(circ.uv_to_met_direction(u.mean(), v.mean()))
    assert unit_dir == pytest.approx(270.0, abs=1.0)
    assert weighted_dir == pytest.approx(90.0, abs=1.0)
