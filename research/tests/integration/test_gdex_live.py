"""Tests that touch the live GDEX servers.

Excluded by default (``addopts = -m 'not network'``); run them with
``pytest -m network``. They exist as a drift alarm: every constant this package
hard-codes about the archive is checked against the real thing, so if GDEX
renames a variable or changes the level list, one of these fails instead of 2160
downloads silently returning the wrong shape.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from windclim import urls
from windclim.config import LEVELS_HPA, kept_levels
from windclim.fetch.cache import FetchTask
from windclim.fetch.normalize import CANON, normalize, validate_slab
from windclim.fetch.opendap import open_and_subset
from windclim.regions import MASTER

pytestmark = pytest.mark.network

URL_2016_01 = urls.anl_p_url("ugrd", 2016, 1, 1, 5)


@pytest.fixture(scope="module")
def live() -> xr.Dataset:
    ds = xr.open_dataset(URL_2016_01, engine="netcdf4", decode_times=True)
    yield ds
    ds.close()


def test_the_archive_is_reachable_anonymously(live: xr.Dataset) -> None:
    assert live.sizes["time"] == 20


def test_the_hyphenated_variable_name_is_still_right(live: xr.Dataset) -> None:
    assert urls.nc_varname("ugrd", "anl_p") in live.variables


def test_latitude_still_runs_north_to_south(live: xr.Dataset) -> None:
    """The whole reason grid.index_range exists. If this ever flips, several
    assumptions downstream need revisiting rather than silently adapting."""
    lat = live["lat"].values
    assert lat[0] > lat[-1]
    assert lat[0] == pytest.approx(89.7132, abs=1e-3)
    assert lat.size == 480


def test_the_longitude_axis_is_zero_to_360(live: xr.Dataset) -> None:
    lon = live["lon"].values
    assert lon[0] == pytest.approx(0.0)
    assert lon[-1] == pytest.approx(359.625, abs=1e-3)
    assert lon.size == 960


def test_the_pressure_levels_match_the_hard_coded_list(live: xr.Dataset) -> None:
    assert np.allclose(live["pressure_level"].values, np.asarray(LEVELS_HPA))


def test_the_data_is_unpacked_float32_not_scaled_integers(live: xr.Dataset) -> None:
    """The transfer estimate assumes float32 on the wire. If packing appears, the
    volume halves and the sizing comment in urls.py needs updating."""
    enc = live[urls.nc_varname("ugrd", "anl_p")].encoding
    assert "scale_factor" not in enc
    assert "add_offset" not in enc


def test_the_gaussian_weights_are_present(live: xr.Dataset) -> None:
    """Used for the area-weighted regional means."""
    assert "weight" in live.variables
    assert live["weight"].sizes["lat"] == 480


def test_a_small_hyperslab_comes_back_sane(live: xr.Dataset) -> None:
    sub = (
        live[urls.nc_varname("ugrd", "anl_p")]
        .isel(time=0, pressure_level=22, lat=slice(111, 114), lon=slice(352, 355))
        .values
    )
    assert sub.shape == (3, 3)
    assert np.isfinite(sub).all()
    assert np.abs(sub).max() < 150.0


def test_a_full_task_fetch_passes_its_own_validation() -> None:
    task = FetchTask(var="ugrd", product="anl_p", year=2016, month=1, day0=1, day1=5)
    ds, checks = open_and_subset(task)
    assert checks["ok"] is True
    assert checks["shape"] == [20, len(kept_levels()), 49, 49]
    assert np.all(np.diff(ds["lat"].values) > 0)
    assert "u" in ds


@pytest.mark.parametrize(
    ("year", "month", "expected_last_chunk"),
    [(2016, 2, (26, 29)), (2017, 2, (26, 28)), (2019, 4, (26, 30)), (2025, 12, (26, 31))],
)
def test_constructed_filenames_exist_in_the_catalog(
    year: int, month: int, expected_last_chunk: tuple[int, int]
) -> None:
    import httpx

    assert urls.anl_p_chunks(year, month)[-1] == expected_last_chunk
    xml = httpx.get(urls.catalog_url("anl_p", year, month), timeout=60.0).text
    for _, url in urls.month_urls("ugrd", "anl_p", year, month):
        assert url.rsplit("/", 1)[-1] in xml


def test_december_2025_is_complete() -> None:
    """The period 2016-2025 depends on the last month being fully populated."""
    import httpx

    xml = httpx.get(urls.catalog_url("anl_p", 2025, 12), timeout=60.0).text
    for var in ("ugrd", "vgrd", "hgt"):
        for _, url in urls.month_urls(var, "anl_p", 2025, 12):
            assert url.rsplit("/", 1)[-1] in xml


def test_the_synthetic_fixture_still_matches_the_real_file(live: xr.Dataset) -> None:
    """The drift alarm. Every offline test leans on the fake dataset, so the fake
    has to keep matching the real archive's shape, ordering and naming."""
    from ..conftest import make_fake_jra_dataset

    fake = make_fake_jra_dataset("ugrd", "anl_p")
    name = urls.nc_varname("ugrd", "anl_p")

    assert set(fake[name].dims) == set(live[name].dims)
    assert fake[name].dims == live[name].dims
    assert fake[name].dtype == live[name].dtype
    assert fake["lat"].values[0] > fake["lat"].values[-1]
    assert np.allclose(fake["pressure_level"].values, live["pressure_level"].values)
    for key in ("units", "long_name"):
        assert fake[name].attrs[key] == live[name].attrs[key]
    for extra in ("weight", "utc_date_int", "utc_date_str"):
        assert extra in live.variables, extra
        assert extra in fake.variables, extra


def test_normalisation_and_validation_run_on_real_data(live: xr.Dataset) -> None:
    sub = live.isel(
        time=slice(0, 2), lat=slice(111, 160), lon=slice(352, 401),
        pressure_level=[i for i, p in enumerate(LEVELS_HPA) if p >= 3.0],
    ).load()
    out = normalize(sub, "ugrd", "anl_p")
    checks = validate_slab(
        out, var="ugrd", bbox=MASTER, n_times=2, n_levels=len(kept_levels())
    )
    assert checks["ok"] is True
    assert CANON["ugrd"] in out
