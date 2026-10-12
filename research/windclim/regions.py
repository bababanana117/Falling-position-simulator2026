"""Geographic boxes.

One ``MASTER`` box is fetched from GDEX; the analysis regions are sliced out of
that cache locally. The server's cost is set by its internal chunking
(``anl_p`` is chunked ``(1, 23, 240, 480)``), so asking for two small boxes
separately costs the server exactly as much as asking for one box that contains
both -- it just doubles the number of requests and the wall-clock time. Adding a
third region later therefore costs no network at all.

``MASTER`` was also chosen to sit inside a single latitude chunk (index < 240)
and a single longitude chunk (index < 480), so each timestep needs only the two
pressure-level chunks rather than four spatial ones.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BBox", "MASTER", "REGIONS", "to_0_360", "to_signed_lon"]


@dataclass(frozen=True)
class BBox:
    """An inclusive lat/lon box in degrees, longitudes in the 0-360 convention."""

    south: float
    north: float
    west: float
    east: float

    def __post_init__(self) -> None:
        if self.south >= self.north:
            raise ValueError(f"south must be < north, got {self.south} >= {self.north}")
        if self.west >= self.east:
            raise ValueError(f"west must be < east, got {self.west} >= {self.east}")
        if not (self.south >= -90.0 and self.north <= 90.0):
            raise ValueError(f"latitudes must lie in [-90, 90], got {self.south}..{self.north}")
        if not (self.west >= 0.0 and self.east <= 360.0):
            raise ValueError(
                f"longitudes must be given in the 0-360 convention, got {self.west}..{self.east}"
            )

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= to_0_360(lon) <= self.east

    @property
    def lat_mid(self) -> float:
        return 0.5 * (self.south + self.north)


def to_0_360(lon: float) -> float:
    """Map a longitude to the 0-360 convention used by the JRA-3Q grid."""
    return lon % 360.0


def to_signed_lon(lon: float) -> float:
    """Map a longitude to the -180..180 convention used by the web frontend.

    Matches ``normalizeLon`` in ``frontend/src/api/tawhiri.ts``.
    """
    lon = lon % 360.0
    return lon - 360.0 if lon > 180.0 else lon


#: Fetched once; every region is sliced out of this.
MASTER = BBox(south=30.0, north=48.0, west=132.0, east=150.0)

#: A second cache box for western and southern Japan, fetched later and only for
#: the months that were asked about (January and February). Most of Kyushu lies
#: west of 132 E and Okinawa south of 30 N, so neither fits in MASTER.
SOUTHWEST = BBox(south=24.0, north=37.5, west=122.0, east=140.5)

#: All of Japan, from Yonaguni and Hateruma (24 N, 123 E) to Wakkanai and Nemuro
#: (45.5 N, 145.8 E), including Ogasawara (27 N, 142 E). Fetched for every month
#: for the v2 database. Okinotorishima (20 N) and Minamitorishima (154 E) are
#: left out.
JAPAN = BBox(south=24.0, north=46.0, west=122.0, east=146.5)

#: Cache boxes by the name written into the cached file names (``*_<name>.nc``).
FETCH_BOXES: dict[str, BBox] = {"master": MASTER, "sw": SOUTHWEST, "jp": JAPAN}

#: Analysis regions. Each must lie inside the cache box it is read from.
REGIONS: dict[str, BBox] = {
    "hokkaido": BBox(south=40.0, north=46.5, west=138.0, east=149.0),
    "wakayama": BBox(south=32.5, north=35.0, west=134.0, east=137.0),
    # Ainan, Ehime. The launch site sits only 0.55 deg inside MASTER's west
    # edge, so the box cannot be centred on it without a new fetch. It is
    # extended east instead, which is where a balloon from here drifts for
    # most of the year; the summer westward drift runs into the edge, and the
    # report says so rather than hiding it.
    "ehime": BBox(south=31.5, north=34.5, west=132.0, east=136.0),
    # Western and southern Japan, from the Sakishima islands to Shizuoka. Only
    # January and February are cached for it.
    "southwest": SOUTHWEST,
    "japan": JAPAN,
}

#: Which cache box each region is read from. Regions not listed use MASTER.
REGION_CACHE_BOX: dict[str, str] = {"southwest": "sw", "japan": "jp"}


def cache_box_name(region: str) -> str:
    return REGION_CACHE_BOX.get(region, "master")


for _name, _box in REGIONS.items():
    _cache = FETCH_BOXES[cache_box_name(_name)]
    if not (
        _cache.south <= _box.south
        and _box.north <= _cache.north
        and _cache.west <= _box.west
        and _box.east <= _cache.east
    ):
        raise AssertionError(f"region {_name!r} is not contained in its cache box")
del _name, _box, _cache
