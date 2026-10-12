"""Constants for the Hokkaido wind database build.

Everything tunable lives here so that a number in the code is never a mystery.
The numerical tolerances in particular were measured rather than guessed; the
comment on each one says what the measurement was.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

REGION = "hokkaido"
PERIOD = "2016-2025"
PRODUCT_VERSION = "1"
DB_STEM = f"jra3q_{REGION}_wind_{PERIOD}_v{PRODUCT_VERSION}"

DB_PATH = PROJECT_ROOT / f"{DB_STEM}.duckdb"
STAGING_DIR = PROJECT_ROOT / "_staging"
SQL_DIR = PROJECT_ROOT / "sql"

#: Name of the aggregated statistics file the build reads. Only the build
#: needs it; reading the finished database does not.
SOURCE_NETCDF_NAME = f"jra3q_windclim_{REGION}_{PERIOD}_v1.nc"


def source_netcdf() -> Path:
    """Locate the aggregated statistics the build reads.

    This module deliberately imports nothing from the upstream aggregation
    pipeline. That pipeline is not part of what is distributed, and someone
    who only wants to query the finished database must still be able to run
    ``python -m hokduck.verify`` -- which would fail at import time if a
    missing upstream package were required merely to name a path.

    Set ``HOKDUCK_SOURCE_NETCDF`` to point at the file directly. Otherwise
    the pipeline's own output directory is asked for it, and the error says
    so if the pipeline is absent.
    """
    override = os.environ.get("HOKDUCK_SOURCE_NETCDF")
    if override:
        return Path(override)
    try:
        from windclim.config import OUT_ROOT
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "The aggregated statistics were not found.\n"
            f"Set HOKDUCK_SOURCE_NETCDF to the path of {SOURCE_NETCDF_NAME}, "
            "or make the aggregation pipeline that produced it importable.\n"
            "Neither is needed to query the finished database."
        ) from exc
    return Path(OUT_ROOT) / "netcdf" / SOURCE_NETCDF_NAME

# ----------------------------------------------------------------- numerics
#: Cells fitted per numpy block. A (21660, 620) float64 temporary is 107 MB and
#: the Weibull Newton holds three at once; at 4096 the largest transient is
#: 21 MB and peak RSS stays dominated by the month's own u/v arrays.
CELL_BLOCK = 4096

#: Speeds are clamped to this before log(). The measured minimum over
#: 2016-2025 is 2.9e-3 m/s, so this never fires -- it is a guard, not a fudge.
SPEED_FLOOR_MS = 1e-6

#: Below these a family is degenerate: the likelihood diverges and the fit
#: carries no information. Such rows are written with converged = false and a
#: NULL likelihood rather than silently dropped.
DEGENERATE_SIGMA_MS = 1e-6
DEGENERATE_RANGE_MS = 1e-6
DEGENERATE_SIGMA_RAD = 1e-8

#: scipy.optimize.newton's `tol` is an ABSOLUTE step tolerance. At tol=1e-12,
#: 508 of 21,660 von Mises cells are reported non-converged while their actual
#: residual is 1.4e-15 -- for kappa ~ 100 a step of 1e-12 is below float
#: resolution, so it iterates to maxiter and gives up. 1e-8 converges every
#: cell with the same 1.7e-15 residual. test_newton_tol_regression pins this.
NEWTON_TOL = 1e-8
NEWTON_MAXITER = 60

#: von Mises concentration cap. Measured max resultant length over the region
#: is 0.9958 (kappa ~ 120), so the cap is a guard against R -> 1, not a limit
#: that binds in practice.
KAPPA_MAX = 1.0e6

#: The wrapped normal switches representation here. Above it the spatial sum
#: converges in a handful of terms; below it the Fourier form does. Both were
#: checked against an 801-term brute force and agree to 8.9e-16 or better.
WN_FOURIER_SWITCH_R = 0.5
WN_FOURIER_TERMS = 12
WN_SPATIAL_TERMS = 3

#: A winner is flagged ambiguous when the runner-up's AIC gap, deflated by the
#: serial correlation, falls below this. 2 is the conventional "no meaningful
#: difference" threshold for AIC.
AMBIGUOUS_DELTA_AIC = 2.0
