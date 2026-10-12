"""12–2 月にスペースバルーンを上げる場所（日本全国）を選ぶための図。

入力は evaluate.py / ensemble.py / stats.py の出力（results/, data/）。まだ無い
ファイルを使う図は、実行せずに [skip] と理由だけ表示して次の図に進む。

    cd research/winter_japan && python figures.py            # 全部
    cd research/winter_japan && python figures.py --only target_mask,drift_arrows
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

from windclim.figures.coast import draw_coastline  # noqa: E402
from windclim.figures.style import CATEGORICAL, CMAP_SPEED, INK, apply_style  # noqa: E402
from windclim.regions import BBox  # noqa: E402

FIGS = HERE / "figures"
RESULTS = HERE / "results"
DATA = HERE / "data"

#: 図の地図に使う範囲
JAPAN_BOX = BBox(south=24.0, north=46.0, west=122.0, east=146.0)
WEST_BOX = BBox(south=30.5, north=36.5, west=128.5, east=136.0)

#: 壱岐の代表地点（sites.csv の 1 行目）。報告書で個別に扱う
IKI_NAME = "壱岐（島の中央）"

#: 落下点の分類ごとの色（他の図でも同じ色を使う）
CLASS_COLORS = {
    "plain": "#3fa34d",       # 平野（DID の外）
    "urban": "#eb6834",       # 人口集中地区
    "seto": "#2a78d6",        # 瀬戸内海
    "near_sea": "#8fc1e8",    # 海岸から 3 km 以内の海
    "mountain": "#b08968",    # その他の陸地（山地など）
    "sea": "#dfe9f3",         # 海（遠く）
    "snow": "#8b8a84",        # 積雪（灰色）
}
CLASS_LABELS = {
    "plain": "平野（DID の外）",
    "urban": "人口集中地区",
    "seto": "瀬戸内海",
    "near_sea": "海岸から 3 km 以内の海",
    "mountain": "その他の陸地（山地など）",
    "sea": "海",
}
#: 順序を固定したカラーマップ（imshow の値 0..5 に対応）
_CLASS_ORDER = ("sea", "near_sea", "seto", "mountain", "urban", "plain")
CLASS_CMAP = ListedColormap([CLASS_COLORS[k] for k in _CLASS_ORDER])


def _skip(name: str, reason: str) -> None:
    print(f"[skip] {name}: {reason}")


def save(fig: Figure, name: str) -> Path:
    FIGS.mkdir(parents=True, exist_ok=True)
    png = FIGS / f"{name}.png"
    pdf = FIGS / f"{name}.pdf"
    fig.savefig(png, dpi=200)
    fig.savefig(pdf)
    print(f"[ok]   {name} -> {png}")
    return png


def _map_axes(ax, box: BBox, coast_lw: float = 0.6) -> None:
    draw_coastline(ax, box, linewidth=coast_lw)
    ax.set_xlim(box.west, box.east)
    ax.set_ylim(box.south, box.north)
    ax.set_aspect(1.0 / np.cos(np.radians(0.5 * (box.south + box.north))))
    ax.tick_params(labelsize=7.5)


def _pivot(df: pd.DataFrame, col: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """規則的な 0.05 度格子の列を 2D に戻す（pcolormesh 用）。"""
    lat_vals = np.sort(df["lat"].unique())
    lon_vals = np.sort(df["lon"].unique())
    li = {v: i for i, v in enumerate(lat_vals)}
    lj = {v: j for j, v in enumerate(lon_vals)}
    grid = np.full((lat_vals.size, lon_vals.size), np.nan)
    ii = df["lat"].map(li).to_numpy()
    jj = df["lon"].map(lj).to_numpy()
    grid[ii, jj] = df[col].to_numpy()
    return lat_vals, lon_vals, grid


def _boxes_overlap(a: tuple, boxes: list) -> bool:
    ax0, ay0, ax1, ay1 = a
    return any(ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0 for bx0, by0, bx1, by1 in boxes)


def _mark_sites(ax, sites: pd.DataFrame, fontsize: float = 7.0) -> None:
    """星印と地点名を打つ。地点どうしが近くて重なりそうなときは、他の星や
    先に置いたラベルにぶつからない向き・距離を探して置き、引き出し線を添える。
    軸の外（図の余白や隣の図）にはみ出す候補は選ばない。
    """
    names = sites["name"].astype(str).to_numpy()
    lons = sites["lon"].to_numpy(dtype=float)
    lats = sites["lat"].to_numpy(dtype=float)
    fig = ax.figure
    px_per_pt = fig.dpi / 72.0
    anchors = ax.transData.transform(np.column_stack([lons, lats])).astype(float)
    # 数 km しか離れていない地点は星が重なって潰れるので、表示上だけ少し離す
    min_sep_px = 9.0
    for i in range(len(anchors)):
        for j in range(i + 1, len(anchors)):
            d = anchors[j] - anchors[i]
            dist = float(np.hypot(*d))
            if 0 < dist < min_sep_px:
                ang = np.arctan2(d[1], d[0])
                push = (min_sep_px - dist) / 2 + 1.0
                step = push * np.array([np.cos(ang), np.sin(ang)])
                anchors[i] -= step
                anchors[j] += step
            elif dist == 0:
                anchors[j] += (min_sep_px / 2 + 1.0) * np.array([1.0, 0.0])
    star_xy = ax.transData.inverted().transform(anchors)
    ax.plot(star_xy[:, 0], star_xy[:, 1], marker="*", markersize=10, linestyle="none",
             markerfacecolor=CATEGORICAL[1], markeredgecolor="white",
             markeredgewidth=0.8, zorder=6)
    # このラベルはこの軸の中に収める（隣の図や紙面の外にはみ出させない）
    pos = ax.get_position()
    (axb_x0, axb_y0), (axb_x1, axb_y1) = fig.transFigure.transform(
        [[pos.x0, pos.y0], [pos.x1, pos.y1]])
    margin = 2.0
    ax_bounds = (axb_x0 + margin, axb_y0 + margin, axb_x1 - margin, axb_y1 - margin)
    star_r = 7.0
    marker_boxes = [(x - star_r, y - star_r, x + star_r, y + star_r) for x, y in anchors]
    placed: list[tuple] = []
    angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    # 長い名前が先に良い位置を選べるよう、文字数の多い順に置く
    order = np.argsort(-np.array([len(n) for n in names]))
    for k in order:
        ax_px, ay_px = anchors[k]
        w_px = (len(names[k]) * fontsize * 1.15 + 5) * px_per_pt
        h_px = fontsize * 1.7 * px_per_pt
        best = None
        for allow_outside in (False, True):
            for radius_pt in (11, 18, 27, 38, 52):
                r_px = radius_pt * px_per_pt
                for ang in angles:
                    dx_px, dy_px = r_px * np.cos(ang), r_px * np.sin(ang)
                    ha = "left" if dx_px >= -1 else "right"
                    va = "bottom" if dy_px >= -1 else "top"
                    cx, cy = ax_px + dx_px, ay_px + dy_px
                    x0 = cx if ha == "left" else cx - w_px
                    y0 = cy if va == "bottom" else cy - h_px
                    box = (x0, y0, x0 + w_px, y0 + h_px)
                    inside = (allow_outside or (box[0] >= ax_bounds[0] and box[1] >= ax_bounds[1]
                              and box[2] <= ax_bounds[2] and box[3] <= ax_bounds[3]))
                    if inside and not _boxes_overlap(box, placed) \
                            and not _boxes_overlap(box, marker_boxes):
                        best = (dx_px / px_per_pt, dy_px / px_per_pt, ha, va, box)
                        break
                if best is not None:
                    break
            if best is not None:
                break
        if best is None:
            best = (14.0, 14.0, "left", "bottom",
                    (ax_px, ay_px, ax_px + w_px, ay_px + h_px))
        dx, dy, ha, va, box = best
        placed.append(box)
        ax.annotate(names[k], (star_xy[k, 0], star_xy[k, 1]), xytext=(dx, dy),
                    textcoords="offset points",
                    fontsize=fontsize, color=INK["primary"], ha=ha, va=va, zorder=7,
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85},
                    arrowprops={"arrowstyle": "-", "color": INK["secondary"], "lw": 0.6,
                                "shrinkA": 0, "shrinkB": 3})


def _load_sites() -> pd.DataFrame | None:
    path = RESULTS / "sites.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def _load_stats(scenario: str = "std") -> list[dict] | None:
    path = RESULTS / "stats.json"
    if not path.exists():
        return None
    allres = json.loads(path.read_text(encoding="utf-8"))
    return allres.get(scenario)


def _best_plus_iki(stats: list[dict], n_best: int = 3) -> list[dict]:
    """p_total 上位 n_best と壱岐（IKI_NAME の地点）をあわせて返す。"""
    ordered = sorted(stats, key=lambda r: r["p_total"], reverse=True)
    iki = next((r for r in stats if r["name"] == IKI_NAME), None)
    best = [r for r in ordered if iki is None or r["name"] != IKI_NAME][:n_best]
    if iki is not None and iki not in best:
        return best + [iki]
    return ordered[: n_best + 1]


def _ranked_sites(scenario: str = "std") -> pd.DataFrame | None:
    """sites.csv（緯度経度）と stats.json（p_total）を合わせ、p_total 降順にする。"""
    sites = _load_sites()
    stats = _load_stats(scenario)
    if sites is None or stats is None:
        return None
    p_total = {r["name"]: r["p_total"] for r in stats}
    df = sites.copy()
    df["p_total"] = df["name"].map(p_total)
    return df.sort_values("p_total", ascending=False).reset_index(drop=True)




def _mark_top_sites(ax, ranked: pd.DataFrame, n_top: int = 5, fontsize: float = 8.0) -> None:
    """壱岐と上位 n_top に番号を付ける（名前は図の下の一覧に書く）。
    地点が数 km〜数十 km しか離れていないので、名前を地図に直接書くと重なって読めない。
    壱岐は「壱」、上位は順位の数字。"""
    labeled = _numbered(ranked, n_top)
    other = ranked[~ranked["name"].isin(labeled["name"])]
    if len(other):
        ax.plot(other["lon"], other["lat"], ".", markersize=4.0, color=INK["secondary"],
                alpha=0.8, zorder=5)
    stars = [(r.lon, r.lat) for r in labeled.itertuples()]
    placed: list[tuple[float, float]] = []
    for r in labeled.itertuples():
        ax.plot(r.lon, r.lat, marker="*", markersize=9, color="#D55E00",
                markeredgecolor="white", markeredgewidth=0.6, zorder=6)
        # 番号は、ほかの星とすでに置いた番号から 0.3 度以上離れた方向に置く（西＝海側を優先）
        best = None
        for rad in (0.4, 0.6, 0.8):
            for ang in (180, 150, 210, 120, 240, 90, 270, 60, 300, 30, 330, 0):
                x = r.lon + rad * np.cos(np.radians(ang))
                y = r.lat + rad * np.sin(np.radians(ang))
                others = [q for q in stars if q != (r.lon, r.lat)] + placed
                if all(np.hypot(x - a, y - b) > 0.3 for a, b in others):
                    best = (x, y)
                    break
            if best:
                break
        best = best or (r.lon - 0.4, r.lat)
        placed.append(best)
        ax.annotate(r.tag, (r.lon, r.lat), xytext=best, fontsize=fontsize, ha="center",
                    va="center", fontweight="bold", color=INK["primary"], zorder=7,
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85},
                    arrowprops={"arrowstyle": "-", "lw": 0.6, "color": INK["secondary"]})


def _numbered(ranked: pd.DataFrame, n_top: int = 5) -> pd.DataFrame:
    top = ranked[ranked["name"] != IKI_NAME].head(n_top).copy()
    top["tag"] = [str(i + 1) for i in range(len(top))]
    iki = ranked[ranked["name"] == IKI_NAME].copy()
    iki["tag"] = "壱"
    return pd.concat([top, iki])


def _site_key_text(ranked: pd.DataFrame, n_top: int = 5) -> str:
    lab = _numbered(ranked, n_top)
    return "　".join(f"{r.tag}: {r.name}" for r in lab.itertuples())


# --- 地形の色分け（target_mask, landing_clouds で共有） -------------------------------

def _terrain_class_array(terrain: C.Terrain, step: int = 1) -> np.ndarray:
    land = terrain.land[::step, ::step]
    plain = terrain.plain[::step, ::step]
    urban = terrain.urban[::step, ::step]
    seto = terrain.seto[::step, ::step]
    near_sea = (~land) & (terrain.sea_dist_km[::step, ::step] <= C.COAST_KM)
    cls = np.zeros(land.shape, dtype=np.uint8)                    # sea
    cls[near_sea] = _CLASS_ORDER.index("near_sea")
    cls[seto] = _CLASS_ORDER.index("seto")
    cls[land] = _CLASS_ORDER.index("mountain")
    cls[land & plain] = _CLASS_ORDER.index("plain")
    cls[land & urban] = _CLASS_ORDER.index("urban")
    return cls


def _terrain_legend_handles() -> list[Patch]:
    return [Patch(color=CLASS_COLORS[k], label=CLASS_LABELS[k]) for k in
            ("plain", "urban", "seto", "near_sea", "mountain", "sea")]


# --- target_mask ---------------------------------------------------------------

def fig_target_mask() -> None:
    name = "target_mask"
    terrain = C.Terrain()
    step = 3                                    # 間引いて描画を速くする
    cls = _terrain_class_array(terrain, step)
    extent = terrain.extent
    fig = Figure(figsize=(13.5, 6.2))
    left, right = fig.subplots(1, 2)
    for ax, box, title in ((left, JAPAN_BOX, "日本全国"), (right, WEST_BOX, "西日本の拡大")):
        ax.imshow(cls, extent=extent, origin="upper", cmap=CLASS_CMAP, vmin=-0.5,
                  vmax=len(_CLASS_ORDER) - 0.5, interpolation="nearest")
        _map_axes(ax, box, coast_lw=0.5)
        ax.set_title(title, fontsize=11)
    fig.legend(handles=_terrain_legend_handles(), loc="lower center", ncol=3,
               fontsize=8.5, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("落下点の分類", fontsize=12)
    fig.tight_layout(rect=(0, 0.09, 1, 0.96))
    save(fig, name)


# --- snow_weather ----------------------------------------------------------------

def fig_snow_weather() -> None:
    name = "snow_weather"
    if not list(DATA.glob("era5_sfc_*.nc")):
        _skip(name, "data/era5_sfc_*.nc がまだ無い")
        return
    sfc = C.Surface()
    sel = sfc.dates.month.isin((12, 1, 2))
    if not sel.any():
        _skip(name, "ERA5 に 12–2 月のデータが無い")
        return
    snow_free = 100.0 * (sfc.sd[sel] < C.SNOW_SD_M).mean(axis=0)
    wx_ok = 100.0 * ((sfc.ws[sel] <= C.SFC_WIND_MAX) & (sfc.tp[sel] < C.PRECIP_MAX_MM)).mean(axis=0)
    cmap = CMAP_SPEED.reversed()
    fig = Figure(figsize=(13, 6.2))
    left, right = fig.subplots(1, 2)
    m1 = left.pcolormesh(sfc.lon, sfc.lat, snow_free, cmap=cmap, vmin=0, vmax=100,
                          shading="nearest")
    _map_axes(left, JAPAN_BOX, coast_lw=0.5)
    left.set_title("雪のない日の割合（12–2 月）", fontsize=11)
    fig.colorbar(m1, ax=left, shrink=0.75, label="[%]")
    m2 = right.pcolormesh(sfc.lon, sfc.lat, wx_ok, cmap=cmap, vmin=0, vmax=100,
                           shading="nearest")
    _map_axes(right, JAPAN_BOX, coast_lw=0.5)
    right.set_title("9 時の地上気象が打ち上げに向く日の割合", fontsize=11)
    fig.colorbar(m2, ax=right, shrink=0.75, label="[%]")
    fig.suptitle("積雪と地上気象（ERA5、2016–2025 年 12–2 月）", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, name)


# --- drift_arrows ------------------------------------------------------------------

def fig_drift_arrows() -> None:
    name = "drift_arrows"
    path = RESULTS / "screen_std.csv"
    if not path.exists():
        _skip(name, f"{path} が無い")
        return
    df = pd.read_csv(path)
    lat_vals, lon_vals, dist = _pivot(df, "dist_mean_km")
    _, _, east = _pivot(df, "east_mean_km")
    _, _, north = _pivot(df, "north_mean_km")
    fig = Figure(figsize=(9.5, 8.0))
    ax = fig.subplots()
    mesh = ax.pcolormesh(lon_vals, lat_vals, dist, cmap=CMAP_SPEED, shading="nearest")
    # 矢印は実寸。密になりすぎないよう ~0.5 度おきに間引く
    step = max(int(round(0.5 / C.LAUNCH_STEP)), 1)
    la = lat_vals[::step]
    lo = lon_vals[::step]
    lat_mid = float(np.mean(la))
    LA, LO = np.meshgrid(la, lo, indexing="ij")
    E = east[::step, ::step]
    N = north[::step, ::step]
    good = np.isfinite(E) & np.isfinite(N)
    ax.quiver(LO[good], LA[good], E[good], N[good], color=INK["primary"],
               angles="xy", scale_units="xy",
               scale=C.KM_PER_DEG * np.cos(np.radians(lat_mid)), width=0.0028, zorder=5)
    _map_axes(ax, JAPAN_BOX, coast_lw=0.5)
    fig.colorbar(mesh, ax=ax, shrink=0.8, label="平均の飛行距離 [km]")
    ax.set_title("標準の飛行条件での平均落下位置（矢先が平均落下点、矢印は実寸）", fontsize=11)
    fig.tight_layout()
    save(fig, name)


# --- p_maps_std / p_maps_short -----------------------------------------------------

_P_PANELS = (("p_wind", "落下予測が目標に入る（雪を問わない）", 60), ("p_land", "目標に入り、落下点に雪なし", 60),
             ("p_total", "実施できる（すべて満たす）", 60), ("p_sfc", "9 時の地上気象が向く（ERA5）", 100))


def _add_japan_inset(ax, df: pd.DataFrame, col: str, vmax: float) -> None:
    """左上に全国の分布を小さく添える（この地図が西日本の拡大だと分かるように）。"""
    lat_all, lon_all, grid_all = _pivot(df, col)
    inset = ax.inset_axes((0.02, 0.54, 0.34, 0.30))
    inset.pcolormesh(lon_all, lat_all, 100 * grid_all, cmap=CMAP_SPEED, vmin=0, vmax=vmax,
                      shading="nearest")
    _map_axes(inset, JAPAN_BOX, coast_lw=0.3)
    inset.set_xticks([])
    inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor(INK["secondary"])
        spine.set_linewidth(0.7)
    box = {"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85}
    inset.text(0.04, 0.96, "全国", transform=inset.transAxes, fontsize=6.5, ha="left",
               va="top", bbox=box)


def _p_map_panel(ax, df: pd.DataFrame, col: str, title: str, ranked, vmax: float,
                  inset: bool = False):
    lat_vals, lon_vals, grid = _pivot(df, col)
    mesh = ax.pcolormesh(lon_vals, lat_vals, 100 * grid, cmap=CMAP_SPEED, vmin=0,
                          vmax=vmax, shading="nearest")
    _map_axes(ax, WEST_BOX, coast_lw=0.5)
    if ranked is not None:
        _mark_top_sites(ax, ranked)
    ax.set_title(title, fontsize=10.5)
    if inset:
        _add_japan_inset(ax, df, col, vmax)
    return mesh


def fig_p_maps_std() -> None:
    name = "p_maps_std"
    path = RESULTS / "screen_std.csv"
    if not path.exists():
        _skip(name, f"{path} が無い")
        return
    df = pd.read_csv(path)
    ranked = _ranked_sites("std")
    fig = Figure(figsize=(11.5, 11.0))
    gs = fig.add_gridspec(2, 3, width_ratios=(1, 1, 0.05), wspace=0.12, hspace=0.18)
    axes = [fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]),
            fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])]
    cax60, cax100 = fig.add_subplot(gs[0, 2]), fig.add_subplot(gs[1, 2])
    order = (0, 1, 2, 3)          # 上段: 落下 2 枚、下段: 実施できる（左）・地上気象（右）
    mesh60 = mesh100 = None
    for k, (col, title, vmax) in enumerate(_P_PANELS):
        mesh = _p_map_panel(axes[order[k]], df, col, title, ranked, vmax, inset=False)
        if vmax == 100:
            mesh100 = mesh
        else:
            mesh60 = mesh
    fig.colorbar(mesh60, cax=cax60, label="割合 [%]（上段と左下、0–60 %）")
    fig.colorbar(mesh100, cax=cax100, label="割合 [%]（右下、0–100 %）")
    fig.suptitle("標準の飛行条件での確率（2016–2025 年 12–2 月、西日本）", fontsize=13)
    if ranked is not None:
        fig.text(0.5, 0.045, _site_key_text(ranked), ha="center", fontsize=9)
    save(fig, name)


def fig_p_maps_short() -> None:
    name = "p_maps_short"
    p_std, p_short = RESULTS / "screen_std.csv", RESULTS / "screen_short.csv"
    if not p_std.exists() or not p_short.exists():
        _skip(name, f"{p_std} または {p_short} が無い")
        return
    d_std, d_short = pd.read_csv(p_std), pd.read_csv(p_short)
    ranked = _ranked_sites("std")
    fig = Figure(figsize=(12.5, 6.2))
    left, right = fig.subplots(1, 2)
    panels = ((left, d_std, C.SCENARIOS["std"][0], True),
              (right, d_short, C.SCENARIOS["short"][0], False))
    mesh = None
    for ax, df, label, _ in panels:
        mesh = _p_map_panel(ax, df, "p_total", label, ranked, 60, inset=False)
    fig.colorbar(mesh, ax=[left, right], shrink=0.75, label="実施できる割合 [%]（0–60 %）")
    fig.suptitle("実施できる確率: 標準の飛行と短時間の飛行", fontsize=12)
    if ranked is not None:
        fig.text(0.45, 0.04, "番号は標準の飛行での順位　" + _site_key_text(ranked), ha="center", fontsize=9)
    save(fig, name)


# --- p_total_months --------------------------------------------------------------

def fig_p_total_months() -> None:
    name = "p_total_months"
    path = RESULTS / "screen_std.csv"
    if not path.exists():
        _skip(name, f"{path} が無い")
        return
    df = pd.read_csv(path)
    ranked = _ranked_sites("std")
    months = (("p_total_m12", "12 月"), ("p_total_m1", "1 月"), ("p_total_m2", "2 月"))
    missing = [c for c, _ in months if c not in df.columns]
    if missing:
        _skip(name, f"列が無い: {missing}")
        return
    fig = Figure(figsize=(14, 5.6))
    axes = fig.subplots(1, 3)
    mesh = None
    for k, (ax, (col, title)) in enumerate(zip(axes, months, strict=True)):
        mesh = _p_map_panel(ax, df, col, f"実施できる割合（{title}）", ranked, 60, inset=False)
    fig.colorbar(mesh, ax=list(axes), shrink=0.7, label="[%]（0–60 %）")
    if ranked is not None:
        fig.text(0.45, 0.06, _site_key_text(ranked), ha="center", fontsize=9)
    fig.suptitle("月別の「実施できる割合」（西日本の拡大、標準の飛行条件）", fontsize=12)
    save(fig, name)


# --- ranking -----------------------------------------------------------------------

def fig_ranking() -> None:
    name = "ranking"
    std = _load_stats("std")
    if std is None:
        _skip(name, "results/stats.json が無い")
        return
    short = _load_stats("short") or []
    short_by_name = {r["name"]: r for r in short}
    ordered = sorted(std, key=lambda r: r["p_total"], reverse=True)
    names = [r["name"] for r in ordered]
    y = np.arange(len(ordered))[::-1]
    p = np.array([100 * r["p_total"] for r in ordered])
    lo = np.array([100 * r["ci_total"][0] for r in ordered])
    hi = np.array([100 * r["ci_total"][1] for r in ordered])
    fig = Figure(figsize=(8.5, max(3.2, 0.42 * len(ordered) + 1.2)))
    ax = fig.subplots()
    colors = [CATEGORICAL[1] if n == IKI_NAME else CATEGORICAL[0] for n in names]
    ax.barh(y, p, xerr=[p - lo, hi - p], color=colors, height=0.55,
            error_kw={"ecolor": INK["secondary"], "elinewidth": 1.1, "capsize": 3}, zorder=3)
    for k, r in enumerate(ordered):
        sr = short_by_name.get(r["name"])
        if sr is not None:
            ax.plot(100 * sr["p_total"], y[k], marker="D", markersize=6,
                     markerfacecolor="white", markeredgecolor=INK["primary"],
                     markeredgewidth=1.3, zorder=4)
    ax.set_yticks(y, names, fontsize=9)
    for k, n in enumerate(names):
        if n == IKI_NAME:
            ax.get_yticklabels()[k].set_fontweight("bold")
    ax.set_xlabel("実施できる割合 [%]（95% 信頼区間）")
    short_max = max((100 * sr["p_total"] for sr in short_by_name.values()), default=0.0)
    ax.set_xlim(0, max(hi.max(), short_max) * 1.15 + 1)
    # 図の中に置くと、値の大きい地点のひし形（短時間）と重なるので、外に出す
    handles = [Patch(color=CATEGORICAL[0], label="標準（誤差棒は 95% 信頼区間）"),
               Patch(color=CATEGORICAL[1], label=IKI_NAME),
               Line2D([0], [0], marker="D", linestyle="none", markersize=7,
                      markerfacecolor="white", markeredgecolor=INK["primary"], label="短時間")]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=8.5, frameon=False,
               bbox_to_anchor=(0.5, -0.005))
    ax.set_title("地点別の「実施できる割合」", fontsize=11)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    save(fig, name)


# --- landing_clouds ----------------------------------------------------------------

def fig_landing_clouds() -> None:
    name = "landing_clouds"
    ens_path = DATA / "ensemble_std.npz"
    if not ens_path.exists():
        _skip(name, f"{ens_path} が無い")
        return
    if not list(DATA.glob("era5_sfc_*.nc")):
        _skip(name, "data/era5_sfc_*.nc がまだ無い（成否の判定に地上気象が要る）")
        return
    stats = _load_stats("std")
    if stats is None:
        _skip(name, "results/stats.json が無い")
        return
    from evaluate import judge  # noqa: PLC0415

    d = np.load(ens_path, allow_pickle=True)
    names = list(d["names"])
    picks = _best_plus_iki(stats, n_best=3)
    sites_df = pd.read_csv(RESULTS / "sites.csv").set_index("name")
    terrain = C.Terrain()
    sfc = C.Surface()
    times = pd.DatetimeIndex(d["times"])
    step = 4                                     # 地形図の間引き（表示のみ）
    cls = _terrain_class_array(terrain, step)
    extent = terrain.extent
    n_panels = len(picks)
    ncol = 2
    nrow = (n_panels + ncol - 1) // ncol
    fig = Figure(figsize=(11.5, 5.1 * nrow))
    axes = np.atleast_1d(fig.subplots(nrow, ncol, gridspec_kw={"hspace": 0.28})).ravel()
    for ax, r in zip(axes, picks, strict=False):
        if r["name"] not in names or r["name"] not in sites_df.index:
            ax.set_visible(False)
            continue
        s = names.index(r["name"])
        site_lat = float(sites_df.loc[r["name"], "lat"])
        site_lon = float(sites_df.loc[r["name"], "lon"])
        lat_pts = d["lat"][:, s, :]
        lon_pts = d["lon"][:, s, :]
        cand = pd.DataFrame({"lat": np.full(lat_pts.shape[1], site_lat),
                              "lon": np.full(lat_pts.shape[1], site_lon)})
        ok = np.zeros_like(lat_pts, dtype=bool)
        for k in range(lat_pts.shape[0]):
            j = judge(terrain, sfc, cand, lat_pts[k][None, :], lon_pts[k][None, :], times[[k]])
            ok[k] = j["total"][0]
        ax.imshow(cls, extent=extent, origin="upper", cmap=CLASS_CMAP, vmin=-0.5,
                  vmax=len(_CLASS_ORDER) - 0.5, interpolation="nearest", zorder=0)
        ax.plot(lon_pts[~ok], lat_pts[~ok], ".", markersize=1.4, color=INK["muted"],
                 alpha=0.35, zorder=2)
        # CATEGORICAL[0] は「瀬戸内海」の背景と同じ青なので、そこに重なると見えなくなる。
        # 成功はどの背景色の上でも読めるよう、ほぼ黒にする
        ax.plot(lon_pts[ok], lat_pts[ok], ".", markersize=1.8, color=INK["primary"],
                 alpha=0.7, zorder=3)
        ax.plot(site_lon, site_lat, "*", markersize=14, color=CATEGORICAL[1],
                 markeredgecolor="white", markeredgewidth=1.0, zorder=5)
        # 打ち上げ地点は必ず地図の中に入るよう、範囲の計算にそれも含める
        pad = 1.0
        lat_lo = min(np.nanpercentile(lat_pts, 1), site_lat) - pad
        lat_hi = max(np.nanpercentile(lat_pts, 99), site_lat) + pad
        lon_lo = min(np.nanpercentile(lon_pts, 1), site_lon) - pad
        lon_hi = max(np.nanpercentile(lon_pts, 99), site_lon) + pad
        box = BBox(south=max(lat_lo, JAPAN_BOX.south), north=min(lat_hi, JAPAN_BOX.north),
                   west=max(lon_lo, JAPAN_BOX.west), east=min(lon_hi, JAPAN_BOX.east))
        _map_axes(ax, box, coast_lw=0.5)
        ax.set_title(f"{r['name']}（実施できる割合 {100 * ok.mean():.0f} %）", fontsize=10.5)
    for ax in axes[n_panels:]:
        ax.set_visible(False)
    handles = [*_terrain_legend_handles(),
               Patch(color=INK["primary"], label="成功（実施できた回）"),
               Patch(color=INK["muted"], label="失敗")]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("アンサンブルの落下点（標準の飛行条件）", fontsize=12)
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    save(fig, name)


# --- breakdown / iki_detail: stats.json の "why"（互いに排他、合計 1）-------------------

#: (キー, 色, 短い日本語名)。成功 3 種を寒色、失敗 6 種を暖色・灰色にする
WHY_SPEC = (
    ("success_plain_ok", CLASS_COLORS["plain"], "成功: 平野"),
    ("success_seto", CLASS_COLORS["seto"], "成功: 瀬戸内海"),
    ("success_near_sea", CLASS_COLORS["near_sea"], "成功: 海岸近くの海"),
    ("launch_snow", CLASS_COLORS["snow"], "打ち上げ地点に雪"),
    ("surface_weather", CATEGORICAL[3], "地上の風・雨"),
    ("landing_mountain", CLASS_COLORS["mountain"], "山地に落下"),
    ("landing_far_sea", "#a65d57", "沖の海に落下"),
    ("landing_urban", CLASS_COLORS["urban"], "市街地に落下"),
    ("landing_snow", "#c9c8c3", "落下点に雪"),
)
#: 濃い色の区間は白文字、淡い色の区間は黒文字にする
_WHY_LIGHT_BG = {"success_near_sea", "landing_snow"}


def _why_bar(ax, y: float, why: dict, height: float = 0.6, label_min: float = 3.0,
             alpha: float = 1.0, hatch: str | None = None, label: bool = True) -> None:
    left = 0.0
    for key, color, _ in WHY_SPEC:
        val = 100 * float(why.get(key, 0.0))
        ax.barh(y, val, left=left, color=color, height=height, zorder=3, alpha=alpha,
                hatch=hatch, edgecolor=(INK["secondary"] if hatch else "none"), linewidth=0.4)
        if label and val >= label_min:
            text_color = INK["primary"] if key in _WHY_LIGHT_BG else "white"
            ax.text(left + val / 2, y, f"{val:.0f}", ha="center", va="center",
                    fontsize=7, color=text_color, zorder=4, alpha=alpha)
        left += val


def fig_breakdown() -> None:
    name = "breakdown"
    std = _load_stats("std")
    short = _load_stats("short")
    if std is None or short is None:
        _skip(name, "results/stats.json が無い")
        return
    order = [r["name"] for r in sorted(std, key=lambda r: r["p_total"], reverse=True)]
    short_by_name = {r["name"]: r for r in short}
    std_by_name = {r["name"]: r for r in std}
    y = np.arange(len(order))[::-1]

    fig = Figure(figsize=(13.5, max(3.6, 0.42 * len(order) + 1.6)))
    left, right = fig.subplots(1, 2, sharey=True)
    for ax, by_name, label in ((left, std_by_name, C.SCENARIOS["std"][0]),
                                (right, short_by_name, C.SCENARIOS["short"][0])):
        for k, name_ in zip(y, order, strict=True):
            _why_bar(ax, k, by_name[name_]["why"])
        ax.set_xlim(0, 100)
        ax.set_xlabel("内訳 [%]")
        ax.set_title(label, fontsize=10.5)
    left.set_yticks(y, order, fontsize=9)
    for k, n in enumerate(order):
        if n == IKI_NAME:
            left.get_yticklabels()[k].set_fontweight("bold")
    handles = [Patch(color=c, label=lab) for _, c, lab in WHY_SPEC]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("成功・失敗の内訳（地点は標準の実施できる割合の順、数字は %）", fontsize=12)
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    save(fig, name)


# --- calendar ------------------------------------------------------------------------

_SEASON_DAY_LABELS = ("12/1", "1/1", "2/1")
_SEASON_DAY_TICKS = (0, 31, 62)


def _season_of(date: pd.Timestamp) -> int:
    return date.year if date.month == 12 else date.year - 1


def _calendar_grid(dates: pd.DatetimeIndex, values: np.ndarray) -> tuple[list[int], np.ndarray]:
    seasons = sorted({_season_of(d) for d in dates})
    grid = np.full((len(seasons), 90), np.nan)
    weekend = np.zeros((len(seasons), 90), dtype=bool)
    for k, d in enumerate(dates):
        s = _season_of(d)
        row = seasons.index(s)
        origin = pd.Timestamp(s, 12, 1)
        col = (d - origin).days
        if 0 <= col < 90:
            grid[row, col] = values[k]
            weekend[row, col] = d.weekday() >= 5
    return seasons, grid, weekend


def _draw_calendar(ax, seasons: list[int], grid: np.ndarray, weekend: np.ndarray, title: str):
    mesh = ax.pcolormesh(np.arange(91), np.arange(len(seasons) + 1), 100 * grid,
                          cmap=CMAP_SPEED, vmin=0, vmax=100, shading="flat")
    for row in range(weekend.shape[0]):
        for col in range(weekend.shape[1]):
            if weekend[row, col]:
                ax.add_patch(Rectangle((col, row), 1, 1, fill=False,
                                        edgecolor=INK["primary"], linewidth=0.6, zorder=3))
    ax.set_xticks(_SEASON_DAY_TICKS, _SEASON_DAY_LABELS)
    ylabels = [f"{s}/{s + 1 - 2000}" for s in seasons]
    ax.set_yticks(np.arange(len(seasons)) + 0.5, ylabels, fontsize=8)
    ax.set_title(title, fontsize=10.5)
    ax.set_xlim(0, 90)
    ax.set_ylim(0, len(seasons))
    return mesh


def fig_calendar() -> None:
    name = "calendar"
    path = RESULTS / "daily_total_std.csv"
    stats = _load_stats("std")
    if not path.exists() or stats is None:
        _skip(name, f"{path} か results/stats.json が無い")
        return
    df = pd.read_csv(path, parse_dates=["date"])
    ordered = sorted(stats, key=lambda r: r["p_total"], reverse=True)
    best = ordered[0]["name"]
    iki = next((r["name"] for r in stats if r["name"] == IKI_NAME), None)
    targets = [best] + ([iki] if iki and iki != best else [])
    missing = [t for t in targets if t not in df.columns]
    if missing:
        _skip(name, f"日ごとの確率が無い地点: {missing}")
        return
    fig = Figure(figsize=(9.5, 3.6 * len(targets)))
    axes = np.atleast_1d(fig.subplots(len(targets), 1))
    mesh = None
    for ax, t in zip(axes, targets, strict=True):
        seasons, grid, weekend = _calendar_grid(pd.DatetimeIndex(df["date"]), df[t].to_numpy())
        mesh = _draw_calendar(ax, seasons, grid, weekend, f"{t}（枠は土日）")
    fig.colorbar(mesh, ax=list(axes), shrink=0.7, label="実施できる割合 [%]")
    fig.suptitle("季節ごとの実施できる割合（標準の飛行条件）", fontsize=12)
    save(fig, name)


# --- weekend ---------------------------------------------------------------------

def fig_weekend() -> None:
    name = "weekend"
    stats = _load_stats("std")
    if stats is None:
        _skip(name, "results/stats.json が無い")
        return
    ordered = sorted(stats, key=lambda r: r["p_total"], reverse=True)
    picks = _best_plus_iki(stats, n_best=3)
    fig = Figure(figsize=(15, 4.6))
    a, b, c = fig.subplots(1, 3)

    names = [r["name"] for r in ordered]
    x = np.arange(len(names))
    w = 0.26
    weekday = [100 * r["p_total_weekday"] for r in ordered]
    weekend_ = [100 * r["p_total_weekend"] for r in ordered]
    offday = [100 * r["p_total_offday"] for r in ordered]
    a.bar(x - w, weekday, width=w, color=CATEGORICAL[0], label="平日")
    a.bar(x, weekend_, width=w, color=CATEGORICAL[1], label="土日")
    a.bar(x + w, offday, width=w, color=CATEGORICAL[2], label="土日祝")
    a.set_xticks(x, names, rotation=35, ha="right", fontsize=8)
    a.set_ylabel("実施できる割合 [%]")
    a.legend(fontsize=8)
    a.set_title("曜日による違い", fontsize=10.5)

    ns = [1, 2, 3, 4, 6, 8]
    for k, r in enumerate(picks):
        ys = [100 * r["p_success_within_weekends"][str(n)] for n in ns]
        b.plot(ns, ys, marker="o", color=CATEGORICAL[k % len(CATEGORICAL)], label=r["name"])
    b.set_xlabel("挑戦した週末の数")
    b.set_ylabel("成功している割合 [%]")
    b.set_xticks(ns)
    b.legend(fontsize=8)
    note = "12–2 月のどの週末から数え始めても。季節の終わりで打ち切り"
    b.set_title(f"週末ごとに挑戦したときの成功確率\n（{note}）", fontsize=9.5)

    months = ("12", "1", "2")
    mlab = ("12 月", "1 月", "2 月")
    xm = np.arange(len(months))
    for k, r in enumerate(picks):
        ys = [100 * r["p_month_has_ok_weekend"][m] for m in months]
        c.plot(xm, ys, marker="s", color=CATEGORICAL[k % len(CATEGORICAL)], label=r["name"])
    c.set_xticks(xm, mlab)
    c.set_ylabel("実施できる土日が月に 1 回以上ある割合 [%]")
    c.legend(fontsize=8)
    c.set_title("月ごとの見込み", fontsize=10.5)
    fig.suptitle("土日祝日の実施しやすさ", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, name)


# --- by_year -----------------------------------------------------------------------

def fig_by_year() -> None:
    name = "by_year"
    stats = _load_stats("std")
    if stats is None:
        _skip(name, "results/stats.json が無い")
        return
    picks = _best_plus_iki(stats, n_best=3)
    fig = Figure(figsize=(9, 5.2))
    ax = fig.subplots()
    for k, r in enumerate(picks):
        years = sorted(int(y) for y in r["by_year"])
        ys = [100 * r["by_year"][str(y)] for y in years]
        ax.plot(years, ys, marker="o", color=CATEGORICAL[k % len(CATEGORICAL)], label=r["name"])
    ax.set_xlabel("暦年（その年の 1・2・12 月）")
    ax.set_ylabel("実施できる割合 [%]")
    ax.legend(fontsize=8.5)
    ax.set_title("年による違い（標準の飛行条件）", fontsize=11)
    fig.tight_layout()
    save(fig, name)


# --- sensitivity -------------------------------------------------------------------

#: 感度分析の対象地点と、地点ごとの固定色
_SENS_SITES = (IKI_NAME, "平戸・大島", "唐津・加唐島", "下関・蓋井島", "糸島・志摩")
_SENS_COLORS = (CATEGORICAL[0], CATEGORICAL[1], CATEGORICAL[2], CATEGORICAL[3], "#a34e96")
#: (列名, x 軸ラベル, 既定値, 見出し)
_SENS_PARAMS = (
    ("coast_km", "海岸からの距離の上限 [km]", 3.0, "着水を認める海岸からの距離"),
    ("wind_max", "地上 10 m 風速の上限 [m/s]", 5.0, "地上風速の上限"),
    ("precip_max", "降水量の上限 [mm]", 0.5, "降水量の上限"),
)


def fig_sensitivity() -> None:
    name = "sensitivity"
    path = RESULTS / "sensitivity.csv"
    if not path.exists():
        _skip(name, f"{path} が無い")
        return
    df = pd.read_csv(path)
    fig = Figure(figsize=(15, 4.8))
    axes = fig.subplots(1, 3)
    for ax, (col, xlabel, default, title) in zip(axes, _SENS_PARAMS, strict=True):
        sub = df[df["param"] == col]
        for site, color in zip(_SENS_SITES, _SENS_COLORS, strict=True):
            s = sub[sub["site"] == site].sort_values("value")
            if s.empty:
                continue
            ax.plot(s["value"], 100 * s["p_total"], marker="o", color=color, label=site)
        ax.axvline(default, color=INK["muted"], linestyle="--", linewidth=1, zorder=1)
        ax.text(default, ax.get_ylim()[1] if ax.get_ylim()[1] else 1, "既定", fontsize=7,
                color=INK["secondary"], ha="center", va="bottom")
        ax.set_xticks(sorted(sub["value"].unique()))
        ax.set_xlabel(xlabel)
        ax.set_ylabel("実施できる割合 [%]")
        ax.set_title(title, fontsize=10.5)
    handles = [Line2D([0], [0], color=c, marker="o", label=s)
               for s, c in zip(_SENS_SITES, _SENS_COLORS, strict=True)]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=8.5, frameon=False,
               bbox_to_anchor=(0.5, -0.03))
    fig.suptitle("判定基準を変えたときの「実施できる割合」（標準の飛行条件）", fontsize=12)
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    save(fig, name)


# --- iki_detail ----------------------------------------------------------------------

def _load_stats_amedas(scenario: str) -> dict | None:
    path = RESULTS / "stats_amedas.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return next((r for r in d.get(scenario, []) if r["name"] == IKI_NAME), None)


def fig_iki_detail() -> None:
    name = "iki_detail"
    std = _load_stats("std")
    short = _load_stats("short")
    if std is None or short is None:
        _skip(name, "results/stats.json が無い")
        return
    r_std = next((r for r in std if r["name"] == IKI_NAME), None)
    r_short = next((r for r in short if r["name"] == IKI_NAME), None)
    if r_std is None or r_short is None:
        _skip(name, f"stats.json に {IKI_NAME} が無い")
        return
    # アメダス（芦辺）に基づく値があれば、それを主に使い、ERA5 は薄いハッチで添える
    am_std = _load_stats_amedas("std")
    am_short = _load_stats_amedas("short")
    have_amedas = am_std is not None and am_short is not None
    main_std, main_short = (am_std, am_short) if have_amedas else (r_std, r_short)
    era5_note = ("（地上気象はアメダス・芦辺。薄いハッチが ERA5）" if have_amedas
                 else "（地上気象は ERA5）")

    fig = Figure(figsize=(16, 6.4))
    a, b, c = fig.subplots(1, 3, width_ratios=(1.1, 1.0, 1.0))

    if have_amedas:
        _why_bar(a, 3, main_std["why"], height=0.6)
        _why_bar(a, 2.15, r_std["why"], height=0.45, alpha=0.4, hatch="////", label=False)
        _why_bar(a, 1, main_short["why"], height=0.6)
        _why_bar(a, 0.15, r_short["why"], height=0.45, alpha=0.4, hatch="////", label=False)
        a.set_yticks([3, 1], [C.SCENARIOS["std"][0], C.SCENARIOS["short"][0]], fontsize=8.5)
        a.set_ylim(-0.6, 3.8)
        handles_a = [Patch(facecolor=INK["muted"], label="アメダス（芦辺）"),
                     Patch(facecolor=INK["muted"], alpha=0.4, hatch="////",
                           edgecolor=INK["secondary"], label="ERA5（参考）")]
        a.legend(handles=handles_a, loc="upper center", bbox_to_anchor=(0.5, -0.12),
                 ncol=2, fontsize=7.5)
    else:
        _why_bar(a, 1, main_std["why"], height=0.55)
        _why_bar(a, 0, main_short["why"], height=0.55)
        a.set_yticks([1, 0], [C.SCENARIOS["std"][0], C.SCENARIOS["short"][0]], fontsize=8.5)
        a.set_ylim(-0.6, 1.6)
    a.set_xlim(0, 100)
    a.set_xlabel("内訳 [%]（数字は %）")
    a.set_title(f"打ち上げ・落下の内訳\n{era5_note}", fontsize=9.5)

    months = ("12", "1", "2")
    mlab = ("12 月", "1 月", "2 月")
    xm = np.arange(len(months))
    w = 0.32
    for off, r, color, label in ((-w / 2, main_std, CATEGORICAL[0], C.SCENARIOS["std"][0]),
                                  (w / 2, main_short, CATEGORICAL[1], C.SCENARIOS["short"][0])):
        p = np.array([100 * r["by_month"][m] for m in months])
        lo = np.array([100 * r["by_month_ci"][m][0] for m in months])
        hi = np.array([100 * r["by_month_ci"][m][1] for m in months])
        b.bar(xm + off, p, width=w, color=color, label=label,
              yerr=[p - lo, hi - p], error_kw={"ecolor": INK["secondary"], "elinewidth": 1,
                                                "capsize": 3})
    if have_amedas:
        for off, r in ((-w / 2, r_std), (w / 2, r_short)):
            era5_p = [100 * r["by_month"][m] for m in months]
            b.plot(xm + off, era5_p, marker="D", markersize=5, linestyle="none",
                   markerfacecolor="none", markeredgecolor=INK["secondary"],
                   markeredgewidth=1.2, zorder=5)
    b.set_xticks(xm, mlab)
    b.set_ylabel("実施できる割合 [%]")
    b.set_ylim(0, 65)
    b.set_title("月別（95% 信頼区間、◇ は ERA5）" if have_amedas else "月別（95% 信頼区間）",
               fontsize=9.5)

    cats = (("p_total_weekday", "平日"), ("p_total_weekend", "土日"),
            ("p_total_offday", "土日祝"), ("p_total_newyear", "年末年始"))
    xc = np.arange(len(cats))
    for off, r, color, label in ((-w / 2, main_std, CATEGORICAL[0], C.SCENARIOS["std"][0]),
                                  (w / 2, main_short, CATEGORICAL[1], C.SCENARIOS["short"][0])):
        vals = [100 * r[k] for k, _ in cats]
        c.bar(xc + off, vals, width=w, color=color, label=label)
    if have_amedas:
        for off, r in ((-w / 2, r_std), (w / 2, r_short)):
            era5_vals = [100 * r[k] for k, _ in cats]
            c.plot(xc + off, era5_vals, marker="D", markersize=5, linestyle="none",
                   markerfacecolor="none", markeredgecolor=INK["secondary"],
                   markeredgewidth=1.2, zorder=5)
    c.set_xticks(xc, [lab for _, lab in cats])
    c.set_ylabel("実施できる割合 [%]")
    c.set_ylim(0, 65)
    c.set_title("曜日・祝日による違い", fontsize=10.5)

    fig.suptitle(f"{IKI_NAME} の詳細", fontsize=12)
    fig.tight_layout(rect=(0, 0.2, 1, 0.93))
    # 内訳の色の意味（左の図の下）と、棒の色の意味（中央・右の図の下）
    why_handles = [Patch(color=col, label=lab) for _, col, lab in WHY_SPEC]
    fig.legend(handles=why_handles, loc="lower left", bbox_to_anchor=(0.02, 0.0), ncol=3,
               fontsize=8, frameon=False)
    bar_handles = [Patch(color=CATEGORICAL[0], label=C.SCENARIOS["std"][0]),
                   Patch(color=CATEGORICAL[1], label=C.SCENARIOS["short"][0])]
    if have_amedas:
        bar_handles.append(Line2D([], [], marker="D", linestyle="none", markerfacecolor="none",
                                  markeredgecolor=INK["secondary"],
                                  label="地上気象を ERA5 で判定した場合"))
    fig.legend(handles=bar_handles, loc="lower center", bbox_to_anchor=(0.7, 0.02), ncol=2,
               fontsize=8.5, frameon=False)
    save(fig, name)


# --- amedas_compare ------------------------------------------------------------------

#: (地点名, アメダスの観測所名)
_AMEDAS_SITES = ((IKI_NAME, "芦辺"), ("平戸・大島", "平戸"), ("唐津・加唐島", "唐津"))


def fig_amedas_compare() -> None:
    name = "amedas_compare"
    amedas_path = DATA / "amedas_09jst.csv"
    agree_path = RESULTS / "stats_amedas.json"
    if not amedas_path.exists() or not agree_path.exists():
        _skip(name, f"{amedas_path} か {agree_path} が無い")
        return
    if not list(DATA.glob("era5_sfc_*.nc")):
        _skip(name, "data/era5_sfc_*.nc がまだ無い")
        return
    amedas = pd.read_csv(amedas_path)
    agreement = json.loads(agree_path.read_text(encoding="utf-8"))["agreement"]
    missing = [s for s, _ in _AMEDAS_SITES if s not in agreement]
    if missing:
        _skip(name, f"agreement に無い地点: {missing}")
        return

    fig = Figure(figsize=(16.5, 5.2))
    a, b, c = fig.subplots(1, 3)

    # (a) 9 時の地上気象が向く日の割合: ERA5（最寄りの陸の格子） vs アメダス
    x = np.arange(len(_AMEDAS_SITES))
    w = 0.32
    era5_ok = [100 * agreement[s]["era5_ok"] for s, _ in _AMEDAS_SITES]
    amedas_ok = [100 * agreement[s]["amedas_ok"] for s, _ in _AMEDAS_SITES]
    a.bar(x - w / 2, era5_ok, width=w, color=CATEGORICAL[0], label="ERA5（最寄りの陸の格子）")
    a.bar(x + w / 2, amedas_ok, width=w, color=CATEGORICAL[1], label="アメダス")
    a.set_xticks(x, [f"{s}\n（{st}）" for s, st in _AMEDAS_SITES], fontsize=8)
    a.set_ylabel("9 時の地上気象が向く日の割合 [%]")
    a.set_ylim(0, 100)
    a.legend(fontsize=8, loc="upper left", ncol=2)
    a.set_title("地上気象の判定（ERA5 とアメダス）", fontsize=10.5)

    # (b) 壱岐の 9 時風速: ERA5（陸格子・海寄りの格子） vs アメダス（芦辺）
    sfc = C.Surface()
    ash = amedas[amedas["station"] == "芦辺"].dropna(subset=["ws09"]).copy()
    ash["date"] = pd.DatetimeIndex(ash["date"]).normalize()
    ash = ash[ash["date"].isin(sfc.dates)]
    k = sfc.day_index(pd.DatetimeIndex(ash["date"]))
    i_land, j_land = sfc._ij(np.array([33.78]), np.array([129.72]))
    era5_land = sfc.ws[k, i_land[0], j_land[0]]
    i_sea = int(round((sfc.lat[0] - 33.75) / 0.25))
    j_sea = int(round((129.75 - sfc.lon[0]) / 0.25))
    era5_sea = sfc.ws[k, i_sea, j_sea]
    amedas_ws = ash["ws09"].to_numpy()
    b.scatter(amedas_ws, era5_land, s=12, color=CATEGORICAL[0], alpha=0.5,
              label="ERA5（陸の格子）")
    b.scatter(amedas_ws, era5_sea, s=12, color=CATEGORICAL[2], alpha=0.5,
              label="ERA5（海寄りの格子）")
    lim = float(max(amedas_ws.max(), era5_land.max(), era5_sea.max())) * 1.08
    b.plot([0, lim], [0, lim], color=INK["muted"], linestyle="--", linewidth=1, zorder=1)
    b.axvline(C.SFC_WIND_MAX, color=INK["secondary"], linestyle=":", linewidth=1, zorder=1)
    b.axhline(C.SFC_WIND_MAX, color=INK["secondary"], linestyle=":", linewidth=1, zorder=1)
    b.set_xlim(0, lim)
    b.set_ylim(0, lim)
    b.set_aspect("equal")
    b.set_xlabel("アメダス（芦辺）の 9 時風速 [m/s]")
    b.set_ylabel("ERA5 の 9 時風速 [m/s]")
    b.legend(fontsize=7.5, loc="upper left")
    b.set_title(f"壱岐の風速（点線は {C.SFC_WIND_MAX:.0f} m/s の基準・1:1 線）", fontsize=9.5)

    # (c) 判定の一致（両方とも向く／ERA5 のみ／アメダスのみ／両方 NG）
    y = np.arange(len(_AMEDAS_SITES))[::-1]
    cats = (("both_ok", CATEGORICAL[0], "両方とも向く"),
            ("era5_only", CATEGORICAL[2], "ERA5 のみ向く"),
            ("amedas_only", CATEGORICAL[3], "アメダスのみ向く"),
            ("both_ng", INK["muted"], "両方とも NG"))
    left = np.zeros(len(_AMEDAS_SITES))
    for key, color, label in cats:
        vals = np.array([100 * agreement[s][key] for s, _ in _AMEDAS_SITES])
        c.barh(y, vals, left=left, color=color, height=0.6, label=label)
        left = left + vals
    c.set_yticks(y, [s for s, _ in _AMEDAS_SITES], fontsize=8.5)
    c.set_xlabel("日数の割合 [%]")
    c.set_xlim(0, 100)
    c.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=7.8)
    c.set_title("日ごとの判定の一致", fontsize=10.5)

    fig.suptitle("地上気象の判定: ERA5 とアメダスの比較", fontsize=12)
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))
    save(fig, name)


# --- CLI -------------------------------------------------------------------------

FIGURES = {
    "target_mask": fig_target_mask,
    "snow_weather": fig_snow_weather,
    "drift_arrows": fig_drift_arrows,
    "p_maps_std": fig_p_maps_std,
    "p_total_months": fig_p_total_months,
    "p_maps_short": fig_p_maps_short,
    "ranking": fig_ranking,
    "landing_clouds": fig_landing_clouds,
    "breakdown": fig_breakdown,
    "calendar": fig_calendar,
    "weekend": fig_weekend,
    "by_year": fig_by_year,
    "sensitivity": fig_sensitivity,
    "iki_detail": fig_iki_detail,
    "amedas_compare": fig_amedas_compare,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default=None, help="カンマ区切りの図の名前（省略時は全部）")
    a = ap.parse_args(argv)
    # CJK フォントに太字が無いのは織り込み済みなので、findfont の警告は消す
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    apply_style(japanese=True)
    names = list(FIGURES) if a.only is None else [n.strip() for n in a.only.split(",")]
    for n in names:
        fn = FIGURES.get(n)
        if fn is None:
            print(f"[skip] 不明な図の名前: {n}")
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 1 つの図の失敗で他を止めない
            print(f"[error] {n}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
