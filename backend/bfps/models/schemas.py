"""API リクエスト/レスポンスのPydanticモデル."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FlightProfile(BaseModel):
    launch_latitude: float = Field(ge=-90, le=90)
    launch_longitude: float = Field(ge=-180, le=360)
    launch_altitude: float = 0.0
    launch_datetime: datetime
    ascent_rate: float = Field(gt=0, le=15)
    burst_altitude: float = Field(gt=1000, le=45000)
    descent_rate: float = Field(gt=0, le=30)


class TrajectoryPointOut(BaseModel):
    latitude: float
    longitude: float
    altitude: float
    time_s: float


class SimulateRequest(BaseModel):
    profile: FlightProfile
    engine: Literal["native", "tawhiri"] = "native"
    wind_source: Literal["openmeteo", "constant"] = "openmeteo"
    constant_wind_u: float = 0.0
    constant_wind_v: float = 0.0
    dt: float = Field(default=10.0, ge=1.0, le=60.0)


class SimulateResponse(BaseModel):
    trajectory: list[TrajectoryPointOut]
    landing_latitude: float
    landing_longitude: float
    burst_index: int
    flight_time_s: float
    warnings: list[str] = []


class DistributionsIn(BaseModel):
    ascent_rate_std: float = Field(default=0.5, ge=0)
    burst_altitude_std: float = Field(default=1500.0, ge=0)
    descent_rate_std: float = Field(default=0.5, ge=0)
    wind_error_std: float = Field(default=1.0, ge=0)


class MonteCarloRequest(BaseModel):
    profile: FlightProfile
    distributions: DistributionsIn = DistributionsIn()
    n_samples: int = Field(default=500, ge=10, le=2000)
    seed: int | None = 42
    wind_source: Literal["openmeteo", "constant"] = "openmeteo"
    constant_wind_u: float = 0.0
    constant_wind_v: float = 0.0


class EllipseOut(BaseModel):
    center_lat: float
    center_lon: float
    semi_major_m: float
    semi_minor_m: float
    bearing_deg: float


class MonteCarloResponse(BaseModel):
    landings: list[tuple[float, float]]  # [lat, lon]
    mean_lat: float
    mean_lon: float
    ellipse_95: EllipseOut
    percentile_radii_m: dict[int, float]
    flight_time_stats: dict[str, float]
    warnings: list[str] = []


class OptimizeRequest(BaseModel):
    profile: FlightProfile
    distributions: DistributionsIn = DistributionsIn()
    launch_time_offsets_h: list[float] = Field(default=[0, 6, 12, 18, 24], max_length=20)
    ascent_rates: list[float] = Field(default=[3, 4, 5, 6, 7], max_length=20)
    target_latitude: float | None = None
    target_longitude: float | None = None
    n_per_cell: int = Field(default=50, ge=10, le=200)
    seed: int | None = 42
    wind_source: Literal["openmeteo", "constant"] = "openmeteo"
    constant_wind_u: float = 0.0
    constant_wind_v: float = 0.0


class OptimizeCellOut(BaseModel):
    launch_datetime: datetime
    ascent_rate: float
    score: float
    mean_lat: float
    mean_lon: float


class OptimizeResponse(BaseModel):
    best: OptimizeCellOut
    grid: list[OptimizeCellOut]
    warnings: list[str] = []


class HealthResponse(BaseModel):
    status: str
    version: str


class ClimatologyRequest(BaseModel):
    launch_latitude: float = Field(ge=-90, le=90)
    launch_longitude: float = Field(ge=-180, le=360)
    launch_altitude: float = 0.0
    launch_datetime: datetime
    ascent_rate: float = Field(gt=0, le=15)
    burst_altitude: float = Field(gt=1000, le=45000)
    descent_rate: float = Field(gt=0, le=30)
    n_samples: int = Field(default=500, ge=10, le=2000)
    seed: int | None = 42


class TimebinOut(BaseModel):
    month: int
    bin: int
    label: str
    period: str


class CellOut(BaseModel):
    latitude: float
    longitude: float
    distance_km: float


class LatLonOut(BaseModel):
    latitude: float
    longitude: float


class ClimatologyResponse(BaseModel):
    timebin: TimebinOut
    cell: CellOut
    mean_landing: LatLonOut
    covariance_m2: list[list[float]]
    rho: float
    samples: list[list[float]]
    trajectory: list[TrajectoryPointOut]
    burst_index: int
    flight_time_s: float
    warnings: list[str] = []
