"""winter_japan の共通部品: 地形・市街地・積雪・地上気象のマスクと、軌道の計算。

判定の定義（既定値）

* 打ち上げ: 陸地で、その日 12 時 JST に積雪（ERA5、水当量 1 mm 以上）がない。
  電柱やビルのない広場かどうかは格子では判定できないので、上位の候補について
  別に OpenStreetMap で広場を探す（osm_sites.py）。
* 落下: 次のどれかなら成功。
  - 平野（標高 100 m 以下・傾斜 2° 以下）で人口集中地区（DID）の外、雪がない
  - 瀬戸内海（関門・豊予・鳴門・紀淡の各海峡の内側）
  - 海岸から COAST_KM 以内の海（既定 3 km）
* 地上気象（9 時 JST、ERA5）: 10 m 風速 5 m/s 以下、00–03 UTC の降水 0.5 mm 未満。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.path import Path as MplPath
from scipy.ndimage import distance_transform_edt

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(RESEARCH / "winter_sw"))

from windclim.fetch.terrain import load_terrain, size_for  # noqa: E402
from windclim.regions import BBox  # noqa: E402
from windclim.stats.drift import descent_rate_ms  # noqa: E402

KM_PER_DEG = 111.195
BOX = BBox(south=24.0, north=46.5, west=122.0, east=147.0)
DATA = HERE / "data"
RESULTS = HERE / "results"
FIGS = HERE / "figures"

PLAIN_MAX_ELEV_M = 100.0
PLAIN_MAX_SLOPE_DEG = 2.0
SNOW_SD_M = 0.001
COAST_KM = 3.0
SFC_WIND_MAX = 5.0
PRECIP_MAX_MM = 0.5
LAUNCH_STEP = 0.05

IKI = (33.78, 129.72)          # 壱岐島（島の中央付近）

# 瀬戸内海（winter_sw と同じ定義）
SETO_POLYGON = np.array([
    (130.95, 34.05), (130.95, 33.85), (131.20, 33.60), (131.45, 33.15),
    (131.88, 33.20), (131.87, 33.27), (132.02, 33.34),
    (132.50, 33.45), (133.00, 33.80), (134.00, 34.00),
    (134.65, 34.23), (134.75, 34.20), (135.05, 34.27),
    (135.30, 34.40), (135.55, 34.80), (134.50, 34.95), (133.00, 34.75),
    (132.00, 34.55), (131.20, 34.25),
])

#: 飛行条件。名前 → (上昇 m/s, 破裂高度 m, 降下 m/s 海面等価)
SCENARIOS = {
    "std": ("標準（上昇 5 m/s・破裂 30 km）", 5.0, 30000.0, 6.0),
    "short": ("短時間（上昇 8 m/s・破裂 20 km）", 8.0, 20000.0, 6.0),
}


def in_japan(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """朝鮮半島・済州島・ロシア（沿海州・サハリン・国後など）・中国を外す。"""
    korea = ((lat > 34.0) & (lon < 129.15)) | ((lat > 34.75) & (lon < 130.0))
    jeju = (lat > 33.1) & (lat < 33.6) & (lon > 126.0) & (lon < 127.0)
    russia = ((lat > 42.3) & (lon < 139.0)) | (lat > 45.6) \
        | ((lat > 43.55) & (lon > 145.45)) | (lon > 145.9)
    china = (lat > 27.5) & (lon < 124.0)
    return ~(korea | jeju | russia | china)


# --- 地形 -----------------------------------------------------------------------

def _rasterize_did(shape, box, dlat, dlon) -> np.ndarray:
    cache = DATA / f"did_mask_{shape[0]}x{shape[1]}.npy"
    if cache.exists():
        return np.load(cache)
    mask = np.zeros(shape, dtype=bool)
    files = sorted((RESEARCH / "winter_sw" / "data" / "did").glob("A16-20_*_DID.geojson"))
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
    """DEM（約 600 m 間隔）から陸・平野・DID・瀬戸内海・海岸からの距離を作る。"""

    def __init__(self, width: int = 4400) -> None:
        w, h = size_for(BOX, width=width)
        tile = load_terrain(BOX, width=w, height=h, allow_fetch=False)
        self.elev = tile.elevation.astype(np.float32)
        self.box = tile.bbox
        ny, nx = self.elev.shape
        self.dlat = (self.box.north - self.box.south) / ny
        self.dlon = (self.box.east - self.box.west) / nx
        lat = self.box.north - (np.arange(ny) + 0.5) * self.dlat
        self.lat1d = lat
        self.lon1d = self.box.west + (np.arange(nx) + 0.5) * self.dlon
        dy = self.dlat * KM_PER_DEG * 1000.0
        dx = self.dlon * KM_PER_DEG * 1000.0 * np.cos(np.radians(lat))[:, None]
        gy, gx = np.gradient(self.elev)
        slope = np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))
        self.land = self.elev > 1.0
        self.plain = self.land & (self.elev <= PLAIN_MAX_ELEV_M) & (slope <= PLAIN_MAX_SLOPE_DEG)
        self.urban = _rasterize_did(self.elev.shape, self.box, self.dlat, self.dlon) & self.land
        ii, jj = np.mgrid[0:ny, 0:nx]
        pts = np.column_stack([self.lon1d[jj.ravel()], lat[ii.ravel()]])
        self.seto = MplPath(SETO_POLYGON).contains_points(pts).reshape(ny, nx) & ~self.land
        # 海岸からの距離（km）。画素の縦横の大きさを緯度 35 度で近似する
        sampling = (self.dlat * KM_PER_DEG, self.dlon * KM_PER_DEG * np.cos(np.radians(35)))
        self.sea_dist_km = distance_transform_edt(~self.land, sampling=sampling).astype(np.float32)

    def index(self, lat, lon):
        i = np.floor((self.box.north - lat) / self.dlat).astype(int)
        j = np.floor((lon - self.box.west) / self.dlon).astype(int)
        inside = (i >= 0) & (i < self.elev.shape[0]) & (j >= 0) & (j < self.elev.shape[1])
        return np.clip(i, 0, self.elev.shape[0] - 1), np.clip(j, 0, self.elev.shape[1] - 1), inside

    @property
    def extent(self):
        return (self.box.west, self.box.east, self.box.south, self.box.north)


def launch_candidates(terrain: Terrain, step: float = LAUNCH_STEP) -> pd.DataFrame:
    lat = np.arange(24.2, 45.6, step)
    lon = np.arange(122.9, 145.9, step)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    la, lo = la.ravel(), lo.ravel()
    i, j, inside = terrain.index(la, lo)
    keep = inside & terrain.land[i, j] & in_japan(la, lo)
    return pd.DataFrame({"lat": np.round(la[keep], 3), "lon": np.round(lo[keep], 3),
                         "elev": terrain.elev[i[keep], j[keep]]})


# --- ERA5（積雪・地上気象） --------------------------------------------------------

class Surface:
    """ERA5 の日ごとの値（9 時 JST 前後）。日付と緯度経度で最寄りの 0.25 度格子を引く。"""

    def __init__(self) -> None:
        files = sorted(DATA.glob("era5_sfc_*.nc"))
        if not files:
            raise SystemExit("ERA5 がありません。fetch_era5.py を先に実行してください")
        ds = xr.open_mfdataset(files, combine="by_coords").load()
        self.dates = pd.DatetimeIndex(ds["time"].values).normalize()
        self.lat = ds["latitude"].values
        self.lon = ds["longitude"].values
        self.sd = ds["sd"].values
        self.ws = np.hypot(ds["u10_00"].values, ds["v10_00"].values)
        self.tp = ds["tp_0003"].values
        self.gust = ds["gust_0003"].values if "gust_0003" in ds else None
        self.tcc = ds["tcc_00"].values if "tcc_00" in ds else None
        self.date_index = {d: k for k, d in enumerate(self.dates)}
        # 陸の点は、海が大半の格子（壱岐のような小さな島）でも最寄りの陸の格子で引く。
        # 海の格子の地上風は陸より強く、積雪は 0 になるため。
        self.land_i = self.land_j = None
        lsm_file = DATA / "era5_lsm.nc"
        if lsm_file.exists():
            with xr.open_dataset(lsm_file) as m:
                lsm = m["lsm"].squeeze().sel(latitude=self.lat, longitude=self.lon,
                                             method="nearest").values
            _, (li, lj) = distance_transform_edt(lsm < 0.5, return_indices=True)
            self.land_i, self.land_j = li, lj

    def _ij(self, lat, lon):
        i = np.clip(np.rint((self.lat[0] - lat) / 0.25).astype(int), 0, self.lat.size - 1)
        j = np.clip(np.rint((lon - self.lon[0]) / 0.25).astype(int), 0, self.lon.size - 1)
        if self.land_i is not None:
            i, j = self.land_i[i, j], self.land_j[i, j]
        return i, j

    def day_index(self, dates: pd.DatetimeIndex) -> np.ndarray:
        k = np.array([self.date_index.get(d, -1) for d in dates])
        if (k < 0).any():
            raise ValueError("ERA5 に無い日付がある")
        return k

    def field(self, name: str, k: np.ndarray, lat, lon) -> np.ndarray:
        """k は (day,) 、lat/lon は (day, point) か (point,)。"""
        arr = getattr(self, name)
        i, j = self._ij(np.asarray(lat), np.asarray(lon))
        kk = k.reshape((-1,) + (1,) * (np.ndim(i) - 1)) if np.ndim(i) > 1 else k[:, None]
        if np.ndim(i) == 1:
            i, j = i[None, :], j[None, :]
        return arr[kk, i, j]


# --- 軌道 ------------------------------------------------------------------------

class Winds:
    def __init__(self) -> None:
        d = np.load(DATA / "jra3q_00utc.npz")
        self.times = pd.DatetimeIndex(d["times"])
        self.lat = d["lat"].astype(float)
        self.lon = d["lon"].astype(float)
        # 高度の低い順（気圧の高い順）に並べ替える
        self.u = d["u"][:, ::-1]
        self.v = d["v"][:, ::-1]
        self.alt = d["alt"][:, ::-1]
        self.level = d["level"][::-1]


def _bilinear(field: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    """field (lat, lon)、fi/fj は小数の添字。"""
    ny, nx = field.shape
    fi = np.clip(fi, 0, ny - 1.000001)
    fj = np.clip(fj, 0, nx - 1.000001)
    i0 = fi.astype(int)
    j0 = fj.astype(int)
    a = fi - i0
    b = fj - j0
    return ((1 - a) * (1 - b) * field[i0, j0] + (1 - a) * b * field[i0, j0 + 1]
            + a * (1 - b) * field[i0 + 1, j0] + a * b * field[i0 + 1, j0 + 1])


def trajectory(w: Winds, t: int, lat0: np.ndarray, lon0: np.ndarray, elev0: np.ndarray,
               ascent: np.ndarray, burst: np.ndarray, descent: np.ndarray):
    """解析 t の風で、各点から上げたときの落下点（緯度・経度）と飛行時間。

    気圧面ごとの層（隣の面との中点で区切る）を上昇・下降それぞれで通り、層の中では
    その面の風を、その時点の位置で双線形補間して使う。風は打ち上げ時刻で固定。
    ascent/burst/descent は点ごとの値（アンサンブルに使う）。
    """
    lat = lat0.astype(float).copy()
    lon = lon0.astype(float).copy()
    # 層の境界は打ち上げ点の最寄り格子の高度で決める
    ci = np.abs(w.lat[:, None] - lat0[None, :]).argmin(axis=0)
    cj = np.abs(w.lon[:, None] - lon0[None, :]).argmin(axis=0)
    alt = w.alt[t][:, ci, cj]                                   # (level, point)
    mid = 0.5 * (alt[:-1] + alt[1:])
    lower = np.concatenate([np.full((1, alt.shape[1]), -1e4), mid])
    upper = np.concatenate([mid, np.full((1, alt.shape[1]), 1e5)])
    up_lo = np.clip(lower, elev0, burst)
    up_hi = np.clip(upper, elev0, burst)
    dn_lo = np.clip(lower, 0.0, burst)
    dn_hi = np.clip(upper, 0.0, burst)
    t_up = np.maximum(up_hi - up_lo, 0) / ascent
    t_dn = np.maximum(dn_hi - dn_lo, 0) / descent_rate_ms(alt, 1.0) / descent
    dlat_grid = np.diff(w.lat).mean()
    dlon_grid = np.diff(w.lon).mean()
    uu, vv = w.u[t], w.v[t]
    nl = alt.shape[0]
    order = list(range(nl)) + list(range(nl - 1, -1, -1))
    for step, k in enumerate(order):
        dt = t_up[k] if step < nl else t_dn[k]
        if not np.any(dt > 0):
            continue
        fi = np.interp(lat, w.lat, np.arange(w.lat.size)) if dlat_grid > 0 else None
        fj = (lon - w.lon[0]) / dlon_grid
        u = _bilinear(uu[k], fi, fj)
        v = _bilinear(vv[k], fi, fj)
        lat = lat + v * dt / 1000.0 / KM_PER_DEG
        lon = lon + u * dt / 1000.0 / (KM_PER_DEG * np.cos(np.radians(lat)))
    return lat, lon, (t_up.sum(0) + t_dn.sum(0))


# --- 落下点の判定 -------------------------------------------------------------------

def landing_classes(terrain: Terrain, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    i, j, inside = terrain.index(lat, lon)
    land = terrain.land[i, j] & inside
    return {
        "inside": inside,
        "land": land,
        "plain": terrain.plain[i, j] & inside,
        "urban": terrain.urban[i, j] & inside,
        "seto": terrain.seto[i, j] & inside,
        "sea_dist": np.where(land | ~inside, np.inf, terrain.sea_dist_km[i, j]),
    }
