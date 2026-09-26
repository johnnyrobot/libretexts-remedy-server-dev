"""Quality-layer endpoints.

These routes are additive and opt-in. They do not change the default
remediation job flow.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings
from backend.app.engine_service import filetype_for_suffix
from backend.app.quality_calibration import (
    QualityCalibrationError,
    assert_quality_calibrated,
    quality_calibration_status,
)
from project_remedy.behavioral_proxies.shared.base import BehavioralModelSeparationError
from project_remedy.config import load_config
from project_remedy.models import FileType
from project_remedy.quality_judges.office.audit import audit_office_quality
from project_remedy.quality_judges.pdf.audit import audit_pdf_quality
from project_remedy.quality_judges.shared.base import ModelSeparationError
from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
    not_applicable_dimensions,
)
from project_remedy.quality_judges.shared.registry import required_judge_calibrations
from project_remedy.vision_planner.experiment_store import ExperimentStore
from tools.annotate_corpus import (
    validate_annotation_record,
    write_annotation_record,
)


_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_REVIEW_QUEUE_STATUSES = {"queued", "claimed", "completed"}

# Errors that should surface as 409 from the audit endpoints. Grouped at module
# scope so both audit handlers share a single source of truth.
_AUDIT_CONFLICT_ERRORS = (
    QualityCalibrationError,
    BehavioralModelSeparationError,
    ModelSeparationError,
)


def _reject_non_numeric_response_value(field: str, value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    return value


def _reject_non_boolean_response_value(field: str, value: Any) -> Any:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _reject_non_empty_string(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _reject_invalid_datetime_response_value(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date-time string") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def _reject_non_empty_string_list(field: str, value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    return value


def _reject_string_list_map(field: str, value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    for key, items in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field} keys must be non-empty strings")
        _reject_non_empty_string_list(f"{field}.{key}", items)
    return value


def _reject_object_list(field: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must contain objects")
    return value


def _reject_object_map(field: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{field} keys must be non-empty strings")
    return value


def _reject_non_negative_integer(field: str, value: Any) -> Any:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _assert_dimension_applicable_to_format(fmt: str, dimension: str) -> None:
    """Raise ValueError if (fmt, dimension) is not in the applicability matrix."""
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"format unsupported: {fmt}")
    if dimension not in DIMENSIONS_BY_FORMAT[fmt]:
        raise ValueError(f"dimension {dimension!r} is not applicable to {fmt}")


class QualityDimensionScoreResponse(BaseModel):
    dimension: str
    format: str
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    variance: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    per_criterion: dict[str, float] = Field(default_factory=dict)
    judge_versions: list[str] = Field(default_factory=list)
    sample_findings: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)

    @field_validator("dimension", "format", mode="before")
    @classmethod
    def _reject_malformed_identity_fields(cls, value: Any, info: Any) -> str:
        return _reject_non_empty_string(str(info.field_name), value)

    @field_validator("score", "variance", "confidence", mode="before")
    @classmethod
    def _reject_malformed_numeric_fields(cls, value: Any, info: Any) -> Any:
        return _reject_non_numeric_response_value(str(info.field_name), value)

    @field_validator("per_criterion", mode="before")
    @classmethod
    def _validate_per_criterion(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("per_criterion must be an object")
        for criterion, score in value.items():
            _reject_non_empty_string("per_criterion key", criterion)
            _reject_non_numeric_response_value(f"per_criterion.{criterion}", score)
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ValueError(f"per_criterion.{criterion} must be finite")
            if numeric < 0.0 or numeric > 1.0:
                raise ValueError(
                    f"per_criterion.{criterion} must be between 0.0 and 1.0"
                )
        return value

    @field_validator("judge_versions", mode="before")
    @classmethod
    def _validate_judge_versions(cls, value: Any) -> list[str]:
        return _reject_non_empty_string_list("judge_versions", value)

    @field_validator("sample_findings", mode="before")
    @classmethod
    def _validate_sample_findings(cls, value: Any) -> list[dict[str, Any]]:
        return _reject_object_list("sample_findings", value)

    @model_validator(mode="after")
    def _validate_dimension_applicability(self) -> "QualityDimensionScoreResponse":
        _assert_dimension_applicable_to_format(self.format, self.dimension)
        return self


class BehavioralTestResultResponse(BaseModel):
    test_name: str
    dimension: str
    format: str
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    threshold: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("test_name", "dimension", "format", mode="before")
    @classmethod
    def _reject_malformed_identity_fields(cls, value: Any, info: Any) -> str:
        return _reject_non_empty_string(str(info.field_name), value)

    @field_validator("score", "threshold", "confidence", mode="before")
    @classmethod
    def _reject_malformed_numeric_fields(cls, value: Any, info: Any) -> Any:
        return _reject_non_numeric_response_value(str(info.field_name), value)

    @field_validator("passed", mode="before")
    @classmethod
    def _reject_malformed_passed(cls, value: Any) -> Any:
        return _reject_non_boolean_response_value("passed", value)

    @field_validator("findings", mode="before")
    @classmethod
    def _validate_findings(cls, value: Any) -> list[dict[str, Any]]:
        return _reject_object_list("findings", value)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        return value

    @model_validator(mode="after")
    def _validate_dimension_applicability(self) -> "BehavioralTestResultResponse":
        _assert_dimension_applicable_to_format(self.format, self.dimension)
        return self


class QualityResultResponse(BaseModel):
    format: str
    dimensions: dict[str, QualityDimensionScoreResponse] = Field(default_factory=dict)
    behavioral: dict[str, BehavioralTestResultResponse] = Field(default_factory=dict)
    overall_pass: bool
    failing_dimensions: list[str] = Field(default_factory=list)
    not_applicable_dimensions: list[str] = Field(default_factory=list)

    @field_validator("format", mode="before")
    @classmethod
    def _reject_malformed_format(cls, value: Any) -> str:
        return _reject_non_empty_string("format", value)

    @field_validator("dimensions", "behavioral", mode="before")
    @classmethod
    def _reject_malformed_result_maps(cls, value: Any, info: Any) -> dict[str, Any]:
        return _reject_object_map(str(info.field_name), value)

    @field_validator("overall_pass", mode="before")
    @classmethod
    def _reject_malformed_overall_pass(cls, value: Any) -> Any:
        return _reject_non_boolean_response_value("overall_pass", value)

    @field_validator("failing_dimensions", "not_applicable_dimensions", mode="before")
    @classmethod
    def _validate_dimension_lists(cls, value: Any, info: Any) -> list[str]:
        return _reject_non_empty_string_list(str(info.field_name), value)

    @model_validator(mode="after")
    def _validate_result_shape(self) -> "QualityResultResponse":
        if self.format not in DIMENSIONS_BY_FORMAT:
            raise ValueError(f"format unsupported: {self.format}")
        applicable = set(DIMENSIONS_BY_FORMAT[self.format])
        not_applicable = set(not_applicable_dimensions(self.format))
        for key, score in self.dimensions.items():
            if key != score.dimension:
                raise ValueError(f"dimensions key {key!r} must match nested dimension")
            if score.format != self.format:
                raise ValueError("dimension score format must match quality result format")
        for key, result in self.behavioral.items():
            if key != result.test_name:
                raise ValueError(f"behavioral key {key!r} must match nested test_name")
            if result.format != self.format:
                raise ValueError("behavioral result format must match quality result format")
        if invalid := sorted(set(self.failing_dimensions) - applicable):
            raise ValueError(
                f"failing_dimensions contains unsupported dimension(s): {', '.join(invalid)}"
            )
        if invalid := sorted(set(self.not_applicable_dimensions) - not_applicable):
            raise ValueError(
                "not_applicable_dimensions contains applicable or unknown "
                f"dimension(s): {', '.join(invalid)}"
            )
        return self


class QualityDimensionsResponse(BaseModel):
    all_dimensions: list[str]
    formats: dict[str, list[str]]
    not_applicable: dict[str, list[str]]

    @field_validator("all_dimensions", mode="before")
    @classmethod
    def _validate_all_dimensions(cls, value: Any) -> list[str]:
        return _reject_non_empty_string_list("all_dimensions", value)

    @field_validator("formats", "not_applicable", mode="before")
    @classmethod
    def _validate_dimension_maps(cls, value: Any, info: Any) -> dict[str, list[str]]:
        return _reject_string_list_map(str(info.field_name), value)


class CalibrationRowResponse(BaseModel):
    judge_id: str
    judge_version: str
    format: str
    dimension: str
    cohens_kappa: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    measured_at: str

    @field_validator("judge_id", "judge_version", "format", "dimension", mode="before")
    @classmethod
    def _reject_malformed_identity_fields(cls, value: Any, info: Any) -> str:
        return _reject_non_empty_string(str(info.field_name), value)

    @field_validator("cohens_kappa", "sample_size", mode="before")
    @classmethod
    def _reject_malformed_numeric_fields(cls, value: Any, info: Any) -> Any:
        if info.field_name == "cohens_kappa":
            return _reject_non_numeric_response_value("cohens_kappa", value)
        if isinstance(value, bool):
            raise ValueError("sample_size must be a positive integer")
        return value

    @field_validator("sample_size", mode="before")
    @classmethod
    def _reject_non_integer_sample_size(cls, value: Any) -> Any:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("sample_size must be a positive integer")
        return value

    @field_validator("measured_at", mode="before")
    @classmethod
    def _reject_invalid_measured_at(cls, value: Any) -> str:
        return _reject_invalid_datetime_response_value("measured_at", value)

    @model_validator(mode="after")
    def _validate_calibration_applicability(self) -> "CalibrationRowResponse":
        _assert_dimension_applicable_to_format(self.format, self.dimension)
        return self


class CalibrationListResponse(BaseModel):
    items: list[CalibrationRowResponse]
    total: int
    readiness: dict[str, Any]

    @field_validator("total", mode="before")
    @classmethod
    def _reject_malformed_total(cls, value: Any) -> Any:
        return _reject_non_negative_integer("total", value)

    @field_validator("readiness", mode="before")
    @classmethod
    def _reject_malformed_readiness(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("readiness must be an object")
        return value


class ReviewQueueResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int

    @field_validator("items", mode="before")
    @classmethod
    def _reject_malformed_items(cls, value: Any) -> Any:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError("items must be a list of objects")
        return value

    @field_validator("total", "offset", mode="before")
    @classmethod
    def _reject_malformed_non_negative_counts(cls, value: Any, info: Any) -> Any:
        return _reject_non_negative_integer(str(info.field_name), value)

    @field_validator("limit", mode="before")
    @classmethod
    def _reject_malformed_limit(cls, value: Any) -> Any:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("limit must be a positive integer")
        return value


class ReviewClaimRequest(BaseModel):
    doc_id: str
    reviewer_id: str
    format: str | None = None


class ReviewClaimResponse(BaseModel):
    claimed: bool
    item: dict[str, Any]

    @field_validator("claimed", mode="before")
    @classmethod
    def _reject_malformed_claimed(cls, value: Any) -> Any:
        return _reject_non_boolean_response_value("claimed", value)

    @field_validator("item", mode="before")
    @classmethod
    def _reject_malformed_item(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("item must be an object")
        return value


class ReviewSubmitResponse(BaseModel):
    accepted: bool
    annotation_path: str = ""
    calibration_rows_recorded: int = 0
    queue_item_completed: bool = False

    @field_validator("accepted", "queue_item_completed", mode="before")
    @classmethod
    def _reject_malformed_boolean_fields(cls, value: Any, info: Any) -> Any:
        return _reject_non_boolean_response_value(str(info.field_name), value)

    @field_validator("annotation_path", mode="before")
    @classmethod
    def _reject_malformed_annotation_path(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("annotation_path must be a string")
        return value

    @field_validator("calibration_rows_recorded", mode="before")
    @classmethod
    def _reject_malformed_calibration_count(cls, value: Any) -> Any:
        return _reject_non_negative_integer("calibration_rows_recorded", value)


async def _stage_pdf_for_quality(file: UploadFile, settings: Settings) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Accepts .pdf only.",
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max upload size ({settings.max_upload_mb} MB).",
        )
    if not contents.startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Uploaded file is not a valid PDF (magic-byte check failed).",
        )
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staged = settings.job_dir / f"_quality-{uuid.uuid4().hex}.pdf"
    staged.write_bytes(contents)
    return staged


async def _stage_office_for_quality(file: UploadFile, settings: Settings) -> tuple[Path, FileType]:
    suffix = Path(file.filename or "").suffix.lower()
    file_type = filetype_for_suffix(suffix)
    # Quality audit only supports OOXML formats; legacy OLE2 (.doc/.ppt/.xls) is rejected.
    if file_type not in {FileType.DOCX, FileType.PPTX, FileType.XLSX}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Accepts .docx/.pptx/.xlsx Office files only.",
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max upload size ({settings.max_upload_mb} MB).",
        )
    if not contents.startswith(_ZIP_MAGIC):
        raise HTTPException(415, "Not a valid OOXML (ZIP) file.")
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staged = settings.job_dir / f"_quality-{uuid.uuid4().hex}{suffix}"
    staged.write_bytes(contents)
    return staged, file_type


def build_router(
    settings: Settings,
    limiter: Limiter,
    upload_rate_limit: str,
) -> APIRouter:
    router = APIRouter(prefix="/v1/quality")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    @router.get("/dimensions", response_model=QualityDimensionsResponse, dependencies=[require_key])
    async def quality_dimensions() -> QualityDimensionsResponse:
        return QualityDimensionsResponse(
            all_dimensions=list(ALL_QUALITY_DIMENSIONS),
            formats={
                fmt: list(dimensions)
                for fmt, dimensions in DIMENSIONS_BY_FORMAT.items()
            },
            not_applicable={
                fmt: list(not_applicable_dimensions(fmt))
                for fmt in DIMENSIONS_BY_FORMAT
            },
        )

    @router.get("/calibration", response_model=CalibrationListResponse, dependencies=[require_key])
    async def quality_calibration(
        format: str | None = Query(default=None),
        dimension: str | None = Query(default=None),
    ) -> CalibrationListResponse:
        _validate_calibration_filters(format, dimension)
        store = ExperimentStore(settings.quality_experiment_store_path)
        rows = store.list_judge_calibration(format=format, dimension=dimension)
        readiness = {}
        if format:
            readiness = quality_calibration_status(settings, format).to_dict()
        return CalibrationListResponse(items=rows, total=len(rows), readiness=readiness)

    @router.get("/review/queue", response_model=ReviewQueueResponse, dependencies=[require_key])
    async def review_queue(
        request: Request,
        format: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> ReviewQueueResponse:
        _require_reviewer_key(request, settings)
        _validate_format_value(format, field="format")
        items = _read_jsonl(settings.quality_review_queue_path)
        if format:
            items = [item for item in items if item.get("format") == format]
        return ReviewQueueResponse(
            items=items[offset : offset + limit],
            total=len(items),
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/review/claim",
        response_model=ReviewClaimResponse,
        dependencies=[require_key],
    )
    async def review_claim(
        request: Request,
        claim: ReviewClaimRequest,
    ) -> ReviewClaimResponse:
        _require_reviewer_key(request, settings)
        _validate_format_value(claim.format, field="format")
        item = _claim_review_item(
            settings.quality_review_queue_path,
            doc_id=claim.doc_id,
            reviewer_id=claim.reviewer_id,
            fmt=claim.format,
        )
        return ReviewClaimResponse(claimed=True, item=item)

    @router.post(
        "/review/submit",
        response_model=ReviewSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[require_key],
    )
    async def review_submit(
        request: Request,
        verdict: dict[str, Any] = Body(...),
    ) -> ReviewSubmitResponse:
        _require_reviewer_key(request, settings)
        _validate_review_submission_identity(verdict)
        calibration_rows = _validated_calibration_rows_if_present(verdict)
        _reject_existing_calibration_conflicts(calibration_rows, settings)
        _assert_review_evidence_matches_submission(verdict, calibration_rows)
        _assert_review_submitter_can_complete(
            settings.quality_review_queue_path,
            verdict,
            has_annotation=isinstance(verdict.get("annotation"), dict),
            calibration_rows=calibration_rows,
        )
        _assert_review_submission_has_evidence(verdict, calibration_rows)
        annotation_path = _write_annotation_if_present(verdict, settings)
        calibration_count = _record_validated_calibration_rows(calibration_rows, settings)
        completed = _mark_review_completed_if_present(
            settings.quality_review_queue_path,
            verdict,
        )
        submission = {
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict,
            "annotation_path": str(annotation_path) if annotation_path else "",
            "calibration_rows_recorded": calibration_count,
            "queue_item_completed": completed,
        }
        _append_jsonl(settings.quality_review_submission_path, submission)
        return ReviewSubmitResponse(
            accepted=True,
            annotation_path=str(annotation_path) if annotation_path else "",
            calibration_rows_recorded=calibration_count,
            queue_item_completed=completed,
        )

    @router.post("/audit/pdf", response_model=QualityResultResponse, dependencies=[require_key])
    @upload_limit
    async def audit_pdf(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        staged = await _stage_pdf_for_quality(file, settings)
        try:
            assert_quality_calibrated(settings, "pdf")
            result = audit_pdf_quality(staged, config=load_config())
        except _AUDIT_CONFLICT_ERRORS as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        finally:
            staged.unlink(missing_ok=True)
        payload = QualityResultResponse.model_validate(asdict(result))
        return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))

    @router.post("/audit/office", response_model=QualityResultResponse, dependencies=[require_key])
    @upload_limit
    async def audit_office(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        staged, file_type = await _stage_office_for_quality(file, settings)
        try:
            assert_quality_calibrated(settings, file_type.value)
            result = audit_office_quality(staged, file_type=file_type, config=load_config())
        except _AUDIT_CONFLICT_ERRORS as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        finally:
            staged.unlink(missing_ok=True)
        payload = QualityResultResponse.model_validate(asdict(result))
        return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))

    return router


def _require_reviewer_key(request: Request, settings: Settings) -> None:
    """Gate specialist review endpoints when reviewer keys are configured."""
    if not settings.reviewer_keys:
        return
    supplied = request.headers.get("X-Reviewer-Key", "")
    if supplied not in settings.reviewer_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer key required.",
        )


def _validate_format_value(fmt: str | None, *, field: str) -> None:
    if fmt is None or fmt == "":
        return
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} unsupported format: {fmt}",
        )


def _validate_calibration_filters(fmt: str | None, dimension: str | None) -> None:
    _validate_format_value(fmt, field="format")
    if not dimension:
        return
    if dimension not in ALL_QUALITY_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"dimension unsupported: {dimension}",
        )
    if fmt and dimension not in DIMENSIONS_BY_FORMAT[fmt]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"dimension {dimension!r} is not applicable to {fmt}",
        )


def _validate_review_submission_identity(verdict: dict[str, Any]) -> None:
    for field_name in ("doc_id", "format", "reviewer_id"):
        if field_name not in verdict:
            continue
        value = verdict[field_name]
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"review submission {field_name} must be a non-empty string",
            )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"quality review JSONL is invalid at line {line_number}",
            ) from exc
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"quality review JSONL row {line_number} must be an object",
            )
        _validate_review_queue_row(item, line_number=line_number)
        items.append(item)
    return items


def _validate_review_queue_row(item: dict[str, Any], *, line_number: int) -> None:
    doc_id = item.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        _raise_invalid_review_queue_row(line_number, "doc_id is required")
    fmt = item.get("format")
    if fmt not in DIMENSIONS_BY_FORMAT:
        _raise_invalid_review_queue_row(line_number, f"unsupported format: {fmt}")
    status_value = item.get("status", "queued")
    if not isinstance(status_value, str) or status_value not in _REVIEW_QUEUE_STATUSES:
        _raise_invalid_review_queue_row(
            line_number,
            "status must be queued, claimed, or completed",
        )
    for field_name in ("source_path", "document_class"):
        if field_name in item and not isinstance(item[field_name], str):
            _raise_invalid_review_queue_row(
                line_number,
                f"{field_name} must be a string",
            )
    for field_name in ("claimed_by", "completed_by"):
        if field_name in item and (
            not isinstance(item[field_name], str) or not item[field_name].strip()
        ):
            _raise_invalid_review_queue_row(
                line_number,
                f"{field_name} must be a non-empty string",
            )
    if status_value == "claimed":
        if not isinstance(item.get("claimed_by"), str) or not item["claimed_by"].strip():
            _raise_invalid_review_queue_row(
                line_number,
                "claimed_by is required for claimed status",
            )
        if "claimed_at" not in item:
            _raise_invalid_review_queue_row(
                line_number,
                "claimed_at is required for claimed status",
            )
    if status_value == "completed" and "completed_at" not in item:
        _raise_invalid_review_queue_row(
            line_number,
            "completed_at is required for completed status",
        )
    source_sha256 = item.get("source_sha256", "")
    if not isinstance(source_sha256, str) or (
        source_sha256 and not _SHA256_RE.match(source_sha256)
    ):
        _raise_invalid_review_queue_row(
            line_number,
            "source_sha256 must be a sha256 hex digest",
        )
    if "priority_score" in item:
        _validate_review_queue_priority_score(item["priority_score"], line_number)
    if "priority_reasons" in item:
        _validate_review_queue_string_list(
            item["priority_reasons"],
            field_name="priority_reasons",
            line_number=line_number,
        )
    weak_dimensions = item.get("weak_dimensions", [])
    _validate_review_queue_string_list(
        weak_dimensions,
        field_name="weak_dimensions",
        line_number=line_number,
    )
    if len(set(weak_dimensions)) != len(weak_dimensions):
        _raise_invalid_review_queue_row(
            line_number,
            "weak_dimensions must not contain duplicates",
        )
    unsupported = sorted(set(weak_dimensions) - set(DIMENSIONS_BY_FORMAT[str(fmt)]))
    if unsupported:
        _raise_invalid_review_queue_row(
            line_number,
            "weak_dimensions contains dimension(s) not applicable to "
            f"{fmt}: {', '.join(unsupported)}",
        )
    for field_name in ("sampled_at", "claimed_at", "completed_at"):
        if field_name in item:
            _validate_review_queue_datetime(
                item[field_name],
                field_name=field_name,
                line_number=line_number,
            )


def _validate_review_queue_priority_score(value: Any, line_number: int) -> None:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError):
        _raise_invalid_review_queue_row(line_number, "priority_score must be numeric")
    if not math.isfinite(numeric):
        _raise_invalid_review_queue_row(line_number, "priority_score must be finite")
    if numeric < 0.0:
        _raise_invalid_review_queue_row(
            line_number,
            "priority_score must be non-negative",
        )


def _validate_review_queue_string_list(
    value: Any,
    *,
    field_name: str,
    line_number: int,
) -> None:
    if not isinstance(value, list):
        _raise_invalid_review_queue_row(line_number, f"{field_name} must be a list")
    invalid = [
        item
        for item in value
        if not isinstance(item, str) or not item.strip()
    ]
    if invalid:
        _raise_invalid_review_queue_row(
            line_number,
            f"{field_name} must contain non-empty strings",
        )


def _validate_review_queue_datetime(
    value: Any,
    *,
    field_name: str,
    line_number: int,
) -> None:
    if not isinstance(value, str) or not value.strip():
        _raise_invalid_review_queue_row(
            line_number,
            f"{field_name} must be an ISO date-time string",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _raise_invalid_review_queue_row(
            line_number,
            f"{field_name} must be an ISO date-time string",
        )
    if parsed.tzinfo is None:
        _raise_invalid_review_queue_row(
            line_number,
            f"{field_name} must include a timezone",
        )


def _raise_invalid_review_queue_row(line_number: int, detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"quality review JSONL row {line_number} invalid: {detail}",
    )


def _append_jsonl(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    tmp.replace(path)


def _claim_review_item(
    path: Path,
    *,
    doc_id: str,
    reviewer_id: str,
    fmt: str | None = None,
) -> dict[str, Any]:
    if not doc_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="doc_id is required",
        )
    if not reviewer_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="reviewer_id is required",
        )
    items = _read_jsonl(path)
    for item in items:
        if item.get("doc_id") != doc_id:
            continue
        if fmt and item.get("format") != fmt:
            continue
        if item.get("status") == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review item is already completed.",
            )
        current_reviewer = str(item.get("claimed_by") or "")
        if current_reviewer and current_reviewer != reviewer_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review item is already claimed.",
            )
        item["status"] = "claimed"
        item["claimed_by"] = reviewer_id
        item["claimed_at"] = datetime.now(timezone.utc).isoformat()
        _write_jsonl(path, items)
        return item
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Review item not found.",
    )


def _mark_review_completed_if_present(path: Path, verdict: dict[str, Any]) -> bool:
    annotation = verdict.get("annotation")
    annotation_payload = annotation if isinstance(annotation, dict) else {}
    doc_id = str(verdict.get("doc_id") or annotation_payload.get("doc_id") or "")
    fmt = verdict.get("format") or annotation_payload.get("format")
    if not doc_id:
        return False
    items = _read_jsonl(path)
    completed = False
    for item in items:
        if item.get("doc_id") != doc_id:
            continue
        if fmt and item.get("format") != fmt:
            continue
        item["status"] = "completed"
        item["completed_at"] = datetime.now(timezone.utc).isoformat()
        reviewer_id = str(verdict.get("reviewer_id") or "")
        if reviewer_id:
            item["completed_by"] = reviewer_id
        completed = True
        break
    if completed:
        _write_jsonl(path, items)
    return completed


def _assert_review_submitter_can_complete(
    path: Path,
    verdict: dict[str, Any],
    *,
    has_annotation: bool,
    calibration_rows: list[dict[str, Any]],
) -> None:
    """Reject submissions that try to complete another reviewer's claimed work."""
    annotation = verdict.get("annotation")
    annotation_payload = annotation if isinstance(annotation, dict) else {}
    doc_id = str(verdict.get("doc_id") or annotation_payload.get("doc_id") or "")
    fmt = verdict.get("format") or annotation_payload.get("format")
    if not doc_id:
        return
    reviewer_id = str(verdict.get("reviewer_id") or "")
    saw_different_format = False
    for item in _read_jsonl(path):
        if item.get("doc_id") != doc_id:
            continue
        if fmt and item.get("format") != fmt:
            saw_different_format = True
            continue
        if item.get("status") == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review item is already completed.",
            )
        claimed_by = str(item.get("claimed_by") or "")
        if claimed_by and reviewer_id != claimed_by:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review item is claimed by a different reviewer.",
            )
        if not has_annotation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="queued review completion requires annotation evidence",
            )
        item_format = str(item.get("format") or "")
        for row in calibration_rows:
            if item_format and str(row["format"]) != item_format:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="calibration row format must match queued review format",
                )
        return
    if has_annotation and saw_different_format:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="annotation format must match queued review format",
        )


