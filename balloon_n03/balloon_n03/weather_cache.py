"""N03: bounded, concurrent in-memory forecast cache; independent of flight physics."""
from collections import OrderedDict
from concurrent.futures import Future
from datetime import timedelta
from threading import BoundedSemaphore, Lock
from time import sleep
import socket
from urllib.error import HTTPError, URLError

from weather_service import jst_now, interpret, validate, fetch_raw
from weather_quality import apply_quality, check_config


class ForecastCache:
    def __init__(self, ttl=timedelta(minutes=30), fetcher=fetch_raw,
                 clock=jst_now, thresholds=None, max_entries=200,
                 max_age=timedelta(hours=6), max_concurrent=5,
                 retry_delay=1.0, sleeper=sleep):
        if not (timedelta(0) < ttl <= max_age) or max_entries < 1 or max_concurrent < 1 or retry_delay < 0:
            raise ValueError('キャッシュ設定が不正です')
        self.ttl = ttl
        self.fetcher = fetcher
        self.clock = clock
        self.thresholds = check_config(thresholds)
        self.max_age = max_age
        self.max_entries = max_entries
        self.retry_delay = retry_delay
        self.sleeper = sleeper
        self.entries = OrderedDict()
        self._flights = {}
        self._lock = Lock()
        self._slots = BoundedSemaphore(max_concurrent)

    @staticmethod
    def _key(lat, lon, today):
        # N01's request parameters are constant. If configurable later, include all
        # model, fields, units, timezone and period settings in this cache key.
        return (lat, lon, today, 'best_match', '7days', 'Asia/Tokyo', 'ms')

    @staticmethod
    def _retryable(exc):
        if isinstance(exc, HTTPError):
            return exc.code in (500, 502, 503, 504)
        return isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, URLError))

    def _download(self, lat, lon):
        with self._slots:
            for attempt in range(2):
                try:
                    return self.fetcher(lat, lon)
                except Exception as exc:
                    if attempt or not self._retryable(exc):
                        raise
                    self.sleeper(self.retry_delay)
        raise RuntimeError('unreachable')

    def _purge(self, now):
        for key in list(self.entries):
            if now - self.entries[key]['fetched_at'] >= self.max_age:
                del self.entries[key]

    def _format(self, entry, latitude, longitude, when, candidate_id,
                now, *, cache_hit, refresh, refresh_error=None):
        if entry is None:
            result = {'status': 'api_error', 'error': '予報APIを取得できません',
                      'cache_status': 'unavailable'}
            if refresh_error:
                result['error'] += ': ' + str(refresh_error)
            return apply_quality(result, None, now=now, ttl=self.ttl,
                                 thresholds=self.thresholds, last_refresh=refresh,
                                 cache_hit=False)
        result = interpret(entry['raw'], latitude=latitude, longitude=longitude,
                           when=when, candidate_id=candidate_id,
                           fetched_at=entry['fetched_at'], now=now)
        age = now - entry['fetched_at']
        result['cache_status'] = 'fresh' if age < self.ttl else 'stale'
        if refresh_error:
            result['refresh_error'] = str(refresh_error)
        return apply_quality(result, entry['raw'], now=now, ttl=self.ttl,
                             thresholds=self.thresholds, last_refresh=refresh,
                             cache_hit=cache_hit)

    def get(self, latitude, longitude, when, candidate_id=None, force=False):
        now = self.clock()
        try:
            validate(latitude, longitude, when, now)
        except (ValueError, LookupError) as exc:
            result = {'status': 'out_of_range' if isinstance(exc, LookupError)
                      else 'invalid_input', 'error': str(exc)}
            return apply_quality(result, None, now=now, ttl=self.ttl,
                                 thresholds=self.thresholds,
                                 last_refresh={'status': 'not_attempted'})

        key = self._key(latitude, longitude, now.date())
        with self._lock:
            self._purge(now)
            entry = self.entries.get(key)
            if entry is not None:
                self.entries.move_to_end(key)
            flight = self._flights.get(key)
            # Requests arriving during a fetch share that flight even when force=True.
            if flight is not None:
                leader = False
            elif entry is not None and not force and now - entry['fetched_at'] < self.ttl:
                return self._format(entry, latitude, longitude, when,
                                    candidate_id, now, cache_hit=True,
                                    refresh={'status': 'not_attempted'})
            else:
                flight = Future()
                self._flights[key] = flight
                leader = True

        if leader:
            try:
                raw = self._download(latitude, longitude)
                new_entry = {'raw': raw, 'fetched_at': self.clock()}
                with self._lock:
                    self.entries[key] = new_entry
                    self.entries.move_to_end(key)
                    self._purge(self.clock())
                    while len(self.entries) > self.max_entries:
                        self.entries.popitem(last=False)
                flight.set_result((new_entry, None))
            except Exception as exc:
                flight.set_result((None, exc))
            finally:
                with self._lock:
                    self._flights.pop(key, None)

        new_entry, error = flight.result()
        result_now = self.clock()
        if error is None:
            return self._format(new_entry, latitude, longitude, when,
                                candidate_id, result_now, cache_hit=not leader,
                                refresh={'status': 'success' if leader else 'not_attempted'})
        # On failure, reference data is allowed only from the SAME JST forecast
        # date/key and for under 6 hours. Never label stale data as fresh.
        with self._lock:
            old = self.entries.get(key)
            if old is not None and result_now - old['fetched_at'] >= self.max_age:
                old = None
        return self._format(old, latitude, longitude, when, candidate_id,
                            result_now, cache_hit=old is not None,
                            refresh={'status': 'failed', 'error_code': 'api_error'},
                            refresh_error=error)
