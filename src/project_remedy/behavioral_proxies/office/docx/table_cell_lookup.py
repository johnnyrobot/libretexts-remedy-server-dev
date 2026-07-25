"""DOCX table-cell lookup proxy over Word table structures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office._checks import report_for, result_from_rules
from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion
from project_remedy.models import FileType


@dataclass(frozen=True)
class DOCXTableSummary:
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


class DOCXTableCellLookupTest:
    test_name = "table_cell_lookup"
    dimension = "table_structure"
    format = "docx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        if artifact_path.exists():
            return _result_from_table_summaries(
                docx_table_summaries(artifact_path),
                answerer=kwargs.get("answerer"),
                baseline_text=str(kwargs.get("baseline_text") or ""),
                candidate_text=str(kwargs.get("candidate_text") or ""),
            )
        return result_from_rules(
            report_for(artifact_path, FileType.DOCX, kwargs),
            test_name=self.test_name,
            dimension=self.dimension,
            fmt=self.format,
            rule_ids=("docx-table-headers",),
            threshold=0.95,
        )


def docx_table_summaries(artifact_path: Path) -> list[DOCXTableSummary]:
    """Return deterministic table-structure signals from a DOCX artifact."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return []

    try:
        document = Document(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes this proxy inapplicable.
        return []

    summaries: list[DOCXTableSummary] = []
    for table_index, table in enumerate(document.tables, start=1):
        row_count = len(table.rows)
        column_count = len(table.columns)
        has_header_row = False
        empty_header_columns: tuple[int, ...] = ()
        if row_count:
            tr_pr = table.rows[0]._tr.trPr
            has_header_row = _row_has_repeating_header(
                tr_pr,
                qn("w:tblHeader"),
                qn("w:val"),
            )
            empty_header_columns = tuple(
                column_index + 1
                for column_index in range(column_count)
                if _column_has_data(table, column_index)
                and not table.cell(0, column_index).text.strip()
            )
        summaries.append(
            DOCXTableSummary(
                table_index=table_index,
                row_count=row_count,
                column_count=column_count,
                has_header_row=has_header_row,
                empty_header_columns=empty_header_columns,
                rows=tuple(
                    tuple(" ".join(cell.text.split()) for cell in row.cells)
                    for row in table.rows
                ),
            )
        )
    return summaries


def _result_from_table_summaries(
    tables: list[DOCXTableSummary],
    *,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    if not tables:
        return BehavioralTestResult(
            test_name="table_cell_lookup",
            dimension="table_structure",
            format="docx",
            passed=True,
            score=1.0,
            threshold=0.95,
            confidence=0.45,
            metadata={
                "applicable": False,
                "parser_support": "python_docx_tables",
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
    candidate_context = candidate_text or "\n\n".join(_serialize_table(table) for table in tables)
    findings = [
        {
            "severity": "error",
            "issue": _table_issue(table),
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
        "parser_support": "python_docx_tables",
        "table_count": len(tables),
        "llm_answering_enabled": answerer is not None,
        "lookup_question_count": len(lookup_questions),
    }
    if answerer is not None and lookup_questions:
        retention = score_answer_retention(
            questions=lookup_questions,
            baseline_context=baseline_text or candidate_context,
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
        test_name="table_cell_lookup",
        dimension="table_structure",
        format="docx",
        passed=score >= 0.95,
        score=round(score, 4),
        threshold=0.95,
        confidence=0.70,
        findings=findings,
        metadata=metadata,
    )


def _table_issue(table: DOCXTableSummary) -> str:
    if table.row_count < 2 or table.column_count < 1:
        return "docx_table_too_small_for_lookup"
    if not table.has_header_row:
        return "docx_table_missing_repeated_header_row"
    if table.empty_header_columns:
        return "docx_table_empty_header_cells"
    return "docx_table_cell_lookup_failed"


def _row_has_repeating_header(tr_pr: Any, header_tag: str, val_attr: str) -> bool:
    if tr_pr is None:
        return False
    tbl_header = tr_pr.find(header_tag)
    if tbl_header is None:
        return False
    value = tbl_header.get(val_attr)
    if value is None:
        return True
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def _column_has_data(table: Any, column_index: int) -> bool:
    for row_index in range(1, len(table.rows)):
        if table.cell(row_index, column_index).text.strip():
            return True
    return False


def _lookup_questions(table: DOCXTableSummary) -> list[GeneratedQuestion]:
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
                        f"In DOCX table {table.table_index}, what is the value "
                        f"for row {row_label}, column {header}?"
                    ),
                    expected_answer=expected,
                    source_dimension="table_structure",
                )
            )
    return questions


def _serialize_table(table: DOCXTableSummary) -> str:
    lines = []
    for row in table.rows:
        values = [cell for cell in row if cell]
        if values:
            lines.append(" | ".join(values))
    return "\n".join(lines)
