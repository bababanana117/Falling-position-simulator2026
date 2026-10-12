"""Cache paths, completion detection, resumability and task planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from windclim.config import HGT_TIME_STRIDE
from windclim.fetch import cache
from windclim.regions import MASTER


def a_task(**kw) -> cache.FetchTask:
    base = dict(var="ugrd", product="anl_p", year=2016, month=1, day0=1, day1=5)
    base.update(kw)
    return cache.FetchTask(**base)


# --- identity ----------------------------------------------------------------


def test_cache_path_is_deterministic_and_nested_by_year() -> None:
    p = cache.cache_path(Path("/tmp/root"), a_task())
    assert p == Path("/tmp/root/raw/anl_p/ugrd/2016/ugrd_20160101-20160105_master.nc")


def test_sidecar_and_part_paths_sit_next_to_the_data() -> None:
    nc = cache.cache_path(Path("/r"), a_task())
    assert cache.sidecar_path(nc).name == "ugrd_20160101-20160105_master.json"
    assert cache.part_path(nc).name == "ugrd_20160101-20160105_master.nc.part"


def test_url_matches_the_urls_module() -> None:
    assert a_task().url.endswith("ugrd-pres-an-gauss.2016010100_2016010518.nc")
    assert a_task(product="anl_p125", day1=31).url.endswith(
        "ugrd-pres-an-ll125.2016010100_2016013118.nc"
    )


def test_expected_counts() -> None:
    t = a_task()
    assert t.n_days == 5
    assert t.n_times_source == 20
    assert t.n_times_expected == 20
    assert t.n_levels_expected == 38


def test_hgt_stride_keeps_one_analysis_per_file() -> None:
    t = a_task(var="hgt", time_stride=HGT_TIME_STRIDE)
    assert t.n_times_source == 20
    assert t.n_times_expected == 1


def test_task_is_hashable_so_it_can_key_a_dict() -> None:
    assert len({a_task(), a_task()}) == 1


# --- completion detection ----------------------------------------------------


def _write_complete(root: Path, task: cache.FetchTask, *, shape=None) -> Path:
    nc = cache.cache_path(root, task)
    nc.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.part_path(nc)
    tmp.write_bytes(b"not really netcdf, but non-empty")
    shape = shape or [task.n_times_expected, task.n_levels_expected, 49, 49]
    cache.finalize(tmp, nc, {"url": task.url, "shape": shape})
    return nc


def test_absent_file_is_not_complete(tmp_path: Path) -> None:
    assert not cache.is_complete(tmp_path, a_task())


def test_a_part_file_alone_is_not_complete(tmp_path: Path) -> None:
    nc = cache.cache_path(tmp_path, a_task())
    nc.parent.mkdir(parents=True, exist_ok=True)
    cache.part_path(nc).write_bytes(b"half a download")
    assert not cache.is_complete(tmp_path, a_task())


def test_finalize_makes_it_complete(tmp_path: Path) -> None:
    _write_complete(tmp_path, a_task())
    assert cache.is_complete(tmp_path, a_task())


def test_finalize_removes_the_part_file(tmp_path: Path) -> None:
    nc = _write_complete(tmp_path, a_task())
    assert not cache.part_path(nc).exists()


def test_finalize_records_size_and_hash(tmp_path: Path) -> None:
    nc = _write_complete(tmp_path, a_task())
    meta = json.loads(cache.sidecar_path(nc).read_text())
    assert meta["nbytes"] == nc.stat().st_size
    assert len(meta["sha256"]) == 64


def test_data_without_a_sidecar_is_not_complete(tmp_path: Path) -> None:
    nc = _write_complete(tmp_path, a_task())
    cache.sidecar_path(nc).unlink()
    assert not cache.is_complete(tmp_path, a_task())


def test_a_corrupt_sidecar_re_queues_the_task(tmp_path: Path) -> None:
    nc = _write_complete(tmp_path, a_task())
    cache.sidecar_path(nc).write_text("{ this is not json")
    assert not cache.is_complete(tmp_path, a_task())


def test_a_wrong_shape_re_queues_the_task(tmp_path: Path) -> None:
    """Catches a truncated download or a subset taken with the wrong bounds."""
    _write_complete(tmp_path, a_task(), shape=[19, 38, 49, 49])
    assert not cache.is_complete(tmp_path, a_task())


def test_wrong_level_count_re_queues_the_task(tmp_path: Path) -> None:
    _write_complete(tmp_path, a_task(), shape=[20, 45, 49, 49])
    assert not cache.is_complete(tmp_path, a_task())


def test_deep_check_detects_a_modified_file(tmp_path: Path) -> None:
    nc = _write_complete(tmp_path, a_task())
    assert cache.is_complete(tmp_path, a_task(), deep=True)
    nc.write_bytes(b"tampered with, same length......")
    assert not cache.is_complete(tmp_path, a_task(), deep=True)


def test_discard_partials_is_safe_to_call_twice(tmp_path: Path) -> None:
    cache.discard_partials(tmp_path, a_task())
    cache.discard_partials(tmp_path, a_task())


# --- planning ----------------------------------------------------------------


def test_plan_tasks_full_run_is_2160_requests() -> None:
    tasks = cache.plan_tasks(("ugrd", "vgrd", "hgt"), "anl_p", range(2016, 2026))
    assert len(tasks) == 2160          # 10 years x 12 months x 6 chunks x 3 vars
    assert len({t.rel_path for t in tasks}) == 2160


def test_plan_tasks_gives_hgt_a_stride_but_not_the_winds() -> None:
    tasks = cache.plan_tasks(("ugrd", "hgt"), "anl_p", [2016], months=[1])
    assert {t.time_stride for t in tasks if t.var == "ugrd"} == {1}
    assert {t.time_stride for t in tasks if t.var == "hgt"} == {HGT_TIME_STRIDE}


def test_plan_tasks_covers_february_correctly() -> None:
    tasks = cache.plan_tasks(("ugrd",), "anl_p", [2016], months=[2])
    assert [(t.day0, t.day1) for t in tasks][-1] == (26, 29)
    tasks = cache.plan_tasks(("ugrd",), "anl_p", [2017], months=[2])
    assert [(t.day0, t.day1) for t in tasks][-1] == (26, 28)


def test_plan_tasks_for_anl_p125_is_one_file_per_month() -> None:
    tasks = cache.plan_tasks(("ugrd",), "anl_p125", [2016])
    assert len(tasks) == 12


def test_plan_tasks_carries_the_bbox_through() -> None:
    t = cache.plan_tasks(("ugrd",), "anl_p", [2016], months=[1])[0]
    assert t.bbox == MASTER


def test_pending_tasks_skips_what_is_already_done(tmp_path: Path) -> None:
    tasks = cache.plan_tasks(("ugrd",), "anl_p", [2016], months=[1])
    assert len(cache.pending_tasks(tmp_path, tasks)) == 6
    _write_complete(tmp_path, tasks[0])
    _write_complete(tmp_path, tasks[3])
    pending = cache.pending_tasks(tmp_path, tasks)
    assert len(pending) == 4
    assert tasks[0] not in pending


# --- manifest ----------------------------------------------------------------


def test_manifest_round_trip(tmp_path: Path) -> None:
    cache.append_manifest(tmp_path, {"url": "a", "status": "ok"})
    cache.append_manifest(tmp_path, {"url": "b", "status": "missing"})
    rows = cache.read_manifest(tmp_path)
    assert [r["url"] for r in rows] == ["a", "b"]
    assert rows[1]["status"] == "missing"


def test_reading_an_absent_manifest_gives_an_empty_list(tmp_path: Path) -> None:
    assert cache.read_manifest(tmp_path) == []


def test_task_to_record_is_json_serialisable() -> None:
    rec = cache.task_to_record(a_task(), status="ok", elapsed_s=1.5)
    json.dumps(rec)
    assert rec["status"] == "ok"
    assert rec["bbox"]["north"] == pytest.approx(MASTER.north)
    assert rec["url"].startswith("https://")
