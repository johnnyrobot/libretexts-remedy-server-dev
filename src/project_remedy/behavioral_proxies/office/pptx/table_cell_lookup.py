"""PPTX table-cell lookup proxy over table shapes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion


@dataclass(frozen=True)
class PPTXTableSummary:
    slide_index: int
    table_index: int
    row_count: int
    column_count: int
    has_header_row: bool
    empty_header_columns: tuple[int, ...]
    rows: tuple[tuple[str, ...], ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.row_count >= 2
            and self.column_count >= 1
            and self.has_header_row
            and not self.empty_header_columns
        )


class PPTXTableCellLookupTest:
    test_name = "table_cell_lookup"
    dimension = "table_structure"
    format = "pptx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        answerer: BehavioralAnswerer | None = kwargs.get("answerer")
        tables = _pptx_table_summaries(artifact_path)
        if not tables:
            return BehavioralTestResult(
                test_name=self.test_name,
                dimension=self.dimension,
                format=self.format,
                passed=True,
                score=1.0,
                threshold=0.95,
                confidence=0.30,
                metadata={
                    "applicable": False,
                    "parser_support": "python_pptx_table_shapes",
                    "table_count": 0,
                    "llm_answering_enabled": answerer is not None,
                },
            )

        failures = [table for table in tables if not table.passed]
        structural_score = (len(tables) - len(failures)) / len(tables)
        score = structural_score
        lookup_questions = [
            question
            for table in tables
            for question in _lookup_questions(table)
        ][:5]
        candidate_context = str(kwargs.get("candidate_text") or "") or "\n\n".join(
            _serialize_table(table) for table in tables
        )
        findings = [
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
        ]
        metadata = {
            "applicable": True,
            "parser_support": "python_pptx_table_shapes",
            "table_count": len(tables),
            "llm_answering_enabled": answerer is not None,
            "lookup_question_count": len(lookup_questions),
        }
        if answerer is not None and lookup_questions:
            retention = score_answer_retention(
                questions=lookup_questions,
                baseline_context=str(kwargs.get("baseline_text") or "") or candidate_context,
                candidate_context=candidate_context,
                answerer=answerer,
            )
            score = min(structural_score, retention.retention)
            findings.extend(retention.findings)
            metadata.update(
                {
                    "baseline_accuracy": retention.baseline_accuracy,
                    "candidate_accuracy": retention.candidate_accuracy,
                    "answer_accuracy_retention": retention.retention,
                }
            )
        return BehavioralTestResult(
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=score >= 0.95,
            score=round(score, 4),
            threshold=0.95,
            confidence=0.65,
            findings=findings,
            metadata=metadata,
        )


def _pptx_table_summaries(artifact_path: Path) -> list[PPTXTableSummary]:
    if not artifact_path.exists():
        return []
    try:
        from pptx import Presentation
    except ImportError:
        return []

    try:
        presentation = Presentation(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes this proxy inapplicable.
        return []

    summaries: list[PPTXTableSummary] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        table_index = 0
        for shape in slide.shapes:
            if not getattr(shape, "has_table", False):
                continue
            table_index += 1
            table = shape.table
            row_count = len(table.rows)
            column_count = len(table.columns)
            empty_header_columns = tuple(
                column_index + 1
                for column_index in range(column_count)
                if _column_has_data(table, column_index)
                and not table.cell(0, column_index).text.strip()
            )
            summaries.append(
                PPTXTableSummary(
                    slide_index=slide_index,
                    table_index=table_index,
                    row_count=row_count,
                    column_count=column_count,
                    has_header_row=bool(getattr(table, "first_row", False)),
                    empty_header_columns=empty_header_columns,
                    rows=tuple(
                        tuple(
                            " ".join(table.cell(row_index, column_index).text.split())
                            for column_index in range(column_count)
                        )
                        for row_index in range(row_count)
                    ),
                )
            )
    return summaries


def _table_issue(table: PPTXTableSummary) -> str:
    if table.row_count < 2 or table.column_count < 1:
        return "pptx_table_too_small_for_lookup"
    if not table.has_header_row:
        return "pptx_table_missing_header_row"
    if table.empty_header_columns:
        return "pptx_table_empty_header_cells"
    return "pptx_table_cell_lookup_failed"


def _column_has_data(table: Any, column_index: int) -> bool:
    for row_index in range(1, len(table.rows)):
        if table.cell(row_index, column_index).text.strip():
            return True
    return False


def _lookup_questions(table: PPTXTableSummary) -> list[GeneratedQuestion]:
    if len(table.rows) < 2:
        return []
    headers = [cell for cell in table.rows[0] if cell]
    if not headers:
        return []
    questions: list[GeneratedQuestion] = []
    for row in table.rows[1:]:
        if len(row) < 2:
            continue
        row_label = row[0]
        if not row_label:
            continue
        for column_index, expected in enumerate(row[1:], start=1):
            if not expected:
                continue
            header = headers[column_index] if column_index < len(headers) else f"column {column_index + 1}"
            questions.append(
                GeneratedQuestion(
                    question=(
                        f"On slide {table.slide_index}, in PPTX table "
                        f"{table.table_index}, what is the value for row "
                        f"{row_label}, column {header}?"
                    ),
                    expected_answer=expected,
                    source_dimension="table_structure",
                )
            )
    return questions


def _serialize_table(table: PPTXTableSummary) -> str:
    lines = []
    for row in table.rows:
        values = [cell for cell in row if cell]
        if values:
            lines.append(" | ".join(values))
    return "\n".join(lines)
