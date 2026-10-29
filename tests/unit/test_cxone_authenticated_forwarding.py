"""Actual ASGI -> local HTTP hop; synthetic Bridge, keys and assertions only."""
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.cxone_routes import build_router

VECTORS = json.loads((Path(__file__).parent / 'contracts_v1/lt-1-reviewer-wire-v1-vectors.json').read_text())
SERVICE_KEY = 'a1' * 32
APP_KEY = 'synthetic-inbound-only'
UNKNOWN = {'error': 'write_outcome_unknown', 'outcome': 'unknown_write', 'operation_id': 'synthetic-operation',
           'applied': None, 'restored': False, 'audit_recorded': None, 'requires_reconciliation': True,
           'reconciliation': 'required', 'evidence_effect': 'invalidate'}


@contextmanager
def bridge_fixture():
    observed = []
    reply = SimpleNamespace(status=200, body={'ok': True}, disconnect=False)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            self.respond(body)

        def do_GET(self):
            self.respond(None)

        def respond(self, body):
            observed.append((self.path, self.headers, body))
            if reply.disconnect:
                self.close_connection = True
                return
            encoded = json.dumps(reply.body).encode()
            self.send_response(reply.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', observed, reply
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def forwarding_client(tmp_path):
    with bridge_fixture() as (url, observed, reply):
        key = tmp_path / 'synthetic-key'
        key.write_text(SERVICE_KEY + '\n')
        settings = Settings(api_key=APP_KEY, cxone_integration_enabled=True, cxone_bridge_base_url=url,
                            remedy_bridge_service_key_file=key)
        app = FastAPI()
        app.include_router(build_router(settings))
        with TestClient(app) as client:
            client.headers['X-API-Key'] = APP_KEY
            yield client, observed, reply


def mutation(vector=None):
    vector = vector or VECTORS['positive'][0]
    return {'page_id': '42', 'preview_hash': 'compat-hash', 'preview_token': vector['context']['expected_binding']['preview_token'],
            'reviewer_assertion': vector['compact']}


def test_exact_assertion_and_unknown_outcome_survive_both_hops(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.status, reply.body = 502, UNKNOWN
        response = client.post('/v1/cxone/page/apply-fix', json=mutation())
        assert response.status_code == 502
        assert response.json() == UNKNOWN
        assert len(observed) == 1
        _, headers, body = observed[0]
        assert headers.get('X-Remedy-Service-Key') == SERVICE_KEY
        assert headers.get('X-API-Key') is None
        assert body['reviewer_assertion'] == VECTORS['positive'][0]['compact']
        assert 'requested_by' not in body


@pytest.mark.parametrize('status,body', [
    (200, {'outcome': 'not_attempted', 'reason': 'no_change', 'applied': False, 'evidence_effect': 'preserve'}),
    (200, {'outcome': 'known_success', 'applied': True, 'audit_recorded': False, 'evidence_effect': 'invalidate'}),
    (409, {'outcome': 'not_attempted', 'reason': 'stale_preview', 'evidence_effect': 'invalidate'}),
    (403, {'outcome': 'not_attempted', 'reason': 'target_mismatch', 'evidence_effect': 'invalidate'}),
    (503, {'error': 'claim_store_unavailable', 'outcome': 'pending', 'evidence_effect': 'hold'}),
])
def test_status_and_evidence_are_not_reinterpreted(tmp_path, status, body):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.status, reply.body = status, body
        response = client.post('/v1/cxone/page/apply-fix', json=mutation())
        assert (response.status_code, response.json()) == (status, body)
        assert len(observed) == 1


@pytest.mark.parametrize('vector', VECTORS['positive'], ids=lambda v: v['name'])
def test_shared_positive_vector_bytes_are_forwarded_without_identity_changes(tmp_path, vector):
    with forwarding_client(tmp_path) as (client, observed, reply):
        action = 'restore' if vector['context']['expected_binding']['action'] == 'cxone.restore' else 'apply-fix'
        response = client.post(f'/v1/cxone/page/{action}', json=mutation(vector))
        assert response.status_code == 200
        assert observed[0][2]['reviewer_assertion'].encode('ascii') == vector['compact'].encode('ascii')


def test_shared_corpus_raw_signatures_with_independent_python_crypto():
    import base64
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    def decode(text):
        return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    key = Ed25519PublicKey.from_public_bytes(decode(VECTORS['public_jwk']['x']))
    for vector in VECTORS['positive'] + VECTORS['negative']:
        assertion = vector['compact']
        h, p, s = assertion.split('.')
        try:
            key.verify(decode(s), (h + '.' + p).encode('ascii'))
            valid = True
        except InvalidSignature:
            valid = False
        assert valid == vector['raw_signature_valid'], vector['name']


@pytest.mark.parametrize('headers', [[], [('X-API-Key', 'wrong')],
    [('X-API-Key', APP_KEY), ('x-api-key', APP_KEY)], [('X-API-Key', APP_KEY), ('x-api-key', 'wrong')]])
def test_inbound_key_missing_incorrect_duplicate_is_denied_before_bridge(tmp_path, headers):
    with forwarding_client(tmp_path) as (client, observed, reply):
        client.headers.pop('X-API-Key')
        response = client.post('/v1/cxone/page/scan', json={'page_id': '42'}, headers=headers)
        assert response.status_code == 401
        assert not observed


@pytest.mark.parametrize('bad', [' a.b.c', 'YQ.YQ.YQ==', 'YQ.YQ.YR', 'YQ..YQ', 'YQ.YQ.YQ.extra', 7, None, 'a' * 8193])
def test_invalid_assertion_encoding_never_reaches_bridge_or_error_body(tmp_path, bad):
    with forwarding_client(tmp_path) as (client, observed, reply):
        response = client.post('/v1/cxone/page/apply-fix', json={**mutation(), 'reviewer_assertion': bad})
        assert response.status_code == 400
        assert response.json() == {'detail': 'Invalid CXone JSON or assertion transport.'}
        assert not observed


@pytest.mark.parametrize('carrier', ['duplicate', 'escaped_duplicate', 'camel', 'header', 'query', 'cookie', 'authorization', 'nested'])
def test_duplicate_or_alternate_assertion_carriers_are_denied(tmp_path, carrier):
    with forwarding_client(tmp_path) as (client, observed, reply):
        body = mutation()
        options = {}
        path = '/v1/cxone/page/apply-fix'
        if carrier in {'duplicate', 'escaped_duplicate'}:
            field = 'reviewer_assertion' if carrier == 'duplicate' else r'reviewer_\u0061ssertion'
            options['content'] = json.dumps(body)[:-1] + ',"' + field + '":"YQ.YQ.YQ"}'
            options['headers'] = {'Content-Type': 'application/json'}
        else:
            if carrier == 'camel':
                body['reviewerAssertion'] = body['reviewer_assertion']
            elif carrier == 'nested':
                body['extra'] = {'reviewer_assertion': body['reviewer_assertion']}
            elif carrier == 'header':
                options['headers'] = {'X-Remedy-Reviewer-Assertion': body['reviewer_assertion']}
            elif carrier == 'query':
                path += '?reviewer_assertion=YQ.YQ.YQ'
            elif carrier == 'cookie':
                options['headers'] = {'Cookie': 'reviewer_assertion=YQ.YQ.YQ'}
            else:
                options['headers'] = {'Authorization': 'Bearer YQ.YQ.YQ'}
            options['json'] = body
        response = client.post(path, **options)
        assert response.status_code == 400
        assert not observed


def test_status_lookup_is_authenticated_readonly_and_preserves_pair_and_metadata(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = {**UNKNOWN, 'outcome': 'pending', 'evidence_effect': 'hold'}
        pair = {'issuer': 'urn:libretexts:conductor:test', 'jti': 'A' * 43}
        response = client.post('/v1/cxone/page/operation-status', json=pair)
        assert (response.status_code, response.json()) == (200, reply.body)
        assert observed[0][2] == pair
        assert len(observed) == 1
        reply.status, reply.body = 404, {'error': 'operation_not_found'}
        assert client.post('/v1/cxone/page/operation-status', json=pair).status_code == 404
        assert len(observed) == 2
        assert client.post('/v1/cxone/page/operation-status', json={**pair, 'page_id': '42'}).status_code == 400
        assert len(observed) == 2


@pytest.mark.parametrize('state,status,ok', [('ready', 200, True), ('degraded', 503, False), ('misconfigured', 503, False)])
def test_private_readiness_capabilities_are_forwarded(tmp_path, state, status, ok):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.status = status
        reply.body = {'ok': ok, 'state': state, 'capabilities': {'scan': True, 'preview': True, 'mutate': ok, 'operation_status': ok}}
        response = client.get('/v1/cxone/health')
        assert (response.status_code, response.json()) == (status, {**reply.body, 'enabled': True})
        path, headers, body = observed[0]
        assert path == '/readyz'
        assert headers.get('X-Remedy-Service-Key') == SERVICE_KEY
        assert headers.get('X-API-Key') is None


def test_liveness_alone_does_not_establish_readiness(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = {'ok': True, 'state': 'ready'}
        assert client.get('/v1/cxone/health').status_code == 503


def test_preview_binding_and_expiry_remain_authoritative(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = {'review_binding': VECTORS['positive'][0]['context']['expected_binding'], 'review_expires_at': 1793255500}
        response = client.post('/v1/cxone/page/preview-fix', json={'page_id': '42'})
        assert response.json() == reply.body


def test_lost_mutation_response_does_not_retry_or_claim_no_write(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.disconnect = True
        response = client.post('/v1/cxone/page/apply-fix', json=mutation())
        assert response.status_code == 502
        assert response.json()['detail']['outcome'] == 'unknown_write'
        assert response.json()['detail']['evidence_effect'] == 'invalidate'
        assert response.json()['detail']['retryable'] is False
        assert len(observed) == 1


@pytest.mark.parametrize('raw', [b'', b'a' * 63, b'A' * 64, b'a' * 64 + b'\n\n', b'a' * 64 + b' ', b'a' * 64 + b'\r\n'])
def test_malformed_service_file_fails_safe_preflight(tmp_path, raw):
    path = tmp_path / 'key'
    path.write_bytes(raw)
    settings = Settings(api_key=APP_KEY, cxone_integration_enabled=True, remedy_bridge_service_key_file=path)
    errors = settings.validation_errors()
    assert any('REMEDY_BRIDGE_SERVICE_KEY_FILE' in error for error in errors)
    assert all(str(path) not in error for error in errors)


def test_no_production_downgrade_and_key_is_read_once(tmp_path):
    path = tmp_path / 'key'
    path.write_text(SERVICE_KEY)
    settings = Settings(api_key=APP_KEY, cxone_integration_enabled=True, remedy_bridge_service_key_file=path)
    assert settings.validation_errors() == []
    path.write_text('invalid replacement')
    assert settings.bridge_service_key == SERVICE_KEY
    assert Settings(app_env='production', remedy_reviewer_required=False, cxone_integration_enabled=True).validation_errors()
    assert Settings(remedy_reviewer_required=False, cxone_integration_enabled=True, cxone_bridge_base_url='http://bridge:5175').validation_errors()


def test_missing_assertion_is_rejected_without_remote_attempt(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        body = mutation()
        body.pop('reviewer_assertion')
        assert client.post('/v1/cxone/page/apply-fix', json=body).status_code == 401
        assert not observed


def test_full_app_unknown_alias_auth_and_public_liveness(tmp_path):
    from backend.app.main import create_app
    settings = Settings(api_key=APP_KEY, job_store_path=tmp_path / 'jobs.db', job_dir=tmp_path / 'jobs',
                        backup_dir=tmp_path / 'backups')
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/cxone/api/apply', content='invalid json').status_code == 401
        assert client.post('/v1/cxone/api/apply', headers={'X-API-Key': APP_KEY}).status_code == 404
        assert client.get('/healthz').json() == {'ok': True}
        assert client.post('/v1/cxone/page/scan', json={'page_id': '42'},
                           headers=[('X-API-Key', APP_KEY), ('x-api-key', APP_KEY)]).status_code == 401


def test_negative_shared_corpus_transport_preserves_bytes_or_rejects_encoding(tmp_path):
    # Synthetic peer deliberately rejects all negative vectors; it is not the
    # product verifier. Policy/crypto rejection belongs to actual Bridge tests.
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.status, reply.body = 401, {'error': 'invalid_reviewer_assertion', 'outcome': 'not_attempted'}
        for vector in VECTORS['negative']:
            before = len(observed)
            response = client.post('/v1/cxone/page/apply-fix', json={**mutation(), 'reviewer_assertion': vector['compact']})
            if vector['name'] not in {'padded-header-segment', 'noncanonical-signature-base64url'}:
                assert (response.status_code, response.json()) == (401, reply.body), vector['name']
                assert observed[-1][2]['reviewer_assertion'] == vector['compact'], vector['name']
                assert len(observed) == before + 1
            else:
                assert response.status_code == 400, vector['name']
                assert len(observed) == before


def test_cors_preflight_reaches_configured_cors_policy_without_disclosing_data(tmp_path):
    from backend.app.main import create_app
    settings = Settings(api_key=APP_KEY, job_store_path=tmp_path / 'jobs.db', job_dir=tmp_path / 'jobs',
                        backup_dir=tmp_path / 'backups', cors_allow_origins=['https://conductor.example.invalid'])
    with TestClient(create_app(settings)) as client:
        response = client.options('/v1/cxone/page/scan', headers={
            'Origin': 'https://conductor.example.invalid', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'X-API-Key,Content-Type'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'https://conductor.example.invalid'
        assert client.post('/v1/cxone/page/scan', json={'page_id': '42'}).status_code == 401


def test_invalid_required_mode_environment_never_downgrades(monkeypatch):
    from backend.app.config import load_settings
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    monkeypatch.setenv('REMEDY_REVIEWER_REQUIRED', 'typo')
    with pytest.raises(ValueError, match='explicit boolean'):
        load_settings()


def test_invalid_mutation_never_echoes_assertion_in_validation_errors(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        body = mutation()
        body.pop('preview_hash')
        response = client.post('/v1/cxone/page/apply-fix', json=body)
        assert response.status_code == 422
        assert body['reviewer_assertion'] not in response.text
        assert not observed


@pytest.mark.parametrize('query', [{}, {'issuer': 'test', 'jti': 7}, {'issuer': 'test', 'jti': 'B' * 43},
                                   {'issuer': 'test', 'jti': 'A' * 43, 'extra': True}])
def test_malformed_operation_lookup_is_safe_400(tmp_path, query):
    with forwarding_client(tmp_path) as (client, observed, reply):
        assert client.post('/v1/cxone/page/operation-status', json=query).status_code == 400
        assert not observed


def test_openapi_still_documents_inbound_key_header():
    app = FastAPI()
    app.include_router(build_router(Settings(api_key=APP_KEY)))
    parameters = app.openapi()['paths']['/v1/cxone/page/scan']['post']['parameters']
    assert any(p['name'].lower() == 'x-api-key' and p['in'] == 'header' for p in parameters)


TERMINAL_V1 = json.loads((Path(__file__).parent / 'contracts_v1/cxone-terminal-v1-fixtures.json').read_text())


@pytest.mark.parametrize('status,body',
    [(200, item['body']) for item in TERMINAL_V1['statuses']] + [
        (200, {'outcome': 'pending', 'terminal_proof': None}),
        (200, {'outcome': 'unknown_write', 'reconciliation': 'resolved', 'terminal_proof': None}),
        (404, {'error': 'operation_not_found'}),
        (503, {'error': 'claim_store_unavailable'}),
    ])
def test_terminal_v1_projection_is_preserved_without_signer_or_outcome_inference(tmp_path, status, body):
    # Producer fixture is immutable synthetic data. Its hostname is never used
    # as a network destination: the only upstream hop is this local HTTP fixture.
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.status, reply.body = status, body
        pair = {'issuer': 'urn:conductor:synthetic', 'jti': 'A' * 43}
        response = client.post('/v1/cxone/page/operation-status', json=pair)
        assert (response.status_code, response.json()) == (status, body)
        assert len(observed) == 1
        path, headers, forwarded = observed[0]
        assert path == '/v1/cxone/page/operation-status' and forwarded == pair
        assert headers.get('X-Remedy-Service-Key') == SERVICE_KEY
        assert headers.get('X-API-Key') is None
        # A caller cannot substitute its own proof or target for stored identity.
        refused = client.post('/v1/cxone/page/operation-status', json={**pair, 'terminal_proof': body.get('terminal_proof')})
        assert refused.status_code == 400
        assert len(observed) == 1


def test_absent_bridge_explicitly_has_no_mutation_capability(tmp_path):
    # Engine/Scanner operation needs no Bridge service/signing configuration.
    app = FastAPI()
    app.include_router(build_router(Settings(api_key=APP_KEY)))
    with TestClient(app) as client:
        response = client.get('/v1/cxone/health', headers={'X-API-Key': APP_KEY})
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'state': 'disabled', 'enabled': False,
        'capabilities': {'scan': False, 'preview': False, 'mutate': False, 'operation_status': False}}


REVIEW_READY = {'ok': True, 'state': 'ready',
    'capabilities': {'scan': True, 'preview': True, 'mutate': False, 'operation_status': False},
    'profile': {'contract': 'cxone-review-v1', 'name': 'review-only',
                'required_capabilities': ['scan', 'preview'], 'unavailable_reasons': []}}


def test_selected_review_profile_accepts_only_its_required_read_capabilities(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = REVIEW_READY
        response = client.get('/v1/cxone/health')
        assert response.status_code == 200
        assert response.json() == {**REVIEW_READY, 'enabled': True}


@pytest.mark.parametrize('damage', ['legacy-partial', 'null-profile', 'unknown-contract', 'unknown-name',
                                  'missing-required', 'duplicate-required', 'scan-failed', 'mutation-enabled',
                                  'invalid-reasons', 'ready-with-reasons'])
def test_readiness_rejects_unknown_or_inconsistent_profile(tmp_path, damage):
    body = json.loads(json.dumps(REVIEW_READY))
    if damage == 'legacy-partial': del body['profile']
    elif damage == 'null-profile': body['profile'] = None
    elif damage == 'unknown-contract': body['profile']['contract'] = 'future-unverified'
    elif damage == 'unknown-name': body['profile']['name'] = 'scan-only'
    elif damage == 'missing-required': body['profile']['required_capabilities'] = []
    elif damage == 'duplicate-required': body['profile']['required_capabilities'] = ['scan', 'scan', 'preview']
    elif damage == 'scan-failed': body['capabilities']['scan'] = False
    elif damage == 'mutation-enabled': body['capabilities']['mutate'] = True
    elif damage == 'invalid-reasons': body['profile']['unavailable_reasons'] = None
    else: body['profile']['unavailable_reasons'] = ['read_dependency_unavailable']
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = body
        response = client.get('/v1/cxone/health')
        assert response.status_code == 503
        assert response.json()['error'] == 'cxone_readiness_invalid'


@pytest.mark.parametrize('field', ['state', 'name'])
def test_readiness_malformed_list_fields_fail_closed(tmp_path, field):
    body = json.loads(json.dumps(REVIEW_READY))
    if field == 'state': body['state'] = []
    else: body['profile']['name'] = []
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = body
        assert client.get('/v1/cxone/health').status_code == 503


def test_legacy_full_readiness_ignores_additive_unrequired_capability(tmp_path):
    with forwarding_client(tmp_path) as (client, observed, reply):
        reply.body = {'ok': True, 'state': 'ready', 'capabilities':
                      {'scan': True, 'preview': True, 'mutate': True, 'operation_status': True, 'future_optional': False}}
        response = client.get('/v1/cxone/health')
        assert response.status_code == 200
        assert 'profile' not in response.json()
