"""Shared quality judge protocol, result types, and model separation checks."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any, Literal, Protocol

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
)


class ModelSeparationError(ValueError):
    """Raised when a judge model overlaps with a production remediation model."""


@dataclass(frozen=True)
class QualityJudgeConfig:
    """Runtime configuration for quality judges."""

    backend: str
    model: str
    production_models: tuple[str, ...] = ()
    base_url: str = ""

    def validate_model_separation(self) -> None:
        """Raise if the judge model overlaps with production model families."""
        assert_model_separation(self.model, self.production_models)


@dataclass
class QualityDimensionScore:
    """Per-dimension quality score returned by a judge ensemble."""

    dimension: str
    format: str
    score: float
    variance: float = 0.0
    per_criterion: dict[str, float] = field(default_factory=dict)
    judge_versions: list[str] = field(default_factory=list)
    sample_findings: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def __post_init__(self) -> None:
        """Ensure per-criterion keys are backed by versioned rubric entries."""
        if not isinstance(self.dimension, str) or not self.dimension.strip():
            raise ValueError("dimension must be a non-empty string")
        if not isinstance(self.format, str) or not self.format.strip():
            raise ValueError("format must be a non-empty string")
        if not isinstance(self.per_criterion, dict):
            raise ValueError("per_criterion must be an object")
        if any(
            not isinstance(criterion, str) or not criterion.strip()
            for criterion in self.per_criterion
        ):
            raise ValueError("per_criterion keys must be non-empty strings")
        if not isinstance(self.judge_versions, list):
            raise ValueError("judge_versions must be a list")
        if any(
            not isinstance(version, str) or not version.strip()
            for version in self.judge_versions
        ):
            raise ValueError("judge_versions entries must be non-empty strings")
        if not isinstance(self.sample_findings, list):
            raise ValueError("sample_findings must be a list")
        if any(not isinstance(finding, dict) for finding in self.sample_findings):
            raise ValueError("sample_findings entries must be objects")
        require_unit_interval("score", self.score)
        _require_non_negative_finite("variance", self.variance)
        require_unit_interval("confidence", self.confidence)
        if self.format not in DIMENSIONS_BY_FORMAT:
            raise ValueError(f"unsupported quality score format: {self.format}")
        if self.dimension not in DIMENSIONS_BY_FORMAT[self.format]:
            raise ValueError(
                f"quality score dimension {self.dimension!r} "
                f"is not applicable to {self.format}"
            )
        if not self.per_criterion or not self.dimension:
            return
        from project_remedy.quality_judges.shared.rubric_loader import (
            criterion_ids_for_dimension,
        )

        allowed = criterion_ids_for_dimension(self.dimension)
        unknown = sorted(set(self.per_criterion) - allowed)
        if unknown:
            joined = ", ".join(unknown)
            raise ValueError(
                f"{self.dimension} score uses criterion key(s) not present "
                f"in the versioned rubric: {joined}"
            )
        for criterion, value in self.per_criterion.items():
            require_unit_interval(f"per_criterion.{criterion}", value)


@dataclass
class QualityResult:
    """Aggregate quality-layer result for one artifact."""

    format: str
    dimensions: dict[str, QualityDimensionScore] = field(default_factory=dict)
    behavioral: dict[str, BehavioralTestResult] = field(default_factory=dict)
    overall_pass: bool = False
    failing_dimensions: list[str] = field(default_factory=list)
    not_applicable_dimensions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.format not in DIMENSIONS_BY_FORMAT:
            raise ValueError(f"unsupported quality result format: {self.format}")
        if not isinstance(self.overall_pass, bool):
            raise ValueError("overall_pass must be a boolean")
        if not isinstance(self.dimensions, dict):
            raise ValueError("dimensions must be an object")
        if not isinstance(self.behavioral, dict):
            raise ValueError("behavioral must be an object")
        if not isinstance(self.failing_dimensions, list):
            raise ValueError("failing_dimensions must be a list")
        if not isinstance(self.not_applicable_dimensions, list):
            raise ValueError("not_applicable_dimensions must be a list")
        applicable = set(DIMENSIONS_BY_FORMAT[self.format])
        for key, score in self.dimensions.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("dimensions keys must be non-empty strings")
            if not isinstance(score, QualityDimensionScore):
                raise ValueError("dimensions values must be QualityDimensionScore objects")
            if key != score.dimension:
                raise ValueError(
                    f"quality result dimension key {key!r} must match score "
                    f"dimension {score.dimension!r}"
                )
            if score.format != self.format:
                raise ValueError(
                    f"quality result dimension {key!r} format {score.format!r} "
                    f"must match result format {self.format!r}"
                )
        for key, result in self.behavioral.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("behavioral keys must be non-empty strings")
            if not isinstance(result, BehavioralTestResult):
                raise ValueError("behavioral values must be BehavioralTestResult objects")
            if key != result.test_name:
                raise ValueError(
                    f"quality result behavioral key {key!r} must match test "
                    f"name {result.test_name!r}"
                )
            if result.format != self.format:
                raise ValueError(
                    f"quality result behavioral test {key!r} format "
                    f"{result.format!r} must match result format {self.format!r}"
                )
        seen_failing: set[str] = set()
        for dimension in self.failing_dimensions:
            if not isinstance(dimension, str) or not dimension:
                raise ValueError("failing_dimensions entries must be non-empty strings")
            if dimension in seen_failing:
                raise ValueError(f"duplicate failing dimension: {dimension}")
            seen_failing.add(dimension)
            if dimension not in applicable:
                raise ValueError(
                    f"failing dimension {dimension!r} is not applicable to {self.format}"
                )
        seen_not_applicable: set[str] = set()
        for dimension in self.not_applicable_dimensions:
            if not isinstance(dimension, str) or not dimension:
                raise ValueError(
                    "not_applicable_dimensions entries must be non-empty strings"
                )
            if dimension in seen_not_applicable:
                raise ValueError(f"duplicate not_applicable dimension: {dimension}")
            seen_not_applicable.add(dimension)
            if dimension not in ALL_QUALITY_DIMENSIONS:
                raise ValueError(f"unknown not_applicable dimension: {dimension}")
            if dimension in applicable:
                raise ValueError(
                    f"not_applicable dimension {dimension!r} applies to {self.format}"
                )


class QualityJudge(Protocol):
    """Protocol implemented by narrow, format-specific judges."""

    judge_id: str
    judge_version: str
    dimension: str
    format: str
    config: QualityJudgeConfig

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        """Score one artifact for this judge's dimension."""

    def compare(
        self,
        artifact_a: Path,
        artifact_b: Path,
        **kwargs: Any,
    ) -> Literal["A_better", "B_better", "tied"]:
        """Pairwise comparison mode for annotated better/worse pairs."""


