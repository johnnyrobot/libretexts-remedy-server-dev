"""Isolated UNACCEPTED LT212 staging; canonical release inputs/sealer stay intact."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
INPUTS = Path(__file__).with_name('lt212-inputs')
OLD_INDEX = '99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8'
NEW_INDEX = '2e1297e9c180af7dce1f2e6894c6afffd0aff20ed71c3434dbccd36f14dc6e29'
PUBLICATION = '6dba464c1554a2c828da5e2419fc772b6cea9342fb93675d221d3a8b3d62d7e8'
BRIDGE = '95a54dd3af850ca8eb5b8bf8be0395f0543c049e'
SECURITY_GATE = 'CLEAN_LOCKED_AUDITS_REQUIRED'
CONDUCTOR = '617187fd7993714ae4d6fb939b30268fb7be6eee'
RELEASE_PREFIX = 'https://github.com/johnnyrobot/conductor-remedy-patch/releases/download/lt128-conductor-617187fd7993-run41451937248/'
FLAGS = ('deploymentReady', 'productionWritesEnabled', 'liveProvidersVerified',
         'productionSSOVerified', 'releaseOwnerAcceptance')
OVERLAY_SHA256 = '7e198bf9d7b4922c4b5220c8350106bd6bcebab6f37b664e0c1a2001a4a4f809'
OVERLAY_FILES = ('.github/stack-proof/full_proof.py', '.github/stack-proof/synthetic_signed_proof.py',
                 'deploy/stack/preflight.py', 'deploy/stack/compose.integration.yml',
                 'deploy/stack/env/renderer.env.example', 'deploy/stack/integration-profile.md')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def materialize_recorded_build(stage, record):
    """Reproduce the built Dockerfile from recorded bases, without re-resolving."""
    path = Path(stage) / 'Dockerfile'
    before = digest(path)
    if before != record['original_dockerfile_sha256']:
        raise ValueError('build source baseline changed')
    stages, lines = set(), []
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'FROM\s+(?:(--platform=\S+)\s+)?(\S+)(?:\s+AS\s+(\S+))?',line,re.I)
        if match:
            platform, image, name = match.groups()
            if image.lower() not in stages:
                identity = record['bases'].get(image)
                if not isinstance(identity,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',identity):
                    raise ValueError('recorded build base missing')
                image = image.split('@')[0] + '@' + identity
            line = 'FROM ' + (platform + ' ' if platform else '') + image + (' AS ' + name if name else '')
            if name: stages.add(name.lower())
        lines.append(line)
    raw = ('\n'.join(lines) + '\n').encode()
    after = hashlib.sha256(raw).hexdigest()
    if after != record['input_sha256']['Dockerfile']:
        raise ValueError('recorded build source output differs')
    path.write_bytes(raw)
    return {'before':before,'after':after}


def inputs():
    value = json.loads((INPUTS / 'inputs.json').read_text())
    if (value['status'] != 'UNACCEPTED' or value['securityGate'] != SECURITY_GATE or
            value['bridgeSource'] != BRIDGE or value['conductorSource'] != CONDUCTOR or
            digest(INPUTS / 'candidate-index.json') != NEW_INDEX or
            digest(INPUTS / 'publication-receipt.json') != PUBLICATION):
        raise ValueError('reviewed rehearsal inputs changed')
    index = json.loads((INPUTS / 'candidate-index.json').read_text())
    if (index['execution']['checkoutCommit'] != CONDUCTOR or
            value['releasePrefix'] != RELEASE_PREFIX or
            any(index.get(key) is not False for key in FLAGS)):
        raise ValueError('rehearsal acceptance flags must be false')
    publication = json.loads((INPUTS / 'publication-receipt.json').read_text())
    assets = {item['name']:{'bytes':item['bytes'], 'sha256':item['sha256']}
              for item in publication['publishedAssets']}
    if any(item['downloadURL'] != RELEASE_PREFIX + item['name'] for item in publication['publishedAssets']):
        raise ValueError('reviewed public location differs')
    assets['acquisition-receipt.json'] = {'bytes':4055, 'sha256':publication['acquisitionReceiptSHA256']}
    assets['publication-receipt.json'] = {'bytes':(INPUTS / 'publication-receipt.json').stat().st_size,
                                         'sha256':PUBLICATION}
    if value['assets'] != assets or assets['candidate-index.json']['sha256'] != NEW_INDEX:
        raise ValueError('reviewed public byte pins differ')
    overlay = value['sourceOverlay']
    if (overlay['path'] != 'renderer-trust.patch' or overlay['sha256'] != OVERLAY_SHA256 or
            digest(INPUTS / overlay['path']) != OVERLAY_SHA256 or set(overlay['files']) != set(OVERLAY_FILES)):
        raise ValueError('reviewed source overlay changed')
    return value


def prepare(stage):
    """Apply exact pin overlays only to a fresh, explicitly named source stage."""
    stage = Path(stage)
    if (stage.name != 'server' or stage.parent.name != '.stack-inputs' or
            stage.is_symlink() or stage.parent.is_symlink() or (stage / '.git').exists()):
        raise ValueError('fresh isolated server stage required')
    marker = stage / 'UNACCEPTED-LT212.json'
    if marker.exists():
        raise ValueError('existing rehearsal stage refused')
    value = inputs()
    if (digest(stage / 'deploy/stack/conductor-candidates.json') != OLD_INDEX or
            digest(stage / 'uv.lock') != value['serverUVLockSHA256'] or
            digest(stage / 'src/project_remedy/html_tools/package-lock.json') != value['serverNodeLockSHA256']):
        raise ValueError('baseline or reviewed locks changed; new validation required')
    bundle_path = stage / 'deploy/stack/bundle.json'
    bundle = json.loads(bundle_path.read_text())
    if bundle['deploymentReady'] is not False or bundle['productionWritesEnabled'] is not False:
        raise ValueError('accepted source cannot become rehearsal evidence')
    overlay = value['sourceOverlay']
    if any(digest(stage / name) != binding['before'] for name, binding in overlay['files'].items()):
        raise ValueError('canonical overlay baseline changed; new validation required')
    changed = tuple(dict.fromkeys(('deploy/stack/bundle.json', 'deploy/stack/conductor-candidates.json',
               'deploy/stack/preflight.py', '.github/stack-proof/conductor_artifacts.py', *OVERLAY_FILES)))
    before = {name: digest(stage / name) for name in changed}
    patch = (INPUTS / overlay['path']).resolve()
    git_environment = os.environ.copy()
    # --no-index still discovers a surrounding checkout and filters its paths.
    # Stop discovery at the stage's parent; never use the caller's Git index.
    git_environment['GIT_CEILING_DIRECTORIES'] = str(stage.parent.resolve())
    for field in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
        git_environment.pop(field, None)
    subprocess.run(['git', 'apply', '--no-index', '--unidiff-zero', '--check', str(patch)], cwd=stage, check=True,
                   env=git_environment, capture_output=True, timeout=30)
    subprocess.run(['git', 'apply', '--no-index', '--unidiff-zero', str(patch)], cwd=stage, check=True,
                   env=git_environment, capture_output=True, timeout=30)
    if any(digest(stage / name) != binding['after'] for name, binding in overlay['files'].items()):
        raise ValueError('source overlay output differs')
    replacements = {}
    for name in ('deploy/stack/preflight.py', '.github/stack-proof/conductor_artifacts.py'):
        text = (stage / name).read_text()
        if text.count(OLD_INDEX) != 1:
            raise ValueError('unknown verifier source; exact pin overlay refused')
        replacements[name] = text.replace(OLD_INDEX, NEW_INDEX)
    bundle.update(bridgeSource=BRIDGE, rendererSource=BRIDGE, conductorMetadataSource=CONDUCTOR,
                  conductorCandidateIndexSHA256=NEW_INDEX,
                  acceptance=value['acceptanceLabel'])
    bundle_path.write_text(json.dumps(bundle, indent=2) + '\n')
    shutil.copyfile(INPUTS / 'candidate-index.json', stage / changed[1])
    for name, text in replacements.items():
        (stage / name).write_text(text)
    if any(digest(stage / name) != binding['stagedAfter'] for name, binding in overlay['files'].items()):
        raise ValueError('final staged source differs from pinned binding')
    receipt = {'status':'UNACCEPTED', 'securityGate':SECURITY_GATE,
               'bridgeSource':BRIDGE, 'conductorSource':CONDUCTOR,
               'indexSHA256':NEW_INDEX, 'globalFlags':dict.fromkeys(FLAGS, False),
               'sourceOverlay':overlay,
               'overlays':{name:{'before':before[name], 'after':digest(stage / name)} for name in changed},
               'canonicalInputsModified':False, 'cleanSealPermitted':False}
    with marker.open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
    return receipt


def acquire(destination, producer):
    """Download exact public released bytes, then use the pinned producer verifier."""
    value = inputs()
    destination, producer = Path(destination), Path(producer)
    if subprocess.check_output(['git', '-C', str(producer), 'rev-parse', 'HEAD'], text=True).strip() != CONDUCTOR:
        raise ValueError('exact producer checkout required')
    destination.mkdir(mode=0o700)
    for name, expected in value['assets'].items():
        if Path(name).name != name or not 0 < expected['bytes'] <= 300 * 1024**2:
            raise ValueError('unsafe released input')
        path = destination / name
        total = 0
        with urlopen(value['releasePrefix'] + name, timeout=120) as source, path.open('xb') as output:
            while block := source.read(min(1024**2, expected['bytes'] + 1 - total)):
                output.write(block)
                total += len(block)
                if total > expected['bytes']:
                    raise ValueError('oversized released input')
        if total != expected['bytes'] or digest(path) != expected['sha256']:
            raise ValueError('released input bytes differ: ' + name)
    index = json.loads((destination / 'candidate-index.json').read_text())
    if subprocess.check_output(['git', '-C', str(producer), 'rev-parse', 'HEAD^{tree}'], text=True).strip() != index['execution']['checkoutTree']:
        raise ValueError('producer source tree differs')
    for name, expected in index['execution']['executionInputs'].items():
        if digest(producer / name) != expected:
            raise ValueError('producer execution source differs: ' + name)
    with zipfile.ZipFile(destination / 'candidate-records.zip') as archive:
        names = archive.namelist()
        if len(names) != 12 or len(set(names)) != 12:
            raise ValueError('producer record inventory differs')
        checksums = archive.read('records-checksums.sha256').decode().splitlines()
        if len([line for line in checksums if line]) != 11:
            raise ValueError('all eleven producer records required')
        checked = set()
        for line in checksums:
            if not line: continue
            expected, name = line.split('  ', 1)
            if name in checked:
                raise ValueError('duplicate producer record checksum')
            checked.add(name)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('producer record checksum mismatch')
        if checked != set(names) - {'records-checksums.sha256'}:
            raise ValueError('unchecked producer record')
    verifier_path = producer / 'tools/verify-candidate-archive.py'
    spec = importlib.util.spec_from_file_location('reviewed_producer_archive', verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    results = []
    for item in index['candidates']:
        target = item['target']
        manifest = producer / item['deliveryManifestPath']
        if digest(manifest) != item['deliveryManifestSHA256'] or len(item['patches']) != 36:
            raise ValueError('reviewed 36-patch delivery required')
        for patch in item['patches']:
            if digest(manifest.parent / patch['path']) != patch['sha256']:
                raise ValueError('producer patch changed')
        artifact = destination / (target + '.zip')
        results.append(verifier.verify(index, target, artifact))
        target_dir = destination / 'targets' / target
        target_dir.mkdir(parents=True)
        os.link(artifact, target_dir / 'original-artifact.zip')
    receipt = {'status':'UNACCEPTED', 'securityGate':SECURITY_GATE, 'source':CONDUCTOR,
               'indexSHA256':NEW_INDEX, 'recordPayloadsVerified':11, 'targets':results,
               'assets':value['assets'], 'producerVerifierSHA256':digest(verifier_path),
               'globalFlags':dict.fromkeys(FLAGS, False)}
    (destination / 'download-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'acquire'))
    parser.add_argument('destination', type=Path)
    parser.add_argument('--producer', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.destination)
    elif args.producer is None:
        parser.error('--producer is required for acquire')
    else:
        acquire(args.destination, args.producer)
