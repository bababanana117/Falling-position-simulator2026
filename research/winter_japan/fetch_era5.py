"""ERA5 の日本付近・冬季データを取ってくる（12・1・2 月、2016–2025 年）。

NSF NCAR GDEX の ERA5（データセット d633000）から、南西諸島から北海道まで
（北緯 24.0–46.5 度、東経 122.0–147.0 度）を覆う箱を、月ごとに 1 ファイルへ
まとめて切り出す。変数は次の 8 つ、すべて ERA5 の 0.25 度格子のまま：

    sd        積雪深（水当量, m）           03 UTC（12 時 JST）
    u10_00/v10_00  10 m 風                  00 UTC（09 時 JST）
    u10_03/v10_03  10 m 風                  03 UTC（12 時 JST）
    tcc_00    全雲量                        00 UTC（09 時 JST）
    tp_0003   降水量（mm）                  00–03 UTC 積算
    gust_0003 10 m 突風（m/s）              00–03 UTC 最大

sd・風・雲量は解析値（``e5.oper.an.sfc``）から素直に 1 時刻ずつ取れるが、
降水と突風は「予報値」（``e5.oper.fc.sfc.accumu`` / ``...minmax``）にしか
入っていない。予報ファイルは 06 UTC と 18 UTC 初期値・前 1〜12 時間分の
半月ファイルで、00–03 UTC は前日 18 UTC 初期値の forecast_hour=6..9 に
あたる（6 が 00 UTC、9 が 03 UTC）。

  * 降水（LSP, CP）は GDEX 変換後の時点で forecast_hour ごとの 1 時間降水量に
    なっている（初期値からの累積ではない。実データで確認：累積なら単調非減少の
    はずが実際は増減する）。forecast_hour=7,8,9（01,02,03 UTC の 1 時間降水）を
    そのまま合計すれば 00–03 UTC の 3 時間降水量。単位は m なので ×1000 で mm に。
  * 突風（10FG）はその 1 時間内の最大値なので、forecast_hour=7,8,9（それぞれ
    00–01, 01–02, 02–03 UTC）の最大を取る。

月初の 1 日分は「前日 18 UTC」が前月の半月ファイルに入っているため、
12・1・2 月それぞれ 11・12・1 月のファイルも読みに行く（取得はするが、
出力ファイルには混ぜない＝前月分の 1 初期値だけを使う）。

もう 1 つ、時間変化しない海陸マスク（``e5.oper.invariant``, param 128_172_lsm,
変数名 ``LSM``）を同じ箱で 1 回だけ取り、``era5_lsm.nc`` に保存する。壱岐の
ように 0.25 度格子ではほぼ海に囲まれた小島があり、その格子点の地上風は
海上補正が乗って陸上の実態とずれるため、解析側で「陸優勢な最寄りセル」を
選ぶのに使う。

netCDF/HDF5 はスレッドから同時に叩くと壊れるので、月ごとにプロセスで
並列化する。ファイルは ``.part.nc`` に書いてから rename するので、
既存ファイルはスキップでき、再実行しても安全。

    python winter_japan/fetch_era5.py
    python winter_japan/fetch_era5.py --workers 8
"""

from __future__ import annotations

import argparse
import calendar
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from windclim.regions import BBox  # noqa: E402

log = logging.getLogger("winter_japan.era5")

AN_ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.an.sfc"
ACCUMU_ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.fc.sfc.accumu"
MINMAX_ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.fc.sfc.minmax"
#: 海陸マスクは不変量（invariant）で、1979-01-01 00 UTC の 1 時刻しかない。
LSM_URL = ("https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.invariant/197901/"
           "e5.oper.invariant.128_172_lsm.ll025sc.1979010100_1979010100.nc")
CACHE = HERE / "data"

#: 対象範囲。台湾寄りの南西諸島から北海道までを覆う（緯度は南→北、経度は東経）。
BOX = BBox(south=24.0, north=46.5, west=122.0, east=147.0)

#: 取ってくる月。12・1・2 月 × 2016–2025 年 = 30 か月。
MONTHS = (
    [(y, 1) for y in range(2016, 2026)]
    + [(y, 2) for y in range(2016, 2026)]
    + [(y, 12) for y in range(2016, 2026)]
)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def an_sfc_url(param_code: str, year: int, month: int) -> str:
    """解析値（時別値）ファイルの URL。1 か月分がまるごと 1 ファイル。"""
    last = calendar.monthrange(year, month)[1]
    stamp = f"{year:04d}{month:02d}"
    return (f"{AN_ROOT}/{stamp}/e5.oper.an.sfc.{param_code}.ll025sc."
            f"{stamp}0100_{stamp}{last:02d}23.nc")


