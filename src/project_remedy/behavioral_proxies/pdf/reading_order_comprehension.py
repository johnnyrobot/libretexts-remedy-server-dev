"""PDF reading-order comprehension behavioral proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.transcript_analyzer import analyze_tag_tree_report
from project_remedy.behavioral_proxies.shared.base import (
    BehavioralTestResult,
    require_unit_interval,
)
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


def score_reading_order_report(
    report: TagTreeReport,
    *,
    threshold: float = 0.90,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
) -> BehavioralTestResult:
    """Score whether the serialized reading order is usable for comprehension."""
    findings = analyze_tag_tree_report(report)
    transcript = report.reading_order_text
    question_source = baseline_text or transcript
    questions = generate_comprehension_questions(
        question_source,
        dimension="reading_order",
        limit=5,
    )
    error_count = sum(1 for finding in findings if finding.get("severity") == "error")
    warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
    if not questions:
        score = 0.0
        findings.append(
            {
                "severity": "error",
                "issue": "insufficient_comprehension_material",
                "message": "Transcript did not contain enough text to generate questions.",
            }
        )
    elif answerer is not None:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or transcript,
            candidate_context=transcript,
            answerer=answerer,
        )
        score = retention.retention
        findings.extend(retention.findings)
    else:
        score = max(0.0, 1.0 - (error_count * 0.5) - (warning_count * 0.1))
    metadata = {
        "question_count": len(questions),
        "llm_answering_enabled": answerer is not None,
    }
    if answerer is not None and questions:
        metadata.update(
            {
                "baseline_accuracy": retention.baseline_accuracy,
                "candidate_accuracy": retention.candidate_accuracy,
                "answer_accuracy_retention": retention.retention,
            }
        )
    return BehavioralTestResult(
        test_name="reading_order_comprehension",
        dimension="reading_order",
        format="pdf",
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.65,
        findings=findings,
        metadata=metadata,
    )


class PDFReadingOrderComprehensionTest:
    """Deterministic scaffold for the PRD reading-order comprehension proxy."""

    test_name = "reading_order_comprehension"
    dimension = "reading_order"
    format = "pdf"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        report = kwargs.get("tag_tree_report") or read_tag_tree(artifact_path)
        threshold = require_unit_interval("threshold", kwargs.get("threshold", 0.90))
        return score_reading_order_report(
            report,
            threshold=threshold,
            answerer=kwargs.get("answerer"),
            baseline_text=str(kwargs.get("baseline_text") or ""),
        )
