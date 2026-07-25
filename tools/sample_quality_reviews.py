"""Sample quality review candidates into the specialist queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)
from project_remedy.vision_planner.experiment_store import ExperimentRecord, ExperimentStore

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
QUALITY_DIMENSION_SET = set(ALL_QUALITY_DIMENSIONS)


@dataclass(frozen=True)
class ReviewCandidate:
    """One document candidate for specialist quality review."""

    doc_id: str
    format: str
    source_path: str = ""
    source_sha256: str = ""
    document_class: str = ""
    quality_dimensions: dict[str, float] = field(default_factory=dict)
    dimension_variance: dict[str, float] = field(default_factory=dict)
    behavioral_confidence: dict[str, float] = field(default_factory=dict)


def load_candidates_jsonl(path: Path) -> list[ReviewCandidate]:
    """Load review candidates from JSONL."""
    candidates: list[ReviewCandidate] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        candidates.append(_candidate_from_payload(payload, source=f"{path}:{line_number}"))
    return candidates


def sample_review_candidates(
    candidates: Iterable[ReviewCandidate],
    *,
    limit: int,
    random_fraction: float = 0.2,
    salt: str = "quality-review-v1",
) -> list[dict[str, Any]]:
    """Select candidates with priority strata plus deterministic random coverage."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if (
        isinstance(random_fraction, bool)
        or not isinstance(random_fraction, (int, float))
        or not math.isfinite(float(random_fraction))
    ):
        raise ValueError("random_fraction must be finite")
    if random_fraction < 0 or random_fraction > 1:
        raise ValueError("random_fraction must be between 0 and 1")

    items = [
        _validate_review_candidate(candidate, source=f"candidate {index}")
        for index, candidate in enumerate(candidates, 1)
    ]
    if not items:
        return []

    random_quota = min(len(items), int(round(limit * random_fraction)))
    priority_quota = max(0, limit - random_quota)

    priority_sorted = sorted(
        items,
        key=lambda item: (
            candidate_priority(item),
            _stable_unit_interval(f"{salt}:priority:{_candidate_identity_token(item)}"),
        ),
        reverse=True,
    )
    selected: list[ReviewCandidate] = priority_sorted[:priority_quota]
    selected_identities = {_candidate_identity(item) for item in selected}

    random_sorted = sorted(
        [item for item in items if _candidate_identity(item) not in selected_identities],
        key=lambda item: _stable_unit_interval(f"{salt}:random:{_candidate_identity_token(item)}"),
    )
    selected.extend(random_sorted[: max(0, limit - len(selected))])

    sampled_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "doc_id": item.doc_id,
            "format": item.format,
            "source_path": item.source_path,
            "source_sha256": item.source_sha256,
            "document_class": item.document_class,
            "weak_dimensions": [
                dimension
                for dimension, score in item.quality_dimensions.items()
                if score < 0.8
            ],
            "priority_score": round(candidate_priority(item), 4),
            "priority_reasons": candidate_priority_reasons(item),
            "sampled_at": sampled_at,
            "status": "queued",
        }
        for item in selected[:limit]
    ]


def candidates_from_experiments(
    experiments: Iterable[ExperimentRecord],
    *,
    fmt: str | None = "pdf",
) -> list[ReviewCandidate]:
    """Build review candidates from stored quality experiment records."""
    candidates: list[ReviewCandidate] = []
    for experiment in experiments:
        if not experiment.quality_dimensions and not experiment.behavioral_results:
            continue
        experiment_format = _canonical_format(experiment.document_format)
        if fmt is not None:
            requested_format = _canonical_format(fmt)
            if experiment_format != requested_format:
                continue
            candidate_format = requested_format
        else:
            candidate_format = experiment_format
        candidates.append(
            ReviewCandidate(
                doc_id=experiment.document_hash,
                format=candidate_format,
                document_class=experiment.document_type,
                quality_dimensions=_coerce_dimension_scores(
                    experiment.quality_dimensions,
                    key="quality_dimensions",
                    fmt=candidate_format,
                    source=f"experiment {experiment.experiment_id}",
                ),
                behavioral_confidence=_coerce_behavioral_confidence(
                    {
                        test_name: 1.0 if passed else 0.0
                        for test_name, passed in experiment.behavioral_results.items()
                    },
                    fmt=candidate_format,
                    source=f"experiment {experiment.experiment_id}",
                ),
            )
        )
    return candidates


