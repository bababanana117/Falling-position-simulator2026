"""Backoff schedule and, more importantly, what must not be retried."""

from __future__ import annotations

import random

import pytest

from windclim.fetch import retry

# --- backoff schedule --------------------------------------------------------


def test_backoff_is_exponential_and_capped() -> None:
    d = retry.backoff_delays(8, base=5.0, factor=2.0, cap=300.0, jitter=0.0)
    assert d == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0]


def test_backoff_has_one_fewer_delay_than_attempts() -> None:
    assert len(retry.backoff_delays(6, jitter=0.0)) == 5
    assert retry.backoff_delays(1) == []


def test_backoff_jitter_stays_within_bounds_and_varies() -> None:
    rng = random.Random(0)
    d = retry.backoff_delays(6, base=5.0, factor=2.0, jitter=0.3, rng=rng)
    nominal = [5.0, 10.0, 20.0, 40.0, 80.0]
    for got, want in zip(d, nominal, strict=True):
        assert 0.7 * want <= got <= 1.3 * want
    assert d != nominal


def test_total_patience_is_a_couple_of_minutes() -> None:
    """Short on purpose: a longer outage is handled by resuming, not by waiting."""
    assert 120.0 < sum(retry.backoff_delays(6, jitter=0.0)) < 200.0


# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "HTTP 404: Not Found",
        "NetCDF: file not found",
        "resource does not exist",
        "unknown file",
    ],
)
def test_missing_file_errors_are_permanent(message: str) -> None:
    assert retry.classify_error(OSError(message)) == "permanent"


@pytest.mark.parametrize(
    "message",
    [
        "NetCDF: I/O failure",
        "NetCDF: DAP failure",
        "The read operation timed out",
        "Connection reset by peer",
        "HTTP 503 Service Unavailable",
        "curl error 56",
    ],
)
def test_server_and_network_errors_are_retried(message: str) -> None:
    assert retry.classify_error(OSError(message)) == "retry"


def test_unknown_errors_are_retried() -> None:
    """A spurious retry costs seconds; giving up early costs the whole file."""
    assert retry.classify_error(RuntimeError("something odd happened")) == "retry"


# --- with_retry --------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_succeeds_immediately_without_sleeping() -> None:
    sleeper = _Recorder()
    assert retry.with_retry(lambda: 42, sleep=sleeper) == 42
    assert sleeper.slept == []


def test_retries_then_succeeds_and_follows_the_schedule() -> None:
    calls = {"n": 0}
    sleeper = _Recorder()

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("NetCDF: I/O failure")
        return "ok"

    assert retry.with_retry(flaky, attempts=6, sleep=sleeper, jitter=0.0) == "ok"
    assert calls["n"] == 3
    assert sleeper.slept == [5.0, 10.0]


def test_a_permanent_error_is_not_retried_at_all() -> None:
    """The point of the classifier: a wrong filename must fail in one attempt."""
    calls = {"n": 0}
    sleeper = _Recorder()

    def missing() -> None:
        calls["n"] += 1
        raise OSError("HTTP 404: Not Found")

    with pytest.raises(retry.PermanentFetchError):
        retry.with_retry(missing, attempts=6, url="http://example/x.nc", sleep=sleeper)
    assert calls["n"] == 1
    assert sleeper.slept == []


def test_exhaustion_raises_fetch_failed_carrying_the_url() -> None:
    sleeper = _Recorder()

    def always_fails() -> None:
        raise OSError("NetCDF: DAP failure")

    with pytest.raises(retry.FetchFailed) as excinfo:
        retry.with_retry(
            always_fails, attempts=4, url="http://example/y.nc", sleep=sleeper, jitter=0.0
        )
    assert excinfo.value.url == "http://example/y.nc"
    assert "DAP failure" in str(excinfo.value)
    assert sleeper.slept == [5.0, 10.0, 20.0]


def test_permanent_error_is_a_subclass_of_fetch_failed() -> None:
    assert issubclass(retry.PermanentFetchError, retry.FetchFailed)


def test_on_retry_callback_sees_each_attempt() -> None:
    seen: list[tuple[int, float]] = []
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("timeout")
        return "ok"

    retry.with_retry(
        flaky,
        attempts=5,
        on_retry=lambda i, d, e: seen.append((i, d)),
        sleep=_Recorder(),
        jitter=0.0,
    )
    assert seen == [(1, 5.0), (2, 10.0)]


def test_keyboard_interrupt_is_not_swallowed() -> None:
    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        retry.with_retry(interrupted, sleep=_Recorder())


def test_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError):
        retry.with_retry(lambda: 1, attempts=0)
