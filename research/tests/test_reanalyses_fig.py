"""The reanalysis comparison figure and the specifications behind it.

The figure exists to justify a choice, so the tests check the two properties
that make it honest: that the JRA-3Q entry matches the data actually fetched,
and that the figure does not quietly reverse its own axis.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from windclim.config import LEVELS_HPA  # noqa: E402
from windclim.figures import plots, style  # noqa: E402
from windclim.figures.reanalyses import (  # noqa: E402
    BURST_KM,
    PRODUCTS,
    fig_reanalysis_comparison,
)


@pytest.fixture(autouse=True, scope="module")
def _style():
    style.apply_style(japanese=True)


def _by_name(name: str):
    return next(p for p in PRODUCTS if p.name == name)


def test_the_jra3q_entry_matches_the_data_actually_fetched() -> None:
    """The one row claimed as measured has to agree with the archive.

    Everything else in the figure is a specification typed in by hand. If the
    row that is supposed to be checkable drifts away from the files, the
    figure's whole claim to authority goes with it.
    """
    jra = _by_name("JRA-3Q")
    assert jra.measured is True
    assert jra.deg == 0.375
    assert jra.top_hpa == min(LEVELS_HPA)
    assert jra.n_levels == len(LEVELS_HPA)


def test_only_jra3q_claims_to_be_measured() -> None:
    assert [p.name for p in PRODUCTS if p.measured] == ["JRA-3Q"]


def test_the_products_that_cannot_reach_burst_are_below_the_line() -> None:
    """NCEP R1 stops at 10 hPa, which is the burst altitude itself.

    This is the figure's main discriminator, so it is worth pinning: if a
    future edit to the specs moved it above the line the figure would stop
    making its point.
    """
    assert _by_name("NCEP/NCAR R1").top_km < BURST_KM + 2.0
    for name in ("JRA-3Q", "ERA5", "MERRA-2", "JRA-55"):
        assert _by_name(name).top_km > BURST_KM + 10.0


def test_grid_spacing_is_reported_at_the_working_latitude() -> None:
    """A degree of longitude is 73 km at 43 N, not 111."""
    assert _by_name("ERA5").km == pytest.approx(0.25 * 111.195 * 0.7314, rel=1e-3)
    assert _by_name("JRA-3Q").km == pytest.approx(30.5, abs=0.5)


def test_the_resolution_axis_puts_finer_on_the_right(tmp_path: Path) -> None:
    """The caption says "finer to the right", so the axis has to be inverted.

    Left to itself a log axis increases rightwards, which would put the
    coarsest product where the reader is told the best ones are.
    """
    fig = fig_reanalysis_comparison()
    lo, hi = fig.axes[0].get_xlim()
    assert lo > hi
    png, pdf = plots.save(fig, tmp_path, "F12", "reanalyses")
    assert png.stat().st_size > 20000
    assert pdf.stat().st_size > 5000


def test_a_product_still_being_extended_has_no_end_year() -> None:
    assert _by_name("JRA-55").end_year == 2023
    assert _by_name("JRA-3Q").end_year is None
    assert _by_name("ERA5").end_year is None
