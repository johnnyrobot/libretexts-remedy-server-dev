"""XLSX chart and image alt-text quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office.xlsx.alt_text_substitution import (
    assess_xlsx_drawing_alt_text,
    _xlsx_drawing_objects,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class XLSXAltTextQualityJudge(OfficeHeuristicJudge):
    judge_id = "xlsx_alt_text_quality"
    judge_version = "alt_text_judge_v1"
    dimension = "alt_text"
    format = "xlsx"
    file_type = FileType.XLSX
    prompt_name = "alt_text_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        objects = _xlsx_drawing_objects(artifact_path)
        if not objects:
            return self._score(
                score=1.0,
                per_criterion={"xlsx_drawing_alt_text_parser_coverage": 0.0},
                confidence=0.30,
            )
        assessment = assess_xlsx_drawing_alt_text(objects)
        return self._score(
            score=assessment.score,
            per_criterion={
                "drawing_alt_text_presence": assessment.presence_score,
                "drawing_alt_text_specificity": assessment.specificity_score,
            },
            findings=list(assessment.findings),
            confidence=0.60,
        )
