"""Small numeric helpers shared across quality judges."""

from __future__ import annotations


def safe_ratio(numerator: int, denominator: int) -> float:
    """Return ``numerator / denominator`` rounded to 4 places, or 0.0 when zero."""
    return round(numerator / denominator, 4) if denominator else 0.0
