"""API key auth dependency.

Checks the ``X-API-Key`` header against ``settings.api_key``. If the
configured key is empty, auth is disabled (useful for local dev).
"""

from __future__ import annotations

from secrets import compare_digest

from fastapi import Header, HTTPException, status

from backend.app.config import Settings


def require_api_key_dependency(settings: Settings):
    """Factory that returns a FastAPI dependency bound to *settings*."""

    async def _dep(x_api_key: str | None = Header(default=None)) -> None:
        if not settings.api_key:
            return  # auth disabled
        if not compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key header.",
            )

    return _dep
