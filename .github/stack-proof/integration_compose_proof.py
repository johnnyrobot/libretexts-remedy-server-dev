"""Exercise the public full-integration Compose package on an isolated Linux runner.

Only external ADAPT/CXone and TLS termination are fixtures. Products, their public
commands and their controls are unchanged. No deployment acceptance is implied.
``verify`` returns (artifact-safe receipt, PRIVATE preflight contexts). Callers
must never serialize the latter into uploaded evidence.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import ssl
import subprocess
import time
import uuid

from evidence import collect_browser_evidence, write_product_log


OWNED = ('remedy-server', 'adapt-scanner', 'remedy-bridge', 'remedy-renderer', 'mongo', 'conductor')
MODES = ('review', 'history', 'production-held')
BASE_FILES = ('docker-compose.yml', 'compose.scanner.yml', 'compose.bridge.yml', 'compose.integration.yml')
MONGO = 'mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'


def prepare_package(root, work):
    """Copy every public file unchanged; generate nonsecret fixture env selections."""
    source = Path(root) / 'deploy/stack'
    package = Path(work) / 'public-compose-package'
    package.mkdir(mode=0o700)
    hashes = {}
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', 'deploy/stack'],
                             capture_output=True, text=True, check=True).stdout.split('\0')
    for name in sorted(name for name in tracked if name):
        original = Path(root) / name
        if original.is_symlink():
            raise ValueError('public package symlink refused')
        if original.is_file():
            relative = original.relative_to(source)
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            if target.read_bytes() != original.read_bytes():
                raise ValueError('public package copy changed')
            hashes[str(relative)] = hashlib.sha256(original.read_bytes()).hexdigest()
    replacements = {
        'https://ollama.com/v1': 'https://provider.invalid/v1',
        'https://REPLACE_WITH_REVIEWED_CONDUCTOR_ORIGIN': 'https://conductor.invalid',
        'https://REPLACE_WITH_AUTHORIZED_ADAPT_HOST': 'http://127.0.0.1:8081',
        'REPLACE_WITH_REVIEWED_CONDUCTOR_HOST,https://REPLACE_WITH_REVIEWED_CONDUCTOR_HOST':
            'conductor.invalid,https://conductor.invalid,https://conductor.invalid:8443',
        'REPLACE_WITH_AUTHORIZED_MAILGUN_DOMAIN': 'fixture.example.invalid',
    }
    for role in ('remedy-server', 'adapt-scanner', 'remedy-bridge', 'renderer', 'conductor'):
        text = (package / 'env' / (role + '.env.example')).read_text()
        for old, new in replacements.items():
            text = text.replace(old, new)
        if 'REPLACE_WITH_' in text:
            raise ValueError('unresolved public fixture metadata')
        target = package / 'env' / (role + '.env')
        target.write_text(text)
        target.chmod(0o600)
    return package, hashes


def prepare_tls(tls_root, fixture, scanner_uid):
    """Prepare the exact role-owned files consumed by the public preflight."""
    tls_root.mkdir(mode=0o700)
    for role, uid in (('server', 999), ('scanner', scanner_uid), ('bridge', 1000), ('conductor', 1000)):
        directory = _private_directory(tls_root / role, uid)
        _private_file(directory / 'ca.pem', uid, (fixture / 'ca.pem').read_bytes())
        if role == 'server':
            for name in ('cert.pem', 'key.pem'):
                _private_file(directory / name, uid, (fixture / name).read_bytes())


def require_terminal_history(body, issuer, jti, epoch):
    proof = body.get('terminal_proof') if isinstance(body, dict) else None
    if (not isinstance(proof, dict) or body.get('outcome') != 'not_attempted' or
            proof.get('contract') != 'cxone-terminal-v1' or proof.get('state') != 'terminal' or
            proof.get('issuer') != issuer or proof.get('jti') != jti or proof.get('trust_epoch') != epoch or
            any(proof.get(field) != body.get(field) for field in ('operation_id', 'action', 'outcome', 'reason', 'audit_recorded')) or
            proof.get('terminal_updated_at') != body.get('updated_at') or
            body.get('audit_recorded') is not None or body.get('requires_reconciliation') is not False or
            not re.fullmatch(r'[a-f0-9]{64}', proof.get('binding_sha256', ''))):
        raise ValueError('actual optional read-only historical lookup failed')


def validate_fixture_overlay(overlay):
    """CI may only add dedicated readonly test inputs to owned services."""
    allowed = {
        'remedy-server': {'/proof/job_state_probe.py'},
        'mongo': {'/run/bootstrap', '/proof/mongo_bootstrap.js'},
        'conductor': {'/fixture', '/proof/conductor_probe.mjs'},
    }
    for role, value in overlay.get('services', {}).items():
        if role not in OWNED:
            if role not in {'external-adapt', 'external-cxone', 'test-tls', 'test-browser'}:
                raise ValueError('unrecognized fixture service')
            continue
        if set(value) != {'volumes'}:
            raise ValueError('CI cannot override owned service configuration')
        for mount in value['volumes']:
            if (mount.get('target') not in allowed.get(role, set()) or
                    mount.get('type') != 'bind' or mount.get('read_only') is not True or
                    mount.get('bind') != {'create_host_path': False}):
                raise ValueError('CI cannot override an owned product mount')


def _bind(source, target, readonly=True):
    return {'type': 'bind', 'source': str(source), 'target': target, 'read_only': readonly,
            'bind': {'create_host_path': False}}


def _private_file(path, uid, content, mode=0o400):
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    path.chmod(mode)
    os.chown(path, uid, uid)


def _private_directory(path, uid):
    path.mkdir(mode=0o700)
    os.chown(path, uid, uid)
    return path


def verify(root, work, evidence, prefix, imports, conductor_imports, fixture, nss_seed, keys, allocate_state):
    """Run all three public profiles for both original compiled target images.

    ``imports`` and ``conductor_imports`` are verified receipt dictionaries.
    ``keys`` maps server/scanner/bridge/renderer to protected UID-owned dirs.
    ``fixture`` contains this run's synthetic ca.pem/cert.pem/key.pem, never the
    CA private key. ``nss_seed`` is the fresh compatible public CA-only NSS seed.
    ``allocate_state(label, uid, budget_bytes)`` allocates dedicated bounded ext4
    state, retained by the caller. No input state is deleted or unmounted here.
    Errors raise after preserving sanitized diagnostics and a false receipt.
    """
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or platform.system() != 'Linux' or
            platform.machine() != 'x86_64'):
        raise RuntimeError('isolated authorized Linux amd64 GitHub runner required')
    root, work, evidence, fixture, nss_seed = map(Path, (root, work, evidence, fixture, nss_seed))
    keys = {role: Path(path) for role, path in keys.items()}
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,70}', prefix):
        raise ValueError('invalid proof prefix')
    if imports.get('verificationComplete') is not True or conductor_imports.get('verificationComplete') is not True:
        raise ValueError('verified immutable import receipts required')
    bundle = json.loads((root / 'deploy/stack/bundle.json').read_text())
    index = json.loads((root / 'deploy/stack/conductor-candidates.json').read_text())
    targets = {item['target']: item for item in index['candidates']}
    if (len(targets) != 2 or set(conductor_imports['targets']) != set(targets) or
            conductor_imports['indexSHA256'] != bundle['conductorCandidateIndexSHA256'] or
            hashlib.sha256((root / 'deploy/stack/conductor-candidates.json').read_bytes()).hexdigest() != conductor_imports['indexSHA256']):
        raise ValueError('both frozen original Conductor targets required')
    evidence.mkdir(exist_ok=True)
    workspace = work / 'public-integration'
    workspace.mkdir(mode=0o700)
    package, hashes = prepare_package(root, workspace)
    receipt = {'verificationComplete': False, 'deploymentReady': False, 'productionWritesEnabled': False,
               'operationalAcceptanceComplete': False, 'configurationHashes': hashes, 'targets': {},
               'scope': 'synthetic exact public Compose; production SSO, providers, target host and storage operational acceptance unverified'}
    (evidence / 'public-integration-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    contexts = []
    sensitive = set()
    source = root / '.github/stack-proof'
    command_number = 0

    def run(*args, check=True, input_text=None, timeout=180, env=None, private_stdout=False):
        nonlocal command_number
        command_number += 1
        result = subprocess.run(list(map(str, args)), input=input_text, capture_output=True, text=True, timeout=timeout, env=env)
        # Keep both streams even on failure; never include argv or raw Env.
        if result.returncode:
            stdout = (f'private stdout bytes={len(result.stdout.encode())} sha256=' +
                      hashlib.sha256(result.stdout.encode()).hexdigest() + '\n') if private_stdout else result.stdout
            write_product_log(evidence / f'public-command-{command_number}.log', stdout + result.stderr, sensitive)
        if check and result.returncode:
            raise RuntimeError(f'public proof command {command_number} failed (exit {result.returncode}); see sanitized log')
        return result

    def safe_error(error):
        message = type(error).__name__ + ': ' + str(error)
        for value in sorted(sensitive, key=len, reverse=True):
            message = message.replace(value, '[synthetic credential redacted]')
        return message[:1600]

    def identity(image):
        value = json.loads(run('docker', 'image', 'inspect', image).stdout)[0]
        if value['Os'] != 'linux' or value['Architecture'] != 'amd64':
            raise ValueError('immutable Linux amd64 image required')
        return value

    images = {role: imports['images'][role]['loadedDockerImageID'] for role in ('server', 'bridge', 'renderer')}
    for role, image in images.items():
        if identity(image)['Id'] != image:
            raise ValueError('import identity changed')
    images['scanner'] = identity(bundle['scannerImage'])['Id']
    images['mongo'] = identity(MONGO)['Id']
    tls_root = workspace / 'tls'
    prepare_tls(tls_root, fixture, keys['scanner'].stat().st_uid)
    frontend_tls = _private_directory(workspace / 'frontend-tls', 1000)
    for name in ('cert.pem', 'key.pem'):
        _private_file(frontend_tls / name, 1000, (fixture / name).read_bytes())
    for directory in keys.values():
        for path in directory.iterdir():
            if path.is_file():
                sensitive.add(path.read_text().strip())
    for name in ('key.pem',):
        sensitive.add((fixture / name).read_text().strip())

    def allocate(label, uid, role):
        return Path(allocate_state('public-' + label, uid, bundle['limits'][role]['stateBytes']))

    def state_hash(directory):
        return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(directory.rglob('*')) if path.is_file() and
                not path.name.endswith('-shm') and not (path.name.endswith('-wal') and path.stat().st_size == 0)}

    try:
        for target, pin in conductor_imports['targets'].items():
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,32}', target):
                raise ValueError('invalid frozen target name')
            if pin['baseCommit'] != targets[target]['baseCommit'] or pin['sourceTree'] != targets[target]['sourceTree']:
                raise ValueError('original Conductor target pin differs')
            conductor_image = pin['loadedDockerImageID']
            if identity(conductor_image)['Id'] != conductor_image:
                raise ValueError('original Conductor image identity differs')
            directory = workspace / target
            directory.mkdir(mode=0o700)
            secret_root = directory / 'secrets'
            secret_root.mkdir(mode=0o700)
            for role, original in keys.items():
                copied = secret_root / role
                shutil.copytree(original, copied)
                uid = original.stat().st_uid
                os.chown(copied, uid, uid)
                copied.chmod(0o700)
                for path in copied.iterdir():
                    if path.is_symlink() or not path.is_file():
                        raise ValueError('protected regular role credentials required')
                    os.chown(path, uid, uid)
                    path.chmod(0o400)
            bootstrap = _private_directory(directory / 'bootstrap', 999)
            mongo_credentials = {'admin': uuid.uuid4().hex, 'application': uuid.uuid4().hex}
            sensitive.update(mongo_credentials.values())
            _private_file(bootstrap / 'credentials.json', 999, json.dumps(mongo_credentials))
            app = {name: uuid.uuid4().hex for name in ('editor', 'auditor', 'outsider', 'password')}
            app.update(projectID='ci00000001', sectionID='158000000000000000000001',
                       pageURL='https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic')
            sensitive.add(app['password'])
            app_root = _private_directory(directory / 'app', 1000)
            browser_root = _private_directory(directory / 'browser-config', 1001)
            _private_file(app_root / 'app.json', 1000, json.dumps(app))
            _private_file(browser_root / 'app.json', 1001, json.dumps(app))
            conductor_keys = _private_directory(secret_root / 'conductor', 1000)
            values = {'session': uuid.uuid4().hex, 'mongo': 'mongodb://conductor:' + mongo_credentials['application'] +
                      '@mongo:27017/conductor_synthetic?authSource=conductor_synthetic',
                      'remedy': (secret_root / 'server/app').read_text().strip(),
                      'openai': 'synthetic-not-real', 'stripe': 'sk_test_synthetic_not_real', 'mailgun': 'synthetic-not-real'}
            sensitive.update(values.values())
            for name, value in values.items():
                _private_file(conductor_keys / name, 1000, value + '\n')
            signer = _private_directory(directory / 'signer', 1000)
            run('node', source / 'signing_fixture.mjs', signer)
            for path in signer.iterdir():
                path.chmod(0o400)
                os.chown(path, 1000, 1000)
            signing = json.loads((signer / 'metadata.json').read_text())
            sensitive.add((signer / 'private.pem').read_text().strip())
            server_state = allocate('server-' + target, 999, 'server')
            mongo_state = allocate('mongo-' + target, 999, 'mongo')
            ledger = allocate('ledger-' + target, 1000, 'bridge')
            fence = allocate('fence-' + target, 1000, 'fence')
            # Provision only empty synthetic historical data via the actual
            # image's ledger protocol. Never edit SQLite or fabricate a status.
            helper_name = prefix + '-public-ledger-' + target.replace('.', '-')
            helper_args = ['docker', 'run', '--name', helper_name, '--rm', '-i', '--network', 'none', '--user', '1000:1000',
                           '--label', 'org.libretexts.stack-proof-owner=' + prefix,
                           '--init', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                           '--cpus', '1', '--memory', '256m', '--pids-limit', '64', '--shm-size', '64m',
                           '--stop-timeout', '30', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
                           '--mount', f'type=bind,src={ledger},dst=/ledger',
                           '--mount', f'type=bind,src={fence},dst=/fence', '--entrypoint', 'python3', images['bridge'],
                           'packages/conductor-panel/server/ledger-helper.py', '--directory', '/ledger',
                           '--fence', '/fence/fence.json', '--epoch', signing['trust_epoch'], '--initialize']
            history_jti = 'A' * 43
            history_claim = {'issuer': signing['issuer'], 'jti': history_jti, 'preview_token': uuid.uuid4().hex,
                             'target': {'hostname': 'dev.libretexts.org', 'page_id': '42'},
                             'binding': {'action': 'cxone.apply'}, 'subject': 'synthetic-history-actor',
                             'expires_at': 4102444800}
            # Each protocol exchange is bounded by the same subprocess timeout;
            # the small controller forwards only public synthetic metadata.
            seed_script = '''import json,select,subprocess,sys
claim_input=json.load(sys.stdin)
p=subprocess.Popen(json.loads(sys.argv[1]),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
def reply():
 assert select.select([p.stdout],[],[],30)[0],'ledger protocol deadline'
 return json.loads(p.stdout.readline())
assert reply()=={'ready':True}
def command(name,data):
 p.stdin.write(json.dumps({'id':name,'command':name,'data':data})+'\\n');p.stdin.flush()
 response=reply();assert 'error' not in response,response
 return response['result']
claim=command('claim',claim_input)
terminal=command('finish',{'operation_id':claim['operation_id'],'outcome':'not_attempted','reason':'pre_dispatch_failure'})
assert terminal['outcome']=='not_attempted'
p.stdin.close();assert p.wait(timeout=20)==0
print(json.dumps({'historySeededViaActualLedger':True,'operationID':terminal['operation_id'],'helperExitCode':0}))
'''
            try:
                seeded = run('python3', '-c', seed_script, json.dumps(helper_args), input_text=json.dumps(history_claim))
            finally:
                # A timed-out controller cannot orphan a helper with store
                # ownership. Match its exact name, owner label and image first.
                helper_ids = run('docker', 'ps', '-a', '--filter', 'name=^/' + helper_name + '$', '--format', '{{.ID}}').stdout.split()
                for identifier in helper_ids:
                    helper = json.loads(run('docker', 'inspect', identifier).stdout)[0]
                    if (helper['Name'] != '/' + helper_name or helper['Image'] != images['bridge'] or
                            helper['Config']['Labels'].get('org.libretexts.stack-proof-owner') != prefix):
                        raise RuntimeError('ledger helper cleanup ownership mismatch')
                    helper_logs = run('docker', 'logs', identifier, check=False)
                    write_product_log(evidence / ('public-ledger-' + target + '.log'), helper_logs.stdout + helper_logs.stderr, sensitive)
                    if helper['State']['Running']:
                        run('docker', 'stop', identifier)
                    # --rm may already have removed it on graceful stop.
                    remaining = run('docker', 'ps', '-a', '--filter', 'name=^/' + helper_name + '$', '--format', '{{.ID}}').stdout.split()
                    if remaining:
                        current = json.loads(run('docker', 'inspect', remaining[0]).stdout)[0]
                        if current['Id'] != helper['Id']:
                            raise RuntimeError('ledger helper identity changed during cleanup')
                        run('docker', 'rm', current['Id'])
            seed_result = json.loads(seeded.stdout)
            target_receipt = {'loadedDockerImageID': conductor_image, 'baseCommit': pin['baseCommit'],
                              'sourceTree': pin['sourceTree'], 'profiles': {}, 'complete': False,
                              'historyFixture': seed_result,
                              'historicalFixtureSource': 'actual-ledger-helper-synthetic-seed',
                              'endToEndSignedRecoveryProvenByHistoryFixture': False}
            receipt['targets'][target] = target_receipt
            browser_evidence = directory / ('browser-' + target)
            browser_evidence.mkdir(mode=0o700)
            os.chown(browser_evidence, 1001, 1001)
            for mode in MODES:
                _run_profile(root=root, directory=directory, package=package, evidence=evidence, prefix=prefix,
                             target=target, mode=mode, images=images, conductor_image=conductor_image,
                             scanner_image=bundle['scannerImage'], bundle=bundle, tls_root=tls_root,
                             frontend_tls=frontend_tls, fixture=fixture, nss_seed=nss_seed,
                             secret_root=secret_root, bootstrap=bootstrap, app_root=app_root,
                             browser_root=browser_root, browser_evidence=browser_evidence,
                             server_state=server_state, mongo_state=mongo_state, ledger=ledger, fence=fence,
                             signer=signer, signing=signing, history_jti=history_jti, run=run,
                             sensitive=sensitive, target_receipt=target_receipt, contexts=contexts,
                             state_hash=state_hash, allocate=allocate, conductor_targets=conductor_imports['targets'])
            target_receipt['complete'] = all(target_receipt['profiles'].get(mode, {}).get('complete') is True for mode in MODES)
        receipt['verificationComplete'] = len(receipt['targets']) == 2 and all(v['complete'] for v in receipt['targets'].values())
        if not receipt['verificationComplete']:
            raise RuntimeError('public integration proof incomplete; release flags remain false')
    except Exception as error:
        receipt['error'] = safe_error(error)
        raise RuntimeError(receipt['error']) from None
    finally:
        (evidence / 'public-integration-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt, contexts


def _run_profile(*, root, directory, package, evidence, prefix, target, mode, images, conductor_image,
                 scanner_image, bundle, tls_root, frontend_tls, fixture, nss_seed, secret_root, bootstrap,
                 app_root, browser_root, browser_evidence, server_state, mongo_state, ledger, fence,
                 signer, signing, history_jti, run, sensitive, target_receipt, contexts, state_hash,
                 allocate, conductor_targets):
    """One Compose project's lifetime; preserve state and own exact cleanup."""
    project = prefix + '-public-' + target.replace('.', '-') + '-' + mode
    network = project + '_remedy'
    owner = uuid.uuid4().hex
    source = root / '.github/stack-proof'
    selected = list(BASE_FILES)
    if mode != 'review':
        selected.append('compose.history.yml')
    if mode == 'production-held':
        selected.append('compose.signed.yml')
    interpolation = {
        'REMEDY_SERVER_IMAGE': images['server'], 'REMEDY_BRIDGE_IMAGE': images['bridge'],
        'REMEDY_RENDERER_IMAGE': images['renderer'], 'REMEDY_CONDUCTOR_IMAGE': conductor_image,
        'REMEDY_STATE_ROOT': str(server_state), 'REMEDY_SECRET_ROOT': str(secret_root),
        'REMEDY_TLS_ROOT': str(tls_root), 'REMEDY_NSS_SEED_ROOT': str(nss_seed),
        'REMEDY_MONGO_STATE_ROOT': str(mongo_state), 'REMEDY_BRIDGE_STATE_ROOT': str(ledger),
        'REMEDY_FENCE_ROOT': str(fence),
        'REMEDY_SERVER_SECCOMP_FILE': str(root / 'deploy/chromium-seccomp-amd64.json'),
        'REMEDY_SCANNER_SECCOMP_FILE': str(root / 'deploy/stack/scanner-seccomp-amd64.json'),
        'REMEDY_RENDERER_SECCOMP_FILE': str(package / 'renderer-seccomp-amd64.json'),
        'REMEDY_BRIDGE_PROFILE': 'full-write' if mode == 'production-held' else 'review-only',
        'REMEDY_OPERATION_STATUS_ISSUER': signing['issuer'], 'REMEDY_REVIEWER_TRUST_EPOCH': signing['trust_epoch'],
        'REMEDY_REVIEWER_KEYRING_PATH': str(signer / 'production.json'),
        'REMEDY_REVIEWER_SIGNING_KEY_PATH': str(signer / 'private.pem'), 'REMEDY_REVIEWER_KEY_ID': signing['kid'],
        'REMEDY_REVIEWER_ISSUER': signing['issuer'], 'REMEDY_REVIEWER_AUDIENCE': signing['audience'],
        'REMEDY_REVIEWER_KEY_ENABLED': 'true', 'REMEDY_REVIEWER_KEY_NOT_BEFORE': '0',
        'REMEDY_REVIEWER_KEY_NOT_AFTER': '4102444800',
    }
    env_file = directory / (mode + '-interpolation.env')
    env_file.write_text(''.join(f'{name}={value}\n' for name, value in interpolation.items()))
    env_file.chmod(0o600)
    common = {'image': images['server'], 'user': '999:999', 'init': True, 'read_only': True,
              'restart': 'no', 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
              'cpus': 1, 'mem_limit': '256m', 'pids_limit': 64, 'shm_size': '64m',
              'stop_grace_period': '30s', 'tmpfs': ['/tmp:rw,nosuid,nodev,size=64m'], 'dns': ['127.0.0.1']}
    external_adapt = {**common, 'entrypoint': ['python', '/proof/external.py', '--kind', 'adapt'],
                      'volumes': [_bind(source / 'external.py', '/proof/external.py')],
                      'network_mode': 'service:adapt-scanner'}
    del external_adapt['dns']
    browser = {**common, 'image': images['renderer'], 'user': '1001:1001', 'cpus': 1.5, 'mem_limit': '2g',
               'pids_limit': 256, 'shm_size': '1g', 'tmpfs': ['/tmp:rw,nosuid,nodev,size=512m'],
               'security_opt': ['no-new-privileges:true', 'seccomp=' + str(package / 'renderer-seccomp-amd64.json')],
               'environment': {'HOME': '/tmp/renderer-home'},
               'entrypoint': ['sh', '/opt/remedy-bundle/browser-home.sh', 'node', '/proof/conductor_browser.mjs'],
               'volumes': [_bind(package / 'browser-home.sh', '/opt/remedy-bundle/browser-home.sh'),
                           _bind(source / 'conductor_browser.mjs', '/proof/conductor_browser.mjs'),
                           _bind(browser_root, '/fixture'), _bind(nss_seed, '/run/certificates/nss-seed'),
                           _bind(browser_evidence, '/browser-evidence', False)], 'networks': ['remedy']}
    overlay = {'services': {
        'remedy-server': {'volumes': [_bind(source / 'job_state_probe.py', '/proof/job_state_probe.py')]},
        'external-adapt': external_adapt,
        'external-cxone': {**common, 'entrypoint': ['python', '/proof/external.py', '--kind', 'cxone'],
                           'volumes': [_bind(source / 'external.py', '/proof/external.py'), _bind(fixture, '/fixtures')],
                           'networks': {'remedy': {'ipv4_address': '203.0.113.10', 'aliases': ['dev.libretexts.org']}}},
        'mongo': {'volumes': [_bind(bootstrap, '/run/bootstrap'), _bind(source / 'mongo_bootstrap.js', '/proof/mongo_bootstrap.js')]},
        'conductor': {'volumes': [_bind(app_root, '/fixture'), _bind(source / 'conductor_probe.mjs', '/proof/conductor_probe.mjs')]},
        'test-tls': {**common, 'image': conductor_image, 'user': '1000:1000',
                     'entrypoint': ['node', '/proof/tls_proxy.mjs'],
                     'volumes': [_bind(source / 'tls_proxy.mjs', '/proof/tls_proxy.mjs'), _bind(frontend_tls, '/fixtures')],
                     'networks': {'remedy': {'aliases': ['conductor.invalid']}}},
        'test-browser': browser,
    }, 'networks': {'remedy': {'internal': True, 'ipam': {'config': [{'subnet': '203.0.113.0/24'}]},
                              'labels': {'org.libretexts.stack-proof-owner': owner}}}}
    validate_fixture_overlay(overlay)
    overlay_path = directory / (mode + '-external.json')
    overlay_path.write_text(json.dumps(overlay))
    overlay_path.chmod(0o600)
    compose_args = ['docker', 'compose', '--project-name', project, '--env-file', str(env_file)]
    for name in selected:
        compose_args += ['-f', str(package / name)]
    public_compose_args = list(compose_args)
    compose_args += ['-f', str(overlay_path)]

    # Host variables take precedence over --env-file. Exclude only our explicit
    # interpolation names on every call without changing the caller environment.
    compose_environment = {name: value for name, value in os.environ.items() if name not in interpolation}

    def compose(*args, interpolation_file=None, **kwargs):
        arguments = list(compose_args)
        if interpolation_file is not None:
            arguments[arguments.index('--env-file') + 1] = str(interpolation_file)
        return run(*arguments, *args, env=compose_environment, **kwargs)

    config_path = directory / (mode + '-resolved-public-private.json')
    actual_config_path = directory / (mode + '-resolved-ci-private.json')
    config_path.write_text(run(*public_compose_args, 'config', '--format', 'json',
                               env=compose_environment, private_stdout=True).stdout)
    config_path.chmod(0o600)
    actual_config_path.write_text(compose('config', '--format', 'json', private_stdout=True).stdout)
    actual_config_path.chmod(0o600)
    config = json.loads(config_path.read_text())
    actual_config = json.loads(actual_config_path.read_text())
    test_mounts = {'remedy-server': {'/proof/job_state_probe.py'},
                   'mongo': {'/run/bootstrap', '/proof/mongo_bootstrap.js'},
                   'conductor': {'/fixture', '/proof/conductor_probe.mjs'}}
    for role in OWNED:
        if config['services'][role].get('ports'):
            raise ValueError('public profile published a port')
        public_service = dict(config['services'][role])
        actual_service = dict(actual_config['services'][role])
        actual_service['volumes'] = [mount for mount in actual_service.get('volumes', [])
                                     if mount['target'] not in test_mounts.get(role, set())]
        if actual_service != public_service:
            raise ValueError('CI changed owned public service configuration: ' + role)
    context = {'target': target, 'mode': mode, 'project': project, 'config_path': config_path,
               'public_config_path': config_path, 'actual_config_path': actual_config_path,
               'package_root': package, 'renderer_seccomp': package / 'renderer-seccomp-amd64.json',
               'state_root': server_state, 'mongo_state_root': mongo_state, 'bridge_state_root': ledger,
               'fence_root': fence, 'secret_root': secret_root, 'tls_root': tls_root, 'nss_seed_root': nss_seed,
               'selected_files': tuple(package / name for name in selected), 'interpolation_file': env_file}
    contexts.append(context)
    profile = {'complete': False, 'publicComposeFiles': selected,
               'resolvedConfigurationSHA256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
               'actualResolvedConfigurationSHA256': hashlib.sha256(actual_config_path.read_bytes()).hexdigest(),
               'ownedConfigurationPreserved': True,
               'approvedCIDifferences': {
                   'readonlyTestMounts': {role: sorted(mounts) for role, mounts in test_mounts.items()},
                   'externalFixtureServices': ['external-adapt', 'external-cxone', 'test-tls', 'test-browser'],
                   'internalTestNetworkSubnet': '203.0.113.0/24',
                   'fixtureAliases': {'external-cxone': ['dev.libretexts.org'], 'test-tls': ['conductor.invalid']},
                   'externalAdaptSharesScannerNetworkNamespace': True},
               'containers': {}, 'shutdown': {}, 'externalMutations': None}
    target_receipt['profiles'][mode] = profile
    rule = None
    containers = {}
    created = False
    passed = False

    def inspect(role):
        identifier = compose('ps', '--all', '--quiet', role).stdout.strip()
        if not identifier or '\n' in identifier:
            raise RuntimeError('one exact project container required for ' + role)
        value = json.loads(run('docker', 'inspect', identifier).stdout)[0]
        labels = value['Config']['Labels']
        if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') != role:
            raise RuntimeError('project container ownership mismatch')
        containers[role] = value['Id']
        return value

    def request(role, port, path, body=None, key=None, control=False, tls=False):
        value = inspect(role)
        address = value['NetworkSettings']['Networks'][network]['IPAddress']
        connection = http.client.HTTPConnection(address, port, timeout=150)
        if tls:
            connection.connect()
            connection.sock = ssl.create_default_context(cafile=str(fixture / 'ca.pem')).wrap_socket(
                connection.sock, server_hostname='remedy-server')
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['X-Fixture-Control' if control else 'X-API-Key'] = key
        try:
            connection.request('POST' if body is not None else 'GET', path,
                               json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw)
        finally:
            connection.close()

    def wait(role, port, path='/healthz', key=None, control=False, tls=False, expected=200):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if not inspect(role)['State']['Running']:
                raise RuntimeError(role + ' exited before readiness')
            try:
                status, value = request(role, port, path, key=key, control=control, tls=tls)
                if status == expected:
                    return value
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(.2)
        raise RuntimeError('public profile readiness deadline: ' + role)

    def probe(phase, label=None):
        result = run('docker', 'exec', inspect('conductor')['Id'], 'node', '/opt/remedy-bundle/secret-env.mjs',
                     'conductor', 'node', '/proof/conductor_probe.mjs', phase, check=False)
        suffix = '-' + label if label else ''
        write_product_log(evidence / f'public-{target}-{mode}{suffix}-probe.log', result.stdout + result.stderr, sensitive)
        if result.returncode:
            raise RuntimeError('actual public compiled Conductor probe failed; see sanitized log')
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        if observed.get('passed') is not True:
            raise RuntimeError('actual compiled consumer did not pass')
        if label:
            profile.setdefault('operationalConsumerProbes', {})[label] = observed
        else:
            profile['consumer'] = observed
        return observed

    server_key = (secret_root / 'server/app').read_text().strip()
    scanner_key = (secret_root / 'scanner/api').read_text().strip()
    before_history = (state_hash(ledger), state_hash(fence)) if mode == 'history' else None
    try:
        created = True
        compose('create')
        info = json.loads(run('docker', 'network', 'inspect', network).stdout)[0]
        if (not info['Internal'] or info['Labels'].get('com.docker.compose.project') != project or
                info['Labels'].get('org.libretexts.stack-proof-owner') != owner):
            raise RuntimeError('private Compose network ownership mismatch')
        interface = info['Options'].get('com.docker.network.bridge.name', 'br-' + info['Id'][:12])
        rule = ['INPUT', '-i', interface, '-m', 'conntrack', '!', '--ctstate', 'ESTABLISHED,RELATED',
                '-m', 'comment', '--comment', owner, '-j', 'DROP']
        run('iptables', '-I', *rule)
        compose('up', '-d', '--no-deps', 'mongo', 'remedy-server', 'remedy-renderer', 'external-cxone')
        deadline = time.monotonic() + 60
        while run('docker', 'exec', inspect('mongo')['Id'], 'mongosh', '--quiet', '--eval',
                  'db.adminCommand({ping:1}).ok', check=False).stdout.strip() != '1':
            if time.monotonic() >= deadline:
                raise RuntimeError('authenticated Mongo startup deadline')
            time.sleep(.2)
        if mode == 'review':
            initialized = run('docker', 'exec', inspect('mongo')['Id'], 'mongosh', '--quiet', '--norc', '/proof/mongo_bootstrap.js')
            write_product_log(evidence / f'public-{target}-mongo-bootstrap.log', initialized.stdout + initialized.stderr, sensitive)
            profile['authenticatedMongoBootstrap'] = True
        wait('remedy-server', 8000, '/readyz', tls=True)
        wait('remedy-renderer', 5180)
        wait('external-cxone', 8082, '/control/status', key='synthetic-control-only', control=True)
        compose('up', '-d', '--no-deps', 'adapt-scanner', 'remedy-bridge')
        wait('adapt-scanner', 5176)
        compose('up', '-d', '--no-deps', 'external-adapt')
        wait('adapt-scanner', 8081, '/control/status', key='synthetic-control-only', control=True)
        code, scan = request('adapt-scanner', 5176, '/v1/adapt/scan', {'mode': 'question', 'id': 101}, scanner_key)
        if code != 200 or not scan['results'][0]['findings'] or scan['results'][0]['capturedBytes'] <= 0:
            raise RuntimeError('actual public Scanner/TLS Server scan failed')
        profile['actualScannerAgainstTLSserver'] = True
        health = wait('remedy-server', 8000, '/v1/cxone/health', key=server_key, tls=True,
                      expected=503 if mode == 'production-held' else 200)
        if (health['profile']['name'] != ('full-write' if mode == 'production-held' else 'review-only') or
                health['capabilities']['scan'] is not True or health['capabilities']['preview'] is not True or
                health['capabilities']['mutate'] is not False):
            raise RuntimeError('public required read capabilities or mutation hold failed')
        if health['capabilities']['operation_status'] is not (mode != 'review'):
            raise RuntimeError('public history capability disagrees with selected overlay')
        profile['readiness'] = {'status': 503 if mode == 'production-held' else 200,
                                'profile': health['profile']['name'], 'capabilities': health['capabilities']}
        compose('up', '-d', '--no-deps', 'conductor')
        wait('conductor', 5000, '/health')
        probe(mode)
        if mode == 'history':
            code, historical = request('remedy-server', 8000, '/v1/cxone/page/operation-status',
                                       {'issuer': signing['issuer'], 'jti': history_jti}, server_key, tls=True)
            if code != 200:
                raise RuntimeError('actual optional read-only historical lookup failed')
            require_terminal_history(historical, signing['issuer'], history_jti, signing['trust_epoch'])
            code, missing = request('remedy-server', 8000, '/v1/cxone/page/operation-status',
                                    {'issuer': signing['issuer'], 'jti': 'B' * 42 + 'A'}, server_key, tls=True)
            if code != 404 or missing.get('error') != 'operation_not_found':
                raise RuntimeError('missing history was not preserved as unknown')
            profile['history'] = {'actualHistoricalTerminalRead': True, 'signerAbsent': True,
                                  'missingLookupStatus': 404, 'missingIsNoWriteProof': False}
        for role in OWNED:
            value = inspect(role)
            host, actual = value['HostConfig'], value['Config']
            logical = {'remedy-server': 'server', 'adapt-scanner': 'scanner', 'remedy-bridge': 'bridge',
                       'remedy-renderer': 'renderer', 'mongo': 'mongo', 'conductor': 'conductor'}[role]
            limits = bundle['limits'][logical]
            expected_image = conductor_image if role == 'conductor' else images[logical]
            if (value['Image'] != expected_image or host.get('PortBindings') or not host['ReadonlyRootfs'] or
                    not host['Init'] or host['CapDrop'] != ['ALL'] or
                    not any(opt in {'no-new-privileges', 'no-new-privileges:true'} for opt in host['SecurityOpt']) or
                    host['Memory'] != limits['memoryBytes'] or host['NanoCpus'] != int(limits['cpus'] * 10**9) or
                    host['PidsLimit'] != limits['pids'] or actual['StopTimeout'] != limits['stopSeconds']):
                raise RuntimeError('public product identity or runtime controls differ: ' + role)
            expected_shm = limits.get('shmBytes', 64 * 1024**2)
            if host['ShmSize'] != expected_shm:
                raise RuntimeError('public product shared-memory limit differs: ' + role)
            status = dict(line.split(':', 1) for line in run('docker', 'exec', value['Id'], 'cat', '/proc/1/status').stdout.splitlines() if ':' in line)
            uid = int(status['Uid'].split()[1])
            expected_uid = {'server': 999, 'bridge': 1000, 'renderer': 1001, 'mongo': 999, 'conductor': 1000,
                            'scanner': (secret_root / 'scanner').stat().st_uid}[logical]
            if (uid != expected_uid or uid == 0 or int(status['CapEff'].strip(), 16) != 0 or
                    status['NoNewPrivs'].strip() != '1' or status['Seccomp'].strip() != '2'):
                raise RuntimeError('public nonroot kernel sandbox differs: ' + role)
            destinations = {mount['Destination'] for mount in value['Mounts']}
            if role != 'conductor' and '/run/signing/private.pem' in destinations:
                raise RuntimeError('private reviewer signing material exposed to another role')
            if mode == 'review' and role == 'remedy-bridge' and destinations & {'/ledger', '/fence', '/run/reviewer/keyring.json'}:
                raise RuntimeError('review startup unexpectedly needs writer/history inputs')
            if mode != 'production-held' and role == 'conductor' and '/run/signing/private.pem' in destinations:
                raise RuntimeError('optional rollout unexpectedly needs signer')
            profile['containers'][role] = {'id': value['Id'], 'imageID': value['Image'], 'uid': uid,
                                           'capEff': 0, 'noNewPrivileges': True, 'seccomp': 2,
                                           'memoryBytes': host['Memory'], 'nanoCpus': host['NanoCpus'],
                                           'pidLimit': host['PidsLimit'], 'shmBytes': host['ShmSize'],
                                           'stopSeconds': actual['StopTimeout'], 'readOnlyRoot': True}
        if inspect('remedy-bridge')['HostConfig']['NetworkMode'] != 'container:' + inspect('remedy-server')['Id']:
            raise RuntimeError('Bridge public shared namespace changed')
        if mode == 'review':
            compose('up', '-d', '--no-deps', 'test-tls')
            deadline = time.monotonic() + 30
            while run('docker', 'exec', inspect('remedy-server')['Id'], 'curl', '--cacert', '/run/tls/ca.pem',
                      '-fsS', 'https://conductor.invalid:8443/health', check=False).returncode:
                if time.monotonic() >= deadline:
                    raise RuntimeError('actual compiled frontend private TLS readiness deadline')
                time.sleep(.2)
            # Test fixture owns only TLS termination. Browser assertions require
            # the actual compiled app and its actual secure session cookies.
            compose('up', '-d', '--no-deps', 'test-browser')
            browser_id = inspect('test-browser')['Id']
            if run('docker', 'wait', browser_id).stdout.strip() != '0':
                raise RuntimeError('actual compiled UI test failed; see sanitized browser evidence')
            logs = run('docker', 'logs', browser_id)
            browser_result = json.loads(logs.stdout.strip().splitlines()[-1])
            if browser_result.get('passed') is not True:
                raise RuntimeError('actual compiled UI did not pass')
            profile['browser'] = browser_result
        if before_history is not None and before_history != (state_hash(ledger), state_hash(fence)):
            raise RuntimeError('optional read-only history changed ledger or independent fence')
        if before_history is not None:
            profile['history'].update(durableLedgerAndFenceUnchanged=True, sqliteTransientCoordinationAllowed=True)
        if mode == 'production-held':
            profile['operations'] = {'complete': False}
            _operational_rehearsal(
                root=root, directory=directory, evidence=evidence, target=target, project=project,
                interpolation=interpolation, public_compose_args=public_compose_args,
                compose_environment=compose_environment, compose=compose, inspect=inspect, request=request,
                wait=wait, probe=probe, run=run, sensitive=sensitive, bundle=bundle, context=context,
                allocate=allocate, conductor_targets=conductor_targets, current_image=conductor_image,
                server_state=server_state, ledger=ledger, mongo_state=mongo_state, fence=fence,
                signing=signing, signer=signer, secret_root=secret_root, tls_root=tls_root,
                nss_seed=nss_seed, fixture=fixture, frontend_tls=frontend_tls, server_key=server_key,
                history_jti=history_jti, result=profile['operations'], expected_runtime=profile['containers'])
        code, counter = request('external-cxone', 8082, '/control/status', key='synthetic-control-only', control=True)
        if code != 200 or counter['mutations'] != 0:
            raise RuntimeError('unexpected external mutation in public production proof')
        profile['externalMutations'] = 0
        passed = True
    finally:
        errors = []
        if created:
            try:
                if inspect('external-cxone')['State']['Running']:
                    status, counter = request('external-cxone', 8082, '/control/status', key='synthetic-control-only', control=True)
                    if status != 200:
                        raise RuntimeError('external mutation counter unavailable')
                    profile['externalMutations'] = counter['mutations']
                    if counter['mutations'] != 0:
                        errors.append('external mutation attempts observed')
            except Exception as error:
                # A startup failure is still a failed proof; absence of a
                # measurement never becomes an asserted zero.
                profile['externalMutationCounterError'] = str(error)
                passed = False
            # ps does not expose Env. Inspect only exact returned IDs and verify
            # both Compose labels before stopping/removing any container.
            ids = compose('ps', '--all', '--quiet', check=False).stdout.split()
            approved = []
            for identifier in ids:
                try:
                    value = json.loads(run('docker', 'inspect', identifier).stdout)[0]
                    labels = value['Config']['Labels']
                    role = labels.get('com.docker.compose.service')
                    if labels.get('com.docker.compose.project') != project or role not in {*OWNED, 'external-adapt', 'external-cxone', 'test-tls', 'test-browser'}:
                        raise RuntimeError('cleanup ownership mismatch')
                    approved.append((identifier, role))
                except Exception as error:
                    errors.append(str(error))
            for identifier, role in sorted(approved, key=lambda item: {
                    'test-browser': 0, 'test-tls': 1, 'conductor': 2, 'adapt-scanner': 3,
                    'external-adapt': 4, 'remedy-bridge': 5, 'remedy-renderer': 6,
                    'remedy-server': 7, 'mongo': 8, 'external-cxone': 9}[item[1]]):
                try:
                    run('docker', 'stop', identifier)
                    value = json.loads(run('docker', 'inspect', identifier).stdout)[0]
                    logs = run('docker', 'logs', identifier, check=False)
                    write_product_log(evidence / f'public-{target}-{mode}-{role}.log', logs.stdout + logs.stderr, sensitive)
                    exit_code = value['State']['ExitCode']
                    profile['shutdown'][role] = exit_code
                    allowed = {143} if role in {'remedy-server', 'external-adapt', 'external-cxone'} else {0}
                    # Created but deliberately unused test infra has never run.
                    if value['State']['Status'] == 'created':
                        allowed = {0}
                    run('docker', 'rm', identifier)
                    if exit_code not in allowed:
                        raise RuntimeError(f'{role} shutdown exit {exit_code}; expected {sorted(allowed)}')
                    if role in OWNED and value['State']['Status'] != 'created':
                        state = value['State']
                        if (state['Status'] != 'exited' or state.get('Error') != '' or
                                any(state.get(field, True) for field in ('Running', 'Paused', 'Restarting', 'Dead', 'OOMKilled'))):
                            raise RuntimeError('final owned product shutdown state failed: ' + role)
                        if role == 'remedy-server' and 'Application shutdown complete' not in logs.stdout + logs.stderr:
                            raise RuntimeError('final Server lifespan completion unavailable')
                        profile.setdefault('shutdownEvidence', {})[role] = {'oomKilled': False, 'errorEmpty': True,
                                                                           'exited': True, 'rawExitCode': exit_code}
                except Exception as error:
                    errors.append(str(error))
            # Do not use compose down: remove only our own exact verified empty
            # network, never anonymous volumes or a name-matched foreign object.
            try:
                info = json.loads(run('docker', 'network', 'inspect', network).stdout)[0]
                if info['Labels'].get('com.docker.compose.project') != project or info['Labels'].get('org.libretexts.stack-proof-owner') != owner:
                    raise RuntimeError('cleanup network ownership mismatch')
                if not info.get('Containers'):
                    run('docker', 'network', 'rm', info['Id'])
            except Exception as error:
                errors.append(str(error))
        if rule is not None:
            if run('iptables', '-D', *rule, check=False).returncode:
                errors.append('owned input rule cleanup failed')
        browser_output = evidence / f'public-browser-{target}-{mode}'
        browser_output.mkdir(exist_ok=True)
        collect_browser_evidence(directory, browser_output, (target,), sensitive)
        profile['complete'] = passed and not errors
        if errors:
            profile['cleanupErrors'] = errors
            raise RuntimeError('public profile cleanup or graceful shutdown failed; see receipt')


