"""PDF heading navigation behavioral proxy."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import (
    BehavioralTestResult,
    require_unit_interval,
)
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


_HEADING_TAGS = {"H", "H1", "H2", "H3", "H4", "H5", "H6"}
_GENERIC_HEADING_LABELS = {
    "heading",
    "section",
    "title",
    "untitled",
}


def _heading_level(tag: str) -> int:
    if tag == "H":
        return 0
    match = re.match(r"^H(\d)$", tag)
    return int(match.group(1)) if match else 0


def score_heading_navigation_report(
    report: TagTreeReport,
    *,
    threshold: float = 0.85,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    """Score whether the heading outline supports navigation."""
    headings = [node for node in report.nodes if node.tag in _HEADING_TAGS]
    findings: list[dict[str, Any]] = []
    if not headings:
        return BehavioralTestResult(
            test_name="heading_navigation",
            dimension="heading_semantics",
            format="pdf",
            passed=False,
            score=0.0,
            threshold=threshold,
            confidence=0.8,
            findings=[
                {
                    "severity": "warning",
                    "issue": "no_headings",
                    "message": "No headings are available for navigation.",
                }
            ],
            metadata={"heading_count": 0},
        )

    normalized_counts = Counter(
        " ".join((node.text or node.alt_text or "").split()).casefold()
        for node in headings
        if (node.text or node.alt_text or "").strip()
    )
    duplicate_normalized = {
        normalized
        for normalized, count in normalized_counts.items()
        if count > 1
    }

    previous = 0
    issue_weight = 0.0
    non_descriptive_headings = 0
    duplicate_headings = 0
    for node in headings:
        level = _heading_level(node.tag)
        text = " ".join((node.text or node.alt_text or "").split())
        normalized = text.casefold()
        if not text:
            issue_weight += 1.0
            findings.append(
                {
                    "severity": "error",
                    "issue": "empty_heading",
                    "page": node.page,
                    "tag": node.tag,
                }
            )
        elif _is_non_descriptive_heading(normalized):
            issue_weight += 1.0
            non_descriptive_headings += 1
            findings.append(
                {
                    "severity": "warning",
                    "issue": "non_descriptive_heading",
                    "page": node.page,
                    "tag": node.tag,
                    "text": text,
                }
            )
        elif normalized in duplicate_normalized:
            issue_weight += 1.0
            duplicate_headings += 1
            findings.append(
                {
                    "severity": "warning",
                    "issue": "duplicate_heading",
                    "page": node.page,
                    "tag": node.tag,
                    "text": text,
                }
            )
        if level and previous and level > previous + 1:
            issue_weight += 1.0
            findings.append(
                {
                    "severity": "error",
                    "issue": "heading_level_skip",
                    "page": node.page,
                    "tag": node.tag,
                    "previous_level": previous,
                }
            )
        if level:
            previous = level

    structural_score = max(0.0, 1.0 - (issue_weight / max(len(headings), 1)))
    score = structural_score
    questions = _navigation_questions(report)
    metadata: dict[str, Any] = {
        "heading_count": len(headings),
        "non_descriptive_heading_count": non_descriptive_headings,
        "duplicate_heading_count": duplicate_headings,
        "llm_answering_enabled": answerer is not None,
        "navigation_question_count": len(questions),
    }
    if answerer is not None and questions:
        candidate_context = candidate_text or _heading_outline_text(headings)
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or report.reading_order_text,
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
        format="pdf",
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.75,
        findings=findings,
        metadata=metadata,
    )


class PDFHeadingNavigationTest:
    """Deterministic scaffold for the PRD heading navigation proxy."""

    test_name = "heading_navigation"
    dimension = "heading_semantics"
    format = "pdf"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        report = kwargs.get("tag_tree_report") or read_tag_tree(artifact_path)
        threshold = require_unit_interval("threshold", kwargs.get("threshold", 0.85))
        return score_heading_navigation_report(
            report,
            threshold=threshold,
            answerer=kwargs.get("answerer"),
            baseline_text=str(kwargs.get("baseline_text") or ""),
            candidate_text=str(kwargs.get("candidate_text") or ""),
        )


def _navigation_questions(report: TagTreeReport) -> list[GeneratedQuestion]:
    questions: list[GeneratedQuestion] = []
    current_heading = ""
    for node in report.nodes:
        text = " ".join((node.text or node.alt_text or "").split())
        if node.tag in _HEADING_TAGS:
            current_heading = text
            continue
        if not current_heading or len(text.split()) < 4:
            continue
        questions.append(
            GeneratedQuestion(
                question=(
                    "Which heading contains information about this content: "
                    f"{text[:120]}?"
                ),
                expected_answer=current_heading,
                source_dimension="heading_semantics",
            )
        )
        if len(questions) >= 5:
            break
    return questions


def _is_non_descriptive_heading(normalized: str) -> bool:
    return normalized in _GENERIC_HEADING_LABELS or normalized.startswith("section ")


def _heading_outline_text(headings: list) -> str:
    lines = []
    for node in headings:
        text = " ".join((node.text or node.alt_text or "").split())
        if text:
            lines.append(f"{node.tag}: {text}")
    return "\n".join(lines)
