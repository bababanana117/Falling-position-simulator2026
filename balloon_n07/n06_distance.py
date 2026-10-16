"""N06: saved-result normalization and WGS84 ranking. No flight or HTTP imports."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
from geographiclib.geodesic import Geodesic
import geographiclib

MAX_FILE_BYTES = 64 * 1024 * 1024

class N06Error(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

def error(code, message):
    return {'code': code, 'message': message}

def coordinate(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise N06Error('INVALID_COORDINATE', name + ' must be a number, not a string/bool')
    try:
        finite = math.isfinite(value)
    except (OverflowError, ValueError):
        finite = False
    if not finite or not lower <= value <= upper:
        raise N06Error('INVALID_COORDINATE', name + ' is outside the WGS84 coordinate range')
    return float(value)

def target_point(latitude, longitude):
    return {'schema': 'n06.target/1',
            'target_latitude_deg': coordinate(latitude, 'target_latitude_deg', -90, 90),
            'target_longitude_deg': coordinate(longitude, 'target_longitude_deg', -180, 180)}

def parse_target(value):
    if not isinstance(value, dict) or set(value) - {'schema', 'target_latitude_deg', 'target_longitude_deg'}:
        raise N06Error('INVALID_TARGET', 'target requires only latitude/longitude and optional schema')
    if value.get('schema', 'n06.target/1') != 'n06.target/1':
        raise N06Error('INVALID_TARGET', 'unsupported target schema')
    return target_point(value.get('target_latitude_deg'), value.get('target_longitude_deg'))

def distance_m(landing_latitude, landing_longitude, target):
    target = parse_target(target)
    lat = coordinate(landing_latitude, 'landing_latitude_deg', -90, 90)
    lon = coordinate(landing_longitude, 'landing_longitude_deg', -180, 180)
    value = Geodesic.WGS84.Inverse(lat, lon, target['target_latitude_deg'], target['target_longitude_deg'])['s12']
    if not math.isfinite(value) or value < 0:
        raise N06Error('GEODESIC_ERROR', 'WGS84 returned an invalid distance')
    return value

def parse_json_bytes(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise N06Error('INVALID_JSON', 'duplicate key: '+key)
            result[key] = value
        return result
    def nonfinite(text):
        raise N06Error('INVALID_JSON', 'nonfinite number: '+text)
    def finite_float(text):
        v = float(text)
        if not math.isfinite(v): nonfinite(text)
        return v
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                          parse_constant=nonfinite, parse_float=finite_float)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, N06Error): raise
        raise N06Error('INVALID_JSON', str(exc)) from exc

def load_json(path):
    with Path(path).open('rb') as f:
        raw = f.read(MAX_FILE_BYTES+1)
    if len(raw) > MAX_FILE_BYTES:
        raise N06Error('FILE_SIZE_LIMIT', 'JSON file exceeds 64 MiB; use a single-case result file')
    digest = hashlib.sha256(raw).hexdigest()
    try:
        return parse_json_bytes(raw), digest
    except N06Error as exc:
        exc.source_sha256 = digest
        raise

def _id(value, name):
    if value is not None and (not isinstance(value, str) or not value or len(value) > 200):
        raise N06Error('INVALID_IDENTIFIER', name+' must be a nonempty string or null')
    return value

def _unwrap(value):
    """Finite explicit formats; do not recursively search arbitrary dictionaries."""
    if not isinstance(value, dict):
        raise N06Error('UNSUPPORTED_FORMAT', 'result root must be an object')
    if value.get('schema') == 'balloon.flight.result/1':
        return value, None, None, 'balloon_raw_result', None
    if value.get('mode') == 'isolated_api_single':
        job = value.get('run')
        job = job if isinstance(job, dict) else {}
        job_state = job.get('state') or value.get('state')
        envelope = value.get('envelope')
        if envelope is None:
            return None, job.get('run_id'), job_state, 'n05_api_record', value.get('error') or job.get('error')
        if not isinstance(envelope, dict) or not isinstance(envelope.get('result'), dict):
            raise N06Error('INVALID_WRAPPER', 'N05 API envelope.result must be an object')
        run_id = envelope.get('run_id')
        if not isinstance(run_id, str) or not run_id:
            raise N06Error('INVALID_WRAPPER', 'API result requires run_id')
        if job.get('run_id') is not None and job['run_id'] != run_id:
            raise N06Error('IDENTITY_MISMATCH', 'API job and result run IDs differ')
        if job_state is not None and job_state != 'completed':
            raise N06Error('JOB_RESULT_CONFLICT', 'saved result contradicts API job state')
        return envelope['result'], run_id, job_state, 'n05_api_record', None
    # The N05 direct CLI writes provenance + state + result + case_config.
    if isinstance(value.get('provenance'), dict) and value.get('state') in (
        'landed', 'stopped', 'input_error', 'engine_exception', 'weather_load_error'):
        state = value['state']; result = value.get('result')
        if state in ('landed', 'stopped'):
            if not isinstance(result, dict) or result.get('status') != state:
                raise N06Error('WRAPPER_STATUS_CONFLICT', 'N05 wrapper and flight status differ')
        elif result is not None:
            raise N06Error('WRAPPER_STATUS_CONFLICT', 'N05 error record must not contain a flight result')
        return result, value.get('run_id'), None, 'n05_direct_record', value.get('error')
    # Existing GET /runs/{id}/result returns this identified envelope.
    if isinstance(value.get('run_id'), str) and value.get('kind') == 'single_run' and 'result' in value:
        if not isinstance(value['result'], dict):
            raise N06Error('INVALID_WRAPPER', 'API result must be an object')
        return value['result'], value['run_id'], None, 'balloon_api_result', None
    # A job detail is not a scientific result, even when state=completed.
    if isinstance(value.get('run_id'), str) and value.get('state') in (
        'queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted') and 'result' not in value:
        return None, value['run_id'], value['state'], 'balloon_api_job_only', value.get('error')
    raise N06Error('UNSUPPORTED_FORMAT', 'not a supported saved single-case result; benchmark/ensemble/arbitrary wrappers are not accepted')

def normalize_result(value, candidate_id, input_index=0, source_path=None, source_sha256=None):
    _id(candidate_id, 'candidate_id')
    if candidate_id is None: raise N06Error('INVALID_IDENTIFIER', 'candidate_id must be explicit')
    row = {'candidate_id': candidate_id, 'run_id': None, 'input_index': input_index,
           'source_path': source_path, 'source_sha256': source_sha256, 'source_format': None,
           'launch_latitude_deg': None, 'launch_longitude_deg': None,
           'landing_latitude_deg': None, 'landing_longitude_deg': None,
           'distance_to_target_m': None, 'flight_status': None, 'job_state': None,
           'evaluable': False, 'error': None}
    try:
        result, run_id, job_state, source_format, source_error = _unwrap(value)
        row.update(run_id=_id(run_id,'run_id'), job_state=job_state, source_format=source_format)
        if result is None:
            row['error'] = error('NO_SAVED_FLIGHT_RESULT', 'job/error record has no saved scientific flight result')
            row['error']['source_error'] = copy.deepcopy(source_error)
            return row
        if result.get('schema') != 'balloon.flight.result/1':
            raise N06Error('UNSUPPORTED_FLIGHT_SCHEMA', 'requires balloon.flight.result/1')
        status = result.get('status'); row['flight_status'] = status if isinstance(status,str) else None
        if status not in ('landed', 'stopped'):
            raise N06Error('INVALID_FLIGHT_STATUS', 'unknown scientific flight status')
        launch = result.get('config', {}).get('launch') if isinstance(result.get('config'),dict) else None
        if not isinstance(launch, dict):
            raise N06Error('MISSING_LAUNCH', 'result.config.launch is required for comparison')
        row['launch_latitude_deg'] = coordinate(launch.get('latitude_deg'),'launch latitude',-90,90)
        row['launch_longitude_deg'] = coordinate(launch.get('longitude_deg'),'launch longitude',-180,180)
        if status == 'stopped':
            if result.get('complete') is not False:
                raise N06Error('STATUS_CONFLICT', 'stopped requires complete=false')
            row['error'] = error('FLIGHT_STOPPED', 'no landing: final trajectory record is never used')
            row['error']['stop_reason'] = copy.deepcopy(result.get('stop_reason'))
            return row
        if result.get('complete') is not True or result.get('stop_reason') is not None:
            raise N06Error('STATUS_CONFLICT', 'landed requires complete=true and no stop reason')
        summary = result.get('summary')
        landing = summary.get('landing') if isinstance(summary,dict) else None
        if not isinstance(landing,dict):
            raise N06Error('MISSING_LANDING', 'landed result lacks summary.landing')
        row['landing_latitude_deg'] = coordinate(landing.get('latitude_deg'),'landing latitude',-90,90)
        row['landing_longitude_deg'] = coordinate(landing.get('longitude_deg'),'landing longitude',-180,180)
        row['evaluable'] = True
    except N06Error as exc:
        row.update(evaluable=False, distance_to_target_m=None, error=error(exc.code,str(exc)))
        row['landing_latitude_deg'] = row['landing_longitude_deg'] = None
    return row

def load_candidates(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest, digest = load_json(manifest_path)
    if not isinstance(manifest,dict) or set(manifest) != {'schema','candidates'} or manifest['schema'] != 'n06.inputs/1':
        raise N06Error('INVALID_MANIFEST', 'requires schema=n06.inputs/1 and candidates list')
    entries = manifest['candidates']
    if not isinstance(entries,list) or not 1 <= len(entries) <= 1000:
        raise N06Error('INVALID_MANIFEST', 'requires 1..1000 saved result references')
    rows = []
    for index, entry in enumerate(entries):
        if not isinstance(entry,dict) or set(entry) != {'candidate_id','path'}:
            raise N06Error('INVALID_MANIFEST', 'each item needs exactly candidate_id and path')
        _id(entry['candidate_id'],'candidate_id')
        if entry['candidate_id'] is None or not isinstance(entry['path'],str) or not entry['path']:
            raise N06Error('INVALID_MANIFEST','candidate_id and file path must be nonempty strings')
        path = Path(entry['path']); path = path if path.is_absolute() else manifest_path.parent/path
        path = path.resolve()
        try:
            data, sha = load_json(path)
            row = normalize_result(data,entry['candidate_id'],index,str(path),sha)
        except (OSError, N06Error) as exc:
            row = normalize_result({},entry['candidate_id'],index,str(path))
            row['source_sha256'] = getattr(exc, 'source_sha256', None)
            row['error'] = error(getattr(exc,'code','INPUT_FILE_ERROR'),str(exc))
        rows.append(row)
    return rows, {'manifest_path':str(manifest_path), 'manifest_sha256':digest}

def evaluate_candidates(normalized_rows, target):
    """Reuse normalized landing coordinates for a different target; no reload/run."""
    target = parse_target(target); ranked=[]; not_evaluated=[]
    for original in normalized_rows:
        row = copy.deepcopy(original); row['distance_to_target_m'] = None
        if row.get('evaluable') and row.get('flight_status') != 'landed':
            row.update(evaluable=False,error=error('NORMALIZED_STATUS_CONFLICT','only normalized landed results may be evaluated'))
            not_evaluated.append(row)
        elif row.get('evaluable'):
            try:
                row['distance_to_target_m'] = distance_m(row['landing_latitude_deg'],row['landing_longitude_deg'],target)
                ranked.append(row)
            except N06Error as exc:
                row.update(evaluable=False,error=error(exc.code,str(exc)));not_evaluated.append(row)
        else:not_evaluated.append(row)
    # Exact numerical distance, then original manifest order. No rounded sorting.
    ranked.sort(key=lambda r:(r['distance_to_target_m'],r['input_index']))
    for rank,row in enumerate(ranked,1):row['rank']=rank
    return {'schema':'n06.comparison/1','target':target,
            'distance_definition':{'model':'WGS84 ellipsoid','method':'GeographicLib.Geodesic.WGS84.Inverse',
                                   'library_version':geographiclib.__version__,'unit':'m','height_used':False},
            'ranked':ranked,'not_evaluated':not_evaluated,
            'best_candidate':copy.deepcopy(ranked[0]) if ranked else None,
            'counts':{'input':len(normalized_rows),'ranked':len(ranked),'not_evaluated':len(not_evaluated)},
            'interpretation':'distance comparison only; no safety decision, forecast probability or target feasibility guarantee',
            'flight_computations':0,'api_calls':0}
