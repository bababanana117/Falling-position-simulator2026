"""Existing single-run API transport: bounded reads, no automatic POST retries."""
import json
import urllib.error
import urllib.parse
import urllib.request
from core import Problem
from n06_distance import parse_json_bytes

class ApiError(Problem):
    def __init__(self,code,message,status=None,ambiguous=False):super().__init__(code,message);self.status=status;self.ambiguous=ambiguous
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k):return None

def base_url(base):
    p=urllib.parse.urlsplit(base)
    if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password or p.path not in ('','/') or p.query or p.fragment:
        raise Problem('API_BASE','PoC supports isolated loopback HTTP only')
    return base.rstrip('/')

class Api:
    def __init__(self,base,instance=None,timeout=15):
        self.base=base_url(base);self.instance=instance;self.timeout=timeout
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def call(self,path,body=None):
        headers={'Accept':'application/json'}
        if self.instance:headers['X-Balloon-Instance-Id']=self.instance
        data=None
        if body is not None:headers['Content-Type']='application/json';data=json.dumps(body,allow_nan=False).encode()
        request=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(64*1024*1024+1)
                if len(raw)>64*1024*1024:raise ApiError('RESPONSE_LIMIT','response exceeds 64MiB',ambiguous=body is not None)
                try:
                    value=parse_json_bytes(raw)
                    if not isinstance(value,dict):raise ValueError('API response must be an object')
                    return value
                except Exception as e:raise ApiError('INVALID_API_JSON',str(e),ambiguous=body is not None)
        except urllib.error.HTTPError as e:
            try:doc=parse_json_bytes(e.read(65536));detail=doc.get('error',{})
            except Exception:detail={}
            code=detail.get('code') if isinstance(detail,dict) else None
            message=detail.get('message') if isinstance(detail,dict) else None
            raise ApiError(code or 'HTTP_ERROR',message or str(e),e.code,ambiguous=(body is not None and e.code>=500)) from e
        except (urllib.error.URLError,TimeoutError,OSError) as e:raise ApiError('CONNECTION_ERROR',str(e),ambiguous=body is not None) from e
    def health(self):return self.call('/api/v1/health')
    def sources(self):return self.call('/api/v1/weather-sources')
    def submit(self,body):return self.call('/api/v1/runs',body)
    def lookup(self,rid):return self.call('/api/v1/run-requests?'+urllib.parse.urlencode({'client_request_id':rid}))
    def job(self,rid):return self.call('/api/v1/runs/'+urllib.parse.quote(rid,safe=''))
    def result(self,rid):return self.call('/api/v1/runs/'+urllib.parse.quote(rid,safe='')+'/result')
