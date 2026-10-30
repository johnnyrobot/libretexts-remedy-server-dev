"""Synthetic EXTERNAL ADAPT/CXone only. Never a replacement owned product."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import hmac
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

HTML='<!doctype html><html lang="en"><head><title>Synthetic question</title></head><body><main><h1>Retained stack sentinel</h1><h3>Skipped heading fixture</h3><p>Controlled external data.</p><img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="></main></body></html>'

# Only the separate development write rehearsal uses this source. The explicit
# thead/columnheader declarations let the reviewed table-header rule convert td
# to th/scope without inventing meaning or calling an unavailable AI provider.
SIGNED_SOURCE = ('<h1>Retained signed stack sentinel</h1><p>Exact Unicode café; α; 水.</p>'
    '<table><caption>Explicit synthetic header meanings</caption><thead><tr>'
    '<td role="columnheader">Item</td><td role="columnheader">Value</td>'
    '</tr></thead><tbody><tr><td>Alpha</td><td>One</td></tr></tbody></table>')


def synthetic_cxone_auth(token):
    """Only the pinned SDK's public fake credentials, never provider credentials."""
    match=re.fullmatch(r'synthetic-key_([0-9]{10})_=synthetic-user_([a-f0-9]{64})',token or '')
    if not match or abs(int(time.time())-int(match[1]))>120: return False
    expected=hmac.new(b'synthetic-secret',f'synthetic-key{match[1]}=synthetic-user'.encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,match[2])


