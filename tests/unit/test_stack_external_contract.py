"""Fake external HTTP only; no product server or signed/Linux acceptance."""
import importlib.util
import json
import hashlib
import hmac
from pathlib import Path
import threading
import time
from http.client import HTTPConnection, RemoteDisconnected
from http.server import ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor

import pytest

MODULE = Path(__file__).resolve().parents[2] / ".github/stack-proof/external.py"


@pytest.fixture
def external():
    # Full unit runs may reach this file long after collection; SDK tokens are
    # deliberately short lived and must be fresh for each protocol scenario.
    AUTH.update(sdk_auth())
    spec = importlib.util.spec_from_file_location("stack_external", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    servers = []

    def start(*, kind="cxone", synthetic=False, source_controls=False):
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.build_handler(
            kind, synthetic_development_mutations=synthetic, synthetic_source_changes=source_controls))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))

        def request(method, path, body=None, headers=None):
            connection = HTTPConnection(*server.server_address, timeout=3)
            connection.request(method, path, body=body, headers=headers or {})
            try:
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        return request

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def sdk_auth(epoch=None):
    epoch = int(time.time()) if epoch is None else epoch
    digest = hmac.new(b"synthetic-secret", f"synthetic-key{epoch}=synthetic-user".encode(), hashlib.sha256).hexdigest()
    return {"X-Deki-Token": f"synthetic-key_{epoch}_=synthetic-user_{digest}"}


AUTH = sdk_auth()
CONTROL = {"X-Fixture-Control": "synthetic-control-only"}
CONTENTS = "/@api/deki/pages/42/contents"


def test_default_profile_preserves_read_envelopes_and_rejects_every_mutation(external):
    request = external()
    assert request("GET", CONTENTS)[0] == 401
    status, raw = request("GET", CONTENTS, headers=AUTH)
    assert status == 200
    assert json.loads(raw)["body"].startswith("<h1>Retained stack sentinel</h1>")
    assert request("POST", CONTENTS, "<p>must not change</p>", AUTH)[0] == 503
    status, raw = request("GET", "/control/state", headers=CONTROL)
    assert status == 200
    assert json.loads(raw)["mutations"] == 1
    assert request("POST", "/control/change-source", json.dumps({"fragment": "changed"}), CONTROL)[0] == 403
    assert request("POST", "/control/state", '{"lost_remote_response":true}', CONTROL)[0] == 403
    assert request("POST", "/control/state", '{"hold_mutation":true}', CONTROL)[0] == 403


def test_explicit_synthetic_mode_preserves_exact_utf8_and_revision_in_all_reads(external):
    request = external(synthetic=True)
    fragment = '<h1>“α-helix” — π; café; 水</h1>\n<p>Exact authored bytes.</p>'
    assert request("POST", CONTENTS, fragment.encode(), {})[0] == 401
    status, raw = request("POST", CONTENTS, fragment.encode(), AUTH)
    assert status == 200
    assert json.loads(raw) == {"page": {"@revision": "2"}}
    status, raw = request("GET", CONTENTS + "?mode=edit", headers=AUTH)
    assert json.loads(raw)["body"] == fragment
    assert json.loads(request("GET", "/@api/deki/pages/42/info", headers=AUTH)[1])["@revision"] == "2"
    reader = request("GET", "/Sandboxes/johnnyphung/Stack/Synthetic")[1].decode()
    assert fragment in reader
    assert request("POST", "/@api/deki/pages/43/contents", b"wrong page", AUTH)[0] == 503
    meta = json.loads(request("GET", "/control/status", headers=CONTROL)[1])
    assert meta["writes"] == 1
    assert meta["revision"] == 2
    assert fragment not in json.dumps(meta)


def test_signed_write_fixture_provides_explicit_headers_without_ai(external):
    from html.parser import HTMLParser
    class Table(HTMLParser):
        def __init__(self):
            super().__init__(); self.in_head = False; self.header_cells = []; self.actual_headers = 0
        def handle_starttag(self, name, attrs):
            if name == 'thead': self.in_head = True
            if name == 'th': self.actual_headers += 1
            if self.in_head and name == 'td': self.header_cells.append(dict(attrs).get('role'))
        def handle_endtag(self, name):
            if name == 'thead': self.in_head = False
    request = external(synthetic=True)
    status, raw = request('GET', CONTENTS + '?mode=edit', headers=AUTH)
    assert status == 200
    source = json.loads(raw)['body']; table = Table(); table.feed(source)
    assert table.header_cells == ['columnheader', 'columnheader']
    assert table.actual_headers == 0
    assert 'café' in source
    assert json.loads(request('GET', '/control/status', headers=CONTROL)[1])['writes'] == 0


