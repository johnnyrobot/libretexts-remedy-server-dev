"""/v1/vision-plan/* endpoints (Phase G, OPT-IN Tier 3).

Per the repo's AI strategy (REMEDY-69): the deterministic
fix_and_verify + faithful rebuild path is the default. Vision Planner
is exposed here as an explicit, opt-in tool — **not** wired into the
default /v1/remediate fallback.

Only a single end-to-end ``/v1/vision-plan/run`` endpoint is exposed
for v1. The grounder/planner/executor primitives are internal to the
pipeline; if you need them individually, compose a custom script over
the ``project_remedy.vision_planner`` package.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings
from backend.app.jobs import JOB_KIND_VISION_PLAN_RUN, JobStore, JobWorker
from backend.app.routes import _finalize_upload_and_enqueue


_PDF_MAGIC = b"%PDF-"


async def _stage_pdf(file: UploadFile, settings: Settings) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(415, "Accepts .pdf only.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB.")
    if not contents.startswith(_PDF_MAGIC):
        raise HTTPException(415, "Not a valid PDF.")
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staging = settings.job_dir / f"_vp-{uuid.uuid4().hex}.pdf"
    staging.write_bytes(contents)
    return staging


def build_router(
    settings: Settings,
    store: JobStore,
    worker: JobWorker,
    limiter: Limiter,
    upload_rate_limit: str,
) -> APIRouter:
    router = APIRouter(prefix="/v1/vision-plan")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    @router.post("/run", dependencies=[require_key])
    @upload_limit
    async def vision_plan_run(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        """End-to-end Vision Planner (Tier 3) rescue path, opt-in.

        Uploads a PDF, runs grounder → planner → executor with the current
        harness + configured LLM client, and returns a job id. Poll
        ``/v1/jobs/{id}`` for progress; when done, ``/v1/jobs/{id}/result``
        returns the remediated PDF and ``/v1/jobs/{id}/report`` returns the
        run trace as JSON.

        **Not** the default remediation path. Use ``/v1/remediate`` for
        the standard deterministic + faithful-rebuild pipeline.
        """
        staging = await _stage_pdf(file, settings)
        body = await _finalize_upload_and_enqueue(
            store, worker, settings, staging, ".pdf",
            kind=JOB_KIND_VISION_PLAN_RUN, result_media_type="application/pdf",
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)

    return router
