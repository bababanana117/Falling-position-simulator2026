"""URL and filename construction for GDEX dataset d640000.

Every expected string in this file was copied from a live GDEX catalog listing
on 2026-09-18. These are exact-match tests on purpose: if GDEX renames anything,
this fails loudly instead of the fetcher quietly 404-ing 2160 times.
"""

from __future__ import annotations

import pytest

from windclim import urls

DODS = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d640000"


# --- variable names inside the files -----------------------------------------


@pytest.mark.parametrize(
    ("var", "product", "expected"),
    [
        ("ugrd", "anl_p", "ugrd-pres-an-gauss"),
        ("vgrd", "anl_p", "vgrd-pres-an-gauss"),
        ("hgt", "anl_p", "hgt-pres-an-gauss"),
        ("ugrd", "anl_p125", "ugrd-pres-an-ll125"),
        ("hgt", "anl_p125", "hgt-pres-an-ll125"),
    ],
)
def test_nc_varname(var: str, product: str, expected: str) -> None:
    assert urls.nc_varname(var, product) == expected


def test_nc_varname_rejects_unknown_var() -> None:
    with pytest.raises(ValueError):
        urls.nc_varname("tmp", "anl_p")


def test_nc_varname_rejects_unknown_product() -> None:
    with pytest.raises(ValueError):
        urls.nc_varname("ugrd", "anl_model")


def test_dap_escaped_name_matches_the_raw_dds_form() -> None:
    assert urls.dap_escaped(urls.nc_varname("ugrd", "anl_p")) == "ugrd%2Dpres%2Dan%2Dgauss"


# --- 5-day chunking of anl_p -------------------------------------------------


def test_anl_p_chunks_january() -> None:
    assert urls.anl_p_chunks(2016, 1) == [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 31)]


def test_anl_p_chunks_leap_february() -> None:
    assert urls.anl_p_chunks(2016, 2) == [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 29)]


def test_anl_p_chunks_common_february() -> None:
    assert urls.anl_p_chunks(2017, 2) == [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 28)]


def test_anl_p_chunks_thirty_day_month() -> None:
    assert urls.anl_p_chunks(2019, 4) == [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 30)]


def test_anl_p_chunks_always_cover_the_month_exactly() -> None:
    import calendar

    for year in range(2016, 2026):
        for month in range(1, 13):
            chunks = urls.anl_p_chunks(year, month)
            days = [d for a, b in chunks for d in range(a, b + 1)]
            assert days == list(range(1, calendar.monthrange(year, month)[1] + 1))


# --- full URLs ---------------------------------------------------------------


def test_anl_p_url_matches_verified_string() -> None:
    assert urls.anl_p_url("ugrd", 2016, 1, 1, 5) == (
        f"{DODS}/anl_p/201601/"
        "jra3q.anl_p.0_2_2.ugrd-pres-an-gauss.2016010100_2016010518.nc"
    )


def test_anl_p_url_last_chunk_of_december_2025() -> None:
    assert urls.anl_p_url("ugrd", 2025, 12, 26, 31).endswith(
        "jra3q.anl_p.0_2_2.ugrd-pres-an-gauss.2025122600_2025123118.nc"
    )


def test_anl_p_url_vgrd_and_hgt_param_codes() -> None:
    assert ".0_2_3.vgrd-" in urls.anl_p_url("vgrd", 2016, 1, 1, 5)
    assert ".0_3_5.hgt-" in urls.anl_p_url("hgt", 2016, 1, 1, 5)


def test_anl_p125_url_matches_verified_string() -> None:
    assert urls.anl_p125_url("ugrd", 2016, 1) == (
        f"{DODS}/anl_p125/201601/"
        "jra3q.anl_p125.0_2_2.ugrd-pres-an-ll125.2016010100_2016013118.nc"
    )


def test_anl_p125_url_leap_february_ends_on_the_29th() -> None:
    assert urls.anl_p125_url("ugrd", 2016, 2).endswith("2016020100_2016022918.nc")


def test_anl_p125_url_common_february_ends_on_the_28th() -> None:
    assert urls.anl_p125_url("ugrd", 2017, 2).endswith("2017020100_2017022818.nc")


def test_catalog_url() -> None:
    assert urls.catalog_url("anl_p", 2016, 2) == (
        "https://tds.gdex.ucar.edu/thredds/catalog/files/g/d640000/anl_p/201602/catalog.xml"
    )


# --- month_urls dispatch -----------------------------------------------------


def test_month_urls_anl_p_has_six_chunks() -> None:
    got = urls.month_urls("ugrd", "anl_p", 2016, 1)
    assert len(got) == 6
    assert got[0][0] == (1, 5)
    assert got[-1][0] == (26, 31)


def test_month_urls_anl_p125_has_one_file() -> None:
    got = urls.month_urls("ugrd", "anl_p125", 2016, 1)
    assert len(got) == 1
    assert got[0][0] == (1, 31)


def test_source_verified_marker_is_present() -> None:
    """A dated marker so a future reader knows when these strings were checked."""
    assert urls.SOURCE_VERIFIED_ON == "2026-09-18"
