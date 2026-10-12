"""全候補の落下点を判定し、打ち上げ場所ごとの確率を出す（公称の飛行条件）。

確率は 2016–2025 年の 12・1・2 月の 903 日（9 時 JST）に対する割合。

* p_wind   : 落下点が目標（平野・瀬戸内海・海岸近くの海）に入る。雪は問わない
* p_land   : 上に加えて、陸の落下点に雪がない
* p_launch : 打ち上げ地点に雪がない
* p_sfc    : 地上気象（風 5 m/s 以下・降水 0.5 mm 未満）
* p_total  : 以上をすべて満たす（実施できる日）

    cd research && python winter_japan/evaluate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402


def judge(terrain: C.Terrain, sfc: C.Surface, cand: pd.DataFrame, lat: np.ndarray,
          lon: np.ndarray, times: pd.DatetimeIndex, coast_km: float = C.COAST_KM,
          wind_max: float = C.SFC_WIND_MAX, precip_max: float = C.PRECIP_MAX_MM) -> dict:
    """(day, point) の真偽値をまとめて返す。"""
    cls = C.landing_classes(terrain, lat, lon)
    k = sfc.day_index(times.normalize())
    snow_land = sfc.field("sd", k, lat, lon) >= C.SNOW_SD_M
    la0, lo0 = cand["lat"].to_numpy(), cand["lon"].to_numpy()
    snow_launch = sfc.field("sd", k, la0, lo0) >= C.SNOW_SD_M
    ws = sfc.field("ws", k, la0, lo0)
    tp = sfc.field("tp", k, la0, lo0)
    target_land = cls["plain"] & ~cls["urban"]
    near_sea = ~cls["land"] & cls["inside"] & (cls["sea_dist"] <= coast_km)
    water_ok = cls["seto"] | near_sea
    wind_ok = target_land | water_ok
    land_ok = (target_land & ~snow_land) | water_ok
    sfc_ok = (ws <= wind_max) & (tp < precip_max)
    return {
        "wind": wind_ok, "land": land_ok, "launch": ~snow_launch, "sfc": sfc_ok,
        "total": land_ok & ~snow_launch & sfc_ok,
        # 失敗の内訳（落下点）
        "f_far_sea": ~cls["land"] & ~water_ok,
        "f_mountain": cls["land"] & ~cls["plain"],
        "f_urban": cls["plain"] & cls["urban"],
        "f_snow_landing": target_land & snow_land,
        "seto": cls["seto"], "near_sea": near_sea & ~cls["seto"], "plain_ok": target_land,
    }


def main() -> int:
    terrain = C.Terrain()
    sfc = C.Surface()
    cand = pd.read_csv(C.DATA / "candidates.csv")
    C.RESULTS.mkdir(exist_ok=True)
    for key in C.SCENARIOS:
        d = np.load(C.DATA / f"landings_{key}.npz")
        times = pd.DatetimeIndex(d["times"])
        res = cand.copy()
        daily = {}
        for k0 in range(0, len(cand), 3000):
            sl = slice(k0, k0 + 3000)
            j = judge(terrain, sfc, cand.iloc[sl], d["lat"][:, sl], d["lon"][:, sl], times)
            for name, arr in j.items():
                daily.setdefault(name, []).append(arr)
        daily = {k: np.concatenate(v, axis=1) for k, v in daily.items()}
        for name, arr in daily.items():
            res[f"p_{name}"] = arr.mean(axis=0)
        for m in (12, 1, 2):
            sel = times.month == m
            for name in ("wind", "land", "launch", "sfc", "total"):
                res[f"p_{name}_m{m}"] = daily[name][sel].mean(axis=0)
        e = (d["lon"] - cand["lon"].to_numpy()) * C.KM_PER_DEG * np.cos(np.radians(cand["lat"].to_numpy()))
        n = (d["lat"] - cand["lat"].to_numpy()) * C.KM_PER_DEG
        res["dist_mean_km"] = np.hypot(e, n).mean(axis=0)
        res["east_mean_km"] = e.mean(axis=0)
        res["north_mean_km"] = n.mean(axis=0)
        res["flight_h"] = d["dur"].mean(axis=0) / 3600
        res.to_csv(C.RESULTS / f"screen_{key}.csv", index=False, float_format="%.4f")
        np.savez_compressed(C.DATA / f"daily_{key}.npz", times=d["times"],
                            **{k: np.packbits(v, axis=0) for k, v in daily.items()})
        top = res.sort_values("p_total", ascending=False).head(10)
        print(key)
        print(top[["lat", "lon", "p_wind", "p_land", "p_launch", "p_sfc", "p_total"]].to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
