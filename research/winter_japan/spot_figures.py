"""打ち上げに使えそうな広場の一覧・図・表（osm_spots.py → spot_probability.py の結果から）。

同じ学校や公園の中の「敷地」と「グラウンド」のように、名前が同じで 300 m 以内の
候補は 1 つにまとめ、クリアランス（電線・建物・林までの距離）の大きいほうを残す。

出力:
  results/launch_spots.csv          まとめた一覧（Google マップのリンクつき）
  figures/launch_spots_iki.png/pdf  壱岐島の地図と一覧
  figures/launch_spots_west.png/pdf 北部九州・山口の地図（実施できる確率で色分け）
  report/tables/spots_iki.tex, spots_top.tex

    cd research && python winter_japan/spot_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

from windclim.figures.style import apply_style  # noqa: E402

KIND_JA = {"school": "学校", "university": "大学", "pitch": "グラウンド", "park": "公園",
           "grass": "草地", "sports_centre": "運動施設", "recreation_ground": "広場",
           "stadium": "競技場", "track": "陸上トラック"}
TAB = HERE / "report" / "tables"


def load() -> pd.DataFrame:
    d = pd.read_csv(C.RESULTS / "osm_spots_prob.csv")
    d["name"] = d["name"].fillna("（名前なし）").str.replace(r"（付近:\s*", "（付近: ", regex=True)
    d["kind_ja"] = d["kind"].map(KIND_JA).fillna(d["kind"])
    d = d.sort_values("clearance_m", ascending=False)
    keep, taken = [], []
    for r in d.itertuples():
        base = r.name.replace("（付近: ", "").rstrip("）")
        dup = any(base == b and np.hypot((r.best_lat - la) * 111, (r.best_lon - lo) * 93) < 0.3
                  for b, la, lo in taken)
        if dup:
            continue
        taken.append((base, r.best_lat, r.best_lon))
        keep.append(r.Index)
    out = d.loc[keep].copy()
    out["permission"] = np.where(out["kind"].isin(["school", "university"])
                                 | out["name"].str.contains("学校|高校|大学", regex=True),
                                 "要許可（学校）", "")
    out["gmaps"] = [f"https://www.google.com/maps?q={a:.5f},{b:.5f}"
                    for a, b in zip(out.best_lat, out.best_lon, strict=True)]
    return out


def land_background(ax, box):
    t = C.Terrain()
    i0 = int((t.box.north - box[3]) / t.dlat)
    i1 = int((t.box.north - box[2]) / t.dlat)
    j0 = int((box[0] - t.box.west) / t.dlon)
    j1 = int((box[1] - t.box.west) / t.dlon)
    land = t.land[i0:i1, j0:j1]
    seto = t.seto[i0:i1, j0:j1]
    cls = np.where(land, 1, np.where(seto, 2, 0))
    ax.imshow(cls, extent=(t.box.west + j0 * t.dlon, t.box.west + j1 * t.dlon,
                           t.box.north - i1 * t.dlat, t.box.north - i0 * t.dlat),
              cmap=ListedColormap(["#dfe9f3", "#efebe0", "#9cc3ea"]), vmin=0, vmax=2,
              interpolation="nearest", origin="upper")
    ax.set_xlim(box[0], box[1])
    ax.set_ylim(box[2], box[3])
    ax.set_aspect(1 / np.cos(np.radians(0.5 * (box[2] + box[3]))))


def fig_iki(d: pd.DataFrame) -> None:
    iki = d[d.area_group == "壱岐"].sort_values("clearance_m", ascending=False).reset_index(drop=True)
    fig = Figure(figsize=(13.5, 8.6))
    ax = fig.add_axes((0.04, 0.07, 0.5, 0.86))
    box = (129.61, 129.83, 33.70, 33.88)
    ax.set_facecolor("#dfe9f3")
    # 海岸線は OpenStreetMap（キャッシュ済み）。島の形が細かく出る
    from osm_spots import AREA_QUERIES, fetch_coastline  # noqa: PLC0415
    spec = dict(key=AREA_QUERIES[0][1], kind="bbox", **AREA_QUERIES[0][3])
    for e in fetch_coastline(spec).get("elements", []):
        g = e.get("geometry")
        if g:
            ax.plot([q["lon"] for q in g], [q["lat"] for q in g], color="#555", lw=0.9, zorder=3)
    ax.set_xlim(box[0], box[1])
    ax.set_ylim(box[2], box[3])
    ax.set_aspect(1 / np.cos(np.radians(33.79)))
    colors = {100: "#0072B2", 60: "#009E73", 40: "#E69F00"}
    for lo_c, col in ((40, colors[40]), (60, colors[60]), (100, colors[100])):
        s = iki[(iki.clearance_m >= lo_c) & (iki.clearance_m < {40: 60, 60: 100, 100: 1e9}[lo_c])]
        ax.scatter(s.best_lon, s.best_lat, s=46, color=col, edgecolor="#1b1f3a", lw=0.7, zorder=4)
    ap = (33.7493, 129.7853)
    ax.plot(ap[1], ap[0], marker="^", ms=11, color="#A01818", zorder=5)
    th = np.linspace(0, 2 * np.pi, 200)
    ax.plot(ap[1] + 3 / 93 * np.cos(th), ap[0] + 3 / 111 * np.sin(th), color="#A01818",
            ls="--", lw=1.2)
    ax.text(ap[1] + 0.004, ap[0] - 0.034, "壱岐空港\n（3 km 圏は除外）", color="#A01818",
            fontsize=9, ha="center")
    top = iki.head(20)
    placed = []
    for k, r in enumerate(top.itertuples(), start=1):
        best = None
        for rad in (0.007, 0.010, 0.013):
            for ang in (45, 135, -45, -135, 90, -90, 0, 180):
                x = r.best_lon + rad * np.cos(np.radians(ang)) / np.cos(np.radians(33.8))
                y = r.best_lat + rad * np.sin(np.radians(ang))
                if all(np.hypot((x - a) * 0.83, y - b) > 0.0075 for a, b in placed) and \
                        all(np.hypot((x - q.best_lon) * 0.83, y - q.best_lat) > 0.004
                            for q in top.itertuples()):
                    best = (x, y)
                    break
            if best:
                break
        best = best or (r.best_lon + 0.008, r.best_lat + 0.006)
        placed.append(best)
        ax.annotate(str(k), (r.best_lon, r.best_lat), xytext=best, fontsize=8.5,
                    ha="center", va="center", fontweight="bold",
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "#1b1f3a", "lw": 0.6},
                    arrowprops={"arrowstyle": "-", "lw": 0.6, "color": "#444"}, zorder=6)
    handles = [Line2D([], [], marker="o", ls="", color=colors[100], mec="#1b1f3a",
                      label="100 m 以上"),
               Line2D([], [], marker="o", ls="", color=colors[60], mec="#1b1f3a", label="60〜100 m"),
               Line2D([], [], marker="o", ls="", color=colors[40], mec="#1b1f3a", label="40〜60 m")]
    ax.legend(handles=handles, title="電線・建物・林までの距離", loc="upper left", fontsize=8.5,
              title_fontsize=8.5, framealpha=0.95)
    ax.set_title(f"壱岐島の打ち上げ候補地（{len(iki)} か所）", fontsize=12)
    ax.tick_params(labelsize=8)
    # 一覧
    tx = fig.add_axes((0.56, 0.07, 0.42, 0.86))
    tx.axis("off")
    tx.set_title("上位 20 か所（距離の大きい順）", fontsize=11)
    rows = [["番号", "名前", "種類", "距離", "面積", "確率"]]
    for k, r in enumerate(top.itertuples(), start=1):
        name = r.name if len(r.name) <= 16 else r.name[:15] + "…"
        rows.append([str(k), name, r.kind_ja, f"{r.clearance_m:.0f} m", f"{r.area_m2 / 1e4:.1f} ha",
                     f"{100 * r.p_std:.0f} %"])
    tb = tx.table(cellText=rows, loc="upper center", cellLoc="left",
                  colWidths=[0.07, 0.47, 0.13, 0.11, 0.11, 0.11])
    tb.auto_set_font_size(False)
    tb.set_fontsize(8.5)
    tb.scale(1, 1.32)
    for (i, _), cell in tb.get_celld().items():
        cell.set_edgecolor("#cccccc")
        if i == 0:
            cell.set_facecolor("#1b1f3a")
            cell.get_text().set_color("white")
    tx.text(0.0, -0.02, "距離は OpenStreetMap に載っている電線・建物・林までの最短距離。\n"
            "地方の電線は登録が少ないので、実際はもっと近い可能性がある。\n"
            "確率は標準の飛行・地上気象はアメダス芦辺。学校は使用の許可が要る。",
            fontsize=8.5, va="top", transform=tx.transAxes)
    for ext in ("png", "pdf"):
        fig.savefig(C.FIGS / f"launch_spots_iki.{ext}", dpi=200)


def fig_west(d: pd.DataFrame) -> None:
    fig = Figure(figsize=(12.5, 7.6))
    ax = fig.add_axes((0.05, 0.08, 0.8, 0.84))
    land_background(ax, (129.3, 131.55, 33.2, 34.55))
    for key, mk, lab in (("p_std", "o", "標準の飛行"),):
        sc = ax.scatter(d.best_lon, d.best_lat, c=100 * d[key], cmap="viridis", vmin=10, vmax=40,
                        s=22, marker=mk, edgecolor="#1b1f3a", lw=0.4, zorder=4, label=lab)
    cax = fig.add_axes((0.87, 0.2, 0.02, 0.6))
    fig.colorbar(sc, cax=cax, label="実施できる確率 [%]（標準の飛行）")
    for g, s in d.groupby("area_group"):
        la, lo = s.best_lat.max() + 0.04, s.best_lon.mean()
        ax.text(lo, la, f"{g}\n{len(s)} か所・{100 * s.p_std.median():.0f} %", fontsize=8.5,
                ha="center", va="bottom",
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.85})
    ax.set_title(f"北部九州・山口の打ち上げ候補地（{len(d)} か所、ラベルは件数と確率の中央値）",
                 fontsize=12)
    fig.text(0.05, 0.02, "地上気象: 壱岐はアメダス芦辺、平戸・唐津はアメダス平戸・唐津、"
             "その他は ERA5（ERA5 は沿岸で確率が低めに出る）", fontsize=9)
    ax.tick_params(labelsize=8)
    for ext in ("png", "pdf"):
        fig.savefig(C.FIGS / f"launch_spots_west.{ext}", dpi=200)


def tables(d: pd.DataFrame) -> None:
    iki = d[d.area_group == "壱岐"].sort_values("clearance_m", ascending=False).head(15)
    rows = []
    for k, r in enumerate(iki.itertuples(), start=1):
        rows.append(f"{k} & {r.name} & {r.kind_ja} & {r.best_lat:.4f}, {r.best_lon:.4f} & "
                    f"{r.clearance_m:.0f} & {r.area_m2 / 1e4:.1f} & {r.dist_airport_km:.1f} & "
                    f"{100 * r.p_std:.0f} / {100 * r.p_short:.0f} & {r.permission} \\\\")
    (TAB / "spots_iki.tex").write_text(
        "\\begin{tabular}{rllcrrrcl}\n\\toprule\n"
        " & 名前 & 種類 & 緯度, 経度 & 距離 [m] & 面積 [ha] & 空港 [km] & 確率 [\\%] & \\\\\n"
        "\\midrule\n" + "\n".join(rows).replace("&", "&").replace("_", "\\_")
        + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")
    rows = []
    for g, s in d.groupby("area_group"):
        s = s.sort_values("clearance_m", ascending=False)
        best = s.iloc[0]
        rows.append((s.p_std.median(), f"{g} & {len(s)} & {(s.clearance_m >= 60).sum()} & "
                     f"{100 * s.p_std.min():.0f}--{100 * s.p_std.max():.0f} & "
                     f"{100 * s.p_short.min():.0f}--{100 * s.p_short.max():.0f} & "
                     f"{best['name']}（{best.clearance_m:.0f} m） \\\\"))
    rows = [r for _, r in sorted(rows, reverse=True)]
    (TAB / "spots_groups.tex").write_text(
        "\\begin{tabular}{lrrccl}\n\\toprule\n"
        "地域 & 候補 & 距離 60 m 以上 & 標準 [\\%] & 短時間 [\\%] & 距離がいちばん大きい所 \\\\\n"
        "\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")


def main() -> int:
    apply_style(japanese=True)
    d = load()
    cols = ["area_group", "name", "kind_ja", "permission", "best_lat", "best_lon", "clearance_m",
            "dist_power_m", "dist_building_m", "area_m2", "dist_airport_km", "p_std", "p_short",
            "sfc_source", "gmaps", "osm_url"]
    d[cols].to_csv(C.RESULTS / "launch_spots.csv", index=False, float_format="%.4f")
    fig_iki(d)
    fig_west(d)
    tables(d)
    print(len(d), "spots after merge;", d.groupby("area_group").size().to_dict())
    iki = d[d.area_group == "壱岐"]
    print("iki p_std range", iki.p_std.min(), iki.p_std.max(), "n", len(iki),
          ">=60m", (iki.clearance_m >= 60).sum())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
