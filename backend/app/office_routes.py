"""/v1/office/* endpoints (Phase E).

Offers explicit Office-only variants. The generic ``/v1/remediate``
endpoint also accepts Office uploads and dispatches to the same engine
handler; these endpoints exist for clarity and for the sync ``/check``
path that ``/v1/remediate`` doesn't provide.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings
from backend.app.engine_service import filetype_for_suffix, is_office, media_type_for
from backend.app.jobs import JOB_KIND_REMEDIATE_OFFICE, JobStore, JobWorker
from backend.app.routes import _finalize_upload_and_enqueue  # reuse helper
from project_remedy.models import FileType


_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


async def _stage_office(file: UploadFile, settings: Settings) -> tuple[Path, FileType]:
    suffix = Path(file.filename or "").suffix.lower()
    ft = filetype_for_suffix(suffix)
    if ft is None or not is_office(ft):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Accepts .docx/.doc/.pptx/.ppt/.xlsx/.xls only.",
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max upload size ({settings.max_upload_mb} MB).",
        )
    if ft in (FileType.DOCX, FileType.PPTX, FileType.XLSX):
        if not contents.startswith(_ZIP_MAGIC):
            raise HTTPException(415, "Not a valid OOXML (ZIP) file.")
    else:  # legacy OLE2
        if not contents.startswith(_OLE2_MAGIC):
            raise HTTPException(415, "Not a valid OLE2 (legacy Office) file.")
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staging = settings.job_dir / f"_office-{uuid.uuid4().hex}{suffix}"
    staging.write_bytes(contents)
    return staging, ft


def build_router(
    settings: Settings,
    store: JobStore,
    worker: JobWorker,
    limiter: Limiter,
    upload_rate_limit: str,
) -> APIRouter:
    router = APIRouter(prefix="/v1/office")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    @router.post("/remediate", dependencies=[require_key])
    @upload_limit
    async def office_remediate(
        request: Request,
        file: UploadFile = File(...),
        quality: bool = Query(
            False,
            description="Opt in to attaching quality-layer audit results to Office remediation metadata.",
        ),
    ) -> JSONResponse:
        """Office-only remediate endpoint. Alias for /v1/remediate when you
        want the 415 message to be Office-specific.
        """
        staging, ft = await _stage_office(file, settings)
        body = await _finalize_upload_and_enqueue(
            store, worker, settings, staging, Path(file.filename or "").suffix,
            kind=JOB_KIND_REMEDIATE_OFFICE, result_media_type=media_type_for(ft),
            metadata_json=json.dumps({"quality": True}) if quality else None,
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)

    @router.post("/check", dependencies=[require_key])
    @upload_limit
    async def office_check(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        """Synchronous accessibility check on an uploaded Office doc."""
        from project_remedy.office_acceptance import evaluate_office_acceptance

        staging, ft = await _stage_office(file, settings)
        try:
            result = evaluate_office_acceptance(staging, file_type=ft)
            return JSONResponse({
                "file_type": ft.value,
                "passed": getattr(result, "passed", True),
                "checks": [asdict(r) for r in result.checker_report.results],
                "screen_reader_issues": [asdict(i) for i in result.screen_reader_result.issues],
                "package_valid": result.package_result.passed,
                "warnings": list(getattr(result, "warnings", [])),
            })
        finally:
            staging.unlink(missing_ok=True)

    return router
