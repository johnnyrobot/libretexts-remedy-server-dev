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
state={'reads':0,'mutations':0,'denied':0,'fail':False,'empty':False,'malformed':False,'clean':False,'hold':False,'held':0,'requests':[]}
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
                    for key in ('fail','empty','malformed','clean','hold'):
                        if key in value: state[key]=value[key] is True
            with lock: snapshot=json.loads(json.dumps(state))
            return self.reply(200,snapshot)
        with lock:
            state['requests'].append({'method':self.command,'path':path})
            if self.command!='GET': state['mutations']+=1
            else: state['reads']+=1
            failed,empty,malformed,clean,hold=state['fail'],state['empty'],state['malformed'],state['clean'],state['hold']
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
                if hold:
                    with lock: state['held']+=1
                    while True:
                        with lock: active=state['hold']
                        if not active: break
                        import time;time.sleep(.02)
                content='<!doctype html><html lang="en"><head><title>Synthetic clean question</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main><h1>Actual clean fixture</h1><p>Controlled data.</p></main></body></html>' if clean else HTML
                return self.reply(200,'<html><body><form><input type="password"></form></body></html>' if malformed else content,True)
        else:
            if not self.headers.get('X-Deki-Token'):
                with lock: state['denied']+=1
                return self.reply(401,{'error':'external_auth_required'})
            if path.endswith('/info'): return self.reply(200,{'@id':'42','path':{'#text':'Sandboxes/johnnyphung/Stack/Synthetic'},'title':'Synthetic page'})
            if '/contents' in path:
                # mode=edit is authored page SOURCE, not a complete rendered
                # document/editor wrapper. Keep ADAPT's full HTML separate.
                fragment=HTML.split('<main>',1)[1].split('</main>',1)[0]
                return self.reply(200,{'body':fragment})
        return self.reply(404,{'error':'synthetic_route_not_found'})
if args.kind=='adapt':
    ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
else:
    secure=ThreadingHTTPServer(('0.0.0.0',443),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain('/fixtures/cert.pem','/fixtures/key.pem')
    secure.socket=tls.wrap_socket(secure.socket,server_side=True)
    threading.Thread(target=secure.serve_forever,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',8082),Handler).serve_forever()
