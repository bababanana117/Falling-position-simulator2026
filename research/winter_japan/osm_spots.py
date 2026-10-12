"""北部九州・西部山口の冬季スペースバルーン打ち上げ候補地を OpenStreetMap から探す。

``osm_sites.py`` の改良版。あちらは風の候補地点ごとに半径 8 km を検索し、上位 5 件
だけを残していたため候補が少なすぎた（壱岐空港と思われる無名ポリゴンを誤って候補に
含めてもいた）。こちらは:

* 壱岐島は島全体を bbox で検索する。
* 本土側は候補サイト（唐津・呼子、平戸、糸島、下関、長門、宗像・福津、北九州、
  唐津・相知）を中心に半径 12 km の円で検索する。
* leisure=pitch/park/sports_centre/recreation_ground/stadium/track、
  landuse=recreation_ground/grass（grass は 0.5 ha 以上）、amenity=school/university
  （学校のグラウンドは「許可が必要」と明記する）を候補地とする。
* 障害物として送電線・鉄塔・電柱、建物、（無線）鉄塔、林縁、空港を同じクエリで取得する。
* 候補ポリゴンの内部に格子点をまいて、障害物から最も離れた点（クリアランス最大点）
  を打ち上げ点として採用する。

上位 5 件に絞らず、条件を満たすものは全部出力する。最終判断は必ず現地確認すること。

使い方:
    python osm_spots.py
    python osm_spots.py --no-figures      # 図を作らない
    python osm_spots.py --area 壱岐        # 特定エリアだけ再取得したいとき

Overpass への配慮:
    エリアごとに 1 回のリクエストにまとめる（候補地・送電線・建物・鉄塔・林縁・
    空港を 1 クエリに同居させる）。タイムアウトはサーバー側 240 秒。生の JSON
    レスポンスは data/osm_cache/ 以下にキャッシュし、再実行では通信しない。
    リクエストの間は数秒あけ、429/504 はバックオフして再試行し、駄目なら別の
    ミラーサーバーに切り替える。

注意（現地確認の前に必ず読むこと）:
    * 日本の郊外・離島では送電線・電柱が OSM に完全には登録されていないことが
      多い。ここでの clearance_m は「OSM に載っている障害物からの距離」であり、
      実際の余裕の上限値でしかない。
    * 学校のグラウンドは使用に学校・教育委員会の許可が必要。
    * landuse=grass は公園の芝生から個人宅の庭まで玉石混淆なので、現地写真や
      航空写真での確認を強く推奨する。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
import requests
import shapely
from shapely import Polygon, LineString, Point, MultiPolygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from osm_sites import Proj, name_of  # noqa: E402

CACHE_DIR = HERE / "data" / "osm_cache"
RESULTS = HERE / "results"
FIGS = HERE / "figures"

# この実行環境では overpass-api.de 以外のミラー（kumi.systems, openstreetmap.fr など）
# へは到達できなかった（ネットワークの許可リストの外）。overpass-api.de は公開インス
# タンスで、数回に 1 回程度 504 (Gateway Timeout) を返すが、数秒あけて再試行すれば
# たいてい通る。ミラーを増やすより、同じ URL への再試行回数を増やす方針にする。
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter"]
TIMEOUT_S = 240
USER_AGENT = "falling-position-simulator2026/osm_spots.py (research tool)"
EARTH_R_M = 6_371_000.0

# --- しきい値 -----------------------------------------------------------------
MIN_AREA_M2 = 3_000.0
MIN_GRASS_AREA_M2 = 5_000.0          # landuse=grass はこれ以上のみ候補にする
MIN_CLEARANCE_M = 40.0
CLEARANCE_TIERS = (40.0, 60.0, 100.0)
AIRPORT_EXCLUDE_KM = 3.0
AIRPORT_WARN_KM = 9.0
GRID_SPACING_M = 5.0
GRID_MAX_SAMPLES = 4000
NEARBY_NAME_RADIUS_M = 300.0

LEISURE_CAND = ("pitch", "park", "sports_centre", "recreation_ground", "stadium", "track")
LANDUSE_CAND = ("recreation_ground", "grass")
AMENITY_CAND = ("school", "university")

# --- 検索エリア -----------------------------------------------------------------
# kind="bbox": south/west/north/east。 kind="circle": lat/lon/radius_km。
AREA_QUERIES = [
    ("壱岐", "iki", "bbox",
     dict(south=33.69, west=129.62, north=33.88, east=129.82)),
    ("唐津・呼子", "karatsu_kachiko", "circle", dict(lat=33.60, lon=129.85, radius_km=12)),
    ("唐津・呼子", "yobuko", "circle", dict(lat=33.54, lon=129.89, radius_km=12)),
    ("平戸", "hirado_oshima", "circle", dict(lat=33.50, lon=129.55, radius_km=12)),
    ("平戸", "hirado_island", "circle", dict(lat=33.36, lon=129.53, radius_km=12)),
    ("糸島", "itoshima", "circle", dict(lat=33.60, lon=130.20, radius_km=12)),
    ("下関", "shimonoseki_futaoi", "circle", dict(lat=34.10, lon=130.80, radius_km=12)),
    ("下関", "shimonoseki_honoku", "circle", dict(lat=34.20, lon=130.93, radius_km=12)),
    ("長門", "nagato_misumi", "circle", dict(lat=34.35, lon=131.30, radius_km=12)),
    ("宗像・福津", "fukutsu", "circle", dict(lat=33.75, lon=130.50, radius_km=12)),
    ("宗像・福津", "munakata", "circle", dict(lat=33.805, lon=130.542, radius_km=12)),
    ("北九州", "kitakyushu_wakamatsu", "circle", dict(lat=33.90, lon=130.80, radius_km=12)),
    ("唐津・相知", "karatsu_ochi", "circle", dict(lat=33.35, lon=130.00, radius_km=12)),
]

AREA_GROUP_ORDER = ["壱岐", "唐津・呼子", "平戸", "糸島", "下関", "長門", "宗像・福津",
                    "北九州", "唐津・相知"]


# ---------------------------------------------------------------------------
# Overpass 問い合わせ
# ---------------------------------------------------------------------------

def area_filter(spec: dict) -> str:
    """Overpass 側のフィルタは常に bbox にする。

    "around" フィルタは Overpass にとって bbox よりずっと重く、公開インスタンスでは
    12 km 円で何度も 504 (Gateway Timeout) になった。そこで Overpass には外接矩形
    だけを頼み、実際の半径 12 km への絞り込みは Python 側で（中心からの距離で）
    かける（enclosing_bbox / process_area 内の距離フィルタを参照）。
    """
    s, w, n, e = enclosing_bbox(spec)
    return f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"


def enclosing_bbox(spec: dict) -> tuple[float, float, float, float]:
    """(south, west, north, east)。円のエリアも外接矩形にする（出力を clip するため）。"""
    if spec["kind"] == "bbox":
        return spec["south"], spec["west"], spec["north"], spec["east"]
    lat, lon, r = spec["lat"], spec["lon"], spec["radius_km"]
    dlat = r / 111.195
    dlon = r / (111.195 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def _clip(spec: dict) -> str:
    """out geom(bbox) 用の bbox 文字列。巨大な森林ポリゴンや送電線の座標数を
    エリア外まで含めて転送させないための clip（Overpass への負荷軽減）。"""
    s, w, n, e = enclosing_bbox(spec)
    return f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"


# それぞれ独立したクエリにして 1 リクエストを軽くする（キャッシュも別々）。
# CATEGORY_QUERIES[name] = (Overpass QL のフィルタ集合の作り方, タイムアウト秒)
def _cand_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    leisure_re = "^(" + "|".join(LEISURE_CAND) + ")$"
    landuse_re = "^(" + "|".join(LANDUSE_CAND) + ")$"
    amenity_re = "^(" + "|".join(AMENITY_CAND) + ")$"
    return f"""
