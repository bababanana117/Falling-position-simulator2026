#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
気象庁アメダス（地上気象観測）の毎時値を取得するスクリプト。

目的
----
気球放球の可否判断（風速・降水の基準）をキャリブレーションするため、
長崎県・佐賀県の3地点について、冬季（12月・1月・2月）の9時JSTの
風速・風向と、9時から12時までの降水量合計を過去10年分まとめて取得する。

対象地点
--------
- 芦辺（壱岐, 長崎県, prec_no=84, block_no=1144）
  JMAの観測種目フラグ上、壱岐地区の「芦辺」には風速計があり、
  実際に hourly_a1.php のデータにも平均風速・風向の実測値が入っている
  （欠測ではなく "///" ではない数値）ことをサンプル取得で確認済み。
  そのため石田（block_no=1478）への切替えは行わず、芦辺を採用した。
- 平戸（長崎県, prec_no=84, block_no=47805）
  こちらは特別地域気象観測所（"s" タイプ）のため、AMeDAS用の
  hourly_a1.php ではなく hourly_s1.php を用いる。
- 唐津（佐賀県, prec_no=85, block_no=1610）

対象期間
--------
2016〜2025年の1月・2月・12月（各年12月は同年12月、1・2月は同年）。
合計903日 × 3地点。

取得元URL（1日1地点）
----------------------
https://www.data.jma.go.jp/stats/etrn/view/hourly_a1.php?prec_no=..&block_no=....&year=YYYY&month=M&day=D&view=
https://www.data.jma.go.jp/stats/etrn/view/hourly_s1.php?prec_no=..&block_no=....&year=YYYY&month=M&day=D&view=

hourly_a1.php（AMeDAS）の列構成（実際のページのヘッダから確認）:
    時, 降水量(mm), 気温(℃), 露点温度(℃), 蒸気圧(hPa), 湿度(％),
    平均風速(m/s), 風向, 日照時間(h), 降雪(cm), 積雪(cm)   -- 計11列

hourly_s1.php（特別地域気象観測所）の列構成:
    時, 気圧(現地), 気圧(海面), 降水量(mm), 気温(℃), 露点温度(℃),
    蒸気圧(hPa), 湿度(％), 風速(m/s), 風向, 日照時間(h),
    全天日射量(MJ/m2), 降雪(cm), 積雪(cm), 天気, 雲量, 視程(km) -- 計17列

JMAの記号の扱い
----------------
- "--"          : 降水量・降雪・積雪では「観測されたが量がゼロ（無降水/無積雪）」
                  を意味するので 0.0 として扱う。
- "×" "///" 空欄 : 欠測として NaN（None）にする。
- 末尾の ")" "]" などの品質フラグは取り除いて数値だけを残す。

抽出する値
----------
- 9時の平均風速・風向（ws09, wd09）
- 10時・11時・12時の降水量の合計（precip_09_12）
  ＝各時刻の値はその時刻に終わる1時間の降水量なので、
    10時+11時+12時の値の合計が「9時から12時までの降水量」になる。
- 9時の積雪（snow_depth09）。ページに積雪列が無い場合はNaN。

出力
----
research/winter_japan/data/amedas_09jst.csv
    列: date, station, block_no, ws09, wd09, precip_09_12, snow_depth09

キャッシュ
----------
取得した生HTMLは research/winter_japan/data/amedas_cache/ に保存し、
再実行時はキャッシュがあればそれを使う（サーバーへの再アクセスをしない）。

マナー
------
同時接続数は最大4、リクエスト毎に短いランダム待機を入れ、
失敗時は指数バックオフで再試行する。User-Agentは氏名やメールアドレスを
含まない中立な文字列 "Mozilla/5.0 (research script)" を用いる。

実行方法
--------
    conda activate jra3q
    python fetch_amedas.py
