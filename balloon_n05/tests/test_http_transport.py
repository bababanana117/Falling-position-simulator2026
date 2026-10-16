"""Local HTTP MOCK only: validates wire format, not Balloon Lab execution."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from api_probe import Client, request_body

class HttpTransportTests(unittest.TestCase):
    def test_one_post_headers_poll_and_result(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def emit(self,status,body):
                b=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            def do_GET(self):
                seen.append(('GET',self.path,self.headers.get('X-Balloon-Instance-Id')))
                if self.path=='/api/v1/health':self.emit(200,{'instance_id':'MOCK-instance'})
                elif self.path.endswith('/result'):self.emit(200,{'run_id':'mock-run','result':{'status':'stopped','complete':False,'summary':{'landing':None}}})
                else:self.emit(200,{'run_id':'mock-run','state':'completed','result_available':True})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(('POST',self.path,self.headers.get('X-Balloon-Instance-Id'),self.headers.get('Content-Type'),body))
                self.emit(202,{'run_id':'mock-run','state':'queued'})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            c=Client('http://127.0.0.1:'+str(server.server_port))
            b=request_body({'MOCK_ONLY':True},'MOCK-source','MOCK-request')
            r=c.once(b)
            posts=[x for x in seen if x[0]=='POST']
            self.assertEqual(len(posts),1);self.assertEqual(posts[0][1],'/api/v1/runs')
            self.assertEqual(posts[0][2],'MOCK-instance');self.assertEqual(posts[0][3],'application/json');self.assertEqual(posts[0][4],b)
            self.assertEqual(r['envelope']['result']['status'],'stopped')
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
