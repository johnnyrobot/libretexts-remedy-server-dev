from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings


def _configure_import_env(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "import-state"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("JOB_STORE_PATH", str(state_dir / "jobs.db"))
    monkeypatch.setenv("JOB_DIR", str(state_dir / "jobs"))
    monkeypatch.setenv("JOB_BACKUP_DIR", str(state_dir / "job_backups"))


def _create_test_app(tmp_path: Path, monkeypatch):
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    settings = Settings(
        api_key="",
        ollama_api_key="test-ollama-key",
        job_store_path=tmp_path / "state" / "jobs.db",
        job_dir=tmp_path / "job_data",
        backup_dir=tmp_path / "job_backups",
    )
    return main.create_app(settings)


def test_remediate_default_metadata_is_unchanged_without_quality(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/remediate",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 202
    metadata = json.loads(response.json()["metadata_json"])
    assert metadata == {"allow_semantic_rebuild": False}


def test_remediate_quality_query_sets_opt_in_metadata(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/remediate?quality=true",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 202
    metadata = json.loads(response.json()["metadata_json"])
    assert metadata == {"allow_semantic_rebuild": False, "quality": True}


def test_remediate_quality_false_metadata_matches_default(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/remediate?quality=false",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 202
    metadata = json.loads(response.json()["metadata_json"])
    assert metadata == {"allow_semantic_rebuild": False}


def test_office_remediate_quality_query_sets_opt_in_metadata(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/office/remediate?quality=true",
            files={"file": ("sample.docx", b"PK\x03\x04fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    assert response.status_code == 202
    assert json.loads(response.json()["metadata_json"]) == {"quality": True}


def test_office_remediate_quality_false_metadata_matches_default(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/office/remediate?quality=false",
            files={"file": ("sample.docx", b"PK\x03\x04fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    assert response.status_code == 202
    assert json.loads(response.json()["metadata_json"]) == {}
