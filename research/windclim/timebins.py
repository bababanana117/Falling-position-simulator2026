"""Half-month binning.

A bin here is a fixed range of days within a calendar month:

    H1 = 1-15,  H2 = 16-end of month

The boundaries fall on the same dates every year, so "the first half of March"
names the same 15 days in 2016 and in 2025, and a ten-year statistic for that
label is directly usable. That is the same reason the pipeline originally used
four seven-day bins per month, and it still holds.

Why fifteen days rather than seven
----------------------------------
The seven-day version was chosen before there was any evidence about what the
data supports. The time-resolution study (see :mod:`windclim.stats.timescale`)
later measured it: the leave-one-year-out error is flat between five and fifteen
days, and the one-standard-error rule picks **fifteen** for Wakayama and thirty
for Hokkaido. Seven days was never wrong -- it sits inside the indistinguishable
range -- but it was finer than the evidence called for, and it left the report
recommending one granularity while shipping another.

Nothing is lost in accuracy. Re-running the cross-validation season by season,
fifteen-day bins differ from seven-day bins by less than one standard error in
all eight season-by-region cases, and are marginally *better* in six of them.

What is gained is precision on the percentiles. Consecutive six-hourly analyses
are almost identical (lag-1 autocorrelation about 0.975), so a seven-day bin's
280 samples are worth only about four independent ones. Doubling the bin halves
the noise on the quantities the report leans on: the 90th percentile of wind
speed at 200 hPa has a standard error of 1.70 m/s at seven days and 1.04 m/s at
fifteen.

The bins are also more even. Seven-day bins run 7 to 10 days long -- a 43 per
cent spread, because the last one absorbs the remainder of the month -- while
half-months run 13 to 16, a 23 per cent spread. They are still not equal, so the
sample count is stored alongside every statistic rather than assumed uniform.

A bin width is a presentational choice, not a discovery. The study's own
conclusion is that the real structure is a smooth one-to-two-month seasonal
cycle -- a six-term Fourier series beats every bin width tried -- and any
step-function binning is an approximation to that curve.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "ANALYSES_PER_DAY",
    "DEFAULT_SCHEME",
    "HALF_MONTH",
    "HALVES",
    "HALF_STARTS",
    "JST",
    "SCHEMES",
    "WEEK",
    "BinScheme",
    "SEASONS",
    "SEASON_ORDER",
    "assign_bin",
    "expected_sample_count",
    "half_calendar",
    "half_day_range",
    "half_of_month",
    "month_of",
    "n_days_in_bin",
    "scheme_by_name",
    "scheme_of",
    "season_of",
]

#: JRA-3Q analyses are 6-hourly: 00/06/12/18 UTC = 09/15/21/03 JST.
ANALYSES_PER_DAY = 4

JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class BinScheme:
    """One way of cutting a calendar month into fixed day-of-month bins.

    The pipeline ships one scheme and can reproduce the other. ``starts`` gives
    the first day of each bin; the last bin always runs to the end of the month,
    which is why it is the only one whose length varies.
    """

    name: str
    starts: tuple[int, ...]
    labels: tuple[str, ...]
    short: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.starts) != len(self.labels) or len(self.starts) != len(self.short):
            raise ValueError("starts, labels and short must be the same length")
        if self.starts[0] != 1:
            raise ValueError(f"the first bin must start on day 1, got {self.starts[0]}")
        if list(self.starts) != sorted(self.starts):
            raise ValueError(f"starts must be ascending, got {self.starts}")

    @property
    def bins(self) -> tuple[int, ...]:
        """1-based bin indices."""
        return tuple(range(1, len(self.starts) + 1))

    @property
    def n_bins(self) -> int:
        return len(self.starts)

    def index_of(self, day: int) -> int:
        """Which bin a day-of-month falls in, 1-based."""
        if not 1 <= day <= 31:
            raise ValueError(f"day must be in 1..31, got {day}")
        return int(np.searchsorted(np.asarray(self.starts), day, side="right"))

    def day_range(self, year: int, month: int, index: int) -> tuple[int, int]:
        """Inclusive ``(first_day, last_day)`` of one bin."""
        if index not in self.bins:
            raise ValueError(f"index must be one of {self.bins}, got {index}")
        start = self.starts[index - 1]
        if index == self.n_bins:
            return start, calendar.monthrange(year, month)[1]
        return start, self.starts[index] - 1

    def n_days(self, year: int, month: int, index: int) -> int:
        first, last = self.day_range(year, month, index)
        return last - first + 1

    def expected_samples(self, month: int, index: int, years: Iterable[int]) -> int:
        """Analyses a bin should hold over ``years``, as a sanity gate."""
        return sum(self.n_days(y, month, index) for y in years) * ANALYSES_PER_DAY

    def calendar_rows(self, years: Iterable[int]) -> list[dict[str, int]]:
        """One row per (month, bin) describing how the bin is defined."""
        years = list(years)
        rows: list[dict[str, int]] = []
        for month in range(1, 13):
            for index in self.bins:
                ends = [self.day_range(y, month, index)[1] for y in years]
                n_days = sum(self.n_days(y, month, index) for y in years)
                rows.append(
                    {
                        "month": month,
                        "bin": index,
                        "start_day": self.starts[index - 1],
                        "end_day_min": min(ends),
                        "end_day_max": max(ends),
                        "n_days": n_days,
                        "n_analyses": n_days * ANALYSES_PER_DAY,
                    }
                )
        return rows


#: The shipped scheme. See the module docstring for why fifteen days.
HALF_MONTH = BinScheme(
    name="half",
    starts=(1, 16),
    labels=("前半 (1-15日)", "後半 (16日-月末)"),
    short=("H1", "H2"),
)

#: The scheme the pipeline used before the time-resolution study. Kept so the
#: appendix's figures can be regenerated rather than archived as stale files.
WEEK = BinScheme(
    name="week",
    starts=(1, 8, 15, 22),
    labels=("W1 (1-7日)", "W2 (8-14日)", "W3 (15-21日)", "W4 (22日-月末)"),
    short=("W1", "W2", "W3", "W4"),
)

SCHEMES: dict[str, BinScheme] = {s.name: s for s in (HALF_MONTH, WEEK)}
DEFAULT_SCHEME = HALF_MONTH


def scheme_by_name(name: str) -> BinScheme:
    try:
        return SCHEMES[name]
    except KeyError:
        raise ValueError(
            f"unknown bin scheme {name!r}; known: {sorted(SCHEMES)}"
        ) from None


# --- the default scheme, for callers that do not care ------------------------

HALF_STARTS: tuple[int, ...] = DEFAULT_SCHEME.starts
HALVES: tuple[int, ...] = DEFAULT_SCHEME.bins


def half_of_month(day: int) -> int:
    """Bin index of a day-of-month under the default scheme."""
    return DEFAULT_SCHEME.index_of(day)


def half_day_range(year: int, month: int, half: int) -> tuple[int, int]:
    """Inclusive day range of a bin under the default scheme."""
    return DEFAULT_SCHEME.day_range(year, month, half)


def n_days_in_bin(year: int, month: int, half: int) -> int:
    return DEFAULT_SCHEME.n_days(year, month, half)


def expected_sample_count(month: int, half: int, years: Iterable[int]) -> int:
    return DEFAULT_SCHEME.expected_samples(month, half, years)


def half_calendar(years: Iterable[int]) -> list[dict[str, int]]:
    return DEFAULT_SCHEME.calendar_rows(years)


def assign_bin(
    when: datetime, *, convention: str = "utc", scheme: BinScheme | None = None
) -> tuple[int, int]:
    """Map an analysis time to its ``(month, bin)``.

    ``convention="utc"`` bins by the UTC date, which is the data's own axis and
    needs no carry-over between calendar months. ``convention="jst"`` shifts to
    Japan Standard Time first, which moves the 18 UTC analysis onto the next JST
    day. Only an analysis sitting on a bin edge can change bin, so the two agree
    on all but a handful of samples; the pipeline computes both so the report
    can show that rather than assert it.
    """
    scheme = scheme or DEFAULT_SCHEME
    if when.tzinfo is None:
        raise ValueError("assign_bin requires a timezone-aware datetime")
    if convention == "utc":
        local = when.astimezone(UTC)
    elif convention == "jst":
        local = when.astimezone(JST)
    else:
        raise ValueError(f"convention must be 'utc' or 'jst', got {convention!r}")
    return local.month, scheme.index_of(local.day)


#: The four meteorological seasons, by calendar month. Winter is DJF rather than
#: JFM because it is the atmosphere's own year, not the civil one, that matters
#: here: the polar vortex, the jet's southward shift and the monsoon retreat all
#: turn over between November and December.
SEASONS: dict[str, tuple[int, ...]] = {
    "冬 (12-2月)": (12, 1, 2),
    "春 (3-5月)": (3, 4, 5),
    "夏 (6-8月)": (6, 7, 8),
    "秋 (9-11月)": (9, 10, 11),
}

#: Months in the order the figures and tables walk the seasons.
SEASON_ORDER: tuple[str, ...] = tuple(SEASONS)


def month_of(times) -> NDArray[np.int64]:
    """Calendar month 1-12 of each ``datetime64``.

    The obvious shortcut -- taking the day-of-year fraction and multiplying by
    twelve -- is wrong by up to a day and a half, because the months are not the
    same length. That is harmless for a curve plotted against day of year and not
    harmless at all for a season boundary, where it moves a handful of analyses
    from February into March every year.
    """
    t = np.asarray(times, dtype="datetime64[M]")
    return (t.astype("datetime64[M]").astype(int) % 12 + 1).astype(np.int64)


def season_of(times) -> NDArray[np.object_]:
    """Season label of each ``datetime64``, using :data:`SEASONS`."""
    month = month_of(times)
    out = np.empty(month.shape, dtype=object)
    for name, months in SEASONS.items():
        out[np.isin(month, months)] = name
    return out


def scheme_of(ds) -> BinScheme:
    """Recover the bin scheme a dataset was built under.

    Reads the attributes :func:`windclim.stats.aggregate.aggregate_month` writes.
    Falls back to the default only for datasets made before the attribute
    existed, and says so, because silently guessing the scheme would mislabel
    every axis in a figure.
    """
    name = ds.attrs.get("bin_scheme")
    if name is None:
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).warning(
            "dataset has no bin_scheme attribute; assuming %r. Re-run the "
            "aggregation to record it.", DEFAULT_SCHEME.name,
        )
        return DEFAULT_SCHEME
    scheme = scheme_by_name(str(name))
    n = int(ds.sizes.get("bin", scheme.n_bins))
    if n != scheme.n_bins:
        raise ValueError(
            f"dataset says scheme {name!r} ({scheme.n_bins} bins) but the bin "
            f"dimension has length {n}"
        )
    return scheme
