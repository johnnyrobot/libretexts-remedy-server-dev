"""Fail-closed candidate input/host checks; never provision keys, mounts or policy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import importlib
import signal
import sqlite3
import stat
import subprocess
import sys
import uuid

def _unique_json(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate_json_field')
        result[key]=value
    return result

def read_json(raw):
    return json.loads(raw,object_pairs_hook=_unique_json)

SERVER_RUNTIME_PROBE = '''
import asyncio, os, tempfile
from pathlib import Path
import fitz
from backend.app.supervisor import probe_adoption
from project_remedy.html_to_pdf import HTMLToPDFConverter

assert os.geteuid() != 0 and probe_adoption()
status = dict(line.split(':', 1) for line in Path('/proc/1/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(), 16) == 0 and status['NoNewPrivs'].strip() == '1' and status['Seccomp'].strip() == '2'
for field, path in [('REMEDY_PREFLIGHT_MEMORY','memory.max'), ('REMEDY_PREFLIGHT_PIDS','pids.max')]:
    assert Path('/sys/fs/cgroup', path).read_text().strip() == os.environ[field]
quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
assert quota != 'max' and int(quota) / int(period) == float(os.environ['REMEDY_PREFLIGHT_CPUS'])
async def verify():
    converter = HTMLToPDFConverter(max_concurrent=1)
    try:
        await converter.start()
        with tempfile.TemporaryDirectory(prefix="remedy-preflight-") as directory:
            output = Path(directory) / "probe.pdf"
            result = await converter.convert("<!doctype html><html lang='en'><title>Preflight</title><body><main><h1>Preflight renderer sentinel</h1></main></body></html>", output)
            assert result.success and output.is_file()
            with fitz.open(output) as document:
                assert document.page_count == 1 and "Preflight renderer sentinel" in document[0].get_text()
    finally:
        await converter.close()
asyncio.run(verify())
print("pidfd-subreaper-and-sandboxed-renderer-available")
'''

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile',choices=['engine','engine-scanner','bridge-review','bridge-full','integration'],required=True)
parser.add_argument('--artifacts',type=Path,required=True)
parser.add_argument('--proof',type=Path,required=True)
parser.add_argument('--state-root',type=Path,required=True)
parser.add_argument('--production',action='store_true')
parser.add_argument('--secret-root',type=Path,required=True)
parser.add_argument('--with-scanner',action='store_true')
parser.add_argument('--integration-proof',type=Path)
parser.add_argument('--conductor-target',choices=['release-2.156.2','staging-67301b35'])
parser.add_argument('--conductor-artifacts',type=Path)
parser.add_argument('--compose-config',type=Path)
parser.add_argument('--integration-mode',choices=['review-only','full-write'])
parser.add_argument('--tls-root',type=Path)
parser.add_argument('--nss-seed-root',type=Path)
parser.add_argument('--mongo-state-root',type=Path)
parser.add_argument('--renderer-seccomp',type=Path)
parser.add_argument('--history',action='store_true')
parser.add_argument('--bridge-state-root',type=Path)
parser.add_argument('--fence-root',type=Path)
parser.add_argument('--trust-epoch')
parser.add_argument('--status-issuer')
parser.add_argument('--signing-config',type=Path)
parser.add_argument('--keyring',type=Path)
parser.add_argument('--signing-key',type=Path)

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def run(*command):
    result=subprocess.run(command,text=True,capture_output=True,timeout=15)
    if result.returncode: raise ValueError('required_host_check_failed:'+command[0])
    return result.stdout.strip()

NODE_GUARD = """const fs=require('node:fs');const assert=require('node:assert/strict');
const status=fs.readFileSync('/proc/1/status','utf8');
assert.ok(process.getuid()>0);assert.match(status,/^CapEff:\\s+0+$/m);
assert.match(status,/^NoNewPrivs:\\s+1$/m);assert.match(status,/^Seccomp:\\s+2$/m);
for(const [name,path] of [['REMEDY_PREFLIGHT_MEMORY','memory.max'],['REMEDY_PREFLIGHT_PIDS','pids.max']])assert.equal(fs.readFileSync('/sys/fs/cgroup/'+path,'utf8').trim(),process.env[name]);
const [q,p]=fs.readFileSync('/sys/fs/cgroup/cpu.max','utf8').trim().split(/ +/);assert.notEqual(q,'max');assert.equal(Number(q)/Number(p),Number(process.env.REMEDY_PREFLIGHT_CPUS));
if(process.env.REMEDY_PREFLIGHT_UID)assert.equal(process.getuid(),Number(process.env.REMEDY_PREFLIGHT_UID));
const r=require('node:child_process').spawnSync(process.argv[1],process.argv.slice(2),{env:process.env,stdio:'inherit'});
if(r.error)process.exit(1);process.exit(r.status??1);"""


def probe(image, role, policy, profile, secret_root=None, bridge=False, expression=None,
          *, integration=False, mounts=(), environment=None, command_override=None, uid=None):
    """Exact-ID, labelled, no-network disposable probes; never an application/store."""
    require(re.fullmatch(r'sha256:[a-f0-9]{64}',image) is not None, 'immutable_probe_image_required')
    name='remedy-preflight-'+uuid.uuid4().hex
    owner=uuid.uuid4().hex
    limits=policy['limits'][role]
    arguments=['docker','create','--name',name,'--label','org.libretexts.preflight-owner='+owner,
        '--network','none','--init','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--cpus',str(limits['cpus']),'--memory',str(limits['memoryBytes']), '--stop-timeout',str(limits['stopSeconds']),
        '--pids-limit',str(limits['pids']),'--tmpfs','/tmp:rw,nosuid,nodev,size='+str(limits['tmpBytes']),
        '--env','HOME='+('/tmp/renderer-home' if role=='renderer' else '/tmp'),'--env','TMPDIR=/tmp']
    for field,value in {'MEMORY':limits['memoryBytes'],'PIDS':limits['pids'],'CPUS':limits['cpus']}.items():
        arguments+=['--env','REMEDY_PREFLIGHT_'+field+'='+str(value)]
    if role in {'server','scanner','renderer'}:
        arguments+=['--shm-size',str(limits['shmBytes']),'--security-opt','seccomp='+str(profile)]
    else:
        arguments+=['--shm-size',str(limits.get('shmBytes',64*1024**2))]
    if uid is not None or role in ROLE_UID:
        uid=uid if uid is not None else ROLE_UID[role]
        arguments+=['--user',f'{uid}:{uid}','--env','REMEDY_PREFLIGHT_UID='+str(uid)]
    if role=='mongo':
        # Mask both image VOLUME declarations; no anonymous persistent volume is
        # ever created and no existing database is opened by a prerequisite probe.
        arguments+=['--tmpfs','/data/db:rw,nosuid,nodev,size=16m',
                    '--tmpfs','/data/configdb:rw,nosuid,nodev,size='+str(limits['configdbTmpBytes'])]
    for source,target in mounts:
        arguments+=['--mount',f'type=bind,src={source},dst={target},readonly']
    for key,value in (environment or {}).items(): arguments+=['--env',key+'='+value]
    if secret_root is not None:
        directory=secret_root/role
        require(not directory.is_symlink() and directory.is_dir(), 'private_role_directory_required')
        arguments+=['--mount',f'type=bind,src={directory},dst=/run/secrets,readonly',
                    '--mount',f'type=bind,src={ROOT}/deploy/stack/secret-env.mjs,dst=/proof/secret-env.mjs,readonly']
        fields=ROLE_FILES[role] if integration else {
            'server':{'APP_API_KEY':'app','OLLAMA_API_KEY':'ollama'},
            'scanner':{'SCANNER_API_KEY':'api','ADAPT_TOKEN':'adapt','REMEDY_API_KEY':'remedy'},
            'bridge':{'SERVER_KEY':'key','SERVER_SECRET':'secret','SERVER_USER':'user'}}[role].copy()
        if bridge and role in {'server','bridge'}: fields['REMEDY_BRIDGE_SERVICE_KEY']='service'
        for field,file in fields.items(): arguments+=['--env',field+'_FILE=/run/secrets/'+file]
        command=['node','/proof/secret-env.mjs',role,'node','-e',expression] if expression else ['node','/proof/secret-env.mjs',role,'--check']
    elif role=='server':
        command=['python','-c',SERVER_RUNTIME_PROBE]
    else:
        command=['node','--input-type=module','-e','import {chromium} from "playwright"; if(process.getuid()===0)process.exit(1); const b=await chromium.launch({headless:true,chromiumSandbox:true});const p=await b.newPage();await p.setContent("<html><body>Preflight</body></html>");await b.close();console.log("sandbox-launch-closed")']
    if command_override is not None: command=command_override
    if command[0]=='node': command=['node','-e',NODE_GUARD,*command]
    if role=='renderer':
        arguments+=['--mount',f'type=bind,src={ROOT}/deploy/stack/browser-home.sh,dst=/proof/browser-home.sh,readonly']
        command=['sh','/proof/browser-home.sh',*command]
    container=None
    try:
        container=run(*arguments,'--entrypoint',command[0],image,*command[1:])
        require(re.fullmatch(r'[a-f0-9]{64}',container) is not None, 'immutable_probe_container_required')
        inspection=read_json(run('docker','inspect',container))[0]
        host=inspection['HostConfig']
        require(inspection['Id']==container and inspection['Image']==image and host['Init'] is True and host['ReadonlyRootfs'] is True and
                host['CapDrop']==['ALL'] and not host.get('CapAdd') and not host.get('Privileged') and host['NetworkMode']=='none' and
                not host.get('PortBindings') and 'no-new-privileges:true' in host['SecurityOpt'] and
                host['Memory']==limits['memoryBytes'] and host['PidsLimit']==limits['pids'] and host['NanoCpus']==int(limits['cpus']*10**9) and
                host['ShmSize']==limits.get('shmBytes',64*1024**2) and inspection['Config']['StopTimeout']==limits['stopSeconds'],
                'disposable_probe_runtime_profile_mismatch')
        seccomp_options = [value.split('=',1)[1] for value in host['SecurityOpt'] if value.startswith('seccomp=')]
        if profile is not None:
            require(len(seccomp_options)==1 and (seccomp_options[0]==str(profile) or
                    read_json(seccomp_options[0])==read_json(profile.read_text())), 'actual_probe_seccomp_filter_mismatch')
        else:
            require(not seccomp_options, 'unexpected_probe_seccomp_filter')
        result=subprocess.run(['docker','start','--attach',container],capture_output=True,text=True,timeout=60)
        require(result.returncode==0, 'image_kernel_or_private_credentials_failed:'+role)
        final=read_json(run('docker','inspect',container))[0]
        require(final['Id']==container and final['State'].get('Running') is False and final['State'].get('ExitCode')==0 and
                final['State'].get('OOMKilled') is False, 'disposable_probe_did_not_complete_successfully:'+role)
        return result.stdout.strip()
    finally:
        # Discover by our random name only if create was interrupted before its
        # response. Every destructive command still requires its full immutable
        # ID and the exact owner label created by this invocation.
        unwinding = sys.exc_info()[0] is not None
        cleanup_failed = False
        try:
            value=read_json(run('docker','inspect',container or name))[0]
            owned_id=value.get('Id','')
            require(re.fullmatch(r'[a-f0-9]{64}',owned_id) is not None and
                    (container is None or owned_id==container) and
                    value.get('Config',{}).get('Labels',{}).get('org.libretexts.preflight-owner')==owner,
                    'disposable_probe_owner_mismatch')
            try:
                subprocess.run(['docker','stop','--time','5',owned_id],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            except (OSError,subprocess.TimeoutExpired):
                pass  # force-remove the same verified immutable ID below
            result=subprocess.run(['docker','rm','--force','--volumes',owned_id],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            cleanup_failed = result.returncode != 0
        except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.TimeoutExpired):
            cleanup_failed = container is not None
        if cleanup_failed and not unwinding:
            raise ValueError('owned_disposable_probe_cleanup_failed')


INDEX_SHA256 = '99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8'
MONGO = 'mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'
INTEGRATION_SCOPE = 'compiled-auth-scan-rendered-preview-and-production-hold'
ROLE_UID = {'server':999, 'bridge':1000, 'renderer':1001, 'conductor':1000, 'mongo':999}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verifiers():
    # These are the same fail-closed archive/configuration verifiers that produce
    # the receipts. Importing them performs no download, import or process work.
    directory = str(ROOT / '.github/stack-proof')
    sys.path.insert(0, directory)
    try:
        return importlib.import_module('verify_imports'), importlib.import_module('conductor_artifacts')
    finally:
        sys.path.remove(directory)


def index_candidates(policy):
    path = ROOT / 'deploy/stack/conductor-candidates.json'
    require(policy.get('conductorCandidateIndexSHA256') == INDEX_SHA256 and sha(path) == INDEX_SHA256,
            'original_32patch_conductor_index_required')
    index = read_json(path.read_text())
    require(index.get('formatVersion') == 1, 'unsupported_conductor_index_schema')
    return {item['target']:item for item in index['candidates']}


def bounded_tmpfs(value, destination, size):
    require(isinstance(value, dict) and isinstance(value.get(destination), str), 'missing_bounded_tmpfs')
    options = value[destination].split(',')
    require({'rw','nosuid','nodev'} <= set(options), 'unsafe_tmpfs_options')
    sizes = [option[5:] for option in options if option.startswith('size=')]
    require(len(sizes) == 1, 'missing_bounded_tmpfs_size')
    match = re.fullmatch(r'([0-9]+)([kmg]?)', sizes[0], re.I)
    require(match is not None, 'unsupported_tmpfs_size')
    actual = int(match[1]) * {'':1,'k':1024,'m':1024**2,'g':1024**3}[match[2].lower()]
    require(actual == size, 'tmpfs_capacity_mismatch')


def validate_integration_proof(candidate, baseline, full, target, policy):
    """Validate a completed commissioning receipt, never grant deployment/write admission.

    Actual archive bytes and currently loaded configurations are checked separately
    before probes; this seam alone establishes no host or provider acceptance.
    """
    candidates = index_candidates(policy)
    require(full.get('schema', 'remedy-full-proof-v1') == 'remedy-full-proof-v1', 'unsupported_integration_proof_schema')
    require(target in candidates, 'original_conductor_target_required')
    require(full.get('conductorIndexSHA256') == INDEX_SHA256, 'original_conductor_import_index_binding_required')
    require(full.get('verificationScope') == INTEGRATION_SCOPE and full.get('verificationComplete') is True,
            'incomplete_or_wrong_scope_integration_proof')
    require(type(full.get('operationalAcceptanceComplete')) is bool, 'integration_acceptance_field_required')
    require(not any(full.get(key) for key in ('error','errors','uiFailures','shutdownErrors','externalMutationMeasurementError')),
            'failed_integration_proof')
    require(type(full.get('externalMutations')) is int and full['externalMutations'] == 0,
            'external_mutation_proof_required')
    require(full.get('serverSource') == candidate['serverSource'], 'integration_source_mismatch')
    require(candidate.get('bridgeSource') == policy['bridgeSource'], 'reviewed_bridge_source_required')
    require(set(full.get('targets', {})) == set(candidates), 'complete_target_proofs_required')
    require(all(full.get(field) is True for field in ('actualScannerAgainstTLSserver','bridgePrivateSigningKeyAbsent',
                'rendererInitialNamespaceChrootDenied')), 'missing_integration_security_or_tls_evidence')
    require(type(full.get('rendererUID')) is int and full['rendererUID'] == 1001, 'renderer_uid_1001_required')
    imports = baseline['importedArtifacts']['images']
    identities = {role:imports[role]['loadedDockerImageID'] for role in ('server','bridge','renderer')}
    identities['scanner'] = baseline['images']['scanner']['id']
    consumer_ids = set()
    runtime, _ = verifiers()
    for name, expected in candidates.items():
        result = full['targets'][name]
        require(result.get('complete') is True, 'incomplete_conductor_target')
        artifact = result['artifact']
        pin = expected['validation']
        required = {'baseCommit':expected['baseCommit'], 'sourceTree':expected['sourceTree'],
                    'artifactID':pin['artifactID'], 'ZIPDigest':pin['artifactDigest'],
                    'archiveSHA256':pin['archiveSHA256'], 'imageID':pin['imageID'],
                    'sourceConfigDigest':pin['imageID']}
        require(all(artifact.get(key) == value for key,value in required.items()), 'original_conductor_artifact_mismatch')
        original_ids = {pin['imageID']}
        if artifact.get('sourceManifestDigest') is not None:
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', artifact['sourceManifestDigest']) is not None,
                    'invalid_original_manifest_identity')
            original_ids.add(artifact['sourceManifestDigest'])
        require(artifact.get('loadedDockerImageID') in original_ids, 'original_loaded_conductor_identity_required')
        require(artifact.get('filesystemDiffIDs') and all(re.fullmatch(r'sha256:[a-f0-9]{64}', item)
                for item in artifact['filesystemDiffIDs']), 'conductor_filesystem_binding_required')
        configuration = runtime.runtime_configuration(artifact['runtimeConfiguration'])
        require(configuration == runtime.runtime_configuration(artifact['inspectConfiguration']), 'conductor_runtime_configuration_mismatch')
        require((configuration['Entrypoint'] or []) + (configuration['Cmd'] or []) == ['node','dist/server.js'] and
                (configuration['Labels'] or {}).get('org.opencontainers.image.revision') == expected['sourceTree'],
                'original_compiled_conductor_entrypoint_required')
        consumer_ids.add(artifact['loadedDockerImageID'])
        phases = result.get('phases', [])
        require(isinstance(phases, list) and len(phases) == 4 and all(phase.get('passed') is True for phase in phases),
                'complete_backend_and_actual_ui_phases_required')
        for phase in ('review','production-held'):
            observations = [item for item in phases if item.get('phase') == phase]
            require(len(observations) == 1, 'review_and_production_hold_evidence_required')
            item = observations[0]
            require(all(item.get(field) is True for field in ('compiledEntrypoint','realAuthenticationAndMongo','projectAuthorization',
                        'realScanPreview','realRenderedEvidence','productionMutationDenied')) and
                    item.get('node') == pin['runtimeNode'] and type(item.get('intents')) is int and item['intents'] == 0,
                    'incomplete_compiled_conductor_backend_evidence')
        browser = [item for item in phases if item.get('realCompiledUI') is True]
        require(len(browser) == 1 and all(browser[0].get(field) is True for field in
                ('trustedTLS','browserManagedSecureCookie','manualFailureEvidenceSaved','productionMutationFalse')) and
                browser[0].get('productionSSOVerified') is False, 'actual_compiled_ui_evidence_required')
        freshness = [item for item in phases if item.get('actualBrowserSourceChange') is True]
        require(len(freshness) == 1 and all(freshness[0].get(field) is True for field in
                ('changedSourceStalesManualEvidence','immutableReviewHistory','productionMutationFalse')) and
                type(freshness[0].get('verifiedCriteria')) is int and freshness[0]['verifiedCriteria'] == 0 and
                freshness[0].get('realCompiledUI') is not True and freshness[0].get('phase') not in {'review','production-held'},
                'actual_browser_source_freshness_evidence_required')
    started = full.get('started')
    require(isinstance(started, list) and started, 'actual_runtime_inventory_required')
    observed = set()
    observed_consumers = set()
    for item in started:
        role = item.get('role')
        if role not in {'server','scanner','bridge','renderer','mongo','conductor'}:
            continue  # explicitly separate fixture/tool roles from product roles
        observed.add(role)
        limits = policy['limits'][role]
        require(type(item.get('uid')) is int and item['uid'] > 0 and
                (role not in ROLE_UID or item['uid'] == ROLE_UID[role]), 'runtime_uid_mismatch')
        require(type(item.get('capEff')) is int and item['capEff'] == 0 and item.get('noNewPrivileges') is True and
                type(item.get('seccomp')) is int and item['seccomp'] == 2 and item.get('readOnlyRoot') is True and item.get('init') is True, 'unsafe_actual_runtime_security')
        profile = ROOT / ('deploy/chromium-seccomp-amd64.json' if role == 'server' else 'deploy/stack/' + role + '-seccomp-amd64.json')
        require(item.get('seccompProfileSHA256') == (sha(profile) if role in {'server','scanner','renderer'} else None),
                'actual_seccomp_profile_mismatch')
        for field, expected in {'cpus':limits['cpus'], 'memoryBytes':limits['memoryBytes'], 'pidLimit':limits['pids'],
                                'shmBytes':limits.get('shmBytes',64*1024**2), 'stopSeconds':limits['stopSeconds']}.items():
            require((type(item.get(field)) in (int,float) if field=='cpus' else type(item.get(field)) is int) and item[field] == expected, 'actual_runtime_limits_mismatch')
        bounded_tmpfs(item.get('tmpfs'), '/tmp', limits['tmpBytes'])
        if role == 'mongo':
            bounded_tmpfs(item['tmpfs'], '/data/configdb', limits['configdbTmpBytes'])
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', item.get('imageID','')) is not None, 'immutable_mongo_identity_required')
        elif role == 'conductor':
            require(item.get('imageID') in consumer_ids, 'conductor_runtime_identity_mismatch')
            observed_consumers.add(item['imageID'])
        else:
            require(item.get('imageID') == identities[role], 'integration_runtime_image_mismatch')
    require(observed == {'server','scanner','bridge','renderer','mongo','conductor'} and observed_consumers == consumer_ids,
            'complete_product_runtime_inventory_required')
    return full['targets'][target]['artifact']


# Explicit role/file matrix shared with the unchanged file loader. Values never
# appear in a command line, exception, receipt or output; compare only hashes.
ROLE_FILES = {
    'server': {'APP_API_KEY':'app','OLLAMA_API_KEY':'ollama','REMEDY_BRIDGE_SERVICE_KEY':'service'},
    'scanner': {'SCANNER_API_KEY':'api','ADAPT_TOKEN':'adapt','REMEDY_API_KEY':'remedy'},
    'bridge': {'SERVER_KEY':'key','SERVER_SECRET':'secret','SERVER_USER':'user','REMEDY_BRIDGE_SERVICE_KEY':'service','RENDER_SCANNER_TOKEN':'renderer'},
    'renderer': {'RENDER_SCANNER_TOKEN':'token'},
    'conductor': {'SECRETKEY':'session','MONGOOSEURI':'mongo','REMEDY_API_KEY':'remedy','OPENAI_API_KEY':'openai','STRIPE_SECRET_KEY':'stripe','MAILGUN_API_KEY':'mailgun'},
}
SERVICES = {'server':'remedy-server','scanner':'adapt-scanner','bridge':'remedy-bridge',
            'renderer':'remedy-renderer','mongo':'mongo','conductor':'conductor'}
SIGNING_FIELDS = {'REMEDY_REVIEWER_SIGNING_KEY_FILE','REMEDY_REVIEWER_KEY_ID','REMEDY_REVIEWER_ISSUER',
                  'REMEDY_REVIEWER_AUDIENCE','REMEDY_REVIEWER_KEY_ENABLED',
                  'REMEDY_REVIEWER_KEY_NOT_BEFORE','REMEDY_REVIEWER_KEY_NOT_AFTER'}


def canonical(path):
    require(isinstance(path, Path) and path.is_absolute() and path.resolve(strict=True) == path,
            'absolute_existing_canonical_path_required')
    return path


def private_directory(path, uid):
    canonical(path)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700,
            'private_role_directory_owner_or_mode_invalid')


def protected_file(path, uid, maximum=16384, *, contents=True):
    canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1 and
                stat.S_IMODE(info.st_mode) in {0o400,0o600} and 0 < info.st_size <= maximum,
                'protected_file_owner_mode_or_size_invalid')
        if not contents:
            return b''
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            value = stream.read(maximum + 1)
        require(len(value) == info.st_size and os.fstat(fd).st_mtime_ns == info.st_mtime_ns,
                'protected_file_changed_during_check')
        return value
    finally:
        os.close(fd)


def validate_storage(path, uid, maximum):
    private_directory(path, uid)
    require(run('findmnt','--noheadings','--output','FSTYPE','--target',str(path)) in {'ext4','xfs'},
            'unsupported_persistent_filesystem')
    capacity = os.statvfs(path)
    total, free = capacity.f_frsize * capacity.f_blocks, capacity.f_frsize * capacity.f_bavail
    require(0 < total <= maximum, 'bounded_state_filesystem_required')
    require(free >= 16*1024**2, 'insufficient_state_capacity')
    return {'capacityBytes':total, 'freeBytes':free, 'maximumBytes':maximum, 'uid':uid}


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def validate_credentials(secret_root, scanner_uid):
    canonical(secret_root)
    digests = {}
    for role, fields in ROLE_FILES.items():
        uid = scanner_uid if role == 'scanner' else ROLE_UID[role]
        directory = secret_root / role
        private_directory(directory, uid)
        # A role cannot accidentally receive signing material or another role's
        # credential through its whole-directory mount.
        require({item.name for item in directory.iterdir()} == set(fields.values()), 'unexpected_role_credential_file')
        for field, name in fields.items():
            raw = protected_file(directory / name, uid)
            value = raw[:-1] if raw.endswith(b'\n') else raw
            require(bool(re.fullmatch(rb'[\x21-\x7e]+', value)), 'credential_bytes_invalid')
            if field == 'REMEDY_BRIDGE_SERVICE_KEY':
                require(bool(re.fullmatch(rb'[a-f0-9]{64}', value)), 'service_key_format_invalid')
            if field == 'MONGOOSEURI':
                from urllib.parse import urlsplit, parse_qs
                uri = urlsplit(value.decode('ascii'))
                require(uri.scheme == 'mongodb' and uri.hostname == 'mongo' and uri.port in (None,27017) and
                        bool(uri.username) and bool(uri.password) and
                        bool(re.fullmatch(r'/[A-Za-z0-9_-]+', uri.path)) and
                        parse_qs(uri.query).get('authSource') == [uri.path[1:]],
                        'preprovisioned_authenticated_mongo_uri_required')
            digests[role, field] = hashlib.sha256(raw).digest()
    for left, right in [(('server','APP_API_KEY'),('scanner','REMEDY_API_KEY')),
                        (('server','APP_API_KEY'),('conductor','REMEDY_API_KEY')),
                        (('server','REMEDY_BRIDGE_SERVICE_KEY'),('bridge','REMEDY_BRIDGE_SERVICE_KEY')),
                        (('bridge','RENDER_SCANNER_TOKEN'),('renderer','RENDER_SCANNER_TOKEN'))]:
        require(digests[left] == digests[right], 'cross_role_credential_bytes_mismatch')


def validate_tls(root, scanner_uid):
    canonical(root)
    ca_digest = None
    for role in ('server','scanner','bridge','conductor'):
        uid = scanner_uid if role == 'scanner' else ROLE_UID[role]
        directory = root / role
        private_directory(directory, uid)
        names = {'cert.pem','key.pem','ca.pem'} if role == 'server' else {'ca.pem'}
        require({item.name for item in directory.iterdir()} == names, 'unexpected_tls_role_file')
        for name in names:
            raw = protected_file(directory / name, uid, 1024*1024)
            if name == 'key.pem': require(b'PRIVATE KEY' in raw and b'ENCRYPTED' not in raw, 'noninteractive_tls_private_key_required')
            if name != 'key.pem':
                require(b'PRIVATE KEY' not in raw and b'-----BEGIN CERTIFICATE-----' in raw, 'public_certificate_required')
            if name == 'ca.pem':
                current = hashlib.sha256(raw).digest()
                require(ca_digest is None or current == ca_digest, 'cross_role_ca_mismatch')
                ca_digest = current
    server = root / 'server'
    run('openssl','verify','-CAfile',str(server/'ca.pem'),'-purpose','sslserver','-verify_hostname','remedy-server',str(server/'cert.pem'))
    run('openssl','x509','-in',str(server/'cert.pem'),'-checkend','0','-noout')
    public = run('openssl','x509','-in',str(server/'cert.pem'),'-pubkey','-noout')
    private_public = run('openssl','pkey','-in',str(server/'key.pem'),'-pubout')
    require(hashlib.sha256(public.encode()).digest() == hashlib.sha256(private_public.encode()).digest(), 'tls_private_key_mismatch')
    return ca_digest


def validate_nss_seed(root, full, ca_path):
    private_directory(root, 1001)
    require({item.name for item in root.iterdir()} <= {'cert9.db','key4.db','pkcs11.txt'} and
            {'cert9.db','key4.db'} <= {item.name for item in root.iterdir()}, 'fresh_public_nss_seed_required')
    for name in ('cert9.db','key4.db'):
        protected_file(root/name, 1001, 16*1024**2)
    if (root/'pkcs11.txt').exists() or (root/'pkcs11.txt').is_symlink(): protected_file(root/'pkcs11.txt',1001)
    # Inspect SQLite in immutable read-only mode: no WAL, initialization or key
    # generation is allowed. The paired browser launch still runs in the image.
    try:
        with sqlite3.connect((root/'key4.db').as_uri()+'?mode=ro&immutable=1', uri=True) as database:
            require(database.execute('SELECT count(*) FROM nssPrivate').fetchone() == (0,), 'nss_private_identities_forbidden')
        with sqlite3.connect((root/'cert9.db').as_uri()+'?mode=ro&immutable=1', uri=True) as database:
            require(database.execute('SELECT count(*) FROM nssPublic').fetchone()[0] > 0, 'public_nss_trust_required')
    except sqlite3.Error:
        raise ValueError('unsupported_or_invalid_public_nss_database') from None
    setup = full.get('NSSSetup', {})
    require(setup.get('hostToolPackage') == '2:3.98-1ubuntu0.3' and setup.get('runtimePackage') == '2:3.98-1ubuntu0.2' and
            setup.get('toolSHA256') == '505b13e3087e1abcabec3f1485e0e76b81322667dcae25758341b46bcfc5b62d',
            'reviewed_nss_compatibility_pair_required')
    tool = Path('/usr/bin/certutil')
    require(sha(tool) == setup['toolSHA256'] and
            run('dpkg-query','-W','-f=${Version}','libnss3-tools') == setup['hostToolPackage'], 'unsupported_nss_seed_toolchain')
    ca_blocks = re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',protected_file(ca_path,999,1024*1024),re.S)
    approved = set()
    for pem in ca_blocks:
        result = subprocess.run(['openssl','x509','-noout','-fingerprint','-sha256'],input=pem,capture_output=True,timeout=15)
        require(result.returncode == 0, 'invalid_reviewed_ca_bundle')
        approved.add(result.stdout.decode('ascii').strip())
    fingerprints = set()
    try:
        with sqlite3.connect((root/'cert9.db').as_uri()+'?mode=ro&immutable=1', uri=True) as database:
            certificates = database.execute('SELECT a11 FROM nssPublic WHERE a11 IS NOT NULL').fetchall()
        require(bool(certificates), 'public_nss_ca_certificates_required')
        for (der,) in certificates:
            require(isinstance(der,bytes) and 0 < len(der) <= 1024*1024, 'unsupported_public_nss_certificate')
            for arguments in (['-ext','basicConstraints'],['-fingerprint','-sha256']):
                result = subprocess.run(['openssl','x509','-inform','DER','-noout',*arguments],input=der,capture_output=True,timeout=15)
                require(result.returncode == 0, 'invalid_nss_ca_certificate')
                if arguments[0] == '-ext': require(b'CA:TRUE' in result.stdout, 'ca_only_nss_seed_required')
                else: fingerprints.add(result.stdout.decode('ascii').strip())
    except sqlite3.Error:
        raise ValueError('unsupported_public_nss_certificate_schema') from None
    require(fingerprints == approved and bool(approved), 'only_reviewed_server_ca_allowed_in_renderer_seed')


def validate_history(args):
    require(isinstance(args.trust_epoch, str) and 0 < len(args.trust_epoch) <= 512 and
            '\x00' not in args.trust_epoch and '\n' not in args.trust_epoch and
            bool(args.status_issuer), 'explicit_opaque_history_epoch_and_issuer_required')
    fence_path = args.fence_root/'fence.json'
    before = protected_file(fence_path, 1000)
    fence = read_json(before)
    require(set(fence) == {'trust_epoch','durability_seq'} and fence['trust_epoch'] == args.trust_epoch and
            type(fence['durability_seq']) is int and 0 <= fence['durability_seq'] <= 9007199254740991,
            'current_independent_fence_required')
    ledger = args.bridge_state_root/'claims.sqlite3'
    protected_file(ledger, 1000, 512*1024**2, contents=False)
    for suffix in ('-wal','-journal'):
        sidecar=Path(str(ledger)+suffix)
        require(not sidecar.is_symlink() and (not sidecar.exists() or sidecar.stat().st_size==0), 'checkpointed_history_ledger_required')
    try:
        with sqlite3.connect(ledger.as_uri()+'?mode=ro&immutable=1',uri=True) as database:
            database.execute('PRAGMA query_only=ON')
            require(database.execute('PRAGMA quick_check').fetchone() == ('ok',), 'invalid_history_ledger')
            rows = database.execute('SELECT trust_epoch,durability_seq FROM meta WHERE singleton=1').fetchall()
            require(rows == [(args.trust_epoch, fence['durability_seq'])], 'ledger_and_current_fence_mismatch')
    except sqlite3.Error:
        raise ValueError('invalid_history_ledger') from None
    require(protected_file(fence_path,1000) == before, 'current_fence_changed_during_check')


def validate_signing(args):
    values = read_json(protected_file(args.signing_config, os.getuid()))
    require(set(values) == SIGNING_FIELDS and all(isinstance(value,str) and value for value in values.values()),
            'seven_existing_signer_settings_required')
    require(values['REMEDY_REVIEWER_SIGNING_KEY_FILE'] == '/run/signing/private.pem' and
            values['REMEDY_REVIEWER_KEY_ENABLED'] in {'true','false'}, 'invalid_signer_configuration')
    start, end = values['REMEDY_REVIEWER_KEY_NOT_BEFORE'], values['REMEDY_REVIEWER_KEY_NOT_AFTER']
    require(start.isdigit() and end.isdigit(), 'invalid_signer_validity')
    import time
    enabled = values['REMEDY_REVIEWER_KEY_ENABLED'] == 'true'
    require(0 <= int(start) < int(end) <= 9007199254740991, 'invalid_signer_validity')
    require(not enabled or int(start) <= int(time.time()) < int(end), 'signer_outside_validity_window')
    ring_raw = protected_file(args.keyring, 1000)
    require(b'PRIVATE KEY' not in ring_raw, 'bridge_keyring_must_be_public')
    ring = read_json(ring_raw)
    require(set(ring) == {'issuer','audience','environment','trust_epoch','keys'}, 'public_keyring_fields_required')
    require(ring.get('environment') == 'production' and ring.get('trust_epoch') == args.trust_epoch and
            ring.get('issuer') == values['REMEDY_REVIEWER_ISSUER'] and ring.get('audience') == values['REMEDY_REVIEWER_AUDIENCE'],
            'signer_keyring_policy_mismatch')
    require(isinstance(ring.get('keys'),list) and ring['keys'], 'public_production_keyring_required')
    for key in ring['keys']:
        require(set(key) <= {'kid','kty','crv','x','issuer','audience','environment','trust_epoch','not_before','not_after','enabled','revoked_at'} and
                key.get('kty') == 'OKP' and key.get('crv') == 'Ed25519' and 'd' not in key,
                'public_ed25519_keyring_required')
    selected = [key for key in ring['keys'] if key.get('kid') == values['REMEDY_REVIEWER_KEY_ID']]
    require(len(selected) == 1, 'coordinated_signing_key_id_required')
    key = selected[0]
    require(key.get('environment') == 'production' and key.get('issuer') == ring['issuer'] and key.get('audience') == ring['audience'] and
            key.get('trust_epoch') == args.trust_epoch and type(key.get('enabled')) is bool and
            (not enabled or (key['enabled'] is True and key.get('revoked_at') is None)) and
            key.get('not_before') == int(start) and key.get('not_after') == int(end), 'coordinated_signing_policy_required')
    protected_file(args.signing_key, 1000)
    return values


def validate_compose(config, args, policy, identities, scanner_uid, signing, *, configuration_hashes):
    """Check explicit resolved Compose data without executing or printing it."""
    require(isinstance(config,dict) and set(config.get('services', {})) == set(SERVICES.values()), 'exact_integration_service_inventory_required')
    require(config.get('networks',{}).get('remedy',{}).get('internal') is True, 'private_internal_network_required')
    # A private package copy may change paths, but never the frozen source bytes.
    for name,relative in {'credential-loader':'deploy/stack/secret-env.mjs',
                          'browser-home':'deploy/stack/browser-home.sh'}.items():
        source = canonical(Path(config.get('configs',{}).get(name,{}).get('file','')))
        info = source.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                relative in configuration_hashes and sha(source) == configuration_hashes[relative],
                'frozen_package_config_source_required')
    loader = '/opt/remedy-bundle/secret-env.mjs'
    mounted = {}
    for role, name in SERVICES.items():
        service = config['services'][name]
        limits = policy['limits'][role]
        expected_image = MONGO if role == 'mongo' else policy['scannerImage'] if role == 'scanner' else identities[role]
        require(service.get('image') == expected_image and not service.get('build'), 'exact_compose_image_required')
        require(not service.get('ports') and service.get('restart') == 'no' and not service.get('privileged') and
                not service.get('cap_add') and service.get('cap_drop') == ['ALL'] and
                service.get('init') is True and service.get('read_only') is True,
                'unsafe_compose_security_or_restart')
        uid = scanner_uid if role == 'scanner' else ROLE_UID[role]
        if role == 'scanner': require(not service.get('user'), 'exact_scanner_default_user_required')
        if role != 'scanner': require(service.get('user') == f'{uid}:{uid}', 'compose_runtime_uid_mismatch')
        require(not any(service.get(field) for field in ('devices','device_cgroup_rules','volumes_from','pid','ipc','userns_mode','links','external_links','extra_hosts','secrets','sysctls','cgroup_parent','cgroup','runtime','env_file','extends','post_start','pre_stop')),
                'unsupported_compose_host_access')
        for field, expected in {'cpus':limits['cpus'],'mem_limit':limits['memoryBytes'],'pids_limit':limits['pids'],
                                'shm_size':limits.get('shmBytes',64*1024**2)}.items():
            require(service.get(field, 64*1024**2 if field=='shm_size' else None) == expected, 'compose_resource_limits_mismatch')
        duration = service.get('stop_grace_period','')
        match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?',duration) if isinstance(duration,str) else None
        require(match is not None and bool(duration) and sum(int(value or 0)*scale for value,scale in zip(match.groups(),(3600,60,1))) == limits['stopSeconds'],
                'compose_stop_grace_mismatch')
        options = service.get('security_opt', [])
        required_options = {'no-new-privileges:true'}
        if role in {'server','scanner','renderer'}:
            path = args.renderer_seccomp if role == 'renderer' else ROOT / ('deploy/chromium-seccomp-amd64.json' if role == 'server' else 'deploy/stack/scanner-seccomp-amd64.json')
            required_options.add('seccomp='+str(path))
        require(set(options) == required_options, 'reviewed_compose_security_options_required')
        tmpfs = service.get('tmpfs', [])
        require(isinstance(tmpfs,list), 'bounded_compose_tmpfs_required')
        tmpfs_map = dict(item.split(':',1) for item in tmpfs)
        bounded_tmpfs(tmpfs_map, '/tmp', limits['tmpBytes'])
        require(set(tmpfs_map) == ({'/tmp','/data/configdb'} if role == 'mongo' else {'/tmp'}), 'unexpected_writable_tmpfs')
        if role == 'mongo': bounded_tmpfs(tmpfs_map,'/data/configdb',limits['configdbTmpBytes'])
        env = service.get('environment', {})
        require(isinstance(env,dict) and env.get('NODE_ENV') == 'production', 'explicit_production_node_environment_required')
        example = {'server':'remedy-server','scanner':'adapt-scanner','bridge':'remedy-bridge','renderer':'renderer','conductor':'conductor'}.get(role)
        allowed = {line.split('=',1)[0] for line in (ROOT/'deploy/stack/env'/(example+'.env.example')).read_text().splitlines() if line and not line.startswith('#')} if example else set()
        allowed |= {'NODE_ENV','NODE_EXTRA_CA_CERTS','RENDER_SCANNER_URL','RENDER_SCANNER_TOKEN_FILE','REMEDY_BRIDGE_SERVICE_KEY_FILE'}
        if role == 'server': allowed |= {'CXONE_INTEGRATION_ENABLED','CXONE_BRIDGE_BASE_URL'}
        if role == 'bridge': allowed |= {'REMEDY_BRIDGE_PROFILE'}
        if role == 'mongo': allowed |= {'HOME'}
        if role in {'bridge','conductor'}: allowed |= {'REMEDY_REVIEWER_TRUST_EPOCH'}
        if role == 'conductor': allowed |= SIGNING_FIELDS
        if role == 'bridge': allowed |= {'REMEDY_CLAIM_DB','REMEDY_CLAIM_FENCE_DIR','REMEDY_OPERATION_STATUS_ISSUER','REMEDY_REVIEWER_KEYRING_FILE','REMEDY_SNAPSHOT_DIR','REMEDY_AUDIT_LOG'}
        require(set(env) <= allowed, 'unreviewed_compose_environment_field')
        require(not any(isinstance(value,str) and 'REPLACE_WITH_' in value for value in env.values()), 'unresolved_compose_configuration_placeholder')
        if role in {'server','conductor'}: require(env.get('APP_ENV') == 'production', 'production_application_environment_required')
        require(not any(field in env for field in ('NODE_TLS_REJECT_UNAUTHORIZED','REMEDY_REVIEWER_TRUST_EPOCH_FILE','IGNORE_HTTPS_ERRORS','CHROMIUM_FLAGS')),
                'unsupported_security_environment')
        if role != 'conductor': require(not any(field in env for field in SIGNING_FIELDS), 'private_signer_only_on_conductor')
        if role != 'bridge': require('REMEDY_REVIEWER_KEYRING_FILE' not in env, 'public_keyring_only_on_bridge')
        for field, filename in ROLE_FILES.get(role,{}).items():
            require(field not in env and env.get(field+'_FILE') == '/run/secrets/'+filename, 'private_file_credential_configuration_required')
        for other_role, fields in ROLE_FILES.items():
            require(not any(field in env for field in fields), 'direct_secret_environment_forbidden')
            if other_role != role:
                require(not any(field+'_FILE' in env for field in set(fields)-set(ROLE_FILES.get(role,{}))), 'cross_role_secret_mount_forbidden')
        if role != 'mongo':
            expected_entrypoint = ['node',loader,role]
            if role == 'renderer': expected_entrypoint = ['sh','/opt/remedy-bundle/browser-home.sh',*expected_entrypoint]
            require(service.get('entrypoint') == expected_entrypoint, 'unchanged_file_loader_entrypoint_required')
            files = {item['source']:item['target'] for item in service.get('configs',[])}
            require(set(files) == ({'credential-loader','browser-home'} if role=='renderer' else {'credential-loader'}) and len(files) == len(service.get('configs',[])),
                    'unexpected_compose_config_mount')
            require(files.get('credential-loader') == loader,
                    'reviewed_credential_loader_config_required')
        if role in {'scanner','bridge','conductor'}:
            require(env.get('NODE_EXTRA_CA_CERTS') == '/run/tls/ca.pem', 'node_private_ca_trust_required')
        if role == 'bridge':
            require(service.get('network_mode') == 'service:remedy-server' and not service.get('networks') and
                    env.get('REMEDY_BRIDGE_PROFILE') == args.integration_mode and env.get('CONDUCTOR_API_HOST') == '127.0.0.1' and
                    env.get('RENDER_SCANNER_URL') == 'http://remedy-renderer:5180' and env.get('SERVER_DOMAIN') == 'dev.libretexts.org' and
                    env.get('REMEDY_REVIEWER_REQUIRED') == 'true' and env.get('REMEDY_WRITE_ALLOWLIST') == '^Sandboxes/johnnyphung(?:/|$)', 'private_bridge_profile_or_namespace_mismatch')
            require(service.get('command') == ['node','--import','tsx','packages/conductor-panel/server/server.ts'], 'unchanged_bridge_command_required')
        else:
            require(not service.get('network_mode'), 'unexpected_service_network_namespace')
            require(set(service.get('networks',{})) == {'remedy'} and service.get('dns') == ['127.0.0.1'], 'private_service_network_required')
        if role == 'server':
            require(service.get('command') == ['uvicorn','backend.app.main:app','--host','0.0.0.0','--port','8000','--workers','1',
                    '--timeout-graceful-shutdown','15','--ssl-certfile','/run/tls/cert.pem','--ssl-keyfile','/run/tls/key.pem'] and
                    env.get('CXONE_INTEGRATION_ENABLED') == 'true' and env.get('CXONE_BRIDGE_BASE_URL') == 'http://127.0.0.1:5175',
                    'single_tls_server_command_required')
        elif role in {'scanner','conductor'}:
            require(service.get('command') == ['node','dist/server.js'], 'actual_compiled_node_command_required')
            endpoint = env.get('REMEDY_ENDPOINT') if role == 'scanner' else env.get('REMEDY_API_BASE_URL')
            require(endpoint == ('https://remedy-server:8000/v1/validate/html' if role == 'scanner' else 'https://remedy-server:8000'), 'private_tls_server_endpoint_required')
            if role == 'conductor':
                require(env.get('REMEDY_ENABLED') == 'true' and env.get('ORG_ID') == env.get('REMEDY_ORG_ID') and bool(env.get('ORG_ID')),
                        'coordinated_conductor_organization_required')
        elif role == 'renderer':
            require(service.get('command') == ['node','server.mjs'] and env.get('RENDER_ALLOWED_HOSTS') == 'dev.libretexts.org' and env.get('HOME') == '/tmp/renderer-home' and
                    files.get('browser-home') == '/opt/remedy-bundle/browser-home.sh', 'bounded_renderer_home_initializer_required')
        elif role == 'mongo':
            require(service.get('entrypoint') == ['mongod'] and service.get('command') == ['--auth','--bind_ip_all','--wiredTigerCacheSizeGB','0.25'],
                    'authenticated_bounded_mongo_command_required')
            require(not any(key.startswith('MONGO_INITDB_') for key in env), 'mongo_credential_provisioning_forbidden')
        expected_mounts = {}
        if role != 'mongo': expected_mounts['/run/secrets'] = (args.secret_root/role, True)
        if role == 'server':
            expected_mounts['/app/state'] = (args.state_root, False)
            expected_mounts.update({'/run/tls/'+name:(args.tls_root/'server'/name, True) for name in ('cert.pem','key.pem','ca.pem')})
        elif role in {'scanner','bridge','conductor'}:
            expected_mounts['/run/tls/ca.pem'] = (args.tls_root/role/'ca.pem', True)
        elif role == 'renderer': expected_mounts['/run/certificates/nss-seed'] = (args.nss_seed_root, True)
        elif role == 'mongo': expected_mounts['/data/db'] = (args.mongo_state_root, False)
        if role == 'bridge' and args.history:
            expected_mounts.update({'/ledger':(args.bridge_state_root,False),'/fence':(args.fence_root,False)})
        if role == 'bridge' and signing: expected_mounts['/run/reviewer/keyring.json'] = (args.keyring,True)
        if role == 'conductor' and signing: expected_mounts['/run/signing/private.pem'] = (args.signing_key,True)
        volumes = service.get('volumes',[])
        require(len(volumes) == len(expected_mounts), 'unexpected_compose_mount_inventory')
        mounted[role] = {}
        for volume in volumes:
            destination = volume.get('target')
            require(destination in expected_mounts and destination not in mounted[role], 'unexpected_or_duplicate_compose_mount')
            path, readonly = expected_mounts[destination]
            require(volume.get('type') == 'bind' and volume.get('source') == str(path) and
                    bool(volume.get('read_only',False)) == readonly and volume.get('bind',{}).get('create_host_path') is False,
                    'preprovisioned_exact_mount_required')
            mounted[role][destination] = str(path)
        if role in {'bridge','conductor'}:
            if args.history:
                require(env.get('REMEDY_REVIEWER_TRUST_EPOCH') == args.trust_epoch, 'exact_opaque_trust_epoch_required')
                if role == 'bridge':
                    require(env.get('REMEDY_OPERATION_STATUS_ISSUER') == args.status_issuer and
                            env.get('REMEDY_CLAIM_DB') == '/ledger/claims.sqlite3' and env.get('REMEDY_CLAIM_FENCE_DIR') == '/fence',
                            'existing_history_configuration_required')
            else:
                require(not any(field in env for field in ('REMEDY_CLAIM_DB','REMEDY_CLAIM_FENCE_DIR','REMEDY_OPERATION_STATUS_ISSUER','REMEDY_REVIEWER_TRUST_EPOCH')),
                        'unexpected_history_configuration')
            if role == 'conductor':
                require(all(env.get(field) == value for field,value in signing.items()) if signing else not any(field in env for field in SIGNING_FIELDS),
                        'explicit_optional_signer_configuration_required')
            elif signing:
                require(env.get('REMEDY_REVIEWER_KEYRING_FILE') == '/run/reviewer/keyring.json' and env.get('REMEDY_SNAPSHOT_DIR') == '/ledger/snapshots' and
                        env.get('REMEDY_AUDIT_LOG') == '/ledger/audit.log', 'existing_signed_bridge_configuration_required')
            else:
                require(not any(field in env for field in ('REMEDY_REVIEWER_KEYRING_FILE','REMEDY_SNAPSHOT_DIR','REMEDY_AUDIT_LOG')),
                        'unexpected_signed_bridge_configuration')
    return mounted


def require_registry_manifest(loaded,reference,role):
    expected={reference}
    if reference == MONGO:
        # RepoDigests normally omits the pull tag. These are only Docker Hub's
        # familiar and fully qualified spellings of this exact official image.
        digest=MONGO.split('@',1)[1]
        expected.update({'mongo@'+digest,'docker.io/library/mongo@'+digest})
    observed=loaded.get('RepoDigests',[])
    require(loaded.get('Os') == 'linux' and loaded.get('Architecture') == 'amd64' and not loaded.get('Variant') and
            isinstance(observed,list) and all(isinstance(item,str) for item in observed) and bool(expected.intersection(observed)) and
            re.fullmatch(r'sha256:[a-f0-9]{64}',loaded.get('Id','')) is not None,
            'exact_registry_manifest_image_required:'+role)


def verify_integration_images(args, candidate, baseline, artifact, policy):
    runtime, consumer = verifiers()
    identities = {}
    for role in ('server','bridge','renderer'):
        binding = baseline['importedArtifacts']['images'][role]
        digest, source, _ = runtime.read_oci(args.artifacts/(role+'.oci.tar'))
        require(binding['OCIConfigDigest'] == 'sha256:'+digest and source['rootfs']['diff_ids'] == binding['filesystemDiffIDs'],
                'original_owned_image_configuration_required')
        image = binding['loadedDockerImageID']
        require(re.fullmatch(r'sha256:[a-f0-9]{64}',image) is not None, 'immutable_owned_image_identity_required')
        loaded = read_json(run('docker','image','inspect',image))[0]
        require(loaded.get('Id') == image and loaded.get('Os') == 'linux' and loaded.get('Architecture') == 'amd64' and not loaded.get('Variant') and
                loaded.get('RootFS') == {'Type':'layers','Layers':binding['filesystemDiffIDs']} and
                runtime.runtime_configuration(loaded['Config']) == runtime.runtime_configuration(source['config']),
                'loaded_owned_image_differs_from_original_archive')
        expected_hash = hashlib.sha256(json.dumps(runtime.runtime_configuration(loaded['Config']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        require(expected_hash == binding['runtimeConfigurationSHA256'], 'owned_image_runtime_hash_mismatch')
        identities[role] = image
    selected = index_candidates(policy)[args.conductor_target]
    pin = selected['validation']
    directory = canonical(args.conductor_artifacts)
    require('sha256:'+sha(directory/'original-artifact.zip') == pin['artifactDigest'] and sha(directory/pin['archive']) == pin['archiveSHA256'],
            'original_conductor_zip_or_archive_mismatch')
    original = consumer.verify_saved_image(directory/pin['archive'],pin['imageID'])
    require(original['sourceManifestDigest'] == artifact.get('sourceManifestDigest'), 'original_conductor_manifest_mismatch')
    loaded = read_json(run('docker','image','inspect',artifact['loadedDockerImageID']))[0]
    mapping = consumer.verify_loaded_image(original, loaded)
    for field in ('sourceConfigDigest','loadedDockerImageID','filesystemDiffIDs','runtimeConfigurationSHA256'):
        require(mapping[field] == artifact[field], 'conductor_proof_loaded_configuration_mismatch')
    require(original['runtimeConfiguration'] == artifact['runtimeConfiguration'], 'conductor_proof_original_configuration_mismatch')
    identities['conductor'] = mapping['loadedDockerImageID']
    for role, reference in [('scanner',policy['scannerImage']),('mongo',MONGO)]:
        loaded = read_json(run('docker','image','inspect',reference))[0]
        require_registry_manifest(loaded,reference,role)
        if role == 'scanner': require(loaded['Id'] == baseline['images']['scanner']['id'] and loaded['RootFS']['Layers'] == baseline['images']['scanner']['layers'],
                                      'scanner_runtime_identity_mismatch')
        identities[role] = loaded['Id']
    return identities


def validate_flags(args):
    fields = ('integration_proof','conductor_target','conductor_artifacts','integration_mode','compose_config',
              'tls_root','nss_seed_root','mongo_state_root','renderer_seccomp')
    optional = ('history','bridge_state_root','fence_root','trust_epoch','status_issuer','signing_config','keyring','signing_key')
    if args.profile != 'integration':
        require(not any(getattr(args,field) for field in (*fields,*optional)), 'integration_flags_require_integration_profile')
        return
    require(all(getattr(args,field) is not None for field in fields), 'explicit_complete_integration_inputs_required')
    require(not args.with_scanner, 'integration_already_requires_exact_scanner')
    history_fields = ('bridge_state_root','fence_root','trust_epoch','status_issuer')
    require(all(getattr(args,field) is not None for field in history_fields) if args.history else
            not any(getattr(args,field) is not None for field in history_fields), 'explicit_complete_history_inputs_required')
    signed = [args.signing_config,args.keyring,args.signing_key]
    require(not any(signed) or (all(signed) and args.history), 'signing_requires_explicit_history_and_three_signing_inputs')


def validate_docker():
    docker = read_json(run('docker','info','--format','{{json .}}'))
    require(docker.get('OSType') == 'linux' and docker.get('Architecture') in {'x86_64','amd64'} and
            docker.get('CgroupVersion') == '2' and 'docker desktop' not in docker.get('OperatingSystem','').lower() and
            not any('rootless' in value or 'userns' in value for value in docker.get('SecurityOptions',[])),
            'unsupported_rootful_linux_docker_cgroup_profile')
    version = run('docker','compose','version','--short')
    require(re.fullmatch(r'v?2\.[0-9]+\.[0-9]+(?:[-+].*)?',version) is not None, 'docker_compose_v2_required')


def integration_check(args, candidate, baseline, policy):
    full = read_json(args.integration_proof.read_text())
    artifact = validate_integration_proof(candidate,baseline,full,args.conductor_target,policy)
    require(sha(canonical(args.renderer_seccomp)) == policy['rendererSeccompSHA256'], 'reviewed_renderer_seccomp_required')
    storage = {'server':validate_storage(args.state_root,999,policy['limits']['server']['stateBytes']),
               'mongo':validate_storage(args.mongo_state_root,999,policy['limits']['mongo']['stateBytes'])}
    stores = [args.state_root,args.mongo_state_root]
    if args.history:
        storage['bridge'] = validate_storage(args.bridge_state_root,1000,policy['limits']['bridge']['stateBytes'])
        storage['fence'] = validate_storage(args.fence_root,1000,policy['limits']['fence']['stateBytes'])
        stores += [args.bridge_state_root,args.fence_root]
        require(args.fence_root.stat().st_dev != args.bridge_state_root.stat().st_dev, 'independent_fence_filesystem_required')
    require(not any(overlaps(left,right) for n,left in enumerate(stores) for right in stores[n+1:]), 'independent_nonoverlapping_state_roots_required')
    protected = [args.secret_root,args.tls_root,args.nss_seed_root,args.compose_config]
    if args.signing_config: protected += [args.signing_config,args.keyring,args.signing_key]
    for path in protected:
        canonical(path)
        require(not any(overlaps(path,store) for store in stores), 'credentials_and_trust_must_stay_outside_state_roots')
    # Existing state is required, never initialized or connected here. This checks
    # format/auth prerequisites, not the provisioned account's actual login.
    require((args.mongo_state_root/'WiredTiger').is_file() and not (args.mongo_state_root/'WiredTiger').is_symlink(),
            'preprovisioned_mongo_data_required')
    validate_docker()
    identities = verify_integration_images(args,candidate,baseline,artifact,policy)
    require(all(item['imageID'] == identities['mongo'] for item in full['started'] if item['role'] == 'mongo'),
            'mongo_full_proof_identity_mismatch')
    scanner_records = [item for item in full['started'] if item['role'] == 'scanner']
    require(len({item['uid'] for item in scanner_records}) == 1, 'consistent_actual_scanner_uid_required')
    scanner_uid = scanner_records[0]['uid']
    actual_uid = probe(identities['scanner'],'scanner',policy,ROOT/'deploy/stack/scanner-seccomp-amd64.json',
                       command_override=['node','-e','console.log(process.getuid())'])
    require(actual_uid == str(scanner_uid), 'original_scanner_default_uid_mismatch')
    validate_credentials(args.secret_root,scanner_uid)
    validate_tls(args.tls_root,scanner_uid)
    validate_nss_seed(args.nss_seed_root,full,args.tls_root/'server/ca.pem')
    if args.history: validate_history(args)
    signing = validate_signing(args) if args.signing_config else {}
    config = read_json(protected_file(args.compose_config,os.getuid(),4*1024**2))
    require(stat.S_IMODE(args.compose_config.stat().st_mode) == 0o600, 'private_resolved_compose_mode_0600_required')
    validate_compose(config,args,policy,identities,scanner_uid,signing,configuration_hashes=candidate['configurationSha256'])
    profiles = {'server':ROOT/'deploy/chromium-seccomp-amd64.json',
                'scanner':ROOT/'deploy/stack/scanner-seccomp-amd64.json','renderer':args.renderer_seccomp,
                'bridge':None,'conductor':None,'mongo':None}
    runtime_checks = {}
    nss_mount = [(args.nss_seed_root,'/run/certificates/nss-seed')]
    for role in ('server','scanner','bridge','renderer','conductor'):
        mounts = nss_mount if role == 'renderer' else ([(args.tls_root/role/'ca.pem','/run/tls/ca.pem')] if role in {'scanner','bridge','conductor'} else [])
        trust_env = {'NODE_EXTRA_CA_CERTS':'/run/tls/ca.pem'} if role in {'scanner','bridge','conductor'} else {}
        probe(identities[role],role,policy,profiles[role],args.secret_root,True,integration=True,mounts=mounts,environment=trust_env,
              uid=scanner_uid if role=='scanner' else ROLE_UID[role])
    for role in ('server','scanner','renderer'):
        runtime_checks[role] = probe(identities[role],role,policy,profiles[role],integration=True,
                                     mounts=nss_mount if role=='renderer' else [], uid=scanner_uid if role=='scanner' else ROLE_UID[role])
    require(runtime_checks['server'] == 'pidfd-subreaper-and-sandboxed-renderer-available' and
            runtime_checks['scanner'] == 'sandbox-launch-closed' and runtime_checks['renderer'] == 'sandbox-launch-closed',
            'complete_genuine_runtime_probe_results_required')
    renderer_denial = probe(identities['renderer'],'renderer',policy,profiles['renderer'],integration=True,mounts=nss_mount,
                           command_override=['sh','-c', 'if chroot / /bin/true >/dev/null 2>&1; then exit 1; fi; printf initial-namespace-chroot-denied'])
    require(renderer_denial == 'initial-namespace-chroot-denied', 'renderer_initial_namespace_chroot_denial_required')
    nss_version = probe(identities['renderer'],'renderer',policy,profiles['renderer'],integration=True,mounts=nss_mount,
                        command_override=['dpkg-query','-W','-f=${Version}','libnss3'])
    require(nss_version == full['NSSSetup']['runtimePackage'], 'immutable_renderer_nss_runtime_mismatch')
    crypto = """const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
