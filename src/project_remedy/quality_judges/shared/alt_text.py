"""Shared alt-text specificity helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_remedy.pdf_checker import _is_generic_alt_text


GENERIC_ALT_TEXT_LABELS = {
    "chart",
    "diagram",
    "figure",
    "graph",
    "graphic",
    "image",
    "photo",
    "picture",
    "plot",
}


@dataclass(frozen=True)
class AltTextAssessment:
    score: float
    presence_score: float
    specificity_score: float
    findings: tuple[dict[str, Any], ...]
    missing_count: int
    non_substitutive_count: int
    duplicate_count: int


def alt_text_value(item: Any) -> str:
    """Return the title/description alt text carried by an OOXML object."""
    return " ".join(
        str(part).strip()
        for part in (
            getattr(item, "title", ""),
            getattr(item, "description", ""),
        )
        if str(part).strip()
    )


def has_alt_text(item: Any) -> bool:
    return bool(alt_text_value(item))


def has_substitutive_alt_text(item: Any) -> bool:
    text = str(getattr(item, "description", "")).strip() or str(
        getattr(item, "title", "")
    ).strip()
    return bool(text) and not is_generic_alt_text(text)


def is_generic_alt_text(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    if normalized in GENERIC_ALT_TEXT_LABELS:
        return True
    return _is_generic_alt_text(text)


def assess_office_alt_text(
    objects: list[Any],
    *,
    missing_issue: str,
    generic_issue: str,
    duplicate_issue: str,
) -> AltTextAssessment:
    """Score OOXML alt text for presence, specificity, and duplicate reuse."""
    if not objects:
        return AltTextAssessment(
            score=1.0,
            presence_score=0.0,
            specificity_score=0.0,
            findings=(),
            missing_count=0,
            non_substitutive_count=0,
            duplicate_count=0,
        )

    findings: list[dict[str, Any]] = []
    missing = [item for item in objects if not has_alt_text(item)]
    non_substitutive = [
        item for item in objects if has_alt_text(item) and not has_substitutive_alt_text(item)
    ]
    substitutive_by_text: dict[str, list[Any]] = {}
    for item in objects:
        if has_substitutive_alt_text(item):
            normalized = " ".join(alt_text_value(item).casefold().split())
            substitutive_by_text.setdefault(normalized, []).append(item)

    for item in missing:
        findings.append(_object_finding(item, issue=missing_issue))
    for item in non_substitutive:
        finding = _object_finding(item, issue=generic_issue)
        finding["alt_text"] = alt_text_value(item)
        findings.append(finding)

    duplicate_count = 0
    for alt_text, duplicates in sorted(substitutive_by_text.items()):
        if len(duplicates) < 2:
            continue
        duplicate_count += len(duplicates) - 1
        findings.append(
            {
                "severity": "error",
                "issue": duplicate_issue,
                "object_indices": [
                    int(getattr(item, "object_index", 0) or 0)
                    for item in duplicates
                ],
                "duplicate_count": len(duplicates),
                "alt_text": alt_text,
            }
        )

    substitutive_count = max(
        0,
        sum(1 for item in objects if has_substitutive_alt_text(item)) - duplicate_count,
    )
    presence_score = (len(objects) - len(missing)) / len(objects)
    specificity_score = substitutive_count / len(objects)
    return AltTextAssessment(
        score=specificity_score,
        presence_score=presence_score,
        specificity_score=specificity_score,
        findings=tuple(findings),
        missing_count=len(missing),
        non_substitutive_count=len(non_substitutive),
        duplicate_count=duplicate_count,
    )


def _object_finding(item: Any, *, issue: str) -> dict[str, Any]:
    return {
        "severity": "error",
        "issue": issue,
        "source": str(getattr(item, "source", "")),
        "object_index": int(getattr(item, "object_index", 0) or 0),
        "name": str(getattr(item, "name", "")),
    }
