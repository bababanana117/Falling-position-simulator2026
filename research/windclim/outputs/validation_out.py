"""Run the time-resolution study and write its tables.

Order matters here. The weekday placebo runs first and its result is carried in
every output, because a non-zero placebo skill would invalidate everything
below it. Reporting the answer without reporting that check would be reporting
half of it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ..stats import significance as sig
from ..stats import timescale as ts

__all__ = [
    "ValidationResult",
    "run_validation",
    "shared_skill_max",
    "write_validation_tables",
]

log = logging.getLogger(__name__)

SEASONS = {"冬 (12-2月)": (12, 1, 2), "春 (3-5月)": (3, 4, 5),
           "夏 (6-8月)": (6, 7, 8), "秋 (9-11月)": (9, 10, 11)}

#: Above this, a placebo predictor is showing skill it cannot have, and the
#: cross-validation is not to be trusted.
PLACEBO_TOLERANCE = 0.02

#: The bin width the product ships. Quoted in the summary so the table that
#: justifies the choice also shows where the choice landed.
SHIPPED_DAYS = 15.0


@dataclass
class ValidationResult:
    region: str
    placebo_skill: float
    bins: pd.DataFrame
    harmonics: pd.DataFrame
    by_level: pd.DataFrame
    by_season: pd.DataFrame
    variance: pd.DataFrame
    headline: dict = field(default_factory=dict)

    @property
    def placebo_ok(self) -> bool:
        return abs(self.placebo_skill) < PLACEBO_TOLERANCE


def _target(ds: xr.Dataset) -> np.ndarray:
    """Landing displacement in km, shape ``(time, cell, 2)``."""
    dx = ds["dx_east_m"].values.reshape(ds.sizes["time"], -1)
    dy = ds["dy_north_m"].values.reshape(ds.sizes["time"], -1)
    return np.stack([dx, dy], axis=-1) / 1000.0


def _bin_frame(r: ts.BinCVResult, reference_days: float | None = None) -> pd.DataFrame:
    pair = r.paired_difference(reference_days)
    order = np.argsort(-r.granularity_days)
    return pd.DataFrame(
        {
            "granularity_days": r.granularity_days[order],
            "train_rmse_km": r.train_rmse[order],
            "test_rmse_km": r.test_rmse[order],
            "skill": r.skill[order],
            "variance_explained": 1.0 - (1.0 - r.skill[order]) ** 2,
            "samples_per_bin": r.n_per_bin[order],
            "vs_best_km": pair["mean"][order],
            "vs_best_sem_km": pair["sem"][order],
            "vs_best_sigma": pair["mean"][order] / np.maximum(pair["sem"][order], 1e-12),
            "folds_better": pair["wins"][order],
        }
    )


def run_validation(
    features: xr.Dataset,
    region: str,
    *,
    granularities=ts.DEFAULT_GRANULARITIES_DAYS,
    k_values=range(0, 27),
    n_permutations: int = 500,
) -> ValidationResult:
    """The whole study for one region, from the per-analysis feature table."""
    t = features["time"].values
    doy = ts.day_of_year_fraction(t)
    years = ts.year_of(t)
    target = _target(features)
    month = (doy * 12).astype(int) + 1

    log.info("%s: weekday placebo", region)
    placebo = ts.loyo_label_skill(target, ts.weekday_labels(t), years, vector_axis=-1)
    if abs(placebo) >= PLACEBO_TOLERANCE:
        log.error(
            "weekday placebo showed skill %.4f; the cross-validation is unsound "
            "and the rest of this run must not be believed", placebo
        )

    log.info("%s: bin-width cross-validation", region)
    r = ts.loyo_bin_cv(target, doy, years, granularities, vector_axis=-1)
    bins = _bin_frame(r)
    lo, hi = r.resolved_range()
    recommended = r.parsimonious_days

    log.info("%s: harmonic cross-validation", region)
    h = ts.loyo_harmonic_cv(target, doy, years, k_values, vector_axis=-1)
    harmonics = pd.DataFrame(
        {
            "k": h.k_values,
            "resolution_days": [ts.harmonic_resolution_days(int(k)) for k in h.k_values],
            "test_rmse_km": h.test_rmse,
            "train_rmse_km": h.train_rmse,
            "skill": h.skill,
        }
    )

    log.info("%s: by altitude", region)
    rows = []
    for pi, p in enumerate(features["plevel"].values):
        w = np.stack(
            [
                features["u"].values[:, pi].reshape(len(t), -1),
                features["v"].values[:, pi].reshape(len(t), -1),
            ],
            axis=-1,
        )
        rw = ts.loyo_bin_cv(w, doy, years, granularities, vector_axis=-1)
        a, b = rw.resolved_range()
        rows.append(
            {
                "level_hpa": float(p),
                "best_days": rw.best_days,
                "recommended_days": rw.parsimonious_days,
                "resolved_lo_days": a,
                "resolved_hi_days": b,
                "skill": rw.best_skill,
                "variance_explained": 1.0 - (1.0 - rw.best_skill) ** 2,
                "baseline_rmse_ms": float(rw.test_rmse[np.argmax(rw.granularity_days)]),
                "best_rmse_ms": float(rw.test_rmse.min()),
            }
        )
    by_level = pd.DataFrame(rows)

    log.info("%s: by season", region)
    rows = []
    for name, months in SEASONS.items():
        m = np.isin(month, months)
        rs = ts.loyo_bin_cv(target[m], doy[m], years[m], granularities, vector_axis=-1)
        a, b = rs.resolved_range()
        rows.append(
            {
                "season": name,
                "best_days": rs.best_days,
                "recommended_days": rs.parsimonious_days,
                "resolved_lo_days": a,
                "resolved_hi_days": b,
                "skill": rs.best_skill,
                "baseline_rmse_km": float(rs.test_rmse[np.argmax(rs.granularity_days)]),
                "best_rmse_km": float(rs.test_rmse.min()),
            }
        )
    by_season = pd.DataFrame(rows)

    log.info("%s: variance decomposition and null tests", region)
    rows = []
    for label, width in (("月 (30日)", 30.0), ("週 (7日)", 7.0), ("日 (1日)", 1.0)):
        labels = ts.bin_index(doy, ts.n_bins_for(width))
        parts = sig.variance_decomposition(target, labels, years)
        half = sig.split_half_correlation(target, labels, years)
        perm = sig.block_permutation_test(
            target, labels, years, n_permutations=n_permutations
        )
        rows.append(
            {
                "grouping": label,
                "eta_squared": parts.eta_squared,
                "between_bins": parts.between_bins,
                "within_bins": parts.within_bins,
                "interannual": parts.interannual,
                "split_half_r": half["correlation"],
                "permutation_p": perm["p_value"],
            }
        )
    # Does the half add anything to the month? Nested bins, shuffled inside months.
    fine = ts.bin_index(doy, 48)
    coarse = fine // 4
    nested = sig.block_permutation_test(
        target, fine, years, within=coarse, n_permutations=n_permutations
    )
    residual = sig.split_half_correlation(target, fine, years, remove=coarse)
    rows.append(
        {
            "grouping": "週 (月内の残差)",
            "eta_squared": float("nan"),
            "between_bins": nested["observed"],
            "within_bins": float("nan"),
            "interannual": float("nan"),
            "split_half_r": residual["correlation"],
            "permutation_p": nested["p_value"],
        }
    )
    variance = pd.DataFrame(rows)

    i7 = int(np.argmin(np.abs(r.granularity_days - 7.0)))
    i30 = int(np.argmin(np.abs(r.granularity_days - 30.0)))
    i1 = int(np.argmin(np.abs(r.granularity_days - 1.0)))
    # The width the product actually ships, so the table that justifies the
    # choice also contains it.
    i_shipped = int(np.argmin(np.abs(r.granularity_days - SHIPPED_DAYS)))
    pair = r.paired_difference()
    headline = {
        "region": region,
        "placebo_skill": placebo,
        "baseline_rmse_km": float(r.test_rmse[np.argmax(r.granularity_days)]),
        "best_rmse_km": float(r.test_rmse.min()),
        "best_days": r.best_days,
        "recommended_days": recommended,
        "resolved_lo_days": lo,
        "resolved_hi_days": hi,
        "skill": r.best_skill,
        "variance_explained": 1.0 - (1.0 - r.best_skill) ** 2,
        "harmonic_best_k": h.best_k,
        "harmonic_recommended_k": h.parsimonious_k,
        "harmonic_resolution_days": h.best_resolution_days,
        "harmonic_recommended_resolution_days": ts.harmonic_resolution_days(
            h.parsimonious_k
        ),
        "harmonic_best_rmse_km": float(h.test_rmse.min()),
        "week_vs_best_km": float(pair["mean"][i7]),
        "week_vs_best_sigma": float(pair["mean"][i7] / max(pair["sem"][i7], 1e-12)),
        "month_vs_best_km": float(pair["mean"][i30]),
        "month_vs_best_sigma": float(pair["mean"][i30] / max(pair["sem"][i30], 1e-12)),
        "day_vs_best_km": float(pair["mean"][i1]),
        "day_vs_best_sigma": float(pair["mean"][i1] / max(pair["sem"][i1], 1e-12)),
        "shipped_days": SHIPPED_DAYS,
        "shipped_vs_best_km": float(pair["mean"][i_shipped]),
        "shipped_vs_best_sigma": float(
            pair["mean"][i_shipped] / max(pair["sem"][i_shipped], 1e-12)
        ),
        "week_adds_to_month_p": nested["p_value"],
        "week_residual_split_half_r": residual["correlation"],
    }
    return ValidationResult(region, placebo, bins, harmonics, by_level, by_season,
                            variance, headline)


def format_validation(v: ValidationResult) -> str:
    h = v.headline
    lines = [
        f"=== {v.region} 時間解像度の検証 ===",
        "",
        f"曜日プラセボ: skill = {v.placebo_skill:+.4f}  "
        f"{'OK（手法は健全）' if v.placebo_ok else 'FAIL（以下の結果は信用できない）'}",
        "",
        f"季節情報なしの誤差      : {h['baseline_rmse_km']:.1f} km",
        f"到達できる最小誤差      : {h['best_rmse_km']:.1f} km（ビン幅 {h['best_days']:.0f} 日）",
        f"推奨するビン幅          : {h['recommended_days']:.0f} 日"
        "（同点なら粗い方を採る。1 標準誤差ルール）",
        f"誤差の削減              : {100 * h['skill']:.0f} %"
        f"（分散でいえば {100 * h['variance_explained']:.0f} %）",
        f"区別できないビン幅の範囲: {h['resolved_lo_days']:.0f} 〜 {h['resolved_hi_days']:.0f} 日",
        "",
        f"調和解析: 最適 K = {h['harmonic_best_k']}"
        f"（分解能 {h['harmonic_resolution_days']:.0f} 日）"
        f"、誤差 {h['harmonic_best_rmse_km']:.1f} km"
        f"  / 推奨 K = {h['harmonic_recommended_k']}"
        f"（分解能 {h['harmonic_recommended_resolution_days']:.0f} 日）",
        "",
        "最良との差（対応のある比較、10 年で対にする）:",
        f"  日 (1 日) : {h['day_vs_best_km']:+.2f} km  ({h['day_vs_best_sigma']:+.1f} SE)",
        f"  週 (7 日) : {h['week_vs_best_km']:+.2f} km  ({h['week_vs_best_sigma']:+.1f} SE)",
        f"  半月 ({h['shipped_days']:.0f} 日) : {h['shipped_vs_best_km']:+.2f} km  "
        f"({h['shipped_vs_best_sigma']:+.1f} SE)  <- 本統計が採用",
        f"  月 (30 日): {h['month_vs_best_km']:+.2f} km  ({h['month_vs_best_sigma']:+.1f} SE)",
        "",
        f"週は月に情報を加えるか: 順列検定 p = {h['week_adds_to_month_p']:.3f}、"
        f"月内残差の半分割相関 = {h['week_residual_split_half_r']:+.2f}",
        "",
        "高度別:",
        f"  {'hPa':>6} {'最適[日]':>9} {'区別できない':>14} {'誤差削減':>9}",
    ]
    for _, row in v.by_level.iterrows():
        lines.append(
            f"  {row['level_hpa']:6.0f} {row['best_days']:9.0f} "
            f"{f'{row.resolved_lo_days:.0f}-{row.resolved_hi_days:.0f} 日':>14} "
            f"{100 * row['skill']:8.0f} %"
        )
    lines += ["", "季節別:", f"  {'季節':<12} {'最適[日]':>9} {'区別できない':>14} {'誤差削減':>9}"]
    for _, row in v.by_season.iterrows():
        lines.append(
            f"  {row['season']:<12} {row['best_days']:9.0f} "
            f"{f'{row.resolved_lo_days:.0f}-{row.resolved_hi_days:.0f} 日':>14} "
            f"{100 * row['skill']:8.0f} %"
        )
    return "\n".join(lines)


def shared_skill_max(out_dir: Path, kind: str, *,
                     regions=("hokkaido", "wakayama", "ehime")) -> float | None:
    """The skill axis limit that lets the regions' figures be compared by eye.

    ``kind`` is ``"by_level"`` or ``"by_season"``. Reads whichever regions have
    already been written and returns the largest skill among them, in percent,
    rounded up to a round number.

    Without this each figure scales to its own data, and the region with the
    weaker signal gets bars just as long as the region with the stronger one.
    For the season breakdown that would put Hokkaido's 5 percent and Wakayama's
    34 percent at the same width, which is the opposite of the chapter's point.
    Returns ``None`` when nothing has been written yet, so a first run still
    draws something rather than failing.
    """
    out_dir = Path(out_dir)
    best = 0.0
    for region in regions:
        path = out_dir / f"timescale_{kind}_{region}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "skill" in frame and frame["skill"].notna().any():
            best = max(best, float(frame["skill"].max()))
    if best <= 0.0:
        return None
    pct = 100.0 * best
    step = 5.0 if pct < 40.0 else 10.0
    return float(np.ceil(pct / step) * step)


def write_validation_tables(v: ValidationResult, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, frame in (
        (f"timescale_{v.region}.csv", v.bins),
        (f"timescale_harmonic_{v.region}.csv", v.harmonics),
        (f"timescale_by_level_{v.region}.csv", v.by_level),
        (f"timescale_by_season_{v.region}.csv", v.by_season),
        (f"timescale_variance_{v.region}.csv", v.variance),
    ):
        path = out_dir / name
        frame.to_csv(path, index=False, float_format="%.5g")
        written[name] = path
    path = out_dir / f"validation_summary_{v.region}.txt"
    path.write_text(format_validation(v), encoding="utf-8")
    written[path.name] = path
    return written
