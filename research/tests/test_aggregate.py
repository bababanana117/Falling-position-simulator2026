"""End-to-end aggregation over a synthetic cache.

This is the highest-value test in the suite: it is the only one that exercises
loading, region slicing, half binning, every statistic and the assembly of the
output dataset together. Values are chosen so each bin's answer can be worked out
by hand.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from windclim.stats import aggregate as agg
from windclim.stats.circular import uv_to_met_direction
from windclim.timebins import half_of_month

YEARS = range(2016, 2019)          # three years, including the leap year 2016
CFG = agg.AggregateConfig(years=YEARS, by_hour=False)

# Inside the Hokkaido box, so region slicing keeps all of it.
LAT = (41.0, 42.0, 43.0)
LON = (140.0, 141.0)
LEVELS = (200.0, 500.0)


def _cache(tmp_path: Path, **kw) -> Path:
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, lat=LAT, lon=LON, levels=LEVELS, **kw)
    return tmp_path


# --- loading -----------------------------------------------------------------


def test_load_month_reads_every_analysis(tmp_path: Path) -> None:
    root = _cache(tmp_path)
    s = agg.load_month(root, "hokkaido", 1, CFG)
    assert s.n == 3 * 31 * 4                      # three Januaries, 6-hourly
    assert s.u.shape == (s.n, 2, 3, 2)
    assert np.all(np.diff(s.times) >= np.timedelta64(0, "ns"))


def test_load_month_keeps_the_height_subsample(tmp_path: Path) -> None:
    root = _cache(tmp_path)
    s = agg.load_month(root, "hokkaido", 1, CFG)
    assert s.z is not None
    # Five of January's six chunks hold 20 analyses, so a stride of 20 keeps one
    # each; the last runs 26-31 Jan (24 analyses) and keeps two. Seven per year.
    assert s.z.shape[0] == 3 * 7


def test_load_month_keeps_the_gaussian_weights(tmp_path: Path) -> None:
    s = agg.load_month(_cache(tmp_path), "hokkaido", 1, CFG)
    assert s.weight.shape == (3,)


def test_load_month_slices_to_the_region(tmp_path: Path) -> None:
    from .conftest import write_fake_cache

    write_fake_cache(
        tmp_path,
        years=YEARS,
        lat=(33.0, 34.0, 42.0, 43.0),
        lon=(135.0, 136.0),
        levels=LEVELS,
    )
    s = agg.load_month(tmp_path, "wakayama", 1, CFG)
    assert s.lat.tolist() == [33.0, 34.0]


def test_a_region_outside_the_cached_box_is_an_error_not_a_nearest_guess(
    tmp_path: Path,
) -> None:
    """Without this, a Hokkaido-only cache would answer a Wakayama query with the
    nearest Hokkaido row and every number downstream would be real but wrong."""
    root = _cache(tmp_path)          # latitudes 41-43 N only
    with pytest.raises(ValueError, match="does not overlap"):
        agg.load_month(root, "wakayama", 1, CFG)


def test_missing_cache_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="windclim fetch"):
        agg.load_month(tmp_path, "hokkaido", 1, CFG)


# --- binning -----------------------------------------------------------------


def test_sample_counts_per_half(tmp_path: Path) -> None:
    """H1 is always 15 days; January's H2 is 16. Three years, four analyses a day."""
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, CFG), CFG)
    n = ds["n"].values
    assert ds.sizes["bin"] == 2
    assert np.all(n[0] == 3 * 15 * 4)
    assert np.all(n[1] == 3 * 16 * 4)


def test_february_second_half_is_shorter_and_leap_aware(tmp_path: Path) -> None:
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, months=(2,), lat=LAT, lon=LON, levels=LEVELS)
    ds = agg.aggregate_month(agg.load_month(tmp_path, "hokkaido", 2, CFG), CFG)
    # H2 runs 16 Feb to the end: 14 days in leap 2016, 13 in 2017 and 2018.
    assert np.all(ds["n"].values[1] == (14 + 13 + 13) * 4)
    assert np.all(ds["n"].values[0] == 3 * 15 * 4)


def test_every_sample_lands_in_the_half_its_date_says(tmp_path: Path) -> None:
    """The value encodes its own half, so a mis-binned sample shows up as a mean
    that is not a whole number."""
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 10.0 * half_of_month(d))
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.allclose(ds["u_mean"].values[:, 0, 0, 0], [10.0, 20.0])
    assert np.allclose(ds["u_var"].values, 0.0, atol=1e-6)


# --- statistics --------------------------------------------------------------


def test_a_steady_westerly_gives_the_textbook_answers(tmp_path: Path) -> None:
    root = _cache(tmp_path, u_of=lambda *_: 10.0, v_of=lambda *_: 0.0)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.allclose(ds["speed_mean"].values, 10.0)
    assert np.allclose(ds["speed_vector_mean"].values, 10.0)
    assert np.allclose(ds["constancy"].values, 1.0)
    assert np.allclose(ds["speed_p50"].values, 10.0)
    assert np.allclose(ds["speed_max"].values, 10.0)
    assert np.allclose(ds["speed_std"].values, 0.0, atol=1e-5)
    d = uv_to_met_direction(ds["u_mean"].values, ds["v_mean"].values)
    assert np.allclose(d, 270.0)


