"""The raw-to-canonical boundary, exercised against the synthetic JRA-3Q file."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from windclim.config import FILL_VALUE, kept_levels
from windclim.fetch import normalize as nz
from windclim.regions import MASTER, BBox
from windclim.urls import dap_escaped, nc_varname

from .conftest import make_fake_jra_dataset

# --- finding the variable ----------------------------------------------------


def test_finds_the_hyphenated_name(fake_ugrd: xr.Dataset) -> None:
    assert nz.find_source_var(fake_ugrd, "ugrd", "anl_p") == "ugrd-pres-an-gauss"


def test_finds_the_dap_escaped_name(fake_ugrd: xr.Dataset) -> None:
    escaped = dap_escaped(nc_varname("ugrd", "anl_p"))
    ds = fake_ugrd.rename({nc_varname("ugrd", "anl_p"): escaped})
    assert nz.find_source_var(ds, "ugrd", "anl_p") == escaped


def test_falls_back_to_the_only_four_dimensional_variable(fake_ugrd: xr.Dataset) -> None:
    ds = fake_ugrd.rename({nc_varname("ugrd", "anl_p"): "something-unexpected"})
    assert nz.find_source_var(ds, "ugrd", "anl_p") == "something-unexpected"


def test_raises_when_there_is_no_candidate(fake_ugrd: xr.Dataset) -> None:
    ds = fake_ugrd.drop_vars(nc_varname("ugrd", "anl_p"))
    with pytest.raises(KeyError):
        nz.find_source_var(ds, "ugrd", "anl_p")


# --- normalisation -----------------------------------------------------------


def test_renames_to_the_canonical_short_name(fake_ugrd: xr.Dataset) -> None:
    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    assert "u" in out
    assert not any("-" in str(n) for n in out.variables)


def test_renames_the_level_dimension(fake_ugrd: xr.Dataset) -> None:
    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    assert "level" in out.dims
    assert "pressure_level" not in out.dims


def test_latitude_comes_out_ascending(fake_ugrd: xr.Dataset) -> None:
    assert fake_ugrd["lat"][0] > fake_ugrd["lat"][-1]
    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    assert np.all(np.diff(out["lat"].values) > 0)


def test_flipping_latitude_carries_the_data_with_it(fake_ugrd: xr.Dataset) -> None:
    """Sorting the axis is not enough -- the values must move too."""
    name = nc_varname("ugrd", "anl_p")
    probe_lat = float(fake_ugrd["lat"][3])
    probe_lon = float(fake_ugrd["lon"][5])
    before = float(fake_ugrd[name].isel(time=2, pressure_level=7)[3, 5])

    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    after = float(
        out["u"].isel(time=2, level=7).sel(lat=probe_lat, lon=probe_lon, method="nearest")
    )
    assert after == pytest.approx(before)


def test_keeps_the_gaussian_weights(fake_ugrd: xr.Dataset) -> None:
    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    assert "weight" in out
    assert out["weight"].sizes["lat"] == out.sizes["lat"]


def test_drops_the_bookkeeping_variables(fake_ugrd: xr.Dataset) -> None:
    out = nz.normalize(fake_ugrd, "ugrd", "anl_p")
    assert "utc_date_str" not in out
    assert "original_number_of_grid_points_per_latitude_circle" not in out


def test_fill_values_become_nan() -> None:
    ds = make_fake_jra_dataset("ugrd", fill_fraction=0.02, seed=9)
    out = nz.normalize(ds, "ugrd", "anl_p")
    assert np.isnan(out["u"].values).any()
    assert np.nanmax(np.abs(out["u"].values)) < FILL_VALUE * 0.5


def test_output_is_float32(fake_ugrd: xr.Dataset) -> None:
    assert nz.normalize(fake_ugrd, "ugrd", "anl_p")["u"].dtype == np.float32


def test_height_normalises_to_z(fake_hgt: xr.Dataset) -> None:
    out = nz.normalize(fake_hgt, "hgt", "anl_p")
    assert "z" in out
    assert out["z"].attrs["units"] == "gpm"


# --- validation --------------------------------------------------------------


def _normalised(**kw) -> xr.Dataset:
    return nz.normalize(make_fake_jra_dataset("ugrd", **kw), "ugrd", "anl_p")


def test_a_good_slab_passes_and_reports_its_checks() -> None:
    ds = _normalised()
    checks = nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)
    assert checks["ok"] is True
    assert checks["shape"] == [20, 45, 49, 49]
    assert checks["time_step_hours"] == [6]
    assert checks["nan_fraction"] == pytest.approx(0.0)


def test_wrong_time_count_is_rejected() -> None:
    ds = _normalised(n_time=19)
    with pytest.raises(ValueError, match="20 analyses"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_wrong_level_count_is_rejected() -> None:
    ds = _normalised().isel(level=slice(0, 30))
    with pytest.raises(ValueError, match="levels"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_a_slab_from_the_wrong_place_is_rejected() -> None:
    """The failure this whole function exists for: a plausible but wrong hyperslab."""
    ds = _normalised(lat_slice=slice(300, 349))   # southern hemisphere
    with pytest.raises(ValueError, match="latitudes"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_a_slab_from_the_wrong_longitudes_is_rejected() -> None:
    ds = _normalised(lon_slice=slice(0, 49))      # Greenwich
    with pytest.raises(ValueError, match="longitudes"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_impossible_wind_speeds_are_rejected() -> None:
    ds = _normalised()
    ds["u"][0, 0, 0, 0] = 250.0
    with pytest.raises(ValueError, match="outside"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_an_all_missing_slab_is_rejected() -> None:
    ds = _normalised()
    ds["u"][:] = np.nan
    with pytest.raises(ValueError, match="entirely missing"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_a_mostly_missing_slab_is_rejected() -> None:
    ds = nz.normalize(make_fake_jra_dataset("ugrd", fill_fraction=0.2, seed=3), "ugrd", "anl_p")
    with pytest.raises(ValueError, match="missing"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def test_a_ragged_time_axis_is_rejected() -> None:
    ds = _normalised()
    ds = ds.isel(time=[0, 1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
    with pytest.raises(ValueError, match="evenly spaced"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=18, n_levels=45)


def test_a_degenerate_single_column_slab_is_rejected() -> None:
    ds = _normalised().isel(lat=slice(0, 1), lon=slice(0, 1))
    with pytest.raises(ValueError, match="degenerate"):
        nz.validate_slab(ds, var="ugrd", bbox=MASTER, n_times=20, n_levels=45)


def _normalised_hgt(seed: int) -> xr.Dataset:
    """Height, restricted to the levels the pipeline actually fetches (>= 3 hPa).

    The 45-level archive reaches 0.01 hPa, about 80 km. Nothing here ever asks for
    those, so the validator's 60 km ceiling is a tripwire for the subset we use.
    """
    ds = nz.normalize(make_fake_jra_dataset("hgt", seed=seed), "hgt", "anl_p")
    return ds.sel(level=list(kept_levels()))


def test_a_deep_low_with_negative_geopotential_height_is_accepted() -> None:
    """Found by the January 2016 smoke run: inside a deep low the 1000 hPa surface
    sits below sea level, so -73 gpm is real data, not corruption."""
    ds = _normalised_hgt(11)
    ds["z"][0, -1, 0, 0] = -73.4
    checks = nz.validate_slab(ds, var="hgt", bbox=MASTER, n_times=20, n_levels=38)
    assert checks["ok"] is True
    assert checks["value_range"][0] == pytest.approx(-73.4, abs=0.1)


def test_absurdly_negative_height_is_still_rejected() -> None:
    ds = _normalised_hgt(12)
    ds["z"][0, -1, 0, 0] = -5000.0
    with pytest.raises(nz.SlabValidationError):
        nz.validate_slab(ds, var="hgt", bbox=MASTER, n_times=20, n_levels=38)


def test_validation_errors_are_permanent_and_are_value_errors() -> None:
    """They must not be retried, and they must not be filed as 'file missing'."""
    from windclim.fetch.retry import PermanentFetchError, classify_error

    assert issubclass(nz.SlabValidationError, PermanentFetchError)
    assert issubclass(nz.SlabValidationError, ValueError)
    assert classify_error(nz.SlabValidationError("bad slab")) == "permanent"


def test_a_small_region_inside_master_still_validates() -> None:
    ds = _normalised()
    box = BBox(south=40.0, north=46.5, west=138.0, east=149.0)
    sub = ds.sel(lat=slice(box.south, box.north), lon=slice(box.west, box.east))
    checks = nz.validate_slab(
        sub, var="ugrd", bbox=box, n_times=20, n_levels=45
    )
    assert checks["ok"] is True
