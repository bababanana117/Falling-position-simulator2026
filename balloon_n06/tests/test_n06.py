"""All coordinates/results here are synthetic TEST DATA, not flight outputs."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from geographiclib.geodesic import Geodesic
from n06_distance import (target_point,parse_target,distance_m,normalize_result,evaluate_candidates,
                          load_candidates,parse_json_bytes,N06Error)

# Shape-only test double, not an approved flight config or a calculated trajectory.
def flight(lat=43,lon=141.5,status='landed'):
    return {'schema':'balloon.flight.result/1','status':status,'complete':status=='landed',
            'config':{'launch':{'latitude_deg':43,'longitude_deg':141.5}},
            'records':[{'latitude_deg':12,'longitude_deg':34}],
            'summary':{'landing':{'latitude_deg':lat,'longitude_deg':lon} if status=='landed' else None},
            'stop_reason':None if status=='landed' else {'code':'TIME_OUT_OF_RANGE','message':'TEST ONLY'}}

def direct(result):
    return {'provenance':{'mock':True},'state':result['status'],'result':result,'case_config':result['config']}

def api(result):
    return {'run_id':'TEST-run','kind':'single_run','result':result,'weather_snapshot':{'mock':True},'source_snapshot':{}}

class DistanceTests(unittest.TestCase):
    def test_identical_zero(self):self.assertEqual(distance_m(43,141.5,target_point(43,141.5)),0)
    def test_equatorial_known_one_degree(self):
        # WGS84 a=6378137m, equatorial one-degree arc is 111319.49079327357m.
        self.assertAlmostEqual(distance_m(0,0,target_point(0,1)),111319.49079327357,places=6)
    def test_hokkaido_against_wgs84(self):
        expected=Geodesic.WGS84.Inverse(43.0,141.5,43.1,141.6)['s12']
        self.assertAlmostEqual(distance_m(43,141.5,target_point(43.1,141.6)),expected,places=9)
    def test_dateline_short_arc(self):
        self.assertAlmostEqual(distance_m(0,179.9,target_point(0,-179.9)),22263.898158653446,places=6)
    def test_poles_and_equivalent_longitudes(self):
        self.assertEqual(distance_m(90,180,target_point(90,-180)),0)
    def test_invalid_targets(self):
        for lat,lon in [(91,0),(-91,0),(0,181),(0,float('inf')),(float('nan'),0),('43',141),(True,141),(10**400,0)]:
            with self.subTest(lat=lat,lon=lon),self.assertRaises(N06Error):target_point(lat,lon)
    def test_target_schema(self):
        for t in [{},[],{'target_latitude_deg':43,'target_longitude_deg':141,'x':1},
                  {'schema':'other','target_latitude_deg':43,'target_longitude_deg':141}]:
            with self.assertRaises(N06Error):parse_target(t)
    def test_invalid_landing_distance(self):
        with self.assertRaises(N06Error):distance_m('43',141,target_point(43,141))

class ResultTests(unittest.TestCase):
    def test_direct_landed(self):
        r=normalize_result(direct(flight()),'test-c')
        self.assertTrue(r['evaluable']);self.assertIsNone(r['run_id']);self.assertEqual(r['source_format'],'n05_direct_record')
    def test_api_envelope(self):
        r=normalize_result(api(flight()),'test-c')
        self.assertEqual(r['run_id'],'TEST-run');self.assertTrue(r['evaluable']);self.assertIsNone(r['job_state'])
    def test_n05_api_record(self):
        v={'mode':'isolated_api_single','run':{'run_id':'TEST-run','state':'completed'},'envelope':api(flight())}
        r=normalize_result(v,'test-c');self.assertTrue(r['evaluable']);self.assertEqual(r['job_state'],'completed')
    def test_raw_result(self):self.assertTrue(normalize_result(flight(),'test-c')['evaluable'])
    def test_stopped_never_uses_last_record_or_wrapper_landing(self):
        v=direct(flight(status='stopped'));v['landing']={'latitude_deg':43,'longitude_deg':141.5};v['result']['summary']['landing']=v['landing']
        r=normalize_result(v,'test-c');out=evaluate_candidates([r],target_point(12,34))
        self.assertFalse(r['evaluable']);self.assertIsNone(r['landing_latitude_deg']);self.assertEqual(out['ranked'],[])
        self.assertIsNone(out['not_evaluated'][0]['distance_to_target_m']);self.assertEqual(r['error']['code'],'FLIGHT_STOPPED')
    def test_job_completed_without_result(self):
        r=normalize_result({'run_id':'r','state':'completed','result_available':True},'test-c')
        self.assertFalse(r['evaluable']);self.assertEqual(r['job_state'],'completed');self.assertIsNone(r['flight_status'])
    def test_failed_and_queued_jobs(self):
        for state in ['failed','queued','running','cancelled','interrupted']:
            r=normalize_result({'run_id':'r','state':state,'error':{'code':'TEST'}},'test-c')
            self.assertFalse(r['evaluable']);self.assertEqual(r['job_state'],state)
    def test_n05_error_without_result(self):
        r=normalize_result({'provenance':{},'state':'engine_exception','result':None,'error':{'code':'TEST'}},'test-c')
        self.assertEqual(r['error']['code'],'NO_SAVED_FLIGHT_RESULT')
    def test_missing_landing(self):
        f=flight();f['summary']['landing']=None
        self.assertEqual(normalize_result(f,'test-c')['error']['code'],'MISSING_LANDING')
    def test_invalid_landing(self):
        f=flight();f['summary']['landing']['longitude_deg']='141.5'
        r=normalize_result(f,'test-c');self.assertFalse(r['evaluable']);self.assertIsNone(r['landing_latitude_deg'])
    def test_missing_launch(self):
        f=flight();f['config']={}
        self.assertEqual(normalize_result(f,'test-c')['error']['code'],'MISSING_LAUNCH')
    def test_status_and_schema_conflicts(self):
        for mutate in [lambda f:f.update(complete=False),lambda f:f.update(stop_reason={'code':'TEST'}),lambda f:f.update(schema='other')]:
            f=flight();mutate(f);self.assertFalse(normalize_result(api(f),'test-c')['evaluable'])
        f=direct(flight());f['state']='stopped'
        self.assertEqual(normalize_result(f,'test-c')['error']['code'],'WRAPPER_STATUS_CONFLICT')
    def test_job_result_identity_and_state_conflicts(self):
        for job in [{'run_id':'other','state':'completed'},{'run_id':'TEST-run','state':'failed'}]:
            v={'mode':'isolated_api_single','run':job,'envelope':api(flight())}
            self.assertFalse(normalize_result(v,'test-c')['evaluable'])
    def test_unsupported_formats(self):
        for v in [None,[],{}, {'provenance':{},'state':[]}, {'run_id':'r','state':{}},
                  {'result':flight()}, {'schema':'n05.benchmark','batches':[]},
                  {'kind':'ensemble_trial','run_id':'r','result':flight()}]:
            r=normalize_result(v,'test-c');self.assertEqual(r['error']['code'],'UNSUPPORTED_FORMAT')
    def test_no_source_mutation(self):
        v=direct(flight());before=copy.deepcopy(v);r=normalize_result(v,'test-c')
        evaluate_candidates([r],target_point(43,141.5));self.assertEqual(v,before)
    def test_identifiers_preserved(self):
        r=normalize_result(api(flight()),'named-candidate',8,'TEST-PATH','TEST-SHA')
        self.assertEqual((r['candidate_id'],r['run_id'],r['input_index'],r['source_path'],r['source_sha256']),('named-candidate','TEST-run',8,'TEST-PATH','TEST-SHA'))

class RankingTests(unittest.TestCase):
    def test_distance_order_and_unranked(self):
        rows=[normalize_result(flight(0,2),'far',0),normalize_result(flight(0,0),'near',1),normalize_result(flight(status='stopped'),'stop',2)]
        r=evaluate_candidates(rows,target_point(0,0))
        self.assertEqual([x['candidate_id'] for x in r['ranked']],['near','far']);self.assertEqual(r['not_evaluated'][0]['candidate_id'],'stop')
        self.assertEqual(r['best_candidate']['candidate_id'],'near')
    def test_equal_distance_input_order(self):
        rows=[normalize_result(flight(0,1),'z',0),normalize_result(flight(0,1),'a',1)]
        r=evaluate_candidates(rows,target_point(0,0));self.assertEqual([x['candidate_id'] for x in r['ranked']],['z','a'])
    def test_target_changes_only_evaluation(self):
        rows=[normalize_result(flight(0,0),'A',0),normalize_result(flight(0,1),'B',1)];before=copy.deepcopy(rows)
        a=evaluate_candidates(rows,target_point(0,0));b=evaluate_candidates(rows,target_point(0,1))
        self.assertEqual(a['best_candidate']['candidate_id'],'A');self.assertEqual(b['best_candidate']['candidate_id'],'B');self.assertEqual(rows,before)
    def test_no_landed_results_retained(self):
        rows=[normalize_result(flight(status='stopped'),'S')]
        r=evaluate_candidates(rows,target_point(43,141));self.assertIsNone(r['best_candidate']);self.assertEqual(len(r['not_evaluated']),1)
    def test_no_engine_or_api_calls(self):
        # Any lazy import of a flight module or any HTTP socket would fail this test.
        import builtins
        original_import=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.startswith(('balloon_sim','backend','n05_adapter')):raise AssertionError('flight/backend import prohibited')
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=guarded),patch('socket.socket',side_effect=AssertionError('network prohibited')):
            r=normalize_result(flight(),'T');evaluate_candidates([r],target_point(43,141));evaluate_candidates([r],target_point(44,142))
        self.assertEqual(r['landing_latitude_deg'],43)
    def test_normalized_stopped_cannot_override_evaluable(self):
        row=normalize_result(flight(status='stopped'),'S');row.update(evaluable=True,landing_latitude_deg=43,landing_longitude_deg=141)
        r=evaluate_candidates([row],target_point(43,141));self.assertEqual(r['ranked'],[])
        self.assertIsNone(r['not_evaluated'][0]['distance_to_target_m'])

class FileCliTests(unittest.TestCase):
    def test_corrupt_json_rejected(self):
        for b in [b'{broken',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e999}',b'{"x":1,"x":2}',b'\xff']:
            with self.assertRaises(N06Error):parse_json_bytes(b)
    def test_manifest_relative_paths_and_missing_invalid_files(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'good.json').write_text(json.dumps(direct(flight())))
            (p/'bad.json').write_text('{broken')
            m={'schema':'n06.inputs/1','candidates':[{'candidate_id':'good','path':'good.json'},{'candidate_id':'bad','path':'bad.json'},{'candidate_id':'missing','path':'missing.json'}]}
            (p/'manifest.json').write_text(json.dumps(m));rows,_=load_candidates(p/'manifest.json')
            r=evaluate_candidates(rows,target_point(43,141.5));self.assertEqual(r['counts'],{'input':3,'ranked':1,'not_evaluated':2})
            self.assertIsNotNone(rows[1]['source_sha256'])
    def test_cli_and_input_hash_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);source=p/'input.json';source.write_text(json.dumps(direct(flight())))
            before=source.read_bytes();m=p/'manifest.json';m.write_text(json.dumps({'schema':'n06.inputs/1','candidates':[{'candidate_id':'T','path':str(source)}]}))
            cli=Path(__file__).resolve().parents[1]/'compare.py'
            cmd=[sys.executable,'-B',str(cli),'--manifest',str(m),'--target-latitude-deg','43','--target-longitude-deg','141.5','--out',str(p/'out.json')]
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
            out=json.loads((p/'out.json').read_text());self.assertEqual(out['ranked'][0]['distance_to_target_m'],0)
            self.assertEqual(source.read_bytes(),before);self.assertEqual(out['flight_computations'],0)
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,2)
    def test_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json';p.write_text(json.dumps({'schema':'n06.inputs/1','candidates':[]}))
            with self.assertRaises(N06Error):load_candidates(p)

if __name__=='__main__':unittest.main()
