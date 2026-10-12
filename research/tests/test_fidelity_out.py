"""The fidelity driver: the reductions that turn a million flights into a table.

The trajectory integration itself is tested in ``test_trajectory``. What is
checked here is the layer above it -- that the seasons are cut the right way,
that the two rankings are allowed to disagree, and that the launch-slip figure
is not quietly conflated with the simulator's own error.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from windclim.outputs import fidelity_out as fo
from windclim.timebins import SEASON_ORDER


def error_frame(**overrides) -> pd.DataFrame:
    """A summarised error table with winter worst absolutely, best relatively."""
    flight = {SEASON_ORDER[0]: 270.0, SEASON_ORDER[1]: 165.0,
              SEASON_ORDER[2]: 63.0, SEASON_ORDER[3]: 125.0}
    med = overrides.get("median_km", {s: 5.3 - 0.8 * i
                                      for i, s in enumerate(SEASON_ORDER)})
    rows = []
    for season in SEASON_ORDER:
        for variant in fo.COMPARED:
            m = med[season] if variant == "both_frozen" else med[season] * 0.7
            rows.append({
                "season": season, "variant": variant,
                "variant_ja": fo.JP_VARIANT[variant],
                "median_km": m, "p90_km": m * 2, "max_km": m * 5,
                "flight_median_km": flight[season],
                "relative_median": m / flight[season],
                "relative_p90": 2 * m / flight[season], "n": 250000,
            })
    return pd.DataFrame(rows)


def slip_frame() -> pd.DataFrame:
    rows = []
    for i, season in enumerate(SEASON_ORDER):
        for lag in (6, 24, 48):
            rows.append({"season": season, "lag_hours": lag, "unit": "km",
                         "median": 20.0 + 5 * i, "p90": 40.0 + 10 * i,
                         "max": 200.0, "n": 250000})
    return pd.DataFrame(rows)


def launch_frame(n_per_season: int = 500) -> pd.DataFrame:
    """A per-launch frame spanning a full year, as the integrator would return."""
    times = np.arange(
        np.datetime64("2020-01-01T00", "ns"),
        np.datetime64("2021-01-01T00", "ns"),
        np.timedelta64(6, "h"),
    )
    rng = np.random.default_rng(23)
    frame = pd.DataFrame({
        "time": times,
        "ref_dx_m": rng.normal(150000, 40000, times.size),
        "ref_dy_m": rng.normal(0, 20000, times.size),
        "left_grid": np.zeros(times.size, dtype=bool),
        "lat": np.full(times.size, 34.0),
        "lon": np.full(times.size, 135.0),
    })
    for i, variant in enumerate(fo.COMPARED):
        frame[f"err_{variant}_km"] = rng.gamma(2.0, 1.5 + i, times.size)
    from windclim.timebins import season_of
    frame["season"] = season_of(frame["time"].values)
    frame["ref_distance_km"] = np.hypot(frame["ref_dx_m"], frame["ref_dy_m"]) / 1000.0
    return frame


# --------------------------------------------------------------------------
# Summarising the per-launch errors.
# --------------------------------------------------------------------------


def test_every_season_and_variant_gets_a_row() -> None:
    table = fo.summarise_errors(launch_frame())
    assert set(table["season"]) == set(SEASON_ORDER)
    assert set(table["variant"]) == set(fo.COMPARED)
    assert len(table) == len(SEASON_ORDER) * len(fo.COMPARED)


def test_launches_that_left_the_grid_are_excluded_not_averaged_in() -> None:
    """A payload blown off the edge of the cache has a fictional landing point.

    Averaging it in would quietly contaminate the season it belongs to with a
    number that describes the size of the box rather than the atmosphere.
    """
    frame = launch_frame()
    frame.loc[frame.index[:100], "left_grid"] = True
    frame.loc[frame.index[:100], "err_both_frozen_km"] = 9999.0
    table = fo.summarise_errors(frame)
    assert table["max_km"].max() < 1000.0
    assert table["n"].sum() < len(frame) * len(fo.COMPARED)


def test_the_relative_error_is_divided_by_the_flight_not_a_constant() -> None:
    frame = launch_frame()
    table = fo.summarise_errors(frame)
    row = table.iloc[0]
    sub = frame[frame["season"] == row["season"]]
    expected = float(np.median(
        sub[f"err_{row['variant']}_km"] / sub["ref_distance_km"]
    ))
    assert row["relative_median"] == pytest.approx(expected, rel=1e-9)


# --------------------------------------------------------------------------
# The ranking, which is the answer to the question that was asked.
# --------------------------------------------------------------------------


def test_the_two_rankings_are_allowed_to_disagree() -> None:
    """Winter has the largest miss in kilometres and the smallest share of the flight.

    Collapsing the two into one score would pick an answer instead of reporting
    one, so the table keeps both and the report says which question each answers.
    """
    table = fo.rank_seasons(error_frame(), slip_frame())
    winter = table[table["season"] == SEASON_ORDER[0]].iloc[0]
    assert winter["rank_absolute"] == len(SEASON_ORDER)
    assert winter["rank_relative"] == 1


def test_the_ranking_carries_the_launch_slip_alongside_the_error() -> None:
    """Two different risks, and a campaign has to weigh both."""
    table = fo.rank_seasons(error_frame(), slip_frame())
    assert table["slip_24h_median_km"].notna().all()
    assert (table["slip_24h_median_km"] > table["sim_error_median_km"]).all()


def test_the_ranking_uses_the_live_simulator_not_a_half_frozen_variant() -> None:
    """``both_frozen`` is the code that actually runs; the others are diagnostics."""
    error = error_frame()
    table = fo.rank_seasons(error, slip_frame())
    live = error[error["variant"] == "both_frozen"].set_index("season")
    for _, row in table.iterrows():
        assert row["sim_error_median_km"] == pytest.approx(
            float(live.loc[row["season"], "median_km"])
        )


def test_a_missing_slip_lag_leaves_a_gap_rather_than_a_wrong_number() -> None:
    slip = slip_frame()
    slip = slip[slip["lag_hours"] != 24]
    table = fo.rank_seasons(error_frame(), slip)
    assert table["slip_24h_median_km"].isna().all()


# --------------------------------------------------------------------------
# Output.
# --------------------------------------------------------------------------


def _result() -> fo.FidelityResult:
    return fo.FidelityResult(
        region="wakayama",
        lag_wind=pd.DataFrame({"season": list(SEASON_ORDER), "lag_hours": 24,
                               "median": [1.0, 2.0, 3.0, 4.0]}),
        autocorr=pd.DataFrame({"season": list(SEASON_ORDER), "lag_hours": 24,
                               "plevel": 200.0, "r": [0.5, 0.6, 0.7, 0.8]}),
        decorrelation=pd.DataFrame({"season": list(SEASON_ORDER), "plevel": 200.0,
                                    "decorrelation_hours": [24.0, 48.0, 72.0, 96.0],
                                    "decorrelation_days": [1.0, 2.0, 3.0, 4.0]}),
        direction=pd.DataFrame({"season": list(SEASON_ORDER), "plevel": 200.0,
                                "median": [5.0, 10.0, 20.0, 12.0]}),
        variance=pd.DataFrame([{"scope": "全体", "total": 169.0, "within_day": 10.6,
                                "day_to_day": 81.7, "seasonal": 76.7,
                                "interannual": 4.1, "within_day_fraction": 0.06}]),
        slip=slip_frame(),
        error=error_frame(),
        ranking=fo.rank_seasons(error_frame(), slip_frame()),
        headline={"n_launches": 1051992, "map_factor_gap_km": 3.45},
    )


def test_every_non_empty_table_is_written(tmp_path: Path) -> None:
    written = fo.write_fidelity_tables(_result(), tmp_path)
    names = {p.name for p in written}
    assert "fidelity_ranking_wakayama.csv" in names
    assert "variability_decorrelation_wakayama.csv" in names
    assert all(p.stat().st_size > 0 for p in written)


def test_an_empty_table_is_skipped_rather_than_written_blank(tmp_path: Path) -> None:
    """A zero-row CSV in the output folder looks like a failed run, not a skipped stage."""
    result = _result()
    result.error = pd.DataFrame()
    result.ranking = pd.DataFrame()
    names = {p.name for p in fo.write_fidelity_tables(result, tmp_path)}
    assert "fidelity_error_wakayama.csv" not in names
    assert "variability_decorrelation_wakayama.csv" in names


def test_the_summary_quotes_the_numbers_the_report_needs() -> None:
    text = fo.format_fidelity(_result())
    for needle in ("1/e", "24 時間", "近似誤差", "総合", "診断"):
        assert needle in text
    for season in SEASON_ORDER:
        assert season in text


def test_the_summary_survives_a_variability_only_run() -> None:
    """``--stage variability`` skips the trajectories; the summary must still print."""
    result = _result()
    result.error = pd.DataFrame()
    result.ranking = pd.DataFrame()
    result.headline = {}
    text = fo.format_fidelity(result)
    assert "1/e" in text
    assert "近似誤差" not in text
