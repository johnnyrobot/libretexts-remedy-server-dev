"""Held-out quality evaluation helpers for dimension-aware strategies."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
)


PRD_MIN_TARGET_LIFT = 0.05
PRD_MAX_OTHER_REGRESSION = 0.02
PRD_REQUIRED_CONTROLLED_AB_RUNS = 3
QUALITY_DIMENSION_SET = set(ALL_QUALITY_DIMENSIONS)
SUPPORTED_FORMATS = set(DIMENSIONS_BY_FORMAT)


@dataclass(frozen=True)
class CorpusSplit:
    """Deterministic proposal/holdout split for annotated corpus records."""

    proposal_set: list[dict[str, Any]]
    holdout_set: list[dict[str, Any]]


@dataclass(frozen=True)
class PromotionDecision:
    """Promotion decision for one dimension-aware strategy evaluation."""

    strategy_name: str
    target_dimension: str
    target_lift: float
    regressions: dict[str, float] = field(default_factory=dict)
    promoted: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HoldoutABEvaluation:
    """Aggregated held-out A/B result for one dimension-aware strategy."""

    strategy_name: str
    target_dimension: str
    run_id: str
    evaluated_doc_ids: list[str]
    source_hashes: dict[str, str]
    baseline_scores: dict[str, float]
    candidate_scores: dict[str, float]
    decision: PromotionDecision
    formats: dict[str, str] = field(default_factory=dict)

    @property
    def sample_size(self) -> int:
        return len(self.evaluated_doc_ids)


@dataclass(frozen=True)
class ControlledABSuccess:
    """Series-level Phase G success decision for controlled A/B evidence."""

    strategy_name: str
    target_dimension: str
    required_experiments: int
    total_experiments: int
    successful_experiments: int
    passed: bool = False
    reason: str = ""
    regressions: dict[str, dict[str, float]] = field(default_factory=dict)


def _require_unit_interval(
    name: str,
    value: float,
    *,
    exclusive: bool = False,
) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    if exclusive:
        if numeric <= 0.0 or numeric >= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
    elif numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return numeric


def _require_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_score_delta(name: str, value: float) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    if numeric < -1.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between -1 and 1")
    return numeric


def deterministic_corpus_split(
    records: Iterable[Mapping[str, Any]],
    *,
    holdout_ratio: float = 0.2,
    salt: str = "quality-layer-v1",
) -> CorpusSplit:
    """Split records into proposal and holdout sets using stable hashes."""
    holdout_ratio = _require_unit_interval(
        "holdout_ratio",
        holdout_ratio,
        exclusive=True,
    )
    salt = _require_non_empty_string("salt", salt)

    proposal: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    scored: list[tuple[float, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    seen_source_hashes: dict[str, str] = {}
    split_items = _materialize_mapping_records(
        records,
        collection_label="split records",
        item_label="split record",
    )
    for index, item in enumerate(split_items, 1):
        doc_id = _record_id(item).strip()
        if not doc_id:
            raise ValueError(
                "split record "
                f"{index} missing doc_id, document_hash, or source_path"
            )
        if doc_id in seen_ids:
            raise ValueError(f"duplicate corpus split document: {doc_id}")
        seen_ids.add(doc_id)

        source_sha = _source_sha256(item, label=f"split record for {doc_id}")
        if not source_sha:
            raise ValueError(f"split record for {doc_id} missing source_sha256")
        _validate_sha256(source_sha, label=f"split record for {doc_id}")
        existing_doc_id = seen_source_hashes.get(source_sha)
        if existing_doc_id is not None:
            raise ValueError(
                "duplicate corpus split source artifact: "
                f"{doc_id} and {existing_doc_id}"
            )
        seen_source_hashes[source_sha] = doc_id

        score = _stable_unit_interval(f"{salt}:{source_sha}")
        scored.append((score, item))
        if score < holdout_ratio:
            holdout.append(item)
        else:
            proposal.append(item)

    if len(scored) < 2:
        raise ValueError("corpus split requires at least two records")

    # Keep tiny synthetic sets useful in tests while remaining deterministic.
    if len(scored) > 1 and not holdout:
        selected = min(range(len(scored)), key=lambda idx: scored[idx][0])
        holdout.append(scored[selected][1])
        proposal = [
            record
            for index, (_score, record) in enumerate(scored)
            if index != selected
        ]
    if len(scored) > 1 and not proposal:
        selected = max(range(len(scored)), key=lambda idx: scored[idx][0])
        proposal.append(scored[selected][1])
        holdout = [
            record
            for index, (_score, record) in enumerate(scored)
            if index != selected
        ]

    return CorpusSplit(proposal_set=proposal, holdout_set=holdout)


def evaluate_holdout_ab(
    *,
    strategy_name: str,
    target_dimension: str,
    run_id: str | None = None,
    holdout_records: Iterable[Mapping[str, Any]],
    baseline_results: Iterable[Mapping[str, Any]],
    candidate_results: Iterable[Mapping[str, Any]],
    min_target_lift: float = 0.05,
    max_other_regression: float = 0.02,
) -> HoldoutABEvaluation:
    """Aggregate complete holdout document scores and apply promotion criteria."""
    strategy_name = _require_non_empty_string("strategy_name", strategy_name)
    target_dimension = _require_quality_dimension(
        "target_dimension",
        target_dimension,
    )
    min_target_lift = _require_unit_interval("min_target_lift", min_target_lift)
    max_other_regression = _require_unit_interval(
        "max_other_regression",
        max_other_regression,
    )
    _require_prd_promotion_thresholds(
        min_target_lift=min_target_lift,
        max_other_regression=max_other_regression,
    )
    holdout_items = _materialize_mapping_records(
        holdout_records,
        collection_label="holdout_records",
        item_label="holdout record",
    )
    if not holdout_items:
        raise ValueError("holdout evaluation requires at least one holdout record")

    holdout_ids: set[str] = set()
    expected_source_hashes: dict[str, str] = {}
    expected_formats: dict[str, str] = {}
    seen_source_hashes: dict[str, str] = {}
    for record in holdout_items:
        doc_id = _record_id(record)
        if not doc_id:
            raise ValueError(
                "holdout record missing doc_id, document_hash, or source_path"
            )
        if doc_id in holdout_ids:
            raise ValueError(f"duplicate holdout document: {doc_id}")
        holdout_ids.add(doc_id)

        source_sha = _source_sha256(record, label=f"holdout record for {doc_id}")
        if not source_sha:
            raise ValueError(f"holdout record for {doc_id} missing source_sha256")
        _validate_sha256(source_sha, label=f"holdout record for {doc_id}")
        existing_doc_id = seen_source_hashes.get(source_sha)
        if existing_doc_id is not None:
            raise ValueError(
                "duplicate holdout source artifact: "
                f"{doc_id} and {existing_doc_id}"
            )
        seen_source_hashes[source_sha] = doc_id
        expected_source_hashes[doc_id] = source_sha
        fmt = _record_format(record, label=f"holdout record for {doc_id}")
        if fmt:
            expected_formats[doc_id] = fmt

    baseline_by_doc = _quality_results_by_doc(
        baseline_results,
        expected_source_hashes=expected_source_hashes,
        expected_formats=expected_formats,
        label="baseline",
    )
    candidate_by_doc = _quality_results_by_doc(
        candidate_results,
        expected_source_hashes=expected_source_hashes,
        expected_formats=expected_formats,
        label="candidate",
    )
    outside_holdout = sorted(
        (set(baseline_by_doc) | set(candidate_by_doc)) - holdout_ids
    )
    if outside_holdout:
        raise ValueError(
            "holdout evaluation received non-holdout result(s): "
            + ", ".join(outside_holdout)
        )
    missing_baseline = sorted(holdout_ids - set(baseline_by_doc))
    if missing_baseline:
        raise ValueError(
            "baseline results missing holdout document(s): "
            + ", ".join(missing_baseline)
        )
    missing_candidate = sorted(holdout_ids - set(candidate_by_doc))
    if missing_candidate:
        raise ValueError(
            "candidate results missing holdout document(s): "
            + ", ".join(missing_candidate)
        )

    evaluated_ids = sorted(holdout_ids)
    _validate_per_document_dimensions(
        evaluated_ids=evaluated_ids,
        target_dimension=target_dimension,
        baseline_by_doc=baseline_by_doc,
        candidate_by_doc=candidate_by_doc,
    )

    baseline_scores = _mean_dimension_scores(
        baseline_by_doc[doc_id]
        for doc_id in evaluated_ids
    )
    candidate_scores = _mean_dimension_scores(
        candidate_by_doc[doc_id]
        for doc_id in evaluated_ids
    )
    promotion_format = _single_format(expected_formats)
    decision = evaluate_strategy_promotion(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        min_target_lift=min_target_lift,
        max_other_regression=max_other_regression,
        document_format=promotion_format or None,
    )
    return HoldoutABEvaluation(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        run_id=_require_non_empty_string("run_id", run_id)
        if run_id is not None
        else _stable_evaluation_run_id(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            evaluated_doc_ids=evaluated_ids,
            source_hashes=expected_source_hashes,
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
            formats=expected_formats,
        ),
        evaluated_doc_ids=evaluated_ids,
        source_hashes={
            doc_id: expected_source_hashes[doc_id]
            for doc_id in evaluated_ids
        },
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        decision=decision,
        formats={
            doc_id: expected_formats[doc_id]
            for doc_id in evaluated_ids
            if doc_id in expected_formats
        },
    )


def evaluate_controlled_ab_success(
    *,
    strategy_name: str,
    target_dimension: str,
    evaluations: Iterable[HoldoutABEvaluation],
    required_experiments: int = 3,
) -> ControlledABSuccess:
    """Apply the PRD Phase G success criterion across repeated A/B runs."""
    strategy_name = _require_non_empty_string("strategy_name", strategy_name)
    target_dimension = _require_quality_dimension(
        "target_dimension",
        target_dimension,
    )
    required_experiments = _require_positive_int(
        "required_experiments",
        required_experiments,
    )
    if required_experiments < PRD_REQUIRED_CONTROLLED_AB_RUNS:
        raise ValueError(
            "required_experiments must be at least "
            f"{PRD_REQUIRED_CONTROLLED_AB_RUNS}"
        )
    runs = _materialize_ab_evaluations(evaluations)
    seen_run_ids: set[str] = set()
    seen_evidence: dict[str, str] = {}
    seen_source_artifacts: dict[str, str] = {}
    seen_doc_ids: dict[str, str] = {}
    for index, evaluation in enumerate(runs, 1):
        if not isinstance(evaluation, HoldoutABEvaluation):
            raise ValueError(f"evaluation {index} must be a HoldoutABEvaluation")
        run_id = _require_non_empty_string(
            f"evaluation {index} run_id",
            evaluation.run_id,
        )
        if run_id in seen_run_ids:
            raise ValueError(f"duplicate controlled A/B run_id: {run_id}")
        seen_run_ids.add(run_id)
        evaluation_strategy_name = _require_non_empty_string(
            f"evaluation {index} strategy_name",
            evaluation.strategy_name,
        )
        if evaluation_strategy_name != strategy_name:
            raise ValueError(
                "evaluation strategy mismatch: "
                f"{evaluation.strategy_name} != {strategy_name}"
            )
        evaluation_target_dimension = _require_quality_dimension(
            f"evaluation {index} target_dimension",
            evaluation.target_dimension,
        )
        if evaluation_target_dimension != target_dimension:
            raise ValueError(
                "evaluation target dimension mismatch: "
                f"{evaluation.target_dimension} != {target_dimension}"
            )
        _validate_holdout_ab_evaluation(
            evaluation,
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            label=f"evaluation {index}",
        )
        evidence_fingerprint = _evaluation_evidence_fingerprint(evaluation)
        existing_run_id = seen_evidence.get(evidence_fingerprint)
        if existing_run_id is not None:
            raise ValueError(
                "duplicate controlled A/B evidence: "
                f"{run_id} duplicates {existing_run_id}"
            )
        seen_evidence[evidence_fingerprint] = run_id
        for source_hash in _normalized_evaluation_source_hashes(evaluation).values():
            existing_source_run_id = seen_source_artifacts.get(source_hash)
            if existing_source_run_id is not None:
                raise ValueError(
                    "controlled A/B source artifact reused across runs: "
                    f"{run_id} reuses source artifact from {existing_source_run_id}"
                )
            seen_source_artifacts[source_hash] = run_id
        for doc_id in _normalized_evaluation_doc_ids(evaluation):
            existing_doc_run_id = seen_doc_ids.get(doc_id)
            if existing_doc_run_id is not None:
                raise ValueError(
                    "controlled A/B document reused across runs: "
                    f"{run_id} reuses {doc_id} from {existing_doc_run_id}"
                )
            seen_doc_ids[doc_id] = run_id

    regressions = {
        f"run_{index + 1}": _normalized_regression_deltas(
            evaluation.decision.regressions,
        )
        for index, evaluation in enumerate(runs)
        if evaluation.decision.regressions
    }
    if regressions:
        return ControlledABSuccess(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            required_experiments=required_experiments,
            total_experiments=len(runs),
            successful_experiments=sum(1 for run in runs if run.decision.promoted),
            passed=False,
            reason="one or more controlled A/B runs regressed non-target dimensions",
            regressions=regressions,
        )

    successes = sum(1 for run in runs if run.decision.promoted)
    if successes < required_experiments:
        return ControlledABSuccess(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            required_experiments=required_experiments,
            total_experiments=len(runs),
            successful_experiments=successes,
            passed=False,
            reason=(
                "successful controlled A/B experiments "
                f"{successes} < required {required_experiments}"
            ),
        )

    return ControlledABSuccess(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        required_experiments=required_experiments,
        total_experiments=len(runs),
        successful_experiments=successes,
        passed=True,
        reason="controlled A/B success criterion met",
    )


def _materialize_ab_evaluations(
    evaluations: Iterable[HoldoutABEvaluation],
) -> list[HoldoutABEvaluation]:
    if isinstance(evaluations, (str, bytes)) or isinstance(evaluations, Mapping):
        raise ValueError("evaluations must be an iterable of HoldoutABEvaluation")
    try:
        return list(evaluations)
    except TypeError as exc:
        raise ValueError(
            "evaluations must be an iterable of HoldoutABEvaluation"
        ) from exc


def _normalized_evaluation_source_hashes(
    evaluation: HoldoutABEvaluation,
) -> dict[str, str]:
    return {
        doc_id.strip(): source_hash
        for doc_id, source_hash in evaluation.source_hashes.items()
    }


def _normalized_evaluation_formats(
    evaluation: HoldoutABEvaluation,
) -> dict[str, str]:
    return {
        doc_id.strip(): fmt
        for doc_id, fmt in evaluation.formats.items()
    }


def _normalized_evaluation_doc_ids(evaluation: HoldoutABEvaluation) -> list[str]:
    return [doc_id.strip() for doc_id in evaluation.evaluated_doc_ids]


def _validate_holdout_ab_evaluation(
    evaluation: HoldoutABEvaluation,
    *,
    strategy_name: str,
    target_dimension: str,
    label: str,
) -> None:
    if not isinstance(evaluation, HoldoutABEvaluation):
        raise ValueError(f"{label} must be a HoldoutABEvaluation")
    if not isinstance(evaluation.evaluated_doc_ids, list) or not evaluation.evaluated_doc_ids:
        raise ValueError(f"{label} must include evaluated_doc_ids")
    invalid_doc_ids = [
        doc_id
        for doc_id in evaluation.evaluated_doc_ids
        if not isinstance(doc_id, str) or not doc_id.strip()
    ]
    if invalid_doc_ids:
        raise ValueError(f"{label} evaluated_doc_ids must contain non-empty strings")
    normalized_doc_ids = [doc_id.strip() for doc_id in evaluation.evaluated_doc_ids]
    if len(set(normalized_doc_ids)) != len(normalized_doc_ids):
        raise ValueError(f"{label} evaluated_doc_ids must not contain duplicates")
    _validate_evaluation_source_hashes(
        evaluation.source_hashes,
        evaluated_doc_ids=normalized_doc_ids,
        label=label,
    )
    formats = _validate_evaluation_formats(
        evaluation.formats,
        evaluated_doc_ids=normalized_doc_ids,
        label=label,
    )
    baseline_scores = _coerce_dimension_scores(
        evaluation.baseline_scores,
        label=f"{label} baseline scores",
    )
    _validate_score_dimensions_for_formats(
        baseline_scores,
        formats=formats,
        label=f"{label} baseline scores",
    )
    candidate_scores = _coerce_dimension_scores(
        evaluation.candidate_scores,
        label=f"{label} candidate scores",
    )
    _validate_score_dimensions_for_formats(
        candidate_scores,
        formats=formats,
        label=f"{label} candidate scores",
    )
    if not baseline_scores:
        raise ValueError(
            f"{label} baseline scores must include at least one dimension score"
        )
    if not candidate_scores:
        raise ValueError(
            f"{label} candidate scores must include at least one dimension score"
        )
    if target_dimension not in baseline_scores:
        raise ValueError(f"{label} baseline scores missing target dimension {target_dimension}")
    if target_dimension not in candidate_scores:
        raise ValueError(f"{label} candidate scores missing target dimension {target_dimension}")
    extra_candidate_dimensions = sorted(
        dimension
        for dimension in candidate_scores
        if dimension != target_dimension and dimension not in baseline_scores
    )
    if extra_candidate_dimensions:
        raise ValueError(
            f"{label} candidate scores contain non-baseline dimension(s): "
            + ", ".join(extra_candidate_dimensions)
        )
    missing_candidate_dimensions = sorted(
        dimension
        for dimension in baseline_scores
        if dimension != target_dimension and dimension not in candidate_scores
    )
    if missing_candidate_dimensions:
        raise ValueError(
            f"{label} candidate scores missing non-target dimension(s): "
            + ", ".join(missing_candidate_dimensions)
        )
    non_target_dimensions = [
        dimension
        for dimension in baseline_scores
        if dimension != target_dimension
    ]
    if not non_target_dimensions:
        raise ValueError(
            f"{label} scores must include at least one non-target dimension"
        )
    decision = evaluation.decision
    if not isinstance(decision, PromotionDecision):
        raise ValueError(f"{label} decision must be a PromotionDecision")
    decision_strategy_name = _require_non_empty_string(
        f"{label} decision strategy_name",
        decision.strategy_name,
    )
    if decision_strategy_name != strategy_name:
        raise ValueError(
            f"{label} decision strategy mismatch: "
            f"{decision.strategy_name} != {strategy_name}"
        )
    decision_target_dimension = _require_quality_dimension(
        f"{label} decision target_dimension",
        decision.target_dimension,
    )
    if decision_target_dimension != target_dimension:
        raise ValueError(
            f"{label} decision target dimension mismatch: "
            f"{decision.target_dimension} != {target_dimension}"
        )
    decision_target_lift = round(
        _require_score_delta(f"{label} decision target_lift", decision.target_lift),
        6,
    )
    if not isinstance(decision.promoted, bool):
        raise ValueError(f"{label} decision promoted must be a boolean")
    if not isinstance(decision.reason, str):
        raise ValueError(f"{label} decision reason must be a string")
    if not isinstance(decision.regressions, dict):
        raise ValueError(f"{label} decision regressions must be an object")
    normalized_regressions: dict[str, float] = {}
    for dimension, regression in decision.regressions.items():
        if not isinstance(dimension, str) or not dimension.strip():
            raise ValueError(
                f"{label} decision regression dimension name must be a non-empty string"
            )
        if dimension != dimension.strip():
            raise ValueError(
                f"{label} decision regression dimension name must be canonical"
            )
        dimension_name = dimension
        if dimension_name not in QUALITY_DIMENSION_SET:
            raise ValueError(
                f"{label} decision regression dimension {dimension_name!r} is unsupported"
            )
        _validate_dimension_for_formats(
            dimension_name,
            formats=formats,
            label=f"{label} decision regression",
        )
        if dimension_name in normalized_regressions:
            raise ValueError(
                f"{label} decision regression dimensions must be unique"
            )
        try:
            if isinstance(regression, bool):
                raise TypeError
            numeric_regression = float(regression)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label} decision regression {dimension!r} must be numeric"
            ) from exc
        if not math.isfinite(numeric_regression):
            raise ValueError(
                f"{label} decision regression {dimension!r} must be finite"
            )
        normalized_regressions[dimension_name] = round(numeric_regression, 6)

    expected_decision = evaluate_strategy_promotion(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        document_format=_single_format(formats) or None,
    )
    if decision_target_lift != expected_decision.target_lift:
        raise ValueError(
            f"{label} decision target_lift does not match score maps"
        )
    if normalized_regressions != expected_decision.regressions:
        raise ValueError(
            f"{label} decision regressions do not match score-derived regressions"
        )
    if decision.promoted != expected_decision.promoted:
        raise ValueError(
            f"{label} decision promoted does not match score-derived criteria"
        )
    if decision.reason != expected_decision.reason:
        raise ValueError(
            f"{label} decision reason does not match score-derived criteria"
        )


def _validate_evaluation_source_hashes(
    source_hashes: Mapping[str, Any],
    *,
    evaluated_doc_ids: Iterable[str],
    label: str,
) -> None:
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise ValueError(f"{label} source_hashes must be a non-empty object")
    normalized_hashes: dict[str, str] = {}
    seen_source_hashes: dict[str, str] = {}
    for raw_doc_id, raw_hash in source_hashes.items():
        if not isinstance(raw_doc_id, str) or not raw_doc_id.strip():
            raise ValueError(f"{label} source_hashes document ID must be non-empty")
        doc_id = raw_doc_id.strip()
        if doc_id in normalized_hashes:
            raise ValueError(f"{label} source_hashes document IDs must be unique")
        if not isinstance(raw_hash, str):
            raise ValueError(
                f"{label} source_hashes[{doc_id!r}] must be a sha256 hex digest"
            )
        _validate_sha256(raw_hash, label=f"{label} source_hashes[{doc_id!r}]")
        existing_doc_id = seen_source_hashes.get(raw_hash)
        if existing_doc_id is not None:
            raise ValueError(
                f"{label} source_hashes duplicate source artifact: "
                f"{doc_id} and {existing_doc_id}"
            )
        seen_source_hashes[raw_hash] = doc_id
        normalized_hashes[doc_id] = raw_hash

    expected_ids = set(evaluated_doc_ids)
    missing = sorted(expected_ids - set(normalized_hashes))
    if missing:
        raise ValueError(
            f"{label} source_hashes missing evaluated document(s): "
            + ", ".join(missing)
        )
    extra = sorted(set(normalized_hashes) - expected_ids)
    if extra:
        raise ValueError(
            f"{label} source_hashes contain non-evaluated document(s): "
            + ", ".join(extra)
        )


def _validate_evaluation_formats(
    formats: Mapping[str, Any],
    *,
    evaluated_doc_ids: Iterable[str],
    label: str,
) -> dict[str, str]:
    if not isinstance(formats, Mapping) or not formats:
        raise ValueError(f"{label} formats must be a non-empty object")
    normalized_formats: dict[str, str] = {}
    for raw_doc_id, raw_format in formats.items():
        if not isinstance(raw_doc_id, str) or not raw_doc_id.strip():
            raise ValueError(f"{label} formats document ID must be non-empty")
        doc_id = raw_doc_id.strip()
        if doc_id in normalized_formats:
            raise ValueError(f"{label} formats document IDs must be unique")
        normalized_formats[doc_id] = _canonical_format_value(
            raw_format,
            label=f"{label} formats[{doc_id!r}]",
        )

    expected_ids = set(evaluated_doc_ids)
    missing = sorted(expected_ids - set(normalized_formats))
    if missing:
        raise ValueError(
            f"{label} formats missing evaluated document(s): "
            + ", ".join(missing)
        )
    extra = sorted(set(normalized_formats) - expected_ids)
    if extra:
        raise ValueError(
            f"{label} formats contain non-evaluated document(s): "
            + ", ".join(extra)
        )
    return normalized_formats


def _validate_score_dimensions_for_formats(
    scores: Mapping[str, float],
    *,
    formats: Mapping[str, str],
    label: str,
) -> None:
    for dimension in scores:
        _validate_dimension_for_formats(dimension, formats=formats, label=label)


def _validate_dimension_for_formats(
    dimension: str,
    *,
    formats: Mapping[str, str],
    label: str,
) -> None:
    for fmt in sorted(set(formats.values())):
        if dimension not in DIMENSIONS_BY_FORMAT[fmt]:
            raise ValueError(
                f"{label} dimension {dimension!r} is not applicable to {fmt}"
            )


def _single_format(formats: Mapping[str, str]) -> str:
    unique_formats = set(formats.values())
    if len(unique_formats) != 1:
        return ""
    return next(iter(unique_formats))


def _normalized_regression_deltas(
    regressions: Mapping[str, Any],
) -> dict[str, float]:
    return {
        dimension.strip(): round(float(regression), 6)
        for dimension, regression in regressions.items()
    }


def evaluate_strategy_promotion(
    *,
    strategy_name: str,
    target_dimension: str,
    baseline_scores: Mapping[str, float],
    candidate_scores: Mapping[str, float],
    min_target_lift: float = 0.05,
    max_other_regression: float = 0.02,
    document_format: str | None = None,
) -> PromotionDecision:
    """Apply PRD Phase G holdout promotion criteria."""
    strategy_name = _require_non_empty_string("strategy_name", strategy_name)
    target_dimension = _require_quality_dimension(
        "target_dimension",
        target_dimension,
    )
    active_format = (
        _canonical_format_value(document_format, label="document_format")
        if document_format is not None
        else ""
    )
    if active_format:
        _validate_dimension_for_formats(
            target_dimension,
            formats={"promotion": active_format},
            label="target_dimension",
        )
    min_target_lift = _require_unit_interval("min_target_lift", min_target_lift)
    max_other_regression = _require_unit_interval(
        "max_other_regression",
        max_other_regression,
    )
    _require_prd_promotion_thresholds(
        min_target_lift=min_target_lift,
        max_other_regression=max_other_regression,
    )
    baseline_scores = _coerce_dimension_scores(
        baseline_scores,
        label="baseline scores",
        fmt=active_format,
    )
    candidate_scores = _coerce_dimension_scores(
        candidate_scores,
        label="candidate scores",
        fmt=active_format,
    )
    if target_dimension not in baseline_scores or target_dimension not in candidate_scores:
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=0.0,
            promoted=False,
            reason="target dimension missing from evaluation scores",
        )

    target_lift = round(
        candidate_scores[target_dimension] - baseline_scores[target_dimension],
        6,
    )
    missing_non_target_dimensions = sorted(
        dimension
        for dimension in baseline_scores
        if dimension != target_dimension and dimension not in candidate_scores
    )
    if missing_non_target_dimensions:
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=target_lift,
            promoted=False,
            reason=(
                "non-target dimension missing from candidate evaluation: "
                + ", ".join(missing_non_target_dimensions)
            ),
        )
    extra_candidate_dimensions = sorted(
        dimension
        for dimension in candidate_scores
        if dimension != target_dimension and dimension not in baseline_scores
    )
    if extra_candidate_dimensions:
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=target_lift,
            promoted=False,
            reason=(
                "non-target dimension missing from baseline evaluation: "
                + ", ".join(extra_candidate_dimensions)
            ),
        )
    if not any(dimension != target_dimension for dimension in baseline_scores):
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=target_lift,
            promoted=False,
            reason="non-target dimensions missing from evaluation scores",
        )
    regressions = {
        dimension: round(candidate_scores[dimension] - baseline, 6)
        for dimension, baseline in baseline_scores.items()
        if dimension != target_dimension
        and dimension in candidate_scores
        and candidate_scores[dimension] - baseline < -max_other_regression
    }
    if target_lift < min_target_lift:
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=target_lift,
            regressions=regressions,
            promoted=False,
            reason=(
                f"target lift {target_lift:.3f} < required "
                f"{min_target_lift:.3f}"
            ),
        )
    if regressions:
        return PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=target_lift,
            regressions=regressions,
            promoted=False,
            reason="non-target dimension regression exceeded threshold",
        )
    return PromotionDecision(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        target_lift=target_lift,
        regressions={},
        promoted=True,
        reason="promotion criteria met",
    )


def _stable_unit_interval(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / float(0xFFFFFFFFFFFFFFFF)


def _require_prd_promotion_thresholds(
    *,
    min_target_lift: float,
    max_other_regression: float,
) -> None:
    if min_target_lift < PRD_MIN_TARGET_LIFT:
        raise ValueError(
            "min_target_lift must be at least "
            f"{PRD_MIN_TARGET_LIFT:.2f}"
        )
    if max_other_regression > PRD_MAX_OTHER_REGRESSION:
        raise ValueError(
            "max_other_regression must be at most "
            f"{PRD_MAX_OTHER_REGRESSION:.2f}"
        )


def _stable_evaluation_run_id(
    *,
    strategy_name: str,
    target_dimension: str,
    evaluated_doc_ids: Iterable[str],
    source_hashes: Mapping[str, str],
    baseline_scores: Mapping[str, float],
    candidate_scores: Mapping[str, float],
    formats: Mapping[str, str] | None = None,
) -> str:
    parts = [strategy_name, target_dimension]
    parts.extend(
        f"doc:{doc_id}:{source_hashes[doc_id]}"
        for doc_id in sorted(evaluated_doc_ids)
    )
    if formats:
        parts.extend(
            f"format:{doc_id}:{formats[doc_id]}"
            for doc_id in sorted(formats)
        )
    parts.extend(
        f"baseline:{dimension}:{score:.6f}"
        for dimension, score in sorted(baseline_scores.items())
    )
    parts.extend(
        f"candidate:{dimension}:{score:.6f}"
        for dimension, score in sorted(candidate_scores.items())
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"holdout-ab-{digest[:16]}"


def _evaluation_evidence_fingerprint(evaluation: HoldoutABEvaluation) -> str:
    """Stable fingerprint for the substance of a controlled A/B run."""
    doc_ids = _normalized_evaluation_doc_ids(evaluation)
    source_hashes = _normalized_evaluation_source_hashes(evaluation)
    formats = _normalized_evaluation_formats(evaluation)
    baseline_scores = _coerce_dimension_scores(
        evaluation.baseline_scores,
        label="evaluation baseline scores",
    )
    candidate_scores = _coerce_dimension_scores(
        evaluation.candidate_scores,
        label="evaluation candidate scores",
    )
    return _stable_evaluation_run_id(
        strategy_name=_require_non_empty_string(
            "evaluation strategy_name",
            evaluation.strategy_name,
        ),
        target_dimension=_require_quality_dimension(
            "evaluation target_dimension",
            evaluation.target_dimension,
        ),
        evaluated_doc_ids=doc_ids,
        source_hashes=source_hashes,
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        formats=formats,
    )


def _record_id(record: Mapping[str, Any]) -> str:
    for key in ("doc_id", "document_hash", "source_path"):
        value = record.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return ""
        return value.strip()
    return ""


def _record_format(record: Mapping[str, Any], *, label: str) -> str:
    if "format" not in record:
        return ""
    return _canonical_format_value(
        record.get("format"),
        label=f"{label} format",
        unsupported_label=label,
    )


def _canonical_format_value(
    raw_format: Any,
    *,
    label: str,
    unsupported_label: str | None = None,
) -> str:
    if not isinstance(raw_format, str) or not raw_format.strip():
        raise ValueError(f"{label} must be a non-empty string")
    fmt = raw_format.strip().lower()
    if raw_format != fmt:
        raise ValueError(f"{label} must be canonical")
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"{unsupported_label or label} unsupported format: {fmt}")
    return fmt


def _require_non_empty_string(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_quality_dimension(name: str, value: str) -> str:
    dimension = _require_non_empty_string(name, value)
    if value != dimension:
        raise ValueError(f"{name} must be a canonical quality dimension")
    if dimension not in QUALITY_DIMENSION_SET:
        raise ValueError(f"{name} is not a supported quality dimension: {dimension}")
    return dimension


def _quality_results_by_doc(
    records: Iterable[Mapping[str, Any]],
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
    expected_formats: Mapping[str, str] | None = None,
    label: str = "quality",
) -> dict[str, dict[str, float]]:
    expected_source_hashes = expected_source_hashes or {}
    expected_formats = expected_formats or {}
    results: dict[str, dict[str, float]] = {}
    for record in _materialize_mapping_records(
        records,
        collection_label=f"{label}_results",
        item_label=f"{label} result",
    ):
        doc_id = _record_id(record)
        if not doc_id:
            raise ValueError(
                f"{label} result missing doc_id, document_hash, or source_path"
            )
        if doc_id in results:
            raise ValueError(f"{label} results contain duplicate document: {doc_id}")
        expected_source_hash = expected_source_hashes.get(doc_id)
        if expected_source_hash:
            actual_source_hash = _source_sha256(
                record,
                label=f"{label} result for {doc_id}",
            )
            if not actual_source_hash:
                raise ValueError(f"{label} result for {doc_id} missing source_sha256")
            _validate_sha256(actual_source_hash, label=f"{label} result for {doc_id}")
            if actual_source_hash != expected_source_hash:
                raise ValueError(f"{label} result for {doc_id} source_sha256 mismatch")
        expected_format = expected_formats.get(doc_id, "")
        actual_format = _record_format(record, label=f"{label} result for {doc_id}")
        if expected_format and actual_format and actual_format != expected_format:
            raise ValueError(
                f"{label} result for {doc_id} format {actual_format!r} "
                f"does not match holdout format {expected_format!r}"
            )
        results[doc_id] = _quality_dimensions(
            record,
            label=f"{label} result for {doc_id}",
            fmt=actual_format or expected_format,
        )
    return results


def _materialize_mapping_records(
    records: Iterable[Mapping[str, Any]],
    *,
    collection_label: str,
    item_label: str,
) -> list[dict[str, Any]]:
    if isinstance(records, (str, bytes)) or isinstance(records, Mapping):
        raise ValueError(f"{collection_label} must be an iterable of objects")
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise ValueError(
            f"{collection_label} must be an iterable of objects"
        ) from exc
    items: list[dict[str, Any]] = []
    for index, record in enumerate(iterator, 1):
        if not isinstance(record, Mapping):
            raise ValueError(f"{item_label} {index} must be an object")
        items.append(dict(record))
    return items


def _validate_per_document_dimensions(
    *,
    evaluated_ids: Iterable[str],
    target_dimension: str,
    baseline_by_doc: Mapping[str, Mapping[str, float]],
    candidate_by_doc: Mapping[str, Mapping[str, float]],
) -> None:
    """Reject partial per-document dimension evidence before aggregation."""
    reference_dimensions: set[str] | None = None
    for doc_id in evaluated_ids:
        baseline_dimensions = set(baseline_by_doc[doc_id])
        candidate_dimensions = set(candidate_by_doc[doc_id])
        if target_dimension not in baseline_dimensions:
            raise ValueError(
                f"baseline result for {doc_id} missing target dimension "
                f"{target_dimension}"
            )
        if target_dimension not in candidate_dimensions:
            raise ValueError(
                f"candidate result for {doc_id} missing target dimension "
                f"{target_dimension}"
            )
        if not any(
            dimension != target_dimension
            for dimension in baseline_dimensions
        ):
            raise ValueError(
                f"baseline result for {doc_id} missing non-target dimension evidence"
            )
        missing_non_target = sorted(
            dimension
            for dimension in baseline_dimensions - {target_dimension}
            if dimension not in candidate_dimensions
        )
        if missing_non_target:
            raise ValueError(
                f"candidate result for {doc_id} missing non-target dimension(s): "
                + ", ".join(missing_non_target)
            )
        extra_candidate = sorted(
            dimension
            for dimension in candidate_dimensions - {target_dimension}
            if dimension not in baseline_dimensions
        )
        if extra_candidate:
            raise ValueError(
                f"candidate result for {doc_id} contains non-baseline dimension(s): "
                + ", ".join(extra_candidate)
            )
        if reference_dimensions is None:
            reference_dimensions = baseline_dimensions
            continue
        if baseline_dimensions != reference_dimensions:
            missing_dimensions = sorted(reference_dimensions - baseline_dimensions)
            extra_dimensions = sorted(baseline_dimensions - reference_dimensions)
            details: list[str] = []
            if missing_dimensions:
                details.append("missing " + ", ".join(missing_dimensions))
            if extra_dimensions:
                details.append("extra " + ", ".join(extra_dimensions))
            raise ValueError(
                "holdout evaluation dimension coverage for "
                f"{doc_id} differs from other holdout documents: "
                + "; ".join(details)
            )


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(
        char not in "0123456789abcdef"
        for char in value
    ):
        raise ValueError(f"{label} source_sha256 must be a sha256 hex digest")


def _source_sha256(record: Mapping[str, Any], *, label: str) -> str:
    direct_hash = ""
    if "source_sha256" in record:
        direct = record.get("source_sha256")
        if not isinstance(direct, str) or not direct.strip():
            raise ValueError(f"{label} source_sha256 must be a non-empty string")
        direct_hash = direct

    nested_hash = ""
    if "artifact_hashes" in record:
        artifact_hashes = record.get("artifact_hashes")
        if not isinstance(artifact_hashes, Mapping):
            raise ValueError(f"{label} artifact_hashes must be an object")
        nested = artifact_hashes.get("source_sha256")
        if not isinstance(nested, str) or not nested.strip():
            raise ValueError(
                f"{label} artifact_hashes.source_sha256 must be a non-empty string"
            )
        nested_hash = nested

    if direct_hash and nested_hash and direct_hash != nested_hash:
        raise ValueError(
            f"{label} source_sha256 conflicts with artifact_hashes.source_sha256"
        )
    return direct_hash or nested_hash


def _quality_dimensions(
    record: Mapping[str, Any],
    *,
    label: str,
    fmt: str = "",
) -> dict[str, float]:
    active_format = fmt or _record_format(record, label=label)
    if "quality_dimensions" in record:
        raw = record.get("quality_dimensions")
        if not isinstance(raw, Mapping):
            raise ValueError(f"{label} quality_dimensions must be an object")
        scores = _coerce_dimension_scores(raw, label=label, fmt=active_format)
        if not scores:
            raise ValueError(f"{label} must include at least one dimension score")
        return scores

    if "dimensions" in record:
        dimensions = record.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise ValueError(f"{label} dimensions must be an object")
        raw_scores: dict[Any, Any] = {}
        for dimension, payload in dimensions.items():
            if isinstance(payload, Mapping):
                if "score" not in payload:
                    raise ValueError(
                        f"{label} dimension {dimension!r} missing score"
                    )
                raw_scores[dimension] = payload["score"]
            elif isinstance(payload, (int, float)):
                raw_scores[dimension] = payload
            else:
                raise ValueError(
                    f"{label} dimension {dimension!r} must be numeric or an object with score"
                )
        scores = _coerce_dimension_scores(raw_scores, label=label, fmt=active_format)
        if not scores:
            raise ValueError(f"{label} must include at least one dimension score")
        return scores
    raise ValueError(f"{label} must include quality_dimensions or dimensions")


def _coerce_dimension_scores(
    raw_scores: Mapping[str, Any],
    *,
    label: str,
    fmt: str = "",
) -> dict[str, float]:
    if not isinstance(raw_scores, Mapping):
        raise ValueError(f"{label} must be an object")
    scores: dict[str, float] = {}
    for dimension, raw_score in raw_scores.items():
        if not isinstance(dimension, str) or not dimension.strip():
            raise ValueError(f"{label} dimension name must be non-empty")
        if dimension != dimension.strip():
            raise ValueError(f"{label} dimension name must be canonical")
        dimension_name = dimension
        if dimension_name not in QUALITY_DIMENSION_SET:
            raise ValueError(
                f"{label} dimension {dimension_name!r} is unsupported"
            )
        if fmt and dimension_name not in DIMENSIONS_BY_FORMAT[fmt]:
            raise ValueError(
                f"{label} dimension {dimension_name!r} is not applicable to {fmt}"
            )
        if dimension_name in scores:
            raise ValueError(f"{label} dimension names must be unique")
        try:
            if isinstance(raw_score, bool):
                raise TypeError
            score = float(raw_score)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label} dimension {dimension!r} score must be numeric"
            ) from exc
        if not math.isfinite(score):
            raise ValueError(
                f"{label} dimension {dimension!r} score must be finite"
            )
        if score < 0.0 or score > 1.0:
            raise ValueError(
                f"{label} dimension {dimension!r} score must be between 0.0 and 1.0"
            )
        scores[dimension_name] = score
    return scores


def _mean_dimension_scores(records: Iterable[Mapping[str, float]]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for record in records:
        for dimension, score in record.items():
            values.setdefault(dimension, []).append(float(score))
    return {
        dimension: round(sum(scores) / len(scores), 6)
        for dimension, scores in sorted(values.items())
        if scores
    }
