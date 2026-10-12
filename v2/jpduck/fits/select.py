"""Model selection across the fitted families.

The winner is the smallest AIC among the families that converged. That much is
conventional. The part that matters more is the ambiguity flag.

Consecutive six-hourly analyses are nearly the same air. Measured over the
whole database the lag-1 autocorrelation of speed averages 0.74 and reaches
0.95, so the 600 analyses in a half-month bin carry the information of 99 on
average and as few as 17. Every log-likelihood here is computed as if all 600
were independent, which inflates every AIC *difference* by n/n_eff -- 8.6
times on average, up to 37.

Rather than bury that, a winner is flagged ambiguous when its lead over the
runner-up, deflated by that factor, drops below 2. Reading ``is_selected`` as
"this is the shape of the distribution" would be over-reading it;
``is_ambiguous`` is how the database says so.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..config import AMBIGUOUS_DELTA_AIC

__all__ = ["assign_selection"]


def assign_selection(
    aic: NDArray[np.float64],
    converged: NDArray[np.bool_],
    n: int,
    n_eff: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.bool_], NDArray[np.bool_]]:
    """Rank families per cell.

    ``aic`` and ``converged`` are ``(nfamily, ncell)``, in a fixed declaration
    order which doubles as the tie-break: earlier families win exact ties,
    which preserves the intent of the two-way ``if aic_n <= aic_w`` the
    upstream pipeline used.

    Returns ``(delta_aic, is_selected, is_ambiguous)``, each ``(nfamily,
    ncell)``. ``delta_aic`` is measured against the best *converged* family, so
    a family that failed to converge gets NaN rather than a misleading number.
    """
    aic = np.asarray(aic, dtype=np.float64)
    converged = np.asarray(converged, dtype=bool)
    nfam, ncell = aic.shape

    usable = converged & np.isfinite(aic)
    masked = np.where(usable, aic, np.inf)

    best = masked.min(axis=0)
    any_ok = np.isfinite(best)

    delta = np.full(aic.shape, np.nan)
    np.subtract(masked, best[None, :], out=delta, where=usable & any_ok[None, :])

    # argmin over the first axis breaks ties towards the lower index, which is
    # the declaration order.
    winner = np.argmin(masked, axis=0)
    is_selected = np.zeros(aic.shape, dtype=bool)
    is_selected[winner, np.arange(ncell)] = any_ok

    # The runner-up gap: second smallest delta among the usable families.
    with np.errstate(invalid="ignore"):
        gaps = np.where(usable, delta, np.inf)
    gaps[winner, np.arange(ncell)] = np.inf
    runner_up = gaps.min(axis=0)

    scale = np.divide(
        np.asarray(n_eff, dtype=np.float64), float(n),
        out=np.ones(ncell), where=np.isfinite(n_eff),
    )
    ambiguous_cell = any_ok & np.isfinite(runner_up) & (runner_up * scale < AMBIGUOUS_DELTA_AIC)

    is_ambiguous = np.zeros(aic.shape, dtype=bool)
    is_ambiguous[winner, np.arange(ncell)] = ambiguous_cell
    return delta, is_selected, is_ambiguous
