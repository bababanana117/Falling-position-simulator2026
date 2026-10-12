"""Does the simulator match reality, and does the answer depend on the season?

The climatology chapters say where the wind usually goes. This one asks a
different question, and it is the question a launch campaign actually has:
**when is the prediction most likely to come true?**

"Come true" has to be pinned to something measurable. Four things can make a
predicted landing point wrong, and only three of them can be measured from a
reanalysis:

1. the simulator freezes the wind at the launch **time** -- measurable here;
2. the simulator freezes the wind at the launch **place** -- measurable here;
3. the launch slips by a few hours and the wind has moved on -- measurable here;
4. the forecast the simulator was given was wrong in the first place -- **not**
   measurable here, because that needs an archive of past forecasts, not an
   archive of past weather.

The fourth is likely the largest of the four in practice. Leaving it out is a
limit of the data, not a claim that it is small, and the report says so where the
numbers are quoted. What the first three give is a floor: even with a perfect
forecast, the simulator would still be wrong by this much.

The first two are measured by flying the payload through the real field and
comparing against the same flight with one or both freezes applied -- see
:mod:`windclim.stats.trajectory`. The third needs no trajectory at all, only the
per-analysis displacement the feature table already holds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ..grid import bbox_slices
from ..regions import MASTER, REGIONS
from ..stats import trajectory as tj
from ..stats import variability as vb
from ..stats.aggregate import AggregateConfig, load_window
from ..stats.altitude import geopotential_to_geometric
from ..timebins import SEASON_ORDER, season_of

__all__ = [
    "FidelityResult",
    "example_tracks",
    "exclusion_bias",
    "run_fidelity",
    "run_trajectory_errors",
    "run_variability",
    "write_fidelity_tables",
    "format_fidelity",
]

log = logging.getLogger(__name__)

#: Variants compared against the reference. ``both_frozen`` is the live
#: simulator; the other two isolate one freeze each so the report can say which
#: of the two is worth fixing.
COMPARED: tuple[str, ...] = ("time_frozen", "place_frozen", "both_frozen")

JP_VARIANT = {
    "reference": "基準（固定なし）",
    "time_frozen": "時刻のみ固定",
    "place_frozen": "地点のみ固定",
    "both_frozen": "両方固定（現行シミュレータ）",
}


@dataclass
class FidelityResult:
    region: str
    lag_wind: pd.DataFrame
    autocorr: pd.DataFrame
    decorrelation: pd.DataFrame
    direction: pd.DataFrame
    variance: pd.DataFrame
    slip: pd.DataFrame
    error: pd.DataFrame = field(default_factory=pd.DataFrame)
    ranking: pd.DataFrame = field(default_factory=pd.DataFrame)
    headline: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# A and B: everything that is a reduction of the feature table.
# --------------------------------------------------------------------------


def run_variability(features: xr.Dataset, region: str) -> FidelityResult:
    """Parts A and B: how fast the wind changes, and how far the landing point moves.

    Both are reductions over the per-analysis feature table, so this needs no
    access to the cache and runs in seconds.
    """
    t = features["time"].values
    levels = features["plevel"].values
    wind = np.stack([features["u"].values, features["v"].values], axis=-1)

    log.info("%s: wind change by lag and season", region)
    lag_wind = vb.lag_change_table(wind, t, levels=levels)

    log.info("%s: autocorrelation", region)
    autocorr = vb.vector_autocorrelation_table(wind, t, levels=levels)
    decorrelation = _decorrelation_frame(autocorr)

    log.info("%s: day-to-day direction change", region)
    direction = vb.daily_direction_change(
        features["u"].values, features["v"].values, t, levels=levels
    )

    log.info("%s: variance split", region)
    variance = vb.variance_split_table(wind.reshape(t.size, -1), t)

    log.info("%s: launch-slip movement", region)
    slip = vb.drift_slip_table(
        features["dx_east_m"].values, features["dy_north_m"].values, t
    )

    return FidelityResult(
        region=region,
        lag_wind=lag_wind,
        autocorr=autocorr,
        decorrelation=decorrelation,
        direction=direction,
        variance=variance,
        slip=slip,
    )


def _decorrelation_frame(autocorr: pd.DataFrame) -> pd.DataFrame:
    """Boil each season-and-level autocorrelation curve down to its 1/e crossing."""
    rows: list[dict] = []
    keys = ["season", "plevel"] if "plevel" in autocorr else ["season"]
    for key, sub in autocorr.groupby(keys, sort=False):
        sub = sub.sort_values("lag_hours")
        hours = vb.decorrelation_hours(sub["lag_hours"].values, sub["r"].values)
        row = dict(zip(keys, key if isinstance(key, tuple) else (key,), strict=True))
        rows.append(row | {"decorrelation_hours": hours, "decorrelation_days": hours / 24.0})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# C: the simulator's own approximation error.
# --------------------------------------------------------------------------


def _region_altitude(samples, lat_slice: slice, lon_slice: slice) -> np.ndarray:
    """One ascending altitude profile for the whole region, this month.

    Averaged over the month's geopotential-height samples and over the region's
    columns. All four variants must fly the same ``z(t)``; a per-column profile
    would make them differ in flight *duration* as well as in wind, and the
    comparison would no longer isolate the freezing. See
    :mod:`windclim.stats.trajectory` for the size of what this gives up.
    """
    with np.errstate(invalid="ignore"):
        z = np.nanmean(samples.z, axis=0)                    # (level, lat, lon)
    lat3 = samples.lat[None, :, None]
    geom = geopotential_to_geometric(z, np.broadcast_to(lat3, z.shape))
    region = geom[:, lat_slice, lon_slice]
    with np.errstate(invalid="ignore"):
        profile = np.nanmean(region.reshape(region.shape[0], -1), axis=1)
    return profile[::-1], region                             # ascending altitude


def run_trajectory_errors(
    cache_root: Path,
    region: str,
    cfg: AggregateConfig,
    *,
    dt: float = 120.0,
    months: tuple[tuple[int, int], ...] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Fly every launch four ways and return the per-launch errors.

    Returns ``(frame, diagnostics)``. The frame has one row per launch, with the
    distance from each variant's landing point to the reference's.

    The wind is read over the **whole master box**, not the region: a winter
    flight travels a few hundred kilometres east and leaves the region entirely,
    so cutting to the region would clip the trajectory rather than the data.
    """
    bbox = REGIONS[region]
    todo = months or tuple(
        (year, month) for year in cfg.years for month in range(1, 13)
    )

    times: list[np.ndarray] = []
    rows: list[dict[str, np.ndarray]] = []
    map_factor_gap = 0.0
    n_left_grid = 0
    n_dropped = 0
    alt_spread: dict[str, float] = {}

    for year, month in todo:
        samples = load_window(Path(cache_root), MASTER, year, month, cfg)
        if samples.z is None or not samples.z.size:
            raise ValueError(f"{year:04d}-{month:02d} has no geopotential height cached")

        lat_slice, lon_slice = bbox_slices(samples.lat, samples.lon, bbox, strict=True)
        profile, region_alt = _region_altitude(samples, lat_slice, lon_slice)
        alt_spread = tj.altitude_profile_spread(
            region_alt, burst_altitude_m=cfg.flight.burst_altitude_m
        )
        schedule = tj.build_schedule(profile, cfg.flight)

        # The raw files store ascending pressure; the flight model wants ascending
        # altitude, so the level axis is reversed once, here.
        wind = tj.GriddedWind(
            lat=samples.lat, lon=samples.lon,
            u=np.ascontiguousarray(samples.u[:, ::-1]),
            v=np.ascontiguousarray(samples.v[:, ::-1]),
        )

        in_month = np.asarray(samples.times, dtype="datetime64[M]").astype(int) % 12 + 1
        launchable = np.nonzero(in_month == month)[0]
        # The final analysis of the archive has no successor to fly into.
        needed = int(np.ceil(schedule.total_seconds / tj.ANALYSIS_INTERVAL_S))
        keep = launchable[launchable + needed < samples.times.size]
        n_dropped += int(launchable.size - keep.size)
        if keep.size == 0:
            continue

        cell_lat = samples.lat[lat_slice]
        cell_lon = samples.lon[lon_slice]
        gy, gx = np.meshgrid(cell_lat, cell_lon, indexing="ij")
        n_cell = gy.size
        launch_lat = np.tile(gy.ravel(), keep.size)
        launch_lon = np.tile(gx.ravel(), keep.size)
        launch_it = np.repeat(keep, n_cell)

        out = {
            name: tj.integrate(
                wind, schedule, launch_lat, launch_lon, launch_it, variant=name, dt=dt
            )
            for name in ("reference", *COMPARED)
        }
        ref = out["reference"]
        n_left_grid += int(ref.left_grid.sum())

        map_factor_gap = max(
            map_factor_gap,
            _map_factor_gap(samples, profile, lat_slice, lon_slice, keep,
                             out["both_frozen"], cfg),
        )

        row = {
            "ref_dx_m": ref.dx_east_m.astype(np.float32),
            "ref_dy_m": ref.dy_north_m.astype(np.float32),
            "left_grid": ref.left_grid,
            "lat": launch_lat.astype(np.float32),
            "lon": launch_lon.astype(np.float32),
        }
        for name in COMPARED:
            row[f"err_{name}_km"] = (
                np.hypot(out[name].dx_east_m - ref.dx_east_m,
                         out[name].dy_north_m - ref.dy_north_m) / 1000.0
            ).astype(np.float32)
        rows.append(row)
        times.append(np.repeat(samples.times[keep], n_cell))
        log.info(
            "%s %04d-%02d: %d launches, flight %.0f s",
            region, year, month, keep.size * n_cell, schedule.total_seconds,
        )
        del samples, wind

    frame = pd.DataFrame({k: np.concatenate([r[k] for r in rows]) for k in rows[0]})
    frame["time"] = np.concatenate(times)
    frame["season"] = season_of(frame["time"].values)
    frame["ref_distance_km"] = np.hypot(frame["ref_dx_m"], frame["ref_dy_m"]) / 1000.0

    diagnostics = {
        "n_launches": int(len(frame)),
        "n_left_grid": n_left_grid,
        "n_dropped_no_successor": n_dropped,
        "map_factor_gap_km": map_factor_gap,
        "altitude_spread": alt_spread,
        "dt_s": dt,
    }
    return frame, diagnostics


