"""Turn the cached analyses into per-(month, half, level, lat, lon) statistics.

The loop is over **calendar months**, not over files. For January it loads all
ten Januaries at once, cuts them to the region, splits them into the four half
bins and computes every statistic exactly, then frees the month and moves on.

That shape is what makes exact percentiles affordable. One bin of the Hokkaido
region is 280 analyses x 38 levels x ~540 cells, about 46 MB in float64 -- so
every sample of a bin fits in memory and ``np.nanpercentile`` can be used
directly. No streaming approximation, no t-digest, no reservoir sampling.

Accumulation is in float64; only the results are stored as float32.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import xarray as xr

from ..config import DEFAULT_PRODUCT, LEVEL_MIN_HPA, YEARS
from ..grid import bbox_slices
from ..regions import REGIONS, BBox, cache_box_name, to_signed_lon
from ..timebins import DEFAULT_SCHEME, BinScheme, assign_bin
from .altitude import geopotential_to_geometric
from .drift import FlightProfile, displacements, flight_seconds, travel_bearing_deg
from .vector import (
    DEFAULT_PERCENTILES,
    DEFAULT_THRESHOLDS,
    constancy,
    effective_sample_size,
    exceedance_freq,
    lag1_autocorr,
    moments,
    scalar_mean_speed,
    speed,
    speed_percentiles,
    unit_component_means,
    vector_mean_speed,
)

__all__ = [
    "AggregateConfig",
    "MonthSamples",
    "aggregate_all",
    "aggregate_month",
    "load_month",
    "load_window",
]

log = logging.getLogger(__name__)

#: Above this pressure (i.e. below this altitude) the diurnal cycle is real --
#: sea breeze, nocturnal decoupling -- and worth resolving by analysis hour.
HOUR_PRODUCT_MIN_HPA = 300.0

#: Wind-rose bins. Sixteen compass sectors centred on N, NNE, ... and six speed
#: classes. A rose is the honest way to show a bimodal direction, which the mean
#: and the ellipse both hide -- and bimodality is the headline finding in the
#: stratosphere at the seasonal reversals, not an edge case.
ROSE_SECTORS = 16
ROSE_SPEED_EDGES: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0, 30.0, 50.0, np.inf)


@dataclass(frozen=True)
class AggregateConfig:
    years: range = YEARS
    product: str = DEFAULT_PRODUCT
    date_convention: str = "utc"
    percentiles: tuple[float, ...] = DEFAULT_PERCENTILES
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS
    level_min_hpa: float = LEVEL_MIN_HPA
    hour_product_min_hpa: float = HOUR_PRODUCT_MIN_HPA
    by_hour: bool = True
    #: Roses are kept for one representative cell only -- a full grid of
    #: (16 sectors x 6 classes) histograms would be larger than every other
    #: product combined. ``None`` means the centre of the region.
    roses: bool = True
    rose_cell: tuple[int, int] | None = None
    #: Integrate a nominal flight through every profile, so the landing spread is
    #: measured rather than inferred. See :mod:`windclim.stats.drift`.
    drift: bool = True
    flight: FlightProfile = field(default_factory=FlightProfile)
    #: How each calendar month is cut into bins. The shipped product uses
    #: half-months; :data:`windclim.timebins.WEEK` reproduces the seven-day
    #: version the appendix shows. Everything downstream reads the scheme off
    #: the dataset rather than from a global, so the two cannot be mixed up.
    scheme: BinScheme = DEFAULT_SCHEME


@dataclass
class MonthSamples:
    """Every analysis of one calendar month, across all years, for one region."""

    month: int
    level: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    weight: np.ndarray
    times: np.ndarray                      # datetime64[ns], length N
    u: np.ndarray                          # (N, level, lat, lon) float32
    v: np.ndarray
    z_times: np.ndarray = field(default_factory=lambda: np.array([], dtype="datetime64[ns]"))
    z: np.ndarray | None = None            # (Nz, level, lat, lon) float32

    @property
    def n(self) -> int:
        return self.times.size


def _year_files(cache_root: Path, product: str, var: str, year: int, month: int,
                box_name: str = "master") -> list[Path]:
    folder = Path(cache_root) / "raw" / product / var / f"{year:04d}"
    pattern = f"{var}_{year:04d}{month:02d}*_{box_name}.nc"
    return sorted(folder.glob(pattern))


def _open_region(path: Path, name: str, bbox: BBox) -> xr.Dataset:
    """Open one cached file and cut it to a region.

    ``strict=True``: the cache holds the master box, which contains every region
    by construction, so a file that does not span the region is a broken cache
    rather than an edge case to clip silently.
    """
    ds = xr.open_dataset(path, engine="netcdf4")
    try:
        lat_sl, lon_sl = bbox_slices(ds["lat"].values, ds["lon"].values, bbox, strict=True)
    except ValueError as exc:
        ds.close()
        raise ValueError(f"{path.name}: {exc}") from exc
    return ds.isel(lat=lat_sl, lon=lon_sl)


def load_window(
    cache_root: Path,
    bbox: BBox,
    year: int,
    month: int,
    cfg: AggregateConfig,
    *,
    extend_analyses: int = 1,
) -> MonthSamples:
    """One calendar month of **one** year, in time order, cut to ``bbox``.

    :func:`load_month` loads every year of a calendar month at once, because the
    half statistics pool them. Trajectory work needs the opposite shape: a
    contiguous run of analyses, in order, so that a flight can be advected from
    one analysis into the next.

    ``extend_analyses`` carries the first few analyses of the following month in
    as well. A flight launched at 18 UTC on the last day of the month lands two
    and a bit hours later, still inside the same six-hour interval, so it needs
    the next analysis -- which belongs to the next month's files. Without this
    the last launch of every month would have to be dropped, which is twelve
    launches a year thrown away for a bookkeeping reason.
    """
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    u_parts: list[np.ndarray] = []
    v_parts: list[np.ndarray] = []
    t_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    zt_parts: list[np.ndarray] = []
    level = lat = lon = weight = None

    plan: list[tuple[int, int, int | None]] = [(year, month, None)]
    if extend_analyses > 0:
        plan.append((nxt[0], nxt[1], extend_analyses))

    for yr, mo, limit in plan:
        u_files = _year_files(cache_root, cfg.product, "ugrd", yr, mo)
        v_files = _year_files(cache_root, cfg.product, "vgrd", yr, mo)
        if len(u_files) != len(v_files):
            raise ValueError(
                f"{yr:04d}-{mo:02d}: {len(u_files)} u files but {len(v_files)} v files"
            )
        if not u_files:
            if limit is None:
                raise FileNotFoundError(
                    f"no cached files for {yr:04d}-{mo:02d} under {cache_root}"
                )
            continue                      # past the end of the archive; caller drops the tail
        if limit is not None:
            u_files, v_files = u_files[:1], v_files[:1]
        for up, vp in zip(u_files, v_files, strict=True):
            with _open_region(up, "u", bbox) as du, _open_region(vp, "v", bbox) as dv:
                if level is None:
                    level = du["level"].values.astype(float)
                    lat = du["lat"].values.astype(float)
                    lon = du["lon"].values.astype(float)
                    weight = (
                        du["weight"].values.astype(float)
                        if "weight" in du
                        else np.cos(np.radians(lat))
                    )
                if not np.array_equal(du["time"].values, dv["time"].values):
                    raise ValueError(f"time axes differ between {up.name} and {vp.name}")
                cut = slice(None) if limit is None else slice(0, limit)
                u_parts.append(du["u"].values[cut])
                v_parts.append(dv["v"].values[cut])
                t_parts.append(du["time"].values[cut])

        z_files = _year_files(cache_root, cfg.product, "hgt", yr, mo)
        if limit is None:
            for zp in z_files:
                with _open_region(zp, "z", bbox) as dz:
                    z_parts.append(dz["z"].values)
                    zt_parts.append(dz["time"].values)

    times = np.concatenate(t_parts)
    order = np.argsort(times)
    return MonthSamples(
        month=month,
        level=level,
        lat=lat,
        lon=lon,
        weight=weight,
        times=times[order],
        u=np.concatenate(u_parts)[order],
        v=np.concatenate(v_parts)[order],
        z_times=np.concatenate(zt_parts) if zt_parts else np.array([], dtype=times.dtype),
        z=np.concatenate(z_parts) if z_parts else None,
    )


def load_month(
    cache_root: Path, region: str, month: int, cfg: AggregateConfig
) -> MonthSamples:
    """Read every cached file for one calendar month and cut it to ``region``."""
    bbox = REGIONS[region]
    box_name = cache_box_name(region)
    u_parts: list[np.ndarray] = []
    v_parts: list[np.ndarray] = []
    t_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    zt_parts: list[np.ndarray] = []
    level = lat = lon = weight = None

    for year in cfg.years:
        u_files = _year_files(cache_root, cfg.product, "ugrd", year, month, box_name)
        v_files = _year_files(cache_root, cfg.product, "vgrd", year, month, box_name)
        if not u_files or len(u_files) != len(v_files):
            log.warning("month %04d-%02d: %d u files, %d v files", year, month,
                        len(u_files), len(v_files))
        for up, vp in zip(u_files, v_files, strict=False):
            with _open_region(up, "u", bbox) as du, _open_region(vp, "v", bbox) as dv:
                if level is None:
                    level = du["level"].values.astype(float)
                    lat = du["lat"].values.astype(float)
                    lon = du["lon"].values.astype(float)
                    weight = (
                        du["weight"].values.astype(float)
                        if "weight" in du
                        else np.cos(np.radians(lat))
                    )
                if not np.array_equal(du["time"].values, dv["time"].values):
                    raise ValueError(f"time axes differ between {up.name} and {vp.name}")
                u_parts.append(du["u"].values)
                v_parts.append(dv["v"].values)
                t_parts.append(du["time"].values)

        for zp in _year_files(cache_root, cfg.product, "hgt", year, month, box_name):
            with _open_region(zp, "z", bbox) as dz:
                z_parts.append(dz["z"].values)
                zt_parts.append(dz["time"].values)

    if not u_parts:
        raise FileNotFoundError(
            f"no cached files for month {month:02d} under {cache_root}; run `windclim fetch` first"
        )

    times = np.concatenate(t_parts)
    order = np.argsort(times)
    return MonthSamples(
        month=month,
        level=level,
        lat=lat,
        lon=lon,
        weight=weight,
        times=times[order],
        u=np.concatenate(u_parts)[order],
        v=np.concatenate(v_parts)[order],
        z_times=np.concatenate(zt_parts) if zt_parts else np.array([], dtype=times.dtype),
        z=np.concatenate(z_parts) if z_parts else None,
    )


def _bin_index(
    times: np.ndarray, convention: str, scheme: BinScheme
) -> tuple[np.ndarray, np.ndarray]:
    """``(month, bin)`` for each analysis time, plus its UTC hour."""
    stamps = [t.astype("datetime64[s]").item().replace(tzinfo=__import__("datetime").timezone.utc)
              for t in times]
    bins = np.array(
        [assign_bin(t, convention=convention, scheme=scheme) for t in stamps], dtype=int
    )
    hours = np.array([t.hour for t in stamps], dtype=int)
    return bins, hours


def _year_of(times: np.ndarray) -> np.ndarray:
    return times.astype("datetime64[Y]").astype(int) + 1970


def _pooled_lag1(sp: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Lag-1 autocorrelation of the speed within each year's contiguous run, pooled.

    Computing it across the whole ten-year sample would be wrong: consecutive
    samples from different Januaries are a year apart, not six hours, and the
    joins would drag the estimate towards zero and so overstate the effective
    sample size.
    """
    per_year: list[np.ndarray] = []
    lengths: list[int] = []
    for y in np.unique(years):
        run = sp[years == y]
        if run.shape[0] < 3:
            continue
        per_year.append(lag1_autocorr(run, axis=0))
        lengths.append(run.shape[0])
    if not per_year:
        return np.full(sp.shape[1:], np.nan)
    w = np.asarray(lengths, dtype=float)[:, None, None, None]
    stack = np.stack(per_year)
    with np.errstate(invalid="ignore"):
        return np.nansum(stack * w, axis=0) / np.nansum(np.isfinite(stack) * w, axis=0)


