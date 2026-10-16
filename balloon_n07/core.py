"""N07 persistence, formal input binding and spatial order. No flight engine."""
import contextlib
import copy
import hashlib
import importlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from geographiclib.geodesic import Geodesic
from n06_distance import N06Error, coordinate, parse_target, parse_json_bytes, normalize_result, evaluate_candidates

EXPECTED='fbb1cc76c112d8c495d2044604b330f1c0f5c8d6'
TERMINAL={'landed','stopped','invalid_input','failed'}
ACTIVE={'sending','submission_unknown','accepted','running'}
COMMON={'WEATHER_CHANGED','WEATHER_UNAVAILABLE','UNKNOWN_WEATHER_SOURCE','WEATHER_WINDOW_UNSUPPORTED',
        'SOURCE_CHANGED','SOURCE_UNAVAILABLE','EXECUTION_UNAVAILABLE','WORKER_PROCESS_BROKEN',
        'RESULT_INTEGRITY_ERROR','INSTANCE_MISMATCH','QUEUE_FULL','GFS_MISMATCH','ENGINE_MISMATCH'}

def now():return datetime.now(timezone.utc).isoformat()
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(v):return hashlib.sha256(canon(v).encode()).hexdigest()
def err(code,message):return {'code':code,'message':message}
class Problem(RuntimeError):
    def __init__(self,code,message):self.code=code;super().__init__(message)
def read_json(path):return parse_json_bytes(Path(path).read_bytes())

def safe_directory(path):
    p=Path(path).resolve()
    if any((a/'.git').exists() for a in [p,*p.parents]):raise Problem('STORE_IN_REPOSITORY','N07 state must be outside all Git repositories')
    if p.name in {'state','isolated-api-state'} and (p/'registry.sqlite3').exists():raise Problem('PRODUCTION_STORE','never use the Balloon API state directory')
    if (p/'registry.sqlite3').exists():raise Problem('PRODUCTION_STORE','existing API registry detected')
    return p

def formal_validator(root):
    root=Path(root).resolve()
    sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if sha!=EXPECTED:raise Problem('COMMIT_CHANGED','re-audit a different engine commit')
    sys.dont_write_bytecode=True;sys.path.insert(0,str(root))
    module=importlib.import_module('balloon_sim.flight.config')
    if Path(module.__file__).resolve()!=root/'balloon_sim/flight/config.py':raise Problem('WRONG_IMPORT','another engine config module is loaded')
    return module.validate_config

def source_identity(source):
    if not isinstance(source,dict):raise Problem('GFS_UNAVAILABLE','saved GFS source missing')
    if source.get('kind') not in ('fixture','acquired_gfs'):raise Problem('NOT_GFS','not a supported GFS source kind')
    if source.get('kind')=='fixture' and source.get('id') not in ('hokkaido-gfs-fixture','wakayama-gfs-fixture'):
        raise Problem('NOT_GFS','only existing named GFS fixtures accepted')
    if not isinstance(source.get('sha256'),str) or len(source['sha256'])!=64 or any(c not in '0123456789abcdef' for c in source['sha256']):
        raise Problem('GFS_IDENTITY_MISSING','SHA256 is required')
    for key in ('id','valid_times_utc','bounds','metadata'):
        if key not in source:raise Problem('GFS_IDENTITY_MISSING','missing '+key)
    # Freeze all source semantics; labels/default editor config are presentation.
    return copy.deepcopy({k:v for k,v in source.items() if k not in ('default_config','label')})

def spatial_order(rows):
    good=[r for r in rows if r['state']=='pending']
    if not good:return []
    def distance(a,b):return Geodesic.WGS84.Inverse(a['input']['latitude_deg'],a['input']['longitude_deg'],b['input']['latitude_deg'],b['input']['longitude_deg'])['s12']
    # Start with a global farthest pair. Ties use original input indices.
    if len(good)==1:return [good[0]['candidate_id']]
    pairs=[(a,b) for i,a in enumerate(good) for b in good[i+1:]]
    first,second=max(pairs,key=lambda pair:(distance(*pair),-pair[0]['input_index'],-pair[1]['input_index']))
    chosen=[first,second];left=[r for r in good if r not in chosen]
    while left:
        best=max(left,key=lambda r:(min(distance(r,s) for s in chosen),-r['input_index']))
        chosen.append(best);left.remove(best)
    return [r['candidate_id'] for r in chosen]

def fixed_payload(doc):return {k:doc[k] for k in ('api_base','instance_id','api_version','config','gfs','candidates_input','execution_order')}

