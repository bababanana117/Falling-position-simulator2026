"""Half-month binning: fixed day-of-month halves, H1 = 1-15, H2 = 16-end of month.

The dates are fixed rather than derived from the ISO week, so "the first half of
March" is the same 15 days every year and a ten-year statistic for that label
means something. The price is that H2 runs 13 to 16 days, so the bins are not
equal and the sample count has to travel with every statistic.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime

import pytest

from windclim import timebins as tb

YEARS = range(2016, 2026)


# --- half_of_month -----------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "half"),
    [
        (1, 1), (2, 1), (14, 1), (15, 1),      # the boundary belongs to the first half
        (16, 2), (17, 2), (28, 2), (29, 2), (30, 2), (31, 2),
    ],
)
def test_half_of_month_boundaries(day: int, half: int) -> None:
    assert tb.half_of_month(day) == half


@pytest.mark.parametrize("day", [0, -1, 32, 100])
def test_half_of_month_rejects_impossible_days(day: int) -> None:
    with pytest.raises(ValueError, match="day must be in"):
        tb.half_of_month(day)


# --- half_day_range ----------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "month", "half", "expected"),
    [
        (2016, 1, 1, (1, 15)),
        (2016, 1, 2, (16, 31)),
        (2016, 2, 2, (16, 29)),      # leap February
        (2017, 2, 2, (16, 28)),      # ordinary February
        (2016, 4, 2, (16, 30)),      # 30-day month
        (2016, 4, 1, (1, 15)),
    ],
)
def test_half_day_range(year: int, month: int, half: int, expected: tuple[int, int]) -> None:
    assert tb.half_day_range(year, month, half) == expected


def test_half_day_range_rejects_a_bad_half() -> None:
    for half in (0, 3, 4):
        with pytest.raises(ValueError, match="index must be one of"):
            tb.half_day_range(2016, 1, half)


def test_the_first_half_is_always_exactly_fifteen_days() -> None:
    """Only H2 absorbs the month's remainder; H1 never varies."""
    for year in YEARS:
        for month in range(1, 13):
            assert tb.n_days_in_bin(year, month, 1) == 15


def test_the_second_half_spans_thirteen_to_sixteen_days() -> None:
    """February is the short end, the 31-day months the long one.

    The seven-day scheme this replaced ran 7 to 10 days, a 43 per cent spread;
    this is 23 per cent. Still uneven, which is why the sample count is stored.
    """
    lengths = {
        tb.n_days_in_bin(y, m, 2) for y in YEARS for m in range(1, 13)
    }
    assert lengths == {13, 14, 15, 16}


def test_halves_partition_every_month_exactly_once() -> None:
    """Every day of 2016-2025 falls in exactly one bin, with no gaps or overlaps."""
    for year in YEARS:
        for month in range(1, 13):
            covered: list[int] = []
            for half in tb.HALVES:
                d0, d1 = tb.half_day_range(year, month, half)
                covered.extend(range(d0, d1 + 1))
            assert covered == list(range(1, calendar.monthrange(year, month)[1] + 1))


# --- expected_sample_count ---------------------------------------------------


@pytest.mark.parametrize(
    ("month", "half", "expected"),
    [
        (1, 1, 15 * 10 * 4),                 # 15 days, ten years, four analyses a day
        (1, 2, 16 * 10 * 4),                 # January has 31 days
        (4, 2, 15 * 10 * 4),                 # April has 30
        (2, 1, 15 * 10 * 4),
    ],
)
def test_expected_sample_count(month: int, half: int, expected: int) -> None:
    assert tb.expected_sample_count(month, half, YEARS) == expected


def test_february_second_half_is_leap_aware() -> None:
    """Three leap years in 2016-2025, so February H2 holds three extra days."""
    assert tb.expected_sample_count(2, 2, YEARS) == (13 * 7 + 14 * 3) * 4


def test_total_sample_count_equals_all_analyses_in_period() -> None:
    total = sum(
        tb.expected_sample_count(m, h, YEARS) for m in range(1, 13) for h in tb.HALVES
    )
    n_days = sum(366 if calendar.isleap(y) else 365 for y in YEARS)
    assert total == n_days * 4


# --- assign_bin --------------------------------------------------------------


def _utc(y: int, m: int, d: int, h: int) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


def test_assign_bin_utc_convention() -> None:
    assert tb.assign_bin(_utc(2016, 1, 15, 18), convention="utc") == (1, 1)
    assert tb.assign_bin(_utc(2016, 1, 16, 0), convention="utc") == (1, 2)


def test_assign_bin_jst_convention_shifts_across_the_boundary() -> None:
    """18Z on 15 Jan is 16 Jan in JST (UTC+9), so it lands in H2 under the JST rule."""
    assert tb.assign_bin(_utc(2016, 1, 15, 18), convention="jst") == (1, 2)
    assert tb.assign_bin(_utc(2016, 1, 15, 12), convention="jst") == (1, 1)  # 21 JST


def test_assign_bin_jst_can_roll_into_the_next_month() -> None:
    assert tb.assign_bin(_utc(2016, 1, 31, 18), convention="jst") == (2, 1)


def test_assign_bin_rejects_unknown_convention() -> None:
    with pytest.raises(ValueError):
        tb.assign_bin(_utc(2016, 1, 1, 0), convention="local")


def test_assign_bin_requires_timezone_aware_input() -> None:
    with pytest.raises(ValueError):
        tb.assign_bin(datetime(2016, 1, 1, 0), convention="utc")  # noqa: DTZ001


def test_only_the_edge_analyses_change_bin_between_conventions() -> None:
    """Widening the bin from 7 days to 15 halves how often the convention matters.

    Only the 18 UTC analysis can move, and only on the last day of a bin. With
    two bins a month instead of four, there are half as many bin edges for it to
    move across.
    """
    moved = 0
    total = 0
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(2017, month)[1] + 1):
            for hour in (0, 6, 12, 18):
                t = _utc(2017, month, day, hour)
                total += 1
                if tb.assign_bin(t, convention="utc") != tb.assign_bin(t, convention="jst"):
                    moved += 1
    assert moved == 24               # one analysis at each of 24 bin edges
    assert total == 365 * 4
    assert moved / total < 0.02


# --- half_calendar -----------------------------------------------------------


def test_half_calendar_shape_and_contents() -> None:
    rows = tb.half_calendar(YEARS)
    assert len(rows) == 24
    jan_h2 = next(r for r in rows if r["month"] == 1 and r["bin"] == 2)
    assert jan_h2 == {
        "month": 1,
        "bin": 2,
        "start_day": 16,
        "end_day_min": 31,
        "end_day_max": 31,
        "n_days": 160,
        "n_analyses": 640,
    }
    feb_h2 = next(r for r in rows if r["month"] == 2 and r["bin"] == 2)
    assert feb_h2["end_day_min"] == 28
    assert feb_h2["end_day_max"] == 29
    assert feb_h2["n_days"] == 13 * 7 + 14 * 3
    assert feb_h2["n_analyses"] == feb_h2["n_days"] * 4


def test_half_calendar_first_halves_never_vary() -> None:
    for row in tb.half_calendar(YEARS):
        if row["bin"] == 1:
            assert row["end_day_min"] == row["end_day_max"] == 15
            assert row["n_days"] == 150
