"""The schema declaration is the single source of the DDL and the comments.

``jpduck.schema`` declares every table and column once. ``create_statements``
and ``comment_statements`` are both generated from that declaration, and
``meta_column`` is loaded from it too, so the three cannot drift apart. These
tests pin the properties that make that true.
"""

from __future__ import annotations

import re

import duckdb
import pytest

from jpduck.ingest.meta import build_meta_column
from jpduck.schema import TABLES, TABLES_BY_NAME, comment_statements, create_statements


def test_every_table_is_declared_once():
    names = [t.name for t in TABLES]
    assert len(names) == len(set(names))
    assert set(names) == set(TABLES_BY_NAME)


def test_every_column_has_a_comment():
    missing = [
        f"{t.name}.{c.name}" for t in TABLES for c in t.columns if not c.comment
    ]
    assert missing == [], "a column without a comment would fail the docs build"


#: Suffixes that name a physical quantity. A surrogate key or a label has no
#: unit and is meant to have ``unit = None``; a length in metres is not.
_UNIT_SUFFIXES = ("_ms", "_km", "_m", "_m2", "_deg", "_rad", "_hpa", "_s", "_pct")


def test_columns_that_carry_a_quantity_declare_its_unit():
    missing = [
        f"{t.name}.{c.name}"
        for t in TABLES
        for c in t.columns
        if c.name.endswith(_UNIT_SUFFIXES) and c.unit is None
    ]
    assert missing == []


def test_column_names_are_unique_within_a_table():
    for table in TABLES:
        names = [c.name for c in table.columns]
        assert len(names) == len(set(names)), table.name


def test_order_by_columns_exist():
    for table in TABLES:
        known = {c.name for c in table.columns}
        assert set(table.order_by or ()) <= known, table.name


def test_the_declared_ddl_actually_runs():
    """A typo in a type or an ENUM would otherwise only show up in a 9-minute build."""
    with duckdb.connect() as con:
        for stmt in create_statements():
            con.execute(stmt)
        for stmt in comment_statements():
            con.execute(stmt)
        rows = con.execute(
            "SELECT table_name, column_name, data_type, comment FROM duckdb_columns() "
            "WHERE database_name = current_database() AND schema_name = 'main' "
            "AND NOT internal"
        ).fetchall()

    declared = {(t.name, c.name) for t in TABLES for c in t.columns}
    built = {(r[0], r[1]) for r in rows}
    assert built == declared
    assert all(r[3] for r in rows), "every column must carry its COMMENT ON"


def test_comment_statements_cover_every_column_exactly_once():
    targets = re.findall(r"COMMENT ON COLUMN (\S+)\.(\S+) IS", "\n".join(comment_statements()))
    declared = [(t.name, c.name) for t in TABLES for c in t.columns]
    assert sorted(targets) == sorted(declared)


def test_meta_column_matches_the_declaration():
    """meta_column travels inside the file; it must say the same thing."""
    frame = build_meta_column()
    pairs = set(zip(frame["table_name"], frame["column_name"], strict=True))
    declared = {(t.name, c.name) for t in TABLES for c in t.columns}
    assert pairs == declared
    assert not frame["description"].isna().any()


@pytest.mark.parametrize("table", ["fact_wind", "fact_speed_fit", "fact_dir_fit"])
def test_fact_tables_carry_both_keys_and_natural_values(table):
    """The redundancy is deliberate: it removes a join from every query."""
    names = {c.name for c in TABLES_BY_NAME[table].columns}
    assert {"timebin_id", "level_id", "cell_id"} <= names
    assert {"month", "bin", "level_hpa", "lat", "lon"} <= names


def test_stored_comments_are_plain_text():
    """A COMMENT ON is read verbatim in a SQL client, and inserted verbatim
    into the manual. reStructuredText markup in it renders as literal
    asterisks in both places, so none is allowed."""
    offenders = [
        f"{t.name}.{c.name}"
        for t in TABLES
        for c in t.columns
        if "**" in c.comment or "``" in c.comment
    ]
    assert offenders == []
