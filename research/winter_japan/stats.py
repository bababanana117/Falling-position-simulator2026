"""ensemble.py の日ごとの確率から、場所ごとの確率・信頼区間・土日の確率を出す。

信頼区間は年ごとのブロック・ブートストラップ（2016–2025 の 10 年を復元抽出、4000 回）。
同じ冬の中の日どうしは天気が続くので、日を独立に扱うと区間が狭く出すぎる。

土日祝の判定: 土・日と、12–2 月の祝日（元日、成人の日、建国記念の日、天皇誕生日
（2016–2018 は 12/23、2020 以降は 2/23）、振替休日）。年末年始の休み（12/29–1/3）は
別に数える。

    cd research && python winter_japan/stats.py
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

B = 4000
RNG = np.random.default_rng(11)


def holidays(dates: pd.DatetimeIndex) -> np.ndarray:
    hol = set()
    for y in range(2015, 2027):
        hol.add(pd.Timestamp(y, 1, 1))
        jan = pd.date_range(f"{y}-01-01", f"{y}-01-31")
        hol.add(jan[jan.weekday == 0][1])                    # 成人の日: 1 月第 2 月曜
        hol.add(pd.Timestamp(y, 2, 11))
        if y >= 2020:
            hol.add(pd.Timestamp(y, 2, 23))
        if y <= 2018:
            hol.add(pd.Timestamp(y, 12, 23))
    for h in list(hol):                                      # 振替休日
        if h.weekday() == 6:
            nxt = h + pd.Timedelta(days=1)
            while nxt in hol:
                nxt += pd.Timedelta(days=1)
            hol.add(nxt)
    return np.array([d in hol for d in dates])


def year_boot(p: np.ndarray, years: np.ndarray, stat=np.mean) -> tuple[float, float]:
    uy = np.unique(years)
    groups = [p[years == y] for y in uy]
    vals = np.empty(B)
    for b in range(B):
        pick = RNG.integers(0, len(uy), len(uy))
        vals[b] = stat(np.concatenate([groups[k] for k in pick]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def weekend_blocks(dates: pd.DatetimeIndex, off: np.ndarray) -> list[np.ndarray]:
    """連続する休日のかたまり（土日、祝日つきの連休）の添字。"""
    blocks, cur = [], []
    for k in range(len(dates)):
        if off[k] and (not cur or (dates[k] - dates[cur[-1]]).days == 1):
            cur.append(k)
        else:
            if cur:
                blocks.append(np.array(cur))
            cur = [k] if off[k] else []
    if cur:
        blocks.append(np.array(cur))
    return blocks


def site_stats(name: str, p: dict[str, np.ndarray], dates: pd.DatetimeIndex,
               lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> dict:
    years = dates.year.to_numpy()
    wkend = dates.weekday.to_numpy() >= 5
    off = wkend | holidays(dates)
    newyear = ((dates.month == 12) & (dates.day >= 29)) | ((dates.month == 1) & (dates.day <= 3))
    pt = p["total"]
    out = {"name": name}
    for k in ("wind", "land", "launch", "sfc", "total"):
        out[f"p_{k}"] = float(p[k].mean())
    out["ci_total"] = year_boot(pt, years)
    out["ci_wind"] = year_boot(p["wind"], years)
    # 気象条件（地上・雪）だけで実施できる日の割合と、そこからの落下の成功
    wx = p["launch"] * p["sfc"]      # 0/1（飛行条件に依らない）
    out["p_weather_ok"] = float(wx.mean())
    out["p_landing_given_weather"] = float(pt.sum() / max(wx.sum(), 1e-9))
    out["by_month"] = {int(m): float(pt[dates.month == m].mean()) for m in (12, 1, 2)}
    out["by_month_ci"] = {int(m): year_boot(pt[dates.month == m], years[dates.month == m])
                          for m in (12, 1, 2)}
    out["by_year"] = {int(y): float(pt[(years == y)].mean()) for y in np.unique(years)}
    # 土日
    out["p_total_weekend"] = float(pt[wkend].mean())
    out["p_total_weekday"] = float(pt[~wkend].mean())
    out["p_total_offday"] = float(pt[off].mean())
    out["p_total_newyear"] = float(pt[newyear].mean())
    out["ci_weekend"] = year_boot(pt[wkend], years[wkend])
    # 1 回の週末（土日の 2 日）で、どちらかの日に実施できる確率
    sat = np.where(dates.weekday == 5)[0]
    pairs = [(s, s + 1) for s in sat if s + 1 < len(dates) and (dates[s + 1] - dates[s]).days == 1]
    p_pair = np.array([1 - (1 - pt[a]) * (1 - pt[b]) for a, b in pairs])
    p_sat_only = np.array([pt[a] for a, _ in pairs])
    out["p_weekend_either"] = float(p_pair.mean())
    out["p_weekend_sat"] = float(p_sat_only.mean())
    out["ci_weekend_either"] = year_boot(p_pair, years[[a for a, _ in pairs]])
    # 土日の天気のつながり: 土曜に実施できたとき日曜も実施できる確率
    a_ = np.array([pt[a] for a, _ in pairs])
    b_ = np.array([pt[b] for _, b in pairs])
    out["p_sun_given_sat"] = float((a_ * b_).sum() / max(a_.sum(), 1e-9))
    # 1 シーズン（12–2 月）あたり、実施できる土日の日数の期待値
    season = np.where(dates.month == 12, dates.year + 1, dates.year)
    full = [s for s in np.unique(season) if 2017 <= s <= 2025]
    out["n_ok_weekend_days_per_season"] = float(np.mean([pt[(season == s) & wkend].sum() for s in full]))
    out["n_ok_days_per_season"] = float(np.mean([pt[season == s].sum() for s in full]))
    out["n_ok_offdays_per_season"] = float(np.mean([pt[(season == s) & off].sum() for s in full]))
    # 各月に 1 日でも実施できる土日がある確率
    pm = {}
    for m in (12, 1, 2):
        vals = []
        for y in np.unique(years):
            sel = (years == y) & (dates.month == m) & wkend
            if sel.sum() >= 6:
                vals.append(1 - np.prod(1 - pt[sel]))
        pm[int(m)] = float(np.mean(vals))
    out["p_month_has_ok_weekend"] = pm
    # シーズン中に土日で n 回以上実施できる確率（日ごとの成否を乱数で）
    sims = []
    for s in full:
        sel = (season == s) & wkend
        draws = RNG.random((2000, sel.sum())) < pt[sel][None, :]
        sims.append(draws.sum(axis=1))
    sims = np.concatenate(sims)
    out["p_season_weekend_at_least"] = {n: float((sims >= n).mean()) for n in (1, 2, 3, 5)}
    # 週末ごとに挑戦したとき、最初に実施できるまでの週末の数。
    # 12–2 月のどの週末から始めても同じ重みで数える（シーズン内で打ち切り）
    waits = []
    for s in full:
        idx = [k for k, (a, _) in enumerate(pairs) if season[a] == s]
        pp = p_pair[idx]
        for _ in range(300):
            ok = RNG.random(len(pp)) < pp
            nxt = np.full(len(pp), 99)
            last = 99
            for q in range(len(pp) - 1, -1, -1):
                if ok[q]:
                    last = q
                nxt[q] = last - q + 1 if last < 99 else 99
            waits.append(nxt)
    waits = np.concatenate(waits)
    out["wait_weekends_median"] = float(np.median(waits))
    out["p_success_within_weekends"] = {n: float((waits <= n).mean()) for n in (1, 2, 3, 4, 6, 8)}
    # 実施できない理由を重ならないように分ける（その日の判断の順番: 雪 → 地上気象 → 落下点）
    wx = p["launch"] * p["sfc"]
    out["why"] = {
        "launch_snow": float((1 - p["launch"]).mean()),
        "surface_weather": float((p["launch"] * (1 - p["sfc"])).mean()),
        "landing_mountain": float((wx * p["f_mountain"]).mean()),
        "landing_far_sea": float((wx * p["f_far_sea"]).mean()),
        "landing_urban": float((wx * p["f_urban"]).mean()),
        "landing_snow": float((wx * p["f_snow_landing"]).mean()),
        "success_plain": float((wx * p["plain_ok"] * p["land"].clip(0, 1) / np.maximum(p["land"], 1e-9)).mean()),
        "success": float(pt.mean()),
    }
    # 成功の内訳（平野・瀬戸内海・海岸近くの海）は成功した日の割合で按分する
    tot = p["plain_ok"] + p["seto"] + p["near_sea"]
    for name in ("plain_ok", "seto", "near_sea"):
        share = np.divide(p[name], tot, out=np.zeros_like(tot), where=tot > 0)
        out["why"][f"success_{name}"] = float((pt * share).mean())
    del out["why"]["success_plain"]
    # 「統計風のとおり」になる確率: 落下点がその月の平均落下点から 30/50 km 以内
    within = {}
    for r in (30, 50):
        vals = []
        for m in (12, 1, 2):
            sel = dates.month == m
            mla, mlo = lat[sel].mean(), lon[sel].mean()
            dx = (lon[sel] - mlo) * C.KM_PER_DEG * np.cos(np.radians(mla))
            dy = (lat[sel] - mla) * C.KM_PER_DEG
            vals.append((np.hypot(dx, dy) <= r).mean(axis=1))
        within[r] = float(np.concatenate(vals).mean())
    out["p_near_climatology"] = within
    for k in ("f_far_sea", "f_mountain", "f_urban", "f_snow_landing", "seto", "near_sea", "plain_ok"):
        out[k] = float(p[k].mean())
    return out


def main() -> int:
    allres = {}
    for key in C.SCENARIOS:
        d = np.load(C.DATA / f"ensemble_{key}.npz", allow_pickle=True)
        dates = pd.DatetimeIndex(d["times"]).normalize()
        names = list(d["names"])
        sites = pd.read_csv(C.RESULTS / "sites.csv")
        res = []
        for s, name in enumerate(names):
            p = {k[2:]: d[k][:, s] for k in d.files if k.startswith("p_")}
            res.append(site_stats(name, p, dates, d["lat"][:, s], d["lon"][:, s],
                                  float(sites.loc[s, "lat"]), float(sites.loc[s, "lon"])))
        allres[key] = res
        daily = pd.DataFrame({"date": dates})
        for s, name in enumerate(names):
            daily[name] = d["p_total"][:, s]
        daily.to_csv(C.RESULTS / f"daily_total_{key}.csv", index=False, float_format="%.3f")
    (C.RESULTS / "stats.json").write_text(json.dumps(allres, ensure_ascii=False, indent=1))
    for r in allres["std"]:
        print(r["name"], round(r["p_total"], 3), [round(x, 3) for x in r["ci_total"]],
              "wkend-either", round(r["p_weekend_either"], 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
