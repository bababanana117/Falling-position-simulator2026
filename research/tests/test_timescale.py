"""Does the data support a half, a month, or only a season?

These tests are the ones that matter most in the whole suite, because they check
the *method* rather than the data. A cross-validation that is too permissive will
declare a signal in pure noise; one that is too blunt will miss a signal that is
plainly there. Both failures are checked here against inputs whose right answer
is known by construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from windclim.stats import timescale as ts

YEARS = np.arange(2016, 2026)


def synthetic_times(years=YEARS, per_day=4):
    """6-hourly timestamps over whole years, as datetime64[ns]."""
    out = []
    for y in years:
        start = np.datetime64(f"{y}-01-01T00", "h")
        end = np.datetime64(f"{y + 1}-01-01T00", "h")
        out.append(np.arange(start, end, np.timedelta64(24 // per_day, "h")))
    return np.concatenate(out).astype("datetime64[ns]")


TIMES = synthetic_times()
DOY = None  # filled lazily by the fixture below


@pytest.fixture(scope="module")
def axes():
    doy = ts.day_of_year_fraction(TIMES)
    years = ts.year_of(TIMES)
    return doy, years


# --- the day-of-year axis ----------------------------------------------------


def test_day_of_year_fraction_spans_zero_to_one() -> None:
    doy = ts.day_of_year_fraction(TIMES)
    assert doy.min() >= 0.0
    assert doy.max() < 1.0


def test_new_year_is_zero() -> None:
    t = np.array(["2019-01-01T00"], dtype="datetime64[ns]")
    assert float(ts.day_of_year_fraction(t)[0]) == pytest.approx(0.0)


def test_end_of_year_is_close_to_one() -> None:
    t = np.array(["2019-12-31T18"], dtype="datetime64[ns]")
    assert float(ts.day_of_year_fraction(t)[0]) > 0.99


def test_leap_years_line_up_with_common_years() -> None:
    """Normalising by the year's own length keeps 1 March in the same place,
    instead of shifting the whole second half of every leap year by a day."""
    leap = ts.day_of_year_fraction(np.array(["2016-03-01T00"], dtype="datetime64[ns]"))
    common = ts.day_of_year_fraction(np.array(["2017-03-01T00"], dtype="datetime64[ns]"))
    assert abs(float(leap[0]) - float(common[0])) < 0.005


def test_year_of_matches_the_calendar() -> None:
    t = np.array(["2016-12-31T18", "2017-01-01T00"], dtype="datetime64[ns]")
    assert ts.year_of(t).tolist() == [2016, 2017]


# --- binning -----------------------------------------------------------------


@pytest.mark.parametrize("n_bins", [1, 4, 12, 73, 365])
def test_bin_index_is_within_range(axes, n_bins: int) -> None:
    doy, _ = axes
    idx = ts.bin_index(doy, n_bins)
    assert idx.min() >= 0
    assert idx.max() < n_bins


def test_bin_count_from_width() -> None:
    assert ts.n_bins_for(365.0) == 1
    assert ts.n_bins_for(30.0) == 12
    assert ts.n_bins_for(7.0) == 52
    assert ts.n_bins_for(1.0) == 365


# --- the central claim: white noise must not look like a signal --------------


def test_pure_noise_prefers_the_coarsest_granularity(axes) -> None:
    """With no seasonal signal at all, every extra bin only fits noise, so the
    out-of-sample error must rise as the bins get finer."""
    doy, years = axes
    rng = np.random.default_rng(0)
    values = rng.normal(0.0, 1.0, size=(doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.best_days == max(ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.test_rmse[0] > r.test_rmse[-1]      # finest is worse than coarsest


def test_pure_noise_gives_no_skill(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(1)
    values = rng.normal(0.0, 1.0, size=(doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, (7.0, 30.0, 365.0))
    assert r.skill[r.granularity_days == 7.0][0] < 0.02


def test_training_error_always_falls_as_bins_get_finer(axes) -> None:
    """The signature of overfitting. If this does not hold, the fit is broken."""
    doy, years = axes
    rng = np.random.default_rng(2)
    values = rng.normal(0.0, 1.0, size=(doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    coarse_to_fine = np.argsort(-r.granularity_days)
    train = r.train_rmse[coarse_to_fine]
    assert np.all(np.diff(train) <= 1e-9)


def test_out_of_sample_error_never_beats_in_sample(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(3)
    values = rng.normal(0.0, 1.0, size=(doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert np.all(r.test_rmse >= r.train_rmse - 1e-9)


# --- and a real signal must be found -----------------------------------------


def test_an_annual_cycle_is_detected(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(4)
    signal = 10.0 * np.sin(2 * np.pi * doy)
    values = (signal + rng.normal(0.0, 1.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.best_days < 365.0
    assert r.best_skill > 0.8


def test_a_monthly_signal_needs_monthly_bins(axes) -> None:
    """A 30-day oscillation is invisible to a 91-day bin and resolved by a 15-day one."""
    doy, years = axes
    rng = np.random.default_rng(5)
    signal = 10.0 * np.sin(2 * np.pi * 12 * doy)
    values = (signal + rng.normal(0.0, 1.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, (91.0, 30.0, 15.0, 7.0))
    by_d = dict(zip(r.granularity_days, r.skill, strict=True))
    assert by_d[91.0] < 0.1          # too coarse to see a 30-day cycle
    assert by_d[30.0] < 0.1          # a bin as long as the period averages it away
    assert by_d[15.0] > 0.5          # half the period resolves it


def test_skill_is_measured_against_no_seasonal_information(axes) -> None:
    """The baseline is a single whole-year bin, whatever the caller asked for.

    Tying it to the coarsest granularity in the list would make two runs
    incomparable: asking about (91, 30) and about (365, 30) would report
    different skill for the same 30-day model.
    """
    doy, years = axes
    rng = np.random.default_rng(14)
    values = (10.0 * np.sin(2 * np.pi * doy) + rng.normal(0, 1.0, doy.size))[:, None]
    wide = ts.loyo_bin_cv(values, doy, years, (365.0, 30.0))
    narrow = ts.loyo_bin_cv(values, doy, years, (91.0, 30.0))
    s_wide = wide.skill[wide.granularity_days == 30.0][0]
    s_narrow = narrow.skill[narrow.granularity_days == 30.0][0]
    assert s_wide == pytest.approx(s_narrow, abs=1e-9)


def test_a_perfectly_repeating_signal_supports_the_finest_bins(axes) -> None:
    """The mechanism, stated as a test.

    If every year were identical apart from white noise, daily resolution really
    would be justified: nine training years give 36 samples per one-day bin, so
    the bin mean is precise and there is no penalty for narrowing further. What
    limits the resolvable granularity in the real atmosphere is not noise but
    **interannual variability** -- the same calendar half differing from year to
    year. The next test adds it and the optimum moves.
    """
    doy, years = axes
    rng = np.random.default_rng(6)
    signal = 8.0 * np.sin(2 * np.pi * 6 * doy)
    values = (signal + rng.normal(0.0, 6.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.best_days <= 5.0


def test_interannual_variability_is_what_coarsens_the_optimum(axes) -> None:
    """Same signal, but its phase wanders from year to year, as weather does.

    Now a narrow bin is estimating something that was not the same thing in each
    training year, so it generalises worse and the optimum moves to a coarser
    width.
    """
    doy, years = axes
    rng = np.random.default_rng(15)
    phase = {y: rng.normal(0.0, 0.9) for y in np.unique(years)}
    shift = np.array([phase[y] for y in years])
    signal = 8.0 * np.sin(2 * np.pi * 6 * doy + shift)
    values = (signal + rng.normal(0.0, 3.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.best_days >= 10.0


# --- harmonic version --------------------------------------------------------


def test_harmonic_design_has_the_right_width(axes) -> None:
    doy, _ = axes
    assert ts.harmonic_design(doy[:10], 0).shape == (10, 1)
    assert ts.harmonic_design(doy[:10], 3).shape == (10, 7)


def test_harmonic_design_is_periodic() -> None:
    a = ts.harmonic_design(np.array([0.0]), 4)
    b = ts.harmonic_design(np.array([1.0 - 1e-12]), 4)
    assert np.allclose(a, b, atol=1e-6)


def test_a_pure_annual_cycle_needs_one_harmonic(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(7)
    values = (10.0 * np.sin(2 * np.pi * doy) + rng.normal(0, 1.0, doy.size))[:, None]
    r = ts.loyo_harmonic_cv(values, doy, years, k_values=range(0, 9))
    assert r.best_k == 1


def test_a_thirty_day_signal_needs_twelve_harmonics(axes) -> None:
    """K harmonics resolve 365/(2K) days, so a 30-day period needs K = 12."""
    doy, years = axes
    rng = np.random.default_rng(8)
    values = (10.0 * np.sin(2 * np.pi * 12 * doy) + rng.normal(0, 1.0, doy.size))[:, None]
    r = ts.loyo_harmonic_cv(values, doy, years, k_values=range(0, 20))
    assert r.best_k == 12


def test_noise_needs_no_harmonics(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(9)
    values = rng.normal(0, 1.0, doy.size)[:, None]
    r = ts.loyo_harmonic_cv(values, doy, years, k_values=range(0, 13))
    assert r.best_k == 0


def test_harmonic_resolution_conversion() -> None:
    assert ts.harmonic_resolution_days(1) == pytest.approx(182.5, abs=0.5)
    assert ts.harmonic_resolution_days(12) == pytest.approx(15.2, abs=0.5)
    assert ts.harmonic_resolution_days(26) == pytest.approx(7.0, abs=0.3)


# --- the placebo -------------------------------------------------------------


def test_weekday_carries_no_skill_even_when_the_season_does(axes) -> None:
    """The free atmosphere does not know what day of the half it is. Any skill
    here would mean the cross-validation itself is broken, so this runs before
    any real result is believed."""
    doy, years = axes
    rng = np.random.default_rng(10)
    values = (20.0 * np.sin(2 * np.pi * doy) + rng.normal(0, 3.0, doy.size))[:, None]
    skill = ts.loyo_label_skill(values, ts.weekday_labels(TIMES), years)
    assert abs(skill) < 0.02


def test_weekday_labels_cover_seven_values() -> None:
    labels = ts.weekday_labels(TIMES)
    assert set(np.unique(labels)) == set(range(7))


def test_the_placebo_machinery_does_find_a_planted_weekday_effect(axes) -> None:
    """The placebo must be capable of detecting an effect, or its silence on the
    real data would prove nothing."""
    doy, years = axes
    rng = np.random.default_rng(11)
    labels = ts.weekday_labels(TIMES)
    values = (5.0 * labels + rng.normal(0, 1.0, doy.size))[:, None]
    assert ts.loyo_label_skill(values, labels, years) > 0.9


# --- vector targets ----------------------------------------------------------


def test_vector_rmse_sums_the_components(axes) -> None:
    """A landing error is a distance, not two independent numbers."""
    doy, years = axes
    rng = np.random.default_rng(12)
    values = rng.normal(0, 1.0, size=(doy.size, 5, 2))
    r_scalar = ts.loyo_bin_cv(values, doy, years, (365.0,))
    r_vector = ts.loyo_bin_cv(values, doy, years, (365.0,), vector_axis=-1)
    assert r_vector.test_rmse[0] == pytest.approx(r_scalar.test_rmse[0] * np.sqrt(2), rel=0.02)


def test_per_fold_errors_are_reported(axes) -> None:
    """The curve needs an error bar: if the minimum is inside the year-to-year
    scatter, the honest answer is that the granularity cannot be resolved."""
    doy, years = axes
    rng = np.random.default_rng(13)
    values = rng.normal(0, 1.0, size=(doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, (30.0, 365.0))
    assert r.fold_test_rmse.shape == (2, len(np.unique(years)))
    assert np.all(np.isfinite(r.fold_test_rmse))


def test_samples_per_bin_is_reported(axes) -> None:
    doy, years = axes
    values = np.zeros((doy.size, 1))
    r = ts.loyo_bin_cv(values, doy, years, (1.0, 365.0))
    n1 = r.n_per_bin[r.granularity_days == 1.0][0]
    n365 = r.n_per_bin[r.granularity_days == 365.0][0]
    assert n1 == pytest.approx(40, abs=2)        # 10 years x 4 analyses a day
    assert n365 == pytest.approx(14610, rel=0.01)


# --- guards ------------------------------------------------------------------


def test_a_single_year_cannot_be_cross_validated(axes) -> None:
    doy, years = axes
    one = years == 2016
    with pytest.raises(ValueError, match="at least two years"):
        ts.loyo_bin_cv(np.zeros((one.sum(), 1)), doy[one], years[one], (30.0,))


def test_mismatched_lengths_are_rejected(axes) -> None:
    doy, years = axes
    with pytest.raises(ValueError, match="length"):
        ts.loyo_bin_cv(np.zeros((10, 1)), doy, years, (30.0,))


# --- choosing between granularities that tie ---------------------------------


def test_a_tie_is_resolved_towards_the_coarser_model(axes) -> None:
    """The curve is flat near its minimum, so the bare argmin is not a safe
    recommendation: it will pick the finer of two widths that differ by less
    than the noise. The one-standard-error rule prefers the weaker claim."""
    doy, years = axes
    rng = np.random.default_rng(20)
    signal = 6.0 * np.sin(2 * np.pi * 3 * doy)
    values = (signal + rng.normal(0.0, 5.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    assert r.parsimonious_days >= r.best_days


def test_the_parsimonious_choice_sits_inside_the_resolved_range(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(21)
    values = (8.0 * np.sin(2 * np.pi * 4 * doy) + rng.normal(0, 4.0, doy.size))[:, None]
    r = ts.loyo_bin_cv(values, doy, years, ts.DEFAULT_GRANULARITIES_DAYS)
    lo, hi = r.resolved_range()
    assert lo <= r.parsimonious_days <= hi


def test_harmonics_are_also_chosen_parsimoniously(axes) -> None:
    doy, years = axes
    rng = np.random.default_rng(22)
    values = (10.0 * np.sin(2 * np.pi * doy) + rng.normal(0, 2.0, doy.size))[:, None]
    h = ts.loyo_harmonic_cv(values, doy, years, k_values=range(0, 15))
    assert h.parsimonious_k <= h.best_k
    assert h.parsimonious_k >= 1