def _stats_for(
    u: np.ndarray, v: np.ndarray, years: np.ndarray, cfg: AggregateConfig
) -> dict[str, np.ndarray]:
    """Every statistic for one bin's samples, shaped ``(level, lat, lon)``."""
    m = moments(u, v, axis=0)
    sp = speed(u, v)
    sm = scalar_mean_speed(u, v)
    svm = vector_mean_speed(m.u_mean, m.v_mean)
    r1 = _pooled_lag1(sp, years)
    u_unit, v_unit = unit_component_means(u, v, axis=0)

    with np.errstate(invalid="ignore"):
        sp_std = np.nanstd(sp, axis=0, ddof=1)
        sp_max = np.nanmax(sp, axis=0)

    out: dict[str, np.ndarray] = {
        "n": m.n,
        "u_mean": m.u_mean,
        "v_mean": m.v_mean,
        "u_var": m.u_var,
        "v_var": m.v_var,
        "uv_cov": m.uv_cov,
        "speed_mean": sm,
        "speed_vector_mean": svm,
        "speed_std": sp_std,
        "speed_max": sp_max,
        "constancy": constancy(svm, sm),
        "u_unit_mean": u_unit,
        "v_unit_mean": v_unit,
        "lag1_autocorr": r1,
        "n_eff": effective_sample_size(m.n, r1),
    }
    pcts = speed_percentiles(u, v, qs=cfg.percentiles, axis=0)
    for q, arr in zip(cfg.percentiles, pcts, strict=True):
        out[f"speed_p{int(q):02d}"] = arr
    exc = exceedance_freq(u, v, thresholds=cfg.thresholds, axis=0)
    for t, arr in zip(cfg.thresholds, exc, strict=True):
        out[f"exceed_gt{int(t)}"] = arr
    return out


