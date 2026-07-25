"""Calibrate quality judges against specialist corpus annotations.

The CLI compares judge scores with human annotation scores per
judge x version x format x dimension and records Cohen's kappa in the
existing experiment store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from project_remedy.models import FileType
from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT
from project_remedy.quality_judges.shared.base import model_family
from project_remedy.quality_judges.shared.registry import required_judge_calibrations
from project_remedy.vision_planner.experiment_store import ExperimentStore
from tools.annotate_corpus import (
    DEFAULT_CORPUS_ROOT,
    OFFICE_FORMATS,
    iter_annotation_paths,
    validate_annotation_file,
)


DEFAULT_KAPPA_THRESHOLD = 0.8


def _require_unit_interval(name: str, value: float) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return numeric


def _require_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_timezone_datetime(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date-time string") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _require_payload_string(
    payload: dict[str, Any],
    field: str,
    *,
    source: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value


def _optional_payload_string(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    *,
    source: str,
) -> str:
    for field in fields:
        if field not in payload:
            continue
        value = payload[field]
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{source}: {field} must be a string")
        if value.strip():
            return value
    return ""


@dataclass(frozen=True)
class JudgeResultRow:
    """One judge result for one annotated document dimension."""

    doc_id: str
    format: str
    dimension: str
    score: float
    judge_id: str
    judge_version: str
    artifact_path: str = ""
    artifact_sha256: str = ""
    judge_model: str = ""
    artifact_generator_model: str = ""


@dataclass(frozen=True)
class JudgeComparisonRow:
    """One pairwise judge verdict for one annotated comparison."""

    format: str
    dimension: str
    a_path: str
    b_path: str
    winner: str
    judge_id: str
    judge_version: str
    a_sha256: str = ""
    b_sha256: str = ""
    judge_model: str = ""
    artifact_generator_model: str = ""


@dataclass(frozen=True)
class CalibrationMetric:
    """Cohen's kappa result for one judge x dimension slice."""

    judge_id: str
    judge_version: str
    format: str
    dimension: str
    cohens_kappa: float
    sample_size: int
    measured_at: str


def build_drift_alerts(
    metrics: Iterable[CalibrationMetric],
    *,
    kappa_threshold: float,
    min_samples: int,
) -> list[dict[str, Any]]:
    """Build structured drift alert payloads from calibration metrics."""
    kappa_threshold = _require_unit_interval("kappa_threshold", kappa_threshold)
    min_samples = _require_positive_int("min_samples", min_samples)
    validated_metrics = [
        _validate_calibration_metric(metric, source=f"metric {index}")
        for index, metric in enumerate(metrics, 1)
    ]
    alerts: list[dict[str, Any]] = []
    for metric in validated_metrics:
        if metric.sample_size < min_samples or metric.cohens_kappa >= kappa_threshold:
            continue
        alerts.append(
            {
                "event": "quality_judge_drift",
                "judge_id": metric.judge_id,
                "judge_version": metric.judge_version,
                "format": metric.format,
                "dimension": metric.dimension,
                "cohens_kappa": metric.cohens_kappa,
                "kappa_threshold": kappa_threshold,
                "sample_size": metric.sample_size,
                "measured_at": metric.measured_at,
            }
        )
    return alerts


def build_rolling_drift_alerts(
    metrics: Iterable[CalibrationMetric],
    *,
    kappa_threshold: float,
    min_samples: int,
    rolling_window: int,
) -> list[dict[str, Any]]:
    """Build drift alerts from the latest N measurements per judge slice."""
    rolling_window = _require_positive_int("rolling_window", rolling_window)
    if rolling_window <= 1:
        return build_drift_alerts(
            metrics,
            kappa_threshold=kappa_threshold,
            min_samples=min_samples,
        )

    grouped: dict[tuple[str, str, str, str], list[CalibrationMetric]] = defaultdict(
        list
    )
    for index, metric in enumerate(metrics, 1):
        metric = _validate_calibration_metric(metric, source=f"metric {index}")
        grouped[
            (
                metric.judge_id,
                metric.judge_version,
                metric.format,
                metric.dimension,
            )
        ].append(metric)

    alerts: list[dict[str, Any]] = []
    for key, group in sorted(grouped.items()):
        window = sorted(
            group,
            key=lambda item: _parse_timezone_datetime(item.measured_at),
        )[-rolling_window:]
        sample_size = sum(item.sample_size for item in window)
        if sample_size < min_samples:
            continue
        weighted_kappa = round(
            sum(item.cohens_kappa * item.sample_size for item in window) / sample_size,
            6,
        )
        if weighted_kappa >= kappa_threshold:
            continue
        judge_id, judge_version, fmt, dimension = key
        alerts.append(
            {
                "event": "quality_judge_drift",
                "judge_id": judge_id,
                "judge_version": judge_version,
                "format": fmt,
                "dimension": dimension,
                "cohens_kappa": weighted_kappa,
                "kappa_threshold": kappa_threshold,
                "sample_size": sample_size,
                "measured_at": window[-1].measured_at,
                "rolling_window": rolling_window,
                "window_measurements": len(window),
                "window_start": window[0].measured_at,
                "window_end": window[-1].measured_at,
            }
        )
    return alerts