def _operational_rehearsal(*, root, directory, evidence, target, project, interpolation,
                          public_compose_args, compose_environment, compose, inspect, request, wait, probe,
                          run, sensitive, bundle, context, allocate, conductor_targets, current_image,
                          server_state, ledger, mongo_state, fence, signing, signer, secret_root, tls_root,
                          nss_seed, fixture, frontend_tls, server_key, history_jti, result, expected_runtime):
    """Cold-clone actual stores, reopen them, and alternate only owned binaries.

    All raw data, plans and archives stay in operator-owned private WORK. The
    receipt reports hashes and observations; it never promotes CLI admission or
    cleanup flags into application acceptance.
    """
    result.update(scope='owned-Remedy-feature-compatibility', complete=False,
                  productionSSOVerified=False, entireUpstreamProductionCompatibilityVerified=False,
                  historicalFixtureSource='actual-ledger-helper-synthetic-seed',
                  endToEndSignedRecoveryProvenByHistoryFixture=False)
    private = directory / 'cold-operations'
    private.mkdir(mode=0o700)
    if private.stat().st_uid != 0 or private.stat().st_mode & 0o077:
        raise RuntimeError('root-owned private operational output directory required')
    fence_path = fence / 'fence.json'

    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def private_json(name, value):
        path = private / name
        path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
        path.chmod(0o600)
        return path

    def job(mode, witness=None):
        args = ['docker', 'exec']
        if witness is not None:
            args.append('-i')
        args += [inspect('remedy-server')['Id'], 'node', '/opt/remedy-bundle/secret-env.mjs',
                 'server', 'python', '/proof/job_state_probe.py', mode]
        observed = run(*args, input_text=json.dumps(witness) if witness is not None else None, private_stdout=True)
        value = json.loads(observed.stdout.strip().splitlines()[-1])
        public = {key: value[key] for key in ('jobID', 'inputSHA256', 'outputSHA256', 'options',
                  'postCount', 'genuineDOCXParsed', 'persistedOptionsUnchanged', 'postRepeated') if key in value}
        write_product_log(evidence / f'public-{target}-office-{mode}-{len(result.get("stages", []))}.log',
                          json.dumps(public) + '\n' + observed.stderr, sensitive)
        return value

    # No session cookie or password is printed. This witness reads immutable
    # collections through the actual authenticated driver and also exercises the
    # product's authenticated public history route using a real fallback session.
    readonly_witness_js = r'''
import fs from 'node:fs';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
import {MongoClient} from '/usr/src/conductor/server/node_modules/mongodb/lib/index.js';
const config=JSON.parse(fs.readFileSync('/fixture/app.json'));
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const client=new MongoClient(process.env.MONGOOSEURI);await client.connect();const db=client.db();
const collections={};
for(const name of ['conformancerecords','remedyoperationrecords']){
 const rows=await db.collection(name).find({projectID:config.projectID}).sort({_id:1}).toArray();
 collections[name]={count:rows.length,sha256:hash(rows)};
 if(name==='conformancerecords')assert.ok(rows.some(r=>r.kind==='review'&&r.actor===config.editor&&r.data?.status==='fail'));
}
const login=await fetch('http://127.0.0.1:5000/api/v1/auth/fallback-auth',{method:'POST',redirect:'manual',headers:{'Content-Type':'application/json',Origin:'https://conductor.invalid'},body:JSON.stringify({email:'editor@candidate.example.invalid',password:config.password})});
assert.equal(login.status,302);const cookies=login.headers.getSetCookie().map(c=>c.split(';')[0]).join('; ');
const path='/api/v1/project/'+config.projectID+'/accessibility/workqueue/conformance/history?sectionID='+config.sectionID+'&criterionID=1.1.1';
const response=await fetch('http://127.0.0.1:5000'+path,{headers:{Cookie:cookies,Origin:'https://conductor.invalid','X-Requested-With':'XMLHttpRequest'}});
const history=await response.json();assert.equal(response.status,200);assert.equal(history.err,false);assert.equal(history.nextCursor,null);
assert.ok(history.records.some(r=>r.actor===config.editor&&r.data?.status==='fail'));
await client.close();console.log(JSON.stringify({collections,publicHistory:{count:history.records.length,sha256:hash(history)},syntheticFailureActorPreserved:true}));
'''

    def immutable_history():
        value = run('docker', 'exec', '-i', inspect('conductor')['Id'], 'node', '/opt/remedy-bundle/secret-env.mjs',
                    'conductor', 'node', '--input-type=module', input_text=readonly_witness_js)
        write_product_log(evidence / f'public-{target}-history-witness-{len(result.get("stages", []))}.log',
                          value.stdout + value.stderr, sensitive)
        return json.loads(value.stdout.strip().splitlines()[-1])

    def history_status():
        code, value = request('remedy-server', 8000, '/v1/cxone/page/operation-status',
                              {'issuer': signing['issuer'], 'jti': history_jti}, server_key, tls=True)
        if code != 200:
            raise RuntimeError('historical actor/outcome unavailable after operational transition')
        require_terminal_history(value, signing['issuer'], history_jti, signing['trust_epoch'])
        return {'status': code, 'sha256': hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
                'outcome': value['outcome'], 'operationID': value['operation_id'],
                'terminalProofSHA256': hashlib.sha256(json.dumps(value.get('terminal_proof'), sort_keys=True).encode()).hexdigest()}

    witness = job('create')
    private_json('original-office-witness.json', witness)
    result['officeJob'] = {key: witness[key] for key in ('jobID', 'inputSHA256', 'outputSHA256', 'options', 'postCount', 'genuineDOCXParsed')}
    baseline_history = immutable_history()
    baseline_status = history_status()
    result['immutableHistoryBefore'] = baseline_history
    result['bridgeHistoryBefore'] = baseline_status
    result['fenceSHA256'] = digest(fence_path)
    result['stages'] = []
    original_stores = {'server': server_state, 'bridge': ledger, 'mongo': mongo_state}

    def process_identity(pid):
        try:
            return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]
        except (FileNotFoundError, ProcessLookupError):
            return None

    def stop_owned(role, phase):
        initial = inspect(role)
        if not initial['State']['Running']:
            raise RuntimeError('operational stop requires running exact owned product: ' + role)
        baseline = expected_runtime[role]
        host = initial['HostConfig']
        if (not host['Init'] or not host['ReadonlyRootfs'] or host['CapDrop'] != ['ALL'] or
                not any(opt in {'no-new-privileges', 'no-new-privileges:true'} for opt in host['SecurityOpt']) or
                host['Memory'] != baseline['memoryBytes'] or host['NanoCpus'] != baseline['nanoCpus'] or
                host['PidsLimit'] != baseline['pidLimit'] or host['ShmSize'] != baseline['shmBytes'] or
                initial['Config']['StopTimeout'] != baseline['stopSeconds'] or host.get('PortBindings')):
            raise RuntimeError('operational stop runtime controls differ')
        kernel = dict(line.split(':', 1) for line in run('docker', 'exec', initial['Id'], 'cat', '/proc/1/status').stdout.splitlines() if ':' in line)
        if (int(kernel['Uid'].split()[1]) != baseline['uid'] or int(kernel['CapEff'].strip(), 16) != 0 or
                kernel['NoNewPrivs'].strip() != '1' or kernel['Seccomp'].strip() != '2'):
            raise RuntimeError('operational stop nonroot kernel controls differ')
        census = run('docker', 'top', initial['Id'], '-eo', 'pid').stdout.splitlines()[1:]
        lifetimes = {int(line.strip()): process_identity(int(line.strip())) for line in census}
        lifetimes = {pid: tick for pid, tick in lifetimes.items() if tick is not None}
        init_pid = initial['State']['Pid']
        cgroup_files = []
        for line in Path('/proc', str(init_pid), 'cgroup').read_text().splitlines():
            hierarchy, _, path = line.split(':', 2)
            if hierarchy == '0':
                cgroup_files.append(Path('/sys/fs/cgroup') / path.lstrip('/') / 'cgroup.procs')
        started = time.monotonic()
        run('docker', 'stop', initial['Id'])
        value = inspect(role)
        if value['Id'] != initial['Id'] or value['Image'] != initial['Image']:
            raise RuntimeError('product identity changed while stopping')
        state = value['State']
        expected_exit = 143 if role == 'remedy-server' else 0
        if (state['Status'] != 'exited' or state['ExitCode'] != expected_exit or state['Pid'] != 0 or
                state.get('Error') != '' or any(state.get(field, True) for field in ('Running', 'Paused', 'Restarting', 'Dead', 'OOMKilled'))):
            raise RuntimeError('operational product stop did not complete gracefully: ' + role)
        if any(process_identity(pid) == tick for pid, tick in lifetimes.items()):
            raise RuntimeError('owned process lifetime survived stopped container: ' + role)
        if any(path.exists() and path.read_text().strip() for path in cgroup_files):
            raise RuntimeError('owned cgroup retained processes after stop: ' + role)
        logs = run('docker', 'logs', initial['Id'], check=False)
        write_product_log(evidence / f'public-{target}-{phase}-{role}-stop.log', logs.stdout + logs.stderr, sensitive)
        if role == 'remedy-server' and 'Application shutdown complete' not in logs.stdout + logs.stderr:
            raise RuntimeError('actual Uvicorn lifespan completion unavailable')
        return value, {'containerID': value['Id'], 'imageID': value['Image'], 'exitCode': state['ExitCode'],
                       'oomKilled': False, 'errorEmpty': True, 'stopSeconds': round(time.monotonic() - started, 3),
                       'uid': baseline['uid'], 'capEff': 0, 'noNewPrivileges': True, 'seccomp': 2,
                       'knownPublicBoundsAndInitVerified': True,
                       'observedProcessLifetimesEnded': len(lifetimes), 'remainingCgroupProcesses': 0,
                       'serverLifespanCompleted': role == 'remedy-server'}

    stopped = {}
    result['coldStop'] = {}
    for role in ('conductor', 'adapt-scanner', 'remedy-bridge', 'remedy-renderer', 'remedy-server', 'mongo'):
        stopped[role], result['coldStop'][role] = stop_owned(role, 'cold-capture')
    # Match the actual ownership directory names, retaining every marker byte.
    unresolved = [path for directory_path in server_state.rglob('*.execution.lock.unresolved')
                  if directory_path.is_dir() for path in directory_path.iterdir()]
    result['serverUnresolvedMarkersRetained'] = len(unresolved)
    if unresolved:
        raise RuntimeError('unresolved Server ownership retained; no automatic clone admission')
    fence_value = json.loads(fence_path.read_text())
    database = sqlite3.connect((ledger / 'claims.sqlite3').as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        database.execute('PRAGMA query_only=ON')
        database.execute('BEGIN')
        meta = database.execute('SELECT trust_epoch,durability_seq FROM meta WHERE singleton=1').fetchone()
    finally:
        database.close()
    if (meta != (signing['trust_epoch'], fence_value['durability_seq']) or
            fence_value['trust_epoch'] != signing['trust_epoch'] or digest(fence_path) != result['fenceSHA256']):
        raise RuntimeError('current independent fence and readonly SQL metadata disagree')
    result['currentFenceMatchesReadonlySQLMeta'] = True
    logical = {'remedy-server': 'server', 'remedy-bridge': 'bridge', 'mongo': 'mongo',
               'adapt-scanner': 'scanner', 'remedy-renderer': 'renderer', 'conductor': 'conductor'}
    plan = {'version': 1,
            'stores': {role: {'source': str(path), 'container': stopped[{'server': 'remedy-server', 'bridge': 'remedy-bridge', 'mongo': 'mongo'}[role]]['Id'],
                              'destination': {'server': '/app/state', 'bridge': '/ledger', 'mongo': '/data/db'}[role]}
                       for role, path in original_stores.items()},
            'processes': {logical[role]: {'id': value['Id'], 'image': value['Image'],
                                        'exit_code': 143 if role == 'remedy-server' else 0} for role, value in stopped.items()},
            'fence': str(fence_path),
            'credential_roots': list(map(str, (secret_root, tls_root, signer, fixture, frontend_tls, nss_seed)))}
    plan_file = private_json('cold-plan.json', plan)
    archive, backup_receipt = private / 'cold-stores.tar', private / 'cold-backup-receipt.json'
    cold_cli = root / 'deploy/stack/cold_state.py'

    def cold(operation, targets=None, archive_path=archive, check=True):
        arguments = ['python3', str(cold_cli), operation, '--plan', str(plan_file), '--archive', str(archive_path),
                     '--receipt', str(backup_receipt)]
        if targets is not None:
            arguments += ['--targets', str(private_json(operation + '-' + str(len(list(private.glob('restore-*.json')))) + '.json',
                                                       {key: str(value) for key, value in targets.items()}))]
        return run(*arguments, check=check, timeout=180)

    captured = json.loads(cold('backup').stdout)
    if captured['admissionAuthorized'] or captured['processCleanupCertified']:
        raise RuntimeError('cold transport unexpectedly claimed admission or cleanup authority')
    result['coldBackup'] = {**captured, 'receiptSHA256': digest(backup_receipt), 'planSHA256': digest(plan_file),
                            'toolSHA256': digest(cold_cli), 'privateArchiveRetained': True}

    def new_targets(label):
        return {role: allocate(label + '-' + target + '-' + role, 999 if role != 'bridge' else 1000, role)
                for role in original_stores}

    clones = new_targets('clone')
    restored = json.loads(cold('restore', clones).stdout)
    if restored['admissionAuthorized'] or restored['processCleanupCertified']:
        raise RuntimeError('cold clone unexpectedly claimed application acceptance')
    result['coldClone'] = {'verifiedByActualCLI': True, 'admissionAuthorized': False,
                           'processCleanupCertified': False, 'originalStoppedContainersRetainedDuringClone': True}
    empty_targets = new_targets('negative-empty')
    corrupt = private / 'tampered-copy.tar'
    shutil.copyfile(archive, corrupt)
    corrupt.chmod(0o600)
    with corrupt.open('ab') as stream:
        stream.write(b'LT197 synthetic archive integrity rejection witness')
    rejected = cold('restore', empty_targets, archive_path=corrupt, check=False)
    if rejected.returncode == 0 or 'archive digest mismatch' not in rejected.stdout or any(any(path.iterdir()) for path in empty_targets.values()):
        raise RuntimeError('tampered archive was not refused before target writes')
    result['negativeCases'] = {'tamperedArchive': {'refusedBeforeWrites': True, 'copySHA256': digest(corrupt)}}
    nonempty = new_targets('negative-nonempty')
    occupied = nonempty['server'] / 'synthetic-nonempty-witness'
    occupied.write_text('retained synthetic target ownership witness\n')
    occupied.chmod(0o600)
    rejected = cold('restore', nonempty, check=False)
    if (rejected.returncode == 0 or 'restore target must be an existing empty directory' not in rejected.stdout or
            set(nonempty['server'].iterdir()) != {occupied} or any(any(path.iterdir()) for role, path in nonempty.items() if role != 'server')):
        raise RuntimeError('nonempty restore target was not conservatively refused')
    result['negativeCases']['nonemptyTarget'] = {'refusedBeforeWrites': True, 'witnessRetained': True}
    advanced = server_state / 'lt197-new-work-after-capture.json'
    _private_file(advanced, 999, '{"syntheticNewWorkAfterCapture":true}\n', 0o600)
    rejected = cold('restore', empty_targets, check=False)
    if rejected.returncode == 0 or 'current stores advanced or changed' not in rejected.stdout or any(any(path.iterdir()) for path in empty_targets.values()):
        raise RuntimeError('newer original state was not protected from stale restore')
    result['negativeCases']['newerOriginalState'] = {'refusedBeforeWrites': True, 'newWorkWitnessRetained': True,
                                                   'witnessSHA256': digest(advanced)}
    if digest(fence_path) != result['fenceSHA256']:
        raise RuntimeError('cold clone or negative case altered current independent fence')
    # Only after positive clone validation and refusals have finished may the
    # exact stopped originals be replaced. Original store directories remain.
    for role, value in stopped.items():
        current = inspect(role)
        if current['Id'] != value['Id'] or current['State']['Running']:
            raise RuntimeError('original stopped product identity changed before replacement')
        run('docker', 'rm', value['Id'])
    adapt = inspect('external-adapt')
    run('docker', 'stop', adapt['Id'])
    adapt_stopped = inspect('external-adapt')
    if adapt_stopped['Id'] != adapt['Id'] or adapt_stopped['State']['ExitCode'] != 143:
        raise RuntimeError('synthetic ADAPT namespace helper did not stop cleanly')
    run('docker', 'rm', adapt['Id'])

    clone_values = {**interpolation, 'REMEDY_STATE_ROOT': str(clones['server']),
                    'REMEDY_BRIDGE_STATE_ROOT': str(clones['bridge']), 'REMEDY_MONGO_STATE_ROOT': str(clones['mongo'])}
    context['operational_contexts'] = []

    def configuration(phase, image, image_target):
        values = {**clone_values, 'REMEDY_CONDUCTOR_IMAGE': image}
        env_file = private / (phase + '-interpolation.env')
        env_file.write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
        env_file.chmod(0o600)
        args = list(public_compose_args)
        args[args.index('--env-file') + 1] = str(env_file)
        public_config = private / (phase + '-public-config.json')
        public_config.write_text(run(*args, 'config', '--format', 'json', env=compose_environment, private_stdout=True).stdout)
        public_config.chmod(0o600)
        actual_config = private / (phase + '-actual-config.json')
        actual_config.write_text(compose('config', '--format', 'json', interpolation_file=env_file, private_stdout=True).stdout)
        actual_config.chmod(0o600)
        context['operational_contexts'].append({**{key: value for key, value in context.items() if key != 'operational_contexts'},
                                                'target': image_target, 'operational_phase': phase, 'config_path': public_config,
                                                'public_config_path': public_config, 'actual_config_path': actual_config,
                                                'state_root': clones['server'], 'bridge_state_root': clones['bridge'],
                                                'mongo_state_root': clones['mongo'], 'interpolation_file': env_file})
        return env_file, {'publicConfigurationSHA256': digest(public_config), 'actualConfigurationSHA256': digest(actual_config)}

    def stage_witness(phase, image_target, image, configuration_hashes):
        observation = {'phase': phase, 'target': image_target, 'loadedDockerImageID': image,
                       **configuration_hashes, 'runtime': {}, 'complete': False}
        result['stages'].append(observation)
        build_code, build = request('conductor', 5000, '/api/v1/build')
        if build_code != 200 or build['ref'] != conductor_targets[image_target]['sourceTree']:
            raise RuntimeError('actual original compiled Conductor build ref differs')
        # Existing probe verifies current real auth/project authorization, source
        # and rendered scan, preview and valid signed production mutation denial.
        observation['sourceTree'] = build['ref']
        observation['consumer'] = probe('production-held', label=phase)
        history = immutable_history()
        status = history_status()
        if history != baseline_history or status != baseline_status or digest(fence_path) != result['fenceSHA256']:
            raise RuntimeError('immutable actor/outcome/history or current fence changed across transition')
        observation.update(oldOfficeJob=job('verify-existing', witness), immutableHistory=history,
                           historicalStatus=status, currentFenceUnchanged=True)
        for role in OWNED:
            value = inspect(role)
            baseline = expected_runtime[role]
            host = value['HostConfig']
            expected_image = image if role == 'conductor' else baseline['imageID']
            if (value['Image'] != expected_image or not host['ReadonlyRootfs'] or not host['Init'] or
                    host['CapDrop'] != ['ALL'] or not any(opt in {'no-new-privileges', 'no-new-privileges:true'} for opt in host['SecurityOpt']) or
                    host['Memory'] != baseline['memoryBytes'] or host['NanoCpus'] != baseline['nanoCpus'] or
                    host['PidsLimit'] != baseline['pidLimit'] or host['ShmSize'] != baseline['shmBytes'] or
                    value['Config']['StopTimeout'] != baseline['stopSeconds'] or host.get('PortBindings')):
                raise RuntimeError('operational reopen changed public runtime controls')
            kernel = dict(line.split(':', 1) for line in run('docker', 'exec', value['Id'], 'cat', '/proc/1/status').stdout.splitlines() if ':' in line)
            if (int(kernel['Uid'].split()[1]) != baseline['uid'] or int(kernel['CapEff'].strip(), 16) != 0 or
                    kernel['NoNewPrivs'].strip() != '1' or kernel['Seccomp'].strip() != '2'):
                raise RuntimeError('operational reopen changed nonroot kernel sandbox')
            observation['runtime'][role] = {'containerID': value['Id'], 'imageID': value['Image'], 'unchangedControls': True,
                                           'uid': baseline['uid'], 'capEff': 0, 'noNewPrivileges': True, 'seccomp': 2}
        health = wait('remedy-server', 8000, '/v1/cxone/health', key=server_key, tls=True, expected=503)
        if health['capabilities']['mutate'] is not False or not all(health['capabilities'][name] for name in ('scan', 'preview', 'operation_status')):
            raise RuntimeError('production write hold or reads changed after operational transition')
        code, counter = request('external-cxone', 8082, '/control/status', key='synthetic-control-only', control=True)
        if code != 200 or counter['mutations'] != 0:
            raise RuntimeError('external mutation attempted during operational rehearsal')
        observation.update(externalMutations=0, productionReadinessStatus=503, mutate=False, complete=True)

    clone_env, hashes = configuration('restored-original', current_image, target)
    compose('up', '-d', '--no-deps', 'mongo', 'remedy-server', 'remedy-renderer', interpolation_file=clone_env)
    deadline = time.monotonic() + 60
    while run('docker', 'exec', inspect('mongo')['Id'], 'mongosh', '--quiet', '--eval',
              'db.adminCommand({ping:1}).ok', check=False).stdout.strip() != '1':
        if time.monotonic() >= deadline:
            raise RuntimeError('restored authenticated Mongo reopening deadline')
        time.sleep(.2)
    wait('remedy-server', 8000, '/readyz', tls=True)
    wait('remedy-renderer', 5180)
    compose('up', '-d', '--no-deps', 'remedy-bridge', 'adapt-scanner', interpolation_file=clone_env)
    wait('adapt-scanner', 5176)
    compose('up', '-d', '--no-deps', 'external-adapt', 'conductor', interpolation_file=clone_env)
    wait('conductor', 5000, '/health')
    # Restored Mongo and ledger are reopened by their shipping processes. No
    # first-user initialization, checkpoint, migration or recovery repair runs.
    stage_witness('restored-original', target, current_image, hashes)
    other_target = next(name for name in conductor_targets if name != target)
    for phase, selected_target in (('other-owned-binary', other_target), ('rollback-current-data', target)):
        _, stopped_conductor = stop_owned('conductor', phase)
        image = conductor_targets[selected_target]['loadedDockerImageID']
        env_file, hashes = configuration(phase, image, selected_target)
        compose('up', '-d', '--no-deps', '--force-recreate', 'conductor', interpolation_file=env_file)
        wait('conductor', 5000, '/health')
        stage_witness(phase, selected_target, image, hashes)
        result['stages'][-1]['previousConductorStop'] = stopped_conductor
    result.update(complete=True, originalsPreserved=True, currentClonedDataReusedForRollback=True,
                  oldDataNeverRestoredAfterNewActivity=True, independentFenceNeverCopiedOrRestored=True,
                  productionWritesEnabled=False, operationalAcceptanceComplete=False)
