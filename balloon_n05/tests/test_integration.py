"""Opt-in REAL GFS test. Skips when approved saved inputs are absent."""
import copy
import os
import unittest
from n05_adapter import EngineBinding, strict_json, file_hash

ROOT=os.environ.get('N05_ENGINE_ROOT');CONFIG=os.environ.get('N05_CONFIG');WEATHER=os.environ.get('N05_WEATHER')
@unittest.skipUnless(ROOT and CONFIG and WEATHER,'REAL GFS UNVERIFIED: N05_ENGINE_ROOT/CONFIG/WEATHER not supplied')
class RealGfsTests(unittest.TestCase):
    def test_adapter_matches_original_and_repeats(self):
        b=EngineBinding(ROOT);config=strict_json(CONFIG);before=copy.deepcopy(config)
        hashes=[file_hash(CONFIG),file_hash(WEATHER)];field,info=b.load_gfs(WEATHER)
        original=b.module.simulate(copy.deepcopy(config),field)
        adapted=b.run(config,field);again=b.run(config,field)
        self.assertEqual(adapted['result'],original);self.assertEqual(again['result'],original)
        self.assertIn(adapted['state'],['landed','stopped']);self.assertEqual(config,before)
        if original['status']=='stopped':self.assertIsNone(adapted['landing'])
        self.assertEqual(hashes,[file_hash(CONFIG),file_hash(WEATHER)]);b.assert_unchanged()
    def test_changed_site_matches_original(self):
        # A different REAL site must be supplied explicitly; never fabricate a weather field.
        lat=os.environ.get('N05_TEST_LAT');lon=os.environ.get('N05_TEST_LON')
        if not lat or not lon:self.skipTest('approved alternate coordinate not supplied')
        b=EngineBinding(ROOT);config=strict_json(CONFIG);field,_=b.load_gfs(WEATHER)
        changed=copy.deepcopy(config);changed['launch']['latitude_deg']=float(lat);changed['launch']['longitude_deg']=float(lon)
        original=b.module.simulate(changed,field);r=b.run(config,field,float(lat),float(lon))
        self.assertEqual(r['result'],original);b.assert_unchanged()

if __name__=='__main__':unittest.main()