def candidate_priority(candidate: ReviewCandidate) -> float:
    """Compute deterministic review priority from PRD sampling signals."""
    weak_dimension_count = sum(
        1 for score in candidate.quality_dimensions.values() if score < 0.8
    )
    max_variance = max(candidate.dimension_variance.values(), default=0.0)
    low_confidence_gap = max(
        (1.0 - confidence for confidence in candidate.behavioral_confidence.values()),
        default=0.0,
    )
    return (weak_dimension_count * 2.0) + (max_variance * 4.0) + low_confidence_gap


def candidate_priority_reasons(candidate: ReviewCandidate) -> list[str]:
    """Return human-readable reasons a candidate was sampled."""
    reasons: list[str] = []
    weak = [
        dimension
        for dimension, score in candidate.quality_dimensions.items()
        if score < 0.8
    ]
    if weak:
        reasons.append(f"weak_dimensions:{','.join(sorted(weak))}")
    high_variance = [
        dimension
        for dimension, variance in candidate.dimension_variance.items()
        if variance >= 0.05
    ]
    if high_variance:
        reasons.append(f"high_variance:{','.join(sorted(high_variance))}")
    low_confidence = [
        name
        for name, confidence in candidate.behavioral_confidence.items()
        if confidence < 0.5
    ]
    if low_confidence:
        reasons.append(f"low_behavioral_confidence:{','.join(sorted(low_confidence))}")
    return reasons or ["random_stratum"]


def _canonical_format(fmt: str) -> str:
    if not isinstance(fmt, str) or not fmt.strip():
        raise ValueError("format must be a non-empty string")
    if fmt != fmt.strip().lower():
        raise ValueError("format must be canonical")
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"unsupported format: {fmt}")
    return fmt


def append_queue_items(queue_path: Path, items: Iterable[dict[str, Any]]) -> int:
    """Append sampled items to the JSONL specialist queue."""
    new_items = list(items)
    for item in new_items:
        _validate_queue_item_for_append(item)
    rows = _dedupe_new_queue_items(_load_existing_queue_items(queue_path), new_items)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    return len(rows)


def _load_existing_queue_items(queue_path: Path) -> list[dict[str, Any]]:
    if not queue_path.exists():
        return []
    existing: list[dict[str, Any]] = []
    for line_number, line in enumerate(queue_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{queue_path}: invalid JSON at line {line_number}: {exc}"
            ) from exc
        if not isinstance(item, dict):
            raise ValueError(f"{queue_path}: row {line_number} must be an object")
        _validate_existing_queue_item(item, path=queue_path, line_number=line_number)
        existing.append(item)
    return existing


def _dedupe_new_queue_items(
    existing: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {
        _queue_identity(item)
        for item in existing
        if item.get("status") != "completed"
    }
    deduped: list[dict[str, Any]] = []
    for item in rows:
        identity = _queue_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(item)
    return deduped


def _queue_identity(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("format", "")), str(item.get("doc_id", "")))


def _validate_queue_item_for_append(item: dict[str, Any]) -> None:
    if not isinstance(item, dict):
        raise ValueError("queue item must be an object")
    doc_id = item.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise ValueError("queue item doc_id is required")
    fmt = item.get("format")
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"queue item unsupported format: {fmt}")
    for field_name in ("source_path", "document_class"):
        if field_name in item and not isinstance(item[field_name], str):
            raise ValueError(f"queue item {field_name} must be a string")
    status = item.get("status")
    if status is not None and status != "queued":
        raise ValueError("queue item status must be queued when provided")
    source_sha256 = item.get("source_sha256", "")
    if not isinstance(source_sha256, str):
        raise ValueError("queue item source_sha256 must be a sha256 hex digest")
    if source_sha256 and not SHA256_RE.match(source_sha256):
        raise ValueError("queue item source_sha256 must be a sha256 hex digest")
    if "priority_score" in item:
        _validate_queue_priority_score(item["priority_score"])
    if "priority_reasons" in item:
        _validate_queue_string_list(
            item["priority_reasons"],
            field_name="priority_reasons",
        )
    if "sampled_at" in item:
        _validate_queue_datetime(item["sampled_at"], field_name="sampled_at")
    weak_dimensions = item.get("weak_dimensions", [])
    if not isinstance(weak_dimensions, list):
        raise ValueError("queue item weak_dimensions must be a list")
    _validate_queue_string_list(weak_dimensions, field_name="weak_dimensions")
    if len(set(weak_dimensions)) != len(weak_dimensions):
        raise ValueError("queue item weak_dimensions must not contain duplicates")
    unsupported = sorted(
        set(weak_dimensions) - set(DIMENSIONS_BY_FORMAT[str(fmt)])
    )
    if unsupported:
        raise ValueError(
            f"queue item weak_dimensions contains dimension(s) not applicable to {fmt}: "
            + ", ".join(unsupported)
        )