def _assert_review_evidence_matches_submission(
    verdict: dict[str, Any],
    calibration_rows: list[dict[str, Any]],
) -> None:
    """Reject durable evidence that is bound to a different review item."""
    annotation = verdict.get("annotation")
    annotation_payload = annotation if isinstance(annotation, dict) else {}
    verdict_doc_id = str(verdict.get("doc_id") or "")
    annotation_doc_id = str(annotation_payload.get("doc_id") or "")
    if verdict_doc_id and annotation_doc_id and verdict_doc_id != annotation_doc_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="annotation doc_id must match review submission doc_id",
        )

    verdict_format = str(verdict.get("format") or "")
    annotation_format = str(annotation_payload.get("format") or "")
    _validate_format_value(verdict_format, field="review submission format")
    if verdict_format and annotation_format and verdict_format != annotation_format:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="annotation format must match review submission format",
        )

    expected_format = verdict_format or annotation_format
    if expected_format:
        for row in calibration_rows:
            if str(row["format"]) != expected_format:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="calibration row format must match review submission format",
                )


def _assert_review_submission_has_evidence(
    verdict: dict[str, Any],
    calibration_rows: list[dict[str, Any]],
) -> None:
    if "annotation" in verdict or calibration_rows:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="review submission requires annotation or calibration evidence",
    )


