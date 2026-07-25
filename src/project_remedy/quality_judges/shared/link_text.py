"""Shared link-text descriptiveness helpers."""

from __future__ import annotations

import re


GENERIC_LINK_TEXT = {
    "click here",
    "here",
    "read more",
    "more",
    "learn more",
    "download",
    "link",
    "this link",
    "visit website",
    "website",
}
_RAW_URL_TEXT_RE = re.compile(
    r"(?:https?://|www\.)\S+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/\S*)?",
    re.IGNORECASE,
)


def descriptive_link_text(text: str, target: str = "") -> bool:
    """Return whether visible link text is useful without surrounding context."""
    normalized = " ".join(text.split()).strip().lower()
    if not normalized:
        return False
    if normalized in GENERIC_LINK_TEXT:
        return False
    if _RAW_URL_TEXT_RE.fullmatch(normalized):
        return False
    target_normalized = target.strip().lower().rstrip("/")
    if target_normalized and normalized.rstrip("/") == target_normalized:
        return False
    return len(normalized) >= 4
