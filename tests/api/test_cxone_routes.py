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
        if isinstance(self._data, Exception):
            raise self._data
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

    async def get(self, path: str):
        self.calls.append({"path": path, "client_kwargs": self.kwargs})
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


def _settings(
    tmp_path: Path,
    *,
    api_key: str = "",
    cxone_integration_enabled: bool = True,
) -> Settings:
    return Settings(
        api_key=api_key,
        ollama_api_key="test-ollama-key",
        job_store_path=tmp_path / "state" / "jobs.db",
        job_dir=tmp_path / "job_data",
        backup_dir=tmp_path / "job_backups",
        cxone_integration_enabled=cxone_integration_enabled,
        cxone_bridge_base_url="http://bridge.local",
        cxone_bridge_timeout_seconds=12.0,
    )


def _create_test_app(
    tmp_path: Path,
    monkeypatch,
    *,
    api_key: str = "",
    cxone_integration_enabled: bool = True,
):
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    return main.create_app(_settings(
        tmp_path,
        api_key=api_key,
        cxone_integration_enabled=cxone_integration_enabled,
    ))


def test_cxone_is_disabled_by_default_without_affecting_core_health(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(
        tmp_path,
        monkeypatch,
        cxone_integration_enabled=False,
    )

    with TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        integration = client.get("/v1/cxone/health")
        scan = client.post(
            "/v1/cxone/page/scan",
            json={"page_id": 123},
        )

    assert health.status_code == 200
    assert ready.status_code == 200
    assert integration.status_code == 200
    assert integration.json() == {
        "ok": True,
        "state": "disabled",
        "enabled": False,
        "write_scope": {
            "host": "dev.libretexts.org",
            "root": "Sandboxes/johnnyphung",
        },
    }
    assert scan.status_code == 503
    assert scan.json()["detail"]["error"] == "cxone_integration_disabled"
    assert _RecordingAsyncClient.calls == []


def test_cxone_health_reports_bridge_state_without_changing_core_readiness(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(
        200,
        {"ok": False, "state": "misconfigured", "error": "cxone_configuration_invalid"},
    )
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        integration = client.get("/v1/cxone/health")
        ready = client.get("/readyz")

    assert integration.status_code == 200
    assert integration.json()["state"] == "misconfigured"
    assert integration.json()["ok"] is False
    assert ready.status_code == 200
    assert _RecordingAsyncClient.calls == [{
        "path": "/healthz",
        "client_kwargs": {"base_url": "http://bridge.local", "timeout": 5.0},
    }]


def test_cxone_health_maps_non_json_bridge_response_to_degraded(monkeypatch, tmp_path):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response = _FakeBridgeResponse(200, ValueError("not json"))
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        integration = client.get("/v1/cxone/health")
        core_health = client.get("/healthz")

    assert integration.status_code == 200
    assert integration.json()["state"] == "degraded"
    assert integration.json()["error"] == "cxone_bridge_unavailable"
    assert core_health.status_code == 200


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
