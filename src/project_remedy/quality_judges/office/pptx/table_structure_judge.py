"""PPTX table-structure quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office.pptx.table_cell_lookup import (
    PPTXTableSummary,
    _pptx_table_summaries,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PPTXTableStructureJudge(OfficeHeuristicJudge):
    judge_id = "pptx_table_structure_quality"
    judge_version = "table_structure_judge_v1"
    dimension = "table_structure"
    format = "pptx"
    file_type = FileType.PPTX
    prompt_name = "table_structure_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:  # noqa: ARG002
        tables = _pptx_table_summaries(artifact_path)
        if not tables:
            return self._score(
                score=1.0,
                per_criterion={"pptx_table_shape_parser_coverage": 0.0},
                confidence=0.30,
            )
        failures = [table for table in tables if not table.passed]
        score = (len(tables) - len(failures)) / len(tables)
        return self._score(
            score=score,
            per_criterion={
                "pptx_table_header_row_presence": safe_ratio(
                    sum(1 for table in tables if table.has_header_row),
                    len(tables),
                ),
                "table_header_cells_present": safe_ratio(
                    sum(1 for table in tables if not table.empty_header_columns),
                    len(tables),
                ),
            },
            findings=[
                {
                    "severity": "error",
                    "issue": _table_issue(table),
                    "slide_index": table.slide_index,
                    "table_index": table.table_index,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "has_header_row": table.has_header_row,
                    "empty_header_columns": list(table.empty_header_columns),
                }
                for table in failures
            ],
            confidence=0.65,
        )


def _table_issue(table: PPTXTableSummary) -> str:
    if table.row_count < 2 or table.column_count < 1:
        return "pptx_table_too_small_for_lookup"
    if not table.has_header_row:
        return "pptx_table_missing_header_row"
    if table.empty_header_columns:
        return "pptx_table_empty_header_cells"
    return "pptx_table_header_lookup_failed"
