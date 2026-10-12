"""Grid index arithmetic.

The single most dangerous property of the JRA-3Q files is that latitude runs
*descending* (89.71 N first, 89.71 S last). ``ds.sel(lat=slice(30, 48))`` on
such an axis returns an **empty** array without raising, so a wrong-way slice
fails silently and every downstream statistic becomes NaN. Everything here works
for both orderings, and :func:`index_range` is unit-tested against an ascending
axis as well so that property cannot regress.
"""

from __future__ import annotations

import logging

import numpy as np

from .regions import BBox

log = logging.getLogger(__name__)

__all__ = [
    "EARTH_RADIUS_M",
    "assert_box_overlaps",
    "assert_no_dateline_wrap",
    "bbox_slices",
    "haversine_km",
    "index_range",
    "is_descending",
    "nearest_cell",
]

EARTH_RADIUS_M = 6371008.8  # IUGG mean radius


def is_descending(coord: np.ndarray) -> bool:
    coord = np.asarray(coord)
    if coord.size < 2:
        return False
    return bool(coord[0] > coord[-1])


def index_range(coord: np.ndarray, lo: float, hi: float) -> slice:
    """Smallest contiguous ``slice`` of ``coord`` covering ``[lo, hi]``.

    Works for ascending and descending axes alike. The returned slice is always
    in increasing *index* order, which is what ``isel`` wants; it may therefore
    correspond to decreasing coordinate values.

    The endpoints snap to the nearest grid point, so the selection can extend
    slightly beyond the requested range rather than cutting inside it.
    """
    coord = np.asarray(coord, dtype=float)
    if coord.ndim != 1:
        raise ValueError(f"coord must be 1-D, got shape {coord.shape}")
    if lo > hi:
        raise ValueError(f"lo must be <= hi, got {lo} > {hi}")
    i_lo = int(np.argmin(np.abs(coord - lo)))
    i_hi = int(np.argmin(np.abs(coord - hi)))
    first, last = sorted((i_lo, i_hi))
    return slice(first, last + 1)


def assert_no_dateline_wrap(bbox: BBox) -> None:
    """Refuse a box that crosses 0/360 instead of silently selecting the wrong side.

    Both regions of interest sit at 132-150 E, well away from the seam. A box
    that does wrap needs two slices concatenated, which is not implemented --
    better to say so than to return half the data.
    """
    if bbox.west > bbox.east:
        raise NotImplementedError(
            f"bbox crosses the 0/360 seam ({bbox.west}..{bbox.east}); "
            "wrapped selections are not supported"
        )


def assert_box_overlaps(lat: np.ndarray, lon: np.ndarray, bbox: BBox) -> None:
    """Raise if the axes do not intersect the box at all; warn if they only part-cover it.

    :func:`index_range` snaps to the nearest grid point, which is what we want at
    the edges. It degrades badly when the box lies wholly outside the data: asking
    a Hokkaido-only file for Wakayama would quietly return the single nearest row,
    and every statistic computed from it would be real numbers from the wrong
    place. No overlap is therefore an error.

    Partial coverage is only a warning, because a deliberately small extract -- a
    test fixture, a single-column probe -- is a legitimate thing to have.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    dlat = float(np.max(np.abs(np.diff(lat)))) if lat.size > 1 else 0.0
    dlon = float(np.max(np.abs(np.diff(lon)))) if lon.size > 1 else 0.0

    if lat.max() < bbox.south - dlat or lat.min() > bbox.north + dlat:
        raise ValueError(
            f"latitude axis {lat.min():.3f}..{lat.max():.3f} does not overlap "
            f"{bbox.south}..{bbox.north}"
        )
    if lon.max() < bbox.west - dlon or lon.min() > bbox.east + dlon:
        raise ValueError(
            f"longitude axis {lon.min():.3f}..{lon.max():.3f} does not overlap "
            f"{bbox.west}..{bbox.east}"
        )
    if lat.min() > bbox.south + dlat or lat.max() < bbox.north - dlat:
        log.warning(
            "latitude axis %.3f..%.3f only partly covers %.3f..%.3f",
            lat.min(), lat.max(), bbox.south, bbox.north,
        )
    if lon.min() > bbox.west + dlon or lon.max() < bbox.east - dlon:
        log.warning(
            "longitude axis %.3f..%.3f only partly covers %.3f..%.3f",
            lon.min(), lon.max(), bbox.west, bbox.east,
        )


def bbox_slices(
    lat: np.ndarray, lon: np.ndarray, bbox: BBox, *, strict: bool = False
) -> tuple[slice, slice]:
    """``(lat_slice, lon_slice)`` selecting ``bbox`` from the given axes.

    ``strict=True`` first insists the axes actually intersect the box. Use it
    whenever the box is a *sub*-region of what the file should contain; leave it
    off when cutting a box out of a global grid.
    """
    assert_no_dateline_wrap(bbox)
    if strict:
        assert_box_overlaps(lat, lon, bbox)
    return index_range(lat, bbox.south, bbox.north), index_range(lon, bbox.west, bbox.east)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return float(2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a)) / 1000.0)


def nearest_cell(
    lat: np.ndarray, lon: np.ndarray, target_lat: float, target_lon: float
) -> tuple[int, int, float]:
    """Indices of the grid cell nearest a point, plus the offset in km.

    The offset is returned so it can be reported: at 0.375 deg a launch site can
    sit up to ~25 km from its nearest cell centre, and that is a real caveat on
    any "site" table. Values are never interpolated between cells -- interpolating
    a percentile or a covariance is not a valid operation on either.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    i = int(np.argmin(np.abs(lat - target_lat)))
    j = int(np.argmin(np.abs(lon - (target_lon % 360.0))))
    return i, j, haversine_km(target_lat, target_lon, float(lat[i]), float(lon[j]))
