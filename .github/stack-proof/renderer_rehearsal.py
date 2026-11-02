"""Run the reviewed thirty renderer cases in the exact imported rehearsal image."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import io

from lt212_rehearsal import BRIDGE, digest
from verify_imports import read_oci, runtime_configuration


def run(*args, timeout=120):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=timeout)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('isolated authorized GitHub Linux amd64 runner required')
    root = Path.cwd()
    evidence = root / '.stack-proof-evidence'
    evidence.mkdir(exist_ok=True)
    artifacts = root / '.stack-artifacts'
    metadata = json.loads((artifacts / 'candidate.json').read_text())
    assert metadata['serverSource'] == os.environ['GITHUB_SHA'] and metadata['bridgeSource'] == BRIDGE
    archive = artifacts / 'renderer.oci.tar'
    assert digest(archive) == metadata['sha256']['renderer.oci.tar']
    config_digest, source, blobs = read_oci(archive)
    loaded = json.loads(run('docker', 'image', 'inspect', 'remedy-renderer:stack-candidate'))[0]
    assert loaded['Os'] == 'linux' and loaded['Architecture'] == 'amd64'
    assert loaded['RootFS']['Layers'] == source['rootfs']['diff_ids']
    assert runtime_configuration(loaded['Config']) == runtime_configuration(source['config'])
    assert loaded['Config']['Labels']['org.opencontainers.image.revision'] == BRIDGE
    producer = Path(os.environ['GITHUB_WORKSPACE']) / '.stack-bridge-producer'
    assert run('git', '-C', producer, 'rev-parse', 'HEAD').strip() == BRIDGE
    owner = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    name = 'lt212-renderer-' + owner
    label = 'org.libretexts.lt212-owner'
    profile = producer / 'browser-scanner/seccomp_profile.json'
    assert digest(profile) == json.loads((root / 'deploy/stack/bundle.json').read_text())['rendererSeccompSHA256']
    receipt = {'status':'UNACCEPTED', 'source':BRIDGE, 'serverSource':os.environ['GITHUB_SHA'],
               'imageID':loaded['Id'], 'OCIConfigDigest':'sha256:' + config_digest,
               'OCIArchiveSHA256':digest(archive), 'OCIBlobsVerified':blobs,
               'verificationComplete':False, 'shutdownConfirmed':False, 'imageFiles':{}}
    identity = None
    try:
        identity = run('docker', 'create', '--name', name, '--label', label + '=' + owner,
            '--init', '--network', 'none', '--read-only', '--user', '1001:1001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--security-opt', 'seccomp=' + str(profile), '--memory', '2g', '--cpus', '1.5',
            '--pids-limit', '256', '--shm-size', '1g', '--stop-timeout', '30',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m', '-e', 'RUN_BROWSER_TESTS=1',
            '-e', 'NPM_CONFIG_CACHE=/tmp/npm-cache', '--entrypoint', '/bin/sh', loaded['Id'],
            '-c', 'node --version && python3 --version && exec npm test').strip()
        info = json.loads(run('docker', 'inspect', identity))[0]
        assert info['Image'] == loaded['Id'] and info['Config']['Labels'][label] == owner
        for file in ('process-guardian.py', 'guardian_channel.py', 'process-owner.mjs', 'job-storage.mjs', 'server.mjs'):
            raw = subprocess.check_output(['docker','cp',identity + ':/app/' + file,'-'], timeout=30)
            with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                members = tar.getmembers()
                assert len(members) == 1 and members[0].isfile()
                actual = hashlib.sha256(tar.extractfile(members[0]).read()).hexdigest()
            assert actual == digest(producer / 'browser-scanner' / file)
            receipt['imageFiles'][file] = actual
        result = subprocess.run(['docker','start','--attach',identity], capture_output=True, text=True, timeout=600)
        log = result.stdout + result.stderr
        (evidence / 'renderer-thirty-tests.log').write_text(log)
        receipt['runtimeNode'] = next(line for line in result.stdout.splitlines() if re.fullmatch(r'v\d+\.\d+\.\d+', line))
        receipt['runtimePython'] = next(line for line in result.stdout.splitlines() if line.startswith('Python '))
        assert result.returncode == 0
        for field, expected in (('tests',30),('pass',30),('fail',0),('skipped',0)):
            assert re.search(r'^# ' + field + ' ' + str(expected) + r'\s*$', log, re.M), field
        assert json.loads(run('docker','inspect',identity))[0]['State']['ExitCode'] == 0
        receipt.update(testsPassed=True, tests=30, passed=30, skipped=0)
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        try:
            if identity:
                before = json.loads(run('docker','inspect',identity))[0]
                assert before['Config']['Labels'][label] == owner and before['Image'] == loaded['Id']
                run('docker','stop','--time','30',identity, timeout=90)
                final = json.loads(run('docker','inspect',identity))[0]
                receipt['shutdownConfirmed'] = final['State']['Running'] is False and final['State']['Pid'] == 0
                (evidence / 'renderer-container.json').write_text(json.dumps(final,indent=2) + '\n')
                assert receipt['shutdownConfirmed']
        finally:
            receipt['verificationComplete'] = receipt.get('testsPassed') is True and receipt['shutdownConfirmed'] is True
            (evidence / 'renderer-rebuilt-result.json').write_text(json.dumps(receipt,indent=2) + '\n')


if __name__ == '__main__':
    main()