def _map_factor_gap(
    samples, profile, lat_slice, lon_slice, keep, both_frozen, cfg
) -> float:
    """Largest disagreement between the integrator and the closed form, in km.

    With both freezes on, the two are computing the same integral by different
    routes, so this should be small -- the residue of the ``1/cos(lat)`` factor
    that the closed form does not carry, plus float32 rounding in the cache.
    Watching it on every month is how a wiring mistake in the level ordering or
    the layer times would be caught on real data, not only in the tests.
    """
    from ..stats.drift import displacements  # noqa: PLC0415

    u = samples.u[keep][:, ::-1, lat_slice, lon_slice].astype(float)
    v = samples.v[keep][:, ::-1, lat_slice, lon_slice].astype(float)
    alt = np.broadcast_to(profile[:, None, None], u.shape[1:])
    dx, dy = displacements(u, v, alt, cfg.flight)
    gap = np.hypot(
        dx.reshape(-1) - both_frozen.dx_east_m, dy.reshape(-1) - both_frozen.dy_north_m
    )
    return float(np.nanmax(gap)) / 1000.0


def _example_launch(region: str, cell_lat, cell_lon) -> tuple[float, float]:
    """Where the illustrative flight starts.

    The region's named reference site when it has one, so the picture is of a
    place someone actually launches from rather than of the arithmetic centre
    of a bounding box. Falls back to the centre cell for a region with no site
    in ``sites.json``, which is the case for Wakayama.
    """
    from .csv_out import REFERENCE_SITE, _reference_site, region_sites  # noqa: PLC0415

    if region in REFERENCE_SITE:
        try:
            site = _reference_site(region_sites(region), region)
        except (ValueError, IndexError):
            log.warning("no reference site for %s; using the centre cell", region)
        else:
            return float(site["lat"]), float(site["lon"])
    return float(cell_lat[cell_lat.size // 2]), float(cell_lon[cell_lon.size // 2])


def example_tracks(
    cache_root: Path,
    region: str,
    cfg: AggregateConfig,
    year: int,
    month: int,
    *,
    day: int = 15,
    hour: int = 0,
    dt: float = 60.0,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], tuple[float, float], float]:
    """One flight from the centre of the region, flown all four ways.

    A single case rather than a statistic. The tables say how large the error
    usually is; a picture of one flight says what that means on a map, which is
    the part a reader can carry away. A finer step than the production run,
    because here the cost is one trajectory and the curve should look smooth.
    """
    samples = load_window(Path(cache_root), MASTER, year, month, cfg)
    lat_slice, lon_slice = bbox_slices(samples.lat, samples.lon, REGIONS[region],
                                       strict=True)
    profile, _ = _region_altitude(samples, lat_slice, lon_slice)
    schedule = tj.build_schedule(profile, cfg.flight)
    wind = tj.GriddedWind(
        lat=samples.lat, lon=samples.lon,
        u=np.ascontiguousarray(samples.u[:, ::-1]),
        v=np.ascontiguousarray(samples.v[:, ::-1]),
    )
    want = np.datetime64(f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}", "ns")
    it = int(np.argmin(np.abs(samples.times.astype("datetime64[ns]") - want)))
    cell_lat = samples.lat[lat_slice]
    cell_lon = samples.lon[lon_slice]
    la, lo = _example_launch(region, cell_lat, cell_lon)

    tracks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in ("reference", *COMPARED):
        out = tj.integrate(
            wind, schedule, np.array([la]), np.array([lo]), np.array([it]),
            variant=name, dt=dt, track=True,
        )
        tracks[name] = (out.track_lon[:, 0], out.track_lat[:, 0])
    ref = tracks["reference"]
    live = tracks["both_frozen"]
    gap_km = float(
        np.hypot((live[0][-1] - ref[0][-1]) * np.cos(np.radians(la)),
                 live[1][-1] - ref[1][-1]) * 111.195
    )
    return tracks, (la, lo), gap_km


def exclusion_bias(frame: pd.DataFrame) -> dict:
    """What dropping the trajectories that left the grid does to the answer.

    They are not a random sample. A payload only runs off the edge of the
    cached box when it is travelling fast towards it, so the dropped flights
    are the long, windy ones -- exactly the ones with the largest error. The
    reported medians are therefore biased **low**, and by how much is something
    to measure rather than wave at.
    """
    left = frame["left_grid"].to_numpy()
    if not left.any():
        return {"n_left": 0, "fraction": 0.0}
    out: dict = {
        "n_left": int(left.sum()),
        "fraction": float(left.mean()),
        "lon_min_left": float(frame["lon"][left].min()),
        "lon_max_left": float(frame["lon"][left].max()),
        "flight_km_left": float(np.median(frame["ref_distance_km"][left])),
        "flight_km_kept": float(np.median(frame["ref_distance_km"][~left])),
    }
    for variant in COMPARED:
        col = frame[f"err_{variant}_km"]
        kept = float(np.median(col[~left]))
        gone = float(np.median(col[left]))
        out[f"{variant}_kept_km"] = kept
        out[f"{variant}_left_km"] = gone
        # What the median would move to if the dropped flights were included at
        # their own level: a first-order estimate, not a correction.
        out[f"{variant}_bias_pct"] = 100.0 * left.mean() * (gone - kept) / max(kept, 1e-9)
    return out


def summarise_errors(frame: pd.DataFrame) -> pd.DataFrame:
    """Season by variant: how far off the frozen wind puts the landing point."""
    usable = frame[~frame["left_grid"]]
    rows: list[dict] = []
    for season in SEASON_ORDER:
        sub = usable[usable["season"] == season]
        if sub.empty:
            continue
        distance = sub["ref_distance_km"].to_numpy()
        for variant in COMPARED:
            err = sub[f"err_{variant}_km"].to_numpy()
            rows.append({
                "season": season,
                "variant": variant,
                "variant_ja": JP_VARIANT[variant],
                "median_km": float(np.median(err)),
                "p90_km": float(np.percentile(err, 90)),
                "max_km": float(err.max()),
                "flight_median_km": float(np.median(distance)),
                "relative_median": float(np.median(err / np.maximum(distance, 1e-6))),
                "relative_p90": float(
                    np.percentile(err / np.maximum(distance, 1e-6), 90)
                ),
                "n": int(err.size),
            })
    return pd.DataFrame(rows)


def rank_seasons(error: pd.DataFrame, slip: pd.DataFrame) -> pd.DataFrame:
    """Part D: one row per season, absolute and relative, error and slip together.

    Both columns are needed and they do not agree. Winter flies 275 km and summer
    46 km, so winter is almost bound to have the larger absolute error whatever
    the atmosphere does; the relative figure is the one that says whether the
    prediction is *proportionally* trustworthy, and it is not knowable in advance.
    """
    live = error[error["variant"] == "both_frozen"].set_index("season")
    day_slip = slip[slip["lag_hours"] == 24].set_index("season")
    rows: list[dict] = []
    for season in SEASON_ORDER:
        if season not in live.index:
            continue
        e = live.loc[season]
        rows.append({
            "season": season,
            "flight_median_km": e["flight_median_km"],
            "sim_error_median_km": e["median_km"],
            "sim_error_p90_km": e["p90_km"],
            "sim_error_relative_median": e["relative_median"],
            "slip_24h_median_km": (
                float(day_slip.loc[season, "median"]) if season in day_slip.index
                else np.nan
            ),
            "slip_24h_p90_km": (
                float(day_slip.loc[season, "p90"]) if season in day_slip.index
                else np.nan
            ),
        })
    out = pd.DataFrame(rows)
    out["rank_absolute"] = out["sim_error_median_km"].rank().astype(int)
    out["rank_relative"] = out["sim_error_relative_median"].rank().astype(int)
    return out


# --------------------------------------------------------------------------
# Driver and output.
# --------------------------------------------------------------------------


def run_fidelity(
    features: xr.Dataset,
    cache_root: Path,
    region: str,
    cfg: AggregateConfig,
    *,
    dt: float = 120.0,
    with_trajectories: bool = True,
    months: tuple[tuple[int, int], ...] | None = None,
) -> FidelityResult:
    """The whole study for one region."""
    result = run_variability(features, region)
    if not with_trajectories:
        return result

    frame, diagnostics = run_trajectory_errors(
        cache_root, region, cfg, dt=dt, months=months
    )
    result.error = summarise_errors(frame)
    result.ranking = rank_seasons(result.error, result.slip)
    result.headline = _headline(result, diagnostics | {"exclusion": exclusion_bias(frame)})
    return result


def _headline(result: FidelityResult, diagnostics: dict) -> dict:
    live = result.error[result.error["variant"] == "both_frozen"]
    by_season = live.set_index("season")
    worst_abs = by_season["median_km"].idxmax() if not by_season.empty else None
    best_rel = by_season["relative_median"].idxmin() if not by_season.empty else None
    dominant = (
        result.error.groupby("variant")["median_km"].median().drop("both_frozen")
    )
    return diagnostics | {
        "worst_absolute_season": worst_abs,
        "best_relative_season": best_rel,
        "dominant_freeze": dominant.idxmax() if not dominant.empty else None,
        "time_vs_place_ratio": (
            float(dominant.get("time_frozen", np.nan)
                  / max(dominant.get("place_frozen", np.nan), 1e-12))
        ),
    }


def write_fidelity_tables(result: FidelityResult, out_root: Path) -> list[Path]:
    """One CSV per table, under ``out/csv``."""
    folder = Path(out_root) / "csv"
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    tables = {
        "variability_lag": result.lag_wind,
        "variability_autocorr": result.autocorr,
        "variability_decorrelation": result.decorrelation,
        "variability_direction": result.direction,
        "variability_variance": result.variance,
        "fidelity_slip": result.slip,
        "fidelity_error": result.error,
        "fidelity_ranking": result.ranking,
    }
    for name, frame in tables.items():
        if frame is None or frame.empty:
            continue
        path = folder / f"{name}_{result.region}.csv"
        frame.to_csv(path, index=False, float_format="%.6g")
        written.append(path)
    return written


def format_fidelity(result: FidelityResult) -> str:
    """The numbers the report quotes, as plain text for the console and a file."""
    lines = [f"=== {result.region}: 日々の変動とシミュレーションの忠実度 ==="]

    lines.append("\n-- 風が入れ替わるまでの時間 (自己相関が 1/e を切る, 日) --")
    if not result.decorrelation.empty and "plevel" in result.decorrelation:
        pivot = result.decorrelation.pivot(
            index="plevel", columns="season", values="decorrelation_days"
        )
        lines.append(pivot.reindex(columns=list(SEASON_ORDER)).to_string(
            float_format=lambda x: f"{x:5.2f}"
        ))

    lines.append("\n-- 打ち上げが 24 時間ずれたときの落下点の移動 (km) --")
    day = result.slip[result.slip["lag_hours"] == 24]
    for _, r in day.iterrows():
        lines.append(
            f"  {r['season']:<12s} 中央値 {r['median']:7.1f}  p90 {r['p90']:7.1f}  "
            f"最大 {r['max']:7.1f}"
        )

    if not result.error.empty:
        lines.append("\n-- シミュレータの近似誤差 (基準軌道との距離, km) --")
        for season in SEASON_ORDER:
            sub = result.error[result.error["season"] == season]
            if sub.empty:
                continue
            lines.append(f"  {season}")
            for _, r in sub.iterrows():
                lines.append(
                    f"    {r['variant_ja']:<24s} 中央値 {r['median_km']:6.1f} km"
                    f"  p90 {r['p90_km']:6.1f} km"
                    f"  飛行距離比 {100 * r['relative_median']:5.1f}%"
                )

    if not result.ranking.empty:
        lines.append("\n-- 総合 --")
        lines.append(result.ranking.to_string(index=False, float_format=lambda x: f"{x:.3g}"))

    if result.headline:
        lines.append("\n-- 診断 --")
        for k, v in result.headline.items():
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)
