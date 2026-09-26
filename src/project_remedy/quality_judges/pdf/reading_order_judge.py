"""Narrow PDF reading-order quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.reading_order_comprehension import (
    score_reading_order_report,
)
from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PDFReadingOrderJudge(PDFHeuristicJudge):
    judge_id = "pdf_reading_order"
    judge_version = "reading_order_judge_v1"
    dimension = "reading_order"
    prompt_name = "reading_order_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        result = score_reading_order_report(self._report(artifact_path, **kwargs))
        return self._score(
            score=result.score,
            per_criterion={"transcript_comprehension_proxy": result.score},
            findings=result.findings,
            confidence=result.confidence,
        )
