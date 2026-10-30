"""Offline checks at the public package/CI override seam; never start Docker."""
import importlib.util
import hashlib
import io
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROOF = ROOT / '.github/stack-proof'
sys.path.insert(0, str(PROOF))
spec = importlib.util.spec_from_file_location('integration_compose_proof', PROOF / 'integration_compose_proof.py')
module = importlib.util.module_from_spec(spec)


def load():
    spec.loader.exec_module(module)
    return module


def test_package_copy_retains_every_public_byte_and_resolves_only_fixture_metadata(tmp_path):
    proof = load()
    package, hashes = proof.prepare_package(ROOT, tmp_path)
    for relative, digest in hashes.items():
        assert (package / relative).read_bytes() == (ROOT / 'deploy/stack' / relative).read_bytes()
        assert len(digest) == 64
    assert (package / 'env/adapt-scanner.env').read_text().count('ADAPT_BASE_URL=http://127.0.0.1:8081') == 1
    assert 'SERVER_DOMAIN=dev.libretexts.org' in (package / 'env/remedy-bridge.env').read_text()
    assert 'REMEDY_WRITE_ALLOWLIST=^Sandboxes/johnnyphung(?:/|$)' in (package / 'env/remedy-bridge.env').read_text()
    conductor = (package / 'env/conductor.env').read_text()
    assert 'PRODUCTIONURLS=conductor.invalid,https://conductor.invalid,https://conductor.invalid:8443' in conductor
    assert 'REMEDY_REVIEWER_SIGNING' not in conductor


def test_public_tls_preparation_meets_actual_preflight_file_permissions(tmp_path, monkeypatch):
    import os
    proof = load()
    fixture = tmp_path / 'fixture'
    fixture.mkdir()
    for name in ('ca.pem', 'cert.pem', 'key.pem'):
        (fixture / name).write_text('synthetic-' + name)
    # UID transitions are the privileged OS adapter; exercise real disk modes
    # and the unchanged public preflight guard as this unprivileged test user.
    monkeypatch.setattr(proof.os, 'chown', lambda *args: None)
    root = tmp_path / 'tls'
    proof.prepare_tls(root, fixture, os.getuid())
    preflight_spec = importlib.util.spec_from_file_location('tls_preflight', ROOT / 'deploy/stack/preflight.py')
    preflight = importlib.util.module_from_spec(preflight_spec)
    preflight_spec.loader.exec_module(preflight)
    for path in root.rglob('*.pem'):
        assert preflight.protected_file(path, os.getuid()) == ('synthetic-' + path.name).encode()


def test_historical_proof_uses_the_published_nested_terminal_state():
    import json
    fixtures = json.loads((ROOT / 'tests/unit/contracts_v1/cxone-terminal-v1-fixtures.json').read_text())
    body = next(item['body'] for item in fixtures['statuses'] if item['name'] == 'not-attempted-no-change')
    assert 'state' not in body
    load().require_terminal_history(body, 'urn:conductor:synthetic', 'A' * 43, 'synthetic-terminal-epoch')


@pytest.mark.parametrize('damage', ['404', 'pending', 'wrong-epoch', 'wrong-nonce', 'outer-outcome'])
def test_historical_control_never_infers_no_write_from_untrusted_status(damage):
    import json
    fixtures = json.loads((ROOT / 'tests/unit/contracts_v1/cxone-terminal-v1-fixtures.json').read_text())
    body = next(item['body'] for item in fixtures['statuses'] if item['name'] == 'not-attempted-no-change')
    if damage == '404': body = {'error': 'operation_not_found'}
    elif damage == 'pending': body = {'outcome': 'pending', 'terminal_proof': None}
    elif damage == 'wrong-epoch': body['terminal_proof']['trust_epoch'] = 'different'
    elif damage == 'wrong-nonce': body['terminal_proof']['jti'] = 'B' * 43
    elif damage == 'outer-outcome': body['outcome'] = 'unknown_write'
    with pytest.raises(ValueError):
        load().require_terminal_history(body, 'urn:conductor:synthetic', 'A' * 43, 'synthetic-terminal-epoch')


@pytest.mark.parametrize('override', [
    {'services': {'mongo': {'command': ['mongod', '--noauth']}}},
    {'services': {'remedy-renderer': {'security_opt': ['seccomp=unconfined']}}},
    {'services': {'conductor': {'environment': {'NODE_ENV': 'test'}}}},
    {'services': {'remedy-bridge': {'network_mode': 'bridge'}}},
    {'services': {'remedy-server': {'ports': ['8000:8000']}}},
    {'services': {'remedy-server': {'volumes': [{'target': '/run/secrets', 'source': '/tmp/unprotected'}]}}},
])
def test_ci_overlay_cannot_replace_owned_service_configuration(override):
    with pytest.raises(ValueError):
        load().validate_fixture_overlay(override)


def test_ci_overlay_accepts_only_dedicated_readonly_test_driver_mounts():
    load().validate_fixture_overlay({'services': {
        'mongo': {'volumes': [
            {'type': 'bind', 'source': '/private/bootstrap', 'target': '/run/bootstrap', 'read_only': True,
             'bind': {'create_host_path': False}},
        ]},
        'conductor': {'volumes': [
            {'type': 'bind', 'source': '/private/probe.mjs', 'target': '/proof/conductor_probe.mjs', 'read_only': True,
             'bind': {'create_host_path': False}},
        ]},
    }})


def test_restored_job_requires_original_artifact_and_exact_persisted_options():
    from docx import Document
    helper_spec = importlib.util.spec_from_file_location('job_state_probe', PROOF / 'job_state_probe.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    doc = Document()
    doc.add_paragraph(helper.SENTINEL)
    stream = io.BytesIO()
    doc.save(stream)
    raw = stream.getvalue()
    status = {'id': 'a' * 32, 'kind': 'remediate_office', 'status': 'done',
              'metadata_json': '{"allow_semantic_rebuild":false}', 'created_at': 'unchanged'}
    expected = {'jobID': 'a' * 32, 'inputSHA256': 'b' * 64,
                'outputSHA256': hashlib.sha256(raw).hexdigest(), 'statusSnapshot': status}
    assert helper.verify_existing(status, raw, expected)['outputSHA256'] == expected['outputSHA256']
    with pytest.raises(ValueError, match='persisted job metadata'):
        helper.verify_existing({**status, 'metadata_json': '{}'}, raw, expected)
    with pytest.raises(ValueError, match='artifact hash'):
        helper.verify_existing(status, raw + b'changed', expected)


def test_retained_job_options_preserve_the_actual_office_acceptance_metadata():
    helper_spec = importlib.util.spec_from_file_location('job_options_probe', PROOF / 'job_state_probe.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    # The production engine enriches terminal metadata with an acceptance
    # advisory; it does not replace the original admission options.
    import json
    status = {'metadata_json': json.dumps({'allow_semantic_rebuild': False,
        'acceptance': {'passed': False, 'failed_rule_ids': ['unresolved-manual-review'], 'summary': 'Advisory remains unresolved.'}})}
    assert helper.retained_options(status) == {'allow_semantic_rebuild': False}
    original = json.loads(status['metadata_json'])
    for metadata in ({**original, 'allow_semantic_rebuild': True}, {**original, 'quality': True}, {'allow_semantic_rebuild': False}):
        with pytest.raises(ValueError, match='admission options'):
            helper.retained_options({'metadata_json': json.dumps(metadata)})
