"""The direction estimators.

von Mises is checked against scipy. The wrapped normal has no library
implementation at all, so it is checked against an 801-term brute-force sum
and against numerical integration of its own density -- the only honest way to
verify a formula nobody else ships.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from jpduck.config import NEWTON_TOL, WN_FOURIER_SWITCH_R
from jpduck.fits.circular import (
    circular_moments,
    fit_all_direction,
    fit_circular_uniform,
    fit_von_mises,
    fit_wrapped_normal,
    kuiper_statistic,
    von_mises_score,
    wrap_pi,
    wrapped_normal_cdf,
    wrapped_normal_logpdf,
)
from jpduck.fits.reference import (
    brute_wrapped_normal_cdf,
    brute_wrapped_normal_logpdf,
    scipy_direction_fit,
    von_mises_cdf_series,
)

LN_2PI = float(np.log(2 * np.pi))


@pytest.fixture(scope="module")
def vm_block():
    rng = np.random.default_rng(20260922)
    kappas = np.concatenate([rng.uniform(0.05, 5.0, 60), rng.uniform(5.0, 200.0, 40)])
    mus = rng.uniform(-np.pi, np.pi, 100)
    theta = np.array([
        stats.vonmises.rvs(k, loc=m, size=600, random_state=int(500 + i))
        for i, (k, m) in enumerate(zip(kappas, mus, strict=True))
    ])
    return wrap_pi(theta), kappas, mus


def test_vonmises_matches_scipy(vm_block):
    theta, _, _ = vm_block
    m = circular_moments(theta)
    fit = fit_von_mises(np.sort(theta, axis=1), m)
    assert fit.converged.all()
    for i in range(0, 100, 11):
        ref = scipy_direction_fit(theta[i])
        assert fit.params["kappa"][i] == pytest.approx(ref["kappa"], rel=1e-8)
        assert wrap_pi(fit.params["mu_rad"][i] - ref["mu_rad"]) == pytest.approx(0.0, abs=1e-10)
        assert fit.loglik[i] == pytest.approx(ref["loglik"], rel=1e-9)


def test_vonmises_kappa_residual(vm_block):
    theta, _, _ = vm_block
    m = circular_moments(theta)
    fit = fit_von_mises(np.sort(theta, axis=1), m)
    assert np.abs(von_mises_score(fit.params["kappa"], m.rbar)).max() < 1e-12


def test_newton_tol_regression(vm_block):
    """``newton``'s tol is an ABSOLUTE step tolerance, not a relative one.

    At kappa ~ 100 a step of 1e-12 is below float resolution, so a tighter tol
    makes it iterate to maxiter and report failure on cells that are in fact
    converged to 1e-15. This pins the working value and documents the trap.
    """
    from scipy import optimize

    from jpduck.fits.circular import _kappa_start, von_mises_score_deriv

    theta, _, _ = vm_block
    m = circular_moments(theta)
    common = dict(
        fprime=von_mises_score_deriv, args=(m.rbar,), maxiter=60, full_output=True
    )
    _, conv_ok, _ = optimize.newton(
        von_mises_score, _kappa_start(m.rbar), tol=NEWTON_TOL, **common
    )
    with pytest.warns(RuntimeWarning, match="failed to converge"):
        k_tight, conv_tight, _ = optimize.newton(
            von_mises_score, _kappa_start(m.rbar), tol=1e-14, **common
        )
    assert np.all(conv_ok), "tol=1e-8 must converge every cell"
    high_kappa = m.rbar > 0.9
    if high_kappa.any():
        # The tight tolerance gives up on concentrated cells whose residual is
        # already at machine precision.
        assert np.abs(von_mises_score(k_tight, m.rbar))[high_kappa].max() < 1e-12
        assert not np.all(conv_tight[high_kappa])


@pytest.mark.parametrize("rbar", [0.999, 0.9, 0.7, 0.55, 0.5, 0.4, 0.2, 0.05, 0.001])
def test_wrapped_normal_logpdf_matches_brute_force(rbar):
    """Both branches, against 801 spatial terms."""
    sigma = float(np.sqrt(-2.0 * np.log(rbar)))
    delta = np.linspace(-np.pi, np.pi, 201)[None, :]
    got = wrapped_normal_logpdf(delta, np.array([sigma]), np.array([rbar]))
    want = brute_wrapped_normal_logpdf(delta[0], sigma)
    assert np.abs(got[0] - want).max() < 1e-12


@pytest.mark.parametrize("rbar", [0.95, 0.6, 0.3, 0.02])
def test_wrapped_normal_normalises(rbar):
    sigma = float(np.sqrt(-2.0 * np.log(rbar)))
    d = np.linspace(-np.pi, np.pi, 20001)
    f = np.exp(wrapped_normal_logpdf(d[None, :], np.array([sigma]), np.array([rbar]))[0])
    assert np.trapezoid(f, d) == pytest.approx(1.0, abs=1e-10)


def test_wrapped_normal_branch_continuity():
    """Each branch must match the truth right at the switch.

    Comparing the two branches to *each other* across the switch does not
    isolate them: the resultant length differs by 2e-9 between the two sides
    and the density genuinely moves by ~1.8e-8 over that gap, which swamps any
    branch error. Comparing each side to the brute force at its own resultant
    length is the stronger statement and is what continuity actually requires.
    """
    eps = 1e-9
    d = np.linspace(-np.pi, np.pi, 101)
    for r in (WN_FOURIER_SWITCH_R - eps, WN_FOURIER_SWITCH_R + eps):
        sigma = float(np.sqrt(-2.0 * np.log(r)))
        got = wrapped_normal_logpdf(d[None, :], np.array([sigma]), np.array([r]))[0]
        want = brute_wrapped_normal_logpdf(d, sigma)
        assert np.abs(got - want).max() < 1e-12, f"branch at rbar={r}"


@pytest.mark.parametrize("rbar", [0.99, 0.7, 0.45, 0.1])
def test_wrapped_normal_cdf(rbar):
    sigma = float(np.sqrt(-2.0 * np.log(rbar)))
    for delta in (-2.0, -0.5, 0.0, 1.1, 2.9):
        got = wrapped_normal_cdf(
            np.array([[delta]]), np.array([sigma]), np.array([rbar])
        )[0, 0]
        assert got == pytest.approx(brute_wrapped_normal_cdf(delta, sigma), abs=2e-6)
    ends = wrapped_normal_cdf(
        np.array([[-np.pi, np.pi]]), np.array([sigma]), np.array([rbar])
    )[0]
    assert ends[0] == pytest.approx(0.0, abs=1e-12)
    assert ends[1] == pytest.approx(1.0, abs=1e-12)


def test_wrapped_normal_sigma_equals_mardia(vm_block):
    """sigma is Mardia's circular SD -- the same quantity as circ_sd_deg."""
    from windclim.stats.circular import circular_sd_deg

    theta, _, _ = vm_block
    m = circular_moments(theta)
    fit = fit_wrapped_normal(np.sort(theta, axis=1), m)
    ours = np.degrees(fit.params["wn_sigma_rad"])
    theirs = circular_sd_deg(m.rbar)
    keep = np.isfinite(theirs)
    assert np.allclose(ours[keep], theirs[keep], rtol=1e-12)


