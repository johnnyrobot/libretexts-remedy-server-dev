"""Unambiguous assertion transport; signature verification belongs to Bridge."""
from __future__ import annotations

import base64
import json
import re

from fastapi import HTTPException, Request

from backend.app.config import Settings


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


def _compact(value) -> bool:
    if not isinstance(value, str) or len(value) > 8192:
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", part):
            return False
        try:
            raw = base64.b64decode(part + "=" * (-len(part) % 4), altchars=b"-_", validate=True)
        except ValueError:
            return False
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != part:
            return False
    return True


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
        if request.url.path.endswith("/operation-status") and "reviewer_assertion" in body:
            raise ValueError("assertion not allowed on status")
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid CXone JSON or assertion transport.") from None
