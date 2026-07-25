"""DOCX partial reading-order coherence quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXReadingOrderJudge(OfficeHeuristicJudge):
    judge_id = "docx_reading_order_quality"
    judge_version = "reading_order_judge_v1"
    dimension = "reading_order"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "reading_order_judge_v1.md"
    rule_ids = ()

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        """Represent DOCX's mostly-linear reading order as a partial signal."""
        return self._score(
            score=1.0,
            per_criterion={"linear_document_order_proxy": 0.5},
            findings=[
                {
                    "severity": "info",
                    "issue": "partial_docx_reading_order_signal",
                    "message": "DOCX reading order is treated as a mostly linear partial signal in v1.",
                }
            ],
            confidence=0.25,
        )
