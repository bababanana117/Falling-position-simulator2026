"""Long-format Parquet, for anyone who would rather use pandas than xarray.

The asymmetry with the NetCDF is deliberate and worth stating in one place:

* **NetCDF is canonical.** It stores the moments -- ``u_var``, ``v_var``,
  ``uv_cov`` -- and nothing that can be reconstructed from them.
* **Parquet is convenient.** It stores the moments *and* the things people
  actually plot: directions, ellipse axes, shear, altitude in km.

So the two never disagree; Parquet just saves a step. It is partitioned by region
and month so a single month can be read without touching the rest.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from .derive import add_derived

__all__ = ["PARQUET_SCHEMA", "to_dataframe", "write_parquet"]

_KEY_FIELDS = [
    pa.field("region", pa.dictionary(pa.int32(), pa.string())),
    pa.field("month", pa.int8()),
    pa.field("bin", pa.int8()),
    pa.field("level_hpa", pa.float32()),
    pa.field("lat", pa.float32()),
    pa.field("lon", pa.float32()),
    pa.field("n", pa.int32()),
    pa.field("n_eff", pa.float32()),
]

_VALUE_FIELDS = [
    "u_mean", "v_mean", "u_var", "v_var", "uv_cov",
    "speed_mean", "speed_vector_mean", "speed_std", "speed_max", "speed_se",
    "speed_p10", "speed_p25", "speed_p50", "speed_p75", "speed_p90", "speed_p95",
    "exceed_gt10", "exceed_gt20", "exceed_gt30", "exceed_gt40",
    "constancy", "lag1_autocorr",
    "dir_vector_mean", "dir_unit_mean", "resultant_length", "circ_sd_deg",
    "ellipse_major", "ellipse_minor", "ellipse_angle_deg",
    "z_mean_gpm", "z_std_gpm", "alt_geom_mean_m", "alt_geom_mean_km", "shear_mag",
]

#: Drift is a property of the whole column, so it has no level axis. It is joined
#: onto every row of its (month, half, lat, lon) column rather than given a file
#: of its own -- one table is easier to use than two that must be merged.
_DRIFT_FIELDS = [
    "drift_east_m", "drift_north_m", "drift_dist_mean_km", "drift_dist_p50_km",
    "drift_dist_p90_km", "drift_dist_p95_km", "drift_dist_max_km",
    "drift_bearing_deg", "drift_east_var", "drift_north_var", "drift_cov",
    "drift_flight_time_s",
]

PARQUET_SCHEMA = pa.schema(
    _KEY_FIELDS + [pa.field(n, pa.float32()) for n in _VALUE_FIELDS + _DRIFT_FIELDS]
)


def to_dataframe(ds: xr.Dataset, region: str, *, derived: bool = True) -> pd.DataFrame:
    """One row per ``(month, half, level, lat, lon)``."""
    full = add_derived(ds) if derived else ds
    keep = [v for v in ("n", "n_eff", *_VALUE_FIELDS, *_DRIFT_FIELDS) if v in full.data_vars]
    core = full[keep].drop_vars(
        [v for v in full.coords if v not in ("month", "bin", "level", "lat", "lon")],
        errors="ignore",
    )
    df = core.to_dataframe().reset_index()
    df = df.rename(columns={"level": "level_hpa"})
    df.insert(0, "region", region)

    for field in PARQUET_SCHEMA:
        if field.name not in df.columns:
            df[field.name] = np.nan
    df = df[[f.name for f in PARQUET_SCHEMA]]
    df["region"] = df["region"].astype("category")
    for col in ("month", "bin"):
        df[col] = df[col].astype("int8")
    df["n"] = df["n"].fillna(0).astype("int32")
    for f in PARQUET_SCHEMA:
        if f.name not in ("region", "month", "bin", "n"):
            df[f.name] = df[f.name].astype("float32")
    return df


def write_parquet(ds: xr.Dataset, root: Path, region: str, *, derived: bool = True) -> Path:
    """Write a Hive-partitioned dataset at ``root/region=.../month=.../``.

    ``region`` is a partition value, so a second bin scheme has to go under a
    different ``root`` rather than a decorated region name -- otherwise the two
    schemes would land in the same partition and read back as one table.
    """
    df = to_dataframe(ds, region, derived=derived)
    table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pq.write_to_dataset(
        table,
        root_path=str(root),
        partition_cols=["region", "month"],
        compression="zstd",
        existing_data_behavior="delete_matching",
    )
    return root
