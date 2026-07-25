"""Shared Office behavioral proxy helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.models import FileType
from project_remedy.office_acceptance import OfficeCheckReport, run_office_checker


def report_for(path: Path, file_type: FileType, kwargs: dict[str, Any]) -> OfficeCheckReport:
    report = kwargs.get("checker_report")
    if isinstance(report, OfficeCheckReport):
        return report
    return run_office_checker(path, file_type)


def result_from_rules(
    report: OfficeCheckReport,
    *,
    test_name: str,
    dimension: str,
    fmt: str,
    rule_ids: tuple[str, ...],
    threshold: float = 1.0,
) -> BehavioralTestResult:
    """Score pass/fail rule-backed Office proxy tests."""
    matched = [result for result in report.results if result.rule_id in rule_ids]
    if not matched:
        return BehavioralTestResult(
            test_name=test_name,
            dimension=dimension,
            format=fmt,
            passed=True,
            score=1.0,
            threshold=threshold,
            confidence=0.30,
            metadata={"applicable": False, "rule_ids": list(rule_ids)},
        )
    passed = [result for result in matched if result.status != "Failed"]
    score = len(passed) / len(matched)
    findings = [
        {
            "severity": "error",
            "issue": "office_behavioral_rule_failed",
            "rule_id": result.rule_id,
            "description": result.description,
            "details": list(result.details),
        }
        for result in matched
        if result.status == "Failed"
    ]
    return BehavioralTestResult(
        test_name=test_name,
        dimension=dimension,
        format=fmt,
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.65,
        findings=findings,
        metadata={"applicable": True, "rule_ids": list(rule_ids)},
    )
