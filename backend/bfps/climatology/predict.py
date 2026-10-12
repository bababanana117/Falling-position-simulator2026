"""統計モードの予測: 格子点と時期を決め、平均・散らばり・標本・平均の軌道をまとめる。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .model import (
    STANDARD_FLIGHT,
    FlightSettings,
    drift_covariance,
    layer_seconds,
    mean_drift,
    offset_to_latlon,
    sample_offsets,
    solve_rho,
)
from .store import ClimatologyStore, timebin_for
from .trajectory import mean_trajectory

MAX_CELL_DISTANCE_KM = 60.0
PERIOD = "2016–2025"


class OutsideDomainError(ValueError):
    pass


@dataclass
class Prediction:
    timebin: tuple[int, int, str]                 # month, bin, label
    cell: tuple[float, float, float]              # lat, lon, distance_km
    mean_landing: tuple[float, float]
    covariance: np.ndarray
    rho: float
    samples: np.ndarray                           # (n, 2) lat, lon
    trajectory: list[tuple[float, float, float, float]]
    burst_index: int
    flight_time_s: float
    warnings: list[str]


def predict(store: ClimatologyStore, lat: float, lon: float, launch: datetime,
            f: FlightSettings, n_samples: int, seed: int | None) -> Prediction:
    if lon > 180:
        lon -= 360
    cid, clat, clon, dist = store.nearest_cell(lat, lon)
    if dist > MAX_CELL_DISTANCE_KM:
        raise OutsideDomainError(
            f"打ち上げ地点が統計データの範囲外です（最寄りの格子点まで {dist:.0f} km）")
    tb, month, b, label = timebin_for(launch)
    lv = store.levels(cid, tb)
    T = layer_seconds(lv.alt_m, f)
    T_std = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    ev, nv = store.drift_var(cid, tb)
    rho = solve_rho(lv, T_std, ev, nv)
    mean = mean_drift(lv, T)
    cov = drift_covariance(lv, T, rho)
    off = sample_offsets(mean, cov, n_samples, seed)
    s_lat, s_lon = offset_to_latlon(lat, lon, off[:, 0], off[:, 1])
    m_lat, m_lon = offset_to_latlon(lat, lon, np.array([mean[0]]), np.array([mean[1]]))
    traj, burst_index = mean_trajectory(store, tb, lat, lon, f)
    warnings = []
    if f.burst_altitude > float(lv.alt_m[-1]):
        warnings.append(
            f"破裂高度が統計データの最上層（約 {lv.alt_m[-1] / 1000:.0f} km）より上です。"
            "それより上の風は最上層の値で代用しています")
    return Prediction(
        timebin=(month, b, label), cell=(clat, clon, dist),
        mean_landing=(float(m_lat[0]), float(m_lon[0])), covariance=cov, rho=rho,
        samples=np.column_stack([s_lat, s_lon]), trajectory=traj, burst_index=burst_index,
        flight_time_s=float(T.sum()), warnings=warnings)
