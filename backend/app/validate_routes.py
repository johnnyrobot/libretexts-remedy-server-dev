"""/v1/validate/* endpoints (Phase F).

- HTML validation: axe + pa11y + Lighthouse (via AccessibilityValidator)
- WAVE API: requires WAVE_API_KEY in env/config + a public URL of the
  HTML (WAVE fetches it server-side). For uploaded HTML this endpoint
  returns 501 unless the client supplies ``url`` form data.
- veraPDF: runs the veraPDF binary against an uploaded PDF.
- Adobe: Adobe PDF Services API (requires ADOBE_CLIENT_ID / SECRET).
- WCAG 2-tier: WCAGVisionVerifier (requires vision provider).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings
from backend.app.html_utils import (
    html_validator_dependency_detail,
    serialize_validation_report,
    stage_html_upload,
)


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
    staging = settings.job_dir / f"_pdf-{uuid.uuid4().hex}.pdf"
    staging.write_bytes(contents)
    return staging


def build_router(settings: Settings, limiter: Limiter, upload_rate_limit: str) -> APIRouter:
    router = APIRouter(prefix="/v1/validate")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    # ------------------------------------------------------------------
    # /html — axe + pa11y + Lighthouse
    # ------------------------------------------------------------------

    @router.post("/html", dependencies=[require_key])
    @upload_limit
    async def validate_html(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        from project_remedy.config import load_config
        from project_remedy.database import DatabaseManager
        from project_remedy.validator import AccessibilityValidator

        path = await stage_html_upload(file, settings)
        try:
            cfg = load_config()
            db = DatabaseManager()
            validator = AccessibilityValidator(cfg, None, db)
            try:
                report = await validator.validate(path)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=html_validator_dependency_detail(exc),
                ) from exc
            return JSONResponse(serialize_validation_report(report))
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /html/wave — WAVE API (needs public URL; returns 501 without one)
    # ------------------------------------------------------------------

    @router.post("/html/wave", dependencies=[require_key])
    async def validate_wave(url: str = Form(...)) -> JSONResponse:
        from project_remedy.config import load_config
        import httpx

        cfg = load_config()
        key = cfg.validation.wave_api_key
        if not key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WAVE_API_KEY not configured.",
            )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(
                    "https://wave.webaim.org/api/request",
                    params={
                        "key": key,
                        "url": url,
                        "reporttype": cfg.validation.wave_report_type,
                    },
                )
                r.raise_for_status()
                return JSONResponse(r.json())
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"WAVE API error: {exc}")

    # ------------------------------------------------------------------
    # /pdf/verapdf — veraPDF PDF/UA-1 validation
    # ------------------------------------------------------------------

    @router.post("/pdf/verapdf", dependencies=[require_key])
    @upload_limit
    async def validate_verapdf(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        import shutil as _shutil
        import subprocess

        path = await _stage_pdf(file, settings)
        try:
            from project_remedy.config import load_config
            cfg = load_config()
            verapdf = cfg.pdf_remediation.verapdf_path or _shutil.which("verapdf")
            if not verapdf or not Path(verapdf).exists():
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "veraPDF not found. Set VERAPDF_PATH or install veraPDF "
                        "+ Java 17+. https://verapdf.org/"
                    ),
                )
            proc = await asyncio.to_thread(
                subprocess.run,
                [verapdf, "--format", "json", "--flavour", "ua1", str(path)],
                capture_output=True, text=True, timeout=300,
            )
            import json as _json
            try:
                payload = _json.loads(proc.stdout) if proc.stdout else {}
            except _json.JSONDecodeError:
                payload = {"raw": proc.stdout[:4000]}
            return JSONResponse({
                "returncode": proc.returncode,
                "report": payload,
                "stderr": proc.stderr[:1000] if proc.stderr else "",
            })
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /pdf/adobe — Adobe PDF Services API
    # ------------------------------------------------------------------

    @router.post("/pdf/adobe", dependencies=[require_key])
    @upload_limit
    async def validate_adobe(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        import os
        from project_remedy.adobe_checker import check_accessibility

        if not (os.environ.get("ADOBE_CLIENT_ID") and os.environ.get("ADOBE_CLIENT_SECRET")):
            raise HTTPException(
                status_code=503,
                detail="Set ADOBE_CLIENT_ID + ADOBE_CLIENT_SECRET env vars.",
            )
        path = await _stage_pdf(file, settings)
        try:
            result = await asyncio.to_thread(check_accessibility, path)
            return JSONResponse({
                "passed": result.passed,
                "issues": result.issues,
                "raw_response_size": len(result.raw_report) if hasattr(result, "raw_report") else 0,
            })
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Adobe API error: {exc}")
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /pdf/wcag — 2-tier WCAG verifier
    # ------------------------------------------------------------------

    @router.post("/pdf/wcag", dependencies=[require_key])
    @upload_limit
    async def validate_wcag(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        from project_remedy.config import load_config
        from project_remedy.pdf_vision import create_provider_from_config
        from project_remedy.pdf_wcag_verifier import WCAGVisionVerifier

        path = await _stage_pdf(file, settings)
        try:
            cfg = load_config()
            provider = create_provider_from_config(cfg)
            if provider is None:
                raise HTTPException(503, "No vision provider configured.")
            verifier = WCAGVisionVerifier(provider)
            result = await verifier.verify_document(path)
            return JSONResponse(result.to_dict())
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"WCAG verify error: {exc}")
        finally:
            path.unlink(missing_ok=True)

    return router
