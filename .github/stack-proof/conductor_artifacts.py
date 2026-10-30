"""Download original Conductor delivery ZIPs; verify bytes before Docker import.

Uses only the current runner's existing ephemeral GitHub token, never a PAT or
cross-repository secret. A 403 is an explicit packaging blocker, not a reason to
rebuild the consumer or substitute its historical candidates.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit
import zipfile
from verify_imports import runtime_configuration

class ArtifactRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected is not None and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            redirected.remove_header('Authorization')
        return redirected


INDEX_SHA256 = '99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_saved_image(path, expected_id):
    with tarfile.open(path, 'r:*') as archive:
        names = archive.getnames()
        if len(names) != len(set(names)):
            raise ValueError('duplicate saved-image entry')
        manifest = json.load(archive.extractfile('manifest.json'))
        if len(manifest) != 1:
            raise ValueError('exactly one saved image required')
        record = manifest[0]
        raw = archive.extractfile(record['Config']).read()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if digest != expected_id:
            raise ValueError('saved-image config digest mismatch')
        config = json.loads(raw)
        if set(config) - {'architecture','os','config','created','history','rootfs'}:
            raise ValueError('unsupported saved-image platform/configuration field')
        if config.get('os') != 'linux' or config.get('architecture') != 'amd64':
            raise ValueError('Linux amd64 saved image required')
        layers = config['rootfs']['diff_ids']
        if len(layers) != len(record['Layers']):
            raise ValueError('saved-image layer count mismatch')
        for name, expected in zip(record['Layers'], layers):
            with archive.extractfile(name) as stream:
                actual = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected:
                raise ValueError('saved-image layer digest mismatch')
        manifest_digest = None
        if 'index.json' in names:
            index = json.load(archive.extractfile('index.json'))
            if index.get('schemaVersion') != 2 or len(index.get('manifests', [])) != 1:
                raise ValueError('one original OCI manifest required')
            descriptor = index['manifests'][0]
            manifest_digest = descriptor['digest']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', manifest_digest):
                raise ValueError('invalid OCI manifest digest')
            manifest_raw = archive.extractfile('blobs/sha256/' + manifest_digest.split(':')[1]).read()
            if 'sha256:' + hashlib.sha256(manifest_raw).hexdigest() != manifest_digest or len(manifest_raw) != descriptor['size']:
                raise ValueError('original OCI manifest digest mismatch')
            oci = json.loads(manifest_raw)
            if oci.get('schemaVersion') != 2 or oci.get('mediaType') != 'application/vnd.oci.image.manifest.v1+json':
                raise ValueError('unsupported original OCI manifest')
            if oci['config']['digest'] != digest or oci['config']['size'] != len(raw):
                raise ValueError('OCI manifest config differs from saved config')
            if len(oci['layers']) != len(layers) or any(layer['mediaType'] != 'application/vnd.oci.image.layer.v1.tar' or layer['digest'] != expected or layer['size'] != archive.getmember(name).size
                for layer,name,expected in zip(oci['layers'],record['Layers'],layers)):
                raise ValueError('OCI manifest layers differ from saved layers')
        runtime_configuration(config.get('config', {}))
        tags = record.get('RepoTags', [])
        if len(tags) != 1 or not isinstance(tags[0], str) or not tags[0]:
            raise ValueError('one verified saved-image reference required')
        return {'imageID': digest, 'sourceConfigDigest': digest, 'sourceManifestDigest':manifest_digest, 'verifiedReference': tags[0],
                'filesystemDiffIDs': layers, 'runtimeConfiguration': config.get('config', {})}


def verify_loaded_image(source, loaded):
    """Map original config to immutable runtime identity, never trusting a tag alone."""
    identity = loaded.get('Id', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', identity):
        raise ValueError('immutable loaded image identity required')
    if identity not in {source['sourceConfigDigest'], source['sourceManifestDigest']}:
        raise ValueError('loaded image is not an original archive identity')
    if loaded.get('Architecture') != 'amd64' or loaded.get('Os') != 'linux' or loaded.get('Variant'):
        raise ValueError('loaded platform differs from saved Linux amd64 image')
    if loaded.get('RootFS') != {'Type':'layers', 'Layers': source['filesystemDiffIDs']}:
        raise ValueError('loaded filesystem differs from verified saved image')
    expected = runtime_configuration(source['runtimeConfiguration'])
    actual = runtime_configuration(loaded['Config'])
    if actual != expected:
        raise ValueError('loaded runtime configuration differs from saved image')
    return {'sourceConfigDigest':source['sourceConfigDigest'], 'loadedDockerImageID':identity,
            'identityChanged': identity != source['sourceConfigDigest'],
            'loadedIdentityKind':'source-config' if identity==source['sourceConfigDigest'] else 'source-OCI-manifest',
            'runtimeConfigurationSHA256':hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'inspectConfiguration':loaded['Config'], 'filesystemDiffIDs':source['filesystemDiffIDs'],
            'configurationRepresentationChanges':{key:{'sourcePresent':key in source['runtimeConfiguration'],
                'source':source['runtimeConfiguration'].get(key),'loadedPresent':key in loaded['Config'],'loaded':loaded['Config'].get(key)}
                for key in set(source['runtimeConfiguration'])|set(loaded['Config'])
                if (key in source['runtimeConfiguration'],source['runtimeConfiguration'].get(key)) != (key in loaded['Config'],loaded['Config'].get(key))}}


def main():
    root = Path.cwd()
    index_path = root / 'deploy/stack/conductor-candidates.json'
    if sha256(index_path) != INDEX_SHA256:
        raise ValueError('authoritative current-candidates index changed')
    index = json.loads(index_path.read_text())
    output = root / '.stack-conductor'
    output.mkdir(mode=0o700)
    receipt = {'indexSHA256': INDEX_SHA256, 'targets': {}, 'verificationComplete': False}
    try:
        for target in index['candidates']:
            pin = target['validation']
            name = target['target']
            destination = output / name
            destination.mkdir()
            archive_zip = destination / 'original-artifact.zip'
            url = 'https://api.github.com/repos/johnnyrobot/conductor-remedy-patch/actions/artifacts/' + str(pin['artifactID']) + '/zip'
            headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
            if os.environ.get('GH_TOKEN'):
                headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
            with build_opener(ArtifactRedirect()).open(Request(url, headers=headers), timeout=120) as response, archive_zip.open('xb') as stream:
                shutil.copyfileobj(response, stream)
            if 'sha256:' + sha256(archive_zip) != pin['artifactDigest']:
                raise ValueError('original artifact ZIP digest mismatch: ' + name)
            # Extract only the known image payload; ZIP paths never become host paths.
            with zipfile.ZipFile(archive_zip) as zipped:
                matches = [info for info in zipped.infolist() if Path(info.filename).name == pin['archive']]
                if len(matches) != 1:
                    raise ValueError('exact saved-image payload absent')
                image_path = destination / pin['archive']
                with zipped.open(matches[0]) as source, image_path.open('xb') as stream:
                    shutil.copyfileobj(source, stream)
            if sha256(image_path) != pin['archiveSHA256']:
                raise ValueError('saved-image archive digest mismatch')
            source = verify_saved_image(image_path, pin['imageID'])
            load = subprocess.run(['docker', 'load', '--input', str(image_path)], capture_output=True, text=True)
            (root / '.stack-proof-evidence' / ('conductor-load-' + name + '.log')).write_text(load.stdout + load.stderr)
            load.check_returncode()
            loaded = json.loads(subprocess.check_output(['docker', 'image', 'inspect', source['verifiedReference']], text=True))[0]
            (root / '.stack-proof-evidence' / ('conductor-inspect-' + name + '.json')).write_text(json.dumps(loaded,indent=2)+'\n')
            mapping = verify_loaded_image(source, loaded)
            # Resolve once more by verified immutable identity, which all launches use.
            immutable = json.loads(subprocess.check_output(['docker','image','inspect',mapping['loadedDockerImageID']],text=True))[0]
            if verify_loaded_image(source, immutable) != mapping:
                raise ValueError('immutable identity lookup changed after verification')
            if source['runtimeConfiguration'].get('Labels',{}).get('org.opencontainers.image.revision') != target['sourceTree']:
                raise ValueError('saved consumer source tree mismatch')
            receipt['targets'][name] = {'baseCommit': target['baseCommit'], 'sourceTree': target['sourceTree'],
                'artifactID': pin['artifactID'], 'ZIPDigest': pin['artifactDigest'], 'archiveSHA256': pin['archiveSHA256'],
                **source, **mapping}
        receipt['verificationComplete'] = True
    finally:
        (root / '.stack-proof-evidence/conductor-imports.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
