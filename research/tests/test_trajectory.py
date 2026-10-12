"""The gridded integrator, pinned against answers that are known independently.

The point of :mod:`windclim.stats.trajectory` is to measure how wrong the frozen
wind is. A measurement is only worth as much as the instrument, so the instrument
is checked here against three kinds of known answer: the closed form the rest of
the package already uses, the analytic solution of the advection equation on a
sphere, and the interpolator's own exactness on fields it should reproduce
perfectly.
"""

from __future__ import annotations

import numpy as np
import pytest

from windclim.config import kept_levels
from windclim.grid import EARTH_RADIUS_M
from windclim.stats import trajectory as tj
from windclim.stats.altitude import isa_altitude_from_pressure
from windclim.stats.drift import FlightProfile, displacements, flight_seconds, layer_seconds

FLIGHT = FlightProfile()

#: A realistic grid: the master box resolution, cut to something small and fast.
LAT = np.arange(30.0, 40.01, 0.375)
LON = np.arange(132.0, 145.01, 0.375)


@pytest.fixture(scope="module")
def alt() -> np.ndarray:
    """Level altitudes ascending, from the pressure levels actually fetched."""
    p = np.asarray(kept_levels(), dtype=float)[::-1]      # 1000 hPa first
    return isa_altitude_from_pressure(p)


@pytest.fixture(scope="module")
def schedule(alt) -> tj.FlightSchedule:
    return tj.build_schedule(alt, FLIGHT)


def make_wind(u_field, v_field, n_times: int = 4) -> tj.GriddedWind:
    """Build a :class:`GriddedWind` from callables ``f(t_index, level, lat, lon)``."""
    n_lev = len(kept_levels())
    la = LAT[None, None, :, None]
    lo = LON[None, None, None, :]
    lev = np.arange(n_lev)[None, :, None, None]
    ti = np.arange(n_times)[:, None, None, None]
    shape = (n_times, n_lev, LAT.size, LON.size)
    u = np.broadcast_to(np.asarray(u_field(ti, lev, la, lo), dtype=float), shape)
    v = np.broadcast_to(np.asarray(v_field(ti, lev, la, lo), dtype=float), shape)
    return tj.GriddedWind(
        lat=LAT.copy(), lon=LON.copy(),
        u=np.ascontiguousarray(u, dtype=np.float32),
        v=np.ascontiguousarray(v, dtype=np.float32),
    )


def launch_at(lat: float, lon: float, it: int = 0):
    return np.array([lat]), np.array([lon]), np.array([it])


# --------------------------------------------------------------------------
# The vertical model must be the one the rest of the package already uses.
# --------------------------------------------------------------------------


def test_schedule_reproduces_the_layer_times_exactly(alt, schedule) -> None:
    """If the flight lasted a different time, every variant would be biased.

    The whole comparison rests on all four variants flying the identical z(t), and
    on that z(t) being the one ``drift.displacements`` implicitly assumes.
    """
    assert schedule.total_seconds == pytest.approx(
        float(flight_seconds(alt, FLIGHT)), rel=1e-12
    )


def test_schedule_visits_each_layer_twice(alt, schedule) -> None:
    """Once going up and once coming down -- and with the right split.

    The descent is faster than the ascent in thin air, so the two halves are not
    equal; getting them the wrong way round would put too much weight on the
    stratosphere, where the wind is strongest.
    """
    seconds = layer_seconds(alt, FLIGHT)
    used = np.nonzero(seconds > 0)[0]
    for k in used:
        total = schedule.seconds[schedule.level_index == k].sum()
        assert total == pytest.approx(float(seconds[k]), rel=1e-12)
    assert schedule.n_segments == 2 * used.size


def test_schedule_starts_at_the_lowest_level_and_turns_round_at_burst(alt, schedule) -> None:
    """The flight begins at 1000 hPa, about 110 m up, not at the ground.

    That is inherited from ``layer_seconds``, whose bottom layer edge is the
    lowest level's own altitude rather than sea level, and it is left alone on
    purpose: changing it would move every drift number already in the report. The
    cost is about 40 of 8280 seconds, spent in the slowest and weakest wind of the
    flight, and it is identical for all four variants, so it cancels out of every
    difference this module exists to measure.
    """
    assert schedule.z_start[0] == pytest.approx(float(alt[0]))
    assert schedule.z_end[-1] == pytest.approx(float(alt[0]))
    assert schedule.z_end.max() == pytest.approx(FLIGHT.burst_altitude_m)
    assert 0.0 < float(alt[0]) < 200.0


