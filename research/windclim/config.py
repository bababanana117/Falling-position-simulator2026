"""Pipeline-wide constants and paths.

Everything that could drift if GDEX changes its archive lives here or in
:mod:`windclim.urls`, marked with the date it was last checked against the live
server. The network-marked tests re-verify these.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "ANALYSIS_HOURS_UTC",
    "CACHE_ROOT",
    "DEFAULT_PRODUCT",
    "FILL_VALUE",
    "HGT_TIME_STRIDE",
    "LEVELS_HPA",
    "LEVEL_MIN_HPA",
    "MAX_WORKERS",
    "MIN_REQUEST_INTERVAL_S",
    "OUT_ROOT",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "REPO_ROOT",
    "VARS",
    "YEARS",
    "kept_levels",
]

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent          # research/
REPO_ROOT = PROJECT_ROOT.parent             # repository root

CACHE_ROOT = Path(os.environ.get("WINDCLIM_CACHE", PROJECT_ROOT / "data"))
OUT_ROOT = Path(os.environ.get("WINDCLIM_OUT", PROJECT_ROOT / "out"))

#: Ten complete years. Verified 2026-09-18 that anl_p/202512 is fully populated.
YEARS = range(2016, 2026)

DEFAULT_PRODUCT = "anl_p"          # 0.375 deg; anl_p125 is the 1.25 deg cross-check

VARS: tuple[str, ...] = ("ugrd", "vgrd", "hgt")

#: JRA-3Q analysis times. In JST these are 09, 15, 21 and 03 (next day).
ANALYSIS_HOURS_UTC: tuple[int, ...] = (0, 6, 12, 18)

#: All 45 isobaric levels in the archive, ascending in pressure.
LEVELS_HPA: tuple[float, ...] = (
    0.01, 0.03, 0.1, 0.3, 0.7, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0, 40.0,
    50.0, 60.0, 70.0, 85.0, 100.0, 125.0, 150.0, 175.0, 200.0, 225.0, 250.0,
    300.0, 350.0, 400.0, 450.0, 500.0, 550.0, 600.0, 650.0, 700.0, 750.0, 775.0,
    800.0, 825.0, 850.0, 875.0, 900.0, 925.0, 950.0, 975.0, 1000.0,
)

#: Keep levels at or below this many hPa above the ground, i.e. p >= 3 hPa.
#: 3 hPa is about 40 km, comfortably above any burst altitude; the seven levels
#: above it (2 hPa and thinner) reach into the mesosphere and are of no use to a
#: balloon, so they are dropped before transfer.
LEVEL_MIN_HPA = 3.0

#: Geopotential height barely varies through the day, and its only job here is to
#: label the pressure levels with an altitude, so one analysis per 5-day file is
#: plenty (720 samples over ten years, ~15 per half bin).
HGT_TIME_STRIDE = 20

#: Politeness settings for the shared GDEX server, chosen from measurement on
#: 2026-09-18: one request alone takes 13.7 s, three workers still averaged
#: 13.7 s per file, but six workers reached 4.3 s per file. The server does
#: parallelise, so the whole 2160-request run is about 2.5 hours rather than 8.
#: Six concurrent connections is a modest load on a public service; there was no
#: attempt to find the point where it stops scaling.
MAX_WORKERS = 6
MIN_REQUEST_INTERVAL_S = 1.0

FILL_VALUE = 9.999e20


def kept_levels(level_min_hpa: float = LEVEL_MIN_HPA) -> tuple[float, ...]:
    """The subset of :data:`LEVELS_HPA` actually fetched and analysed."""
    return tuple(p for p in LEVELS_HPA if p >= level_min_hpa)
