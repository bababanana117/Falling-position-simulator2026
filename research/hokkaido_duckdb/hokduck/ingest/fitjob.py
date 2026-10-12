"""Fit the distributions, one calendar month at a time.

This is the only stage that needs the raw cache. The shipped NetCDF holds
moments and percentiles, not the individual analyses, and a distribution
cannot be fitted to a mean -- so the six-hourly fields are read back through
the aggregation pipeline's ``load_month``, which pools all ten years of one
calendar month and cuts to the region in a single call.

Memory is bounded two ways: one month is held at a time (about 215 MB of u
and v), and the cells of a bin are fitted in blocks, so the largest float64
temporary is a few tens of megabytes rather than the 800 MB a whole bin would
need.

Output is one Parquet pair per month, which makes the stage restartable: a
month that fails, or a month whose fits need redoing, can be rerun on its own.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from windclim.stats.aggregate import AggregateConfig, _bin_index, load_month
from windclim.stats.circular import uv_to_met_direction

from ..config import CELL_BLOCK, REGION
from ..fits.circular import fit_all_direction
from ..fits.linear import fit_all_speed
from ..fits.select import assign_selection

log = logging.getLogger(__name__)

__all__ = ["fit_month", "speed_frame_columns", "direction_frame_columns"]

SPEED_PARAM_COLS = (
    "mu_ms", "sigma_ms", "weibull_shape", "weibull_scale_ms", "weibull_loc_ms",
    "uniform_a_ms", "uniform_b_ms",
)
DIR_PARAM_COLS = ("mu_rad", "kappa", "wn_sigma_rad")


def speed_frame_columns() -> tuple[str, ...]:
    return (
        "timebin_id", "level_id", "cell_id", "month", "bin", "level_hpa", "lat", "lon",
        "family", "n", "n_eff", "n_params", *SPEED_PARAM_COLS,
        "loglik", "aic", "delta_aic", "ks_stat", "prob_negative",
        "converged", "is_selected", "is_ambiguous",
    )


def direction_frame_columns() -> tuple[str, ...]:
    return (
        "timebin_id", "level_id", "cell_id", "month", "bin", "level_hpa", "lat", "lon",
        "family", "n", "n_eff", "n_params", "estimator",
        "mu_deg", "mu_rad", "kappa", "wn_sigma_rad", "wn_sigma_deg", "resultant_length",
        "loglik", "aic", "delta_aic", "kuiper_stat",
        "converged", "is_selected", "is_ambiguous",
    )


def _grid_keys(n_level: int, n_lat: int, n_lon: int, levels, lats, lons):
    """The (level, lat, lon) key columns for one bin's flattened cells."""
    li, yi, xi = np.meshgrid(
        np.arange(n_level), np.arange(n_lat), np.arange(n_lon), indexing="ij"
    )
    li, yi, xi = li.ravel(), yi.ravel(), xi.ravel()
    return {
        "level_id": li.astype("int16"),
        "cell_id": (yi * n_lon + xi).astype("int16"),
        "level_hpa": levels[li],
        "lat": lats[yi],
        "lon": lons[xi],
    }