def test_circular_uniform_loglik():
    theta = np.random.default_rng(5).uniform(-np.pi, np.pi, size=(4, 700))
    fit = fit_circular_uniform(np.sort(theta, axis=1), circular_moments(theta))
    assert fit.n_params == 0
    assert np.allclose(fit.loglik, -700 * LN_2PI)
    assert np.allclose(fit.aic, -2 * fit.loglik)


def test_circular_uniform_beats_von_mises_on_uniform_data():
    r"""The null model wins on null data -- on average, and usually, not always.

    It would be wrong to assert it wins every time. Under a uniform truth the
    Rayleigh statistic :math:`2n\bar R^2` is :math:`\chi^2_2`, and the von
    Mises log-likelihood gain over the uniform is :math:`\approx n\bar R^2/2`,
    so the AIC gap is :math:`4 - \chi^2_2` in expectation. That is negative --
    von Mises wins by chance -- whenever :math:`\chi^2_2 > 4`, which happens
    with probability :math:`e^{-2} = 13.5\%`. So the sharp statement is about
    the mean gap, which must sit at :math:`4 - E[\chi^2_2] = 2`.
    """
    theta = np.random.default_rng(6).uniform(-np.pi, np.pi, size=(400, 3000))
    by = {f.family: f for f in fit_all_direction(theta)}
    gap_vm = by["von_mises"].aic - by["circular_uniform"].aic
    gap_wn = by["wrapped_normal"].aic - by["circular_uniform"].aic

    assert gap_vm.mean() == pytest.approx(2.0, abs=0.4)
    assert (gap_vm > 0).mean() > 0.80          # theory says ~86.5 %
    assert (gap_wn > 0).mean() > 0.80


