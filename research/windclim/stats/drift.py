"""Where a balloon launched into this wind would actually land.

The rest of this package describes the wind. This module answers the question the
project exists for: *if we launch from here, in this half, how far and which way
does the payload go?*

The flight model is the one the simulator already uses
(``backend/bfps/core/trajectory.py``): the balloon rises at a constant rate to its
burst altitude, then falls at a sea-level-equivalent rate scaled by air density,
and the horizontal motion is pure advection with no inertia. Under that model the
horizontal displacement is

.. math::
   \\Delta x = \\sum_k u_k\\, T_k, \\qquad \\Delta y = \\sum_k v_k\\, T_k

where ``T_k`` is the time spent inside level *k*'s layer, going up and coming back
down. ``T_k`` depends only on the layer thickness and the descent law, not on the
wind, so the displacement is **linear in the wind profile**.

That linearity is what makes this worth doing. It means the displacement can be
computed for every single analysis and the statistics taken afterwards -- the
landing spread is measured, not inferred from an assumption about how the levels
correlate with each other. (It also means the drift of the mean wind equals the
mean of the drifts, which is not generally true of things computed from a
climatology and is worth saying out loud.)

Two limitations follow from the model rather than from the data, and both match
what the simulator already assumes:

* the wind profile is frozen in space and time for the whole flight, exactly as
  ``wind.py`` freezes the profile fetched at the launch point;
* the burst altitude is fixed, so this is the spread due to the *wind* alone,
  with none of the spread that comes from the balloon itself bursting early or
  late.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .altitude import R_AIR, pressure_isa

__all__ = [
    "FlightProfile",
    "descent_rate_ms",
    "displacements",
    "layer_seconds",
]

#: ISA sea-level density, matching ``backend/bfps/core/atmosphere.py``.
RHO0_ISA = 1.2250


@dataclass(frozen=True)
class FlightProfile:
    """A nominal flight. The defaults are a typical latex-balloon sounding.

    These are not tuned to any particular payload: the point of the drift maps is
    to compare places and halves against each other, and any fixed flight does
    that. A real campaign should re-run with its own numbers.
    """

    ascent_rate_ms: float = 5.0
    burst_altitude_m: float = 30000.0
    descent_rate_ms: float = 6.0          # sea-level equivalent
    launch_altitude_m: float = 0.0

    def label(self) -> str:
        return (
            f"上昇 {self.ascent_rate_ms:.0f} m/s, 破裂 {self.burst_altitude_m / 1000:.0f} km, "
            f"降下 {self.descent_rate_ms:.0f} m/s (海面等価)"
        )


def _density_isa(z_m: NDArray[np.float64]) -> NDArray[np.float64]:
    """ISA density at a geopotential altitude, in kg/m^3."""
    p = pressure_isa(z_m)
    # T from the same layer model the pressure came from.
    from .altitude import _ISA_LAYERS, _layer_index_by_altitude  # noqa: PLC0415

    h = np.atleast_1d(np.asarray(z_m, dtype=float))
    idx = _layer_index_by_altitude(h)
    t = np.empty_like(h)
    for i in np.unique(idx):
        h_b, t_b, lapse = _ISA_LAYERS[i]
        m = idx == i
        t[m] = t_b + lapse * (h[m] - h_b)
    return (np.atleast_1d(p) / (R_AIR * t)).reshape(np.shape(z_m))


def descent_rate_ms(z_m, sea_level_rate: float) -> NDArray[np.float64]:
    """Descent speed at altitude, from the sea-level-equivalent rate.

    ``v(z) = v_0 sqrt(rho_0 / rho(z))`` -- the same law as
    ``backend/bfps/core/trajectory.py:52``. Thin air means a fast fall, which is
    why the payload spends so little time in the stratosphere on the way down and
    why the descent leg contributes less drift than its altitude range suggests.
    """
    rho = np.maximum(_density_isa(np.maximum(np.asarray(z_m, dtype=float), 0.0)), 1e-4)
    return sea_level_rate * np.sqrt(RHO0_ISA / rho)


def layer_seconds(alt_m: NDArray[np.float64], flight: FlightProfile) -> NDArray[np.float64]:
    """Seconds spent inside each level's layer, ascent plus descent.

    ``alt_m`` is the altitude of each pressure level, shaped ``(level, ...)`` and
    **ascending in altitude**. Layer edges are the midpoints between neighbouring
    levels, clipped to the launch altitude and the burst altitude, so a level that
    sits entirely above burst contributes nothing.
    """
    alt = np.asarray(alt_m, dtype=float)
    if alt.ndim == 0:
        raise ValueError("alt_m must have a level axis")
    n = alt.shape[0]
    if n < 2:
        raise ValueError("need at least two levels to define layer thicknesses")

    mid = 0.5 * (alt[:-1] + alt[1:])
    lower = np.concatenate([alt[:1], mid], axis=0)
    upper = np.concatenate([mid, alt[-1:]], axis=0)

    lo = np.clip(lower, flight.launch_altitude_m, flight.burst_altitude_m)
    hi = np.clip(upper, flight.launch_altitude_m, flight.burst_altitude_m)
    thickness = np.maximum(hi - lo, 0.0)

    up = thickness / flight.ascent_rate_ms
    down = thickness / descent_rate_ms(alt, flight.descent_rate_ms)
    return up + down


def displacements(
    u: NDArray[np.float64],
    v: NDArray[np.float64],
    alt_m: NDArray[np.float64],
    flight: FlightProfile,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Horizontal displacement in metres for each sample.

    ``u``/``v`` are ``(time, level, lat, lon)``; ``alt_m`` is ``(level, lat, lon)``
    ascending in altitude. Returns ``(dx_east, dy_north)`` shaped
    ``(time, lat, lon)``.
    """
    weights = layer_seconds(alt_m, flight)          # (level, lat, lon)
    w = weights[None, ...]
    with np.errstate(invalid="ignore"):
        dx = np.nansum(np.asarray(u, dtype=float) * w, axis=1)
        dy = np.nansum(np.asarray(v, dtype=float) * w, axis=1)
    # A column with no usable wind at all should be NaN, not zero.
    any_valid = np.isfinite(np.asarray(u, dtype=float)).any(axis=1)
    return np.where(any_valid, dx, np.nan), np.where(any_valid, dy, np.nan)


def flight_seconds(alt_m: NDArray[np.float64], flight: FlightProfile) -> NDArray[np.float64]:
    """Total flight time implied by the model, summed over the layers."""
    return layer_seconds(alt_m, flight).sum(axis=0)


def travel_bearing_deg(dx: NDArray[np.float64], dy: NDArray[np.float64]) -> NDArray[np.float64]:
    """Compass bearing the payload travels *towards*, north = 0, clockwise.

    Note the convention is the opposite of ``dir_vector_mean`` elsewhere in this
    package, which follows the meteorological habit of naming the direction the
    wind comes *from*. A westerly wind is 270 degrees but carries the payload
    towards 90. Mixing the two up would put every landing site on the wrong side
    of the launch point, so the two are named differently everywhere.
    """
    return (np.degrees(np.arctan2(np.asarray(dx, dtype=float),
                                  np.asarray(dy, dtype=float))) + 360.0) % 360.0
