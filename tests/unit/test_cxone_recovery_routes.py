from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.cxone_routes import build_router


def test_recovery_routes_require_auth_and_forward_review_tokens():
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(api_key="test-key")))
    client = TestClient(app)
    cases = {
        "snapshots": {},
        "restore-preview": {"snapshot_timestamp": "2026-09-13T17:00:00Z"},
        "restore": {"preview_hash": "hash", "preview_token": "reviewed"},
        "revise-preview": {"preview_token": "reviewed", "alt_edits": [{"src": "a.gif", "text": "Description"}]},
    }
    for action, fields in cases.items():
        path = f"/v1/cxone/page/{action}"
        body = {"page_id": 4218, **fields}
        with patch("backend.app.cxone_routes._forward", new_callable=AsyncMock) as forward:
            forward.return_value = {"ok": True}
            assert client.post(path, json=body).status_code == 401
            forward.assert_not_called()
            assert client.post(path, json=body, headers={"X-API-Key": "test-key"}).status_code == 200
            assert forward.call_args.args[1:] == (path, body)


def test_restore_requires_reviewed_preview():
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(api_key="test-key")))
    response = TestClient(app).post("/v1/cxone/page/restore", json={"page_id": 4218}, headers={"X-API-Key": "test-key"})
    assert response.status_code == 422