assert.equal(process.version,'v22.22.3');assert.ok(fs.statSync('dist/server.js').isFile());
const publicKey=crypto.createPublicKey({key:Buffer.from('302a300506032b6570032100'+'00'.repeat(32),'hex'),format:'der',type:'spki'});
assert.equal(publicKey.asymmetricKeyType,'ed25519');assert.equal(crypto.verify(null,Buffer.from('preflight'),publicKey,Buffer.alloc(64)),false);
console.log('compiled-node22-crypto-and-file-credentials-available');"""
    runtime_checks['conductor'] = probe(identities['conductor'],'conductor',policy,None,args.secret_root,True,crypto,integration=True)
    mongo = """set -eu
[ "$(id -u)" = 999 ]
awk '/^CapEff:/ {if ($2 !~ /^0+$/) exit 1; c=1} /^NoNewPrivs:/ {if ($2 != 1) exit 1; n=1} /^Seccomp:/ {if ($2 != 2) exit 1; s=1} END {if (!(c && n && s)) exit 1}' /proc/1/status
[ "$(cat /sys/fs/cgroup/memory.max)" = "$REMEDY_PREFLIGHT_MEMORY" ]
[ "$(cat /sys/fs/cgroup/pids.max)" = "$REMEDY_PREFLIGHT_PIDS" ]
awk -v cpus="$REMEDY_PREFLIGHT_CPUS" '{if ($1 == "max" || $1/$2 != cpus) exit 1}' /sys/fs/cgroup/cpu.max
mongod --version >/dev/null
printf 'mongo-binary-auth-and-storage-prerequisites-only'
"""
    runtime_checks['mongo'] = probe(identities['mongo'],'mongo',policy,None,integration=True,command_override=['sh','-c',mongo])
    require(runtime_checks['conductor'] == 'compiled-node22-crypto-and-file-credentials-available' and
            runtime_checks['mongo'] == 'mongo-binary-auth-and-storage-prerequisites-only', 'complete_crypto_and_mongo_prerequisite_results_required')
    if signing:
        public_expression = """import fs from 'node:fs';import c from 'node:crypto';