def make_plan(candidates,config,target,source,health,base,validator):
    if not isinstance(candidates,dict) or set(candidates)!={'schema','altitude_reference','candidates'} or candidates['schema']!='n07.candidates/1' or candidates['altitude_reference']!='geometric_ASL_m':
        raise Problem('INVALID_CANDIDATES','use n07.candidates/1 and geometric_ASL_m')
    values=candidates['candidates']
    if not isinstance(values,list) or not 1<=len(values)<=50:raise Problem('CANDIDATE_LIMIT','requires 1..50 candidates')
    ids=[]
    for item in values:
        cid=item.get('candidate_id') if isinstance(item,dict) else None
        if not isinstance(cid,str) or not cid.strip() or len(cid)>128:raise Problem('CANDIDATE_ID','all IDs must be unambiguous nonempty strings <=128 chars')
        ids.append(cid)
    if len(ids)!=len(set(ids)):raise Problem('DUPLICATE_CANDIDATE_ID','duplicate IDs stop the entire plan')
    resolved=validator(copy.deepcopy(config));gfs=source_identity(source);target=parse_target(target)
    if health.get('workers')!=1 or not health.get('instance_id') or not health.get('flight_execution',{}).get('available'):
        raise Problem('API_UNAVAILABLE','requires healthy single-worker verification API')
    # Reject common time-window mismatch even for legacy fixture (do not extrapolate).
    try:
        stamps=gfs['valid_times_utc'];times=[datetime.fromisoformat(v.replace('Z','+00:00')) for v in stamps]
        start=datetime.fromisoformat(resolved['launch']['time_utc'])
        end=start+timedelta(seconds=resolved['integration']['max_duration_s'])
        if not times or start<min(times) or end>max(times):raise ValueError('full max_duration window not supported')
    except (KeyError,TypeError,ValueError) as e:raise Problem('WEATHER_WINDOW_UNSUPPORTED',str(e))
    rows=[]
    for i,item in enumerate(values):
        r={'candidate_id':item['candidate_id'],'input_index':i,'input':copy.deepcopy(item),'state':'pending',
           'config':None,'attempts':[],'result_ref':None,'normalized':None,'reused_from':None,'errors':[]}
        try:
            if set(item)!={'candidate_id','latitude_deg','longitude_deg','altitude_m'}:raise Problem('INVALID_CANDIDATE_FIELDS','exactly ID/latitude/longitude/altitude required')
            lat=coordinate(item['latitude_deg'],'latitude',-90,90);lon=coordinate(item['longitude_deg'],'longitude',-180,180)
            if abs(lat)==90:raise Problem('INVALID_COORDINATE','engine launch excludes poles')
            alt=item['altitude_m']
            if isinstance(alt,bool) or not isinstance(alt,(int,float)) or not math.isfinite(alt):raise Problem('ALTITUDE_UNKNOWN','finite numeric ASL altitude required')
            c=copy.deepcopy(resolved);c['launch'].update(latitude_deg=lat,longitude_deg=lon,altitude_m=alt)
            c=validator(c)
            bounds=gfs['bounds'];lo,hi=bounds['lat'];west,east=bounds['lon']
            if not lo<=lat<=hi or not any(west<=x<=east for x in (lon,lon-360,lon+360)):raise Problem('LAUNCH_OUTSIDE_GFS','launch outside saved horizontal bounds')
            r['config']=c
        except (ValueError,TypeError,KeyError,OverflowError,Problem) as e:
            r['state']='invalid_input';r['errors'].append(err(getattr(e,'code','INVALID_INPUT'),str(e)))
        rows.append(r)
    order=spatial_order(rows)
    for r in rows:r['execution_index']=order.index(r['candidate_id']) if r['candidate_id'] in order else None
    d={'schema':'n07.search/1','search_id':str(uuid.uuid4()),'created_utc':now(),'state':'created','pause_requested':False,
       'api_base':base,'instance_id':health['instance_id'],'api_version':health.get('version'),
       'config':resolved,'gfs':gfs,'candidates_input':copy.deepcopy(values),'execution_order':order,
       'rows':rows,'target':target,'evaluations':[],'history':[{'at':now(),'event':'created'}],
       'source_snapshot':None,'active_candidate':None,'errors':[]}
    d['fixed_sha256']=digest(fixed_payload(d));d['plan_integrity']=digest({'rows':[{k:r[k] for k in ('candidate_id','input_index','input','config','execution_index')} for r in rows]})
    return d

