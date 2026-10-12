"""Fly the payload through the grid instead of freezing the wind at the launch point.

Everything else in this package -- and the simulator in ``backend/`` -- computes a
landing point by taking one vertical wind profile and holding it still for the
whole flight. :mod:`windclim.stats.drift` does it in closed form, summing
``u_k T_k`` over the levels; ``backend/bfps/core/wind.py`` does it by returning
the launch-point profile no matter which latitude, longitude or time it is asked
for. Both give the same answer, and both are approximations.

This module removes the approximation so its size can be measured. The payload is
advected through the actual four-dimensional wind field: as it moves east it
samples the wind where it now *is*, and as the flight wears on it samples the wind
at the time it now *is*.

Four variants are available, and the difference between them is the whole point:

===============  ==============  =============  ===============================
variant          wind sampled    wind sampled   corresponds to
                 at time         at position
===============  ==============  =============  ===============================
``reference``    flight time     payload        the best the reanalysis can say
``time_frozen``  launch time     payload        freezing time alone
``place_frozen`` flight time     launch point   freezing place alone
``both_frozen``  launch time     launch point   **the current simulator**
===============  ==============  =============  ===============================

``both_frozen`` is redundant by construction: under both freezes the integral
collapses to the sum :func:`windclim.stats.drift.displacements` already computes.
That redundancy is deliberate -- it is the cross-check that the new integrator and
the old closed form agree where they are supposed to, and ``tests/test_trajectory``
asserts it to machine precision on *non-uniform* wind, not just on a constant
field.

The agreement is exact only where the map factor is constant, which is why those
tests use a purely zonal or purely meridional field. With both components active
the payload changes latitude during the flight, the ``1/cos(lat)`` factor changes
with it, and the closed form -- which has no latitude in it at all -- differs by a
few tenths of a percent. The integrator keeps the varying factor, because that is
what the simulator does and because it is the correct geometry.

Two design choices need stating, because neither is the obvious one.

**The vertical model is the layer model, not a finer one.** The payload is treated
as flying through layer *k* with level *k*'s wind, for exactly the
``layer_seconds`` that :mod:`windclim.stats.drift` already computes. A more
faithful scheme would interpolate the wind between pressure levels, but then the
difference from ``displacements`` would mix the vertical refinement in with the
horizontal and temporal freezing, and the measurement would no longer be of the
thing it claims to measure. Using the identical vertical discretisation makes
every difference reported here attributable to the freezing alone.

**The altitude profile is shared by every launch cell in a region.** All four
variants must fly the same ``z(t)``; if they did not, part of the difference
between them would be a difference in flight duration rather than in wind. Using
one profile per region rather than one per column also keeps the whole batch on a
single time grid, which is what makes the integration vectorisable. The cost is
small and measured rather than assumed: across Wakayama the altitude of a level
varies by at most about 190 m, which is 0.6 percent of the thirty-kilometre
climb, and :func:`altitude_profile_spread` reports the figure for every month so
the report can quote it.

Interpolation policy
--------------------
The rest of this package refuses to interpolate between grid cells
(``grid.nearest_cell``, ``outputs/csv_out``), and that refusal is right: the
stored quantities are *statistics*, and the interpolation of two 90th percentiles
is not a 90th percentile of anything. Here the interpolated quantity is the wind
field itself, which is a continuous physical field that the grid samples. A
balloon does not fly along grid points, so refusing to interpolate would be the
larger error, not the smaller one. To keep the two cases from being confused, the
bilinear interpolation lives only in this module and is never applied to a
statistic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..grid import EARTH_RADIUS_M
from .drift import FlightProfile, descent_rate_ms

__all__ = [
    "VARIANTS",
    "FlightSchedule",
    "GriddedWind",
    "TrajectoryResult",
    "altitude_profile_spread",
    "build_schedule",
    "integrate",
]

#: The four freeze combinations, in the order the report presents them.
VARIANTS: tuple[str, ...] = ("reference", "time_frozen", "place_frozen", "both_frozen")

#: Seconds between JRA-3Q analyses. A nominal flight lasts about 2.3 hours, so a
#: launch on the analysis grid never needs more than the two analyses bracketing
#: it -- which is why the time weight below is a single scalar per step rather
#: than a per-trajectory gather.
ANALYSIS_INTERVAL_S = 6 * 3600.0


@dataclass(frozen=True)
class FlightSchedule:
    """The vertical part of the flight, precomputed once and shared by every run.

    The flight is a sequence of segments. Each one is spent inside a single
    pressure level's layer, so ``level_index`` says which level's wind applies and
    ``seconds`` says for how long. Ascent visits the layers bottom to top, descent
    top to bottom, and the two together reproduce ``layer_seconds`` exactly.
    """

    level_index: NDArray[np.int64]     # (segment,) index into the ascending-altitude axis
    seconds: NDArray[np.float64]       # (segment,) duration of that segment
    z_start: NDArray[np.float64]       # (segment,) altitude entering the segment
    z_end: NDArray[np.float64]         # (segment,) altitude leaving it

    @property
    def total_seconds(self) -> float:
        return float(self.seconds.sum())

    @property
    def n_segments(self) -> int:
        return int(self.seconds.size)


def build_schedule(alt_m: NDArray[np.float64], flight: FlightProfile) -> FlightSchedule:
    """Turn one altitude profile into the ascent-then-descent segment list.

    ``alt_m`` is ``(level,)`` and **ascending in altitude**, the same convention
    :func:`windclim.stats.drift.layer_seconds` uses. Levels that sit entirely
    above burst get a zero-length segment and are dropped.
    """
    alt = np.asarray(alt_m, dtype=float).ravel()
    if alt.ndim != 1 or alt.size < 2:
        raise ValueError("alt_m must be a 1-D profile with at least two levels")
    if not np.all(np.diff(alt) > 0):
        raise ValueError("alt_m must be strictly ascending in altitude")

    mid = 0.5 * (alt[:-1] + alt[1:])
    lower = np.concatenate([alt[:1], mid])
    upper = np.concatenate([mid, alt[-1:]])
    lo = np.clip(lower, flight.launch_altitude_m, flight.burst_altitude_m)
    hi = np.clip(upper, flight.launch_altitude_m, flight.burst_altitude_m)
    thickness = np.maximum(hi - lo, 0.0)

    up = thickness / flight.ascent_rate_ms
    down = thickness / descent_rate_ms(alt, flight.descent_rate_ms)

    keep = thickness > 0.0
    k_up = np.nonzero(keep)[0]
    k_dn = k_up[::-1]

    return FlightSchedule(
        level_index=np.concatenate([k_up, k_dn]),
        seconds=np.concatenate([up[k_up], down[k_dn]]),
        z_start=np.concatenate([lo[k_up], hi[k_dn]]),
        z_end=np.concatenate([hi[k_up], lo[k_dn]]),
    )


def altitude_profile_spread(
    alt_m: NDArray[np.float64], *, burst_altitude_m: float = 30000.0
) -> dict[str, float]:
    """How much the altitude of a level varies across the columns of a region.

    ``alt_m`` is ``(level, lat, lon)``. Using one profile for the whole region
    misplaces each layer boundary by at most this much, so this is the size of
    that approximation, stated rather than asserted.

    The spread is reported against the **burst altitude**, not against the
    level's own altitude. Dividing by the level's altitude looks alarming near
    the ground -- twenty metres of spread at 1000 hPa, which sits about a hundred
    metres up, is a twenty percent "error" -- but nothing about the flight cares
    about that ratio. What the flight cares about is how far the layer edge moved
    compared with the thirty kilometres it has to climb.
    """
    alt = np.asarray(alt_m, dtype=float).reshape(alt_m.shape[0], -1)
    with np.errstate(invalid="ignore"):
        spread = np.nanmax(alt, axis=1) - np.nanmin(alt, axis=1)
        mean = np.nanmean(alt, axis=1)
    k = int(np.nanargmax(spread))
    return {
        "max_spread_m": float(spread[k]),
        "fraction_of_climb": float(spread[k] / burst_altitude_m),
        "level_of_max": k,
        "altitude_of_max_m": float(mean[k]),
    }


@dataclass
class GriddedWind:
    """A window of analyses on the model grid, ready to be sampled.

    ``u``/``v`` are ``(time, level, lat, lon)`` with the level axis **ascending in
    altitude** -- the raw files store ascending pressure, so the caller reverses
    them once. ``lat`` must be ascending and ``lon`` ascending in 0-360.
    """

    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    u: NDArray[np.float32]
    v: NDArray[np.float32]

    def __post_init__(self) -> None:
        if not np.all(np.diff(self.lat) > 0):
            raise ValueError("lat must be strictly ascending")
        if not np.all(np.diff(self.lon) > 0):
            raise ValueError("lon must be strictly ascending")
        if self.u.shape != self.v.shape:
            raise ValueError(f"u {self.u.shape} and v {self.v.shape} differ")
        if self.u.shape[2:] != (self.lat.size, self.lon.size):
            raise ValueError(
                f"u trailing shape {self.u.shape[2:]} does not match the "
                f"grid ({self.lat.size}, {self.lon.size})"
            )

    @property
    def n_times(self) -> int:
        return int(self.u.shape[0])

    def sample(
        self,
        lat: NDArray[np.float64],
        lon: NDArray[np.float64],
        level: int,
        it: NDArray[np.int64],
        w: float,
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
        """Bilinear in space, linear in time, exact in level.

        ``it`` is the index of the analysis at or before each trajectory's current
        time and ``w`` the fraction of the way to the next one, shared by the whole
        batch because every launch sits on the analysis grid and every trajectory
        is at the same elapsed time. Returns ``(u, v, inside)``; positions outside
        the grid are clamped to the edge and flagged, rather than silently
        wrapping or producing NaN.
        """
        la = np.asarray(lat, dtype=float)
        lo = np.asarray(lon, dtype=float)
        inside = (
            (la >= self.lat[0]) & (la <= self.lat[-1])
            & (lo >= self.lon[0]) & (lo <= self.lon[-1])
        )
        la = np.clip(la, self.lat[0], self.lat[-1])
        lo = np.clip(lo, self.lon[0], self.lon[-1])

        i = np.clip(np.searchsorted(self.lat, la) - 1, 0, self.lat.size - 2)
        j = np.clip(np.searchsorted(self.lon, lo) - 1, 0, self.lon.size - 2)
        fy = (la - self.lat[i]) / (self.lat[i + 1] - self.lat[i])
        fx = (lo - self.lon[j]) / (self.lon[j + 1] - self.lon[j])

        def blend(field: NDArray[np.float32]) -> NDArray[np.float64]:
            a = field[it, level, i, j]
            b = field[it, level, i, j + 1]
            c = field[it, level, i + 1, j]
            d = field[it, level, i + 1, j + 1]
            lower = a + (b - a) * fx
            upper = c + (d - c) * fx
            now = lower + (upper - lower) * fy
            if w == 0.0:
                return now.astype(float)
            a2 = field[it + 1, level, i, j]
            b2 = field[it + 1, level, i, j + 1]
            c2 = field[it + 1, level, i + 1, j]
            d2 = field[it + 1, level, i + 1, j + 1]
            lower2 = a2 + (b2 - a2) * fx
            upper2 = c2 + (d2 - c2) * fx
            nxt = lower2 + (upper2 - lower2) * fy
            return (now + (nxt - now) * w).astype(float)

        return blend(self.u), blend(self.v), inside


@dataclass
class TrajectoryResult:
    """Landing points for one variant, plus what went wrong where."""

    variant: str
    lat: NDArray[np.float64]           # (trajectory,) landing latitude
    lon: NDArray[np.float64]           # (trajectory,) landing longitude, 0-360
    dx_east_m: NDArray[np.float64]     # (trajectory,) displacement from launch
    dy_north_m: NDArray[np.float64]
    left_grid: NDArray[np.bool_]       # (trajectory,) touched the edge of the data
    flight_seconds: float
    #: ``(step, trajectory)`` positions and altitude, only when ``track=True``.
    track_lat: NDArray[np.float64] | None = None
    track_lon: NDArray[np.float64] | None = None
    track_alt: NDArray[np.float64] | None = None

    @property
    def n(self) -> int:
        return int(self.lat.size)


def _derivatives(
    u: NDArray[np.float64], v: NDArray[np.float64], lat: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Wind in m/s to rate of change of latitude and longitude in degrees per second.

    The same conversion as ``backend/bfps/core/trajectory.py:88-90``. The cosine
    is clipped well away from zero; these regions are mid-latitude, so the clip
    never binds, but a silent division by zero at a pole would be worse than an
    obviously wrong answer.
    """
    dlat = np.degrees(v / EARTH_RADIUS_M)
    coslat = np.maximum(np.cos(np.radians(lat)), 1e-6)
    dlon = np.degrees(u / (EARTH_RADIUS_M * coslat))
    return dlat, dlon


