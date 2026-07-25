"""DOCX alt-text quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._alt_text import (
    docx_alt_text_objects,
    score_alt_text_objects,
)
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXAltTextQualityJudge(OfficeHeuristicJudge):
    judge_id = "docx_alt_text_quality"
    judge_version = "alt_text_judge_v1"
    dimension = "alt_text"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "alt_text_judge_v1.md"
    rule_ids = ("docx-alt-text",)

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        ooxml_score = score_alt_text_objects(
            docx_alt_text_objects(artifact_path),
            judge_id=self.judge_id,
            judge_version=self.judge_version,
            fmt=self.format,
        )
        if ooxml_score is not None:
            return ooxml_score
        return super().judge(artifact_path, **kwargs)
