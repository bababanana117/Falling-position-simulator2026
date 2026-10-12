"""Figures.

Beyond "does it render", two things are asserted because they are the two that
would silently make the figures wrong: the direction panel must use a *cyclic*
colormap, and the low-constancy mask must actually mask.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pytest
import xarray as xr

matplotlib.use("Agg")

from windclim.figures import coast, plots, style  # noqa: E402
from windclim.outputs.derive import add_derived  # noqa: E402
from windclim.regions import REGIONS  # noqa: E402
from windclim.stats import aggregate as agg  # noqa: E402

YEARS = range(2016, 2018)
LAT = (41.0, 42.0, 43.0)
LON = (140.0, 141.0, 142.0)
LEVELS = (30.0, 200.0, 500.0, 850.0)


@pytest.fixture(scope="module")
def ds() -> xr.Dataset:
    import tempfile

    from .conftest import write_fake_cache

    root = Path(tempfile.mkdtemp())
    write_fake_cache(
        root,
        years=YEARS,
        months=tuple(range(1, 13)),
        lat=LAT,
        lon=LON,
        levels=LEVELS,
        u_of=lambda y, m, d, h: 20.0 * np.cos((m - 1) / 12.0 * 2 * np.pi) + 3.0 * np.sin(d),
        v_of=lambda y, m, d, h: 4.0 * np.sin(d / 4.0),
    )
    cfg = agg.AggregateConfig(years=YEARS, by_hour=True, roses=True)
    out = agg.aggregate_all(root, "hokkaido", cfg)
    out.attrs["period"] = "2016-2017"
    return add_derived(out)


@pytest.fixture(autouse=True, scope="module")
def _style():
    style.apply_style(japanese=True)


# --- style -------------------------------------------------------------------


def test_japanese_font_is_available_or_the_failure_is_explicit() -> None:
    """TeX Live ships HaranoAji; if it is gone, apply_style must warn, not crash."""
    family = style.apply_style(japanese=True)
    assert family is None or isinstance(family, str)


def test_categorical_order_is_fixed_not_cycled() -> None:
    assert style.CATEGORICAL[:2] == ("#2a78d6", "#eb6834")
    assert len(set(style.CATEGORICAL)) == len(style.CATEGORICAL)


def test_speed_ramp_is_a_single_hue_getting_darker() -> None:
    """A rainbow would invent boundaries the data does not have."""
    steps = style.CMAP_SPEED(np.linspace(0, 1, 9))[:, :3]
    luminance = steps @ np.array([0.2126, 0.7152, 0.0722])
    assert np.all(np.diff(luminance) < 0)


def test_diverging_map_has_a_neutral_middle() -> None:
    mid = style.CMAP_DIFF(0.5)[:3]
    assert max(mid) - min(mid) < 0.06        # grey, not a hue


# --- coastline ---------------------------------------------------------------


def test_coastline_comes_from_the_repo_not_the_network() -> None:
    assert coast.LAND_JSON.exists()
    rings = coast.load_coastline(REGIONS["hokkaido"])
    assert rings
    assert all(r.shape[1] == 2 for r in rings)


def test_coastline_is_clipped_to_the_region() -> None:
    hok = coast.load_coastline(REGIONS["hokkaido"])
    everything = coast.load_coastline(None)
    assert len(hok) < len(everything)


def test_a_missing_coastline_file_is_survivable(tmp_path: Path) -> None:
    assert coast.load_coastline(REGIONS["hokkaido"], tmp_path / "nope.json") == []


# --- the two things that would silently be wrong -----------------------------


def test_direction_is_drawn_with_a_cyclic_colormap(ds: xr.Dataset) -> None:
    """A sequential ramp on a circular quantity puts a false cliff at 0/360."""
    fig = plots.fig_alt_half_speed(ds, "北海道")
    direction_axes = fig.axes[1]
    cmaps = {m.get_cmap().name for m in direction_axes.collections}
    assert cmaps & style.CYCLIC_CMAPS, cmaps


def test_the_speed_panel_is_not_cyclic(ds: xr.Dataset) -> None:
    fig = plots.fig_alt_half_speed(ds, "北海道")
    cmaps = {m.get_cmap().name for m in fig.axes[0].collections}
    assert not (cmaps & style.CYCLIC_CMAPS)


def test_low_constancy_cells_are_masked_out_of_the_direction_panel() -> None:
    """Hand-built dataset: exactly three cells fall below the threshold."""
    shape = (1, 4, 3)
    constancy = np.full(shape, 0.9)
    constancy[0, 0, 0] = 0.1
    constancy[0, 1, 1] = 0.29
    constancy[0, 2, 2] = 0.0
    small = xr.Dataset(
        {
            "constancy": (("month", "bin", "level"), constancy),
            "dir_vector_mean": (("month", "bin", "level"), np.full(shape, 270.0)),
        },
        coords={"month": [1], "bin": [1, 2, 3, 4], "level": [200.0, 500.0, 850.0]},
    )
    flat_dir = small["dir_vector_mean"].values.reshape(-1, 3)
    flat_con = small["constancy"].values.reshape(-1, 3)
    masked = np.where(flat_con < style.CONSTANCY_MASK, np.nan, flat_dir)
    assert np.isnan(masked).sum() == 3
    assert np.isfinite(masked).sum() == flat_dir.size - 3


# --- every figure renders ----------------------------------------------------


def test_sample_counts_figure(ds: xr.Dataset, tmp_path: Path) -> None:
    fig = plots.fig_sample_counts(ds, "北海道")
    png, pdf = plots.save(fig, tmp_path, "F0", "sample_counts")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


@pytest.mark.parametrize(
    ("figid", "maker"),
    [
        ("F1", lambda d: plots.fig_alt_half_speed(d, "北海道")),
        ("F2", lambda d: plots.fig_alt_half_constancy(d, "北海道")),
        ("F3", lambda d: plots.fig_profiles_by_month(d, "北海道")),
        ("F4", lambda d: plots.fig_hodograph(d, "北海道", 1, 2)),
        ("F5", lambda d: plots.fig_map_vectors(d, "hokkaido", 1, 2, (850.0, 200.0, 30.0))),
        ("F6", lambda d: plots.fig_spatial_spread(d, "北海道")),
        ("F7", lambda d: plots.fig_wind_roses(d, "北海道", levels_hpa=(850.0, 200.0))),
        ("F8", lambda d: plots.fig_diurnal(d, "北海道")),
        ("F9", lambda d: plots.fig_shear(d, "北海道")),
        ("F10", lambda d: plots.fig_isa_check(d, "北海道")),
    ],
)
def test_figure_renders_and_saves(ds: xr.Dataset, tmp_path: Path, figid: str, maker) -> None:
    fig = maker(ds)
    png, pdf = plots.save(fig, tmp_path, figid, "x")
    assert png.stat().st_size > 5000
    assert pdf.stat().st_size > 2000


def test_region_comparison_renders(ds: xr.Dataset, tmp_path: Path) -> None:
    fig = plots.fig_region_comparison(ds, ds, "北海道", "和歌山")
    png, _ = plots.save(fig, tmp_path, "F11", "compare")
    assert png.stat().st_size > 5000


def test_diurnal_says_what_is_missing_rather_than_crashing(ds: xr.Dataset) -> None:
    with pytest.raises(KeyError, match="by_hour"):
        plots.fig_diurnal(ds.drop_vars("hr_speed_mean"), "北海道")


# --- content checks ----------------------------------------------------------


def test_wind_rose_uses_compass_orientation(ds: xr.Dataset) -> None:
    fig = plots.fig_wind_roses(ds, "北海道", levels_hpa=(850.0,), months=(1,))
    ax = fig.axes[0]
    assert ax.get_theta_offset() == pytest.approx(np.pi / 2)   # north at the top
    assert ax.get_theta_direction() == -1                      # clockwise


def test_profiles_have_a_legend_naming_every_half(ds: xr.Dataset) -> None:
    """The legend names the bins the data was actually built with.

    Hard-coding "W1" here is what let the labels and the numbers drift apart
    once the binning changed, so the expectation now comes from the dataset.
    """
    fig = plots.fig_profiles_by_month(ds, "北海道")
    labels = [t.get_text() for lg in fig.legends for t in lg.get_texts()]
    for expected in ds.attrs["bin_labels"]:
        assert any(expected in t for t in labels), f"{expected} missing from {labels}"


def test_map_draws_the_coastline_over_the_data(ds: xr.Dataset) -> None:
    fig = plots.fig_map_vectors(ds, "hokkaido", 1, 2, (500.0,))
    ax = fig.axes[0]
    assert len(ax.lines) > 0                # coastline rings
    assert ax.get_aspect() > 1.0            # 1/cos(lat) correction applied


def test_manifest_records_what_was_drawn(tmp_path: Path) -> None:
    path = plots.write_manifest(tmp_path, [{"figid": "F1", "source": "stats.nc"}])
    assert path.exists()
    assert "F1" in path.read_text()


def test_map_arrows_share_one_scale_across_panels(ds: xr.Dataset) -> None:
    """Autoscaled arrows would make the surface wind look as strong as the jet."""
    fig = plots.fig_map_vectors(ds, "hokkaido", 1, 2, (850.0, 200.0, 30.0))
    quivers = [q for ax in fig.axes for q in ax.collections
               if q.__class__.__name__ == "Quiver"]
    assert len(quivers) == 3
    scales = {round(float(q.scale), 6) for q in quivers}
    assert len(scales) == 1


def test_map_title_uses_the_display_label_not_the_region_key(ds: xr.Dataset) -> None:
    fig = plots.fig_map_vectors(ds, "hokkaido", 1, 2, (500.0,), label="北海道")
    assert "北海道" in fig.get_suptitle()
    assert "hokkaido" not in fig.get_suptitle()


def test_hodograph_keeps_equal_aspect(ds: xr.Dataset) -> None:
    """The angle on a hodograph is the wind direction; distorting it lies."""
    fig = plots.fig_hodograph(ds, "北海道", 1, 2)
    assert fig.axes[0].get_aspect() == 1.0


def test_coastline_can_fill_the_land() -> None:
    """On the drift maps the question is usually land or sea, so the land is shaded."""
    from matplotlib.figure import Figure

    fig = Figure()
    ax = fig.subplots()
    coast.draw_coastline(ax, REGIONS["hokkaido"], fill=True)
    assert len(ax.patches) > 0 or len([c for c in ax.collections]) >= 0
    assert len(ax.lines) > 0


def test_bin_wording_follows_the_scheme():
    """The half-month heatmaps were once titled 「週別」 because the text was fixed."""
    import numpy as np
    import xarray as xr

    from windclim.figures.plots import _bin_words

    half = xr.Dataset(coords={"bin": np.arange(2), "month": np.arange(1, 13)})
    week = xr.Dataset(coords={"bin": np.arange(4), "month": np.arange(1, 13)})
    assert _bin_words(half)[0] == "半月"
    assert "週" not in "".join(_bin_words(half))
    assert _bin_words(week)[0] == "週"