def _validate_existing_queue_item(
    item: dict[str, Any],
    *,
    path: Path,
    line_number: int,
) -> None:
    try:
        _validate_existing_queue_item_payload(item)
    except ValueError as exc:
        raise ValueError(f"{path}: row {line_number} invalid: {exc}") from exc


def _validate_existing_queue_item_payload(item: dict[str, Any]) -> None:
    doc_id = item.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise ValueError("doc_id is required")
    fmt = item.get("format")
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"unsupported format: {fmt}")
    status = item.get("status", "queued")
    if not isinstance(status, str) or status not in {"queued", "claimed", "completed"}:
        raise ValueError("status must be queued, claimed, or completed")
    for field_name in ("source_path", "document_class"):
        if field_name in item and not isinstance(item[field_name], str):
            raise ValueError(f"{field_name} must be a string")
    for field_name in ("claimed_by", "completed_by"):
        if field_name in item and (
            not isinstance(item[field_name], str) or not item[field_name].strip()
        ):
            raise ValueError(f"{field_name} must be a non-empty string")
    if status == "claimed":
        if not isinstance(item.get("claimed_by"), str) or not item["claimed_by"].strip():
            raise ValueError("claimed_by is required for claimed status")
        if "claimed_at" not in item:
            raise ValueError("claimed_at is required for claimed status")
    if status == "completed" and "completed_at" not in item:
        raise ValueError("completed_at is required for completed status")
    source_sha256 = item.get("source_sha256", "")
    if not isinstance(source_sha256, str):
        raise ValueError("source_sha256 must be a sha256 hex digest")
    if source_sha256 and not SHA256_RE.match(source_sha256):
        raise ValueError("source_sha256 must be a sha256 hex digest")
    if "priority_score" in item:
        _validate_queue_priority_score(item["priority_score"])
    if "priority_reasons" in item:
        _validate_queue_string_list(
            item["priority_reasons"],
            field_name="priority_reasons",
        )
    for field_name in ("sampled_at", "claimed_at", "completed_at"):
        if field_name in item:
            _validate_queue_datetime(item[field_name], field_name=field_name)
    weak_dimensions = item.get("weak_dimensions", [])
    if not isinstance(weak_dimensions, list):
        raise ValueError("weak_dimensions must be a list")
    _validate_queue_string_list(weak_dimensions, field_name="weak_dimensions")
    if len(set(weak_dimensions)) != len(weak_dimensions):
        raise ValueError("weak_dimensions must not contain duplicates")
    unsupported = sorted(set(weak_dimensions) - set(DIMENSIONS_BY_FORMAT[str(fmt)]))
    if unsupported:
        raise ValueError(
            "weak_dimensions contains dimension(s) not applicable to "
            f"{fmt}: {', '.join(unsupported)}"
        )


