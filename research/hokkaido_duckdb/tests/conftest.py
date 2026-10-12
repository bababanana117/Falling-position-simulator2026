"""Import paths for the test run.

Two directories have to be importable: ``hokkaido_duckdb`` for ``hokduck``,
and its parent for the upstream aggregation pipeline that the slow tests
reconcile against. Neither package is pip-installed -- the
whole repository works by being run from ``research/`` -- and pytest only
prepends the rootdir of the test package itself, so both are added here.
"""

import sys
from pathlib import Path

_HOKDUCK_PARENT = Path(__file__).resolve().parents[1]   # research/hokkaido_duckdb
_RESEARCH = _HOKDUCK_PARENT.parent                      # research

for _p in (_HOKDUCK_PARENT, _RESEARCH):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: needs the built database or the six-hourly cache"
    )


@pytest.fixture(scope="session")
def db():
    """A read-only connection to the built database, or skip.

    The database is an 300 MB build artefact that is not in git, so tests that
    need it skip rather than fail on a fresh checkout.
    """
    import duckdb
    from hokduck.config import DB_PATH

    if not DB_PATH.exists():
        pytest.skip(f"{DB_PATH.name} not built")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    yield con
    con.close()