def test_a_wind_that_reverses_every_analysis_has_zero_constancy(tmp_path: Path) -> None:
    """The stratospheric-reversal case in miniature: strong wind, no net transport."""
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 10.0 if h in (0, 12) else -10.0)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.allclose(ds["speed_mean"].values, 10.0)
    assert np.allclose(ds["speed_vector_mean"].values, 0.0, atol=1e-5)
    assert np.allclose(ds["constancy"].values, 0.0, atol=1e-5)


def test_vector_mean_never_exceeds_scalar_mean(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    root = _cache(
        tmp_path,
        u_of=lambda *_: float(rng.normal(8, 20)),
        v_of=lambda *_: float(rng.normal(-3, 15)),
    )
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.all(
        ds["speed_vector_mean"].values <= ds["speed_mean"].values + 1e-4
    )


def test_percentiles_match_a_hand_computation(tmp_path: Path) -> None:
    """Speed alternates between 4 and 16 in a 3:1 ratio, so p50 = 4 and p90 = 16."""
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 16.0 if h == 18 else 4.0)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.allclose(ds["speed_p50"].values, 4.0)
    assert np.allclose(ds["speed_p90"].values, 16.0)
    assert np.allclose(ds["speed_mean"].values, 7.0)


def test_exceedance_frequency_matches_the_duty_cycle(tmp_path: Path) -> None:
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 25.0 if h == 0 else 5.0)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.allclose(ds["exceed_gt20"].values, 0.25)
    assert np.allclose(ds["exceed_gt30"].values, 0.0)


def test_effective_sample_size_is_far_below_the_raw_count(tmp_path: Path) -> None:
    """A slowly varying wind: 84 analyses carry nowhere near 84 independent values."""
    root = _cache(
        tmp_path, u_of=lambda y, m, d, h: 20.0 + 10.0 * np.sin((d * 4 + h / 6) / 8.0)
    )
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.all(ds["lag1_autocorr"].values > 0.8)
    assert np.all(ds["n_eff"].values < ds["n"].values / 4)
    assert np.all(ds["n_eff"].values >= 1.0)


def test_white_noise_keeps_most_of_its_effective_samples(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    root = _cache(tmp_path, u_of=lambda *_: float(rng.normal(0, 10)))
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, CFG), CFG)
    assert np.all(np.abs(ds["lag1_autocorr"].values) < 0.3)
    assert np.all(ds["n_eff"].values > ds["n"].values * 0.4)


# --- altitude and coordinates -----------------------------------------------


def test_height_becomes_a_geometric_altitude(tmp_path: Path) -> None:
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, CFG), CFG)
    assert "z_mean_gpm" in ds
    assert "alt_geom_mean_m" in ds
    # 200 hPa sits higher than 500 hPa, and geometric exceeds geopotential.
    alt = ds["alt_geom_mean_m"].values
    assert np.all(alt[:, 0] > alt[:, 1])
    assert np.all(alt > ds["z_mean_gpm"].values)


def test_longitudes_come_out_in_the_frontend_convention(tmp_path: Path) -> None:
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, CFG), CFG)
    assert np.all(ds["lon"].values <= 180.0)
    assert np.all(ds["lat"].values[:-1] < ds["lat"].values[1:])


def test_no_direction_variable_is_stored(tmp_path: Path) -> None:
    """Directions are derived at export from the moments, never accumulated."""
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, CFG), CFG)
    assert not [v for v in ds.data_vars if "dir" in str(v)]


# --- by-hour product ---------------------------------------------------------


def test_hour_product_splits_the_samples_four_ways(tmp_path: Path) -> None:
    cfg = agg.AggregateConfig(years=YEARS, by_hour=True, hour_product_min_hpa=300.0)
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, cfg), cfg)
    assert ds.sizes["hour"] == 4
    assert np.all(ds["hr_n"].values[0] == 3 * 15)
    assert list(ds["hour_jst"].values) == [9, 15, 21, 3]


def test_hour_product_only_covers_the_lower_troposphere(tmp_path: Path) -> None:
    cfg = agg.AggregateConfig(years=YEARS, by_hour=True, hour_product_min_hpa=300.0)
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, cfg), cfg)
    assert list(ds["level_low"].values) == [500.0]     # 200 hPa is excluded


def test_hour_product_sees_a_diurnal_cycle_the_main_product_averages_away(
    tmp_path: Path,
) -> None:
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 20.0 if h == 6 else 2.0)
    cfg = agg.AggregateConfig(years=YEARS, by_hour=True)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, cfg), cfg)
    by_hour = ds["hr_speed_mean"].values[0, :, 0, 0, 0]
    assert np.allclose(by_hour, [2.0, 20.0, 2.0, 2.0])
    assert np.allclose(ds["speed_mean"].values[0, 1, 0, 0], 6.5)


