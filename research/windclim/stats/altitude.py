"""Pressure levels, geopotential height and geometric altitude.

Three different vertical coordinates appear in this pipeline and confusing them
is a classic error, so the naming rule is strict:

``p_hpa``
    Pressure. What the data is actually indexed by.
``*_gpm``
    **Geopotential** height in geopotential metres, which is what the ``hgt``
    variable stores. It measures work done against gravity, not distance.
``*_geom_m``
    **Geometric** altitude in metres. This is the height a balloon's GPS
    reports, and the axis a human reads.

No variable in this package is ever called just ``height`` or ``alt``.

The geopotential-to-geometric conversion accounts for gravity varying with
latitude (Somigliana) and with the Earth's oblateness (List 1968). The
correction is about +140 m at 30 km and 45 N -- small, but the same order as the
vertical spacing between the upper pressure levels, so it is not noise.

``isa_altitude_from_pressure`` is a fallback only, mirroring
``backend/bfps/core/atmosphere.py``. The real ``hgt`` field is always preferred:
it is the actual observed-and-analysed height, whereas ISA is an idealisation
that ignores season, latitude and weather entirely. Comparing the two is a
useful check on the existing simulator (figure F10).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "G0",
    "earth_radius_effective",
    "geometric_to_geopotential",
    "geopotential_to_geometric",
    "gravity_at_latitude",
    "isa_altitude_from_pressure",
    "pressure_isa",
]

G0 = 9.80665  # standard gravity, m/s^2 -- the definition of a geopotential metre

# ISA constants and layers, matching backend/bfps/core/atmosphere.py.
R_AIR = 287.05287
P0_PA = 101325.0
_ISA_LAYERS = (
    (0.0, 288.15, -0.0065),
    (11000.0, 216.65, 0.0),
    (20000.0, 216.65, 0.001),
    (32000.0, 228.65, 0.0028),  # extrapolated above 32 km
)


def gravity_at_latitude(lat_deg: ArrayLike) -> NDArray[np.float64]:
    """Normal gravity at mean sea level, m/s^2 (Somigliana approximation)."""
    phi = np.radians(np.asarray(lat_deg, dtype=float))
    s1 = np.sin(phi) ** 2
    s2 = np.sin(2.0 * phi) ** 2
    return 9.780325 * (1.0 + 0.0053024 * s1 - 0.0000058 * s2)


def earth_radius_effective(lat_deg: ArrayLike) -> NDArray[np.float64]:
    """Effective Earth radius for the height conversion, m (List 1968)."""
    phi = np.radians(np.asarray(lat_deg, dtype=float))
    return 6378137.0 / (1.006803 - 0.006706 * np.sin(phi) ** 2)


def geopotential_to_geometric(z_gpm: ArrayLike, lat_deg: ArrayLike) -> NDArray[np.float64]:
    """Geopotential height [gpm] -> geometric altitude [m]."""
    z = np.asarray(z_gpm, dtype=float)
    g = gravity_at_latitude(lat_deg)
    r = earth_radius_effective(lat_deg)
    return r * z * G0 / (g * r - z * G0)


def geometric_to_geopotential(z_geom_m: ArrayLike, lat_deg: ArrayLike) -> NDArray[np.float64]:
    """Geometric altitude [m] -> geopotential height [gpm]. Inverse of the above."""
    z = np.asarray(z_geom_m, dtype=float)
    g = gravity_at_latitude(lat_deg)
    r = earth_radius_effective(lat_deg)
    return g * r * z / (G0 * (r + z))


def _isa_base_pressures() -> list[float]:
    out = [P0_PA]
    for i in range(1, len(_ISA_LAYERS)):
        h_b, t_b, lapse = _ISA_LAYERS[i - 1]
        h_top = _ISA_LAYERS[i][0]
        p_b = out[-1]
        if lapse == 0.0:
            out.append(p_b * float(np.exp(-G0 * (h_top - h_b) / (R_AIR * t_b))))
        else:
            out.append(p_b * float((1 + lapse * (h_top - h_b) / t_b) ** (-G0 / (R_AIR * lapse))))
    return out


_ISA_BASE_P = _isa_base_pressures()


def _layer_index_by_altitude(h: NDArray[np.float64]) -> NDArray[np.int_]:
    idx = np.zeros(h.shape, dtype=int)
    for i in range(1, len(_ISA_LAYERS)):
        idx[h >= _ISA_LAYERS[i][0]] = i
    return idx


def _layer_index_by_pressure(p_pa: NDArray[np.float64]) -> NDArray[np.int_]:
    idx = np.zeros(p_pa.shape, dtype=int)
    for i in range(1, len(_ISA_LAYERS)):
        idx[p_pa <= _ISA_BASE_P[i]] = i
    return idx


def _unwrap(out: NDArray[np.float64], like: NDArray[np.float64]) -> NDArray[np.float64]:
    """Give a scalar back for a scalar argument, as numpy ufuncs do."""
    return out.reshape(like.shape)[()]


def pressure_isa(alt_m: ArrayLike) -> NDArray[np.float64]:
    """ISA pressure [Pa] at a geopotential altitude [m]."""
    arg = np.asarray(alt_m, dtype=float)
    h = np.atleast_1d(arg)
    out = np.empty_like(h)
    for i in np.unique(_layer_index_by_altitude(h)):
        h_b, t_b, lapse = _ISA_LAYERS[i]
        p_b = _ISA_BASE_P[i]
        m = _layer_index_by_altitude(h) == i
        dh = h[m] - h_b
        if lapse == 0.0:
            out[m] = p_b * np.exp(-G0 * dh / (R_AIR * t_b))
        else:
            out[m] = p_b * (1 + lapse * dh / t_b) ** (-G0 / (R_AIR * lapse))
    return _unwrap(out, arg)


def isa_altitude_from_pressure(p_hpa: ArrayLike) -> NDArray[np.float64]:
    """ISA altitude [m] from pressure [hPa], inverted analytically per layer.

    Fallback only. ``backend/bfps/core/atmosphere.py:82`` does the same inversion
    by bisection; the answers agree to well under a millimetre.
    """
    arg = np.asarray(p_hpa, dtype=float)
    p = np.atleast_1d(arg) * 100.0
    idx = _layer_index_by_pressure(p)
    out = np.empty_like(p)
    for i in np.unique(idx):
        h_b, t_b, lapse = _ISA_LAYERS[i]
        p_b = _ISA_BASE_P[i]
        m = idx == i
        if lapse == 0.0:
            out[m] = h_b - R_AIR * t_b / G0 * np.log(p[m] / p_b)
        else:
            out[m] = h_b + t_b / lapse * ((p[m] / p_b) ** (-R_AIR * lapse / G0) - 1.0)
    return _unwrap(out, arg)
