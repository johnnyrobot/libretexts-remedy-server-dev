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
