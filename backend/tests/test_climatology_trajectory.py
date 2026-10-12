import numpy as np
import pytest
from climatology_fixture import make_db

from bfps.climatology.model import STANDARD_FLIGHT, layer_seconds, mean_drift
from bfps.climatology.store import ClimatologyStore
from bfps.climatology.trajectory import mean_trajectory


def test_constant_wind_matches_layer_sum(tmp_path):
    p = tmp_path / "c.duckdb"
    make_db(p, u=10.0, v=0.0)
    store = ClimatologyStore(p)
    pts, burst = mean_trajectory(store, 0, 33.0, 130.0, STANDARD_FLIGHT, dt=10.0)
    lat, lon, alt, t = pts[-1]
    assert alt == 0.0
    assert pts[burst][2] == pytest.approx(30000.0)
    lv = store.levels(0, 0)
    T = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    e, _ = mean_drift(lv, T)
    east_m = (lon - 130.0) * 111195.0 * np.cos(np.radians(33.0))
    # 合成 DB は 8 面しかなく層が厚いので、層ごとに一定の降下速度とみなす layer_seconds と、
    # 30 秒きざみで密度を変える軌道とで飛行時間が数 % ずれる。風は一定なので距離も同じだけずれる
    assert east_m == pytest.approx(e, rel=0.1)
    assert east_m / t == pytest.approx(10.0, rel=1e-6)
    assert lat == pytest.approx(33.0, abs=1e-6)
    assert t == pytest.approx(T.sum(), rel=0.1)
