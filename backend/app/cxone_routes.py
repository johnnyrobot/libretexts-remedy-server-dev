"""Local CXone page remediation proxy routes.

These routes let Conductor point at remedy-server while the CXone-specific
implementation remains in the local LibreTexts Remedy Node bridge.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from backend.app.cxone_transport import CxoneRoute, MUTATION_PATHS, guard_request, bridge_headers
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


class CxoneRestorePreviewRequest(CxoneScanRequest):
    snapshot_timestamp: str


class CxoneRestoreRequest(CxoneScanRequest):
    preview_hash: str
    preview_token: str


class CxoneOperationStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    issuer: str = Field(min_length=1, max_length=2048)
    jti: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class CxoneReviseRequest(CxoneScanRequest):
    preview_token: str
    alt_edits: list[dict[str, str]]


def build_router(settings: Settings) -> APIRouter:
    if getattr(settings, "cxone_integration_enabled", False):
        errors = settings.validation_errors()
        if errors:
            raise RuntimeError("Invalid CXone settings: " + "; ".join(errors))
    router = APIRouter(route_class=CxoneRoute, dependencies=[Depends(require_api_key_dependency(settings)), Depends(guard_request)])

    @router.get("/v1/cxone/health")
    async def cxone_health() -> Any:
        if not settings.cxone_integration_enabled:
            return {"ok": True, "state": "disabled", "enabled": False,
                    "capabilities": {name: False for name in ("scan", "preview", "mutate", "operation_status")}}
        try:
            async with httpx.AsyncClient(
                base_url=settings.cxone_bridge_base_url.rstrip("/"),
                timeout=settings.cxone_health_timeout_seconds,
                headers=bridge_headers(settings),
                trust_env=False,
            ) as client:
                response = await client.get("/readyz")
            data = _json_response(response)
        except (httpx.RequestError, HTTPException):
            return JSONResponse(status_code=503, content={
                "ok": False, "state": "degraded", "enabled": True,
                "error": "cxone_bridge_unavailable",
            })
        capabilities = data.get("capabilities") if isinstance(data, dict) else None
        if (not isinstance(data, dict) or type(data.get("ok")) is not bool
                or not isinstance(data.get("state"), str)
                or data.get("state") not in {"ready", "degraded", "misconfigured"}
                or not isinstance(capabilities, dict)
                or any(type(capabilities.get(name)) is not bool
                       for name in ("scan", "preview", "mutate", "operation_status"))
                or data["ok"] != (data["state"] == "ready")
                or response.status_code not in {200, 503}
                or (response.status_code == 200) != data["ok"]
                or not _valid_profile_readiness(data, capabilities)):
            return JSONResponse(status_code=503, content={
                "ok": False, "state": "misconfigured", "enabled": True,
                "error": "cxone_readiness_invalid",
            })
        return JSONResponse(status_code=response.status_code, content={**data, "enabled": True})

    @router.post("/v1/cxone/page/scan")
    async def scan_page(body: CxoneScanRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/scan", _payload(body))

    @router.post("/v1/cxone/page/preview-fix")
    async def preview_fix(body: CxonePreviewRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/preview-fix", _payload(body))

    @router.post("/v1/cxone/page/apply-fix")
    async def apply_fix(body: CxoneApplyRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/apply-fix", _payload(body))

    @router.post("/v1/cxone/page/snapshots")
    async def snapshots(body: CxoneScanRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/snapshots", _payload(body))

    @router.post("/v1/cxone/page/restore-preview")
    async def restore_preview(body: CxoneRestorePreviewRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/restore-preview", _payload(body))

    @router.post("/v1/cxone/page/restore")
    async def restore(body: CxoneRestoreRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/restore", _payload(body))

    @router.post("/v1/cxone/page/revise-preview")
    async def revise_preview(body: CxoneReviseRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/revise-preview", _payload(body))

    @router.post("/v1/cxone/page/operation-status")
    async def operation_status(body: CxoneOperationStatusRequest) -> Any:
        return await _forward(settings, "/v1/cxone/page/operation-status", _payload(body))

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
    if path != "/v1/cxone/page/operation-status" and not payload.get("page_url") and not payload.get("page_id"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_page_identifier",
                "message": "Request must include page_url or page_id.",
            },
        )

    bridge_url = settings.cxone_bridge_base_url.rstrip("/")
    if (settings.remedy_reviewer_required
            and path in MUTATION_PATHS
            and not payload.get("reviewer_assertion")):
        raise HTTPException(status_code=401, detail="Reviewer assertion is required.")
    try:
        async with httpx.AsyncClient(
            base_url=bridge_url,
            timeout=settings.cxone_bridge_timeout_seconds,
            headers=bridge_headers(settings),
            trust_env=False,
        ) as client:
            response = await client.post(path, json=payload)
    except httpx.TimeoutException as exc:
        raise _transport_failure(path, 504, "cxone_bridge_timeout") from exc
    except httpx.RequestError as exc:
        raise _transport_failure(path, 502, "cxone_bridge_unavailable") from exc

    try:
        data = _json_response(response)
    except HTTPException as exc:
        raise _transport_failure(path, 502, "cxone_bridge_non_json") from exc
    return JSONResponse(status_code=response.status_code, content=data)


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True)


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


def _transport_failure(path: str, status_code: int, error: str) -> HTTPException:
    detail: dict[str, Any] = {"error": error, "retryable": False}
    if path in MUTATION_PATHS:
        # A lost response cannot establish whether Bridge dispatched the write.
        detail.update(outcome="unknown_write", operation_id=None,
                      requires_reconciliation=True, evidence_effect="invalidate")
    return HTTPException(status_code=status_code, detail=detail)


def _valid_profile_readiness(data: dict[str, Any], capabilities: dict[str, bool]) -> bool:
    """Check the published named-capability contract; old producers stay full-write."""
    if "profile" not in data:
        return not data["ok"] or all(capabilities[name] for name in ("scan", "preview", "mutate", "operation_status"))
    profile = data["profile"]
    if not isinstance(profile, dict) or profile.get("contract") != "cxone-review-v1":
        return False
    name = profile.get("name")
    if name not in ("review-only", "full-write"):
        return False
    required = ["scan", "preview"] if name == "review-only" else ["scan", "preview", "mutate", "operation_status"]
    declared = profile.get("required_capabilities")
    reasons = profile.get("unavailable_reasons")
    if (not isinstance(declared, list) or not all(isinstance(item, str) for item in declared)
            or len(declared) != len(required) or set(declared) != set(required)
            or not isinstance(reasons, list) or not all(isinstance(item, str) and item for item in reasons)):
        return False
    if name == "review-only" and capabilities["mutate"]:
        return False
    ready = all(capabilities[item] for item in required)
    return ready == data["ok"] and bool(reasons) == (not ready)
