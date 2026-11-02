"""Public integration packaging contracts; no Docker or live services are used."""
from pathlib import Path
import subprocess

import pytest
import yaml


STACK = Path(__file__).resolve().parents[2] / 'deploy/stack'


def document(name):
    return yaml.safe_load((STACK / name).read_text())


def test_integration_uses_verified_products_and_private_verified_tls():
    services = document('compose.integration.yml')['services']
    server = services['remedy-server']
    assert server['command'][-4:] == [
        '--ssl-certfile', '/run/tls/cert.pem', '--ssl-keyfile', '/run/tls/key.pem',
    ]
    assert '--cacert' in server['healthcheck']['test']
    assert services['conductor']['command'] == ['node', 'dist/server.js']
    assert services['conductor']['user'] == '1000:1000'
    assert services['conductor']['environment']['REMEDY_API_BASE_URL'] == 'https://remedy-server:8000'
    assert services['adapt-scanner']['environment']['REMEDY_ENDPOINT'] == 'https://remedy-server:8000/v1/validate/html'
    for role in ('conductor', 'remedy-renderer'):
        assert '${REMEDY_' in services[role]['image'] and ':?' in services[role]['image']
    for role in ('conductor', 'remedy-bridge', 'adapt-scanner'):
        assert services[role]['environment']['NODE_EXTRA_CA_CERTS'] == '/run/tls/ca.pem'
    for service in services.values():
        assert 'ports' not in service and 'build' not in service
        assert service['restart'] == 'no'
        assert service['environment']['NODE_ENV'] == 'production'


def test_history_is_separate_from_signing_and_uses_independent_current_fence():
    integration = document('compose.integration.yml')['services']
    assert all('REMEDY_CLAIM_DB' not in service.get('environment', {}) for service in integration.values())
    services = document('compose.history.yml')['services']
    bridge = services['remedy-bridge']
    assert bridge['environment']['REMEDY_CLAIM_DB'] == '/ledger/claims.sqlite3'
    assert bridge['environment']['REMEDY_CLAIM_FENCE_DIR'] == '/fence'
    assert ':?' in bridge['environment']['REMEDY_OPERATION_STATUS_ISSUER']
    epoch = bridge['environment']['REMEDY_REVIEWER_TRUST_EPOCH']
    assert ':?' in epoch
    assert services['conductor']['environment']['REMEDY_REVIEWER_TRUST_EPOCH'] == epoch
    assert {mount['target'] for mount in bridge['volumes']} == {'/ledger', '/fence'}
    for service in services.values():
        assert all('SIGNING' not in key and 'KEYRING' not in key and 'EPOCH_FILE' not in key for key in service['environment'])
        assert 'REMEDY_BRIDGE_PROFILE' not in service['environment']


def test_signed_overlay_separates_private_signer_from_public_keyring():
    services = document('compose.signed.yml')['services']
    assert set(services) == {'remedy-bridge', 'conductor'}
    bridge = services['remedy-bridge']
    conductor = services['conductor']
    assert bridge['environment']['REMEDY_REVIEWER_KEYRING_FILE'] == '/run/reviewer/keyring.json'
    assert bridge['environment']['REMEDY_SNAPSHOT_DIR'] == '/ledger/snapshots'
    assert bridge['environment']['REMEDY_AUDIT_LOG'] == '/ledger/audit.log'
    assert conductor['environment']['REMEDY_REVIEWER_SIGNING_KEY_FILE'] == '/run/signing/private.pem'
    assert set(conductor['environment']) == {
        'REMEDY_REVIEWER_SIGNING_KEY_FILE', 'REMEDY_REVIEWER_KEY_ID',
        'REMEDY_REVIEWER_ISSUER', 'REMEDY_REVIEWER_AUDIENCE',
        'REMEDY_REVIEWER_KEY_ENABLED', 'REMEDY_REVIEWER_KEY_NOT_BEFORE',
        'REMEDY_REVIEWER_KEY_NOT_AFTER',
    }
    assert {mount['target'] for mount in bridge['volumes']} == {'/run/reviewer/keyring.json'}
    assert {mount['target'] for mount in conductor['volumes']} == {'/run/signing/private.pem'}
    assert 'REMEDY_BRIDGE_PROFILE' not in bridge['environment']


def env_example(name):
    return dict(
        line.split('=', 1) for line in (STACK / 'env' / name).read_text().splitlines()
        if line and not line.startswith('#')
    )


