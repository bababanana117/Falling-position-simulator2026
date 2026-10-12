"""動画に使う数字と地図を、research/winter_japan の出力から集める。

動画の数字はすべてここから来る。手で書いた値は使わない。

    cd research && python ../video/winter/prepare_data.py     # video/winter/build/data.json, data.npz
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WJ = REPO / "research" / "winter_japan"
sys.path.insert(0, str(REPO / "research"))
sys.path.insert(0, str(WJ))

import common as C
from evaluate import judge
from windclim.figures.coast import load_coastline
from windclim.regions import BBox

OUT = HERE / "build"
IKI = "壱岐（島の中央）"
REGIONS = {
    "北海道": lambda d: d.lat > 41.4,
    "東北": lambda d: (d.lat > 37.0) & (d.lat <= 41.4) & (d.lon > 139.0),
    "関東": lambda d: (d.lat > 34.8) & (d.lat <= 37.0) & (d.lon > 138.8),
    "中部": lambda d: (d.lat > 34.4) & (d.lat <= 37.6) & (d.lon > 136.0) & (d.lon <= 138.8),
    "近畿": lambda d: (d.lat > 33.4) & (d.lat <= 36.0) & (d.lon > 134.3) & (d.lon <= 136.0),
    "四国": lambda d: (d.lat > 32.6) & (d.lat <= 34.4) & (d.lon > 132.0) & (d.lon <= 134.8)
    & ~((d.lat > 34.0) & (d.lon < 133.0)),
    "中国": lambda d: (d.lat > 33.8) & (d.lat <= 35.7) & (d.lon > 130.8) & (d.lon <= 134.3),
    "九州北西": lambda d: (d.lat > 30.9) & (d.lat <= 34.8) & (d.lon <= 132.1)
    & ~((d.lat > 33.8) & (d.lon > 130.8)),
}


def coast(box: BBox, min_pts: int = 6, step: int = 2) -> list:
    rings = []
    for r in load_coastline(box):
        if r[:, 0].max() < box.west or r[:, 0].min() > box.east:
            continue
        if r[:, 1].max() < box.south or r[:, 1].min() > box.north:
            continue
        if len(r) < min_pts:
            continue
        rr = r[::step] if len(r) > 60 else r
        rings.append(np.round(rr, 3).tolist())
    return rings


def iki_members(terrain, sfc, am) -> dict:
    """壱岐の 903 日 × 64 本の落下点と、その 1 本が成功したか（地上気象はアメダス芦辺）。"""
    d = np.load(C.DATA / "ensemble_std.npz", allow_pickle=True)
    names = list(d["names"])
    s = names.index(IKI)
    lat, lon = d["lat"][:, s, :], d["lon"][:, s, :]
    times = pd.DatetimeIndex(d["times"])
    nt, m = lat.shape
    cand = pd.DataFrame({"lat": np.full(m, C.IKI[0]), "lon": np.full(m, C.IKI[1])})
    j = judge(terrain, sfc, cand, lat, lon, times)
    obs = am[am["station"] == "芦辺"].set_index("date").reindex(times.normalize())
    ok_sfc = ((obs["ws09"] <= C.SFC_WIND_MAX) & (obs["precip_09_12"] < C.PRECIP_MAX_MM)).to_numpy()
    valid = obs["ws09"].notna().to_numpy() & obs["precip_09_12"].notna().to_numpy()
    sfc_day = np.where(valid, ok_sfc, j["sfc"][:, 0])
    success = j["land"] & j["launch"] & sfc_day[:, None]
    # 落下点の分類: 0 成功(瀬戸内海) 1 成功(平野) 2 成功(海岸近く) 3 山地 4 沖 5 市街地 6 その他
    cls = np.full(lat.shape, 6, dtype=np.int8)
    cls[j["f_urban"]] = 5
    cls[j["f_far_sea"]] = 4
    cls[j["f_mountain"]] = 3
    cls[j["near_sea"]] = 2
    cls[j["plain_ok"]] = 1
    cls[j["seto"]] = 0
    rng = np.random.default_rng(5)
    k = rng.choice(nt * m, size=2400, replace=False)
    daily = (j["land"].mean(axis=1) * j["launch"][:, 0] * sfc_day).astype(float)
    return {
        "pts": np.column_stack([lat.ravel()[k], lon.ravel()[k], cls.ravel()[k],
                                success.ravel()[k]]).round(3).tolist(),
        "daily": {"dates": [str(x.date()) for x in times], "p": np.round(daily, 3).tolist()},
    }


def iki_coast_rings() -> list:
    """壱岐島の海岸線（OpenStreetMap の natural=coastline）を、端点どうしをつないで閉じた輪にする。"""
    from osm_spots import AREA_QUERIES, fetch_coastline

    spec = dict(key=AREA_QUERIES[0][1], kind="bbox", **AREA_QUERIES[0][3])
    ways = [[(q["lon"], q["lat"]) for q in e["geometry"]]
            for e in fetch_coastline(spec)["elements"] if e.get("geometry")]
    rings = [w for w in ways if w[0] == w[-1]]
    open_ = [w for w in ways if w[0] != w[-1]]
    while open_:
        cur = open_.pop()
        grown = True
        while grown and cur[0] != cur[-1]:
            grown = False
            for k, w in enumerate(open_):
                if w[0] == cur[-1]:
                    cur = cur + w[1:]
                    open_.pop(k)
                    grown = True
                    break
                if w[-1] == cur[0]:
                    cur = w[:-1] + cur
                    open_.pop(k)
                    grown = True
                    break
        rings.append(cur)
    out = []
    for r in rings:
        if len(r) < 4:
            continue
        step = 3 if len(r) > 300 else 1
        out.append([[round(x, 5), round(y, 5)] for x, y in r[::step]])
    return out


def launch_spots() -> dict:
    """打ち上げ候補の広場（spot_figures.py の launch_spots.csv）。"""
    d = pd.read_csv(C.RESULTS / "launch_spots.csv")
    iki = d[d.area_group == "壱岐"].sort_values("clearance_m", ascending=False)
    return {
        "n_total": len(d), "n_iki": len(iki),
        "n_iki_60": int((iki.clearance_m >= 60).sum()),
        "iki_p_std": [round(100 * iki.p_std.min()), round(100 * iki.p_std.max())],
        "iki": [[round(r.best_lat, 5), round(r.best_lon, 5), round(r.clearance_m), r.name]
                for r in iki.itertuples()],
        "iki_coast": iki_coast_rings(),
    }


def sens_wind_amedas(am) -> list:
    """壱岐（標準の飛行）で、地上の風の上限を変えたときの実施できる確率（アメダス芦辺で判定）。"""
    d = np.load(C.DATA / "ensemble_std.npz", allow_pickle=True)
    s = list(d["names"]).index(IKI)
    dates = pd.DatetimeIndex(d["times"]).normalize()
    o = am[am["station"] == "芦辺"].set_index("date").reindex(dates)
    valid = o["ws09"].notna().to_numpy() & o["precip_09_12"].notna().to_numpy()
    out = []
    for w in (3.0, 4.0, 5.0, 7.0, 10.0):
        ok = ((o["ws09"] <= w) & (o["precip_09_12"] < C.PRECIP_MAX_MM)).to_numpy()
        sfc = np.where(valid, ok, d["p_sfc"][:, s] > 0.5)
        out.append([w, round(100 * float((d["p_land"][:, s] * d["p_launch"][:, s] * sfc).mean()))])
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    terrain = C.Terrain()
    sfc = C.Surface()
    am = pd.read_csv(C.DATA / "amedas_09jst.csv", parse_dates=["date"])
    std = json.loads((C.RESULTS / "stats.json").read_text())
    amd = json.loads((C.RESULTS / "stats_amedas.json").read_text())
    sites = pd.read_csv(C.RESULTS / "sites.csv")
    scr = {k: pd.read_csv(C.RESULTS / f"screen_{k}.csv") for k in ("std", "short")}

    # 実施できる確率の格子（0.05 度）
    d = scr["std"]
    lat_v = np.round(np.arange(24.2, 45.6, C.LAUNCH_STEP), 3)
    lon_v = np.round(np.arange(122.9, 145.9, C.LAUNCH_STEP), 3)
    grids = {}
    for key, df in scr.items():
        g = np.full((lat_v.size, lon_v.size), -1, dtype=np.int16)
        i = np.rint((df["lat"] - lat_v[0]) / C.LAUNCH_STEP).astype(int)
        jj = np.rint((df["lon"] - lon_v[0]) / C.LAUNCH_STEP).astype(int)
        g[i, jj] = np.rint(100 * df["p_total"]).astype(int)
        grids[f"ptotal_{key}"] = g
    # 地形の分類（落下の目標）を 0.02 度で。0 海 1 近海 2 瀬戸内海 3 山地 4 市街地 5 平野
    step = 3
    cls = np.zeros(terrain.elev[::step, ::step].shape, dtype=np.int8)
    land, plain = terrain.land[::step, ::step], terrain.plain[::step, ::step]
    urban, seto = terrain.urban[::step, ::step], terrain.seto[::step, ::step]
    near = (~terrain.land & (terrain.sea_dist_km <= C.COAST_KM))[::step, ::step]
    cls[near] = 1
    cls[seto] = 2
    cls[land] = 3
    cls[land & urban] = 4
    cls[land & plain & ~urban] = 5
    np.savez_compressed(OUT / "data.npz", lat=lat_v, lon=lon_v, terrain_cls=cls,
                        terrain_extent=np.array(terrain.extent), **grids)

    # 平均の流され方の矢印（1 度おき）
    arrows = []
    for _, r in d.iterrows():
        if abs(r.lat * 2 - round(r.lat * 2)) < 1e-6 and abs(r.lon - round(r.lon)) < 1e-6:
            arrows.append([r.lat, r.lon, round(r.east_mean_km, 1), round(r.north_mean_km, 1)])

    region = {}
    for name, f in REGIONS.items():
        out = {}
        for key, df in scr.items():
            df = df[df.elev <= 200]
            s = df[f(df)].sort_values("p_total", ascending=False).head(1).iloc[0]
            out[key] = [round(float(s.lat), 2), round(float(s.lon), 2), round(100 * s.p_total)]
        region[name] = out

    def site_rows(key):
        return [{"name": r["name"], "p": round(100 * r["p_total"], 1),
                 "ci": [round(100 * x, 1) for x in r["ci_total"]]} for r in std[key]]

    am_std = {r["name"]: r for r in amd["std"]}
    am_short = {r["name"]: r for r in amd["short"]}
    iki_std, iki_short = am_std[IKI], am_short[IKI]
    osm = pd.read_csv(C.RESULTS / "osm_sites.csv")
    osm = osm[osm["name"].notna()].sort_values("area_m2", ascending=False)
    top_std = sorted(std["std"], key=lambda r: -r["p_total"])[:5]
    top_short = sorted(std["short"], key=lambda r: -r["p_total"])[:5]
    no_seto = [100 * (r["why"]["success_plain_ok"] + r["why"]["success_near_sea"])
               for key in ("std", "short") for r in std[key]]

    data = {
        "n_days": 903, "n_candidates": len(d), "n_members": 64,
        "drift_mean_km": round(float(np.hypot(d.east_mean_km, d.north_mean_km).mean())),
        "coast": coast(BBox(south=24.0, north=46.0, west=122.5, east=146.5)),
        "seto_polygon": C.SETO_POLYGON.round(3).tolist(),
        "sites": sites.to_dict(orient="records"),
        "arrows": arrows,
        "region": region,
        "ranking_std": site_rows("std"), "ranking_short": site_rows("short"),
        "top_std": [[r["name"], round(100 * r["p_total"])] for r in top_std],
        "top_short": [[r["name"], round(100 * r["p_total"])] for r in top_short],
        "seto_share": [round(100 * r["why"]["success_seto"] / r["p_total"]) for r in top_std],
        "no_seto_range": [round(min(no_seto)), round(max(no_seto))],
        "amedas": {k: {"era5": round(100 * v["era5_ok"]), "obs": round(100 * v["amedas_ok"]),
                       "station": v["station"], "ws_median": v["amedas_ws_median"]}
                   for k, v in amd["agreement"].items() if k != "壱岐・郷ノ浦"},
        "iki": {
            "p_std": round(100 * iki_std["p_total"]), "p_short": round(100 * iki_short["p_total"]),
            "ci_std": [round(100 * x) for x in iki_std["ci_total"]],
            "ci_short": [round(100 * x) for x in iki_short["ci_total"]],
            "why": {k: round(100 * v, 1) for k, v in iki_std["why"].items()},
            "weekend_day": round(100 * iki_std["p_total_weekend"]),
            "weekend_either": round(100 * iki_std["p_weekend_either"]),
            "ok_weekend_days": round(iki_std["n_ok_weekend_days_per_season"], 1),
            "within": {k: round(100 * v) for k, v in iki_std["p_success_within_weekends"].items()},
            "by_month": {k: round(100 * v) for k, v in iki_std["by_month"].items()},
        },
        "sens_wind": sens_wind_amedas(am),
        "osm": [{"cand": r.candidate, "name": r.name, "lat": r.lat, "lon": r.lon,
                 "ha": round(r.area_m2 / 1e4, 1)} for r in osm.itertuples()][:8],
    }
    data["iki_members"] = iki_members(terrain, sfc, am)
    data["spots"] = launch_spots()
    import xarray as xr
    with xr.open_dataset(C.DATA / "era5_lsm.nc") as m:
        lsm = float(m["lsm"].squeeze().sel(latitude=C.IKI[0], longitude=C.IKI[1],
                                             method="nearest"))
    data["iki_cell_sea_pct"] = round(100 * (1 - lsm))
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False))
    brief = {k: v for k, v in data.items() if k not in ("coast", "arrows", "iki_members", "sites")}
    print(json.dumps(brief, ensure_ascii=False, indent=0)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
