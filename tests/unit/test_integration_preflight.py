"""Integration preflight at the public CLI and immutable-receipt validation seams."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/stack/preflight.py'


@pytest.mark.parametrize('profile', ['engine', 'bridge-review', 'integration'])
def test_integration_production_refuses_before_any_missing_input_or_host_access(tmp_path, profile):
    result = subprocess.run([
        sys.executable, str(SCRIPT), '--profile', profile, '--production',
        '--integration-proof', str(tmp_path / 'absent-full-result.json'),
        '--conductor-target', 'release-2.156.2', '--artifacts', str(tmp_path / 'absent'),
        '--proof', str(tmp_path / 'absent-result.json'), '--state-root', str(tmp_path / 'state'),
        '--secret-root', str(tmp_path / 'credentials'),
    ], env={'PATH': ''}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error'] == 'deployment_not_accepted_by_release_owner'
    assert 'absent' not in result.stdout + result.stderr


@pytest.fixture
def preflight():
    spec = importlib.util.spec_from_file_location('integration_preflight', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def receipts():
    policy = json.loads((ROOT / 'deploy/stack/bundle.json').read_text())
    index = json.loads((ROOT / 'deploy/stack/conductor-candidates.json').read_text())
    candidate = {'serverSource': 'a' * 40, 'bridgeSource': policy['bridgeSource'],
                 'sha256': {role + '.oci.tar': str(n) * 64 for n, role in enumerate(('server', 'bridge', 'renderer'), 1)}}
    baseline = {'images': {}, 'importedArtifacts': {'images': {}}}
    full = {'serverSource': 'a' * 40, 'verificationComplete': True,
            'verificationScope': 'compiled-auth-scan-rendered-preview-and-production-hold',
            'operationalAcceptanceComplete': False, 'externalMutations': 0,
            'conductorIndexSHA256': '99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8',
            'actualScannerAgainstTLSserver': True, 'bridgePrivateSigningKeyAbsent': True,
            'rendererInitialNamespaceChrootDenied': True, 'rendererUID': 1001,
            'targets': {}, 'started': []}
    identities = {}
    for n, role in enumerate(('server', 'bridge', 'renderer', 'scanner', 'mongo'), 1):
        identities[role] = 'sha256:' + str(n) * 64
        baseline['images'][role] = {'id': identities[role], 'layers': ['sha256:' + 'f' * 64]}
        if role in {'server', 'bridge', 'renderer'}:
            baseline['importedArtifacts']['images'][role] = {'loadedDockerImageID': identities[role]}
    for target in index['candidates']:
        pin = target['validation']
        artifact = {'baseCommit': target['baseCommit'], 'sourceTree': target['sourceTree'],
                    'artifactID': pin['artifactID'], 'ZIPDigest': pin['artifactDigest'],
                    'archiveSHA256': pin['archiveSHA256'], 'imageID': pin['imageID'],
                    'sourceConfigDigest': pin['imageID'], 'sourceManifestDigest': None,
                    'loadedDockerImageID': pin['imageID'], 'filesystemDiffIDs': ['sha256:' + 'e' * 64],
                    'runtimeConfiguration': {'Entrypoint': ['node', 'dist/server.js'], 'Labels': {'org.opencontainers.image.revision': target['sourceTree']}},
                    'inspectConfiguration': {'Entrypoint': ['node', 'dist/server.js'], 'Labels': {'org.opencontainers.image.revision': target['sourceTree']}}}
        phases = [{field: True for field in ('passed', 'compiledEntrypoint', 'realAuthenticationAndMongo',
                  'projectAuthorization', 'realScanPreview', 'realRenderedEvidence', 'productionMutationDenied')}
                  | {'phase': phase, 'node': 'v22.22.3', 'intents': 0, 'verifiedCriteria': 0}
                  for phase in ('review', 'production-held')]
        production_phase = phases.pop()
        phases.append({'passed': True, 'realCompiledUI': True, 'trustedTLS': True,
                       'browserManagedSecureCookie': True, 'manualFailureEvidenceSaved': True,
                       'productionMutationFalse': True, 'productionSSOVerified': False})
        phases.append({'passed': True, 'actualBrowserSourceChange': True, 'changedSourceStalesManualEvidence': True,
                       'immutableReviewHistory': True, 'verifiedCriteria': 0, 'productionMutationFalse': True})
        phases.append(production_phase)
        full['targets'][target['target']] = {'complete': True, 'artifact': artifact, 'phases': phases}
        identities['conductor'] = pin['imageID']
        for role in ('conductor',):
            limits = policy['limits'][role]
            full['started'].append({'role': role, 'imageID': identities[role], 'uid': 1000, 'capEff': 0,
                'noNewPrivileges': True, 'seccomp': 2, 'cpus': limits['cpus'], 'memoryBytes': limits['memoryBytes'],
                'pidLimit': limits['pids'], 'shmBytes': limits['shmBytes'], 'stopSeconds': limits['stopSeconds'],
                'readOnlyRoot': True, 'init': True, 'seccompProfileSHA256': None, 'tmpfs': {'/tmp': 'rw,nosuid,nodev,size=536870912'}})
    for role in ('server', 'bridge', 'renderer', 'scanner', 'mongo'):
        limits = policy['limits'][role]
        tmpfs = {'/tmp': 'rw,nosuid,nodev,size=' + str(limits['tmpBytes'])}
        if role == 'mongo': tmpfs['/data/configdb'] = 'rw,nosuid,nodev,noexec,size=16m'
        full['started'].append({'role': role, 'imageID': identities[role], 'uid': {'server': 999, 'bridge': 1000, 'renderer': 1001, 'scanner': 1002, 'mongo': 999}[role],
            'capEff': 0, 'noNewPrivileges': True, 'seccomp': 2, 'cpus': limits['cpus'], 'memoryBytes': limits['memoryBytes'],
            'pidLimit': limits['pids'], 'shmBytes': limits.get('shmBytes', 67108864), 'stopSeconds': limits['stopSeconds'],
            'readOnlyRoot': True, 'init': True, 'seccompProfileSHA256': None, 'tmpfs': tmpfs})
    for item in full['started']:
        if item['role'] in {'server', 'scanner', 'renderer'}:
            path = ROOT / ('deploy/chromium-seccomp-amd64.json' if item['role'] == 'server' else 'deploy/stack/' + item['role'] + '-seccomp-amd64.json')
            import hashlib
            item['seccompProfileSHA256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return policy, candidate, baseline, full


def test_complete_compiled_receipt_is_compatibility_evidence_only(preflight, receipts):
    policy, candidate, baseline, full = receipts
    artifact = preflight.validate_integration_proof(candidate, baseline, full, 'release-2.156.2', policy)
    assert artifact['sourceTree'] == 'a60544214de7d3613e1dad0da99a6c62722c49a8'
    assert full['operationalAcceptanceComplete'] is False


@pytest.mark.parametrize('damage', [
    'partial', 'wrong-source', 'wrong-scope', 'ui-failure', 'unknown-schema', 'missing-ui',
    'missing-production-held', 'new-image', 'wrong-target-tree', 'missing-runtime',
    'root-renderer', 'capability', 'weak-tmpfs', 'missing-init', 'wrong-seccomp', 'mutation', 'wrong-index',
])
def test_integration_receipt_refuses_partial_or_inconsistent_evidence(preflight, receipts, damage):
    policy, candidate, baseline, full = receipts
    target = full['targets']['release-2.156.2']
    renderer = next(item for item in full['started'] if item['role'] == 'renderer')
    if damage == 'partial': full['verificationComplete'] = False
    elif damage == 'wrong-source': full['serverSource'] = 'b' * 40
    elif damage == 'wrong-scope': full['verificationScope'] = 'helper-tests-only'
    elif damage == 'ui-failure': full['uiFailures'] = [{'target': 'staging-67301b35'}]
    elif damage == 'unknown-schema': full['schema'] = 'unreviewed-v2'
    elif damage == 'missing-ui': target['phases'] = [item for item in target['phases'] if not item.get('realCompiledUI')]
    elif damage == 'missing-production-held': next(item for item in target['phases'] if item.get('phase')=='production-held')['phase'] = 'dev-test'
    elif damage == 'new-image': target['artifact']['loadedDockerImageID'] = 'sha256:' + '0' * 64
    elif damage == 'wrong-target-tree': target['artifact']['sourceTree'] = full['targets']['staging-67301b35']['artifact']['sourceTree']
    elif damage == 'missing-runtime': full['started'] = [item for item in full['started'] if item['role'] != 'mongo']
    elif damage == 'root-renderer': renderer['uid'] = 0
    elif damage == 'capability': renderer['capEff'] = 1
    elif damage == 'weak-tmpfs': renderer['tmpfs']['/tmp'] = 'rw,size=8g'
    elif damage == 'missing-init': renderer.pop('init')
    elif damage == 'wrong-seccomp': renderer['seccompProfileSHA256'] = '0' * 64
    elif damage == 'mutation': full['externalMutations'] = 1
    elif damage == 'wrong-index': full['conductorIndexSHA256'] = '0'*64
    with pytest.raises(ValueError):
        preflight.validate_integration_proof(candidate, baseline, full, 'release-2.156.2', policy)


@pytest.fixture
def integration_config(tmp_path, receipts):
    """Static expansion of the shipped YAML/examples; never reads a real .env."""
    import copy
    from types import SimpleNamespace
    import re
    import yaml

    policy, _, _, full = receipts
    args = SimpleNamespace(secret_root=tmp_path/'secrets', tls_root=tmp_path/'tls',
        nss_seed_root=tmp_path/'nss', state_root=tmp_path/'state', mongo_state_root=tmp_path/'mongo',
        bridge_state_root=None, fence_root=None, keyring=None, signing_key=None,
        renderer_seccomp=ROOT/'deploy/stack/renderer-seccomp-amd64.json', integration_mode='full-write',
        history=False, trust_epoch=None, status_issuer=None)
    identities = {item['role']: item['imageID'] for item in full['started']}
    identities['conductor'] = full['targets']['release-2.156.2']['artifact']['loadedDockerImageID']
    replacements = {
        'REMEDY_SERVER_IMAGE': identities['server'], 'REMEDY_BRIDGE_IMAGE': identities['bridge'],
        'REMEDY_RENDERER_IMAGE': identities['renderer'], 'REMEDY_CONDUCTOR_IMAGE': identities['conductor'],
        'REMEDY_SERVER_SECCOMP_FILE': str(ROOT/'deploy/chromium-seccomp-amd64.json'),
        'REMEDY_SCANNER_SECCOMP_FILE': str(ROOT/'deploy/stack/scanner-seccomp-amd64.json'),
        'REMEDY_RENDERER_SECCOMP_FILE': str(args.renderer_seccomp), 'REMEDY_BRIDGE_PROFILE': 'full-write',
        'REMEDY_TLS_ROOT': str(args.tls_root), 'REMEDY_SECRET_ROOT': str(args.secret_root),
        'REMEDY_STATE_ROOT': str(args.state_root), 'REMEDY_MONGO_STATE_ROOT': str(args.mongo_state_root),
        'REMEDY_NSS_SEED_ROOT': str(args.nss_seed_root),
    }
    config = {'services': {}, 'configs': {}, 'networks': {}}
    for filename in ('docker-compose.yml', 'compose.scanner.yml', 'compose.bridge.yml', 'compose.integration.yml'):
        text = (ROOT/'deploy/stack'/filename).read_text()
        text = re.sub(r'\$\{([A-Z_]+):\?[^}]*\}', lambda m: replacements[m[1]], text)
        layer = yaml.safe_load(text)
        config['configs'].update(layer.get('configs', {}))
        config['networks'].update(layer.get('networks', {}))
        for name, service in layer['services'].items():
            merged = config['services'].setdefault(name, {})
            for field, value in service.items():
                if field == 'environment': merged.setdefault(field, {}).update(value)
                elif field in {'volumes', 'configs'}:
                    match = 'target' if field == 'volumes' else 'source'
                    by_target = {item[match]: item for item in merged.get(field, [])}
                    by_target.update({item[match]: item for item in value})
                    merged[field] = list(by_target.values())
                else: merged[field] = copy.deepcopy(value)
    for service in config['services'].values():
        env = {}
        for name in service.pop('env_file', []):
            text = (ROOT/'deploy/stack'/str(name + '.example')).read_text()
            env.update(line.split('=', 1) for line in text.splitlines() if line and not line.startswith('#'))
        env.update(service.get('environment', {}))
        service['environment'] = {field: value.replace('REPLACE_WITH_REVIEWED_CONDUCTOR_ORIGIN','staff.example.invalid').replace('REPLACE_WITH_AUTHORIZED_ADAPT_HOST','adapt.example.invalid').replace('REPLACE_WITH_REVIEWED_CONDUCTOR_HOST','staff.example.invalid').replace('REPLACE_WITH_AUTHORIZED_MAILGUN_DOMAIN','mail.example.invalid') if isinstance(value,str) else value for field,value in env.items()}
        if isinstance(service.get('networks'), list): service['networks'] = dict.fromkeys(service['networks'], {})
        for field in ('mem_limit', 'shm_size'):
            value = service[field]
            match = re.fullmatch(r'(\d+)(m|g|gb)', value)
            service[field] = int(match[1]) * (1024**2 if match[2] == 'm' else 1024**3)
    for value in config['configs'].values(): value['file'] = str(ROOT/'deploy/stack'/Path(value['file']))
    import hashlib
    args.configuration_hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                 ('deploy/stack/secret-env.mjs','deploy/stack/browser-home.sh')}
    return config, args, policy, identities


def test_full_startup_compatibility_can_be_preflighted_without_signer(preflight, integration_config):
    config, args, policy, identities = integration_config
    mounts = preflight.validate_compose(config, args, policy, identities, 1002, {}, configuration_hashes=args.configuration_hashes)
    assert mounts['mongo']['/data/db'] == str(args.mongo_state_root)
    assert '/run/signing/private.pem' not in mounts['conductor']
    assert '/run/reviewer/keyring.json' not in mounts['bridge']


@pytest.mark.parametrize('damage', [
    'direct-secret', 'wrong-mount', 'implicit-create', 'weak-renderer', 'mongo-no-auth',
    'mutable-consumer', 'http-server', 'wrong-mode', 'unbounded-configdb', 'signer-leak',
    'restart-storm', 'fake-compiled-command', 'public-port',
])
def test_intended_compose_refuses_unsafe_integration_configuration(preflight, integration_config, damage):
    config, args, policy, identities = integration_config
    services = config['services']
    if damage == 'direct-secret': services['conductor']['environment']['SECRETKEY'] = 'synthetic-do-not-print'
    elif damage == 'wrong-mount': services['remedy-server']['volumes'][0]['source'] = '/different/state'
    elif damage == 'implicit-create': services['mongo']['volumes'][0]['bind']['create_host_path'] = True
    elif damage == 'weak-renderer': services['remedy-renderer']['security_opt'] = ['seccomp=unconfined']
    elif damage == 'mongo-no-auth': services['mongo']['command'].remove('--auth')
    elif damage == 'mutable-consumer': services['conductor']['image'] = 'conductor:latest'
    elif damage == 'http-server': services['conductor']['environment']['REMEDY_API_BASE_URL'] = 'http://remedy-server:8000'
    elif damage == 'wrong-mode': services['remedy-bridge']['environment']['REMEDY_BRIDGE_PROFILE'] = 'review-only'
    elif damage == 'unbounded-configdb': services['mongo']['tmpfs'].pop()
    elif damage == 'signer-leak': services['remedy-bridge']['environment']['REMEDY_REVIEWER_SIGNING_KEY_FILE'] = '/private.pem'
    elif damage == 'restart-storm': services['remedy-bridge']['restart'] = 'always'
    elif damage == 'fake-compiled-command': services['conductor']['command'] = ['node', 'fake_frontend.mjs']
    elif damage == 'public-port': services['remedy-bridge']['ports'] = ['5175:5175']
    with pytest.raises(ValueError) as error:
        preflight.validate_compose(config, args, policy, identities, 1002, {}, configuration_hashes=args.configuration_hashes)
    assert 'synthetic-do-not-print' not in str(error.value)


def test_canonical_paths_and_file_modes_are_required_without_secret_disclosure(preflight, tmp_path):
    import os
    private = tmp_path.resolve()/'credential'
    private.write_text('synthetic-do-not-print')
    private.chmod(0o600)
    assert preflight.protected_file(private, os.getuid()) == b'synthetic-do-not-print'
    linked = private.with_name('linked')
    linked.symlink_to(private)
    with pytest.raises(ValueError): preflight.protected_file(linked, os.getuid())
    private.chmod(0o644)
    with pytest.raises(ValueError) as error: preflight.protected_file(private, os.getuid())
    assert 'synthetic-do-not-print' not in str(error.value)


def test_history_epoch_and_current_fence_are_checked_with_signer_absent(preflight, tmp_path, monkeypatch):
    import os
    import sqlite3
    from types import SimpleNamespace
    root = tmp_path.resolve()
    ledger, fence = root/'ledger', root/'fence'
    ledger.mkdir(); fence.mkdir()
    database = ledger/'claims.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE meta(singleton INTEGER PRIMARY KEY, trust_epoch TEXT, durability_seq INTEGER)')
        connection.execute('INSERT INTO meta VALUES (1, ?, 9)', (' Exact opaque epoch ',))
    database.chmod(0o600)
    current = fence/'fence.json'
    current.write_text(json.dumps({'trust_epoch':' Exact opaque epoch ','durability_seq':9}))
    current.chmod(0o600)
    # POSIX ownership is an OS adapter; this test account owns only its own files.
    protected = preflight.protected_file
    monkeypatch.setattr(preflight, 'protected_file', lambda p, uid, maximum=16384, **kw:
                        protected(p, os.getuid(), maximum, **kw))
    args = SimpleNamespace(trust_epoch=' Exact opaque epoch ', status_issuer='urn:synthetic:issuer',
                           bridge_state_root=ledger, fence_root=fence)
    before = {p: p.read_bytes() for p in (database, current)}
    preflight.validate_history(args)
    assert {p: p.read_bytes() for p in before} == before
    args.trust_epoch = 'Exact opaque epoch'
    with pytest.raises(ValueError, match='current_independent_fence_required'):
        preflight.validate_history(args)
    args.trust_epoch = ' Exact opaque epoch '
    current.write_text(json.dumps({'trust_epoch':' Exact opaque epoch ','durability_seq':10}))
    with pytest.raises(ValueError, match='ledger_and_current_fence_mismatch'):
        preflight.validate_history(args)


def test_storage_budget_checks_underlying_capacity_and_available_space(preflight, tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    root = tmp_path.resolve()
    root.chmod(0o700)
    monkeypatch.setattr(preflight, 'run', lambda *command: 'ext4')
    monkeypatch.setattr(preflight.os, 'statvfs', lambda path: SimpleNamespace(f_frsize=4096, f_blocks=262144, f_bavail=131072))
    result = preflight.validate_storage(root, os.getuid(), 1073741824)
    assert result['capacityBytes'] == 1073741824 and result['freeBytes'] == 536870912
    monkeypatch.setattr(preflight.os, 'statvfs', lambda path: SimpleNamespace(f_frsize=4096, f_blocks=524288, f_bavail=131072))
    with pytest.raises(ValueError, match='bounded_state_filesystem_required'):
        preflight.validate_storage(root, os.getuid(), 1073741824)
    monkeypatch.setattr(preflight.os, 'statvfs', lambda path: SimpleNamespace(f_frsize=4096, f_blocks=262144, f_bavail=1))
    with pytest.raises(ValueError, match='insufficient_state_capacity'):
        preflight.validate_storage(root, os.getuid(), 1073741824)


@pytest.mark.parametrize('failure', ['timeout', 'signal', 'cleanup-stop-timeout', None])
def test_disposable_probes_cleanup_only_the_exact_owned_id(preflight, receipts, monkeypatch, failure):
    policy = receipts[0]
    image, container = 'sha256:' + 'a'*64, 'b'*64
    calls = []
    owner = None

    def docker(command, **kwargs):
        nonlocal owner
        calls.append(list(command))
        if command[:2] == ('docker', 'create') or command[:2] == ['docker', 'create']:
            owner = next(value.split('=', 1)[1] for value in command if str(value).startswith('org.libretexts.preflight-owner='))
            return subprocess.CompletedProcess(command, 0, container+'\n', '')
        if command[:2] == ('docker', 'inspect'):
            value = {'Id':container, 'Image':image, 'State':{'Running':False,'ExitCode':0,'OOMKilled':False}, 'Config':{'StopTimeout':30, 'Labels':{'org.libretexts.preflight-owner':owner}},
                'HostConfig':{'Init':True, 'ReadonlyRootfs':True, 'CapDrop':['ALL'], 'CapAdd':None,
                    'Privileged':False, 'NetworkMode':'none', 'PortBindings':{}, 'SecurityOpt':['no-new-privileges:true','seccomp='+str(ROOT/'deploy/stack/renderer-seccomp-amd64.json')],
                    'Memory':2147483648, 'PidsLimit':256, 'NanoCpus':1500000000, 'ShmSize':1073741824}}
            return subprocess.CompletedProcess(command, 0, json.dumps([value]), '')
        if list(command[:2]) == ['docker', 'start']:
            if failure == 'timeout': raise subprocess.TimeoutExpired(command, 60)
            if failure == 'signal': raise preflight.PreflightInterrupted(15)
            return subprocess.CompletedProcess(command, 0, 'sandbox-launch-closed\n', '')
        if list(command[:2]) == ['docker', 'stop'] and failure == 'cleanup-stop-timeout':
            raise subprocess.TimeoutExpired(command, 10)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(preflight.subprocess, 'run', docker)
    arguments = (image, 'renderer', policy, ROOT/'deploy/stack/renderer-seccomp-amd64.json')
    if failure in {'timeout', 'signal'}:
        with pytest.raises(subprocess.TimeoutExpired if failure=='timeout' else preflight.PreflightInterrupted):
            preflight.probe(*arguments)
    else:
        assert preflight.probe(*arguments) == 'sandbox-launch-closed'
    destructive = [call for call in calls if call[1] in {'stop', 'rm'}]
    assert destructive == [['docker','stop','--time','5',container], ['docker','rm','--force','--volumes',container]]
    create = calls[0]
    assert create[create.index('--network')+1] == 'none'
    assert image in create and '--read-only' in create and '--init' in create
    assert not any('/app/state' in value or '/ledger' in value for value in create)


@pytest.mark.parametrize('extra', [
    ['--integration-mode', 'full-write'],
    ['--history'],
])
def test_legacy_profile_refuses_integration_flags_before_host_or_inputs(tmp_path, extra):
    result = subprocess.run([sys.executable,str(SCRIPT),'--profile','engine',
        '--artifacts',str(tmp_path/'absent'),'--proof',str(tmp_path/'absent-proof'),
        '--state-root',str(tmp_path/'state'),'--secret-root',str(tmp_path/'secrets'),*extra],
        env={'PATH':''},capture_output=True,text=True,timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error'] == 'integration_flags_require_integration_profile'


def test_integration_requires_an_explicit_mode_and_complete_inputs(tmp_path):
    result = subprocess.run([sys.executable,str(SCRIPT),'--profile','integration',
        '--artifacts',str(tmp_path/'absent'),'--proof',str(tmp_path/'absent-proof'),
        '--state-root',str(tmp_path/'state'),'--secret-root',str(tmp_path/'secrets')],
        env={'PATH':''},capture_output=True,text=True,timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error'] == 'explicit_complete_integration_inputs_required'


def test_optional_review_history_inventory_does_not_need_signer(preflight, integration_config):
    config,args,policy,identities = integration_config
    args.integration_mode = 'review-only'; args.history = True
    args.bridge_state_root = args.state_root.with_name('ledger')
    args.fence_root = args.state_root.with_name('independent-fence')
    args.trust_epoch = ' Exact opaque epoch '
    args.status_issuer = 'urn:synthetic:issuer'
    bridge = config['services']['remedy-bridge']
    bridge['environment'].update(REMEDY_BRIDGE_PROFILE='review-only', REMEDY_REVIEWER_TRUST_EPOCH=args.trust_epoch,
        REMEDY_CLAIM_DB='/ledger/claims.sqlite3', REMEDY_CLAIM_FENCE_DIR='/fence', REMEDY_OPERATION_STATUS_ISSUER=args.status_issuer)
    config['services']['conductor']['environment']['REMEDY_REVIEWER_TRUST_EPOCH'] = args.trust_epoch
    for source,destination in ((args.bridge_state_root,'/ledger'),(args.fence_root,'/fence')):
        bridge['volumes'].append({'type':'bind','source':str(source),'target':destination,'bind':{'create_host_path':False}})
    mounts = preflight.validate_compose(config,args,policy,identities,1002,{},configuration_hashes=args.configuration_hashes)
    assert mounts['bridge']['/fence'] == str(args.fence_root)
    assert '/run/signing/private.pem' not in mounts['conductor']


def test_byte_identical_copied_package_configs_are_compatible(preflight, integration_config, tmp_path):
    config,args,policy,identities = integration_config
    package = tmp_path.resolve()/'copied-package'
    package.mkdir()
    for name,filename in (('credential-loader','secret-env.mjs'),('browser-home','browser-home.sh')):
        target = package/filename
        target.write_bytes((ROOT/'deploy/stack'/filename).read_bytes())
        config['configs'][name]['file'] = str(target)
    assert preflight.validate_compose(config,args,policy,identities,1002,{},configuration_hashes=args.configuration_hashes)['renderer']['/run/certificates/nss-seed'] == str(args.nss_seed_root)


@pytest.fixture
def disabled_signing(preflight, tmp_path, monkeypatch):
    import base64
    import os
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
    root = tmp_path.resolve()
    private = Ed25519PrivateKey.from_private_bytes(b'\x51'*32)  # synthetic unit fixture only
    values = {'REMEDY_REVIEWER_SIGNING_KEY_FILE':'/run/signing/private.pem',
              'REMEDY_REVIEWER_KEY_ID':'synthetic-disabled', 'REMEDY_REVIEWER_ISSUER':'urn:synthetic:conductor',
              'REMEDY_REVIEWER_AUDIENCE':'urn:synthetic:bridge', 'REMEDY_REVIEWER_KEY_ENABLED':'false',
              'REMEDY_REVIEWER_KEY_NOT_BEFORE':'0', 'REMEDY_REVIEWER_KEY_NOT_AFTER':'4102444800'}
    common = {'issuer':'urn:synthetic:conductor','audience':'urn:synthetic:bridge',
              'environment':'production','trust_epoch':' Exact independent epoch '}
    public = base64.urlsafe_b64encode(private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode().rstrip('=')
    ring = {**common,'keys':[{**common,'kid':'synthetic-disabled','kty':'OKP','crv':'Ed25519','x':public,
                             'enabled':True,'revoked_at':None,'not_before':0,'not_after':4102444800}]}
    args = SimpleNamespace(signing_config=root/'signing.json', keyring=root/'public-keyring.json',
                           signing_key=root/'private.pem', trust_epoch=common['trust_epoch'])
    args.signing_config.write_text(json.dumps(values)); args.keyring.write_text(json.dumps(ring))
    args.signing_key.write_bytes(private.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
    for path in (args.signing_config,args.keyring,args.signing_key): path.chmod(0o600)
    protected = preflight.protected_file
    monkeypatch.setattr(preflight, 'protected_file', lambda p, uid, maximum=16384, **kw:
                        protected(p, os.getuid(), maximum, **kw))
    return args,values,ring


def test_explicitly_disabled_conductor_signer_keeps_independent_bridge_key_enabled(preflight, disabled_signing):
    args,values,ring = disabled_signing
    before = args.keyring.read_bytes()
    assert preflight.validate_signing(args)['REMEDY_REVIEWER_KEY_ENABLED'] == 'false'
    assert args.keyring.read_bytes() == before
    assert json.loads(before)['keys'][0]['enabled'] is True


@pytest.mark.parametrize('damage', ['bytes','symlink','missing-frozen-hash'])
def test_copied_package_sources_must_still_match_frozen_regular_bytes(preflight, integration_config, tmp_path, damage):
    config,args,policy,identities = integration_config
    source = tmp_path.resolve()/'copied-loader.mjs'
    original = ROOT/'deploy/stack/secret-env.mjs'
    if damage == 'symlink': source.symlink_to(original)
    else: source.write_bytes(original.read_bytes() + (b'\n// changed\n' if damage=='bytes' else b''))
    config['configs']['credential-loader']['file'] = str(source)
    if damage == 'missing-frozen-hash': args.configuration_hashes.pop('deploy/stack/secret-env.mjs')
    with pytest.raises(ValueError):
        preflight.validate_compose(config,args,policy,identities,1002,{},configuration_hashes=args.configuration_hashes)


def test_disabled_signer_must_remain_explicit_and_protected(preflight, disabled_signing):
    args,values,ring = disabled_signing
    values['REMEDY_REVIEWER_KEY_ENABLED'] = 'disabled'
    args.signing_config.write_text(json.dumps(values))
    with pytest.raises(ValueError, match='invalid_signer_configuration'):
        preflight.validate_signing(args)
    values['REMEDY_REVIEWER_KEY_ENABLED'] = 'false'
    args.signing_config.write_text(json.dumps(values))
    args.signing_key.chmod(0o644)
    with pytest.raises(ValueError, match='protected_file_owner_mode_or_size_invalid'):
        preflight.validate_signing(args)


def test_disabled_conductor_signer_is_compatible_with_full_history_compose(preflight, integration_config, disabled_signing):
    config,args,policy,identities = integration_config
    signing_args,values,ring = disabled_signing
    signing = preflight.validate_signing(signing_args)
    args.history = True; args.trust_epoch = signing_args.trust_epoch
    args.status_issuer = values['REMEDY_REVIEWER_ISSUER']
    args.bridge_state_root = args.state_root.with_name('ledger')
    args.fence_root = args.state_root.with_name('fence')
    args.keyring = signing_args.keyring; args.signing_key = signing_args.signing_key
    bridge = config['services']['remedy-bridge']; conductor = config['services']['conductor']
    bridge['environment'].update(REMEDY_REVIEWER_TRUST_EPOCH=args.trust_epoch, REMEDY_CLAIM_DB='/ledger/claims.sqlite3',
        REMEDY_CLAIM_FENCE_DIR='/fence', REMEDY_OPERATION_STATUS_ISSUER=args.status_issuer,
        REMEDY_REVIEWER_KEYRING_FILE='/run/reviewer/keyring.json', REMEDY_SNAPSHOT_DIR='/ledger/snapshots', REMEDY_AUDIT_LOG='/ledger/audit.log')
    conductor['environment'].update(signing)
    conductor['environment']['REMEDY_REVIEWER_TRUST_EPOCH'] = args.trust_epoch
    for source,destination,readonly in ((args.bridge_state_root,'/ledger',False),(args.fence_root,'/fence',False),(args.keyring,'/run/reviewer/keyring.json',True)):
        bridge['volumes'].append({'type':'bind','source':str(source),'target':destination,'read_only':readonly,'bind':{'create_host_path':False}})
    conductor['volumes'].append({'type':'bind','source':str(args.signing_key),'target':'/run/signing/private.pem','read_only':True,'bind':{'create_host_path':False}})
    mounts = preflight.validate_compose(config,args,policy,identities,1002,signing,configuration_hashes=args.configuration_hashes)
    assert conductor['environment']['REMEDY_REVIEWER_KEY_ENABLED'] == 'false'
    assert json.loads(args.keyring.read_bytes())['keys'][0]['enabled'] is True
    assert '/run/signing/private.pem' not in mounts['bridge']
    assert '/run/reviewer/keyring.json' not in mounts['conductor']


@pytest.mark.parametrize('damage', ['missing', 'false-source-change', 'false-staleness', 'false-history', 'false-mutation-hold', 'nonzero-verified', 'boolean-verified'])
def test_changed_source_requires_real_browser_staleness_and_immutable_history(preflight, receipts, damage):
    policy,candidate,baseline,full = receipts
    target = full['targets']['release-2.156.2']
    freshness = next(item for item in target['phases'] if item.get('actualBrowserSourceChange'))
    if damage == 'missing': target['phases'].remove(freshness)
    elif damage == 'false-source-change': freshness['actualBrowserSourceChange'] = False
    elif damage == 'false-staleness': freshness['changedSourceStalesManualEvidence'] = False
    elif damage == 'false-history': freshness['immutableReviewHistory'] = False
    elif damage == 'false-mutation-hold': freshness['productionMutationFalse'] = False
    elif damage == 'nonzero-verified': freshness['verifiedCriteria'] = 1
    elif damage == 'boolean-verified': freshness['verifiedCriteria'] = False
    with pytest.raises(ValueError):
        preflight.validate_integration_proof(candidate,baseline,full,'release-2.156.2',policy)