def test_schedule_rejects_a_descending_profile() -> None:
    """The raw files store ascending pressure, which is descending altitude.

    Feeding that straight in would silently invert the flight, so it is an error
    rather than something to sort quietly.
    """
    with pytest.raises(ValueError, match="ascending in altitude"):
        tj.build_schedule(np.array([30000.0, 20000.0, 10000.0]), FLIGHT)


# --------------------------------------------------------------------------
# Cross-check against the closed form the package already trusts.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("variant", tj.VARIANTS)
def test_no_wind_means_no_displacement(schedule, variant) -> None:
    wind = make_wind(lambda t, k, y, x: 0.0, lambda t, k, y, x: 0.0)
    la, lo, it = launch_at(34.0, 135.0)
    out = tj.integrate(wind, schedule, la, lo, it, variant=variant, dt=120.0)
    assert out.dx_east_m[0] == pytest.approx(0.0, abs=1e-9)
    assert out.dy_north_m[0] == pytest.approx(0.0, abs=1e-9)
    assert not out.left_grid.any()


@pytest.mark.parametrize("variant", tj.VARIANTS)
def test_uniform_zonal_wind_gives_speed_times_flight_time(schedule, variant) -> None:
    """Every variant must agree here: with a uniform steady wind, nothing is frozen.

    This is the case where the simulator's approximation is not an approximation
    at all, so any disagreement between the variants would be a bug in the
    integrator rather than a property of the atmosphere.
    """
    u0 = 20.0
    wind = make_wind(lambda t, k, y, x: u0, lambda t, k, y, x: 0.0)
    la, lo, it = launch_at(34.0, 135.0)
    out = tj.integrate(wind, schedule, la, lo, it, variant=variant, dt=60.0)
    assert out.dx_east_m[0] == pytest.approx(u0 * schedule.total_seconds, rel=1e-9)
    assert out.dy_north_m[0] == pytest.approx(0.0, abs=1e-6)


def test_both_frozen_matches_the_closed_form_on_a_non_uniform_zonal_field(
    alt, schedule
) -> None:
    """The strong version of the cross-check: sheared wind, still exact.

    A constant field would not test much -- any integrator gets that right. Here
    the wind varies with level, with position and with time, so the closed form
    and the integrator agree only if the layer times, the level indexing and the
    freezing all line up. Purely zonal keeps the latitude fixed, which removes the
    ``1/cos(lat)`` factor from the comparison; the closed form has no latitude in
    it, so that factor is the one thing it genuinely cannot represent.
    """
    def u(t, k, y, x):
        return 5.0 + 0.8 * k + 3.0 * np.sin(np.radians(4 * x)) + 2.0 * (y - 34.0) + 1.5 * t

    wind = make_wind(u, lambda t, k, y, x: 0.0)
    lat0, lon0 = 34.028846153846146, 135.0     # exactly on the grid
    i = int(np.argmin(np.abs(LAT - lat0)))
    j = int(np.argmin(np.abs(LON - lon0)))
    la, lo, it = launch_at(float(LAT[i]), float(LON[j]), it=1)

    out = tj.integrate(wind, schedule, la, lo, it, variant="both_frozen", dt=120.0)

    # The closed form, fed the very same profile at the very same analysis.
    uu = wind.u[1:2, :, i, j][:, :, None, None].astype(float)
    vv = wind.v[1:2, :, i, j][:, :, None, None].astype(float)
    dx, dy = displacements(uu, vv, np.asarray(alt)[:, None, None], FLIGHT)

    assert out.dx_east_m[0] == pytest.approx(float(dx[0, 0, 0]), rel=1e-12)
    assert out.dy_north_m[0] == pytest.approx(float(dy[0, 0, 0]), abs=1e-9)


def test_both_frozen_matches_the_closed_form_on_a_non_uniform_meridional_field(
    alt, schedule
) -> None:
    """The northward half of the same check.

    ``dy`` never involves the map factor, so this one is exact for any field.
    """
    def v(t, k, y, x):
        return -4.0 + 0.5 * k + 2.0 * np.cos(np.radians(3 * x)) + 1.0 * t

    wind = make_wind(lambda t, k, y, x: 0.0, v)
    i, j = 10, 8
    la, lo, it = launch_at(float(LAT[i]), float(LON[j]), it=1)

    out = tj.integrate(wind, schedule, la, lo, it, variant="both_frozen", dt=120.0)

    uu = wind.u[1:2, :, i, j][:, :, None, None].astype(float)
    vv = wind.v[1:2, :, i, j][:, :, None, None].astype(float)
    dx, dy = displacements(uu, vv, np.asarray(alt)[:, None, None], FLIGHT)

    assert out.dy_north_m[0] == pytest.approx(float(dy[0, 0, 0]), rel=1e-12)
    assert out.dx_east_m[0] == pytest.approx(float(dx[0, 0, 0]), abs=1e-9)