def test_von_mises_wins_on_concentrated_data():
    """A concentrated alternative beats the null decisively when it is true.

    Note what is *not* asserted: that von Mises beats the wrapped normal on
    von Mises data. At the concentration used here the two densities are
    nearly the same curve, so which one wins is close to a coin toss -- and
    the wrapped normal is moment-matched, so it reproduces the resultant
    length exactly. All that can honestly be claimed is that the two unimodal
    families land within a few AIC units of each other, far from the null.
    """
    theta = stats.vonmises.rvs(4.0, size=(40, 2000), random_state=12)
    by = {f.family: f for f in fit_all_direction(wrap_pi(theta))}
    assert (by["von_mises"].aic < by["circular_uniform"].aic - 100).all()
    assert (by["wrapped_normal"].aic < by["circular_uniform"].aic - 100).all()
    # Per observation, not in total: with n = 2000 even a 54-unit AIC gap is
    # 0.013 nats per analysis, which is what "nearly the same curve" means.
    per_obs = np.abs(by["von_mises"].loglik - by["wrapped_normal"].loglik) / 2000
    assert per_obs.max() < 0.05


def test_kuiper_rotation_invariant():
    """The reason Kuiper is used instead of KS."""
    theta = stats.vonmises.rvs(2.0, size=(1, 4000), random_state=11)
    base = fit_all_direction(theta)
    rotated = fit_all_direction(wrap_pi(theta + 1.234))
    for a, b in zip(base, rotated, strict=True):
        assert a.kuiper[0] == pytest.approx(b.kuiper[0], abs=1e-12)


def test_kuiper_uniform_reference():
    u = np.linspace(0.0, 1.0, 1001)[None, 1:]
    assert kuiper_statistic(u)[0] < 2e-3


@pytest.mark.parametrize("kappa", [0.01, 0.5, 3.0, 30.0, 200.0])
def test_vonmises_cdf_series_matches_scipy(kappa):
    """Our fallback series against the library routine we actually call."""
    delta = np.linspace(-np.pi + 1e-9, np.pi - 1e-9, 51)
    assert np.abs(
        von_mises_cdf_series(delta, kappa) - stats.vonmises.cdf(delta, kappa)
    ).max() < 1e-5


def test_mu_equals_dir_unit_mean(vm_block):
    """mu in met degrees must equal what the pipeline derives from the unit means."""
    from windclim.stats.circular import uv_to_met_direction

    theta, _, _ = vm_block
    m = circular_moments(theta)
    # theta is already a met FROM-direction in radians; reconstruct u, v.
    u_unit = -np.sin(theta).mean(axis=1)
    v_unit = -np.cos(theta).mean(axis=1)
    ours = np.degrees(m.mu) % 360.0
    theirs = uv_to_met_direction(u_unit, v_unit)
    assert np.allclose(wrap_pi(np.radians(ours - theirs)), 0.0, atol=1e-9)
