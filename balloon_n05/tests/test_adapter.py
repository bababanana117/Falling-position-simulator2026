"""Mock-only adapter tests; no synthetic weather field or real flight is created."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from n05_adapter import change_location, run_loaded, extract_landing, strict_json, write_new, N05Error
from api_probe import validate_base, request_body, Client, ApiFailure

# A mock test input, NOT an approved flight condition or a flight recommendation.
CONFIG = {'launch': {'latitude_deg': 35.0, 'longitude_deg': 139.0, 'altitude_m': 100,
                     'time_utc': '2026-10-13T00:00:00+00:00'},
          'ascent': {'mode': 'constant_speed', 'speed_m_s': 5},
          'burst': {'mode': 'altitude', 'altitude_m': 20000},
          'descent': {'mode': 'rated_speed', 'reference_speed_m_s': 5},
          'extra': {'list': [1, 2]}}
LANDING = {'latitude_deg': 35.1, 'longitude_deg': 139.1, 'altitude_m': 50,
           'time_utc': '2026-10-13T02:00:00+00:00'}

def landed():
    return {'status': 'landed', 'complete': True, 'records': [], 'summary': {'landing': copy.deepcopy(LANDING)}, 'stop_reason': None}

def stopped(code='TIME_OUT_OF_RANGE'):
    return {'status': 'stopped', 'complete': False,
            'records': [{'latitude_deg': 30, 'longitude_deg': 140}],
            'summary': {'landing': None}, 'stop_reason': {'code': code, 'message': 'MOCK ONLY'}}

class AdapterTests(unittest.TestCase):
    def test_coordinates_only(self):
        before = copy.deepcopy(CONFIG); after = change_location(CONFIG, 36, 140)
        expect = copy.deepcopy(before); expect['launch'].update(latitude_deg=36, longitude_deg=140)
        self.assertEqual(after, expect); self.assertEqual(CONFIG, before)
    def test_nested_copy(self):
        after = change_location(CONFIG); after['extra']['list'].append(3)
        self.assertEqual(CONFIG['extra']['list'], [1, 2])
    def test_invalid_coordinates(self):
        for lat, lon in [(90,139),(-90,139),(float('nan'),139),(35,181),(True,139),('35',139),(10**400,139)]:
            with self.subTest(lat=lat, lon=lon), self.assertRaises(N05Error): change_location(CONFIG,lat,lon)
    def test_missing_launch(self):
        with self.assertRaises(N05Error): change_location({})
    def test_engine_receives_unchanged_other_fields(self):
        sim = Mock(return_value=landed()); field = object(); validate = Mock()
        before = copy.deepcopy(CONFIG)
        r = run_loaded(CONFIG, field, latitude=36, simulator=sim, validator=validate)
        self.assertEqual(r['state'], 'landed'); self.assertIs(sim.call_args.args[1],field)
        self.assertEqual(sim.call_args.args[0],change_location(before,36)); self.assertEqual(CONFIG,before)
    def test_simulator_mutation_isolated(self):
        def mutate(c,w): c['extra']['list'].append(9); return landed()
        before=copy.deepcopy(CONFIG); run_loaded(CONFIG,object(),simulator=mutate,validator=lambda c:c)
        self.assertEqual(CONFIG,before)
    def test_mock_reproducibility(self):
        sim=lambda c,w:landed(); field=object()
        a=run_loaded(CONFIG,field,simulator=sim,validator=lambda c:c)
        b=run_loaded(CONFIG,field,simulator=sim,validator=lambda c:c)
        self.assertEqual(a['result'],b['result'])  # mocks only; not GFS proof
    def test_landed(self): self.assertEqual(extract_landing(landed()),LANDING)
    def test_stopped_has_no_landing(self):
        r=stopped();r['summary']['landing']=LANDING
        self.assertIsNone(extract_landing(r))
    def test_invalid_engine_result(self):
        for r in [{'status':'failed'}, {'status':'landed','complete':True,'summary':{}},
                  {'status':'landed','complete':False,'summary':{'landing':LANDING}}]:
            with self.assertRaises(N05Error): extract_landing(r)
    def test_validation_failure_no_compute(self):
        sim=Mock(); err=N05Error('INVALID_CONFIG','mock rejection')
        r=run_loaded(CONFIG,object(),simulator=sim,validator=Mock(side_effect=err))
        self.assertEqual(r['state'],'input_error');sim.assert_not_called()
    def test_support_stop_not_exception(self):
        r=run_loaded(CONFIG,object(),simulator=lambda c,w:stopped(),validator=lambda c:c)
        self.assertEqual(r['state'],'stopped');self.assertEqual(r['error']['code'],'TIME_OUT_OF_RANGE');self.assertIsNone(r['landing'])
    def test_engine_failure_distinct(self):
        r=run_loaded(CONFIG,object(),simulator=Mock(side_effect=RuntimeError('mock computation failure')),validator=lambda c:c)
        self.assertEqual(r['state'],'engine_exception');self.assertIsNone(r['landing'])
    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json'
            for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}']:
                p.write_text(text)
                with self.assertRaises(N05Error):strict_json(p)
    def test_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';write_new(p,{'x':1})
            with self.assertRaises(FileExistsError):write_new(p,{'x':2})
            self.assertEqual(strict_json(p),{'x':1})
    def test_api_payload_nonmutating(self):
        before=copy.deepcopy(CONFIG);b=request_body(CONFIG,'saved-source','fixed-id')
        self.assertEqual(b['client_request_id'],'fixed-id');b['config']['extra']['list'].append(9)
        self.assertEqual(CONFIG,before)
    def test_api_external_disabled(self):
        for url in ['https://example.com','http://example.com','http://user:pass@localhost','http://localhost/x','http://localhost?x=1']:
            with self.assertRaises(ValueError):validate_base(url)
        self.assertEqual(validate_base('http://127.0.0.1:8768/'),'http://127.0.0.1:8768')
    def test_api_waiting_and_result(self):
        c=Client('http://127.0.0.1:8768');c.call=Mock(side_effect=[{'instance_id':'test-instance'},
            {'run_id':'r','state':'queued'},{'run_id':'r','state':'completed','result_available':True},{'result':stopped()}])
        r=c.once(request_body(CONFIG,'s','id'))
        self.assertEqual(r['envelope']['result']['status'],'stopped');self.assertEqual(c.call.call_count,4)
    def test_api_post_failure_not_retried(self):
        c=Client('http://127.0.0.1:8768');c.call=Mock(side_effect=[{'instance_id':'i'},ApiFailure('communication_unknown')])
        with self.assertRaises(ApiFailure):c.once(request_body(CONFIG,'s','id'))
        self.assertEqual(c.call.call_count,2)
    def test_api_instance_changed(self):
        c=Client('http://localhost:8768','old');c.call=Mock(return_value={'instance_id':'new'})
        with self.assertRaises(ApiFailure):c.once(request_body(CONFIG,'s','id'))
        self.assertEqual(c.call.call_count,1)

if __name__=='__main__':unittest.main()
