"""Separate synthetic TEST signed commissioning; no production write activation.

Linux GitHub runner only. No provider or production host is contacted. This is a
synthetic commissioning proof, never permission to enable production writes.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time
import uuid
from evidence import write_product_log
from verify_imports import runtime_configuration

ROOT=Path.cwd();OUT=ROOT/'.stack-proof-evidence'
if os.environ.get('GITHUB_ACTIONS')!='true' or platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('Isolated authorized GitHub Linux amd64 runner required; no local Docker fallback.')
if os.geteuid()!=0:
    raise SystemExit('Dedicated Linux runner root is required for bounded ext4 and private network policy.')
PREFIX='lt197-signed-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
WORK=Path(os.environ['RUNNER_TEMP'])/PREFIX;WORK.mkdir(mode=0o700)
sensitive_values=set()
OWNER=uuid.uuid4().hex;network=PREFIX+'-private';owned=[];rule=None;rule_installed=False;mounted=[];network_created=False
report={'serverSource':os.environ['GITHUB_SHA'],'deploymentReady':False,'productionWritesEnabled':False,'targets':{},'scenario':'synthetic-test','verificationScope':'retained-signed-test-flows-and-explicit-recovery','operationalAcceptanceComplete':False,'verificationComplete':False}
INPUT=json.loads((ROOT/'deploy/stack/bundle.json').read_text())
consumers={'targets':{}}
image_aliases={}
MONGO='mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'

def run(*args,check=True):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180)
    if check and result.returncode:raise RuntimeError(str(args[:3])+': '+result.stderr[-1500:])
    return result.stdout

def inspect(name):return json.loads(run('docker','inspect',name))[0]
def image_uid(image):
    configuration=json.loads(run('docker','image','inspect',image))[0]
    assert configuration['Config']['User'] not in ('','0','0:0','root','root:root')
    raw=run('docker','run','--rm','--network','none','--read-only','--init','--cap-drop','ALL',
            '--security-opt','no-new-privileges:true','--cpus','0.25','--memory','64m','--pids-limit','32',
            '--shm-size','64m','--stop-timeout','10','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m',
            '--label','org.libretexts.stack-proof-owner='+OWNER,'--entrypoint','node',image,'-e','console.log(process.getuid())')
    uid=int(raw.strip());assert uid>0
    return uid
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

def bounded_state(label,uid,capacity):
    assert re.fullmatch(r'[a-z][a-z0-9_.-]{1,90}',label) and '..' not in label
    assert type(capacity) is int and 32*1024**2<=capacity<=4*1024**3
    directory=WORK/('volume-'+label);directory.mkdir(mode=0o700)
    image=WORK/(label+'.ext4')
    with image.open('xb') as stream:stream.truncate(capacity)
    run('mkfs.ext4','-q','-F','-m','0',image)
    run('mount','-t','ext4','-o','loop,nodev,nosuid,noexec',image,directory)
    mounted.append(directory)
    data=directory/'data';data.mkdir(mode=0o700);os.chown(data,uid,uid)
    fs=os.statvfs(data);actual=fs.f_frsize*fs.f_blocks
    assert actual<=capacity and actual>=capacity*0.75,'bounded state capacity mismatch'
    report.setdefault('storage',[]).append({'label':label,'filesystem':'ext4','imageBytes':capacity,'capacityBytes':actual,'initialFreeBytes':fs.f_frsize*fs.f_bavail,'uid':uid,'mode':'0700'})
    return data

def start(role,image,command,env=None,mounts=(),extra=(),uid=None,limits=(1,'256m',64,'64m',30)):
    name=PREFIX+'-'+role
    image=image_aliases.get(image,image)
    cpu,memory,pids,shm,stop=limits
    explicit_profiles=[str(option).split('=',1)[1] for option in extra if str(option).startswith('seccomp=')]
    assert len(explicit_profiles)<=1
    profile_hash=hashlib.sha256(Path(explicit_profiles[0]).read_bytes()).hexdigest() if explicit_profiles else None
    temporary=INPUT['limits'].get(role,{}).get('tmpBytes',512*1024**2)
    assert type(temporary) is int and temporary>0
    args=['docker','run','--detach','--name',name,'--label','org.libretexts.stack-proof-owner='+OWNER,
        '--init','--cap-drop','ALL','--security-opt','no-new-privileges:true','--read-only',
        '--cpus',str(cpu),'--memory',memory,'--pids-limit',str(pids),'--shm-size',shm,'--stop-timeout',str(stop),
        '--tmpfs',f'/tmp:rw,nosuid,nodev,size={temporary}']
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
        report.setdefault('started',[]).append({'role':role,'imageID':value['Image'],'uid':actual_uid,'capEff':0,'noNewPrivileges':True,'seccomp':2,'cpus':cpu,'memoryBytes':host['Memory'],'pidLimit':pids,'shmBytes':host['ShmSize'],'stopSeconds':stop,'readOnlyRoot':True,'tmpfs':host['Tmpfs'],'init':host['Init'],'seccompProfileSHA256':profile_hash})
    return name

def stop(role):
    name=PREFIX+'-'+role;value=inspect(name)
    assert value['Config']['Labels']['org.libretexts.stack-proof-owner']==OWNER
    usage={}
    if value['State']['Running']:
        for field,path in [('memoryPeakBytes','memory.peak'),('pidPeak','pids.peak')]:
            raw=run('docker','exec',name,'cat','/sys/fs/cgroup/'+path,check=False).strip()
            usage[field]=int(raw) if raw.isdigit() else None
        usage['cpuStat']=run('docker','exec',name,'cat','/sys/fs/cgroup/cpu.stat',check=False).strip()
    started=time.monotonic();run('docker','stop',name)
    elapsed=time.monotonic()-started
    final=inspect(name)
    # Signed product logs can contain request metadata. Publish only the client's
    # bounded structured checkpoints, never raw product bodies/assertions/headers.
    report.setdefault('stopped',[]).append({'role':role,'image':value['Image'],'exitCode':final['State']['ExitCode'],'stopSeconds':round(elapsed,3),'usageIncludingDiagnosticExec':usage})
    expected = {143} if role in {'cxone','adapt','server'} else {0}
    if role=='ui' and report.get('uiFailures'):expected={0,1} # failed test driver, never a product success
    run('docker','rm',name);owned.remove(name)
    assert final['State']['ExitCode'] in expected,(role,final['State'])

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
    assert imports['verificationComplete'] and consumers['verificationComplete'] and imports['serverSource']==os.environ['GITHUB_SHA']
    full_result=json.loads((OUT/'full-result.json').read_text())
    assert full_result['verificationComplete'] and full_result['serverSource']==os.environ['GITHUB_SHA'], 'normal production-hold proof must finish first'
    assert consumers['indexSHA256']==INPUT['conductorCandidateIndexSHA256']
    candidate=json.loads((ROOT/'.stack-artifacts/candidate.json').read_text())
    assert candidate['serverSource']==os.environ['GITHUB_SHA'] and candidate['productionWritesEnabled'] is False and candidate['deploymentReady'] is False
    for profile in ('deploy/stack/scanner-seccomp-amd64.json','deploy/stack/renderer-seccomp-amd64.json'):
        assert hashlib.sha256((ROOT/profile).read_bytes()).hexdigest()==candidate['configurationSha256'][profile],'reviewed seccomp bytes changed'
    build_inputs_path=ROOT/'.stack-artifacts/build-inputs.json'
    assert hashlib.sha256(build_inputs_path.read_bytes()).hexdigest()==candidate['sha256']['build-inputs.json']
    build_inputs=json.loads(build_inputs_path.read_text())
    assert hashlib.sha256((ROOT/'deploy/chromium-seccomp-amd64.json').read_bytes()).hexdigest()==build_inputs['server']['input_sha256']['deploy/chromium-seccomp-amd64.json']
    assert set(consumers['targets'])=={entry['target'] for entry in json.loads((ROOT/'deploy/stack/conductor-candidates.json').read_text())['candidates']} and len(consumers['targets'])==2
    assert 'VERSION_ID=\"24.04\"' in Path('/etc/os-release').read_text(), 'matching Ubuntu24 NSS tools required'
    report['conductorIndexSHA256']=consumers['indexSHA256']
    for role in ('server','bridge','renderer'):
        value=json.loads(run('docker','image','inspect','remedy-'+role+':stack-candidate'))[0]
        assert value['Id']==imports['images'][role]['loadedDockerImageID']
        image_aliases['remedy-'+role+':stack-candidate']=imports['images'][role]['loadedDockerImageID']
        actual=runtime_configuration(value['Config'])
        assert hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()==imports['images'][role]['runtimeConfigurationSHA256']
    scanner_image=json.loads(run('docker','image','inspect',INPUT['scannerImage']))[0]
    assert scanner_image['Architecture']=='amd64' and scanner_image['Os']=='linux'
    assert INPUT['scannerImage'] in scanner_image['RepoDigests']
    image_aliases[INPUT['scannerImage']]=scanner_image['Id']
    for pin in consumers['targets'].values():
        loaded=json.loads(run('docker','image','inspect',pin['loadedDockerImageID']))[0]
        assert loaded['RootFS']['Layers']==pin['filesystemDiffIDs']
        assert hashlib.sha256(json.dumps(runtime_configuration(loaded['Config']),sort_keys=True,separators=(',',':')).encode()).hexdigest()==pin['runtimeConfigurationSHA256']
    run('docker','pull',MONGO)
    mongo_image=json.loads(run('docker','image','inspect',MONGO))[0]
    assert mongo_image['Architecture']=='amd64' and mongo_image['Os']=='linux' and MONGO in mongo_image['RepoDigests']
    image_aliases[MONGO]=mongo_image['Id']
    run('docker','network','create','--internal','--subnet','198.51.100.0/24','--label','org.libretexts.stack-proof-owner='+OWNER,network);network_created=True
    info=json.loads(run('docker','network','inspect',network))[0];assert info['Internal']
    interface=info['Options'].get('com.docker.network.bridge.name','br-'+info['Id'][:12])
    rule=['INPUT','-i',interface,'-m','conntrack','!','--ctstate','ESTABLISHED,RELATED','-j','DROP'];run('iptables','-I',*rule);rule_installed=True
    fixture=WORK/'fixture';fixture.mkdir();fixture.chmod(0o755)
    authority=WORK/'private-fixture-authority';authority.mkdir(mode=0o700)
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=LT197 isolated synthetic authority',
        '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign','-keyout',authority/'ca.key','-out',fixture/'ca.pem')
    (authority/'ca.key').chmod(0o400)
    run('openssl','req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=dev.libretexts.org','-keyout',fixture/'key.pem','-out',authority/'server.csr')
    extensions=authority/'server.ext';extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:dev.libretexts.org,DNS:remedy-server,DNS:conductor.invalid,DNS:remedy-gateway\n')
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
    renderer_uid=image_uid(imports['images']['renderer']['loadedDockerImageID'])
    report['rendererUID']=renderer_uid
    for p in [nss,*nss.iterdir()]:os.chown(p,renderer_uid,renderer_uid);p.chmod(0o700 if p.is_dir() else 0o600)
    state=bounded_state('server',999,INPUT['limits']['server']['stateBytes'])
    server_keys=private('server-keys',999,{'app':'synthetic-server-key','ollama':'synthetic-provider-key','service':'a1'*32})
    bridge_keys=private('bridge-keys',1000,{'key':'synthetic-key','secret':'synthetic-secret','user':'synthetic-user','service':'a1'*32,'renderer':'synthetic-renderer-token'})
    renderer_keys=private('renderer-keys',renderer_uid,{'token':'synthetic-renderer-token'})
    scanner_uid=image_uid(image_aliases[INPUT['scannerImage']])
    scanner_keys=private('scanner-keys',scanner_uid,{'api':'synthetic-scanner-key','adapt':'synthetic-adapt-token','remedy':'synthetic-server-key'})
    source=ROOT/'.github/stack-proof';loader=ROOT/'deploy/stack/secret-env.mjs';net=['--network',network]
    start('cxone','remedy-server:stack-candidate',['python','/proof/external.py','--kind','cxone','--synthetic-development-mutations'],mounts=[(source/'external.py','/proof/external.py',True),(fixture,'/fixtures',True)],extra=[*net,'--ip','198.51.100.10','--network-alias','dev.libretexts.org'],uid=999)
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
    start('renderer','remedy-renderer:stack-candidate',['sh','/proof/nss_home.sh','node','/proof/secret-env.mjs','renderer','node','server.mjs'],envfile('renderer',{'RENDER_SCANNER_TOKEN_FILE':'/run/secrets/token','RENDER_ALLOWED_HOSTS':'dev.libretexts.org','HOME':'/tmp/renderer-home'}),[(loader,'/proof/secret-env.mjs',True),(renderer_keys,'/run/secrets',True),(ROOT/'deploy/stack/browser-home.sh','/proof/nss_home.sh',True),(nss,'/run/certificates/nss-seed',True),(source/'renderer_diagnose.mjs','/proof/renderer_diagnose.mjs',True)],extra=[*net,'--network-alias','remedy-renderer','--security-opt','seccomp='+str(ROOT/'deploy/stack/renderer-seccomp-amd64.json')],limits=(1.5,'2g',256,'1g',30))
    wait('renderer',5180)
    report['NSSSetup']['runtimePackage']=run('docker','exec',PREFIX+'-renderer','dpkg-query','-W','-f=${Version}','libnss3').strip()
    report['NSSSetup']['runtimeOS']=run('docker','exec',PREFIX+'-renderer','cat','/etc/os-release')
    assert 'VERSION_ID="24.04"' in report['NSSSetup']['runtimeOS'],'matching Ubuntu24 renderer NSS required'
    denied_chroot=subprocess.run(['docker','exec',PREFIX+'-renderer','chroot','/','/bin/true'],capture_output=True,text=True,timeout=10)
    assert denied_chroot.returncode!=0 and 'Operation not permitted' in denied_chroot.stderr,'initial namespace chroot must remain kernel-denied'
    report['rendererInitialNamespaceChrootDenied']=True
    bridge_base={'NODE_ENV':'production','CONDUCTOR_API_HOST':'127.0.0.1','REMEDY_REVIEWER_REQUIRED':'true','REMEDY_BRIDGE_SERVICE_KEY_FILE':'/run/secrets/service','CXONE_INTEGRATION_ENABLED':'true','SERVER_DOMAIN':'dev.libretexts.org','SERVER_KEY_FILE':'/run/secrets/key','SERVER_SECRET_FILE':'/run/secrets/secret','SERVER_USER_FILE':'/run/secrets/user','REMEDY_WRITE_ALLOWLIST':'^Sandboxes/johnnyphung(?:/|$)','REMEDY_MAX_REQUEST_BYTES':'5000000','REMEDY_WORK_ACTIVE':'1','REMEDY_WORK_QUEUED':'8','REMEDY_WORK_TIMEOUT_MS':'120000','HOME':'/tmp','NODE_EXTRA_CA_CERTS':'/fixtures/ca.pem','RENDER_SCANNER_URL':'http://remedy-renderer:5180','RENDER_SCANNER_TOKEN_FILE':'/run/secrets/renderer'}
    # TLS relay is a bounded TRANSPORT fixture. Its upstream is the actual Server;
    # Conductor still authenticates normally and Server still validates its key.
    gate_tls=WORK/'gate-tls';gate_tls.mkdir(mode=0o755)
    for name in ('key.pem','cert.pem','ca.pem'):
        destination=gate_tls/name;destination.write_bytes((fixture/name).read_bytes())
        os.chown(destination,1000,1000);destination.chmod(0o400 if name=='key.pem' else 0o444)
    start('gate',consumers['targets'][next(iter(consumers['targets']))]['loadedDockerImageID'],
          ['node','/proof/response_gate.mjs'],envfile('gate',{'GITHUB_ACTIONS':'true'}),
          [(source/'response_gate.mjs','/proof/response_gate.mjs',True),(gate_tls,'/fixtures',True)],
          extra=[*net,'--network-alias','remedy-gateway'],uid=1000,limits=(1,'256m',64,'64m',30))

    def gate_control(path='/control/status',post=False):
        args=['docker','exec',PREFIX+'-server','curl','--cacert','/fixtures/ca.pem','-fsS',
              '-H','X-Fixture-Control: synthetic-control-only']
        if post:args+=['-X','POST','--data','{}']
        value=json.loads(run(*args,'https://remedy-gateway:8444'+path))
        assert isinstance(value.get('forwarded'),int)
        return value

    deadline=time.monotonic()+30
    while True:
        try:gate_control();break
        except Exception:
            assert time.monotonic()<deadline,'verified TLS response gate unavailable';time.sleep(.2)

    def fixture_state(path='/control/status',body=None):
        code,value=request('cxone',8082,path,body,key='synthetic-control-only',control=True)
        assert code==200 and isinstance(value.get('writes'),int)
        return value

    for target,pin in consumers['targets'].items():
        phases=[];report['targets'][target]={'artifact':pin,'phases':phases,'complete':False}
        fixture_state('/control/reset-source',{})
        baseline_writes=fixture_state()['writes']
        mongo_data=bounded_state('mongo-'+target,999,INPUT['limits']['mongo']['stateBytes'])
        mongo_bootstrap=private('mongo-bootstrap-'+target,999,{'credentials.json':json.dumps({'admin':uuid.uuid4().hex,'application':uuid.uuid4().hex})})
        start('mongo',MONGO,['mongod','--auth','--bind_ip_all','--wiredTigerCacheSizeGB','0.25'],
              mounts=[(mongo_data,'/data/db',False),(mongo_bootstrap,'/run/bootstrap',True),(source/'mongo_bootstrap.js','/proof/mongo_bootstrap.js',True)],
              extra=[*net,'--network-alias','mongo','--tmpfs','/data/configdb:rw,nosuid,nodev,noexec,size=16m'],uid=999,limits=(1,'1g',128,'64m',60))
        deadline=time.monotonic()+60
        while run('docker','exec',PREFIX+'-mongo','mongosh','--quiet','--eval','db.adminCommand({ping:1}).ok',check=False).strip()!='1':
            assert time.monotonic()<deadline;time.sleep(.2)
        run('docker','exec',PREFIX+'-mongo','mongosh','--quiet','--norc','/proof/mongo_bootstrap.js')
        mongo_credentials=json.loads((mongo_bootstrap/'credentials.json').read_text());sensitive_values.update(mongo_credentials.values())
        config={'editor':uuid.uuid4().hex,'auditor':uuid.uuid4().hex,'outsider':uuid.uuid4().hex,'admin':uuid.uuid4().hex,
                'password':uuid.uuid4().hex,'projectID':'ci00000001','sectionID':'158000000000000000000001',
                'pageURL':'https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic'}
        sensitive_values.add(config['password']);app_fixture=private('app-'+target,1000,{'app.json':json.dumps(config)})
        conductor_keys=private('conductor-keys-'+target,1000,{'session':uuid.uuid4().hex,
            'mongo':'mongodb://conductor:'+mongo_credentials['application']+'@mongo:27017/conductor_synthetic?authSource=conductor_synthetic',
            'remedy':'synthetic-server-key','openai':'synthetic-not-real','stripe':'sk_test_synthetic_not_real','mailgun':'synthetic-not-real'})
        signer=WORK/('signer-'+target);signer.mkdir(mode=0o700);run('node',source/'signing_fixture.mjs',signer)
        signing=json.loads((signer/'metadata.json').read_text())
        for item in [signer,*signer.iterdir()]:os.chown(item,1000,1000)
        ledger=bounded_state('ledger-'+target,1000,INPUT['limits']['bridge']['stateBytes'])
        fence=bounded_state('fence-'+target,1000,INPUT['limits']['fence']['stateBytes'])
        bridge_image=imports['images']['bridge']['loadedDockerImageID']

        def helper(arguments,decision_directory=None):
            # Every offline helper is a bounded, nonroot process using the exact
            # maintained image. The writer is stopped before any resolution.
            assert PREFIX+'-bridge' not in owned and PREFIX+'-conductor' not in owned
            name=PREFIX+'-offline'
            args=['docker','run','--name',name,'--label','org.libretexts.stack-proof-owner='+OWNER,
                  '--network','none','--user','1000:1000','--read-only','--init','--cap-drop','ALL',
                  '--security-opt','no-new-privileges:true','--cpus','1','--memory','256m','--pids-limit','32',
                  '--shm-size','64m','--stop-timeout','30','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m',
                  '--mount',f'type=bind,src={ledger},dst=/ledger','--mount',f'type=bind,src={fence},dst=/fence']
            if decision_directory:args+=['--mount',f'type=bind,src={decision_directory},dst=/decision,readonly']
            args+=['--entrypoint','python3',bridge_image,'packages/conductor-panel/server/ledger-helper.py',
                   '--directory','/ledger','--fence','/fence/fence.json','--epoch',signing['trust_epoch'],*arguments]
            # Keep ownership registered even if the one-shot helper fails.
            owned.append(name)
            result=subprocess.run(args,capture_output=True,text=True,timeout=60)
            value=inspect(name);assert value['Config']['Labels']['org.libretexts.stack-proof-owner']==OWNER
            assert not value['State']['Running'] and value['Image']==bridge_image
            report.setdefault('offlineHelpers',[]).append({'target':target,'imageID':value['Image'],'exitCode':value['State']['ExitCode'],
                'networkDisabled':value['HostConfig']['NetworkMode']=='none','readOnlyRoot':value['HostConfig']['ReadonlyRootfs'],
                'nonroot':value['Config']['User']=='1000:1000','capDrop':value['HostConfig']['CapDrop']})
            assert result.returncode==0,'actual offline helper refused operation'
            run('docker','rm',name);owned.remove(name)
            return result.stdout

        assert json.loads(helper(['--initialize']))['ready'] is True
        app_env={'NODE_ENV':'production','APP_ENV':'candidate_ci','ORG_ID':'libretexts','PORT':'5000','TRUST_PROXY_HOPS':'0',
                 'PRODUCTIONURLS':'conductor.invalid,https://conductor.invalid,https://conductor.invalid:8443',
                 'SECRETKEY_FILE':'/run/secrets/session','MONGOOSEURI_FILE':'/run/secrets/mongo','REMEDY_API_KEY_FILE':'/run/secrets/remedy',
                 'OPENAI_API_KEY_FILE':'/run/secrets/openai','STRIPE_SECRET_KEY_FILE':'/run/secrets/stripe','MAILGUN_API_KEY_FILE':'/run/secrets/mailgun',
                 'MAILGUN_DOMAIN':'fixture.example.invalid','NEW_RELIC_ENABLED':'false','NODE_EXTRA_CA_CERTS':'/fixtures/ca.pem',
                 'REMEDY_ENABLED':'true','REMEDY_ORG_ID':'libretexts','REMEDY_API_BASE_URL':'https://remedy-gateway:8444'}
        signer_env={'REMEDY_REVIEWER_SIGNING_KEY_FILE':'/run/signing/private.pem','REMEDY_REVIEWER_KEY_ID':signing['kid'],
                    'REMEDY_REVIEWER_ISSUER':signing['issuer'],'REMEDY_REVIEWER_AUDIENCE':signing['audience'],
                    'REMEDY_REVIEWER_KEY_ENABLED':'true','REMEDY_REVIEWER_KEY_NOT_BEFORE':'0','REMEDY_REVIEWER_KEY_NOT_AFTER':'4102444800'}

        def start_bridge(history=False,missing_audit=False):
            settings={**bridge_base,'NODE_ENV':'production' if history else 'test',
                      'REMEDY_BRIDGE_PROFILE':'review-only' if history else 'full-write',
                      'REMEDY_REVIEWER_TRUST_EPOCH':signing['trust_epoch'],'REMEDY_CLAIM_DB':'/ledger/claims.sqlite3',
                      'REMEDY_CLAIM_FENCE_DIR':'/fence','REMEDY_SNAPSHOT_DIR':'/ledger/snapshots',
                      'REMEDY_AUDIT_LOG':'/run/synthetic-readonly-audit/audit.log' if missing_audit else '/ledger/audit.log'}
            mounts=[(loader,'/proof/secret-env.mjs',True),(bridge_keys,'/run/secrets',True),(fixture/'ca.pem','/fixtures/ca.pem',True),
                    (ledger,'/ledger',False),(fence,'/fence',history)]
            if history:settings['REMEDY_OPERATION_STATUS_ISSUER']=signing['issuer']
            else:
                settings['REMEDY_REVIEWER_KEYRING_FILE']='/run/reviewer-keyring.json'
                mounts.append((signer/'test.json','/run/reviewer-keyring.json',True))
            start('bridge',bridge_image,['node','/proof/secret-env.mjs','bridge','node','--import','tsx','packages/conductor-panel/server/server.ts'],
                  envfile('bridge',settings),mounts,extra=['--network','container:'+PREFIX+'-server'],uid=1000,limits=(1,'768m',128,'64m',30))
            deadline=time.monotonic()+60
            while run('docker','exec',PREFIX+'-server','curl','-sS','-o','/dev/null','-w','%{http_code}',
                      '-H','X-Remedy-Service-Key: '+'a1'*32,'http://127.0.0.1:5175/readyz',check=False).strip()!='200':
                assert time.monotonic()<deadline,'actual synthetic or historical Bridge readiness';time.sleep(.2)
            absent=json.loads(run('docker','exec',PREFIX+'-bridge','node','-e',
                "const fs=require('fs');console.log(JSON.stringify(['/run/signing/private.pem','/run/reviewer-keyring.json'].map(p=>fs.existsSync(p))))"))
            assert absent==[False,not history]

        def start_conductor(signed=False,epoch=None):
            settings={**app_env,**(signer_env if signed else {})}
            if epoch is not None:settings['REMEDY_REVIEWER_TRUST_EPOCH']=epoch
            mounts=[(loader,'/proof/secret-env.mjs',True),(conductor_keys,'/run/secrets',True),(app_fixture,'/fixture',True),
                    (fixture/'ca.pem','/fixtures/ca.pem',True),(source/'dev_client.mjs','/proof/dev_client.mjs',True)]
            if signed:mounts.append((signer/'private.pem','/run/signing/private.pem',True))
            start('conductor',pin['loadedDockerImageID'],['node','/proof/secret-env.mjs','conductor','node','dist/server.js'],
                  envfile('conductor',settings),mounts,extra=[*net,'--network-alias','conductor'],uid=1000,limits=(2,'1536m',256,'64m',30))
            wait('conductor',5000,'/health')
            if not signed:
                settings_absent=run('docker','exec',PREFIX+'-conductor','node','-e',
                    "const fs=require('fs');console.log(JSON.stringify({keyPresent:fs.existsSync('/run/signing/private.pem'),signerEnv:Object.keys(process.env).filter(k=>k.startsWith('REMEDY_REVIEWER_')&&k!=='REMEDY_REVIEWER_TRUST_EPOCH')}))")
                checked=json.loads(settings_absent);assert checked=={'keyPresent':False,'signerEnv':[]}

        def phase(name,local_id=None):
            signer_observation=json.loads(run('docker','exec',PREFIX+'-conductor','node','-e',
                "const fs=require('fs');console.log(JSON.stringify({keyPresent:fs.existsSync('/run/signing/private.pem'),signerEnv:Object.keys(process.env).filter(k=>k.startsWith('REMEDY_REVIEWER_')&&k!=='REMEDY_REVIEWER_TRUST_EPOCH')}))"))
            signer_present=signer_observation['keyPresent'] or bool(signer_observation['signerEnv'])
            if not signer_present:assert signer_observation=={'keyPresent':False,'signerEnv':[]}
            command=['docker','exec',PREFIX+'-conductor','node','/proof/secret-env.mjs','conductor','node','/proof/dev_client.mjs',name,
                     'http://198.51.100.10:8082',*([local_id] if local_id else [])]
            result=subprocess.run(command,capture_output=True,text=True,timeout=900)
            log_name='synthetic-'+target+'-'+str(len(phases))+'-'+name+'.log'
            write_product_log(OUT/log_name,result.stdout+result.stderr,sensitive_values)
            assert result.returncode==0,'actual synthetic client phase failed: '+target+'/'+name
            observations=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            assert observations and all(value.get('passed') is True and value.get('phase')==name for value in observations)
            phases.append({'phase':name,'signerPresent':signer_present,'checkpoints':observations,'external':{key:fixture_state()[key] for key in ('writes','mutations','revision','source_sha256')},'gate':gate_control()})
            return observations

        def pending_id(observations):
            return next(value['localOperationID'] for value in observations if value['checkpoint']=='actual_pending_unknown_or_lost_terminal_reply')

        start_bridge();start_conductor(signed=True)
        phase('seed');phase('known');phase('race')
        # A real audit-path failure records audit_recorded:false; it is retained
        # through lost reply, restart and terminal recovery without fabrication.
        stop('conductor');stop('bridge');start_bridge(missing_audit=True);start_conductor(signed=True)
        gate_before=gate_control();gate_control('/control/drop-next-apply-reply',post=True)
        terminal_observations=phase('terminal-lost-reply');terminal_id=pending_id(terminal_observations)
        assert next(value for value in terminal_observations if value['checkpoint']=='actual_pending_unknown_or_lost_terminal_reply')['auditRecorded'] is False
        assert gate_control()['dropped']==gate_before['dropped']+1
        stop('conductor');stop('bridge')
        start_bridge(history=True);start_conductor()
        phase('status',terminal_id);phase('recover-refused',terminal_id)
        stop('conductor');start_conductor(epoch=signing['trust_epoch']+'-wrong')
        phase('recover-refused',terminal_id)
        stop('conductor');start_conductor(epoch=signing['trust_epoch'])
        phase('recover',terminal_id);phase('status',terminal_id)
        stop('conductor');stop('bridge')
        # The next fake-source reset is a manual fixture edit, never an owned
        # evidence rewrite. The real scan obtains fresh canonical bytes.
        fixture_state('/control/reset-source',{})
        start_bridge();start_conductor(signed=True)
        unknown_id=pending_id(phase('unknown'));phase('recover-refused',unknown_id)
        stop('conductor');stop('bridge')
        assert fixture_state()['lost_remote_response'] is False
        settlement=fixture_state()
        raw_report=helper(['--readonly-report']);ledger_report=json.loads(raw_report)
        unknowns=[value for value in ledger_report['operations'] if value['outcome']=='unknown_write' and value['requires_reconciliation']]
        assert len(unknowns)==1 and ledger_report['trust_epoch']==signing['trust_epoch']
        unknown=unknowns[0]
        for operation in ledger_report['operations']:sensitive_values.add(operation['jti'])
        # This is a synthetic operator decision backed by the actual complete
        # stopped-ledger report and the fixture's single committed lost reply.
        decision={'operation_id':unknown['operation_id'],'target':unknown['target'],'trust_epoch':ledger_report['trust_epoch'],
                  'expected_seq':ledger_report['durability_seq'],'expected_state':'terminal','expected_outcome':'unknown_write',
                  'expected_updated_at':unknown['updated_at'],'report_sha256':hashlib.sha256(raw_report.encode()).hexdigest(),
                  'operator':'lt197-synthetic-operator','reason':'Isolated fake external fixture committed exactly one reviewed mutation and closed its response; all original writers are stopped.',
                  'external_settlement_acknowledged':True,'writer_drained':True}
        decision_dir=private('offline-decision-'+target,1000,{'report.json':raw_report.rstrip('\n'),'decision.json':json.dumps(decision)})
        # private() adds a single newline: retain exactly those report bytes in
        # the digest checked by the real helper, without reconstructing JSON.
        assert (decision_dir/'report.json').read_bytes()==raw_report.encode()
        resolved=json.loads(helper(['--offline-resolve','/decision/decision.json','--report-file','/decision/report.json'],decision_dir))
        assert resolved['outcome']=='unknown_write' and resolved['reconciliation']=='resolved' and not resolved['requires_reconciliation']
        after_report=json.loads(helper(['--readonly-report']))
        preserved=next(value for value in after_report['operations'] if value['operation_id']==unknown['operation_id'])
        for key in ('issuer','jti','binding_sha256','subject','created_at','outcome','reason','audit_recorded'):
            assert preserved[key]==unknown[key],'offline resolution rewrote original operation'
        assert after_report['durability_seq']==ledger_report['durability_seq']+1
        assert fixture_state()['writes']==settlement['writes'],'offline resolution attempted a remote write'
        report['targets'][target]['offlineResolution']={'operationID':resolved['operation_id'],'originalOutcome':'unknown_write',
            'reconciliation':'resolved','exclusiveStoppedWriter':True,'originalFieldsPreserved':True,'remoteWrites':0,
            'actualHelperImageID':bridge_image,'currentIndependentFencePreserved':True}
        start_bridge(history=True);start_conductor(epoch=signing['trust_epoch'])
        phase('status',unknown_id);phase('recover',unknown_id);phase('status',unknown_id)
        stop('conductor');stop('bridge');stop('mongo')
        report['targets'][target]['externalWrites']=fixture_state()['writes']-baseline_writes
        report['targets'][target]['complete']=True
    report['verificationComplete']=len(report['targets'])==2 and all(value['complete'] for value in report['targets'].values())
    if report['verificationComplete']:report['verifiedCriteria']=0
except Exception as error:
    report['error']=safe_error(error)
finally:
    if PREFIX+'-cxone' in owned:
        try:
            observed=fixture_state()
            report['syntheticExternalWrites']=observed['writes'];report['syntheticExternalAttempts']=observed['mutations']
        except Exception as error:report['counterError']=safe_error(error);report['verificationComplete']=False
    for name in list(reversed(owned)):
        try:stop(name.removeprefix(PREFIX+'-'))
        except Exception as error:report.setdefault('shutdownErrors',[]).append(safe_error(error)[:600])
    if rule_installed:run('iptables','-D',*rule,check=False)
    if network_created:
        try:
            info=json.loads(run('docker','network','inspect',network))[0]
            assert info['Labels']['org.libretexts.stack-proof-owner']==OWNER
            run('docker','network','rm',network)
        except Exception as error:report.setdefault('shutdownErrors',[]).append(safe_error(error)[:600])
    for directory in reversed(mounted):
        try:run('umount',directory)
        except Exception as error:report.setdefault('shutdownErrors',[]).append(safe_error(error)[:600])
    if report.get('shutdownErrors') or report.get('error'):report['verificationComplete']=False
    (OUT/'synthetic-signed-result.json').write_text(json.dumps(report,indent=2)+'\n')
if not report['verificationComplete']:raise SystemExit('Synthetic test signed proof incomplete; all release flags remain false')
