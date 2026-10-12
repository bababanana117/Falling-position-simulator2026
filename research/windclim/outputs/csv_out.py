"""Six small CSVs that a person can actually read.

The full grid is a million rows and thirty columns; as text that is about 200 MB
and nobody will ever open it. Parquet already covers that case. What is missing
from both is a handful of short tables aimed at specific questions, so those are
what gets written here -- and committed to git, since they are the part a reader
of the report might want to check.

On launch sites: the nearest grid cell is used, never an interpolation between
cells. Interpolating a percentile gives a number that is not a percentile of
anything, and interpolating a covariance is worse. The distance from the site to
the cell centre is reported in ``region_grid_*.csv`` so the approximation is
visible rather than hidden.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ..config import REPO_ROOT
from ..grid import nearest_cell
from ..regions import REGIONS
from ..stats.spatial import area_mean
from .derive import add_derived

__all__ = [
    "FLIGHT_LAYERS",
    "load_sites",
    "region_sites",
    "write_csv_tables",
]

SITES_JSON = REPO_ROOT / "frontend" / "public" / "sites.json"

#: The site whose column the per-site tables and the report quote, by region.
#: Named rather than taken as the first row of ``sites.json``: the file lists
#: over a hundred parks in Tokachi and the order they happen to appear in is not
#: a decision anyone made. Naming it here makes the choice reviewable, and a
#: rename in the JSON becomes a loud failure rather than a silent change of
#: which site the report is about.
REFERENCE_SITE: dict[str, str] = {"hokkaido": "VOISING", "ehime": "南レク御荘公園"}

#: Layers that mean something to a balloon flight, in km of geometric altitude.
FLIGHT_LAYERS: tuple[tuple[str, float, float], ...] = (
    ("0-2 km surface/boundary layer", 0.0, 2.0),
    ("2-6 km lower troposphere", 2.0, 6.0),
    ("6-12 km jet", 6.0, 12.0),
    ("12-20 km lower stratosphere", 12.0, 20.0),
    ("20-30 km float/burst", 20.0, 30.0),
    ("30-40 km upper stratosphere", 30.0, 40.0),
)

_SITE_COLUMNS = [
    "month", "bin", "level_hpa", "alt_km", "n", "n_eff",
    "speed_mean", "speed_p50", "speed_p90", "dir_vector_mean", "constancy", "shear_mag",
]


def load_sites(path: Path = SITES_JSON) -> pd.DataFrame:
    """Launch sites from the web app's own ``sites.json``."""
    if not Path(path).exists():
        return pd.DataFrame(columns=["group", "name", "lat", "lon", "altitude_m"])
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = [
        {
            "group": group,
            "name": name,
            "lat": float(site["latitude"]),
            "lon": float(site["longitude"]),
            "altitude_m": float(site.get("altitude", 0.0)),
        }
        for group, sites in raw.items()
        for name, site in sites.items()
    ]
    return pd.DataFrame(rows)


def region_sites(region: str, path: Path = SITES_JSON) -> pd.DataFrame:
    """Sites that fall inside a region's box.

    Wakayama has no entry in ``sites.json``, so its tables are region-wide only.
    That is a deliberate consequence rather than an oversight: inventing a
    reference point would put a spurious precision into the output.
    """
    box = REGIONS[region]
    sites = load_sites(path)
    if sites.empty:
        return sites
    inside = sites.apply(lambda r: box.contains(r["lat"], r["lon"]), axis=1)
    return sites[inside].reset_index(drop=True)


def _area_mean(ds: xr.Dataset, name: str) -> np.ndarray:
    return area_mean(ds, name).values


def _reference_site(sites: pd.DataFrame, region: str):
    """The row of ``sites`` the per-site outputs describe.

    Looks up :data:`REFERENCE_SITE` by region. A name that is not in the file is
    an error rather than a quiet fallback: the report names the site in its
    text, so silently describing a different one would make the prose wrong
    without anything failing.
    """
    want = REFERENCE_SITE.get(region)
    if want is None:
        return sites.iloc[0]
    match = sites[sites["name"] == want]
    if match.empty:
        raise ValueError(
            f"reference site {want!r} for region {region!r} is not in "
            f"{SITES_JSON.name}; found {sorted(sites['name'])[:5]}..."
        )
    return match.iloc[0]


