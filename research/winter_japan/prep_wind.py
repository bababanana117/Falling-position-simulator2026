"""JRA-3Q（日本全国）から 12・1・2 月の 00 UTC（9 時 JST）の風と高度を取り出す。

打ち上げは 9 時 JST に 1 日 1 回と考えるので、6 時間ごとの解析のうち 00 UTC だけを使う。
2016–2025 年の 12・1・2 月（906 日）。出力は data/jra3q_00utc.npz（約 1.6 GB）。

    cd research && python winter_japan/prep_wind.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from windclim.config import CACHE_ROOT  # noqa: E402
from windclim.stats.aggregate import AggregateConfig, load_month  # noqa: E402
from windclim.stats.altitude import geopotential_to_geometric  # noqa: E402

OUT = HERE / "data" / "jra3q_00utc.npz"


def main() -> int:
    us, vs, alts, times = [], [], [], []
    lat = lon = level = None
    for month in (12, 1, 2):
        s = load_month(CACHE_ROOT, "japan", month, AggregateConfig())
        t = s.times.astype("datetime64[h]")
        keep = (t.astype(int) % 24) == 0
        # 高度（hgt）はキャッシュに間引いて入っているので、月平均の高度を使う
        lat, lon, level = s.lat, s.lon, s.level
        lat3 = np.broadcast_to(lat[None, :, None], s.z[0].shape)
        alt1 = geopotential_to_geometric(np.nanmean(s.z, axis=0), lat3).astype(np.float32)
        alt = np.broadcast_to(alt1, (int(keep.sum()),) + alt1.shape)
        us.append(s.u[keep].astype(np.float32))
        vs.append(s.v[keep].astype(np.float32))
        alts.append(alt.astype(np.float32))
        times.append(s.times[keep])
        print(month, int(keep.sum()), flush=True)
        del s
    t = np.concatenate(times)
    order = np.argsort(t)
    np.savez(OUT, times=t[order], lat=lat, lon=lon, level=level,
             u=np.concatenate(us)[order], v=np.concatenate(vs)[order],
             alt=np.concatenate(alts)[order])
    print(OUT, t.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
