"""Direct child replay must retain the trusted parent ASGI request semantics."""
import json
from io import BytesIO

import httpx
import pytest
from fastapi import FastAPI

from backend.app.config import Settings
from backend.app.execution import execute_http


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("JOB_STORE_PATH", str(tmp_path / "import.db"))
    monkeypatch.setenv("JOB_DIR", str(tmp_path / "import-jobs"))
    return Settings(api_key="fixture-key", job_store_path=tmp_path / "request.db", job_dir=tmp_path / "jobs")


@pytest.mark.parametrize("scheme", ["https", "http"])
async def test_replay_slash_redirect_matches_framework_scheme_host_query(settings, scheme):
    path, query = "/v1/pdf/check/", b"probe=a%2Fb&probe=c"
    headers = [(b"host", b"synthetic.invalid:8443"), (b"x-api-key", b"fixture-key"),
               (b"x-forwarded-proto", b"untrusted-scheme")]
    wire = {"scheme": scheme, "method": "POST", "path": path, "query_string": query, "headers": headers}
    code, returned_headers, _ = await execute_http(settings, wire, b"", emit=lambda _: None)
    control = FastAPI()
    @control.post("/v1/pdf/check")
    async def unreachable():
        raise AssertionError("Redirect must precede route execution")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control),
                                base_url=f"{scheme}://synthetic.invalid:8443", follow_redirects=False) as client:
        expected = await client.post(path + "?" + query.decode(), headers=dict(headers))
    assert code == expected.status_code == 307
    assert dict(returned_headers)[b"location"].decode() == expected.headers["location"]
    assert expected.headers["location"] == f"{scheme}://synthetic.invalid:8443/v1/pdf/check?probe=a%2Fb&probe=c"


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("key,expected", [("fixture-key", 200), ("wrong-fixture-key", 401)])
async def test_replay_actual_office_route_preserves_body_and_auth_headers(settings, scheme, key, expected):
    from docx import Document
    document = Document()
    document.add_paragraph("Synthetic replay sentinel")
    source = BytesIO()
    document.save(source)
    request = httpx.Request("POST", f"{scheme}://synthetic.invalid/v1/office/check?fixture=retained",
                           headers={"X-API-Key": key, "X-Request-ID": "synthetic-replay-id"},
                           files={"file": ("fixture.docx", source.getvalue())})
    body = request.read()
    wire = {"scheme": scheme, "method": request.method, "path": request.url.path,
            "query_string": request.url.query, "headers": list(request.headers.raw)}
    code, headers, content = await execute_http(settings, wire, body, emit=lambda _: None)
    assert code == expected
    if code == 200:
        assert dict(headers)[b"x-request-id"] == b"synthetic-replay-id"
        payload = json.loads(content)
        assert payload["file_type"] == "docx" and payload["package_valid"] is True