def _write_annotation_if_present(verdict: dict, settings: Settings) -> Path | None:
    """Persist a specialist annotation when the verdict carries one."""
    annotation = verdict.get("annotation")
    if annotation is None:
        return None
    if not isinstance(annotation, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="annotation must be an object",
        )
    errors = validate_annotation_record(annotation)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "annotation failed validation",
                "errors": [str(error) for error in errors],
            },
        )
    binding_errors = _review_queue_annotation_binding_errors(
        settings.quality_review_queue_path,
        annotation,
    )
    if binding_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "annotation does not match queued review item",
                "errors": binding_errors,
            },
        )
    try:
        return write_annotation_record(
            annotation,
            root=settings.quality_corpus_root_path,
            overwrite=bool(verdict.get("overwrite_annotation", False)),
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


def _review_queue_annotation_binding_errors(path: Path, annotation: dict[str, Any]) -> list[str]:
    """Return queue/annotation source binding errors for matching queued work."""
    doc_id = str(annotation.get("doc_id") or "")
    fmt = str(annotation.get("format") or "")
    if not doc_id or not fmt:
        return []
    queue_item = None
    for item in _read_jsonl(path):
        if item.get("doc_id") == doc_id and item.get("format") == fmt:
            queue_item = item
            break
    if queue_item is None:
        return []
    errors: list[str] = []
    queued_source = str(queue_item.get("source_path") or "")
    if queued_source and str(annotation.get("source_path") or "") != queued_source:
        errors.append("annotation source_path must match queued review source_path")
    queued_sha = str(queue_item.get("source_sha256") or "")
    artifact_hashes = annotation.get("artifact_hashes") if isinstance(annotation.get("artifact_hashes"), dict) else {}
    annotation_sha = str(artifact_hashes.get("source_sha256") or "")
    if queued_sha and annotation_sha != queued_sha:
        errors.append("annotation source_sha256 must match queued review source_sha256")
    return errors


def _validated_calibration_rows_if_present(verdict: dict) -> list[dict[str, Any]]:
    """Validate calibration rows before any review-submission side effects."""
    rows = verdict.get("calibration")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="calibration must be a list",
        )
    required_fields = {
        "judge_id",
        "judge_version",
        "format",
        "dimension",
        "cohens_kappa",
        "sample_size",
    }
    validated_rows: list[dict[str, Any]] = []
    seen_rows: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="calibration rows must be objects",
            )
        missing = sorted(required_fields - set(row))
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"calibration row missing fields: {', '.join(missing)}",
            )
        _validate_calibration_row(row)
        row_key = (
            str(row["judge_id"]),
            str(row["judge_version"]),
            str(row["format"]),
            str(row["dimension"]),
        )
        if row_key in seen_rows:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "duplicate calibration row: "
                    f"{row['judge_id']}:{row['judge_version']}({row['format']}/{row['dimension']})"
                ),
            )
        seen_rows.add(row_key)
        validated = dict(row)
        if validated.get("measured_at") is None:
            validated["measured_at"] = datetime.now(timezone.utc).isoformat()
        validated_rows.append(validated)
    return validated_rows