def _validate_queue_priority_score(value: Any) -> None:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("queue item priority_score must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError("queue item priority_score must be finite")
    if numeric < 0.0:
        raise ValueError("queue item priority_score must be non-negative")


def _validate_queue_string_list(value: Any, *, field_name: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"queue item {field_name} must be a list")
    invalid = [
        item
        for item in value
        if not isinstance(item, str) or not item.strip()
    ]
    if invalid:
        raise ValueError(f"queue item {field_name} must contain non-empty strings")


def _validate_queue_datetime(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"queue item {field_name} must be an ISO date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"queue item {field_name} must be an ISO date-time string"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"queue item {field_name} must include a timezone")


def _candidate_identity(candidate: ReviewCandidate) -> tuple[str, str]:
    return (candidate.format, candidate.doc_id)


def _candidate_identity_token(candidate: ReviewCandidate) -> str:
    return f"{candidate.format}:{candidate.doc_id}"


def _candidate_from_payload(payload: dict[str, Any], *, source: str) -> ReviewCandidate:
    if not isinstance(payload, dict):
        raise ValueError(f"{source}: row must be an object")
    doc_id = _required_candidate_string(payload, "doc_id", source=source)
    if payload.get("format") not in {"pdf", "docx", "pptx", "xlsx"}:
        raise ValueError(f"{source}: unsupported format")
    fmt = str(payload["format"])
    source_path = _optional_candidate_string(payload, "source_path", source=source)
    source_sha256 = _candidate_source_sha256(
        source_path=source_path,
        provided=_optional_candidate_string(payload, "source_sha256", source=source),
        source=source,
    )
    return ReviewCandidate(
        doc_id=doc_id,
        format=fmt,
        source_path=source_path,
        source_sha256=source_sha256,
        document_class=_optional_candidate_string(
            payload,
            "document_class",
            source=source,
        ),
        quality_dimensions=_load_dimension_scores(
            payload,
            key="quality_dimensions",
            fmt=fmt,
            source=source,
        ),
        dimension_variance=_load_dimension_scores(
            payload,
            key="dimension_variance",
            fmt=fmt,
            source=source,
        ),
        behavioral_confidence=_load_behavioral_confidence(
            payload,
            fmt=fmt,
            source=source,
        ),
    )


def _required_candidate_string(
    payload: dict[str, Any],
    key: str,
    *,
    source: str,
) -> str:
    return _required_string_value(payload.get(key), key, source=source)


def _required_string_value(value: Any, field_name: str, *, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field_name} is required")
    return value


def _optional_candidate_string(
    payload: dict[str, Any],
    key: str,
    *,
    source: str,
) -> str:
    if key not in payload:
        return ""
    return _optional_string_value(payload[key], key, source=source)


def _optional_string_value(value: Any, field_name: str, *, source: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{source}: {field_name} must be a string")
    return value


def _validate_review_candidate(candidate: Any, *, source: str) -> ReviewCandidate:
    if not isinstance(candidate, ReviewCandidate):
        raise ValueError(f"{source}: must be a ReviewCandidate")
    doc_id = _required_string_value(candidate.doc_id, "doc_id", source=source)
    fmt = _required_string_value(candidate.format, "format", source=source)
    if fmt not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"{source}: unsupported format")
    source_path = _optional_string_value(
        candidate.source_path,
        "source_path",
        source=source,
    )
    source_sha256 = _candidate_source_sha256(
        source_path=source_path,
        provided=_optional_string_value(
            candidate.source_sha256,
            "source_sha256",
            source=source,
        ),
        source=source,
    )
    return ReviewCandidate(
        doc_id=doc_id,
        format=fmt,
        source_path=source_path,
        source_sha256=source_sha256,
        document_class=_optional_string_value(
            candidate.document_class,
            "document_class",
            source=source,
        ),
        quality_dimensions=_coerce_dimension_scores(
            candidate.quality_dimensions,
            key="quality_dimensions",
            fmt=fmt,
            source=source,
        ),
        dimension_variance=_coerce_dimension_scores(
            candidate.dimension_variance,
            key="dimension_variance",
            fmt=fmt,
            source=source,
        ),
        behavioral_confidence=_coerce_behavioral_confidence(
            candidate.behavioral_confidence,
            fmt=fmt,
            source=source,
        ),
    )


def _load_dimension_scores(
    payload: dict[str, Any],
    *,
    key: str,
    fmt: str,
    source: str,
) -> dict[str, float]:
    raw_value = payload[key] if key in payload else {}
    return _coerce_dimension_scores(raw_value, key=key, fmt=fmt, source=source)


def _coerce_dimension_scores(
    raw_value: Any,
    *,
    key: str,
    fmt: str,
    source: str,
) -> dict[str, float]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{source}: {key} must be an object")
    invalid_dimensions = [
        dimension
        for dimension in raw_value
        if not isinstance(dimension, str) or not dimension.strip()
    ]
    if invalid_dimensions:
        raise ValueError(f"{source}: {key} keys must be non-empty strings")
    unsupported = sorted(
        set(raw_value) - set(DIMENSIONS_BY_FORMAT[fmt])
    )
    if unsupported:
        raise ValueError(
            f"{source}: {key} contains dimension(s) not applicable to {fmt}: "
            + ", ".join(unsupported)
        )
    scores: dict[str, float] = {}
    for dimension, score in raw_value.items():
        try:
            if isinstance(score, bool):
                raise TypeError
            numeric = float(score)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{source}: {key}.{dimension} must be numeric"
            ) from exc
        if not math.isfinite(numeric):
            raise ValueError(
                f"{source}: {key}.{dimension} must be finite"
            )
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError(
                f"{source}: {key}.{dimension} must be between 0.0 and 1.0"
            )
        scores[str(dimension)] = numeric
    return scores


def _load_behavioral_confidence(
    payload: dict[str, Any],
    *,
    fmt: str,
    source: str,
) -> dict[str, float]:
    raw_value = payload["behavioral_confidence"] if "behavioral_confidence" in payload else {}
    return _coerce_behavioral_confidence(raw_value, fmt=fmt, source=source)


def _coerce_behavioral_confidence(
    raw_value: Any,
    *,
    fmt: str,
    source: str,
) -> dict[str, float]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{source}: behavioral_confidence must be an object")
    confidence: dict[str, float] = {}
    for test_name, value in raw_value.items():
        if not isinstance(test_name, str) or not test_name.strip():
            raise ValueError(
                f"{source}: behavioral_confidence keys must be non-empty strings"
            )
        if test_name != test_name.strip():
            raise ValueError(
                f"{source}: behavioral_confidence keys must be canonical test names"
            )
        dimension = dimension_from_behavioral_test(test_name)
        if dimension not in QUALITY_DIMENSION_SET:
            raise ValueError(
                f"{source}: unsupported behavioral confidence test: {test_name}"
            )
        if dimension not in DIMENSIONS_BY_FORMAT[fmt]:
            raise ValueError(
                f"{source}: behavioral confidence {test_name!r} maps to dimension "
                f"{dimension!r}, which is not applicable to {fmt}"
            )
        try:
            if isinstance(value, bool):
                raise TypeError
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{source}: behavioral_confidence.{test_name} must be numeric"
            ) from exc
        if not math.isfinite(numeric):
            raise ValueError(
                f"{source}: behavioral_confidence.{test_name} must be finite"
            )
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError(
                f"{source}: behavioral_confidence.{test_name} must be between 0.0 and 1.0"
            )
        confidence[test_name] = numeric
    return confidence


