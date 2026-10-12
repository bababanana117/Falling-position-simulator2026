"""Resumable, idempotent on-disk cache for downloaded subsets.

The full fetch is roughly 2160 requests and several hours, so it *will* be
interrupted -- by a dropped connection, a server restart, or someone closing the
laptop. The rules that make restarting free:

* Write to ``<name>.nc.part`` and ``os.replace()`` it into position. On the same
  filesystem that is atomic, so a half-written file can never be mistaken for a
  finished one.
* Write the JSON sidecar *after* the rename. "Sidecar exists and its recorded
  shape matches what we asked for" is the definition of complete. A missing
  sidecar means re-fetch, which is the safe direction to fail in.
* ``manifest.jsonl`` is append-only, so concurrent workers cannot corrupt it and
  a resume is one pass over the file.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import HGT_TIME_STRIDE, LEVEL_MIN_HPA, kept_levels
from ..regions import MASTER, BBox
from ..urls import anl_p125_url, anl_p_url, month_urls, nc_varname

__all__ = [
    "FetchTask",
    "append_manifest",
    "cache_path",
    "finalize",
    "is_complete",
    "part_path",
    "plan_tasks",
    "read_manifest",
    "sha256_file",
    "sidecar_path",
]

ANALYSES_PER_DAY = 4


@dataclass(frozen=True)
class FetchTask:
    """One downloaded file: one variable, one source file, one spatial box."""

    var: str
    product: str
    year: int
    month: int
    day0: int
    day1: int
    bbox: BBox = MASTER
    level_min_hpa: float = LEVEL_MIN_HPA
    time_stride: int = 1
    box_name: str = "master"

    @property
    def url(self) -> str:
        if self.product == "anl_p":
            return anl_p_url(self.var, self.year, self.month, self.day0, self.day1)
        return anl_p125_url(self.var, self.year, self.month)

    @property
    def nc_varname(self) -> str:
        return nc_varname(self.var, self.product)

    @property
    def n_days(self) -> int:
        return self.day1 - self.day0 + 1

    @property
    def n_times_source(self) -> int:
        """Analyses in the source file, before any stride is applied."""
        return self.n_days * ANALYSES_PER_DAY

    @property
    def n_times_expected(self) -> int:
        """Analyses we expect to keep."""
        return len(range(0, self.n_times_source, self.time_stride))

    @property
    def n_levels_expected(self) -> int:
        return len(kept_levels(self.level_min_hpa))

    @property
    def stem(self) -> str:
        return (
            f"{self.var}_{self.year:04d}{self.month:02d}{self.day0:02d}"
            f"-{self.year:04d}{self.month:02d}{self.day1:02d}_{self.box_name}"
        )

    @property
    def rel_path(self) -> Path:
        return Path("raw") / self.product / self.var / f"{self.year:04d}" / f"{self.stem}.nc"


def cache_path(root: Path, task: FetchTask) -> Path:
    return Path(root) / task.rel_path


def part_path(nc: Path) -> Path:
    return nc.with_suffix(nc.suffix + ".part")


def sidecar_path(nc: Path) -> Path:
    return nc.with_suffix(".json")


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def is_complete(root: Path, task: FetchTask, *, deep: bool = False) -> bool:
    """Has this task already produced a usable file?

    The fast path checks the sidecar's recorded shape, which catches a truncated
    or wrongly-subset download. ``deep=True`` also re-hashes the file, which is
    for ``--verify`` runs rather than for every resume.
    """
    nc = cache_path(root, task)
    side = sidecar_path(nc)
    if not nc.exists() or not side.exists():
        return False
    try:
        meta = json.loads(side.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    shape = meta.get("shape")
    if not (isinstance(shape, list) and len(shape) == 4):
        return False
    if shape[0] != task.n_times_expected or shape[1] != task.n_levels_expected:
        return False
    if meta.get("nbytes") is not None and nc.stat().st_size == 0:
        return False
    if deep:
        recorded = meta.get("sha256")
        if not recorded or recorded != sha256_file(nc):
            return False
    return True


def finalize(tmp: Path, final: Path, meta: dict[str, Any]) -> None:
    """Atomically move a finished download into place, then record it.

    Order matters: the sidecar is the completion marker, so it must never appear
    before the data it describes.
    """
    final.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta)
    os.replace(tmp, final)
    meta.setdefault("nbytes", final.stat().st_size)
    meta.setdefault("sha256", sha256_file(final))
    side = sidecar_path(final)
    side_tmp = side.with_suffix(".json.part")
    side_tmp.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str))
    os.replace(side_tmp, side)


def discard_partials(root: Path, task: FetchTask) -> None:
    """Remove leftovers from an interrupted attempt."""
    nc = cache_path(root, task)
    for p in (part_path(nc), sidecar_path(nc).with_suffix(".json.part")):
        p.unlink(missing_ok=True)


def plan_tasks(
    vars_: Sequence[str],
    product: str,
    years: Iterable[int],
    *,
    bbox: BBox = MASTER,
    level_min_hpa: float = LEVEL_MIN_HPA,
    months: Iterable[int] = range(1, 13),
    hgt_stride: int = HGT_TIME_STRIDE,
    box_name: str = "master",
) -> list[FetchTask]:
    """Every file that has to be downloaded, in chronological order."""
    months = list(months)
    tasks: list[FetchTask] = []
    for year in years:
        for month in months:
            for var in vars_:
                stride = hgt_stride if var == "hgt" else 1
                for (day0, day1), _url in month_urls(var, product, year, month):
                    tasks.append(
                        FetchTask(
                            var=var,
                            product=product,
                            year=year,
                            month=month,
                            day0=day0,
                            day1=day1,
                            bbox=bbox,
                            level_min_hpa=level_min_hpa,
                            time_stride=stride,
                            box_name=box_name,
                        )
                    )
    return tasks


def pending_tasks(root: Path, tasks: Sequence[FetchTask], *, deep: bool = False) -> list[FetchTask]:
    return [t for t in tasks if not is_complete(root, t, deep=deep)]


def manifest_path(root: Path) -> Path:
    return Path(root) / "raw" / "manifest.jsonl"


def append_manifest(root: Path, record: dict[str, Any]) -> None:
    path = manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def read_manifest(root: Path) -> list[dict[str, Any]]:
    path = manifest_path(root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def task_to_record(task: FetchTask, **extra: Any) -> dict[str, Any]:
    rec = asdict(task)
    rec["bbox"] = asdict(task.bbox)
    rec["url"] = task.url
    rec.update(extra)
    return rec
