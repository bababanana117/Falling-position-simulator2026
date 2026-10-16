"""Loopback HTTP and real child-process crash tests. All API payloads are MOCK."""
import copy
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from api import Api
from core import Store,make_plan,Problem,formal_validator
from manager import Manager
from test_n07 import FakeApi,candidates,CONFIG,SOURCE,HEALTH,TARGET,validator

class ProtocolTests(unittest.TestCase):
    def test_http_wire_contract_and_serial_manager(self):
        fake=FakeApi();seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,value,status=200):
                b=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            def do_GET(self):
                seen.append(('GET',self.path,self.headers.get('X-Balloon-Instance-Id')))
                if self.path=='/api/v1/health':self.respond(fake.health())
                elif self.path=='/api/v1/weather-sources':self.respond(fake.sources())
                elif self.path.endswith('/result'):self.respond(fake.result(self.path.split('/')[-2]))
                else:self.respond(fake.job(self.path.split('/')[-1]))
            def do_POST(self):
                self.assertions=(self.headers.get('Content-Type'),self.headers.get('X-Balloon-Instance-Id'))
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(('POST',body,self.assertions))
                self.respond(fake.submit(body),202)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with tempfile.TemporaryDirectory() as d:
                store=Store(d);plan=make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,base,validator);sid=store.create(plan)
                Manager(store,Api(base),sleep=lambda s:None).run(sid)
                self.assertEqual(store.get(sid)['state'],'completed')
                posts=[s for s in seen if s[0]=='POST'];self.assertEqual(len(posts),3)
                self.assertEqual(posts[0][2],('application/json','MOCK-instance'))
                self.assertEqual(set(posts[0][1]),{'client_request_id','candidate_id','candidate_revision','label','weather_source_id','config'})
        finally:server.shutdown();server.server_close();thread.join()
    def test_real_child_process_crash_after_intent(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'http://127.0.0.1:8768',validator))
            src="from core import Store; from manager import Manager; import os; from test_n07 import FakeApi; s=Store(os.environ['N07_TEST_STORE']); m=Manager(s,FakeApi(),hook=lambda phase:os._exit(17) if phase=='after_intent_commit' else None); m.run(os.environ['N07_TEST_ID'])"
            env=os.environ.copy();env['N07_TEST_STORE']=d;env['N07_TEST_ID']=sid
            env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]),env.get('PYTHONPATH','')])
            r=subprocess.run([sys.executable,'-B','-c',src],env=env,capture_output=True,text=True)
            self.assertEqual(r.returncode,17,r.stderr)
            self.assertEqual(Store(d).get(sid)['rows'][0]['state'],'sending')
            fake=FakeApi();Manager(Store(d),fake,sleep=lambda s:None).run(sid)
            self.assertEqual(fake.posts,0);self.assertEqual(Store(d).get(sid)['rows'][0]['state'],'submission_unknown')
    def test_result_atomic_rename_failure_keeps_job(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi()
            with patch('core.os.replace',side_effect=OSError('MOCK rename failure')):Manager(store,fake,sleep=lambda s:None).run(sid)
            self.assertEqual(store.get(sid)['state'],'paused');self.assertEqual(fake.posts,1)
            Manager(store,fake,sleep=lambda s:None).run(sid);self.assertEqual(fake.posts,3)
    def test_n06_distances_and_stable_order(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);c=candidates();c['candidates'][1].update(longitude_deg=141.5)
            sid=store.create(make_plan(c,CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi()
            Manager(store,fake,sleep=lambda s:None).run(sid)
            ranked=store.get(sid)['evaluations'][-1]['ranked']
            self.assertEqual(ranked[0]['distance_to_target_m'],0);self.assertEqual([r['candidate_id'] for r in ranked[:2]],['C0','C1'])
    @unittest.skipUnless(os.environ.get('N07_VALIDATOR_ROOT'),'original config validator path not supplied')
    def test_original_validator_only_no_simulate(self):
        validate=formal_validator(os.environ['N07_VALIDATOR_ROOT'])
        before=copy.deepcopy(CONFIG);plan=make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validate)
        self.assertEqual(CONFIG,before);self.assertEqual(len(plan['rows']),3)
        self.assertEqual(plan['config']['ascent']['mode'],'constant_speed')

if __name__=='__main__':unittest.main()

class AdditionalBoundaries(unittest.TestCase):
    def test_context_connection_failure_never_submits(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi()
            fake.health=lambda:(_ for _ in ()).throw(Exception('not used'))
            from api import ApiError
            fake.health=lambda:(_ for _ in ()).throw(ApiError('CONNECTION_ERROR','MOCK offline'))
            Manager(store,fake).run(sid);self.assertEqual(fake.posts,0);self.assertEqual(store.get(sid)['state'],'paused')
    def test_only_launch_position_and_altitude_vary(self):
        before=copy.deepcopy(CONFIG);c=candidates();c['candidates'][1]['altitude_m']=101
        plan=make_plan(c,CONFIG,TARGET,SOURCE,HEALTH,'x',validator)
        for r in plan['rows']:
            a=copy.deepcopy(r['config']);b=copy.deepcopy(plan['config'])
            for x in (a,b):
                for k in ('latitude_deg','longitude_deg','altitude_m'):x['launch'].pop(k)
            self.assertEqual(a,b)
        self.assertEqual(CONFIG,before)
    def test_missing_gfs_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi();fake.sources=lambda:{'sources':[]}
            Manager(store,fake).run(sid);self.assertEqual(fake.posts,0);self.assertEqual(store.get(sid)['state'],'paused')
    def test_invalid_target_rejects_plan(self):
        with self.assertRaises(ValueError):make_plan(candidates(),CONFIG,{'target_latitude_deg':'43','target_longitude_deg':141},SOURCE,HEALTH,'x',validator)
    def test_completed_inspection_without_api(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi();manager=Manager(store,fake,sleep=lambda s:None);manager.run(sid)
            fake.health=lambda:(_ for _ in ()).throw(AssertionError('must not contact API for completed run'))
            manager.run(sid);manager.target(sid,{'target_latitude_deg':44,'target_longitude_deg':142})
            self.assertEqual(store.get(sid)['state'],'completed')

class PauseBoundaries(unittest.TestCase):
    def test_pause_before_next_post(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi()
            manager=Manager(store,fake)
            manager.control_poll=lambda:manager.request_pause(sid)
            manager.run(sid);self.assertEqual(fake.posts,0);self.assertEqual(store.get(sid)['state'],'paused')
    def test_wait_timeout_recovers_original_run(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));fake=FakeApi();fake.running=True
            manager=Manager(store,fake,sleep=lambda s:None);manager.run(sid,wait_seconds=0)
            self.assertEqual(fake.posts,1);self.assertEqual(store.get(sid)['state'],'paused')
            for j in fake.jobs.values():j['state']='completed'
            fake.running=False;manager.run(sid);self.assertEqual(fake.posts,3)

class NetworkCrashBoundaries(unittest.TestCase):
    def test_real_http_acceptance_response_disconnect(self):
        import urllib.parse
        fake=FakeApi();drop=[True]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def emit(self,value,status=200):
                b=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            def do_GET(self):
                if self.path=='/api/v1/health':self.emit(fake.health())
                elif self.path=='/api/v1/weather-sources':self.emit(fake.sources())
                elif self.path.startswith('/api/v1/run-requests?'):
                    rid=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)['client_request_id'][0]
                    try:self.emit(fake.lookup(rid))
                    except ApiError:self.emit({'error':{'code':'RUN_REQUEST_NOT_FOUND','message':'MOCK only'}},404)
                elif self.path.endswith('/result'):self.emit(fake.result(self.path.split('/')[-2]))
                else:self.emit(fake.job(self.path.split('/')[-1]))
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));reply=fake.submit(body)
                if drop[0]:drop[0]=False;self.close_connection=True;self.connection.close();return
                self.emit(reply,202)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with tempfile.TemporaryDirectory() as d:
                store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,base,validator))
                Manager(store,Api(base),sleep=lambda s:None).run(sid)
                self.assertEqual(fake.posts,1);self.assertEqual(store.get(sid)['rows'][0]['state'],'submission_unknown')
                Manager(Store(d),Api(base),sleep=lambda s:None).run(sid)
                self.assertEqual(fake.posts,3);self.assertEqual(store.get(sid)['state'],'completed')
        finally:server.shutdown();server.server_close();thread.join()
    def test_real_sqlite_uncommitted_crash_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'x',validator));before=store.get(sid)
            script="import sqlite3,os; db=sqlite3.connect(os.environ['N07_TEST_DB']); db.execute('BEGIN IMMEDIATE'); db.execute(\"UPDATE searches SET document='{}' WHERE id=?\",(os.environ['N07_TEST_ID'],)); os._exit(19)"
            env=os.environ.copy();env['N07_TEST_DB']=str(store.path);env['N07_TEST_ID']=sid
            r=subprocess.run([sys.executable,'-B','-c',script],env=env,capture_output=True,text=True)
            self.assertEqual(r.returncode,19);self.assertEqual(Store(d).get(sid),before)

class StoreOwnership(unittest.TestCase):
    def test_unrelated_database_not_modified(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'n07.sqlite3'
            with contextlib.closing(sqlite3.connect(p)) as db, db:
                db.execute('CREATE TABLE unrelated (x TEXT)');db.execute("INSERT INTO unrelated VALUES ('keep')")
            with self.assertRaises(Problem):Store(d)
            with contextlib.closing(sqlite3.connect(p)) as db, db:
                self.assertEqual(db.execute('SELECT x FROM unrelated').fetchone()[0],'keep')
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='searches'").fetchone()[0],0)
