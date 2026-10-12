"""判定の基準を変えたときに、選んだ場所の確率がどう変わるか（感度）。

ensemble.py の落下点（64 通りの飛行条件）を使い、次を 1 つずつ変える。

* 海岸から何 km までの海を成功に数えるか: 0（海は瀬戸内海だけ）/ 1 / 3 / 5 / 10 km
* 地上の風の上限: 3 / 4 / 5 / 7 / 10 m/s
* 降水の上限: 0.1 / 0.5 / 2 mm（9–12 時の合計）

    cd research && python winter_japan/sens.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402
from evaluate import judge  # noqa: E402


def main() -> int:
    terrain = C.Terrain()
    sfc = C.Surface()
    d = np.load(C.DATA / "ensemble_std.npz", allow_pickle=True)
    times = pd.DatetimeIndex(d["times"])
    names = list(d["names"])
    nt, n, m = d["lat"].shape
    sites = pd.read_csv(C.RESULTS / "sites.csv")
    cand = pd.DataFrame({"lat": np.repeat(sites["lat"], m).to_numpy(),
                         "lon": np.repeat(sites["lon"], m).to_numpy()})
    lat = d["lat"].reshape(nt, -1)
    lon = d["lon"].reshape(nt, -1)
    rows = []
    cases = [("coast_km", v) for v in (0.0, 1.0, 3.0, 5.0, 10.0)] \
        + [("wind_max", v) for v in (3.0, 4.0, 5.0, 7.0, 10.0)] \
        + [("precip_max", v) for v in (0.1, 0.5, 2.0)]
    for what, val in cases:
        kw = {what: val}
        j = judge(terrain, sfc, cand, lat, lon, times, **kw)
        p = j["total"].reshape(nt, n, m).mean(axis=2).mean(axis=0)
        pw = j["land"].reshape(nt, n, m).mean(axis=2).mean(axis=0)
        for s, name in enumerate(names):
            rows.append({"param": what, "value": val, "site": name,
                         "p_total": p[s], "p_land": pw[s]})
        print(what, val, flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(C.RESULTS / "sensitivity.csv", index=False, float_format="%.4f")
    print(out.pivot_table(index=["param", "value"], columns="site", values="p_total").round(3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
