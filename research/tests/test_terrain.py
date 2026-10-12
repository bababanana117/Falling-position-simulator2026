"""The terrain tile: caching, validation and the map it feeds.

The fetch itself needs the network and is marked accordingly. Everything
below it -- the cache path, the guard that stops a plotting call reaching out,
and the check that what came back is actually elevation -- is tested offline
against a written file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from windclim.fetch import terrain
from windclim.regions import BBox

BOX = BBox(south=32.0, north=36.0, west=134.0, east=140.0)


def _write_tile(root: Path, box: BBox, w: int, h: int, values=None,
                actual: BBox | None = None) -> Path:
    """A cached tile plus the sidecar a real fetch would have left beside it.

    ``actual`` is the extent the service reported, which is the one the tile
    is drawn at; it defaults to the requested box, the case where the service
    honoured the request.
    """
    import json

    from PIL import Image

    path = terrain.terrain_path(box, w, h, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if values is None:
        values = np.linspace(-6000.0, 3000.0, w * h, dtype=np.float32).reshape(h, w)
    Image.fromarray(np.asarray(values, dtype=np.float32), mode="F").save(path)
    a = actual or box
    path.with_suffix(".tif.json").write_text(json.dumps({
        "source": terrain.SOURCE_NAME,
        "requested_bbox": [box.south, box.north, box.west, box.east],
        "actual_bbox": [a.south, a.north, a.west, a.east],
        "size": [w, h],
    }))
    return path


def test_the_cache_path_encodes_the_box_and_the_size(tmp_path: Path) -> None:
    """Two different boxes must not share a file, or one would serve the other."""
    a = terrain.terrain_path(BOX, 100, 80, tmp_path)
    b = terrain.terrain_path(BBox(south=40.0, north=46.0, west=138.0, east=149.0),
                             100, 80, tmp_path)
    c = terrain.terrain_path(BOX, 200, 80, tmp_path)
    assert a != b
    assert a != c
    assert a.parent.name == "terrain"


def test_loading_without_a_cache_refuses_rather_than_downloading(tmp_path: Path) -> None:
    """A figure must never acquire a network dependency by being drawn."""
    with pytest.raises(FileNotFoundError, match="--fetch-dem"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_a_cached_tile_loads_with_the_right_extent(tmp_path: Path) -> None:
    _write_tile(tmp_path, BOX, 100, 80)
    tile = terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)
    assert tile.shape == (80, 100)
    assert tile.extent == (BOX.west, BOX.east, BOX.south, BOX.north)
    assert tile.elevation.dtype == np.float32


def test_a_cache_file_that_does_not_match_its_name_is_an_error(tmp_path: Path) -> None:
    """The size is in the file name, so a mismatch means the cache is corrupt.

    A truncated download or a hand-edited file would otherwise be drawn as a
    map of the wrong area.
    """
    _write_tile(tmp_path, BOX, 100, 80, values=np.zeros((40, 50), dtype=np.float32))
    with pytest.raises(ValueError, match="expected a 80x100"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_values_outside_the_plausible_range_are_rejected(tmp_path: Path) -> None:
    """The service can return something that is not elevation.

    Drawing that as terrain would produce a map that looks fine and is wrong,
    which is worse than failing, so the range is checked on every load.
    """
    bad = np.full((80, 100), 1e6, dtype=np.float32)
    _write_tile(tmp_path, BOX, 100, 80, bad)
    with pytest.raises(ValueError, match="plausible range"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_an_all_nan_tile_is_rejected(tmp_path: Path) -> None:
    _write_tile(tmp_path, BOX, 100, 80, np.full((80, 100), np.nan, dtype=np.float32))
    with pytest.raises(ValueError, match="every pixel is NaN"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_the_map_figure_draws_every_cloud_in_its_own_colour(tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from windclim.figures import plots, style
    from windclim.figures.windsample_fig import fig_landing_map

    style.apply_style(japanese=True)
    _write_tile(tmp_path, BOX, 120, 90)
    tile = terrain.load_terrain(BOX, width=120, height=90, cache_root=tmp_path)
    rng = np.random.default_rng(0)
    clouds = {
        "観測": (rng.normal(250, 50, 300), rng.normal(0, 45, 300)),
        "モデル": (rng.normal(250, 45, 300), rng.normal(0, 40, 300)),
        "＋機体": (rng.normal(250, 48, 300), rng.normal(0, 42, 300)),
    }
    fig = fig_landing_map(tile, clouds, 33.9, 135.38, "和歌山")
    colours = {
        tuple(np.round(c.get_facecolor()[0][:3], 3))
        for c in fig.axes[0].collections if len(c.get_offsets()) > 10
    }
    assert len(colours) == len(clouds), "two clouds share a colour"
    png, _ = plots.save(fig, tmp_path, "A2", "map")
    assert png.stat().st_size > 50000


def test_too_many_clouds_is_an_error_not_a_colour_collision(tmp_path: Path) -> None:
    """Cycling the palette would silently give two scenarios the same hue."""
    import matplotlib

    matplotlib.use("Agg")
    from windclim.figures.windsample_fig import _OVER_MAP, fig_landing_map

    _write_tile(tmp_path, BOX, 60, 40)
    tile = terrain.load_terrain(BOX, width=60, height=40, cache_root=tmp_path)
    clouds = {f"c{i}": (np.zeros(5), np.zeros(5)) for i in range(len(_OVER_MAP) + 1)}
    with pytest.raises(ValueError, match="distinguishable colours"):
        fig_landing_map(tile, clouds, 33.9, 135.38)


def test_the_extent_comes_from_the_service_not_the_request() -> None:
    """The service may widen the box, and the tile has to say so.

    ``exportImage`` adjusts the bounding box to match the requested image
    aspect ratio. Asking for 7 degrees of longitude in a 1440x840 image gets
    9.43 degrees back. Reading the request instead of the reply places every
    pixel wrong by a smooth stretch, which draws a plausible map of nowhere.
    """
    asked = BBox(south=31.1, north=36.6, west=134.5, east=141.5)
    reply = {"extent": {"xmin": 133.2857, "ymin": 31.1,
                        "xmax": 142.7143, "ymax": 36.6},
             "width": 1440, "height": 840}
    got = terrain._extent_of(reply, 1440, 840)
    assert got.west == pytest.approx(133.2857)
    assert got.east == pytest.approx(142.7143)
    assert got.west < asked.west and got.east > asked.east
    # The returned box has the image's aspect ratio, which is the whole cause.
    assert (got.east - got.west) / (got.north - got.south) == pytest.approx(
        1440 / 840, rel=1e-3
    )


def test_a_widened_tile_is_drawn_at_the_extent_it_covers(tmp_path: Path) -> None:
    """The loaded tile must carry the service's extent, not the request."""
    asked = BBox(south=31.1, north=36.6, west=134.5, east=141.5)
    wider = BBox(south=31.1, north=36.6, west=133.2857, east=142.7143)
    _write_tile(tmp_path, asked, 80, 60, actual=wider)
    tile = terrain.load_terrain(asked, width=80, height=60, cache_root=tmp_path)
    assert tile.extent == (wider.west, wider.east, wider.south, wider.north)


