"""Narrow PDF heading semantics quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.heading_navigation import (
    score_heading_navigation_report,
)
from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PDFHeadingSemanticsJudge(PDFHeuristicJudge):
    judge_id = "pdf_heading_semantics"
    judge_version = "heading_semantics_judge_v1"
    dimension = "heading_semantics"
    prompt_name = "heading_semantics_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        result = score_heading_navigation_report(self._report(artifact_path, **kwargs))
        heading_count = int(result.metadata.get("heading_count", 0))
        non_descriptive_count = int(result.metadata.get("non_descriptive_heading_count", 0))
        duplicate_count = int(result.metadata.get("duplicate_heading_count", 0))
        return self._score(
            score=result.score,
            per_criterion={
                "outline_navigation": result.score,
                "heading_label_descriptiveness": safe_ratio(
                    heading_count - non_descriptive_count,
                    heading_count,
                ),
                "heading_label_uniqueness": safe_ratio(
                    heading_count - duplicate_count,
                    heading_count,
                ),
            },
            findings=result.findings,
            confidence=result.confidence,
        )
