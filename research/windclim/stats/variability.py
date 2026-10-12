"""How fast the wind changes, and whether that speed depends on the season.

The climatology answers "what is the wind usually like in the third half of
January". This module answers a different question that matters just as much to
someone planning a launch: **how quickly does it stop being like that?**

Three things are measured, all of them broken down by season.

*How far the wind moves in a given time.* The size of ``V(t+L) - V(t)`` as a
vector, for lags from six hours to ten days. This is the direct answer to "if I
look at the wind now, how wrong will I be in a day?" It is a vector difference,
not a difference of speeds: a wind that keeps its strength and turns ninety
degrees has changed completely, and a scalar comparison would call that no change
at all.

*How long the wind remembers.* The lag at which the autocorrelation of the wind
anomaly falls through ``1/e``. One number per season per level, and the natural
unit for "how often is a fresh forecast worth fetching".

*How far the landing point moves if the launch slips.* The same lag machinery
applied to the displacement the flight model already computes per analysis. This
is the operational form of the question, in kilometres.

Two things are done deliberately and would be wrong done casually.

**Pairs are kept inside one season.** At a lag of ten days a pair that starts on
28 February ends in March. Counting it under winter would smear the seasons
together at exactly the lags where the difference between them is the headline.
Every pair reported under a season has both of its endpoints in that season.

**Directions are never subtracted as numbers.** The day-to-day change in wind
direction is computed by resolving both days into components, and the difference
is wrapped onto ``[-180, 180]`` before its size is taken. Subtracting 350 from 10
gives -340, which would report an almost-unchanged wind as a near-reversal. See
:mod:`windclim.stats.circular`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ..timebins import SEASON_ORDER, season_of
from .circular import uv_to_met_direction
from .significance import variance_decomposition
from .vector import lag_autocorr

__all__ = [
    "DEFAULT_DRIFT_LAGS_HOURS",
    "DEFAULT_LAGS_HOURS",
    "ANALYSIS_STEP_HOURS",
    "analysis_step_hours",
    "autocorrelation_component_table",
    "daily_direction_change",
    "daily_means",
    "decorrelation_hours",
    "drift_slip_table",
    "lag_change_table",
    "vector_autocorrelation_table",
    "variance_split_table",
]

#: Lags for the wind-change curve. Six hours is one analysis step. The long end
#: is set by two opposing pressures: summer's upper-level wind is still
#: correlated at ten days, so a shorter list would report "no crossing" instead
#: of a number; but the anomaly is taken about the season's own mean and a season
#: is only about ninety days, so a lag approaching a third of that estimates the
#: correlation from too little independent data and biases it towards zero.
#: Twenty days is as far as this goes.
DEFAULT_LAGS_HOURS: tuple[int, ...] = (6, 12, 24, 48, 72, 120, 240, 360, 480)

#: Lags for the launch-slip question. Nobody reschedules a campaign by ten days,
#: so this stops at five.
DEFAULT_DRIFT_LAGS_HOURS: tuple[int, ...] = (6, 12, 24, 48, 72, 120)

ANALYSIS_STEP_HOURS = 6.0


def analysis_step_hours(times: NDArray) -> float:
    """The spacing of the analysis grid, refusing anything irregular.

    Every lag here is turned into an index offset, which is only the same thing
    as a time offset if the grid has no gaps. A missing analysis would silently
    turn a 24-hour lag into a 30-hour one, so it is checked rather than assumed.
    """
    t = np.asarray(times, dtype="datetime64[s]").astype(np.int64)
    if t.size < 2:
        raise ValueError("need at least two analyses")
    step = np.diff(t)
    unique = np.unique(step)
    if unique.size != 1:
        raise ValueError(
            f"the analysis grid has {unique.size} different spacings "
            f"({unique.min() / 3600:.1f}..{unique.max() / 3600:.1f} h); "
            "lags cannot be index offsets on a grid with gaps"
        )
    return float(unique[0]) / 3600.0


def _lag_steps(times: NDArray, lag_hours: int) -> int:
    step = analysis_step_hours(times)
    if lag_hours % step != 0:
        raise ValueError(f"lag {lag_hours} h is not a multiple of the {step:g} h grid")
    return int(round(lag_hours / step))


def _as_vector(values: NDArray) -> NDArray[np.float64]:
    """Reshape ``(time, ...)`` with a trailing 2-axis into ``(time, cell, 2)``."""
    v = np.asarray(values, dtype=np.float64)
    if v.ndim < 2 or v.shape[-1] != 2:
        raise ValueError(
            f"expected a trailing component axis of length 2, got shape {v.shape}"
        )
    return v.reshape(v.shape[0], -1, 2)


def _season_pair_mask(times: NDArray, k: int) -> dict[str, NDArray[np.bool_]]:
    """For each season, the starts whose lagged partner is in the same season."""
    season = season_of(times)
    same = season[:-k] == season[k:]
    return {s: (season[:-k] == s) & same for s in SEASON_ORDER}


def lag_change_table(
    values: NDArray,
    times: NDArray,
    *,
    lags_hours: tuple[int, ...] = DEFAULT_LAGS_HOURS,
    levels: NDArray | None = None,
    scale: float = 1.0,
    unit: str = "m s-1",
) -> pd.DataFrame:
    """Size of ``V(t+L) - V(t)`` by season and lag, and by level if given.

    ``values`` is ``(time, ..., 2)``. When ``levels`` is given it must name the
    second axis, ``(time, level, ..., 2)``, and the answer is resolved by level.
    ``scale`` multiplies the result, for turning metres into kilometres.
    """
    v = np.asarray(values, dtype=np.float64)
    has_level = levels is not None
    if has_level and v.shape[1] != len(levels):
        raise ValueError(f"levels has {len(levels)} entries but axis 1 is {v.shape[1]}")

    rows: list[dict] = []
    for lag in lags_hours:
        k = _lag_steps(times, lag)
        if k >= v.shape[0]:
            continue
        delta = v[k:] - v[:-k]
        mag = np.hypot(delta[..., 0], delta[..., 1]) * scale
        masks = _season_pair_mask(times, k)
        for season, m in masks.items():
            if not m.any():
                continue
            picked = mag[m]
            if has_level:
                for li, level in enumerate(np.asarray(levels)):
                    rows.append(
                        _summarise(picked[:, li], season, lag, unit)
                        | {"plevel": float(level)}
                    )
            else:
                rows.append(_summarise(picked, season, lag, unit))
    return pd.DataFrame(rows)


def _summarise(x: NDArray, season: str, lag_hours: int, unit: str) -> dict:
    flat = np.asarray(x, dtype=float).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return {"season": season, "lag_hours": lag_hours, "unit": unit,
                "median": np.nan, "p90": np.nan, "max": np.nan, "n": 0}
    return {
        "season": season,
        "lag_hours": lag_hours,
        "unit": unit,
        "median": float(np.median(finite)),
        "p90": float(np.percentile(finite, 90)),
        "max": float(finite.max()),
        "n": int(finite.size),
    }


def vector_autocorrelation_table(
    values: NDArray,
    times: NDArray,
    *,
    lags_hours: tuple[int, ...] = DEFAULT_LAGS_HOURS,
    levels: NDArray | None = None,
) -> pd.DataFrame:
    """Vector autocorrelation of the wind anomaly, by season, lag and level.

    The anomaly is taken about that season's own mean, so a season whose wind
    simply blows steadily in one direction does not score a high correlation for
    that reason alone -- what is measured is the persistence of the *departures*
    from the seasonal wind, which is the part a forecast has to work for.
    """
    v = np.asarray(values, dtype=np.float64)
    has_level = levels is not None
    season = season_of(times)
    rows: list[dict] = []

    for s in SEASON_ORDER:
        in_season = season == s
        if in_season.sum() < 2:
            continue
        anomaly = v.copy()
        anomaly[in_season] -= np.nanmean(v[in_season], axis=0, keepdims=True)
        for lag in lags_hours:
            k = _lag_steps(times, lag)
            if k >= v.shape[0]:
                continue
            m = (season[:-k] == s) & (season[k:] == s)
            if not m.any():
                continue
            a = anomaly[:-k][m]
            b = anomaly[k:][m]
            if has_level:
                for li, level in enumerate(np.asarray(levels)):
                    rows.append({
                        "season": s, "lag_hours": lag, "plevel": float(level),
                        "r": _vector_corr(a[:, li], b[:, li]),
                    })
            else:
                rows.append({"season": s, "lag_hours": lag, "r": _vector_corr(a, b)})
    return pd.DataFrame(rows)


def _vector_corr(a: NDArray, b: NDArray) -> float:
    """``<a . b> / sqrt(<|a|^2><|b|^2>)`` for two samples of 2-D anomalies.

    The vector form rather than separate ``u`` and ``v`` correlations, because a
    wind that keeps its strength and rotates has lost its memory even though each
    component may still look correlated with itself.
    """
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    b = np.asarray(b, dtype=float).reshape(-1, 2)
    ok = np.isfinite(a).all(axis=1) & np.isfinite(b).all(axis=1)
    if ok.sum() < 2:
        return float("nan")
    a, b = a[ok], b[ok]
    num = float(np.mean(np.sum(a * b, axis=1)))
    den = float(np.sqrt(np.mean(np.sum(a * a, axis=1)) * np.mean(np.sum(b * b, axis=1))))
    return num / den if den > 0 else float("nan")


def decorrelation_hours(
    lags_hours: NDArray, r: NDArray, *, threshold: float = float(np.exp(-1))
) -> float:
    """Where the autocorrelation curve first falls through ``1/e``, interpolated.

    Returns NaN if the curve never gets there within the lags supplied, which is
    a real answer -- it means the wind's memory is longer than the window looked
    at -- and is more useful than reporting the last lag as though it were the
    crossing.
    """
    lags = np.asarray(lags_hours, dtype=float)
    rr = np.asarray(r, dtype=float)
    order = np.argsort(lags)
    lags, rr = lags[order], rr[order]
    below = np.nonzero(rr < threshold)[0]
    if below.size == 0:
        return float("nan")
    i = int(below[0])
    if i == 0:
        return float(lags[0])
    r0, r1 = rr[i - 1], rr[i]
    if not np.isfinite(r0) or r0 == r1:
        return float(lags[i])
    frac = (r0 - threshold) / (r0 - r1)
    return float(lags[i - 1] + frac * (lags[i] - lags[i - 1]))


def daily_means(
    values: NDArray, times: NDArray
) -> tuple[NDArray[np.float64], NDArray]:
    """Average each calendar day's analyses. Returns ``(means, day_dates)``.

    A day is the unit the question is asked in ("does the wind change from day to
    day"), and averaging to it first removes the diurnal cycle, which is a
    different phenomenon that would otherwise be counted as day-to-day change.
    """
    v = np.asarray(values, dtype=np.float64)
    days = np.asarray(times, dtype="datetime64[D]")
    uniq, inverse = np.unique(days, return_inverse=True)
    out = np.full((uniq.size, *v.shape[1:]), np.nan)
    for i in range(uniq.size):
        sel = inverse == i
        with np.errstate(invalid="ignore"):
            out[i] = np.nanmean(v[sel], axis=0)
    return out, uniq


def daily_direction_change(
    u: NDArray, v: NDArray, times: NDArray, *, levels: NDArray | None = None
) -> pd.DataFrame:
    """Size of the day-to-day change in daily-mean wind direction, by season.

    Consecutive calendar days only, and both days in the same season. The result
    is an unsigned angle in degrees, so a 20-degree veer and a 20-degree back
    count the same -- the question is how much the direction moves, not which way.
    """
    du, days = daily_means(np.asarray(u, dtype=float), times)
    dv, _ = daily_means(np.asarray(v, dtype=float), times)
    direction = uv_to_met_direction(du, dv)

    consecutive = (days[1:] - days[:-1]) == np.timedelta64(1, "D")
    season = season_of(days.astype("datetime64[ns]"))
    same = (season[:-1] == season[1:]) & consecutive

    diff = np.abs((direction[1:] - direction[:-1] + 180.0) % 360.0 - 180.0)

    rows: list[dict] = []
    for s in SEASON_ORDER:
        m = same & (season[:-1] == s)
        if not m.any():
            continue
        picked = diff[m]
        if levels is not None:
            for li, level in enumerate(np.asarray(levels)):
                rows.append(
                    _summarise(picked[:, li], s, 24, "deg") | {"plevel": float(level)}
                )
        else:
            rows.append(_summarise(picked, s, 24, "deg"))
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class VarianceSplit:
    """Where the variance of a quantity lives, in the units of its square."""

    season: str
    total: float
    within_day: float
    day_to_day: float
    seasonal: float
    interannual: float

    @property
    def within_day_fraction(self) -> float:
        return self.within_day / self.total if self.total > 0 else float("nan")


def variance_split_table(values: NDArray, times: NDArray) -> pd.DataFrame:
    """Split the variance into within-day, day-to-day and between-season parts.

    ``seasonal`` and ``interannual`` come from
    :func:`windclim.stats.significance.variance_decomposition` with the season as
    the bin, so they mean exactly what they mean everywhere else in this package:
    what a seasonal climatology explains, and how far a season's own mean wanders
    from year to year. The two parts added here split what is left over into the
    diurnal cycle and everything slower than a day but faster than a season.
    """
    v = np.asarray(values, dtype=np.float64)
    flat = v.reshape(v.shape[0], -1)
    day_of = np.asarray(times, dtype="datetime64[D]")
    _, day_index = np.unique(day_of, return_inverse=True)
    season = season_of(times)
    years = np.asarray(times, dtype="datetime64[Y]").astype(int) + 1970

    lookup = {s: i for i, s in enumerate(SEASON_ORDER)}
    labels = np.array([lookup[s] for s in season], dtype=np.int64)
    parts = variance_decomposition(flat, labels, years)

    day_mean = np.zeros_like(flat)
    for d in np.unique(day_index):
        m = day_index == d
        with np.errstate(invalid="ignore"):
            day_mean[m] = np.nanmean(flat[m], axis=0)
    within_day = float(np.nanmean((flat - day_mean) ** 2))

    rows = [{
        "scope": "全体",
        "total": parts.total,
        "within_day": within_day,
        "day_to_day": max(parts.within_bins - within_day, 0.0),
        "seasonal": parts.between_bins,
        "interannual": parts.interannual,
    }]
    for s in SEASON_ORDER:
        m = season == s
        if not m.any():
            continue
        sub = flat[m]
        sub_day = day_mean[m]
        rows.append({
            "scope": s,
            "total": float(np.nanmean((sub - np.nanmean(sub, axis=0)) ** 2)),
            "within_day": float(np.nanmean((sub - sub_day) ** 2)),
            "day_to_day": float(
                np.nanmean((sub_day - np.nanmean(sub, axis=0)) ** 2)
            ),
            "seasonal": np.nan,
            "interannual": np.nan,
        })
    out = pd.DataFrame(rows)
    out["within_day_fraction"] = out["within_day"] / out["total"]
    return out


def drift_slip_table(
    dx_m: NDArray,
    dy_m: NDArray,
    times: NDArray,
    *,
    lags_hours: tuple[int, ...] = DEFAULT_DRIFT_LAGS_HOURS,
) -> pd.DataFrame:
    """How far the predicted landing point moves if the launch slips by ``L``.

    This is the launch-slip question in the units it is asked in. It is *not* an
    error in the simulator -- the simulator would have been right about both
    launches. It is the sensitivity of the answer to the schedule, which is what
    decides how much slack a campaign needs.
    """
    d = np.stack([np.asarray(dx_m, dtype=float), np.asarray(dy_m, dtype=float)], axis=-1)
    return lag_change_table(d, times, lags_hours=lags_hours, scale=1e-3, unit="km")


def autocorrelation_component_table(
    values: NDArray, times: NDArray, *, lags_hours: tuple[int, ...] = DEFAULT_LAGS_HOURS
) -> pd.DataFrame:
    """Per-component autocorrelation, as a cross-check on the vector form.

    Reusing :func:`windclim.stats.vector.lag_autocorr` here keeps the two
    definitions in the same place: if the vector correlation and the component
    correlations disagree wildly, one of them is wrong.
    """
    v = _as_vector(values)
    rows: list[dict] = []
    for lag in lags_hours:
        k = _lag_steps(times, lag)
        if k >= v.shape[0]:
            continue
        rows.append({
            "lag_hours": lag,
            "r_u": float(np.nanmean(lag_autocorr(v[..., 0], k))),
            "r_v": float(np.nanmean(lag_autocorr(v[..., 1], k))),
        })
    return pd.DataFrame(rows)
