"""Supporting evidence for the time-resolution answer.

:mod:`windclim.stats.timescale` settles the main question by cross-validation.
This module adds three things it does not:

* **How much** the climatology explains, as a fraction of the total variance --
  cross-validation says which model is best, not whether the best is any good.
* A **formal null test** on the bin labels, kept honest by shuffling whole
  synoptic runs rather than individual analyses.
* **Reproducibility**: would a different decade have produced the same picture?

On the null test: the paired fold comparison in
:meth:`~windclim.stats.timescale.BinCVResult.paired_difference` is already an
exact sign test -- ten out of ten folds agreeing is p = 0.002 two-sided, with no
resampling at all. The permutation test is kept because it tests a different
null (that the label carries no information, rather than that one model beats
another), and because two routes agreeing is worth more than either alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "VarianceParts",
    "block_labels",
    "block_permutation_test",
    "between_group_variance",
    "split_half_correlation",
    "variance_decomposition",
]


# --- how much does the climatology explain? ----------------------------------


@dataclass(frozen=True)
class VarianceParts:
    """Total variance split into the parts a climatology can and cannot reach."""

    total: float
    between_bins: float
    within_bins: float
    interannual: float

    @property
    def eta_squared(self) -> float:
        """Fraction of the variance the bin labels account for."""
        return self.between_bins / self.total if self.total > 0 else float("nan")


def variance_decomposition(
    values: NDArray, bin_labels: NDArray[np.int64], years: NDArray[np.int64]
) -> VarianceParts:
    """Split the variance into seasonal, synoptic and interannual parts.

    ``between_bins`` is what a climatology can predict. ``within_bins`` is the
    day-to-day weather it cannot. ``interannual`` is how much a given bin's mean
    moves from year to year, which is the part that makes narrow bins fail to
    generalise even when the underlying signal is real.
    """
    v = np.asarray(values, dtype=np.float64).reshape(len(values), -1)
    labels = np.asarray(bin_labels)
    years = np.asarray(years)

    grand = np.nanmean(v, axis=0)
    total = float(np.nanmean((v - grand) ** 2))

    bins = np.unique(labels)
    between = 0.0
    within = 0.0
    inter = 0.0
    for b in bins:
        m = labels == b
        if not m.any():
            continue
        w = m.mean()
        bin_mean = np.nanmean(v[m], axis=0)
        between += w * float(np.nanmean((bin_mean - grand) ** 2))
        within += w * float(np.nanmean((v[m] - bin_mean) ** 2))
        per_year = [
            np.nanmean(v[m & (years == y)], axis=0)
            for y in np.unique(years[m])
            if (m & (years == y)).any()
        ]
        if len(per_year) > 1:
            inter += w * float(np.nanmean(np.nanvar(np.stack(per_year), axis=0, ddof=1)))
    return VarianceParts(total=total, between_bins=between, within_bins=within,
                         interannual=inter)


# --- the null test -----------------------------------------------------------


def between_group_variance(values: NDArray, labels: NDArray[np.int64]) -> float:
    """Weighted variance of the group means -- the statistic the null test uses."""
    v = np.asarray(values, dtype=np.float64).reshape(len(values), -1)
    labels = np.asarray(labels)
    grand = np.nanmean(v, axis=0)
    out = 0.0
    for b in np.unique(labels):
        m = labels == b
        out += m.mean() * float(np.nanmean((np.nanmean(v[m], axis=0) - grand) ** 2))
    return out


def block_labels(
    years: NDArray[np.int64], bin_labels: NDArray[np.int64]
) -> NDArray[np.int64]:
    """Group samples into contiguous (year, bin) runs.

    These runs are the unit that gets shuffled. Permuting individual 6-hourly
    analyses instead would destroy the autocorrelation, shrink the null
    distribution and make almost anything look significant -- the single easiest
    way to get a spuriously confident answer out of a test like this.
    """
    years = np.asarray(years)
    bins = np.asarray(bin_labels)
    key = years.astype(np.int64) * (int(bins.max()) + 1) + bins
    _, inverse = np.unique(key, return_inverse=True)
    return inverse.astype(np.int64)


def _nests_inside(fine: NDArray[np.int64], coarse: NDArray[np.int64]) -> bool:
    """Does each fine label belong to exactly one coarse group?"""
    fine = np.asarray(fine)
    coarse = np.asarray(coarse)
    return all(np.unique(coarse[fine == f]).size == 1 for f in np.unique(fine))


def block_permutation_test(
    values: NDArray,
    bin_labels: NDArray[np.int64],
    years: NDArray[np.int64],
    *,
    within: NDArray[np.int64] | None = None,
    n_permutations: int = 1000,
    seed: int = 0,
) -> dict:
    """Is the between-bin spread larger than relabelling whole runs would give?

    ``within`` restricts the shuffle to happen inside each of its groups. Passing
    the month there asks the sharper question -- *does the half carry information
    beyond the month?* -- rather than the near-certain one about whether the year
    has seasons at all.

    For that question to be well posed the fine bins must **nest** inside the
    coarse ones. If a half bin straddles a month boundary it carries a mixture of
    two months, shuffling it moves that mixture around, and the test reports
    structure that belongs to the month rather than to the half. The four
    fixed day-of-month halves used elsewhere in this package nest by construction;
    an evenly spaced 52-bin year does not.
    """
    if within is not None and not _nests_inside(bin_labels, within):
        raise ValueError(
            "bin_labels must nest inside `within`: every fine bin has to lie "
            "entirely within one coarse group, or the test attributes the "
            "coarse structure to the fine labels"
        )
    labels = np.asarray(bin_labels)
    blocks = block_labels(years, labels)
    rng = np.random.default_rng(seed)

    n_blocks = int(blocks.max()) + 1
    block_label = np.zeros(n_blocks, dtype=np.int64)
    block_within = np.zeros(n_blocks, dtype=np.int64)
    for b in range(n_blocks):
        first = int(np.flatnonzero(blocks == b)[0])
        block_label[b] = labels[first]
        block_within[b] = 0 if within is None else np.asarray(within)[first]

    observed = between_group_variance(values, labels)
    null = np.empty(n_permutations)
    for i in range(n_permutations):
        shuffled = block_label.copy()
        for g in np.unique(block_within):
            m = block_within == g
            shuffled[m] = rng.permutation(shuffled[m])
        null[i] = between_group_variance(values, shuffled[blocks])

    p = float((np.count_nonzero(null >= observed) + 1) / (n_permutations + 1))
    return {
        "observed": observed,
        "null_median": float(np.median(null)),
        "null_p95": float(np.percentile(null, 95)),
        "p_value": p,
        "n_permutations": n_permutations,
        "n_blocks": n_blocks,
    }


# --- would another decade have shown the same thing? -------------------------


def split_half_correlation(
    values: NDArray,
    bin_labels: NDArray[np.int64],
    years: NDArray[np.int64],
    *,
    remove: NDArray[np.int64] | None = None,
) -> dict:
    """Pattern correlation between climatologies built from each half of the years.

    ``remove`` subtracts a coarser grouping's mean first, so the correlation
    describes only the structure the finer grouping adds. Without that, a strong
    annual cycle makes everything correlate at 0.99 and the question of whether
    the *half* reproduces goes unanswered.
    """
    v = np.asarray(values, dtype=np.float64).reshape(len(values), -1)
    labels = np.asarray(bin_labels)
    years = np.asarray(years)
    uniq = np.unique(years)
    first, second = uniq[: len(uniq) // 2], uniq[len(uniq) // 2:]

    if remove is not None:
        coarse = np.asarray(remove)
        for c in np.unique(coarse):
            m = coarse == c
            v = v.copy()
            v[m] -= np.nanmean(v[m], axis=0)

    def climatology(mask):
        return np.stack([
            np.nanmean(v[mask & (labels == b)], axis=0)
            if (mask & (labels == b)).any() else np.full(v.shape[1], np.nan)
            for b in np.unique(labels)
        ])

    a = climatology(np.isin(years, first)).ravel()
    b = climatology(np.isin(years, second)).ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return {"correlation": float("nan"), "n": int(ok.sum())}
    r = float(np.corrcoef(a[ok], b[ok])[0, 1])
    return {
        "correlation": r,
        "n": int(ok.sum()),
        "first_years": [int(y) for y in first],
        "second_years": [int(y) for y in second],
    }
