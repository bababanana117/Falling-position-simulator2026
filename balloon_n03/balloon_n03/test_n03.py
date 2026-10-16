import threading
import time
import unittest
from datetime import datetime, timedelta
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
from test_weather import fixture
from weather_service import JST
from weather_cache import ForecastCache

START = datetime(2026, 10, 11, 2, 0, tzinfo=JST)
WHEN = '2026-10-11T09:30:00+09:00'


class TestN03(unittest.TestCase):
    def setUp(self):
        self.clock = [START]
        self.calls = []
        self.fetch = lambda lat, lon: self._fetch(lat, lon)

    def _fetch(self, lat, lon):
        self.calls.append((lat, lon))
        return fixture(lat, lon)

    def cache(self, **kwargs):
        return ForecastCache(fetcher=self.fetch, clock=lambda: self.clock[0],
                             retry_delay=0, **kwargs)

    def test_shared_coordinate_and_time(self):
        c = self.cache()
        a = c.get(33, 132.5, WHEN, candidate_id='A')
        b = c.get(33, 132.5, '2026-10-11T10:30:00+09:00', candidate_id='B')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(a['candidate_id'], 'A')
        self.assertEqual(b['candidate_id'], 'B')
        self.assertTrue(b['quality']['cache_hit'])

    def test_force_refresh(self):
        c = self.cache()
        c.get(33, 132.5, WHEN)
        c.get(33, 132.5, WHEN, force=True)
        self.assertEqual(len(self.calls), 2)

    def test_expired_fallback(self):
        c = self.cache()
        c.get(33, 132.5, WHEN)
        self.clock[0] += timedelta(hours=2)
        self.fetch = lambda *args: (_ for _ in ()).throw(ValueError('offline'))
        c.fetcher = self.fetch
        b = c.get(33, 132.5, WHEN)
        self.assertEqual(b['quality']['freshness'], 'stale')
        self.assertEqual(b['quality']['last_refresh']['status'], 'failed')
        self.assertEqual(b['status'], 'partial')  # Fixture intentionally misses gust

    def test_six_hour_purge(self):
        c = self.cache()
        c.get(33, 132.5, WHEN)
        self.clock[0] += timedelta(hours=6)
        c.fetcher = lambda *args: (_ for _ in ()).throw(ValueError('offline'))
        b = c.get(33, 132.5, WHEN)
        self.assertEqual(b['quality']['freshness'], 'unavailable')
        self.assertEqual(b['status'], 'api_error')

    def test_lru(self):
        c = self.cache(max_entries=2)
        c.get(33, 132.5, WHEN)
        c.get(34, 132.5, WHEN)
        c.get(33, 132.5, WHEN)
        c.get(35, 132.5, WHEN)
        self.assertEqual(len(c.entries), 2)
        c.get(34, 132.5, WHEN)
        self.assertEqual(len(self.calls), 4)

    def test_same_key_single_flight(self):
        calls = [0]
        started = threading.Event()
        release = threading.Event()
        def fetch(lat, lon):
            calls[0] += 1
            started.set()
            self.assertTrue(release.wait(3))
            return fixture(lat, lon)
        c = self.cache()
        c.fetcher = fetch
        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(c.get, 33, 132.5, WHEN, 'A')
            self.assertTrue(started.wait(3))
            b = executor.submit(c.get, 33, 132.5, WHEN, 'B', True)
            time.sleep(.05)
            release.set()
            self.assertEqual(a.result()['candidate_id'], 'A')
            self.assertEqual(b.result()['candidate_id'], 'B')
        self.assertEqual(calls[0], 1)

    def test_retry_once(self):
        attempts = [0]
        def fetch(lat, lon):
            attempts[0] += 1
            if attempts[0] == 1:
                raise TimeoutError('timed out')
            return fixture(lat, lon)
        c = self.cache()
        c.fetcher = fetch
        self.assertIn(c.get(33, 132.5, WHEN)['status'], ('success', 'partial'))
        self.assertEqual(attempts[0], 2)

    def test_429_no_retry(self):
        attempts = [0]
        def fetch(lat, lon):
            attempts[0] += 1
            raise HTTPError('test', 429, 'rate limited', {}, None)
        c = self.cache()
        c.fetcher = fetch
        self.assertEqual(c.get(33, 132.5, WHEN)['status'], 'api_error')
        self.assertEqual(attempts[0], 1)

    def test_concurrency_limit(self):
        lock = threading.Lock()
        active = [0]
        peak = [0]
        def fetch(lat, lon):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(.03)
            with lock:
                active[0] -= 1
            return fixture(lat, lon)
        c = self.cache(max_concurrent=2)
        c.fetcher = fetch
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: c.get(30+n, 132.5, WHEN), range(6)))
        self.assertEqual(len(results), 6)
        self.assertLessEqual(peak[0], 2)

    def test_date_key_changes(self):
        c = self.cache()
        c.get(33, 132.5, WHEN)
        self.clock[0] = datetime(2026,10,12,0,5,tzinfo=JST)
        # Different date, same geographic request must not reuse prior 7-day window
        c.get(33,132.5,'2026-10-12T09:30:00+09:00')
        self.assertEqual(len(self.calls),2)

if __name__ == '__main__':
    unittest.main()
