"""osm_spots.py の結果を地図にする。

壱岐島の詳細図（海岸線は OSM の natural=coastline、建物も薄く重ねる）と、
北部九州・西部山口全体の概観図（海岸線は frontend の land.json）の 2 枚を作る。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from osm_spots import FIGS, fetch_category, fetch_coastline  # noqa: E402
from windclim.figures.coast import draw_coastline, set_geographic_aspect  # noqa: E402
from windclim.figures.style import apply_style, INK  # noqa: E402
from windclim.regions import BBox  # noqa: E402

# 壱岐空港 RJDB（OSM の aerodrome から取れなければこの値にフォールバックする）
IKI_AIRPORT_FALLBACK = (33.749, 129.785)

TIER_COLORS = {
    "100+": "#1baf7a",   # windclim CATEGORICAL の緑
    "60-100": "#eda100",  # 同・黄
    "40-60": "#eb6834",   # 同・橙
}


def clearance_tier(c: float) -> str:
    if c >= 100:
        return "100+"
    if c >= 60:
        return "60-100"
    return "40-60"


def _iki_airport_center(iki_spec: dict) -> tuple[float, float]:
    data = fetch_category(iki_spec, "air")
    lats, lons = [], []
    for e in data.get("elements", []):
        if e.get("tags", {}).get("aeroway") != "aerodrome":
            continue
        geom = e.get("geometry")
        if geom:
            lats.extend(p["lat"] for p in geom)
            lons.extend(p["lon"] for p in geom)
    if lats:
        return sum(lats) / len(lats), sum(lons) / len(lons)
    return IKI_AIRPORT_FALLBACK


def make_iki_figure(kept: list[dict], iki_spec: dict) -> None:
    apply_style(japanese=True)
    rows = [r for r in kept if r["area_group"] == "壱岐"]
    rows_sorted = sorted(rows, key=lambda r: (-r["clearance_m"], -r["area_m2"]))

    fig, (ax, ax_tbl) = plt.subplots(
        1, 2, figsize=(13, 8), gridspec_kw={"width_ratios": [2.6, 1.0]}
    )

    # 海岸線（OSM）
    coast = fetch_coastline(iki_spec)
    n_coast = 0
    for e in coast.get("elements", []):
        geom = e.get("geometry")
        if not geom:
            continue
        lons = [p["lon"] for p in geom]
        lats = [p["lat"] for p in geom]
        ax.plot(lons, lats, color=INK["secondary"], linewidth=0.9, zorder=5)
        n_coast += 1
    if n_coast == 0:
        # OSM から取れなかった場合は frontend の海岸線で代用する
        bbox = BBox(south=iki_spec["south"], north=iki_spec["north"],
                    west=iki_spec["west"], east=iki_spec["east"])
        draw_coastline(ax, bbox, fill=True, fill_zorder=0)

    # 建物を薄く重ねる（軽いので）
    bld = fetch_category(iki_spec, "building")
    segs = []
    for e in bld.get("elements", []):
        geom = e.get("geometry")
        if geom and len(geom) >= 2:
            segs.append([(p["lon"], p["lat"]) for p in geom])
    if segs:
        from matplotlib.collections import LineCollection
        ax.add_collection(LineCollection(segs, colors="#c8c6c0", linewidths=0.3, zorder=1))

    # 空港と 3 km 円
    air_lat, air_lon = _iki_airport_center(iki_spec)
    dlat = 3.0 / 111.195
    ax.add_patch(Circle((air_lon, air_lat), radius=dlat, fill=False,
                         edgecolor="#8c1f1f", linewidth=1.2, linestyle="--", zorder=6))
    ax.plot(air_lon, air_lat, marker="^", color="#8c1f1f", markersize=8, zorder=7)
    ax.annotate("壱岐空港 (3 km 圏)", (air_lon, air_lat), textcoords="offset points",
                xytext=(6, 6), fontsize=8, color="#8c1f1f")

    for r in rows:
        tier = clearance_tier(r["clearance_m"])
        ax.scatter(r["best_lon"], r["best_lat"], color=TIER_COLORS[tier], s=26,
                   edgecolor="white", linewidth=0.4, zorder=8)

    top = rows_sorted[:15]
    # 同じ学校・公園の別ポリゴン（校庭とピッチなど）がほぼ同じ場所に来ることが
    # あるので、近い点ほど角度と距離をずらしてラベルの重なりを避ける。
    placed: list[tuple[float, float]] = []
    for i, r in enumerate(top, start=1):
        lon, lat = r["best_lon"], r["best_lat"]
        k = sum(1 for plon, plat in placed
                if abs(plon - lon) < 0.0015 and abs(plat - lat) < 0.0015)
        angle = math.radians(50 * k + 25)
        radius = 7 + 6 * k
        dx, dy = radius * math.cos(angle), radius * math.sin(angle)
        ax.annotate(str(i), (lon, lat), fontsize=7, fontweight="bold", color=INK["primary"],
                    textcoords="offset points", xytext=(dx, dy), zorder=9,
                    bbox=dict(boxstyle="circle,pad=0.15", fc="white", ec="none", alpha=0.8))
        placed.append((lon, lat))

    ax.set_xlim(iki_spec["west"], iki_spec["east"])
    ax.set_ylim(iki_spec["south"], iki_spec["north"])
    set_geographic_aspect(ax, (iki_spec["south"] + iki_spec["north"]) / 2)
    ax.set_title(f"壱岐島 打ち上げ候補地 (OSM, n={len(rows)})")
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")

    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markersize=8,
               label=f"クリアランス {label} m")
        for label, c in [("100 以上", TIER_COLORS["100+"]),
                         ("60〜100", TIER_COLORS["60-100"]),
                         ("40〜60", TIER_COLORS["40-60"])]
    ]
    legend_handles.append(Line2D([0], [0], marker="^", color="#8c1f1f", linestyle="none",
                                  markersize=8, label="空港・3 km 圏"))
    ax.legend(handles=legend_handles, loc="lower left", fontsize=8)

    # 右側: 上位表
    ax_tbl.axis("off")
    lines = [f"{i}. {r['name'] or r['kind']}\n"
             f"    clearance {r['clearance_m']:.0f} m / {r['area_m2'] / 10000:.2f} ha"
             for i, r in enumerate(top, start=1)]
    ax_tbl.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=7.5,
                family="monospace" if False else None, transform=ax_tbl.transAxes)
    ax_tbl.set_title("上位候補（クリアランス順）", fontsize=10)

    fig.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / "launch_spots_iki.png")
    fig.savefig(FIGS / "launch_spots_iki.pdf")
    plt.close(fig)
    print(f"{FIGS / 'launch_spots_iki.png'} を書き出した")


GROUP_COLORS = {
    "壱岐": "#1baf7a", "唐津・呼子": "#2a78d6", "平戸": "#eda100", "糸島": "#8c1f1f",
    "下関": "#7a4fb5", "長門": "#c2185b", "宗像・福津": "#0d7d7d", "北九州": "#eb6834",
    "唐津・相知": "#555555",
}


def make_overview_figure(kept: list[dict], area_queries: list[tuple]) -> None:
    apply_style(japanese=True)
    fig, ax = plt.subplots(figsize=(9, 10))

    south = min(min(s["lat"] - s["radius_km"] / 111.195 if k == "circle" else s["south"]
                     for _, _, k, s in area_queries), 33.0) - 0.15
    north = max(max(s["lat"] + s["radius_km"] / 111.195 if k == "circle" else s["north"]
                     for _, _, k, s in area_queries), 34.9) + 0.15
    west = min(min(s["lon"] - s["radius_km"] / (111.195 * 0.84) if k == "circle" else s["west"]
                    for _, _, k, s in area_queries), 129.1) - 0.15
    east = max(max(s["lon"] + s["radius_km"] / (111.195 * 0.84) if k == "circle" else s["east"]
                    for _, _, k, s in area_queries), 131.9) + 0.15

    bbox = BBox(south=south, north=north, west=west, east=east)
    draw_coastline(ax, bbox, fill=True, fill_zorder=0)

    counts = {}
    for r in kept:
        counts[r["area_group"]] = counts.get(r["area_group"], 0) + 1

    order = ["壱岐", "唐津・呼子", "平戸", "糸島", "下関", "長門", "宗像・福津",
             "北九州", "唐津・相知"]
    for g in order:
        sub = [r for r in kept if r["area_group"] == g]
        if not sub:
            continue
        ax.scatter([r["best_lon"] for r in sub], [r["best_lat"] for r in sub],
                   color=GROUP_COLORS.get(g, "#333333"), s=14, alpha=0.85,
                   edgecolor="white", linewidth=0.2,
                   label=f"{g} ({counts.get(g, 0)})", zorder=5)

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    set_geographic_aspect(ax, (south + north) / 2)
    ax.set_title(f"北部九州・西部山口 打ち上げ候補地の分布 (合計 {len(kept)} 件)")
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")
    ax.legend(loc="upper left", fontsize=8, markerscale=1.5)

    fig.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / "launch_spots_overview.png")
    fig.savefig(FIGS / "launch_spots_overview.pdf")
    plt.close(fig)
    print(f"{FIGS / 'launch_spots_overview.png'} を書き出した")
