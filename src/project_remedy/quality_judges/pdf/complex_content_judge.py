"""Narrow PDF complex content description quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore

_COMPLEX_CONTENT_TERMS = {
    "axis",
    "bar",
    "chart",
    "data",
    "diagram",
    "equation",
    "flowchart",
    "formula",
    "graph",
    "legend",
    "map",
    "matrix",
    "plot",
    "scatter",
    "timeline",
    "trend",
}


class PDFComplexContentJudge(PDFHeuristicJudge):
    judge_id = "pdf_complex_content"
    judge_version = "complex_content_judge_v1"
    dimension = "complex_content"
    prompt_name = "complex_content_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        report = self._report(artifact_path, **kwargs)
        candidates = [
            node
            for node in report.nodes
            if _is_complex_content_candidate(
                node.tag,
                node.alt_text or node.text,
            )
        ]
        if not candidates:
            return self._score(
                score=1.0,
                per_criterion={"data_level_description": 1.0},
                confidence=1.0,
            )

        descriptive = 0
        findings: list[dict[str, Any]] = []
        for index, node in enumerate(candidates, start=1):
            description = " ".join((node.alt_text or node.text).split())
            has_data_hint = any(char.isdigit() for char in description) or len(description.split()) >= 8
            if has_data_hint:
                descriptive += 1
                continue
            findings.append(
                {
                    "severity": "warning",
                    "issue": "thin_complex_content_description",
                    "content_index": index,
                    "page": node.page,
                    "description": description,
                }
            )
        score = descriptive / len(candidates)
        return self._score(
            score=score,
            per_criterion={"data_level_description": score},
            findings=findings,
            confidence=0.65,
        )


def _is_complex_content_candidate(tag: str, description: str) -> bool:
    if tag == "Formula":
        return True
    if tag not in {"Figure", "Image"}:
        return False
    tokens = {
        token.strip(".,:;()[]{}").casefold()
        for token in description.split()
    }
    return bool(tokens & _COMPLEX_CONTENT_TERMS)
