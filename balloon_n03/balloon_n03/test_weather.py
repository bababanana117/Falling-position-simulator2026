import unittest
from datetime import datetime,timedelta
from weather_service import JST,get_weather,api_url
from weather_cache import ForecastCache

NOW=datetime(2026,10,11,2,0,tzinfo=JST)
def fixture(lat,lon):
    times=[(NOW.replace(hour=0,minute=0)+timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(168)]
    return {'latitude':lat,'longitude':lon,'elevation':55,'hourly':{'time':times,'weather_code':[1]*168,'wind_speed_10m':[2.4]*168,'wind_direction_10m':[45]*168,'wind_gusts_10m':[None]*168,'precipitation':[0.0]*168,'temperature_2m':[22.3]*168}}
class TestN01(unittest.TestCase):
    def test_success_with_missing_gust(self):
        o=get_weather(33,132.5,'2026-10-11T09:30:00+09:00',fetcher=fixture,now=NOW)
        self.assertEqual(o['status'],'partial')
        self.assertEqual(o['forecast']['before']['valid_time'],'2026-10-11T09:00+09:00')
        self.assertEqual(o['forecast']['after']['valid_time'],'2026-10-11T10:00+09:00')
        self.assertEqual(o['forecast']['before']['precipitation_mm'],0)
        self.assertIsNone(o['forecast']['before']['wind_gust_ms'])
    def test_exact_hour_once(self):
        o=get_weather(33,132.5,'2026-10-11T09:00:00+09:00',fetcher=fixture,now=NOW)
        self.assertIsNone(o['forecast']['after'])
    def test_dates(self):
        self.assertEqual(get_weather(33,132.5,'2026-10-18T00:00:00+09:00',fetcher=fixture,now=NOW)['status'],'out_of_range')
    def test_invalid(self):
        self.assertEqual(get_weather(99,132.5,'2026-10-11T09:00:00+09:00',fetcher=fixture,now=NOW)['status'],'invalid_input')
        self.assertEqual(get_weather(33,132.5,'2026-10-11T09:00',fetcher=fixture,now=NOW)['status'],'invalid_input')
    def test_api_failure(self):
        def fail(*x):raise ConnectionError('offline')
        self.assertEqual(get_weather(33,132.5,'2026-10-11T09:00:00+09:00',fetcher=fail,now=NOW)['status'],'api_error')
    def test_cache_stale(self):
        clock=[NOW]
        state=[True]
        def fetch(*a):
            if not state[0]:raise ConnectionError('offline')
            return fixture(*a)
        c=ForecastCache(fetcher=fetch,clock=lambda:clock[0])
        a=c.get(33,132.5,'2026-10-11T09:00:00+09:00')
        self.assertEqual(a['cache_status'],'fresh')
        clock[0]+=timedelta(minutes=31)
        state[0]=False
        b=c.get(33,132.5,'2026-10-11T09:00:00+09:00')
        self.assertEqual(b['cache_status'],'stale')
        self.assertIn('refresh_error',b)
    def test_url(self):
        url=api_url(33,132.5)
        self.assertIn('forecast_days=7',url)
        self.assertIn('models=best_match',url)
if __name__=='__main__':unittest.main()
