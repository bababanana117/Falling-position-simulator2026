"""ERA5 の 1 時間値を北海道の範囲だけ取ってくる。

NSF NCAR GDEX の ERA5（データセット d633000、0.25 度、37 気圧面）を OPeNDAP で
切り出す。ファイルは 1 変数・1 日ごとなので、1 日ずつ取ってキャッシュする。
途中で止めても、再実行すれば取っていない日だけを取る。

    python alpha/fetch_era5.py                 # 2025 年 7 月
    python alpha/fetch_era5.py --month 2025-01
"""

from __future__ import annotations

import argparse
import calendar
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import xarray as xr

log = logging.getLogger("alpha.fetch")

ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.an.pl"
#: 変数名 → (GRIB のパラメータ番号, 格子の種類, ファイル中の変数名)
VARS = {
    "u": ("128_131_u", "ll025uv", "U"),
    "v": ("128_132_v", "ll025uv", "V"),
    "z": ("128_129_z", "ll025sc", "Z"),
}
#: 本文の北海道領域と同じ箱（北緯 40.0〜46.5 度、東経 138.0〜149.0 度）
SOUTH, NORTH, WEST, EAST = 40.0, 46.5, 138.0, 149.0

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data"


def day_url(var: str, year: int, month: int, day: int) -> str:
    code, grid, _ = VARS[var]
    stamp = f"{year:04d}{month:02d}{day:02d}"
    return (f"{ROOT}/{year:04d}{month:02d}/"
            f"e5.oper.an.pl.{code}.{grid}.{stamp}00_{stamp}23.nc")


def cache_path(var: str, year: int, month: int, day: int) -> Path:
    return CACHE / f"era5_{var}_{year:04d}{month:02d}{day:02d}.nc"


def fetch_day(var: str, year: int, month: int, day: int) -> Path:
    out = cache_path(var, year, month, day)
    if out.exists():
        return out
    name = VARS[var][2]
    with xr.open_dataset(day_url(var, year, month, day)) as ds:
        # 緯度は北から南へ並んでいるので、slice も北から南の順に書く
        sub = ds[name].sel(latitude=slice(NORTH, SOUTH),
                           longitude=slice(WEST, EAST)).load()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.nc")
    sub.to_dataset(name=var).to_netcdf(tmp)
    tmp.rename(out)
    log.info("got %s", out.name)
    return out


def _fetch_job(job: tuple[str, int, int, int]) -> Path:
    return fetch_day(*job)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default="2025-07", help="YYYY-MM")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    year, month = (int(x) for x in a.month.split("-"))
    CACHE.mkdir(parents=True, exist_ok=True)
    days = range(1, calendar.monthrange(year, month)[1] + 1)
    jobs = [(var, year, month, d) for d in days for var in VARS]
    # スレッドではなくプロセスで並列にする。netCDF/HDF5 のライブラリは
    # スレッドから同時に呼ぶと壊れる。
    with ProcessPoolExecutor(a.workers) as pool:
        for _ in pool.map(_fetch_job, jobs):
            pass
    log.info("done: %d files in %s", len(jobs), CACHE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