# --------------------------------------------------------------------------
# The two freezes must be separable, or the headline number means nothing.
# --------------------------------------------------------------------------


def test_a_wind_that_only_changes_with_time_is_blind_to_the_place_freeze(
    schedule,
) -> None:
    wind = make_wind(lambda t, k, y, x: 10.0 + 6.0 * t, lambda t, k, y, x: 2.0)
    la, lo, it = launch_at(34.0, 135.0, it=1)
    ref = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=60.0)
    place = tj.integrate(wind, schedule, la, lo, it, variant="place_frozen", dt=60.0)
    time = tj.integrate(wind, schedule, la, lo, it, variant="time_frozen", dt=60.0)

    assert place.dx_east_m[0] == pytest.approx(ref.dx_east_m[0], rel=1e-12)
    assert abs(time.dx_east_m[0] - ref.dx_east_m[0]) > 1000.0


def test_a_wind_that_only_changes_with_place_is_blind_to_the_time_freeze(
    schedule,
) -> None:
    wind = make_wind(
        lambda t, k, y, x: 10.0 + 8.0 * (x - 135.0), lambda t, k, y, x: 2.0
    )
    la, lo, it = launch_at(34.0, 135.0, it=1)
    ref = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=60.0)
    place = tj.integrate(wind, schedule, la, lo, it, variant="place_frozen", dt=60.0)
    time = tj.integrate(wind, schedule, la, lo, it, variant="time_frozen", dt=60.0)

    assert time.dx_east_m[0] == pytest.approx(ref.dx_east_m[0], rel=1e-12)
    assert abs(place.dx_east_m[0] - ref.dx_east_m[0]) > 1000.0


# --------------------------------------------------------------------------
# Numerics: the analytic solution, and convergence in the step size.
# --------------------------------------------------------------------------


def test_constant_wind_follows_the_analytic_loxodrome(schedule) -> None:
    """A steady ``(u, v)`` on a sphere has a closed-form solution; hit it.

    The latitude rises linearly, so the ``1/cos(lat)`` factor in the longitude
    equation keeps changing and the track is not a straight line in degrees. The
    exact answer is the Mercator integral, which is what tells us the RK4 and the
    map factor are wired together correctly rather than merely plausibly.
    """
    u0, v0 = 25.0, 12.0
    wind = make_wind(lambda t, k, y, x: u0, lambda t, k, y, x: v0)
    phi0 = np.radians(31.0)
    la, lo, it = launch_at(31.0, 133.0)
    out = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=30.0)

    phi_t = phi0 + v0 * schedule.total_seconds / EARTH_RADIUS_M
    merc = np.log(np.tan(np.pi / 4 + phi_t / 2)) - np.log(np.tan(np.pi / 4 + phi0 / 2))
    expected_dlon_deg = np.degrees((u0 / v0) * merc)

    assert np.degrees(phi_t) - 31.0 == pytest.approx(out.lat[0] - 31.0, rel=1e-9)
    assert out.lon[0] - 133.0 == pytest.approx(expected_dlon_deg, rel=1e-7)


@pytest.mark.parametrize("dt", [30.0, 60.0, 120.0])
def test_the_landing_point_is_insensitive_to_the_step_size(schedule, dt) -> None:
    """A result that moves when the step changes is a result about the step.

    One kilometre is the tolerance because the errors being measured are tens of
    kilometres; a step-size artefact an order of magnitude smaller than the signal
    cannot change any conclusion.
    """
    def u(t, k, y, x):
        return 12.0 + 0.6 * k + 9.0 * np.sin(np.radians(6 * x)) + 4.0 * t

    def v(t, k, y, x):
        return 3.0 + 5.0 * np.cos(np.radians(5 * y)) - 1.0 * t

    wind = make_wind(u, v)
    la, lo, it = launch_at(33.0, 134.0, it=1)
    fine = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=10.0)
    test = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=dt)
    gap_km = np.hypot(
        test.dx_east_m[0] - fine.dx_east_m[0],
        test.dy_north_m[0] - fine.dy_north_m[0],
    ) / 1000.0
    assert gap_km < 1.0


# --------------------------------------------------------------------------
# The interpolator itself.
# --------------------------------------------------------------------------


