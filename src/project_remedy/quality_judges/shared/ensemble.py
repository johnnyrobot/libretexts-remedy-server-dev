"""Format-agnostic quality judge aggregation."""

from __future__ import annotations

from pathlib import Path
from statistics import mean, pvariance
from typing import Any, Iterable

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityJudge,
    QualityResult,
    require_unit_interval,
)
from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    not_applicable_dimensions,
)


class QualityJudgeEnsemble:
    """Aggregate narrow judges into a per-dimension quality result."""

    def __init__(
        self,
        judges: Iterable[QualityJudge],
        *,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        self._judges = list(judges)
        self._thresholds = _validate_thresholds(thresholds or {})

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityResult:
        """Run judges and aggregate same-dimension scores by mean/variance."""
        by_dimension: dict[str, list[QualityDimensionScore]] = {}
        fmt = ""
        for judge in self._judges:
            score = judge.judge(artifact_path, **kwargs)
            by_dimension.setdefault(score.dimension, []).append(score)
            fmt = fmt or score.format

        dimensions: dict[str, QualityDimensionScore] = {}
        failing: list[str] = []
        for dimension, scores in by_dimension.items():
            values = [score.score for score in scores]
            threshold = self._thresholds.get(dimension, 0.80)
            aggregate = QualityDimensionScore(
                dimension=dimension,
                format=scores[0].format,
                score=round(mean(values), 4),
                variance=round(pvariance(values), 6) if len(values) > 1 else 0.0,
                per_criterion=_mean_per_criterion(scores),
                judge_versions=[
                    version
                    for score in scores
                    for version in score.judge_versions
                ],
                sample_findings=[
                    finding
                    for score in scores
                    for finding in score.sample_findings[:3]
                ][:5],
                confidence=round(mean(score.confidence for score in scores), 4),
            )
            dimensions[dimension] = aggregate
            if aggregate.score < threshold:
                failing.append(dimension)

        return QualityResult(
            format=fmt,
            dimensions=dimensions,
            behavioral={},
            overall_pass=not failing,
            failing_dimensions=failing,
            not_applicable_dimensions=list(not_applicable_dimensions(fmt)) if fmt else [],
        )


def apply_behavioral_precedence(result: QualityResult) -> QualityResult:
    """Let applicable behavioral proxy results override judge-only verdicts."""
    by_dimension: dict[str, list[BehavioralTestResult]] = {}
    for behavioral in result.behavioral.values():
        if behavioral.metadata.get("advisory_only"):
            continue
        if behavioral.metadata.get("applicable") is False:
            continue
        by_dimension.setdefault(behavioral.dimension, []).append(behavioral)

    failing = set(result.failing_dimensions)
    for dimension, tests in by_dimension.items():
        if any(not test.passed for test in tests):
            failing.add(dimension)
        elif all(test.passed for test in tests):
            failing.discard(dimension)

    result.failing_dimensions = sorted(failing)
    result.overall_pass = not result.failing_dimensions
    return result


def _mean_per_criterion(scores: list[QualityDimensionScore]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for score in scores:
        for criterion, value in score.per_criterion.items():
            values.setdefault(criterion, []).append(value)
    return {
        criterion: round(mean(items), 4)
        for criterion, items in values.items()
    }


def _validate_thresholds(thresholds: dict[str, float]) -> dict[str, float]:
    validated: dict[str, float] = {}
    for dimension, threshold in thresholds.items():
        if dimension not in ALL_QUALITY_DIMENSIONS:
            raise ValueError(f"threshold dimension unsupported: {dimension}")
        validated[dimension] = require_unit_interval(
            f"thresholds.{dimension}",
            threshold,
        )
    return validated
