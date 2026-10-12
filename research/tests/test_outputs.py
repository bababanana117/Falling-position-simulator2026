"""Derived fields and the three output formats."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr

from windclim.outputs import csv_out, derive, netcdf_out, parquet_out
from windclim.stats import aggregate as agg

YEARS = range(2016, 2019)
CFG = agg.AggregateConfig(years=YEARS, by_hour=False)
LAT = (41.0, 42.0, 43.0)
LON = (140.0, 141.0)
LEVELS = (200.0, 500.0, 850.0)


@pytest.fixture(scope="module")
def stats(tmp_path_factory) -> xr.Dataset:
    from .conftest import write_fake_cache

    root = tmp_path_factory.mktemp("cache")
    write_fake_cache(
        root,
        years=YEARS,
        months=(1, 2),
        lat=LAT,
        lon=LON,
        levels=LEVELS,
        u_of=lambda y, m, d, h: 10.0 + 5.0 * np.sin(d / 3.0),
        v_of=lambda y, m, d, h: 3.0 * np.cos(d / 5.0),
    )
    return agg.aggregate_all(root, "hokkaido", CFG, months=(1, 2))


# --- derived fields ----------------------------------------------------------


def test_add_derived_adds_every_promised_field(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    for name in derive.DERIVED_VARS:
        assert name in out, name


def test_direction_comes_from_the_component_means(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    expected = (np.degrees(np.arctan2(stats["u_mean"], stats["v_mean"])) + 180.0) % 360.0
    assert np.allclose(out["dir_vector_mean"].values, expected.values, atol=1e-3)


def test_derived_fields_are_float32(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    for name in derive.DERIVED_VARS:
        assert out[name].dtype == np.float32, name


def test_ellipse_axes_are_ordered_and_non_negative(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    major = out["ellipse_major"].values
    minor = out["ellipse_minor"].values
    ok = np.isfinite(major) & np.isfinite(minor)
    assert np.all(major[ok] >= minor[ok] - 1e-6)
    assert np.all(minor[ok] >= 0.0)


def test_resultant_length_is_a_fraction(stats: xr.Dataset) -> None:
    r = derive.add_derived(stats)["resultant_length"].values
    ok = np.isfinite(r)
    assert np.all((r[ok] >= 0.0) & (r[ok] <= 1.0 + 1e-6))


def test_standard_error_uses_the_effective_count_not_the_raw_one(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    naive = out["speed_std"].values / np.sqrt(out["n"].values)
    ok = np.isfinite(out["speed_se"].values) & (out["speed_std"].values > 0)
    assert np.all(out["speed_se"].values[ok] >= naive[ok] - 1e-9)
    assert np.any(out["speed_se"].values[ok] > naive[ok] * 1.5)


def test_shear_has_the_same_shape_and_is_non_negative(stats: xr.Dataset) -> None:
    out = derive.add_derived(stats)
    assert out["shear_mag"].shape == out["u_mean"].shape
    ok = np.isfinite(out["shear_mag"].values)
    assert np.all(out["shear_mag"].values[ok] >= 0.0)


def test_shear_detects_a_turning_wind_at_constant_speed() -> None:
    """A layer where the wind veers 90 degrees without changing speed is sheared,
    and a scalar-speed difference would miss it entirely."""
    dims = ("level",)
    ds = xr.Dataset(
        {
            "u_mean": (dims, np.array([10.0, 0.0], dtype=np.float32)),
            "v_mean": (dims, np.array([0.0, 10.0], dtype=np.float32)),
            "alt_geom_mean_m": (dims, np.array([11000.0, 10000.0], dtype=np.float32)),
        },
        coords={"level": [200.0, 300.0]},
    )
    shear = derive.shear_magnitude(ds["u_mean"], ds["v_mean"], ds["alt_geom_mean_m"])
    assert np.allclose(shear.values, np.hypot(10.0, 10.0) / 1.0)


# --- NetCDF ------------------------------------------------------------------


def test_netcdf_round_trip(stats: xr.Dataset, tmp_path: Path) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "s.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert back.sizes["month"] == 2
        assert back.sizes["bin"] == 2
        assert np.allclose(
            back["speed_mean"].values, derive.add_derived(stats)["speed_mean"].values,
            equal_nan=True,
        )


def test_netcdf_leaves_no_part_file(stats: xr.Dataset, tmp_path: Path) -> None:
    netcdf_out.write_netcdf(stats, tmp_path / "s.nc", "hokkaido", CFG)
    assert not (tmp_path / "s.nc.part").exists()


@pytest.mark.parametrize(
    "name",
    ["n", "n_eff", "u_mean", "v_mean", "u_var", "uv_cov", "speed_mean",
     "speed_vector_mean", "constancy", "dir_vector_mean", "z_mean_gpm",
     "alt_geom_mean_m", "shear_mag", "speed_p50", "exceed_gt20"],
)
def test_every_variable_carries_a_long_name_and_units(
    stats: xr.Dataset, tmp_path: Path, name: str
) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "attrs.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert name in back
        assert back[name].attrs.get("long_name")
        assert back[name].attrs.get("units")


def test_percentiles_do_not_claim_a_cf_cell_method(stats: xr.Dataset, tmp_path: Path) -> None:
    """CF has no cell_methods for a percentile; inventing one would be a lie."""
    path = netcdf_out.write_netcdf(stats, tmp_path / "p.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert "cell_methods" not in back["speed_p90"].attrs
        assert "percentile" in back["speed_p90"].attrs["comment"].lower()


def test_global_attributes_carry_licence_and_citation(stats: xr.Dataset, tmp_path: Path) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "g.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert back.attrs["Conventions"] == "CF-1.10"
        assert "NON-COMMERCIAL" in back.attrs["license"]
        assert "CC BY-NC-SA" in back.attrs["license"]
        assert "10.2151/jmsj.2024-004" in back.attrs["references"]
        assert "H1=1-15, H2=16-end of month" in back.attrs["bin_definition"]


def test_coordinates_are_self_describing(stats: xr.Dataset, tmp_path: Path) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "c.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert back["level"].attrs["standard_name"] == "air_pressure"
        assert back["level"].attrs["positive"] == "down"
        assert back["lat"].attrs["units"] == "degrees_north"
        assert back["bin_end_day"].sel(month=2).values.tolist() == [15, 29]


def test_latitude_stays_ascending_through_the_round_trip(
    stats: xr.Dataset, tmp_path: Path
) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "l.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert np.all(np.diff(back["lat"].values) > 0)


def test_no_object_dtypes_are_written(stats: xr.Dataset, tmp_path: Path) -> None:
    path = netcdf_out.write_netcdf(stats, tmp_path / "o.nc", "hokkaido", CFG)
    with xr.open_dataset(path) as back:
        assert all(v.dtype.kind in "fiub" for v in back.variables.values())


# --- Parquet -----------------------------------------------------------------


def test_parquet_schema_is_frozen(stats: xr.Dataset, tmp_path: Path) -> None:
    root = parquet_out.write_parquet(stats, tmp_path / "pq", "hokkaido")
    table = pq.read_table(root)
    for field in parquet_out.PARQUET_SCHEMA:
        if field.name in ("region", "month"):
            continue                      # partition columns are re-typed on read
        assert field.name in table.schema.names, field.name


def test_parquet_row_count_matches_the_grid(stats: xr.Dataset, tmp_path: Path) -> None:
    root = parquet_out.write_parquet(stats, tmp_path / "pq", "hokkaido")
    df = pd.read_parquet(root)
    assert len(df) == 2 * 2 * len(LEVELS) * len(LAT) * len(LON)


def test_parquet_is_partitioned_by_region_and_month(stats: xr.Dataset, tmp_path: Path) -> None:
    root = parquet_out.write_parquet(stats, tmp_path / "pq", "hokkaido")
    assert (root / "region=hokkaido" / "month=1").is_dir()
    assert (root / "region=hokkaido" / "month=2").is_dir()


def test_parquet_carries_the_derived_conveniences(stats: xr.Dataset, tmp_path: Path) -> None:
    """The stated asymmetry: NetCDF keeps moments, Parquet adds what people plot."""
    df = pd.read_parquet(parquet_out.write_parquet(stats, tmp_path / "pq", "hokkaido"))
    for col in ("dir_vector_mean", "ellipse_major", "shear_mag", "alt_geom_mean_km"):
        assert col in df.columns
    for col in ("u_var", "v_var", "uv_cov"):
        assert col in df.columns


def test_parquet_values_agree_with_the_dataset(stats: xr.Dataset, tmp_path: Path) -> None:
    df = pd.read_parquet(parquet_out.write_parquet(stats, tmp_path / "pq", "hokkaido"))
    row = df[(df["month"] == 1) & (df["bin"] == 2) & (df["level_hpa"] == 500.0)].iloc[0]
    cell = stats.sel(month=1, bin=2, level=500.0, lat=row["lat"], lon=row["lon"])
    assert row["speed_mean"] == pytest.approx(float(cell["speed_mean"]), rel=1e-5)


# --- CSV ---------------------------------------------------------------------


def test_curated_tables_are_written(stats: xr.Dataset, tmp_path: Path) -> None:
    written = csv_out.write_csv_tables(stats, tmp_path / "csv", "hokkaido", CFG, manifest=[])
    for name in (
        "bin_calendar.csv",
        "region_grid_hokkaido.csv",
        "layer_summary_hokkaido.csv",
        "best_launch_halves_hokkaido.csv",
        "data_inventory.csv",
    ):
        assert name in written and written[name].exists()


def test_bin_calendar_has_one_row_per_bin(stats: xr.Dataset, tmp_path: Path) -> None:
    written = csv_out.write_csv_tables(stats, tmp_path / "csv", "hokkaido", CFG)
    cal = pd.read_csv(written["bin_calendar.csv"])
    assert len(cal) == 24
    feb = cal[(cal["month"] == 2) & (cal["bin"] == 2)].iloc[0]
    assert feb["end_day_min"] == 28
    assert feb["end_day_max"] == 29


def test_best_halves_is_ranked_ascending_by_speed(stats: xr.Dataset, tmp_path: Path) -> None:
    written = csv_out.write_csv_tables(stats, tmp_path / "csv", "hokkaido", CFG)
    best = pd.read_csv(written["best_launch_halves_hokkaido.csv"])
    assert best["rank"].tolist() == list(range(1, len(best) + 1))
    assert best["mean_speed_0_30km"].is_monotonic_increasing


def test_site_tables_appear_only_where_a_site_exists(
    stats: xr.Dataset, tmp_path: Path
) -> None:
    """Hokkaido has Tokachi in sites.json; Wakayama deliberately has no entry."""
    hok = csv_out.region_sites("hokkaido")
    wak = csv_out.region_sites("wakayama")
    assert not hok.empty
    assert wak.empty


def test_nearest_site_cell_offset_is_reported(stats: xr.Dataset, tmp_path: Path) -> None:
    written = csv_out.write_csv_tables(stats, tmp_path / "csv", "hokkaido", CFG)
    sites = pd.read_csv(written["region_sites_hokkaido.csv"])
    assert "offset_km" in sites.columns
    assert (sites["offset_km"] >= 0).all()


def test_layer_summary_uses_the_flight_layers(stats: xr.Dataset, tmp_path: Path) -> None:
    written = csv_out.write_csv_tables(stats, tmp_path / "csv", "hokkaido", CFG)
    layers = pd.read_csv(written["layer_summary_hokkaido.csv"])
    assert set(layers["layer"]).issubset({name for name, _, _ in csv_out.FLIGHT_LAYERS})


# --- the report's quotable numbers -------------------------------------------


def test_summary_reports_the_sample_counts(stats: xr.Dataset) -> None:
    from windclim.outputs.summary import summarise

    s = summarise(derive.add_derived(stats), "北海道")
    # Named by the label the dataset itself records, so the summary follows the
    # binning instead of assuming it.
    assert s["n"]["1月 前半 (1-15日)"] == 3 * 15 * 4
    assert s["n"]["1月 後半 (16日-月末)"] == 3 * 16 * 4
    assert s["n"]["2月 後半 (16日-月末)"] == (14 + 13 + 13) * 4
    assert not any(k.startswith("4月") for k in s["n"])   # the fixture has no April


def test_summary_effective_count_is_well_below_the_raw_count(stats: xr.Dataset) -> None:
    from windclim.outputs.summary import summarise

    s = summarise(derive.add_derived(stats), "北海道")
    assert 0.0 < s["n_eff_ratio_median"] < 1.0
    assert s["n_eff_median"] < s["n_max"]


def test_summary_names_a_calmest_and_a_roughest_half(stats: xr.Dataset) -> None:
    from windclim.outputs.summary import summarise

    s = summarise(derive.add_derived(stats), "北海道")
    c = s["column_0_30km"]
    assert c["calmest"]["mean_speed"] <= c["roughest"]["mean_speed"]
    assert 1 <= c["calmest"]["month"] <= 12
    assert 1 <= c["calmest"]["bin"] <= 4


def test_summary_formats_without_crashing(stats: xr.Dataset) -> None:
    from windclim.outputs.summary import format_summary, summarise

    text = format_summary(summarise(derive.add_derived(stats), "北海道"))
    assert "標本数" in text
    assert "ISA からのずれ" in text


def test_ceiling_share_is_reproducible_and_bounded(stats: xr.Dataset) -> None:
    """The report quotes these percentages, so they must come from one function."""
    from windclim.outputs.summary import ceiling_share

    ds = derive.add_derived(stats)
    ds.attrs.setdefault("flight_burst_altitude_m", 30000.0)
    c = ceiling_share(ds)
    assert c["ceiling_m"] == pytest.approx(23800.0)
    assert set(c["by_month"]) == {1, 2}
    assert all(v >= 0.0 for v in c["by_month"].values())


def test_ceiling_share_is_zero_when_nothing_is_above_the_ceiling(stats: xr.Dataset) -> None:
    """The fixture's levels top out near 12 km, well below 23.8 km."""
    from windclim.outputs.summary import ceiling_share

    ds = derive.add_derived(stats)
    assert max(ceiling_share(ds)["by_month"].values()) == pytest.approx(0.0, abs=1e-9)


def test_ceiling_share_can_exceed_one_when_layers_oppose() -> None:
    """Two layers pushing opposite ways make the net small while the upper
    contribution stays large -- that is what the >100 % values in the report mean."""
    import numpy as np

    from windclim.outputs.summary import ceiling_share

    level = [10.0, 500.0]
    alt = np.full((1, 1, 2, 1, 1), 0.0)
    alt[0, 0, 0] = 30000.0
    alt[0, 0, 1] = 5000.0
    u = np.zeros((1, 1, 2, 1, 1))
    u[0, 0, 0] = -20.0          # upper easterly
    u[0, 0, 1] = 21.0           # lower westerly, nearly cancelling
    ds = xr.Dataset(
        {
            "alt_geom_mean_m": (("month", "bin", "level", "lat", "lon"), alt),
            "u_mean": (("month", "bin", "level", "lat", "lon"), u),
            "v_mean": (("month", "bin", "level", "lat", "lon"), np.zeros_like(u)),
            "drift_east_m": (("month", "bin", "lat", "lon"), np.zeros((1, 1, 1, 1))),
        },
        coords={"month": [1], "bin": [1], "level": level, "lat": [43.0], "lon": [143.0]},
    )
    assert ceiling_share(ds)["by_month"][1] > 1.0
