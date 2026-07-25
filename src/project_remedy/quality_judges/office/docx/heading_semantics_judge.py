"""DOCX heading semantics quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office.docx.heading_navigation import (
    docx_heading_outline,
    docx_visual_heading_candidates,
    score_docx_heading_navigation,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXHeadingSemanticsJudge(OfficeHeuristicJudge):
    judge_id = "docx_heading_semantics_quality"
    judge_version = "heading_semantics_judge_v1"
    dimension = "heading_semantics"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "heading_semantics_judge_v1.md"
    rule_ids = ("docx-headings",)

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        if not artifact_path.exists():
            return super().judge(artifact_path, **kwargs)
        result = score_docx_heading_navigation(
            docx_heading_outline(artifact_path),
            visual_heading_candidates=docx_visual_heading_candidates(artifact_path),
        )
        visual_candidate_count = int(result.metadata["visual_heading_candidate_count"])
        return self._score(
            score=result.score,
            per_criterion={
                "outline_navigation": result.score,
                "visual_heading_semantics": (
                    1.0 if visual_candidate_count == 0 else 0.0
                ),
            },
            findings=result.findings,
            confidence=result.confidence,
        )
