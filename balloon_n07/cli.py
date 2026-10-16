"""N07 CLI: standalone, isolated-loopback API only, independent state store."""
import argparse
import copy
import json
import signal
import sqlite3
import sys
import time
from core import Store,Problem,read_json,formal_validator,make_plan,evaluate,now
from api import Api,base_url
from manager import Manager

def summary(d):
    counts={state:sum(r['state']==state for r in d['rows']) for state in ['pending','sending','submission_unknown','accepted','running','landed','stopped','invalid_input','failed']}
    evaluation=evaluate(d);rank={r['candidate_id']:r for r in evaluation['ranked']}
    return {'search_id':d['search_id'],'state':d['state'],'total':len(d['rows']),'counts':counts,
            'processed':sum(counts[k] for k in ('landed','stopped','invalid_input','failed')),
            'best_calculated_only':evaluation['best_candidate'],'target':d['target'],'execution_order':d['execution_order'],
            'pause_requested':d['pause_requested'],'errors':d['errors'],
            'candidates':[{'candidate_id':r['candidate_id'],'input_index':r['input_index'],'execution_index':r['execution_index'],
                'state':r['state'],'launch':r['input'],'run_id':r['result_ref']['run_id'] if r['result_ref'] else (r['attempts'][-1]['run_id'] if r['attempts'] else None),
                'landing':({k:r['normalized'][k] for k in ('landing_latitude_deg','landing_longitude_deg')} if r['state']=='landed' else None),
                'distance_to_target_m':rank.get(r['candidate_id'],{}).get('distance_to_target_m'),'rank':rank.get(r['candidate_id'],{}).get('rank'),
                'reused_from':r['reused_from'],'errors':r['errors']} for r in d['rows']],
            'history':d['history'],'evaluated_utc':evaluation['evaluated_utc']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--store',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('create');c.add_argument('--api',default='http://127.0.0.1:8768');c.add_argument('--ack-isolated-api',action='store_true')
    for key in ('engine-root','common','candidates','target'):c.add_argument('--'+key,required=True)
    for name in ('run','resume'):
        c=sub.add_parser(name);c.add_argument('search_id');c.add_argument('--ack-isolated-api',action='store_true');c.add_argument('--wait-seconds',type=float,default=600)
    for name in ('pause','status','detail','verify'):
        c=sub.add_parser(name);c.add_argument('search_id')
    c=sub.add_parser('target');c.add_argument('search_id');c.add_argument('--file',required=True)
    c=sub.add_parser('retry');c.add_argument('search_id');c.add_argument('--candidate',action='append',required=True);c.add_argument('--ack-isolated-api',action='store_true')
    c=sub.add_parser('result');c.add_argument('search_id');c.add_argument('--candidate',required=True)
    sub.add_parser('list')
    a=p.parse_args()
    try:
        store=Store(a.store)
        if a.command=='create':
            if not a.ack_isolated_api:raise Problem('ISOLATED_ACK','confirm dedicated API port/data_dir')
            base=base_url(a.api);api=Api(base);health=api.health();api.instance=health['instance_id']
            common=read_json(a.common)
            if not isinstance(common,dict) or set(common)!={'schema','weather_source_id','config'} or common['schema']!='n07.common/1':raise Problem('COMMON_SCHEMA','use n07.common/1')
            source=next((s for s in api.sources()['sources'] if s['id']==common['weather_source_id']),None)
            validator=formal_validator(a.engine_root)
            doc=make_plan(read_json(a.candidates),common['config'],read_json(a.target),source,health,base,validator)
            print(store.create(doc));return 0
        if a.command=='list':print(json.dumps([summary(d) for d in store.list()],ensure_ascii=False,indent=2));return 0
        doc=store.get(a.search_id);api=Api(doc['api_base'],doc['instance_id']);manager=Manager(store,api)
        if a.command in ('run','resume'):
            if not a.ack_isolated_api:raise Problem('ISOLATED_ACK','confirm dedicated API')
            if not 1<=a.wait_seconds<=3600:raise Problem('WAIT_LIMIT','wait_seconds must be 1..3600 per case')
            interrupt=[False]
            def requested(signum,frame):interrupt[0]=True
            signal.signal(signal.SIGINT,requested)
            def controls():
                if interrupt[0]:manager.request_pause(a.search_id);interrupt[0]=False
            manager.control_poll=controls
            def sleep(seconds):
                controls()
                time.sleep(seconds)
            manager.sleep=sleep
            def notify(d):
                if interrupt[0]:manager.request_pause(a.search_id);interrupt[0]=False
                print(json.dumps(summary(d),ensure_ascii=False),flush=True)
            manager.run(a.search_id,a.wait_seconds,notify)
        elif a.command=='pause':manager.request_pause(a.search_id)
        elif a.command=='target':manager.target(a.search_id,read_json(a.file))
        elif a.command=='retry':
            if not a.ack_isolated_api:raise Problem('ISOLATED_ACK','confirm dedicated API')
            manager.retry(a.search_id,a.candidate)
        elif a.command=='result':
            row=next((r for r in doc['rows'] if r['candidate_id']==a.candidate),None)
            if not row or not row['result_ref']:raise Problem('NO_RESULT','no complete saved result reference')
            print(json.dumps(store.result(row['result_ref']),ensure_ascii=False,indent=2));return 0
        elif a.command=='detail':print(json.dumps(doc,ensure_ascii=False,indent=2));return 0
        elif a.command=='verify':
            checked=[]
            for row in doc['rows']:
                if row['result_ref']:
                    envelope=store.result(row['result_ref'])
                    if envelope['run_id']!=row['result_ref']['run_id']:raise Problem('RESULT_IDENTITY','local result run ID mismatch')
                    checked.append(row['candidate_id'])
            print(json.dumps({'search_id':a.search_id,'complete_result_hashes_verified':checked,'api_calls':0},ensure_ascii=False,indent=2));return 0
        final=store.get(a.search_id);print(json.dumps(summary(final),ensure_ascii=False,indent=2))
        return 2 if a.command in ('run','resume') and final['state']=='paused' else 0
    except (Problem,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as e:
        print(json.dumps({'error':{'code':getattr(e,'code','CLI_ERROR'),'message':str(e)}},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
