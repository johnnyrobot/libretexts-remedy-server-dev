"""DOCX link-text descriptiveness quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._links import docx_links, score_office_links
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXLinkTextJudge(OfficeHeuristicJudge):
    judge_id = "docx_link_text_quality"
    judge_version = "link_text_judge_v1"
    dimension = "link_text"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "link_text_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        return score_office_links(
            docx_links(artifact_path),
            judge_id=self.judge_id,
            judge_version=self.judge_version,
            fmt=self.format,
        )
