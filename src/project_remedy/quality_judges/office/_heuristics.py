"""Shared deterministic Office judge helpers used before calibrated LLM judging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.office_acceptance import OfficeCheckReport, run_office_checker
from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityJudgeConfig,
)


class OfficeHeuristicJudge:
    """Base class for inactive deterministic Office quality judge scaffolds."""

    judge_id = "office_heuristic"
    judge_version = "v0"
    dimension = ""
    format = ""
    file_type: FileType
    prompt_name = ""
    rule_ids: tuple[str, ...] = ()

    def __init__(self, config: QualityJudgeConfig) -> None:
        config.validate_model_separation()
        self.config = config

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        """Score one Office artifact from existing checker signals."""
        report = self._report(artifact_path, **kwargs)
        matched = (
            [result for result in report.results if result.rule_id in self.rule_ids]
            if self.rule_ids
            else []
        )
        if not matched:
            return self._score(
                score=1.0,
                per_criterion={"deterministic_rule_coverage": 0.0},
                confidence=0.30,
            )

        passed = [result for result in matched if result.status != "Failed"]
        score = len(passed) / len(matched)
        findings = [
            {
                "severity": "error",
                "issue": "office_quality_rule_failed",
                "rule_id": result.rule_id,
                "description": result.description,
                "details": list(result.details),
            }
            for result in matched
            if result.status == "Failed"
        ]
        return self._score(
            score=score,
            per_criterion={"deterministic_rule_coverage": 1.0},
            findings=findings,
            confidence=0.65,
        )

    def compare(self, artifact_a: Path, artifact_b: Path, **kwargs: Any) -> str:
        kwargs_a = dict(kwargs)
        kwargs_b = dict(kwargs)
        if "checker_report_a" in kwargs:
            kwargs_a["checker_report"] = kwargs["checker_report_a"]
        if "checker_report_b" in kwargs:
            kwargs_b["checker_report"] = kwargs["checker_report_b"]
        score_a = self.judge(artifact_a, **kwargs_a).score
        score_b = self.judge(artifact_b, **kwargs_b).score
        if abs(score_a - score_b) < 0.01:
            return "tied"
        return "A_better" if score_a > score_b else "B_better"

    def _report(self, artifact_path: Path, **kwargs: Any) -> OfficeCheckReport:
        report = kwargs.get("checker_report")
        if isinstance(report, OfficeCheckReport):
            return report
        return run_office_checker(artifact_path, self.file_type)

    def _score(
        self,
        *,
        score: float,
        per_criterion: dict[str, float],
        findings: list[dict[str, Any]] | None = None,
        confidence: float,
    ) -> QualityDimensionScore:
        return QualityDimensionScore(
            dimension=self.dimension,
            format=self.format,
            score=round(score, 4),
            variance=0.0,
            per_criterion=per_criterion,
            judge_versions=[f"{self.judge_id}:{self.judge_version}"],
            sample_findings=findings or [],
            confidence=confidence,
        )
