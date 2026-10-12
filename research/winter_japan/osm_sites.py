"""候補地点の周りで、電柱・電線や建物から離れた広場（公園・グラウンドなど）を
OpenStreetMap（Overpass API）から探す。

風の気候値（グリッド約 5 km）から選んだ打ち上げ候補地点について、実際に打ち上げ
できそうな広場を機械的に絞り込むための下ごしらえ。最終判断は必ず現地確認すること
（後述の注意点も参照）。

対象とする「開けた場所」:
    leisure=pitch, leisure=park, leisure=sports_centre, leisure=recreation_ground,
    landuse=recreation_ground
    （leisure=playground は除く）

各ポリゴンについて面積・重心を計算し、重心から最寄りの送電線（power=line /
power=minor_line）と最寄りの建物（building=*）までの距離を求める。以下をすべて
満たすものだけを残す:

    面積 >= 10,000 m2（1 ha）
    最寄りの送電線まで >= 150 m
    最寄りの建物まで   >= 60 m

残った候補を「クリアランス（送電線・建物までの距離の小さい方）→ 面積」の順に
並べ、候補地点ごとに上位 5 件を出力する。

使い方:
    python osm_sites.py input.csv --out results/osm_sites.csv --radius-km 8

入力 CSV は name,lat,lon の列を持つこと。

Overpass への配慮:
    候補地点ごとに 1 回のリクエストにまとめる（開けた場所・送電線・建物の 3 種類
    を 1 クエリに同居させる）。タイムアウトは 180 秒、候補地点の間は 2〜5 秒あける。
    429 (Too Many Requests) / 504 (Gateway Timeout) はバックオフして再試行し、
    それでも駄目なら別のミラーサーバーに切り替える。生の JSON レスポンスは
    data/osm_cache/ 以下にキャッシュし、再実行では通信しない。
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

import requests

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "data" / "osm_cache"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

TIMEOUT_S = 180
USER_AGENT = ("falling-position-simulator2026/osm_sites.py "
              "(research tool)")
MIN_AREA_M2 = 10_000.0
MIN_POWER_DIST_M = 150.0
MIN_BUILDING_DIST_M = 60.0
TOP_N = 5
EARTH_R_M = 6_371_000.0

OPEN_LEISURE = ("pitch", "park", "sports_centre", "recreation_ground")


# ---------------------------------------------------------------------------
# Overpass 問い合わせ
# ---------------------------------------------------------------------------

def build_query(lat: float, lon: float, radius_m: float) -> str:
    """開けた場所・送電線・建物をまとめて取ってくる Overpass QL を作る。"""
    around = f"(around:{radius_m:.0f},{lat:.6f},{lon:.6f})"
    leisure_re = "^(" + "|".join(OPEN_LEISURE) + ")$"
    return f"""
