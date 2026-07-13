"""Local CXone page remediation proxy routes.

These routes let Conductor point at remedy-server while the CXone-specific
implementation remains in the local LibreTexts Remedy Node bridge.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings


class CxoneBridgeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class CxoneScanRequest(CxoneBridgeRequest):
    page_url: str | None = None
    page_id: int | str | None = None
    section_title: str | None = None


class CxonePreviewRequest(CxoneBridgeRequest):
    page_url: str | None = None
    page_id: int | str | None = None
    finding_ids: list[str] = Field(default_factory=list)
    fix_mode: str | None = None
    tier: int | None = None


class CxoneApplyRequest(CxonePreviewRequest):
    preview_hash: str
    preview_token: str | None = None


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    require_key = Depends(require_api_key_dependency(settings))

    @router.get("/v1/cxone/health", dependencies=[require_key])
    async def cxone_health() -> Any:
        scope = {
            "host": "dev.libretexts.org",
            "root": "Sandboxes/johnnyphung",
        }
        if not settings.cxone_integration_enabled:
            return {
                "ok": True,
                "state": "disabled",
                "enabled": False,
                "write_scope": scope,
            }
        try:
            async with httpx.AsyncClient(
                base_url=settings.cxone_bridge_base_url.rstrip("/"),
                timeout=settings.cxone_health_timeout_seconds,
            ) as client:
                response = await client.get("/healthz")
        except (httpx.TimeoutException, httpx.RequestError):
            return {
                "ok": False,
                "state": "degraded",
                "enabled": True,
                "error": "cxone_bridge_unavailable",
                "write_scope": scope,
            }
        try:
            data = _json_response(response)
        except HTTPException:
            return {
                "ok": False,
                "state": "degraded",
                "enabled": True,
                "error": "cxone_bridge_unavailable",
                "write_scope": scope,
            }
        if response.status_code >= 400 or not isinstance(data, dict):
            return {
                "ok": False,
                "state": "degraded",
                "enabled": True,
                "error": "cxone_bridge_unavailable",
                "write_scope": scope,
            }
        state = data.get("state")
        if state not in {"ready", "degraded", "misconfigured"}:
            state = "misconfigured"
        result = {
            "ok": state == "ready",
            "state": state,
            "enabled": True,
            "write_scope": scope,
        }
        if state != "ready":
            result["error"] = data.get("error") or "cxone_configuration_invalid"
        return result

    @router.post("/v1/cxone/page/scan", dependencies=[require_key])
    async def scan_page(body: CxoneScanRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/scan", _payload(body))

    @router.post("/v1/cxone/page/preview-fix", dependencies=[require_key])
    async def preview_fix(body: CxonePreviewRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/preview-fix", _payload(body))

    @router.post("/v1/cxone/page/apply-fix", dependencies=[require_key])
    async def apply_fix(body: CxoneApplyRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/apply-fix", _payload(body))

    return router


async def _forward(settings: Settings, path: str, payload: dict[str, Any]) -> Any:
    if not settings.cxone_integration_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "cxone_integration_disabled",
                "message": "CXone integration is disabled on this environment.",
            },
        )
    if not payload.get("page_url") and not payload.get("page_id"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_page_identifier",
                "message": "Request must include page_url or page_id.",
            },
        )

    bridge_url = settings.cxone_bridge_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=bridge_url,
            timeout=settings.cxone_bridge_timeout_seconds,
        ) as client:
            response = await client.post(path, json=payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "cxone_bridge_timeout",
                "message": "CXone integration timed out.",
            },
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "cxone_bridge_unavailable",
                "message": "CXone integration is unavailable.",
            },
        ) from exc

    data = _json_response(response)
    if response.status_code >= 400:
        status_code = (
            response.status_code
            if response.status_code < status.HTTP_500_INTERNAL_SERVER_ERROR
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": _error_code(data, "cxone_bridge_error"),
                "message": _error_message(data, "CXone bridge request failed."),
                "bridge_status": response.status_code,
            },
        )

    if isinstance(data, dict) and (data.get("err") is True or data.get("error") is True):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": _error_code(data, "cxone_bridge_error"),
                "message": _error_message(data, "CXone bridge request failed."),
            },
        )

    return data


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_none=True)


def _json_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "cxone_bridge_non_json",
                "message": "CXone bridge returned a non-JSON response.",
            },
        ) from exc


def _error_message(data: Any, fallback: str) -> str:
    if not isinstance(data, dict):
        return fallback
    detail = data.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(data.get("message"), str):
        return data["message"]
    if isinstance(data.get("error"), str):
        return data["error"]
    return fallback


def _error_code(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("error"), str):
            return detail["error"]
        if isinstance(data.get("code"), str):
            return data["code"]
        if isinstance(data.get("error"), str):
            return data["error"]
    return fallback
