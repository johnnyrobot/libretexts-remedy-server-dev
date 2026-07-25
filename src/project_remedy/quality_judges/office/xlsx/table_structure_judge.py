"""XLSX table-structure quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office.xlsx.table_cell_lookup import (
    xlsx_table_structure_signals,
)
from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class XLSXTableStructureJudge(OfficeHeuristicJudge):
    judge_id = "xlsx_table_structure_quality"
    judge_version = "table_structure_judge_v1"
    dimension = "table_structure"
    format = "xlsx"
    file_type = FileType.XLSX
    prompt_name = "table_structure_judge_v1.md"
    rule_ids = ("xlsx-header-behaviors",)

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        if not artifact_path.exists():
            return super().judge(artifact_path, **kwargs)

        signals = xlsx_table_structure_signals(artifact_path)
        if not signals:
            return self._score(
                score=1.0,
                per_criterion={
                    "excel_table_presence": 0.0,
                    "header_row_presence": 0.0,
                    "banded_rows": 0.0,
                    "total_row_presence": 0.0,
                },
                confidence=0.45,
            )

        score = sum(signal.score for signal in signals) / len(signals)
        tables = [signal for signal in signals if signal.has_excel_table]
        return self._score(
            score=score,
            per_criterion={
                "excel_table_presence": safe_ratio(
                    sum(1 for signal in signals if signal.has_excel_table),
                    len(signals),
                ),
                "header_row_presence": safe_ratio(
                    sum(1 for signal in tables if signal.has_header_row and not signal.empty_header_columns),
                    len(tables),
                ),
                "banded_rows": safe_ratio(
                    sum(1 for signal in tables if signal.has_banded_rows),
                    len(tables),
                ),
                "total_row_presence": safe_ratio(
                    sum(1 for signal in tables if signal.has_total_row),
                    len(tables),
                ),
            },
            findings=[
                {
                    "severity": "warning" if signal.passed else "error",
                    "issue": signal.issue,
                    "sheet_name": signal.sheet_name,
                    "table_name": signal.table_name,
                    "ref": signal.ref,
                    "empty_header_columns": list(signal.empty_header_columns),
                }
                for signal in signals
                if signal.issue
            ],
            confidence=0.70,
        )