[out:json][timeout:120];
(
  way["leisure"~"{leisure_re}"]{filt};
  relation["leisure"~"{leisure_re}"]{filt};
  way["landuse"~"{landuse_re}"]{filt};
  relation["landuse"~"{landuse_re}"]{filt};
  way["amenity"~"{amenity_re}"]{filt};
  relation["amenity"~"{amenity_re}"]{filt};
)->.cand;
.cand out geom{clip};
""".strip()


def _building_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    return f"""
[out:json][timeout:{TIMEOUT_S}];
(
  way["building"]{filt};
  relation["building"]{filt};
)->.bld;
.bld out geom{clip};
""".strip()


def _power_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    return f"""
[out:json][timeout:180];
(
  way["power"~"^(line|minor_line|cable)$"]{filt};
  node["power"~"^(tower|pole)$"]{filt};
)->.pwr;
.pwr out geom{clip};
""".strip()


def _mast_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    return f"""
[out:json][timeout:90];
(
  node["man_made"~"^(mast|tower)$"]{filt};
  way["man_made"~"^(mast|tower)$"]{filt};
)->.mast;
.mast out geom{clip};
""".strip()


def _forest_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    return f"""
[out:json][timeout:{TIMEOUT_S}];
(
  way["natural"="tree_row"]{filt};
  way["landuse"="forest"]{filt};
  relation["landuse"="forest"]{filt};
  way["natural"="wood"]{filt};
  relation["natural"="wood"]{filt};
)->.forest;
.forest out geom{clip};
""".strip()


def _air_query(spec: dict) -> str:
    filt = area_filter(spec)
    clip = _clip(spec)
    return f"""