[out:json][timeout:{TIMEOUT_S}];
(
  way["leisure"~"{leisure_re}"]{around};
  relation["leisure"~"{leisure_re}"]{around};
  way["landuse"="recreation_ground"]{around};
  relation["landuse"="recreation_ground"]{around};
)->.open;
(
  way["power"~"^(line|minor_line)$"]{around};
)->.power;
(
  way["building"]{around};
  relation["building"]{around};
)->.building;
.open out geom;
.power out geom;
.building out geom;
""".strip()


def cache_path(lat: float, lon: float, radius_km: float) -> Path:
    key = f"{lat:.3f}_{lon:.3f}_r{radius_km:.1f}.json"
    return CACHE_DIR / key


def fetch_overpass(lat: float, lon: float, radius_km: float) -> dict:
    """候補地点まわりの Overpass 結果を取得する（キャッシュがあればそれを使う）。"""
    path = cache_path(lat, lon, radius_km)
    if path.exists():
        return json.loads(path.read_text())

    query = build_query(lat, lon, radius_km * 1000.0)
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        backoff = 5.0
        for attempt in range(4):
            try:
                resp = requests.post(url, data={"data": query}, timeout=TIMEOUT_S + 10,
                                      headers={"User-Agent": USER_AGENT})
            except requests.RequestException as exc:
                last_err = exc
                print(f"  接続エラー ({url}): {exc}", file=sys.stderr)
                break  # このミラーは諦めて次のミラーへ
            if resp.status_code == 200:
                data = resp.json()
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
                return data
            if resp.status_code in (429, 504):
                print(f"  {resp.status_code} を受信、{backoff:.0f} 秒待って再試行"
                      f" ({url}, {attempt + 1}回目)", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                continue
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            break
    raise RuntimeError(f"Overpass への問い合わせに失敗: {last_err}")


# ---------------------------------------------------------------------------
# 幾何計算（候補地点を原点にした正距円筒図法で平面近似）
# ---------------------------------------------------------------------------

class Proj:
    """候補地点を原点にした簡易平面投影（等距円筒図法）。"""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.cos0 = math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        x = math.radians(lon - self.lon0) * EARTH_R_M * self.cos0
        y = math.radians(lat - self.lat0) * EARTH_R_M
        return x, y

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        lon = self.lon0 + math.degrees(x / (EARTH_R_M * self.cos0))
        lat = self.lat0 + math.degrees(y / EARTH_R_M)
        return lat, lon


def ring_area_centroid(xy: list[tuple[float, float]]) -> tuple[float, float, float]:
    """閉じた輪（shoelace 公式）の符号付き面積と重心を返す。

    xy は [(x0,y0), (x1,y1), ...] で、最初と最後の点が同じでなくてもよい
    （内部で閉じる）。
    """
    pts = list(xy)
    if len(pts) < 3:
        return 0.0, 0.0, 0.0
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    a = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:], strict=True):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-9:
        n = len(pts) - 1
        return 0.0, sum(p[0] for p in pts[:-1]) / n, sum(p[1] for p in pts[:-1]) / n
    cx /= (6 * a)
    cy /= (6 * a)
    return a, cx, cy


def point_to_segment_dist(px: float, py: float, ax: float, ay: float,
                           bx: float, by: float) -> float:
    """点 (px,py) から線分 (a,b) までの距離。"""
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
    t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def point_to_polyline_dist(px: float, py: float, xy: list[tuple[float, float]]) -> float:
    """点から折れ線（またはポリゴンの輪）までの最短距離。"""
    best = math.inf
    for (ax, ay), (bx, by) in zip(xy[:-1], xy[1:], strict=True):
        d = point_to_segment_dist(px, py, ax, ay, bx, by)
        if d < best:
            best = d
    return best


# ---------------------------------------------------------------------------
# Overpass 要素 -> 幾何情報への変換
# ---------------------------------------------------------------------------

def way_xy(elem: dict, proj: Proj) -> list[tuple[float, float]] | None:
    geom = elem.get("geometry")
    if not geom:
        return None
    return [proj.to_xy(pt["lat"], pt["lon"]) for pt in geom]


def open_area_polygons(elem: dict, proj: Proj) -> list[list[tuple[float, float]]]:
    """way または relation（マルチポリゴン）から outer の輪だけを取り出す。"""
    if elem["type"] == "way":
        xy = way_xy(elem, proj)
        return [xy] if xy else []
    if elem["type"] == "relation":
        rings = []
        for m in elem.get("members", []):
            if m.get("type") == "way" and m.get("role") == "outer" and m.get("geometry"):
                rings.append([proj.to_xy(pt["lat"], pt["lon"]) for pt in m["geometry"]])
        return rings
    return []


def name_of(tags: dict) -> str:
    return tags.get("name:ja") or tags.get("name") or ""


def polylines_of(elem: dict, proj: Proj) -> list[list[tuple[float, float]]]:
    """送電線・建物 1 件分の折れ線（複数になりうる）を返す。"""
    if elem["type"] == "way":
        xy = way_xy(elem, proj)
        return [xy] if xy and len(xy) >= 2 else []
    if elem["type"] == "relation":
        lines = []
        for m in elem.get("members", []):
            if m.get("type") == "way" and m.get("geometry"):
                xy = [proj.to_xy(pt["lat"], pt["lon"]) for pt in m["geometry"]]
                if len(xy) >= 2:
                    lines.append(xy)
        return lines
    return []


def nearest_dist(cx: float, cy: float, elements: list[dict], proj: Proj) -> float:
    """重心 (cx, cy) から要素群（送電線 or 建物）までの最短距離 [m]。"""
    best = math.inf
    for elem in elements:
        for line in polylines_of(elem, proj):
            d = point_to_polyline_dist(cx, cy, line)
            if d < best:
                best = d
    return best


# ---------------------------------------------------------------------------
# 候補地点 1 件分の処理
# ---------------------------------------------------------------------------

def process_candidate(name: str, lat: float, lon: float, radius_km: float) -> list[dict]:
    data = fetch_overpass(lat, lon, radius_km)
    elements = data.get("elements", [])
    open_elems = [e for e in elements if e["type"] in ("way", "relation")
                  and (e.get("tags", {}).get("leisure") in OPEN_LEISURE
                       or e.get("tags", {}).get("landuse") == "recreation_ground")]
    power_elems = [e for e in elements if e["type"] in ("way", "relation")
                   and e.get("tags", {}).get("power") in ("line", "minor_line")]
    building_elems = [e for e in elements if e["type"] in ("way", "relation")
                       and "building" in e.get("tags", {})]

    proj = Proj(lat, lon)
    rows = []
    for elem in open_elems:
        rings = open_area_polygons(elem, proj)
        if not rings:
            continue
        # 複数の outer 輪を持つマルチポリゴンは面積で合算し、重心は面積加重平均にする
        total_area = 0.0
        weighted_cx = 0.0
        weighted_cy = 0.0
        for ring in rings:
            a, cx, cy = ring_area_centroid(ring)
            a = abs(a)
            total_area += a
            weighted_cx += a * cx
            weighted_cy += a * cy
        if total_area < 1e-6:
            continue
        cx = weighted_cx / total_area
        cy = weighted_cy / total_area

        if total_area < MIN_AREA_M2:
            continue

        dist_power = nearest_dist(cx, cy, power_elems, proj)
        dist_building = nearest_dist(cx, cy, building_elems, proj)
        if dist_power < MIN_POWER_DIST_M or dist_building < MIN_BUILDING_DIST_M:
            continue

        c_lat, c_lon = proj.to_lonlat(cx, cy)
        dist_from_cand_m = math.hypot(cx, cy)
        tags = elem.get("tags", {})
        rows.append({
            "candidate": name,
            "osm_type": elem["type"],
            "osm_id": elem["id"],
            "name": name_of(tags),
            "lat": round(c_lat, 6),
            "lon": round(c_lon, 6),
            "area_m2": round(total_area, 1),
            "dist_power_m": (round(dist_power, 1) if math.isfinite(dist_power) else ""),
            "dist_building_m": (round(dist_building, 1) if math.isfinite(dist_building) else ""),
            "dist_from_candidate_km": round(dist_from_cand_m / 1000.0, 3),
            "osm_url": f"https://www.openstreetmap.org/{elem['type']}/{elem['id']}",
        })

    def clearance(row: dict) -> float:
        dp = row["dist_power_m"] if row["dist_power_m"] != "" else math.inf
        db = row["dist_building_m"] if row["dist_building_m"] != "" else math.inf
        return min(dp, db)

    rows.sort(key=lambda r: (-clearance(r), -r["area_m2"]))
    return rows[:TOP_N]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

OUT_COLUMNS = ["candidate", "osm_type", "osm_id", "name", "lat", "lon", "area_m2",
               "dist_power_m", "dist_building_m", "dist_from_candidate_km", "osm_url"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input_csv", type=Path, help="name,lat,lon の列を持つ CSV")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "osm_sites.csv")
    ap.add_argument("--radius-km", type=float, default=8.0)
    args = ap.parse_args()

    with open(args.input_csv, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    all_rows: list[dict] = []
    for i, row in enumerate(candidates):
        name = row["name"]
        lat, lon = float(row["lat"]), float(row["lon"])
        was_cached = cache_path(lat, lon, args.radius_km).exists()
        print(f"[{i + 1}/{len(candidates)}] {name} ({lat}, {lon})"
              f"{'  [cache]' if was_cached else ''}", flush=True)
        try:
            rows = process_candidate(name, lat, lon, args.radius_km)
        except RuntimeError as exc:
            print(f"  失敗: {exc}", file=sys.stderr)
            rows = []
        print(f"  -> {len(rows)} 件（上位 {TOP_N} 件まで）", flush=True)
        all_rows.extend(rows)
        if not was_cached and i < len(candidates) - 1:
            time.sleep(random.uniform(2.0, 5.0))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"{args.out} に {len(all_rows)} 行を書き出した", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
