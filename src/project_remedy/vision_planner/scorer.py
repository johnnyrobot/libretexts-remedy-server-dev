"""Scorer: evaluate harness variants against held-out document sets.

Computes aggregate metrics from experiment records and determines
whether a variant should be promoted or retired.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from project_remedy.quality_judges.shared.dimensions import (
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)
from project_remedy.vision_planner.experiment_store import (
    ExperimentRecord,
    ExperimentStore,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


@dataclass
class ScoringResult:
    """Aggregate scoring result for a harness variant."""

    harness_id: str
    conformance_rate: float
    manual_review_rate: float
    destructive_edit_count: int
    avg_seconds: float
    total_docs: int
    passed_docs: int
    improvement_over_baseline: float | None = None  # delta vs baseline
    on_pareto_frontier: bool = False


@dataclass
class DimensionMetrics:
    """Per-format, per-dimension quality metrics for a harness variant."""

    dimension: str
    format: str
    quality_score: float
    behavioral_pass_rate: float
    judge_human_agreement: float
    sample_size: int
    regression_from_baseline: float


@dataclass
class ScoringResultV2(ScoringResult):
    """Additive scoring result with per-dimension quality metrics."""

    per_dimension: dict[str, DimensionMetrics] = field(default_factory=dict)
    document_class_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    format_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


def compute_metrics_from_experiments(
    experiments: list[ExperimentRecord],
) -> dict[str, Any]:
    """Compute aggregate metrics from a list of experiment records.

    Returns dict matching the scorer.py format in meta-harness-remedy:
    conformance_rate, manual_review_rate, destructive_edit_count,
    avg_seconds, total_docs, passed_docs.
    """
    if not experiments:
        return {
            "conformance_rate": 0.0,
            "manual_review_rate": 0.0,
            "destructive_edit_count": 0,
            "avg_seconds": 0.0,
            "total_docs": 0,
            "passed_docs": 0,
        }

    total = len(experiments)
    passed = sum(1 for e in experiments if e.passed)

    # Count manual_review operations vs total operations
    total_ops = 0
    manual_ops = 0
    for exp in experiments:
        for op in exp.fix_sequence:
            total_ops += 1
            if op.get("action") == "mark_manual_review":
                manual_ops += 1

    # Destructive edits: docs where violations increased
    destructive = sum(
        1 for e in experiments if e.violations_after > e.violations_before
    )

    # Average time
    times = [e.elapsed_seconds for e in experiments if e.elapsed_seconds > 0]
    avg_seconds = sum(times) / len(times) if times else 0.0

    return {
        "conformance_rate": passed / total,
        "manual_review_rate": manual_ops / total_ops if total_ops > 0 else 0.0,
        "destructive_edit_count": destructive,
        "avg_seconds": round(avg_seconds, 1),
        "total_docs": total,
        "passed_docs": passed,
    }


def compute_dimension_metrics_from_experiments(
    experiments: list[ExperimentRecord],
    *,
    fmt: str = "pdf",
) -> dict[str, DimensionMetrics]:
    """Compute additive per-dimension metrics from experiment records."""
    fmt = _require_metrics_format(fmt)
    applicable_dimensions = set(DIMENSIONS_BY_FORMAT[fmt])
    quality_values: dict[str, list[float]] = {}
    behavioral_counts: dict[str, list[bool]] = {}
    for exp in experiments:
        if exp.document_format != fmt:
            raise ValueError(
                "experiment "
                f"{exp.experiment_id or exp.document_hash or '<unknown>'} "
                f"format {exp.document_format!r} does not match metrics format {fmt!r}"
            )
        for dimension, score in exp.quality_dimensions.items():
            _validate_metric_dimension(
                dimension,
                fmt=fmt,
                applicable_dimensions=applicable_dimensions,
                label="quality_dimensions",
            )
            quality_values.setdefault(dimension, []).append(
                _coerce_metric_score(score, label=f"quality_dimensions.{dimension}")
            )
        for test_name, passed in exp.behavioral_results.items():
            dimension = dimension_from_behavioral_test(test_name)
            _validate_metric_dimension(
                dimension,
                fmt=fmt,
                applicable_dimensions=applicable_dimensions,
                label=f"behavioral_results.{test_name}",
            )
            if not isinstance(passed, bool):
                raise ValueError(
                    f"behavioral_results.{test_name} must be a boolean"
                )
            behavioral_counts.setdefault(dimension, []).append(passed)

    metrics: dict[str, DimensionMetrics] = {}
    for dimension in sorted(set(quality_values) | set(behavioral_counts)):
        values = quality_values.get(dimension, [])
        behavioral = behavioral_counts.get(dimension, [])
        pass_rate = (
            sum(1 for item in behavioral if item) / len(behavioral)
            if behavioral
            else 0.0
        )
        quality_score = sum(values) / len(values) if values else 0.0
        metrics[dimension] = DimensionMetrics(
            dimension=dimension,
            format=fmt,
            quality_score=round(quality_score, 4),
            behavioral_pass_rate=round(pass_rate, 4),
            judge_human_agreement=0.0,
            sample_size=max(len(values), len(behavioral)),
            regression_from_baseline=0.0,
        )
    return metrics


def compute_dimension_metrics_by_format(
    experiments: list[ExperimentRecord],
) -> dict[str, DimensionMetrics]:
    """Compute metrics grouped by each experiment record's document format."""
    grouped: dict[str, list[ExperimentRecord]] = {}
    for experiment in experiments:
        fmt = _require_metrics_format(experiment.document_format)
        grouped.setdefault(fmt, []).append(experiment)

    multi_format = len(grouped) > 1
    combined: dict[str, DimensionMetrics] = {}
    for fmt, records in sorted(grouped.items()):
        metrics = compute_dimension_metrics_from_experiments(records, fmt=fmt)
        for dimension, metric in metrics.items():
            key = f"{fmt}:{dimension}" if multi_format else dimension
            combined[key] = metric
    return combined


