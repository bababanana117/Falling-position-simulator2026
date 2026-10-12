"""Write the canonical NetCDF product.

This file is the one thing other people will actually be handed, so it is written
to be readable on its own: CF standard names where they exist, units on
everything, and two auxiliary coordinates -- ``bin_end_day`` and ``hour_jst`` --
that put the two facts a reader would otherwise have to be told (February's half
four is shorter in leap years; 00 UTC is 09 JST) into ``ncdump -h``.

Where CF has no vocabulary, it says so rather than inventing one. There is no
``cell_methods`` for a percentile, so the percentile variables carry a plain
``comment`` instead of a plausible-looking but fictitious attribute.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from ..config import LEVEL_MIN_HPA
from .derive import add_derived

__all__ = ["ATTRS", "global_attrs", "write_netcdf"]

LICENCE = (
    "CC BY-NC-SA 4.0 - data (c) Japan Meteorological Agency, distributed by "
    "NSF NCAR GDEX (dataset d640000). NON-COMMERCIAL USE ONLY. Derived products "
    "inherit this licence and must carry it on redistribution."
)
REFERENCES = (
    "Kosaka, Y. and co-authors, 2024: The JRA-3Q Reanalysis. "
    "J. Meteor. Soc. Japan, 102, 49-109, doi:10.2151/jmsj.2024-004. "
    "Data: NSF NCAR GDEX d640000, https://gdex.ucar.edu/datasets/d640000/"
)

_PCT_COMMENT = (
    "Empirical percentile of the scalar wind speed over every analysis in the bin "
    "(numpy linear interpolation). CF defines no cell_methods for a percentile, so "
    "none is claimed here."
)

#: ``name -> (long_name, units, standard_name | None, cell_methods | None, comment | None)``
ATTRS: dict[str, tuple[str, str, str | None, str | None, str | None]] = {
    "n": ("Number of analyses in the bin", "1", None, None,
          "Bins are unequal: half 4 spans 8-10 days while halves 1-3 span 7."),
    "n_eff": ("Effective number of independent analyses", "1", None, None,
              "n (1-r1)/(1+r1) from the lag-1 autocorrelation of speed within each "
              "year's contiguous run. Six-hourly analyses are strongly correlated, "
              "so this is typically 20-40 where n is 280."),
    "lag1_autocorr": ("Lag-1 autocorrelation of wind speed", "1", None, None,
                      "Pooled across years, computed only within each year's run."),
    "u_mean": ("Mean eastward wind", "m s-1", "eastward_wind", "time: mean", None),
    "v_mean": ("Mean northward wind", "m s-1", "northward_wind", "time: mean", None),
    "u_var": ("Variance of eastward wind", "m2 s-2", None, "time: variance", None),
    "v_var": ("Variance of northward wind", "m2 s-2", None, "time: variance", None),
    "uv_cov": ("Covariance of eastward and northward wind", "m2 s-2", None, None,
               "With u_var and v_var this is the full scatter ellipse, stored "
               "losslessly; the ellipse axes are derived from it on export."),
    "u_unit_mean": ("Mean eastward component of the unit wind vector", "1", None, "time: mean",
                    "Unweighted by speed; with v_unit_mean it gives the resultant length."),
    "v_unit_mean": ("Mean northward component of the unit wind vector", "1", None, "time: mean",
                    None),
    "speed_mean": ("Mean wind speed", "m s-1", "wind_speed", "time: mean",
                   "Scalar mean of the instantaneous speeds. Always >= "
                   "speed_vector_mean."),
    "speed_vector_mean": ("Speed of the mean wind vector", "m s-1", None, None,
                          "Length of the vector mean. This is the net transport; the "
                          "difference from speed_mean is how much the wind reverses "
                          "within the bin."),
    "speed_std": ("Standard deviation of wind speed", "m s-1", None,
                  "time: standard_deviation", None),
    "speed_max": ("Maximum wind speed", "m s-1", "wind_speed", "time: maximum", None),
    "speed_se": ("Standard error of the mean wind speed", "m s-1", None, None,
                 "speed_std / sqrt(n_eff), not sqrt(n)."),
    "constancy": ("Directional constancy", "1", None, None,
                  "speed_vector_mean / speed_mean, in [0, 1]. 1 means the wind always "
                  "blows the same way; near 0 the mean direction is not meaningful and "
                  "should not be plotted."),
    "dir_vector_mean": ("Mean wind direction (from)", "degree", "wind_from_direction", None,
                        "Meteorological convention: the bearing the wind blows from, "
                        "north = 0, clockwise. Derived from u_mean and v_mean -- "
                        "directions are never averaged as angles."),
    "dir_unit_mean": ("Unit-vector mean wind direction (from)", "degree",
                      "wind_from_direction", None,
                      "As dir_vector_mean but with every analysis weighted equally "
                      "rather than by speed."),
    "resultant_length": ("Mean resultant length R", "1", None, None,
                         "0 = directions uniformly spread, 1 = all identical."),
    "circ_sd_deg": ("Circular standard deviation of direction", "degree", None, None,
                    "Mardia's sqrt(-2 ln R). NaN where R < 0.1, because for a "
                    "near-uniform or bimodal direction a spread is not meaningful."),
    "ellipse_major": ("Semi-major axis of the 1-sigma wind scatter ellipse", "m s-1", None, None,
                      "Assumes the (u, v) scatter is bivariate normal, which fails "
                      "during the stratospheric reversal seasons."),
    "ellipse_minor": ("Semi-minor axis of the 1-sigma wind scatter ellipse", "m s-1", None, None,
                      None),
    "ellipse_angle_deg": ("Orientation of the scatter ellipse", "degree", None, None,
                          "Counter-clockwise from east, in [0, 180)."),
    "shear_mag": ("Magnitude of the vertical shear of the mean wind", "m s-1 km-1", None, None,
                  "|dV/dz| from the vector means, so a layer where the wind turns at "
                  "constant speed still shows shear."),
    "z_mean_gpm": ("Mean geopotential height", "gpm", "geopotential_height", "time: mean",
                   "Geopotential metres, not geometric metres."),
    "z_std_gpm": ("Standard deviation of geopotential height", "gpm", None,
                  "time: standard_deviation", None),
    "alt_geom_mean_m": ("Mean geometric altitude", "m", "altitude", None,
                        "Converted from z_mean_gpm with latitude-dependent gravity "
                        "(Somigliana) and effective Earth radius (List 1968). About "
                        "+140 m at 30 km, 45 N."),
    "alt_geom_mean_km": ("Mean geometric altitude", "km", "altitude", None, None),
    "gauss_weight": ("Gaussian quadrature weight", "1", None, None,
                     "From the source grid; the correct weighting for an area mean."),
    "bin_end_day": ("Last day of month in the bin", "1", None, None,
                     "Maximum across the years used, so February's last bin "
                     "shows 29 rather than 28."),
    "hour_jst": ("Analysis hour in Japan Standard Time", "1", None, None,
                 "UTC + 9. The 18 UTC analysis is 03 JST on the following day."),
    "drift_east_m": ("Mean eastward displacement of a nominal flight", "m", None, None,
                     "Horizontal displacement is linear in the wind profile, so the "
                     "mean of the displacements equals the displacement of the mean "
                     "wind. See the flight_* global attributes for the flight."),
    "drift_north_m": ("Mean northward displacement of a nominal flight", "m", None, None,
                      None),
    "drift_east_var": ("Variance of the eastward displacement", "m2", None, None,
                       "Computed per analysis, so the landing spread is measured "
                       "rather than inferred from level-to-level correlations."),
    "drift_north_var": ("Variance of the northward displacement", "m2", None, None, None),
    "drift_cov": ("Covariance of the eastward and northward displacement", "m2", None, None,
                  "With the two variances this gives the landing ellipse."),
    "drift_dist_mean_km": ("Mean flight distance", "km", None, None,
                           "Mean of the distances, which exceeds the distance of the "
                           "mean landing point whenever the direction varies."),
    "drift_dist_p50_km": ("Median flight distance", "km", None, None, None),
    "drift_dist_p90_km": ("90th percentile of flight distance", "km", None, None,
                          "The bad days. A mean of 150 km with a p90 of 400 km is a "
                          "different operational problem from a mean of 150 km alone."),
    "drift_dist_p95_km": ("95th percentile of flight distance", "km", None, None, None),
    "drift_dist_max_km": ("Maximum flight distance", "km", None, None, None),
    "drift_bearing_deg": ("Bearing the payload travels towards", "degree", None, None,
                          "Compass bearing of travel, north = 0, clockwise. This is the "
                          "OPPOSITE convention to dir_vector_mean, which names the "
                          "direction the wind comes from: a westerly is 270 but carries "
                          "the payload towards 90."),
    "drift_flight_time_s": ("Flight time implied by the flight model", "s", None, None, None),
    "drift_n": ("Analyses used for the drift statistics", "1", None, None, None),
}


def global_attrs(region: str, cfg, *, extra: dict | None = None) -> dict:
    years = list(cfg.years)
    attrs = {
        "Conventions": "CF-1.10",
        "title": (
            f"JRA-3Q wind climatology by month-{cfg.scheme.name}, altitude "
            f"and location ({region})"
        ),
        "summary": (
            "Statistics of the horizontal wind on isobaric surfaces over "
            f"{region}, binned by "
            f"{_bin_definition(cfg.scheme.starts, cfg.scheme.short)} and computed "
            f"from every 6-hourly JRA-3Q analysis in {years[0]}-{years[-1]}. "
            "Intended for planning high-altitude balloon flights: what the wind "
            "usually does at a given place, altitude and time of year."
        ),
        "institution": "Derived locally; source data from the Japan Meteorological Agency",
        "source": f"JRA-3Q reanalysis (JMA), product {cfg.product}",
        "references": REFERENCES,
        "license": LICENCE,
        "history": (
            f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} "
            f"created by windclim: {' '.join(sys.argv)}"
        ),
        "bin_definition": _bin_definition(cfg.scheme.starts, cfg.scheme.short),
        "date_convention": cfg.date_convention,
        "period": f"{years[0]}-{years[-1]}",
        "level_min_hpa": LEVEL_MIN_HPA,
        "date_created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "product_version": "1",
    }
    attrs.update(extra or {})
    return attrs


def _apply_attrs(ds: xr.Dataset) -> xr.Dataset:
    for name, (long_name, units, std, cell, comment) in ATTRS.items():
        for key in (name, f"hr_{name}"):
            if key not in ds.variables:
                continue
            a = ds[key].attrs
            a["long_name"] = long_name if key == name else f"{long_name} (by analysis hour)"
            a["units"] = units
            if std:
                a["standard_name"] = std
            if cell:
                a["cell_methods"] = cell
            if comment:
                a["comment"] = comment
    for name in ds.variables:
        s = str(name)
        if s.startswith("speed_p"):
            ds[name].attrs.update(
                {
                    "long_name": f"{s[7:].lstrip('0')}th percentile of wind speed",
                    "units": "m s-1",
                    "standard_name": "wind_speed",
                    "comment": _PCT_COMMENT,
                }
            )
        elif s.startswith("exceed_gt"):
            thr = s[len("exceed_gt"):]
            ds[name].attrs.update(
                {
                    "long_name": f"Fraction of analyses with wind speed above {thr} m/s",
                    "units": "1",
                    "comment": "Operational risk measure: the mean alone does not "
                               "decide whether a flight is recoverable.",
                }
            )

    ds["level"].attrs.update(
        {"standard_name": "air_pressure", "units": "hPa", "long_name": "isobaric surface",
         "positive": "down", "axis": "Z"}
    )
    ds["lat"].attrs.update(
        {"standard_name": "latitude", "units": "degrees_north", "axis": "Y"}
    )
    ds["lon"].attrs.update(
        {"standard_name": "longitude", "units": "degrees_east", "axis": "X",
         "comment": "-180..180, matching the web frontend's convention."}
    )
    ds["month"].attrs.update({"long_name": "calendar month", "units": "1"})
    ds["bin"].attrs.update(
        {"long_name": ds.attrs.get("bin_scheme", "bin") + " of month", "units": "1",
         "description": _bin_definition(
             ds.attrs.get("bin_start_days", []), ds.attrs.get("bin_short", [])
         )}
    )
    if "level_low" in ds.coords:
        ds["level_low"].attrs.update(
            {"standard_name": "air_pressure", "units": "hPa", "positive": "down",
             "long_name": "isobaric surface (diurnal sub-product)"}
        )
    if "hour" in ds.coords:
        ds["hour"].attrs.update({"long_name": "analysis hour, UTC", "units": "1"})
    return ds


def _bin_definition(starts, short) -> str:
    """Describe the binning in words, from the scheme the data was built under.

    Built from the actual start days rather than from a module constant: the
    file has to describe the numbers inside it, not whatever scheme the code
    was last configured for.
    """
    starts = [int(x) for x in starts]
    short = [str(x) for x in short]
    if not starts:
        return "day-of-month fixed bins; see the bin coordinate"
    parts = []
    for i, start in enumerate(starts):
        name = short[i] if i < len(short) else f"B{i + 1}"
        end = "end of month" if i + 1 == len(starts) else str(starts[i + 1] - 1)
        parts.append(f"{name}={start}-{end}")
    return "day-of-month fixed: " + ", ".join(parts)


def write_netcdf(
    ds: xr.Dataset,
    path: Path,
    region: str,
    cfg,
    *,
    derived: bool = True,
    complevel: int = 4,
) -> Path:
    """Write the dataset, adding derived fields, CF attributes and provenance."""
    out = add_derived(ds) if derived else ds.copy()
    out = _apply_attrs(out)
    out.attrs.update(global_attrs(region, cfg))

    encoding = {}
    for name, da in out.variables.items():
        if da.dtype.kind == "f":
            encoding[name] = {
                "zlib": True, "complevel": complevel, "shuffle": True,
                "dtype": "float32", "_FillValue": np.float32(np.nan),
            }
        elif da.dtype.kind in "iu" and da.ndim > 1:
            encoding[name] = {"zlib": True, "complevel": complevel, "shuffle": True}

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".nc.part")
    out.to_netcdf(tmp, engine="netcdf4", format="NETCDF4", encoding=encoding)
    tmp.replace(path)
    return path