def _validate_calibration_metric(
    metric: CalibrationMetric,
    *,
    source: str,
) -> CalibrationMetric:
    if not isinstance(metric, CalibrationMetric):
        raise ValueError(f"{source} must be a CalibrationMetric")
    for field_name in ("judge_id", "judge_version"):
        value = getattr(metric, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{source}.{field_name} must be a non-empty string")
    if not isinstance(metric.format, str) or not isinstance(metric.dimension, str):
        raise ValueError(f"{source}.format and {source}.dimension must be strings")
    _validate_format_dimension(metric.format, metric.dimension, source=source)
    return CalibrationMetric(
        judge_id=metric.judge_id.strip(),
        judge_version=metric.judge_version.strip(),
        format=metric.format,
        dimension=metric.dimension,
        cohens_kappa=_require_unit_interval(
            f"{source}.cohens_kappa",
            metric.cohens_kappa,
        ),
        sample_size=_require_positive_int(
            f"{source}.sample_size",
            metric.sample_size,
        ),
        measured_at=_require_timezone_datetime(
            f"{source}.measured_at",
            metric.measured_at,
        ),
    )


def _parse_timezone_datetime(value: str) -> datetime:
    _require_timezone_datetime("measured_at", value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def emit_drift_alerts(
    alerts: Iterable[dict[str, Any]],
    *,
    alert_log: Path | None = None,
    webhook_url: str = "",
) -> None:
    """Emit structured drift alerts to JSONL and optional webhook."""
    rows = [
        _validate_drift_alert(alert, source=f"alert {index}")
        for index, alert in enumerate(alerts, 1)
    ]
    if not rows:
        return
    validated_webhook_url = (
        _validate_alert_webhook_url(webhook_url)
        if webhook_url
        else ""
    )
    if alert_log is not None:
        alert_log.parent.mkdir(parents=True, exist_ok=True)
        with alert_log.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    if validated_webhook_url:
        payload = json.dumps({"alerts": rows}).encode("utf-8")
        request = urllib.request.Request(
            validated_webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            response.read()


def _validate_drift_alert(alert: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(alert, dict):
        raise ValueError(f"{source} must be an object")
    if alert.get("event") != "quality_judge_drift":
        raise ValueError(f"{source}.event must be quality_judge_drift")
    for field_name in ("judge_id", "judge_version"):
        value = alert.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{source}.{field_name} must be a non-empty string")
    fmt = alert.get("format")
    dimension = alert.get("dimension")
    if not isinstance(fmt, str) or not isinstance(dimension, str):
        raise ValueError(f"{source}.format and {source}.dimension must be strings")
    _validate_format_dimension(fmt, dimension, source=source)
    row: dict[str, Any] = {
        "event": "quality_judge_drift",
        "judge_id": alert["judge_id"].strip(),
        "judge_version": alert["judge_version"].strip(),
        "format": fmt,
        "dimension": dimension,
        "cohens_kappa": _require_unit_interval(
            f"{source}.cohens_kappa",
            alert.get("cohens_kappa"),
        ),
        "kappa_threshold": _require_unit_interval(
            f"{source}.kappa_threshold",
            alert.get("kappa_threshold"),
        ),
        "sample_size": _require_positive_int(
            f"{source}.sample_size",
            alert.get("sample_size"),
        ),
        "measured_at": _require_timezone_datetime(
            f"{source}.measured_at",
            alert.get("measured_at"),
        ),
    }
    if "rolling_window" in alert:
        row["rolling_window"] = _require_positive_int(
            f"{source}.rolling_window",
            alert.get("rolling_window"),
        )
    if "window_measurements" in alert:
        row["window_measurements"] = _require_positive_int(
            f"{source}.window_measurements",
            alert.get("window_measurements"),
        )
    for field_name in ("window_start", "window_end"):
        if field_name in alert:
            row[field_name] = _require_timezone_datetime(
                f"{source}.{field_name}",
                alert.get(field_name),
            )
    return row


def _validate_alert_webhook_url(webhook_url: Any) -> str:
    if not isinstance(webhook_url, str) or not webhook_url.strip():
        raise ValueError("alert_webhook must be a non-empty URL")
    parsed = urllib.parse.urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("alert_webhook must be an http(s) URL")
    return webhook_url


def score_to_label(score: float, *, threshold: float = 0.8) -> str:
    """Convert a continuous quality score into the calibration label space."""
    threshold = _require_unit_interval("threshold", threshold)
    if isinstance(score, bool):
        raise ValueError("score must be numeric")
    if not math.isfinite(float(score)):
        raise ValueError("score must be finite")
    return "pass" if score >= threshold else "fail"


def compute_cohens_kappa(pairs: Iterable[tuple[str, str]]) -> float:
    """Compute Cohen's kappa for two raters over categorical labels."""
    items = list(pairs)
    if not items:
        raise ValueError("cannot compute Cohen's kappa without samples")

    total = len(items)
    observed = sum(1 for left, right in items if left == right) / total
    left_counts = Counter(left for left, _ in items)
    right_counts = Counter(right for _, right in items)
    labels = set(left_counts) | set(right_counts)
    expected = sum(
        (left_counts[label] / total) * (right_counts[label] / total)
        for label in labels
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return round((observed - expected) / (1.0 - expected), 6)


def load_annotation_records(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load all valid annotation records under a corpus root."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in iter_annotation_paths(root):
        validation_errors = validate_annotation_file(path)
        if validation_errors:
            errors.extend(f"{path}: {error}" for error in validation_errors)
            continue
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records, errors


def load_judge_result_rows(path: Path) -> list[JudgeResultRow]:
    """Load judge result rows from JSONL."""
    rows: list[JudgeResultRow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        rows.append(_judge_result_from_payload(payload, source=f"{path}:{line_number}"))
    return rows


def load_judge_comparison_rows(path: Path) -> list[JudgeComparisonRow]:
    """Load pairwise judge comparison rows from JSONL."""
    rows: list[JudgeComparisonRow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        rows.append(_judge_comparison_from_payload(payload, source=f"{path}:{line_number}"))
    return rows


def run_audits_for_annotations(
    records: Iterable[dict[str, Any]],
    *,
    config: Any | None = None,
) -> tuple[list[JudgeResultRow], list[str]]:
    """Run current quality audits for records whose source artifacts exist."""
    rows: list[JudgeResultRow] = []
    skipped: list[str] = []
    for record in records:
        source_path = Path(record["source_path"])
        if not source_path.exists():
            skipped.append(f"{record['doc_id']}: missing source artifact {source_path}")
            continue
        source_sha256 = _sha256_file(source_path)
        expected_source_sha256 = str((record.get("artifact_hashes") or {}).get("source_sha256") or "")
        if expected_source_sha256 and source_sha256 != expected_source_sha256:
            skipped.append(f"{record['doc_id']}: source artifact hash mismatch {source_path}")
            continue
        try:
            result = _audit_record(source_path, record["format"], config=config)
        except Exception as exc:  # noqa: BLE001 - CLI reports per-document failures.
            skipped.append(f"{record['doc_id']}: audit failed: {exc}")
            continue
        for dimension, score in result.dimensions.items():
            for judge_id, judge_version in _split_judge_versions(score.judge_versions):
                rows.append(
                    JudgeResultRow(
                        doc_id=record["doc_id"],
                        format=record["format"],
                        dimension=dimension,
                        score=score.score,
                        judge_id=judge_id,
                        judge_version=judge_version,
                        artifact_path=str(source_path),
                        artifact_sha256=source_sha256,
                    )
                )
    return rows, skipped


def summarize_calibration(
    records: Iterable[dict[str, Any]],
    judge_rows: Iterable[JudgeResultRow],
    *,
    score_threshold: float = 0.8,
    measured_at: str | None = None,
) -> list[CalibrationMetric]:
    """Compute kappa metrics for all judge-result groups."""
    annotations: dict[tuple[str, str, str], float] = {}
    for record in records:
        doc_id = record["doc_id"]
        fmt = record["format"]
        for dimension, payload in record.get("dimensions", {}).items():
            annotations[(doc_id, fmt, dimension)] = float(payload["score"])

    grouped: dict[tuple[str, str, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in judge_rows:
        human_score = annotations.get((row.doc_id, row.format, row.dimension))
        if human_score is None:
            continue
        key = (row.judge_id, row.judge_version, row.format, row.dimension)
        grouped[key].append(
            (
                score_to_label(human_score, threshold=score_threshold),
                score_to_label(row.score, threshold=score_threshold),
            )
        )

    measured = measured_at or datetime.now(timezone.utc).isoformat()
    metrics: list[CalibrationMetric] = []
    for key, pairs in sorted(grouped.items()):
        judge_id, judge_version, fmt, dimension = key
        metrics.append(
            CalibrationMetric(
                judge_id=judge_id,
                judge_version=judge_version,
                format=fmt,
                dimension=dimension,
                cohens_kappa=compute_cohens_kappa(pairs),
                sample_size=len(pairs),
                measured_at=measured,
            )
        )
    return metrics


def summarize_pairwise_calibration(
    records: Iterable[dict[str, Any]],
    judge_comparisons: Iterable[JudgeComparisonRow],
    *,
    measured_at: str | None = None,
) -> list[CalibrationMetric]:
    """Compute kappa metrics from human better/worse pairs and judge comparisons."""
    human_comparisons: dict[tuple[str, str, str, str], str] = {}
    for record in records:
        fmt = record["format"]
        for comparison in record.get("pairwise_comparisons", []):
            dimension = str(comparison["dimension"])
            key = _comparison_key(
                fmt,
                dimension,
                str(comparison["a_path"]),
                str(comparison["b_path"]),
            )
            human_comparisons[key] = _normalize_winner(str(comparison["winner"]))

    grouped: dict[tuple[str, str, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in judge_comparisons:
        key = _comparison_key(row.format, row.dimension, row.a_path, row.b_path)
        human_winner = human_comparisons.get(key)
        if human_winner is None:
            continue
        metric_key = (row.judge_id, row.judge_version, row.format, row.dimension)
        grouped[metric_key].append((human_winner, _normalize_winner(row.winner)))

    measured = measured_at or datetime.now(timezone.utc).isoformat()
    metrics: list[CalibrationMetric] = []
    for key, pairs in sorted(grouped.items()):
        judge_id, judge_version, fmt, dimension = key
        metrics.append(
            CalibrationMetric(
                judge_id=judge_id,
                judge_version=judge_version,
                format=fmt,
                dimension=dimension,
                cohens_kappa=compute_cohens_kappa(pairs),
                sample_size=len(pairs),
                measured_at=measured,
            )
        )
    return metrics


def record_metrics(store: ExperimentStore, metrics: Iterable[CalibrationMetric]) -> None:
    """Persist calibration metrics into the experiment store."""
    for metric in metrics:
        store.record_judge_calibration(**asdict(metric))


def metrics_from_store_rows(rows: Iterable[dict[str, Any]]) -> list[CalibrationMetric]:
    """Convert persisted calibration rows back into metric objects."""
    metrics: list[CalibrationMetric] = []
    for row in rows:
        metrics.append(
            CalibrationMetric(
                judge_id=str(row["judge_id"]),
                judge_version=str(row["judge_version"]),
                format=str(row["format"]),
                dimension=str(row["dimension"]),
                cohens_kappa=_require_unit_interval(
                    "cohens_kappa",
                    row["cohens_kappa"],
                ),
                sample_size=_require_positive_int(
                    "sample_size",
                    row["sample_size"],
                ),
                measured_at=_require_timezone_datetime(
                    "measured_at",
                    row["measured_at"],
                ),
            )
        )
    return metrics


def calibration_readiness_errors(
    records: Iterable[dict[str, Any]],
    metrics: Iterable[CalibrationMetric],
    *,
    kappa_threshold: float,
    min_samples: int,
) -> list[str]:
    """Return unmet active calibration requirements for annotated formats."""
    kappa_threshold = _require_unit_interval("kappa_threshold", kappa_threshold)
    min_samples = _require_positive_int("min_samples", min_samples)
    formats = sorted({str(record.get("format")) for record in records if record.get("format")})
    metric_map = {
        (
            metric.judge_id,
            metric.judge_version,
            metric.format,
            metric.dimension,
        ): metric
        for metric in metrics
    }
    errors: list[str] = []
    for fmt in formats:
        requirements = required_judge_calibrations(fmt)
        if not requirements:
            errors.append(f"no registered judge calibration requirements for {fmt}")
            continue
        for requirement in requirements:
            key = (
                requirement.judge_id,
                requirement.judge_version,
                requirement.format,
                requirement.dimension,
            )
            metric = metric_map.get(key)
            label = (
                f"{requirement.format}/{requirement.dimension} "
                f"{requirement.judge_id}:{requirement.judge_version}"
            )
            if metric is None:
                errors.append(f"missing calibration metric: {label}")
                continue
            if metric.sample_size < min_samples:
                errors.append(
                    f"calibration sample too small: {label} "
                    f"n={metric.sample_size} < required {min_samples}"
                )
            if metric.cohens_kappa < kappa_threshold:
                errors.append(
                    f"calibration below threshold: {label} "
                    f"kappa={metric.cohens_kappa:.3f} < required {kappa_threshold:.3f}"
                )
    return errors


def judge_result_binding_errors(
    records: Iterable[dict[str, Any]],
    judge_rows: Iterable[JudgeResultRow],
) -> list[str]:
    """Return errors for judge-result rows not bound to the annotated source artifact."""
    annotations = {
        (str(record.get("doc_id")), str(record.get("format"))): record
        for record in records
    }
    errors: list[str] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for index, row in enumerate(judge_rows, 1):
        record = annotations.get((row.doc_id, row.format))
        label = f"judge result row {index} {row.doc_id}/{row.format}/{row.dimension}"
        key = (row.doc_id, row.format, row.dimension, row.judge_id, row.judge_version)
        if key in seen:
            errors.append(f"{label}: duplicate judge result row")
        seen.add(key)
        if record is None:
            errors.append(f"{label}: no matching annotation")
            continue
        expected_path = str(record.get("source_path") or "")
        artifact_hashes = record.get("artifact_hashes") if isinstance(record.get("artifact_hashes"), dict) else {}
        expected_sha = str(artifact_hashes.get("source_sha256") or "")
        if not row.artifact_path:
            errors.append(f"{label}: missing artifact_path")
        elif row.artifact_path != expected_path:
            errors.append(f"{label}: artifact_path must match source_path")
        if not expected_sha:
            errors.append(f"{label}: annotation missing source_sha256")
        elif not row.artifact_sha256:
            errors.append(f"{label}: missing artifact_sha256")
        elif row.artifact_sha256 != expected_sha:
            errors.append(f"{label}: artifact_sha256 must match source_sha256")
        errors.extend(_judge_result_model_errors(record, row, label=label))
    return errors


def _judge_result_model_errors(
    record: dict[str, Any],
    row: JudgeResultRow,
    *,
    label: str,
) -> list[str]:
    return _judge_model_metadata_errors(
        record=record,
        judge_model=row.judge_model,
        artifact_generator_model=row.artifact_generator_model,
        label=label,
    )


def _judge_model_metadata_errors(
    *,
    record: dict[str, Any],
    judge_model: str,
    artifact_generator_model: str,
    label: str,
) -> list[str]:
    judge_model = judge_model.strip()
    if not judge_model:
        return [f"{label}: missing judge_model"]
    judge_family = model_family(judge_model)
    if not judge_family:
        return [f"{label}: judge_model must be a non-empty string"]

    errors: list[str] = []
    for generator_model in _artifact_generator_models_for_calibration(
        record,
        artifact_generator_model=artifact_generator_model,
    ):
        generator_family = model_family(generator_model)
        if not generator_family:
            continue
        if judge_model.lower() == generator_model.lower():
            errors.append(f"{label}: judge_model must differ from artifact generator model")
        elif judge_family == generator_family:
            errors.append(
                f"{label}: judge_model family must differ from artifact generator "
                f"model {generator_model!r}"
            )
    return errors


def _artifact_generator_models_for_calibration(
    record: dict[str, Any],
    *,
    artifact_generator_model: str,
) -> list[str]:
    models: list[str] = []
    if artifact_generator_model.strip():
        models.append(artifact_generator_model.strip())
    provenance = record.get("provenance")
    if isinstance(provenance, dict):
        candidate_seed_model = provenance.get("candidate_seed_model")
        if isinstance(candidate_seed_model, str) and candidate_seed_model.strip():
            models.append(candidate_seed_model.strip())
    return models


def judge_comparison_binding_errors(
    records: Iterable[dict[str, Any]],
    judge_comparisons: Iterable[JudgeComparisonRow],
) -> list[str]:
    """Return errors for pairwise judge rows not bound to annotation candidate hashes."""
    annotations: dict[tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for record in records:
        fmt = record["format"]
        for comparison in record.get("pairwise_comparisons", []):
            key = _comparison_key(
                fmt,
                str(comparison.get("dimension")),
                str(comparison.get("a_path")),
                str(comparison.get("b_path")),
            )
            annotations[key] = (comparison, record)
    errors: list[str] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for index, row in enumerate(judge_comparisons, 1):
        key = _comparison_key(row.format, row.dimension, row.a_path, row.b_path)
        annotation_match = annotations.get(key)
        label = f"judge comparison row {index} {row.format}/{row.dimension}"
        duplicate_key = (
            row.format,
            row.dimension,
            key[2],
            key[3],
            row.judge_id,
            row.judge_version,
        )
        if duplicate_key in seen:
            errors.append(f"{label}: duplicate judge comparison row")
        seen.add(duplicate_key)
        if annotation_match is None:
            errors.append(f"{label}: no matching annotation pairwise comparison")
            continue
        comparison, record = annotation_match
        expected_a_sha = str(comparison.get("a_sha256") or "")
        expected_b_sha = str(comparison.get("b_sha256") or "")
        if expected_a_sha:
            if not row.a_sha256:
                errors.append(f"{label}: missing a_sha256")
            elif row.a_sha256 != expected_a_sha:
                errors.append(f"{label}: a_sha256 must match annotation pairwise comparison")
        if expected_b_sha:
            if not row.b_sha256:
                errors.append(f"{label}: missing b_sha256")
            elif row.b_sha256 != expected_b_sha:
                errors.append(f"{label}: b_sha256 must match annotation pairwise comparison")
        errors.extend(
            _judge_model_metadata_errors(
                record=record,
                judge_model=row.judge_model,
                artifact_generator_model=row.artifact_generator_model,
                label=label,
            )
        )
    return errors


def _judge_result_from_payload(payload: dict[str, Any], *, source: str) -> JudgeResultRow:
    if not isinstance(payload, dict):
        raise ValueError(f"{source}: row must be an object")
    required = ("doc_id", "format", "dimension", "score", "judge_id", "judge_version")
    missing = [
        field
        for field in required
        if field not in payload
    ]
    if missing:
        raise ValueError(f"{source}: missing required field(s): {', '.join(missing)}")
    doc_id = _require_payload_string(payload, "doc_id", source=source)
    fmt = _require_payload_string(payload, "format", source=source)
    dimension = _require_payload_string(payload, "dimension", source=source)
    judge_id = _require_payload_string(payload, "judge_id", source=source)
    judge_version = _require_payload_string(payload, "judge_version", source=source)
    _validate_format_dimension(fmt, dimension, source=source)
    try:
        if isinstance(payload["score"], bool):
            raise TypeError
        score = float(payload["score"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: score must be numeric") from exc
    if not math.isfinite(score):
        raise ValueError(f"{source}: score must be finite")
    if score < 0 or score > 1:
        raise ValueError(f"{source}: score must be between 0 and 1")
    return JudgeResultRow(
        doc_id=doc_id,
        format=fmt,
        dimension=dimension,
        score=score,
        judge_id=judge_id,
        judge_version=judge_version,
        artifact_path=_optional_payload_string(
            payload,
            ("artifact_path", "source_path"),
            source=source,
        ),
        artifact_sha256=_optional_payload_string(
            payload,
            ("artifact_sha256", "source_sha256"),
            source=source,
        ),
        judge_model=_optional_payload_string(
            payload,
            ("judge_model", "quality_judge_model", "model"),
            source=source,
        ),
        artifact_generator_model=_optional_payload_string(
            payload,
            (
                "artifact_generator_model",
                "generated_by_model",
                "candidate_seed_model",
                "production_model",
            ),
            source=source,
        ),
    )


def _judge_comparison_from_payload(payload: dict[str, Any], *, source: str) -> JudgeComparisonRow:
    if not isinstance(payload, dict):
        raise ValueError(f"{source}: row must be an object")
    required = (
        "format",
        "dimension",
        "a_path",
        "b_path",
        "winner",
        "judge_id",
        "judge_version",
    )
    missing = [
        field
        for field in required
        if field not in payload
    ]
    if missing:
        raise ValueError(f"{source}: missing required field(s): {', '.join(missing)}")
    fmt = _require_payload_string(payload, "format", source=source)
    dimension = _require_payload_string(payload, "dimension", source=source)
    a_path = _require_payload_string(payload, "a_path", source=source)
    b_path = _require_payload_string(payload, "b_path", source=source)
    winner = _require_payload_string(payload, "winner", source=source)
    judge_id = _require_payload_string(payload, "judge_id", source=source)
    judge_version = _require_payload_string(payload, "judge_version", source=source)
    _validate_format_dimension(fmt, dimension, source=source)
    return JudgeComparisonRow(
        format=fmt,
        dimension=dimension,
        a_path=a_path,
        b_path=b_path,
        winner=_normalize_winner(winner),
        judge_id=judge_id,
        judge_version=judge_version,
        a_sha256=_optional_payload_string(payload, ("a_sha256",), source=source),
        b_sha256=_optional_payload_string(payload, ("b_sha256",), source=source),
        judge_model=_optional_payload_string(
            payload,
            ("judge_model", "quality_judge_model", "model"),
            source=source,
        ),
        artifact_generator_model=_optional_payload_string(
            payload,
            (
                "artifact_generator_model",
                "generated_by_model",
                "candidate_seed_model",
                "production_model",
            ),
            source=source,
        ),
    )


def _validate_format_dimension(fmt: str, dimension: str, *, source: str) -> None:
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"{source}: unsupported format: {fmt}")
    if dimension not in DIMENSIONS_BY_FORMAT[fmt]:
        raise ValueError(
            f"{source}: dimension {dimension!r} is not applicable to {fmt}"
        )


def _normalize_winner(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "a": "a",
        "a_better": "a",
        "a-better": "a",
        "b": "b",
        "b_better": "b",
        "b-better": "b",
        "tie": "tied",
        "tied": "tied",
    }
    winner = aliases.get(normalized)
    if winner is None:
        raise ValueError(f"unsupported pairwise winner: {value!r}")
    return winner


def _comparison_key(fmt: str, dimension: str, a_path: str, b_path: str) -> tuple[str, str, str, str]:
    return (
        fmt,
        dimension,
        _normalize_path_token(a_path),
        _normalize_path_token(b_path),
    )


def _normalize_path_token(value: str) -> str:
    path = Path(value)
    if path.exists():
        return str(path.resolve())
    return path.as_posix()


def _audit_record(source_path: Path, fmt: str, *, config: Any | None = None):
    if fmt == "pdf":
        from project_remedy.quality_judges.pdf.audit import audit_pdf_quality

        return audit_pdf_quality(source_path, config=config)
    if fmt in OFFICE_FORMATS:
        from project_remedy.quality_judges.office.audit import audit_office_quality

        return audit_office_quality(
            source_path,
            file_type=FileType(fmt),
            config=config,
        )
    raise ValueError(f"Unsupported annotation format: {fmt}")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _split_judge_versions(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if ":" in value:
            judge_id, judge_version = value.split(":", 1)
        else:
            judge_id, judge_version = value, "unknown"
        pairs.append((judge_id, judge_version))
    return pairs or [("unknown", "unknown")]


def _cmd_calibrate(args: argparse.Namespace) -> int:
    _validate_calibration_args(args)
    root = Path(args.root)
    records, annotation_errors = load_annotation_records(root)
    if annotation_errors:
        for error in annotation_errors:
            print(error, file=sys.stderr)
        return 2
    if not records:
        print(f"no annotation JSON files found under {root}", file=sys.stderr)
        return 1

    skipped: list[str] = []
    if args.judge_results:
        judge_rows = load_judge_result_rows(Path(args.judge_results))
        binding_errors = judge_result_binding_errors(records, judge_rows)
        if binding_errors:
            for error in binding_errors:
                print(error, file=sys.stderr)
            return 2
    else:
        judge_rows, skipped = run_audits_for_annotations(records)

    metrics = summarize_calibration(
        records,
        judge_rows,
        score_threshold=args.score_threshold,
    )
    comparison_rows: list[JudgeComparisonRow] = []
    if args.judge_comparisons:
        comparison_rows = load_judge_comparison_rows(Path(args.judge_comparisons))
        comparison_binding_errors = judge_comparison_binding_errors(records, comparison_rows)
        if comparison_binding_errors:
            for error in comparison_binding_errors:
                print(error, file=sys.stderr)
            return 2
        metrics.extend(
            summarize_pairwise_calibration(records, comparison_rows)
        )
    store = ExperimentStore(args.store)
    alert_metrics = list(metrics)
    if args.rolling_window > 1:
        alert_metrics = metrics_from_store_rows(store.list_judge_calibration()) + alert_metrics
    alerts = build_rolling_drift_alerts(
        alert_metrics,
        kappa_threshold=args.kappa_threshold,
        min_samples=args.min_samples,
        rolling_window=args.rolling_window,
    )
    readiness_errors = []
    if args.enforce_readiness:
        readiness_errors = calibration_readiness_errors(
            records,
            metrics,
            kappa_threshold=args.kappa_threshold,
            min_samples=args.min_samples,
        )
    if metrics and not args.dry_run:
        record_metrics(store, metrics)
    emit_drift_alerts(
        alerts,
        alert_log=Path(args.alert_log) if args.alert_log else None,
        webhook_url=args.alert_webhook or "",
    )

    payload = {
        "root": str(root),
        "metrics": [asdict(metric) for metric in metrics],
        "alerts": alerts,
        "skipped": skipped,
        "judge_comparison_rows": len(comparison_rows),
        "calibration_ready": bool(metrics) and not readiness_errors,
        "readiness_errors": readiness_errors,
        "recorded": bool(metrics and not args.dry_run),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"annotations: {len(records)}")
        print(f"judge rows: {len(judge_rows)}")
        print(f"judge comparison rows: {len(comparison_rows)}")
        print(f"metrics: {len(metrics)}")
        for metric in metrics:
            print(
                f"{metric.format}/{metric.dimension} "
                f"{metric.judge_id}:{metric.judge_version} "
                f"kappa={metric.cohens_kappa:.3f} n={metric.sample_size}"
            )
        for alert in alerts:
            print(
                "DRIFT_ALERT "
                f"format={alert['format']} dimension={alert['dimension']} "
                f"judge={alert['judge_id']}:{alert['judge_version']} "
                f"kappa={alert['cohens_kappa']:.3f}",
                file=sys.stderr,
            )
        for item in skipped:
            print(f"skipped: {item}", file=sys.stderr)
        for item in readiness_errors:
            print(f"readiness: {item}", file=sys.stderr)

    if not metrics:
        return 1
    if args.enforce_readiness and readiness_errors:
        return 1
    return 0


def _validate_calibration_args(args: argparse.Namespace) -> None:
    _require_unit_interval("score_threshold", args.score_threshold)
    _require_unit_interval("kappa_threshold", args.kappa_threshold)
    _require_positive_int("min_samples", args.min_samples)
    _require_positive_int("rolling_window", args.rolling_window)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibrate = subparsers.add_parser("calibrate", help="compute judge-human agreement")
    calibrate.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    calibrate.add_argument("--store", default="quality_experiments.db")
    calibrate.add_argument(
        "--judge-results",
        help=(
            "JSONL rows with doc_id, format, dimension, score, judge_id, judge_version, "
            "artifact_path, artifact_sha256, judge_model"
        ),
    )
    calibrate.add_argument(
        "--judge-comparisons",
        help=(
            "JSONL rows with format, dimension, a_path, b_path, winner, judge_id, "
            "judge_version, judge_model, and optional hashes"
        ),
    )
    calibrate.add_argument("--score-threshold", type=float, default=0.8)
    calibrate.add_argument("--kappa-threshold", type=float, default=DEFAULT_KAPPA_THRESHOLD)
    calibrate.add_argument("--min-samples", type=int, default=1)
    calibrate.add_argument(
        "--rolling-window",
        type=int,
        default=1,
        help="number of recent calibration measurements per judge slice used for drift alerts",
    )
    calibrate.add_argument("--alert-log", help="append structured drift alerts to JSONL")
    calibrate.add_argument("--alert-webhook", help="optional webhook URL for drift alerts")
    calibrate.add_argument(
        "--enforce-readiness",
        action="store_true",
        help="fail unless every registered judge/version for annotated formats meets thresholds",
    )
    calibrate.add_argument("--dry-run", action="store_true")
    calibrate.add_argument("--json", action="store_true")
    calibrate.set_defaults(func=_cmd_calibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI prints concise failures.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
