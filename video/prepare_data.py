"""動画に使う数字を、研究の出力から 1 つの JSON にまとめる。

動画の中の数字はすべてここから来る。手で書いた値は使わない。

    cd research && python ../video/prepare_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RESEARCH = REPO / "research"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(RESEARCH / "winter_sw"))

import analyze as W  # noqa: E402

from windclim.figures.coast import load_coastline  # noqa: E402
from windclim.regions import BBox  # noqa: E402
from windclim.stats.drift import FlightProfile  # noqa: E402

CSV = RESEARCH / "out" / "csv"
NC = RESEARCH / "out" / "netcdf"
MAP = BBox(south=30.0, north=46.0, west=128.0, east=147.0)
IKI = (33.8, 129.7)


def hokkaido_jet() -> list[float]:
    """代表地点、200 hPa の平均風速を 24 の半月ビンで。"""
    d = pd.read_csv(CSV / "site_profile_hokkaido.csv")
    d = d[d["level_hpa"] == 200].sort_values(["month", "bin"])
    return [round(float(v), 1) for v in d["speed_mean"]]


def roses() -> dict[str, list[float]]:
    """北海道上空 10 hPa の風配（16 方位、吹いてくる向き）。"""
    with xr.open_dataset(NC / "jra3q_windclim_hokkaido_2016-2025_v1.nc") as ds:
        out = {}
        for key, (m, b) in {"jul": (7, 2), "oct": (10, 2)}.items():
            h = ds["rose_counts"].sel(month=m, bin=b, level=10.0).sum("speed_class").values
            out[key] = [round(float(x), 4) for x in h / h.sum()]
    return out


def winter_arrows() -> list[dict]:
    """1 月の平均落下位置の矢印。西日本は新たに取った範囲、北海道は本文の統計から。"""
    arrows = []
    s, alt = W.month_samples(1)
    drift = W.month_drift(s, alt, FlightProfile())
    e = drift["east_km"].mean(axis=0)
    n = drift["north_km"].mean(axis=0)
    terrain = W.Terrain()
    for i in range(1, drift["lat"].size, 4):
        for j in range(1, drift["lon"].size, 5):
            la, lo = float(drift["lat"][i]), float(drift["lon"][j])
            if not (MAP.south < la < MAP.north and MAP.west < lo < MAP.east):
                continue
            ti, tj, ins = terrain.index(np.array([la]), np.array([lo]))
            if not (ins[0] and terrain.land[ti[0], tj[0]]):
                continue
            arrows.append({"lat": la, "lon": lo, "e": round(float(e[i, j]), 1),
                           "n": round(float(n[i, j]), 1)})
    with xr.open_dataset(NC / "jra3q_windclim_hokkaido_2016-2025_v1.nc") as ds:
        jan = ds.sel(month=1)
        de = jan["drift_east_m"].mean("bin").values / 1000.0
        dn = jan["drift_north_m"].mean("bin").values / 1000.0
        for i in range(1, ds.sizes["lat"], 6):
            for j in range(2, ds.sizes["lon"], 8):
                arrows.append({"lat": float(ds["lat"][i]), "lon": float(ds["lon"][j]),
                               "e": round(float(de[i, j]), 1), "n": round(float(dn[i, j]), 1)})
    return arrows


def summer_arrows() -> list[dict]:
    """7 月後半の平均落下位置（3 領域の代表）。drift_*.csv の値。"""
    out = []
    for region, lat, lon in (("hokkaido", 43.0, 143.3), ("wakayama", 33.9, 135.4),
                             ("ehime", 32.96, 132.55)):
        d = pd.read_csv(CSV / f"drift_{region}.csv").set_index(["month", "bin"])
        r = d.loc[(7, 2)]
        out.append({"region": region, "lat": lat, "lon": lon,
                    "dist": round(float(r["dist_mean_km"])),
                    "bearing": round(float(r["bearing_deg"])),
                    "e": round(float(r["east_km"]), 1), "n": round(float(r["north_km"]), 1)})
    return out


def iki_landings() -> dict:
    """壱岐から 1・2 月に標準の飛行条件で上げた場合の落下点と、成功の割合。"""
    W.OPTIONS["allow_seto"] = True
    terrain, snow = W.Terrain(), W.Snow()
    pts, oks = [], []
    for month in (1, 2):
        s, alt = W.month_samples(month)
        drift = W.month_drift(s, alt, FlightProfile())
        sel = np.ones(drift["times"].size, dtype=bool)
        _, _, lat, lon = W.landings(np.array([IKI[0]]), np.array([IKI[1]]), drift, sel)
        i, j, ins = terrain.index(lat, lon)
        dates = drift["times"].normalize()
        ok = ((terrain.target[i, j] & ins & ~snow.has_snow(dates, lat, lon))
              | (terrain.seto[i, j] & ins))
        ok &= ~snow.has_snow(dates, np.full_like(lat, IKI[0]), np.full_like(lon, IKI[1]))
        pts.append(np.column_stack([lat[:, 0], lon[:, 0]]))
        oks.append(ok[:, 0])
    pts, ok = np.concatenate(pts), np.concatenate(oks)
    rng = np.random.default_rng(3)
    k = rng.choice(len(pts), size=500, replace=False)
    summary = json.loads((RESEARCH / "winter_sw" / "results" / "seto" / "summary.json").read_text())
    best = summary["best_by_scenario"]
    return {
        "launch": IKI,
        "points": [[round(float(a), 3), round(float(b), 3), bool(c)]
                   for (a, b), c in zip(pts[k], ok[k], strict=True)],
        "p_standard": round(float(ok.mean()), 3),
        "p_iki_standard_table": best["標準（5 m/s・30 km）"]["p_good_mean"],
        "p_best": best["速い上昇・破裂 20 km"]["p_good_mean"],
        "best_site": [best["速い上昇・破裂 20 km"]["lat"], best["速い上昇・破裂 20 km"]["lon"]],
        "seto_polygon": W.SETO_POLYGON.round(3).tolist(),
    }


def coast() -> list[list[list[float]]]:
    rings = []
    for r in load_coastline(MAP):
        if r[:, 0].max() < MAP.west or r[:, 0].min() > MAP.east:
            continue
        if r[:, 1].max() < MAP.south or r[:, 1].min() > MAP.north:
            continue
        if len(r) < 4:
            continue
        rings.append(np.round(r, 3).tolist())
    return rings


def main() -> int:
    data = {
        "jet_hokkaido_200hpa": hokkaido_jet(),
        "jet_winter_200hpa": {"北海道": 40.2, "和歌山": 75.5, "愛媛": 75.4},
        "roses_10hpa": roses(),
        "winter_arrows": winter_arrows(),
        "summer_arrows": summer_arrows(),
        "iki": iki_landings(),
        "coast": coast(),
        "map_box": [MAP.south, MAP.north, MAP.west, MAP.east],
    }
    # 冬の 200 hPa は第 4・5 章の値（numbers と同じ）を、netcdf から確かめる
    for region, label in (("hokkaido", "北海道"), ("wakayama", "和歌山"), ("ehime", "愛媛")):
        from windclim.stats.spatial import area_mean  # noqa: PLC0415
        with xr.open_dataset(NC / f"jra3q_windclim_{region}_2016-2025_v1.nc") as ds:
            sp = area_mean(ds, "speed_mean").sel(level=200.0, month=[12, 1, 2]).mean().item()
        assert abs(sp - data["jet_winter_200hpa"][label]) < 0.6, (region, sp)
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False))
    print({k: (len(v) if isinstance(v, list) else "ok") for k, v in data.items()})
    print("iki", data["iki"]["p_standard"], data["iki"]["p_iki_standard_table"], data["iki"]["p_best"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
