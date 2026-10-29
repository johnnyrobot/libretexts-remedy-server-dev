"""API key auth dependency.

Checks the ``X-API-Key`` header against ``settings.api_key``. If the
configured key is empty, auth is disabled (useful for local dev).
"""

from __future__ import annotations

from hashlib import sha256
from secrets import compare_digest

from fastapi import Header, HTTPException, Request, status

from backend.app.config import Settings


def require_api_key_dependency(settings: Settings):
    """Factory that returns a FastAPI dependency bound to *settings*."""

    expected = sha256(settings.api_key.encode("utf-8")).digest()

    async def _dep(request: Request, x_api_key: str | None = Header(default=None)) -> None:
        # The declared header preserves OpenAPI; only the raw list is trusted.
        keys = request.headers.getlist("x-api-key")
        if len(keys) > 1:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")
        if not settings.api_key:
            return  # auth disabled
        if not compare_digest(sha256((keys[0] if keys else "").encode("utf-8")).digest(), expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key header.",
            )

    return _dep
