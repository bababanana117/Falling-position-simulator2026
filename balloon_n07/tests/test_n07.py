"""MOCK API only. No real GFS/flight; coordinates/results are test doubles."""
import copy
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from core import Store,make_plan,Problem,source_identity,digest,spatial_order
from manager import Manager
from api import ApiError

CONFIG={'schema':'balloon.flight.config/1','launch':{'latitude_deg':43,'longitude_deg':141.5,'altitude_m':100,'time_utc':'2026-10-13T00:00:00+00:00'},
        'ascent':{'mode':'constant_speed','speed_m_s':5},'burst':{'mode':'altitude','altitude_m':20000},
        'descent':{'mode':'rated_speed','reference_speed_m_s':5},'integration':{'max_duration_s':14400}}
SOURCE={'id':'hokkaido-gfs-fixture','kind':'fixture','schema':'balloon.weather/1','sha256':'a'*64,'bytes':123,
        'run_utc':'2026-10-13T00:00:00+00:00','valid_times_utc':['2026-10-13T00:00:00+00:00','2026-10-14T00:00:00+00:00'],
        'bounds':{'lat':[-80,80],'lon':[-180,180]},'metadata':{'MOCK_ONLY':True}}
HEALTH={'workers':1,'instance_id':'MOCK-instance','version':'0.58.0','flight_execution':{'available':True}}
SNAPSHOT={'fingerprint':'MOCK-source','files':{'MOCK':True},'environment':{'MOCK':True}}
TARGET={'target_latitude_deg':43,'target_longitude_deg':141.5}

def candidates(n=3):
    return {'schema':'n07.candidates/1','altitude_reference':'geometric_ASL_m',
            'candidates':[{'candidate_id':f'C{i}','latitude_deg':43,'longitude_deg':141.5+i*.001,'altitude_m':100} for i in range(n)]}

def validator(c):return copy.deepcopy(c)  # MOCK flow tests, not a parallel physical validator

class FakeApi:
    def __init__(self):
        self.source=copy.deepcopy(SOURCE);self.health_value=copy.deepcopy(HEALTH);self.instance=None
        self.jobs={};self.posts=0;self.drop=False;self.fail_before=False;self.running=False;self.max_active=0
        self.stop_ids=set();self.failed_ids=set();self.common_ids=set();self.pause_callback=None;self.bad_result=False;self.engine_changed=False
    def health(self):return copy.deepcopy(self.health_value)
    def sources(self):return {'sources':[copy.deepcopy(self.source)]}
    def submit(self,body):
        self.posts+=1
        if self.fail_before:raise ApiError('CONNECTION_ERROR','MOCK disconnected before acceptance',ambiguous=True)
        active=sum(j['state'] in ('queued','running') for j in self.jobs.values())
        if active:raise AssertionError('more than one simultaneous MOCK job')
        rid='mock-run-'+str(self.posts);state='running' if self.running else 'completed'
        cid=body['candidate_id']
        error=None
        if cid in self.failed_ids:state='failed';error={'code':'MOCK_LOCAL_ERROR','message':'point failure test double'}
        if cid in self.common_ids:state='failed';error={'code':'EXECUTION_FAILED','message':'ambiguous common failure test double'}
        job={'run_id':rid,'state':state,'error':error,'result_available':state=='completed',
             'spec':{'submitted_input':copy.deepcopy(body),'config':copy.deepcopy(body['config']),
                     'weather_snapshot':source_identity(self.source),'source_snapshot':copy.deepcopy(SNAPSHOT)}}
        if self.engine_changed:job['spec']['source_snapshot']['fingerprint']='MOCK-changed'
        self.jobs[body['client_request_id']]=job;self.max_active=max(self.max_active,active+1)
        if self.drop:self.drop=False;raise ApiError('CONNECTION_ERROR','MOCK response dropped after accepted',ambiguous=True)
        return {'run_id':rid,'state':state}
    def lookup(self,key):
        if key not in self.jobs:raise ApiError('RUN_REQUEST_NOT_FOUND','MOCK 404',404)
        return copy.deepcopy(self.jobs[key])
    def job(self,rid):return copy.deepcopy(next(j for j in self.jobs.values() if j['run_id']==rid))
    def result(self,rid):
        j=self.job(rid);c=j['spec']['config'];cid=j['spec']['submitted_input']['candidate_id']
        stopped=cid in self.stop_ids
        f={'schema':'balloon.flight.result/1','status':'stopped' if stopped else 'landed','complete':not stopped,'config':copy.deepcopy(c),
           'records':[{'TEST_DOUBLE_ONLY':True,'latitude_deg':c['launch']['latitude_deg'],'longitude_deg':c['launch']['longitude_deg']}],
           'events':[], 'summary':{'landing':None if stopped else {'latitude_deg':c['launch']['latitude_deg'],'longitude_deg':c['launch']['longitude_deg']}},
           'stop_reason':{'code':'TIME_OUT_OF_RANGE','message':'MOCK_ONLY'} if stopped else None}
        if self.bad_result:f['summary']['landing']=None
        return {'run_id':rid,'kind':'single_run','weather_snapshot':j['spec']['weather_snapshot'],'source_snapshot':j['spec']['source_snapshot'],'result':f}

