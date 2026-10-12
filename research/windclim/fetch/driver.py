"""Runs the whole download: scheduling, politeness, logging and the final tally.

Two choices here are worth stating.

**Processes, not threads.** netCDF4/HDF5 thread-safety depends on how the library
was built, and -- more decisively -- a DAP call that hangs past its timeout can
only be *killed* if it is a process. ``future.result(timeout=...)`` on a thread
leaves the thread running forever.

**Six workers, with a minimum spacing between requests.** GDEX is a shared,
publicly funded service and each request makes it decompress about 420 MB, so
the first guess was that concurrency would buy nothing. Measurement said
otherwise: three workers averaged 13.7 s per file -- the same as one -- while six
reached 4.3 s. Six is used because it is measurably faster and still a modest
number of connections; no attempt was made to find where it stops scaling.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..config import MAX_WORKERS, MIN_REQUEST_INTERVAL_S
from .cache import (
    FetchTask,
    append_manifest,
    cache_path,
    discard_partials,
    finalize,
    part_path,
    pending_tasks,
    task_to_record,
)
from .ncss import NcssFetcher
from .normalize import SlabValidationError
from .opendap import OpendapFetcher
from .retry import FetchFailed, PermanentFetchError, with_retry

__all__ = ["FetchReport", "make_fetcher", "run_fetch"]

log = logging.getLogger(__name__)

_FETCHERS = {"opendap": OpendapFetcher, "ncss": NcssFetcher}

# Shared across worker processes by the pool initialiser.
_RATE_LOCK = None
_LAST_REQUEST = None
_FETCHER_NAME = "opendap"
_CACHE_ROOT = Path(".")
_MIN_INTERVAL = MIN_REQUEST_INTERVAL_S


def make_fetcher(name: str):
    try:
        return _FETCHERS[name]()
    except KeyError:
        raise ValueError(f"unknown fetcher {name!r}; choose from {sorted(_FETCHERS)}") from None


@dataclass
class FetchReport:
    """What happened, in a form that is safe to print at the end of a long run."""

    completed: int = 0
    skipped: int = 0
    bytes_total: int = 0
    elapsed_s: float = 0.0
    missing: list[str] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.failed and not self.invalid

    def summary(self) -> str:
        lines = [
            f"fetched {self.completed}, skipped {self.skipped} already-complete, "
            f"{self.bytes_total / 1e9:.2f} GB in {self.elapsed_s / 60:.1f} min",
        ]
        if self.missing:
            lines.append(f"MISSING ({len(self.missing)}) -- these files were not on the server:")
            lines += [f"  {u}" for u in self.missing[:20]]
            if len(self.missing) > 20:
                lines.append(f"  ... and {len(self.missing) - 20} more")
            lines.append(
                "  A handful of gaps is survivable. A long list means the filename "
                "pattern is wrong -- check windclim/urls.py against the live catalog."
            )
        if self.invalid:
            lines.append(
                f"INVALID ({len(self.invalid)}) -- downloaded but failed the physical checks. "
                "Re-running will not help; either the archive changed or windclim is wrong:"
            )
            lines += [f"  {u}: {err}" for u, err in self.invalid[:20]]
        if self.failed:
            lines.append(f"FAILED ({len(self.failed)}) -- retry by re-running; the cache resumes:")
            lines += [f"  {u}: {err}" for u, err in self.failed[:20]]
        return "\n".join(lines)


def _init_worker(fetcher_name: str, cache_root: str, min_interval: float, lock, last) -> None:
    global _FETCHER_NAME, _CACHE_ROOT, _MIN_INTERVAL, _RATE_LOCK, _LAST_REQUEST
    _FETCHER_NAME = fetcher_name
    _CACHE_ROOT = Path(cache_root)
    _MIN_INTERVAL = min_interval
    _RATE_LOCK = lock
    _LAST_REQUEST = last
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(process)d] %(message)s",
    )


def _throttle() -> None:
    """Keep at least ``_MIN_INTERVAL`` seconds between request starts, pool-wide."""
    if _RATE_LOCK is None or _LAST_REQUEST is None:
        return
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _LAST_REQUEST.value + _MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _LAST_REQUEST.value = now


def _run_one(task: FetchTask) -> dict:
    """Worker entry point. Always returns a record; never raises across the pool."""
    started = datetime.now(UTC)
    nc = cache_path(_CACHE_ROOT, task)
    discard_partials(_CACHE_ROOT, task)
    fetcher = make_fetcher(_FETCHER_NAME)

    def attempt() -> dict:
        _throttle()
        ds, checks = fetcher.fetch(task)
        nc.parent.mkdir(parents=True, exist_ok=True)
        tmp = part_path(nc)
        name = checks["canonical_name"]
        encoding = {name: {"zlib": True, "complevel": 1, "dtype": "float32"}}
        ds.to_netcdf(tmp, engine="netcdf4", encoding=encoding)
        ds.close()
        return checks

    try:
        checks = with_retry(
            attempt,
            attempts=6,
            url=task.url,
            on_retry=lambda i, d, e: log.warning(
                "retry %d in %.0fs after %s: %s", i, d, type(e).__name__, e
            ),
        )
    except SlabValidationError as exc:
        discard_partials(_CACHE_ROOT, task)
        return task_to_record(task, status="invalid", error=str(exc), started_at=started)
    except PermanentFetchError as exc:
        discard_partials(_CACHE_ROOT, task)
        return task_to_record(task, status="missing", error=str(exc), started_at=started)
    except FetchFailed as exc:
        discard_partials(_CACHE_ROOT, task)
        return task_to_record(task, status="failed", error=str(exc), started_at=started)
    except Exception as exc:  # noqa: BLE001 - reported, never crashes the pool
        discard_partials(_CACHE_ROOT, task)
        return task_to_record(
            task, status="failed", error=f"{type(exc).__name__}: {exc}", started_at=started
        )

    meta = dict(checks)
    meta.update(
        {
            "url": task.url,
            "var": task.var,
            "product": task.product,
            "fetched_at": datetime.now(UTC).isoformat(),
            "windclim_version": _version(),
            "git_commit": _git_commit(),
        }
    )
    finalize(part_path(nc), nc, meta)
    return task_to_record(
        task,
        status="ok",
        nbytes=nc.stat().st_size,
        elapsed_s=checks.get("elapsed_s"),
        started_at=started,
    )


def _version() -> str:
    from .. import __version__  # local import keeps worker start-up cheap

    return __version__


def _git_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is nice to have, not required
        return "unknown"


def free_bytes(path: Path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def run_fetch(
    tasks: Sequence[FetchTask],
    *,
    cache_root: Path,
    fetcher_name: str = "opendap",
    workers: int = MAX_WORKERS,
    min_interval_s: float = MIN_REQUEST_INTERVAL_S,
    dry_run: bool = False,
    deep_verify: bool = False,
    required_free_gb: float = 20.0,
) -> FetchReport:
    """Download every pending task, resuming whatever is already cached."""
    cache_root = Path(cache_root)
    report = FetchReport()

    todo = pending_tasks(cache_root, tasks, deep=deep_verify)
    report.skipped = len(tasks) - len(todo)

    if dry_run:
        for t in todo:
            print(t.url)
        return report

    cache_root.mkdir(parents=True, exist_ok=True)
    free_gb = free_bytes(cache_root) / 1e9
    if free_gb < required_free_gb:
        raise RuntimeError(
            f"only {free_gb:.1f} GB free at {cache_root}; "
            f"the full cache needs about 11 GB and this run wants {required_free_gb:.0f} GB "
            "of headroom. Free some space or point WINDCLIM_CACHE elsewhere."
        )

    log.info(
        "fetching %d files (%d already cached) with %d workers via %s; %.0f GB free",
        len(todo),
        report.skipped,
        workers,
        fetcher_name,
        free_gb,
    )

    t0 = time.perf_counter()
    ctx = mp.get_context("spawn")
    lock = ctx.Lock()
    last = ctx.Value("d", 0.0)
    done = 0
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=ctx,
        initializer=_init_worker,
        initargs=(fetcher_name, str(cache_root), min_interval_s, lock, last),
    ) as pool:
        futures = {pool.submit(_run_one, t): t for t in todo}
        for fut in as_completed(futures):
            rec = fut.result()
            append_manifest(cache_root, rec)
            done += 1
            status = rec["status"]
            if status == "ok":
                report.completed += 1
                report.bytes_total += int(rec.get("nbytes") or 0)
            elif status == "missing":
                report.missing.append(rec["url"])
            elif status == "invalid":
                report.invalid.append((rec["url"], str(rec.get("error"))))
            else:
                report.failed.append((rec["url"], str(rec.get("error"))))
            if done % 25 == 0 or done == len(todo):
                rate = done / max(time.perf_counter() - t0, 1e-9)
                remaining = (len(todo) - done) / rate if rate > 0 else float("nan")
                log.info(
                    "%d/%d done (%d ok, %d missing, %d failed) - about %.0f min left",
                    done,
                    len(todo),
                    report.completed,
                    len(report.missing),
                    len(report.failed) + len(report.invalid),
                    remaining / 60.0,
                )

    report.elapsed_s = time.perf_counter() - t0
    return report
