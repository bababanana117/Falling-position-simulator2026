"""Shared fixtures.

The important one is :func:`make_fake_jra_dataset`, which reproduces every awkward
property of a real JRA-3Q file -- hyphenated variable name, descending Gaussian
latitude, the exact 45-value pressure axis, the 6-hourly time axis, float32 with
JMA's fill value, and the extra bookkeeping variables that sit alongside the wind
field. Building it locally means the offline test suite needs no network and
raises no licensing question about committing real data.

The one network-marked test ``test_fake_fixture_matches_real_structure`` asserts
that this fake still matches the real thing, so it doubles as a drift alarm if
GDEX ever changes the archive.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from windclim import urls
from windclim.config import FILL_VALUE, LEVELS_HPA

# Real axes, verified against the live file on 2026-09-18.
REAL_LAT_FIRST = 89.7132
REAL_LAT_LAST = -89.7132
REAL_N_LAT = 480
REAL_N_LON = 960
REAL_DLON = 0.375


def gaussian_like_lat(n: int = REAL_N_LAT) -> np.ndarray:
    """Descending latitude axis with the real endpoints.

    A linear ramp, not true Gaussian quadrature points: the tests here only care
    about ordering and endpoints, and nothing in the pipeline assumes the axis is
    evenly spaced.
    """
    return np.linspace(REAL_LAT_FIRST, REAL_LAT_LAST, n)


def make_fake_jra_dataset(
    var: str = "ugrd",
    product: str = "anl_p",
    *,
    n_time: int = 20,
    lat_slice: slice | None = None,
    lon_slice: slice | None = None,
    start: str = "2016-01-01T00",
    seed: int = 0,
    fill_fraction: float = 0.0,
) -> xr.Dataset:
    """A miniature stand-in for one downloaded JRA-3Q file."""
    rng = np.random.default_rng(seed)
    name = urls.nc_varname(var, product)

    lat_full = gaussian_like_lat()
    lon_full = np.arange(REAL_N_LON) * REAL_DLON
    lat = lat_full[lat_slice if lat_slice is not None else slice(111, 160)]
    lon = lon_full[lon_slice if lon_slice is not None else slice(352, 401)]
    levels = np.asarray(LEVELS_HPA, dtype=np.float32)
    time = np.arange(n_time) * np.timedelta64(6, "h") + np.datetime64(start)

    shape = (n_time, levels.size, lat.size, lon.size)
    if var == "hgt":
        # Height falls monotonically with pressure; add a little noise.
        # np.interp needs an ascending xp, and log(pressure) descends with height,
        # so the anchors are given thin-air-first.
        base = np.interp(
            np.log(levels), [np.log(0.01), np.log(1000.0)], [80000.0, 110.0]
        )
        data = base[None, :, None, None] + rng.normal(0.0, 30.0, shape)
    else:
        data = rng.normal(5.0, 15.0, shape)
    data = data.astype(np.float32)

    if fill_fraction > 0.0:
        mask = rng.random(shape) < fill_fraction
        data[mask] = np.float32(FILL_VALUE)

    date_int = np.array(
        [int(str(np.datetime64(t, "h")).replace("-", "").replace("T", "").replace(":", ""))
         for t in time],
        dtype=np.int64,
    )

    ds = xr.Dataset(
        {
            name: (("time", "pressure_level", "lat", "lon"), data),
            # Bookkeeping variables that really are in the files. `weight` is the
            # Gaussian quadrature weight per latitude, which is the correct
            # weighting for an area mean on this grid.
            "weight": (("lat",), np.cos(np.radians(lat)).astype(np.float32)),
            "utc_date_int": (("time",), date_int),
            "utc_date_str": (("time",), np.array([str(t)[:13] for t in time], dtype="U13")),
            "original_number_of_grid_points_per_latitude_circle": (
                ("lat",),
                np.full(lat.size, REAL_N_LON, dtype=np.int32),
            ),
        },
        coords={
            "time": time,
            "pressure_level": levels,
            "lat": lat.astype(np.float32),
            "lon": lon.astype(np.float32),
        },
    )
    ds[name].attrs.update(
        {
            "long_name": {"ugrd": "U-component of wind", "vgrd": "V-component of wind",
                          "hgt": "Geopotential height"}[var],
            "units": {"ugrd": "m s-1", "vgrd": "m s-1", "hgt": "gpm"}[var],
            "_FillValue": np.float32(FILL_VALUE),
            "missing_value": np.float32(FILL_VALUE),
            "data_type": "analysis",
            "time_step": "6-hour",
        }
    )
    ds["pressure_level"].attrs.update({"units": "hPa", "long_name": "isobaric surface"})
    ds["lat"].attrs.update({"units": "degrees_north", "long_name": "gaussian latitude"})
    ds["lon"].attrs.update({"units": "degrees_east", "long_name": "longitude"})
    return ds


@pytest.fixture
def fake_ugrd() -> xr.Dataset:
    return make_fake_jra_dataset("ugrd")


@pytest.fixture
def fake_vgrd() -> xr.Dataset:
    return make_fake_jra_dataset("vgrd", seed=1)


@pytest.fixture
def fake_hgt() -> xr.Dataset:
    return make_fake_jra_dataset("hgt", seed=2)


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch):
    """Make any attempt to open a socket an error.

    Used to prove that ``--dry-run`` really is dry.
    """
    import socket

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("this code path must not open a network connection")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return None


def write_fake_cache(
    root,
    *,
    years,
    months=(1,),
    product: str = "anl_p",
    lat=(41.0, 42.0, 43.0),
    lon=(140.0, 141.0),
    levels=(200.0, 500.0),
    u_of=None,
    v_of=None,
):
    """Write a miniature cache in the layout ``load_month`` expects.

    Files are already normalised (``u``/``v``/``z``, ascending latitude), because
    that is what the fetcher stores. ``u_of``/``v_of`` are called with
    ``(year, month, day, hour)`` so a test can make the value encode its own bin
    and then assert the aggregation put it in the right place.
    """
    import calendar
    from pathlib import Path

    from windclim.config import HGT_TIME_STRIDE
    from windclim.urls import anl_p_chunks

    root = Path(root)
    lat = np.asarray(lat, dtype=np.float32)
    lon = np.asarray(lon, dtype=np.float32)
    levels = np.asarray(levels, dtype=np.float32)
    u_of = u_of or (lambda y, m, d, h: 10.0)
    v_of = v_of or (lambda y, m, d, h: 0.0)

    written = []
    for year in years:
        for month in months:
            for day0, day1 in anl_p_chunks(year, month):
                stamps = [
                    np.datetime64(f"{year:04d}-{month:02d}-{d:02d}T{h:02d}", "ns")
                    for d in range(day0, day1 + 1)
                    for h in (0, 6, 12, 18)
                ]
                nt = len(stamps)
                shape = (nt, levels.size, lat.size, lon.size)
                uu = np.empty(shape, dtype=np.float32)
                vv = np.empty(shape, dtype=np.float32)
                for i, t in enumerate(stamps):
                    py = t.astype("datetime64[s]").item()
                    uu[i] = u_of(py.year, py.month, py.day, py.hour)
                    vv[i] = v_of(py.year, py.month, py.day, py.hour)

                for var, name, data, times in (
                    ("ugrd", "u", uu, stamps),
                    ("vgrd", "v", vv, stamps),
                    ("hgt", "z", None, stamps[::HGT_TIME_STRIDE]),
                ):
                    if name == "z":
                        zshape = (len(times), levels.size, lat.size, lon.size)
                        base = np.interp(
                            np.log(levels), [np.log(0.01), np.log(1000.0)], [80000.0, 110.0]
                        )
                        data = np.broadcast_to(
                            base[None, :, None, None], zshape
                        ).astype(np.float32)
                    ds = xr.Dataset(
                        {
                            name: (("time", "level", "lat", "lon"), data),
                            "weight": (("lat",), np.cos(np.radians(lat)).astype(np.float32)),
                        },
                        coords={
                            "time": np.asarray(times),
                            "level": levels,
                            "lat": lat,
                            "lon": lon,
                        },
                    )
                    folder = root / "raw" / product / var / f"{year:04d}"
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / (
                        f"{var}_{year:04d}{month:02d}{day0:02d}"
                        f"-{year:04d}{month:02d}{day1:02d}_master.nc"
                    )
                    ds.to_netcdf(path)
                    written.append(path)
    assert calendar.monthrange(list(years)[0], list(months)[0])[1] > 0
    return written
