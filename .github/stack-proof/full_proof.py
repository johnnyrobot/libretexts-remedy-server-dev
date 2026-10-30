"""Actual immutable compiled Conductor + current owned services, external fixtures only.

Linux GitHub runner only. No provider or production host is contacted. This is a
synthetic commissioning proof, never permission to enable production writes.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import uuid
from evidence import write_product_log, collect_browser_evidence

ROOT=Path.cwd();OUT=ROOT/'.stack-proof-evidence'
if os.environ.get('GITHUB_ACTIONS')!='true' or platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('Isolated authorized GitHub Linux amd64 runner required; no local Docker fallback.')
PREFIX='lt197-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
WORK=Path(os.environ['RUNNER_TEMP'])/PREFIX;WORK.mkdir(mode=0o700)
sensitive_values=set()
OWNER=uuid.uuid4().hex;network=PREFIX+'-private';owned=[];rule=None;mounted=False;network_created=False
report={'serverSource':os.environ['GITHUB_SHA'],'deploymentReady':False,'productionWritesEnabled':False,'targets':{},'verificationScope':'compiled-auth-scan-rendered-preview-and-production-hold','operationalAcceptanceComplete':False,'verificationComplete':False}
INPUT=json.loads((ROOT/'deploy/stack/bundle.json').read_text())
consumers={'targets':{}}
MONGO='mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'

def run(*args,check=True):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180)
    if check and result.returncode:raise RuntimeError(str(args[:3])+': '+result.stderr[-1500:])
    return result.stdout

def inspect(name):return json.loads(run('docker','inspect',name))[0]
def safe_error(error):
    value=type(error).__name__+': '+str(error)
    for secret in sorted(sensitive_values,key=len,reverse=True):value=value.replace(secret,'[synthetic credential redacted]')
    return value[:1800]
def product_log(name):
    value=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=30)
    return value.stdout+value.stderr
def envfile(name,values):
    p=WORK/(name+'.env');p.write_text(''.join(f'{k}={v}\n' for k,v in values.items()));p.chmod(0o600);return p

def private(name,uid,values):
    sensitive_values.update(values.values())
    p=WORK/name;p.mkdir(mode=0o700);os.chown(p,uid,uid)
    for field,value in values.items():
        f=p/field;f.write_text(value+'\n');f.chmod(0o400);os.chown(f,uid,uid)
    return p

def start(role,image,command,env=None,mounts=(),extra=(),uid=None,limits=(1,'256m',64,'64m',30)):
    name=PREFIX+'-'+role
    cpu,memory,pids,shm,stop=limits
    args=['docker','run','--detach','--name',name,'--label','org.libretexts.stack-proof-owner='+OWNER,
        '--init','--cap-drop','ALL','--security-opt','no-new-privileges:true','--read-only',
        '--cpus',str(cpu),'--memory',memory,'--pids-limit',str(pids),'--shm-size',shm,'--stop-timeout',str(stop),
        '--tmpfs','/tmp:rw,nosuid,nodev,size=512m']
    if uid is not None:args+=['--user',str(uid)+':'+str(uid)]
    if env:args+=['--env-file',str(env)]
    for source,target,ro in mounts:args+=['--mount',f'type=bind,src={source},dst={target}'+(',readonly' if ro else '')]
    args+=list(extra)+['--entrypoint',command[0],image,*command[1:]]
    run(*args)
    owned.append(name)
    value=inspect(name)
    host=value['HostConfig']
    assert not host.get('PortBindings')
    assert host['ReadonlyRootfs'] and host['Init'] and host['CapDrop']==['ALL']
    assert any(option in {'no-new-privileges','no-new-privileges:true'} for option in host['SecurityOpt'])
    def bytes_for(text):return int(text[:-1])*({'g':1024**3,'m':1024**2}[text[-1]])
    assert host['NanoCpus']==int(float(cpu)*10**9) and host['Memory']==bytes_for(memory)
    assert host['PidsLimit']==pids and host['ShmSize']==bytes_for(shm) and value['Config']['StopTimeout']==stop
    image_config=json.loads(run('docker','image','inspect',image))[0]
    assert image_config['Architecture']=='amd64' and image_config['Os']=='linux' and value['Image']==image_config['Id']
    # PID1 is the retained init process in the product's actual nonroot context.
    if role!='ui':
        status=dict(line.split(':',1) for line in run('docker','exec',name,'cat','/proc/1/status').splitlines() if ':' in line)
        actual_uid=int(status['Uid'].split()[1]);assert actual_uid>0
        assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
        report.setdefault('started',[]).append({'role':role,'imageID':value['Image'],'uid':actual_uid,'capEff':0,'noNewPrivileges':True,'seccomp':2,'cpus':cpu,'memoryBytes':host['Memory'],'pidLimit':pids,'shmBytes':host['ShmSize'],'stopSeconds':stop,'readOnlyRoot':True})
    return name

def stop(role):
    name=PREFIX+'-'+role;value=inspect(name)
    assert value['Config']['Labels']['org.libretexts.stack-proof-owner']==OWNER
    run('docker','stop',name)
    final=inspect(name)
    write_product_log(OUT/(role+'-'+str(len(report.get('stopped',[])))+'.log'),product_log(name),sensitive_values)
    report.setdefault('stopped',[]).append({'role':role,'image':value['Image'],'exitCode':final['State']['ExitCode']})
    expected = {143} if role in {'cxone','adapt','server'} else {0}
    assert final['State']['ExitCode'] in expected,(role,final['State'])
    run('docker','rm',name);owned.remove(name)

def address(role):return inspect(PREFIX+'-'+role)['NetworkSettings']['Networks'][network]['IPAddress']
def request(role,port,path,body=None,key=None,control=False):
    conn=http.client.HTTPConnection(address(role),port,timeout=150)
    headers={'Content-Type':'application/json'}
    if key:headers['X-Fixture-Control' if control else 'X-API-Key']=key
    try:
        conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();raw=response.read()
        try:value=json.loads(raw)
        except ValueError:value={'nonJsonBytes':len(raw)}
        return response.status,value
    finally:conn.close()

def wait(role,port,path='/healthz',key=None,control=False):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        try:
            if request(role,port,path,key=key,control=control)[0]==200:return
        except (OSError,http.client.HTTPException):pass
        assert inspect(PREFIX+'-'+role)['State']['Running'],role+' exited before readiness'
        time.sleep(.2)
    raise RuntimeError('Readiness deadline: '+role)

try:
    imports=json.loads((OUT/'imports.json').read_text());consumers=json.loads((OUT/'conductor-imports.json').read_text())
    assert imports['verificationComplete'] and consumers['verificationComplete']
    for role in ('server','bridge','renderer'):
        value=json.loads(run('docker','image','inspect','remedy-'+role+':stack-candidate'))[0]
        assert value['Id']==imports['images'][role]['loadedDockerImageID']
    run('docker','pull',MONGO)
    run('docker','network','create','--internal','--subnet','198.51.100.0/24','--label','org.libretexts.stack-proof-owner='+OWNER,network);network_created=True
    info=json.loads(run('docker','network','inspect',network))[0];assert info['Internal']
    interface=info['Options'].get('com.docker.network.bridge.name','br-'+info['Id'][:12])
    rule=['INPUT','-i',interface,'-m','conntrack','!','--ctstate','ESTABLISHED,RELATED','-j','DROP'];run('iptables','-I',*rule)
    fixture=WORK/'fixture';fixture.mkdir();fixture.chmod(0o755)
    authority=WORK/'private-fixture-authority';authority.mkdir(mode=0o700)
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=LT197 isolated synthetic authority',
        '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign','-keyout',authority/'ca.key','-out',fixture/'ca.pem')
    (authority/'ca.key').chmod(0o400)
    run('openssl','req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=dev.libretexts.org','-keyout',fixture/'key.pem','-out',authority/'server.csr')
    extensions=authority/'server.ext';extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:dev.libretexts.org,DNS:remedy-server,DNS:conductor.invalid\n')
    run('openssl','x509','-req','-in',authority/'server.csr','-CA',fixture/'ca.pem','-CAkey',authority/'ca.key','-CAcreateserial','-days','1','-sha256','-extfile',extensions,'-out',fixture/'cert.pem')
    run('openssl','verify','-CAfile',fixture/'ca.pem',fixture/'cert.pem')
    (fixture/'ca.pem').chmod(0o444)
    for name in ('ca.pem','cert.pem'):(OUT/('public-fixture-'+name)).write_bytes((fixture/name).read_bytes())
    tls_fixture=WORK/'frontend-tls';tls_fixture.mkdir(mode=0o755)
    for name in ('key.pem','cert.pem'):
        (tls_fixture/name).write_bytes((fixture/name).read_bytes());os.chown(tls_fixture/name,1000,1000);(tls_fixture/name).chmod(0o400 if name=='key.pem' else 0o444)
    (fixture/'key.pem').chmod(0o400);os.chown(fixture/'key.pem',999,999);(fixture/'cert.pem').chmod(0o444)
    # Chromium's NSS trust store uses the local fixture CA. Certificate and
    # hostname verification stay enabled; no browser or Node TLS bypass.
    report['NSSSetup']={'toolSHA256':hashlib.sha256(Path('/usr/bin/certutil').read_bytes()).hexdigest(),'hostToolPackage':run('dpkg-query','-W','-f=${Version}','libnss3-tools').strip(),'hostOS':Path('/etc/os-release').read_text(),'temporaryHome':'/tmp/renderer-home','temporaryBytes':512*1024*1024}
    nss=WORK/'nssdb';nss.mkdir();run('certutil','-N','--empty-password','-d','sql:'+str(nss))
    run('certutil','-A','-d','sql:'+str(nss),'-n','isolated-cxone-fixture','-t','C,,','-i',fixture/'ca.pem')
    renderer_uid=int(run('docker','run','--rm','--network','none','--entrypoint','node',imports['images']['renderer']['loadedDockerImageID'],'-e','console.log(process.getuid())').strip());assert renderer_uid!=0
    report['rendererUID']=renderer_uid
    for p in [nss,*nss.iterdir()]:os.chown(p,renderer_uid,renderer_uid);p.chmod(0o700 if p.is_dir() else 0o600)
    state=WORK/'state';state.mkdir();state_image=WORK/'state.ext4'
    with state_image.open('xb') as f:f.truncate(INPUT['limits']['server']['stateBytes'])
    run('mkfs.ext4','-q','-F','-m','0',state_image);run('mount','-t','ext4','-o','loop,nodev,nosuid,noexec',state_image,state);mounted=True
    os.chown(state,999,999);state.chmod(0o700)
    server_keys=private('server-keys',999,{'app':'synthetic-server-key','ollama':'synthetic-provider-key','service':'a1'*32})
    bridge_keys=private('bridge-keys',1000,{'key':'synthetic-key','secret':'synthetic-secret','user':'synthetic-user','service':'a1'*32})
    renderer_keys=private('renderer-keys',renderer_uid,{'token':'synthetic-renderer-token'})
    scanner_uid=int(run('docker','run','--rm','--network','none','--entrypoint','node',INPUT['scannerImage'],'-e','console.log(process.getuid())').strip());assert scanner_uid!=0
    scanner_keys=private('scanner-keys',scanner_uid,{'api':'synthetic-scanner-key','adapt':'synthetic-adapt-token','remedy':'synthetic-server-key'})
    source=ROOT/'.github/stack-proof';loader=ROOT/'deploy/stack/secret-env.mjs';net=['--network',network]
    start('cxone','remedy-server:stack-candidate',['python','/proof/external.py','--kind','cxone'],mounts=[(source/'external.py','/proof/external.py',True),(fixture,'/fixtures',True)],extra=[*net,'--ip','198.51.100.10','--network-alias','dev.libretexts.org'],uid=999)
    wait('cxone',8082,'/control/status','synthetic-control-only',True)
    server_env={'APP_ENV':'production','PYTHON_DOTENV_DISABLED':'1','APP_API_KEY_FILE':'/run/secrets/app','OLLAMA_API_KEY_FILE':'/run/secrets/ollama','OLLAMA_BASE_URL':'https://provider.invalid/v1','CORS_ALLOW_ORIGINS':'https://conductor.invalid','JOB_DIR':'/app/state/jobs','JOB_STORE_PATH':'/app/state/jobs.sqlite3','JOB_BACKUP_DIR':'/app/state/backups','OUTPUT_DIR':'/app/state/output','LOG_DIR':'/app/state/logs','HOME':'/tmp','TMPDIR':'/tmp','CXONE_INTEGRATION_ENABLED':'true','CXONE_BRIDGE_BASE_URL':'http://127.0.0.1:5175','REMEDY_BRIDGE_SERVICE_KEY_FILE':'/run/secrets/service','WORKER_CONCURRENCY':'1','WORKER_MAX_PENDING':'8','JOB_TOTAL_TIMEOUT_SECONDS':'900','MAX_UPLOAD_MB':'4','MAX_REQUEST_BYTES':'5000000','RATE_LIMIT_DEFAULT':'10000/minute','RATE_LIMIT_UPLOADS':'10000/minute'}
    start('server','remedy-server:stack-candidate',['node','/proof/secret-env.mjs','server','uvicorn','backend.app.main:app','--host','0.0.0.0','--port','8000','--workers','1','--timeout-graceful-shutdown','15','--ssl-certfile','/fixtures/cert.pem','--ssl-keyfile','/fixtures/key.pem'],envfile('server',server_env),[(loader,'/proof/secret-env.mjs',True),(server_keys,'/run/secrets',True),(state,'/app/state',False),(fixture,'/fixtures',True)],extra=[*net,'--network-alias','remedy-server','--security-opt','seccomp='+str(ROOT/'deploy/chromium-seccomp-amd64.json')],limits=(4,'4g',512,'256m',120))
    deadline=time.monotonic()+60
    while run('docker','exec',PREFIX+'-server','curl','--cacert','/fixtures/ca.pem','-fsS','https://remedy-server:8000/readyz',check=False).strip()=='':
        assert time.monotonic()<deadline,'actual TLS Server readiness';time.sleep(.2)
    # Exact Scanner calls the actual TLS Server, keeping certificate checks on.
    scanner_env={'ADAPT_BASE_URL':'http://127.0.0.1:8081','ADAPT_TOKEN_FILE':'/run/secrets/adapt','SCANNER_API_KEY_FILE':'/run/secrets/api','REMEDY_API_KEY_FILE':'/run/secrets/remedy','SCAN_MODE':'http','RENDER_MODE':'iframe','REMEDY_ENDPOINT':'https://remedy-server:8000/v1/validate/html','NODE_EXTRA_CA_CERTS':'/fixtures/ca.pem','HOME':'/tmp','TMPDIR':'/tmp','SCANNER_MAX_ACTIVE_JOBS':'1','SCANNER_MAX_QUEUED_JOBS':'8','SCANNER_JOB_TIMEOUT_MS':'900000','SCANNER_MAX_REQUEST_BYTES':'5000000','REMEDY_TIMEOUT_MS':'920000'}
    start('scanner',INPUT['scannerImage'],['node','/proof/secret-env.mjs','scanner','node','dist/server.js'],envfile('scanner',scanner_env),[(loader,'/proof/secret-env.mjs',True),(scanner_keys,'/run/secrets',True),(fixture/'ca.pem','/fixtures/ca.pem',True)],extra=[*net,'--security-opt','seccomp='+str(ROOT/'deploy/stack/scanner-seccomp-amd64.json')],limits=(2,'2g',512,'1g',20))
    wait('scanner',5176)
    start('adapt','remedy-server:stack-candidate',['python','/proof/external.py','--kind','adapt'],mounts=[(source/'external.py','/proof/external.py',True)],extra=['--network','container:'+PREFIX+'-scanner'],uid=999)
    wait('scanner',8081,'/control/status','synthetic-control-only',True)
    code,scan=request('scanner',5176,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key');assert code==200 and scan['results'][0]['findings'] and scan['results'][0]['capturedBytes']>0,scan
    report['actualScannerAgainstTLSserver']=True
    start('renderer','remedy-renderer:stack-candidate',['sh','/proof/nss_home.sh','node','/proof/secret-env.mjs','renderer','node','server.mjs'],envfile('renderer',{'RENDER_SCANNER_TOKEN_FILE':'/run/secrets/token','RENDER_ALLOWED_HOSTS':'dev.libretexts.org','HOME':'/tmp/renderer-home'}),[(loader,'/proof/secret-env.mjs',True),(renderer_keys,'/run/secrets',True),(source/'nss_home.sh','/proof/nss_home.sh',True),(nss,'/fixture-nss',True),(source/'renderer_diagnose.mjs','/proof/renderer_diagnose.mjs',True)],extra=[*net,'--network-alias','remedy-renderer','--security-opt','seccomp='+str(ROOT/'deploy/stack/renderer-seccomp-amd64.json')],limits=(1.5,'2g',256,'1g',30))
    wait('renderer',5180)
    report['NSSSetup']['runtimePackage']=run('docker','exec',PREFIX+'-renderer','dpkg-query','-W','-f=${Version}','libnss3').strip()
    denied_chroot=subprocess.run(['docker','exec',PREFIX+'-renderer','chroot','/','/bin/true'],capture_output=True,text=True,timeout=10)
    assert denied_chroot.returncode!=0 and 'Operation not permitted' in denied_chroot.stderr,'initial namespace chroot must remain kernel-denied'
    report['rendererInitialNamespaceChrootDenied']=True
    bridge_base={'NODE_ENV':'production','CONDUCTOR_API_HOST':'127.0.0.1','REMEDY_REVIEWER_REQUIRED':'true','REMEDY_BRIDGE_SERVICE_KEY_FILE':'/run/secrets/service','CXONE_INTEGRATION_ENABLED':'true','SERVER_DOMAIN':'dev.libretexts.org','SERVER_KEY_FILE':'/run/secrets/key','SERVER_SECRET_FILE':'/run/secrets/secret','SERVER_USER_FILE':'/run/secrets/user','REMEDY_WRITE_ALLOWLIST':'^Sandboxes/johnnyphung(?:/|$)','REMEDY_MAX_REQUEST_BYTES':'5000000','REMEDY_WORK_ACTIVE':'1','REMEDY_WORK_QUEUED':'8','REMEDY_WORK_TIMEOUT_MS':'120000','HOME':'/tmp','NODE_EXTRA_CA_CERTS':'/fixtures/ca.pem','RENDER_SCANNER_URL':'http://remedy-renderer:5180','RENDER_SCANNER_TOKEN':'synthetic-renderer-token'}
    for target,pin in consumers['targets'].items():
        phases=[];report['targets'][target]={'artifact':pin,'phases':phases,'complete':False}
        mongo_data=WORK/('mongo-'+target);mongo_data.mkdir();os.chown(mongo_data,999,999)
        mongo_bootstrap=private('mongo-bootstrap-'+target,999,{'credentials.json':json.dumps({'admin':uuid.uuid4().hex,'application':uuid.uuid4().hex})})
        start('mongo',MONGO,['mongod','--auth','--bind_ip_all'],mounts=[(mongo_data,'/data/db',False),(mongo_bootstrap,'/run/bootstrap',True),(source/'mongo_bootstrap.js','/proof/mongo_bootstrap.js',True)],extra=[*net,'--network-alias','mongo'],uid=999,limits=(1,'1g',128,'64m',60))
        deadline=time.monotonic()+60
        while run('docker','exec',PREFIX+'-mongo','mongosh','--quiet','--eval','db.adminCommand({ping:1}).ok',check=False).strip()!='1':
            assert time.monotonic()<deadline;time.sleep(.2)
        run('docker','exec',PREFIX+'-mongo','mongosh','--quiet','--norc','/proof/mongo_bootstrap.js')
        mongo_credentials=json.loads((mongo_bootstrap/'credentials.json').read_text())
        sensitive_values.update(mongo_credentials.values())
        config={'editor':uuid.uuid4().hex,'auditor':uuid.uuid4().hex,'outsider':uuid.uuid4().hex,'password':uuid.uuid4().hex,'projectID':'ci00000001','sectionID':'158000000000000000000001','pageURL':'https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic'}
        sensitive_values.add(config['password'])
        app_fixture=private('app-'+target,1000,{'app.json':json.dumps(config)})
        browser_fixture=private('browser-config-'+target,renderer_uid,{'app.json':json.dumps(config)})
        conductor_keys=private('conductor-keys-'+target,1000,{'session':uuid.uuid4().hex,'mongo':'mongodb://conductor:'+mongo_credentials['application']+'@mongo:27017/conductor_synthetic?authSource=conductor_synthetic','remedy':'synthetic-server-key','openai':'synthetic-not-real','stripe':'sk_test_synthetic_not_real','mailgun':'synthetic-not-real'})
        signer=WORK/('signer-'+target);signer.mkdir(mode=0o700)
        run('node',source/'signing_fixture.mjs',signer)
        signing=json.loads((signer/'metadata.json').read_text())
        for item in [signer,*signer.iterdir()]:os.chown(item,1000,1000)
        ledger=WORK/('ledger-'+target);ledger.mkdir(mode=0o700);os.chown(ledger,1000,1000)
        fence=WORK/('independent-fence-'+target);fence.mkdir(mode=0o700);os.chown(fence,1000,1000)
        run('docker','run','--rm','--network','none','--user','1000:1000','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--mount',f'type=bind,src={ledger},dst=/ledger','--mount',f'type=bind,src={fence},dst=/fence',imports['images']['bridge']['loadedDockerImageID'],'python3','packages/conductor-panel/server/ledger-helper.py','--directory','/ledger','--fence','/fence/fence.json','--epoch',signing['trust_epoch'],'--initialize')
        app_env={'NODE_ENV':'production','APP_ENV':'candidate_ci','ORG_ID':'libretexts','PORT':'5000','TRUST_PROXY_HOPS':'0','PRODUCTIONURLS':'conductor.invalid,https://conductor.invalid,https://conductor.invalid:8443','SECRETKEY_FILE':'/run/secrets/session','MONGOOSEURI_FILE':'/run/secrets/mongo','REMEDY_API_KEY_FILE':'/run/secrets/remedy','OPENAI_API_KEY_FILE':'/run/secrets/openai','STRIPE_SECRET_KEY_FILE':'/run/secrets/stripe','MAILGUN_API_KEY_FILE':'/run/secrets/mailgun','MAILGUN_DOMAIN':'fixture.example.invalid','NEW_RELIC_ENABLED':'false','NODE_EXTRA_CA_CERTS':'/fixtures/ca.pem','REMEDY_ENABLED':'true','REMEDY_ORG_ID':'libretexts','REMEDY_API_BASE_URL':'https://remedy-server:8000'}
        for phase in ('review','production-held'):
            writer_env={} if phase=='review' else {'REMEDY_REVIEWER_KEYRING_FILE':'/run/reviewer-keyring.json','REMEDY_REVIEWER_TRUST_EPOCH':signing['trust_epoch'],'REMEDY_CLAIM_DB':'/ledger/claims.sqlite3','REMEDY_CLAIM_FENCE_DIR':'/fence','REMEDY_SNAPSHOT_DIR':'/ledger/snapshots','REMEDY_AUDIT_LOG':'/ledger/audit.log'}
            signer_env={} if phase=='review' else {'REMEDY_REVIEWER_SIGNING_KEY_FILE':'/run/signing/private.pem','REMEDY_REVIEWER_KEY_ID':signing['kid'],'REMEDY_REVIEWER_ISSUER':signing['issuer'],'REMEDY_REVIEWER_AUDIENCE':signing['audience'],'REMEDY_REVIEWER_KEY_ENABLED':'true','REMEDY_REVIEWER_KEY_NOT_BEFORE':'0','REMEDY_REVIEWER_KEY_NOT_AFTER':'4102444800'}
            writer_mounts=[] if phase=='review' else [(signer/'production.json','/run/reviewer-keyring.json',True),(ledger,'/ledger',False),(fence,'/fence',False)]
            start('bridge','remedy-bridge:stack-candidate',['node','/proof/secret-env.mjs','bridge','node','--import','tsx','packages/conductor-panel/server/server.ts'],envfile('bridge',{**bridge_base,**writer_env,'REMEDY_BRIDGE_PROFILE':'review-only' if phase=='review' else 'full-write'}),[(loader,'/proof/secret-env.mjs',True),(bridge_keys,'/run/secrets',True),(fixture/'ca.pem','/fixtures/ca.pem',True),*writer_mounts],extra=['--network','container:'+PREFIX+'-server'],uid=1000,limits=(1,'768m',128,'64m',30))
            deadline=time.monotonic()+60
            private_paths=run('docker','exec',PREFIX+'-bridge','node','-e',"const fs=require('fs');console.log(JSON.stringify(['/run/signing/private.pem','/signer/private.pem'].map(p=>fs.existsSync(p))))")
            assert json.loads(private_paths)==[False,False],'Bridge must never receive reviewer private signing material'
            report['bridgePrivateSigningKeyAbsent']=True
            expected='200' if phase=='review' else '503'
            while run('docker','exec',PREFIX+'-server','curl','-sS','-o','/dev/null','-w','%{http_code}','-H','X-Remedy-Service-Key: '+'a1'*32,'http://127.0.0.1:5175/readyz',check=False).strip()!=expected:
                assert time.monotonic()<deadline,'actual Bridge readiness';time.sleep(.2)
            start('conductor',pin['loadedDockerImageID'],['node','/proof/secret-env.mjs','conductor','node','dist/server.js'],envfile('conductor',{**app_env,**signer_env}),[(loader,'/proof/secret-env.mjs',True),(conductor_keys,'/run/secrets',True),(app_fixture,'/fixture',True),(fixture/'ca.pem','/fixtures/ca.pem',True),(source/'conductor_probe.mjs','/proof/conductor_probe.mjs',True),*([(signer/'private.pem','/run/signing/private.pem',True)] if phase!='review' else [])],extra=[*net,'--network-alias','conductor'],uid=1000,limits=(2,'1536m',256,'64m',30))
            wait('conductor',5000,'/health')
            probe=subprocess.run(['docker','exec',PREFIX+'-conductor','node','/proof/secret-env.mjs','conductor','node','/proof/conductor_probe.mjs',phase],capture_output=True,text=True,timeout=180)
            write_product_log(OUT/('conductor-'+target+'-'+phase+'.log'),probe.stdout+probe.stderr,sensitive_values)
            if probe.returncode:raise RuntimeError('actual compiled consumer '+target+'/'+phase+': '+probe.stderr[-1500:])
            raw=probe.stdout
            observation=json.loads(raw.strip().splitlines()[-1]);assert observation['passed'];phases.append(observation)
            if phase=='review':
                browser_evidence=WORK/('browser-'+target);browser_evidence.mkdir();os.chown(browser_evidence,renderer_uid,renderer_uid)
                start('tls',pin['loadedDockerImageID'],['node','/proof/tls_proxy.mjs'],mounts=[(source/'tls_proxy.mjs','/proof/tls_proxy.mjs',True),(tls_fixture,'/fixtures',True)],extra=[*net,'--network-alias','conductor.invalid'],uid=1000)
                tls_deadline=time.monotonic()+20
                while run('docker','exec',PREFIX+'-server','curl','--cacert','/fixtures/ca.pem','-sS','-o','/dev/null','-w','%{http_code}','https://conductor.invalid:8443/health',check=False).strip()!='200':
                    assert time.monotonic()<tls_deadline,'verified private TLS frontend readiness';time.sleep(.2)
                start('ui',imports['images']['renderer']['loadedDockerImageID'],['sh','/proof/nss_home.sh','node','/proof/conductor_browser.mjs'],envfile('ui',{'HOME':'/tmp/renderer-home'}),[(source/'conductor_browser.mjs','/proof/conductor_browser.mjs',True),(browser_fixture,'/fixture',True),(source/'nss_home.sh','/proof/nss_home.sh',True),(nss,'/fixture-nss',True),(browser_evidence,'/browser-evidence',False)],extra=[*net,'--security-opt','seccomp='+str(ROOT/'deploy/stack/renderer-seccomp-amd64.json')],uid=renderer_uid,limits=(1.5,'2g',256,'1g',30))
                assert run('docker','wait',PREFIX+'-ui').strip()=='0','actual UI browser failed; see sanitized ui log'
                browser_result=json.loads(run('docker','logs',PREFIX+'-ui').strip().splitlines()[-1]);assert browser_result['passed']
                phases.append(browser_result)
                (OUT/('browser-'+target+'.png')).write_bytes((browser_evidence/'synthetic-review.png').read_bytes())
                stop('ui');stop('tls')
            stop('conductor');stop('bridge')
        stop('mongo')
        report['targets'][target]['complete']=True
    code,status=request('cxone',8082,'/control/status',key='synthetic-control-only',control=True)
    assert code==200 and status['mutations']==0,status
    report['externalMutations']=0;report['verificationComplete']=len(report['targets'])==2
except Exception as error:
    report['error']=safe_error(error)
    collect_browser_evidence(WORK,OUT,consumers['targets'],sensitive_values)
    if PREFIX+'-renderer' in owned and inspect(PREFIX+'-renderer')['State']['Running']:
        try:
            process=subprocess.run(['docker','exec','--env','DEBUG=pw:browser',PREFIX+'-renderer','node','/proof/renderer_diagnose.mjs'],capture_output=True,text=True,timeout=180)
            write_product_log(OUT/'renderer-browser-process.log',process.stderr,sensitive_values)
            process.check_returncode();diagnostic=process.stdout
            write_product_log(OUT/'renderer-diagnostic.json',diagnostic,sensitive_values)
        except Exception as diagnostic_error:report['rendererDiagnosticError']=safe_error(diagnostic_error)
    raise RuntimeError(report['error']) from None
finally:
    for name in list(reversed(owned)):
        try:stop(name.removeprefix(PREFIX+'-'))
        except Exception as error:report.setdefault('shutdownErrors',[]).append(safe_error(error)[:600])
    if rule:run('iptables','-D',*rule,check=False)
    if network_created:run('docker','network','rm',network,check=False)
    if mounted:run('umount',WORK/'state')
    if report.get('shutdownErrors'):report['verificationComplete']=False
    (OUT/'full-result.json').write_text(json.dumps(report,indent=2)+'\n')
if not report['verificationComplete']:raise SystemExit('Full stack proof incomplete; release flags remain false')