def fit_month(
    cache_root: Path,
    month: int,
    cfg: AggregateConfig,
    out_dir: Path,
    n_eff_lookup: pd.DataFrame,
    *,
    region: str = REGION,
    cell_block: int = CELL_BLOCK,
) -> tuple[Path, Path]:
    """Fit both halves of one calendar month and write two Parquet files.

    ``n_eff_lookup`` carries the effective sample size from the shipped
    statistics, indexed by ``(timebin_id, level_id, cell_id)``. It is not
    recomputed here: it belongs to the same pooled sample and the NetCDF
    already has it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = load_month(cache_root, region, month, cfg)
    bins, _hours = _bin_index(samples.times, cfg.date_convention, cfg.scheme)

    levels = np.asarray(samples.level, dtype=float)
    lats = np.asarray(samples.lat, dtype=float)
    lons = np.asarray(samples.lon, dtype=float)
    n_level, n_lat, n_lon = levels.size, lats.size, lons.size
    ncell = n_level * n_lat * n_lon

    speed_rows: list[pd.DataFrame] = []
    dir_rows: list[pd.DataFrame] = []

    for half in (1, 2):
        sel = (bins[:, 0] == month) & (bins[:, 1] == half)
        if not sel.any():
            raise ValueError(f"no analyses for month {month} bin {half}")
        timebin_id = (month - 1) * 2 + (half - 1)
        u = samples.u[sel]
        v = samples.v[sel]
        n_obs = int(u.shape[0])
        keys = _grid_keys(n_level, n_lat, n_lon, levels, lats, lons)

        neff = (
            n_eff_lookup.reindex(
                pd.MultiIndex.from_arrays(
                    [
                        np.full(ncell, timebin_id, dtype="int16"),
                        keys["level_id"],
                        keys["cell_id"],
                    ]
                )
            )["n_eff"].to_numpy(dtype=float)
        )

        # (n, level, lat, lon) -> (cell, n): one contiguous row per cell, which
        # is the layout every reduction in the fitters wants.
        speed = np.hypot(u, v).reshape(n_obs, ncell).T
        direction = np.radians(
            uv_to_met_direction(
                u.reshape(n_obs, ncell).T.astype(np.float64),
                v.reshape(n_obs, ncell).T.astype(np.float64),
            )
        )
        del u, v

        s_parts, d_parts = [], []
        for start in range(0, ncell, cell_block):
            stop = min(start + cell_block, ncell)
            blk = slice(start, stop)
            block_keys = {k: val[blk] for k, val in keys.items()}
            block_neff = neff[blk]

            s_parts.append(
                _speed_block(
                    np.ascontiguousarray(speed[blk], dtype=np.float64),
                    block_keys, block_neff, timebin_id, month, half, n_obs,
                )
            )
            d_parts.append(
                _direction_block(
                    np.ascontiguousarray(direction[blk], dtype=np.float64),
                    block_keys, block_neff, timebin_id, month, half, n_obs,
                )
            )
        del speed, direction

        speed_rows.append(pd.concat(s_parts, ignore_index=True))
        dir_rows.append(pd.concat(d_parts, ignore_index=True))
        log.info("month %02d bin %d: %d analyses, %d cells fitted", month, half, n_obs, ncell)

    del samples

    speed_path = out_dir / f"fits_speed_{month:02d}.parquet"
    dir_path = out_dir / f"fits_dir_{month:02d}.parquet"
    _write(pd.concat(speed_rows, ignore_index=True), speed_frame_columns(), speed_path)
    _write(pd.concat(dir_rows, ignore_index=True), direction_frame_columns(), dir_path)
    return speed_path, dir_path


def _speed_block(x, keys, neff, timebin_id, month, half, n_obs) -> pd.DataFrame:
    fits = fit_all_speed(x)
    aic = np.vstack([f.aic for f in fits])
    conv = np.vstack([f.converged for f in fits])
    delta, selected, ambiguous = assign_selection(aic, conv, n_obs, neff)

    frames = []
    for i, f in enumerate(fits):
        row = {
            "timebin_id": np.full(x.shape[0], timebin_id, dtype="int16"),
            "month": np.full(x.shape[0], month, dtype="int8"),
            "bin": np.full(x.shape[0], half, dtype="int8"),
            **keys,
            "family": f.family,
            "n": np.full(x.shape[0], n_obs, dtype="int32"),
            "n_eff": neff,
            "n_params": np.full(x.shape[0], f.n_params, dtype="int8"),
            "loglik": f.loglik,
            "aic": f.aic,
            "delta_aic": delta[i],
            "ks_stat": f.ks,
            "prob_negative": f.extra.get("prob_negative", np.full(x.shape[0], np.nan)),
            "converged": f.converged,
            "is_selected": selected[i],
            "is_ambiguous": ambiguous[i],
        }
        for name in SPEED_PARAM_COLS:
            row[name] = f.params.get(name, np.full(x.shape[0], np.nan))
        frames.append(pd.DataFrame(row))
    return pd.concat(frames, ignore_index=True)


def _direction_block(theta, keys, neff, timebin_id, month, half, n_obs) -> pd.DataFrame:
    fits = fit_all_direction(theta)
    aic = np.vstack([f.aic for f in fits])
    conv = np.vstack([f.converged for f in fits])
    delta, selected, ambiguous = assign_selection(aic, conv, n_obs, neff)

    from ..fits.circular import circular_moments, wrap_pi

    m = circular_moments(wrap_pi(theta))
    mu_deg = np.degrees(m.mu) % 360.0

    frames = []
    for i, f in enumerate(fits):
        sigma_rad = f.params.get("wn_sigma_rad", np.full(theta.shape[0], np.nan))
        row = {
            "timebin_id": np.full(theta.shape[0], timebin_id, dtype="int16"),
            "month": np.full(theta.shape[0], month, dtype="int8"),
            "bin": np.full(theta.shape[0], half, dtype="int8"),
            **keys,
            "family": f.family,
            "n": np.full(theta.shape[0], n_obs, dtype="int32"),
            "n_eff": neff,
            "n_params": np.full(theta.shape[0], f.n_params, dtype="int8"),
            "estimator": f.estimator,
            "mu_deg": mu_deg if f.family != "circular_uniform" else np.full(theta.shape[0], np.nan),
            "mu_rad": f.params.get("mu_rad", np.full(theta.shape[0], np.nan)),
            "kappa": f.params.get("kappa", np.full(theta.shape[0], np.nan)),
            "wn_sigma_rad": sigma_rad,
            "wn_sigma_deg": np.degrees(sigma_rad),
            "resultant_length": m.rbar,
            "loglik": f.loglik,
            "aic": f.aic,
            "delta_aic": delta[i],
            "kuiper_stat": f.kuiper,
            "converged": f.converged,
            "is_selected": selected[i],
            "is_ambiguous": ambiguous[i],
        }
        frames.append(pd.DataFrame(row))
    return pd.concat(frames, ignore_index=True)


def _write(df: pd.DataFrame, columns, path: Path) -> None:
    df = df[list(columns)]
    # Sorted on the key tuple so DuckDB's zone maps prune tightly on the
    # filters people actually write.
    df = df.sort_values(["timebin_id", "level_id", "cell_id", "family"], kind="stable")
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path, compression="zstd")
