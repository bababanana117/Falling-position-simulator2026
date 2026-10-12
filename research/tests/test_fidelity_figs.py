"""Figures for the variability and fidelity chapter.

These check that each figure renders and that the things a reader has to be able
to see are actually on the page -- the seasons distinguishable, the two error
measures kept apart, the "no crossing" case labelled rather than dropped.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

from windclim.figures import fidelity as ff  # noqa: E402
from windclim.figures import plots, style  # noqa: E402
from windclim.timebins import SEASON_ORDER  # noqa: E402

LAGS = (6, 12, 24, 48, 72, 120, 240, 360, 480)
LEVELS = (10.0, 30.0, 100.0, 200.0, 500.0, 850.0)


@pytest.fixture(autouse=True, scope="module")
def _style():
    style.apply_style(japanese=True)


@pytest.fixture
def lag_wind() -> pd.DataFrame:
    rows = []
    for si, season in enumerate(SEASON_ORDER):
        for level in LEVELS:
            for lag in LAGS:
                med = (2.0 + si) * np.sqrt(lag / 6.0) * (1.0 + 800.0 / level)
                rows.append({"season": season, "plevel": level, "lag_hours": lag,
                             "unit": "m s-1", "median": med, "p90": med * 2.1,
                             "max": med * 4.0, "n": 10000})
    return pd.DataFrame(rows)


@pytest.fixture
def decorrelation() -> pd.DataFrame:
    rows = []
    for si, season in enumerate(SEASON_ORDER):
        for level in LEVELS:
            days = 0.7 + si * 1.3 + (800.0 / level)
            # Summer at 10 hPa never crosses -- the case the figure must label.
            if season == SEASON_ORDER[2] and level == 10.0:
                days = np.nan
            rows.append({"season": season, "plevel": level,
                         "decorrelation_hours": days * 24, "decorrelation_days": days})
    return pd.DataFrame(rows)


@pytest.fixture
def direction() -> pd.DataFrame:
    rows = []
    for si, season in enumerate(SEASON_ORDER):
        for level in LEVELS:
            med = 5.0 + 4.0 * si + 600.0 / level
            rows.append({"season": season, "plevel": level, "lag_hours": 24,
                         "unit": "deg", "median": med, "p90": med * 2.4,
                         "max": 180.0, "n": 900})
    return pd.DataFrame(rows)


@pytest.fixture
def slip() -> pd.DataFrame:
    rows = []
    for si, season in enumerate(SEASON_ORDER):
        for lag in (6, 12, 24, 48, 72, 120):
            med = (10.0 + 6.0 * si) * np.sqrt(lag / 6.0)
            rows.append({"season": season, "lag_hours": lag, "unit": "km",
                         "median": med, "p90": med * 1.9, "max": med * 5.0,
                         "n": 250000})
    return pd.DataFrame(rows)


@pytest.fixture
def error() -> pd.DataFrame:
    rows = []
    flight = {SEASON_ORDER[0]: 235.0, SEASON_ORDER[1]: 140.0,
              SEASON_ORDER[2]: 46.0, SEASON_ORDER[3]: 120.0}
    for season in SEASON_ORDER:
        for vi, variant in enumerate(("time_frozen", "place_frozen", "both_frozen")):
            med = 3.0 + vi
            rows.append({
                "season": season, "variant": variant,
                "variant_ja": ff.VARIANT_LABEL[variant],
                "median_km": med, "p90_km": med * 2.0, "max_km": med * 5.0,
                "flight_median_km": flight[season],
                "relative_median": med / flight[season],
                "relative_p90": med * 2.0 / flight[season], "n": 250000,
            })
    return pd.DataFrame(rows)


@pytest.fixture
def variance() -> pd.DataFrame:
    return pd.DataFrame([
        {"scope": "全体", "total": 169.0, "within_day": 10.6, "day_to_day": 81.7,
         "seasonal": 76.7, "interannual": 4.1, "within_day_fraction": 0.063},
    ])


def test_change_curve_renders(lag_wind, tmp_path: Path) -> None:
    fig = ff.fig_change_curve(lag_wind, "和歌山")
    png, pdf = plots.save(fig, tmp_path, "G1", "change")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_change_curve_uses_a_log_lag_axis(lag_wind) -> None:
    """Six hours to twenty days on a linear axis buries the short lags at the edge."""
    fig = ff.fig_change_curve(lag_wind, "和歌山")
    assert all(ax.get_xscale() == "log" for ax in fig.axes)


def test_change_curve_has_a_panel_per_level(lag_wind) -> None:
    fig = ff.fig_change_curve(lag_wind, "和歌山")
    titles = {ax.get_title() for ax in fig.axes}
    assert titles == {f"{p:g} hPa" for p in LEVELS}


def test_every_season_keeps_the_same_colour_across_figures(lag_wind, slip) -> None:
    """A reader who learns the colours once should not have to relearn them.

    The seasons are identities, so the hue is assigned by slot and never cycled.
    """
    assert len(set(ff.SEASON_COLOR.values())) == len(SEASON_ORDER)
    curve = ff.fig_change_curve(lag_wind, "和歌山")
    slips = ff.fig_slip_curve(slip, "和歌山")
    curve_colors = {ln.get_label(): ln.get_color() for ln in curve.axes[0].lines}
    slip_colors = {ln.get_label(): ln.get_color() for ln in slips.axes[0].lines}
    for season in SEASON_ORDER:
        assert curve_colors[season] == slip_colors[season] == ff.SEASON_COLOR[season]


def test_decorrelation_labels_the_case_that_never_crosses(decorrelation) -> None:
    """A blank bar reads as zero, which is the opposite of what NaN means here.

    NaN means the wind was still correlated at the longest lag looked at, i.e.
    the memory is *long*. Left unlabelled it would be read as no memory at all.
    """
    fig = ff.fig_decorrelation(decorrelation, "和歌山")
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert any("20日超" in t for t in texts)


def test_decorrelation_renders(decorrelation, tmp_path: Path) -> None:
    fig = ff.fig_decorrelation(decorrelation, "和歌山")
    png, _ = plots.save(fig, tmp_path, "G2", "decorrelation")
    assert png.stat().st_size > 5000


def test_direction_change_puts_pressure_on_a_descending_axis(direction) -> None:
    """A profile is read with the ground at the bottom, so pressure runs downwards."""
    fig = ff.fig_direction_change(direction, "和歌山")
    lo, hi = fig.axes[0].get_ylim()
    assert lo > hi


def test_direction_change_renders(direction, tmp_path: Path) -> None:
    fig = ff.fig_direction_change(direction, "和歌山")
    png, _ = plots.save(fig, tmp_path, "G3", "direction")
    assert png.stat().st_size > 5000


def test_slip_curve_renders(slip, tmp_path: Path) -> None:
    fig = ff.fig_slip_curve(slip, "和歌山")
    png, _ = plots.save(fig, tmp_path, "G4", "slip")
    assert png.stat().st_size > 5000


def test_error_breakdown_keeps_absolute_and_relative_apart(error) -> None:
    """One score would be a judgement; two panels is a measurement.

    Winter flies six times as far as summer, so the two panels can and do rank
    the seasons differently, and collapsing them would hide that.
    """
    fig = ff.fig_error_breakdown(error, "和歌山")
    labels = [ax.get_ylabel() for ax in fig.axes]
    assert "着地点のずれ (km)" in labels
    assert "飛行距離に対する割合 (%)" in labels


def test_error_breakdown_renders(error, tmp_path: Path) -> None:
    fig = ff.fig_error_breakdown(error, "和歌山")
    png, pdf = plots.save(fig, tmp_path, "G5", "error")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_variance_split_renders_and_adds_to_the_whole(variance, tmp_path: Path) -> None:
    fig = ff.fig_variance_split(variance, "和歌山")
    ax = fig.axes[0]
    widths = sorted(p.get_width() for p in ax.patches)
    row = variance.iloc[0]
    assert sum(widths) == pytest.approx(
        row["seasonal"] + row["day_to_day"] + row["within_day"]
    )
    png, _ = plots.save(fig, tmp_path, "G6", "variance")
    assert png.stat().st_size > 4000


def test_trajectory_map_renders_with_every_variant(tmp_path: Path) -> None:
    t = np.linspace(0, 1, 60)
    tracks = {
        "reference": (135.0 + 2.4 * t, 34.0 - 0.3 * t),
        "time_frozen": (135.0 + 2.3 * t, 34.0 - 0.28 * t),
        "place_frozen": (135.0 + 2.5 * t, 34.0 - 0.33 * t),
        "both_frozen": (135.0 + 2.2 * t, 34.0 - 0.26 * t),
    }
    fig = ff.fig_trajectory_map(tracks, (34.0, 135.0), "和歌山", "2020年1月の一例")
    labels = [t.get_text() for t in fig.legends[0].get_texts()]
    assert len(labels) == 4
    png, _ = plots.save(fig, tmp_path, "G7", "track")
    assert png.stat().st_size > 8000


def test_trajectory_map_zooms_in_on_the_landing_points(tmp_path: Path) -> None:
    """At the scale of a winter flight, a few kilometres is thinner than the line.

    Four tracks drawn on top of each other read as "identical", which is the
    wrong conclusion. The second panel exists so the small difference is visible
    as a small difference.
    """
    t = np.linspace(0, 1, 40)
    tracks = {
        "reference": (135.0 + 2.40 * t, 34.0 - 0.30 * t),
        "both_frozen": (135.0 + 2.44 * t, 34.0 - 0.28 * t),
    }
    fig = ff.fig_trajectory_map(tracks, (34.0, 135.0), "和歌山", "例")
    wide, zoom = fig.axes[0], fig.axes[1]
    assert np.ptp(zoom.get_xlim()) < 0.25 * np.ptp(wide.get_xlim())


def test_trajectory_map_marks_the_launch_point(tmp_path: Path) -> None:
    """Without it the reader cannot tell which end of the track is the start."""
    tracks = {"reference": (np.array([135.0, 137.0]), np.array([34.0, 33.8]))}
    fig = ff.fig_trajectory_map(tracks, (34.0, 135.0), "和歌山", "例")
    assert any(ln.get_marker() == "*" for ln in fig.axes[0].lines)
