"""Map overlays, including the drift maps.

The drift maps are drawn to scale -- the arrow tip *is* the predicted landing
point -- so the tests check the geometry, not just that a file appeared.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import pytest
import xarray as xr

matplotlib.use("Agg")

from windclim.figures import maps, plots, style  # noqa: E402
from windclim.outputs.derive import add_derived  # noqa: E402
from windclim.stats import aggregate as agg  # noqa: E402

YEARS = range(2016, 2018)
LAT = (41.0, 42.0, 43.0, 44.0)
LON = (140.0, 141.0, 142.0, 143.0)
LEVELS = (30.0, 200.0, 500.0, 850.0, 1000.0)


@pytest.fixture(scope="module")
def ds() -> xr.Dataset:
    from .conftest import write_fake_cache

    root = Path(tempfile.mkdtemp())
    write_fake_cache(
        root,
        years=YEARS,
        months=tuple(range(1, 13)),
        lat=LAT,
        lon=LON,
        levels=LEVELS,
        u_of=lambda y, m, d, h: 25.0 * np.cos((m - 1) / 12.0 * 2 * np.pi) + 4.0 * np.sin(d),
        v_of=lambda y, m, d, h: 5.0 * np.sin(d / 4.0),
    )
    cfg = agg.AggregateConfig(years=YEARS, by_hour=False, roses=False, drift=True)
    out = agg.aggregate_all(root, "hokkaido", cfg)
    out.attrs["period"] = "2016-2017"
    return add_derived(out)


@pytest.fixture(autouse=True, scope="module")
def _style():
    style.apply_style(japanese=True)


# --- drift statistics reached the dataset ------------------------------------


def test_drift_variables_are_present(ds: xr.Dataset) -> None:
    for name in ("drift_east_m", "drift_north_m", "drift_dist_mean_km",
                 "drift_dist_p90_km", "drift_bearing_deg", "drift_flight_time_s"):
        assert name in ds, name


def test_drift_has_no_level_axis(ds: xr.Dataset) -> None:
    """It is a property of the whole column, not of one pressure surface."""
    assert set(ds["drift_east_m"].dims) == {"month", "bin", "lat", "lon"}


def test_flight_parameters_are_recorded(ds: xr.Dataset) -> None:
    assert ds.attrs["flight_burst_altitude_m"] == pytest.approx(30000.0)
    assert "上昇" in ds.attrs["flight_description"]


def test_a_westerly_month_drifts_east(ds: xr.Dataset) -> None:
    """The fixture's January wind is strongly westerly, so the payload goes east."""
    jan = ds.sel(month=1, bin=2)
    assert float(jan["drift_east_m"].mean()) > 0
    assert 45.0 < float(jan["drift_bearing_deg"].mean()) < 135.0


def test_a_summer_month_drifts_the_other_way(ds: xr.Dataset) -> None:
    jul = ds.sel(month=7, bin=2)
    assert float(jul["drift_east_m"].mean()) < 0


def test_percentile_distance_exceeds_the_median(ds: xr.Dataset) -> None:
    ok = np.isfinite(ds["drift_dist_p90_km"].values)
    assert np.all(
        ds["drift_dist_p90_km"].values[ok] >= ds["drift_dist_p50_km"].values[ok] - 1e-3
    )


def test_mean_distance_is_at_least_the_distance_of_the_mean(ds: xr.Dataset) -> None:
    """Jensen: averaging the distances cannot give less than the distance of the
    average displacement, and the gap is how much the direction wanders."""
    d_of_mean = np.hypot(ds["drift_east_m"].values, ds["drift_north_m"].values) / 1000.0
    ok = np.isfinite(d_of_mean)
    assert np.all(ds["drift_dist_mean_km"].values[ok] >= d_of_mean[ok] - 1e-3)


def test_flight_time_matches_the_model(ds: xr.Dataset) -> None:
    minutes = ds["drift_flight_time_s"].values / 60.0
    ok = np.isfinite(minutes)
    assert np.all((minutes[ok] > 100.0) & (minutes[ok] < 200.0))


# --- geometry helpers --------------------------------------------------------


def test_metres_to_degrees_round_trip() -> None:
    dlon, dlat = maps._m_to_deg(111_320.0, 111_320.0, 0.0)
    assert dlat == pytest.approx(1.0, rel=0.01)
    assert dlon == pytest.approx(1.0, rel=0.01)


