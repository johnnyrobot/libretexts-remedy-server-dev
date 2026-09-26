"""DOCX table-structure quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office.docx.table_cell_lookup import (
    docx_table_summaries,
    DOCXTableSummary,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class DOCXTableStructureJudge(OfficeHeuristicJudge):
    judge_id = "docx_table_structure_quality"
    judge_version = "table_structure_judge_v1"
    dimension = "table_structure"
    format = "docx"
    file_type = FileType.DOCX
    prompt_name = "table_structure_judge_v1.md"
    rule_ids = ("docx-table-headers",)

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        if not artifact_path.exists():
            return super().judge(artifact_path, **kwargs)

        tables = docx_table_summaries(artifact_path)
        if not tables:
            return self._score(
                score=1.0,
                per_criterion={
                    "repeated_header_rows": 0.0,
                    "non_empty_header_cells": 0.0,
                },
                confidence=0.45,
            )
        failures = [table for table in tables if not table.passed]
        score = (len(tables) - len(failures)) / len(tables)
        return self._score(
            score=score,
            per_criterion={
                "repeated_header_rows": safe_ratio(
                    sum(1 for table in tables if table.has_header_row),
                    len(tables),
                ),
                "non_empty_header_cells": safe_ratio(
                    sum(1 for table in tables if not table.empty_header_columns),
                    len(tables),
                ),
            },
            findings=[_finding(table) for table in failures],
            confidence=0.70,
        )


def _finding(table: DOCXTableSummary) -> dict[str, Any]:
    issue = "docx_table_cell_lookup_failed"
    if table.row_count < 2 or table.column_count < 1:
        issue = "docx_table_too_small_for_lookup"
    elif not table.has_header_row:
        issue = "docx_table_missing_repeated_header_row"
    elif table.empty_header_columns:
        issue = "docx_table_empty_header_cells"
    return {
        "severity": "error",
        "issue": issue,
        "table_index": table.table_index,
        "row_count": table.row_count,
        "column_count": table.column_count,
        "has_header_row": table.has_header_row,
        "empty_header_columns": list(table.empty_header_columns),
    }
