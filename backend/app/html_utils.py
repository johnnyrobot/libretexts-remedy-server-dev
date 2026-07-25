"""Shared helpers for HTML upload, validation, and remediation routes."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from backend.app.config import Settings
from project_remedy.config import PipelineConfig
from project_remedy.models import ValidationResult
from project_remedy.validator import ValidationReport


async def stage_html_upload(file: UploadFile, settings: Settings) -> Path:
    """Validate and stage an uploaded HTML file under ``settings.job_dir``."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".html", ".htm"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Accepts .html / .htm only.",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max upload size ({settings.max_upload_mb} MB).",
        )
    if b"<html" not in contents.lower():
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File does not appear to be HTML.",
        )

    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staging = settings.job_dir / f"_html-{uuid.uuid4().hex}.html"
    staging.write_bytes(contents)
    return staging


def create_llm_client(config: PipelineConfig) -> Any:
    """Create the HTML-path LLM client."""
    from project_remedy.ollama_client import OllamaClient

    return OllamaClient(config)


def serialize_validation_result(result: ValidationResult) -> dict[str, Any]:
    """Return a stable JSON shape for a single validation tool result."""
    return {
        "score": result.score,
        "passed": result.passed,
        "violations": result.violations,
    }


def serialize_validation_report(report: ValidationReport) -> dict[str, Any]:
    """Return a stable JSON shape for a validation report."""
    return {
        "axe": serialize_validation_result(report.axe_result),
        "pa11y": serialize_validation_result(report.pa11y_result),
        "lighthouse": serialize_validation_result(report.lighthouse_result),
        "wave": serialize_validation_result(report.wave_result),
        "overall_passed": report.passed,
        "summary": report.summary,
        "all_violations": report.all_violations,
    }


def html_validator_dependency_detail(exc: Exception) -> str:
    """Render a consistent 503 detail for missing HTML validation tooling."""
    return (
        f"External validator tool missing: {exc}. "
        "Ensure pa11y, lighthouse, and playwright chromium are installed."
    )
