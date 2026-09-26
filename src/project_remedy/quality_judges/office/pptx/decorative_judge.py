"""PPTX decorative-classification quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._decorative import (
    pptx_decorative_shapes,
    score_decorative_shapes,
)
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PPTXDecorativeJudge(OfficeHeuristicJudge):
    judge_id = "pptx_decorative_quality"
    judge_version = "decorative_judge_v1"
    dimension = "decorative"
    format = "pptx"
    file_type = FileType.PPTX
    prompt_name = "decorative_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        return score_decorative_shapes(
            pptx_decorative_shapes(artifact_path),
            judge_id=self.judge_id,
            judge_version=self.judge_version,
            fmt=self.format,
        )