def _format_breakdown_from_dimension_metrics(
    metrics: dict[str, DimensionMetrics],
) -> dict[str, dict[str, float]]:
    breakdown: dict[str, dict[str, float]] = {}
    for metric in metrics.values():
        breakdown.setdefault(metric.format, {})[metric.dimension] = metric.quality_score
    return breakdown


def compute_document_class_breakdown(
    experiments: list[ExperimentRecord],
) -> dict[str, dict[str, float]]:
    """Return mean quality score by document class and dimension."""
    grouped: dict[str, dict[str, list[float]]] = {}
    for exp in experiments:
        if not exp.document_type:
            continue
        fmt = _require_metrics_format(exp.document_format)
        applicable_dimensions = set(DIMENSIONS_BY_FORMAT[fmt])
        for dimension, score in exp.quality_dimensions.items():
            _validate_metric_dimension(
                dimension,
                fmt=fmt,
                applicable_dimensions=applicable_dimensions,
                label="quality_dimensions",
            )
            grouped.setdefault(exp.document_type, {}).setdefault(dimension, []).append(
                _coerce_metric_score(score, label=f"quality_dimensions.{dimension}")
            )
    return {
        doc_type: {
            dimension: round(sum(values) / len(values), 4)
            for dimension, values in dimensions.items()
            if values
        }
        for doc_type, dimensions in grouped.items()
    }


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class HarnessScorer:
    """Score harness variants and update the experiment store metrics.

    Computes metrics from experiment records, updates the variant's
    stored metrics, and determines Pareto frontier membership.
    """

    def __init__(
        self,
        store: ExperimentStore,
        baseline_harness_id: str = "h000_baseline",
        min_docs_for_scoring: int = 5,
    ):
        self._store = store
        self._baseline_id = baseline_harness_id
        self._min_docs = min_docs_for_scoring

    def score_variant(self, harness_id: str) -> ScoringResultV2 | None:
        """Score a harness variant based on its experiment records.

        Returns None if insufficient data (fewer than min_docs experiments).
        Updates the variant's metrics in the store.
        """
        experiments = self._store.get_experiments_for_harness(harness_id)

        if len(experiments) < self._min_docs:
            logger.info(
                "Skipping scoring for %s: only %d/%d docs evaluated",
                harness_id, len(experiments), self._min_docs,
            )
            return None

        metrics = compute_metrics_from_experiments(experiments)
        per_dimension = compute_dimension_metrics_by_format(experiments)
        doc_class_breakdown = compute_document_class_breakdown(experiments)
        format_breakdown = _format_breakdown_from_dimension_metrics(per_dimension)

        # Update the variant's stored metrics
        self._store.update_variant_metrics(
            harness_id=harness_id,
            conformance_rate=metrics["conformance_rate"],
            manual_review_rate=metrics["manual_review_rate"],
            destructive_edit_count=metrics["destructive_edit_count"],
            avg_seconds=metrics["avg_seconds"],
            total_docs=metrics["total_docs"],
            passed_docs=metrics["passed_docs"],
        )

        # Compare against baseline
        improvement = None
        baseline = self._store.get_variant(self._baseline_id)
        if baseline and baseline.total_docs > 0:
            improvement = metrics["conformance_rate"] - baseline.conformance_rate

        # Update Pareto frontier
        frontier = self._store.update_pareto_frontier()
        on_frontier = any(f["harness_id"] == harness_id for f in frontier)

        result = ScoringResultV2(
            harness_id=harness_id,
            conformance_rate=metrics["conformance_rate"],
            manual_review_rate=metrics["manual_review_rate"],
            destructive_edit_count=metrics["destructive_edit_count"],
            avg_seconds=metrics["avg_seconds"],
            total_docs=metrics["total_docs"],
            passed_docs=metrics["passed_docs"],
            improvement_over_baseline=improvement,
            on_pareto_frontier=on_frontier,
            per_dimension=per_dimension,
            document_class_breakdown=doc_class_breakdown,
            format_breakdown=format_breakdown,
        )

        logger.info(
            "Scored %s: conformance=%.1f%% (%d/%d), improvement=%s, frontier=%s",
            harness_id,
            result.conformance_rate * 100,
            result.passed_docs,
            result.total_docs,
            f"{improvement:+.1f}pp" if improvement is not None else "N/A",
            "YES" if on_frontier else "no",
        )

        return result

    def compare_variants(
        self, harness_a: str, harness_b: str
    ) -> dict[str, Any]:
        """Compare two harness variants head-to-head.

        Returns comparison dict with per-metric deltas and a recommendation.
        """
        variant_a = self._store.get_variant(harness_a)
        variant_b = self._store.get_variant(harness_b)

        if variant_a is None or variant_b is None:
            return {"error": "One or both variants not found"}

        deltas = {
            "conformance_rate": variant_a.conformance_rate - variant_b.conformance_rate,
            "manual_review_rate": variant_a.manual_review_rate - variant_b.manual_review_rate,
            "destructive_edit_count": variant_a.destructive_edit_count - variant_b.destructive_edit_count,
            "avg_seconds": variant_a.avg_seconds - variant_b.avg_seconds,
        }

        # Determine winner: higher conformance is primary metric
        if deltas["conformance_rate"] > 0.01:
            recommendation = f"{harness_a} is better (higher conformance)"
        elif deltas["conformance_rate"] < -0.01:
            recommendation = f"{harness_b} is better (higher conformance)"
        elif deltas["destructive_edit_count"] < 0:
            recommendation = f"{harness_a} is better (fewer destructive edits)"
        elif deltas["destructive_edit_count"] > 0:
            recommendation = f"{harness_b} is better (fewer destructive edits)"
        elif deltas["avg_seconds"] < -5:
            recommendation = f"{harness_a} is better (faster)"
        elif deltas["avg_seconds"] > 5:
            recommendation = f"{harness_b} is better (faster)"
        else:
            recommendation = "No significant difference"

        return {
            "variant_a": harness_a,
            "variant_b": harness_b,
            "deltas": deltas,
            "recommendation": recommendation,
        }

    def rank_variants(
        self,
        status: str | None = None,
        metric: str = "conformance_rate",
        limit: int = 10,
    ) -> list[dict]:
        """Rank variants by a specific metric.

        Args:
            status: Filter by variant status (active/retired/promoted) or None for all.
            metric: Which metric to sort by.
            limit: Max variants to return.

        Returns list of dicts with harness_id and metric values.
        """
        variants = self._store.list_variants(status=status)

        # Only include variants with experiments
        scored = [v for v in variants if v.total_docs > 0]

        # Sort by metric (higher is better for conformance, lower for others)
        reverse = metric in ("conformance_rate",)
        scored.sort(key=lambda v: getattr(v, metric, 0), reverse=reverse)

        return [
            {
                "harness_id": v.harness_id,
                "conformance_rate": v.conformance_rate,
                "manual_review_rate": v.manual_review_rate,
                "destructive_edit_count": v.destructive_edit_count,
                "avg_seconds": v.avg_seconds,
                "total_docs": v.total_docs,
                "passed_docs": v.passed_docs,
                "status": v.status,
            }
            for v in scored[:limit]
        ]


def _require_metrics_format(fmt: str) -> str:
    if not isinstance(fmt, str) or not fmt.strip():
        raise ValueError("fmt must be a non-empty string")
    if fmt != fmt.strip().lower():
        raise ValueError("fmt must be canonical")
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"unsupported metrics format: {fmt}")
    return fmt


def _validate_metric_dimension(
    dimension: str,
    *,
    fmt: str,
    applicable_dimensions: set[str],
    label: str,
) -> None:
    if not isinstance(dimension, str) or not dimension.strip():
        raise ValueError(f"{label} dimension must be a non-empty string")
    if dimension != dimension.strip():
        raise ValueError(f"{label} dimension must be canonical")
    if dimension not in applicable_dimensions:
        raise ValueError(
            f"{label} dimension {dimension!r} is not applicable to {fmt}"
        )


def _coerce_metric_score(score: Any, *, label: str) -> float:
    if isinstance(score, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        numeric = float(score)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{label} must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{label} must be between 0.0 and 1.0")
    return numeric