def test_a_tile_without_a_recorded_extent_is_refused(tmp_path: Path) -> None:
    """Sidecars written before the extent was asked for cannot be trusted.

    They record only the requested box. Falling back to it would restore the
    bug silently, so such a tile has to be re-fetched.
    """
    import json

    path = _write_tile(tmp_path, BOX, 100, 80)
    side = path.with_suffix(".tif.json")
    side.write_text(json.dumps({"bbox": [BOX.south, BOX.north, BOX.west, BOX.east]}))
    with pytest.raises(ValueError, match="predates the extent check"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_a_tile_with_no_sidecar_at_all_is_refused(tmp_path: Path) -> None:
    path = _write_tile(tmp_path, BOX, 100, 80)
    path.with_suffix(".tif.json").unlink()
    with pytest.raises(FileNotFoundError, match="true extent is"):
        terrain.load_terrain(BOX, width=100, height=80, cache_root=tmp_path)


def test_a_reply_of_the_wrong_size_is_an_error() -> None:
    """Pixel dimensions anchor the extent to the array, so they must agree."""
    reply = {"extent": {"xmin": 134.0, "ymin": 32.0, "xmax": 140.0, "ymax": 36.0},
             "width": 700, "height": 840}
    with pytest.raises(OSError, match="service reports 700x840"):
        terrain._extent_of(reply, 1440, 840)


@pytest.mark.network
def test_the_live_service_places_land_and_sea_where_they_belong(tmp_path: Path) -> None:
    """The check the shipped map failed: are the pixels where they claim to be?

    A deliberately mismatched aspect ratio (box 1.27, image 1.71) forces the
    service to widen the box, so this only passes if the reply is believed
    over the request. The landmarks are far apart and unambiguous: Cape Shio
    on the Kii peninsula against the Kii channel one degree west of it.
    """
    box = BBox(south=31.1, north=36.6, west=134.5, east=141.5)
    terrain.fetch_terrain(box, width=1440, height=840, cache_root=tmp_path)
    tile = terrain.load_terrain(box, width=1440, height=840, cache_root=tmp_path)

    def at(lat: float, lon: float) -> float:
        w, e, s, n = tile.extent
        h, wd = tile.elevation.shape
        j = round((lon - w) / (e - w) * (wd - 1))
        i = round((n - lat) / (n - s) * (h - 1))
        return float(tile.elevation[i, j])

    assert at(33.44, 135.76) > 0.0, "Cape Shio is land"
    assert at(33.90, 135.00) < 0.0, "the Kii channel is sea"
    assert at(33.00, 137.50) < -2000.0, "the Nankai Trough is deep"
    assert at(35.25, 136.10) == pytest.approx(85.0, abs=40.0), "Lake Biwa sits at 85 m"
    assert at(35.36, 138.73) > 2500.0, "Mount Fuji is high even when smoothed"


@pytest.mark.network
def test_the_live_service_returns_elevation(tmp_path: Path) -> None:
    """Small live check that the URL and the pixel type still behave."""
    small = BBox(south=33.0, north=35.0, west=135.0, east=137.0)
    terrain.fetch_terrain(small, width=60, height=60, cache_root=tmp_path)
    tile = terrain.load_terrain(small, width=60, height=60, cache_root=tmp_path)
    e = tile.elevation
    assert e.min() < 0.0 < e.max(), "this box spans the Kii coast, so it needs both"
    sidecar = terrain.terrain_path(small, 60, 60, tmp_path).with_suffix(".tif.json")
    assert sidecar.exists()
