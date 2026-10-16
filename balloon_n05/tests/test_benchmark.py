"""Mock flow/count tests only. Their timings are NOT flight measurements."""
import copy
import unittest
from unittest.mock import Mock
from benchmark import benchmark

class BenchmarkTests(unittest.TestCase):
    def binding(self):
        b=Mock()
        b.load_gfs.return_value=(object(),{'sha256':'MOCK-HASH','load_seconds':0.0})
        b.run.return_value={'state':'stopped','simulate_seconds':0.0,'result':None,'landing':None,'error':{'code':'MOCK_ONLY'}}
        return b
    def test_shared_one_load_ten_runs(self):
        b=self.binding();c={'MOCK_ONLY':[1]};before=copy.deepcopy(c)
        sites=[{'latitude_deg':35,'longitude_deg':139} for _ in range(10)]
        r=benchmark(b,c,'NOT-A-FILE',sites,10)
        self.assertEqual(b.load_gfs.call_count,1);self.assertEqual(b.run.call_count,10)
        self.assertEqual(r['states'],{'stopped':10});self.assertEqual(c,before)
    def test_reload_ten_loads_not_eleven(self):
        b=self.binding();sites=[{'latitude_deg':35,'longitude_deg':139} for _ in range(10)]
        r=benchmark(b,{'MOCK_ONLY':True},'NOT-A-FILE',sites,10,True)
        self.assertEqual(b.load_gfs.call_count,10);self.assertEqual(r['weather_load_count'],10)
    def test_not_enough_sites_no_loading(self):
        b=self.binding()
        with self.assertRaises(ValueError):benchmark(b,{},'NOT-A-FILE',[],10)
        b.load_gfs.assert_not_called()
    def test_changed_weather_between_loads_fails(self):
        b=self.binding();b.load_gfs.side_effect=[(object(),{'sha256':'first','load_seconds':0}), (object(),{'sha256':'changed','load_seconds':0})]
        with self.assertRaises(ValueError):benchmark(b,{},'NOT-A-FILE',[{'latitude_deg':35,'longitude_deg':139}]*10,10,True)

if __name__=='__main__':unittest.main()
