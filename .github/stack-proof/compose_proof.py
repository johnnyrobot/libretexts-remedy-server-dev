"""Run the public Compose files unchanged with isolated synthetic providers."""
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import time
from urllib.parse import urlsplit


def verify(root, work, evidence, prefix, images, state, fixture, keys):
    package=work/'compose-package';package.mkdir(mode=0o700)
    shutil.copytree(root/'deploy/stack',package,dirs_exist_ok=True)
    project=prefix+'-compose'
    network=project+'_remedy'
    rule=None
    receipt={'configurationHashes':{},'profiles':{},'productionWritesEnabled':False}
    for name in ('docker-compose.yml','compose.scanner.yml','compose.bridge.yml','secret-env.mjs'):
        before=(root/'deploy/stack'/name).read_bytes()
        assert (package/name).read_bytes()==before
        receipt['configurationHashes'][name]=hashlib.sha256(before).hexdigest()
    secret_root=work/'compose-secrets';secret_root.mkdir(mode=0o700)
    for role,source in keys.items():
        target=secret_root/role;shutil.copytree(source,target)
        owner=source.stat()
        os.chown(target,owner.st_uid,owner.st_gid);target.chmod(0o700)
        for path in target.iterdir(): os.chown(path,owner.st_uid,owner.st_gid);path.chmod(0o400)
    for role in ('remedy-server','adapt-scanner','remedy-bridge'):
        text=(package/'env'/f'{role}.env.example').read_text()
        text=text.replace('https://ollama.com/v1','https://provider.invalid/v1')
        text=text.replace('https://REPLACE_WITH_REVIEWED_CONDUCTOR_ORIGIN','https://conductor.fixture.invalid')
        text=text.replace('https://REPLACE_WITH_AUTHORIZED_ADAPT_HOST','http://127.0.0.1:8081')
        if role=='remedy-bridge': text+='\nNODE_EXTRA_CA_CERTS=/fixtures/cert.pem\n'
        (package/'env'/f'{role}.env').write_text(text)
    env=os.environ.copy()
    env.update(REMEDY_SERVER_IMAGE=images['server']['id'],REMEDY_BRIDGE_IMAGE=images['bridge']['id'],
        REMEDY_SERVER_SECCOMP_FILE=str(root/'deploy/chromium-seccomp-amd64.json'),
        REMEDY_SCANNER_SECCOMP_FILE=str(root/'deploy/stack/scanner-seccomp-amd64.json'),
        REMEDY_STATE_ROOT=str(state),REMEDY_SECRET_ROOT=str(secret_root),REMEDY_BRIDGE_PROFILE='review-only')
    # Only external product dependencies are fixtures. The owned services use
    # the public package commands, controls, mounts and exact imported images.
    common={'image':images['server']['id'],'init':True,'read_only':True,'cap_drop':['ALL'],
        'security_opt':['no-new-privileges:true'],'cpus':1,'mem_limit':'128m','pids_limit':32,
        'tmpfs':['/tmp:rw,nosuid,nodev,size=16m'],'dns':['127.0.0.1']}
    def fixture_health(port):
        return {'test':['CMD','python','-c',
            'from urllib.request import Request,urlopen;assert urlopen(Request("http://127.0.0.1:'+str(port)+'/control/status",headers={"X-Fixture-Control":"synthetic-control-only"}),timeout=1).status==200'],
            'interval':'2s','timeout':'2s','retries':20,'start_period':'5s'}
    override={'services':{
        'external-adapt':{**common,'entrypoint':['python','/proof/external.py','--kind','adapt'],
            'volumes':[str(root/'.github/stack-proof/external.py')+':/proof/external.py:ro'],
            'network_mode':'service:adapt-scanner','depends_on':{'adapt-scanner':{'condition':'service_started'}},
            'healthcheck':fixture_health(8081)},
        'external-cxone':{**common,'entrypoint':['python','/proof/external.py','--kind','cxone'],
            'volumes':[str(root/'.github/stack-proof/external.py')+':/proof/external.py:ro',str(fixture)+':/fixtures:ro'],
            'networks':{'remedy':{'aliases':['dev.libretexts.org']}},'healthcheck':fixture_health(8082)},
        'remedy-bridge':{'volumes':[str(fixture/'cert.pem')+':/fixtures/cert.pem:ro']}}}
    # The real Scanner permits plaintext ADAPT only on loopback. Keep that
    # guard intact; the synthetic external adapter shares its namespace.
    del override['services']['external-adapt']['dns']

    def run(*args,check=True,combined=False):
        value=subprocess.run(list(map(str,args)),env=env,text=True,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if combined else subprocess.PIPE,timeout=180)
        if check and value.returncode: raise RuntimeError('Compose rehearsal command failed: '+str(args[:3])+': '+(value.stdout if combined else value.stderr)[-1200:])
        return value.stdout

    def compose(bridge,*args):
        files=['-f',str(package/'docker-compose.yml'),'-f',str(package/'compose.scanner.yml')]
        if bridge: files+=['-f',str(package/'compose.bridge.yml')]
        # Base needs only ADAPT; omit Bridge and CXone entirely in that profile.
        fixture_override=json.loads(json.dumps(override))
        if not bridge:
            del fixture_override['services']['remedy-bridge'];del fixture_override['services']['external-cxone']
        selected=package/('external-review.json' if bridge else 'external-engine.json')
        selected.write_text(json.dumps(fixture_override))
        return run('docker','compose','--project-name',project,*files,'-f',selected,*args)

    def inspect(service):
        value=json.loads(run('docker','inspect',compose(True,'ps','--all','--quiet',service).strip()))[0]
        assert value['Config']['Labels']['com.docker.compose.project']==project
        return value

    def request(service,port,path,body=None,key=None,control=False):
        value=inspect(service)
        ip=value['NetworkSettings']['Networks'][network]['IPAddress']
        conn=http.client.HTTPConnection(ip,port,timeout=180)
        try:
            headers={'X-Fixture-Control' if control else 'X-API-Key':key} if key else {}
            if body is not None: headers['Content-Type']='application/json'
            conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally: conn.close()

    try:
        compose(False,'create')
        info=json.loads(run('docker','network','inspect',network))[0]
        assert info['Internal'] is True and info['Labels']['com.docker.compose.project']==project
        interface=info['Options'].get('com.docker.network.bridge.name','br-'+info['Id'][:12])
        rule=['INPUT','-i',interface,'-m','conntrack','!','--ctstate','ESTABLISHED,RELATED','-j','DROP']
        run('iptables','-I',*rule)
        compose(False,'up','--detach','--wait','--wait-timeout','90')
        assert not compose(True,'ps','--all','--quiet','remedy-bridge').strip()
        code,health=request('remedy-server',8000,'/v1/cxone/health',key='synthetic-server-key')
        assert code==200 and health['enabled'] is False and health['capabilities']['mutate'] is False
        deadline=time.monotonic()+30
        while True:
            try:
                if request('adapt-scanner',8081,'/control/status',key='synthetic-control-only',control=True)[0]==200: break
            except OSError: pass
            assert time.monotonic()<deadline
            time.sleep(.1)
        code,scan=request('adapt-scanner',5176,'/v1/adapt/scan',{'mode':'question','id':101},'synthetic-scanner-key')
        assert code==200 and scan['results'][0]['findings'] and scan['results'][0]['capturedBytes']>0,scan
        receipt['profiles']['engine-scanner']={'bridgeAbsent':True,'actualScan':True}
        compose(True,'up','--detach','--wait','--wait-timeout','90')
        deadline=time.monotonic()+30
        while True:
            code,health=request('remedy-server',8000,'/v1/cxone/health',key='synthetic-server-key')
            if code==200: break
            assert time.monotonic()<deadline,health
            time.sleep(.1)
        assert health['profile']['name']=='review-only' and health['capabilities']['mutate'] is False,health
        bridge=inspect('remedy-bridge');server=inspect('remedy-server')
        assert bridge['HostConfig']['NetworkMode']=='container:'+server['Id'] and not bridge['HostConfig'].get('PortBindings')
        code,preview=request('remedy-server',8000,'/v1/cxone/page/preview-fix',{'page_id':'42','review_images':True},'synthetic-server-key')
        assert code==200 and preview['review_binding']['action']=='cxone.apply',preview
        vectors=json.loads((root/'tests/unit/contracts_v1/lt-1-reviewer-wire-v1-vectors.json').read_text())
        code,denied=request('remedy-server',8000,'/v1/cxone/page/apply-fix',{'page_id':'42',
            'preview_hash':preview['preview_hash'],'preview_token':preview['preview_token'],
            'reviewer_assertion':vectors['positive'][0]['compact']},'synthetic-server-key')
        assert code==503 and denied['error']=='review_only_profile' and denied['outcome']=='not_attempted',denied
        code,status=request('external-cxone',8082,'/control/status',key='synthetic-control-only',control=True)
        assert code==200 and status['mutations']==0
        for role in ('remedy-server','adapt-scanner','remedy-bridge'):
            value=inspect(role);host=value['HostConfig']
            assert host['ReadonlyRootfs'] and host['Init'] and host['CapDrop']==['ALL'] and 'no-new-privileges:true' in host['SecurityOpt']
            assert not host.get('PortBindings')
            expected={'remedy-server':(4294967296,4000000000,512,268435456,120),
                'adapt-scanner':(2147483648,2000000000,512,1073741824,20),
                'remedy-bridge':(805306368,1000000000,128,67108864,30)}[role]
            assert (host['Memory'],host['NanoCpus'],host['PidsLimit'],host['ShmSize'],value['Config']['StopTimeout'])==expected
            receipt.setdefault('containers',{})[role]={'id':value['Id'],'image':value['Image'],'stopSeconds':value['Config']['StopTimeout'],'hostConfig':{k:host[k] for k in ('Memory','NanoCpus','PidsLimit','ShmSize','NetworkMode')}}
        receipt['profiles']['bridge-review']={'namespaceShared':True,'actualPreview':True,'mutationDenied':True,'externalMutations':0}
    finally:
        try:
            ids=compose(True,'ps','--all','--quiet').split()
            for identifier in ids:
                value=json.loads(run('docker','inspect',identifier))[0]
                assert value['Config']['Labels']['com.docker.compose.project']==project
                service=value['Config']['Labels']['com.docker.compose.service']
                receipt.setdefault('startupDiagnostics',{})[service]={
                    'state':value['State'],'entrypoint':value['Config']['Entrypoint'],'command':value['Config']['Cmd'],
                    'healthcheck':value['Config'].get('Healthcheck')}
                if service=='adapt-scanner' and value['State']['Running']:
                    receipt['startupDiagnostics'][service]['actualHealthProbe']=run('docker','exec',identifier,'node','-e',
                        'fetch("http://127.0.0.1:5176/healthz").then(async r=>console.log(JSON.stringify({status:r.status,body:await r.text()}))).catch(e=>{console.error(e.cause?.code??e.name);process.exitCode=1})',check=False,combined=True)[-2000:]
            compose(True,'stop')
            for identifier in ids:
                value=json.loads(run('docker','inspect',identifier))[0]
                service=value['Config']['Labels']['com.docker.compose.service']
                logs=run('docker','logs',identifier,check=False,combined=True)
                for secret in ('synthetic-server-key','synthetic-provider-key','synthetic-scanner-key',
                    'synthetic-adapt-token','synthetic-control-only','synthetic-secret','a1'*32):
                    logs=logs.replace(secret,'[synthetic credential redacted]')
                (evidence/('compose-'+service+'.log')).write_text(logs[-80000:])
                receipt.setdefault('shutdown',{})[service]=value['State']['ExitCode']
                assert value['State']['ExitCode'] in {0,143},value['State']
            compose(True,'down')
        finally:
            if rule is not None: run('iptables','-D',*rule,check=False)
            (evidence/'compose-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    receipt['verificationComplete']=True
    (evidence/'compose-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt
