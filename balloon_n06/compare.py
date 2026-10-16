"""N06 offline comparison CLI. No network and no flight calculation."""
import argparse
import json
import sys
from pathlib import Path
from n06_distance import load_json, parse_target, target_point, load_candidates, evaluate_candidates, N06Error

def main():
    p=argparse.ArgumentParser(description='Compare saved landings with a target using WGS84; never simulate')
    p.add_argument('--manifest',required=True)
    p.add_argument('--target');p.add_argument('--target-latitude-deg',type=float);p.add_argument('--target-longitude-deg',type=float)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    try:
        if a.target:
            if a.target_latitude_deg is not None or a.target_longitude_deg is not None:
                raise N06Error('INVALID_TARGET','choose target JSON OR both CLI coordinates')
            target=parse_target(load_json(a.target)[0])
        else:target=target_point(a.target_latitude_deg,a.target_longitude_deg)
        out=Path(a.out).resolve()
        if out.exists():raise N06Error('OUTPUT_EXISTS','use a new output filename; no overwrite')
        if any((parent/'.git').exists() for parent in [out.parent,*out.parents]):
            raise N06Error('OUTPUT_IN_REPOSITORY','output must be outside existing Git repositories')
        rows,provenance=load_candidates(a.manifest)
        result=evaluate_candidates(rows,target);result['inputs']=provenance
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('x',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,allow_nan=False,indent=2);f.write('\n')
        print('candidate_id | distance_to_target_m | input_index')
        for r in result['ranked']:print(f"{r['candidate_id']} | {r['distance_to_target_m']:.3f} | {r['input_index']}")
        for r in result['not_evaluated']:print(f"{r['candidate_id']} | NOT EVALUATED: {r['error']['code']} | {r['input_index']}")
        print('Saved:',out,'; flight computations=0; API calls=0')
        return 0
    except (OSError,N06Error) as e:
        print(json.dumps({'error':{'code':getattr(e,'code','FILE_ERROR'),'message':str(e)}},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