def build_handler(kind, *, synthetic_development_mutations=False, synthetic_source_changes=False):
    if kind not in ('adapt', 'cxone') or ((synthetic_development_mutations or synthetic_source_changes) and kind != 'cxone'):
        raise ValueError('synthetic development mutations require cxone')
    lock=threading.Lock()
    state={'reads':0,'mutations':0,'denied':0,'fail':False,'empty':False,'malformed':False,'clean':False,'hold':False,'held':0,'requests':[]}
    source=SIGNED_SOURCE if synthetic_development_mutations else HTML.split('<main>',1)[1].split('</main>',1)[0]
    fragment=source
    source_controls=synthetic_source_changes or synthetic_development_mutations
    if source_controls:state['revision']=1
    if synthetic_development_mutations:
        state.update(writes=0,revision=1,lost_remote_response=False,hold_mutation=False,mutation_held=0)
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
            nonlocal fragment
            path=urlsplit(self.path).path
            if path.startswith('/control/'):
                if self.headers.get('X-Fixture-Control')!='synthetic-control-only': return self.reply(401,{'error':'control_auth_required'})
                if path in ('/control/reset-source','/control/change-source') and not source_controls: return self.reply(403,{'error':'synthetic_source_controls_required'})
                if self.command=='POST':
                    try: n=int(self.headers.get('Content-Length','0'))
                    except ValueError: return self.reply(400,{'error':'control_invalid'})
                    if n<0: return self.reply(400,{'error':'control_invalid'})
                    if n>1000: return self.reply(413,{'error':'control_limit'})
                    try: value=json.loads(self.rfile.read(n))
                    except (ValueError,UnicodeError): return self.reply(400,{'error':'control_invalid'})
                    if not isinstance(value,dict): return self.reply(400,{'error':'control_invalid'})
                    if not synthetic_development_mutations and any(key in value for key in ('lost_remote_response','hold_mutation')):
                        return self.reply(403,{'error':'synthetic_development_only'})
                    if path=='/control/change-source' and not isinstance(value.get('fragment'),str):
                        return self.reply(400,{'error':'control_fragment_required'})
                    if path=='/control/change-source':
                        try: value['fragment'].encode('utf-8',errors='strict')
                        except UnicodeError: return self.reply(400,{'error':'control_invalid_utf8'})
                    with lock:
                        for key in ('fail','empty','malformed','clean','hold'):
                            if key in value: state[key]=value[key] is True
                        if synthetic_development_mutations:
                            for key in ('lost_remote_response','hold_mutation'):
                                if key in value: state[key]=value[key] is True
                        if source_controls and path in ('/control/reset-source','/control/change-source'):
                            fragment=source if path=='/control/reset-source' else value['fragment']
                            state['revision']+=1
                with lock:
                    snapshot=json.loads(json.dumps(state))
                    if source_controls: snapshot['source_sha256']=hashlib.sha256(fragment.encode()).hexdigest()
                return self.reply(200,snapshot)
            with lock:
                state['requests'].append({'method':self.command,'path':path})
                state['requests']=state['requests'][-1000:]
                if self.command!='GET': state['mutations']+=1
                else: state['reads']+=1
                failed,empty,malformed,clean,hold=state['fail'],state['empty'],state['malformed'],state['clean'],state['hold']
            if self.command!='GET':
                if not (synthetic_development_mutations and self.command=='POST' and path=='/@api/deki/pages/42/contents'):
                    return self.reply(503,{'error':'synthetic_remote_mutation_forbidden'})
                if failed or not synthetic_cxone_auth(self.headers.get('X-Deki-Token')):
                    with lock: state['denied']+=1
                    return self.reply(401,{'error':'external_auth_required'})
                try: n=int(self.headers.get('Content-Length','-1'))
                except ValueError: return self.reply(400,{'error':'synthetic_invalid_length'})
                if self.headers.get('Transfer-Encoding') or n<0: return self.reply(400,{'error':'synthetic_invalid_length'})
                if n>5000000: return self.reply(413,{'error':'synthetic_body_limit'})
                self.connection.settimeout(5)
                try: raw=self.rfile.read(n)
                except (TimeoutError,OSError): return self.reply(408,{'error':'synthetic_body_timeout'})
                try: authored=raw.decode('utf-8',errors='strict')
                except UnicodeError: return self.reply(400,{'error':'synthetic_invalid_utf8'})
                if len(raw)!=n: return self.reply(400,{'error':'synthetic_incomplete_body'})
                with lock:
                    held=state['hold_mutation']
                    if held: state['mutation_held']+=1
                deadline=time.monotonic()+30
                while held:
                    if time.monotonic()>=deadline: return self.reply(503,{'error':'synthetic_hold_expired'})
                    time.sleep(.02)
                    with lock: held=state['hold_mutation']
                with lock:
                    fragment=authored
                    state['revision']+=1
                    state['writes']+=1
                    revision=state['revision']
                    lost=state['lost_remote_response']
                    state['lost_remote_response']=False
                if lost:
                    self.close_connection=True
                    try: self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    self.connection.close()
                    return
                return self.reply(200,{'page':{'@revision':str(revision)}})
            if failed: return self.reply(401,{'error':'synthetic_external_auth_failure'})
            if kind=='adapt':
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
                            time.sleep(.02)
                    content='<!doctype html><html lang="en"><head><title>Synthetic clean question</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main><h1>Actual clean fixture</h1><p>Controlled data.</p></main></body></html>' if clean else HTML
                    return self.reply(200,'<html><body><form><input type="password"></form></body></html>' if malformed else content,True)
            else:
                if path.startswith('/Sandboxes/johnnyphung/'):
                    with lock: current=fragment
                    return self.reply(200, '<!doctype html><html lang="en"><head><title>Synthetic reader</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main><section class="mt-content-container">'+current+'</section></main></body></html>', True)
                if not self.headers.get('X-Deki-Token'):
                    with lock: state['denied']+=1
                    return self.reply(401,{'error':'external_auth_required'})
                if path.endswith('/info'):
                    info={'@id':'42','path':{'#text':'Sandboxes/johnnyphung/Stack/Synthetic'},'title':'Synthetic page'}
                    if source_controls:
                        with lock: info['@revision']=str(state['revision'])
                    return self.reply(200,info)
                if '/contents' in path:
                    # mode=edit is authored page SOURCE, not a complete rendered
                    # document/editor wrapper. Keep ADAPT's full HTML separate.
                    with lock: current=fragment
                    return self.reply(200,{'body':current})
            return self.reply(404,{'error':'synthetic_route_not_found'})
    return Handler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=['adapt','cxone'],required=True)
    parser.add_argument('--synthetic-development-mutations',action='store_true',
                        help='Permit only synthetic CXone authored-content writes; never use for production proof.')
    parser.add_argument('--synthetic-source-controls',action='store_true',help='Allow authenticated fixture source replacement without enabling its mutation API.')
    args=parser.parse_args()
    if args.synthetic_development_mutations and args.kind != 'cxone':
        parser.error('--synthetic-development-mutations requires --kind cxone')
    Handler=build_handler(args.kind,synthetic_development_mutations=args.synthetic_development_mutations,synthetic_source_changes=args.synthetic_source_controls)
    if args.kind=='adapt':
        ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
    else:
        secure=ThreadingHTTPServer(('0.0.0.0',443),Handler)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain('/fixtures/cert.pem','/fixtures/key.pem')
        secure.socket=tls.wrap_socket(secure.socket,server_side=True)
        threading.Thread(target=secure.serve_forever,daemon=True).start()
        ThreadingHTTPServer(('0.0.0.0',8082),Handler).serve_forever()


if __name__ == '__main__':
    main()
