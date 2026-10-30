"""Exact-artifact Linux rehearsal using only owned isolated CI resources."""
import hashlib
import sys
import http.client
import concurrent.futures
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import errno
import threading
import uuid
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from urllib.parse import urlsplit
from observer import Observer
from metrics import Metrics
from compose_proof import verify as verify_compose
from evidence import write_product_log

ROOT=Path.cwd();EVIDENCE=ROOT/'.stack-proof-evidence'
EVIDENCE.mkdir(exist_ok=True)
INPUT=json.loads((ROOT/'deploy/stack/bundle.json').read_text())
SCANNER=INPUT['scannerImage']; SERVER='remedy-server:stack-candidate'; BRIDGE='remedy-bridge:stack-candidate'
if os.environ.get('GITHUB_ACTIONS')!='true' or platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('This rehearsal requires an isolated authorized GitHub Linux amd64 runner; no local Docker fallback.')
PREFIX='lt196-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
WORK=Path(os.environ['RUNNER_TEMP'])/PREFIX
WORK.mkdir(mode=0o700)  # never reuse/delete somebody else's prior evidence
network=PREFIX+'-private';containers=[];observer=None;state_mounted=False;host_canary=None;deny_rule=None;network_created=False;owner_token=uuid.uuid4().hex;metrics=Metrics();report={'serverSource':os.environ['GITHUB_SHA'],'deploymentReady':False,'productionWritesEnabled':False,'sections':[],'images':{},'profiles':{},'errors':[]}
def cmd(*args,check=True):
    result=subprocess.run(list(map(str,args)),text=True,capture_output=True)
    if check and result.returncode: raise RuntimeError(str(args[:3])+': '+result.stderr[-1600:])
    return result.stdout

def response_after_send(conn,method,path,body=None,headers=None,encode_chunked=False):
    try:
        conn.request(method,path,body=body,headers=headers or {},encode_chunked=encode_chunked)
    except (BrokenPipeError,ConnectionResetError) as error:
        # Early refusal can close the write side while an eager client is still
        # sending. A readable actual HTTP response is still mandatory below;
        # the socket error alone is never considered a successful assertion.
        report.setdefault('clientWriteClosures',[]).append({'path':path,'error':type(error).__name__})
    return conn.getresponse()

def request(base,path,body=None,key=None,control=False):
    url=urlsplit(base); conn=http.client.HTTPConnection(url.hostname,url.port,timeout=950)
    headers={}
    if key: headers['X-Fixture-Control' if control else 'X-API-Key']=key
    raw=json.dumps(body).encode() if body is not None else None
    if raw is not None: headers['Content-Type']='application/json'
    try:
        response=response_after_send(conn,'POST' if raw is not None else 'GET',path,raw,headers)
        data=response.read()
        try: value=json.loads(data)
        except ValueError: value={'nonJsonBytes':len(data)}
        return response.status,value
    finally: conn.close()

def multipart(base,path,content,filename='fixture.html',extra=()):
    boundary='stack-proof-controlled-boundary'
    raw=bytearray()
    for name,value in extra:
        raw.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()+value+b'\r\n')
    raw.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+content+f'\r\n--{boundary}--\r\n'.encode())
    url=urlsplit(base);connection=http.client.HTTPConnection(url.hostname,url.port,timeout=950)
    try:
        response=response_after_send(connection,'POST',path,raw,{'X-API-Key':'synthetic-server-key','Content-Type':'multipart/form-data; boundary='+boundary})
        data=response.read()
        try: value=json.loads(data)
        except ValueError: value={'nonJsonBytes':len(data)}
        return response.status,value,len(raw)
    finally: connection.close()

def terminal(base,job):
    deadline=time.monotonic()+120
    while True:
        status,result=request(base,'/v1/jobs/'+job['id'],key='synthetic-server-key');assert status==200
        if result['status'] in {'done','failed'}: return result
        assert time.monotonic()<deadline;time.sleep(.05)

def wait(base,path='/healthz',key=None):
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            status,body=request(base,path,key=key)
            if status==200: return body
        except (OSError,http.client.HTTPException): pass
        time.sleep(.1)
    raise RuntimeError('Actual service did not become ready: '+path)

def port(name,number):
    info=json.loads(cmd('docker','inspect',name))[0]
    address=info['NetworkSettings']['Networks'][network]['IPAddress']
    assert address and info['HostConfig']['NetworkMode']==network
    report.setdefault('privateClientEndpoints',{})[name+':'+str(number)]={'privateAddress':address,'hostPortPublished':False}
    return 'http://'+address+':'+str(number)

def write_env(name,values):
    file=WORK/(name+'.env');file.write_text(''.join(f'{k}={v}\n' for k,v in values.items()));file.chmod(0o600)
    return file

def credentials(role,uid,values):
    directory=WORK/role;directory.mkdir(mode=0o700);os.chown(directory,uid,uid)
    for name,value in values.items():
        file=directory/name;file.write_text(value+'\n');os.chown(file,uid,uid);file.chmod(0o400)
    return directory

