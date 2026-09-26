"""DOCX decorative-classification quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._decorative import (
    docx_decorative_shapes,
    score_decorative_shapes,
)
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXDecorativeJudge(OfficeHeuristicJudge):
    judge_id = "docx_decorative_quality"
    judge_version = "decorative_judge_v1"
    dimension = "decorative"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "decorative_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        return score_decorative_shapes(
            docx_decorative_shapes(artifact_path),
            judge_id=self.judge_id,
            judge_version=self.judge_version,
            fmt=self.format,
        )
