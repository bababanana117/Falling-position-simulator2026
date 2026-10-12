"""Grid index arithmetic, with the descending-latitude trap pinned down."""

from __future__ import annotations

import numpy as np
import pytest

from windclim import grid
from windclim.regions import (
    FETCH_BOXES,
    MASTER,
    REGIONS,
    SOUTHWEST,
    BBox,
    cache_box_name,
    to_0_360,
    to_signed_lon,
)

# The real JRA-3Q latitude axis: Gaussian, descending, 480 points.
DESC_LAT = np.linspace(89.7132, -89.7132, 480)
ASC_LAT = DESC_LAT[::-1].copy()
LON = np.arange(960) * 0.375


# --- index_range -------------------------------------------------------------


def test_index_range_on_descending_axis_is_not_empty() -> None:
    """The bug this guards: sel(lat=slice(30, 48)) on a descending axis is empty."""
    sl = grid.index_range(DESC_LAT, 30.0, 48.0)
    picked = DESC_LAT[sl]
    assert picked.size > 0
    assert picked.min() <= 30.2
    assert picked.max() >= 47.8


def test_index_range_on_ascending_axis_gives_the_same_values() -> None:
    desc = np.sort(DESC_LAT[grid.index_range(DESC_LAT, 30.0, 48.0)])
    asc = np.sort(ASC_LAT[grid.index_range(ASC_LAT, 30.0, 48.0)])
    assert np.allclose(desc, asc)


def test_index_range_is_always_increasing_in_index() -> None:
    for coord in (DESC_LAT, ASC_LAT):
        sl = grid.index_range(coord, 30.0, 48.0)
        assert sl.start < sl.stop


def test_index_range_covers_the_requested_span() -> None:
    """Endpoints snap outward to the nearest grid point, never inward."""
    sl = grid.index_range(LON, 132.0, 150.0)
    picked = LON[sl]
    assert picked[0] <= 132.0 + 0.375 / 2
    assert picked[-1] >= 150.0 - 0.375 / 2


def test_index_range_single_point() -> None:
    sl = grid.index_range(LON, 135.0, 135.0)
    assert sl.stop - sl.start == 1
    assert LON[sl][0] == pytest.approx(135.0)


def test_index_range_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError):
        grid.index_range(DESC_LAT, 48.0, 30.0)


def test_index_range_rejects_2d_input() -> None:
    with pytest.raises(ValueError):
        grid.index_range(np.zeros((2, 2)), 0.0, 1.0)


def test_is_descending() -> None:
    assert grid.is_descending(DESC_LAT)
    assert not grid.is_descending(ASC_LAT)


# --- dateline guard ----------------------------------------------------------


def test_assert_no_dateline_wrap_passes_for_our_regions() -> None:
    grid.assert_no_dateline_wrap(MASTER)
    for box in REGIONS.values():
        grid.assert_no_dateline_wrap(box)


def test_wrapped_box_cannot_even_be_constructed() -> None:
    """BBox itself rejects west > east, so the seam case is caught earlier."""
    with pytest.raises(ValueError):
        BBox(south=30.0, north=40.0, west=350.0, east=10.0)


# --- bbox_slices -------------------------------------------------------------


def test_bbox_slices_master_matches_the_live_probe() -> None:
    """Indices measured against the real file on 2026-09-18."""
    lat_sl, lon_sl = grid.bbox_slices(DESC_LAT, LON, MASTER)
    assert (lat_sl.start, lat_sl.stop) == (111, 160)
    assert (lon_sl.start, lon_sl.stop) == (352, 401)
    assert DESC_LAT[lat_sl].size == 49
    assert LON[lon_sl].size == 49


def test_master_stays_inside_one_chunk_quadrant() -> None:
    """anl_p is chunked (1, 23, 240, 480): staying inside one spatial quadrant
    means each timestep costs the server two chunks, not eight."""
    lat_sl, lon_sl = grid.bbox_slices(DESC_LAT, LON, MASTER)
    assert lat_sl.stop <= 240
    assert lon_sl.stop <= 480


def test_regions_are_smaller_than_their_cache_box() -> None:
    for name, box in REGIONS.items():
        cache = FETCH_BOXES[cache_box_name(name)]
        m_lat, m_lon = grid.bbox_slices(DESC_LAT, LON, cache)
        r_lat, r_lon = grid.bbox_slices(DESC_LAT, LON, box)
        assert m_lat.start <= r_lat.start and r_lat.stop <= m_lat.stop
        assert m_lon.start <= r_lon.start and r_lon.stop <= m_lon.stop


def test_southwest_box_stays_inside_one_chunk_quadrant() -> None:
    lat_sl, lon_sl = grid.bbox_slices(DESC_LAT, LON, SOUTHWEST)
    assert lat_sl.stop <= 240
    assert lon_sl.stop <= 480


# --- distances and nearest cell ---------------------------------------------


def test_haversine_zero_distance() -> None:
    assert grid.haversine_km(43.0, 143.0, 43.0, 143.0) == pytest.approx(0.0)


def test_haversine_one_degree_of_latitude() -> None:
    assert grid.haversine_km(43.0, 143.0, 44.0, 143.0) == pytest.approx(111.2, abs=0.5)


def test_nearest_cell_for_the_voising_launch_site() -> None:
    """VOISING, Hokkaido, the reference site in frontend/public/sites.json."""
    i, j, off = grid.nearest_cell(DESC_LAT, LON, 42.182306, 142.850972)
    assert DESC_LAT[i] == pytest.approx(42.182306, abs=0.2)
    assert LON[j] == pytest.approx(142.850972, abs=0.2)
    # At 0.375 deg a site can sit up to ~25 km from a cell centre; this one is
    # close, and the offset is reported so the caveat travels with the number.
    assert off < 25.0
    assert off == pytest.approx(4.7, abs=1.0)


def test_nearest_cell_accepts_signed_longitude() -> None:
    i1, j1, _ = grid.nearest_cell(DESC_LAT, LON, 34.0, 135.5)
    i2, j2, _ = grid.nearest_cell(DESC_LAT, LON, 34.0, 135.5 - 360.0)
    assert (i1, j1) == (i2, j2)


# --- longitude conventions ---------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [(143.4, 143.4), (-120.0, 240.0), (360.0, 0.0)])
def test_to_0_360(raw: float, expected: float) -> None:
    assert to_0_360(raw) == pytest.approx(expected)


@pytest.mark.parametrize(("raw", "expected"), [(143.4, 143.4), (240.0, -120.0), (180.0, 180.0)])
def test_to_signed_lon(raw: float, expected: float) -> None:
    assert to_signed_lon(raw) == pytest.approx(expected)


def test_longitude_round_trip() -> None:
    for lon in (0.0, 45.0, 143.4405, 179.9, 180.0, 270.0, 359.625):
        assert to_0_360(to_signed_lon(lon)) == pytest.approx(lon)
