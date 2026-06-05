from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.quality_calibration import (
    QualityCalibrationError,
    quality_calibration_status,
)
from backend.app.config import Settings
from backend.app.quality_routes import (
    BehavioralTestResultResponse,
    CalibrationListResponse,
    CalibrationRowResponse,
    QualityDimensionsResponse,
    QualityDimensionScoreResponse,
    QualityResultResponse,
    ReviewClaimResponse,
    ReviewQueueResponse,
    ReviewSubmitResponse,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityResult,
)
from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT
from project_remedy.quality_judges.shared.registry import required_judge_calibrations
from project_remedy.vision_planner.experiment_store import ExperimentStore
from tools.annotate_corpus import build_annotation_record


def _configure_import_env(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "import-state"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("JOB_STORE_PATH", str(state_dir / "jobs.db"))
    monkeypatch.setenv("JOB_DIR", str(state_dir / "jobs"))
    monkeypatch.setenv("JOB_BACKUP_DIR", str(state_dir / "job_backups"))
    monkeypatch.setenv("QUALITY_JUDGE_MODEL", "llama3.1:8b")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="",
        ollama_api_key="test-ollama-key",
        job_store_path=tmp_path / "state" / "jobs.db",
        job_dir=tmp_path / "job_data",
        backup_dir=tmp_path / "job_backups",
        quality_experiment_store_path=tmp_path / "quality_experiments.db",
        quality_review_queue_path=tmp_path / "quality_review_queue.jsonl",
        quality_review_submission_path=tmp_path / "quality_review_submissions.jsonl",
        quality_corpus_root_path=tmp_path / "corpus" / "v1",
    )


def _create_test_app(tmp_path: Path, monkeypatch):
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    return main.create_app(_settings(tmp_path))


def _record_required_calibrations(
    store: ExperimentStore,
    fmt: str,
    *,
    cohens_kappa: float = 0.8,
    sample_size: int = 1,
    measured_at: str = "2026-05-08T00:00:00+00:00",
) -> None:
    for requirement in required_judge_calibrations(fmt):
        store.record_judge_calibration(
            judge_id=requirement.judge_id,
            judge_version=requirement.judge_version,
            format=requirement.format,
            dimension=requirement.dimension,
            cohens_kappa=cohens_kappa,
            sample_size=sample_size,
            measured_at=measured_at,
        )


