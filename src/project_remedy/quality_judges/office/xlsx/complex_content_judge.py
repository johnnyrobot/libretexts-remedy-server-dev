"""XLSX complex-content description quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._complex import (
    score_complex_objects,
    xlsx_complex_objects,
)
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class XLSXComplexContentJudge(OfficeHeuristicJudge):
    judge_id = "xlsx_complex_content_quality"
    judge_version = "complex_content_judge_v1"
    dimension = "complex_content"
    format = "xlsx"
    file_type = FileType.XLSX
    prompt_name = "complex_content_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        return score_complex_objects(
            xlsx_complex_objects(artifact_path),
            judge_id=self.judge_id,
            judge_version=self.judge_version,
            fmt=self.format,
        )
