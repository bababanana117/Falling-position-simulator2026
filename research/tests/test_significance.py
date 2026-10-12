"""Variance decomposition, the block permutation null, and split-half reproducibility.

As in :mod:`tests.test_timescale`, the point of these tests is to check the
*method* on inputs whose answer is known. The permutation test in particular has
a well-known failure mode -- shuffling autocorrelated samples individually -- and
that failure is reproduced here deliberately so the fix can be shown to work.
"""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import significance as sig
from windclim.stats import timescale as ts

from .test_timescale import synthetic_times

TIMES = synthetic_times()
DOY = ts.day_of_year_fraction(TIMES)
YEARS = ts.year_of(TIMES)
# Four half bins per month, so the fine labels nest inside the coarse ones --
# the condition the within-group permutation needs (see block_permutation_test).
WEEKISH = ts.bin_index(DOY, 48)
MONTH = WEEKISH // 4


# --- variance decomposition --------------------------------------------------


def test_pure_noise_has_almost_no_between_bin_variance() -> None:
    rng = np.random.default_rng(0)
    v = rng.normal(0, 1.0, (DOY.size, 1))
    parts = sig.variance_decomposition(v, MONTH, YEARS)
    assert parts.eta_squared < 0.01


def test_a_strong_seasonal_cycle_dominates_the_variance() -> None:
    v = (10.0 * np.sin(2 * np.pi * DOY))[:, None]
    parts = sig.variance_decomposition(v, MONTH, YEARS)
    assert parts.eta_squared > 0.9


def test_the_parts_add_up_to_the_total() -> None:
    rng = np.random.default_rng(1)
    v = (5.0 * np.sin(2 * np.pi * DOY) + rng.normal(0, 3.0, DOY.size))[:, None]
    parts = sig.variance_decomposition(v, MONTH, YEARS)
    assert parts.between_bins + parts.within_bins == pytest.approx(parts.total, rel=1e-6)


def test_a_known_variance_ratio_is_recovered() -> None:
    """Signal variance 8, noise variance 2, so eta^2 should be about 0.8."""
    rng = np.random.default_rng(2)
    signal = 4.0 * np.sin(2 * np.pi * MONTH / 12.0)      # variance 8
    v = (signal + rng.normal(0, 2.0, DOY.size))[:, None]  # variance 4
    parts = sig.variance_decomposition(v, MONTH, YEARS)
    assert parts.eta_squared == pytest.approx(8 / 12, abs=0.05)


def test_interannual_variability_is_reported_separately() -> None:
    """A signal that shifts every year has a big interannual part, which is what
    makes narrow bins fail to generalise even when the signal is real."""
    rng = np.random.default_rng(3)
    offset = {y: rng.normal(0, 5.0) for y in np.unique(YEARS)}
    v = np.array([offset[y] for y in YEARS])[:, None]
    parts = sig.variance_decomposition(v, MONTH, YEARS)
    assert parts.interannual > 10.0


# --- the block permutation null ----------------------------------------------


def test_noise_is_not_significant() -> None:
    rng = np.random.default_rng(4)
    v = rng.normal(0, 1.0, (DOY.size, 1))
    r = sig.block_permutation_test(v, MONTH, YEARS, n_permutations=200, seed=0)
    assert r["p_value"] > 0.05


def test_a_real_seasonal_cycle_is_significant() -> None:
    rng = np.random.default_rng(5)
    v = (10.0 * np.sin(2 * np.pi * DOY) + rng.normal(0, 1.0, DOY.size))[:, None]
    r = sig.block_permutation_test(v, MONTH, YEARS, n_permutations=200, seed=0)
    assert r["p_value"] < 0.01
    assert r["observed"] > r["null_p95"]


def test_shuffling_single_samples_would_give_a_false_positive() -> None:
    """The reason whole runs are shuffled, demonstrated rather than asserted.

    An autocorrelated series with no seasonal cycle at all looks highly
    significant if the samples are permuted one at a time, because the null
    distribution then describes independent data that the real series is not.
    Permuting whole runs keeps the correlation and the false positive goes away.
    """
    rng = np.random.default_rng(6)
    x = np.zeros(DOY.size)
    for i in range(1, x.size):
        x[i] = 0.995 * x[i - 1] + rng.normal(0, 1.0)
    v = x[:, None]

    observed = sig.between_group_variance(v, MONTH)
    naive_null = np.array([
        sig.between_group_variance(v, rng.permutation(MONTH)) for _ in range(200)
    ])
    naive_p = (np.count_nonzero(naive_null >= observed) + 1) / 201
    blocked_p = sig.block_permutation_test(
        v, MONTH, YEARS, n_permutations=200, seed=1
    )["p_value"]

    assert naive_p < 0.01        # the wrong test is confidently wrong
    assert blocked_p > naive_p   # the right test is not fooled as easily


def test_blocks_are_contiguous_runs() -> None:
    blocks = sig.block_labels(YEARS, MONTH)
    assert blocks.max() + 1 == len(np.unique(YEARS)) * len(np.unique(MONTH))


def test_non_nesting_bins_are_rejected() -> None:
    """A 52-bin year does not nest inside 12 months, so the question would be
    ill-posed and the test says so rather than answering it wrongly."""
    v = np.zeros((DOY.size, 1))
    with pytest.raises(ValueError, match="nest"):
        sig.block_permutation_test(
            v, ts.bin_index(DOY, 52), YEARS, within=(DOY * 12).astype(int),
            n_permutations=10,
        )


def test_restricting_the_shuffle_asks_the_sharper_question() -> None:
    """With a signal that varies between months but not within them, shuffling
    half labels inside each month must find nothing."""
    rng = np.random.default_rng(7)
    v = (10.0 * np.sin(2 * np.pi * MONTH / 12.0) + rng.normal(0, 1.0, DOY.size))[:, None]
    free = sig.block_permutation_test(v, WEEKISH, YEARS, n_permutations=200, seed=2)
    inside = sig.block_permutation_test(
        v, WEEKISH, YEARS, within=MONTH, n_permutations=200, seed=2
    )
    assert free["p_value"] < 0.01        # "is there a seasonal cycle" -- yes
    assert inside["p_value"] > 0.05      # "does the half add to the month" -- no


# --- reproducibility ---------------------------------------------------------


def test_a_reproducible_signal_correlates_across_halves() -> None:
    rng = np.random.default_rng(8)
    v = (10.0 * np.sin(2 * np.pi * DOY) + rng.normal(0, 1.0, DOY.size))[:, None]
    r = sig.split_half_correlation(v, MONTH, YEARS)
    assert r["correlation"] > 0.98
    assert r["first_years"] == [2016, 2017, 2018, 2019, 2020]


def test_noise_does_not_correlate_across_halves() -> None:
    rng = np.random.default_rng(9)
    v = rng.normal(0, 1.0, (DOY.size, 1))
    r = sig.split_half_correlation(v, MONTH, YEARS)
    assert abs(r["correlation"]) < 0.6


def test_removing_the_coarse_mean_isolates_the_finer_structure() -> None:
    """A signal with monthly structure but nothing inside the month: after the
    monthly mean is removed, the half-monthly pattern must stop reproducing."""
    rng = np.random.default_rng(10)
    v = (10.0 * np.sin(2 * np.pi * MONTH / 12.0) + rng.normal(0, 2.0, DOY.size))[:, None]
    raw = sig.split_half_correlation(v, WEEKISH, YEARS)
    residual = sig.split_half_correlation(v, WEEKISH, YEARS, remove=MONTH)
    assert raw["correlation"] > 0.9
    assert residual["correlation"] < 0.5
