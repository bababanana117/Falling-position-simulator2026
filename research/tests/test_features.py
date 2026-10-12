"""The one-pass feature table that every later test reduces over."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from windclim.stats import aggregate as agg
from windclim.stats import features as ft
from windclim.stats.timescale import day_of_year_fraction, year_of

YEARS = range(2016, 2019)
CFG = agg.AggregateConfig(years=YEARS, by_hour=False, roses=False, drift=False)
LAT = (41.0, 42.0, 43.0)
LON = (140.0, 141.0)
LEVELS = (10.0, 30.0, 100.0, 200.0, 500.0, 850.0, 1000.0)


def _cache(tmp_path: Path, **kw) -> Path:
    from .conftest import write_fake_cache

    write_fake_cache(
        tmp_path, years=YEARS, months=(1, 2), lat=LAT, lon=LON, levels=LEVELS, **kw
    )
    return tmp_path


def test_one_row_per_analysis(tmp_path: Path) -> None:
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1, 2))
    # Jan x3 = 93 days; Feb = 29 + 28 + 28 = 85 (only 2016 is a leap year).
    assert ds.sizes["time"] == (93 + 85) * 4
    assert ds["dx_east_m"].dims == ("time", "lat", "lon")


def test_times_come_out_sorted(tmp_path: Path) -> None:
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1, 2))
    assert np.all(np.diff(ds["time"].values) > np.timedelta64(0, "ns"))


def test_diagnostic_levels_are_the_nearest_available(tmp_path: Path) -> None:
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1,))
    assert list(ds["plevel"].values) == list(ft.DIAGNOSTIC_LEVELS_HPA)
    assert ds["u"].dims == ("time", "plevel", "lat", "lon")


def test_a_steady_westerly_drifts_east_every_time(tmp_path: Path) -> None:
    root = _cache(tmp_path, u_of=lambda *_: 12.0, v_of=lambda *_: 0.0)
    ds = ft.build_features(root, "hokkaido", CFG, months=(1,))
    assert np.all(ds["dx_east_m"].values > 0)
    assert np.allclose(ds["dy_north_m"].values, 0.0, atol=1.0)


def test_displacement_matches_a_direct_computation(tmp_path: Path) -> None:
    """The feature table must agree with drift.displacements, not approximate it."""
    from windclim.stats.drift import FlightProfile, flight_seconds

    root = _cache(tmp_path, u_of=lambda *_: 10.0, v_of=lambda *_: 0.0)
    ds = ft.build_features(root, "hokkaido", CFG, months=(1,))
    # A uniform 10 m/s wind for the whole column: displacement = speed x time.
    alt = np.linspace(110.0, 80000.0, len(LEVELS))[:, None, None]
    expected = 10.0 * float(flight_seconds(alt, FlightProfile()).squeeze())
    assert float(ds["dx_east_m"].values.mean()) == pytest.approx(expected, rel=0.25)


def test_longitudes_use_the_frontend_convention(tmp_path: Path) -> None:
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1,))
    assert np.all(np.abs(ds["lon"].values) <= 180.0)


def test_flight_parameters_are_recorded(tmp_path: Path) -> None:
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1,))
    assert ds.attrs["flight_burst_altitude_m"] == pytest.approx(30000.0)
    assert ds.attrs["region"] == "hokkaido"


def test_round_trip_through_netcdf(tmp_path: Path) -> None:
    root = _cache(tmp_path)
    out = tmp_path / "f.nc"
    built = ft.build_features(root, "hokkaido", CFG, months=(1,), out_path=out)
    assert out.exists()
    assert not out.with_suffix(".nc.part").exists()
    with ft.open_features(out) as back:
        assert back.sizes["time"] == built.sizes["time"]
        assert np.allclose(back["dx_east_m"].values, built["dx_east_m"].values)


def test_the_time_axis_supports_the_cross_validation_axes(tmp_path: Path) -> None:
    """The whole point of the table: day-of-year and year come straight off it."""
    ds = ft.build_features(_cache(tmp_path), "hokkaido", CFG, months=(1, 2))
    doy = day_of_year_fraction(ds["time"].values)
    years = year_of(ds["time"].values)
    assert doy.min() >= 0.0 and doy.max() < 1.0
    assert set(np.unique(years)) == {2016, 2017, 2018}


def test_a_cache_without_height_is_rejected(tmp_path: Path) -> None:
    """Without geopotential height there are no layer thicknesses, so the flight
    model cannot be integrated -- better to say so than to guess."""
    from .conftest import write_fake_cache

    write_fake_cache(tmp_path, years=YEARS, months=(1,), lat=LAT, lon=LON, levels=LEVELS)
    for p in (tmp_path / "raw" / "anl_p" / "hgt").rglob("*.nc"):
        p.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        ft.build_features(tmp_path, "hokkaido", CFG, months=(1,))


def test_features_path_encodes_region_and_period() -> None:
    p = ft.features_path(Path("/out"), "hokkaido", range(2016, 2026))
    assert p.name == "features_hokkaido_2016-2025.nc"
