"""平均の風で飛ばした 1 本の軌道（地図に描く用）。

dt 秒ごとに高さを進め、その時点の位置の最寄り格子点・その高さを含む層の平均風で
水平に動かす。層は fact_wind の平均高度の中点で区切る（model.layer_seconds と同じ）。
"""

from __future__ import annotations

import numpy as np

from .model import M_PER_DEG, FlightSettings, descent_speed
from .store import ClimatologyStore


def _wind_at(store: ClimatologyStore, timebin_id: int, lat: float, lon: float,
             alt: float) -> tuple[float, float]:
    cid, _, _, _ = store.nearest_cell(lat, lon)
    lv = store.levels(cid, timebin_id)
    mid = 0.5 * (lv.alt_m[:-1] + lv.alt_m[1:])
    k = int(np.searchsorted(mid, alt))
    return float(lv.u_mean[k]), float(lv.v_mean[k])


def mean_trajectory(store: ClimatologyStore, timebin_id: int, lat0: float, lon0: float,
                    f: FlightSettings, dt: float = 30.0
                    ) -> tuple[list[tuple[float, float, float, float]], int]:
    lat, lon, alt, t = lat0, lon0, f.launch_altitude, 0.0
    pts = [(lat, lon, alt, t)]
    # 上昇
    while alt < f.burst_altitude:
        step = min(dt, (f.burst_altitude - alt) / f.ascent_rate)
        u, v = _wind_at(store, timebin_id, lat, lon, alt + 0.5 * f.ascent_rate * step)
        lat += v * step / M_PER_DEG
        lon += u * step / (M_PER_DEG * np.cos(np.radians(lat)))
        alt = min(f.burst_altitude, alt + f.ascent_rate * step)
        t += step
        pts.append((lat, lon, alt, t))
    burst_index = len(pts) - 1
    # 降下
    while alt > 0.0:
        w = float(descent_speed(np.array([alt]), f.descent_rate)[0])
        step = min(dt, alt / w)
        u, v = _wind_at(store, timebin_id, lat, lon, alt - 0.5 * w * step)
        lat += v * step / M_PER_DEG
        lon += u * step / (M_PER_DEG * np.cos(np.radians(lat)))
        alt = max(0.0, alt - w * step)
        t += step
        pts.append((lat, lon, alt, t))
    return pts, burst_index
