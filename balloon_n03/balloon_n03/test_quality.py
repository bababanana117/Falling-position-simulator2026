import unittest
from datetime import datetime, timedelta
from weather_service import JST
from weather_cache import ForecastCache
from weather_quality import apply_quality, check_config
from test_weather import fixture, NOW

WHEN = '2026-10-11T09:30:00+09:00'

class QualityTests(unittest.TestCase):
    def test_valid_and_missing(self):
        cache = ForecastCache(fetcher=fixture, clock=lambda: NOW)
        out = cache.get(33, 132.5, WHEN)
        self.assertEqual(out['status'], 'partial')
        self.assertEqual(out['quality']['freshness'], 'fresh')
        self.assertFalse(out['quality']['cache_hit'])
        self.assertTrue(any(i['field']=='wind_gust_ms' and i['type']=='missing' for i in out['quality']['issues']))
        out = cache.get(33,132.5,WHEN)
        self.assertTrue(out['quality']['cache_hit'])
        self.assertEqual(out['quality']['last_refresh']['status'],'not_attempted')

    def test_invalid_field_only(self):
        def bad(lat,lon):
            data=fixture(lat,lon)
            data['hourly']['wind_speed_10m'][9]=-3
            data['hourly']['wind_direction_10m'][9]=400
            return data
        out=ForecastCache(fetcher=bad,clock=lambda:NOW).get(33,132.5,WHEN)
        self.assertIsNone(out['forecast']['before']['wind_speed_ms'])
        self.assertIsNone(out['forecast']['before']['wind_direction_deg'])
        self.assertEqual(out['forecast']['before']['temperature_c'],22.3)
        self.assertTrue(any(i['type']=='invalid_value' for i in out['quality']['issues']))

    def test_extreme_kept_and_custom_threshold(self):
        def windy(lat,lon):
            data=fixture(lat,lon)
            data['hourly']['wind_speed_10m'][9]=15
            return data
        c=ForecastCache(fetcher=windy,clock=lambda:NOW,thresholds={'wind_speed_ms':{'max':10}})
        out=c.get(33,132.5,WHEN)
        self.assertEqual(out['forecast']['before']['wind_speed_ms'],15)
        self.assertTrue(any(i['type']=='extreme_value' and i['field']=='wind_speed_ms' for i in out['quality']['issues']))

    def test_unknown_code(self):
        def bad(lat,lon):
            data=fixture(lat,lon)
            data['hourly']['weather_code'][9]=999
            return data
        out=ForecastCache(fetcher=bad,clock=lambda:NOW).get(33,132.5,WHEN)
        self.assertEqual(out['forecast']['before']['weather_code'],999)
        self.assertEqual(out['forecast']['before']['weather_label'],'不明')
        self.assertTrue(any(i['type']=='unknown_weather_code' for i in out['quality']['issues']))

    def test_stale_refresh_failure(self):
        clock=[NOW]
        ok=[True]
        def fetch(lat,lon):
            if not ok[0]: raise ConnectionError('offline')
            return fixture(lat,lon)
        cache=ForecastCache(fetcher=fetch,clock=lambda:clock[0])
        cache.get(33,132.5,WHEN)
        clock[0]+=timedelta(minutes=31)
        ok[0]=False
        out=cache.get(33,132.5,WHEN)
        self.assertEqual(out['quality']['freshness'],'stale')
        self.assertEqual(out['quality']['last_refresh']['status'],'failed')
        self.assertTrue(out['quality']['cache_hit'])

    def test_invalid_config(self):
        with self.assertRaises(ValueError): check_config({'wind_speed_ms':{'max':float('nan')}})

if __name__=='__main__': unittest.main()