def aggregate_month(samples: MonthSamples, cfg: AggregateConfig) -> xr.Dataset:
    """Statistics for one calendar month, dims ``(half, level, lat, lon)``."""
    bins, hours = _bin_index(samples.times, cfg.date_convention, cfg.scheme)
    years = _year_of(samples.times)
    dims = ("bin", "level", "lat", "lon")
    shape = (cfg.scheme.n_bins, samples.level.size, samples.lat.size, samples.lon.size)

    accum: dict[str, np.ndarray] = {}
    for wi, half in enumerate(cfg.scheme.bins):
        sel = (bins[:, 0] == samples.month) & (bins[:, 1] == half)
        if not sel.any():
            log.warning("month %02d half %d has no samples", samples.month, half)
            continue
        stats = _stats_for(samples.u[sel], samples.v[sel], years[sel], cfg)
        for key, arr in stats.items():
            if key not in accum:
                accum[key] = np.full(shape, 0 if key == "n" else np.nan,
                                     dtype=np.int64 if key == "n" else np.float64)
            accum[key][wi] = arr

    data_vars = {
        k: (dims, v.astype(np.int32 if k == "n" else np.float32)) for k, v in accum.items()
    }

    # Geopotential height -> the altitude axis a human reads.
    if samples.z is not None and samples.z.size:
        z_bins, _ = _bin_index(samples.z_times, cfg.date_convention, cfg.scheme)
        z_mean = np.full(shape, np.nan)
        z_std = np.full(shape, np.nan)
        for wi, half in enumerate(cfg.scheme.bins):
            sel = (z_bins[:, 0] == samples.month) & (z_bins[:, 1] == half)
            if not sel.any():
                continue
            with np.errstate(invalid="ignore"):
                z_mean[wi] = np.nanmean(samples.z[sel], axis=0)
                z_std[wi] = np.nanstd(samples.z[sel], axis=0, ddof=1)
        lat3 = samples.lat[None, None, :, None]
        data_vars["z_mean_gpm"] = (dims, z_mean.astype(np.float32))
        data_vars["z_std_gpm"] = (dims, z_std.astype(np.float32))
        data_vars["alt_geom_mean_m"] = (
            dims,
            geopotential_to_geometric(z_mean, np.broadcast_to(lat3, shape)).astype(np.float32),
        )

    ds = xr.Dataset(
        data_vars,
        coords={
            "bin": np.asarray(cfg.scheme.bins, dtype=np.int8),
            "level": samples.level.astype(np.float32),
            "lat": samples.lat.astype(np.float32),
            "lon": np.asarray([to_signed_lon(x) for x in samples.lon], dtype=np.float32),
        },
    )
    ds = ds.assign_coords(month=np.int8(samples.month))
    # Carry the binning with the data. Everything downstream -- axis labels,
    # CSV column names, the sample-count gate -- reads these rather than a
    # module global, so a figure can never claim a scheme the numbers were not
    # computed under.
    ds.attrs["bin_scheme"] = cfg.scheme.name
    ds.attrs["bin_labels"] = list(cfg.scheme.labels)
    ds.attrs["bin_short"] = list(cfg.scheme.short)
    ds.attrs["bin_start_days"] = list(cfg.scheme.starts)
    ds["gauss_weight"] = (("lat",), samples.weight.astype(np.float32))

    if cfg.drift and samples.z is not None and samples.z.size:
        drift_ds = _aggregate_drift(samples, cfg, bins, data_vars)
        ds = ds.merge(drift_ds)
        ds.attrs.update(drift_ds.attrs)   # merge keeps only the left operand's attrs
    if cfg.by_hour:
        ds = ds.merge(_aggregate_by_hour(samples, cfg, bins, hours, years))
    if cfg.roses:
        roses = _aggregate_roses(samples, cfg, bins)
        # merge keeps only the left operand's attrs, so carry the rose cell over.
        ds = ds.merge(roses)
        ds.attrs.update(roses.attrs)
    return ds


