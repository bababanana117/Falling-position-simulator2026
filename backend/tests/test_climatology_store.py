from datetime import UTC, datetime

import numpy as np
import pytest
from climatology_fixture import ALT, make_db

from bfps.climatology.store import ClimatologyStore, timebin_for


@pytest.fixture()
def store(tmp_path):
    p = tmp_path / "clim.duckdb"
    make_db(p, u=12.0, rho=0.4)
    return ClimatologyStore(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ClimatologyStore(tmp_path / "none.duckdb")


def test_nearest_cell(store):
    cid, lat, lon, dist = store.nearest_cell(33.45, 130.40)
    assert cid == 3 and lat == 33.5 and lon == 130.5
    assert 5.0 < dist < 15.0


def test_levels_sorted_by_altitude(store):
    lv = store.levels(3, 0)
    assert np.all(np.diff(lv.alt_m) > 0)
    assert lv.alt_m == pytest.approx(ALT)
    assert lv.u_mean == pytest.approx(np.full(ALT.size, 12.0))


def test_drift_var(store):
    ev, nv = store.drift_var(3, 5)
    assert ev > 0 and nv > 0


@pytest.mark.parametrize("iso,expected", [
    ("2027-01-10T03:00:00+00:00", (0, 1, 1, "1月前半")),
    ("2027-01-15T14:59:00+00:00", (0, 1, 1, "1月前半")),   # JST 1/15 23:59
    ("2027-01-15T15:00:00+00:00", (1, 1, 2, "1月後半")),   # JST 1/16 00:00
    ("2027-12-31T15:30:00+00:00", (0, 1, 1, "1月前半")),   # JST 2028/1/1
    ("2027-02-28T00:00:00+00:00", (3, 2, 2, "2月後半")),
])
def test_timebin_for(iso, expected):
    assert timebin_for(datetime.fromisoformat(iso)) == expected


def test_timebin_naive_is_utc():
    assert timebin_for(datetime(2027, 7, 20, 0, 0)) == (13, 7, 2, "7月後半")
    assert timebin_for(datetime(2027, 7, 20, 0, 0, tzinfo=UTC))[0] == 13