"""

from __future__ import annotations

import calendar
import csv
import random
import re
import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "data" / "amedas_cache"
OUT_CSV = BASE_DIR / "data" / "amedas_09jst.csv"

USER_AGENT = "Mozilla/5.0 (research script)"
HEADERS = {"User-Agent": USER_AGENT}

MAX_CONCURRENCY = 4
REQUEST_TIMEOUT = 20
MAX_RETRIES = 5
MIN_VALID_HTML_SIZE = 500  # これより小さいキャッシュは壊れているとみなし再取得する

STATIONS = [
    {"name": "芦辺", "prec_no": "84", "block_no": "1144", "page": "a1"},
    {"name": "平戸", "prec_no": "84", "block_no": "47805", "page": "s1"},
    {"name": "唐津", "prec_no": "85", "block_no": "1610", "page": "a1"},
]

# 列インデックス（0始まり）。ヘッダをサンプル取得して確認した固定値。
COLUMN_MAP = {
    "a1": {"precip": 1, "wind_speed": 6, "wind_dir": 7, "snow_depth": 10, "ncols": 11},
    "s1": {"precip": 3, "wind_speed": 8, "wind_dir": 9, "snow_depth": 13, "ncols": 17},
}

_semaphore = threading.Semaphore(MAX_CONCURRENCY)


def clean_numeric(raw: str):
    """JMAの毎時表の数値セルを float に変換する。欠測は None。"""
    if raw is None:
        return None
    s = raw.strip()
    if s in ("", "×", "///", "#", "-", "×)", "×]"):
        return None
    if s == "--":
        return 0.0
    # 末尾の品質フラグ ")" "]" "}" を除去
    s = re.sub(r"[)\]}]+$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def clean_text(raw: str):
    """風向などの文字列セル。欠測は None。"""
    if raw is None:
        return None
    s = raw.strip()
    if s in ("", "×", "///", "#"):
        return None
    return s


def cache_path(station: dict, y: int, m: int, d: int) -> Path:
    return CACHE_DIR / f"{station['page']}_{station['prec_no']}_{station['block_no']}_{y:04d}{m:02d}{d:02d}.html"


def fetch_html(station: dict, y: int, m: int, d: int) -> str:
    """1日1地点分のHTMLを取得する。キャッシュがあればそれを使う。"""
    path = cache_path(station, y, m, d)
    if path.exists() and path.stat().st_size >= MIN_VALID_HTML_SIZE:
        return path.read_text(encoding="utf-8")

    url = (
        f"https://www.data.jma.go.jp/stats/etrn/view/hourly_{station['page']}.php"
        f"?prec_no={station['prec_no']}&block_no={station['block_no']}"
        f"&year={y}&month={m}&day={d}&view="
    )
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            with _semaphore:
                time.sleep(random.uniform(0.3, 0.9))
                resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            text = resp.text
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep((2 ** attempt) + random.uniform(0, 1.0))
    raise RuntimeError(f"取得失敗: {url} ({last_exc})")


def parse_day(html: str, station: dict) -> dict:
    """1日分のHTMLから9時の風速・風向・積雪と9-12時の降水量合計を抽出する。"""
    result = {"ws09": None, "wd09": None, "precip_09_12": None, "snow_depth09": None}
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tablefix1")
    if table is None:
        return result

    cfg = COLUMN_MAP[station["page"]]
    ncols = cfg["ncols"]

    rows_by_hour = {}
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        h = cells[0]
        if h.isdigit():
            rows_by_hour[int(h)] = cells

    row9 = rows_by_hour.get(9)
    if row9 is not None and len(row9) >= ncols:
        result["ws09"] = clean_numeric(row9[cfg["wind_speed"]])
        result["wd09"] = clean_text(row9[cfg["wind_dir"]])
        result["snow_depth09"] = clean_numeric(row9[cfg["snow_depth"]])

    total = 0.0
    have_any = False
    for h in (10, 11, 12):
        row = rows_by_hour.get(h)
        if row is not None and len(row) >= ncols:
            v = clean_numeric(row[cfg["precip"]])
            if v is not None:
                total += v
                have_any = True
    result["precip_09_12"] = total if have_any else None
    return result


def build_days() -> list[tuple[int, int, int]]:
    """2016-2025年の1・2・12月の全日付を返す（合計903日になるはず）。"""
    days = []
    for y in range(2016, 2026):
        for m in (1, 2):
            ndays = calendar.monthrange(y, m)[1]
            for d in range(1, ndays + 1):
                days.append((y, m, d))
    for y in range(2016, 2026):
        m = 12
        ndays = calendar.monthrange(y, m)[1]
        for d in range(1, ndays + 1):
            days.append((y, m, d))
    return days


def process_one(station: dict, y: int, m: int, d: int) -> dict:
    try:
        html = fetch_html(station, y, m, d)
        parsed = parse_day(html, station)
    except Exception:  # noqa: BLE001
        parsed = {"ws09": None, "wd09": None, "precip_09_12": None, "snow_depth09": None}
    return {
        "date": f"{y:04d}-{m:02d}-{d:02d}",
        "station": station["name"],
        "block_no": station["block_no"],
        **parsed,
    }


def print_summary(results: list[dict]) -> None:
    by_station = defaultdict(list)
    for r in results:
        by_station[r["station"]].append(r)

    print("\n=== station summary (9JST) ===")
    for name, rows in by_station.items():
        n = len(rows)
        ws_vals = [r["ws09"] for r in rows if r["ws09"] is not None]
        precip_vals = [r["precip_09_12"] for r in rows if r["precip_09_12"] is not None]
        missing_ws = n - len(ws_vals)
        missing_precip = n - len(precip_vals)
        missing_frac = (missing_ws + missing_precip) / (2 * n) if n else float("nan")
        median_ws = statistics.median(ws_vals) if ws_vals else float("nan")
        frac_ws_le5 = (sum(1 for v in ws_vals if v <= 5) / len(ws_vals)) if ws_vals else float("nan")
        frac_precip_lt05 = (
            sum(1 for v in precip_vals if v < 0.5) / len(precip_vals) if precip_vals else float("nan")
        )
        both_n = 0
        both_ok = 0
        for r in rows:
            if r["ws09"] is not None and r["precip_09_12"] is not None:
                both_n += 1
                if r["ws09"] <= 5 and r["precip_09_12"] < 0.5:
                    both_ok += 1
        frac_both = (both_ok / both_n) if both_n else float("nan")
        print(
            f"{name}: n={n}  missing_frac={missing_frac:.3f}  "
            f"median_ws09={median_ws:.2f} m/s  frac(ws09<=5)={frac_ws_le5:.3f}  "
            f"frac(precip_09_12<0.5mm)={frac_precip_lt05:.3f}  frac(both)={frac_both:.3f}"
        )


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    days = build_days()
    print(f"対象日数: {len(days)} 日 x {len(STATIONS)} 地点 = {len(days) * len(STATIONS)} 件")

    tasks = [(st, y, m, d) for st in STATIONS for (y, m, d) in days]
    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as ex:
        futures = {ex.submit(process_one, st, y, m, d): (st, y, m, d) for (st, y, m, d) in tasks}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 200 == 0 or done == len(tasks):
                print(f"  progress: {done}/{len(tasks)}", flush=True)

    results.sort(key=lambda r: (r["station"], r["date"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "station", "block_no", "ws09", "wd09", "precip_09_12", "snow_depth09"]
        )
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"書き出し完了: {OUT_CSV} ({len(results)} 行)")

    print_summary(results)


if __name__ == "__main__":
    main()
