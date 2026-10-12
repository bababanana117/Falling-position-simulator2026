"""The day-to-day variability machinery, checked against constructed answers.

Every function here reduces ten years of wind to a handful of numbers, and a
reduction that is subtly wrong looks exactly like a reduction that is right. So
each one is fed a series whose answer is known by construction -- a pure
sinusoid, an AR(1) process with a set time constant, a wind that turns through
north -- and asked to recover it.
"""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import variability as vb
from windclim.timebins import SEASON_ORDER


def hourly_grid(n: int, start: str = "2016-01-01", step_h: int = 6) -> np.ndarray:
    return (
        np.datetime64(start, "ns")
        + np.arange(n, dtype="int64") * np.timedelta64(step_h, "h")
    )


def ten_years() -> np.ndarray:
    """The real analysis grid: 6-hourly, 2016 through 2025, no gaps."""
    return np.arange(
        np.datetime64("2016-01-01T00", "ns"),
        np.datetime64("2026-01-01T00", "ns"),
        np.timedelta64(6, "h"),
    )


# --------------------------------------------------------------------------
# The grid itself. A gap here would corrupt every lag silently.
# --------------------------------------------------------------------------


def test_the_analysis_step_is_measured_not_assumed() -> None:
    assert vb.analysis_step_hours(ten_years()) == pytest.approx(6.0)


def test_a_gap_in_the_analysis_grid_is_an_error() -> None:
    """A lag is an index offset, which only means a time offset on a full grid."""
    t = np.delete(hourly_grid(100), 50)
    with pytest.raises(ValueError, match="different spacings"):
        vb.analysis_step_hours(t)


def test_a_lag_off_the_grid_is_an_error() -> None:
    t = hourly_grid(100)
    v = np.zeros((100, 1, 2))
    with pytest.raises(ValueError, match="not a multiple"):
        vb.lag_change_table(v, t, lags_hours=(9,))


# --------------------------------------------------------------------------
# The change curve.
# --------------------------------------------------------------------------


def test_a_steady_wind_never_changes() -> None:
    t = ten_years()
    v = np.tile(np.array([7.0, -3.0]), (t.size, 1, 1))
    table = vb.lag_change_table(v, t)
    assert np.allclose(table["median"], 0.0, atol=1e-12)
    assert np.allclose(table["p90"], 0.0, atol=1e-12)


def test_the_change_curve_grows_with_the_lag_for_a_random_walk() -> None:
    """More time, more change -- up to the point where the series saturates."""
    rng = np.random.default_rng(3)
    t = ten_years()
    v = np.cumsum(rng.normal(0, 0.3, (t.size, 1, 2)), axis=0)
    table = vb.lag_change_table(v, t, lags_hours=(6, 12, 24, 48))
    for season in SEASON_ORDER:
        med = table[table["season"] == season].sort_values("lag_hours")["median"].values
        assert np.all(np.diff(med) > 0), f"{season} is not monotonic: {med}"


def test_a_rotating_wind_of_constant_speed_still_counts_as_change() -> None:
    """A scalar comparison of speeds would report this wind as perfectly steady.

    It is not steady: after six hours it is blowing from somewhere else, and a
    balloon launched into it goes somewhere else. This is why the difference is
    taken as a vector.
    """
    t = ten_years()
    angle = np.arange(t.size) * (np.pi / 2)          # a quarter turn every analysis
    v = np.stack([10 * np.cos(angle), 10 * np.sin(angle)], axis=-1)[:, None, :]
    table = vb.lag_change_table(v, t, lags_hours=(6,))
    speed_change = np.hypot(v[..., 0], v[..., 1])
    assert np.allclose(speed_change, 10.0)
    assert np.allclose(table["median"], 10.0 * np.sqrt(2), rtol=1e-9)


def test_pairs_never_straddle_a_season_boundary() -> None:
    """At ten days a late-February pair would end in March.

    Winter's own change rate is the headline; letting spring leak into it at the
    long lags would flatten exactly the difference being looked for.
    """
    t = ten_years()
    # Winter is calm, everything else is wild. If pairs leaked, winter's number
    # would jump at the long lags.
    from windclim.timebins import season_of
    season = season_of(t)
    rng = np.random.default_rng(1)
    amp = np.where(season == SEASON_ORDER[0], 0.0, 50.0)[:, None, None]
    v = rng.normal(0, 1, (t.size, 1, 2)) * amp
    table = vb.lag_change_table(v, t, lags_hours=(6, 240))
    winter = table[table["season"] == SEASON_ORDER[0]]
    assert np.allclose(winter["median"], 0.0, atol=1e-12)
    assert (winter["n"] > 0).all()