def _aggregate_roses(samples: MonthSamples, cfg: AggregateConfig, bins: np.ndarray) -> xr.Dataset:
    """Direction x speed histograms at one representative cell.

    Counts, not frequencies: the half bins hold different numbers of analyses, so
    normalising is left to the figure, which can then state what it normalised by.
    """
    i, j = cfg.rose_cell or (samples.lat.size // 2, samples.lon.size // 2)
    u = samples.u[:, :, i, j]
    v = samples.v[:, :, i, j]
    sp = np.hypot(u, v)
    direction = (np.degrees(np.arctan2(u, v)) + 180.0) % 360.0

    width = 360.0 / ROSE_SECTORS
    sector = np.floor(((direction + width / 2.0) % 360.0) / width).astype(int)
    speed_class = np.clip(
        np.searchsorted(np.asarray(ROSE_SPEED_EDGES[1:-1]), sp, side="right"),
        0,
        len(ROSE_SPEED_EDGES) - 2,
    )

    n_class = len(ROSE_SPEED_EDGES) - 1
    shape = (cfg.scheme.n_bins, samples.level.size, ROSE_SECTORS, n_class)
    counts = np.zeros(shape, dtype=np.int32)
    for wi, half in enumerate(cfg.scheme.bins):
        sel = (bins[:, 0] == samples.month) & (bins[:, 1] == half)
        if not sel.any():
            continue
        ok = np.isfinite(sp[sel])
        for lv in range(samples.level.size):
            good = ok[:, lv]
            np.add.at(
                counts[wi, lv],
                (sector[sel][:, lv][good], speed_class[sel][:, lv][good]),
                1,
            )

    return xr.Dataset(
        {"rose_counts": (("bin", "level", "sector", "speed_class"), counts)},
        coords={
            "sector": np.arange(ROSE_SECTORS, dtype=np.int8),
            "sector_deg": (("sector",), (np.arange(ROSE_SECTORS) * width).astype(np.float32)),
            "speed_class": np.arange(n_class, dtype=np.int8),
            "speed_class_lo": (
                ("speed_class",),
                np.asarray(ROSE_SPEED_EDGES[:-1], dtype=np.float32),
            ),
        },
        attrs={
            "rose_cell_lat": float(samples.lat[i]),
            "rose_cell_lon": float(to_signed_lon(samples.lon[j])),
        },
    )


def _aggregate_drift(
    samples: MonthSamples, cfg: AggregateConfig, bins: np.ndarray, data_vars: dict
) -> xr.Dataset:
    """Landing displacement statistics for a nominal flight from every grid cell.

    Computed per analysis and then summarised, not derived from the mean wind:
    the horizontal displacement is linear in the wind profile, so both give the
    same *mean*, but only the per-analysis route gives an honest spread. Inferring
    the spread from the per-level variances would need the correlations between
    levels, which are not stored -- and assuming them would be the sort of
    invisible guess this pipeline is trying to avoid.
    """
    dims = ("bin", "lat", "lon")
    shape = (cfg.scheme.n_bins, samples.lat.size, samples.lon.size)
    alt_all = data_vars["alt_geom_mean_m"][1]          # (half, level, lat, lon)

    keys = ("east_m", "north_m", "east_var", "north_var", "cov",
            "dist_mean_km", "dist_p50_km", "dist_p90_km", "dist_p95_km", "dist_max_km",
            "bearing_deg", "flight_time_s", "n")
    acc = {k: np.full(shape, np.nan) for k in keys}

    for wi, half in enumerate(cfg.scheme.bins):
        sel = (bins[:, 0] == samples.month) & (bins[:, 1] == half)
        if not sel.any():
            continue
        # Levels arrive ascending in pressure, i.e. descending in altitude; the
        # layer-thickness maths wants them the other way round.
        alt = np.asarray(alt_all[wi], dtype=float)[::-1]
        u = samples.u[sel][:, ::-1]
        v = samples.v[sel][:, ::-1]
        if not np.isfinite(alt).all():
            continue

        dx, dy = displacements(u, v, alt, cfg.flight)
        dist_km = np.hypot(dx, dy) / 1000.0
        with np.errstate(invalid="ignore"):
            ex, ny = np.nanmean(dx, axis=0), np.nanmean(dy, axis=0)
            acc["east_m"][wi] = ex
            acc["north_m"][wi] = ny
            acc["east_var"][wi] = np.nanvar(dx, axis=0, ddof=1)
            acc["north_var"][wi] = np.nanvar(dy, axis=0, ddof=1)
            acc["cov"][wi] = np.nanmean(
                (dx - ex) * (dy - ny), axis=0
            ) * dx.shape[0] / max(dx.shape[0] - 1, 1)
            acc["dist_mean_km"][wi] = np.nanmean(dist_km, axis=0)
            for q, key in ((50, "dist_p50_km"), (90, "dist_p90_km"), (95, "dist_p95_km")):
                acc[key][wi] = np.nanpercentile(dist_km, q, axis=0)
            acc["dist_max_km"][wi] = np.nanmax(dist_km, axis=0)
        acc["bearing_deg"][wi] = travel_bearing_deg(ex, ny)
        acc["flight_time_s"][wi] = flight_seconds(alt, cfg.flight)
        acc["n"][wi] = np.isfinite(dist_km).sum(axis=0)

    out = xr.Dataset(
        {f"drift_{k}": (dims, v.astype(np.float32)) for k, v in acc.items() if k != "n"}
        | {"drift_n": (dims, acc["n"].astype(np.int32))}
    )
    out.attrs.update(
        {
            "flight_ascent_rate_ms": cfg.flight.ascent_rate_ms,
            "flight_burst_altitude_m": cfg.flight.burst_altitude_m,
            "flight_descent_rate_ms": cfg.flight.descent_rate_ms,
            "flight_description": cfg.flight.label(),
        }
    )
    return out


def _aggregate_by_hour(
    samples: MonthSamples,
    cfg: AggregateConfig,
    bins: np.ndarray,
    hours: np.ndarray,
    years: np.ndarray,
) -> xr.Dataset:
    """A reduced stat set resolved by analysis hour, lower troposphere only.

    Splitting by hour cuts each bin from 280 samples to 70, which is too few for
    stable percentiles -- hence the reduced set. Restricting it to p >= 300 hPa
    keeps the product small and is justified by what it shows: the diurnal signal
    is confined to the lowest couple of kilometres, which is exactly why the main
    product can marginalise over hour everywhere above.
    """
    keep = samples.level >= cfg.hour_product_min_hpa
    lv = samples.level[keep]
    uh = samples.u[:, keep]
    vh = samples.v[:, keep]
    hour_values = np.array([0, 6, 12, 18], dtype=np.int8)
    dims = ("bin", "hour", "level_low", "lat", "lon")
    shape = (cfg.scheme.n_bins, hour_values.size, lv.size, samples.lat.size, samples.lon.size)

    keys = ("n", "u_mean", "v_mean", "speed_mean", "speed_std", "constancy")
    accum = {
        k: np.full(shape, 0 if k == "n" else np.nan,
                   dtype=np.int64 if k == "n" else np.float64)
        for k in keys
    }
    for wi, half in enumerate(cfg.scheme.bins):
        for hi, hour in enumerate(hour_values):
            sel = (bins[:, 0] == samples.month) & (bins[:, 1] == half) & (hours == hour)
            if not sel.any():
                continue
            m = moments(uh[sel], vh[sel], axis=0)
            sm = scalar_mean_speed(uh[sel], vh[sel])
            svm = vector_mean_speed(m.u_mean, m.v_mean)
            with np.errstate(invalid="ignore"):
                sp_std = np.nanstd(speed(uh[sel], vh[sel]), axis=0, ddof=1)
            for k, arr in (
                ("n", m.n), ("u_mean", m.u_mean), ("v_mean", m.v_mean),
                ("speed_mean", sm), ("speed_std", sp_std),
                ("constancy", constancy(svm, sm)),
            ):
                accum[k][wi, hi] = arr

    return xr.Dataset(
        {
            f"hr_{k}": (dims, v.astype(np.int32 if k == "n" else np.float32))
            for k, v in accum.items()
        },
        coords={
            "hour": hour_values,
            "hour_jst": (("hour",), ((hour_values + 9) % 24).astype(np.int8)),
            "level_low": lv.astype(np.float32),
        },
    )


def aggregate_all(
    cache_root: Path,
    region: str,
    cfg: AggregateConfig | None = None,
    *,
    months: Sequence[int] = tuple(range(1, 13)),
    intermediate_dir: Path | None = None,
) -> xr.Dataset:
    """Run every month and concatenate, dims ``(month, half, level, lat, lon)``."""
    cfg = cfg or AggregateConfig()
    parts: list[xr.Dataset] = []
    for month in months:
        log.info("aggregating %s month %02d", region, month)
        samples = load_month(Path(cache_root), region, month, cfg)
        ds = aggregate_month(samples, cfg)
        del samples
        if intermediate_dir is not None:
            Path(intermediate_dir).mkdir(parents=True, exist_ok=True)
            ds.to_netcdf(Path(intermediate_dir) / f"{region}_{month:02d}.nc")
        parts.append(ds)
    out = xr.concat(parts, dim="month")
    out = out.assign_coords(month=np.asarray(list(months), dtype=np.int8))
    out["bin_end_day"] = (
        ("month", "bin"),
        np.array(
            [
                [max(cfg.scheme.day_range(y, m, b)[1] for y in cfg.years)
                 for b in cfg.scheme.bins]
                for m in months
            ],
            dtype=np.int8,
        ),
    )
    return out
