"""Fail-closed candidate input/host checks; never provision keys, mounts or policy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile',choices=['engine','engine-scanner','bridge-review','bridge-full'],required=True)
parser.add_argument('--artifacts',type=Path,required=True)
parser.add_argument('--proof',type=Path,required=True)
parser.add_argument('--state-root',type=Path,required=True)
parser.add_argument('--production',action='store_true')
parser.add_argument('--secret-root',type=Path,required=True)
parser.add_argument('--with-scanner',action='store_true')
args=parser.parse_args()

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def run(*command):
    result=subprocess.run(command,text=True,capture_output=True,timeout=15)
    if result.returncode: raise ValueError('required_host_check_failed:'+command[0])
    return result.stdout.strip()

def probe(image, role, policy, profile, secret_root=None, bridge=False, expression=None):
    """Only new named disposable probes, never an existing application/store."""
    name='remedy-preflight-'+uuid.uuid4().hex
    limits=policy['limits'][role]
    arguments=['docker','run','--rm','--name',name,'--network','none','--init','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--cpus',str(limits['cpus']),'--memory',str(limits['memoryBytes']),
        '--pids-limit',str(limits['pids']),'--tmpfs','/tmp:rw,nosuid,nodev,size='+str(limits['tmpBytes']),
        '--env','HOME=/tmp','--env','TMPDIR=/tmp']
    if role in {'server','scanner'}:
        arguments+=['--shm-size',str(limits['shmBytes']),'--security-opt','seccomp='+str(profile)]
    if role=='bridge': arguments+=['--user','1000:1000']
    if secret_root is not None:
        directory=secret_root/role
        if directory.is_symlink() or not directory.is_dir(): raise ValueError('private_role_directory_required')
        arguments+=['--mount',f'type=bind,src={directory},dst=/run/secrets,readonly',
                    '--mount',f'type=bind,src={ROOT}/deploy/stack/secret-env.mjs,dst=/proof/secret-env.mjs,readonly']
        fields={'server':{'APP_API_KEY_FILE':'app','OLLAMA_API_KEY_FILE':'ollama'},
                'scanner':{'SCANNER_API_KEY_FILE':'api','ADAPT_TOKEN_FILE':'adapt','REMEDY_API_KEY_FILE':'remedy'},
                'bridge':{'SERVER_KEY_FILE':'key','SERVER_SECRET_FILE':'secret','SERVER_USER_FILE':'user'}}[role]
        if bridge and role in {'server','bridge'}: fields['REMEDY_BRIDGE_SERVICE_KEY_FILE']='service'
        for field,file in fields.items(): arguments+=['--env',field+'=/run/secrets/'+file]
        command=['node','/proof/secret-env.mjs',role,'node','-e',expression] if expression else ['node','/proof/secret-env.mjs',role,'--check']
    elif role=='server':
        command=['python','-c','import os; from backend.app.supervisor import probe_adoption; assert os.geteuid()!=0 and probe_adoption(); print("pidfd-subreeper-profile-available")']
    else:
        command=['node','--input-type=module','-e','import {chromium} from "playwright"; if(process.getuid()===0)process.exit(1); const b=await chromium.launch({headless:true,chromiumSandbox:true});const p=await b.newPage();await p.setContent("<html><body>Preflight</body></html>");await b.close();console.log("sandbox-launch-closed")']
    try:
        result=subprocess.run(arguments+['--entrypoint',command[0],image,*command[1:]],capture_output=True,text=True,timeout=60)
        if result.returncode: raise ValueError('image_kernel_or_private_credentials_failed:'+role)
        return result.stdout.strip()
    finally:
        # Exact disposable probe name created by this invocation only. It has
        # no writable persistent store and has never accepted application work.
        subprocess.run(['docker','stop','--time','20',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)

try:
    policy=json.loads((ROOT/'deploy/stack/bundle.json').read_text())
    if args.profile=='bridge-full' and policy['productionWritesEnabled'] is not True:
        raise ValueError('production_write_profile_remains_held')
    if args.production and policy['deploymentReady'] is not True:
        raise ValueError('deployment_not_accepted_by_release_owner')
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('unsupported_host_linux_amd64_required')
    candidate=json.loads((args.artifacts/'candidate.json').read_text())
    proof=json.loads(args.proof.read_text())
    if not proof.get('verificationComplete') or proof.get('errors'):
        raise ValueError('incomplete_or_failed_actual_service_proof')
    if candidate['serverSource']!=proof.get('serverSource'):
        raise ValueError('candidate_and_proof_source_mismatch')
    for name,expected in candidate['sha256'].items():
        if Path(name).name!=name or sha(args.artifacts/name)!=expected: raise ValueError('archive_or_input_hash_mismatch')
    for name,expected in candidate['configurationSha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path)!=expected: raise ValueError('package_configuration_hash_mismatch')
    store=args.state_root
    if not store.is_absolute() or store.is_symlink() or not store.is_dir(): raise ValueError('private_preprovisioned_state_directory_required')
    info=store.stat()
    if info.st_uid!=999 or info.st_mode & 0o077: raise ValueError('state_owner_999_private_mode_required')
    filesystem=run('findmnt','--noheadings','--output','FSTYPE','--target',str(store))
    if filesystem not in {'ext4','xfs'}: raise ValueError('unsupported_persistent_filesystem')
    capacity=os.statvfs(store)
    if capacity.f_frsize*capacity.f_blocks>policy['limits']['server']['stateBytes']:
        raise ValueError('bounded_state_filesystem_or_verified_quota_required')
    if capacity.f_frsize*capacity.f_bavail<16*1024*1024: raise ValueError('insufficient_state_capacity')
    docker=json.loads(run('docker','info','--format','{{json .}}'))
    if docker.get('OSType')!='linux' or docker.get('Architecture') not in {'x86_64','amd64'} or docker.get('CgroupVersion')!='2':
        raise ValueError('unsupported_docker_cgroup_profile')
    run('docker','compose','version','--short')
    roles=['server']
    if args.profile=='engine-scanner' or args.with_scanner: roles.append('scanner')
    if args.profile.startswith('bridge-'): roles.append('bridge')
    if not args.secret_root.is_absolute() or args.secret_root.is_symlink(): raise ValueError('absolute_private_secret_root_required')
    profiles={'server':ROOT/'deploy/chromium-seccomp-amd64.json','scanner':ROOT/'deploy/stack/scanner-seccomp-amd64.json','bridge':None}
    for role in roles:
        image=proof['images'][role]['id']
        inspection=json.loads(run('docker','image','inspect',image))[0]
        if inspection['Id']!=image or inspection['Architecture']!='amd64': raise ValueError('loaded_image_identity_mismatch')
        probe(image,role,policy,profiles[role],args.secret_root,args.profile.startswith('bridge-'))
        if role!='bridge': probe(image,role,policy,profiles[role])
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
        'checks':'Immutable inputs, private file ownership/bytes, exact loaded images, bounded local persistent capacity, Docker platform and actual per-image pidfd/sandbox launch. Functional provider, private network and operational acceptance remain separate.'}))
except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
    print(json.dumps({'ok':False,'deploymentReady':False,'productionWritesEnabled':False,
        'error':str(error) if isinstance(error,ValueError) else type(error).__name__}))
    sys.exit(1)