[out:json][timeout:90];
(
  way["aeroway"~"^(aerodrome|runway|helipad)$"]{filt};
  relation["aeroway"~"^(aerodrome|runway|helipad)$"]{filt};
  node["aeroway"="helipad"]{filt};
)->.air;
.air out geom{clip};
""".strip()


def _named_query(spec: dict) -> str:
    """無名の候補地に「（付近: XX）」と付けるための、名前つき地物を一括取得する。

    候補ごとに毎回 around クエリを投げると（不安定な公開インスタンス相手に）遅すぎる
    ので、エリアごとに 1 回だけ nwr[name] を取る。geometry は要らないので out center
    にして軽くする。"""
    filt = area_filter(spec)
    return f"""
[out:json][timeout:120];
(
  node["name"]{filt};
  way["name"]{filt};
  relation["name"]{filt};
)->.n;
.n out center;
""".strip()


CATEGORY_QUERIES = {
    "cand": _cand_query,
    "building": _building_query,
    "power": _power_query,
    "mast": _mast_query,
    "forest": _forest_query,
    "air": _air_query,
    "named": _named_query,
}


def coastline_query(spec: dict) -> str:
    filt = area_filter(spec)
    return f"""
[out:json][timeout:{TIMEOUT_S}];
way["natural"="coastline"]{filt}->.c;
.c out geom;
""".strip()


def _query_declared_timeout(query: str) -> int:
    import re
    m = re.search(r"\[timeout:(\d+)\]", query)
    return int(m.group(1)) if m else TIMEOUT_S


def _post_overpass(query: str) -> dict:
    client_timeout = _query_declared_timeout(query) + 30
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        backoff = 6.0
        for attempt in range(12):
            try:
                resp = requests_post(url, query, client_timeout)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                print(f"  接続エラー ({url}): {exc}", file=sys.stderr)
                time.sleep(backoff)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 504):
                print(f"  {resp.status_code} を受信、{backoff:.0f} 秒待って再試行"
                      f" ({url}, {attempt + 1}回目)", file=sys.stderr)
                time.sleep(backoff)
                backoff = min(backoff * 1.6, 45.0)
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                continue
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            break
    raise RuntimeError(f"Overpass への問い合わせに失敗: {last_err}")


def requests_post(url: str, query: str, client_timeout: float):
    return requests.post(url, data={"data": query}, timeout=client_timeout,
                          headers={"User-Agent": USER_AGENT})


def fetch_cached(key: str, query_builder, *args) -> dict:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    query = query_builder(*args)
    data = _post_overpass(query)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def fetch_category(spec: dict, category: str) -> dict:
    """カテゴリ（cand/building/power/mast/forest/air）ごとに別々に取得する。
    1 つの巨大クエリにまとめると Overpass が 504 を返しやすいので分割する。
    失敗したカテゴリは空データとして扱い、そのカテゴリの障害物なしで処理を続ける
    （現地確認が前提のツールなので、取れなかった分は clearance が甘めに出るだけ）。
    """
    query_builder = CATEGORY_QUERIES[category]
    try:
        return fetch_cached(f"area_{spec['key']}_{category}", query_builder, spec)
    except RuntimeError as exc:
        print(f"  {category} の取得に失敗（このカテゴリなしで続行）: {exc}", file=sys.stderr)
        return {"elements": []}


def fetch_coastline(spec: dict) -> dict:
    return fetch_cached(f"coast_{spec['key']}", coastline_query, spec)



# ---------------------------------------------------------------------------
# 幾何: Overpass 要素 -> shapely（Proj で射影した平面座標系）
# ---------------------------------------------------------------------------

def _split_runs(geom_list) -> list[list[dict]]:
    """out geom(bbox) で bbox の外に出た点は null になる（構造を保つため）ので、
    null で区切って「途切れていない区間」ごとのリストに分ける。"""
    if not geom_list:
        return []
    runs: list[list[dict]] = []
    cur: list[dict] = []
    for pt in geom_list:
        if pt is None:
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(pt)
    if cur:
        runs.append(cur)
    return runs


def _ring_xy(geom_list, proj: Proj) -> list[tuple[float, float]] | None:
    if not geom_list or len(geom_list) < 3:
        return None
    return [proj.to_xy(pt["lat"], pt["lon"]) for pt in geom_list]


def _safe_polygon(ring: list[tuple[float, float]]) -> Polygon | None:
    try:
        poly = Polygon(ring)
    except Exception:  # noqa: BLE001
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < 1e-6:
        return None
    return poly


def _way_polygons(geom_list, proj: Proj) -> list[Polygon]:
    """1 つの way の geometry（null で分断されうる）から、切れ目ごとにポリゴンを作る。"""
    polys = []
    for run in _split_runs(geom_list):
        if len(run) < 3:
            continue
        ring = [proj.to_xy(pt["lat"], pt["lon"]) for pt in run]
        poly = _safe_polygon(ring)
        if poly is not None:
            polys.append(poly)
    return polys


def build_area_polygon(elem: dict, proj: Proj):
    """way または relation（マルチポリゴン）から shapely ポリゴンを作る（穴あき対応）。

    out geom(bbox) で bbox の外に出た点は null になっているので、null で切れた
    区間ごとに別のポリゴンとして扱い、最後に和をとる。"""
    if elem["type"] == "way":
        polys = _way_polygons(elem.get("geometry"), proj)
        if not polys:
            return None
        geom = unary_union(polys) if len(polys) > 1 else polys[0]
        return None if geom.is_empty else geom
    if elem["type"] == "relation":
        outers, inners = [], []
        for m in elem.get("members", []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            polys = _way_polygons(m["geometry"], proj)
            if m.get("role") == "inner":
                inners.extend(polys)
            else:
                outers.extend(polys)
        if not outers:
            return None
        geom = unary_union(outers)
        if inners:
            geom = geom.difference(unary_union(inners))
        if geom.is_empty:
            return None
        return geom
    return None


def _way_lines(geom_list, proj: Proj) -> list:
    """1 つの way の geometry（null で分断されうる）から線分・点を作る。"""
    out = []
    for run in _split_runs(geom_list):
        if len(run) == 1:
            out.append(Point(proj.to_xy(run[0]["lat"], run[0]["lon"])))
        elif len(run) >= 2:
            out.append(LineString([proj.to_xy(p["lat"], p["lon"]) for p in run]))
    return out


def build_line_obstacles(elem: dict, proj: Proj) -> list:
    """送電線・林縁など「線」障害物の shapely ジオメトリ（複数になりうる）。"""
    out = []
    if elem["type"] == "way":
        out.extend(_way_lines(elem.get("geometry"), proj))
    elif elem["type"] == "node":
        out.append(Point(proj.to_xy(elem["lat"], elem["lon"])))
    elif elem["type"] == "relation":
        for m in elem.get("members", []):
            if m.get("type") == "way" and m.get("geometry"):
                out.extend(_way_lines(m["geometry"], proj))
    return out


def build_area_boundary(elem: dict, proj: Proj) -> list:
    """森林・空港ポリゴンなどを「輪郭線」（面ではなく線）の障害物として返す。"""
    poly = build_area_polygon(elem, proj)
    if poly is None:
        return []
    geoms = poly.geoms if isinstance(poly, MultiPolygon) else [poly]
    return [LineString(g.exterior.coords) for g in geoms if not g.exterior.is_empty]


# ---------------------------------------------------------------------------
# STRtree ラッパー（空でも安全に nearest を返す）
# ---------------------------------------------------------------------------

class ObstacleIndex:
    def __init__(self, geoms: list):
        self.geoms = [g for g in geoms if g is not None and not g.is_empty]
        self.tree = STRtree(self.geoms) if self.geoms else None

    def nearest_many(self, points: np.ndarray) -> np.ndarray:
        """points: shapely Point の配列。各点までの最短距離 [m] の配列を返す。"""
        n = len(points)
        if self.tree is None or n == 0:
            return np.full(n, math.inf)
        idx, dist = self.tree.query_nearest(points, return_distance=True, all_matches=False)
        out = np.full(n, math.inf)
        out[idx[0]] = dist
        return out

    def nearest_one(self, point: Point) -> float:
        if self.tree is None:
            return math.inf
        idx, dist = self.tree.query_nearest(np.array([point]), return_distance=True,
                                             all_matches=False)
        if len(dist) == 0:
            return math.inf
        return float(dist[0])


# ---------------------------------------------------------------------------
# 候補ポリゴン 1 件分の処理
# ---------------------------------------------------------------------------

def best_launch_point(poly, obstacle_indices: dict[str, ObstacleIndex]):
    """ポリゴン内部で障害物からのクリアランスを最大化する点を探す。

    戻り値: (best_x, best_y, clearance_m, per_obstacle dict, dist_edge_m)
    """
    minx, miny, maxx, maxy = poly.bounds
    width, height = maxx - minx, maxy - miny
    if width <= 0 or height <= 0:
        pt = poly.representative_point()
        return pt.x, pt.y, 0.0, {k: math.inf for k in obstacle_indices}, 0.0

    nx = max(1, int(width / GRID_SPACING_M) + 1)
    ny = max(1, int(height / GRID_SPACING_M) + 1)
    if nx * ny > GRID_MAX_SAMPLES:
        scale = math.sqrt((nx * ny) / GRID_MAX_SAMPLES)
        spacing = GRID_SPACING_M * scale
        nx = max(1, int(width / spacing) + 1)
        ny = max(1, int(height / spacing) + 1)

    xs = minx + (np.arange(nx) + 0.5) * (width / nx)
    ys = miny + (np.arange(ny) + 0.5) * (height / ny)
    gx, gy = np.meshgrid(xs, ys)
    gx, gy = gx.ravel(), gy.ravel()
    pts = shapely.points(gx, gy)

    inside = shapely.contains(poly, pts)
    if not inside.any():
        rp = poly.representative_point()
        pts = np.array([rp])
        gx, gy = np.array([rp.x]), np.array([rp.y])
    else:
        pts = pts[inside]
        gx, gy = gx[inside], gy[inside]

    per_obstacle = {}
    clearance = np.full(len(pts), math.inf)
    for name, idx in obstacle_indices.items():
        d = idx.nearest_many(pts)
        per_obstacle[name] = d
        clearance = np.minimum(clearance, d)

    best_i = int(np.argmax(clearance))
    best_x, best_y = float(gx[best_i]), float(gy[best_i])
    best_clearance = float(clearance[best_i]) if math.isfinite(clearance[best_i]) else 9999.0
    best_per = {k: (float(v[best_i]) if math.isfinite(v[best_i]) else 9999.0)
                for k, v in per_obstacle.items()}
    dist_edge = float(shapely.distance(Point(best_x, best_y), poly.boundary))
    return best_x, best_y, best_clearance, best_per, dist_edge


def classify_kind(tags: dict) -> tuple[str, str, str]:
    """(kind, sport, note) を返す。"""
    leisure = tags.get("leisure", "")
    landuse = tags.get("landuse", "")
    amenity = tags.get("amenity", "")
    sport = tags.get("sport", "")
    if leisure in LEISURE_CAND:
        return leisure, sport, ""
    if landuse in LANDUSE_CAND:
        return landuse, sport, ""
    if amenity in AMENITY_CAND:
        note = "学校敷地内のグラウンド。使用には学校・教育委員会等の許可が必要"
        return amenity, sport, note
    return "other", sport, ""


# ---------------------------------------------------------------------------
# エリア 1 件分の処理
# ---------------------------------------------------------------------------

def process_area(group: str, spec: dict) -> list[dict]:
    def tags_of(e):
        return e.get("tags", {})

    cand_elems = fetch_category(spec, "cand").get("elements", [])
    print(f"  cand {len(cand_elems)} 件を取得", flush=True)
    bld_elems = fetch_category(spec, "building").get("elements", [])
    print(f"  building {len(bld_elems)} 件を取得", flush=True)
    pwr_all = fetch_category(spec, "power").get("elements", [])
    print(f"  power {len(pwr_all)} 件を取得", flush=True)
    mast_elems = fetch_category(spec, "mast").get("elements", [])
    print(f"  mast {len(mast_elems)} 件を取得", flush=True)
    forest_all = fetch_category(spec, "forest").get("elements", [])
    print(f"  forest {len(forest_all)} 件を取得", flush=True)
    air_elems = fetch_category(spec, "air").get("elements", [])
    print(f"  air {len(air_elems)} 件を取得", flush=True)
    named_elems = fetch_category(spec, "named").get("elements", [])
    print(f"  named {len(named_elems)} 件を取得", flush=True)

    pwr_elems = [e for e in pwr_all
                 if (e["type"] == "way" and tags_of(e).get("power") in ("line", "minor_line", "cable"))
                 or (e["type"] == "node" and tags_of(e).get("power") in ("tower", "pole"))]
    forest_line_elems = [e for e in forest_all if tags_of(e).get("natural") == "tree_row"]
    forest_poly_elems = [e for e in forest_all if e["type"] in ("way", "relation") and (
        tags_of(e).get("landuse") == "forest" or tags_of(e).get("natural") == "wood")]

    if spec["kind"] == "bbox":
        c_lat = (spec["south"] + spec["north"]) / 2
        c_lon = (spec["west"] + spec["east"]) / 2
    else:
        c_lat, c_lon = spec["lat"], spec["lon"]
    proj = Proj(c_lat, c_lon)

    # 障害物インデックス
    bld_geoms = []
    for e in bld_elems:
        g = build_area_polygon(e, proj)
        if g is not None:
            bld_geoms.append(g)
    pwr_geoms = []
    for e in pwr_elems:
        pwr_geoms.extend(build_line_obstacles(e, proj))
    mast_geoms = []
    for e in mast_elems:
        mast_geoms.extend(build_line_obstacles(e, proj))
    forest_geoms = []
    for e in forest_line_elems:
        forest_geoms.extend(build_line_obstacles(e, proj))
    for e in forest_poly_elems:
        forest_geoms.extend(build_area_boundary(e, proj))
    air_geoms = []
    for e in air_elems:
        if tags_of(e).get("aeroway") == "runway":
            air_geoms.extend(build_line_obstacles(e, proj))
        else:
            poly = build_area_polygon(e, proj) if e["type"] != "node" else None
            if poly is not None:
                air_geoms.append(poly)
            else:
                air_geoms.extend(build_line_obstacles(e, proj))

    obstacle_indices = {
        "power": ObstacleIndex(pwr_geoms),
        "building": ObstacleIndex(bld_geoms),
        "mast": ObstacleIndex(mast_geoms),
        "forest": ObstacleIndex(forest_geoms),
    }
    airport_index = ObstacleIndex(air_geoms)

    # 名前つき地物（「（付近: XX）」表示用）。候補ごとに問い合わせると遅いので、
    # エリアごとに 1 回取った一覧から近傍探索する。
    named_points = []
    named_names = []
    for el in named_elems:
        nm = name_of(tags_of(el))
        if not nm:
            continue
        if el["type"] == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        named_points.append(Point(proj.to_xy(lat, lon)))
        named_names.append(nm)
    named_tree = STRtree(named_points) if named_points else None
    print(f"  障害物: building {len(bld_geoms)} / power {len(pwr_geoms)} / "
          f"mast {len(mast_geoms)} / forest {len(forest_geoms)} / named {len(named_points)}",
          flush=True)

    # 候補ポリゴンを作る（名前解決のため先に全部作る）。
    # Overpass には外接矩形で問い合わせているので、円のエリアはここで半径 12 km に
    # 絞り込む（proj の原点が円の中心なので、原点からの距離がそのまま使える）。
    radius_m = spec["radius_km"] * 1000.0 if spec["kind"] == "circle" else None
    cand_info = []  # (elem, geom, area_m2)
    for e in cand_elems:
        tags = tags_of(e)
        landuse = tags.get("landuse", "")
        geom = build_area_polygon(e, proj)
        if geom is None or geom.is_empty:
            continue
        if radius_m is not None:
            c = geom.centroid
            if math.hypot(c.x, c.y) > radius_m:
                continue
        area_m2 = geom.area
        if landuse == "grass" and area_m2 < MIN_GRASS_AREA_M2:
            continue
        if area_m2 < MIN_AREA_M2:
            continue
        cand_info.append((e, geom, area_m2))

    named_polys = [(geom, name_of(tags_of(e))) for e, geom, _ in cand_info if name_of(tags_of(e))]
    print(f"  候補ポリゴン（面積・半径で絞り込み後）: {len(cand_info)} 件。"
          f"クリアランス計算を開始", flush=True)

    rows = []
    for ci, (e, geom, area_m2) in enumerate(cand_info):
        if ci and ci % 20 == 0:
            print(f"    ...{ci}/{len(cand_info)} 件処理済み", flush=True)
        tags = tags_of(e)
        kind, sport, note = classify_kind(tags)
        bx, by, clearance, per_obs, dist_edge = best_launch_point(geom, obstacle_indices)
        best_lat, best_lon = proj.to_lonlat(bx, by)

        dist_air_m = airport_index.nearest_one(Point(bx, by))
        dist_air_km = dist_air_m / 1000.0 if math.isfinite(dist_air_m) else math.inf

        name = name_of(tags)
        nearby_marker = False
        if not name:
            pt = Point(bx, by)
            for other_geom, other_name in named_polys:
                if other_geom is geom:
                    continue
                if other_geom.contains(pt):
                    name = other_name
                    break
        if not name and named_tree is not None:
            pt = Point(bx, by)
            i = named_tree.nearest(pt)
            cand_pt = named_points[i]
            d = math.hypot(cand_pt.x - bx, cand_pt.y - by)
            if d <= NEARBY_NAME_RADIUS_M:
                name = f"（付近: {named_names[i]}）"
                nearby_marker = True

        rows.append({
            "area_group": group,
            "kind": kind,
            "sport": sport,
            "name": name,
            "name_is_nearby": nearby_marker,
            "best_lat": round(best_lat, 6),
            "best_lon": round(best_lon, 6),
            "area_m2": round(area_m2, 1),
            "clearance_m": round(clearance, 1),
            "dist_power_m": round(per_obs["power"], 1),
            "dist_building_m": round(per_obs["building"], 1),
            "dist_mast_m": round(per_obs["mast"], 1),
            "dist_forest_m": round(per_obs["forest"], 1),
            "dist_edge_m": round(dist_edge, 1),
            "dist_airport_km": round(dist_air_km, 2) if math.isfinite(dist_air_km) else "",
            "osm_type": e["type"],
            "osm_id": e["id"],
            "osm_url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
            "google_maps_url": f"https://www.google.com/maps?q={best_lat:.6f},{best_lon:.6f}",
            "note": note,
        })
    return rows


# ---------------------------------------------------------------------------
# CLI / メイン処理
# ---------------------------------------------------------------------------

OUT_COLUMNS = [
    "area_group", "kind", "sport", "name", "best_lat", "best_lon", "area_m2",
    "clearance_m", "dist_power_m", "dist_building_m", "dist_mast_m", "dist_forest_m",
    "dist_edge_m", "dist_airport_km", "near_airport_flag", "osm_type", "osm_id",
    "osm_url", "google_maps_url", "note",
]


def dedupe_keep_best(rows: list[dict]) -> list[dict]:
    best: dict[tuple[str, int], dict] = {}
    for r in rows:
        key = (r["osm_type"], r["osm_id"])
        cur = best.get(key)
        if cur is None or r["clearance_m"] > cur["clearance_m"]:
            best[key] = r
    return list(best.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--area", default=None, help="このグループ名だけ処理する（デバッグ用）")
    args = ap.parse_args()

    specs = AREA_QUERIES
    if args.area:
        specs = [s for s in specs if s[0] == args.area]

    all_rows: list[dict] = []
    for i, (group, key, kind, params) in enumerate(specs):
        spec = {"key": key, "kind": kind, **params}
        was_cached = (CACHE_DIR / f"area_{key}.json").exists()
        label = (f"{spec['south']:.2f}-{spec['north']:.2f}N/{spec['west']:.2f}-{spec['east']:.2f}E"
                 if kind == "bbox" else f"{spec['lat']:.2f},{spec['lon']:.2f} r={spec['radius_km']}km")
        print(f"[{i + 1}/{len(specs)}] {group} / {key} ({label})"
              f"{'  [cache]' if was_cached else ''}", flush=True)
        t0 = time.time()
        try:
            rows = process_area(group, spec)
        except RuntimeError as exc:
            print(f"  失敗: {exc}", file=sys.stderr)
            rows = []
        print(f"  -> 候補 {len(rows)} 件（{time.time() - t0:.1f} 秒）", flush=True)
        all_rows.extend(rows)
        if not was_cached and i < len(specs) - 1:
            time.sleep(random.uniform(3.0, 6.0))

    rows = dedupe_keep_best(all_rows)
    n_dup = len(all_rows) - len(rows)
    print(f"重複除去: {len(all_rows)} -> {len(rows)} 件（{n_dup} 件が重複）")

    n_airport_excluded = 0
    kept = []
    for r in rows:
        dk = r["dist_airport_km"]
        if dk != "" and dk < AIRPORT_EXCLUDE_KM:
            n_airport_excluded += 1
            continue
        r["near_airport_flag"] = "空港に近い" if (dk != "" and dk < AIRPORT_WARN_KM) else ""
        if r["clearance_m"] >= MIN_CLEARANCE_M:
            kept.append(r)
    print(f"空港 {AIRPORT_EXCLUDE_KM} km 以内を除外: {n_airport_excluded} 件")
    n_area_fail = sum(1 for r in rows if r["area_m2"] < MIN_AREA_M2)
    print(f"面積 {MIN_AREA_M2:.0f} m2 未満（参考。基本は取得時点で除外済み）: {n_area_fail} 件")

    kept.sort(key=lambda r: (-r["clearance_m"], -r["area_m2"]))

    RESULTS.mkdir(parents=True, exist_ok=True)
    out_all = RESULTS / "osm_spots.csv"
    with open(out_all, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for r in kept:
            w.writerow({k: r.get(k, "") for k in OUT_COLUMNS})
    print(f"{out_all} に {len(kept)} 行")

    iki_rows = [r for r in kept if r["area_group"] == "壱岐"]
    out_iki = RESULTS / "osm_spots_iki.csv"
    with open(out_iki, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for r in iki_rows:
            w.writerow({k: r.get(k, "") for k in OUT_COLUMNS})
    print(f"{out_iki} に {len(iki_rows)} 行")

    print("\nエリア別・クリアランス別の件数:")
    print(f"{'area_group':<12}{'>=40m':>8}{'>=60m':>8}{'>=100m':>8}")
    for g in AREA_GROUP_ORDER:
        sub = [r for r in kept if r["area_group"] == g]
        c40 = sum(1 for r in sub if r["clearance_m"] >= 40)
        c60 = sum(1 for r in sub if r["clearance_m"] >= 60)
        c100 = sum(1 for r in sub if r["clearance_m"] >= 100)
        print(f"{g:<12}{c40:>8}{c60:>8}{c100:>8}")
    c40 = sum(1 for r in kept if r["clearance_m"] >= 40)
    c60 = sum(1 for r in kept if r["clearance_m"] >= 60)
    c100 = sum(1 for r in kept if r["clearance_m"] >= 100)
    print(f"{'合計':<12}{c40:>8}{c60:>8}{c100:>8}")

    if not args.no_figures:
        from osm_spots_figures import make_iki_figure, make_overview_figure
        iki_spec = dict(key=AREA_QUERIES[0][1], kind="bbox", **AREA_QUERIES[0][3])
        make_iki_figure(kept, iki_spec)
        make_overview_figure(kept, AREA_QUERIES)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