def test_bilinear_sampling_is_exact_for_a_bilinear_field() -> None:
    """Bilinear interpolation reproduces ``a + bx + cy + dxy`` with no error.

    If it does not, the interpolator is not bilinear, and every trajectory built
    on it is wrong in a way no trajectory test would localise.
    """
    def u(t, k, y, x):
        return 2.0 + 0.3 * (y - 34.0) - 0.7 * (x - 135.0) + 0.05 * (y - 34.0) * (x - 135.0)

    wind = make_wind(u, lambda t, k, y, x: 0.0, n_times=1)
    rng = np.random.default_rng(0)
    la = rng.uniform(LAT[0], LAT[-1], 500)
    lo = rng.uniform(LON[0], LON[-1], 500)
    got, _, inside = wind.sample(la, lo, 0, np.zeros(500, dtype=np.int64), 0.0)
    want = u(0, 0, la, lo)
    assert inside.all()
    assert np.allclose(got, want, rtol=0, atol=2e-5)


def test_time_sampling_is_exact_for_a_field_linear_in_time() -> None:
    wind = make_wind(lambda t, k, y, x: 3.0 + 7.0 * t, lambda t, k, y, x: 0.0)
    la = np.array([33.1, 34.7])
    lo = np.array([134.2, 138.9])
    it = np.array([1, 1])
    got, _, _ = wind.sample(la, lo, 0, it, 0.25)
    assert np.allclose(got, 3.0 + 7.0 * 1.25, atol=1e-5)


def test_the_sampler_reads_the_level_it_is_asked_for() -> None:
    """Off-by-one in the level axis would quietly swap the jet for the boundary layer."""
    wind = make_wind(lambda t, k, y, x: 1.0 * k, lambda t, k, y, x: 0.0, n_times=1)
    for level in (0, 5, len(kept_levels()) - 1):
        got, _, _ = wind.sample(
            np.array([34.0]), np.array([135.0]), level, np.zeros(1, dtype=np.int64), 0.0
        )
        assert got[0] == pytest.approx(float(level), abs=1e-4)


# --------------------------------------------------------------------------
# Guards. Each of these was a way to get a plausible wrong number.
# --------------------------------------------------------------------------


def test_leaving_the_grid_is_flagged_not_silently_clamped(schedule) -> None:
    """A payload blown past the edge of the cached box has no wind to fly into.

    Clamping it to the edge keeps the integration running, but the landing point
    is then fiction, so it has to be reported and excluded rather than averaged in.
    """
    wind = make_wind(lambda t, k, y, x: 300.0, lambda t, k, y, x: 0.0)
    la, lo, it = launch_at(34.0, 144.0)
    out = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=120.0)
    assert out.left_grid[0]


def test_a_flight_running_past_the_window_is_an_error(schedule) -> None:
    wind = make_wind(lambda t, k, y, x: 5.0, lambda t, k, y, x: 0.0, n_times=2)
    la, lo, it = launch_at(34.0, 135.0, it=1)
    with pytest.raises(ValueError, match="past the end of this window"):
        tj.integrate(wind, schedule, la, lo, it, variant="reference")


def test_a_frozen_flight_may_start_on_the_last_analysis(schedule) -> None:
    """Freezing time means the next analysis is never read, so it need not exist."""
    wind = make_wind(lambda t, k, y, x: 5.0, lambda t, k, y, x: 0.0, n_times=2)
    la, lo, it = launch_at(34.0, 135.0, it=1)
    out = tj.integrate(wind, schedule, la, lo, it, variant="both_frozen")
    assert out.dx_east_m[0] == pytest.approx(5.0 * schedule.total_seconds, rel=1e-9)


def test_an_unknown_variant_is_rejected(schedule) -> None:
    wind = make_wind(lambda t, k, y, x: 0.0, lambda t, k, y, x: 0.0)
    la, lo, it = launch_at(34.0, 135.0)
    with pytest.raises(ValueError, match="variant must be one of"):
        tj.integrate(wind, schedule, la, lo, it, variant="frozen")


def test_a_descending_latitude_axis_is_rejected() -> None:
    """The cache stores ascending latitude; a reversed axis would flip north and south."""
    n_lev = len(kept_levels())
    shape = (1, n_lev, LAT.size, LON.size)
    with pytest.raises(ValueError, match="lat must be strictly ascending"):
        tj.GriddedWind(
            lat=LAT[::-1].copy(), lon=LON.copy(),
            u=np.zeros(shape, dtype=np.float32), v=np.zeros(shape, dtype=np.float32),
        )