def test_the_change_table_resolves_by_level_when_asked() -> None:
    t = hourly_grid(4 * 400)
    rng = np.random.default_rng(5)
    scale = np.array([1.0, 10.0])[None, :, None, None]
    v = rng.normal(0, 1, (t.size, 2, 3, 2)) * scale
    table = vb.lag_change_table(v, t, lags_hours=(24,), levels=np.array([850.0, 200.0]))
    quiet = table[table["plevel"] == 850.0]["median"].mean()
    loud = table[table["plevel"] == 200.0]["median"].mean()
    assert loud == pytest.approx(10 * quiet, rel=0.05)


# --------------------------------------------------------------------------
# Memory: the autocorrelation and where it crosses 1/e.
# --------------------------------------------------------------------------


def test_an_ar1_process_gives_back_its_own_time_constant() -> None:
    """An AR(1) with ``r(L) = exp(-L/tau)`` must decorrelate at ``tau``.

    This is the test that makes the "the wind forgets in N days" number mean
    something: the estimator recovers a time constant it was not told.
    """
    tau_hours = 48.0
    t = ten_years()
    phi = float(np.exp(-6.0 / tau_hours))
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 1, (t.size, 1, 2))
    x = np.empty_like(noise)
    x[0] = noise[0]
    for i in range(1, t.size):
        x[i] = phi * x[i - 1] + np.sqrt(1 - phi**2) * noise[i]

    lags = (6, 12, 24, 48, 72, 120)
    table = vb.vector_autocorrelation_table(x, t, lags_hours=lags)
    for season in SEASON_ORDER:
        sub = table[table["season"] == season].sort_values("lag_hours")
        got = vb.decorrelation_hours(sub["lag_hours"].values, sub["r"].values)
        assert got == pytest.approx(tau_hours, rel=0.12), f"{season}: {got}"


def test_white_noise_has_no_memory_at_all() -> None:
    t = ten_years()
    rng = np.random.default_rng(7)
    x = rng.normal(0, 1, (t.size, 1, 2))
    table = vb.vector_autocorrelation_table(x, t, lags_hours=(6, 24))
    assert np.allclose(table["r"], 0.0, atol=0.05)
    sub = table[table["season"] == SEASON_ORDER[0]].sort_values("lag_hours")
    assert vb.decorrelation_hours(sub["lag_hours"].values, sub["r"].values) == 6.0


def test_a_wind_that_never_forgets_reports_no_crossing() -> None:
    """NaN is the honest answer when the memory is longer than the window looked at.

    Reporting the last lag instead would turn "we do not know" into a number
    someone could plan around.
    """
    assert np.isnan(vb.decorrelation_hours([6, 24, 240], [0.99, 0.98, 0.97]))


def test_the_crossing_is_interpolated_not_snapped_to_a_lag() -> None:
    """Falling from 1 to 0 over 24 hours, 1/e is passed most of the way along.

    Snapping to the nearer lag would quantise every answer onto the handful of
    lags that happen to be in the list, which is a coarser answer than the data
    supports.
    """
    got = vb.decorrelation_hours([24.0, 48.0], [1.0, 0.0])
    assert got == pytest.approx(24.0 + 24.0 * (1.0 - float(np.exp(-1))), rel=1e-9)
    assert 24.0 < got < 48.0


def test_the_anomaly_is_taken_about_the_season_mean() -> None:
    """A steady seasonal wind must not score as persistent by itself.

    Without removing the seasonal mean, a season with a strong steady jet would
    show ``r`` near one at every lag, and be reported as highly predictable when
    in fact none of its *departures* persist at all.
    """
    t = ten_years()
    rng = np.random.default_rng(13)
    v = rng.normal(0, 1, (t.size, 1, 2)) + np.array([60.0, 0.0])
    table = vb.vector_autocorrelation_table(v, t, lags_hours=(6, 24))
    assert np.allclose(table["r"], 0.0, atol=0.05)


# --------------------------------------------------------------------------
# Directions, where the obvious arithmetic is wrong.
# --------------------------------------------------------------------------


def test_the_direction_change_across_north_is_twenty_degrees_not_three_forty() -> None:
    """The canonical circular trap, in the form it takes here."""
    from windclim.stats.circular import met_direction_to_uv

    t = np.arange(
        np.datetime64("2016-01-01T00", "ns"),
        np.datetime64("2016-01-03T00", "ns"),
        np.timedelta64(6, "h"),
    )
    directions = np.repeat([350.0, 10.0], 4)
    u, v = met_direction_to_uv(np.full(8, 12.0), directions)
    table = vb.daily_direction_change(u[:, None], v[:, None], t)
    assert table["median"].iloc[0] == pytest.approx(20.0, abs=1e-6)


