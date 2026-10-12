"""stats.json などから、レポートに入れる表（LaTeX）を作る。数値は手で書かない。

    cd research && python winter_japan/make_tables.py      # report/tables/*.tex
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

OUT = HERE / "report" / "tables"


def pct(x: float, nd: int = 0) -> str:
    return f"{100 * x:.{nd}f}"


def ci(c) -> str:
    return f"{pct(c[0])}--{pct(c[1])}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = json.loads((C.RESULTS / "stats.json").read_text())
    sites = pd.read_csv(C.RESULTS / "sites.csv").set_index("name")
    std = {r["name"]: r for r in s["std"]}
    sho = {r["name"]: r for r in s["short"]}
    order = sorted(std, key=lambda n: -std[n]["p_total"])

    # 表 1: 候補地の一覧（標準と短時間の飛行）
    rows = []
    for n in order:
        a, b = std[n], sho[n]
        rows.append(
            f"{n} & {sites.loc[n, 'lat']:.2f}, {sites.loc[n, 'lon']:.2f} & "
            f"{pct(a['p_wind'])} & {pct(a['p_launch'])} & {pct(a['p_sfc'])} & "
            f"\\textbf{{{pct(a['p_total'])}}} ({ci(a['ci_total'])}) & "
            f"\\textbf{{{pct(b['p_total'])}}} ({ci(b['ci_total'])}) \\\\")
    (OUT / "sites.tex").write_text(
        "\\begin{tabular}{lcrrrcc}\n\\toprule\n"
        "候補地 & 緯度, 経度 & 落下 & 雪なし & 地上気象 & \\multicolumn{2}{c}{実施できる確率 [\\%]} \\\\\n"
        "& & [\\%] & [\\%] & [\\%] & 標準 (95\\% 区間) & 短時間 (95\\% 区間) \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

    # 表 2: 土日の確率（上位と壱岐）
    order_s = sorted(sho, key=lambda n: -sho[n]["p_total"])
    pick = ["壱岐（島の中央）"] + [n for n in dict.fromkeys(order[:4] + order_s[:4])
                               if n != "壱岐（島の中央）"]
    rows = []
    for key, tab in (("標準", std), ("短時間", sho)):
        for n in pick:
            r = tab[n]
            w = r["p_success_within_weekends"]
            rows.append(
                f"{key} & {n} & {pct(r['p_total_weekend'])} & {pct(r['p_weekend_sat'])} & "
                f"{pct(r['p_weekend_either'])} & {pct(r['p_sun_given_sat'])} & "
                f"{r['n_ok_weekend_days_per_season']:.1f} & {pct(w['2'])} & {pct(w['4'])} \\\\")
        rows.append("\\midrule")
    rows.pop()
    (OUT / "weekend.tex").write_text(
        "\\begin{tabular}{llrrrrrrr}\n\\toprule\n"
        "飛行 & 候補地 & 土日の & 決めた土曜 & 土日の & 土曜に実施 & 1 冬に実施 & "
        "\\multicolumn{2}{c}{毎週末挑戦して} \\\\\n"
        "& & 1 日 [\\%] & 1 日 [\\%] & どちらか [\\%] & できたとき & できる土日 & "
        "2 週以内 & 4 週以内 \\\\\n"
        "& & & & & 日曜も [\\%] & [日] & [\\%] & [\\%] \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

    # 表 3: 壱岐の内訳（地上気象はアメダス芦辺。比較に ERA5 の標準）
    am = json.loads((C.RESULTS / "stats_amedas.json").read_text())
    ast = {r["name"]: r for r in am["std"]}
    ash = {r["name"]: r for r in am["short"]}
    rows = []
    labels = [("success_seto", "成功: 瀬戸内海に落ちる"), ("success_plain_ok", "成功: 平野に落ちる"),
              ("success_near_sea", "成功: 海岸から 3 km 以内の海"),
              ("launch_snow", "中止: 打ち上げ地点に雪"), ("surface_weather", "中止: 地上の風・雨"),
              ("landing_mountain", "見送り: 落下予測が山地"), ("landing_far_sea", "見送り: 落下予測が沖の海"),
              ("landing_urban", "見送り: 落下予測が市街地"), ("landing_snow", "見送り: 落下予測地点に雪")]
    n = "壱岐（島の中央）"
    for k, lab in labels:
        rows.append(f"{lab} & {pct(ast[n]['why'][k], 1)} & {pct(ash[n]['why'][k], 1)} & "
                    f"{pct(std[n]['why'][k], 1)} \\\\")
    rows.append("\\midrule")
    rows.append(f"実施できる（成功の合計） & \\textbf{{{pct(ast[n]['p_total'], 1)}}} & "
                f"\\textbf{{{pct(ash[n]['p_total'], 1)}}} & {pct(std[n]['p_total'], 1)} \\\\")
    rows.append(f"\\quad 95\\% 区間 & {ci(ast[n]['ci_total'])} & {ci(ash[n]['ci_total'])} & "
                f"{ci(std[n]['ci_total'])} \\\\")
    rows.append(f"実施できない & {pct(1 - ast[n]['p_total'], 1)} & {pct(1 - ash[n]['p_total'], 1)} & "
                f"{pct(1 - std[n]['p_total'], 1)} \\\\")
    (OUT / "iki.tex").write_text(
        "\\begin{tabular}{lrrr}\n\\toprule\n"
        "& \\multicolumn{2}{c}{地上気象: アメダス芦辺} & ERA5 \\\\\n"
        "9 時の判断の結果 & 標準 [\\%] & 短時間 [\\%] & 標準 [\\%] \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

    # 表 5: アメダスで地上気象を判定した場合
    rows = []
    for m in ast:
        if m == "壱岐・郷ノ浦":
            continue
        a, b = ast[m], ash[m]
        rows.append(f"{m} & {a['station']} & {pct(std[m]['p_sfc'])} & {pct(a['p_sfc'])} & "
                    f"{pct(std[m]['p_total'])} & \\textbf{{{pct(a['p_total'])}}} ({ci(a['ci_total'])}) & "
                    f"{pct(sho[m]['p_total'])} & \\textbf{{{pct(b['p_total'])}}} ({ci(b['ci_total'])}) \\\\")
    (OUT / "amedas.tex").write_text(
        "\\begin{tabular}{llrrrcrc}\n\\toprule\n"
        "& & \\multicolumn{2}{c}{地上気象が向く [\\%]} & \\multicolumn{4}{c}{実施できる [\\%]} \\\\\n"
        "& & & & \\multicolumn{2}{c}{標準} & \\multicolumn{2}{c}{短時間} \\\\\n"
        "候補地 & アメダス & ERA5 & アメダス & ERA5 & アメダス (95\\% 区間) & ERA5 & アメダス (95\\% 区間) \\\\\n"
        "\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

    # 表 6: 壱岐の土日（アメダス）
    rows = []
    for key, tab in (("標準", ast), ("短時間", ash)):
        r = tab[n]
        w = r["p_success_within_weekends"]
        rows.append(f"{key} & {pct(r['p_total'])} & {pct(r['p_total_weekend'])} & {pct(r['p_weekend_sat'])} & "
                    f"{pct(r['p_weekend_either'])} & {pct(r['p_sun_given_sat'])} & "
                    f"{r['n_ok_days_per_season']:.1f} & {r['n_ok_weekend_days_per_season']:.1f} & "
                    f"{pct(w['1'])} & {pct(w['2'])} & {pct(w['4'])} \\\\")
    (OUT / "iki_weekend.tex").write_text(
        "\\begin{tabular}{lrrrrrrrrrr}\n\\toprule\n"
        "& 全日 & 土日の & 決めた & 週末の & 土曜できた & \\multicolumn{2}{c}{1 冬に実施できる [日]} & "
        "\\multicolumn{3}{c}{毎週末挑戦して [\\%]} \\\\\n"
        "飛行 & [\\%] & 1 日 [\\%] & 土曜 [\\%] & どちらか [\\%] & 日曜も [\\%] & 全日 & 土日 & "
        "1 週目 & 2 週以内 & 4 週以内 \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

    # 表 4: 月別
    rows = []
    for n in pick:
        a, b = std[n], sho[n]
        rows.append(f"{n} & " + " & ".join(pct(a['by_month'][m]) for m in ("12", "1", "2"))
                    + " & " + " & ".join(pct(b['by_month'][m]) for m in ("12", "1", "2"))
                    + f" & {pct(a['p_total_newyear'])} & {pct(b['p_total_newyear'])} \\\\")
    (OUT / "months.tex").write_text(
        "\\begin{tabular}{lrrrrrrrr}\n\\toprule\n"
        "& \\multicolumn{3}{c}{標準 [\\%]} & \\multicolumn{3}{c}{短時間 [\\%]} & "
        "\\multicolumn{2}{c}{年末年始 [\\%]} \\\\\n"
        "候補地 & 12 月 & 1 月 & 2 月 & 12 月 & 1 月 & 2 月 & 標準 & 短時間 \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")
    print("tables ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