def _reject_existing_calibration_conflicts(
    rows: list[dict[str, Any]],
    settings: Settings,
) -> None:
    """Reject rows that would collide in the calibration store."""
    if not rows:
        return
    store = ExperimentStore(settings.quality_experiment_store_path)
    for row in rows:
        existing_rows = store.list_judge_calibration(
            format=str(row["format"]),
            dimension=str(row["dimension"]),
        )
        for existing in existing_rows:
            if (
                existing["judge_id"] == str(row["judge_id"])
                and existing["judge_version"] == str(row["judge_version"])
                and existing["measured_at"] == str(row["measured_at"])
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "calibration row already exists: "
                        f"{row['judge_id']}:{row['judge_version']}"
                        f"({row['format']}/{row['dimension']})@{row['measured_at']}"
                    ),
                )


def _record_validated_calibration_rows(
    rows: list[dict[str, Any]],
    settings: Settings,
) -> int:
    """Persist rows that have already passed route-level validation."""
    store = ExperimentStore(settings.quality_experiment_store_path)
    recorded = 0
    for row in rows:
        store.record_judge_calibration(
            judge_id=str(row["judge_id"]),
            judge_version=str(row["judge_version"]),
            format=str(row["format"]),
            dimension=str(row["dimension"]),
            cohens_kappa=float(row["cohens_kappa"]),
            sample_size=int(row["sample_size"]),
            measured_at=row.get("measured_at"),
        )
        recorded += 1
    return recorded


