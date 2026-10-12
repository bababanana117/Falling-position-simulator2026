"""OpenStreetMap で見つけた広場ごとに、実施できる確率を計算する。

ensemble.py と同じ 64 通りの飛行条件のばらつきで、広場の最もひらけた点
（osm_spots.py の best_lat, best_lon）から上げた 903 日の落下点を判定する。
地上気象は、壱岐はアメダス芦辺、平戸・唐津の周辺は各アメダス、それ以外は ERA5。

入力: results/osm_spots.csv
出力: results/osm_spots_prob.csv（osm_spots.csv に p_std, p_short などを足したもの）

    cd research && python winter_japan/spot_probability.py
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
#: 地域 → 地上気象に使うアメダス（無ければ ERA5）
STATION = {"壱岐": "芦辺", "平戸": "平戸", "唐津・呼子": "唐津", "唐津・相知": "唐津"}

W: C.Winds | None = None
PTS = None
PARAMS = None


def _run(t):
    n = len(PTS)
    lat0 = np.repeat(PTS["lat"].to_numpy(), M)
    lon0 = np.repeat(PTS["lon"].to_numpy(), M)
    elev = np.repeat(PTS["elev"].to_numpy(), M)
    asc, burst, desc = (np.tile(p, n) for p in PARAMS)
    la, lo, _ = C.trajectory(W, t, lat0, lon0, elev, asc, burst, desc)
    return t, la.reshape(n, M), lo.reshape(n, M)


def main() -> int:
    global W, PTS, PARAMS
    spots = pd.read_csv(C.RESULTS / "osm_spots.csv")
    terrain = C.Terrain()
    sfc = C.Surface()
    am = pd.read_csv(C.DATA / "amedas_09jst.csv", parse_dates=["date"])
    PTS = pd.DataFrame({"lat": spots["best_lat"], "lon": spots["best_lon"]})
    i, j, _ = terrain.index(PTS["lat"].to_numpy(), PTS["lon"].to_numpy())
    PTS["elev"] = terrain.elev[i, j].clip(0)
    W = C.Winds()
    nt, n = W.times.size, len(PTS)
    dates = W.times.normalize()
    rng = np.random.default_rng(2026)          # ensemble.py と同じ乱数の種
    for key, (_, asc, burst, desc) in C.SCENARIOS.items():
        PARAMS = (rng.normal(asc, 0.1 * asc, M).clip(0.5 * asc),
                  rng.normal(burst, 1500.0, M),
                  rng.normal(desc, 0.1 * desc, M).clip(0.5 * desc))
        lat = np.empty((nt, n, M), np.float32)
        lon = np.empty_like(lat)
        with mp.get_context("fork").Pool(16) as pool:
            for t, la, lo in pool.imap_unordered(_run, range(nt), chunksize=4):
                lat[t], lon[t] = la, lo
        cand = pd.DataFrame({"lat": np.repeat(PTS["lat"], M).to_numpy(),
                             "lon": np.repeat(PTS["lon"], M).to_numpy()})
        jd = judge(terrain, sfc, cand, lat.reshape(nt, -1), lon.reshape(nt, -1), W.times)
        land = jd["land"].reshape(nt, n, M).mean(axis=2)
        launch = jd["launch"].reshape(nt, n, M)[:, :, 0]
        sfc_era = jd["sfc"].reshape(nt, n, M)[:, :, 0]
        sfc_use = sfc_era.astype(float).copy()
        src = np.full(n, "ERA5", dtype=object)
        for g, st in STATION.items():
            sel = (spots["area_group"] == g).to_numpy()
            if not sel.any():
                continue
            o = am[am["station"] == st].set_index("date").reindex(dates)
            ok = ((o["ws09"] <= C.SFC_WIND_MAX) & (o["precip_09_12"] < C.PRECIP_MAX_MM)).to_numpy()
            valid = o["ws09"].notna().to_numpy() & o["precip_09_12"].notna().to_numpy()
            sfc_use[:, sel] = np.where(valid[:, None], ok[:, None], sfc_era[:, sel])
            src[sel] = f"アメダス{st}"
        spots[f"p_land_{key}"] = land.mean(axis=0).round(4)
        spots[f"p_{key}"] = (land * launch * sfc_use).mean(axis=0).round(4)
        spots["sfc_source"] = src
        print(key, "done", flush=True)
    spots.to_csv(C.RESULTS / "osm_spots_prob.csv", index=False)
    cols = ["area_group", "name", "best_lat", "best_lon", "clearance_m", "p_std", "p_short",
            "sfc_source"]
    print(spots.sort_values("p_std", ascending=False)[cols].head(25).to_string())
    print(spots.groupby("area_group")[["p_std", "p_short"]].agg(["min", "max", "count"]).round(3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
