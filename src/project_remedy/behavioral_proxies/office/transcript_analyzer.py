"""Best-effort Office screen-reader transcript analysis proxies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.transcript_analysis import (
    analyze_transcript_text,
)
from project_remedy.models import FileType
from project_remedy.office_acceptance import (
    OfficeScreenReaderResult,
    run_office_screen_reader_checks,
)


class OfficeScreenReaderTranscriptAnalyzer:
    """Advisory Office transcript analyzer backed by existing screen-reader checks."""

    test_name = "screen_reader_transcript_analysis"
    dimension = "reading_order"
    format = ""
    file_type: FileType

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        screen_reader_result = _screen_reader_result(artifact_path, self.file_type, kwargs)
        findings = [
            {
                "severity": issue.severity,
                "issue": "office_screen_reader_issue",
                "rule_id": issue.rule_id,
                "element": issue.element,
                "description": issue.description,
                "suggestion": issue.suggestion,
            }
            for issue in screen_reader_result.issues
        ]
        transcript_text = kwargs.get("transcript_text")
        if isinstance(transcript_text, str):
            findings.extend(
                analyze_transcript_text(
                    transcript_text,
                    source=f"{self.format}_provided_screen_reader_transcript",
                )
            )
        errors = [finding for finding in findings if finding["severity"] == "error"]
        return BehavioralTestResult(
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=not errors,
            score=0.0 if errors else 1.0,
            threshold=1.0,
            confidence=0.50,
            findings=findings,
            metadata={
                "advisory_only": True,
                "parser_support": "office_acceptance_screen_reader_checks",
                "issue_count": len(findings),
                "error_count": len(errors),
                "transcript_sources": [
                    "office_acceptance_screen_reader_checks",
                    *(
                        [f"{self.format}_provided_screen_reader_transcript"]
                        if isinstance(transcript_text, str)
                        else []
                    ),
                ],
            },
        )


class DOCXScreenReaderTranscriptAnalyzer(OfficeScreenReaderTranscriptAnalyzer):
    format = "docx"
    file_type = FileType.DOCX
    dimension = "reading_order"


class PPTXScreenReaderTranscriptAnalyzer(OfficeScreenReaderTranscriptAnalyzer):
    format = "pptx"
    file_type = FileType.PPTX
    dimension = "reading_order"


class XLSXScreenReaderTranscriptAnalyzer(OfficeScreenReaderTranscriptAnalyzer):
    format = "xlsx"
    file_type = FileType.XLSX
    dimension = "sheet_organization"


def _screen_reader_result(
    artifact_path: Path,
    file_type: FileType,
    kwargs: dict[str, Any],
) -> OfficeScreenReaderResult:
    result = kwargs.get("screen_reader_result")
    if isinstance(result, OfficeScreenReaderResult):
        return result
    return run_office_screen_reader_checks(artifact_path, file_type)