def _site_frame(ds: xr.Dataset, i: int, j: int) -> pd.DataFrame:
    sub = ds.isel(lat=i, lon=j)
    frames = []
    for m in sub["month"].values:
        for w in sub["bin"].values:
            cell = sub.sel(month=m, bin=w)
            frames.append(
                pd.DataFrame(
                    {
                        "month": int(m),
                        "bin": int(w),
                        "level_hpa": cell["level"].values,
                        "alt_km": cell.get("alt_geom_mean_km", cell["speed_mean"] * np.nan).values,
                        "n": cell["n"].values,
                        "n_eff": cell["n_eff"].values,
                        "speed_mean": cell["speed_mean"].values,
                        "speed_p50": cell["speed_p50"].values,
                        "speed_p90": cell["speed_p90"].values,
                        "dir_vector_mean": cell["dir_vector_mean"].values,
                        "constancy": cell["constancy"].values,
                        "shear_mag": cell.get(
                            "shear_mag", cell["speed_mean"] * np.nan
                        ).values,
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)[_SITE_COLUMNS]


def _layer_summary(ds: xr.Dataset, per_cell: pd.DataFrame | None = None) -> pd.DataFrame:
    """Collapse the level axis into the six flight-relevant layers."""
    if per_cell is None:
        alt_km = _area_mean(ds, "alt_geom_mean_km")
        frame = pd.DataFrame(
            {
                "month": np.repeat(ds["month"].values, ds.sizes["bin"] * ds.sizes["level"]),
                "bin": np.tile(np.repeat(ds["bin"].values, ds.sizes["level"]),
                                ds.sizes["month"]),
                "level_hpa": np.tile(ds["level"].values, ds.sizes["month"] * ds.sizes["bin"]),
                "alt_km": alt_km.ravel(),
                "speed_mean": _area_mean(ds, "speed_mean").ravel(),
                "speed_p90": _area_mean(ds, "speed_p90").ravel(),
                "constancy": _area_mean(ds, "constancy").ravel(),
                "shear_mag": _area_mean(ds, "shear_mag").ravel(),
            }
        )
    else:
        frame = per_cell.copy()

    rows = []
    for label, lo, hi in FLIGHT_LAYERS:
        sel = frame[(frame["alt_km"] >= lo) & (frame["alt_km"] < hi)]
        if sel.empty:
            continue
        grouped = sel.groupby(["month", "bin"], as_index=False).agg(
            n_levels=("level_hpa", "count"),
            speed_mean=("speed_mean", "mean"),
            speed_p90=("speed_p90", "max"),
            constancy=("constancy", "mean"),
            shear_mag=("shear_mag", "max"),
        )
        grouped.insert(2, "layer", label)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def _drift_table(ds: xr.Dataset) -> pd.DataFrame:
    """Region-mean landing displacement per (month, half) -- 48 rows.

    The single table a launch planner would read: how far, which way, and how bad
    the bad days are, for every half of the year.
    """
    rows = []
    for mi, month in enumerate(ds["month"].values):
        for wi, half in enumerate(ds["bin"].values):
            cell = ds.isel(month=mi, bin=wi)
            east = float(np.nanmean(cell["drift_east_m"].values)) / 1000.0
            north = float(np.nanmean(cell["drift_north_m"].values)) / 1000.0
            rows.append(
                {
                    "month": int(month),
                    "bin": int(half),
                    "east_km": east,
                    "north_km": north,
                    "bearing_deg": float((np.degrees(np.arctan2(east, north)) + 360.0) % 360.0),
                    "dist_mean_km": float(np.nanmean(cell["drift_dist_mean_km"].values)),
                    "dist_p50_km": float(np.nanmean(cell["drift_dist_p50_km"].values)),
                    "dist_p90_km": float(np.nanmean(cell["drift_dist_p90_km"].values)),
                    "dist_max_km": float(np.nanmax(cell["drift_dist_max_km"].values)),
                    "flight_time_min": float(
                        np.nanmean(cell["drift_flight_time_s"].values)
                    ) / 60.0,
                }
            )
    return pd.DataFrame(rows)


def _best_halves(ds: xr.Dataset) -> pd.DataFrame:
    """Rank the 48 half bins by how gentle the column is, 0-30 km.

    The objective is stated rather than optimal: the area-weighted mean wind speed
    integrated over the flight column, with directional constancy as the
    tie-breaker (a steady wind is easier to plan around than a fickle one of the
    same strength). Anyone who disagrees can re-rank the Parquet.
    """
    alt = _area_mean(ds, "alt_geom_mean_km")
    spd = _area_mean(ds, "speed_mean")
    con = _area_mean(ds, "constancy")
    rows = []
    for mi, month in enumerate(ds["month"].values):
        for wi, half in enumerate(ds["bin"].values):
            band = (alt[mi, wi] >= 0.0) & (alt[mi, wi] <= 30.0)
            if not band.any():
                continue
            rows.append(
                {
                    "month": int(month),
                    "bin": int(half),
                    "mean_speed_0_30km": float(np.nanmean(spd[mi, wi][band])),
                    "max_speed_0_30km": float(np.nanmax(spd[mi, wi][band])),
                    "mean_constancy_0_30km": float(np.nanmean(con[mi, wi][band])),
                }
            )
    out = pd.DataFrame(rows).sort_values(
        ["mean_speed_0_30km", "mean_constancy_0_30km"], ascending=[True, False]
    )
    out.insert(0, "rank", range(1, len(out) + 1))
    return out.reset_index(drop=True)


def write_csv_tables(
    ds: xr.Dataset,
    out_dir: Path,
    region: str,
    cfg,
    *,
    manifest: list[dict] | None = None,
    derived: bool = True,
    suffix: str = "",
) -> dict[str, Path]:
    """Write the curated tables and return ``{name: path}``.

    ``suffix`` is appended to the file names, not to ``region``: the region name
    is a key into :data:`windclim.regions.REGIONS` and has to stay valid, while
    the file name is what keeps two bin schemes from overwriting each other.
    """
    full = add_derived(ds) if derived else ds
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, frame: pd.DataFrame) -> None:
        path = out_dir / name
        frame.to_csv(path, index=False, float_format="%.4g")
        written[name] = path

    _write(f"bin_calendar{suffix}.csv", pd.DataFrame(cfg.scheme.calendar_rows(cfg.years)))

    lat = full["lat"].values
    lon = full["lon"].values
    grid_rows = [
        {"lat": float(a), "lon": float(o)} for a in lat for o in lon
    ]
    grid = pd.DataFrame(grid_rows)
    sites = region_sites(region)
    site_rows = []
    for _, s in sites.iterrows():
        i, j, off = nearest_cell(lat, lon, s["lat"], s["lon"])
        site_rows.append(
            {
                "site": s["name"],
                "site_lat": s["lat"],
                "site_lon": s["lon"],
                "cell_lat": float(lat[i]),
                "cell_lon": float(lon[j]),
                "offset_km": round(off, 2),
            }
        )
    grid.attrs["region"] = region
    _write(f"region_grid_{region}{suffix}.csv", grid)
    if site_rows:
        _write(f"region_sites_{region}{suffix}.csv", pd.DataFrame(site_rows))

    per_cell = None
    if not sites.empty:
        s = _reference_site(sites, region)
        i, j, _ = nearest_cell(lat, lon, s["lat"], s["lon"])
        per_cell = _site_frame(full, i, j)
        _write(f"site_profile_{region}{suffix}.csv", per_cell)

    _write(f"layer_summary_{region}{suffix}.csv", _layer_summary(full, per_cell))
    if "drift_dist_mean_km" in full:
        _write(f"drift_{region}{suffix}.csv", _drift_table(full))
    _write(f"best_launch_halves_{region}{suffix}.csv", _best_halves(full))

    if manifest is not None:
        inv = pd.DataFrame(
            [
                {
                    "url": r.get("url"),
                    "var": r.get("var"),
                    "status": r.get("status"),
                    "nbytes": r.get("nbytes"),
                    "n_times": r.get("n_times"),
                    "elapsed_s": r.get("elapsed_s"),
                    "fetched_at": r.get("started_at"),
                }
                for r in manifest
            ]
        )
        _write("data_inventory.csv", inv)

    return written