def fc_half_url(root: str, ds_name: str, param_code: str, year: int, month: int, half: str) -> str:
    """予報値（積算・極値）ファイルの URL。1 か月が前半・後半の 2 ファイルに分かれる。

    ファイル名の日付範囲は月の実際の日数によらず常に ``<月>0106``/``<月>1606``/
    ``<翌月>0106`` の形（2 月でも 30 日の月でも同じ）。
    """
    ym = f"{year:04d}{month:02d}"
    ny, nm = _next_month(year, month)
    nym = f"{ny:04d}{nm:02d}"
    if half == "first":
        rng = f"{ym}0106_{ym}1606"
    else:
        rng = f"{ym}1606_{nym}0106"
    return f"{root}/{ym}/e5.oper.fc.sfc.{ds_name}.{param_code}.ll025sc.{rng}.nc"


def _round_coords(da: xr.DataArray) -> xr.DataArray:
    """緯度経度の浮動小数点誤差を丸めて、変数間で座標をぴったり揃える。"""
    coords = {}
    if "latitude" in da.coords:
        coords["latitude"] = np.round(da["latitude"].values, 4)
    if "longitude" in da.coords:
        coords["longitude"] = np.round(da["longitude"].values, 4)
    return da.assign_coords(coords)


def _fetch_an_hourly(param_code: str, var: str, year: int, month: int, hours: list[int]) -> xr.DataArray:
    """解析値ファイルから、指定した UTC 時刻だけを箱で切り出す。"""
    url = an_sfc_url(param_code, year, month)
    with xr.open_dataset(url) as ds:
        sub = ds[var].sel(latitude=slice(BOX.north, BOX.south), longitude=slice(BOX.west, BOX.east))
        sub = sub.isel(time=sub["time"].dt.hour.isin(hours)).load()
    return _round_coords(sub)


def _day_inits(year: int, month: int) -> list[tuple[date, pd.Timestamp]]:
    """月内の各日について、00–03 UTC を計算するのに要る「前日 18 UTC」初期値を返す。"""
    ndays = calendar.monthrange(year, month)[1]
    out = []
    for d in range(1, ndays + 1):
        day = date(year, month, d)
        init = pd.Timestamp(day) - pd.Timedelta(days=1) + pd.Timedelta(hours=18)
        out.append((day, init))
    return out


def _group_by_file(inits: list[tuple[date, pd.Timestamp]]) -> dict[tuple[int, int, str], list[tuple[date, pd.Timestamp]]]:
    groups: dict[tuple[int, int, str], list[tuple[date, pd.Timestamp]]] = {}
    for day, init in inits:
        half = "first" if init.day <= 15 else "second"
        key = (init.year, init.month, half)
        groups.setdefault(key, []).append((day, init))
    return groups


def _fetch_tp_gust(year: int, month: int) -> tuple[xr.DataArray, xr.DataArray]:
    """00–03 UTC の降水量（mm）と突風最大（m/s）を、日ごとの time 軸で返す。"""
    inits = _day_inits(year, month)
    groups = _group_by_file(inits)

    tp_parts = []
    gust_parts = []
    for (fy, fm, half), items in groups.items():
        days = [pd.Timestamp(d) for d, _ in items]
        init_list = [i for _, i in items]

        lsp_url = fc_half_url(ACCUMU_ROOT, "accumu", "128_142_lsp", fy, fm, half)
        cp_url = fc_half_url(ACCUMU_ROOT, "accumu", "128_143_cp", fy, fm, half)
        fg_url = fc_half_url(MINMAX_ROOT, "minmax", "128_049_10fg", fy, fm, half)

        with xr.open_dataset(lsp_url) as ds:
            lsp = ds["LSP"].sel(forecast_initial_time=init_list, forecast_hour=[7, 8, 9])
            lsp = lsp.sel(latitude=slice(BOX.north, BOX.south), longitude=slice(BOX.west, BOX.east)).load()
        with xr.open_dataset(cp_url) as ds:
            cp = ds["CP"].sel(forecast_initial_time=init_list, forecast_hour=[7, 8, 9])
            cp = cp.sel(latitude=slice(BOX.north, BOX.south), longitude=slice(BOX.west, BOX.east)).load()

        # LSP/CP は forecast_hour ごとの「その 1 時間の」降水量（初期値からの累積ではない）。
        # 実データで確認済み：累積なら単調非減少のはずが、実際は増減する（雨の立ち上がり・
        # 収まりの形）。そのため forecast_hour=7,8,9（01,02,03 UTC の 1 時間降水）を
        # そのまま合計すれば 00-03 UTC の 3 時間降水量になる。
        tp_m = (lsp + cp).sum(dim="forecast_hour")
        # 圧縮由来のごく小さな負値（-1e-5 m 未満のノイズ）だけを 0 に丸める。
        tp_mm = xr.where(tp_m < 0, 0.0, tp_m) * 1000.0
        tp_mm = tp_mm.rename({"forecast_initial_time": "time"}).assign_coords(time=days)
        tp_parts.append(_round_coords(tp_mm))

        with xr.open_dataset(fg_url) as ds:
            fg = ds["VAR_10FG"].sel(forecast_initial_time=init_list, forecast_hour=[7, 8, 9])
            fg = fg.sel(latitude=slice(BOX.north, BOX.south), longitude=slice(BOX.west, BOX.east)).load()
        gust = fg.max(dim="forecast_hour")
        gust = gust.rename({"forecast_initial_time": "time"}).assign_coords(time=days)
        gust_parts.append(_round_coords(gust))

    tp = xr.concat(tp_parts, dim="time").sortby("time")
    gust = xr.concat(gust_parts, dim="time").sortby("time")

    ndays = calendar.monthrange(year, month)[1]
    assert tp.sizes["time"] == ndays, f"tp: expected {ndays} days, got {tp.sizes['time']}"
    assert gust.sizes["time"] == ndays, f"gust: expected {ndays} days, got {gust.sizes['time']}"
    return tp, gust


