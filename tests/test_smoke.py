from __future__ import annotations

import base64
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from project_remedy.pdf_vision import FallbackVisionProvider, OllamaVisionProvider


def _configure_import_env(monkeypatch, tmp_path: Path) -> None:
    """Keep backend.app.main's module-level app out of the repo root."""
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
    )


def _create_test_app(tmp_path: Path, monkeypatch, *, api_key: str = ""):
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    return main.create_app(_settings(tmp_path, api_key=api_key))


def test_core_modules_import(monkeypatch, tmp_path):
    _configure_import_env(monkeypatch, tmp_path)
    modules = [
        "backend.app.auth",
        "backend.app.config",
        "backend.app.routes",
        "backend.app.main",
        "project_remedy",
        "project_remedy.pdf_acceptance",
        "project_remedy.pdf_checker",
    ]

    for module in modules:
        assert importlib.import_module(module)


def test_healthz_and_readyz(monkeypatch, tmp_path):
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"ok": True}
    assert ready.status_code == 200
    assert ready.json() == {
        "ok": True,
        "checks": {
            "job_store": "ok",
            "job_dir": "ok",
            "worker": "ok",
        },
    }


def test_auth_disabled_allows_v1_route_execution(monkeypatch, tmp_path):
    app = _create_test_app(tmp_path, monkeypatch, api_key="")

    with TestClient(app) as client:
        response = client.get("/v1/jobs/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


def test_api_key_auth_rejects_missing_or_wrong_key(monkeypatch, tmp_path):
    app = _create_test_app(tmp_path, monkeypatch, api_key="ci-secret")

    with TestClient(app) as client:
        missing = client.get("/v1/jobs/missing")
        wrong = client.get("/v1/jobs/missing", headers={"X-API-Key": "wrong"})
        allowed = client.get("/v1/jobs/missing", headers={"X-API-Key": "ci-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 404


def test_pdf_vision_alt_text_stages_uploaded_image(monkeypatch, tmp_path):
    app = _create_test_app(tmp_path, monkeypatch, api_key="")
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )

    class FakeProvider:
        seen_path: Path | None = None
        seen_bytes: bytes = b""
        existed_during_call = False

        async def analyze_image(self, image_path, prompt, **kwargs):  # noqa: ARG002
            self.seen_path = Path(image_path)
            self.existed_during_call = self.seen_path.exists()
            self.seen_bytes = self.seen_path.read_bytes()
            return "A small test image."

    provider = FakeProvider()

    def _provider(_cfg):
        return provider

    monkeypatch.setattr("project_remedy.pdf_vision.create_provider_from_config", _provider)

    with TestClient(app) as client:
        response = client.post(
            "/v1/pdf/vision/alt-text",
            files={"file": ("sample.png", png_bytes, "image/png")},
        )

    assert response.status_code == 200
    assert response.json() == {"alt_text": "A small test image."}
    assert provider.seen_path is not None
    assert provider.seen_path.suffix == ".png"
    assert provider.existed_during_call is True
    assert provider.seen_bytes == png_bytes
    assert not provider.seen_path.exists()


def test_pdf_contrast_audit_serializes_pydantic_issues(monkeypatch, tmp_path):
    app = _create_test_app(tmp_path, monkeypatch, api_key="")

    class FakeProvider:
        pass

    def _provider(_cfg):
        return FakeProvider()

    class FakeContrastDetector:
        def __init__(self, provider, dpi=150):  # noqa: ARG002
            pass

        async def detect_document(self, pdf_path, level="AA"):  # noqa: ARG002
            from project_remedy.contrast.models import ContrastIssue, ContrastIssueType

            return [
                ContrastIssue(
                    id="issue-1",
                    issue_type=ContrastIssueType.TEXT,
                    page_index=0,
                    bbox=[1, 2, 3, 4],
                    description="Low contrast text",
                    text_content="Hello",
                )
            ]

    monkeypatch.setattr("project_remedy.pdf_vision.create_provider_from_config", _provider)
    monkeypatch.setattr("project_remedy.contrast.detector.ContrastDetector", FakeContrastDetector)

    with TestClient(app) as client:
        response = client.post(
            "/v1/pdf/contrast/audit",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["issues"][0]["id"] == "issue-1"
    assert payload["issues"][0]["issue_type"] == "text"


async def test_contrast_detector_uses_analyze_image_provider(tmp_path):
    from project_remedy.contrast.detector import ContrastDetector

    class FakeProvider:
        seen_path: Path | None = None
        seen_response_format = None

        async def analyze_image(self, image_path, prompt, **kwargs):  # noqa: ARG002
            self.seen_path = Path(image_path)
            self.seen_response_format = kwargs.get("response_format")
            assert self.seen_path.exists()
            return '{"issues": [], "page_has_contrast_issues": false}'

    provider = FakeProvider()
    detector = ContrastDetector(provider)
    result = await detector._call_vision(b"png-bytes", "prompt", {"type": "object"})

    assert result == {"issues": [], "page_has_contrast_issues": False}
    assert provider.seen_path is not None
    assert provider.seen_response_format == {"type": "object"}
    assert not provider.seen_path.exists()


async def test_contrast_remediator_writes_output_when_no_issues(tmp_path):
    import fitz
    from project_remedy.contrast.remediator import ContrastRemediator

    src = tmp_path / "input.pdf"
    dst = tmp_path / "output.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Readable text")
    doc.save(src)
    doc.close()

    class FakeProvider:
        async def analyze_image(self, image_path, prompt, **kwargs):  # noqa: ARG002
            return '{"issues": [], "page_has_contrast_issues": false}'

    analysis = await ContrastRemediator(FakeProvider(), dpi=72).remediate_document(
        str(src),
        str(dst),
    )

    assert dst.exists()
    assert analysis.total_issues == 0
    assert dst.read_bytes().startswith(b"%PDF")


class _FakeVisionProvider:
    def __init__(self, *, response: str = "", exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls = 0
        self.model = "fake-model"
        self.base_url = "http://fake"

    async def analyze_image(self, image_path, prompt, **kwargs):  # noqa: ARG002
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.response


class _FakeHTTPResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _RecordingAsyncClient:
    calls = []
    response_data = {"message": {"content": "vision response"}}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, endpoint, json):
        self.calls.append(
            {
                "endpoint": endpoint,
                "payload": json,
                "client_kwargs": self.kwargs,
            }
        )
        return _FakeHTTPResponse(self.response_data)


async def test_fallback_vision_provider_uses_next_provider():
    primary = _FakeVisionProvider(exc=RuntimeError("primary failed"))
    fallback = _FakeVisionProvider(response="fallback response")
    provider = FallbackVisionProvider([primary, fallback])

    assert await provider.analyze_image(None, "prompt") == "fallback response"
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_fallback_vision_provider_rejects_empty_response():
    primary = _FakeVisionProvider(response="")
    fallback = _FakeVisionProvider(response="fallback response")
    provider = FallbackVisionProvider([primary, fallback])

    assert await provider.analyze_image(None, "prompt") == "fallback response"
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_ollama_provider_uses_native_api_for_local_root_url(monkeypatch):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response_data = {"message": {"content": "vision response"}}
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)
    monkeypatch.setenv("OLLAMA_LOCAL_KEEP_ALIVE", "1m")

    provider = OllamaVisionProvider(
        base_url="http://localhost:11434",
        api_key="ollama",
        model="gemma4:26b",
        timeout_seconds=30,
        max_retries=0,
    )

    assert await provider.analyze_image(None, "prompt", max_tokens=80) == "vision response"
    assert _RecordingAsyncClient.calls
    call = _RecordingAsyncClient.calls[0]
    assert call["client_kwargs"]["base_url"] == "http://localhost:11434"
    assert call["endpoint"] == "/api/chat"
    assert call["payload"]["model"] == "gemma4:26b"
    assert call["payload"]["messages"][0]["content"] == "prompt"
    assert call["payload"]["keep_alive"] == "1m"


async def test_ollama_provider_rejects_empty_response(monkeypatch):
    import httpx

    _RecordingAsyncClient.calls = []
    _RecordingAsyncClient.response_data = {"message": {"content": ""}}
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)

    provider = OllamaVisionProvider(
        base_url="http://localhost:11434",
        api_key="ollama",
        model="gemma4:26b",
        timeout_seconds=30,
        max_retries=0,
    )

    with pytest.raises(RuntimeError, match="empty vision response"):
        await provider.analyze_image(None, "prompt", max_tokens=80)


async def test_fallback_vision_provider_raises_after_all_fail():
    provider = FallbackVisionProvider(
        [
            _FakeVisionProvider(exc=RuntimeError("primary failed")),
            _FakeVisionProvider(exc=RuntimeError("fallback failed")),
        ]
    )

    try:
        await provider.analyze_image(None, "prompt")
    except RuntimeError as exc:
        assert "All configured vision providers failed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
