"""地上気象を ERA5 の代わりにアメダスの 9 時の観測で判定し、確率を出し直す。

ERA5 の地上風は 0.25 度格子の値で、島や海岸では格子に海が混ざるかどうかで大きく変わる。
近くにアメダスのある候補地は、観測で地上気象を判定したほうが実際に近い。

* 壱岐（2 地点） ← 芦辺
* 平戸・大島    ← 平戸
* 唐津・加唐島、唐津・相知 ← 唐津

判定の基準は本文と同じ（9 時の風 5 m/s 以下、9–12 時の降水 0.5 mm 未満）。
観測が欠けた日は ERA5 の判定を使う。

    cd research && python winter_japan/amedas_adjust.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402
from stats import site_stats  # noqa: E402

STATION = {"壱岐（島の中央）": "芦辺", "壱岐・郷ノ浦": "芦辺", "平戸・大島": "平戸",
           "唐津・加唐島": "唐津", "唐津・相知": "唐津"}


def main() -> int:
    am = pd.read_csv(C.DATA / "amedas_09jst.csv", parse_dates=["date"])
    sites = pd.read_csv(C.RESULTS / "sites.csv")
    out: dict = {"agreement": {}}
    for key in C.SCENARIOS:
        d = np.load(C.DATA / f"ensemble_{key}.npz", allow_pickle=True)
        dates = pd.DatetimeIndex(d["times"]).normalize()
        names = list(d["names"])
        res = []
        for site, st in STATION.items():
            s = names.index(site)
            obs = am[am["station"] == st].set_index("date").reindex(dates)
            ok = ((obs["ws09"] <= C.SFC_WIND_MAX) & (obs["precip_09_12"] < C.PRECIP_MAX_MM))
            valid = obs["ws09"].notna() & obs["precip_09_12"].notna()
            era = d["p_sfc"][:, s] > 0.5
            sfc = np.where(valid, ok, era).astype(np.float32)
            p = {k[2:]: d[k][:, s].copy() for k in d.files if k.startswith("p_")}
            p["sfc"] = sfc
            p["total"] = p["land"] * p["launch"] * sfc
            r = site_stats(site, p, dates, d["lat"][:, s], d["lon"][:, s],
                           float(sites.loc[s, "lat"]), float(sites.loc[s, "lon"]))
            r["station"] = st
            res.append(r)
            if key == "std":
                v = valid.to_numpy()
                e, a = era[v], ok.to_numpy()[v]
                out["agreement"][site] = {
                    "station": st, "n": int(v.sum()),
                    "era5_ok": float(e.mean()), "amedas_ok": float(a.mean()),
                    "both_ok": float((e & a).mean()), "era5_only": float((e & ~a).mean()),
                    "amedas_only": float((~e & a).mean()), "both_ng": float((~e & ~a).mean()),
                    "amedas_ws_median": float(obs["ws09"].median()),
                    "amedas_wind_ok": float((obs["ws09"] <= C.SFC_WIND_MAX)[valid].mean()),
                    "amedas_rain_ok": float((obs["precip_09_12"] < C.PRECIP_MAX_MM)[valid].mean()),
                }
        out[key] = res
    (C.RESULTS / "stats_amedas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for key in C.SCENARIOS:
        for r in out[key]:
            print(key, r["name"], r["station"], "total", round(r["p_total"], 3),
                  [round(x, 3) for x in r["ci_total"]], "sfc", round(r["p_sfc"], 3),
                  "wk-either", round(r["p_weekend_either"], 3), "w2", round(r["p_success_within_weekends"][2], 2),
                  "w4", round(r["p_success_within_weekends"][4], 2), "nwk", round(r["n_ok_weekend_days_per_season"], 1))
    print(json.dumps(out["agreement"], ensure_ascii=False, indent=0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
