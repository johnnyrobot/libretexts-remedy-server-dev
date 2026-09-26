"""DOCX heading navigation proxy over Word outline styles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office._checks import report_for, result_from_rules
from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion
from project_remedy.models import FileType


@dataclass(frozen=True)
class DOCXHeading:
    text: str
    level: int
    paragraph_index: int


@dataclass(frozen=True)
class DOCXVisualHeadingCandidate:
    text: str
    paragraph_index: int
    reasons: tuple[str, ...]


class DOCXHeadingNavigationTest:
    test_name = "heading_navigation"
    dimension = "heading_semantics"
    format = "docx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        if artifact_path.exists():
            return score_docx_heading_navigation(
                docx_heading_outline(artifact_path),
                visual_heading_candidates=docx_visual_heading_candidates(artifact_path),
                answerer=kwargs.get("answerer"),
                navigation_questions=docx_heading_navigation_questions(artifact_path),
                baseline_text=str(kwargs.get("baseline_text") or ""),
                candidate_text=str(kwargs.get("candidate_text") or ""),
            )
        return result_from_rules(
            report_for(artifact_path, FileType.DOCX, kwargs),
            test_name=self.test_name,
            dimension=self.dimension,
            fmt=self.format,
            rule_ids=("docx-headings",),
            threshold=0.85,
        )


def docx_heading_outline(artifact_path: Path) -> list[DOCXHeading]:
    """Extract heading/title paragraphs from a DOCX artifact."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return []

    try:
        document = Document(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes this proxy inapplicable.
        return []

    headings: list[DOCXHeading] = []
    for paragraph_index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if not text:
            continue
        level = _heading_level(paragraph, qn)
        if level is None:
            continue
        headings.append(DOCXHeading(text=text, level=level, paragraph_index=paragraph_index))
    return headings


def docx_visual_heading_candidates(artifact_path: Path) -> list[DOCXVisualHeadingCandidate]:
    """Find visually heading-like DOCX paragraphs missing semantic heading styles."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return []

    try:
        document = Document(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes this proxy inapplicable.
        return []

    candidates: list[DOCXVisualHeadingCandidate] = []
    for paragraph_index, paragraph in enumerate(document.paragraphs, start=1):
        text = " ".join(paragraph.text.split())
        if not text or _heading_level(paragraph, qn) is not None:
            continue
        reasons = _visual_heading_reasons(paragraph, text)
        if not reasons:
            continue
        candidates.append(
            DOCXVisualHeadingCandidate(
                text=text,
                paragraph_index=paragraph_index,
                reasons=tuple(reasons),
            )
        )
    return candidates


def score_docx_heading_navigation(
    headings: list[DOCXHeading],
    *,
    visual_heading_candidates: list[DOCXVisualHeadingCandidate] | None = None,
    threshold: float = 0.85,
    answerer: BehavioralAnswerer | None = None,
    navigation_questions: list[GeneratedQuestion] | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    """Score whether the DOCX heading outline supports navigation."""
    candidates = list(visual_heading_candidates or [])
    if not headings and not candidates:
        return BehavioralTestResult(
            test_name="heading_navigation",
            dimension="heading_semantics",
            format="docx",
            passed=False,
            score=0.0,
            threshold=threshold,
            confidence=0.75,
            findings=[
                {
                    "severity": "warning",
                    "issue": "no_docx_headings",
                    "message": "No Word heading styles or outline levels are available for navigation.",
                }
            ],
            metadata={
                "applicable": True,
                "parser_support": "python_docx_heading_styles",
                "heading_count": 0,
                "visual_heading_candidate_count": 0,
                "llm_answering_enabled": answerer is not None,
            },
        )

    findings: list[dict[str, Any]] = []
    previous = 0
    skips = 0
    for heading in headings:
        if previous and heading.level > previous + 1:
            skips += 1
            findings.append(
                {
                    "severity": "error",
                    "issue": "docx_heading_level_skip",
                    "paragraph_index": heading.paragraph_index,
                    "text": heading.text,
                    "level": heading.level,
                    "previous_level": previous,
                }
            )
        previous = heading.level
    for candidate in candidates:
        findings.append(
            {
                "severity": "error",
                "issue": "docx_visual_heading_without_semantic_style",
                "paragraph_index": candidate.paragraph_index,
                "text": candidate.text,
                "reasons": list(candidate.reasons),
            }
        )
    denominator = len(headings) + len(candidates)
    structural_score = max(0.0, 1.0 - ((skips + len(candidates)) / denominator))
    score = structural_score
    questions = list(navigation_questions or [])
    metadata: dict[str, Any] = {
        "applicable": True,
        "parser_support": "python_docx_heading_styles",
        "heading_count": len(headings),
        "visual_heading_candidate_count": len(candidates),
        "llm_answering_enabled": answerer is not None,
        "navigation_question_count": len(questions),
        "outline": [
            {
                "text": heading.text,
                "level": heading.level,
                "paragraph_index": heading.paragraph_index,
            }
            for heading in headings
        ],
        "visual_heading_candidates": [
            {
                "text": candidate.text,
                "paragraph_index": candidate.paragraph_index,
                "reasons": list(candidate.reasons),
            }
            for candidate in candidates
        ],
    }
    if answerer is not None and questions:
        candidate_context = candidate_text or _heading_outline_text(headings)
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or candidate_context,
            candidate_context=candidate_context,
            answerer=answerer,
        )
        score = min(structural_score, retention.retention)
        findings.extend(retention.findings)
        metadata.update(
            {
                "baseline_accuracy": retention.baseline_accuracy,
                "candidate_accuracy": retention.candidate_accuracy,
                "answer_accuracy_retention": retention.retention,
            }
        )
    return BehavioralTestResult(
        test_name="heading_navigation",
        dimension="heading_semantics",
        format="docx",
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.70,
        findings=findings,
        metadata=metadata,
    )


def docx_heading_navigation_questions(artifact_path: Path) -> list[GeneratedQuestion]:
    """Generate heading-location questions from body paragraphs."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return []

    try:
        document = Document(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes questions unavailable.
        return []

    questions: list[GeneratedQuestion] = []
    current_heading = ""
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        if not text:
            continue
        if _heading_level(paragraph, qn) is not None:
            current_heading = text
            continue
        if not current_heading or len(text.split()) < 4:
            continue
        questions.append(
            GeneratedQuestion(
                question=(
                    "Which Word heading contains information about this content: "
                    f"{text[:120]}?"
                ),
                expected_answer=current_heading,
                source_dimension="heading_semantics",
            )
        )
        if len(questions) >= 5:
            break
    return questions


def _heading_outline_text(headings: list[DOCXHeading]) -> str:
    return "\n".join(
        f"Heading {heading.level}: {heading.text}"
        for heading in headings
        if heading.text
    )


def _visual_heading_reasons(paragraph: Any, text: str) -> list[str]:
    if not _looks_like_standalone_heading_text(text):
        return []
    reasons: list[str] = []
    if _paragraph_has_large_text(paragraph):
        reasons.append("large_text")
    if _paragraph_is_bold(paragraph):
        reasons.append("bold_text")
    return reasons


def _looks_like_standalone_heading_text(text: str) -> bool:
    words = text.split()
    return (
        1 <= len(words) <= 12
        and len(text) <= 100
        and text[-1:] not in {".", "?", "!"}
    )


def _paragraph_has_large_text(paragraph: Any) -> bool:
    sizes = [
        size
        for run in paragraph.runs
        if run.text.strip()
        for size in (_font_size_points(run),)
        if size is not None
    ]
    style_size = _font_size_points(getattr(paragraph, "style", None))
    if style_size is not None:
        sizes.append(style_size)
    return bool(sizes and max(sizes) >= 16.0)


def _paragraph_is_bold(paragraph: Any) -> bool:
    text_runs = [run for run in paragraph.runs if run.text.strip()]
    style_bold = bool(getattr(getattr(getattr(paragraph, "style", None), "font", None), "bold", False))
    if not text_runs:
        return style_bold
    return all(run.bold is True or (run.bold is None and style_bold) for run in text_runs)


def _font_size_points(item: Any) -> float | None:
    font = getattr(item, "font", item)
    size = getattr(font, "size", None)
    points = getattr(size, "pt", None)
    try:
        return float(points) if points is not None else None
    except (TypeError, ValueError):
        return None


def _heading_level(paragraph: Any, qn: Any) -> int | None:
    style_name = (getattr(getattr(paragraph, "style", None), "name", "") or "").strip()
    normalized = style_name.lower()
    if normalized.startswith("title"):
        return 1
    match = re.match(r"^heading\s+([1-6])$", normalized)
    if match:
        return int(match.group(1))
    p_pr = paragraph._p.pPr
    if p_pr is None:
        return None
    outline = p_pr.find(qn("w:outlineLvl"))
    if outline is None:
        return None
    value = outline.get(qn("w:val"))
    try:
        return int(value) + 1
    except (TypeError, ValueError):
        return None
