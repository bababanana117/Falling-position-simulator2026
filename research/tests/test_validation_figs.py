"""Figures for the time-resolution study."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

from windclim.figures import plots, style  # noqa: E402
from windclim.figures import validation as vfig  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _style():
    style.apply_style(japanese=True)


@pytest.fixture
def bins() -> pd.DataFrame:
    days = np.array([365.0, 91.0, 61.0, 30.0, 15.0, 10.0, 7.0, 5.0, 3.0, 2.0, 1.0])
    # A unique minimum at 15 days, so the figure test has a determinate answer.
    test = np.array([118.0, 76.0, 70.0, 66.5, 64.8, 65.0, 64.9, 65.2, 65.7, 66.0, 66.4])
    train = test - np.linspace(0.1, 6.3, days.size)
    best = test.min()
    return pd.DataFrame(
        {
            "granularity_days": days,
            "train_rmse_km": train,
            "test_rmse_km": test,
            "skill": 1.0 - test / test[0],
            "variance_explained": 1.0 - (test / test[0]) ** 2,
            "samples_per_bin": 14610 / np.maximum(np.round(365 / days), 1),
            "vs_best_km": test - best,
            "vs_best_sem_km": np.full(days.size, 0.25),
            "vs_best_sigma": (test - best) / 0.25,
            "folds_better": np.zeros(days.size, dtype=int),
        }
    )


@pytest.fixture
def harmonics() -> pd.DataFrame:
    k = np.arange(0, 27)
    test = 118.0 - 54.0 * (1 - np.exp(-k / 2.0)) + 0.03 * k
    return pd.DataFrame(
        {
            "k": k,
            "resolution_days": [np.inf if i == 0 else 365 / (2 * i) for i in k],
            "test_rmse_km": test,
            "train_rmse_km": test - 0.2 * k - 0.1,
            "skill": 1.0 - test / test[0],
        }
    )


@pytest.fixture
def by_level() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "level_hpa": [850.0, 500.0, 200.0, 100.0, 30.0, 10.0],
            "best_days": [15.0, 15.0, 15.0, 7.0, 15.0, 15.0],
            "resolved_lo_days": [7.0, 10.0, 5.0, 7.0, 1.0, 5.0],
            "resolved_hi_days": [61.0, 30.0, 15.0, 15.0, 30.0, 30.0],
            "skill": [0.06, 0.23, 0.38, 0.49, 0.36, 0.22],
            "variance_explained": [0.12, 0.41, 0.62, 0.74, 0.59, 0.39],
            "baseline_rmse_ms": [6.0, 12.0, 25.0, 18.0, 9.0, 11.0],
            "best_rmse_ms": [5.6, 9.2, 15.5, 9.2, 5.8, 8.6],
        }
    )


@pytest.fixture
def by_season() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": ["冬 (12-2月)", "春 (3-5月)", "夏 (6-8月)", "秋 (9-11月)"],
            "best_days": [365.0, 30.0, 5.0, 7.0],
            "resolved_lo_days": [5.0, 3.0, 5.0, 5.0],
            "resolved_hi_days": [365.0, 61.0, 15.0, 15.0],
            "skill": [0.001, 0.08, 0.26, 0.34],
            "baseline_rmse_km": [95.0, 80.0, 45.0, 70.0],
            "best_rmse_km": [94.9, 73.6, 33.3, 46.2],
        }
    )


@pytest.fixture
def variance() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "grouping": ["月 (30日)", "週 (7日)", "日 (1日)"],
            "eta_squared": [0.30, 0.33, 0.38],
            "between_bins": [1.0, 1.1, 1.3],
            "within_bins": [2.3, 2.2, 2.1],
            "interannual": [0.4, 0.5, 0.9],
            "split_half_r": [0.98, 0.83, 0.41],
            "permutation_p": [0.002, 0.002, 0.002],
        }
    )


def test_skill_curve_renders(bins, tmp_path: Path) -> None:
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=-0.0001)
    png, pdf = plots.save(fig, tmp_path, "V1", "skill_curve")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_skill_curve_marks_the_minimum(bins) -> None:
    """The reader must be able to see which point is the answer."""
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=0.0)
    ax = fig.axes[0]
    hollow = [ln for ln in ax.lines if ln.get_gid() == "best"]
    assert len(hollow) == 1
    assert float(hollow[0].get_xdata()[0]) == pytest.approx(15.0)


def test_skill_curve_reports_the_placebo(bins) -> None:
    """A result shown without its own sanity check is half a result."""
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=-0.0001)
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert any("プラセボ" in t for t in labels)


def test_skill_curve_shows_both_train_and_test(bins) -> None:
    """Without the training curve the reader cannot see that it is overfitting."""
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=0.0)
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert any("訓練" in t for t in labels)
    assert any("検証" in t for t in labels)


def test_bin_width_axis_is_logarithmic(bins) -> None:
    """Widths span 1 to 365 days; a linear axis would bunch everything at the left."""
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=0.0)
    assert fig.axes[0].get_xscale() == "log"


def test_harmonic_curve_renders_with_a_resolution_axis(harmonics, tmp_path: Path) -> None:
    """K = 0 has infinite resolution, which must not break the second axis."""
    fig = vfig.fig_harmonic_curve(harmonics, "和歌山")
    assert len(fig.axes) == 2
    labels = [t.get_text() for t in fig.axes[1].get_xticklabels()]
    assert "15" in labels        # K = 12
    png, _ = plots.save(fig, tmp_path, "V2", "harmonic")
    assert png.stat().st_size > 5000


@pytest.mark.parametrize(
    ("name", "maker"),
    [
        ("V3", lambda f: vfig.fig_by_level(f["by_level"], "和歌山")),
        ("V4", lambda f: vfig.fig_by_season(f["by_season"], "和歌山")),
        ("V5", lambda f: vfig.fig_variance_decomposition(f["variance"], "和歌山")),
    ],
)
def test_breakdown_figures_render(by_level, by_season, variance, tmp_path, name, maker):
    fig = maker({"by_level": by_level, "by_season": by_season, "variance": variance})
    png, pdf = plots.save(fig, tmp_path, name, "x")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_region_comparison_renders(bins, tmp_path: Path) -> None:
    other = bins.copy()
    other["test_rmse_km"] = other["test_rmse_km"] * 0.8 + 12.0
    fig = vfig.fig_region_comparison({"北海道": other, "和歌山": bins})
    png, _ = plots.save(fig, tmp_path, "V6", "compare")
    assert png.stat().st_size > 5000


def test_reference_widths_are_marked(bins) -> None:
    """Day, half and month need to be findable on the curve without counting ticks."""
    fig = vfig.fig_skill_curve(bins, "和歌山", placebo=0.0)
    xs = {round(float(ln.get_xdata()[0]), 3) for ln in fig.axes[0].lines
          if ln.get_linestyle() == ":"}
    assert {1.0, 7.0, 30.0} <= xs


def test_the_skill_axis_can_be_pinned_so_two_regions_compare(by_level) -> None:
    """Auto-scaling makes a weak region's bars as long as a strong region's.

    Hokkaido's best level reduces the error by 24 %, Wakayama's by 49 %. Drawn
    separately with their own axes, both best bars run the full width of the
    panel, and a reader flipping between the two pages sees no difference. The
    pinned axis is what makes the comparison the chapter is making visible.
    """
    fig = vfig.fig_by_level(by_level, "北海道", skill_max=50.0)
    assert fig.axes[0].get_xlim() == (0.0, 50.0)


def test_an_unpinned_skill_axis_still_works(by_level) -> None:
    """A first run, before the other region exists, must still draw something."""
    fig = vfig.fig_by_level(by_level, "和歌山")
    assert fig.axes[0].get_xlim()[1] > 0


def test_the_season_skill_axis_can_be_pinned(by_season) -> None:
    fig = vfig.fig_by_season(by_season, "北海道", skill_max=35.0)
    assert fig.axes[0].get_xlim() == (0.0, 35.0)
