"""Retry policy for a long, unattended download.

The rule that matters most here is what *not* to retry. A 404 means the filename
we constructed is wrong; retrying it six times with backoff just proves that
slowly and then still fails. Those are recorded as ``missing`` and the run
continues, with a loud summary at the end naming every one -- because a handful
of genuinely absent files is survivable, while a systematic naming error is not,
and the difference is obvious from the list.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, Literal, TypeVar

__all__ = [
    "FetchFailed",
    "PermanentFetchError",
    "backoff_delays",
    "classify_error",
    "with_retry",
]

T = TypeVar("T")


class FetchFailed(RuntimeError):
    """A download failed after exhausting its retries."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class PermanentFetchError(FetchFailed):
    """The request will never succeed: the file is not there."""


#: Substrings that mean "this file does not exist", from libnetcdf, THREDDS and HTTP.
_PERMANENT_MARKERS = (
    "404",
    "not found",
    "no such file",
    "file not found",
    "does not exist",
    "unknown file",
)

#: Substrings that mean "the server or the network hiccuped", worth another go.
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "i/o failure",
    "dap failure",
    "curl",
    "500",
    "502",
    "503",
    "504",
)


def backoff_delays(
    attempts: int,
    *,
    base: float = 5.0,
    factor: float = 2.0,
    cap: float = 300.0,
    jitter: float = 0.3,
    rng: random.Random | None = None,
) -> list[float]:
    """Delays before each retry: 5, 10, 20, 40, 80 s ... capped, with jitter.

    Six attempts is about two and a half minutes of patience in total, which is
    deliberately short: a longer outage is handled by re-running the fetch, since
    the cache makes that free.

    Jitter matters because several workers usually fail at the same moment (the
    server went away), and without it they would all come back at the same moment
    too.
    """
    rng = rng or random.Random()
    out: list[float] = []
    for i in range(max(attempts - 1, 0)):
        d = min(base * factor**i, cap)
        out.append(d * (1.0 + rng.uniform(-jitter, jitter)))
    return out


def classify_error(exc: BaseException) -> Literal["retry", "permanent"]:
    """Decide whether an exception is worth another attempt."""
    if isinstance(exc, PermanentFetchError):
        return "permanent"
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(m in text for m in _PERMANENT_MARKERS):
        return "permanent"
    if any(m in text for m in _TRANSIENT_MARKERS):
        return "retry"
    # Unknown failures get retried: a spurious retry costs seconds, while giving
    # up on a transient error costs a whole file.
    return "retry"


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 6,
    url: str | None = None,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    **backoff_kwargs: Any,
) -> T:
    """Call ``fn``, retrying transient failures with exponential backoff."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    delays = backoff_delays(attempts, rng=rng, **backoff_kwargs)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            last = exc
            if classify_error(exc) == "permanent":
                if isinstance(exc, PermanentFetchError):
                    raise
                raise PermanentFetchError(str(exc), url=url) from exc
            if i == attempts - 1:
                break
            delay = delays[i]
            if on_retry is not None:
                on_retry(i + 1, delay, exc)
            sleep(delay)
    raise FetchFailed(f"giving up after {attempts} attempts: {last}", url=url) from last
