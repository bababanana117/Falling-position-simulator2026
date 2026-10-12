"""Filenames and URLs for JRA-3Q on NSF NCAR GDEX (dataset ``d640000``).

The naming scheme is fully deterministic, so these are *constructed* rather than
discovered by crawling the catalog. A ``--discover`` mode (network-marked test)
checks the constructed names against the live catalog; that check is never a
runtime dependency.

Two quirks of the archive are encoded here:

* The variable name inside each file contains hyphens (``ugrd-pres-an-gauss``).
  A raw DAP DDS escapes those as ``%2D``. libnetcdf unescapes them for us, but
  :func:`dap_escaped` exists so the fetcher can recognise either spelling.
* ``anl_p`` (0.375 deg) is split into six fixed 5-day chunks per month starting
  on days 1, 6, 11, 16, 21 and 26; the last chunk runs to the end of the month
  and so is 3-6 days long. ``anl_p125`` (1.25 deg) is one file per month.
"""

from __future__ import annotations

import calendar

__all__ = [
    "GDEX_CATALOG_ROOT",
    "GDEX_DODS_ROOT",
    "GDEX_NCSS_ROOT",
    "PARAM_CODE",
    "PRODUCTS",
    "SOURCE_VERIFIED_ON",
    "VAR_SUFFIX",
    "anl_p125_url",
    "anl_p_chunks",
    "anl_p_url",
    "catalog_url",
    "dap_escaped",
    "month_urls",
    "nc_varname",
    "ncss_url",
]

GDEX_DODS_ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d640000"
GDEX_CATALOG_ROOT = "https://tds.gdex.ucar.edu/thredds/catalog/files/g/d640000"
GDEX_NCSS_ROOT = "https://tds.gdex.ucar.edu/thredds/ncss/grid/files/g/d640000"

#: GRIB2 parameter codes, which appear literally in the filenames.
PARAM_CODE = {"ugrd": "0_2_2", "vgrd": "0_2_3", "hgt": "0_3_5"}

#: Product-specific suffix of the variable name inside each file.
VAR_SUFFIX = {"anl_p": "pres-an-gauss", "anl_p125": "pres-an-ll125"}

PRODUCTS = tuple(VAR_SUFFIX)

#: The day this module's strings were last checked against the live catalog.
SOURCE_VERIFIED_ON = "2026-09-18"

#: Fixed start days of the six ``anl_p`` chunks in every month.
_ANL_P_CHUNK_STARTS = (1, 6, 11, 16, 21, 26)


def _check(var: str, product: str) -> None:
    if var not in PARAM_CODE:
        raise ValueError(f"var must be one of {tuple(PARAM_CODE)}, got {var!r}")
    if product not in VAR_SUFFIX:
        raise ValueError(f"product must be one of {PRODUCTS}, got {product!r}")


def nc_varname(var: str, product: str) -> str:
    """Name of the data variable *inside* the netCDF file, hyphens and all."""
    _check(var, product)
    return f"{var}-{VAR_SUFFIX[product]}"


def dap_escaped(name: str) -> str:
    """The spelling a raw DAP DDS uses for a hyphenated variable name."""
    return name.replace("-", "%2D")


def anl_p_chunks(year: int, month: int) -> list[tuple[int, int]]:
    """Inclusive ``(first_day, last_day)`` of each 5-day ``anl_p`` file."""
    last = calendar.monthrange(year, month)[1]
    out: list[tuple[int, int]] = []
    for i, start in enumerate(_ANL_P_CHUNK_STARTS):
        end = last if i == len(_ANL_P_CHUNK_STARTS) - 1 else start + 4
        out.append((start, end))
    return out


def _filename(var: str, product: str, year: int, month: int, day0: int, day1: int) -> str:
    code = PARAM_CODE[var]
    name = nc_varname(var, product)
    start = f"{year:04d}{month:02d}{day0:02d}00"
    end = f"{year:04d}{month:02d}{day1:02d}18"
    return f"jra3q.{product}.{code}.{name}.{start}_{end}.nc"


def anl_p_url(var: str, year: int, month: int, day0: int, day1: int) -> str:
    """OPeNDAP URL of one 5-day ``anl_p`` (0.375 deg) file."""
    _check(var, "anl_p")
    fn = _filename(var, "anl_p", year, month, day0, day1)
    return f"{GDEX_DODS_ROOT}/anl_p/{year:04d}{month:02d}/{fn}"


def anl_p125_url(var: str, year: int, month: int) -> str:
    """OPeNDAP URL of one monthly ``anl_p125`` (1.25 deg) file."""
    _check(var, "anl_p125")
    last = calendar.monthrange(year, month)[1]
    fn = _filename(var, "anl_p125", year, month, 1, last)
    return f"{GDEX_DODS_ROOT}/anl_p125/{year:04d}{month:02d}/{fn}"


def catalog_url(product: str, year: int, month: int) -> str:
    """THREDDS catalog XML for one month directory."""
    if product not in VAR_SUFFIX:
        raise ValueError(f"product must be one of {PRODUCTS}, got {product!r}")
    return f"{GDEX_CATALOG_ROOT}/{product}/{year:04d}{month:02d}/catalog.xml"


def month_urls(
    var: str, product: str, year: int, month: int
) -> list[tuple[tuple[int, int], str]]:
    """All ``((first_day, last_day), url)`` pairs covering one month."""
    _check(var, product)
    if product == "anl_p":
        return [
            ((d0, d1), anl_p_url(var, year, month, d0, d1))
            for d0, d1 in anl_p_chunks(year, month)
        ]
    last = calendar.monthrange(year, month)[1]
    return [((1, last), anl_p125_url(var, year, month))]


def ncss_url(
    var: str,
    product: str,
    year: int,
    month: int,
    day0: int,
    day1: int,
    *,
    north: float,
    south: float,
    west: float,
    east: float,
) -> str:
    """NetcdfSubset URL for the same file, used as the OPeNDAP fallback.

    NCSS does the subsetting server-side and returns a single netCDF4 file, so
    it can be gentler on the server for small boxes than a DAP hyperslab.
    """
    _check(var, product)
    fn = _filename(var, product, year, month, day0, day1)
    name = nc_varname(var, product)
    start = f"{year:04d}-{month:02d}-{day0:02d}T00:00:00Z"
    end = f"{year:04d}-{month:02d}-{day1:02d}T18:00:00Z"
    query = (
        f"var={name}&north={north}&south={south}&west={west}&east={east}"
        f"&horizStride=1&time_start={start}&time_end={end}&accept=netcdf4"
    )
    return f"{GDEX_NCSS_ROOT}/{product}/{year:04d}{month:02d}/{fn}?{query}"
