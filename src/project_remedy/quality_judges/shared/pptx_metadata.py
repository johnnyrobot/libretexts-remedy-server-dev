"""Shared PPTX metadata validation helpers."""

from __future__ import annotations

from typing import Any


def validate_slide_count(value: Any) -> int | None:
    """Return a validated PPTX slide count.

    Caller-provided slide counts are evidence metadata. They must not be
    coerced from booleans, strings, floats, or negative values because fallback
    per-slide signals would then look more precise than the evidence supports.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("slide_count must be a non-negative integer")
    if value < 0:
        raise ValueError("slide_count must be a non-negative integer")
    return value
