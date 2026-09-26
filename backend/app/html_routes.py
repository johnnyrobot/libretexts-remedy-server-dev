"""/v1/html/* synchronous HTML remediation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings
from backend.app.html_utils import (
    create_llm_client,
    html_validator_dependency_detail,
    serialize_validation_report,
    stage_html_upload,
)
from project_remedy.config import load_config
from project_remedy.database import DatabaseManager
from project_remedy.html_strategy_remediator import HTMLStrategyRemediator
from project_remedy.validator import AccessibilityValidator


def build_router(settings: Settings, limiter: Limiter, upload_rate_limit: str) -> APIRouter:
    router = APIRouter(prefix="/v1/html")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    @router.post("/remediate", dependencies=[require_key])
    @upload_limit
    async def remediate_html(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        """Apply deterministic HTML remediation, then LLM remediation if needed."""
        path = await stage_html_upload(file, settings)
        llm_client = None
        llm_started = False
        try:
            cfg = load_config()
            db = DatabaseManager()
            validator = AccessibilityValidator(cfg, None, db)
            html = path.read_text(encoding="utf-8", errors="replace")

            deterministic_html, deterministic_fixes = HTMLStrategyRemediator().remediate(html)
            path.write_text(deterministic_html, encoding="utf-8")

            try:
                initial_report = await validator.validate(path)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=html_validator_dependency_detail(exc),
                ) from exc

            remediated_html = deterministic_html
            final_report = initial_report
            remediation_count = 0
            used_llm = False

            if not initial_report.passed:
                llm_client = create_llm_client(cfg)
                validator = AccessibilityValidator(cfg, llm_client, db)
                try:
                    await llm_client.start()
                    llm_started = True
                    outcome = await validator.remediate_html_path(
                        path,
                        html=deterministic_html,
                        initial_report=initial_report,
                        page_title=file.filename or "HTML Document",
                        page_path=file.filename or path.name,
                    )
                except FileNotFoundError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=html_validator_dependency_detail(exc),
                    ) from exc

                remediated_html = outcome.html
                final_report = outcome.final_report
                remediation_count = outcome.remediation_count
                used_llm = outcome.used_llm

            return JSONResponse(
                {
                    "passed": final_report.passed,
                    "remediated_html": remediated_html,
                    "deterministic_fixes": deterministic_fixes,
                    "used_llm": used_llm,
                    "remediation_count": remediation_count,
                    "initial_report": serialize_validation_report(initial_report),
                    "final_report": serialize_validation_report(final_report),
                }
            )
        finally:
            if llm_client is not None and llm_started:
                try:
                    await llm_client.close()
                except Exception:  # noqa: BLE001
                    pass
            path.unlink(missing_ok=True)

    return router
