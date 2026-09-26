"""PDF decorative-image skip behavioral proxy."""

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
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


_FIGURE_TAGS = {"Figure", "Image"}


def score_decorative_skip_report(
    report: TagTreeReport,
    *,
    threshold: float = 1.0,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    """Score whether skipped decorative figures appear information-equivalent."""
    figure_nodes = [node for node in report.nodes if node.tag in _FIGURE_TAGS]
    findings: list[dict[str, Any]] = []
    if not figure_nodes:
        return BehavioralTestResult(
            test_name="decorative_skip",
            dimension="decorative",
            format="pdf",
            passed=True,
            score=1.0,
            threshold=threshold,
            confidence=1.0,
            metadata={
                "applicable": False,
                "figure_count": 0,
                "llm_answering_enabled": answerer is not None,
                "question_count": 0,
            },
        )

    safe_skips = 0
    decorative_candidates = 0
    skipped_candidate_ids: set[int] = set()
    for index, node in enumerate(figure_nodes, start=1):
        if node.alt_text.strip():
            continue
        decorative_candidates += 1
        skipped_candidate_ids.add(id(node))
        if not node.text.strip():
            safe_skips += 1
            continue
        findings.append(
            {
                "severity": "error",
                "issue": "informative_figure_skipped",
                "figure_index": index,
                "page": node.page,
                "text_preview": node.text[:120],
            }
        )

    structural_score = (
        1.0
        if decorative_candidates == 0
        else safe_skips / decorative_candidates
    )
    score = structural_score
    baseline_context = baseline_text or _decorative_baseline_context(
        report,
        skipped_candidate_ids,
    )
    candidate_context = candidate_text or _decorative_candidate_context(
        report,
        skipped_candidate_ids,
    )
    questions = generate_comprehension_questions(
        baseline_context,
        dimension="decorative",
        limit=5,
    )
    metadata: dict[str, Any] = {
        "applicable": decorative_candidates > 0,
        "figure_count": len(figure_nodes),
        "decorative_candidates": decorative_candidates,
        "llm_answering_enabled": answerer is not None,
        "question_count": len(questions),
    }
    if answerer is not None and questions:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_context,
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
        test_name="decorative_skip",
        dimension="decorative",
        format="pdf",
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.7,
        findings=findings,
        metadata=metadata,
    )


class PDFDecorativeSkipTest:
    """Deterministic scaffold for the PRD decorative skip proxy."""

    test_name = "decorative_skip"
    dimension = "decorative"
    format = "pdf"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        report = kwargs.get("tag_tree_report") or read_tag_tree(artifact_path)
        threshold = require_unit_interval("threshold", kwargs.get("threshold", 1.0))
        return score_decorative_skip_report(
            report,
            threshold=threshold,
            answerer=kwargs.get("answerer"),
            baseline_text=str(kwargs.get("baseline_text") or ""),
            candidate_text=str(kwargs.get("candidate_text") or ""),
        )


def _decorative_baseline_context(
    report: TagTreeReport,
    skipped_candidate_ids: set[int],
) -> str:
    return _join_node_text(
        node
        for node in report.nodes
        if node.has_content or id(node) in skipped_candidate_ids
    )


def _decorative_candidate_context(
    report: TagTreeReport,
    skipped_candidate_ids: set[int],
) -> str:
    return _join_node_text(
        node
        for node in report.nodes
        if node.has_content and id(node) not in skipped_candidate_ids
    )


def _join_node_text(nodes: Any) -> str:
    return "\n".join(
        normalized
        for normalized in (
            " ".join((node.text or node.alt_text or "").split())
            for node in nodes
        )
        if normalized
    )
