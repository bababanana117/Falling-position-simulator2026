"""Command line entry point.

Run it from the ``research/`` directory: libnetcdf reads ``.dodsrc`` from the
current working directory, and that is where the DAP timeouts and the User-Agent
are set.

    python -m windclim.cli fetch --dry-run
    python -m windclim.cli fetch --years 2016-2025          # a few hours
    python -m windclim.cli aggregate --region wakayama
    python -m windclim.cli export    --region wakayama
    python -m windclim.cli figures   --region wakayama
    python -m windclim.cli compare
    python -m windclim.cli all --region hokkaido
    python -m windclim.cli validate --region hokkaido
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display on a server, and figures are files anyway

from .config import (  # noqa: E402
    CACHE_ROOT,
    DEFAULT_PRODUCT,
    LEVEL_MIN_HPA,
    MAX_WORKERS,
    OUT_ROOT,
    VARS,
    YEARS,
)
from .regions import REGIONS  # noqa: E402
from .timebins import DEFAULT_SCHEME, SCHEMES  # noqa: E402

__all__ = ["build_parser", "main"]

log = logging.getLogger("windclim")

REGION_LABELS = {"hokkaido": "北海道", "wakayama": "和歌山", "ehime": "愛媛",
                 "southwest": "西日本", "japan": "日本"}


def _years(text: str) -> range:
    """``2016-2025`` or ``2016``."""
    if "-" in text:
        a, b = text.split("-", 1)
        return range(int(a), int(b) + 1)
    y = int(text)
    return range(y, y + 1)


def _ints(text: str) -> list[int]:
    """``1``, ``1,2,3`` or ``1-3``."""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="windclim", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def _common(sp):
        sp.add_argument("--region", choices=sorted(REGIONS), required=True)
        sp.add_argument("--years", type=_years, default=YEARS)
        sp.add_argument("--product", default=DEFAULT_PRODUCT, choices=["anl_p", "anl_p125"])
        sp.add_argument("--convention", default="utc", choices=["utc", "jst"])
        sp.add_argument("--cache", type=Path, default=CACHE_ROOT)
        sp.add_argument("--out", type=Path, default=OUT_ROOT)
        sp.add_argument(
            "--scheme", default=DEFAULT_SCHEME.name, choices=sorted(SCHEMES),
            help="how each month is cut into bins (default: %(default)s). "
                 "Non-default runs write to their own files so the two products "
                 "never overwrite one another.",
        )
        return sp

    f = sub.add_parser("fetch", help="download subsets from GDEX into the local cache")
    f.add_argument("--years", type=_years, default=YEARS)
    f.add_argument("--months", type=_ints, default=list(range(1, 13)))
    f.add_argument("--vars", dest="vars_", type=lambda s: s.split(","), default=list(VARS))
    f.add_argument("--product", default=DEFAULT_PRODUCT, choices=["anl_p", "anl_p125"])
    f.add_argument("--backend", default="opendap", choices=["opendap", "ncss"])
    f.add_argument("--workers", type=int, default=MAX_WORKERS)
    f.add_argument("--level-min-hpa", type=float, default=LEVEL_MIN_HPA)
    f.add_argument("--box", default="master", choices=["master", "sw", "jp"],
                   help="which cache box to fetch (sw = western/southern Japan)")
    f.add_argument("--cache", type=Path, default=CACHE_ROOT)
    f.add_argument("--dry-run", action="store_true",
                   help="print the URLs that would be fetched and open no connection")
    f.add_argument("--verify", action="store_true",
                   help="re-hash cached files instead of trusting the recorded shape")

    a = _common(sub.add_parser("aggregate", help="compute the statistics and write the NetCDF"))
    a.add_argument("--months", type=_ints, default=list(range(1, 13)))

    _common(sub.add_parser("export", help="write Parquet and the curated CSV tables"))
    _common(sub.add_parser("figures", help="draw every figure"))
    _common(sub.add_parser("summary", help="print the numbers the report quotes"))

    va = _common(sub.add_parser(
        "validate",
        help="at what time resolution does the seasonal signal stop and the noise start",
    ))
    va.add_argument("--stage", default="all",
                    choices=["all", "features", "analyse", "figures"])
    va.add_argument("--permutations", type=int, default=500)

    fi = _common(sub.add_parser(
        "fidelity",
        help="day-to-day variability by season, and how far the frozen wind is off",
    ))
    fi.add_argument("--stage", default="all",
                    choices=["all", "variability", "trajectories", "figures"])
    fi.add_argument("--dt", type=float, default=120.0,
                    help="integration step in seconds (max; segments subdivide)")

    wi = _common(sub.add_parser(
        "winter",
        help="fit the winter speed distribution and fly Monte Carlo landings",
    ))
    wi.add_argument("--season", default=None,
                    help="season key from timebins.SEASONS (default: the first, winter)")
    wi.add_argument("--samples", type=int, default=4000)
    wi.add_argument("--fetch-dem", action="store_true",
                    help="download the terrain tile for the map if it is not cached")
    wi.add_argument("--dem-width", type=int, default=1440)
    wi.add_argument("--dem-height", type=int, default=None,
                    help="default: derived from the map box so the service "
                         "returns exactly that box")

    c = sub.add_parser("compare", help="draw the two-region comparison")
    c.add_argument("--out", type=Path, default=OUT_ROOT)
    c.add_argument("--years", type=_years, default=YEARS)

    al = _common(sub.add_parser("all", help="aggregate, export and draw, for one region"))
    al.add_argument("--months", type=_ints, default=list(range(1, 13)))
    return p


def _scheme(args):
    from .timebins import DEFAULT_SCHEME, scheme_by_name

    return scheme_by_name(getattr(args, "scheme", None) or DEFAULT_SCHEME.name)


def _tag(args) -> str:
    """Suffix distinguishing non-default runs, so they cannot overwrite each other."""
    from .timebins import DEFAULT_SCHEME

    parts = []
    if getattr(args, "convention", "utc") != "utc":
        parts.append(args.convention)
    scheme = _scheme(args)
    if scheme.name != DEFAULT_SCHEME.name:
        parts.append(scheme.name)
    return "".join(f"_{p}" for p in parts)


def _stats_path(out: Path, region: str, args) -> Path:
    years = list(args.years)
    return (
        out / "netcdf"
        / f"jra3q_windclim_{region}_{years[0]}-{years[-1]}{_tag(args)}_v1.nc"
    )


def _cfg(args):
    from .stats.aggregate import AggregateConfig

    return AggregateConfig(
        years=args.years,
        product=args.product,
        date_convention=args.convention,
        scheme=_scheme(args),
    )


def _cmd_fetch(args) -> int:
    from .fetch.cache import plan_tasks
    from .fetch.driver import run_fetch
    from .regions import FETCH_BOXES

    tasks = plan_tasks(
        args.vars_, args.product, args.years,
        months=args.months, level_min_hpa=args.level_min_hpa,
        bbox=FETCH_BOXES[args.box], box_name=args.box,
    )
    report = run_fetch(
        tasks, cache_root=args.cache, fetcher_name=args.backend,
        workers=args.workers, dry_run=args.dry_run, deep_verify=args.verify,
    )
    if args.dry_run:
        return 0
    print(report.summary())
    return 0 if report.ok else 1


def _cmd_aggregate(args) -> int:
    from .outputs.netcdf_out import write_netcdf
    from .stats.aggregate import aggregate_all

    cfg = _cfg(args)
    ds = aggregate_all(
        args.cache, args.region, cfg,
        months=args.months,
        intermediate_dir=args.out / "intermediate" / args.region,
    )
    path = write_netcdf(ds, _stats_path(args.out, args.region, args), args.region, cfg)
    log.info("wrote %s (%.1f MB)", path, path.stat().st_size / 1e6)
    print(path)
    return 0


def _cmd_export(args) -> int:
    import xarray as xr

    from .fetch.cache import read_manifest
    from .outputs.csv_out import write_csv_tables
    from .outputs.parquet_out import write_parquet

    cfg = _cfg(args)
    with xr.open_dataset(_stats_path(args.out, args.region, args)) as ds:
        ds = ds.load()
    root = write_parquet(
        ds, args.out / "parquet" / ("windclim" + _tag(args)), args.region,
        derived=False,
    )
    log.info("wrote %s", root)
    written = write_csv_tables(
        ds, args.out / "csv", args.region, cfg, suffix=_tag(args),
        manifest=read_manifest(args.cache), derived=False,
    )
    for name, path in written.items():
        log.info("wrote %s", path)
        print(name)
    return 0


def _cmd_figures(args) -> int:
    import xarray as xr

    from .figures import maps, plots, style

    style.apply_style(japanese=True)
    label = REGION_LABELS.get(args.region, args.region)
    out_dir = args.out / "figures" / (args.region + _tag(args))
    with xr.open_dataset(_stats_path(args.out, args.region, args)) as ds:
        ds = ds.load()

    jobs = [
        ("F0", "sample_counts", lambda: plots.fig_sample_counts(ds, label)),
        ("F1", "alt_half_speed", lambda: plots.fig_alt_half_speed(ds, label)),
        ("F2", "alt_half_constancy", lambda: plots.fig_alt_half_constancy(ds, label)),
        ("F3", "profiles_by_month", lambda: plots.fig_profiles_by_month(ds, label)),
        ("F6", "spatial_spread", lambda: plots.fig_spatial_spread(ds, label)),
        ("F9", "shear", lambda: plots.fig_shear(ds, label)),
        ("F10", "isa_check", lambda: plots.fig_isa_check(ds, label)),
    ]
    if "hr_speed_mean" in ds:
        jobs.append(("F8", "diurnal", lambda: plots.fig_diurnal(ds, label)))

    # One rose sheet per bin. Drawing a single representative bin was a leftover
    # from the four-bin scheme, where four sheets of sixteen panels would have
    # been unreadable. With two bins both fit, and the reversal seasons are
    # exactly where the two halves of a month differ most -- which is the one
    # thing a rose shows and a mean cannot.
    for b in (int(x) for x in ds["bin"].values):
        jobs.append(
            (f"F7-{b}", "wind_roses",
             lambda bi=b: plots.fig_wind_roses(ds, label, bin_index=bi))
        )

    for month in (1, 4, 7, 10):
        jobs.append(
            (f"F4-{month:02d}", "hodograph",
             lambda m=month: plots.fig_hodograph(ds, label, m, 2))
        )
        jobs.append(
            (f"F5-{month:02d}", "map_vectors",
             lambda m=month: plots.fig_map_vectors(ds, args.region, m, 2, label=label))
        )

    # Map overlays. These are the ones that answer "where", so there are a lot of
    # them: the same field is easier to read on a coastline than on an axis pair.
    jobs += [
        ("M1-200", "month_grid_200hPa",
         lambda: maps.fig_month_grid_map(ds, args.region, label, 200.0)),
        ("M1-030", "month_grid_30hPa",
         lambda: maps.fig_month_grid_map(ds, args.region, label, 30.0)),
        ("M1-850", "month_grid_850hPa",
         lambda: maps.fig_month_grid_map(ds, args.region, label, 850.0)),
        ("M2", "constancy_map",
         lambda: maps.fig_constancy_map(ds, args.region, label)),
        ("M3-200", "direction_map_200hPa",
         lambda: maps.fig_direction_map(ds, args.region, label, 200.0)),
        ("M3-030", "direction_map_30hPa",
         lambda: maps.fig_direction_map(ds, args.region, label, 30.0)),
    ]
    for month in (1, 4, 7, 10):
        jobs.append(
            (f"M4-{month:02d}", "wind_ellipse_map",
             lambda m=month: maps.fig_wind_ellipse_map(ds, args.region, label, 200.0, m, 2))
        )
    if "drift_dist_mean_km" in ds:
        jobs += [
            ("M5", "drift_month_grid",
             lambda: maps.fig_drift_month_grid(ds, args.region, label)),
            ("M6", "drift_percentile_map",
             lambda: maps.fig_drift_percentile_map(ds, args.region, label)),
        ]
        for month in (1, 4, 7, 10):
            jobs.append(
                (f"M7-{month:02d}", "drift_map",
                 lambda m=month: maps.fig_drift_map(ds, args.region, label, m, 2))
            )
        from .outputs.csv_out import _reference_site, region_sites

        sites = region_sites(args.region)
        if not sites.empty:
            # The same named site the CSV tables and the report use, not
            # whichever one happens to come first in sites.json.
            site = _reference_site(sites, args.region)
            jobs.append(
                ("M8", "landing_ellipse_map",
                 lambda s=site: maps.fig_landing_ellipse_map(
                     ds, args.region, label, float(s["lat"]), float(s["lon"]), str(s["name"])
                 ))
            )
        else:
            centre_lat = float(ds["lat"].values[ds.sizes["lat"] // 2])
            centre_lon = float(ds["lon"].values[ds.sizes["lon"] // 2])
            jobs.append(
                ("M8", "landing_ellipse_map",
                 lambda: maps.fig_landing_ellipse_map(
                     ds, args.region, label, centre_lat, centre_lon, f"{label}中央"
                 ))
            )

    entries = []
    for figid, name, maker in jobs:
        fig = maker()
        png, pdf = plots.save(fig, out_dir, figid, name)
        entries.append({"figid": figid, "name": name, "png": png.name, "pdf": pdf.name,
                        "source": _stats_path(args.out, args.region, args).name})
        log.info("drew %s", png)
    plots.write_manifest(out_dir, entries)
    print(out_dir)
    return 0


def _cmd_summary(args) -> int:
    import xarray as xr

    from .outputs.summary import format_summary, summarise

    with xr.open_dataset(_stats_path(args.out, args.region, args)) as ds:
        ds = ds.load()
    ds.attrs.setdefault("period", f"{list(args.years)[0]}-{list(args.years)[-1]}")
    print(format_summary(summarise(ds, REGION_LABELS.get(args.region, args.region))))
    return 0


def _cmd_validate(args) -> int:
    import pickle

    import xarray as xr

    from .figures import style
    from .figures import validation as vfig
    from .outputs.validation_out import (
        format_validation,
        run_validation,
        shared_skill_max,
        write_validation_tables,
    )
    from .stats.features import build_features, features_path

    cfg = _cfg(args)
    label = REGION_LABELS.get(args.region, args.region)
    fpath = features_path(args.out, args.region, list(args.years))

    if args.stage in ("all", "features") or not fpath.exists():
        build_features(args.cache, args.region, cfg, out_path=fpath)
    if args.stage == "features":
        print(fpath)
        return 0

    # Redrawing is cheap; re-deriving is not. The by-level and by-season figures
    # share one axis across both regions, so the first region has to be redrawn
    # once the second has run -- and without this cache that redraw would repeat
    # the whole permutation test to change a single axis limit.
    cached = args.out / f"validation_{args.region}.pkl"
    if args.stage == "figures" and cached.exists():
        with cached.open("rb") as fh:
            result = pickle.load(fh)      # noqa: S301  written by this command only
        log.info("reusing %s; pass --stage all to recompute", cached)
    else:
        with xr.open_dataset(fpath) as feats:
            feats = feats.load()
        result = run_validation(feats, args.region, n_permutations=args.permutations)
        cached.parent.mkdir(parents=True, exist_ok=True)
        with cached.open("wb") as fh:
            pickle.dump(result, fh)
        write_validation_tables(result, args.out / "csv")

    if not result.placebo_ok:
        log.error(
            "weekday placebo skill %.4f exceeds the tolerance; refusing to draw "
            "figures from an unsound cross-validation", result.placebo_skill
        )
        return 1

    if args.stage in ("all", "figures"):
        style.apply_style(japanese=True)
        out_dir = args.out / "figures" / "validation"
        # Both regions share one skill axis, so the bars can be compared between
        # the two figures rather than only within each one. This reads whichever
        # regions have been written so far, so running the second region redraws
        # it correctly; re-run the first region afterwards to bring it into line.
        level_max = shared_skill_max(args.out / "csv", "by_level")
        season_max = shared_skill_max(args.out / "csv", "by_season")
        log.info("shared skill axis: by_level %s %%, by_season %s %%",
                 level_max, season_max)
        jobs = [
            ("V1", "skill_curve",
             lambda: vfig.fig_skill_curve(result.bins, label,
                                          placebo=result.placebo_skill)),
            ("V2", "harmonic", lambda: vfig.fig_harmonic_curve(result.harmonics, label)),
            ("V3", "by_level",
             lambda: vfig.fig_by_level(result.by_level, label,
                                       skill_max=level_max)),
            ("V4", "by_season",
             lambda: vfig.fig_by_season(result.by_season, label,
                                        skill_max=season_max)),
            ("V5", "variance",
             lambda: vfig.fig_variance_decomposition(result.variance, label)),
        ]
        for figid, name, maker in jobs:
            png, _ = plots_save(maker(), out_dir, f"{figid}-{args.region}", name)
            log.info("drew %s", png)

    print(format_validation(result))
    return 0


def _cmd_fidelity(args) -> int:
    import pickle

    import xarray as xr

    from .figures import fidelity as ffig
    from .figures import style
    from .outputs.fidelity_out import (
        format_fidelity,
        run_fidelity,
        write_fidelity_tables,
    )
    from .stats.features import build_features, features_path

    cfg = _cfg(args)
    label = REGION_LABELS.get(args.region, args.region)
    fpath = features_path(args.out, args.region, list(args.years))
    if not fpath.exists():
        build_features(args.cache, args.region, cfg, out_path=fpath)

    cached = args.out / f"fidelity_{args.region}.pkl"
    if args.stage == "figures" and cached.exists():
        with cached.open("rb") as fh:
            result = pickle.load(fh)      # noqa: S301  written by this command only
    else:
        with xr.open_dataset(fpath) as feats:
            feats = feats.load()
        result = run_fidelity(
            feats, args.cache, args.region, cfg, dt=args.dt,
            with_trajectories=args.stage in ("all", "trajectories"),
        )
        with cached.open("wb") as fh:
            pickle.dump(result, fh)
        for path in write_fidelity_tables(result, args.out):
            log.info("wrote %s", path)

    if args.stage in ("all", "figures"):
        style.apply_style(japanese=True)
        out_dir = args.out / "figures" / "fidelity"
        jobs = [
            ("G1", "change_curve", lambda: ffig.fig_change_curve(result.lag_wind, label)),
            ("G2", "decorrelation",
             lambda: ffig.fig_decorrelation(result.decorrelation, label)),
            ("G3", "direction_change",
             lambda: ffig.fig_direction_change(result.direction, label)),
            ("G4", "slip_curve", lambda: ffig.fig_slip_curve(result.slip, label)),
            ("G6", "variance_split",
             lambda: ffig.fig_variance_split(result.variance, label)),
        ]
        if not result.error.empty:
            jobs.append(
                ("G5", "error_breakdown",
                 lambda: ffig.fig_error_breakdown(result.error, label))
            )
        for figid, name, maker in jobs:
            png, _ = plots_save(maker(), out_dir, f"{figid}-{args.region}", name)
            log.info("drew %s", png)

        # One flight per season, drawn on the coastline. A winter case and a
        # summer case bracket the range; the two shoulder seasons sit between
        # them and would add length without adding a reading.
        from .outputs.fidelity_out import example_tracks  # noqa: PLC0415

        for month, season in ((1, "冬"), (7, "夏")):
            tracks, launch, gap = example_tracks(
                args.cache, args.region, cfg, 2020, month
            )
            fig = ffig.fig_trajectory_map(
                tracks, launch, label,
                f"2020年{month}月15日 00 UTC の一例（{season}・現行との差 {gap:.1f} km）",
            )
            png, _ = plots_save(
                fig, out_dir, f"G7-{month:02d}-{args.region}", "trajectory_map"
            )
            log.info("drew %s", png)

    text = format_fidelity(result)
    (args.out / "csv" / f"fidelity_summary_{args.region}.txt").write_text(
        text, encoding="utf-8"
    )
    print(text)
    return 0


def _cmd_winter(args) -> int:
    from .figures import style
    from .figures.windsample_fig import fig_landing_clouds, fig_speed_fits
    from .outputs.windsample_out import run_winter_study, write_winter_tables

    cfg = _cfg(args)
    label = REGION_LABELS.get(args.region, args.region)
    study = run_winter_study(
        args.cache, _stats_path(args.out, args.region, args), args.region, cfg,
        season=args.season, n=args.samples,
    )
    for path in write_winter_tables(study, args.out):
        log.info("wrote %s", path)

    style.apply_style(japanese=True)
    out_dir = args.out / "figures" / (args.region + _tag(args))
    png, _ = plots_save(
        fig_speed_fits(study.model, study.u, study.v, label), out_dir, "A1", "speed_fits"
    )
    log.info("drew %s", png)
    png, _ = plots_save(
        fig_landing_clouds(study.clouds, label), out_dir, "A3", "landing_clouds"
    )
    log.info("drew %s", png)

    # The map needs a cached terrain tile. Draw it when one is available and
    # say what to run when it is not, rather than reaching for the network
    # from inside a plotting call.
    from .fetch.terrain import load_terrain, size_for  # noqa: PLC0415
    from .figures.windsample_fig import fig_landing_map  # noqa: PLC0415
    from .outputs.windsample_out import terrain_box  # noqa: PLC0415

    box = terrain_box(study)
    dem_w, dem_h = size_for(box, width=args.dem_width)
    if args.dem_height is not None:
        dem_h = args.dem_height
    try:
        tile = load_terrain(box, width=dem_w, height=dem_h,
                            cache_root=args.cache, allow_fetch=args.fetch_dem)
    except FileNotFoundError as exc:
        log.warning("%s", exc)
        log.warning("skipping the terrain map; pass --fetch-dem to download it")
    else:
        png, _ = plots_save(
            fig_landing_map(tile, study.clouds, study.launch_lat, study.launch_lon,
                            label),
            out_dir, "A2", "landing_map",
        )
        log.info("drew %s", png)

    print(study.spread_table().to_string(index=False, float_format=lambda x: f"{x:.1f}"))
    return 0


def plots_save(fig, out_dir, figid, name):
    from .figures.plots import save

    return save(fig, out_dir, figid, name)


def _cmd_compare(args) -> int:
    import xarray as xr

    from .figures import maps, plots, style

    style.apply_style(japanese=True)
    # Match the default product exactly. A substring test also matches the
    # tagged variants (``..._week_v1.nc``, ``..._jst_v1.nc``), and since they
    # sort after the plain file they would silently win, drawing the comparison
    # from a different binning than the rest of the report.
    years = list(args.years) if hasattr(args, "years") else list(YEARS)
    by_region = {}
    for region in REGIONS:
        want = (
            args.out / "netcdf"
            / f"jra3q_windclim_{region}_{years[0]}-{years[-1]}_v1.nc"
        )
        if want.exists():
            by_region[region] = want
    if len(by_region) < 2:
        raise SystemExit(
            "need at least two regions aggregated first; "
            f"found {sorted(by_region)} in {args.out / 'netcdf'}"
        )
    out_dir = args.out / "figures" / "compare"
    loaded = {}
    for region, path in by_region.items():
        with xr.open_dataset(path) as ds:
            loaded[region] = ds.load()
    # Pairs, not all against all: Hokkaido against Wakayama is the north-south
    # contrast; Wakayama against Ehime shows how little 2 deg of longitude
    # changes along the same latitude band.
    for first, second, tag in (("hokkaido", "wakayama", "F11"),
                               ("wakayama", "ehime", "F11b")):
        if first in loaded and second in loaded:
            fig = plots.fig_region_comparison(
                loaded[first], loaded[second],
                REGION_LABELS[first], REGION_LABELS[second],
            )
            png, _ = plots.save(fig, out_dir, tag, "region_comparison")
            log.info("drew %s", png)
    for month in (1, 7):
        over = maps.fig_overview_map(loaded, month=month, labels=REGION_LABELS)
        p2, _ = plots.save(over, out_dir, f"M0-{month:02d}", "overview_map")
        log.info("drew %s", p2)

    import pandas as pd  # noqa: PLC0415

    from .figures import validation as vfig  # noqa: PLC0415

    curves = {}
    for region in loaded:
        csv = args.out / "csv" / f"timescale_{region}.csv"
        if csv.exists():
            curves[REGION_LABELS.get(region, region)] = pd.read_csv(csv)
    if len(curves) >= 2:
        p4, _ = plots.save(vfig.fig_region_comparison(curves),
                           args.out / "figures" / "validation", "V6", "region_comparison")
        log.info("drew %s", p4)

    # Not a result, but the reasoning behind the data chapter's choice of
    # product. Drawn here because it needs no dataset at all.
    from .figures.reanalyses import fig_reanalysis_comparison  # noqa: PLC0415

    p3, _ = plots.save(fig_reanalysis_comparison(), out_dir, "F12", "reanalyses")
    log.info("drew %s", p3)
    print(out_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    handlers = {
        "fetch": _cmd_fetch,
        "aggregate": _cmd_aggregate,
        "export": _cmd_export,
        "figures": _cmd_figures,
        "summary": _cmd_summary,
        "validate": _cmd_validate,
        "fidelity": _cmd_fidelity,
        "winter": _cmd_winter,
        "compare": _cmd_compare,
    }
    if args.command == "all":
        for step in ("aggregate", "export", "figures"):
            rc = handlers[step](args)
            if rc:
                return rc
        return 0
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
