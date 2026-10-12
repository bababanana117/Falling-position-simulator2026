"""1・2 月に、雪がなく、市街地を避けた平野に落ちやすい打ち上げ場所を西日本で探す。

風は JRA-3Q（2016–2025 年の 1・2 月、6 時間ごと）。本文と同じ閉形式で、
解析 1 回ごとの落下点を求める（風は打ち上げ時刻・地点で固定）。その落下点を

* 地形（NOAA NCEI の DEM、約 500 m 間隔）で「平野か」
* 人口集中地区（国土数値情報 A16、2020 年）で「市街地か」
* 積雪（ERA5 の積雪深、同じ日の 12 時 JST）で「雪があるか」

に照らし、打ち上げ場所ごとに「目標に落ちる割合」を半月ごとに出す。目標は
「雪がなく、DID の外の平野」。打ち上げ場所そのものに雪がある日は失敗に数える。
海上回収は考えないので、海に落ちれば失敗である。

飛行条件を変えると飛行距離が変わるので、5 つの条件で同じ評価をする。

    python -m windclim.cli fetch --box sw --months 1,2
    python winter_sw/fetch_snow.py
    python winter_sw/fetch_did.py
    python winter_sw/analyze.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.path import Path as MplPath

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(HERE))

from fetch_snow import LANDING_BOX  # noqa: E402

from windclim.config import CACHE_ROOT  # noqa: E402
from windclim.fetch.terrain import load_terrain, size_for  # noqa: E402
from windclim.figures.coast import draw_coastline  # noqa: E402
from windclim.figures.plots import save  # noqa: E402
from windclim.figures.style import CATEGORICAL, CMAP_SPEED, INK, apply_style  # noqa: E402
from windclim.regions import SOUTHWEST, BBox  # noqa: E402
from windclim.stats.aggregate import AggregateConfig, load_month  # noqa: E402
from windclim.stats.altitude import geopotential_to_geometric  # noqa: E402
from windclim.stats.drift import FlightProfile, displacements  # noqa: E402

KM_PER_DEG = 111.195
#: 平野の定義: 陸地で、標高 100 m 以下、傾斜 2 度以下
PLAIN_MAX_ELEV_M = 100.0
PLAIN_MAX_SLOPE_DEG = 2.0
#: 雪ありの定義: 積雪深（水当量）1 mm 以上。新雪ならおよそ 1 cm にあたる
SNOW_SD_M = 0.001
#: 打ち上げ候補を並べる格子の間隔（度）。風は最寄りの JRA-3Q 格子点のものを使う
LAUNCH_STEP = 0.1
BINS = ((1, 1, "1月前半"), (1, 2, "1月後半"), (2, 1, "2月前半"), (2, 2, "2月後半"))

#: 比べる飛行条件。名前 → (上昇速度 m/s, 破裂高度 m)。降下は海面相当 6 m/s で共通
SCENARIOS = {
    "標準（5 m/s・30 km）": (5.0, 30000.0),
    "速い上昇（8 m/s・30 km）": (8.0, 30000.0),
    "低い破裂（5 m/s・20 km）": (5.0, 20000.0),
    "速い上昇・破裂 25 km": (8.0, 25000.0),
    "速い上昇・破裂 20 km": (8.0, 20000.0),
}
STANDARD = "標準（5 m/s・30 km）"

#: 地方の名前。判定は area_of() で、まず海岸線で本州・九州・四国を分け、
#: 本州の中だけを経度・緯度で分ける。
AREA_NAMES = ("中部（長野・岐阜・山梨・北陸）", "東海（静岡・愛知・三重）", "近畿",
              "中国", "四国", "九州", "離島（五島・隠岐など）", "南西諸島")


#: 比べるための代表地点（関東より西・南）。緯度, 経度
SITES = {
    "浜松": (34.71, 137.73), "名古屋": (35.18, 136.91), "津": (34.73, 136.51),
    "大阪": (34.69, 135.50), "和歌山": (34.23, 135.17), "潮岬": (33.45, 135.76),
    "徳島": (34.07, 134.55), "高知": (33.56, 133.53), "室戸": (33.29, 134.15),
    "岡山": (34.66, 133.92), "広島": (34.40, 132.46), "松山": (33.84, 132.77),
    "愛南": (32.96, 132.55), "鳥取": (35.50, 134.24), "松江": (35.47, 133.05),
    "福岡": (33.59, 130.40), "大分": (33.24, 131.61), "熊本": (32.80, 130.71),
    "宮崎": (31.91, 131.42), "鹿児島": (31.56, 130.56), "種子島": (30.40, 130.97),
    "奄美": (28.38, 129.49), "那覇": (26.21, 127.68), "石垣": (24.34, 124.16),
    "金沢": (36.56, 136.65),
}

#: 適性の地図は本州・四国・九州に絞る。南西諸島はどの条件でもほぼ 0 % で、
#: 全域を描くと本土が小さくなって読めない（値は表と CSV にある）。
MAP_BOX = BBox(south=30.8, north=37.5, west=128.3, east=140.5)

#: 瀬戸内海の範囲。関門海峡・豊予海峡（関崎〜佐田岬）・鳴門海峡・紀淡海峡を
#: 境界とし、紀伊水道と豊後水道は含めない。陸地にかかる部分は、海の判定（DEM）で
#: 落とすので、陸側の頂点は内陸に置いてある。経度, 緯度
SETO_POLYGON = np.array([
    (130.95, 34.05), (130.95, 33.85), (131.20, 33.60), (131.45, 33.15),
    (131.88, 33.20), (131.87, 33.27), (132.02, 33.34),          # 豊予海峡
    (132.50, 33.45), (133.00, 33.80), (134.00, 34.00),
    (134.65, 34.23), (134.75, 34.20), (135.05, 34.27),          # 鳴門・紀淡海峡
    (135.30, 34.40), (135.55, 34.80), (134.50, 34.95), (133.00, 34.75),
    (132.00, 34.55), (131.20, 34.25),
])

#: 瀬戸内海への着水を成功に数えるか（--allow-seto で切り替える）
OPTIONS = {"allow_seto": False}

FIG_DIR = RESEARCH / "out" / "figures" / "winter_sw"
RES_DIR = HERE / "results"


# --- 地形・市街地・積雪 -----------------------------------------------------------

def _rasterize_did(shape: tuple[int, int], box, dlat: float, dlon: float) -> np.ndarray:
    """DID のポリゴンを DEM と同じ格子に塗る。穴（内側の輪）は抜く。"""
    cache = HERE / "data" / f"did_mask_{shape[0]}x{shape[1]}.npy"
    if cache.exists():
        return np.load(cache)
    mask = np.zeros(shape, dtype=bool)
    files = sorted((HERE / "data" / "did").glob("A16-20_*_DID.geojson"))
    if not files:
        raise SystemExit("DID のファイルがありません。先に fetch_did.py を実行してください")
    for f in files:
        for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
            geom = feat["geometry"]
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            for rings in polys:
                ext = np.asarray(rings[0])
                i0 = max(int((box.north - ext[:, 1].max()) / dlat), 0)
                i1 = min(int((box.north - ext[:, 1].min()) / dlat) + 1, shape[0])
                j0 = max(int((ext[:, 0].min() - box.west) / dlon), 0)
                j1 = min(int((ext[:, 0].max() - box.west) / dlon) + 1, shape[1])
                if i1 <= i0 or j1 <= j0:
                    continue
                ii, jj = np.mgrid[i0:i1, j0:j1]
                pts = np.column_stack([box.west + (jj.ravel() + 0.5) * dlon,
                                       box.north - (ii.ravel() + 0.5) * dlat])
                inside = MplPath(ext).contains_points(pts)
                for hole in rings[1:]:
                    inside &= ~MplPath(np.asarray(hole)).contains_points(pts)
                mask[i0:i1, j0:j1] |= inside.reshape(ii.shape)
    np.save(cache, mask)
    return mask


class Terrain:
    """DEM と DID から、陸・平野・市街地のマスクを作り、緯度経度で引けるようにする。"""

    def __init__(self) -> None:
        w, h = size_for(LANDING_BOX, width=4000)
        tile = load_terrain(LANDING_BOX, width=w, height=h, allow_fetch=True)
        self.elev = tile.elevation
        self.box = tile.bbox
        ny, nx = self.elev.shape
        self.dlat = (self.box.north - self.box.south) / ny
        self.dlon = (self.box.east - self.box.west) / nx
        lat = self.box.north - (np.arange(ny) + 0.5) * self.dlat
        dy = self.dlat * KM_PER_DEG * 1000.0
        dx = self.dlon * KM_PER_DEG * 1000.0 * np.cos(np.radians(lat))[:, None]
        gy, gx = np.gradient(self.elev)
        slope = np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))
        self.land = self.elev > 1.0
        self.plain = self.land & (self.elev <= PLAIN_MAX_ELEV_M) & (slope <= PLAIN_MAX_SLOPE_DEG)
        self.urban = _rasterize_did(self.elev.shape, self.box, self.dlat, self.dlon) & self.land
        self.target = self.plain & ~self.urban
        ii, jj = np.mgrid[0:ny, 0:nx]
        pts = np.column_stack([self.box.west + (jj.ravel() + 0.5) * self.dlon,
                               self.box.north - (ii.ravel() + 0.5) * self.dlat])
        in_seto = MplPath(SETO_POLYGON).contains_points(pts).reshape(ny, nx)
        self.seto = in_seto & ~self.land

    def index(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """最寄りの画素。範囲外は inside=False。"""
        i = np.floor((self.box.north - lat) / self.dlat).astype(int)
        j = np.floor((lon - self.box.west) / self.dlon).astype(int)
        inside = (i >= 0) & (i < self.elev.shape[0]) & (j >= 0) & (j < self.elev.shape[1])
        return np.clip(i, 0, self.elev.shape[0] - 1), np.clip(j, 0, self.elev.shape[1] - 1), inside

    @property
    def extent(self) -> tuple[float, float, float, float]:
        return (self.box.west, self.box.east, self.box.south, self.box.north)


class Snow:
    """ERA5 の積雪深。日付と緯度経度で引く。"""

    def __init__(self) -> None:
        files = sorted((HERE / "data").glob("era5_sd_*.nc"))
        if not files:
            raise SystemExit("積雪のファイルがありません。先に fetch_snow.py を実行してください")
        parts = []
        for f in files:
            with xr.open_dataset(f) as ds:
                parts.append(ds["sd"].load())
        sd = xr.concat(parts, "time")
        self.sd = sd.values                                   # (day, lat, lon)
        self.dates = pd.DatetimeIndex(sd["time"].values).normalize()
        self.lat = sd["latitude"].values                      # 北から南
        self.lon = sd["longitude"].values
        self.date_index = {d: k for k, d in enumerate(self.dates)}

    def has_snow(self, dates: pd.DatetimeIndex, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """dates は lat/lon の第 0 軸に対応する。"""
        k = np.array([self.date_index.get(d, -1) for d in dates])
        if (k < 0).any():
            raise ValueError("積雪の無い日付がある")
        i = np.clip(np.rint((self.lat[0] - lat) / 0.25).astype(int), 0, self.lat.size - 1)
        j = np.clip(np.rint((lon - self.lon[0]) / 0.25).astype(int), 0, self.lon.size - 1)
        kk = np.broadcast_to(k.reshape((-1,) + (1,) * (lat.ndim - 1)), lat.shape)
        return self.sd[kk, i, j] >= SNOW_SD_M

    def snow_free_fraction(self) -> xr.DataArray:
        return xr.DataArray((self.sd < SNOW_SD_M).mean(axis=0), dims=("lat", "lon"),
                            coords={"lat": self.lat, "lon": self.lon})


def area_of(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """打ち上げ候補がどの地方に入るか。緯度経度の四角だけで分けると、
    北九州と山口、徳島と和歌山のように海峡をはさむ場所が混ざるので、
    まず海岸線の輪で本州・九州・四国を分ける。"""
    from windclim.figures.coast import load_coastline  # noqa: PLC0415

    rings = load_coastline(SOUTHWEST)

    def ring_area(r):
        x, y = r[:, 0], r[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))

    def pick(lat0, lon0):
        cand = [r for r in rings if MplPath(r).contains_point((lon0, lat0))]
        return min(cand, key=ring_area)

    def near(ring, pts, tol=0.12):
        """輪の内側か、輪の頂点から tol 度以内。海岸線が粗いので、
        沿岸の点が輪の外に出てしまうのを拾う。"""
        inside = MplPath(ring).contains_points(pts)
        d = np.min(np.hypot(pts[:, None, 0] - ring[None, :, 0],
                            pts[:, None, 1] - ring[None, :, 1]), axis=1)
        return inside | (d < tol)

    honshu, kyushu, shikoku = pick(35.5, 137.5), pick(32.5, 130.7), pick(33.6, 133.3)
    pts = np.column_stack([lon.ravel(), lat.ravel()])
    out = np.full(lat.size, AREA_NAMES[6], dtype=object)
    out[lat.ravel() < 30.9] = AREA_NAMES[7]
    # 淡路島や小豆島のような小さな島の内側にある点は、近くの大きな島に寄せない
    big = max(ring_area(honshu), ring_area(kyushu), ring_area(shikoku))
    small = [r for r in rings if ring_area(r) < ring_area(shikoku) and r is not kyushu]
    in_small = np.zeros(len(pts), dtype=bool)
    for r in small:
        in_small |= MplPath(r).contains_points(pts)
    del big
    in_k = near(kyushu, pts) & ~in_small
    in_s = near(shikoku, pts) & ~in_small
    on_honshu = MplPath(honshu).contains_points(pts)
    # 輪の内側を優先し、外側の点は最寄りの島に寄せる
    close_h = near(honshu, pts) & ~on_honshu
    out[in_k] = AREA_NAMES[5]
    out[in_s] = AREA_NAMES[4]
    on_honshu = on_honshu | (close_h & ~in_k & ~in_s & ~in_small)
    out[MplPath(kyushu).contains_points(pts)] = AREA_NAMES[5]
    out[MplPath(shikoku).contains_points(pts)] = AREA_NAMES[4]
    la, lo = lat.ravel(), lon.ravel()
    out[on_honshu & (lo < 134.35)] = AREA_NAMES[3]
    out[on_honshu & (lo >= 134.35) & (lo < 136.0)] = AREA_NAMES[2]
    out[on_honshu & (lo >= 136.0) & (la < 35.4)] = AREA_NAMES[1]
    out[on_honshu & (lo >= 136.0) & (la >= 35.4)] = AREA_NAMES[0]
    return out.reshape(lat.shape)


def in_japan(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """朝鮮半島と済州島を打ち上げ候補から外す（対馬は残す）。"""
    korea = ((lat > 34.0) & (lon < 129.15)) | ((lat > 34.75) & (lon < 130.0))
    jeju = (lat > 33.1) & (lat < 33.6) & (lon > 126.0) & (lon < 127.0)
    return ~(korea | jeju)


# --- 風から落下点 ---------------------------------------------------------------

def month_samples(month: int):
    s = load_month(CACHE_ROOT, "southwest", month, AggregateConfig())
    lat2 = np.broadcast_to(s.lat[:, None], (s.lat.size, s.lon.size))
    z_mean = np.nanmean(s.z, axis=0)                      # (level, lat, lon)
    alt = geopotential_to_geometric(z_mean, np.broadcast_to(lat2, z_mean.shape))
    return s, alt


def month_drift(s, alt: np.ndarray, flight: FlightProfile) -> dict:
    """その月の全解析について、各格子点から上げたときの変位（km）。"""
    # 気圧の低い順（高度の高い順）で届くので、高度の低い順に並べ替える
    dx, dy = displacements(s.u[:, ::-1], s.v[:, ::-1], alt[::-1], flight)
    return {"lat": s.lat, "lon": s.lon, "times": pd.DatetimeIndex(s.times),
            "east_km": dx / 1000.0, "north_km": dy / 1000.0}


def landings(launch_lat, launch_lon, drift: dict, sel: np.ndarray):
    ci = np.abs(drift["lat"][:, None] - launch_lat[None, :]).argmin(axis=0)
    cj = np.abs(drift["lon"][:, None] - launch_lon[None, :]).argmin(axis=0)
    e = drift["east_km"][sel][:, ci, cj]                      # (sample, point)
    n = drift["north_km"][sel][:, ci, cj]
    lat = launch_lat[None, :] + n / KM_PER_DEG
    lon = launch_lon[None, :] + e / (KM_PER_DEG * np.cos(np.radians(launch_lat)))[None, :]
    return e, n, lat, lon


def evaluate(launch_lat: np.ndarray, launch_lon: np.ndarray, drift: dict, sel: np.ndarray,
             terrain: Terrain, snow: Snow) -> dict[str, np.ndarray]:
    """打ち上げ点ごと・解析ごとの落下点を判定し、割合にまとめる。"""
    e, n, lat, lon = landings(launch_lat, launch_lon, drift, sel)
    i, j, inside = terrain.index(lat, lon)
    land = terrain.land[i, j] & inside
    plain = terrain.plain[i, j] & inside
    urban = terrain.urban[i, j] & inside
    dates = drift["times"][sel].normalize()
    snow_land = snow.has_snow(dates, lat, lon)
    snow_launch = snow.has_snow(dates, np.broadcast_to(launch_lat, lat.shape),
                                np.broadcast_to(launch_lon, lon.shape))
    ok_snow = ~snow_land & ~snow_launch
    seto = terrain.seto[i, j] & inside
    good = plain & ~urban & ok_snow
    if OPTIONS["allow_seto"]:
        # 海の上に積雪は無いので、着水は打ち上げ場所の雪だけを問う
        good = good | (seto & ~snow_launch)
    dist = np.hypot(e, n)
    return {
        "p_good": good.mean(axis=0),
        "p_seto": seto.mean(axis=0),
        "p_plain_incl_urban": (plain & ok_snow).mean(axis=0),
        "p_urban": urban.mean(axis=0),
        "p_land": land.mean(axis=0),
        "p_sea": (~land & inside).mean(axis=0),
        "p_outside": (~inside).mean(axis=0),
        "p_snow_landing": (snow_land & land).mean(axis=0),
        "p_snow_launch": snow_launch.mean(axis=0),
        "dist_mean_km": dist.mean(axis=0),
        "dist_p90_km": np.percentile(dist, 90, axis=0),
        "east_km": e.mean(axis=0),
        "north_km": n.mean(axis=0),
    }


def evaluate_chunked(lat, lon, drift, sel, terrain, snow, chunk: int = 1500) -> dict:
    res: dict[str, list] = {}
    for k0 in range(0, lat.size, chunk):
        part = evaluate(lat[k0:k0 + chunk], lon[k0:k0 + chunk], drift, sel, terrain, snow)
        for key, val in part.items():
            res.setdefault(key, []).append(val)
    return {k: np.concatenate(v) for k, v in res.items()}


# --- 図 ------------------------------------------------------------------------

def _map_axes(ax, box=SOUTHWEST) -> None:
    draw_coastline(ax, box, linewidth=0.6)
    ax.set_xlim(box.west, box.east)
    ax.set_ylim(box.south, box.north)
    ax.set_aspect(1 / np.cos(np.radians(0.5 * (box.south + box.north))))
    ax.tick_params(labelsize=8)


def fig_base(terrain: Terrain, snow_free: xr.DataArray) -> Figure:
    fig = Figure(figsize=(12.5, 5.6))
    left, right = fig.subplots(1, 2)
    cls = np.where(~terrain.land, 0, np.where(terrain.urban, 3, np.where(terrain.plain, 2, 1)))
    handles = [Patch(color="#5fae5f", label="平野（DID の外）"),
               Patch(color="#d9534f", label="人口集中地区（DID）"),
               Patch(color="#c9c3b4", label="その他の陸地（山地など）")]
    if OPTIONS["allow_seto"]:
        cls = np.where(terrain.seto, 4, cls)
        handles.insert(1, Patch(color="#6fa8dc", label="瀬戸内海（着水も可）"))
    cmap = ListedColormap(["#dfe9f3", "#c9c3b4", "#5fae5f", "#d9534f", "#6fa8dc"])
    left.imshow(cls, extent=terrain.extent, origin="upper", cmap=cmap, vmin=0, vmax=4,
                interpolation="nearest")
    _map_axes(left, LANDING_BOX)
    left.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9)
    extra = "、または瀬戸内海" if OPTIONS["allow_seto"] else ""
    left.set_title(f"落下の目標: 標高 {PLAIN_MAX_ELEV_M:.0f} m 以下・傾斜 "
                   f"{PLAIN_MAX_SLOPE_DEG:.0f}° 以下で DID の外{extra}", fontsize=10)
    mesh = right.pcolormesh(snow_free["lon"], snow_free["lat"], 100 * snow_free,
                            cmap=CMAP_SPEED.reversed(), vmin=0, vmax=100, shading="nearest")
    _map_axes(right, LANDING_BOX)
    right.set_title("雪のない日の割合（ERA5、1・2 月、2016–2025 年）", fontsize=10)
    fig.colorbar(mesh, ax=right, shrink=0.8, label="[%]")
    fig.tight_layout()
    return fig


def fig_drift(drift_by_bin: dict[str, dict]) -> Figure:
    fig = Figure(figsize=(12, 9.6))
    axes = fig.subplots(2, 2).ravel()
    vmax = max(float(np.nanpercentile(d["dist"], 99)) for d in drift_by_bin.values())
    mesh = None
    for ax, (name, d) in zip(axes, drift_by_bin.items(), strict=True):
        mesh = ax.pcolormesh(d["lon"], d["lat"], d["dist"], cmap=CMAP_SPEED, vmin=0,
                             vmax=vmax, shading="nearest", alpha=0.9)
        # 矢印は実寸なので、東西に重ならないよう経度は 8 格子（3 度）おきに描く
        la, lo = np.meshgrid(d["lat"][2::5], d["lon"][2::8], indexing="ij")
        ax.quiver(lo, la, d["east"][2::5, 2::8], d["north"][2::5, 2::8],
                  color=INK["primary"], angles="xy", scale_units="xy",
                  scale=KM_PER_DEG * np.cos(np.radians(31)), width=0.004)
        ax.plot(lo, la, "o", color=INK["primary"], markersize=2.5)
        _map_axes(ax)
        ax.set_title(name, fontsize=11)
    fig.colorbar(mesh, ax=list(axes), shrink=0.7, label="平均の飛行距離 [km]")
    fig.suptitle("標準の飛行条件での平均落下位置（点が打ち上げ地点、矢先が平均落下点。矢印は実寸）",
                 fontsize=12)
    return fig


def _grid_map(ax, lat, lon, values, vmax=None):
    if vmax is None:
        vmax = 70 if OPTIONS["allow_seto"] else 40
    mesh = ax.pcolormesh(lon, lat, 100 * values, cmap=CMAP_SPEED, vmin=0, vmax=vmax,
                         shading="nearest")
    _map_axes(ax, MAP_BOX)
    return mesh


def fig_suitability(grid: dict[str, np.ndarray], lat, lon, tops: dict[str, pd.DataFrame],
                    title: str) -> Figure:
    fig = Figure(figsize=(12, 8.4))
    axes = fig.subplots(2, 2).ravel()
    mesh = None
    for ax, (name, g) in zip(axes, grid.items(), strict=True):
        mesh = _grid_map(ax, lat, lon, g)
        top = tops[name].head(5)
        ax.plot(top["lon"], top["lat"], "o", markersize=7, markerfacecolor="none",
                markeredgecolor=CATEGORICAL[1], markeredgewidth=1.8)
        ax.set_title(name, fontsize=11)
    fig.colorbar(mesh, ax=list(axes), shrink=0.7, label="目標に落ちる割合 [%]")
    fig.suptitle(title, fontsize=12)
    return fig


def fig_scenarios(mean_grid: dict[str, np.ndarray], lat, lon, dist: dict[str, float]) -> Figure:
    fig = Figure(figsize=(14, 7.4))
    axes = fig.subplots(2, 3).ravel()
    mesh = None
    for ax, (name, g) in zip(axes, mean_grid.items(), strict=False):
        mesh = _grid_map(ax, lat, lon, g)
        k = np.nanargmax(g)
        ax.plot(lon[k % lon.size], lat[k // lon.size], "o", markersize=8, markerfacecolor="none",
                markeredgecolor=CATEGORICAL[1], markeredgewidth=2)
        ax.set_title(f"{name}\n飛行距離 平均 {dist[name]:.0f} km、最良 {100 * np.nanmax(g):.0f} %",
                     fontsize=9.5)
    axes[-1].set_visible(False)
    fig.colorbar(mesh, ax=list(axes[:-1]), shrink=0.7,
                 label="目標に落ちる割合 [%]（1・2 月の平均）")
    fig.suptitle("飛行条件ごとの「目標に落ちる割合」（丸は最も高い地点）", fontsize=12)
    return fig


def fig_clouds(terrain: Terrain, clouds: list[dict]) -> Figure:
    fig = Figure(figsize=(12.5, 5.2 * ((len(clouds) + 1) // 2)))
    axes = np.atleast_1d(fig.subplots((len(clouds) + 1) // 2, 2)).ravel()
    cls = np.where(~terrain.land, 0, np.where(terrain.urban, 3, np.where(terrain.target, 2, 1)))
    if OPTIONS["allow_seto"]:
        cls = np.where(terrain.seto, 4, cls)
    cmap = ListedColormap(["#dfe9f3", "#d8d3c6", "#9fd49f", "#f2a3a1", "#9cc3e6"])
    for ax, c in zip(axes, clouds, strict=False):
        ax.imshow(cls, extent=terrain.extent, origin="upper", cmap=cmap, vmin=0, vmax=4,
                  interpolation="nearest")
        ok = c["good"]
        ax.plot(c["lon"][~ok], c["lat"][~ok], ".", markersize=1.5, color=INK["muted"], alpha=0.5)
        ax.plot(c["lon"][ok], c["lat"][ok], ".", markersize=1.8, color=CATEGORICAL[0], alpha=0.8)
        ax.plot(c["launch"][1], c["launch"][0], "*", markersize=15, color=CATEGORICAL[1],
                markeredgecolor="white")
        pad = 1.6
        box_w = min(c["launch"][1], np.percentile(c["lon"], 2)) - 0.3
        box_e = max(c["launch"][1], np.percentile(c["lon"], 98)) + 0.3
        box_s = min(c["launch"][0], np.percentile(c["lat"], 2)) - 0.3
        box_n = max(c["launch"][0], np.percentile(c["lat"], 98)) + 0.3
        ax.set_xlim(box_w, box_e)
        ax.set_ylim(box_s, box_n)
        ax.set_aspect(1 / np.cos(np.radians(c["launch"][0])))
        draw_coastline(ax, LANDING_BOX, linewidth=0.5)
        ax.set_xlim(box_w, box_e)
        ax.set_ylim(box_s, box_n)
        del pad
        ax.set_title(f"{c['title']}\n目標に落ちる割合 {100 * ok.mean():.0f} %", fontsize=9.5)
        ax.tick_params(labelsize=8)
    for ax in axes[len(clouds):]:
        ax.set_visible(False)
    handles = [Patch(color="#9fd49f", label="目標（DID の外の平野）"),
               Patch(color="#f2a3a1", label="人口集中地区"),
               Patch(color="#d8d3c6", label="山地など"),
               Patch(color=CATEGORICAL[0], label="目標に落ちた回"),
               Patch(color=INK["muted"], label="それ以外（雪の日を含む）")]
    if OPTIONS["allow_seto"]:
        handles.insert(1, Patch(color="#9cc3e6", label="瀬戸内海（目標）"))
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=8.5, frameon=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


# --- 本体 ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global FIG_DIR, RES_DIR
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-seto", action="store_true",
                    help="瀬戸内海への着水も成功に数える（結果は別のフォルダに出す）")
    a = ap.parse_args(argv)
    OPTIONS["allow_seto"] = a.allow_seto
    if a.allow_seto:
        FIG_DIR = FIG_DIR.parent / "winter_sw_seto"
        RES_DIR = RES_DIR / "seto"
    apply_style(japanese=True)
    terrain = Terrain()
    snow = Snow()

    # 打ち上げ候補: 0.1 度間隔の陸上の点（朝鮮半島と済州島は除く）
    glat = np.arange(SOUTHWEST.south + 0.3, SOUTHWEST.north - 0.2, LAUNCH_STEP)
    glon = np.arange(SOUTHWEST.west + 0.2, SOUTHWEST.east - 0.2, LAUNCH_STEP)
    LA, LO = np.meshgrid(glat, glon, indexing="ij")
    i, j, _ = terrain.index(LA, LO)
    cand = terrain.land[i, j] & in_japan(LA, LO)
    pts_lat, pts_lon = LA[cand], LO[cand]

    site_names = list(SITES)
    s_lat = np.array([SITES[s][0] for s in site_names])
    s_lon = np.array([SITES[s][1] for s in site_names])

    samples = {m: month_samples(m) for m in (1, 2)}
    rows, top_rows, drift_maps, dist_mean = [], [], {}, {}
    grids: dict[str, dict[str, np.ndarray]] = {}
    tops: dict[str, dict[str, pd.DataFrame]] = {}
    for scen, (ascent, burst) in SCENARIOS.items():
        flight = FlightProfile(ascent_rate_ms=ascent, burst_altitude_m=burst)
        grids[scen], tops[scen] = {}, {}
        dists = []
        for month in (1, 2):
            s, alt = samples[month]
            drift = month_drift(s, alt, flight)
            days = drift["times"].day
            for m, half, name in BINS:
                if m != month:
                    continue
                sel = (days <= 15) if half == 1 else (days > 15)
                if scen == STANDARD:
                    e, n = drift["east_km"][sel], drift["north_km"][sel]
                    drift_maps[name] = {"lat": drift["lat"], "lon": drift["lon"],
                                        "east": e.mean(axis=0), "north": n.mean(axis=0),
                                        "dist": np.hypot(e, n).mean(axis=0)}
                res = evaluate_chunked(pts_lat, pts_lon, drift, sel, terrain, snow)
                g = np.full(LA.shape, np.nan)
                g[cand] = res["p_good"]
                grids[scen][name] = g
                dists.append(np.nanmean(res["dist_mean_km"]))
                table = pd.DataFrame({"lat": pts_lat, "lon": pts_lon} | res)
                tops[scen][name] = table.sort_values("p_good", ascending=False)
                for r in tops[scen][name].head(10).itertuples():
                    top_rows.append({"scenario": scen, "bin": name} | r._asdict())
                sres = evaluate(s_lat, s_lon, drift, sel, terrain, snow)
                for k, site in enumerate(site_names):
                    rows.append({"scenario": scen, "bin": name, "site": site,
                                 "lat": s_lat[k], "lon": s_lon[k]}
                                | {key: float(val[k]) for key, val in sres.items()})
        dist_mean[scen] = float(np.mean(dists))

    sites = pd.DataFrame(rows)
    top = pd.DataFrame(top_rows).drop(columns="Index")
    RES_DIR.mkdir(parents=True, exist_ok=True)
    sites.to_csv(RES_DIR / "sites_jan_feb.csv", index=False, float_format="%.3f")
    top.to_csv(RES_DIR / "top_launch_points.csv", index=False, float_format="%.3f")

    # 1・2 月を通した平均で見た、飛行条件ごとの最良地点
    mean_grid = {scen: np.nanmean(np.stack(list(g.values())), axis=0) for scen, g in grids.items()}
    best = {}
    for scen, g in mean_grid.items():
        k = int(np.nanargmax(g))
        best[scen] = {"lat": round(float(glat[k // glon.size]), 2),
                      "lon": round(float(glon[k % glon.size]), 2),
                      "p_good_mean": round(float(np.nanmax(g)), 3),
                      "by_bin": {b: round(float(grids[scen][b].ravel()[k]), 3)
                                 for b in grids[scen]},
                      "mean_flight_km": round(dist_mean[scen], 1)}

    # 地方ごとの最良地点（1・2 月の平均）
    area_grid = area_of(LA, LO)
    area_rows = []
    for scen, g in mean_grid.items():
        for area in AREA_NAMES:
            m = (area_grid == area) & np.isfinite(g)
            if not m.any():
                continue
            k = np.flatnonzero(m.ravel())[np.nanargmax(g.ravel()[m.ravel()])]
            area_rows.append({"scenario": scen, "area": area,
                              "lat": round(float(LA.ravel()[k]), 2),
                              "lon": round(float(LO.ravel()[k]), 2),
                              "p_good_mean": round(float(g.ravel()[k]), 3)}
                             | {b: round(float(grids[scen][b].ravel()[k]), 3)
                                for b in grids[scen]})
    areas = pd.DataFrame(area_rows)
    areas.to_csv(RES_DIR / "best_by_area.csv", index=False)

    # 落下点の雲を描く地点: 標準と、最も目標に落ちやすい条件の最良地点
    best_scen = max(best, key=lambda s: best[s]["p_good_mean"])
    cloud_specs = [(STANDARD, best[STANDARD]), (best_scen, best[best_scen])]
    clouds = []
    for scen, b in cloud_specs:
        ascent, burst = SCENARIOS[scen]
        flight = FlightProfile(ascent_rate_ms=ascent, burst_altitude_m=burst)
        for month in (1, 2):
            s, alt = samples[month]
            drift = month_drift(s, alt, flight)
            sel = np.ones(drift["times"].size, dtype=bool)
            la, lo = np.array([b["lat"]]), np.array([b["lon"]])
            _, _, lat, lon = landings(la, lo, drift, sel)
            i2, j2, ins = terrain.index(lat, lon)
            dates = drift["times"].normalize()
            launch_ok = ~snow.has_snow(dates, np.full_like(lat, b["lat"]),
                                       np.full_like(lon, b["lon"]))
            ok = terrain.target[i2, j2] & ins & ~snow.has_snow(dates, lat, lon)
            if OPTIONS["allow_seto"]:
                ok = ok | (terrain.seto[i2, j2] & ins)
            ok = ok & launch_ok
            clouds.append({"lat": lat[:, 0], "lon": lon[:, 0], "good": ok[:, 0],
                           "launch": (b["lat"], b["lon"]),
                           "title": (f"{scen}、{month} 月、"
                                     f"打ち上げ {b['lat']:.1f}°N {b['lon']:.1f}°E")})

    out = [
        save(fig_base(terrain, snow.snow_free_fraction()), FIG_DIR, "W1", "target_and_snow"),
        save(fig_drift(drift_maps), FIG_DIR, "W2", "drift_jan_feb"),
        save(fig_suitability(grids[STANDARD], glat, glon, tops[STANDARD],
                             "標準の飛行条件で目標に落ちる割合（丸は上位 5 地点）"),
             FIG_DIR, "W3", "suitability_standard"),
        save(fig_scenarios(mean_grid, glat, glon, dist_mean), FIG_DIR, "W4", "scenarios"),
        save(fig_suitability(grids[best_scen], glat, glon, tops[best_scen],
                             f"{best_scen} で目標に落ちる割合（丸は上位 5 地点）"),
             FIG_DIR, "W5", "suitability_best"),
        save(fig_clouds(terrain, clouds), FIG_DIR, "W6", "landing_clouds"),
    ]
    frac = {
        "land_plain_share": float(terrain.plain[terrain.land].mean()),
        "plain_urban_share": float((terrain.plain & terrain.urban)[terrain.land].sum()
                                   / terrain.plain[terrain.land].sum()),
    }
    summary = {
        "definitions": {"plain_max_elev_m": PLAIN_MAX_ELEV_M,
                        "plain_max_slope_deg": PLAIN_MAX_SLOPE_DEG,
                        "snow_sd_m": SNOW_SD_M, "launch_step_deg": LAUNCH_STEP},
        "n_launch_points": int(pts_lat.size),
        "terrain": frac,
        "best_by_scenario": best,
        "best_scenario": best_scen,
        "figures": [str(p[0].relative_to(RESEARCH)) for p in out],
    }
    (RES_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(areas.to_string(index=False))
    std = sites[sites["scenario"] == STANDARD]
    print(std.pivot(index="site", columns="bin", values="p_good").round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