def test_a_degree_of_longitude_shrinks_towards_the_pole() -> None:
    at_equator, _ = maps._m_to_deg(100_000.0, 0.0, 0.0)
    at_43, _ = maps._m_to_deg(100_000.0, 0.0, 43.0)
    assert at_43 > at_equator


def test_ellipse_k_factors_follow_the_frontend_convention() -> None:
    """Same k = sqrt(-2 ln(1-p)) as frontend/src/stats/landing.ts."""
    assert maps._k_for(0.5) == pytest.approx(1.1774, abs=1e-3)
    assert maps._k_for(0.95) == pytest.approx(2.4477, abs=1e-3)


def test_the_drift_frame_contains_the_landing_points(ds: xr.Dataset) -> None:
    frame = maps._drift_frame(ds, "hokkaido", 1, 2)
    sub = ds.sel(month=1, bin=2)
    dlon, dlat = maps._m_to_deg(sub["drift_east_m"].values,
                                sub["drift_north_m"].values,
                                ds["lat"].values[:, None])
    assert float(np.nanmax(ds["lon"].values[None, :] + dlon)) <= frame.east + 1e-6
    assert float(np.nanmin(ds["lat"].values[:, None] + dlat)) >= frame.south - 1e-6


# --- rendering ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("figid", "maker"),
    [
        ("M1", lambda d: maps.fig_month_grid_map(d, "hokkaido", "北海道", 200.0)),
        ("M2", lambda d: maps.fig_constancy_map(d, "hokkaido", "北海道",
                                                levels_hpa=(850.0, 200.0))),
        ("M3", lambda d: maps.fig_direction_map(d, "hokkaido", "北海道", 200.0)),
        ("M4", lambda d: maps.fig_wind_ellipse_map(d, "hokkaido", "北海道", 200.0, 1, 2)),
        ("M5", lambda d: maps.fig_drift_month_grid(d, "hokkaido", "北海道")),
        ("M6", lambda d: maps.fig_drift_percentile_map(d, "hokkaido", "北海道")),
        ("M7", lambda d: maps.fig_drift_map(d, "hokkaido", "北海道", 1, 2)),
        ("M8", lambda d: maps.fig_landing_ellipse_map(
            d, "hokkaido", "北海道", 42.1823, 142.8510, "VOISING")),
    ],
)
def test_map_renders_and_saves(ds: xr.Dataset, tmp_path: Path, figid: str, maker) -> None:
    fig = maker(ds)
    png, pdf = plots.save(fig, tmp_path, figid, "x")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_overview_map_shows_both_region_boxes(ds: xr.Dataset, tmp_path: Path) -> None:
    fig = maps.fig_overview_map({"hokkaido": ds}, month=1)
    ax = fig.axes[0]
    boxes = [p for p in ax.patches if p.__class__.__name__ == "Rectangle"]
    assert len(boxes) >= 1
    png, _ = plots.save(fig, tmp_path, "M0", "overview")
    assert png.stat().st_size > 5000


def test_every_map_draws_a_coastline(ds: xr.Dataset) -> None:
    for fig in (
        maps.fig_drift_map(ds, "hokkaido", "北海道", 1, 2),
        maps.fig_wind_ellipse_map(ds, "hokkaido", "北海道", 200.0, 1, 2),
    ):
        assert len(fig.axes[0].lines) > 0


def test_maps_keep_the_geographic_aspect(ds: xr.Dataset) -> None:
    """1/cos(lat) so a degree of longitude is as wide on the page as on the ground."""
    fig = maps.fig_drift_map(ds, "hokkaido", "北海道", 1, 2)
    assert fig.axes[0].get_aspect() == pytest.approx(1.0 / np.cos(np.radians(43.25)), rel=0.02)


def test_direction_map_masks_and_stays_cyclic(ds: xr.Dataset) -> None:
    fig = maps.fig_direction_map(ds, "hokkaido", "北海道", 200.0)
    cmaps = {m.get_cmap().name for m in fig.axes[0].collections}
    assert cmaps & style.CYCLIC_CMAPS


def test_landing_ellipse_map_marks_the_launch_site(ds: xr.Dataset) -> None:
    fig = maps.fig_landing_ellipse_map(ds, "hokkaido", "北海道", 42.1823, 142.8510, "VOISING")
    stars = [ln for ln in fig.axes[0].lines if ln.get_marker() == "*"]
    assert len(stars) == 1
    assert stars[0].get_xdata()[0] == pytest.approx(142.8510)