def _calibration_row_invalid(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
    )


def _validate_calibration_row(row: dict[str, Any]) -> None:
    for field_name in ("judge_id", "judge_version", "format", "dimension"):
        value = row[field_name]
        if not isinstance(value, str) or not value.strip():
            raise _calibration_row_invalid(
                f"calibration row {field_name} must be a non-empty string"
            )
    fmt = str(row["format"])
    dimension = str(row["dimension"])
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise _calibration_row_invalid(f"calibration row unsupported format: {fmt}")
    if dimension not in DIMENSIONS_BY_FORMAT[fmt]:
        raise _calibration_row_invalid(
            f"calibration row dimension {dimension!r} is not applicable to {fmt}"
        )

    kappa_raw = row["cohens_kappa"]
    if isinstance(kappa_raw, bool):
        raise _calibration_row_invalid("calibration row cohens_kappa must be numeric")
    try:
        kappa = float(kappa_raw)
    except (TypeError, ValueError) as exc:
        raise _calibration_row_invalid(
            "calibration row cohens_kappa must be numeric"
        ) from exc
    if not math.isfinite(kappa):
        raise _calibration_row_invalid("calibration row cohens_kappa must be finite")
    if kappa < 0 or kappa > 1:
        raise _calibration_row_invalid(
            "calibration row cohens_kappa must be between 0 and 1"
        )

    sample_size = row["sample_size"]
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, int)
        or sample_size <= 0
    ):
        raise _calibration_row_invalid(
            "calibration row sample_size must be a positive integer"
        )

    measured_at = row.get("measured_at")
    if measured_at is not None:
        try:
            parsed_measured_at = datetime.fromisoformat(str(measured_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise _calibration_row_invalid(
                "calibration row measured_at must be an ISO date-time string"
            ) from exc
        if parsed_measured_at.tzinfo is None:
            raise _calibration_row_invalid(
                "calibration row measured_at must include a timezone"
            )

    requirements = {
        (requirement.judge_id, requirement.judge_version, requirement.dimension)
        for requirement in required_judge_calibrations(fmt)
    }
    key = (str(row["judge_id"]), str(row["judge_version"]), dimension)
    if requirements and key not in requirements:
        raise _calibration_row_invalid(
            "calibration row does not match a required judge calibration "
            f"for {fmt}: {row['judge_id']}:{row['judge_version']}({dimension})"
        )
