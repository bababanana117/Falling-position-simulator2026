"""Launch a local N01 test page: python demo_server.py"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import json
from weather_cache import ForecastCache

cache=ForecastCache()
class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url=urlparse(self.path)
        if url.path!='/api/weather':
            return super().do_GET()
        p=parse_qs(url.query)
        try:
            lat=float(p.get('lat',[''])[0]); lon=float(p.get('lon',[''])[0]); when=p.get('when',[''])[0]
            force=p.get('force',['0'])[0]=='1'
            result=cache.get(lat,lon,when,force=force,candidate_id=p.get('candidate',[''])[0] or None)
        except (ValueError,TypeError) as exc:
            result={'status':'invalid_input','error':str(exc)}
        data=json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
if __name__=='__main__':
    print('N01 demo: http://127.0.0.1:8766/')
    ThreadingHTTPServer(('127.0.0.1',8766),Handler).serve_forever()
