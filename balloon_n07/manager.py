"""Durable finite serial coordinator. Does not import or implement simulate."""
import copy
import time
import uuid
from core import (Store,Problem,TERMINAL,ACTIVE,COMMON,now,digest,err,check_integrity,
                  source_identity,evaluate)
from api import ApiError
from n06_distance import normalize_result

class Manager:
    def __init__(self,store,api,sleep=time.sleep,hook=None,control_poll=None):
        self.store,self.api,self.sleep=store,api,sleep;self.hook=hook or (lambda phase:None)
        self.control_poll=control_poll or (lambda:None)
    def event(self,sid,event,**extra):
        self.store.update(sid,lambda d:d['history'].append({'at':now(),'event':event,**extra}))
    def pause(self,sid,code,message):
        def edit(d):
            d['state']='paused';d['errors'].append({'at':now(),**err(code,message)});d['history'].append({'at':now(),'event':'paused','code':code})
        self.store.update(sid,edit)
    def check_context(self,d):
        check_integrity(d);self.api.instance=d['instance_id']
        health=self.api.health()
        if health.get('instance_id')!=d['instance_id']:raise Problem('INSTANCE_MISMATCH','original API registry is unavailable')
        if health.get('version')!=d['api_version']:raise Problem('API_VERSION_CHANGED','API version differs')
        if not health.get('flight_execution',{}).get('available'):raise Problem('API_UNAVAILABLE','flight worker unavailable')
        current=next((s for s in self.api.sources().get('sources',[]) if s.get('id')==d['gfs']['id']),None)
        if current is None:raise Problem('GFS_UNAVAILABLE','fixed saved source missing')
        if source_identity(current)!=d['gfs']:raise Problem('GFS_MISMATCH','fixed GFS snapshot differs; create a new search')
    def current(self,sid,cid):return next(r for r in self.store.get(sid)['rows'] if r['candidate_id']==cid)
    def change_row(self,sid,cid,fn):
        def edit(d):fn(next(r for r in d['rows'] if r['candidate_id']==cid),d)
        return self.store.update(sid,edit)
    def failed(self,sid,cid,code,message):
        def edit(r,d):
            r['state']='failed';r['errors'].append({'at':now(),**err(code,message)})
            if r['attempts']:r['attempts'][-1]['outcome']='failed';r['attempts'][-1]['finished_utc']=now()
            d['active_candidate']=None
        self.change_row(sid,cid,edit)
    def prepare(self,sid,cid):
        def edit(r,d):
            request_id=str(uuid.uuid4())
            body={'client_request_id':request_id,'candidate_id':r['candidate_id'],'candidate_revision':0,
                  'label':'N07 '+sid+' / '+r['candidate_id'], 'weather_source_id':d['gfs']['id'],'config':copy.deepcopy(r['config'])}
            # Persist request and mapping BEFORE network side effect.
            r['attempts'].append({'ordinal':len(r['attempts'])+1,'created_utc':now(),'request_id':request_id,
                                  'request':body,'request_sha256':digest(body),'run_id':None,'outcome':'sending'})
            r['state']='sending';d['active_candidate']=cid
        self.change_row(sid,cid,edit);self.hook('after_intent_commit')
    def verify_job(self,sid,cid,job):
        r=self.current(sid,cid);a=r['attempts'][-1];d=self.store.get(sid)
        if not isinstance(job,dict) or not isinstance(job.get('run_id'),str) or not job['run_id']:raise Problem('INVALID_JOB','API job lacks run_id')
        if a['run_id'] and job['run_id']!=a['run_id']:raise Problem('RUN_ID_MISMATCH','different accepted run')
        spec=job.get('spec')
        if not isinstance(spec,dict) or spec.get('submitted_input')!=a['request']:raise Problem('REQUEST_MISMATCH','accepted request body differs')
        if source_identity(spec.get('weather_snapshot'))!=d['gfs']:raise Problem('GFS_MISMATCH','accepted run used a different weather snapshot')
        snapshot=spec.get('source_snapshot')
        if not isinstance(snapshot,dict) or not snapshot.get('fingerprint'):raise Problem('ENGINE_IDENTITY_MISSING','run lacks source snapshot')
        if d['source_snapshot'] is not None and snapshot!=d['source_snapshot']:raise Problem('ENGINE_MISMATCH','accepted run source/numerical environment differs')
        def edit(r,d):
            if d['source_snapshot'] is None:d['source_snapshot']=copy.deepcopy(snapshot)
            r['attempts'][-1]['run_id']=job['run_id'];r['attempts'][-1]['job_state']=job['state']
            r['attempts'][-1]['job_started_utc']=job.get('started_at')
            r['attempts'][-1]['job_finished_utc']=job.get('finished_at')
            r['state']='running' if job['state']=='running' else 'accepted'
        self.change_row(sid,cid,edit)
    def recover_job(self,sid,cid):
        r=self.current(sid,cid);a=r['attempts'][-1]
        if digest(a['request'])!=a['request_sha256']:raise Problem('REQUEST_CORRUPT','request checksum differs')
        if a['run_id']:
            return self.api.job(a['run_id'])
        # Unknown/sending after crash always GET, never POST again.
        try:return self.api.lookup(a['request_id'])
        except ApiError as e:
            if e.status==404:
                self.change_row(sid,cid,lambda r,d:r.update(state='submission_unknown'))
                raise Problem('SUBMISSION_UNKNOWN','request not found at this check; no automatic resubmission')
            raise
    def complete(self,sid,cid,job):
        d=self.store.get(sid);r=self.current(sid,cid);rid=r['attempts'][-1]['run_id']
        envelope=self.api.result(rid)
        if envelope.get('run_id')!=rid or envelope.get('kind')!='single_run':raise Problem('RESULT_IDENTITY','result does not match single run')
        if source_identity(envelope.get('weather_snapshot'))!=d['gfs'] or envelope.get('source_snapshot')!=d['source_snapshot']:
            raise Problem('RESULT_IDENTITY','result weather/source snapshot differs')
        result=envelope.get('result')
        if not isinstance(result,dict) or result.get('config')!=r['config']:raise Problem('RESULT_CONFIG_MISMATCH','scientific config differs from frozen candidate')
        normalized=normalize_result(envelope,cid,r['input_index'])
        if (normalized['flight_status'] not in ('landed','stopped')
            or (normalized['flight_status']=='landed' and not normalized['evaluable'])
            or (normalized['flight_status']=='stopped' and (normalized.get('error') or {}).get('code')!='FLIGHT_STOPPED')):
            raise Problem('INVALID_RESULT','scientific result cannot be normalized')
        ref=self.store.save_result(sid,cid,len(r['attempts']),envelope);self.hook('after_result_file')
        def edit(r,d):
            r['state']=normalized['flight_status'];r['result_ref']=ref;r['normalized']=normalized
            r['attempts'][-1].update(outcome=r['state'],finished_utc=now(),result_ref=ref)
            if r['state']=='stopped':r['errors'].append({'at':now(),**(normalized['error'] or {})})
            d['active_candidate']=None
            d['history'].append({'at':now(),'event':'case_completed','candidate_id':cid,'run_id':rid,'state':r['state']})
            d['evaluations'].append(evaluate(d))
        self.change_row(sid,cid,edit)
    def reuse(self,sid,cid):
        d=self.store.get(sid);r=self.current(sid,cid)
        if d['source_snapshot'] is None:return False
        key=digest({'config':r['config'],'gfs':d['gfs'],'source_snapshot':d['source_snapshot']})
        for old in d['rows']:
            if old['candidate_id']==cid or old['state'] not in ('landed','stopped') or not old['result_ref']:continue
            old_key=digest({'config':old['config'],'gfs':d['gfs'],'source_snapshot':d['source_snapshot']})
            if old_key!=key:continue
            # A corrupt reference never becomes a donor; pause for inspection.
            envelope=self.store.result(old['result_ref'])
            if envelope.get('source_snapshot')!=d['source_snapshot'] or source_identity(envelope.get('weather_snapshot'))!=d['gfs']:
                raise Problem('REUSE_IDENTITY','donor result snapshot mismatch')
            normalized=normalize_result(envelope,cid,r['input_index'])
            def edit(r,d):
                r.update(state=old['state'],result_ref=copy.deepcopy(old['result_ref']),normalized=normalized,
                         reused_from={'candidate_id':old['candidate_id'],'run_id':envelope['run_id'],'calculation_key':key})
                d['history'].append({'at':now(),'event':'exact_reuse','candidate_id':cid,'from':old['candidate_id']})
                d['evaluations'].append(evaluate(d))
            self.change_row(sid,cid,edit);return True
        return False
    def drive_case(self,sid,cid,deadline):
        r=self.current(sid,cid)
        if r['state']=='pending':
            self.control_poll()
            if self.store.get(sid)['pause_requested']:raise Problem('USER_PAUSE','paused before next request')
            if self.reuse(sid,cid):return True
            self.prepare(sid,cid);r=self.current(sid,cid)
            try:
                response=self.api.submit(r['attempts'][-1]['request']);self.hook('after_post_before_receipt')
                if not isinstance(response,dict) or not isinstance(response.get('run_id'),str) or not response['run_id']:raise ApiError('INVALID_ACCEPTANCE','missing run ID',ambiguous=True)
                def accepted(r,d):
                    r['attempts'][-1]['run_id']=response['run_id'];r['state']='accepted';r['attempts'][-1]['outcome']='accepted'
                    r['attempts'][-1]['response_received_utc']=now()
                self.change_row(sid,cid,accepted)
            except ApiError as e:
                if e.ambiguous or e.status is None or (e.status and e.status>=500):
                    self.change_row(sid,cid,lambda r,d:r.update(state='submission_unknown'))
                    raise Problem('SUBMISSION_UNKNOWN','POST response uncertain: '+str(e))
                if e.code in COMMON or e.status in (429,409):
                    # Known pre-accept rejection: do not auto retry. Explicit retry can create a new attempt after inspection.
                    self.failed(sid,cid,e.code,str(e));raise
                self.failed(sid,cid,e.code,str(e));return True
        while True:
            if time.monotonic()>=deadline:raise Problem('WAIT_TIMEOUT','finite client wait expired; existing run is retained')
            job=self.recover_job(sid,cid);self.verify_job(sid,cid,job)
            state=job.get('state')
            if state=='completed':self.complete(sid,cid,job);return True
            if state in ('failed','interrupted','cancelled'):
                error=job.get('error') or {};code=error.get('code',state.upper())
                self.failed(sid,cid,code,error.get('message',state))
                if code in COMMON or code=='EXECUTION_FAILED':raise Problem(code,'API failure does not reliably distinguish common/point cause; inspect before resume')
                return True
            if state not in ('queued','running'):raise Problem('UNKNOWN_JOB_STATE',str(state))
            self.sleep(0.25)
    def run(self,sid,wait_seconds=600,notify=None):
        with self.store.runner_lock():
            d=self.store.get(sid)
            if d['state']=='completed' and all(r['state'] in TERMINAL for r in d['rows']):return
            # Never send new work while another search has an unresolved accepted/unknown case.
            for other in self.store.list():
                if other['search_id']!=sid and any(r['state'] in ACTIVE for r in other['rows']):
                    raise Problem('OTHER_SEARCH_ACTIVE','resolve the other search before sending new work')
            try:
                self.check_context(d)
                self.store.update(sid,lambda d:d.update(state='running',pause_requested=False))
                self.event(sid,'resumed')
                while True:
                    self.control_poll()
                    d=self.store.get(sid);check_integrity(d)
                    if d['pause_requested']:
                        self.pause(sid,'USER_PAUSE','paused after current case finished');return
                    active=[r for r in d['rows'] if r['state'] in ACTIVE]
                    if len(active)>1:raise Problem('MULTIPLE_ACTIVE','state has multiple active requests')
                    pending=[r for cid in d['execution_order'] for r in d['rows'] if r['candidate_id']==cid and r['state']=='pending']
                    if not active and not pending:
                        self.store.update(sid,lambda d:d.update(state='completed',active_candidate=None));self.event(sid,'completed');return
                    r=(active or pending)[0]
                    self.check_context(d)
                    self.drive_case(sid,r['candidate_id'],time.monotonic()+wait_seconds)
                    if notify:notify(self.store.get(sid))
            except (Problem,OSError,ValueError,KeyError,TypeError) as e:
                self.pause(sid,getattr(e,'code','MANAGER_ERROR'),str(e))
    def request_pause(self,sid):
        def edit(d):d['pause_requested']=True;d['history'].append({'at':now(),'event':'pause_requested'})
        self.store.update(sid,edit)
    def target(self,sid,target):
        from n06_distance import parse_target
        target=parse_target(target)
        def edit(d):
            d['target']=target;d['history'].append({'at':now(),'event':'target_changed','target':copy.deepcopy(target)})
            d['evaluations'].append(evaluate(d))
        self.store.update(sid,edit)
    def retry(self,sid,cids):
        with self.store.runner_lock():
            d=self.store.get(sid)
            if any(r['state'] in ACTIVE for r in d['rows']):raise Problem('ACTIVE_REQUEST','first resolve accepted or unknown requests')
            if not cids or len(cids)!=len(set(cids)):raise Problem('RETRY_SELECTION','select distinct failed IDs')
            rows={r['candidate_id']:r for r in d['rows']}
            if any(cid not in rows or rows[cid]['state']!='failed' for cid in cids):raise Problem('RETRY_SELECTION','only failed, not stopped/invalid/unknown, may retry')
            self.check_context(d)
            def edit(d):
                for r in d['rows']:
                    if r['candidate_id'] in cids:r['state']='pending'
                d['state']='paused';d['history'].append({'at':now(),'event':'explicit_retry_selected','candidates':cids})
            self.store.update(sid,edit)