def test_the_direction_change_ignores_which_way_it_turned() -> None:
    from windclim.stats.circular import met_direction_to_uv

    t = np.arange(
        np.datetime64("2016-01-01T00", "ns"),
        np.datetime64("2016-01-03T00", "ns"),
        np.timedelta64(6, "h"),
    )
    for pair in ([350.0, 10.0], [10.0, 350.0]):
        u, v = met_direction_to_uv(np.full(8, 12.0), np.repeat(pair, 4))
        table = vb.daily_direction_change(u[:, None], v[:, None], t)
        assert table["median"].iloc[0] == pytest.approx(20.0, abs=1e-6)


def test_non_consecutive_days_are_not_compared() -> None:
    """A gap of a half is not a day-to-day change, whatever the indices say."""
    t = np.concatenate([
        np.arange(np.datetime64("2016-01-01T00", "ns"),
                  np.datetime64("2016-01-02T00", "ns"), np.timedelta64(6, "h")),
        np.arange(np.datetime64("2016-01-20T00", "ns"),
                  np.datetime64("2016-01-21T00", "ns"), np.timedelta64(6, "h")),
    ])
    u = np.concatenate([np.full(4, 10.0), np.full(4, -10.0)])[:, None]
    v = np.zeros_like(u)
    table = vb.daily_direction_change(u, v, t)
    assert table.empty


def test_daily_means_average_the_four_analyses_of_a_day() -> None:
    t = hourly_grid(8)
    v = np.arange(8, dtype=float)[:, None]
    means, days = vb.daily_means(v, t)
    assert days.size == 2
    assert means[0, 0] == pytest.approx(1.5)
    assert means[1, 0] == pytest.approx(5.5)


# --------------------------------------------------------------------------
# Where the variance lives.
# --------------------------------------------------------------------------


def test_a_purely_diurnal_signal_lands_entirely_in_the_within_day_part() -> None:
    t = ten_years()
    hour = (np.asarray(t, dtype="datetime64[h]").astype(np.int64)) % 24
    v = np.sin(2 * np.pi * hour / 24.0)[:, None]
    table = vb.variance_split_table(v, t)
    overall = table[table["scope"] == "全体"].iloc[0]
    assert overall["within_day_fraction"] == pytest.approx(1.0, abs=0.02)
    assert overall["seasonal"] == pytest.approx(0.0, abs=1e-3)


def test_a_purely_seasonal_signal_lands_in_the_seasonal_part() -> None:
    from windclim.timebins import season_of

    t = ten_years()
    lookup = {s: i for i, s in enumerate(SEASON_ORDER)}
    v = np.array([float(lookup[s]) for s in season_of(t)])[:, None]
    table = vb.variance_split_table(v, t)
    overall = table[table["scope"] == "全体"].iloc[0]
    assert overall["seasonal"] / overall["total"] == pytest.approx(1.0, abs=1e-9)
    assert overall["within_day"] == pytest.approx(0.0, abs=1e-12)


def test_the_split_reports_every_season_as_well_as_the_whole() -> None:
    t = ten_years()
    rng = np.random.default_rng(17)
    table = vb.variance_split_table(rng.normal(0, 1, (t.size, 2)), t)
    assert set(table["scope"]) == {"全体", *SEASON_ORDER}


# --------------------------------------------------------------------------
# The launch-slip question, in kilometres.
# --------------------------------------------------------------------------


def test_the_slip_table_is_in_kilometres() -> None:
    t = ten_years()
    dx = np.zeros((t.size, 1))
    dx[1::2] = 30000.0                       # 30 km apart, alternating
    dy = np.zeros_like(dx)
    table = vb.drift_slip_table(dx, dy, t, lags_hours=(6,))
    assert table["unit"].unique().tolist() == ["km"]
    assert np.allclose(table["median"], 30.0)


def test_the_slip_table_covers_every_season() -> None:
    t = ten_years()
    rng = np.random.default_rng(19)
    dx = rng.normal(0, 50000, (t.size, 3, 2))
    table = vb.drift_slip_table(dx[..., 0], dx[..., 1], t)
    assert set(table["season"]) == set(SEASON_ORDER)
    assert (table["n"] > 1000).all()
