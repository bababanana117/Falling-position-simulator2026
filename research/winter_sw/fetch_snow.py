"""ERA5 の積雪深を西日本の範囲だけ取ってくる（1・2 月、2016–2025 年）。

NSF NCAR GDEX の ERA5 地上解析（データセット d633000）から、積雪深
``sd``（水当量、m）を 1 日 1 回（03 UTC = 12 時 JST）切り出す。ファイルは
1 か月・1 変数ごとなので、20 回の取得で済む。

    python winter_sw/fetch_snow.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from windclim.regions import BBox  # noqa: E402

log = logging.getLogger("winter_sw.snow")

ROOT = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/d633000/e5.oper.an.sfc"
CACHE = HERE / "data"
HOUR_UTC = 3
#: 落下点を判定する範囲。冬は東へ 250 km 以上流されるので、打ち上げ候補の範囲
#: （windclim.regions.SOUTHWEST）より東と北へ広げてある。
LANDING_BOX = BBox(south=24.0, north=38.5, west=122.0, east=143.0)


def month_url(year: int, month: int) -> str:
    last = {1: 31, 2: 29 if year % 4 == 0 else 28}[month]
    stamp = f"{year:04d}{month:02d}"
    return (f"{ROOT}/{stamp}/e5.oper.an.sfc.128_141_sd.ll025sc."
            f"{stamp}0100_{stamp}{last:02d}23.nc")


def fetch_month(job: tuple[int, int]) -> Path:
    year, month = job
    out = CACHE / f"era5_sd_{year:04d}{month:02d}.nc"
    if out.exists():
        return out
    with xr.open_dataset(month_url(year, month)) as ds:
        sub = ds["SD"].sel(latitude=slice(LANDING_BOX.north, LANDING_BOX.south),
                           longitude=slice(LANDING_BOX.west, LANDING_BOX.east))
        sub = sub.isel(time=sub["time"].dt.hour == HOUR_UTC).load()
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.nc")
    sub.to_dataset(name="sd").to_netcdf(tmp)
    tmp.rename(out)
    log.info("got %s", out.name)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    jobs = [(y, m) for y in range(2016, 2026) for m in (1, 2)]
    # netCDF/HDF5 はスレッドから同時に呼ぶと壊れるので、プロセスで並列にする
    with ProcessPoolExecutor(a.workers) as pool:
        for _ in pool.map(fetch_month, jobs):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
