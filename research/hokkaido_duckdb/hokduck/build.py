"""Build the database.

    python -m hokduck.build --stage all

Four stages, each restartable:

1. **facts** -- reshape the shipped NetCDF into rows and stage them as Parquet.
   Needs only ``out/netcdf/``, takes about a minute.
2. **fits** -- read the raw six-hourly cache back and fit six distributions to
   every cell. This is the long one, about six minutes, and it writes one
   Parquet pair per month so a single month can be redone.
3. **load** -- create the schema, load the staged Parquet, attach the comments
   and the metadata, build the views, then compact.
4. **verify** -- run ``sql/90_verify.sql`` and refuse to declare success if
   anything fails.

Staging through Parquet rather than inserting directly buys restartability,
the fastest load path DuckDB has, and an intermediate artefact to diff between
runs.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import platform
import resource
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from windclim.config import CACHE_ROOT
from windclim.stats.aggregate import AggregateConfig

from .config import (
    DB_PATH,
    DB_STEM,
    PROJECT_ROOT,
    SOURCE_NETCDF_NAME,
    SQL_DIR,
    STAGING_DIR,
    source_netcdf,
)
from .ingest import dims, facts, meta
from .ingest.fitjob import fit_month
from .schema import TABLES_BY_NAME, comment_statements, create_statements
from .verify import run_checks

log = logging.getLogger("hokduck.build")

STAGE_CHOICES = ("all", "facts", "fits", "load", "verify")


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _write_parquet(df: pd.DataFrame, table: str, path: Path) -> int:
    """Stage one table, keeping only declared columns, in key order."""
    spec = TABLES_BY_NAME[table]
    names = [c.name for c in spec.columns]
    missing = [n for n in names if n not in df.columns]
    if missing:
        raise ValueError(f"{table}: builder did not produce {missing}")
    out = df[names]
    if spec.order_by:
        out = out.sort_values(list(spec.order_by), kind="stable")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), path, compression="zstd")
    return len(out)


# ------------------------------------------------------------- stage 1 ----
def stage_facts(staging: Path) -> dict[str, int]:
    source = source_netcdf()
    log.info("stage 1: reshaping %s", source.name)
    counts = {}
    with xr.open_dataset(source) as raw:
        ds = raw.load()
    grid = dims.build_dim_grid(ds, ds.attrs["rose_cell_lat"], ds.attrs["rose_cell_lon"])
    rose_cell = int(grid.loc[grid["is_rose_cell"], "cell_id"].iloc[0])

    for name, frame in (
        ("dim_grid", grid),
        ("dim_level", dims.build_dim_level(ds)),
        ("dim_timebin", dims.build_dim_timebin(ds)),
        ("dim_hour", dims.build_dim_hour(ds)),
        ("dim_sector", dims.build_dim_sector(ds)),
        ("dim_speed_class", dims.build_dim_speed_class(ds)),
        ("fact_wind", facts.build_fact_wind(ds)),
        ("fact_wind_rose", facts.build_fact_wind_rose(ds, rose_cell)),
        ("fact_wind_diurnal", facts.build_fact_wind_diurnal(ds)),
        ("fact_drift", facts.build_fact_drift(ds)),
    ):
        counts[name] = _write_parquet(frame, name, staging / f"{name}.parquet")
        log.info("  %-20s %8d rows", name, counts[name])
    return counts


# ------------------------------------------------------------- stage 2 ----
def stage_fits(staging: Path, months: list[int]) -> None:
    log.info("stage 2: fitting distributions for months %s", months)
    wind = pd.read_parquet(staging / "fact_wind.parquet",
                           columns=["timebin_id", "level_id", "cell_id", "n_eff"])
    lookup = wind.set_index(["timebin_id", "level_id", "cell_id"])[["n_eff"]]
    cfg = AggregateConfig()
    for month in months:
        t0 = time.perf_counter()
        fit_month(CACHE_ROOT, month, cfg, staging, lookup)
        log.info("  month %02d done in %.0f s (peak RSS %.0f MB)",
                 month, time.perf_counter() - t0, peak_rss_mb())


# ------------------------------------------------------------- stage 3 ----
def stage_load(staging: Path, db_path: Path, provenance: list[dict]) -> None:
    tmp = db_path.with_suffix(".tmp.duckdb")
    for p in (tmp, Path(str(tmp) + ".wal")):
        p.unlink(missing_ok=True)
    log.info("stage 3: loading into %s", tmp.name)

    with duckdb.connect(str(tmp)) as con:
        for stmt in create_statements():
            con.execute(stmt)

        for name in ("dim_grid", "dim_level", "dim_timebin", "dim_hour", "dim_sector",
                     "dim_speed_class", "fact_wind", "fact_wind_rose",
                     "fact_wind_diurnal", "fact_drift"):
            _copy_parquet(con, name, staging / f"{name}.parquet")

        _copy_parquet(con, "fact_speed_fit", staging / "fits_speed_*.parquet")
        _copy_parquet(con, "fact_dir_fit", staging / "fits_dir_*.parquet")

        # Metadata last: it records what the rest of the build just did.
        source = source_netcdf()
        with xr.open_dataset(source) as ds:
            _insert(con, "meta_dataset", meta.build_meta_dataset(
                ds, source, sha256(source)))
        _insert(con, "meta_column", meta.build_meta_column())
        _insert(con, "meta_fit_family", meta.build_meta_fit_family())
        _insert(con, "meta_reference", meta.build_meta_reference())
        _insert(con, "meta_license", meta.build_meta_license())
        if provenance:
            _insert(con, "meta_provenance", pd.DataFrame(provenance))

        for stmt in comment_statements():
            con.execute(stmt)
        con.execute((SQL_DIR / "05_views.sql").read_text(encoding="utf-8"))
        con.execute((SQL_DIR / "06_macros.sql").read_text(encoding="utf-8"))
        con.execute("ANALYZE")
        con.execute("CHECKPOINT")

    # DuckDB does not reclaim space in place, so the shipped file is produced
    # by copying the finished database into a fresh one. Attaching both to an
    # in-memory connection avoids having to guess the implicit database name.
    db_path.unlink(missing_ok=True)
    with duckdb.connect() as con:
        con.execute(f"ATTACH '{tmp}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{db_path}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    tmp.unlink(missing_ok=True)
    Path(str(tmp) + ".wal").unlink(missing_ok=True)
    log.info("  wrote %s (%.0f MB)", db_path.name, db_path.stat().st_size / 1e6)


def _copy_parquet(con: duckdb.DuckDBPyConnection, table: str, source: Path | str) -> None:
    spec = TABLES_BY_NAME[table]
    cols = ", ".join(
        f"CAST({c.name} AS {c.type}) AS {c.name}" for c in spec.columns
    )
    order = f" ORDER BY {', '.join(spec.order_by)}" if spec.order_by else ""
    con.execute(f"INSERT INTO {table} SELECT {cols} FROM read_parquet('{source}'){order}")
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    log.info("  %-20s %8d rows loaded", table, n)


def _insert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    spec = TABLES_BY_NAME[table]
    names = [c.name for c in spec.columns]
    frame = df.reindex(columns=names)
    con.register("_staged", frame)
    cols = ", ".join(f"CAST({c.name} AS {c.type}) AS {c.name}" for c in spec.columns)
    con.execute(f"INSERT INTO {table} SELECT {cols} FROM _staged")
    con.unregister("_staged")
    log.info("  %-20s %8d rows inserted", table, len(frame))


# --------------------------------------------------------------- driver ----
def _month_list(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    bad = [m for m in out if not 1 <= m <= 12]
    if bad:
        raise ValueError(f"months out of range: {bad}")
    return sorted(set(out))


def _preflight() -> None:
    import scipy

    if tuple(int(x) for x in duckdb.__version__.split(".")[:2]) < (1, 1):
        raise SystemExit(f"duckdb >= 1.1 required, found {duckdb.__version__}")
    if tuple(int(x) for x in scipy.__version__.split(".")[:2]) < (1, 14):
        raise SystemExit(f"scipy >= 1.14 required, found {scipy.__version__}")
    if int(np.__version__.split(".")[0]) < 2:
        raise SystemExit(f"numpy >= 2.0 required, found {np.__version__}")
    source = source_netcdf()
    if not source.exists():
        raise SystemExit(
            f"aggregated statistics not found: {source}\n"
            "Produce them with the upstream aggregation pipeline, or point\n"
            "HOKDUCK_SOURCE_NETCDF at the file."
        )


def _write_sidecar(db_path: Path) -> None:
    """The licence must travel with the file, not only inside it."""
    src = PROJECT_ROOT / "LICENSE-DATA.md"
    if src.exists():
        shutil.copyfile(src, db_path.with_suffix(".LICENSE.md"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Hokkaido wind DuckDB.")
    ap.add_argument("--stage", choices=STAGE_CHOICES, default="all")
    ap.add_argument("--months", default="1-12", help="e.g. 1-3,7")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--staging", type=Path, default=STAGING_DIR)
    ap.add_argument("--force", action="store_true", help="overwrite an existing database")
    ap.add_argument("--keep-staging", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    _preflight()
    if a.db.exists() and not a.force and a.stage in ("all", "load"):
        raise SystemExit(f"{a.db} exists; pass --force to replace it")

    months = _month_list(a.months)
    provenance: list[dict] = []
    t_start = time.perf_counter()

    def record(step: str, started: datetime, rows: int | None = None, note: str = "") -> None:
        provenance.append({
            "step": step, "tool": "hokduck", "tool_version": DB_STEM,
            "started_at": started, "finished_at": datetime.now(UTC).replace(tzinfo=None),
            "host": platform.node(),
            "input_name": SOURCE_NETCDF_NAME, "input_sha256": None,
            "rows_written": rows, "peak_rss_mb": peak_rss_mb(), "note": note,
        })

    if a.stage in ("all", "facts"):
        t0 = datetime.now(UTC).replace(tzinfo=None)
        counts = stage_facts(a.staging)
        record("facts", t0, sum(counts.values()), "reshaped from the shipped NetCDF")

    if a.stage in ("all", "fits"):
        t0 = datetime.now(UTC).replace(tzinfo=None)
        stage_fits(a.staging, months)
        record("fits", t0, None, f"months {months}")

    if a.stage in ("all", "load"):
        t0 = datetime.now(UTC).replace(tzinfo=None)
        record("load", t0, None, "staged Parquet into DuckDB")
        stage_load(a.staging, a.db, provenance)
        _write_sidecar(a.db)

    if a.stage in ("all", "verify"):
        with duckdb.connect(str(a.db), read_only=True) as con:
            failed = run_checks(con)
        if failed:
            log.error("%d checks failed: %s", len(failed), ", ".join(failed))
            return 1

    if a.stage == "all" and not a.keep_staging:
        log.info("staging kept at %s (pass --keep-staging to silence this)", a.staging)

    log.info("done in %.0f s, peak RSS %.0f MB", time.perf_counter() - t_start, peak_rss_mb())
    return 0


if __name__ == "__main__":
    sys.exit(main())