def start(name,image,env=None,mounts=(),extra=(),command=(),uid=None):
    options=['docker','run','--detach','--name',name,'--label','org.libretexts.stack-proof-owner='+owner_token,'--init','--cap-drop','ALL','--security-opt','no-new-privileges:true','--read-only']
    if uid is not None: options+=['--user',str(uid)+':'+str(uid)]
    if env: options+=['--env-file',env]
    for source,target,readonly in mounts:
        options+=['--mount',f'type=bind,src={source},dst={target}'+(',readonly' if readonly else '')]
    options+=list(extra)+['--entrypoint',command[0],image,*command[1:]]
    result=subprocess.run(list(map(str,options)),text=True,capture_output=True)
    inspect=subprocess.run(['docker','inspect',name],text=True,capture_output=True)
    if inspect.returncode==0 and json.loads(inspect.stdout)[0]['Config'].get('Labels',{}).get('org.libretexts.stack-proof-owner')==owner_token:
        containers.append(name)
        role=name.removeprefix(PREFIX+'-')
        if role in {'server','scanner','bridge'}: metrics.register(name,json.loads(inspect.stdout)[0],INPUT['limits'][role])
    if result.returncode: raise RuntimeError('Owned container start failed: '+name+': '+result.stderr[-1000:])
    return name