def integrate(
    wind: GriddedWind,
    schedule: FlightSchedule,
    launch_lat: NDArray[np.float64],
    launch_lon: NDArray[np.float64],
    launch_index: NDArray[np.int64],
    *,
    variant: str = "reference",
    dt: float = 120.0,
    track: bool = False,
) -> TrajectoryResult:
    """Advect a batch of payloads through ``wind`` and return where they land.

    ``launch_index`` gives each trajectory's launch analysis as an index into
    ``wind``'s time axis. Every trajectory steps through the same ``schedule``, so
    the batch stays in lockstep and the time weight is one scalar per step.

    ``dt`` is the *maximum* step; each segment is subdivided into whole steps of
    its own, so no step ever straddles a layer boundary. RK4 is used for the
    horizontal motion, matching the simulator; the vertical motion is exact within
    a segment because the vertical rate is constant there.

    ``track=True`` also keeps the whole path. It is off by default because the
    production run integrates a million trajectories and only ever looks at where
    they land; the path is wanted for the handful of flights the report draws.
    """
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
    if dt <= 0:
        raise ValueError("dt must be positive")

    freeze_time = variant in ("time_frozen", "both_frozen")
    freeze_place = variant in ("place_frozen", "both_frozen")

    lat0 = np.asarray(launch_lat, dtype=float).ravel()
    lon0 = np.asarray(launch_lon, dtype=float).ravel() % 360.0
    it0 = np.asarray(launch_index, dtype=np.int64).ravel()
    if not (lat0.size == lon0.size == it0.size):
        raise ValueError("launch_lat, launch_lon and launch_index must be the same length")
    if it0.min() < 0 or it0.max() >= wind.n_times:
        raise ValueError(
            f"launch_index out of range for {wind.n_times} analyses "
            f"({it0.min()}..{it0.max()})"
        )
    # A flight that runs past the end of the window has no wind to fly into.
    needed = int(np.ceil(schedule.total_seconds / ANALYSIS_INTERVAL_S))
    if not freeze_time and it0.max() + needed >= wind.n_times:
        span_h = schedule.total_seconds / 3600.0
        raise ValueError(
            f"a {span_h:.1f} h flight from analysis {it0.max()} needs analysis "
            f"{it0.max() + needed}, which is past the end of this window"
        )

    lat = lat0.copy()
    lon = lon0.copy()
    left = np.zeros(lat.size, dtype=bool)
    elapsed = 0.0
    path: list[tuple[NDArray, NDArray, float]] = []

    def stage(
        la: NDArray[np.float64], lo: NDArray[np.float64], level: int, tau: float
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """One RK4 stage: sample the wind, then turn it into degrees per second.

        The two freezes change only *where the wind is read from*. The conversion
        to degrees always uses the payload's real latitude, because the map factor
        is geometry, not a property of the wind field -- and because the simulator
        does the same thing (``backend/bfps/core/trajectory.py:89`` passes the
        current ``la`` even though the provider ignores it).
        """
        nonlocal left
        if freeze_place:
            sample_la, sample_lo = lat0, lon0
        else:
            sample_la, sample_lo = la, lo
        if freeze_time:
            it, w = it0, 0.0
        else:
            offset, rem = divmod(tau, ANALYSIS_INTERVAL_S)
            it = it0 + int(offset)
            w = rem / ANALYSIS_INTERVAL_S
        u, v, inside = wind.sample(sample_la, sample_lo, level, it, w)
        left |= ~inside
        return _derivatives(u, v, la)

    for seg in range(schedule.n_segments):
        duration = float(schedule.seconds[seg])
        if duration <= 0.0:
            continue
        level = int(schedule.level_index[seg])
        z0 = float(schedule.z_start[seg])
        dz = (float(schedule.z_end[seg]) - z0) / duration
        n_steps = max(int(np.ceil(duration / dt)), 1)
        h = duration / n_steps
        for step in range(n_steps):
            if track:
                path.append((lat.copy(), lon.copy(), z0 + dz * step * h))
            k1a, k1o = stage(lat, lon, level, elapsed)
            k2a, k2o = stage(lat + k1a * h / 2, lon + k1o * h / 2, level, elapsed + h / 2)
            k3a, k3o = stage(lat + k2a * h / 2, lon + k2o * h / 2, level, elapsed + h / 2)
            k4a, k4o = stage(lat + k3a * h, lon + k3o * h, level, elapsed + h)
            lat = lat + (h / 6.0) * (k1a + 2 * k2a + 2 * k3a + k4a)
            lon = lon + (h / 6.0) * (k1o + 2 * k2o + 2 * k3o + k4o)
            elapsed += h
    if track:
        path.append((lat.copy(), lon.copy(), float(schedule.z_end[-1])))

    # Displacement in metres, on the same small-angle basis as the derivatives, so
    # that a uniform wind reproduces u * T exactly rather than to within the
    # curvature of the sphere.
    dy = np.radians(lat - lat0) * EARTH_RADIUS_M
    dlon = (lon - lon0 + 180.0) % 360.0 - 180.0
    dx = np.radians(dlon) * EARTH_RADIUS_M * np.cos(np.radians(lat0))

    return TrajectoryResult(
        variant=variant,
        lat=lat,
        lon=lon % 360.0,
        dx_east_m=dx,
        dy_north_m=dy,
        left_grid=left,
        flight_seconds=schedule.total_seconds,
        track_lat=np.stack([p[0] for p in path]) if track else None,
        track_lon=np.stack([p[1] for p in path]) if track else None,
        track_alt=np.asarray([p[2] for p in path]) if track else None,
    )
