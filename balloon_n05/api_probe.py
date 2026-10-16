"""Prepare one existing API request; submit only to explicitly isolated loopback."""
import argparse
import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from n05_adapter import strict_json, change_location, write_new, error_info

class ApiFailure(RuntimeError):
    def __init__(self, kind, status=None, body=None):
        self.kind, self.status, self.body = kind, status, body
        super().__init__(kind)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def validate_base(base):
    u = urllib.parse.urlsplit(base)
    if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1') or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
        raise ValueError('only an isolated loopback HTTP server is supported')
    return base.rstrip('/')

def request_body(config, source_id, request_id=None):
    if not isinstance(source_id, str) or not source_id.strip(): raise ValueError('source ID required')
    rid = request_id or str(uuid.uuid4())
    return {'client_request_id': rid, 'candidate_id': 'N05-' + rid,
            'candidate_revision': 0, 'label': 'N05 isolated single case',
            'weather_source_id': source_id, 'config': copy.deepcopy(config)}

class Client:
    def __init__(self, base, instance=None, timeout=10):
        self.base, self.instance, self.timeout = validate_base(base), instance, timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def call(self, path, body=None):
        headers = {'Accept': 'application/json'}
        if self.instance: headers['X-Balloon-Instance-Id'] = self.instance
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'; data = json.dumps(body, allow_nan=False).encode()
        req = urllib.request.Request(self.base+path, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read(16*1024*1024+1)
                if len(raw) > 16*1024*1024: raise ApiFailure('response_too_large')
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read(65536)
            try: body = json.loads(raw)
            except (ValueError, UnicodeError): body = {'raw': raw.decode(errors='replace')}
            raise ApiFailure('http_rejected', e.code, body) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # A POST may have been accepted. Never automatically resubmit.
            raise ApiFailure('communication_unknown') from e

    def lookup(self, request_id):
        return self.call('/api/v1/run-requests?' + urllib.parse.urlencode({'client_request_id': request_id}))

    def once(self, body, deadline_s=120):
        health = self.call('/api/v1/health')
        instance = health.get('instance_id')
        if not isinstance(instance, str) or not instance: raise ApiFailure('missing_instance')
        if self.instance and self.instance != instance: raise ApiFailure('instance_mismatch')
        self.instance = instance
        acceptance = self.call('/api/v1/runs', body)
        run_id = acceptance['run_id']; end = time.perf_counter() + deadline_s
        while True:
            run = self.call('/api/v1/runs/'+urllib.parse.quote(run_id, safe=''))
            if run['state'] not in ('queued', 'running'):
                result = self.call('/api/v1/runs/'+urllib.parse.quote(run_id, safe='')+'/result') if run.get('result_available') else None
                return {'instance_id': instance, 'acceptance': acceptance, 'run': run, 'envelope': result}
            if time.perf_counter() >= end:
                return {'instance_id': instance, 'acceptance': acceptance, 'run': run, 'state': 'client_wait_timeout',
                        'note': 'server may still run; this does not cancel or resubmit', 'envelope': None}
            time.sleep(1)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8768')
    p.add_argument('--config'); p.add_argument('--source-id'); p.add_argument('--request-id')
    p.add_argument('--latitude', type=float); p.add_argument('--longitude', type=float)
    p.add_argument('--out', required=True); p.add_argument('--execute', action='store_true')
    p.add_argument('--ack-isolated-server', action='store_true')
    p.add_argument('--lookup', action='store_true'); p.add_argument('--instance-id')
    a = p.parse_args(); out = Path(a.out).resolve()
    try:
        validate_base(a.base)
        if out.exists(): raise FileExistsError('use a new output filename')
        if a.lookup:
            if not a.request_id: raise ValueError('--request-id required')
            write_new(out, {'mode': 'read_only_lookup', 'response': Client(a.base, a.instance_id).lookup(a.request_id)})
            return 0
        if not a.config or not a.source_id: raise ValueError('--config and --source-id required')
        c = change_location(strict_json(a.config), a.latitude, a.longitude)
        body = request_body(c, a.source_id, a.request_id)
        if not a.execute:
            write_new(out, {'mode': 'dry_run_no_network', 'request': body, 'endpoint': a.base+'/api/v1/runs'})
            return 0
        if not a.ack_isolated_server: raise ValueError('--ack-isolated-server required; no production server allowed')
        # Persist the exact intent before POST, without overwriting prior evidence.
        write_new(out.with_name(out.stem+'.intent'+out.suffix), {'base': a.base, 'request': body})
        client = Client(a.base, a.instance_id)
        try:
            response = client.once(body)
            write_new(out, {'mode': 'isolated_api_single', 'request': body, **response})
        except ApiFailure as exc:
            write_new(out, {'mode': 'isolated_api_single', 'request': body, 'instance_id': client.instance,
                            'state': exc.kind, 'http_status': exc.status, 'error': exc.body,
                            'note': 'do not automatically repeat POST; lookup this exact request ID'})
            return 2
        return 0
    except Exception as exc:
        print(error_info(exc)); return 2

if __name__ == '__main__': raise SystemExit(main())
