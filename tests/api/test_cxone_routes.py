from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.config import Settings


class _FakeBridgeResponse:
    def __init__(self, status_code: int, data: Any):
        self.status_code = status_code
        self._data = data

    def json(self) -> Any:
        return self._data


class _RecordingAsyncClient:
    calls: list[dict[str, Any]] = []
    response = _FakeBridgeResponse(200, {"ok": True})

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return None

    async def post(self, path: str, json: dict[str, Any]):
        self.calls.append(
            {
                "path": path,
                "payload": json,
                "client_kwargs": self.kwargs,
            }
        )
        return self.response


def _configure_import_env(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "import-state"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("JOB_STORE_PATH", str(state_dir / "jobs.db"))
    monkeypatch.setenv("JOB_DIR", str(state_dir / "jobs"))
    monkeypatch.setenv("JOB_BACKUP_DIR", str(state_dir / "job_backups"))


def _settings(tmp_path: Path, *, api_key: str = "") -> Settings:
    return Settings(
        api_key=api_key,
        ollama_api_key="test-ollama-key",
        job_store_path=tmp_path / "state" / "jobs.db",
        job_dir=tmp_path / "job_data",
        backup_dir=tmp_path / "job_backups",
        cxone_bridge_base_url="http://bridge.local",
        cxone_bridge_timeout_seconds=12.0,
    )


def _create_test_app(tmp_path: Path, monkeypatch, *, api_key: str = ""):
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    return main.create_app(_settings(tmp_path, api_key=api_key))


def test_cxone_scan_route_forwards_to_configured_bridge(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(
        200,
        {
            "criteria": {"imgAltText": True},
            "evaluated_keys": ["imgAltText"],
            "findings": [],
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/cxone/page/scan",
            json={
                "page_url": "https://dev.libretexts.org/Sandboxes/Test",
                "section_title": "Test",
            },
        )

    assert response.status_code == 200
    assert response.json()["criteria"] == {"imgAltText": True}
    assert _RecordingAsyncClient.calls == [
        {
            "path": "/v1/cxone/page/scan",
            "payload": {
                "page_url": "https://dev.libretexts.org/Sandboxes/Test",
                "section_title": "Test",
            },
            "client_kwargs": {
                "base_url": "http://bridge.local",
                "timeout": 12.0,
            },
        }
    ]


def test_cxone_scan_route_preserves_review_context(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(200, {"ok": True})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/cxone/page/scan",
            json={
                "page_id": 123,
                "wcag_review": {"criteria": [{"id": "1.1.1"}]},
                "doj_exceptions": [{"criterionId": "1.1.1", "status": "verified"}],
            },
        )

    assert response.status_code == 200
    assert _RecordingAsyncClient.calls[0]["payload"] == {
        "page_id": 123,
        "wcag_review": {"criteria": [{"id": "1.1.1"}]},
        "doj_exceptions": [{"criterionId": "1.1.1", "status": "verified"}],
    }


def test_cxone_routes_use_existing_api_key_auth(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(200, {"ok": True})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch, api_key="local-secret")

    with TestClient(app) as client:
        missing = client.post(
            "/v1/cxone/page/preview-fix",
            json={"page_id": 123, "finding_ids": []},
        )
        ok = client.post(
            "/v1/cxone/page/preview-fix",
            headers={"X-API-Key": "local-secret"},
            json={"page_id": 123, "finding_ids": []},
        )

    assert missing.status_code == 401
    assert ok.status_code == 200
    assert _RecordingAsyncClient.calls[0]["payload"] == {
        "page_id": 123,
        "finding_ids": [],
    }


def test_cxone_preview_route_forwards_pipeline_options(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(200, {"ok": True})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/cxone/page/preview-fix",
            json={
                "page_url": "Sandboxes/Test",
                "finding_ids": ["img-alt#0"],
                "fix_mode": "pipeline",
                "tier": 2,
            },
        )

    assert response.status_code == 200
    assert _RecordingAsyncClient.calls[0]["payload"] == {
        "page_url": "Sandboxes/Test",
        "finding_ids": ["img-alt#0"],
        "fix_mode": "pipeline",
        "tier": 2,
    }


def test_cxone_apply_route_forwards_pipeline_preview_token(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(200, {"ok": True})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/cxone/page/apply-fix",
            json={
                "page_id": 123,
                "preview_hash": "preview123",
                "preview_token": "token-123",
                "fix_mode": "pipeline",
                "tier": 3,
            },
        )

    assert response.status_code == 200
    assert _RecordingAsyncClient.calls[0]["payload"] == {
        "page_id": 123,
        "finding_ids": [],
        "fix_mode": "pipeline",
        "tier": 3,
        "preview_hash": "preview123",
        "preview_token": "token-123",
    }


def test_cxone_route_surfaces_bridge_error_detail(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(
        409,
        {
            "error": "stale_preview",
            "message": "Page content changed since preview; refresh and preview again.",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/cxone/page/apply-fix",
            json={"page_url": "Sandboxes/Test", "preview_hash": "old"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "error": "stale_preview",
        "message": "Page content changed since preview; refresh and preview again.",
        "bridge_status": 409,
    }


def test_cxone_route_rejects_missing_page_identifier(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post("/v1/cxone/page/scan", json={"section_title": "No page"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "missing_page_identifier"
    assert _RecordingAsyncClient.calls == []
