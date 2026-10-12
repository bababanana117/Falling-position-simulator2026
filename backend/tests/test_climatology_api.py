from pathlib import Path

import pytest
from climatology_fixture import make_db
from fastapi.testclient import TestClient

from bfps.api import routes_climatology
from bfps.main import app

REQ = {
    "launch_latitude": 33.0,
    "launch_longitude": 130.0,
    "launch_altitude": 0,
    "launch_datetime": "2027-01-10T00:00:00Z",
    "ascent_rate": 5.0,
    "burst_altitude": 30000,
    "descent_rate": 6.0,
    "n_samples": 300,
    "seed": 7,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    p = tmp_path / "c.duckdb"
    make_db(p, u=10.0, v=1.0, rho=0.5)
    monkeypatch.setattr(routes_climatology, "_store", None)
    monkeypatch.setattr(routes_climatology.settings, "climatology_db", str(p))
    return TestClient(app)


def test_predict_ok(client):
    r = client.post("/api/climatology/predict", json=REQ)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["timebin"] == {"month": 1, "bin": 1, "label": "1月前半", "period": "2016–2025"}
    assert b["cell"]["latitude"] == 33.0 and b["cell"]["distance_km"] < 1.0
    assert len(b["samples"]) == 300
    assert b["rho"] == pytest.approx(0.5, abs=1e-6)
    assert b["mean_landing"]["longitude"] > 130.0
    assert b["trajectory"][0]["altitude"] == 0.0
    assert b["trajectory"][b["burst_index"]]["altitude"] == pytest.approx(30000.0)
    assert b["flight_time_s"] > 5000
    assert b["warnings"] == []


def test_predict_warns_high_burst(client):
    r = client.post("/api/climatology/predict", json={**REQ, "burst_altitude": 44000})
    assert r.status_code == 200
    assert any("40 km" in w for w in r.json()["warnings"])


def test_predict_outside_domain(client):
    r = client.post("/api/climatology/predict",
                    json={**REQ, "launch_latitude": 40.0, "launch_longitude": 140.0})
    assert r.status_code == 422


def test_predict_without_db(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_climatology, "_store", None)
    monkeypatch.setattr(routes_climatology.settings, "climatology_db",
                        str(tmp_path / "none.duckdb"))
    r = TestClient(app).post("/api/climatology/predict", json=REQ)
    assert r.status_code == 503
    assert "統計データベースが見つかりません" in r.json()["detail"]


REAL_DB = Path(__file__).resolve().parents[2] / "v2" / "jra3q_japan_wind_2016-2025_v2.duckdb"


@pytest.mark.skipif(not REAL_DB.exists(), reason="本物の DuckDB が無い")
def test_real_db_standard_flight_matches_fact_drift():
    import duckdb
    import numpy as np

    from bfps.climatology.model import (
        STANDARD_FLIGHT,
        drift_covariance,
        layer_seconds,
        mean_drift,
        solve_rho,
    )
    from bfps.climatology.store import ClimatologyStore

    store = ClimatologyStore(REAL_DB)
    cid, _, _, _ = store.nearest_cell(33.78, 129.72)       # 壱岐
    con = duckdb.connect(str(REAL_DB), read_only=True)
    e_obs, n_obs, ev, nv = con.execute(
        "SELECT east_m, north_m, east_var_m2, north_var_m2 FROM fact_drift "
        "WHERE cell_id = ? AND timebin_id = 0", [cid]).fetchone()
    lv = store.levels(cid, 0)
    T = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    e, n = mean_drift(lv, T)
    # fact_drift は解析時刻ごとの層の高度で作られているが、ここでは平均の高度を使うので少しずれる。
    # 南北成分は小さいので、成分ごとではなく落下点のずれの大きさを流され方の 0.5 % 以内で比べる
    assert np.hypot(e - e_obs, n - n_obs) < 5e-3 * np.hypot(e_obs, n_obs)
    rho = solve_rho(lv, T, ev, nv)
    cov = drift_covariance(lv, T, rho)
    assert cov[0, 0] + cov[1, 1] == pytest.approx(ev + nv, rel=0.05)
