"""Terrain and bathymetry for the maps, fetched once and cached.

The coastline in :mod:`windclim.figures.coast` is a line: it says where the
land stops and nothing else. For a map that a reader is meant to locate a
landing point on, the shape of the ground and the depth of the water carry
real information -- a payload that comes down over the Nankai Trough is in
4 km of water, and the figure should say so.

Nothing in the plotting path touches the network. This module downloads a
single raster for a bounding box, writes it to the cache with the same
discipline the wind fetcher uses (temporary file, atomic rename, a JSON
sidecar recording where it came from and when), and every later call reads the
cached file. A figure drawn from a cold cache fails with a message telling you
which command to run rather than quietly reaching out.

Source and licence
------------------
The raster comes from NOAA NCEI's DEM mosaic image service, which serves a
merged land-and-sea elevation model and returns float32 metres, positive up.
The service's own metadata carries **no copyright statement**. Works of the US
federal government are normally in the public domain, and NOAA's bathymetry
products are usually distributed on that basis, but that is a general
expectation rather than something this service asserts. Anyone republishing
these maps should confirm the terms for themselves; the report says the same.

Reading the file needs no new dependency. The service returns a GeoTIFF and
Pillow, already required for the figures, reads float32 TIFF directly. That is
why this is not a rasterio dependency.

The extent is asked for, not assumed
------------------------------------
The service does **not** promise to honour the bounding box. When the box's
aspect ratio does not match the requested pixel dimensions it silently widens
one axis to fit, and returns an image covering more ground than was asked for.
Asking for 134.5-141.5 E at 1440x840 comes back as 133.29-142.71 E.

Assuming the requested box is therefore a way to draw a map whose every
coordinate is wrong by a smooth stretch -- which looks entirely plausible and
puts a launch site on the wrong island. So the fetch asks for the metadata
first (``f=json``), takes the extent the service reports, and stores it in the
sidecar; the tile carries that extent, never the request.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from numpy.typing import NDArray

from ..config import CACHE_ROOT
from ..regions import BBox

__all__ = ["TerrainTile", "fetch_terrain", "load_terrain", "size_for",
           "terrain_path"]

log = logging.getLogger(__name__)

SERVICE = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all"
    "/ImageServer/exportImage"
)
SOURCE_NAME = "NOAA NCEI DEM mosaic (DEM_all)"

#: Plausible elevation range on Earth, used as a gate on what came back. The
#: deepest ocean is about -11 000 m and the highest land about 8 850 m; a tile
#: outside that is not elevation data and must not be drawn as if it were.
MIN_ELEV_M = -11500.0
MAX_ELEV_M = 9000.0


@dataclass(frozen=True)
class TerrainTile:
    """Elevation in metres on a regular lon/lat grid, positive up."""

    elevation: NDArray[np.float32]
    bbox: BBox

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """``(left, right, bottom, top)`` for ``imshow``."""
        return (self.bbox.west, self.bbox.east, self.bbox.south, self.bbox.north)

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape


def size_for(bbox: BBox, *, width: int) -> tuple[int, int]:
    """Pixel dimensions whose aspect ratio matches the box.

    Since the service reshapes the box to fit the image rather than the other
    way round, asking for a matching shape is how you get the box you asked
    for. A mismatch is handled correctly -- the tile records what came back --
    but it returns ground nobody wanted, so the map ends up padded with
    whatever the service added to make the numbers agree.
    """
    span_lon = bbox.east - bbox.west
    span_lat = bbox.north - bbox.south
    if span_lon <= 0 or span_lat <= 0:
        raise ValueError(f"degenerate box: {bbox}")
    return width, max(1, round(width * span_lat / span_lon))


def terrain_path(bbox: BBox, width: int, height: int, cache_root: Path = CACHE_ROOT) -> Path:
    """Where a tile for this box and size is cached."""
    name = (
        f"dem_{bbox.south:.2f}_{bbox.north:.2f}_{bbox.west:.2f}_{bbox.east:.2f}"
        f"_{width}x{height}.tif"
    )
    return Path(cache_root) / "terrain" / name


def fetch_terrain(
    bbox: BBox,
    *,
    width: int = 1400,
    height: int = 1000,
    cache_root: Path = CACHE_ROOT,
    timeout: float = 120.0,
    force: bool = False,
) -> Path:
    """Download the tile if it is not cached, and return its path."""
    path = terrain_path(bbox, width, height, cache_root)
    if path.exists() and not force:
        log.debug("terrain already cached: %s", path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)

    common = {
        "bbox": f"{bbox.west},{bbox.south},{bbox.east},{bbox.north}",
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
    }
    meta_url = f"{SERVICE}?{urlencode(common | {'f': 'json'})}"
    log.info("asking for the terrain extent: %s", meta_url)
    meta = json.loads(_get(meta_url, timeout).decode("utf-8"))
    actual = _extent_of(meta, width, height)
    if not _same_box(actual, bbox):
        log.info(
            "service widened the box: asked %.3f-%.3f E / %.3f-%.3f N, "
            "got %.3f-%.3f E / %.3f-%.3f N",
            bbox.west, bbox.east, bbox.south, bbox.north,
            actual.west, actual.east, actual.south, actual.north,
        )

    url = f"{SERVICE}?{urlencode(common | {'f': 'image'})}"
    payload = _get(url, timeout)
    if len(payload) < 1024:
        raise OSError(f"terrain download returned only {len(payload)} bytes from {url}")

    tmp = path.with_suffix(".tif.part")
    tmp.write_bytes(payload)
    os.replace(tmp, path)
    path.with_suffix(".tif.json").write_text(
        json.dumps({
            "url": url,
            "source": SOURCE_NAME,
            "fetched": datetime.now(UTC).isoformat(timespec="seconds"),
            "requested_bbox": [bbox.south, bbox.north, bbox.west, bbox.east],
            "actual_bbox": [actual.south, actual.north, actual.west, actual.east],
            "size": [width, height],
            "bytes": len(payload),
        }, indent=2),
        encoding="utf-8",
    )
    log.info("wrote %s (%.1f MB)", path, len(payload) / 1e6)
    return path


def _get(url: str, timeout: float) -> bytes:
    req = Request(url, headers={"User-Agent": "windclim/1.0 (research use)"})  # noqa: S310
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _extent_of(meta: dict, width: int, height: int) -> BBox:
    """The box the service says it is returning, not the one we asked for."""
    e = meta.get("extent")
    if not e:
        raise OSError(f"terrain metadata has no extent: {str(meta)[:200]}")
    box = BBox(south=float(e["ymin"]), north=float(e["ymax"]),
               west=float(e["xmin"]), east=float(e["xmax"]))
    got_w, got_h = meta.get("width"), meta.get("height")
    if got_w not in (None, width) or got_h not in (None, height):
        raise OSError(
            f"asked for a {width}x{height} image, service reports {got_w}x{got_h}"
        )
    return box


def _same_box(a: BBox, b: BBox, tol: float = 1e-6) -> bool:
    return all(abs(x - y) < tol for x, y in (
        (a.south, b.south), (a.north, b.north), (a.west, b.west), (a.east, b.east)
    ))


def load_terrain(
    bbox: BBox, *, width: int = 1400, height: int = 1000,
    cache_root: Path = CACHE_ROOT, allow_fetch: bool = False,
) -> TerrainTile:
    """Read the cached tile, validating that it is elevation data.

    ``allow_fetch`` is off by default so a plotting call can never reach the
    network by accident. The error names the command that fixes it.
    """
    path = terrain_path(bbox, width, height, cache_root)
    if not path.exists():
        if not allow_fetch:
            raise FileNotFoundError(
                f"no cached terrain at {path}. Run a command that downloads it "
                f"(e.g. `python -m windclim.cli winter --region wakayama "
                f"--fetch-dem`), or pass allow_fetch=True."
            )
        fetch_terrain(bbox, width=width, height=height, cache_root=cache_root)

    # The tile's real extent lives in the sidecar because the service may have
    # widened the request. Falling back to the request would reintroduce the
    # bug this record exists to prevent, so a missing sidecar is an error.
    side = path.with_suffix(".tif.json")
    if not side.exists():
        raise FileNotFoundError(
            f"{path.name} has no sidecar at {side.name}, so its true extent is "
            "unknown. Delete the tile and re-fetch it."
        )
    record = json.loads(side.read_text(encoding="utf-8"))
    if "actual_bbox" not in record:
        # Sidecars written before the extent was asked for recorded only the
        # requested box. Trusting one would silently restore the old error, so
        # an old tile has to be re-fetched rather than reinterpreted.
        raise ValueError(
            f"{side.name} predates the extent check and records only the "
            "requested box, which the service may not have honoured. "
            f"Delete {path.name} and its sidecar, then re-fetch."
        )
    s_, n_, w_, e_ = record["actual_bbox"]
    actual = BBox(south=s_, north=n_, west=w_, east=e_)

    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as im:
        arr = np.array(im, dtype=np.float32)
    if arr.ndim != 2 or arr.shape != (height, width):
        raise ValueError(f"{path.name}: expected a {height}x{width} array, got {arr.shape}")

    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError(f"{path.name}: every pixel is NaN")
    lo, hi = float(finite.min()), float(finite.max())
    if lo < MIN_ELEV_M or hi > MAX_ELEV_M:
        raise ValueError(
            f"{path.name}: elevations span {lo:.0f} to {hi:.0f} m, outside the "
            f"plausible range {MIN_ELEV_M:.0f} to {MAX_ELEV_M:.0f}. "
            "The service probably returned something other than elevation."
        )
    return TerrainTile(elevation=arr, bbox=actual)
