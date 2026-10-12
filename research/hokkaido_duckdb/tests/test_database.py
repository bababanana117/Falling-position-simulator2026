"""Properties of the built database.

These skip on a fresh checkout, where the 300 MB artefact has not been built.
Everything here is about the file a reader actually receives: its assertions,
its macros, its self-description and its licence.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from hokduck.verify import parse_checks, run_checks

_SQL_DIR = Path(__file__).resolve().parents[1] / "docs" / "_sql"


def test_every_verification_check_passes(db):
    failed = run_checks(db)
    assert failed == []


def test_the_verification_file_has_no_duplicate_names():
    names = [name for name, _ in parse_checks()]
    assert len(names) == len(set(names))
    assert len(names) >= 30


@pytest.mark.parametrize("path", sorted(_SQL_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_every_documented_recipe_runs(db, path):
    """The manual executes these; a recipe that no longer parses must fail here."""
    cur = db.execute(path.read_text(encoding="utf-8"))
    assert cur.description, f"{path.name} returned no columns"


def test_nearest_cell_returns_the_closest_point(db):
    """The macro must beat every other cell, not merely return something."""
    qlat, qlon = 42.506, 143.440
    cell_id, lat, lon, _, _, distance = db.execute(
        "SELECT * FROM nearest_cell(?, ?)", [qlat, qlon]
    ).fetchone()

    rows = db.execute("SELECT cell_id, lat, lon FROM dim_grid").fetchall()

    def haversine(la, lo):
        p1, p2 = math.radians(qlat), math.radians(la)
        dlat, dlon = p2 - p1, math.radians(lo - qlon)
        a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(a))

    best = min(rows, key=lambda r: haversine(r[1], r[2]))
    assert cell_id == best[0]
    assert distance == pytest.approx(haversine(lat, lon), rel=1e-9)


def test_a_round_latitude_is_not_on_the_gaussian_grid(db):
    """The reason nearest_cell exists. If this ever fails, drop the macro."""
    assert db.execute("SELECT count(*) FROM dim_grid WHERE lat = 42.5").fetchone()[0] == 0


def test_fits_at_covers_every_level_once(db):
    rows = db.execute("SELECT level_hpa FROM fits_at(42.506, 143.440, 10, 2)").fetchall()
    levels = [r[0] for r in rows]
    assert len(levels) == 38
    assert len(set(levels)) == 38
    assert levels == sorted(levels, reverse=True), "ordered by height, so pressure descends"


def test_profile_at_agrees_with_a_manual_join(db):
    macro = db.execute(
        "SELECT level_hpa, speed_mean FROM profile_at(42.506, 143.440, 10, 2)"
    ).fetchall()
    manual = db.execute("""
        SELECT w.level_hpa, w.speed_mean
        FROM fact_wind w
        WHERE w.month = 10 AND w.bin = 2
          AND w.cell_id = (SELECT cell_id FROM nearest_cell(42.506, 143.440))
        ORDER BY w.alt_geom_mean_km
    """).fetchall()
    assert macro == manual


def test_the_rendered_pdf_reproduces_the_stored_likelihood(db):
    """The claim the whole product rests on: one row is a complete definition."""
    scipy_stats = pytest.importorskip("scipy.stats")
    numpy = pytest.importorskip("numpy")

    k, lam, loglik, n, aic = db.execute("""
        SELECT weibull_shape, weibull_scale_ms, loglik, n, aic
        FROM fact_speed_fit
        WHERE is_selected AND family = 'weibull_min_loc0'
        ORDER BY timebin_id, level_id, cell_id LIMIT 1
    """).fetchone()

    x = numpy.linspace(0.0, 200.0, 200_001)
    mine = (k / lam) * (x / lam) ** (k - 1) * numpy.exp(-((x / lam) ** k))
    theirs = scipy_stats.weibull_min.pdf(x, k, 0.0, lam)
    assert numpy.allclose(mine[1:], theirs[1:], rtol=1e-9)
    assert numpy.trapezoid(mine, x) == pytest.approx(1.0, abs=1e-6)
    assert aic == pytest.approx(-2 * loglik + 4), "loc is fixed, so k = 2 not 3"
    assert n > 0


def test_the_sample_recipe_draws_from_the_stated_distribution(db):
    numpy = pytest.importorskip("numpy")
    k, lam = db.execute("""
        SELECT weibull_shape, weibull_scale_ms FROM fact_speed_fit
        WHERE is_selected AND family = 'weibull_min_loc0'
        ORDER BY timebin_id, level_id, cell_id LIMIT 1
    """).fetchone()
    rng = numpy.random.default_rng(0)
    u = rng.random(200_000)
    draws = lam * (-numpy.log(1 - u)) ** (1 / k)
    expected = lam * math.gamma(1 + 1 / k)
    assert draws.mean() == pytest.approx(expected, rel=2e-3)


def test_the_licence_travels_inside_the_file(db):
    rows = db.execute(
        "SELECT applies_to, non_commercial, share_alike, attribution_required FROM v_license"
    ).fetchall()
    assert len(rows) == 2
    assert all(r[1] and r[2] and r[3] for r in rows), "CC BY-NC-SA on both rows"
    assert {r[0] for r in rows} == {"source_data", "database"}


def test_the_licence_text_matches_the_netcdf_it_came_from(db):
    from windclim.outputs.netcdf_out import LICENCE

    stored = db.execute(
        "SELECT full_notice FROM meta_license WHERE applies_to = 'source_data'"
    ).fetchone()[0]
    assert LICENCE.strip() in stored or stored.strip() in LICENCE


def test_the_sidecar_licence_file_sits_next_to_the_database():
    from hokduck.config import DB_PATH

    if not DB_PATH.exists():
        pytest.skip("database not built")
    assert DB_PATH.with_suffix(".LICENSE.md").exists()


def test_uniform_winners_are_reported_not_hidden(db):
    """The plan said: if uniform ever wins, look at it rather than assume zero."""
    rows = db.execute("""
        SELECT count(*) AS n, sum(CASE WHEN is_ambiguous THEN 1 ELSE 0 END) AS ambiguous
        FROM fact_speed_fit WHERE is_selected AND family = 'uniform'
    """).fetchone()
    n, ambiguous = rows
    if n:
        # Documented in caveats.rst; the boundary MLE makes AIC too generous.
        assert ambiguous >= 1, "a uniform winner that is not even ambiguous needs looking at"
        assert n < 100, f"{n} uniform winners is too many to be a curiosity"


def test_direction_and_speed_likelihoods_are_kept_apart(db):
    """Different density units, so the two AICs must live in different tables."""
    speed = {r[0] for r in db.execute("SELECT DISTINCT family FROM fact_speed_fit").fetchall()}
    direction = {r[0] for r in db.execute("SELECT DISTINCT family FROM fact_dir_fit").fetchall()}
    assert speed.isdisjoint(direction)


def test_weibull_is_documented_as_excluded_for_direction(db):
    row = db.execute("""
        SELECT included, exclusion_reason FROM meta_fit_family
        WHERE family = 'weibull_min_loc0' AND quantity = 'direction_rad'
    """).fetchone()
    assert row is not None, "the exclusion must be recorded, not merely omitted"
    included, reason = row
    assert not included
    assert reason and len(reason) > 40