def test_quality_dimensions_endpoint(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/v1/quality/dimensions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["formats"]["pdf"] == [
        "alt_text",
        "reading_order",
        "heading_semantics",
        "table_structure",
        "link_text",
        "decorative",
        "complex_content",
    ]
    assert "sheet_organization" in payload["formats"]["xlsx"]
    assert "reading_order" in payload["not_applicable"]["xlsx"]
    assert "slide_title" in payload["not_applicable"]["pdf"]
    assert payload["all_dimensions"][0] == "alt_text"


def test_quality_routes_use_existing_api_key_auth(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), api_key="quality-secret")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        missing = client.get("/v1/quality/dimensions")
        wrong = client.get(
            "/v1/quality/dimensions",
            headers={"X-API-Key": "wrong-secret"},
        )
        allowed = client.get(
            "/v1/quality/dimensions",
            headers={"X-API-Key": "quality-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200


def test_all_quality_routes_reject_missing_or_wrong_api_key(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), api_key="quality-secret")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    def pdf_upload() -> dict[str, object]:
        return {
            "files": {
                "file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
            }
        }

    def office_upload() -> dict[str, object]:
        return {
            "files": {
                "file": (
                    "sample.docx",
                    b"PK\x03\x04fake-docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            }
        }

    def claim_json() -> dict[str, object]:
        return {"json": {"doc_id": "pdf-1", "reviewer_id": "specialist-a"}}

    def submit_json() -> dict[str, object]:
        return {"json": {"doc_id": "pdf-1", "format": "pdf"}}

    cases = [
        ("GET", "/v1/quality/dimensions", dict),
        ("GET", "/v1/quality/calibration", dict),
        ("POST", "/v1/quality/audit/pdf", pdf_upload),
        ("POST", "/v1/quality/audit/office", office_upload),
        ("GET", "/v1/quality/review/queue", dict),
        ("POST", "/v1/quality/review/claim", claim_json),
        ("POST", "/v1/quality/review/submit", submit_json),
    ]

    with TestClient(app) as client:
        for method, path, kwargs_factory in cases:
            missing = client.request(method, path, **kwargs_factory())
            wrong = client.request(
                method,
                path,
                headers={"X-API-Key": "wrong-secret"},
                **kwargs_factory(),
            )

            assert missing.status_code == 401, path
            assert wrong.status_code == 401, path


def test_quality_endpoints_are_documented_in_openapi(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/quality/audit/pdf" in paths
    assert "/v1/quality/audit/office" in paths
    assert "/v1/quality/calibration" in paths
    assert "/v1/quality/review/queue" in paths
    assert "/v1/quality/review/claim" in paths
    assert "/v1/quality/review/submit" in paths
    assert "/v1/quality/dimensions" in paths

    schemas = response.json()["components"]["schemas"]
    expected_response_schemas = {
        "/v1/quality/audit/pdf": ("post", "200", "QualityResultResponse"),
        "/v1/quality/audit/office": ("post", "200", "QualityResultResponse"),
        "/v1/quality/calibration": ("get", "200", "CalibrationListResponse"),
        "/v1/quality/review/queue": ("get", "200", "ReviewQueueResponse"),
        "/v1/quality/review/claim": ("post", "200", "ReviewClaimResponse"),
        "/v1/quality/review/submit": ("post", "202", "ReviewSubmitResponse"),
        "/v1/quality/dimensions": ("get", "200", "QualityDimensionsResponse"),
    }
    for path, (_, _, schema_name) in expected_response_schemas.items():
        assert schema_name in schemas, path
    for path, (method, status_code, schema_name) in expected_response_schemas.items():
        response_schema = paths[path][method]["responses"][status_code]["content"][
            "application/json"
        ]["schema"]
        assert response_schema["$ref"].endswith(f"/{schema_name}"), path

    remediate_params = paths["/v1/remediate"]["post"]["parameters"]
    office_params = paths["/v1/office/remediate"]["post"]["parameters"]
    assert any(param["name"] == "quality" and param["in"] == "query" for param in remediate_params)
    assert any(param["name"] == "quality" and param["in"] == "query" for param in office_params)


def test_quality_response_models_reject_malformed_numeric_evidence() -> None:
    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=float("inf"),
            per_criterion={},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=0.0,
            per_criterion={"informativeness": float("nan")},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=True,
            variance=0.0,
            per_criterion={},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score="0.9",
            variance=0.0,
            per_criterion={},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=0.0,
            per_criterion={"informativeness": "0.9"},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        BehavioralTestResultResponse(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="pdf",
            passed=True,
            score=True,
            threshold=0.8,
            confidence=0.9,
            findings=[],
        )

    with pytest.raises(ValidationError):
        BehavioralTestResultResponse(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="pdf",
            passed="true",
            score=0.9,
            threshold=0.8,
            confidence=0.9,
            findings=[],
        )

    with pytest.raises(ValidationError):
        BehavioralTestResultResponse(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="pdf",
            passed=True,
            score=0.9,
            threshold="0.8",
            confidence=0.9,
            findings=[],
        )

    with pytest.raises(ValidationError):
        QualityResultResponse(
            format="pdf",
            dimensions={},
            behavioral={},
            overall_pass="true",
            failing_dimensions=[],
            not_applicable_dimensions=[],
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=float("nan"),
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa="0.8",
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=1.5,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=True,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=True,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=0,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=1,
            measured_at="2026-05-08T00:00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=1,
            measured_at=["2026-05-08T00:00:00+00:00"],
        )


def test_quality_response_models_reject_malformed_identity_and_nested_shape() -> None:
    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="reading_order",
            format="xlsx",
            score=0.9,
            variance=0.0,
            per_criterion={},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=0.0,
            per_criterion={"": 0.9},
            judge_versions=[],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        QualityDimensionScoreResponse(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=0.0,
            per_criterion={},
            judge_versions=["alt_text_judge_v1", ""],
            sample_findings=[],
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        BehavioralTestResultResponse(
            test_name="alt_text_substitution",
            dimension="reading_order",
            format="xlsx",
            passed=True,
            score=0.9,
            threshold=0.8,
            confidence=0.9,
            findings=[],
        )

    with pytest.raises(ValidationError):
        BehavioralTestResultResponse(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="pdf",
            passed=True,
            score=0.9,
            threshold=0.8,
            confidence=0.9,
            findings=["not-an-object"],
        )

    with pytest.raises(ValidationError):
        QualityResultResponse(
            format="pdf",
            dimensions={
                "reading_order": QualityDimensionScoreResponse(
                    dimension="alt_text",
                    format="pdf",
                    score=0.9,
                    variance=0.0,
                    per_criterion={},
                    judge_versions=[],
                    sample_findings=[],
                    confidence=0.9,
                )
            },
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
            not_applicable_dimensions=[],
        )

    with pytest.raises(ValidationError):
        QualityResultResponse(
            format="pdf",
            dimensions={},
            behavioral={},
            overall_pass=True,
            failing_dimensions=["sheet_organization"],
            not_applicable_dimensions=[],
        )

    with pytest.raises(ValidationError):
        QualityResultResponse(
            format="pdf",
            dimensions={},
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
            not_applicable_dimensions=["alt_text"],
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="",
            judge_version="v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.8,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )

    with pytest.raises(ValidationError):
        CalibrationRowResponse(
            judge_id="judge",
            judge_version="v1",
            format="xlsx",
            dimension="reading_order",
            cohens_kappa=0.8,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )


def test_quality_envelope_response_models_reject_malformed_shape() -> None:
    with pytest.raises(ValidationError):
        QualityDimensionsResponse(
            all_dimensions=["alt_text", ""],
            formats={"pdf": ["alt_text"]},
            not_applicable={"pdf": ["slide_title"]},
        )

    with pytest.raises(ValidationError):
        QualityDimensionsResponse(
            all_dimensions=["alt_text"],
            formats={"pdf": "alt_text"},
            not_applicable={"pdf": ["slide_title"]},
        )

    with pytest.raises(ValidationError):
        CalibrationListResponse(
            items=[],
            total="0",
            readiness={},
        )

    with pytest.raises(ValidationError):
        CalibrationListResponse(
            items=[],
            total=0,
            readiness=[],
        )

    with pytest.raises(ValidationError):
        ReviewQueueResponse(
            items=[["not-an-object"]],
            total=1,
            limit=50,
            offset=0,
        )

    with pytest.raises(ValidationError):
        ReviewQueueResponse(
            items=[],
            total=True,
            limit=50,
            offset=0,
        )

    with pytest.raises(ValidationError):
        ReviewQueueResponse(
            items=[],
            total=0,
            limit=0,
            offset=0,
        )

    with pytest.raises(ValidationError):
        ReviewClaimResponse(claimed="true", item={})

    with pytest.raises(ValidationError):
        ReviewClaimResponse(claimed=True, item=[])

    with pytest.raises(ValidationError):
        ReviewSubmitResponse(
            accepted=True,
            annotation_path=123,
            calibration_rows_recorded=0,
            queue_item_completed=False,
        )

    with pytest.raises(ValidationError):
        ReviewSubmitResponse(
            accepted=True,
            annotation_path="",
            calibration_rows_recorded=-1,
            queue_item_completed=False,
        )

    with pytest.raises(ValidationError):
        ReviewSubmitResponse(
            accepted=True,
            annotation_path="",
            calibration_rows_recorded=0,
            queue_item_completed="false",
        )


def test_quality_pdf_audit_endpoint_serializes_result(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)
    staged_paths: list[Path] = []

    def fake_audit_pdf_quality(pdf_path, *, config=None):  # noqa: ARG001
        staged_paths.append(Path(pdf_path))
        return QualityResult(
            format="pdf",
            dimensions={
                "alt_text": QualityDimensionScore(
                    dimension="alt_text",
                    format="pdf",
                    score=0.9,
                    confidence=0.8,
                )
            },
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
        )

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_pdf_quality", fake_audit_pdf_quality)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/pdf",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "pdf"
    assert payload["dimensions"]["alt_text"]["score"] == 0.9
    assert payload["overall_pass"] is True
    assert staged_paths
    assert not staged_paths[0].exists()


def test_quality_pdf_audit_requires_calibration_when_gate_enabled(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("quality audit must not run before calibration")

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_pdf_quality", fail_audit)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/pdf",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 409
    assert "not calibrated for pdf" in response.json()["detail"]


def test_quality_calibration_status_rejects_unsupported_format(tmp_path) -> None:
    with pytest.raises(QualityCalibrationError, match="unsupported"):
        quality_calibration_status(_settings(tmp_path), "txt")


def test_quality_pdf_audit_runs_when_required_calibration_is_present(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    store = ExperimentStore(settings.quality_experiment_store_path)
    _record_required_calibrations(store, "pdf")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    def fake_audit_pdf_quality(pdf_path, *, config=None):  # noqa: ARG001
        return QualityResult(
            format="pdf",
            dimensions={
                "alt_text": QualityDimensionScore(
                    dimension="alt_text",
                    format="pdf",
                    score=0.9,
                    confidence=0.8,
                )
            },
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
        )

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_pdf_quality", fake_audit_pdf_quality)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/pdf",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json()["format"] == "pdf"


def test_quality_pdf_audit_requires_current_judge_version(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    store = ExperimentStore(settings.quality_experiment_store_path)
    requirements = list(required_judge_calibrations("pdf"))
    stale = requirements[0]
    for requirement in requirements[1:]:
        store.record_judge_calibration(
            judge_id=requirement.judge_id,
            judge_version=requirement.judge_version,
            format=requirement.format,
            dimension=requirement.dimension,
            cohens_kappa=0.8,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )
    store.record_judge_calibration(
        judge_id=stale.judge_id,
        judge_version="stale_prompt_version",
        format=stale.format,
        dimension=stale.dimension,
        cohens_kappa=1.0,
        sample_size=99,
        measured_at="2026-05-08T00:00:00+00:00",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/pdf",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 409
    assert stale.judge_id in response.json()["detail"]
    assert stale.judge_version in response.json()["detail"]


def test_quality_pdf_audit_rejects_stale_calibration_when_age_limit_configured(monkeypatch, tmp_path) -> None:
    settings = replace(
        _settings(tmp_path),
        quality_require_calibration=True,
        quality_max_calibration_age_days=30,
    )
    store = ExperimentStore(settings.quality_experiment_store_path)
    _record_required_calibrations(
        store,
        "pdf",
        measured_at="1970-01-01T00:00:00+00:00",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/pdf",
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "stale calibration" in detail
    assert "1970-01-01T00:00:00+00:00" in detail


def test_quality_calibration_status_uses_latest_timezone_instant(tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    store = ExperimentStore(settings.quality_experiment_store_path)
    requirements = list(required_judge_calibrations("pdf"))
    stale_text_latest = requirements[0]
    for requirement in requirements[1:]:
        store.record_judge_calibration(
            judge_id=requirement.judge_id,
            judge_version=requirement.judge_version,
            format=requirement.format,
            dimension=requirement.dimension,
            cohens_kappa=0.8,
            sample_size=1,
            measured_at="2026-05-09T00:30:00+00:00",
        )
    store.record_judge_calibration(
        judge_id=stale_text_latest.judge_id,
        judge_version=stale_text_latest.judge_version,
        format=stale_text_latest.format,
        dimension=stale_text_latest.dimension,
        cohens_kappa=0.9,
        sample_size=1,
        measured_at="2026-05-09T01:00:00+02:00",
    )
    store.record_judge_calibration(
        judge_id=stale_text_latest.judge_id,
        judge_version=stale_text_latest.judge_version,
        format=stale_text_latest.format,
        dimension=stale_text_latest.dimension,
        cohens_kappa=0.7,
        sample_size=1,
        measured_at="2026-05-09T00:30:00+00:00",
    )

    status = quality_calibration_status(settings, "pdf")

    assert status.ready is False
    assert status.below_threshold == [
        {
            "dimension": stale_text_latest.dimension,
            "judge_id": stale_text_latest.judge_id,
            "judge_version": stale_text_latest.judge_version,
            "format": stale_text_latest.format,
            "cohens_kappa": 0.7,
            "sample_size": 1,
            "measured_at": "2026-05-09T00:30:00+00:00",
        }
    ]


def test_quality_office_audit_endpoint_serializes_result(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)
    staged_paths: list[Path] = []

    def fake_audit_office_quality(file_path, *, file_type, config=None):  # noqa: ARG001
        staged_paths.append(Path(file_path))
        return QualityResult(
            format="docx",
            dimensions={
                "heading_semantics": QualityDimensionScore(
                    dimension="heading_semantics",
                    format="docx",
                    score=1.0,
                    confidence=0.7,
                )
            },
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
        )

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_office_quality", fake_audit_office_quality)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/office",
            files={"file": ("sample.docx", b"PK\x03\x04fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "docx"
    assert payload["dimensions"]["heading_semantics"]["score"] == 1.0
    assert staged_paths
    assert staged_paths[0].suffix == ".docx"
    assert not staged_paths[0].exists()


def test_quality_office_audit_requires_calibration_when_gate_enabled(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("office quality audit must not run before calibration")

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_office_quality", fail_audit)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/office",
            files={
                "file": (
                    "sample.docx",
                    b"PK\x03\x04fake-docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 409
    assert "not calibrated for docx" in response.json()["detail"]


def test_quality_office_audit_runs_when_required_calibration_is_present(monkeypatch, tmp_path) -> None:
    settings = replace(_settings(tmp_path), quality_require_calibration=True)
    store = ExperimentStore(settings.quality_experiment_store_path)
    _record_required_calibrations(store, "docx")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    def fake_audit_office_quality(file_path, *, file_type, config=None):  # noqa: ARG001
        assert file_type == FileType.DOCX
        return QualityResult(
            format="docx",
            dimensions={
                "heading_semantics": QualityDimensionScore(
                    dimension="heading_semantics",
                    format="docx",
                    score=1.0,
                    confidence=0.7,
                )
            },
            behavioral={},
            overall_pass=True,
            failing_dimensions=[],
        )

    quality_routes = importlib.import_module("backend.app.quality_routes")
    monkeypatch.setattr(quality_routes, "audit_office_quality", fake_audit_office_quality)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/audit/office",
            files={
                "file": (
                    "sample.docx",
                    b"PK\x03\x04fake-docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200
    assert response.json()["format"] == "docx"


def test_quality_calibration_endpoint_reads_experiment_store(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    store = ExperimentStore(settings.quality_experiment_store_path)
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.81,
        sample_size=12,
        measured_at="2026-05-08T00:00:00+00:00",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.get("/v1/quality/calibration?format=pdf&dimension=alt_text")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["cohens_kappa"] == 0.81
    assert payload["readiness"]["format"] == "pdf"
    assert payload["readiness"]["ready"] is False
    assert "reading_order" in payload["readiness"]["missing_dimensions"]


def test_quality_calibration_status_reports_malformed_persisted_rows(tmp_path) -> None:
    settings = _settings(tmp_path)
    ExperimentStore(settings.quality_experiment_store_path)
    requirement = required_judge_calibrations("pdf")[0]
    with sqlite3.connect(settings.quality_experiment_store_path) as connection:
        connection.execute(
            """
            INSERT INTO judge_calibration (
                judge_id, judge_version, format, dimension,
                cohens_kappa, sample_size, measured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement.judge_id,
                requirement.judge_version,
                requirement.format,
                requirement.dimension,
                "not-a-number",
                12,
                "2026-05-08T00:00:00+00:00",
            ),
        )

    status = quality_calibration_status(settings, "pdf")

    assert status.ready is False
    assert status.malformed_calibrations == [
        {
            "dimension": requirement.dimension,
            "judge_id": requirement.judge_id,
            "judge_version": requirement.judge_version,
            "format": requirement.format,
            "measured_at": "2026-05-08T00:00:00+00:00",
            "reason": "cohens_kappa must be numeric",
        }
    ]
    assert status.to_dict()["malformed_calibrations"] == status.malformed_calibrations


def test_quality_calibration_rejects_invalid_filters(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        invalid_format = client.get("/v1/quality/calibration?format=txt")
        invalid_dimension = client.get("/v1/quality/calibration?dimension=bogus")
        inapplicable_dimension = client.get(
            "/v1/quality/calibration?format=xlsx&dimension=reading_order"
        )

    assert invalid_format.status_code == 422
    assert invalid_format.json()["detail"] == "format unsupported format: txt"
    assert invalid_dimension.status_code == 422
    assert invalid_dimension.json()["detail"] == "dimension unsupported: bogus"
    assert inapplicable_dimension.status_code == 422
    assert inapplicable_dimension.json()["detail"] == (
        "dimension 'reading_order' is not applicable to xlsx"
    )


def test_quality_review_queue_and_submit_endpoints(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        "\n".join(
            [
                json.dumps({"doc_id": "pdf-1", "format": "pdf"}),
                json.dumps({"doc_id": "docx-1", "format": "docx"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        queue = client.get("/v1/quality/review/queue?format=pdf")
        submit = client.post(
            "/v1/quality/review/submit",
            json={"annotation": annotation},
        )

    assert queue.status_code == 200
    assert queue.json()["items"] == [{"doc_id": "pdf-1", "format": "pdf"}]
    assert submit.status_code == 202
    assert submit.json()["queue_item_completed"] is True

    submissions = [
        json.loads(line)
        for line in settings.quality_review_submission_path.read_text(encoding="utf-8").splitlines()
    ]
    assert submissions[0]["verdict"]["annotation"]["doc_id"] == "pdf-1"
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "completed"


def test_quality_review_queue_rejects_unsupported_format_filter(monkeypatch, tmp_path) -> None:
    app = _create_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/v1/quality/review/queue?format=txt")

    assert response.status_code == 422
    assert response.json()["detail"] == "format unsupported format: txt"


def test_quality_review_queue_paginates_after_format_filter(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"doc_id": "pdf-1", "format": "pdf"},
                {"doc_id": "docx-1", "format": "docx"},
                {"doc_id": "pdf-2", "format": "pdf"},
                {"doc_id": "pdf-3", "format": "pdf"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.get(
            "/v1/quality/review/queue?format=pdf&limit=1&offset=1"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [{"doc_id": "pdf-2", "format": "pdf"}]
    assert payload["total"] == 3
    assert payload["limit"] == 1
    assert payload["offset"] == 1


def test_quality_review_queue_rejects_malformed_jsonl(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text("{not-json\n", encoding="utf-8")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.get("/v1/quality/review/queue")

    assert response.status_code == 500
    assert response.json()["detail"] == "quality review JSONL is invalid at line 1"


def test_quality_review_queue_rejects_non_object_jsonl_rows(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text('["pdf-1"]\n', encoding="utf-8")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.get("/v1/quality/review/queue")

    assert response.status_code == 500
    assert response.json()["detail"] == "quality review JSONL row 1 must be an object"


@pytest.mark.parametrize(
    ("row", "expected_detail"),
    [
        (
            {"doc_id": "pdf-1", "format": "txt"},
            "quality review JSONL row 1 invalid: unsupported format: txt",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "priority_score": True},
            "quality review JSONL row 1 invalid: priority_score must be numeric",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "source_sha256": False},
            (
                "quality review JSONL row 1 invalid: source_sha256 must be "
                "a sha256 hex digest"
            ),
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "weak_dimensions": False},
            "quality review JSONL row 1 invalid: weak_dimensions must be a list",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "status": "in_review"},
            (
                "quality review JSONL row 1 invalid: status must be queued, "
                "claimed, or completed"
            ),
        ),
        (
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "weak_dimensions": ["reading_order"],
            },
            (
                "quality review JSONL row 1 invalid: weak_dimensions contains "
                "dimension(s) not applicable to xlsx: reading_order"
            ),
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "sampled_at": "2026-05-08T00:00:00",
            },
            "quality review JSONL row 1 invalid: sampled_at must include a timezone",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": " ",
                "claimed_at": "2026-05-08T00:00:00+00:00",
            },
            "quality review JSONL row 1 invalid: claimed_by must be a non-empty string",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": "specialist-a",
            },
            "quality review JSONL row 1 invalid: claimed_at is required for claimed status",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "completed",
                "completed_by": "",
                "completed_at": "2026-05-08T00:00:00+00:00",
            },
            "quality review JSONL row 1 invalid: completed_by must be a non-empty string",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "completed",
            },
            "quality review JSONL row 1 invalid: completed_at is required for completed status",
        ),
    ],
)
def test_quality_review_queue_rejects_invalid_persisted_rows(
    monkeypatch,
    tmp_path,
    row,
    expected_detail,
) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.get("/v1/quality/review/queue")

    assert response.status_code == 500
    assert response.json()["detail"] == expected_detail


def test_quality_review_claim_updates_queue_item(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        claim = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "format": "pdf", "reviewer_id": "specialist-a"},
        )

    assert claim.status_code == 200
    payload = claim.json()
    assert payload["claimed"] is True
    assert payload["item"]["status"] == "claimed"
    assert payload["item"]["claimed_by"] == "specialist-a"

    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "claimed"
    assert row["claimed_by"] == "specialist-a"
    assert row["claimed_at"]


def test_quality_review_claim_rejects_unsupported_format(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "format": "txt", "reviewer_id": "specialist-a"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "format unsupported format: txt"
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"


def test_quality_review_claim_rejects_conflicting_claim(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": "specialist-a",
                "claimed_at": "2026-05-08T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "reviewer_id": "specialist-b"},
        )

    assert response.status_code == 409


def test_quality_review_claim_rejects_completed_item(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "completed",
                "claimed_by": "specialist-a",
                "completed_by": "specialist-a",
                "completed_at": "2026-05-08T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "reviewer_id": "specialist-a"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Review item is already completed."
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "completed"
    assert row["completed_by"] == "specialist-a"


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        (
            {"doc_id": " ", "reviewer_id": "specialist-a"},
            "doc_id is required",
        ),
        (
            {"doc_id": "pdf-1", "reviewer_id": " "},
            "reviewer_id is required",
        ),
    ],
)
def test_quality_review_claim_rejects_blank_identity_without_mutation(
    monkeypatch,
    tmp_path,
    payload,
    expected_detail,
) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    original_queue = settings.quality_review_queue_path.read_text(encoding="utf-8")
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post("/v1/quality/review/claim", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    assert settings.quality_review_queue_path.read_text(encoding="utf-8") == original_queue


def test_quality_review_submit_marks_claimed_queue_item_complete(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": "specialist-a",
                "claimed_at": "2026-05-08T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "doc_id": "pdf-1",
                "format": "pdf",
                "reviewer_id": "specialist-a",
                "annotation": annotation,
            },
        )

    assert response.status_code == 202
    assert response.json()["queue_item_completed"] is True
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "completed"
    assert row["completed_at"]
    assert row["completed_by"] == "specialist-a"


def test_quality_review_submit_rejects_bare_verdict_without_evidence(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"doc_id": "pdf-1", "format": "pdf", "score": 0.9},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "review submission requires annotation or calibration evidence"
    )
    assert not settings.quality_review_submission_path.exists()


@pytest.mark.parametrize(
    ("field_name", "value", "expected_detail"),
    [
        (
            "doc_id",
            123,
            "review submission doc_id must be a non-empty string",
        ),
        (
            "format",
            " ",
            "review submission format must be a non-empty string",
        ),
        (
            "reviewer_id",
            123,
            "review submission reviewer_id must be a non-empty string",
        ),
    ],
)
def test_quality_review_submit_rejects_malformed_submission_identity_without_side_effects(
    monkeypatch,
    tmp_path,
    field_name,
    value,
    expected_detail,
) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-identity",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    payload = {"annotation": annotation, field_name: value}

    with TestClient(app) as client:
        response = client.post("/v1/quality/review/submit", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    annotation_path = (
        settings.quality_corpus_root_path / "annotations" / "pdf" / "pdf-identity.json"
    )
    assert not annotation_path.exists()
    assert not settings.quality_review_submission_path.exists()


def test_quality_review_submit_rejects_unsupported_submission_format(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "doc_id": "pdf-1",
                "format": "txt",
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "review submission format unsupported format: txt"
    assert not settings.quality_review_submission_path.exists()
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_queued_verdict_without_annotation(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"doc_id": "pdf-1", "format": "pdf", "score": 0.9},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "queued review completion requires annotation evidence"
    )
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"
    assert not settings.quality_review_submission_path.exists()


def test_quality_review_submit_rejects_annotation_for_different_queue_item(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-2",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"doc_id": "pdf-1", "format": "pdf", "annotation": annotation},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "annotation doc_id must match review submission doc_id"
    )
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"
    annotation_path = settings.quality_corpus_root_path / "annotations" / "pdf" / "pdf-2.json"
    assert not annotation_path.exists()
    assert not settings.quality_review_submission_path.exists()


def test_quality_review_submit_rejects_annotation_for_same_doc_different_queue_format(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "shared-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.docx",
        fmt="docx",
        doc_id="shared-1",
        document_class="report",
        annotator="specialist_a",
        applicable_dimensions=list(DIMENSIONS_BY_FORMAT["docx"]),
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["docx"]},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"annotation": annotation},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "annotation format must match queued review format"
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"
    annotation_path = settings.quality_corpus_root_path / "annotations" / "docx" / "shared-1.json"
    assert not annotation_path.exists()
    assert not settings.quality_review_submission_path.exists()


def test_quality_review_submit_rejects_calibration_for_different_format(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    requirement = next(iter(required_judge_calibrations("docx")))
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "doc_id": "pdf-1",
                "format": "pdf",
                "calibration": [
                    {
                        "judge_id": requirement.judge_id,
                        "judge_version": requirement.judge_version,
                        "format": requirement.format,
                        "dimension": requirement.dimension,
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "calibration row format must match review submission format"
    )
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"
    assert not settings.quality_review_submission_path.exists()
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_calibration_only_queue_completion_when_submission_format_omitted(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}) + "\n",
        encoding="utf-8",
    )
    requirement = next(iter(required_judge_calibrations("docx")))
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "doc_id": "pdf-1",
                "calibration": [
                    {
                        "judge_id": requirement.judge_id,
                        "judge_version": requirement.judge_version,
                        "format": requirement.format,
                        "dimension": requirement.dimension,
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "queued review completion requires annotation evidence"
    )
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "queued"
    assert not settings.quality_review_submission_path.exists()
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_conflicting_claim_without_side_effects(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.quality_review_queue_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-claimed-source",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": "specialist-a",
                "claimed_at": "2026-05-08T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-claimed-source",
        document_class="paper",
        annotator="specialist_b",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "reviewer_id": "specialist-b",
                "annotation": annotation,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Review item is claimed by a different reviewer."
    row = json.loads(settings.quality_review_queue_path.read_text(encoding="utf-8"))
    assert row["status"] == "claimed"
    assert row["claimed_by"] == "specialist-a"
    annotation_path = (
        settings.quality_corpus_root_path
        / "annotations"
        / "pdf"
        / "pdf-claimed-source.json"
    )
    assert not annotation_path.exists()
    assert not settings.quality_review_submission_path.exists()


def test_quality_review_endpoints_require_reviewer_key_when_configured(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.reviewer_keys.append("reviewer-secret")
    settings.quality_review_queue_path.write_text(
        json.dumps({"doc_id": "pdf-1", "format": "pdf"}) + "\n",
        encoding="utf-8",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        queue_forbidden = client.get("/v1/quality/review/queue")
        queue_wrong_key = client.get(
            "/v1/quality/review/queue",
            headers={"X-Reviewer-Key": "wrong-secret"},
        )
        submit_forbidden = client.post(
            "/v1/quality/review/submit",
            json={"doc_id": "pdf-1"},
        )
        submit_wrong_key = client.post(
            "/v1/quality/review/submit",
            json={"doc_id": "pdf-1"},
            headers={"X-Reviewer-Key": "wrong-secret"},
        )
        claim_forbidden = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "reviewer_id": "specialist-a"},
        )
        claim_wrong_key = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "reviewer_id": "specialist-a"},
            headers={"X-Reviewer-Key": "wrong-secret"},
        )
        queue_allowed = client.get(
            "/v1/quality/review/queue",
            headers={"X-Reviewer-Key": "reviewer-secret"},
        )
        claim_allowed = client.post(
            "/v1/quality/review/claim",
            json={"doc_id": "pdf-1", "reviewer_id": "specialist-a"},
            headers={"X-Reviewer-Key": "reviewer-secret"},
        )
        submit_allowed = client.post(
            "/v1/quality/review/submit",
            json={
                "doc_id": "pdf-1",
                "reviewer_id": "specialist-a",
                "annotation": annotation,
            },
            headers={"X-Reviewer-Key": "reviewer-secret"},
        )

    assert queue_forbidden.status_code == 403
    assert queue_wrong_key.status_code == 403
    assert submit_forbidden.status_code == 403
    assert submit_wrong_key.status_code == 403
    assert claim_forbidden.status_code == 403
    assert claim_wrong_key.status_code == 403
    assert queue_allowed.status_code == 200
    assert claim_allowed.status_code == 200
    assert submit_allowed.status_code == 202


def test_quality_review_submit_persists_annotation_and_calibration(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-specialist-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "annotation": annotation,
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                        "measured_at": "2026-05-08T00:00:00+00:00",
                    }
                ],
            },
        )

    assert response.status_code == 202
    payload = response.json()
    annotation_path = settings.quality_corpus_root_path / "annotations" / "pdf" / "pdf-specialist-1.json"
    assert payload["annotation_path"] == str(annotation_path)
    assert payload["calibration_rows_recorded"] == 1
    assert annotation_path.exists()
    persisted = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert persisted["doc_id"] == "pdf-specialist-1"
    assert persisted["provenance"]["gold_standard_source"] == "human_specialist"
    assert persisted["provenance"]["human_verified"] is True

    rows = ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration(
        format="pdf",
        dimension="alt_text",
    )
    assert rows[0]["judge_id"] == "pdf_alt_text_quality"
    assert rows[0]["cohens_kappa"] == 1.0


def test_quality_review_submit_rejects_unregistered_calibration_row(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "calibration": [
                    {
                        "judge_id": "experimental_alt_text",
                        "judge_version": "alt_text_judge_v99",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert "does not match a required judge calibration" in response.json()["detail"]


def test_quality_review_submit_rejects_invalid_calibration_without_writing_annotation(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-invalid-calibration",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "annotation": annotation,
                "calibration": [
                    {
                        "judge_id": "experimental_alt_text",
                        "judge_version": "alt_text_judge_v99",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    annotation_path = (
        settings.quality_corpus_root_path
        / "annotations"
        / "pdf"
        / "pdf-invalid-calibration.json"
    )
    assert not annotation_path.exists()
    assert not settings.quality_review_submission_path.exists()
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_existing_calibration_without_writing_annotation(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    store = ExperimentStore(settings.quality_experiment_store_path)
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="alt_text_judge_v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.9,
        sample_size=2,
        measured_at="2026-05-08T00:00:00+00:00",
    )
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-duplicate-calibration",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "annotation": annotation,
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.0,
                        "sample_size": 2,
                        "measured_at": "2026-05-08T00:00:00+00:00",
                    }
                ],
            },
        )

    assert response.status_code == 409
    assert "calibration row already exists" in response.json()["detail"]
    annotation_path = (
        settings.quality_corpus_root_path
        / "annotations"
        / "pdf"
        / "pdf-duplicate-calibration.json"
    )
    assert not annotation_path.exists()
    rows = ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration()
    assert len(rows) == 1


def test_quality_review_submit_rejects_invalid_calibration_values(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 1.2,
                        "sample_size": 0,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "calibration row cohens_kappa must be between 0 and 1"


def test_quality_review_submit_rejects_boolean_calibration_kappa(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": True,
                        "sample_size": 2,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "calibration row cohens_kappa must be numeric"
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_fractional_calibration_sample_size(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 0.8,
                        "sample_size": 1.5,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "calibration row sample_size must be a positive integer"
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_non_finite_calibration_kappa(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            content=(
                '{"calibration":[{"judge_id":"pdf_alt_text_quality",'
                '"judge_version":"alt_text_judge_v1","format":"pdf",'
                '"dimension":"alt_text","cohens_kappa":NaN,"sample_size":2}]}'
            ),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "calibration row cohens_kappa must be finite"
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_invalid_calibration_measured_at(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={
                "calibration": [
                    {
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "cohens_kappa": 0.9,
                        "sample_size": 2,
                        "measured_at": "2026-05-08T00:00:00",
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "calibration row measured_at must include a timezone"


def test_quality_review_submit_rejects_duplicate_calibration_rows(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    row = {
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "format": "pdf",
        "dimension": "alt_text",
        "cohens_kappa": 0.9,
        "sample_size": 2,
        "measured_at": "2026-05-08T00:00:00+00:00",
    }

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"calibration": [row, row]},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "duplicate calibration row: pdf_alt_text_quality:alt_text_judge_v1(pdf/alt_text)"
    )
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


@pytest.mark.parametrize(
    ("field_name", "value", "expected_detail"),
    [
        (
            "judge_id",
            "",
            "calibration row judge_id must be a non-empty string",
        ),
        (
            "judge_version",
            123,
            "calibration row judge_version must be a non-empty string",
        ),
        (
            "format",
            123,
            "calibration row format must be a non-empty string",
        ),
        (
            "dimension",
            " ",
            "calibration row dimension must be a non-empty string",
        ),
    ],
)
def test_quality_review_submit_rejects_malformed_calibration_identity_without_side_effects(
    monkeypatch,
    tmp_path,
    field_name,
    value,
    expected_detail,
) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    row = {
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "format": "pdf",
        "dimension": "alt_text",
        "cohens_kappa": 0.9,
        "sample_size": 2,
    }
    row[field_name] = value

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"calibration": [row]},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    assert not settings.quality_review_submission_path.exists()
    assert ExperimentStore(settings.quality_experiment_store_path).list_judge_calibration() == []


def test_quality_review_submit_rejects_invalid_annotation(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"annotation": {"doc_id": "missing-required-fields"}},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "annotation failed validation"


def test_quality_review_submit_rejects_annotation_mismatched_to_queue_source(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    annotation = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-queued-source",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    settings.quality_review_queue_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-queued-source",
                "format": "pdf",
                "source_path": str(source),
                "source_sha256": hashlib.sha256(b"different").hexdigest(),
                "status": "queued",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"annotation": annotation},
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "annotation does not match queued review item"
    assert "annotation source_sha256 must match queued review source_sha256" in detail["errors"]
    annotation_path = settings.quality_corpus_root_path / "annotations" / "pdf" / "pdf-queued-source.json"
    assert not annotation_path.exists()


def test_quality_review_submit_rejects_non_human_annotation_provenance(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    _configure_import_env(monkeypatch, tmp_path)
    main = importlib.import_module("backend.app.main")
    app = main.create_app(settings)
    annotation = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-model-gold",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    annotation["provenance"] = {
        "gold_standard_source": "model_output",
        "human_verified": False,
        "candidate_seed_model": "prod-model",
    }

    with TestClient(app) as client:
        response = client.post(
            "/v1/quality/review/submit",
            json={"annotation": annotation},
        )

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert "provenance.gold_standard_source: must be human_specialist" in errors
    assert "provenance.human_verified: must be true" in errors
