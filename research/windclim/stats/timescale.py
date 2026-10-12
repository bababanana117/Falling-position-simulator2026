"""At what time resolution does the seasonal signal stop and the noise start?

The rest of this package bins the year into fixed day-of-month halves. That unit
was chosen because it is how a launch campaign is planned, which says nothing
about whether the data supports it. This module asks the question properly.

It is a model-selection problem, not a hypothesis test, and it has a decisive
shape. Narrow the bins and the climatology fits the ten years in hand better and
better, while each bin holds fewer samples and generalises worse. Leave one year
out, predict it from the other nine, and plot the error against bin width:

* the **training** error falls monotonically as the bins narrow -- that is
  overfitting, and seeing it is how you know the fit is working at all;
* the **validation** error bottoms out somewhere and rises again.

**The minimum of the validation curve is the finest time unit the data supports.**
Anything finer is painting noise.

Two routes to the same answer are provided, because each covers the other's
weakness. Fixed bins are intuitive but the grid is coarse and the bin edges are
arbitrary. A Fourier series has no edges and gives a continuous answer -- K
harmonics resolve about 365/(2K) days, so "is a half supported?" becomes "is
K = 26 supported?".

Finally, :func:`weekday_labels` exists to be *rejected*. The free atmosphere does
not know what day of the half it is, so running the whole procedure on weekday
must yield no skill. If it does yield skill, the cross-validation is broken and
nothing else here can be believed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_GRANULARITIES_DAYS",
    "DEFAULT_K_VALUES",
    "BinCVResult",
    "HarmonicCVResult",
    "bin_index",
    "day_of_year_fraction",
    "harmonic_design",
    "harmonic_resolution_days",
    "loyo_bin_cv",
    "loyo_harmonic_cv",
    "loyo_label_skill",
    "n_bins_for",
    "weekday_labels",
    "year_of",
]

#: Mean year length. Used only to turn a bin width in days into a bin count.
YEAR_DAYS = 365.0

#: A day, a few days, a pentad, the project's half, a ten-day period, a month,
#: two months, a season, and the whole year as the no-seasonal-information
#: baseline.
DEFAULT_GRANULARITIES_DAYS: tuple[float, ...] = (
    1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 30.0, 61.0, 91.0, 365.0,
)

DEFAULT_K_VALUES: tuple[int, ...] = tuple(range(0, 27))


# --- the day-of-year axis ----------------------------------------------------


def year_of(times: NDArray) -> NDArray[np.int64]:
    """Calendar year of each timestamp."""
    return np.asarray(times).astype("datetime64[Y]").astype(int) + 1970


def day_of_year_fraction(times: NDArray) -> NDArray[np.float64]:
    """Position within the year, in ``[0, 1)``.

    Normalising by each year's own length rather than by a fixed 365 keeps
    1 March in the same place in leap and common years. Dividing by a constant
    instead would slide the whole second half of every leap year by a day, which
    over ten years smears exactly the fine structure this module is trying to
    measure.
    """
    t = np.asarray(times).astype("datetime64[s]")
    start = t.astype("datetime64[Y]").astype("datetime64[s]")
    next_year = (t.astype("datetime64[Y]") + np.timedelta64(1, "Y")).astype("datetime64[s]")
    elapsed = (t - start).astype("timedelta64[s]").astype(np.float64)
    length = (next_year - start).astype("timedelta64[s]").astype(np.float64)
    return elapsed / length


def n_bins_for(width_days: float) -> int:
    """How many bins a given bin width divides the year into."""
    if width_days <= 0:
        raise ValueError(f"width_days must be positive, got {width_days}")
    return max(1, int(round(YEAR_DAYS / width_days)))


def bin_index(doy_fraction: NDArray[np.float64], n_bins: int) -> NDArray[np.int64]:
    """Which of ``n_bins`` equal slices of the year each sample falls in."""
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")
    idx = np.floor(np.asarray(doy_fraction, dtype=float) * n_bins).astype(np.int64)
    return np.clip(idx, 0, n_bins - 1)


def weekday_labels(times: NDArray) -> NDArray[np.int64]:
    """Day of the half, 0-6. A predictor with no physical claim on the wind."""
    days = np.asarray(times).astype("datetime64[D]").astype(np.int64)
    return (days + 4) % 7          # 1970-01-01 was a Thursday


def harmonic_resolution_days(k: int) -> float:
    """The shortest timescale a ``k``-harmonic fit can represent."""
    if k <= 0:
        return float("inf")
    return YEAR_DAYS / (2.0 * k)


# --- shared machinery --------------------------------------------------------


def _flatten(values: NDArray) -> tuple[NDArray[np.float64], tuple[int, ...]]:
    v = np.asarray(values, dtype=np.float64)
    return v.reshape(v.shape[0], -1), v.shape[1:]


def _sq_err(pred: NDArray, true: NDArray, trailing: tuple[int, ...],
            vector_axis: int | None) -> NDArray[np.float64]:
    """Squared error, with the components of a vector summed rather than averaged.

    A landing error is a distance: 10 km east and 10 km north is one error of
    14 km, not two errors of 10 km. Averaging over the components instead would
    understate it by sqrt(2) -- harmless for finding the minimum, wrong for
    quoting the number.
    """
    err2 = (pred - true) ** 2
    if vector_axis is None:
        return err2
    err2 = err2.reshape((-1, *trailing))
    axis = vector_axis if vector_axis >= 0 else err2.ndim + vector_axis
    return err2.sum(axis=axis)


def _check(values: NDArray, doy: NDArray, years: NDArray) -> None:
    if not (len(values) == len(doy) == len(years)):
        raise ValueError(
            f"values, doy and years must share a length; got "
            f"{len(values)}, {len(doy)}, {len(years)}"
        )
    if np.unique(years).size < 2:
        raise ValueError("leave-one-year-out needs at least two years")


def _group_means(
    flat: NDArray[np.float64], labels: NDArray[np.int64], n_groups: int
) -> NDArray[np.float64]:
    """Mean of each group, with empty groups left as NaN."""
    totals = np.zeros((n_groups, flat.shape[1]))
    counts = np.zeros(n_groups)
    np.add.at(totals, labels, np.nan_to_num(flat))
    np.add.at(counts, labels, np.isfinite(flat).all(axis=1).astype(float))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = totals / counts[:, None]
    return np.where(counts[:, None] > 0, out, np.nan)


def _predict(means: NDArray, labels: NDArray, fallback: NDArray) -> NDArray:
    """Group mean where the group was populated in training, global mean elsewhere."""
    pred = means[labels]
    empty = ~np.isfinite(pred).all(axis=1)
    if empty.any():
        pred = pred.copy()
        pred[empty] = fallback
    return pred


# --- fixed bins --------------------------------------------------------------


def _loyo_rmse_for_bins(
    flat: NDArray[np.float64],
    doy: NDArray[np.float64],
    years: NDArray,
    uniq: NDArray,
    n_bins: int,
    trailing: tuple[int, ...],
    vector_axis: int | None,
) -> float:
    """Out-of-sample RMSE for one bin count. Used for the no-season baseline."""
    labels = bin_index(doy, n_bins)
    per_fold = []
    for y in uniq:
        test = years == y
        train = ~test
        means = _group_means(flat[train], labels[train], n_bins)
        fallback = np.nanmean(flat[train], axis=0)
        pred = _predict(means, labels[test], fallback)
        per_fold.append(np.nanmean(_sq_err(pred, flat[test], trailing, vector_axis)))
    return float(np.sqrt(np.nanmean(per_fold)))


@dataclass(frozen=True)
class BinCVResult:
    """Leave-one-year-out error as a function of bin width."""

    granularity_days: NDArray[np.float64]
    train_rmse: NDArray[np.float64]
    test_rmse: NDArray[np.float64]
    skill: NDArray[np.float64]
    n_per_bin: NDArray[np.float64]
    fold_test_rmse: NDArray[np.float64] = field(repr=False)

    @property
    def best_days(self) -> float:
        """The bin width with the literal lowest out-of-sample error.

        Prefer :attr:`parsimonious_days` when recommending a granularity: the
        curve is usually flat near its minimum, and the bare argmin will happily
        pick the finer of two widths that differ by less than the noise.
        """
        return float(self.granularity_days[int(np.nanargmin(self.test_rmse))])

    @property
    def parsimonious_days(self) -> float:
        """The **coarsest** width whose error is within one standard error of the best.

        The one-standard-error rule, which is the usual convention in
        cross-validation and the right one here: when two granularities cannot be
        told apart, the coarser one makes the weaker claim about the data and is
        the honest recommendation. Without it a tie at the third decimal place
        would be reported as evidence for daily resolution.
        """
        d = self.paired_difference()
        tied = d["mean"] <= np.maximum(d["sem"], 1e-12)
        if not tied.any():
            return self.best_days
        return float(np.max(self.granularity_days[tied]))

    @property
    def best_skill(self) -> float:
        return float(np.nanmax(self.skill))

    def fold_spread(self) -> NDArray[np.float64]:
        """Standard deviation of the per-year errors.

        This is how much the error varies between years, which is large. It is
        **not** the uncertainty on a comparison between two granularities -- for
        that see :meth:`paired_difference`, because the same years are used
        throughout and the comparison is paired.
        """
        return np.nanstd(self.fold_test_rmse, axis=1, ddof=1)

    def paired_difference(self, reference_days: float | None = None) -> dict:
        """Compare each granularity with a reference, year by year.

        Every granularity is scored on the same ten years, so the right
        comparison is paired: for each held-out year, take the difference in
        error and ask whether it is consistently one-signed. Comparing the
        unpaired spreads instead would hide a small but perfectly reliable
        improvement inside the much larger year-to-year variation.

        Returns the mean difference, its standard error across folds, and the
        number of folds in which the candidate beat the reference. A difference
        smaller than about twice its standard error means the two granularities
        are not distinguishable.
        """
        ref_days = reference_days if reference_days is not None else self.best_days
        j = int(np.argmin(np.abs(self.granularity_days - ref_days)))
        diff = self.fold_test_rmse - self.fold_test_rmse[j][None, :]
        n = diff.shape[1]
        return {
            "reference_days": float(self.granularity_days[j]),
            "mean": np.nanmean(diff, axis=1),
            "sem": np.nanstd(diff, axis=1, ddof=1) / np.sqrt(n),
            "wins": (diff < 0).sum(axis=1),
            "n_folds": n,
        }

    def resolved_range(self, n_sem: float = 2.0) -> tuple[float, float]:
        """The granularities indistinguishable from the best one.

        The honest answer to "what is the right unit" is usually a range rather
        than a single number, because several neighbouring bin widths score the
        same to within the paired uncertainty.
        """
        d = self.paired_difference()
        tied = d["mean"] <= n_sem * np.maximum(d["sem"], 1e-12)
        widths = self.granularity_days[tied]
        return float(np.min(widths)), float(np.max(widths))


def loyo_bin_cv(
    values: NDArray,
    doy_fraction: NDArray[np.float64],
    years: NDArray[np.int64],
    granularities_days: Sequence[float] = DEFAULT_GRANULARITIES_DAYS,
    *,
    vector_axis: int | None = None,
) -> BinCVResult:
    """Leave-one-year-out cross-validation over a grid of bin widths.

    ``values`` is ``(n_samples, ...)``. The skill score is always measured
    against a single whole-year bin -- the model that knows nothing about the
    season -- whether or not that granularity appears in
    ``granularities_days``. Tying the baseline to the caller's list would make
    two runs incomparable.
    """
    _check(values, doy_fraction, years)
    flat, trailing = _flatten(values)
    doy = np.asarray(doy_fraction, dtype=float)
    years = np.asarray(years)
    uniq = np.unique(years)
    widths = np.asarray(list(granularities_days), dtype=float)

    train_rmse = np.empty(widths.size)
    test_rmse = np.empty(widths.size)
    n_per_bin = np.empty(widths.size)
    folds = np.empty((widths.size, uniq.size))

    baseline = _loyo_rmse_for_bins(flat, doy, years, uniq, 1, trailing, vector_axis)

    for i, width in enumerate(widths):
        n_bins = n_bins_for(width)
        labels = bin_index(doy, n_bins)
        n_per_bin[i] = flat.shape[0] / n_bins

        tr_sq: list[NDArray] = []
        for j, y in enumerate(uniq):
            test = years == y
            train = ~test
            means = _group_means(flat[train], labels[train], n_bins)
            fallback = np.nanmean(flat[train], axis=0)

            pred_te = _predict(means, labels[test], fallback)
            folds[i, j] = np.sqrt(
                np.nanmean(_sq_err(pred_te, flat[test], trailing, vector_axis))
            )
            pred_tr = _predict(means, labels[train], fallback)
            tr_sq.append(_sq_err(pred_tr, flat[train], trailing, vector_axis).ravel())

        train_rmse[i] = np.sqrt(np.nanmean(np.concatenate(tr_sq)))
        test_rmse[i] = np.sqrt(np.nanmean(folds[i] ** 2))

    with np.errstate(invalid="ignore", divide="ignore"):
        skill = 1.0 - test_rmse / baseline
    return BinCVResult(widths, train_rmse, test_rmse, skill, n_per_bin, folds)


# --- harmonics ---------------------------------------------------------------


def harmonic_design(doy_fraction: NDArray[np.float64], k: int) -> NDArray[np.float64]:
    """Design matrix for a ``k``-harmonic annual cycle, shape ``(n, 2k + 1)``."""
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")
    t = np.asarray(doy_fraction, dtype=float)
    cols = [np.ones_like(t)]
    for j in range(1, k + 1):
        cols.append(np.cos(2 * np.pi * j * t))
        cols.append(np.sin(2 * np.pi * j * t))
    return np.stack(cols, axis=1)


@dataclass(frozen=True)
class HarmonicCVResult:
    """Leave-one-year-out error as a function of the number of harmonics."""

    k_values: NDArray[np.int64]
    train_rmse: NDArray[np.float64]
    test_rmse: NDArray[np.float64]
    skill: NDArray[np.float64]
    fold_test_rmse: NDArray[np.float64] = field(repr=False)

    @property
    def best_k(self) -> int:
        """The literal minimum. See :attr:`parsimonious_k`."""
        return int(self.k_values[int(np.nanargmin(self.test_rmse))])

    @property
    def parsimonious_k(self) -> int:
        """The **fewest** harmonics within one standard error of the best.

        Same one-standard-error rule as :attr:`BinCVResult.parsimonious_days`,
        and the same reason: fewer harmonics is the weaker claim.
        """
        j = int(np.nanargmin(self.test_rmse))
        diff = self.fold_test_rmse - self.fold_test_rmse[j][None, :]
        sem = np.nanstd(diff, axis=1, ddof=1) / np.sqrt(diff.shape[1])
        tied = np.nanmean(diff, axis=1) <= np.maximum(sem, 1e-12)
        if not tied.any():
            return self.best_k
        return int(np.min(self.k_values[tied]))

    @property
    def best_resolution_days(self) -> float:
        """The finest timescale the chosen fit can represent."""
        return harmonic_resolution_days(self.best_k)


def loyo_harmonic_cv(
    values: NDArray,
    doy_fraction: NDArray[np.float64],
    years: NDArray[np.int64],
    k_values: Iterable[int] = DEFAULT_K_VALUES,
    *,
    vector_axis: int | None = None,
) -> HarmonicCVResult:
    """Leave-one-year-out cross-validation over the number of annual harmonics.

    Unlike fixed bins this has no edges to place, so the answer does not depend
    on where a half is deemed to start.
    """
    _check(values, doy_fraction, years)
    flat, trailing = _flatten(values)
    doy = np.asarray(doy_fraction, dtype=float)
    years = np.asarray(years)
    uniq = np.unique(years)
    ks = np.asarray(list(k_values), dtype=int)

    train_rmse = np.empty(ks.size)
    test_rmse = np.empty(ks.size)
    folds = np.empty((ks.size, uniq.size))

    good = np.isfinite(flat).all(axis=1)
    for i, k in enumerate(ks):
        design = harmonic_design(doy, int(k))
        tr_sq: list[NDArray] = []
        for j, y in enumerate(uniq):
            test = years == y
            train = (~test) & good
            coef, *_ = np.linalg.lstsq(design[train], flat[train], rcond=None)

            pred_te = design[test] @ coef
            folds[i, j] = np.sqrt(
                np.nanmean(_sq_err(pred_te, flat[test], trailing, vector_axis))
            )
            pred_tr = design[train] @ coef
            tr_sq.append(_sq_err(pred_tr, flat[train], trailing, vector_axis).ravel())

        train_rmse[i] = np.sqrt(np.nanmean(np.concatenate(tr_sq)))
        test_rmse[i] = np.sqrt(np.nanmean(folds[i] ** 2))

    # K = 0 is the no-seasonal-information model, computed whether or not the
    # caller asked for it, so skill scores are comparable between runs.
    baseline = _loyo_rmse_for_harmonics(flat, doy, years, uniq, 0, trailing,
                                        vector_axis, good)
    with np.errstate(invalid="ignore", divide="ignore"):
        skill = 1.0 - test_rmse / baseline
    return HarmonicCVResult(ks, train_rmse, test_rmse, skill, folds)


def _loyo_rmse_for_harmonics(
    flat: NDArray[np.float64],
    doy: NDArray[np.float64],
    years: NDArray,
    uniq: NDArray,
    k: int,
    trailing: tuple[int, ...],
    vector_axis: int | None,
    good: NDArray[np.bool_],
) -> float:
    design = harmonic_design(doy, k)
    per_fold = []
    for y in uniq:
        test = years == y
        train = (~test) & good
        coef, *_ = np.linalg.lstsq(design[train], flat[train], rcond=None)
        pred = design[test] @ coef
        per_fold.append(np.nanmean(_sq_err(pred, flat[test], trailing, vector_axis)))
    return float(np.sqrt(np.nanmean(per_fold)))


# --- arbitrary labels, for the placebo ---------------------------------------


def loyo_label_skill(
    values: NDArray,
    labels: NDArray[np.int64],
    years: NDArray[np.int64],
    *,
    vector_axis: int | None = None,
) -> float:
    """Skill of predicting from an arbitrary categorical label, against its own mean.

    Used for the weekday placebo. A skill near zero means the label carries no
    information, which is the required answer for weekday and the reason to
    trust the same machinery when it reports a non-zero answer elsewhere.
    """
    _check(values, labels, years)
    flat, trailing = _flatten(values)
    labels = np.asarray(labels, dtype=np.int64)
    years = np.asarray(years)
    n_groups = int(labels.max()) + 1

    se_model: list[NDArray] = []
    se_base: list[NDArray] = []
    for y in np.unique(years):
        test = years == y
        train = ~test
        means = _group_means(flat[train], labels[train], n_groups)
        fallback = np.nanmean(flat[train], axis=0)
        pred = _predict(means, labels[test], fallback)
        se_model.append(_sq_err(pred, flat[test], trailing, vector_axis).ravel())
        se_base.append(
            _sq_err(
                np.broadcast_to(fallback, flat[test].shape), flat[test], trailing, vector_axis
            ).ravel()
        )
    rmse = np.sqrt(np.nanmean(np.concatenate(se_model)))
    base = np.sqrt(np.nanmean(np.concatenate(se_base)))
    return float(1.0 - rmse / base) if base > 0 else 0.0
