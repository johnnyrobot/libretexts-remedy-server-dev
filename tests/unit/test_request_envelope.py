"""Configured total request bytes precede normalization and product side effects."""
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import load_settings
from backend.app.main import create_app
from tests.unit.test_cxone_authenticated_forwarding import APP_KEY, SERVICE_KEY, bridge_fixture


def settings(tmp_path,monkeypatch,url):
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED','1')
    monkeypatch.setenv('MAX_REQUEST_BYTES','512')
    key=tmp_path/'service';key.write_text(SERVICE_KEY)
    return replace(load_settings(),api_key=APP_KEY,ollama_api_key='synthetic-provider',
        job_store_path=tmp_path/'jobs.db',job_dir=tmp_path/'jobs',backup_dir=tmp_path/'backups',
        cxone_integration_enabled=True,cxone_bridge_base_url=url,remedy_bridge_service_key_file=key)


@pytest.mark.asyncio
@pytest.mark.parametrize('chunked',[False,True])
async def test_raw_envelope_not_normalized_payload_controls_forwarding(tmp_path,monkeypatch,chunked):
    with bridge_fixture() as (url,observed,reply):
        app=create_app(settings(tmp_path,monkeypatch,url))
        body={'page_id':'42','padding':''}
        body['padding']='x'*(512-len(json.dumps(body).encode()))
        exact=json.dumps(body).encode();assert len(exact)==512

        async def content(raw):
            for offset in range(0,len(raw),71): yield raw[offset:offset+71]

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for raw,code in [(exact,200),(exact+b' ',413)]:
                response=await client.post('/v1/cxone/page/scan',content=content(raw) if chunked else raw,
                    headers={'X-API-Key':APP_KEY,'Content-Type':'application/json'})
                assert response.status_code==code,response.text
            assert len(observed)==1
            # Rejected body cannot poison later requests or authentication.
            assert (await client.post('/v1/cxone/page/scan',content=exact+b' ')).status_code==401
            assert (await client.post('/v1/cxone/page/scan',json={'page_id':'42'},headers={'X-API-Key':APP_KEY})).status_code==200
            assert len(observed)==2


def test_ignored_multipart_fields_are_bounded_before_job_acceptance(tmp_path,monkeypatch):
    with bridge_fixture() as (url,observed,reply):
        app=create_app(settings(tmp_path,monkeypatch,url))
        with TestClient(app) as client:
            response=client.post('/v1/convert/html-to-pdf',files={'file':('fixture.html',b'<html>Fixture</html>','text/html')},
                data={'ignored':'x'*600},headers={'X-API-Key':APP_KEY})
            assert response.status_code==413,response.text
            assert 'id' not in response.json()
            assert not list((tmp_path/'jobs').glob('*/submission.json'))
            assert client.get('/healthz').status_code==200


from backend.app.supervisor import supported


@pytest.mark.skipif(not supported(),reason='actual admitted upload requires Linux amd64 pidfd profile')
@pytest.mark.asyncio
async def test_streaming_multipart_refusal_closes_real_spooled_file(tmp_path,monkeypatch):
    import starlette.formparsers
    opened=[]
    original=starlette.formparsers.SpooledTemporaryFile

    def tracked(*args,**kwargs):
        file=original(*args,**kwargs);opened.append(file);return file

    monkeypatch.setattr(starlette.formparsers,'SpooledTemporaryFile',tracked)
    with bridge_fixture() as (url,observed,reply):
        config=replace(settings(tmp_path,monkeypatch,url),max_request_bytes=1500000)
        app=create_app(config)
        raw=(b'--fixture\r\nContent-Disposition: form-data; name="file"; filename="fixture.html"\r\n'
            b'Content-Type: text/html\r\n\r\n'+b'x'*1200000+
            b'\r\n--fixture\r\nContent-Disposition: form-data; name="ignored"\r\n\r\n'+b'x'*400000+b'\r\n--fixture--\r\n')

        async def content():
            for offset in range(0,len(raw),65536): yield raw[offset:offset+65536]

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post('/v1/convert/html-to-pdf',content=content(),
                    headers={'X-API-Key':APP_KEY,'Content-Type':'multipart/form-data; boundary=fixture'})
                assert response.status_code==413,response.text
                assert opened and all(file.closed for file in opened)
                assert any(file.name is not None for file in opened),'actual disk spool was not reached'
                assert not await app.state.store.list_by_statuses({'queued','running','done','failed'})
                assert (await client.get('/readyz')).status_code==200
