"""The driver that turns the feature table into the study's tables."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from windclim.outputs import validation_out as vo
from windclim.stats import timescale as ts

from .test_timescale import synthetic_times


def _features(*, seasonal: float, noise: float, seed: int = 0) -> xr.Dataset:
    """A miniature feature table with a controllable seasonal signal."""
    t = synthetic_times(years=np.arange(2016, 2022))
    doy = ts.day_of_year_fraction(t)
    rng = np.random.default_rng(seed)
    n, ny, nx, nl = t.size, 2, 2, 3
    sig = seasonal * np.sin(2 * np.pi * doy)[:, None, None]
    dx = sig * 1000.0 + rng.normal(0, noise * 1000.0, (n, ny, nx))
    dy = rng.normal(0, noise * 1000.0, (n, ny, nx))
    u = np.broadcast_to(sig[:, None], (n, nl, ny, nx)) + rng.normal(0, noise, (n, nl, ny, nx))
    return xr.Dataset(
        {
            "dx_east_m": (("time", "lat", "lon"), dx),
            "dy_north_m": (("time", "lat", "lon"), dy),
            "u": (("time", "plevel", "lat", "lon"), u),
            "v": (("time", "plevel", "lat", "lon"), rng.normal(0, noise, (n, nl, ny, nx))),
        },
        coords={"time": t, "plevel": [200.0, 500.0, 850.0],
                "lat": [42.0, 43.0], "lon": [140.0, 141.0]},
        attrs={"flight_burst_altitude_m": 30000.0},
    )


@pytest.fixture(scope="module")
def result() -> vo.ValidationResult:
    return vo.run_validation(
        _features(seasonal=30.0, noise=5.0), "hokkaido", n_permutations=60
    )


def test_every_table_is_produced(result) -> None:
    assert len(result.bins) == len(ts.DEFAULT_GRANULARITIES_DAYS)
    assert len(result.harmonics) == 27
    assert len(result.by_level) == 3
    assert len(result.by_season) == 4
    assert len(result.variance) == 4


def test_the_placebo_is_reported_and_passes(result) -> None:
    assert result.placebo_ok
    assert abs(result.headline["placebo_skill"]) < vo.PLACEBO_TOLERANCE


def test_a_planted_seasonal_signal_is_found(result) -> None:
    assert result.headline["best_days"] < 365.0
    assert result.headline["skill"] > 0.5


def test_pure_noise_yields_no_skill() -> None:
    """The driver must not manufacture a result from a featureless input."""
    r = vo.run_validation(
        _features(seasonal=0.0, noise=5.0, seed=3), "hokkaido", n_permutations=60
    )
    assert r.headline["skill"] < 0.05
    assert r.headline["best_days"] == 365.0


def test_the_recommended_width_is_never_finer_than_the_argmin(result) -> None:
    """The one-standard-error rule only ever moves the answer coarser."""
    assert result.headline["recommended_days"] >= result.headline["best_days"]


def test_variance_explained_is_consistent_with_the_skill(result) -> None:
    row = result.bins.loc[result.bins["test_rmse_km"].idxmin()]
    assert row["variance_explained"] == pytest.approx(
        1.0 - (1.0 - row["skill"]) ** 2, rel=1e-6
    )


def test_the_week_versus_month_comparison_is_recorded(result) -> None:
    for key in ("week_vs_best_km", "week_vs_best_sigma", "month_vs_best_km",
                "day_vs_best_sigma", "week_adds_to_month_p"):
        assert key in result.headline
        assert np.isfinite(result.headline[key])


def test_tables_are_written(result, tmp_path: Path) -> None:
    written = vo.write_validation_tables(result, tmp_path)
    assert {"timescale_hokkaido.csv", "timescale_harmonic_hokkaido.csv",
            "timescale_by_level_hokkaido.csv", "timescale_by_season_hokkaido.csv",
            "timescale_variance_hokkaido.csv",
            "validation_summary_hokkaido.txt"} <= set(written)
    for p in written.values():
        assert p.stat().st_size > 0


def test_the_summary_leads_with_the_placebo(result) -> None:
    """A result shown without its own sanity check is half a result."""
    text = vo.format_validation(result)
    assert text.index("プラセボ") < text.index("到達できる最小誤差")


def test_the_summary_names_the_recommended_width(result) -> None:
    assert "推奨するビン幅" in vo.format_validation(result)


def test_the_shared_skill_axis_covers_both_regions(tmp_path) -> None:
    """The limit has to clear the larger region, or its bars run off the panel."""
    import pandas as pd

    from windclim.outputs.validation_out import shared_skill_max

    pd.DataFrame({"skill": [0.06, 0.49, 0.22]}).to_csv(
        tmp_path / "timescale_by_level_wakayama.csv", index=False
    )
    pd.DataFrame({"skill": [0.04, 0.24, 0.10]}).to_csv(
        tmp_path / "timescale_by_level_hokkaido.csv", index=False
    )
    limit = shared_skill_max(tmp_path, "by_level")
    assert limit == 50.0
    assert limit >= 100 * 0.49


def test_the_shared_skill_axis_rounds_tightly_below_forty_percent(tmp_path) -> None:
    """A 34 % maximum becomes 35, not 40.

    The season breakdown tops out at Wakayama's 34 %. Rounding that to the next
    multiple of ten would leave a sixth of the panel permanently blank, which
    shortens every bar for no reason. Above 40 % the coarser step costs
    proportionally less and keeps the tick labels round.
    """
    import pandas as pd

    from windclim.outputs.validation_out import shared_skill_max

    pd.DataFrame({"skill": [0.01, 0.34]}).to_csv(
        tmp_path / "timescale_by_season_wakayama.csv", index=False
    )
    assert shared_skill_max(tmp_path, "by_season") == 35.0

    pd.DataFrame({"skill": [0.42]}).to_csv(
        tmp_path / "timescale_by_level_wakayama.csv", index=False
    )
    assert shared_skill_max(tmp_path, "by_level") == 50.0


def test_a_missing_region_is_skipped_rather_than_fatal(tmp_path) -> None:
    """Running one region before the other must still produce a figure."""
    import pandas as pd

    from windclim.outputs.validation_out import shared_skill_max

    assert shared_skill_max(tmp_path, "by_level") is None
    pd.DataFrame({"skill": [0.34]}).to_csv(
        tmp_path / "timescale_by_season_wakayama.csv", index=False
    )
    assert shared_skill_max(tmp_path, "by_season") == 35.0
