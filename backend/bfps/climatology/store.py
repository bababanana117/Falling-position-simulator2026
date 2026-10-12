"""統計風 DuckDB（JRA-3Q 2016–2025、日本全国 v2）の読み出し。

読み取り専用で 1 つの接続を使い回す。格子点は dim_grid を起動時に読み込み、最寄りは
numpy で探す（本物の DB のマクロ nearest_cell に依らないので、テスト用の小さな DB でも動く）。
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np

from .model import LevelStats

JST = timezone(timedelta(hours=9))
EARTH_RADIUS_KM = 6371.0


def timebin_for(dt: datetime) -> tuple[int, int, int, str]:
    """日時 → (timebin_id, month, bin, ラベル)。日付は JST で数える。tz が無ければ UTC とみなす。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    j = dt.astimezone(JST)
    b = 1 if j.day <= 15 else 2
    return (j.month - 1) * 2 + (b - 1), j.month, b, f"{j.month}月{'前半' if b == 1 else '後半'}"


class ClimatologyStore:
    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        self.path = p
        self._con = duckdb.connect(str(p), read_only=True)
        self._lock = threading.Lock()
        g = self._con.execute("SELECT cell_id, lat, lon FROM dim_grid ORDER BY cell_id").fetchnumpy()
        self._cell = g["cell_id"].astype(int)
        self._lat = g["lat"].astype(float)
        self._lon = g["lon"].astype(float)
        self.levels = lru_cache(maxsize=4096)(self._levels)

    def nearest_cell(self, lat: float, lon: float) -> tuple[int, float, float, float]:
        la1, lo1 = np.radians(lat), np.radians(lon)
        la2, lo2 = np.radians(self._lat), np.radians(self._lon)
        h = (np.sin((la2 - la1) / 2) ** 2
             + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
        d = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h))
        i = int(np.argmin(d))
        return int(self._cell[i]), float(self._lat[i]), float(self._lon[i]), float(d[i])

    def _query(self, sql: str, params: list) -> dict:
        with self._lock:
            return self._con.execute(sql, params).fetchnumpy()

    def _levels(self, cell_id: int, timebin_id: int) -> LevelStats:
        r = self._query(
            """SELECT alt_geom_mean_m, u_mean, v_mean, u_var, v_var, uv_cov
               FROM fact_wind WHERE cell_id = ? AND timebin_id = ?
               ORDER BY level_hpa DESC""", [cell_id, timebin_id])
        if r["alt_geom_mean_m"].size == 0:
            raise KeyError((cell_id, timebin_id))
        return LevelStats(*(np.asarray(r[k], dtype=float) for k in
                            ("alt_geom_mean_m", "u_mean", "v_mean", "u_var", "v_var", "uv_cov")))

    def drift_var(self, cell_id: int, timebin_id: int) -> tuple[float, float]:
        r = self._query("""SELECT east_var_m2, north_var_m2 FROM fact_drift
                           WHERE cell_id = ? AND timebin_id = ?""", [cell_id, timebin_id])
        if r["east_var_m2"].size == 0:
            raise KeyError((cell_id, timebin_id))
        return float(r["east_var_m2"][0]), float(r["north_var_m2"][0])