def fetch_month(job: tuple[int, int]) -> Path:
    year, month = job
    out = CACHE / f"era5_sfc_{year:04d}{month:02d}.nc"
    if out.exists():
        return out

    sd = _fetch_an_hourly("128_141_sd", "SD", year, month, [3])
    sd = sd.assign_coords(time=sd["time"].dt.floor("D"))

    # 00 UTC と 03 UTC を 1 回の取得でまとめて取り、hour で振り分けてから日付に丸める。
    u_raw = _fetch_an_hourly("128_165_10u", "VAR_10U", year, month, [0, 3])
    v_raw = _fetch_an_hourly("128_166_10v", "VAR_10V", year, month, [0, 3])
    u10_00 = u_raw.isel(time=u_raw["time"].dt.hour == 0)
    u10_03 = u_raw.isel(time=u_raw["time"].dt.hour == 3)
    v10_00 = v_raw.isel(time=v_raw["time"].dt.hour == 0)
    v10_03 = v_raw.isel(time=v_raw["time"].dt.hour == 3)
    for da in (u10_00, u10_03, v10_00, v10_03):
        da.coords["time"] = da["time"].dt.floor("D")

    tcc = _fetch_an_hourly("128_164_tcc", "TCC", year, month, [0])
    tcc = tcc.assign_coords(time=tcc["time"].dt.floor("D"))

    tp, gust = _fetch_tp_gust(year, month)

    ds_out = xr.Dataset(
        {
            "sd": sd.drop_vars("utc_date", errors="ignore"),
            "u10_00": u10_00.drop_vars("utc_date", errors="ignore"),
            "v10_00": v10_00.drop_vars("utc_date", errors="ignore"),
            "u10_03": u10_03.drop_vars("utc_date", errors="ignore"),
            "v10_03": v10_03.drop_vars("utc_date", errors="ignore"),
            "tcc_00": tcc.drop_vars("utc_date", errors="ignore"),
            "tp_0003": tp,
            "gust_0003": gust,
        }
    )
    ds_out["tp_0003"].attrs["units"] = "mm"
    ds_out["tp_0003"].attrs["long_name"] = "total precipitation, 00-03 UTC accumulated"
    ds_out["gust_0003"].attrs["units"] = "m s**-1"
    ds_out["gust_0003"].attrs["long_name"] = "10 m wind gust, max over 00-03 UTC"
    ds_out.attrs["source"] = "ERA5 (NSF NCAR GDEX d633000)"
    ds_out.attrs["box"] = f"lat {BOX.south}-{BOX.north} N, lon {BOX.west}-{BOX.east} E"

    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.nc")
    ds_out.to_netcdf(tmp)
    tmp.rename(out)
    log.info("got %s", out.name)
    return out


def fetch_lsm() -> Path:
    """海陸マスク（0=海, 1=陸）を箱で切り出して 1 回だけ保存する。"""
    out = CACHE / "era5_lsm.nc"
    if out.exists():
        return out
    with xr.open_dataset(LSM_URL) as ds:
        sub = ds["LSM"].sel(latitude=slice(BOX.north, BOX.south), longitude=slice(BOX.west, BOX.east))
        sub = sub.isel(time=0, drop=True).load()
    sub = _round_coords(sub)
    sub.attrs["long_name"] = "land-sea mask (0=sea, 1=land)"
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.nc")
    sub.to_dataset(name="lsm").to_netcdf(tmp)
    tmp.rename(out)
    log.info("got %s", out.name)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # netCDF/HDF5 はスレッドから同時に呼ぶと壊れるので、プロセスで並列にする
    with ProcessPoolExecutor(a.workers) as pool:
        # 海陸マスクは月とは独立なので、月次ジョブと一緒にキューへ流す。
        futures = [pool.submit(fetch_lsm)]
        futures += [pool.submit(fetch_month, job) for job in MONTHS]
        for fut in futures:
            fut.result()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
