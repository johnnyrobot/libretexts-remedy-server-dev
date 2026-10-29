"""Exact-artifact Linux rehearsal. No daemon, host policy or live credentials are changed."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from urllib.parse import urlsplit

ROOT=Path.cwd();EVIDENCE=ROOT/'.stack-proof-evidence'
EVIDENCE.mkdir(exist_ok=True)
INPUT=json.loads((ROOT/'deploy/stack/bundle.json').read_text())
SCANNER=INPUT['scannerImage']; SERVER='remedy-server:stack-candidate'; BRIDGE='remedy-bridge:stack-candidate'
if os.environ.get('GITHUB_ACTIONS')!='true' or platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('This rehearsal requires an isolated authorized GitHub Linux amd64 runner; no local Docker fallback.')
PREFIX='lt196-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
WORK=Path(os.environ['RUNNER_TEMP'])/PREFIX
WORK.mkdir(mode=0o700)  # never reuse/delete somebody else's prior evidence
network=PREFIX+'-private';containers=[];report={'serverSource':os.environ['GITHUB_SHA'],'deploymentReady':False,'productionWritesEnabled':False,'sections':[],'images':{},'profiles':{},'errors':[]}
def cmd(*args,check=True):
    result=subprocess.run(list(map(str,args)),text=True,capture_output=True)
    if check and result.returncode: raise RuntimeError(str(args[:3])+': '+result.stderr[-1600:])
    return result.stdout

def request(base,path,body=None,key=None,control=False):
    url=urlsplit(base); conn=http.client.HTTPConnection(url.hostname,url.port,timeout=950)
    headers={}
    if key: headers['X-Fixture-Control' if control else 'X-API-Key']=key
    raw=json.dumps(body).encode() if body is not None else None
    if raw is not None: headers['Content-Type']='application/json'
    try:
        conn.request('POST' if raw is not None else 'GET',path,body=raw,headers=headers)
        response=conn.getresponse();data=response.read()
        try: value=json.loads(data)
        except ValueError: value={'nonJsonBytes':len(data)}
        return response.status,value
    finally: conn.close()

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
    value=cmd('docker','port',name,f'{number}/tcp').strip().splitlines()[0]
    assert value.startswith('127.0.0.1:'),value
    return 'http://'+value

def write_env(name,values):
    file=WORK/(name+'.env');file.write_text(''.join(f'{k}={v}\n' for k,v in values.items()));file.chmod(0o600)
    return file

def credentials(role,uid,values):
    directory=WORK/role;directory.mkdir(mode=0o700);os.chown(directory,uid,uid)
    for name,value in values.items():
        file=directory/name;file.write_text(value+'\n');os.chown(file,uid,uid);file.chmod(0o400)
    return directory

def start(name,image,env=None,mounts=(),extra=(),command=(),uid=None):
    options=['docker','run','--detach','--name',name,'--init','--cap-drop','ALL','--security-opt','no-new-privileges:true','--read-only']
    if uid is not None: options+=['--user',str(uid)+':'+str(uid)]
    if env: options+=['--env-file',env]
    for source,target,readonly in mounts:
        options+=['--mount',f'type=bind,src={source},dst={target}'+(',readonly' if readonly else '')]
    options+=list(extra)+['--entrypoint',command[0],image,*command[1:]]
    cmd(*options);containers.append(name)
    return name

try:
    cmd('docker','network','create','--internal',network)
    inspection=json.loads(cmd('docker','network','inspect',network))[0]
    assert inspection['Internal'] is True
    report['host']={'kernel':cmd('uname','-srmo').strip(),'docker':cmd('docker','version','--format','{{.Server.Version}}').strip(),'networkInternal':True}
    for name,image in [('server',SERVER),('bridge',BRIDGE),('scanner',SCANNER)]:
        info=json.loads(cmd('docker','image','inspect',image))[0]
        assert info['Architecture']=='amd64' and info['Os']=='linux'
        report['images'][name]={'id':info['Id'],'repoDigests':info['RepoDigests'],'layers':info['RootFS']['Layers'],'user':info['Config']['User']}
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
    state=WORK/'state';state.mkdir();os.chown(state,999,999)
    fixture=WORK/'fixture';fixture.mkdir();os.chown(fixture,999,999)
    cmd('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=dev.libretexts.org','-addext','subjectAltName=DNS:dev.libretexts.org','-keyout',fixture/'key.pem','-out',fixture/'cert.pem')
    os.chown(fixture/'key.pem',999,999);(fixture/'key.pem').chmod(0o400);(fixture/'cert.pem').chmod(0o444)
    public=ROOT/'.github/stack-proof';wrapper=ROOT/'deploy/stack/secret-env.mjs'
    base_mounts=[(wrapper,'/proof/secret-env.mjs',True)]
    server_env=write_env('server',{'APP_ENV':'production','PYTHON_DOTENV_DISABLED':'1','APP_API_KEY_FILE':'/run/secrets/app','OLLAMA_API_KEY_FILE':'/run/secrets/ollama','OLLAMA_BASE_URL':'https://provider.invalid/v1','CORS_ALLOW_ORIGINS':'https://conductor.fixture.invalid','JOB_DIR':'/app/state/jobs','JOB_STORE_PATH':'/app/state/jobs.sqlite3','JOB_BACKUP_DIR':'/app/state/backups','OUTPUT_DIR':'/app/state/output','LOG_DIR':'/app/state/logs','LOG_FORMAT':'json','HOME':'/tmp','TMPDIR':'/tmp','CXONE_INTEGRATION_ENABLED':'false','WORKER_CONCURRENCY':'1','WORKER_MAX_PENDING':'8','JOB_TOTAL_TIMEOUT_SECONDS':'900','RATE_LIMIT_DEFAULT':'10000/minute','RATE_LIMIT_UPLOADS':'10000/minute','MAX_UPLOAD_MB':'4'})
    server_options=['--network',network,'--publish','127.0.0.1::8000','--cpus','4','--memory','4g','--pids-limit','512','--shm-size','256m','--stop-timeout','120','--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--security-opt','seccomp='+str(ROOT/'deploy/chromium-seccomp-amd64.json')]
    server_command=['node','/proof/secret-env.mjs','server','uvicorn','backend.app.main:app','--host','0.0.0.0','--port','8000','--workers','1','--timeout-graceful-shutdown','15']
    start(PREFIX+'-server',SERVER,server_env,[*base_mounts,(server_keys,'/run/secrets',True),(state,'/app/state',False)],server_options,server_command)
    server_url=port(PREFIX+'-server',8000);wait(server_url,'/readyz')
    status,health=request(server_url,'/v1/cxone/health',key='synthetic-server-key')
    assert status==200 and health['enabled'] is False and health['capabilities']['mutate'] is False
    assert not any(name.endswith('-bridge') for name in containers)
    scanner_env=write_env('scanner',{'ADAPT_BASE_URL':'http://127.0.0.1:8081','ADAPT_TOKEN_FILE':'/run/secrets/adapt','SCANNER_API_KEY_FILE':'/run/secrets/api','REMEDY_API_KEY_FILE':'/run/secrets/remedy','SCAN_MODE':'http','RENDER_MODE':'iframe','REMEDY_ENDPOINT':f'http://{PREFIX}-server:8000/v1/validate/html','HOME':'/tmp','TMPDIR':'/tmp','SCANNER_MAX_ACTIVE_JOBS':'1','SCANNER_MAX_QUEUED_JOBS':'8','SCANNER_JOB_TIMEOUT_MS':'900000','SCANNER_MAX_REQUEST_BYTES':'5000000','REMEDY_TIMEOUT_MS':'920000'})
    start(PREFIX+'-scanner',SCANNER,scanner_env,[*base_mounts,(scanner_keys,'/run/secrets',True)],['--network',network,'--publish','127.0.0.1::5176','--publish','127.0.0.1::8081','--cpus','2','--memory','2g','--pids-limit','512','--shm-size','1g','--stop-timeout','20','--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--security-opt','seccomp='+str(ROOT/'deploy/stack/scanner-seccomp-amd64.json')],['node','/proof/secret-env.mjs','scanner','node','dist/server.js'])
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
    start(PREFIX+'-cxone',SERVER,mounts=[(public/'external.py','/proof/external.py',True),(fixture,'/fixtures',True)],extra=['--network',network,'--network-alias','dev.libretexts.org','--publish','127.0.0.1::8082','--cpus','1','--memory','128m','--pids-limit','32','--tmpfs','/tmp:rw,nosuid,nodev,size=16m'],command=['python','/proof/external.py','--kind','cxone'])
    cxone_url=port(PREFIX+'-cxone',8082)
    deadline=time.monotonic()+30
    while True:
        try:
            if request(cxone_url,'/control/status',key='synthetic-control-only',control=True)[0]==200: break
        except OSError: pass
        assert time.monotonic()<deadline;time.sleep(.1)
    # Replace only our exact container, retaining its private job store.
    cmd('docker','stop','--time','120',PREFIX+'-server');cmd('docker','rm',PREFIX+'-server');containers.remove(PREFIX+'-server')
    text=server_env.read_text().replace('CXONE_INTEGRATION_ENABLED=false','CXONE_INTEGRATION_ENABLED=true')+'CXONE_BRIDGE_BASE_URL=http://127.0.0.1:5175\nREMEDY_BRIDGE_SERVICE_KEY_FILE=/run/secrets/service\n'
    server_env.write_text(text)
    start(PREFIX+'-server',SERVER,server_env,[*base_mounts,(server_keys,'/run/secrets',True),(state,'/app/state',False)],server_options,server_command)
    server_url=port(PREFIX+'-server',8000);wait(server_url,'/readyz')
    bridge_env=write_env('bridge',{'NODE_ENV':'production','REMEDY_BRIDGE_PROFILE':'review-only','REMEDY_REVIEWER_REQUIRED':'true','REMEDY_BRIDGE_SERVICE_KEY_FILE':'/run/secrets/service','CXONE_INTEGRATION_ENABLED':'true','SERVER_DOMAIN':'dev.libretexts.org','SERVER_KEY_FILE':'/run/secrets/key','SERVER_SECRET_FILE':'/run/secrets/secret','SERVER_USER_FILE':'/run/secrets/user','REMEDY_WRITE_ALLOWLIST':'^Sandboxes/johnnyphung(?:/|$)','REMEDY_WORK_ACTIVE':'1','REMEDY_WORK_QUEUED':'8','REMEDY_WORK_TIMEOUT_MS':'120000','REMEDY_MAX_REQUEST_BYTES':'5000000','NODE_EXTRA_CA_CERTS':'/fixtures/cert.pem','HOME':'/tmp','NPM_CONFIG_CACHE':'/tmp/npm'})
    start(PREFIX+'-bridge',BRIDGE,bridge_env,[*base_mounts,(bridge_keys,'/run/secrets',True),(fixture/'cert.pem','/fixtures/cert.pem',True)],['--network','container:'+PREFIX+'-server','--cpus','1','--memory','768m','--pids-limit','128','--stop-timeout','30','--tmpfs','/tmp:rw,nosuid,nodev,size=256m'],['node','/proof/secret-env.mjs','bridge','node','--import','tsx','packages/conductor-panel/server/server.ts'],1000)
    bridge_health=wait(server_url,'/v1/cxone/health','synthetic-server-key')
    assert bridge_health['profile']['name']=='review-only' and not bridge_health['capabilities']['mutate']
    status,page=request(server_url,'/v1/cxone/page/scan',{'page_id':'42'},'synthetic-server-key')
    assert status==200 and page['findings'],page
    report['profiles']['bridge-review']={'health':bridge_health,'scan':page}
    report['sections'].append('actual-service-bootstrap')
    # Additional causal sandbox/storage/envelope cases must pass before this
    # rehearsal may be described as complete; initial branch runs are tracers.
    required={'actual-service-bootstrap','private-isolation','sandbox-identities','limits-and-failures','bounded-storage','safe-shutdown'}
    report['verificationComplete']=required<=set(report['sections'])
    if not report['verificationComplete']: raise RuntimeError('Remaining LT196 proof phases are not yet implemented')
except Exception as error:
    report['errors'].append(type(error).__name__+': '+str(error)[:2000])
    raise
finally:
    for name in reversed(containers):
        # Only containers created by this invocation; preserve product failure
        # metadata and sanitized logs, then drain through the configured grace.
        try:
            info=json.loads(cmd('docker','inspect',name))[0]
            report.setdefault('containers',{})[name]={'state':info['State'],'hostConfig':{k:info['HostConfig'].get(k) for k in ['Memory','NanoCpus','PidsLimit','ShmSize','Init','ReadonlyRootfs','NetworkMode']}}
            logs=subprocess.run(['docker','logs',name],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout
            for secret in ['synthetic-server-key','synthetic-provider-key','synthetic-scanner-key','synthetic-adapt-token','synthetic-control-only','synthetic-secret','a1'*32]: logs=logs.replace(secret,'[synthetic credential redacted]')
            (EVIDENCE/(name+'.log')).write_text(logs[-50000:])
            cmd('docker','stop',name,check=False)
            cmd('docker','rm',name,check=False)
        except Exception as error: report['errors'].append('diagnostic_or_cleanup_failed:'+type(error).__name__)
    cmd('docker','network','rm',network,check=False)
    (EVIDENCE/'result.json').write_text(json.dumps(report,indent=2)+'\n')