try:
    imports=json.loads((EVIDENCE/'imports.json').read_text())
    assert imports['verificationComplete'] and imports['serverSource']==os.environ['GITHUB_SHA']
    report['importedArtifacts']=imports
    cmd('docker','network','create','--internal','--label','org.libretexts.stack-proof-owner='+owner_token,network);network_created=True
    inspection=json.loads(cmd('docker','network','inspect',network))[0]
    assert inspection['Internal'] is True
    interface=inspection['Options'].get('com.docker.network.bridge.name','br-'+inspection['Id'][:12])
    candidate_deny_rule=['INPUT','-i',interface,'-m','conntrack','!','--ctstate','ESTABLISHED,RELATED','-j','DROP']
    # This only restricts NEW/invalid host ingress from our newly created CI
    # bridge; no ACCEPT, flush, global restore or host-policy relaxation.
    cmd('iptables','-I',*candidate_deny_rule);deny_rule=candidate_deny_rule
    gateway=inspection['IPAM']['Config'][0]['Gateway']
    class Canary(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'controlled-host-listener')
    host_canary=ThreadingHTTPServer((gateway,0),Canary)
    threading.Thread(target=host_canary.serve_forever,daemon=True).start()
    host_canary_port=host_canary.server_port
    report['host']={'kernel':cmd('uname','-srmo').strip(),'docker':cmd('docker','version','--format','{{.Server.Version}}').strip(),'networkInternal':True}
    for name,image in [('server',SERVER),('bridge',BRIDGE),('scanner',SCANNER)]:
        info=json.loads(cmd('docker','image','inspect',image))[0]
        assert info['Architecture']=='amd64' and info['Os']=='linux'
        if name in {'server','scanner'}: assert info['Config'].get('User','') not in {'','0','root'}
        report['images'][name]={'id':info['Id'],'repoDigests':info['RepoDigests'],'layers':info['RootFS']['Layers'],'user':info['Config'].get('User',''),'runtimeUserOverride':'1000:1000' if name=='bridge' else None}
        if name in {'server','bridge'}:
            assert info['Id']==imports['images'][name]['loadedDockerImageID']
            assert info['RootFS']['Layers']==imports['images'][name]['filesystemDiffIDs']
    assert SCANNER in report['images']['scanner']['repoDigests']
    scanner_inputs=json.loads((ROOT/'deploy/stack/scanner-profile-source.json').read_text())
    actual_lock=cmd('docker','run','--rm','--network','none','--entrypoint','node',SCANNER,'-e',
        'process.stdout.write(require("node:crypto").createHash("sha256").update(require("node:fs").readFileSync("/app/package-lock.json")).digest("hex"))').strip()
    assert actual_lock==scanner_inputs['package_lock_sha256']
    report['images']['scanner']['packageLockSha256']=actual_lock
    uid=int(cmd('docker','run','--rm','--network','none','--entrypoint','node',SCANNER,'-e','console.log(process.getuid())').strip())
    assert uid!=0
    server_keys=credentials('server-keys',999,{'app':'synthetic-server-key','ollama':'synthetic-provider-key','service':'a1'*32,'canary':'CANARY_NOT_A_CREDENTIAL'})
    scanner_keys=credentials('scanner-keys',uid,{'api':'synthetic-scanner-key','adapt':'synthetic-adapt-token','remedy':'synthetic-server-key'})
    bridge_keys=credentials('bridge-keys',1000,{'key':'synthetic-key','secret':'synthetic-secret','user':'synthetic-user','service':'a1'*32})
    state=WORK/'state';state.mkdir()
    state_image=WORK/'state.ext4'
    with state_image.open('xb') as stream: stream.truncate(INPUT['limits']['server']['stateBytes'])
    assert state_image.is_file() and not state_image.is_symlink()
    cmd('mkfs.ext4','-q','-F','-m','0',state_image)
    cmd('mount','-t','ext4','-o','loop,nodev,nosuid,noexec',state_image,state);state_mounted=True
    os.chown(state,999,999);state.chmod(0o700)
    space=os.statvfs(state)
    assert space.f_frsize*space.f_blocks<=INPUT['limits']['server']['stateBytes']
    report['storage']={'filesystem':cmd('findmnt','--noheadings','--output','FSTYPE','--target',state).strip(),'capacityBytes':space.f_frsize*space.f_blocks,'privateUid':state.stat().st_uid}
    fixture=WORK/'fixture';fixture.mkdir();os.chown(fixture,999,999)
    cmd('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=dev.libretexts.org','-addext','subjectAltName=DNS:dev.libretexts.org','-keyout',fixture/'key.pem','-out',fixture/'cert.pem')
    os.chown(fixture/'key.pem',999,999);(fixture/'key.pem').chmod(0o400);(fixture/'cert.pem').chmod(0o444)
    public=ROOT/'.github/stack-proof';wrapper=ROOT/'deploy/stack/secret-env.mjs'
    audit={}
    for role in ('server','scanner'):
        directory=EVIDENCE/('observations-'+role);directory.mkdir();directory.chmod(0o777);audit[role]=directory
    observer=Observer({PREFIX+'-'+role:directory for role,directory in audit.items()});observer.start()
    base_mounts=[(wrapper,'/proof/secret-env.mjs',True)]
    # Run the public package first, with exclusive access to disposable state.
    # Failures retain startup health/command/log evidence before instrumentation.
    report['publicCompose']=verify_compose(ROOT,WORK,EVIDENCE,PREFIX,report['images'],state,fixture,
        {'server':server_keys,'scanner':scanner_keys,'bridge':bridge_keys})
    report['sections'].append('public-compose')
    server_env=write_env('server',{'APP_ENV':'production','PYTHON_DOTENV_DISABLED':'1','APP_API_KEY_FILE':'/run/secrets/app','OLLAMA_API_KEY_FILE':'/run/secrets/ollama','OLLAMA_BASE_URL':'https://provider.invalid/v1','CORS_ALLOW_ORIGINS':'https://conductor.fixture.invalid','JOB_DIR':'/app/state/jobs','JOB_STORE_PATH':'/app/state/jobs.sqlite3','JOB_BACKUP_DIR':'/app/state/backups','OUTPUT_DIR':'/app/state/output','LOG_DIR':'/app/state/logs','LOG_FORMAT':'json','HOME':'/tmp','TMPDIR':'/tmp','CXONE_INTEGRATION_ENABLED':'false','WORKER_CONCURRENCY':'1','WORKER_MAX_PENDING':'8','JOB_TOTAL_TIMEOUT_SECONDS':'900','RATE_LIMIT_DEFAULT':'10000/minute','RATE_LIMIT_UPLOADS':'10000/minute','MAX_UPLOAD_MB':'4','MAX_REQUEST_BYTES':'5000000','PYTHONPATH':'/proof-hooks:/app:/app/src'})
    server_options=['--network',network,'--dns','127.0.0.1','--dns','127.0.0.1','--cpus','4','--memory','4g','--pids-limit','512','--shm-size','256m','--stop-timeout','120','--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--security-opt','seccomp='+str(ROOT/'deploy/chromium-seccomp-amd64.json')]
    server_command=['node','/proof/secret-env.mjs','server','uvicorn','backend.app.main:app','--host','0.0.0.0','--port','8000','--workers','1','--timeout-graceful-shutdown','15']
    start(PREFIX+'-server',SERVER,server_env,[*base_mounts,(server_keys,'/run/secrets',True),(state,'/app/state',False),(public/'hooks','/proof-hooks',True),(audit['server'],'/proof-audit',False)],server_options,server_command)
    server_url=port(PREFIX+'-server',8000);wait(server_url,'/readyz')
    status,health=request(server_url,'/v1/cxone/health',key='synthetic-server-key')
    assert status==200 and health['enabled'] is False and health['capabilities']['mutate'] is False
    assert not any(name.endswith('-bridge') for name in containers)
    scanner_env=write_env('scanner',{'ADAPT_BASE_URL':'http://127.0.0.1:8081','ADAPT_TOKEN_FILE':'/run/secrets/adapt','SCANNER_API_KEY_FILE':'/run/secrets/api','REMEDY_API_KEY_FILE':'/run/secrets/remedy','SCAN_MODE':'http','RENDER_MODE':'iframe','REMEDY_ENDPOINT':f'http://{PREFIX}-server:8000/v1/validate/html','HOME':'/tmp','TMPDIR':'/tmp','SCANNER_MAX_ACTIVE_JOBS':'1','SCANNER_MAX_QUEUED_JOBS':'8','SCANNER_JOB_TIMEOUT_MS':'900000','SCANNER_MAX_REQUEST_BYTES':'5000000','REMEDY_TIMEOUT_MS':'920000','NODE_OPTIONS':'--import=file:///proof-hooks/scanner.mjs'})
    start(PREFIX+'-scanner',SCANNER,scanner_env,[*base_mounts,(scanner_keys,'/run/secrets',True),(public/'hooks','/proof-hooks',True),(audit['scanner'],'/proof-audit',False)],['--network',network,'--dns','127.0.0.1','--cpus','2','--memory','2g','--pids-limit','512','--shm-size','1g','--stop-timeout','20','--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--security-opt','seccomp='+str(ROOT/'deploy/stack/scanner-seccomp-amd64.json')],['node','/proof/secret-env.mjs','scanner','node','dist/server.js'])
    scanner_url=port(PREFIX+'-scanner',5176);wait(scanner_url)
    start(PREFIX+'-adapt',SERVER,mounts=[(public/'external.py','/proof/external.py',True)],extra=['--network','container:'+PREFIX+'-scanner','--tmpfs','/tmp:rw,nosuid,nodev,size=16m','--cpus','1','--memory','128m','--pids-limit','32'],command=['python','/proof/external.py','--kind','adapt'])
    adapt_url=port(PREFIX+'-scanner',8081)
    deadline=time.monotonic()+30
    while True:
        try:
            if request(adapt_url,'/control/status',key='synthetic-control-only',control=True)[0]==200: break
        except OSError: pass
        assert time.monotonic()<deadline;time.sleep(.1)
    assert request(scanner_url,'/v1/adapt/scan',{'mode':'question','id':101})[0]==401
    status,scan=request(scanner_url,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key')
    assert status==200 and len(scan['results'])==1 and not scan['results'][0]['failed'],scan
    assert scan['results'][0]['capturedBytes']>0 and scan['results'][0]['findings'],scan
    report['profiles']['engine-scanner']={'bridgeAbsent':True,'serverHealth':health,'scanner':scan}
    # The review-only case uses actual Bridge plus real SDK, fake CXone only.
    start(PREFIX+'-cxone',SERVER,mounts=[(public/'external.py','/proof/external.py',True),(fixture,'/fixtures',True)],extra=['--network',network,'--network-alias','dev.libretexts.org','--cpus','1','--memory','128m','--pids-limit','32','--tmpfs','/tmp:rw,nosuid,nodev,size=16m'],command=['python','/proof/external.py','--kind','cxone'])
    cxone_url=port(PREFIX+'-cxone',8082)
    deadline=time.monotonic()+30
    while True:
        try:
            if request(cxone_url,'/control/status',key='synthetic-control-only',control=True)[0]==200: break
        except OSError: pass
        assert time.monotonic()<deadline;time.sleep(.1)
    # Replace only our exact container, retaining its private job store.
    prior=json.loads(cmd('docker','inspect',PREFIX+'-server'))[0]
    metrics.begin_stop(prior['Id'])
    cmd('docker','stop','--time','120',PREFIX+'-server')
    prior_stopped=json.loads(cmd('docker','inspect',PREFIX+'-server'))[0]
    metrics.finish_stop(prior_stopped)
    assert prior_stopped['State']['ExitCode'] in {0,143},'initial Server stop failed'
    cmd('docker','rm',PREFIX+'-server');containers.remove(PREFIX+'-server')
    text=server_env.read_text().replace('CXONE_INTEGRATION_ENABLED=false','CXONE_INTEGRATION_ENABLED=true')+'CXONE_BRIDGE_BASE_URL=http://127.0.0.1:5175\nREMEDY_BRIDGE_SERVICE_KEY_FILE=/run/secrets/service\n'
    server_env.write_text(text)
    start(PREFIX+'-server',SERVER,server_env,[*base_mounts,(server_keys,'/run/secrets',True),(state,'/app/state',False),(public/'hooks','/proof-hooks',True),(audit['server'],'/proof-audit',False)],server_options,server_command)
    server_url=port(PREFIX+'-server',8000);wait(server_url,'/readyz')
    bridge_env=write_env('bridge',{'NODE_ENV':'production','REMEDY_BRIDGE_PROFILE':'review-only','REMEDY_REVIEWER_REQUIRED':'true','REMEDY_BRIDGE_SERVICE_KEY_FILE':'/run/secrets/service','CXONE_INTEGRATION_ENABLED':'true','SERVER_DOMAIN':'dev.libretexts.org','SERVER_KEY_FILE':'/run/secrets/key','SERVER_SECRET_FILE':'/run/secrets/secret','SERVER_USER_FILE':'/run/secrets/user','REMEDY_WRITE_ALLOWLIST':'^Sandboxes/johnnyphung(?:/|$)','REMEDY_WORK_ACTIVE':'1','REMEDY_WORK_QUEUED':'8','REMEDY_WORK_TIMEOUT_MS':'120000','REMEDY_MAX_REQUEST_BYTES':'5000000','NODE_EXTRA_CA_CERTS':'/fixtures/cert.pem','HOME':'/tmp','NPM_CONFIG_CACHE':'/tmp/npm'})
    start(PREFIX+'-bridge',BRIDGE,bridge_env,[*base_mounts,(bridge_keys,'/run/secrets',True),(fixture/'cert.pem','/fixtures/cert.pem',True)],['--network','container:'+PREFIX+'-server','--cpus','1','--memory','768m','--pids-limit','128','--stop-timeout','30','--tmpfs','/tmp:rw,nosuid,nodev,size=256m'],['node','/proof/secret-env.mjs','bridge','node','--import','tsx','packages/conductor-panel/server/server.ts'],1000)
    bridge_health=wait(server_url,'/v1/cxone/health','synthetic-server-key')
    assert bridge_health['profile']['name']=='review-only' and not bridge_health['capabilities']['mutate']
    status,page=request(server_url,'/v1/cxone/page/scan',{'page_id':'42'},'synthetic-server-key')
    assert status==200 and page['findings'],page
    report['profiles']['bridge-review']={'health':bridge_health,'scan':page}
    assert bridge_health['profile']['contract']=='cxone-review-v1' and bridge_health['capabilities']['operation_status'] is False
    status,preview=request(server_url,'/v1/cxone/page/preview-fix',{'page_id':'42','review_images':True},'synthetic-server-key')
    assert status==200 and preview['review_images'] and preview['review_binding']['action']=='cxone.apply',preview
    assert type(preview['review_expires_at']) is int
    vectors=json.loads((ROOT/'tests/unit/contracts_v1/lt-1-reviewer-wire-v1-vectors.json').read_text())
    assertion=vectors['positive'][0]['compact']
    denied_body={'page_id':'42','preview_hash':preview['preview_hash'],'preview_token':preview['preview_token'],'reviewer_assertion':assertion}
    expected_denial={'error':'review_only_profile','outcome':'not_attempted','evidence_effect':'preserve','retryable':False,'operation_id':None}
    for path in ('/v1/cxone/page/apply-fix','/v1/cxone/page/restore'):
        status,denial=request(server_url,path,denied_body,'synthetic-server-key')
        assert (status,denial)==(503,expected_denial),(status,denial)
    image_source=preview['review_images'][0]['data']['src']
    status,revised=request(server_url,'/v1/cxone/page/revise-preview',{'page_id':'42','preview_token':preview['preview_token'],
        'alt_edits':[{'src':image_source,'text':'Controlled synthetic image description'}]},'synthetic-server-key')
    assert status==200 and 'Controlled synthetic image description' in revised['after_html'],revised
    assert revised['preview_token']!=preview['preview_token']
    assert request(cxone_url,'/control/status',key='synthetic-control-only',control=True)[1]['mutations']==0
    status,missing_history=request(server_url,'/v1/cxone/page/operation-status',{'issuer':'urn:conductor:synthetic','jti':'A'*43},'synthetic-server-key')
    assert status==503 and missing_history['error']=='operation_status_unavailable',missing_history
    report['reviewProof']={'actualPreview':True,'signedMutationDenied':True,'originalPreviewRetainedForValidRevision':True,'missingHistoryUnavailable':True,'externalMutations':0}

    for role in ('server','scanner','bridge'):
        actual_uid=int(cmd('docker','exec',PREFIX+'-'+role,'node','-e','console.log(process.getuid())').strip())
        assert actual_uid!=0
        report['images'][role]['actualRuntimeUid']=actual_uid
    report['sections'].append('actual-service-bootstrap')
    html=b'<!doctype html><html lang="en"><title>Sandbox PDF</title><body><main><h1>Retained actual stack PDF sentinel</h1></main></body></html>'
    boundary='stack-proof-boundary'
    upload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="fixture.html"\r\nContent-Type: text/html\r\n\r\n'.encode()+html+f'\r\n--{boundary}--\r\n'.encode())
    endpoint=urlsplit(server_url);connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port,timeout=950)
    connection.request('POST','/v1/convert/html-to-pdf',upload,{'X-API-Key':'synthetic-server-key','Content-Type':'multipart/form-data; boundary='+boundary})
    response=connection.getresponse();job=json.loads(response.read());assert response.status==202,job;connection.close()
    deadline=time.monotonic()+120
    while True:
        status,job=request(server_url,'/v1/jobs/'+job['id'],key='synthetic-server-key');assert status==200
        if job['status'] in {'done','failed'}: break
        assert time.monotonic()<deadline;time.sleep(.05)
    assert job['status']=='done',job
    connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port,timeout=15)
    connection.request('GET','/v1/jobs/'+job['id']+'/result',headers={'X-API-Key':'synthetic-server-key'})
    response=connection.getresponse();pdf=response.read();assert response.status==200 and pdf.startswith(b'%PDF-');connection.close()
    parsed=subprocess.run(['docker','exec','-i',PREFIX+'-server','python','-c',
        'import io,sys,fitz;d=fitz.open(stream=sys.stdin.buffer.read(),filetype="pdf");assert d.page_count==1 and "Retained actual stack PDF sentinel" in d[0].get_text();print("genuine PDF parsed")'],input=pdf,capture_output=True)
    assert parsed.returncode==0,parsed.stderr.decode()[-500:]
    report['generatedPdf']={'bytes':len(pdf),'sha256':hashlib.sha256(pdf).hexdigest(),'parsedSentinel':True}
    expected={'server-render','server-axe','server-pa11y','server-lighthouse','scanner-browser'}
    assert observer is not None and not observer.errors,observer.errors
    assert expected <= {item['tool'] for item in observer.records},[item['tool'] for item in observer.records]
    report['sections'].append('sandbox-identities')
    server_info=json.loads(cmd('docker','inspect',PREFIX+'-server'))[0]
    bridge_info=json.loads(cmd('docker','inspect',PREFIX+'-bridge'))[0]
    assert not bridge_info['HostConfig'].get('PortBindings') and bridge_info['HostConfig']['NetworkMode'].startswith('container:')
    server_ip=server_info['NetworkSettings']['Networks'][network]['IPAddress']
    isolated=cmd('docker','run','--rm','--network',network,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--cpus','1','--memory','128m','--pids-limit','32','--entrypoint','python',SERVER,'-c',
        'import socket,pathlib;s=socket.socket();s.settimeout(2);assert s.connect_ex(('+repr(server_ip)+',5175))!=0;assert not pathlib.Path("/run/secrets/service").exists();print("private listener and mounts inaccessible")')
    assert 'inaccessible' in isolated
    # Metadata-only loopback observation, no payload/header/credential capture.
    capture=WORK/'bridge-contact-metadata.txt'
    with capture.open('w') as stream:
        packet=subprocess.Popen(['nsenter','--net=/proc/'+str(server_info['State']['Pid'])+'/ns/net',
            'tcpdump','--immediate-mode','-n','-l','-i','lo','tcp dst port 5175'],stdout=stream,stderr=subprocess.PIPE,text=True)
        try:
            # tcpdump's ready line is a causal barrier, not a sleep assumption.
            assert packet.stderr is not None
            deadline=time.monotonic()+10
            while True:
                line=packet.stderr.readline()
                if 'listening on' in line: break
                assert packet.poll() is None and time.monotonic()<deadline,line
            before=request(cxone_url,'/control/status',key='synthetic-control-only',control=True)[1]
            hostile=b'<html lang="en"><title>Blocked resource</title><body><iframe src="file:///run/secrets/canary"></iframe><img alt="controlled" src="http://127.0.0.1:5175/readyz"><script>fetch("http://127.0.0.1:5175/readyz")</script></body></html>'
            status,denied,_=multipart(server_url,'/v1/validate/html',hostile)
            assert status==200 and denied['overall_passed'] is False,denied
            assert 'CANARY_NOT_A_CREDENTIAL' not in json.dumps(denied)
            after=request(cxone_url,'/control/status',key='synthetic-control-only',control=True)[1]
            assert after['reads']==before['reads'] and after['mutations']==0
        finally:
            if packet.poll() is None: packet.terminate()
            packet.wait(timeout=5)
    assert capture.read_text().strip()=='','document contacted private Bridge listener'
    for role in ('server','scanner','bridge'):
        blocked='const net=require("node:net");const s=net.connect({host:process.argv[1],port:Number(process.argv[2])});s.on("connect",()=>process.exit(1));s.on("error",()=>process.exit(0));s.setTimeout(1500,()=>{s.destroy();process.exit(0)});'
        cmd('docker','exec',PREFIX+'-'+role,'node','-e',blocked,gateway,str(host_canary_port))
        cmd('docker','exec',PREFIX+'-'+role,'node','-e',blocked,'198.51.100.1','443')
    report['privateIsolation']={'hostAndExternalEgressDenied':True,'dnsForwardingDisabled':True,'thirdContainerDenied':True,'secretMountAbsentOutside':True,'documentBridgePackets':0,'documentFileCanaryNotDisclosed':True}
    report['sections'].append('private-isolation')
    # Real read error and retry, not an invented successful/empty scan envelope.
    request(cxone_url,'/control/status',{'fail':True},'synthetic-control-only',True)
    status,failed=request(server_url,'/v1/cxone/page/scan',{'page_id':'42'},'synthetic-server-key')
    assert status>=400,failed
    failed_health_code,failed_health=request(server_url,'/v1/cxone/health',key='synthetic-server-key')
    report['requiredReadFailure']={'scanStatus':status,'healthStatus':failed_health_code,'health':failed_health}
    if failed_health_code!=503:
        # Keep this contract defect blocking while exercising independent
        # owned admission/storage seams in the same exact-artifact run.
        report['errors'].append('required_external_read_failure_did_not_make_review_profile_unready')
    request(cxone_url,'/control/status',{'fail':False},'synthetic-control-only',True)
    assert request(server_url,'/v1/cxone/page/scan',{'page_id':'42'},'synthetic-server-key')[0]==200
    assert request(server_url,'/v1/cxone/health',key='synthetic-server-key')[0]==200
    for flag in ('empty','malformed','fail'):
        request(adapt_url,'/control/status',{flag:True},'synthetic-control-only',True)
        code,value=request(scanner_url,'/v1/adapt/scan',{'mode':'assignment','id':1},'synthetic-scanner-key')
        assert value.get('ok') is False and (code>=400 or value.get('exitCode')==1),value
        request(adapt_url,'/control/status',{flag:False},'synthetic-control-only',True)
    request(adapt_url,'/control/status',{'clean':True},'synthetic-control-only',True)
    code,clean=request(scanner_url,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key')
    assert code==200 and clean['ok'] is True and clean['exitCode']==0 and clean['results'][0]['overallPassed'] is True,clean
    request(adapt_url,'/control/status',{'clean':False},'synthetic-control-only',True)
    report['readRecovery']={'bridgeDependencyFailureThenRealRetry':failed_health_code==503,'scannerEmptyMalformedAuthRefused':True,'actualCleanAfterErrors':True}
    # A complete raw JSON request at the published limit; one byte over is
    # refused before any additional source read.
    for base,path,key,body,external in [(scanner_url,'/v1/adapt/scan','synthetic-scanner-key',{'mode':'question','id':101},adapt_url),
                                      (server_url,'/v1/cxone/page/scan','synthetic-server-key',{'page_id':'42'},cxone_url)]:
        base_size=len(json.dumps({**body,'padding':''}).encode())
        exact={**body,'padding':'x'*(5000000-base_size)}
        assert len(json.dumps(exact).encode())==5000000
        accepted_code,accepted_body=request(base,path,exact,key)
        assert accepted_code==200,{'path':path,'status':accepted_code,'body':accepted_body}
        previous=request(external,'/control/status',key='synthetic-control-only',control=True)[1]['reads']
        exact['padding']+='x'
        refused_code,refused_body=request(base,path,exact,key)
        assert refused_code==413,{'path':path,'status':refused_code,'body':refused_body,'requestBytes':5000001}
        assert request(external,'/control/status',key='synthetic-control-only',control=True)[1]['reads']==previous
        url=urlsplit(base);conn=http.client.HTTPConnection(url.hostname,url.port,timeout=180)
        raw=json.dumps(exact).encode()
        try:
            response=response_after_send(conn,'POST',path,(raw[i:i+65536] for i in range(0,len(raw),65536)),
                {'X-API-Key':key,'Content-Type':'application/json'},encode_chunked=True)
            body=response.read()
            assert response.status==413,{'path':path,'chunkedStatus':response.status,'responseBytes':len(body)}
        finally: conn.close()
        assert request(external,'/control/status',key='synthetic-control-only',control=True)[1]['reads']==previous
        report.setdefault('requestEnvelopes',{})[path]={'exact5000000Accepted':True,'oneByteOver413':True,'chunkedOver413':True,'rejectedSourceReads':0}
    # Valid multipart with ignored fields must also respect the total envelope,
    # rather than merely limiting the selected file after full parser spooling.
    code,oversized,total=multipart(server_url,'/v1/convert/html-to-pdf',html,extra=[('ignored'+str(i),b'x'*850000) for i in range(6)])
    assert total>5000000
    assert code==413,{'unexpectedStatus':code,'body':oversized,'requestBytes':total}
    report['sections'].append('limits-and-failures')
    filler=state/('.owned-proof-filler-'+owner_token)
    filled=0
    try:
        with filler.open('xb',buffering=0) as stream:
            # A failed bulk allocation can leave a smaller allocatable tail.
            # Consume filesystem blocks as well; ENOSPC on1MiB alone is not
            # proof that the product cannot allocate its readiness probe.
            block=os.statvfs(state).f_frsize
            chunk=1024*1024
            while filled<=INPUT['limits']['server']['stateBytes']:
                try:
                    written=stream.write(b'0'*chunk)
                    if not written: raise RuntimeError('Owned filler write made no progress')
                    filled+=written
                except OSError as error:
                    if error.errno!=errno.ENOSPC: raise
                    if chunk>block:
                        chunk=block
                        continue
                    break
            try: os.fsync(stream.fileno())
            except OSError as error:
                if error.errno!=errno.ENOSPC: raise
        assert filled<=INPUT['limits']['server']['stateBytes']
        space=os.statvfs(state)
        report['storage']['exhaustionFixture']={'filledBytes':filled,'freeBlocks':space.f_bfree,'availableBlocks':space.f_bavail,'blockBytes':space.f_frsize}
        assert space.f_bavail==0,'fixture did not exhaust bounded store: '+json.dumps(report['storage']['exhaustionFixture'])
        full_code,full_state=request(server_url,'/readyz')
        assert full_code==503,full_state
        failed_code,failed_upload,_=multipart(server_url,'/v1/convert/html-to-pdf',html)
        assert failed_code>=400 and 'id' not in failed_upload,failed_upload
        assert request(server_url,'/healthz')[0]==200
    finally:
        # Only the exclusive filler created above, never a product file/marker.
        if filler.exists(): filler.unlink()
    wait(server_url,'/readyz')
    generated=subprocess.run(['docker','exec',PREFIX+'-server','python','-c',
        'from docx import Document;import io,sys;d=Document();d.add_paragraph("After full disk sentinel");b=io.BytesIO();d.save(b);sys.stdout.buffer.write(b.getvalue())'],capture_output=True)
    assert generated.returncode==0
    accepted,later,_=multipart(server_url,'/v1/remediate',generated.stdout,'recovery.docx')
    assert accepted==202,later
    later=terminal(server_url,later);assert later['status']=='done',later
    connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port,timeout=15)
    connection.request('GET','/v1/jobs/'+later['id']+'/result',headers={'X-API-Key':'synthetic-server-key'})
    response=connection.getresponse();office=response.read();assert response.status==200;connection.close()
    parsed=subprocess.run(['docker','exec','-i',PREFIX+'-server','python','-c',
        'from docx import Document;import io,sys;d=Document(io.BytesIO(sys.stdin.buffer.read()));assert "After full disk sentinel" in [p.text for p in d.paragraphs];print("genuine recovered Office")'],input=office,capture_output=True)
    assert parsed.returncode==0
    status,old=request(server_url,'/v1/jobs/'+job['id'],key='synthetic-server-key');assert status==200 and old['status']=='done'
    report['storage'].update({'fullDiskReadiness503':True,'failedUploadNotAccepted':True,'laterGenuineOfficeDownload':True,'olderJobRetained':True,'filledBytes':filled})
    report['sections'].append('bounded-storage')
    # Causally hold an actual external ADAPT response, fill actual admission,
    # then drain the real API through init/wrapper under its20second grace.
    request(adapt_url,'/control/status',{'hold':True},'synthetic-control-only',True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as callers:
        active=callers.submit(request,scanner_url,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key')
        deadline=time.monotonic()+30
        while request(adapt_url,'/control/status',key='synthetic-control-only',control=True)[1]['held']==0:
            assert not active.done() and time.monotonic()<deadline;time.sleep(.02)
        pending=[active]+[callers.submit(request,scanner_url,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key') for _ in range(9)]
        deadline=time.monotonic()+20
        while not any(f.done() for f in pending): assert time.monotonic()<deadline;time.sleep(.02)
        early=[f.result() for f in pending if f.done()]
        assert early and all(code==503 and body.get('ok') is False for code,body in early),early
        metrics.begin_stop(json.loads(cmd('docker','inspect',PREFIX+'-scanner'))[0]['Id'])
        began=time.monotonic();cmd('docker','stop','--time','20',PREFIX+'-scanner');elapsed=time.monotonic()-began
        result=[f.result(timeout=20) for f in pending]
        stopped_info=json.loads(cmd('docker','inspect',PREFIX+'-scanner'))[0]
        metrics.finish_stop(stopped_info)
        stopped=stopped_info['State']
        assert elapsed<15 and stopped['ExitCode']==0,(elapsed,stopped)
        assert all(code==503 and body.get('ok') is False for code,body in result),result
    report['activeShutdown']={'heldExternalResponseReached':True,'admissionOverflow503':True,'all10Callers503':True,'stopSeconds':elapsed,'exitCode':stopped['ExitCode']}

    # Additional causal sandbox/storage/envelope cases must pass before this
    # rehearsal may be described as complete; initial branch runs are tracers.
    required={'actual-service-bootstrap','private-isolation','sandbox-identities','limits-and-failures','bounded-storage','safe-shutdown','public-compose'}
    report['requiredSections']=sorted(required)
except Exception as error:
    report['errors'].append(type(error).__name__+': '+str(error)[:2000])
    raise
finally:
    if observer is not None:
        observer.close();report['sandboxObservations']=observer.records;report['errors'].extend(observer.errors)
        report['vanishedCensusRows']=observer.vanished_rows
    for name in reversed(containers):
        # Only containers created by this invocation; preserve product failure
        # metadata and sanitized logs, then drain through the configured grace.
        try:
            info=json.loads(cmd('docker','inspect',name))[0]
            assert info['Config'].get('Labels',{}).get('org.libretexts.stack-proof-owner')==owner_token,'refusing unowned container cleanup'
            report.setdefault('containers',{})[name]={'state':info['State'],'runtimeUser':info['Config'].get('User',''),'hostConfig':{k:info['HostConfig'].get(k) for k in ['Memory','NanoCpus','PidsLimit','ShmSize','Init','ReadonlyRootfs','NetworkMode']}}
            if name in {PREFIX+'-server',PREFIX+'-scanner',PREFIX+'-bridge'}: metrics.begin_stop(info['Id'])
            started=time.monotonic();cmd('docker','stop',name,check=False)
            report['containers'][name]['stopSeconds']=time.monotonic()-started
            stopped_info=json.loads(cmd('docker','inspect',name))[0]
            if name in {PREFIX+'-server',PREFIX+'-scanner',PREFIX+'-bridge'}: metrics.finish_stop(stopped_info)
            stopped=stopped_info['State']
            report['containers'][name]['stoppedState']=stopped
            logs=subprocess.run(['docker','logs',name],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout
            write_product_log(EVIDENCE/(name+'.log'),logs)
            # Uvicorn re-raises SIGTERM after lifespan shutdown. Signal exit143
            # is distinct from a forced137; unresolved durable markers still fail.
            accepted={0,143} if name==PREFIX+'-server' else {0}
            if name in {PREFIX+'-server',PREFIX+'-scanner',PREFIX+'-bridge'} and stopped['ExitCode'] not in accepted: report['errors'].append('product_shutdown_failed:'+name)
            if name==PREFIX+'-server' and state_mounted:
                markers=list((WORK/'state').glob('*.execution.lock.unresolved/*'))
                if markers: report['errors'].append('unresolved_engine_ownership_after_stop')
            cmd('docker','rm',name,check=False)
        except Exception as error: report['errors'].append('diagnostic_or_cleanup_failed:'+type(error).__name__)
    if host_canary is not None: host_canary.shutdown();host_canary.server_close()
    if deny_rule is not None: cmd('iptables','-D',*deny_rule,check=False)
    if network_created: cmd('docker','network','rm',network,check=False)
    if state_mounted:
        try: cmd('umount',WORK/'state')
        except Exception as error: report['errors'].append('owned_disposable_state_unmount_failed:'+type(error).__name__)
    if not report['errors'] and 'activeShutdown' in report: report['sections'].append('safe-shutdown')
    required={'actual-service-bootstrap','private-isolation','sandbox-identities','limits-and-failures','bounded-storage','safe-shutdown','public-compose'}
    report['verificationComplete']=required<=set(report['sections']) and not report['errors']
    report['resourceMeasurements']=metrics.close();report['errors'].extend(metrics.errors)
    report['verificationComplete']=report['verificationComplete'] and not report['errors']
    (EVIDENCE/'result.json').write_text(json.dumps(report,indent=2)+'\n')

if not report['verificationComplete']: raise SystemExit('Incomplete/failed actual-service proof; release flags remain false')
