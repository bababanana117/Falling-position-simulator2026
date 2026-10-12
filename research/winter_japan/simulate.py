"""全打ち上げ候補（0.05 度間隔の陸地）から、906 日の 9 時 JST に上げたときの落下点を計算する。

飛行条件は公称値 1 本（SCENARIOS の std と short）。出力は data/landings_<scenario>.npz。
上位の候補と壱岐については ensemble.py で飛行条件のばらつきも入れる。

    cd research && python winter_japan/simulate.py
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

W: C.Winds | None = None
CAND = None


def _run(args):
    t, asc, burst, desc = args
    n = len(CAND)
    lat, lon, dur = C.trajectory(W, t, CAND["lat"].to_numpy(), CAND["lon"].to_numpy(),
                                 CAND["elev"].to_numpy().clip(0),
                                 np.full(n, asc), np.full(n, burst), np.full(n, desc))
    return t, lat.astype(np.float32), lon.astype(np.float32), dur.astype(np.float32)


def main() -> int:
    global W, CAND
    t0 = time.time()
    terrain = C.Terrain()
    print("terrain", terrain.elev.shape, f"{time.time() - t0:.0f}s", flush=True)
    CAND = C.launch_candidates(terrain)
    CAND.to_csv(C.DATA / "candidates.csv", index=False)
    print("candidates", len(CAND), flush=True)
    W = C.Winds()
    nt = W.times.size
    for key, (_, asc, burst, desc) in C.SCENARIOS.items():
        lat = np.empty((nt, len(CAND)), np.float32)
        lon = np.empty_like(lat)
        dur = np.empty_like(lat)
        with mp.get_context("fork").Pool(16) as pool:
            for t, la, lo, du in pool.imap_unordered(_run, [(t, asc, burst, desc) for t in range(nt)],
                                                      chunksize=4):
                lat[t], lon[t], dur[t] = la, lo, du
        np.savez(C.DATA / f"landings_{key}.npz", lat=lat, lon=lon, dur=dur,
                 times=W.times.values)
        print(key, f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