class N07Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'state');self.api=FakeApi()
    def tearDown(self):self.temp.cleanup()
    def plan(self,c=None):
        d=make_plan(c or candidates(),CONFIG,TARGET,SOURCE,HEALTH,'http://127.0.0.1:8768',validator)
        self.store.create(d);return d['search_id']
    def manager(self,**kwargs):return Manager(self.store,self.api,sleep=lambda s:None,**kwargs)
    def test_limits(self):
        for n in (1,50):self.assertEqual(len(self.store.get(self.plan(candidates(n)))['rows']),n)
        for n in (0,51):
            with self.assertRaises(Problem):self.plan(candidates(n))
    def test_bad_ids_stop_whole_plan(self):
        for cid in (None,'',42):
            c=candidates();c['candidates'][0]['candidate_id']=cid
            with self.assertRaises(Problem):self.plan(c)
        c=candidates();c['candidates'][1]['candidate_id']='C0'
        with self.assertRaises(Problem):self.plan(c)
    def test_local_invalid_continues(self):
        c=candidates();c['candidates'][1]['altitude_m']=None;sid=self.plan(c);self.manager().run(sid)
        d=self.store.get(sid);self.assertEqual([r['state'] for r in d['rows']],['landed','invalid_input','landed']);self.assertEqual(self.api.posts,2)
    def test_coordinate_altitude_validation(self):
        for key,value in [('latitude_deg',91),('longitude_deg','141'),('altitude_m',True),('latitude_deg',True),('altitude_m',float('inf'))]:
            # nonfinite values cannot be persisted, so reject those at canonical write.
            c=candidates();c['candidates'][0][key]=value
            if value==float('inf'):
                with self.assertRaises(ValueError):self.plan(c)
            else:
                sid=self.plan(c);self.assertEqual(self.store.get(sid)['rows'][0]['state'],'invalid_input')
    def test_common_invalid_no_search(self):
        with self.assertRaises(ValueError):make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',lambda c:(_ for _ in ()).throw(ValueError('MOCK common invalid')))
    def test_order_deterministic_and_dateline(self):
        c=candidates(4)
        for item,lon in zip(c['candidates'],[179.9,-179.9,0,90]):item['latitude_deg']=0;item['longitude_deg']=lon
        a=make_plan(c,CONFIG,TARGET,SOURCE,HEALTH,'x',validator);b=make_plan(c,CONFIG,TARGET,SOURCE,HEALTH,'x',validator)
        self.assertEqual(a['execution_order'],b['execution_order']);self.assertEqual(a['execution_order'][:2],['C0','C2'])
    def test_serial_50_lightweight_and_full_results(self):
        sid=self.plan(candidates(50));self.manager().run(sid);d=self.store.get(sid)
        self.assertEqual(d['state'],'completed');self.assertEqual(self.api.posts,50);self.assertEqual(self.api.max_active,1)
        self.assertEqual(len(d['evaluations'][-1]['ranked']),50)
        for r in d['rows']:self.assertEqual(self.store.result(r['result_ref'])['result']['records'][0]['TEST_DOUBLE_ONLY'],True)
    def test_stopped_no_distance(self):
        self.api.stop_ids={'C1'};sid=self.plan();self.manager().run(sid);d=self.store.get(sid)
        self.assertEqual(d['rows'][1]['state'],'stopped');self.assertEqual(len(d['evaluations'][-1]['ranked']),2)
    def test_point_failure_continues(self):
        self.api.failed_ids={'C0'};sid=self.plan();self.manager().run(sid)
        self.assertEqual(self.store.get(sid)['state'],'completed');self.assertEqual(self.api.posts,3)
    def test_common_failure_pauses(self):
        self.api.common_ids={'C0'};sid=self.plan();self.manager().run(sid)
        self.assertEqual(self.store.get(sid)['state'],'paused');self.assertEqual(self.api.posts,1)
    def test_target_no_post(self):
        sid=self.plan();m=self.manager();m.run(sid);posts=self.api.posts
        m.target(sid,{'target_latitude_deg':44,'target_longitude_deg':142})
        self.assertEqual(self.api.posts,posts);self.assertEqual(len(self.store.get(sid)['evaluations']),4)
    def test_completed_no_duplicate_on_resume(self):
        sid=self.plan();self.manager().run(sid);self.manager().run(sid);self.assertEqual(self.api.posts,3)
    def test_exact_reuse_keeps_ids(self):
        c=candidates();c['candidates'][1].update(latitude_deg=43,longitude_deg=141.5,altitude_m=100)
        sid=self.plan(c);self.manager().run(sid);d=self.store.get(sid)
        self.assertEqual(self.api.posts,2);self.assertIsNotNone(d['rows'][1]['reused_from']);self.assertEqual(len(d['evaluations'][-1]['ranked']),3)
    def test_altitude_and_nearby_not_reused(self):
        c=candidates();c['candidates'][1].update(longitude_deg=141.5,altitude_m=101)
        sid=self.plan(c);self.manager().run(sid);self.assertEqual(self.api.posts,3)
    def test_pause_after_case_then_resume(self):
        sid=self.plan();m=self.manager()
        m.run(sid,notify=lambda d:m.request_pause(sid));d=self.store.get(sid)
        self.assertEqual(d['state'],'paused');self.assertEqual(self.api.posts,1)
        Manager(Store(self.store.root),self.api,sleep=lambda s:None).run(sid)
        self.assertEqual(self.store.get(sid)['state'],'completed');self.assertEqual(self.api.posts,3)
    def test_response_drop_recover_no_post(self):
        self.api.drop=True;sid=self.plan();self.manager().run(sid)
        self.assertEqual(self.store.get(sid)['rows'][0]['state'],'submission_unknown');self.assertEqual(self.api.posts,1)
        self.manager().run(sid);self.assertEqual(self.api.posts,3);self.assertEqual(self.store.get(sid)['state'],'completed')
    def test_unaccepted_unknown_404_no_resend(self):
        self.api.fail_before=True;sid=self.plan();self.manager().run(sid);self.api.fail_before=False
        self.manager().run(sid);self.assertEqual(self.api.posts,1);self.assertEqual(self.store.get(sid)['state'],'paused')
    def test_crash_before_post_get_only(self):
        sid=self.plan()
        def crash(phase):
            if phase=='after_intent_commit':raise SystemExit('MOCK process crash')
        with self.assertRaises(SystemExit):self.manager(hook=crash).run(sid)
        self.manager().run(sid);self.assertEqual(self.api.posts,0);self.assertEqual(self.store.get(sid)['rows'][0]['state'],'submission_unknown')
    def test_crash_after_post_before_receipt(self):
        sid=self.plan()
        def crash(phase):
            if phase=='after_post_before_receipt':raise SystemExit('MOCK crash')
        with self.assertRaises(SystemExit):self.manager(hook=crash).run(sid)
        self.manager().run(sid);self.assertEqual(self.api.posts,3);self.assertEqual(self.store.get(sid)['state'],'completed')
    def test_crash_after_full_result_file(self):
        sid=self.plan()
        def crash(phase):
            if phase=='after_result_file':raise SystemExit('MOCK crash')
        with self.assertRaises(SystemExit):self.manager(hook=crash).run(sid)
        self.manager().run(sid);self.assertEqual(self.api.posts,3)
    def test_running_recovery(self):
        self.api.running=True;sid=self.plan()
        def sleep(s):
            for j in self.api.jobs.values():j['state']='completed';j['result_available']=True
        Manager(self.store,self.api,sleep=sleep).run(sid);self.assertEqual(self.api.posts,3)
    def test_api_restart_interrupted_no_auto_retry(self):
        self.api.drop=True;sid=self.plan();self.manager().run(sid)
        for j in self.api.jobs.values():j['state']='interrupted';j['error']={'code':'RESTART_INTERRUPTED','message':'MOCK API restart'}
        self.manager().run(sid);self.assertEqual(self.store.get(sid)['rows'][0]['state'],'failed');self.assertEqual(self.api.posts,3)
    def test_instance_replaced_stops(self):
        sid=self.plan();self.api.health_value['instance_id']='other';self.manager().run(sid);self.assertEqual(self.api.posts,0)
    def test_gfs_changed_stops(self):
        sid=self.plan();self.api.source['sha256']='b'*64;self.manager().run(sid);self.assertEqual(self.api.posts,0);self.assertEqual(self.store.get(sid)['state'],'paused')
    def test_result_source_changed_pauses(self):
        sid=self.plan();self.manager().run(sid,notify=lambda d:self.manager().request_pause(sid))
        self.api.engine_changed=True;self.manager().run(sid);self.assertEqual(self.store.get(sid)['state'],'paused')
    def test_corrupt_reuse_result_never_reused(self):
        c=candidates();c['candidates'][1].update(longitude_deg=141.5);sid=self.plan(c)
        self.manager().run(sid,notify=lambda d:self.manager().request_pause(sid));r=self.store.get(sid)['rows'][0]
        (self.store.root/r['result_ref']['path']).write_text('corrupt')
        self.manager().run(sid);self.assertEqual(self.store.get(sid)['state'],'paused')
    def test_sqlite_checksum_corruption(self):
        sid=self.plan()
        with self.store.connect() as db:db.execute("UPDATE searches SET document='{}' WHERE id=?",(sid,))
        with self.assertRaises(Problem):self.store.get(sid)
    def test_transaction_rollback(self):
        sid=self.plan();before=self.store.get(sid)
        def mutate(d):d['state']='broken';raise RuntimeError('MOCK crash during transaction')
        with self.assertRaises(RuntimeError):self.store.update(sid,mutate)
        self.assertEqual(self.store.get(sid),before)
    def test_frozen_condition_edit_rejected(self):
        sid=self.plan()
        with self.assertRaises(Problem):self.store.update(sid,lambda d:d['config']['launch'].update(time_utc='changed'))
    def test_explicit_retry_history_preserved(self):
        self.api.failed_ids={'C0'};sid=self.plan();m=self.manager();m.run(sid);self.api.failed_ids=set();m.retry(sid,['C0']);m.run(sid)
        r=self.store.get(sid)['rows'][0];self.assertEqual(len(r['attempts']),2);self.assertEqual(r['attempts'][0]['outcome'],'failed');self.assertEqual(r['state'],'landed')
    def test_stopped_invalid_unknown_not_retryable(self):
        self.api.stop_ids={'C0'};sid=self.plan();m=self.manager();m.run(sid)
        with self.assertRaises(Problem):m.retry(sid,['C0'])
    def test_searches_independent_new_conditions(self):
        a=self.plan();b=self.plan();self.manager().run(a)
        self.assertEqual(self.store.get(b)['state'],'created');self.assertEqual(self.store.get(a)['state'],'completed')
    def test_two_runners_lock(self):
        with self.store.runner_lock():
            with self.assertRaises(Problem):
                with Store(self.store.root).runner_lock():pass
    def test_other_unknown_blocks_new_search(self):
        a=self.plan();b=self.plan();self.api.fail_before=True;self.manager().run(a);self.api.fail_before=False
        with self.assertRaises(Problem):self.manager().run(b)
        self.assertEqual(self.api.posts,1)

if __name__=='__main__':unittest.main()