def test_examples_use_existing_file_credentials_and_no_signer_for_review_startup():
    conductor = env_example('conductor.env.example')
    renderer = env_example('renderer.env.example')
    assert conductor['NODE_ENV'] == 'production'
    assert conductor['REMEDY_API_BASE_URL'] == 'https://remedy-server:8000'
    assert conductor['REMEDY_ENABLED'] == 'true'
    assert conductor['PORT'] == '5000'
    assert {name: conductor[name] for name in (
        'SECRETKEY_FILE', 'MONGOOSEURI_FILE', 'REMEDY_API_KEY_FILE',
        'OPENAI_API_KEY_FILE', 'STRIPE_SECRET_KEY_FILE', 'MAILGUN_API_KEY_FILE',
    )} == {
        'SECRETKEY_FILE': '/run/secrets/session',
        'MONGOOSEURI_FILE': '/run/secrets/mongo',
        'REMEDY_API_KEY_FILE': '/run/secrets/remedy',
        'OPENAI_API_KEY_FILE': '/run/secrets/openai',
        'STRIPE_SECRET_KEY_FILE': '/run/secrets/stripe',
        'MAILGUN_API_KEY_FILE': '/run/secrets/mailgun',
    }
    assert not any('REVIEWER' in name for name in conductor)
    assert renderer['HOME'] == '/tmp/renderer-home'
    assert renderer['RENDER_SCANNER_TOKEN_FILE'] == '/run/secrets/token'
    assert renderer['RENDER_ALLOWED_HOSTS'] == 'dev.libretexts.org'
    assert renderer['RENDER_SCANNER_PORT'] == '5180'
    assert not any(name in conductor or name in renderer for name in (
        'SECRETKEY', 'MONGOOSEURI', 'REMEDY_API_KEY', 'OPENAI_API_KEY',
        'STRIPE_SECRET_KEY', 'MAILGUN_API_KEY', 'RENDER_SCANNER_TOKEN',
    ))


def test_browser_home_has_one_confined_ca_seed_path_and_execs_the_product():
    script = (STACK / 'browser-home.sh').read_text()
    assert '/tmp/renderer-home' in script
    assert '/run/certificates/nss-seed' in script
    assert 'umask 077' in script
    assert '[ "$(id -u)" -ne 0 ]' in script
    assert 'cert9.db' in script and 'key4.db' in script
    assert '$HOME/.pki/nssdb' in script and '$HOME/.local/share/pki/nssdb' in script
    assert 'pkcs11.txt' not in script
    assert 'exec "$@"' in script
    assert '--rebase-config' not in script and 'sed ' not in script
    subprocess.run(['sh', '-n', str(STACK / 'browser-home.sh')], check=True)


@pytest.mark.parametrize(('role', 'uid', 'cpus', 'memory', 'pids', 'shm', 'stop'), [
    ('remedy-renderer', '1001:1001', 1.5, '2g', 256, '1g', '30s'),
    ('conductor', '1000:1000', 2, '1536m', 256, '64m', '30s'),
    ('mongo', '999:999', 1, '1g', 128, '64m', '60s'),
])
def test_added_owned_services_have_finite_nonroot_sandbox_resources(role, uid, cpus, memory, pids, shm, stop):
    service = document('compose.integration.yml')['services'][role]
    assert service['user'] == uid
    assert service['init'] is True and service['read_only'] is True
    assert service['cap_drop'] == ['ALL']
    assert 'no-new-privileges:true' in service['security_opt']
    assert (service['cpus'], service['mem_limit'], service['pids_limit']) == (cpus, memory, pids)
    assert (service['shm_size'], service['stop_grace_period']) == (shm, stop)
    assert '/tmp:rw,nosuid,nodev,size=512m' in service['tmpfs']
    assert service['networks'] == ['remedy'] and service['dns'] == ['127.0.0.1']


def test_mongo_requires_provisioned_authenticated_bounded_store():
    mongo = document('compose.integration.yml')['services']['mongo']
    assert mongo['image'] == 'mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'
    assert mongo['entrypoint'] == ['mongod']
    assert mongo['command'] == ['--auth', '--bind_ip_all', '--wiredTigerCacheSizeGB', '0.25']
    assert mongo['volumes'][0]['target'] == '/data/db'
    assert '${REMEDY_MONGO_STATE_ROOT:?' in mongo['volumes'][0]['source']
    assert not any('PASSWORD' in name or 'USER' in name for name in mongo['environment'])
    assert '/data/configdb:rw,nosuid,nodev,size=16m,uid=999,gid=999,mode=0700' in mongo['tmpfs']


def test_mounts_refuse_implicit_host_creation_and_protect_credentials():
    for name in ('compose.integration.yml', 'compose.history.yml', 'compose.signed.yml'):
        for service in document(name)['services'].values():
            for mount in service.get('volumes', []):
                assert mount['type'] == 'bind'
                assert mount['bind']['create_host_path'] is False
                if mount['target'].startswith('/run/'):
                    assert mount['read_only'] is True


def test_bridge_remains_private_and_no_writer_readiness_dependency_is_added():
    base = document('docker-compose.yml')
    bridge = document('compose.bridge.yml')['services']['remedy-bridge']
    integration = document('compose.integration.yml')['services']
    assert base['networks']['remedy']['internal'] is True
    assert bridge['network_mode'] == 'service:remedy-server'
    assert env_example('remedy-bridge.env.example')['CONDUCTOR_API_HOST'] == '127.0.0.1'
    assert integration['remedy-bridge']['environment']['RENDER_SCANNER_TOKEN_FILE'] == '/run/secrets/renderer'
    for service in integration.values():
        assert 'depends_on' not in service
        assert 'network_mode' not in service and 'ports' not in service
    assert integration['remedy-renderer']['entrypoint'] == [
        'sh', '/opt/remedy-bundle/browser-home.sh', 'node',
        '/opt/remedy-bundle/secret-env.mjs', 'renderer',
    ]
    assert any('renderer-seccomp-amd64.json' in option for option in integration['remedy-renderer']['security_opt'])
