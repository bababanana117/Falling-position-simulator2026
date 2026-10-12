"""Run the build's assertions against a finished database.

``sql/90_verify.sql`` holds one query per assertion, each of which must return
zero rows. This module runs them and reports the first few offending rows of
anything that fails, so a broken build says what is broken rather than just
that something is.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb

from .config import DB_PATH, SQL_DIR

log = logging.getLogger(__name__)

__all__ = ["Failure", "parse_checks", "run_checks"]

_NAME = re.compile(r"^--\s*@name\s+(\S+)\s*$", re.MULTILINE)


class Failure(Exception):
    """Raised when an assertion returns rows."""


def parse_checks(path: Path | None = None) -> list[tuple[str, str]]:
    """``(name, sql)`` for each ``-- @name`` block in the verification file."""
    path = path or (SQL_DIR / "90_verify.sql")
    text = path.read_text(encoding="utf-8")
    marks = list(_NAME.finditer(text))
    if not marks:
        raise ValueError(f"no '-- @name' markers in {path}")
    checks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip().rstrip(";")
        if body:
            checks.append((m.group(1), body))
    return checks


def run_checks(con: duckdb.DuckDBPyConnection, path: Path | None = None) -> list[str]:
    """Run every assertion. Returns the names that failed, empty if all passed."""
    failed = []
    for name, sql in parse_checks(path):
        try:
            rows = con.execute(sql).fetchall()
        except duckdb.Error as exc:                       # a broken assertion is a failure
            log.error("check %-40s ERROR %s", name, exc)
            failed.append(name)
            continue
        if rows:
            log.error("check %-40s FAILED (%d rows), first: %s", name, len(rows), rows[0])
            failed.append(name)
        else:
            log.info("check %-40s ok", name)
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--quiet", action="store_true", help="only report failures")
    a = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s"
    )
    if not a.db.exists():
        print(f"no database at {a.db}", file=sys.stderr)
        return 2
    with duckdb.connect(str(a.db), read_only=True) as con:
        failed = run_checks(con)
    total = len(parse_checks())
    if failed:
        print(f"\n{len(failed)} of {total} checks FAILED: {', '.join(failed)}")
        return 1
    print(f"\nall {total} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
