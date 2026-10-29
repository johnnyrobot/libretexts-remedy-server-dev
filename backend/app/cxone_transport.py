"""Unambiguous assertion transport; signature verification belongs to Bridge."""
from __future__ import annotations

import base64
import json
import re

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.app.config import Settings

MUTATION_PATHS = frozenset({"/v1/cxone/page/apply-fix", "/v1/cxone/page/restore"})


class CxoneRoute(APIRoute):
    """Framework validation must never echo the signed input object."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                status = 400 if request.url.path.endswith("/operation-status") else 422
                return JSONResponse(status_code=status, content={"detail": "Invalid CXone request."})

        return sanitized


def bridge_headers(settings: Settings) -> dict[str, str]:
    if settings.remedy_reviewer_required or settings.remedy_bridge_service_key_file:
        return {"X-Remedy-Service-Key": settings.bridge_service_key}
    return {}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _assertion_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized == "assertion" or normalized.endswith("reviewerassertion")


def _check_body(value, *, top=False) -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            if _assertion_name(name) and (not top or name != "reviewer_assertion" or not _compact(item)):
                raise ValueError("invalid assertion carrier")
            _check_body(item)
    elif isinstance(value, list):
        for item in value:
            _check_body(item)


def _canonical_segment(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return False
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        return False
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") == value


def _compact(value) -> bool:
    if not isinstance(value, str) or len(value) > 8192:
        return False
    parts = value.split(".")
    return len(parts) == 3 and all(_canonical_segment(part) for part in parts)


async def guard_request(request: Request) -> None:
    # No carrier other than one top-level, snake_case JSON string is accepted.
    for name in request.headers:
        if _assertion_name(name) or name.lower() == "authorization":
            raise HTTPException(status_code=400, detail="Invalid assertion transport.")
    if any(_assertion_name(name) for name in request.query_params) or any(
        _assertion_name(name) for name in request.cookies
    ):
        raise HTTPException(status_code=400, detail="Invalid assertion transport.")
    if request.method != "POST":
        return
    try:
        body = json.loads(await request.body(), object_pairs_hook=_pairs)
        if not isinstance(body, dict):
            raise ValueError("object required")
        _check_body(body, top=True)
        if request.url.path.endswith("/operation-status"):
            nonce = body.get("jti")
            if ("reviewer_assertion" in body or not isinstance(nonce, str)
                    or len(nonce) != 43 or not _canonical_segment(nonce)):
                raise ValueError("invalid operation lookup")
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid CXone JSON or assertion transport.") from None
