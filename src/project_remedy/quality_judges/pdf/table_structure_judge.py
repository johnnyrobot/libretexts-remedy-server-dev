"""Narrow PDF table structure quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.pdf.table_cell_lookup import (
    score_table_cell_lookup_report,
)
from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PDFTableStructureJudge(PDFHeuristicJudge):
    judge_id = "pdf_table_structure"
    judge_version = "table_structure_judge_v1"
    dimension = "table_structure"
    prompt_name = "table_structure_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        result = score_table_cell_lookup_report(self._report(artifact_path, **kwargs))
        return self._score(
            score=result.score,
            per_criterion={"cell_lookup_structure": result.score},
            findings=result.findings,
            confidence=result.confidence,
        )