import {ReviewerVerifier} from './packages/conductor-panel/server/reviewer-auth.ts';
const r=JSON.parse(fs.readFileSync('/run/reviewer/keyring.json'));
const verifier=new ReviewerVerifier({...r,production:true});
if("""+('true' if signing['REMEDY_REVIEWER_KEY_ENABLED']=='true' else 'false')+"""&&!verifier.hasActiveKey())process.exit(1);
const k=r.keys.find(k=>k.kid==="""+json.dumps(signing['REMEDY_REVIEWER_KEY_ID'])+""");
const p=c.createPublicKey({key:k,format:'jwk'});if(p.asymmetricKeyType!=='ed25519')process.exit(1);
console.log(c.createHash('sha256').update(p.export({format:'jwk'}).x).digest('hex'));"""
        private_expression = """const fs=require('node:fs'),c=require('node:crypto');const k=c.createPrivateKey(fs.readFileSync('/run/signing/private.pem'));
if(k.asymmetricKeyType!=='ed25519')process.exit(1);const p=c.createPublicKey(k),m=Buffer.from('remedy-preflight-local-crypto');
if(!c.verify(null,m,p,c.sign(null,m,k)))process.exit(1);console.log(c.createHash('sha256').update(p.export({format:'jwk'}).x).digest('hex'));"""
        public = probe(identities['bridge'],'bridge',policy,None,args.secret_root,True,public_expression,integration=True,
                       mounts=[(args.keyring,'/run/reviewer/keyring.json')],
                       command_override=['node','/proof/secret-env.mjs','bridge','node','--import','tsx','--input-type=module','-e',public_expression])
        private = probe(identities['conductor'],'conductor',policy,None,args.secret_root,True,private_expression,integration=True,
                        mounts=[(args.signing_key,'/run/signing/private.pem')])
        require(public == private and re.fullmatch(r'[a-f0-9]{64}',public) is not None, 'signer_and_public_keyring_mismatch')
        runtime_checks['signing'] = 'matching-ed25519-pair-only-production-writes-held'
    return {'ok':True,'profile':'integration','integrationMode':args.integration_mode,'conductorTarget':args.conductor_target,
            'startupCompatibility':True,'writeReady':False,'admission':False,'deploymentReady':False,'productionWritesEnabled':False,
            'expectedBridgeReadyzStatus':503 if args.integration_mode=='full-write' else 200,
            'expectedProductionHold':'conditional_write_unproven','operationalAcceptanceComplete':False,
            'liveProvidersVerified':False,'productionSSOVerified':False,'namedServiceReadinessVerified':False,
            'mongoAccountLoginVerified':False,'storage':storage,'runtimeChecks':runtime_checks,
            'historyConfigured':args.history,'signerConfigured':bool(signing),
            'signerEnabled':signing.get('REMEDY_REVIEWER_KEY_ENABLED') == 'true',
            'unverified':['target-host-network-and-ingress','live-provider-and-SSO-authorization','provisioned-Mongo-account-login',
                          'operational-backup-upgrade-rollback-acceptance','vendor-atomic-conditional-write-approval'],
            'checks':'Original immutable archive/configuration binding, completed compiled backend/UI proof, explicit FILE/mount/TLS/history prerequisites, bounded local storage and disposable no-network kernel/browser/crypto probes. Compatibility is separate from named service and write admission.'}


def check(args):

    policy=read_json((ROOT/'deploy/stack/bundle.json').read_text())
    if args.profile=='bridge-full' and policy['productionWritesEnabled'] is not True:
        raise ValueError('production_write_profile_remains_held')
    if args.production and policy['deploymentReady'] is not True:
        raise ValueError('deployment_not_accepted_by_release_owner')
    validate_flags(args)
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('unsupported_host_linux_amd64_required')
    candidate=read_json((args.artifacts/'candidate.json').read_text())
    proof=read_json(args.proof.read_text())
    if not proof.get('verificationComplete') or proof.get('errors'):
        raise ValueError('incomplete_or_failed_actual_service_proof')
    if candidate['serverSource']!=proof.get('serverSource'):
        raise ValueError('candidate_and_proof_source_mismatch')
    imports=proof.get('importedArtifacts',{})
    if imports.get('verificationComplete') is not True or imports.get('serverSource')!=candidate['serverSource']:
        raise ValueError('verified_image_import_binding_required')
    for role in (('server','bridge','renderer') if args.profile=='integration' else ('server','bridge')):
        binding=imports['images'][role]
        if candidate['sha256'][role+'.oci.tar']!=binding['OCIArchiveSHA256']:
            raise ValueError('candidate_archive_not_in_proof')
        source=candidate['serverSource'] if role=='server' else candidate['bridgeSource']
        if binding['sourceRevision']!=source:
            raise ValueError('candidate_revision_not_in_proof')
        if (role != 'renderer' or role in proof['images']) and (proof['images'][role]['id']!=binding['loadedDockerImageID'] or proof['images'][role]['layers']!=binding['filesystemDiffIDs']):
            raise ValueError('proof_image_not_bound_to_archive')
    for name,expected in candidate['sha256'].items():
        if Path(name).name!=name or sha(args.artifacts/name)!=expected: raise ValueError('archive_or_input_hash_mismatch')
    for name,expected in candidate['configurationSha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path)!=expected: raise ValueError('package_configuration_hash_mismatch')
    if args.profile=='integration':
        required_helpers={'.github/stack-proof/verify_imports.py','.github/stack-proof/conductor_artifacts.py'}
        require(required_helpers <= set(candidate['configurationSha256']), 'shared_verifier_configuration_binding_required')
        require(proof.get('verificationComplete') is True, 'complete_private_profile_proof_required')
        required_configuration={str(path.relative_to(ROOT)) for path in (ROOT/'deploy/stack').rglob('*') if path.is_file() and path.suffix in {'.py','.mjs','.json','.yml','.example','.md','.sh'}}
        require(required_configuration <= set(candidate['configurationSha256']), 'complete_integration_configuration_binding_required')
        print(json.dumps(integration_check(args,candidate,proof,policy)))
        return
    store=args.state_root
    if not store.is_absolute() or store.is_symlink() or not store.is_dir(): raise ValueError('private_preprovisioned_state_directory_required')
    info=store.stat()
    if info.st_uid!=999 or info.st_mode & 0o077: raise ValueError('state_owner_999_private_mode_required')
    filesystem=run('findmnt','--noheadings','--output','FSTYPE','--target',str(store))
    if filesystem not in {'ext4','xfs'}: raise ValueError('unsupported_persistent_filesystem')
    capacity=os.statvfs(store)
    if capacity.f_frsize*capacity.f_blocks>policy['limits']['server']['stateBytes']:
        raise ValueError('bounded_state_filesystem_required')
    if capacity.f_frsize*capacity.f_bavail<16*1024*1024: raise ValueError('insufficient_state_capacity')
    docker=read_json(run('docker','info','--format','{{json .}}'))
    if docker.get('OSType')!='linux' or docker.get('Architecture') not in {'x86_64','amd64'} or docker.get('CgroupVersion')!='2':
        raise ValueError('unsupported_docker_cgroup_profile')
    run('docker','compose','version','--short')
    roles=['server']
    if args.profile=='engine-scanner' or args.with_scanner: roles.append('scanner')
    if args.profile.startswith('bridge-'): roles.append('bridge')
    if not args.secret_root.is_absolute() or args.secret_root.is_symlink(): raise ValueError('absolute_private_secret_root_required')
    profiles={'server':ROOT/'deploy/chromium-seccomp-amd64.json','scanner':ROOT/'deploy/stack/scanner-seccomp-amd64.json','bridge':None}
    runtime_checks={}
    for role in roles:
        image=proof['images'][role]['id']
        inspection=read_json(run('docker','image','inspect',image))[0]
        if inspection['Id']!=image or inspection['Architecture']!='amd64': raise ValueError('loaded_image_identity_mismatch')
        probe(image,role,policy,profiles[role],args.secret_root,args.profile.startswith('bridge-'))
        if role!='bridge': runtime_checks[role]=probe(image,role,policy,profiles[role])
    if 'scanner' in roles:
        fingerprint='const{createHash}=require("node:crypto");process.stdout.write(createHash("sha256").update(process.env.'
        a=probe(proof['images']['server']['id'],'server',policy,profiles['server'],args.secret_root,args.profile.startswith('bridge-'),fingerprint+'APP_API_KEY).digest("hex"))')
        b=probe(proof['images']['scanner']['id'],'scanner',policy,profiles['scanner'],args.secret_root,False,fingerprint+'REMEDY_API_KEY).digest("hex"))')
        if a!=b: raise ValueError('scanner_server_application_key_mismatch')
    if 'bridge' in roles:
        fingerprint='const{readFileSync}=require("node:fs");const{createHash}=require("node:crypto");process.stdout.write(createHash("sha256").update(readFileSync(process.env.REMEDY_BRIDGE_SERVICE_KEY_FILE)).digest("hex"))'
        a=probe(proof['images']['server']['id'],'server',policy,profiles['server'],args.secret_root,True,fingerprint)
        b=probe(proof['images']['bridge']['id'],'bridge',policy,None,args.secret_root,True,fingerprint)
        if a!=b: raise ValueError('bridge_server_service_key_mismatch')
    print(json.dumps({'ok':True,'profile':args.profile,'deploymentReady':False,
        'productionWritesEnabled':False,'liveProvidersVerified':False,
        'runtimeChecks':runtime_checks,
        'checks':'Immutable inputs, private file ownership/bytes, exact loaded images, bounded local persistent capacity, Docker platform and actual per-image pidfd/sandbox launch. Functional provider, private network and operational acceptance remain separate.'}))

class PreflightInterrupted(BaseException):
    def __init__(self, signum): self.signum=signum

def interrupted(signum, frame):
    raise PreflightInterrupted(signum)

def main(argv=None):
    args=parser.parse_args(argv)
    previous={kind:signal.signal(kind,interrupted) for kind in (signal.SIGINT,signal.SIGTERM)}
    try:
        check(args)
    except PreflightInterrupted as error:
        return 128+error.signum
    except (OSError,ValueError,KeyError,TypeError,IndexError,AssertionError,sqlite3.Error,subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok':False,'deploymentReady':False,'productionWritesEnabled':False,
            'error':str(error) if isinstance(error,ValueError) and re.fullmatch(r'[A-Za-z0-9_:-]+',str(error)) else type(error).__name__}))
        return 1
    finally:
        for kind,handler in previous.items(): signal.signal(kind,handler)
    return 0


if __name__=='__main__':
    sys.exit(main())