def test_lost_response_commits_once_and_controls_never_expose_auth_or_source(external):
    request = external(synthetic=True)
    assert request("POST", "/control/state", '{"lost_remote_response":true}', {})[0] == 401
    assert request("POST", "/control/state", '{"lost_remote_response":true}', CONTROL)[0] == 200
    with pytest.raises(RemoteDisconnected):
        request("POST", CONTENTS, b"<p>Committed despite lost reply</p>", AUTH)
    assert json.loads(request("GET", CONTENTS, headers=AUTH)[1])["body"] == "<p>Committed despite lost reply</p>"
    meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
    assert (meta["writes"], meta["mutations"], meta["revision"]) == (1, 1, 2)
    assert meta["lost_remote_response"] is False
    assert "Committed despite" not in json.dumps(meta)
    assert "synthetic-cxone-token" not in json.dumps(meta)
    assert request("POST", "/control/change-source", '{"fragment":"<p>Manual edit</p>"}', CONTROL)[0] == 200
    assert json.loads(request("GET", CONTENTS, headers=AUTH)[1])["body"] == "<p>Manual edit</p>"
    assert request("POST", "/control/reset-source", "{}", CONTROL)[0] == 200
    meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
    assert (meta["writes"], meta["revision"]) == (1, 4)


@pytest.mark.parametrize("body,headers,status", [
    (b"bad", {"Content-Length": "5000001"}, 413),
    (b"bad", {"Content-Length": "-1"}, 400),
    (b"bad", {"Content-Length": "invalid"}, 400),
    (b"\xff", {}, 400),
    (b"bad", {"Transfer-Encoding": "chunked"}, 400),
])
def test_synthetic_mutation_body_limits_fail_without_committing(external, body, headers, status):
    request = external(synthetic=True)
    assert request("POST", CONTENTS, body, {**AUTH, **headers})[0] == status
    meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
    assert (meta["writes"], meta["revision"]) == (0, 1)


def test_control_is_authenticated_bounded_and_rejects_malformed_values(external):
    request = external(synthetic=True)
    assert request("POST", "/control/state", "{}", {})[0] == 401
    assert request("POST", "/control/state", "x" * 1001, CONTROL)[0] == 413
    assert request("POST", "/control/state", "not json", CONTROL)[0] == 400
    assert request("POST", "/control/state", "[]", CONTROL)[0] == 400
    assert request("POST", "/control/change-source", "{}", CONTROL)[0] == 400
    assert request("POST", "/control/change-source", '{"fragment":"\\ud800"}', CONTROL)[0] == 400


@pytest.mark.parametrize("auth", [
    {}, {"X-Deki-Token": "arbitrary-provider-token"},
    {"X-Deki-Token": "synthetic-key_1234567890_=synthetic-user_" + "0" * 64},
    sdk_auth(1234567890),
])
def test_only_fresh_actual_synthetic_sdk_auth_can_commit(external, auth):
    request = external(synthetic=True)
    assert request("POST", CONTENTS, b"<p>Rejected</p>", auth)[0] == 401
    meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
    assert meta["writes"] == 0
    assert meta["denied"] == 1


def test_synthetic_hold_is_observable_and_released_without_changing_bytes(external):
    request = external(synthetic=True)
    assert request("POST", "/control/state", '{"hold_mutation":true}', CONTROL)[0] == 200
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request, "POST", CONTENTS, b"<p>Barrier exact bytes</p>", AUTH)
        try:
            deadline = time.monotonic() + 2
            while True:
                meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
                if meta["mutation_held"] == 1:
                    break
                assert time.monotonic() < deadline
                time.sleep(.01)
            assert meta["writes"] == 0
            assert not pending.done()
        finally:
            request("POST", "/control/state", '{"hold_mutation":false}', CONTROL)
        assert pending.result()[0] == 200
    meta = json.loads(request("GET", "/control/state", headers=CONTROL)[1])
    assert (meta["writes"], meta["revision"]) == (1, 2)
    assert json.loads(request("GET", CONTENTS, headers=AUTH)[1])["body"] == "<p>Barrier exact bytes</p>"


def test_adapt_envelopes_remain_separate_from_cxone_fragments(external):
    request = external(kind="adapt")
    headers = {"Authorization": "Bearer synthetic-adapt-token"}
    assert request("GET", "/api/assignments/1/questions/ids")[0] == 401
    status, raw = request("GET", "/api/assignments/1/questions/ids", headers=headers)
    assert status == 200
    assert json.loads(raw) == {"type": "success", "question_ids_array": [101], "question_ids": "[101]"}
    assert request("GET", "/api/get-header-html/101", headers=headers)[1].startswith(b"<!doctype html>")
    assert request("POST", "/control/state", '{"empty":true}', CONTROL)[0] == 200
    assert json.loads(request("GET", "/api/assignments/1/questions/ids", headers=headers)[1])["question_ids_array"] == []
    assert request("POST", "/control/state", '{"malformed":true}', CONTROL)[0] == 200
    assert json.loads(request("GET", "/api/assignments/1/questions/ids", headers=headers)[1]) == {"type": "success"}


def test_source_change_controls_do_not_enable_external_mutations(external):
    request=external(source_controls=True)
    fragment='<h1>Changed synthetic reader without a write API</h1>'
    assert request('POST','/control/change-source',json.dumps({'fragment':fragment}),CONTROL)[0]==200
    assert json.loads(request('GET',CONTENTS,headers=AUTH)[1])['body']==fragment
    assert json.loads(request('GET','/control/status',headers=CONTROL)[1])['mutations']==0
    assert request('POST',CONTENTS,'<h1>blocked</h1>',AUTH)[0]==503
    assert request('POST','/control/state','{"lost_remote_response":true}',CONTROL)[0]==403