def model_family(model: str) -> str:
    """Return a coarse model family identifier for separation checks."""
    normalized = model.strip().lower()
    if not normalized:
        return ""
    normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.split(":", 1)[0]
    for suffix in ("-cloud", "_cloud"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def assert_model_separation(judge_model: str, production_models: tuple[str, ...]) -> None:
    """Enforce that judge and remediation models do not share a family."""
    judge = judge_model.strip()
    judge_family = model_family(judge)
    if not judge or not judge_family:
        raise ModelSeparationError("QUALITY_JUDGE_MODEL must be configured")

    for production_model in production_models:
        production = production_model.strip()
        if not production:
            continue
        if judge.lower() == production.lower():
            raise ModelSeparationError(
                "QUALITY_JUDGE_MODEL must differ from production remediation models"
            )
        if judge_family == model_family(production):
            raise ModelSeparationError(
                "QUALITY_JUDGE_MODEL must come from a different model family "
                f"than production model {production!r}"
            )


def quality_config_from_pipeline(config: Any) -> QualityJudgeConfig:
    """Build quality judge config from ``PipelineConfig`` without coupling."""
    api = config.api
    production_models = tuple(
        model
        for model in (
            getattr(api, "text_model", ""),
            getattr(api, "vision_model", ""),
            getattr(api, "escalation_model", ""),
        )
        if model
    )
    quality = QualityJudgeConfig(
        backend=getattr(api, "quality_judge_backend", "ollama"),
        model=getattr(api, "quality_judge_model", ""),
        base_url=getattr(api, "quality_judge_base_url", ""),
        production_models=production_models,
    )
    quality.validate_model_separation()
    return quality


def require_unit_interval(field_name: str, value: float) -> float:
    """Return a validated finite numeric value between 0.0 and 1.0."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return numeric


def _require_non_negative_finite(field_name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
