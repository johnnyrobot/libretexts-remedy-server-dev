"""DOCX partial reading-order comprehension proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)


class DOCXReadingOrderComprehensionTest:
    test_name = "reading_order_comprehension"
    dimension = "reading_order"
    format = "docx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        answerer: BehavioralAnswerer | None = kwargs.get("answerer")
        if answerer is not None:
            return _run_answer_retention(
                artifact_path,
                answerer=answerer,
                baseline_text=str(kwargs.get("baseline_text") or ""),
                candidate_text=str(kwargs.get("candidate_text") or ""),
            )
        return BehavioralTestResult(
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=True,
            score=1.0,
            threshold=0.90,
            confidence=0.25,
            findings=[
                {
                    "severity": "info",
                    "issue": "partial_docx_reading_order_signal",
                    "message": "DOCX reading order is treated as mostly linear pending calibrated parser checks.",
                }
            ],
            metadata={
                "applicable": True,
                "partial": True,
                "llm_answering_enabled": False,
                "parser_support": "linear_docx_scaffold",
            },
        )


def _run_answer_retention(
    artifact_path: Path,
    *,
    answerer: BehavioralAnswerer,
    baseline_text: str,
    candidate_text: str,
) -> BehavioralTestResult:
    candidate_context = candidate_text or _docx_linear_text(artifact_path)
    baseline_context = baseline_text or candidate_context
    questions = generate_comprehension_questions(
        baseline_context or candidate_context,
        dimension="reading_order",
        limit=5,
    )
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "issue": "partial_docx_reading_order_signal",
            "message": "DOCX reading order uses linear Word paragraph/table text for answer retention.",
        }
    ]
    if not questions:
        findings.append(
            {
                "severity": "error",
                "issue": "insufficient_comprehension_material",
                "message": "DOCX text did not contain enough content to generate questions.",
            }
        )
        score = 0.0
        metadata = {
            "baseline_accuracy": 0.0,
            "candidate_accuracy": 0.0,
            "answer_accuracy_retention": 0.0,
        }
    else:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_context,
            candidate_context=candidate_context,
            answerer=answerer,
        )
        findings.extend(retention.findings)
        score = retention.retention
        metadata = {
            "baseline_accuracy": retention.baseline_accuracy,
            "candidate_accuracy": retention.candidate_accuracy,
            "answer_accuracy_retention": retention.retention,
        }
    return BehavioralTestResult(
        test_name=DOCXReadingOrderComprehensionTest.test_name,
        dimension=DOCXReadingOrderComprehensionTest.dimension,
        format=DOCXReadingOrderComprehensionTest.format,
        passed=score >= 0.90,
        score=round(score, 4),
        threshold=0.90,
        confidence=0.50,
        findings=findings,
        metadata={
            "applicable": True,
            "partial": True,
            "llm_answering_enabled": True,
            "parser_support": "python_docx_linear_text",
            "question_count": len(questions),
            **metadata,
        },
    )


def _docx_linear_text(artifact_path: Path) -> str:
    if not artifact_path.exists():
        return ""
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        document = Document(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed DOCX yields no proxy text.
        return ""

    parts = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ]
    for table in document.tables:
        for row in table.rows:
            cells = [
                " ".join(cell.text.split())
                for cell in row.cells
                if cell.text.strip()
            ]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)
