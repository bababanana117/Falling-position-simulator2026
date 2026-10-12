"""テスト用の小さな統計 DuckDB（本物と同じ列名の一部だけを持つ）。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from bfps.climatology.model import (
    STANDARD_FLIGHT,
    LevelStats,
    drift_covariance,
    layer_seconds,
)

ALT = np.array([100.0, 1500.0, 5000.0, 10000.0, 16000.0, 24000.0, 31000.0, 40000.0])
LEVEL_HPA = np.array([1000.0, 850.0, 500.0, 250.0, 100.0, 30.0, 10.0, 3.0])
CELLS = [(0, 33.0, 130.0), (1, 33.0, 130.5), (2, 33.5, 130.0), (3, 33.5, 130.5)]


def make_db(path: str | Path, *, u: float = 10.0, v: float = 0.0, su: float = 3.0,
            sv: float = 2.0, c: float = 0.0, rho: float = 0.5) -> None:
    n = ALT.size
    lv = LevelStats(ALT, np.full(n, u), np.full(n, v), np.full(n, su**2),
                    np.full(n, sv**2), np.full(n, c))
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    cov = drift_covariance(lv, T, rho)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE dim_grid (cell_id SMALLINT, lat DOUBLE, lon DOUBLE)")
    con.executemany("INSERT INTO dim_grid VALUES (?, ?, ?)", CELLS)
    con.execute("""CREATE TABLE fact_wind (timebin_id SMALLINT, cell_id SMALLINT,
        level_hpa DOUBLE, alt_geom_mean_m DOUBLE, u_mean DOUBLE, v_mean DOUBLE,
        u_var DOUBLE, v_var DOUBLE, uv_cov DOUBLE)""")
    con.execute("""CREATE TABLE fact_drift (timebin_id SMALLINT, cell_id SMALLINT,
        east_var_m2 DOUBLE, north_var_m2 DOUBLE)""")
    rows, drows = [], []
    for tb in range(24):
        for cid, _, _ in CELLS:
            for k in range(n):
                rows.append((tb, cid, LEVEL_HPA[k], ALT[k], u, v, su**2, sv**2, c))
            drows.append((tb, cid, float(cov[0, 0]), float(cov[1, 1])))
    con.executemany("INSERT INTO fact_wind VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.executemany("INSERT INTO fact_drift VALUES (?, ?, ?, ?)", drows)
    con.close()
