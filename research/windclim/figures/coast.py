"""Coastlines, read from the web app's own GeoJSON.

The alternative would be cartopy, which pulls in GEOS and PROJ and whose
``ax.coastlines()`` *downloads* Natural Earth data at render time. A pipeline
whose whole premise is "offline and archivable" should not acquire a network
dependency inside a plotting call. ``frontend/public/geo/land.json`` is already in
the repository, already used by the optimiser
(``frontend/src/optimizer/landSea.ts``), and dense enough at this scale -- so the
maps and the web app end up drawing the same coastline, which is a small bonus.

For a box a few degrees across, plate carree with the aspect ratio corrected by
``1/cos(lat)`` is honest to a few percent, and no projection choice changes what
the figures say about wind speed and direction.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT
from ..regions import BBox

__all__ = ["LAND_COLOR", "LAND_JSON", "draw_coastline", "load_coastline", "set_geographic_aspect"]

#: A faint land tint. On the drift maps the question is usually "does it come down
#: on land or in the sea", and an unfilled outline makes that surprisingly hard to
#: read at a glance.
LAND_COLOR = "#eceae4"

LAND_JSON = REPO_ROOT / "frontend" / "public" / "geo" / "land.json"


@lru_cache(maxsize=4)
def _rings(path: str) -> tuple[np.ndarray, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[np.ndarray] = []
    for feature in raw.get("features", []):
        geom = feature.get("geometry") or {}
        kind = geom.get("type")
        if kind == "Polygon":
            polys = [geom["coordinates"]]
        elif kind == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        for poly in polys:
            for ring in poly:
                arr = np.asarray(ring, dtype=float)
                if arr.ndim == 2 and arr.shape[0] >= 3:
                    out.append(arr)
    return tuple(out)


def load_coastline(bbox: BBox | None = None, path: Path = LAND_JSON) -> list[np.ndarray]:
    """Coastline rings as ``(n, 2)`` arrays of ``(lon, lat)`` in -180..180.

    Rings that cannot touch ``bbox`` are dropped, which keeps a whole-world file
    from costing anything on a ten-degree map.
    """
    if not Path(path).exists():
        return []
    rings = _rings(str(path))
    if bbox is None:
        return list(rings)
    west = bbox.west - 360.0 if bbox.west > 180.0 else bbox.west
    east = bbox.east - 360.0 if bbox.east > 180.0 else bbox.east
    keep = []
    for ring in rings:
        if (
            ring[:, 0].max() < west
            or ring[:, 0].min() > east
            or ring[:, 1].max() < bbox.south
            or ring[:, 1].min() > bbox.north
        ):
            continue
        keep.append(ring)
    return keep


def draw_coastline(ax, bbox: BBox | None = None, *, color: str = "#52514e",
                   linewidth: float = 0.7, path: Path = LAND_JSON, zorder: int = 5,
                   fill: bool = False, fill_color: str = LAND_COLOR,
                   fill_zorder: int = 0) -> int:
    """Draw the coastline on an existing axes. Returns how many rings were drawn.

    ``fill=True`` also shades the land. Use it where the sea/land distinction is
    the point -- the drift maps -- and leave it off where a filled background
    would fight with the data underneath.
    """
    rings = load_coastline(bbox, path)
    for ring in rings:
        if fill:
            ax.fill(ring[:, 0], ring[:, 1], color=fill_color, zorder=fill_zorder,
                    linewidth=0)
        ax.plot(ring[:, 0], ring[:, 1], color=color, linewidth=linewidth,
                solid_joinstyle="round", zorder=zorder)
    return len(rings)


def set_geographic_aspect(ax, lat_mid: float) -> None:
    """Make one degree of longitude as wide on the page as it is on the ground."""
    ax.set_aspect(1.0 / max(np.cos(np.radians(lat_mid)), 1e-6))
