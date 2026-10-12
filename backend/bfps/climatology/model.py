"""統計モードの計算（DuckDB に依らない純粋な関数）。

落下点の東・北の移動は、層 k の平均風と滞在時間 T_k の和になる。散らばりは、層ごとの風の
共分散 Σ_k と、層どうしの相関 ρ（一定）から作る。ρ は標準の飛行の実際の散らばり
（DuckDB の fact_drift）を再現するように解く。式は spec の「計算の方法」を参照。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.atmosphere import RHO0_ISA, density_isa

M_PER_DEG = 111195.0


@dataclass(frozen=True)
class FlightSettings:
    ascent_rate: float
    burst_altitude: float
    descent_rate: float          # 海面換算
    launch_altitude: float = 0.0


STANDARD_FLIGHT = FlightSettings(5.0, 30000.0, 6.0, 0.0)


@dataclass(frozen=True)
class LevelStats:
    """1 格子点・1 時期の気圧面ごとの統計。すべて高度の低い順。"""
    alt_m: np.ndarray
    u_mean: np.ndarray
    v_mean: np.ndarray
    u_var: np.ndarray
    v_var: np.ndarray
    uv_cov: np.ndarray


def descent_speed(alt_m: np.ndarray, sea_level_rate: float) -> np.ndarray:
    rho = np.array([max(density_isa(max(float(a), 0.0)), 1e-4) for a in alt_m])
    return sea_level_rate * np.sqrt(RHO0_ISA / rho)


def layer_seconds(alt_m: np.ndarray, f: FlightSettings) -> np.ndarray:
    """各気圧面の層（隣の面との中点で区切る）に、上昇と降下で合わせて何秒いるか。"""
    alt = np.asarray(alt_m, dtype=float)
    mid = 0.5 * (alt[:-1] + alt[1:])
    lower = np.concatenate([[-1.0e4], mid])
    upper = np.concatenate([mid, [1.0e5]])
    up = np.maximum(np.clip(upper, f.launch_altitude, f.burst_altitude)
                    - np.clip(lower, f.launch_altitude, f.burst_altitude), 0.0)
    down = np.maximum(np.clip(upper, 0.0, f.burst_altitude)
                      - np.clip(lower, 0.0, f.burst_altitude), 0.0)
    return up / f.ascent_rate + down / descent_speed(alt, f.descent_rate)


def mean_drift(levels: LevelStats, T: np.ndarray) -> tuple[float, float]:
    return float((T * levels.u_mean).sum()), float((T * levels.v_mean).sum())


def _sqrt_2x2(u_var: float, v_var: float, c: float) -> np.ndarray:
    """2×2 の共分散行列の対称な平方根（負の固有値は 0 にする）。"""
    w, q = np.linalg.eigh(np.array([[u_var, c], [c, v_var]]))
    return (q * np.sqrt(np.clip(w, 0.0, None))) @ q.T


def _parts(levels: LevelStats, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """独立な部分 A = Σ T_k² Σ_k と、完全相関の部分 B = M Mᵀ（M = Σ T_k L_k）。"""
    A = np.zeros((2, 2))
    M = np.zeros((2, 2))
    for k in range(T.size):
        if T[k] == 0.0:
            continue
        S = np.array([[levels.u_var[k], levels.uv_cov[k]],
                      [levels.uv_cov[k], levels.v_var[k]]])
        A += T[k] ** 2 * S
        M += T[k] * _sqrt_2x2(levels.u_var[k], levels.v_var[k], levels.uv_cov[k])
    return A, M @ M.T


def drift_covariance(levels: LevelStats, T: np.ndarray, rho: float) -> np.ndarray:
    A, B = _parts(levels, T)
    return (1.0 - rho) * A + rho * B


def solve_rho(levels: LevelStats, T_std: np.ndarray, east_var: float,
              north_var: float) -> float:
    """標準の飛行の分散（fact_drift）を再現する ρ。東西・南北で解いて平均し 0〜1 に収める。"""
    A, B = _parts(levels, T_std)
    vals = []
    for i, obs in ((0, east_var), (1, north_var)):
        den = B[i, i] - A[i, i]
        if abs(den) > 1e-9 * max(B[i, i], 1.0):
            vals.append((obs - A[i, i]) / den)
    if not vals:
        return 0.0
    return float(np.clip(np.mean(vals), 0.0, 1.0))


def sample_offsets(mean: tuple[float, float], cov: np.ndarray, n: int,
                   seed: int | None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.multivariate_normal(np.asarray(mean, dtype=float), cov, size=n,
                                   method="eigh")


def offset_to_latlon(lat0: float, lon0: float, east_m: np.ndarray,
                     north_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = lat0 + np.asarray(north_m) / M_PER_DEG
    lon = lon0 + np.asarray(east_m) / (M_PER_DEG * np.cos(np.radians(lat0)))
    return lat, lon
