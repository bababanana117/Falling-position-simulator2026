"""Model selection and the ambiguity flag."""

from __future__ import annotations

import numpy as np
import pytest

from jpduck.config import AMBIGUOUS_DELTA_AIC
from jpduck.fits.select import assign_selection


def _call(aic, converged=None, n=600, n_eff=None):
    aic = np.asarray(aic, dtype=float)
    if converged is None:
        converged = np.ones(aic.shape, dtype=bool)
    if n_eff is None:
        n_eff = np.full(aic.shape[1], float(n))
    return assign_selection(aic, np.asarray(converged), n, np.asarray(n_eff, dtype=float))


def test_smallest_aic_wins_and_gets_zero_delta():
    delta, selected, _ = _call([[10.0, 5.0], [7.0, 9.0]])
    assert selected.tolist() == [[False, True], [True, False]]
    assert delta[selected] == pytest.approx([0.0, 0.0])
    assert delta[~selected] == pytest.approx([3.0, 4.0])


def test_exactly_one_winner_per_cell():
    rng = np.random.default_rng(0)
    aic = rng.normal(5000, 50, size=(3, 500))
    _, selected, _ = _call(aic)
    assert selected.sum(axis=0).tolist() == [1] * 500


def test_ties_go_to_the_earlier_family():
    """Preserves the intent of ``if aic_n <= aic_w`` in windsample."""
    _, selected, _ = _call([[42.0], [42.0]])
    assert selected[:, 0].tolist() == [True, False]


def test_a_family_that_did_not_converge_cannot_win():
    aic = [[1.0], [100.0]]
    converged = [[False], [True]]
    delta, selected, _ = _call(aic, converged)
    assert selected[:, 0].tolist() == [False, True]
    assert np.isnan(delta[0, 0]), "a non-converged family gets NaN, not a number"


def test_all_families_failed_leaves_no_winner():
    delta, selected, ambiguous = _call([[1.0], [2.0]], converged=[[False], [False]])
    assert not selected.any()
    assert not ambiguous.any()
    assert np.isnan(delta).all()


def test_ambiguity_uses_the_deflated_gap():
    """A nominal gap of 20 is not a real gap when n_eff is n/20."""
    gap = 20.0
    n, n_eff = 600, 30.0                      # scale = 1/20, so 20 -> 1.0
    _, selected, ambiguous = _call([[0.0], [gap]], n=n, n_eff=[n_eff])
    assert selected[0, 0] and ambiguous[0, 0]
    assert gap * n_eff / n < AMBIGUOUS_DELTA_AIC

    # The same gap with independent samples is decisive.
    _, _, ambiguous_indep = _call([[0.0], [gap]], n=n, n_eff=[float(n)])
    assert not ambiguous_indep.any()


def test_only_the_winner_carries_the_ambiguity_flag():
    _, selected, ambiguous = _call([[0.0], [0.5]], n=600, n_eff=[600.0])
    assert ambiguous[selected].all()
    assert not ambiguous[~selected].any()


def test_the_flag_is_set_at_the_documented_threshold():
    """Just inside and just outside AMBIGUOUS_DELTA_AIC, with n_eff == n."""
    below = AMBIGUOUS_DELTA_AIC - 1e-6
    above = AMBIGUOUS_DELTA_AIC + 1e-6
    _, _, amb_below = _call([[0.0], [below]], n_eff=[600.0])
    _, _, amb_above = _call([[0.0], [above]], n_eff=[600.0])
    assert amb_below.any()
    assert not amb_above.any()
