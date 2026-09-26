"""XLSX sheet-organization quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.behavioral_proxies.office.xlsx.sheet_navigation import (
    XLSXSheetNavigationSignal,
    xlsx_sheet_navigation_signals,
)
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class XLSXSheetOrganizationJudge(OfficeHeuristicJudge):
    judge_id = "xlsx_sheet_organization_quality"
    judge_version = "sheet_organization_judge_v1"
    dimension = "sheet_organization"
    format = "xlsx"
    file_type = FileType.XLSX
    prompt_name = "sheet_organization_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        signals = xlsx_sheet_navigation_signals(artifact_path, kwargs)
        if not signals:
            return self._score(
                score=1.0,
                per_criterion={
                    "sheet_name_descriptiveness": 0.0,
                    "sheet_purpose_alignment": 0.0,
                    "visible_data_sheets": 0.0,
                },
                confidence=0.20,
            )
        score = sum(signal.score for signal in signals) / len(signals)
        findings = [
            {
                "severity": "warning",
                "issue": issue,
                "sheet_name": signal.sheet_name,
                "sheet_index": signal.sheet_index,
                "content_terms": list(signal.content_terms),
            }
            for signal in signals
            for issue in _signal_issues(signal)
        ]
        return self._score(
            score=score,
            per_criterion={
                "sheet_name_descriptiveness": safe_ratio(
                    sum(
                        1
                        for signal in signals
                        if "non_descriptive_sheet_name" not in _signal_issues(signal)
                    ),
                    len(signals),
                ),
                "sheet_purpose_alignment": safe_ratio(
                    sum(
                        1
                        for signal in signals
                        if not {
                            "sheet_name_purpose_unclear",
                            "overview_sheet_not_first",
                        }
                        & set(_signal_issues(signal))
                    ),
                    len(signals),
                ),
                "sheet_ordering": safe_ratio(
                    sum(
                        1
                        for signal in signals
                        if "overview_sheet_not_first" not in _signal_issues(signal)
                    ),
                    len(signals),
                ),
                "visible_data_sheets": safe_ratio(
                    sum(
                        1
                        for signal in signals
                        if "data_sheet_hidden" not in _signal_issues(signal)
                    ),
                    len(signals),
                ),
            },
            findings=findings,
            confidence=0.55,
        )


def _signal_issues(signal: XLSXSheetNavigationSignal) -> tuple[str, ...]:
    return signal.issues or ((signal.issue,) if signal.issue else ())