# --- full-year assembly ------------------------------------------------------


def test_aggregate_all_assembles_the_month_dimension(tmp_path: Path) -> None:
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, months=(1, 2), lat=LAT, lon=LON, levels=LEVELS)
    ds = agg.aggregate_all(tmp_path, "hokkaido", CFG, months=(1, 2))
    core = {k: ds.sizes[k] for k in ("month", "bin", "level", "lat", "lon")}
    assert core == {"month": 2, "bin": 2, "level": 2, "lat": 3, "lon": 2}
    assert list(ds["month"].values) == [1, 2]


def test_half_end_day_records_the_leap_year_variation(tmp_path: Path) -> None:
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, months=(1, 2), lat=LAT, lon=LON, levels=LEVELS)
    ds = agg.aggregate_all(tmp_path, "hokkaido", CFG, months=(1, 2))
    assert ds["bin_end_day"].sel(month=1).values.tolist() == [15, 31]
    assert ds["bin_end_day"].sel(month=2).values.tolist() == [15, 29]


def test_intermediate_files_are_written(tmp_path: Path) -> None:
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, lat=LAT, lon=LON, levels=LEVELS)
    inter = tmp_path / "inter"
    agg.aggregate_all(tmp_path, "hokkaido", CFG, months=(1,), intermediate_dir=inter)
    assert (inter / "hokkaido_01.nc").exists()


def test_jst_convention_moves_the_boundary_sample(tmp_path: Path) -> None:
    """18 UTC on the 15th is the 16th in JST, so it moves from H1 to H2."""
    root = _cache(tmp_path)
    utc = agg.AggregateConfig(years=YEARS, date_convention="utc", by_hour=False)
    jst = agg.AggregateConfig(years=YEARS, date_convention="jst", by_hour=False)
    n_utc = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, utc), utc)["n"].values
    n_jst = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, jst), jst)["n"].values
    assert np.all(n_utc[0] == 3 * 15 * 4)
    assert np.all(n_jst[0] == 3 * 15 * 4 - 3)   # one analysis per year leaves H1
    # H2 gains those three and loses three of its own: 18 UTC on 31 January is
    # 1 February in JST, so it leaves the month altogether. The two cancel.
    assert np.all(n_jst[1] == 3 * 16 * 4)
    assert np.all(n_jst.sum(axis=0) == n_utc.sum(axis=0) - 3)


# --- wind roses --------------------------------------------------------------


def test_roses_have_sixteen_sectors_and_six_speed_classes(tmp_path: Path) -> None:
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, cfg), cfg)
    assert ds["rose_counts"].sizes == {"bin": 2, "level": 2, "sector": 16, "speed_class": 6}


def test_rose_counts_add_up_to_the_sample_count(tmp_path: Path) -> None:
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, cfg), cfg)
    total = ds["rose_counts"].sum(("sector", "speed_class")).values
    assert np.all(total == ds["n"].values[:, :, 0, 0])


def test_a_steady_westerly_lands_in_one_sector(tmp_path: Path) -> None:
    """u = +10 is a wind from 270 deg, which is sector 12 of 16 (270/22.5)."""
    root = _cache(tmp_path, u_of=lambda *_: 10.0, v_of=lambda *_: 0.0)
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, cfg), cfg)
    counts = ds["rose_counts"].values[0, 0]
    assert counts[12].sum() == counts.sum()
    assert float(ds["sector_deg"].values[12]) == pytest.approx(270.0)


def test_rose_speed_classes_bin_as_documented(tmp_path: Path) -> None:
    """Edges are 0, 5, 10, 20, 30, 50: a 25 m/s wind belongs to class 3."""
    root = _cache(tmp_path, u_of=lambda *_: 25.0, v_of=lambda *_: 0.0)
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, cfg), cfg)
    counts = ds["rose_counts"].values[0, 0]
    assert counts[:, 3].sum() == counts.sum()


def test_a_bimodal_wind_shows_two_lobes_where_the_mean_shows_nothing(
    tmp_path: Path,
) -> None:
    """The reversal case: the vector mean is zero and the rose is the only honest
    display of what actually happened."""
    root = _cache(tmp_path, u_of=lambda y, m, d, h: 15.0 if h in (0, 6) else -15.0)
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(root, "hokkaido", 1, cfg), cfg)
    counts = ds["rose_counts"].values[0, 0].sum(axis=1)
    populated = np.flatnonzero(counts)
    assert populated.tolist() == [4, 12]              # from 90 deg and from 270 deg
    assert np.allclose(ds["speed_vector_mean"].values[0, 0], 0.0, atol=1e-5)


def test_rose_cell_position_is_recorded(tmp_path: Path) -> None:
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=True)
    ds = agg.aggregate_month(agg.load_month(_cache(tmp_path), "hokkaido", 1, cfg), cfg)
    assert ds.attrs["rose_cell_lat"] == pytest.approx(42.0)
    assert ds.attrs["rose_cell_lon"] == pytest.approx(141.0)
