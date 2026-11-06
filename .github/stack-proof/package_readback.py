"""Verify/import the uploaded UNACCEPTED bytes on a fresh isolated Linux runner."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile

from seal_package import verify_package, unpack_candidate, digest

ROOT = Path.cwd()
OUT = ROOT / '.stack-package-readback'
SOURCE = ROOT / '.stack-downloaded-source'
WRAPPER = ROOT / '.stack-downloaded-candidate'
PACKAGE = ROOT / '.stack-expanded-candidate'


def run(*args, cwd=None, timeout=300):
    return subprocess.check_output(list(map(str,args)),cwd=cwd,text=True,timeout=timeout).strip()


def load(path):
    return json.loads(path.read_text())


def module(path, name):
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('isolated authorized GitHub Linux amd64 runner required')
    OUT.mkdir(mode=0o700)
    receipt = {'serverSource':os.environ['GITHUB_SHA'],'verificationComplete':False,
               'deploymentReady':False,'productionWritesEnabled':False,'imported':{}}
    try:
        receipt['unpack'] = unpack_candidate(WRAPPER,PACKAGE,os.environ['EXPECTED_CANDIDATE_MANIFEST'],os.environ['EXPECTED_CANDIDATE_TAR'])
        receipt['integrity'] = verify_package(PACKAGE,os.environ['EXPECTED_CANDIDATE_MANIFEST'])
        manifest = load(PACKAGE/'manifest.json')
        assert manifest['source']['commit'] == os.environ['GITHUB_SHA']
        SOURCE.mkdir(mode=0o700)
        # verify_package already rejects traversal, links, duplicate and oversized
        # source entries. Copy only regular recorded files, without executing any.
        with tarfile.open(PACKAGE/'source.tar',mode='r:') as tar:
            for item in tar:
                destination = SOURCE / item.name
                if item.isdir():
                    destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with destination.open('xb') as stream:
                        shutil.copyfileobj(tar.extractfile(item),stream)
                    destination.chmod(item.mode & 0o777)
        for name, expected in manifest['source']['fileSHA256'].items():
            assert digest(SOURCE/name) == expected, 'extracted source differs before execution'
        artifacts = SOURCE/'.stack-artifacts';artifacts.mkdir(mode=0o700)
        evidence = SOURCE/'.stack-proof-evidence';evidence.mkdir(mode=0o700)
        for name in ('candidate.json','build-inputs.json'):
            os.link(PACKAGE/'metadata'/name,artifacts/name)
        os.link(PACKAGE/'metadata/staging.json',artifacts/'rehearsal-inputs.json')
        for role in ('server','bridge','renderer'):
            os.link(PACKAGE/'images'/(role+'.oci.tar'),artifacts/(role+'.oci.tar'))
            run('skopeo','copy','--override-os','linux','--override-arch','amd64',
                'oci-archive:'+str(artifacts/(role+'.oci.tar')),'docker-daemon:remedy-'+role+':stack-candidate')
        run('python3',SOURCE/'.github/stack-proof/verify_imports.py',cwd=SOURCE)
        observed = load(evidence/'imports.json')
        assert observed['verificationComplete']
        for role,expected in manifest['imports']['images'].items():
            for field in ('sourceRevision','OCIArchiveSHA256','OCIConfigDigest','filesystemDiffIDs',
                          'runtimeConfigurationSHA256','OCIBlobsVerified'):
                assert observed['images'][role][field] == expected[field],(role,field)
            receipt['imported'][role] = observed['images'][role]
        run('python3',SOURCE/'.github/stack-proof/conductor_artifacts.py',
            '--from-package',PACKAGE/'conductor',cwd=SOURCE)
        consumers = load(evidence/'conductor-imports.json')
        assert consumers['verificationComplete'] and consumers['indexSHA256'] == manifest['conductorIndexSHA256']
        for target,item in consumers['targets'].items():
            original = manifest['conductor'][target]['import']
            for field in ('baseCommit','sourceTree','archiveSHA256','ZIPDigest','sourceConfigDigest',
                          'filesystemDiffIDs','runtimeConfigurationSHA256'):
                assert item[field] == original[field],(target,field)
        receipt['conductorImports'] = consumers
        preflight = module(SOURCE/'deploy/stack/preflight.py','downloaded_preflight')
        policy = load(SOURCE/'deploy/stack/bundle.json')
        runtime = {}
        for role,profile in (('server',SOURCE/'deploy/chromium-seccomp-amd64.json'),
                             ('renderer',SOURCE/'deploy/stack/renderer-seccomp-amd64.json')):
            runtime[role] = preflight.probe(observed['images'][role]['loadedDockerImageID'],role,policy,profile,integration=True)
        assert runtime['server']=='pidfd-subreaper-and-sandboxed-renderer-available'
        assert runtime['renderer']=='sandbox-launch-closed'
        for target,item in consumers['targets'].items():
            value = preflight.probe(item['loadedDockerImageID'],'conductor',policy,None,integration=True,
                command_override=['node','-e',preflight.CONDUCTOR_CRYPTO_PROBE])
            assert value=='compiled-node22-crypto-and-file-credentials-available'
            runtime[target] = value
        for role,reference in (('scanner',policy['scannerImage']),('mongo',preflight.MONGO)):
            run('docker','pull',reference)
            image = json.loads(run('docker','image','inspect',reference))[0]
            preflight.require_registry_manifest(image,reference,role)
            receipt.setdefault('registry',{})[role] = {'reference':reference,'imageID':image['Id'],'RepoDigests':image['RepoDigests']}
            if role == 'scanner':
                baseline = load(PACKAGE/'evidence/result.json')['images']['scanner']
                assert image['Id'] == baseline['id'] and image['RootFS']['Layers'] == baseline['layers']
                uid = baseline['actualRuntimeUid']
                assert type(uid) is int and uid > 0
                runtime['scanner'] = preflight.probe(image['Id'],'scanner',policy,
                    SOURCE/'deploy/stack/scanner-seccomp-amd64.json',integration=True,uid=uid)
                assert runtime['scanner'] == 'sandbox-launch-closed'
        # Recheck that imported readers never modified a hard-linked payload.
        receipt['afterImportIntegrity'] = verify_package(PACKAGE,os.environ['EXPECTED_CANDIDATE_MANIFEST'])
        assert digest(WRAPPER/'package.tar') == os.environ['EXPECTED_CANDIDATE_TAR']
        receipt['runtimeChecks'] = runtime
        receipt['verificationComplete'] = True
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        (OUT/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')


if __name__ == '__main__':
    main()
