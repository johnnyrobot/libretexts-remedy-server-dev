"""Resolve public build bases once; build from pinned clean source contexts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

root = Path.cwd()
out = root / '.stack-artifacts'
out.mkdir(exist_ok=True)
records = {}
for name in ('server', 'bridge', 'renderer'):
    context = root / '.stack-inputs' / name
    dockerfile = context / 'Dockerfile'
    source = dockerfile.read_text()
    stages, bases, lines = set(), {}, []
    for line in source.splitlines():
        match = re.match(r'FROM\s+(?:(--platform=\S+)\s+)?(\S+)(?:\s+AS\s+(\S+))?$', line, re.I)
        if match:
            platform, image, stage = match.groups()
            if image.lower() not in stages:
                digest = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', image,
                    '--format', '{{.Manifest.Digest}}'], text=True).strip()
                if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
                    raise ValueError('Unresolved base image')
                bases[image] = digest
                image = image.split('@')[0] + '@' + digest
            line = 'FROM ' + (platform + ' ' if platform else '') + image + (' AS ' + stage if stage else '')
            if stage: stages.add(stage.lower())
        lines.append(line)
    dockerfile.write_text('\n'.join(lines) + '\n')
    if name == 'bridge':
        # Canonical Dockerfile and runtime source are retained. Keep test-only
        # private keys and traces outside the candidate build context/layers.
        original = (context / '.dockerignore').read_text()
        (context / 'Dockerfile.dockerignore').write_text(original + '\n**/__tests__\n**/*.test.*\n*.log\n')
    hashes = {}
    for path in ('Dockerfile', 'Dockerfile.dockerignore', 'uv.lock', 'package-lock.json',
                 'deploy/chromium-seccomp-amd64.json', '.dockerignore',
                 'verapdf-installer.zip', 'tools/build-inputs/verapdf-installer.json'):
        file = context / path
        if file.is_file(): hashes[path] = hashlib.sha256(file.read_bytes()).hexdigest()
    for file in context.rglob('package-lock.json'):
        if 'node_modules' not in file.parts: hashes[str(file.relative_to(context))] = hashlib.sha256(file.read_bytes()).hexdigest()
    records[name] = {'bases': bases, 'input_sha256': hashes,
                     'original_dockerfile_sha256': hashlib.sha256(source.encode()).hexdigest()}
(out / 'build-inputs.json').write_text(json.dumps(records, indent=2) + '\n')
