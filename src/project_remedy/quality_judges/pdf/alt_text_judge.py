"""Narrow PDF alt-text quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.alt_text_substitution import (
    score_alt_text_substitution_report,
)
from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PDFAltTextQualityJudge(PDFHeuristicJudge):
    judge_id = "pdf_alt_text_quality"
    judge_version = "alt_text_judge_v1"
    dimension = "alt_text"
    prompt_name = "alt_text_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        result = score_alt_text_substitution_report(self._report(artifact_path, **kwargs))
        return self._score(
            score=result.score,
            per_criterion={"substitutive_alt_text": result.score},
            findings=result.findings,
            confidence=result.confidence,
        )