def _candidate_source_sha256(*, source_path: str, provided: str, source: str) -> str:
    if provided and not SHA256_RE.match(provided):
        raise ValueError(f"{source}: source_sha256 must be a sha256 hex digest")
    path = Path(source_path)
    if not source_path or not path.exists():
        return provided
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if provided and provided != actual:
        raise ValueError(f"{source}: source_sha256 must match source_path bytes")
    return actual


def _stable_unit_interval(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / float(0xFFFFFFFFFFFFFFFF)


def _cmd_sample(args: argparse.Namespace) -> int:
    candidates = load_candidates_jsonl(Path(args.input))
    if args.format:
        candidates = [candidate for candidate in candidates if candidate.format == args.format]
    return _sample_to_queue(candidates, args)


def _cmd_sample_experiments(args: argparse.Namespace) -> int:
    store = ExperimentStore(Path(args.store))
    candidates = candidates_from_experiments(
        store.get_experiments_for_harness(args.harness_id),
        fmt=args.format,
    )
    return _sample_to_queue(candidates, args)


def _sample_to_queue(candidates: Iterable[ReviewCandidate], args: argparse.Namespace) -> int:
    sampled = sample_review_candidates(
        candidates,
        limit=args.limit,
        random_fraction=args.random_fraction,
        salt=args.salt,
    )
    written = 0
    if not args.dry_run:
        written = append_queue_items(Path(args.queue), sampled)
    payload = {"sampled": sampled, "written": written, "dry_run": args.dry_run}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"sampled: {len(sampled)}")
        print(f"written: {written}")
        for item in sampled:
            print(f"{item['doc_id']} {item['format']} {item['priority_reasons']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="sample candidates into review queue")
    sample.add_argument("--input", required=True, help="candidate JSONL path")
    sample.add_argument("--queue", default="./quality_review_queue.jsonl")
    sample.add_argument("--format", choices=("pdf", "docx", "pptx", "xlsx"))
    sample.add_argument("--limit", type=int, default=50)
    sample.add_argument("--random-fraction", type=float, default=0.2)
    sample.add_argument("--salt", default="quality-review-v1")
    sample.add_argument("--dry-run", action="store_true")
    sample.add_argument("--json", action="store_true")
    sample.set_defaults(func=_cmd_sample)

    sample_experiments = subparsers.add_parser(
        "sample-experiments",
        help="sample review candidates from ExperimentStore quality records",
    )
    sample_experiments.add_argument("--store", required=True, help="experiment SQLite path")
    sample_experiments.add_argument("--harness-id", required=True)
    sample_experiments.add_argument("--queue", default="./quality_review_queue.jsonl")
    sample_experiments.add_argument("--format", choices=("pdf", "docx", "pptx", "xlsx"))
    sample_experiments.add_argument("--limit", type=int, default=50)
    sample_experiments.add_argument("--random-fraction", type=float, default=0.2)
    sample_experiments.add_argument("--salt", default="quality-review-v1")
    sample_experiments.add_argument("--dry-run", action="store_true")
    sample_experiments.add_argument("--json", action="store_true")
    sample_experiments.set_defaults(func=_cmd_sample_experiments)

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
