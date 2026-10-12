"""統計モード（気候値）の予測 API。DuckDB は最初の呼び出しで開いて使い回す。"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from ..climatology.model import FlightSettings
from ..climatology.predict import PERIOD, OutsideDomainError, predict
from ..climatology.store import ClimatologyStore
from ..config import settings
from ..models.schemas import (
    CellOut,
    ClimatologyRequest,
    ClimatologyResponse,
    LatLonOut,
    TimebinOut,
    TrajectoryPointOut,
)

router = APIRouter()
_store: ClimatologyStore | None = None
_lock = threading.Lock()


def get_store() -> ClimatologyStore:
    global _store
    with _lock:
        if _store is None:
            try:
                _store = ClimatologyStore(settings.climatology_db)
            except FileNotFoundError as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"統計データベースが見つかりません: {settings.climatology_db}",
                ) from e
        return _store


@router.post("/api/climatology/predict", response_model=ClimatologyResponse)
def climatology_predict(req: ClimatologyRequest) -> ClimatologyResponse:
    store = get_store()
    f = FlightSettings(req.ascent_rate, req.burst_altitude, req.descent_rate,
                       req.launch_altitude)
    try:
        p = predict(store, req.launch_latitude, req.launch_longitude,
                    req.launch_datetime, f, req.n_samples, req.seed)
    except OutsideDomainError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    month, b, label = p.timebin
    return ClimatologyResponse(
        timebin=TimebinOut(month=month, bin=b, label=label, period=PERIOD),
        cell=CellOut(latitude=p.cell[0], longitude=p.cell[1], distance_km=p.cell[2]),
        mean_landing=LatLonOut(latitude=p.mean_landing[0], longitude=p.mean_landing[1]),
        covariance_m2=p.covariance.tolist(),
        rho=p.rho,
        samples=p.samples.round(5).tolist(),
        trajectory=[TrajectoryPointOut(latitude=a, longitude=o, altitude=z, time_s=t)
                    for a, o, z, t in p.trajectory],
        burst_index=p.burst_index,
        flight_time_s=p.flight_time_s,
        warnings=p.warnings,
    )
