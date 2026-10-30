"""Download original Conductor delivery ZIPs; verify bytes before Docker import.

Uses only the current runner's existing ephemeral GitHub token, never a PAT or
cross-repository secret. A 403 is an explicit packaging blocker, not a reason to
rebuild the consumer or substitute its historical candidates.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit
import zipfile

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
        return {'imageID': digest, 'filesystemDiffIDs': layers, 'runtimeConfiguration': config.get('config', {})}


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
            subprocess.run(['docker', 'load', '--input', str(image_path)], check=True, stdout=subprocess.DEVNULL)
            loaded = json.loads(subprocess.check_output(['docker', 'image', 'inspect', pin['imageID']], text=True))[0]
            if loaded['Id'] != source['imageID'] or loaded['RootFS']['Layers'] != source['filesystemDiffIDs']:
                raise ValueError('loaded image differs from verified saved image')
            if loaded['Config'] != source['runtimeConfiguration']:
                raise ValueError('saved-image runtime configuration changed during import')
            receipt['targets'][name] = {'baseCommit': target['baseCommit'], 'sourceTree': target['sourceTree'],
                'artifactID': pin['artifactID'], 'ZIPDigest': pin['artifactDigest'], 'archiveSHA256': pin['archiveSHA256'],
                **source}
        receipt['verificationComplete'] = True
    finally:
        (root / '.stack-proof-evidence/conductor-imports.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
