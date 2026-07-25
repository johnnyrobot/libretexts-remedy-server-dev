"""Narrow PDF decorative classification quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.decorative_skip_test import (
    score_decorative_skip_report,
)
from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PDFDecorativeJudge(PDFHeuristicJudge):
    judge_id = "pdf_decorative"
    judge_version = "decorative_judge_v1"
    dimension = "decorative"
    prompt_name = "decorative_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        result = score_decorative_skip_report(self._report(artifact_path, **kwargs))
        return self._score(
            score=result.score,
            per_criterion={"safe_decorative_skips": result.score},
            findings=result.findings,
            confidence=result.confidence,
        )
