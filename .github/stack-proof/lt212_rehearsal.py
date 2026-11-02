"""Isolated UNACCEPTED LT212 staging; canonical release inputs/sealer stay intact."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
INPUTS = Path(__file__).with_name('lt212-inputs')
OLD_INDEX = '99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8'
NEW_INDEX = '8e85b978fe3c196756c4ca20c059c1a2bf64863e8162f065a3e935de912b1ed8'
PUBLICATION = '87b0c3f507609be0b2240bd887ee519bb2f9e9b4fad920e71752b6a4ba365d50'
BRIDGE = '98edbdcd63b76d0bc90ef864841fb39073ea7b6f'
CONDUCTOR = '973fa92426814c43400a4ee031f3c854a1dc4933'
RELEASE_PREFIX = 'https://github.com/johnnyrobot/conductor-remedy-patch/releases/download/lt190-conductor-973fa9242681-run41404848931/'
FLAGS = ('deploymentReady', 'productionWritesEnabled', 'liveProvidersVerified',
         'productionSSOVerified', 'releaseOwnerAcceptance')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inputs():
    value = json.loads((INPUTS / 'inputs.json').read_text())
    if (value['status'] != 'UNACCEPTED' or value['securityGate'] != 'LT227_UNMET' or
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
    assets = {item['name']:{'bytes':item['bytes'], 'sha256':item['digest'].removeprefix('sha256:')}
              for item in publication['publishedAssets']}
    if any(item['downloadURL'] != RELEASE_PREFIX + item['name'] for item in publication['publishedAssets']):
        raise ValueError('reviewed public location differs')
    assets['publication-receipt.json'] = {'bytes':(INPUTS / 'publication-receipt.json').stat().st_size,
                                         'sha256':PUBLICATION}
    if value['assets'] != assets or assets['candidate-index.json']['sha256'] != NEW_INDEX:
        raise ValueError('reviewed public byte pins differ')
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
        raise ValueError('baseline or security-blocked locks changed; new validation required')
    bundle_path = stage / 'deploy/stack/bundle.json'
    bundle = json.loads(bundle_path.read_text())
    if bundle['deploymentReady'] is not False or bundle['productionWritesEnabled'] is not False:
        raise ValueError('accepted source cannot become rehearsal evidence')
    changed = ('deploy/stack/bundle.json', 'deploy/stack/conductor-candidates.json',
               'deploy/stack/preflight.py', '.github/stack-proof/conductor_artifacts.py')
    before = {name: digest(stage / name) for name in changed}
    replacements = {}
    for name in changed[2:]:
        text = (stage / name).read_text()
        if text.count(OLD_INDEX) != 1:
            raise ValueError('unknown verifier source; exact pin overlay refused')
        replacements[name] = text.replace(OLD_INDEX, NEW_INDEX)
    bundle.update(bridgeSource=BRIDGE, rendererSource=BRIDGE, conductorMetadataSource=CONDUCTOR,
                  conductorCandidateIndexSHA256=NEW_INDEX,
                  acceptance='UNACCEPTED rehearsal; LT227 audit remains unmet; no release or clean seal')
    bundle_path.write_text(json.dumps(bundle, indent=2) + '\n')
    shutil.copyfile(INPUTS / 'candidate-index.json', stage / changed[1])
    for name, text in replacements.items():
        (stage / name).write_text(text)
    receipt = {'status':'UNACCEPTED', 'securityGate':'LT227_UNMET',
               'bridgeSource':BRIDGE, 'conductorSource':CONDUCTOR,
               'indexSHA256':NEW_INDEX, 'globalFlags':dict.fromkeys(FLAGS, False),
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
        if digest(manifest) != item['deliveryManifestSHA256'] or len(item['patches']) != 35:
            raise ValueError('reviewed 35-patch delivery required')
        for patch in item['patches']:
            if digest(manifest.parent / patch['path']) != patch['sha256']:
                raise ValueError('producer patch changed')
        artifact = destination / (target + '.zip')
        results.append(verifier.verify(index, target, artifact))
        target_dir = destination / 'targets' / target
        target_dir.mkdir(parents=True)
        os.link(artifact, target_dir / 'original-artifact.zip')
    receipt = {'status':'UNACCEPTED', 'securityGate':'LT227_UNMET', 'source':CONDUCTOR,
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