def test_the_altitude_spread_across_a_region_is_reported(alt) -> None:
    """Using one profile per region is a stated approximation; this is its size."""
    base = np.asarray(alt)[:, None, None]
    offset = np.linspace(-100.0, 100.0, 8 * 9).reshape(1, 8, 9)
    spread = tj.altitude_profile_spread(base + offset, burst_altitude_m=30000.0)
    assert spread["max_spread_m"] == pytest.approx(200.0, rel=1e-9)
    assert spread["fraction_of_climb"] == pytest.approx(200.0 / 30000.0, rel=1e-9)


def test_the_closed_form_and_the_integrator_part_company_over_the_map_factor(
    alt, schedule
) -> None:
    """With both components active the two stop agreeing exactly, and this is why.

    ``drift.displacements`` sums ``u_k T_k`` into metres and never mentions
    latitude. The integrator works in degrees, so as the payload drifts north the
    ``1/cos(lat)`` factor shifts under it. Neither is a bug: the integrator has
    the correct geometry and the simulator does the same thing, while the closed
    form is a flat-earth shortcut that is fine for a climatology and off by a
    kilometre or two on a 300 km winter flight. Pinning the size here stops it
    being rediscovered as a mystery in the production run.
    """
    u0, v0 = 60.0, 25.0
    wind = make_wind(lambda t, k, y, x: u0, lambda t, k, y, x: v0)
    la, lo, it = launch_at(float(LAT[4]), float(LON[4]))
    out = tj.integrate(wind, schedule, la, lo, it, variant="both_frozen", dt=60.0)

    flat_dx = u0 * schedule.total_seconds
    flat_dy = v0 * schedule.total_seconds
    assert out.dy_north_m[0] == pytest.approx(flat_dy, rel=1e-9)

    # The whole discrepancy is the cosine ratio, evaluated at the mid-flight latitude.
    mid = np.radians(LAT[4] + 0.5 * np.degrees(flat_dy / EARTH_RADIUS_M))
    predicted = flat_dx * np.cos(np.radians(LAT[4])) / np.cos(mid)
    assert out.dx_east_m[0] == pytest.approx(predicted, rel=2e-4)
    assert abs(out.dx_east_m[0] - flat_dx) > 1000.0


def test_the_track_starts_at_the_launch_point_and_ends_where_the_result_says(
    schedule,
) -> None:
    """A path that does not end at the reported landing point is a different flight."""
    wind = make_wind(lambda t, k, y, x: 18.0, lambda t, k, y, x: 4.0)
    la, lo, it = launch_at(34.0, 135.0)
    out = tj.integrate(wind, schedule, la, lo, it, variant="reference", dt=120.0,
                       track=True)
    assert out.track_lat is not None
    assert out.track_lat[0, 0] == pytest.approx(34.0)
    assert out.track_lon[0, 0] == pytest.approx(135.0)
    assert out.track_lat[-1, 0] == pytest.approx(out.lat[0], rel=1e-12)
    assert out.track_lon[-1, 0] == pytest.approx(out.lon[0], rel=1e-12)


def test_the_tracked_altitude_rises_to_burst_then_returns(alt, schedule) -> None:
    wind = make_wind(lambda t, k, y, x: 0.0, lambda t, k, y, x: 0.0)
    la, lo, it = launch_at(34.0, 135.0)
    out = tj.integrate(wind, schedule, la, lo, it, dt=120.0, track=True)
    z = out.track_alt
    peak = int(np.argmax(z))
    assert z[peak] == pytest.approx(FLIGHT.burst_altitude_m, rel=1e-6)
    assert np.all(np.diff(z[: peak + 1]) >= -1e-6)
    assert np.all(np.diff(z[peak:]) <= 1e-6)
    assert z[-1] == pytest.approx(float(alt[0]))


def test_tracking_does_not_change_the_answer(schedule) -> None:
    """The path is a by-product; switching it on must not move the landing point."""
    wind = make_wind(lambda t, k, y, x: 11.0 + 0.4 * k, lambda t, k, y, x: -3.0)
    la, lo, it = launch_at(33.5, 134.5, it=1)
    plain = tj.integrate(wind, schedule, la, lo, it, dt=120.0)
    traced = tj.integrate(wind, schedule, la, lo, it, dt=120.0, track=True)
    assert traced.dx_east_m[0] == pytest.approx(plain.dx_east_m[0], rel=1e-15)
    assert traced.dy_north_m[0] == pytest.approx(plain.dy_north_m[0], rel=1e-15)
