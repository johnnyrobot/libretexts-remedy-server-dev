"""Synthetic EXTERNAL ADAPT/CXone only. Never a replacement owned product."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
from urllib.parse import urlsplit

parser=argparse.ArgumentParser()
parser.add_argument('--kind',choices=['adapt','cxone'],required=True)
args=parser.parse_args()
lock=threading.Lock()
state={'reads':0,'mutations':0,'denied':0,'fail':False,'empty':False,'malformed':False,'requests':[]}
HTML='<!doctype html><html lang="en"><head><title>Synthetic question</title></head><body><main><h1>Retained stack sentinel</h1><h3>Skipped heading fixture</h3><p>Controlled external data.</p><img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="></main></body></html>'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*unused): pass
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def do_PUT(self): self.handle_request()
    def do_DELETE(self): self.handle_request()
    def reply(self,status,body,html=False):
        raw=body.encode() if html else json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json')
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def handle_request(self):
        path=urlsplit(self.path).path
        if path.startswith('/control/'):
            if self.headers.get('X-Fixture-Control')!='synthetic-control-only': return self.reply(401,{'error':'control_auth_required'})
            if self.command=='POST':
                n=int(self.headers.get('Content-Length','0'))
                if n>1000: return self.reply(413,{'error':'control_limit'})
                value=json.loads(self.rfile.read(n))
                with lock:
                    for key in ('fail','empty','malformed'):
                        if key in value: state[key]=value[key] is True
            with lock: snapshot=json.loads(json.dumps(state))
            return self.reply(200,snapshot)
        with lock:
            state['requests'].append({'method':self.command,'path':path})
            if self.command!='GET': state['mutations']+=1
            else: state['reads']+=1
            failed,empty,malformed=state['fail'],state['empty'],state['malformed']
        if self.command!='GET': return self.reply(503,{'error':'synthetic_remote_mutation_forbidden'})
        if failed: return self.reply(401,{'error':'synthetic_external_auth_failure'})
        if args.kind=='adapt':
            valid=(self.headers.get('Authorization')=='Bearer synthetic-adapt-token' or 'token=synthetic-adapt-token' in self.headers.get('Cookie',''))
            if not valid:
                with lock: state['denied']+=1
                return self.reply(401,{'error':'external_auth_required'})
            if path.startswith('/api/assignments/') and path.endswith('/questions/ids'):
                return self.reply(200,{'type':'success'} if malformed else {'type':'success','question_ids_array':[] if empty else [101],'question_ids':'[]' if empty else '[101]'})
            if path.startswith('/api/get-header-html/'):
                return self.reply(200,'<html><body><form><input type="password"></form></body></html>' if malformed else HTML,True)
        else:
            if not self.headers.get('X-Deki-Token'):
                with lock: state['denied']+=1
                return self.reply(401,{'error':'external_auth_required'})
            if path.endswith('/info'): return self.reply(200,{'@id':'42','path':{'#text':'Sandboxes/johnnyphung/Stack/Synthetic'},'title':'Synthetic page'})
            if '/contents' in path: return self.reply(200,{'body':HTML})
        return self.reply(404,{'error':'synthetic_route_not_found'})
if args.kind=='adapt':
    ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
else:
    secure=ThreadingHTTPServer(('0.0.0.0',443),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain('/fixtures/cert.pem','/fixtures/key.pem')
    secure.socket=tls.wrap_socket(secure.socket,server_side=True)
    threading.Thread(target=secure.serve_forever,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',8082),Handler).serve_forever()