def check_integrity(doc):
    if doc.get('schema')!='n07.search/1':raise Problem('STATE_SCHEMA','unsupported saved search schema')
    if digest(fixed_payload(doc))!=doc['fixed_sha256']:raise Problem('FIXED_CONDITIONS_CORRUPT','fixed conditions/order modified')
    rows=[{k:r[k] for k in ('candidate_id','input_index','input','config','execution_index')} for r in doc['rows']]
    if digest({'rows':rows})!=doc['plan_integrity']:raise Problem('CANDIDATES_CORRUPT','candidate configs/order modified')

def evaluate(doc):
    normalized=[]
    for r in doc['rows']:
        if r['state'] in ('landed','stopped') and r['normalized']:
            row=copy.deepcopy(r['normalized']);row['input_index']=r['input_index'];row['execution_index']=r['execution_index']
            normalized.append(row)
    value=evaluate_candidates(normalized,doc['target'])
    value['evaluated_utc']=now();return value

class Store:
    def __init__(self,root):
        self.root=safe_directory(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'n07.sqlite3'
        existed=self.path.exists()
        with self.connect() as db:
            application_id=db.execute('PRAGMA application_id').fetchone()[0]
            if existed and application_id!=2160707:raise Problem('STORE_FORMAT','existing database is not an N07-owned store; do not modify it')
            if not existed:db.execute('PRAGMA application_id=2160707')
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, document TEXT NOT NULL, sha256 TEXT NOT NULL)')
    @contextlib.contextmanager
    def connect(self):
        """Finish the transaction before closing, including setup/body/commit errors.

        sqlite3.Connection.__exit__ commits or rolls back; it does NOT close.
        Keep the connection alive through that exit, then release file handles.
        """
        db=sqlite3.connect(self.path,timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()
    def create(self,doc):
        check_integrity(doc);s=canon(doc)
        with self.connect() as db:db.execute('INSERT INTO searches VALUES (?,?,?)',(doc['search_id'],s,hashlib.sha256(s.encode()).hexdigest()))
        return doc['search_id']
    def decode(self,row):
        if not row:raise Problem('SEARCH_NOT_FOUND','unknown search ID')
        if hashlib.sha256(row[0].encode()).hexdigest()!=row[1]:raise Problem('STATE_CORRUPT','saved document checksum mismatch')
        try:
            d=json.loads(row[0]);check_integrity(d);return d
        except (KeyError,TypeError,ValueError) as e:raise Problem('STATE_CORRUPT','invalid saved search structure: '+str(e)) from e
    def get(self,sid):
        with self.connect() as db:return self.decode(db.execute('SELECT document,sha256 FROM searches WHERE id=?',(sid,)).fetchone())
    def update(self,sid,mutate):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');d=self.decode(db.execute('SELECT document,sha256 FROM searches WHERE id=?',(sid,)).fetchone())
            mutate(d);check_integrity(d);s=canon(d)
            db.execute('UPDATE searches SET document=?,sha256=? WHERE id=?',(s,hashlib.sha256(s.encode()).hexdigest(),sid))
        return d
    def list(self):
        with self.connect() as db:return [self.decode(r) for r in db.execute('SELECT document,sha256 FROM searches ORDER BY id')]
    @contextlib.contextmanager
    def runner_lock(self):
        f=(self.root/'runner.lock').open('a+b')
        try:
            if os.name=='nt':
                import msvcrt
                if os.fstat(f.fileno()).st_size==0:f.write(b'0');f.flush()
                f.seek(0)
                try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                except OSError:raise Problem('RUNNER_BUSY','another manager owns this store')
            else:
                import fcntl
                try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except OSError:raise Problem('RUNNER_BUSY','another manager owns this store')
            yield
        finally:f.close()
    def save_result(self,sid,cid,attempt,envelope):
        raw=(canon(envelope)+'\n').encode();sha=hashlib.sha256(raw).hexdigest()
        folder=self.root/'results'/sid;folder.mkdir(parents=True,exist_ok=True)
        name=str(uuid.uuid4())+'.json';target=folder/name;temp=folder/(name+'.partial')
        with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,target)
        if os.name!='nt':
            fd=os.open(folder,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        return {'path':target.relative_to(self.root).as_posix(),'sha256':sha,'bytes':len(raw),'run_id':envelope['run_id'],
                'api_path':'/api/v1/runs/'+envelope['run_id']+'/result','attempt':attempt,'candidate_id':cid}
    def result(self,ref):
        p=(self.root/ref['path']).resolve()
        if self.root not in p.parents:raise Problem('RESULT_PATH','result reference leaves store')
        raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise Problem('RESULT_CORRUPT','full result SHA mismatch')
        return parse_json_bytes(raw)
