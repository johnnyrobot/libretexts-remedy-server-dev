"""PDF alt-text image-substitution behavioral proxy."""

from __future__ import annotations

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
from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)
from project_remedy.pdf_checker import _is_generic_alt_text
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


_FIGURE_TAGS = {"Figure", "Image"}


def _meaningful_alt_text(text: str) -> bool:
    stripped = " ".join(text.split())
    return len(stripped) >= 10 and not _is_generic_alt_text(stripped)


def score_alt_text_substitution_report(
    report: TagTreeReport,
    *,
    threshold: float = 0.80,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    """Score whether figure alt text can stand in for the image."""
    figures = [node for node in report.nodes if node.tag in _FIGURE_TAGS]
    findings: list[dict[str, Any]] = []
    if not figures:
        return BehavioralTestResult(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="pdf",
            passed=True,
            score=1.0,
            threshold=threshold,
            confidence=1.0,
            metadata={"applicable": False, "figure_count": 0},
        )

    meaningful = 0
    meaningful_by_text: dict[str, list[int]] = {}
    for index, node in enumerate(figures, start=1):
        if _meaningful_alt_text(node.alt_text):
            meaningful += 1
            normalized = " ".join(node.alt_text.casefold().split())
            meaningful_by_text.setdefault(normalized, []).append(index)
            continue
        findings.append(
            {
                "severity": "error",
                "issue": "non_substitutive_alt_text",
                "page": node.page,
                "figure_index": index,
                "alt_text": node.alt_text,
            }
        )

    for normalized, figure_indices in sorted(meaningful_by_text.items()):
        if len(figure_indices) < 2:
            continue
        duplicate_penalty = len(figure_indices) - 1
        meaningful -= duplicate_penalty
        findings.append(
            {
                "severity": "error",
                "issue": "duplicated_substitutive_alt_text",
                "figure_indices": figure_indices,
                "duplicate_count": len(figure_indices),
                "alt_text": normalized,
            }
        )
    heuristic_score = meaningful / len(figures)
    score = heuristic_score
    alt_context = candidate_text or "\n".join(
        node.alt_text
        for node in figures
        if node.alt_text.strip()
    )
    questions = generate_comprehension_questions(
        baseline_text or alt_context,
        dimension="alt_text",
        limit=5,
    )
    metadata: dict[str, Any] = {
        "applicable": True,
        "figure_count": len(figures),
        "llm_answering_enabled": answerer is not None,
        "question_count": len(questions),
    }
    if answerer is not None and questions:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or alt_context,
            candidate_context=alt_context,
            answerer=answerer,
        )
        score = min(heuristic_score, retention.retention)
        findings.extend(retention.findings)
        metadata.update(
            {
                "baseline_accuracy": retention.baseline_accuracy,
                "candidate_accuracy": retention.candidate_accuracy,
                "answer_accuracy_retention": retention.retention,
            }
        )
    return BehavioralTestResult(
        test_name="alt_text_substitution",
        dimension="alt_text",
        format="pdf",
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.75,
        findings=findings,
        metadata=metadata,
    )


class PDFAltTextSubstitutionTest:
    """Deterministic scaffold for the PRD alt-text substitution proxy."""

    test_name = "alt_text_substitution"
    dimension = "alt_text"
    format = "pdf"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        report = kwargs.get("tag_tree_report") or read_tag_tree(artifact_path)
        threshold = require_unit_interval("threshold", kwargs.get("threshold", 0.80))
        return score_alt_text_substitution_report(
            report,
            threshold=threshold,
            answerer=kwargs.get("answerer"),
            baseline_text=str(kwargs.get("baseline_text") or ""),
            candidate_text=str(kwargs.get("candidate_text") or ""),
        )
