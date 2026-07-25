"""Deployment gate for calibrated quality-layer execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from backend.app.config import Settings
from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT
from project_remedy.quality_judges.shared.registry import required_judge_calibrations
from project_remedy.vision_planner.experiment_store import ExperimentStore


class QualityCalibrationError(RuntimeError):
    """Raised when quality execution is required to be calibrated but is not."""


@dataclass(frozen=True)
class QualityCalibrationStatus:
    """Readiness status for calibrated judges in one format."""

    format: str
    ready: bool
    required: bool
    min_cohens_kappa: float
    min_sample_size: int
    required_dimensions: list[str] = field(default_factory=list)
    required_judges: list[dict[str, str]] = field(default_factory=list)
    calibrated_dimensions: list[str] = field(default_factory=list)
    calibrated_judges: list[dict[str, str]] = field(default_factory=list)
    missing_dimensions: list[str] = field(default_factory=list)
    missing_judges: list[dict[str, str]] = field(default_factory=list)
    below_threshold: list[dict[str, Any]] = field(default_factory=list)
    stale_calibrations: list[dict[str, Any]] = field(default_factory=list)
    malformed_calibrations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "ready": self.ready,
            "required": self.required,
            "min_cohens_kappa": self.min_cohens_kappa,
            "min_sample_size": self.min_sample_size,
            "required_dimensions": self.required_dimensions,
            "required_judges": self.required_judges,
            "calibrated_dimensions": self.calibrated_dimensions,
            "calibrated_judges": self.calibrated_judges,
            "missing_dimensions": self.missing_dimensions,
            "missing_judges": self.missing_judges,
            "below_threshold": self.below_threshold,
            "stale_calibrations": self.stale_calibrations,
            "malformed_calibrations": self.malformed_calibrations,
        }


def quality_calibration_status(settings: Settings, fmt: str) -> QualityCalibrationStatus:
    """Return whether every applicable dimension has an acceptable calibration row."""
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise QualityCalibrationError(f"unsupported quality calibration format: {fmt}")

    required_dimensions = list(DIMENSIONS_BY_FORMAT[fmt])
    requirements = list(required_judge_calibrations(fmt))
    store = ExperimentStore(settings.quality_experiment_store_path)
    rows = store.list_judge_calibration(format=fmt)
    calibrated_judges: list[dict[str, str]] = []
    missing_judges: list[dict[str, str]] = []
    below_threshold: list[dict[str, Any]] = []
    stale_calibrations: list[dict[str, Any]] = []
    malformed_calibrations: list[dict[str, Any]] = []
    calibrated_by_dimension: dict[str, set[str]] = {
        dimension: set() for dimension in required_dimensions
    }
    required_by_dimension: dict[str, set[str]] = {
        dimension: set() for dimension in required_dimensions
    }

    for requirement in requirements:
        judge_key = f"{requirement.judge_id}:{requirement.judge_version}"
        required_by_dimension.setdefault(requirement.dimension, set()).add(judge_key)
        matching_rows = [
            row
            for row in rows
            if row["dimension"] == requirement.dimension
            and row["judge_id"] == requirement.judge_id
            and row["judge_version"] == requirement.judge_version
        ]
        if not matching_rows:
            missing_judges.append(requirement.to_dict())
            continue

        latest = matching_rows[0]
        malformed_reason = _malformed_calibration_reason(latest)
        if malformed_reason:
            malformed_calibrations.append(
                {
                    "dimension": requirement.dimension,
                    "judge_id": requirement.judge_id,
                    "judge_version": requirement.judge_version,
                    "format": requirement.format,
                    "measured_at": latest.get("measured_at"),
                    "reason": malformed_reason,
                }
            )
            continue
        stale_reason = _stale_calibration_reason(settings, latest)
        if stale_reason:
            stale_calibrations.append(
                {
                    "dimension": requirement.dimension,
                    "judge_id": requirement.judge_id,
                    "judge_version": requirement.judge_version,
                    "format": requirement.format,
                    "measured_at": latest["measured_at"],
                    "max_age_days": settings.quality_max_calibration_age_days,
                    "reason": stale_reason,
                }
            )
            continue
        if (
            latest["cohens_kappa"] >= settings.quality_min_cohens_kappa
            and latest["sample_size"] >= settings.quality_min_calibration_samples
        ):
            calibrated_judges.append(requirement.to_dict())
            calibrated_by_dimension.setdefault(requirement.dimension, set()).add(judge_key)
            continue

        below_threshold.append(
            {
                "dimension": requirement.dimension,
                "judge_id": requirement.judge_id,
                "judge_version": requirement.judge_version,
                "format": requirement.format,
                "cohens_kappa": latest["cohens_kappa"],
                "sample_size": latest["sample_size"],
                "measured_at": latest["measured_at"],
            }
        )

    missing_dimensions = sorted(
        {
            requirement["dimension"]
            for requirement in missing_judges
        }
    )
    calibrated_dimensions = sorted(
        dimension
        for dimension, required in required_by_dimension.items()
        if required and calibrated_by_dimension.get(dimension, set()) == required
    )
    below_dimensions = {row["dimension"] for row in below_threshold}
    calibrated_dimensions = [
        dimension
        for dimension in calibrated_dimensions
        if dimension not in below_dimensions
    ]

    if not requirements:
        for dimension in required_dimensions:
            rows_for_dimension = [
                row for row in rows if row["dimension"] == dimension
            ]
            if not rows_for_dimension:
                missing_dimensions.append(dimension)
                continue
            latest = rows_for_dimension[0]
            malformed_reason = _malformed_calibration_reason(latest)
            if malformed_reason:
                malformed_calibrations.append(
                    {
                        "dimension": dimension,
                        "format": fmt,
                        "judge_id": latest.get("judge_id"),
                        "judge_version": latest.get("judge_version"),
                        "measured_at": latest.get("measured_at"),
                        "reason": malformed_reason,
                    }
                )
                continue
            stale_reason = _stale_calibration_reason(settings, latest)
            if stale_reason:
                stale_calibrations.append(
                    {
                        "dimension": dimension,
                        "format": fmt,
                        "judge_id": latest["judge_id"],
                        "judge_version": latest["judge_version"],
                        "measured_at": latest["measured_at"],
                        "max_age_days": settings.quality_max_calibration_age_days,
                        "reason": stale_reason,
                    }
                )
                continue
            if (
                latest["cohens_kappa"] >= settings.quality_min_cohens_kappa
                and latest["sample_size"] >= settings.quality_min_calibration_samples
            ):
                calibrated_dimensions.append(dimension)
                continue
            below_threshold.append(
                {
                    "dimension": dimension,
                    "format": fmt,
                    "judge_id": latest["judge_id"],
                    "judge_version": latest["judge_version"],
                    "cohens_kappa": latest["cohens_kappa"],
                    "sample_size": latest["sample_size"],
                    "measured_at": latest["measured_at"],
                }
            )

    return QualityCalibrationStatus(
        format=fmt,
        ready=(
            not missing_dimensions
            and not missing_judges
            and not below_threshold
            and not stale_calibrations
            and not malformed_calibrations
        ),
        required=settings.quality_require_calibration,
        min_cohens_kappa=settings.quality_min_cohens_kappa,
        min_sample_size=settings.quality_min_calibration_samples,
        required_dimensions=required_dimensions,
        required_judges=[requirement.to_dict() for requirement in requirements],
        calibrated_dimensions=calibrated_dimensions,
        calibrated_judges=calibrated_judges,
        missing_dimensions=missing_dimensions,
        missing_judges=missing_judges,
        below_threshold=below_threshold,
        stale_calibrations=stale_calibrations,
        malformed_calibrations=malformed_calibrations,
    )


def _summarize_rows(
    label: str,
    rows: list[dict[str, Any]],
    formatter,
    *,
    limit: int | None = 8,
) -> str | None:
    """Render ``rows`` as ``"label: a, b, c, +N more"`` or ``None`` if empty."""
    if not rows:
        return None
    if limit is None or len(rows) <= limit:
        rendered = ", ".join(formatter(row) for row in rows)
    else:
        rendered = ", ".join(formatter(row) for row in rows[:limit])
        rendered += f", +{len(rows) - limit} more"
    return f"{label}: {rendered}"


def assert_quality_calibrated(settings: Settings, fmt: str | None = None) -> None:
    """Raise when deployment settings require calibration and it is incomplete."""
    if not settings.quality_require_calibration:
        return
    formats = [fmt] if fmt else sorted(DIMENSIONS_BY_FORMAT)
    failure_messages: list[str] = []

    for format_name in formats:
        status = quality_calibration_status(settings, format_name)
        if status.ready:
            continue
        parts = [
            _summarize_rows(
                "missing judges",
                status.missing_judges,
                lambda row: (
                    f"{row['judge_id']}:{row['judge_version']}({row['dimension']})"
                ),
            ),
            (
                "missing dimensions: " + ", ".join(status.missing_dimensions)
                if status.missing_dimensions
                else None
            ),
            # below_threshold is intentionally not truncated to keep operator-facing
            # detail comprehensive when only a handful of judges are weak.
            _summarize_rows(
                "below threshold",
                status.below_threshold,
                lambda row: (
                    f"{row['dimension']} kappa={row['cohens_kappa']} n={row['sample_size']}"
                ),
                limit=None,
            ),
            _summarize_rows(
                "stale calibration",
                status.stale_calibrations,
                lambda row: f"{row['dimension']} measured_at={row['measured_at']}",
            ),
            _summarize_rows(
                "malformed calibration",
                status.malformed_calibrations,
                lambda row: f"{row['dimension']} reason={row['reason']}",
            ),
        ]
        detail = "; ".join(part for part in parts if part) or "no applicable dimensions calibrated"
        failure_messages.append(
            f"{format_name}: {detail}"
        )

    if not failure_messages:
        return

    raise QualityCalibrationError(
        "Quality layer is not calibrated for "
        f"{'; '.join(failure_messages)}. Run tools/calibrate_judges.py and meet "
        f"kappa >= {settings.quality_min_cohens_kappa} before enabling active quality execution."
    )


def _malformed_calibration_reason(row: dict[str, Any]) -> str:
    """Return a shape/type failure reason for a persisted calibration row."""
    cohens_kappa = row.get("cohens_kappa")
    if isinstance(cohens_kappa, bool) or not isinstance(cohens_kappa, int | float):
        return "cohens_kappa must be numeric"
    if not math.isfinite(float(cohens_kappa)):
        return "cohens_kappa must be finite"
    if float(cohens_kappa) < 0.0 or float(cohens_kappa) > 1.0:
        return "cohens_kappa must be between 0 and 1"

    sample_size = row.get("sample_size")
    if isinstance(sample_size, bool) or not isinstance(sample_size, int):
        return "sample_size must be a positive integer"
    if sample_size <= 0:
        return "sample_size must be a positive integer"

    measured_at = row.get("measured_at")
    if not isinstance(measured_at, str) or not measured_at.strip():
        return "measured_at must be an ISO date-time string"
    try:
        parsed = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    except ValueError:
        return "measured_at must be an ISO date-time string"
    if parsed.tzinfo is None:
        return "measured_at must include a timezone"
    return ""


def _stale_calibration_reason(settings: Settings, row: dict[str, Any]) -> str:
    """Return a freshness failure reason for a calibration row, or empty string."""
    max_age_days = settings.quality_max_calibration_age_days
    if max_age_days <= 0:
        return ""
    raw = str(row.get("measured_at") or "")
    try:
        measured_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "measured_at is not an ISO date-time"
    if measured_at.tzinfo is None:
        return "measured_at has no timezone"
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    if measured_at.astimezone(timezone.utc) < cutoff:
        return f"older than {max_age_days} day(s)"
    return ""
