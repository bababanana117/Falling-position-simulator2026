"""選んだ打ち上げ場所について、飛行条件のばらつきを入れて日ごとの成功確率を出す。

公称値の周りに、上昇速度（±10 %）・破裂高度（±1.5 km）・降下速度（±10 %）を
正規分布で 64 通り振る（1 シグマ）。風は解析値のまま。日ごとに 64 本のうち
何本が目標に落ちたかを、その日の「落下が成功する確率」とする。

入力: results/sites.csv（name, lat, lon）
出力: data/ensemble_<scenario>.npz、results/ensemble_<scenario>.csv

    cd research && python winter_japan/ensemble.py
"""

from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402
from evaluate import judge  # noqa: E402

M = 64
W: C.Winds | None = None
SITES = None
PARAMS = None


def _run(t):
    n = len(SITES)
    lat0 = np.repeat(SITES["lat"].to_numpy(), M)
    lon0 = np.repeat(SITES["lon"].to_numpy(), M)
    elev = np.repeat(SITES["elev"].to_numpy(), M)
    asc, burst, desc = (np.tile(p, n) for p in PARAMS)
    la, lo, dur = C.trajectory(W, t, lat0, lon0, elev, asc, burst, desc)
    return t, la.reshape(n, M), lo.reshape(n, M), dur.reshape(n, M)


def main() -> int:
    global W, SITES, PARAMS
    terrain = C.Terrain()
    sfc = C.Surface()
    SITES = pd.read_csv(C.RESULTS / "sites.csv")
    i, j, _ = terrain.index(SITES["lat"].to_numpy(), SITES["lon"].to_numpy())
    SITES["elev"] = terrain.elev[i, j].clip(0)
    W = C.Winds()
    nt = W.times.size
    rng = np.random.default_rng(2026)
    for key, (_, asc, burst, desc) in C.SCENARIOS.items():
        PARAMS = (rng.normal(asc, 0.1 * asc, M).clip(0.5 * asc),
                  rng.normal(burst, 1500.0, M),
                  rng.normal(desc, 0.1 * desc, M).clip(0.5 * desc))
        n = len(SITES)
        lat = np.empty((nt, n, M), np.float32)
        lon = np.empty_like(lat)
        dur = np.empty_like(lat)
        with mp.get_context("fork").Pool(16) as pool:
            for t, la, lo, du in pool.imap_unordered(_run, range(nt), chunksize=4):
                lat[t], lon[t], dur[t] = la, lo, du
        times = W.times
        # 判定は (day, site*member) にならべて evaluate.judge を使う
        cand = pd.DataFrame({"lat": np.repeat(SITES["lat"], M).to_numpy(),
                             "lon": np.repeat(SITES["lon"], M).to_numpy()})
        j = judge(terrain, sfc, cand, lat.reshape(nt, -1), lon.reshape(nt, -1), times)
        out = {k: v.reshape(nt, n, M).mean(axis=2).astype(np.float32) for k, v in j.items()}
        np.savez_compressed(C.DATA / f"ensemble_{key}.npz", times=times.values,
                            names=SITES["name"].to_numpy(), lat=lat, lon=lon,
                            **{f"p_{k}": v for k, v in out.items()})
        summ = SITES[["name", "lat", "lon", "elev"]].copy()
        for k in ("wind", "land", "launch", "sfc", "total", "f_far_sea", "f_mountain",
                  "f_urban", "f_snow_landing", "seto", "near_sea", "plain_ok"):
            summ[f"p_{k}"] = out[k].mean(axis=0)
        e = (lon - SITES["lon"].to_numpy()[None, :, None]) * C.KM_PER_DEG \
            * np.cos(np.radians(SITES["lat"].to_numpy()))[None, :, None]
        nn = (lat - SITES["lat"].to_numpy()[None, :, None]) * C.KM_PER_DEG
        summ["dist_mean_km"] = np.hypot(e, nn).mean(axis=(0, 2))
        summ["flight_h"] = dur.mean(axis=(0, 2)) / 3600
        summ.to_csv(C.RESULTS / f"ensemble_{key}.csv", index=False, float_format="%.4f")
        print(key)
        print(summ.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
