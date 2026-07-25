"""Shared deterministic PDF judge helpers used before calibrated LLM judging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityJudgeConfig,
)
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


class PDFHeuristicJudge:
    """Base class for inactive deterministic PDF quality judge scaffolds."""

    judge_id = "pdf_heuristic"
    judge_version = "v0"
    dimension = ""
    format = "pdf"
    prompt_name = ""

    def __init__(self, config: QualityJudgeConfig) -> None:
        config.validate_model_separation()
        self.config = config

    def _report(self, artifact_path: Path, **kwargs: Any) -> TagTreeReport:
        report = kwargs.get("tag_tree_report")
        if isinstance(report, TagTreeReport):
            return report
        return read_tag_tree(artifact_path)

    def _score(
        self,
        *,
        score: float,
        per_criterion: dict[str, float],
        findings: list[dict[str, Any]] | None = None,
        confidence: float = 0.70,
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

    def compare(self, artifact_a: Path, artifact_b: Path, **kwargs: Any) -> str:
        kwargs_a = dict(kwargs)
        kwargs_b = dict(kwargs)
        if "tag_tree_report_a" in kwargs:
            kwargs_a["tag_tree_report"] = kwargs["tag_tree_report_a"]
        if "tag_tree_report_b" in kwargs:
            kwargs_b["tag_tree_report"] = kwargs["tag_tree_report_b"]
        score_a = self.judge(artifact_a, **kwargs_a).score
        score_b = self.judge(artifact_b, **kwargs_b).score
        if abs(score_a - score_b) < 0.01:
            return "tied"
        return "A_better" if score_a > score_b else "B_better"
