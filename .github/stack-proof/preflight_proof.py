"""Exercise the public preflight on exact imported images and disposable CI state."""
import json
import os
from pathlib import Path
import platform
import subprocess

if os.environ.get('GITHUB_ACTIONS')!='true' or platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('Requires the isolated authorized GitHub Linux amd64 runner.')

root=Path.cwd()
evidence=root/'.stack-proof-evidence'
proof=json.loads((evidence/'result.json').read_text())
assert proof['verificationComplete'] and not proof['errors']
assert proof['serverSource']==os.environ['GITHUB_SHA']
work=Path(os.environ['RUNNER_TEMP'])/('lt196-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'])
image=work/'state.ext4'
state=work/'state'
assert image.is_file() and not image.is_symlink() and image.stat().st_uid==os.getuid()
assert image.stat().st_size==1073741824 and not state.is_symlink()
assert subprocess.run(['mountpoint','--quiet',str(state)]).returncode!=0
receipt={'serverSource':proof['serverSource'],'profiles':{},'deploymentReady':False,'productionWritesEnabled':False}
mounted=False
try:
    subprocess.run(['mount','-t','ext4','-o','loop,nodev,nosuid,noexec',str(image),str(state)],check=True,capture_output=True)
    mounted=True
    common=['python3',str(root/'deploy/stack/preflight.py'),'--artifacts',str(root/'.stack-artifacts'),
        '--proof',str(evidence/'result.json'),'--state-root',str(state),'--secret-root',str(work/'compose-secrets')]
    for profile in ('engine','engine-scanner','bridge-review'):
        args=common+['--profile',profile]+(['--with-scanner'] if profile=='bridge-review' else [])
        result=subprocess.run(args,capture_output=True,text=True,timeout=240)
        value=json.loads(result.stdout)
        receipt['profiles'][profile]={'returncode':result.returncode,'result':value}
        assert result.returncode==0 and value['ok'] is True,(profile,value)
        assert value['deploymentReady'] is False and value['productionWritesEnabled'] is False
        assert value['runtimeChecks']['server']=='pidfd-subreaper-and-sandboxed-renderer-available'
        if profile!='engine': assert value['runtimeChecks']['scanner']=='sandbox-launch-closed'
    for name,args,reason in [('production',common+['--profile','engine','--production'],'deployment_not_accepted_by_release_owner'),
                             ('bridge-full',common+['--profile','bridge-full'],'production_write_profile_remains_held')]:
        result=subprocess.run(args,capture_output=True,text=True,timeout=15)
        value=json.loads(result.stdout)
        receipt['profiles'][name]={'returncode':result.returncode,'result':value}
        assert result.returncode==1 and value['error']==reason,(name,value)
    receipt['verificationComplete']=True
finally:
    if mounted:
        subprocess.run(['umount',str(state)],check=True,capture_output=True)
    (evidence/'preflight-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
