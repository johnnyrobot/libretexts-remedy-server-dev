"""Format-aware annotation CLI for the Remedy quality reference corpus.

This tool captures specialist judgments for the quality-layer corpus defined
in ``v2_docs/document-remediation-prd.md``. It intentionally does not generate
gold judgments with a model; it records human-supplied scores and notes in a
stable JSON format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT


SUPPORTED_FORMATS = tuple(DIMENSIONS_BY_FORMAT)
OFFICE_FORMATS = tuple(fmt for fmt in SUPPORTED_FORMATS if fmt != "pdf")

DEFAULT_CORPUS_ROOT = SCRIPT_DIR / "corpus_annotations" / "v1"
SCHEMA_PATH = SCRIPT_DIR / "corpus_annotations" / "schema.json"

PHASE_A_DEFAULT_MINIMUMS = {
    "total": 50,
    "pdf": 30,
    "office": 20,
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _canonical_manifest_annotation_path(path_value: str, *, root: Path) -> str:
    """Normalize manifest annotation paths for comparison and drift checks."""
    value = (path_value or "").strip()
    if not value:
        return ""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    candidate = root / path
    return str(candidate.resolve()) if candidate.exists() else str(path.resolve())


def _require_non_negative_int(name: str, value: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if numeric < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return numeric


@dataclass(frozen=True)
class ValidationError:
    """One annotation validation problem."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load the version-controlled JSON Schema document."""
    return json.loads(path.read_text(encoding="utf-8"))


def infer_format(source_path: Path, explicit: str | None = None) -> str:
    """Resolve the corpus format from an explicit value or file suffix."""
    if explicit:
        fmt = explicit.lower().strip()
    else:
        fmt = source_path.suffix.lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        accepted = ", ".join(SUPPORTED_FORMATS)
        raise ValueError(f"Unsupported format '{fmt}'. Expected one of: {accepted}")
    return fmt


def parse_dimension_scores(values: Iterable[str]) -> dict[str, float]:
    """Parse repeated ``dimension=0.92`` CLI arguments."""
    scores: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Score must be dimension=value, got: {value}")
        dimension, raw_score = value.split("=", 1)
        dimension = dimension.strip()
        try:
            score = float(raw_score.strip())
        except ValueError as exc:
            raise ValueError(f"Score for {dimension!r} is not numeric") from exc
        if not math.isfinite(score):
            raise ValueError(f"Score for {dimension!r} must be finite")
        scores[dimension] = score
    return scores


def parse_dimension_notes(values: Iterable[str]) -> dict[str, str]:
    """Parse repeated ``dimension=notes`` CLI arguments."""
    notes: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Note must be dimension=text, got: {value}")
        dimension, note = value.split("=", 1)
        notes[dimension.strip()] = note.strip()
    return notes


def parse_pairwise_comparisons(values: Iterable[str]) -> list[dict[str, Any]]:
    """Parse repeated pairwise comparison JSON objects."""
    comparisons: list[dict[str, Any]] = []
    required = {"a_path", "b_path", "winner", "dimension", "rationale"}
    for value in values:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Pairwise comparison must be JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Pairwise comparison must be a JSON object")
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"Pairwise comparison missing fields: {', '.join(missing)}")
        comparisons.append(payload)
    return comparisons


def parse_format_specific_items(values: Iterable[str], *, item_name: str) -> list[dict[str, Any]]:
    """Parse repeated format-specific JSON objects for nested Office annotations."""
    items: list[dict[str, Any]] = []
    for value in values:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{item_name} annotation must be JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{item_name} annotation must be a JSON object")
        items.append(payload)
    return items


def prompt_dimension_judgments(
    *,
    dimensions: Iterable[str],
    existing_scores: dict[str, float] | None = None,
    existing_notes: dict[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Prompt an annotator for missing per-dimension scores and notes."""
    input_fn = input_fn or input
    scores = dict(existing_scores or {})
    notes = dict(existing_notes or {})
    for dimension in dimensions:
        while dimension not in scores:
            raw = input_fn(f"{dimension} score (0.0-1.0): ").strip()
            try:
                score = float(raw)
            except ValueError:
                print("Score must be numeric.", file=sys.stderr)
                continue
            if not math.isfinite(score):
                print("Score must be finite.", file=sys.stderr)
                continue
            if score < 0 or score > 1:
                print("Score must be between 0 and 1.", file=sys.stderr)
                continue
            scores[dimension] = score
        if dimension not in notes:
            note = input_fn(f"{dimension} notes (optional): ").strip()
            if note:
                notes[dimension] = note
    return scores, notes


def prompt_pairwise_comparisons(
    *,
    input_fn: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Prompt an annotator for zero or more pairwise better/worse judgments."""
    input_fn = input_fn or input
    comparisons: list[dict[str, Any]] = []
    while True:
        add = input_fn("Add pairwise comparison? [y/N]: ").strip().lower()
        if add not in {"y", "yes"}:
            return comparisons
        dimension = input_fn("comparison dimension: ").strip()
        a_path = input_fn("candidate A path: ").strip()
        b_path = input_fn("candidate B path: ").strip()
        winner = input_fn("winner [a/b/tied]: ").strip().lower()
        rationale = input_fn("rationale: ").strip()
        comparisons.append(
            {
                "a_path": a_path,
                "b_path": b_path,
                "winner": winner,
                "dimension": dimension,
                "rationale": rationale,
            }
        )


def validate_annotation_record(record: dict[str, Any]) -> list[ValidationError]:
    """Validate the PRD annotation contract without external dependencies.

    The JSON Schema is the portable contract; this function enforces the same
    high-value invariants in the CLI and tests without adding a new dependency.
    """
    errors: list[ValidationError] = []
    required = {
        "doc_id",
        "format",
        "source_path",
        "document_class",
        "edge_case_flags",
        "gold_remediation_path",
        "known_bad_artifact_paths",
        "artifact_hashes",
        "annotator",
        "annotated_at",
        "annotation_version",
        "provenance",
        "applicable_dimensions",
        "dimensions",
        "pairwise_comparisons",
        "format_specific",
    }
    for key in sorted(required - set(record)):
        errors.append(ValidationError(key, "missing required field"))
    allowed_top_level = required
    for key in sorted(set(record) - allowed_top_level):
        errors.append(ValidationError(key, "unknown field"))

    edge_case_flags = record.get("edge_case_flags")
    if not isinstance(edge_case_flags, list):
        errors.append(ValidationError("edge_case_flags", "must be a list"))
    else:
        seen_flags: set[str] = set()
        for index, flag in enumerate(edge_case_flags):
            if not isinstance(flag, str) or not flag.strip():
                errors.append(ValidationError(f"edge_case_flags[{index}]", "must be a non-empty string"))
                continue
            if flag in seen_flags:
                errors.append(ValidationError("edge_case_flags", f"duplicate flag: {flag}"))
            seen_flags.add(flag)

    known_bad_paths = record.get("known_bad_artifact_paths")
    if not isinstance(known_bad_paths, list):
        errors.append(ValidationError("known_bad_artifact_paths", "must be a list"))
    else:
        seen_paths: set[str] = set()
        for index, path_value in enumerate(known_bad_paths):
            if not isinstance(path_value, str) or not path_value.strip():
                errors.append(ValidationError(f"known_bad_artifact_paths[{index}]", "must be a non-empty string"))
                continue
            if path_value in seen_paths:
                errors.append(ValidationError("known_bad_artifact_paths", f"duplicate path: {path_value}"))
            seen_paths.add(path_value)

    artifact_hashes = record.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        errors.append(ValidationError("artifact_hashes", "must be an object"))
    else:
        allowed_hash_keys = {"source_sha256", "gold_remediation_sha256", "known_bad_sha256"}
        for key in sorted(set(artifact_hashes) - allowed_hash_keys):
            errors.append(ValidationError(f"artifact_hashes.{key}", "unknown field"))
        for key in ("source_sha256", "gold_remediation_sha256"):
            if key not in artifact_hashes:
                errors.append(ValidationError(f"artifact_hashes.{key}", "missing required field"))
                continue
            digest = artifact_hashes.get(key)
            if not isinstance(digest, str) or (digest and not SHA256_RE.match(digest)):
                errors.append(ValidationError(f"artifact_hashes.{key}", "must be empty or a sha256 hex digest"))
        known_bad_hashes = artifact_hashes.get("known_bad_sha256")
        if not isinstance(known_bad_hashes, dict):
            errors.append(ValidationError("artifact_hashes.known_bad_sha256", "must be an object"))
        else:
            for path_value, digest in known_bad_hashes.items():
                if not isinstance(path_value, str) or not path_value.strip():
                    errors.append(ValidationError("artifact_hashes.known_bad_sha256", "paths must be non-empty strings"))
                if not isinstance(digest, str) or (digest and not SHA256_RE.match(digest)):
                    errors.append(
                        ValidationError(
                            f"artifact_hashes.known_bad_sha256.{path_value}",
                            "must be empty or a sha256 hex digest",
                        )
                    )

    fmt = str(record.get("format", "")).strip().lower()
    if fmt not in SUPPORTED_FORMATS:
        errors.append(ValidationError("format", f"unsupported format: {fmt!r}"))
        return errors

    allowed_dimensions = set(DIMENSIONS_BY_FORMAT[fmt])
    applicable = record.get("applicable_dimensions") or []
    if not isinstance(applicable, list) or not applicable:
        errors.append(ValidationError("applicable_dimensions", "must be a non-empty list"))
        applicable = []

    seen: set[str] = set()
    for dimension in applicable:
        if dimension in seen:
            errors.append(ValidationError("applicable_dimensions", f"duplicate dimension: {dimension}"))
        seen.add(str(dimension))
        if dimension not in allowed_dimensions:
            errors.append(
                ValidationError(
                    "applicable_dimensions",
                    f"{dimension!r} is not applicable to {fmt}",
                )
            )

    dimensions = record.get("dimensions") or {}
    if not isinstance(dimensions, dict):
        errors.append(ValidationError("dimensions", "must be an object"))
        dimensions = {}

    for dimension in dimensions:
        if dimension not in allowed_dimensions:
            errors.append(ValidationError("dimensions", f"{dimension!r} is not applicable to {fmt}"))
        if dimension not in applicable:
            errors.append(ValidationError("dimensions", f"{dimension!r} is not listed as applicable"))

    for dimension in applicable:
        item = dimensions.get(dimension)
        if not isinstance(item, dict):
            errors.append(ValidationError(f"dimensions.{dimension}", "missing dimension annotation"))
            continue
        score = item.get("score")
        if not isinstance(score, int | float) or isinstance(score, bool):
            errors.append(ValidationError(f"dimensions.{dimension}.score", "must be numeric"))
        elif not math.isfinite(float(score)):
            errors.append(ValidationError(f"dimensions.{dimension}.score", "must be finite"))
        elif score < 0 or score > 1:
            errors.append(ValidationError(f"dimensions.{dimension}.score", "must be between 0 and 1"))

    specific = record.get("format_specific") or {}
    if not isinstance(specific, dict):
        errors.append(ValidationError("format_specific", "must be an object"))
        specific = {}
    unknown_format_blocks = sorted(set(specific) - set(SUPPORTED_FORMATS))
    for key in unknown_format_blocks:
        errors.append(ValidationError(f"format_specific.{key}", "unknown format block"))
    extra_format_blocks = sorted((set(specific) & set(SUPPORTED_FORMATS)) - {fmt})
    for key in extra_format_blocks:
        errors.append(ValidationError(f"format_specific.{key}", f"not allowed for {fmt} annotation"))
    if fmt not in specific:
        errors.append(ValidationError("format_specific", f"missing {fmt} block"))
    else:
        errors.extend(_validate_format_specific(fmt, specific.get(fmt)))

    comparisons = record.get("pairwise_comparisons") or []
    if not isinstance(comparisons, list):
        errors.append(ValidationError("pairwise_comparisons", "must be a list"))
        comparisons = []
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            errors.append(ValidationError(f"pairwise_comparisons[{index}]", "must be an object"))
            continue
        required_comparison = {"a_path", "a_sha256", "b_path", "b_sha256", "winner", "dimension", "rationale"}
        for key in sorted(required_comparison - set(comparison)):
            errors.append(ValidationError(f"pairwise_comparisons[{index}].{key}", "missing required field"))
        for key in sorted(set(comparison) - required_comparison):
            errors.append(ValidationError(f"pairwise_comparisons[{index}].{key}", "unknown field"))
        for key in ("a_path", "b_path"):
            if key in comparison and not str(comparison.get(key, "")).strip():
                errors.append(ValidationError(f"pairwise_comparisons[{index}].{key}", "must be non-empty"))
        for key in ("a_sha256", "b_sha256"):
            if key in comparison:
                digest = comparison.get(key)
                if not isinstance(digest, str) or (digest and not SHA256_RE.match(digest)):
                    errors.append(
                        ValidationError(
                            f"pairwise_comparisons[{index}].{key}",
                            "must be empty or a sha256 hex digest",
                        )
                    )
        if "rationale" in comparison and not isinstance(comparison.get("rationale"), str):
            errors.append(ValidationError(f"pairwise_comparisons[{index}].rationale", "must be a string"))
        winner = comparison.get("winner")
        if winner not in {"a", "b", "tied"}:
            errors.append(ValidationError(f"pairwise_comparisons[{index}].winner", "must be a, b, or tied"))
        dimension = comparison.get("dimension")
        if dimension not in allowed_dimensions:
            errors.append(
                ValidationError(
                    f"pairwise_comparisons[{index}].dimension",
                    f"{dimension!r} is not applicable to {fmt}",
                )
            )

    for string_field in ("source_path", "document_class", "annotator"):
        if not str(record.get(string_field, "")).strip():
            errors.append(ValidationError(string_field, "must be non-empty"))

    doc_id = str(record.get("doc_id", ""))
    if not doc_id.strip():
        errors.append(ValidationError("doc_id", "must be non-empty"))
    elif not DOC_ID_RE.match(doc_id) or ".." in doc_id:
        errors.append(
            ValidationError(
                "doc_id",
                "must contain only [A-Za-z0-9._-] (1-128 chars) and no path separators",
            )
        )

    version = str(record.get("annotation_version", ""))
    if not re.match(r"^\d+\.\d+$", version):
        errors.append(ValidationError("annotation_version", "must look like '1.0'"))
    annotated_at = record.get("annotated_at")
    if not isinstance(annotated_at, str) or not annotated_at.strip():
        errors.append(ValidationError("annotated_at", "must be an ISO date-time string"))
    else:
        try:
            parsed_at = datetime.fromisoformat(annotated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(ValidationError("annotated_at", "must be an ISO date-time string"))
        else:
            if parsed_at.tzinfo is None:
                errors.append(ValidationError("annotated_at", "must include a timezone"))

    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(ValidationError("provenance", "must be an object"))
    else:
        allowed_provenance = {
            "gold_standard_source",
            "human_verified",
            "candidate_seed_model",
            "candidate_seed_notes",
        }
        for key in sorted(set(provenance) - allowed_provenance):
            errors.append(ValidationError(f"provenance.{key}", "unknown field"))
        source = provenance.get("gold_standard_source")
        if source != "human_specialist":
            errors.append(
                ValidationError(
                    "provenance.gold_standard_source",
                    "must be human_specialist",
                )
            )
        if provenance.get("human_verified") is not True:
            errors.append(ValidationError("provenance.human_verified", "must be true"))
        seed_model = provenance.get("candidate_seed_model")
        if not isinstance(seed_model, str):
            errors.append(ValidationError("provenance.candidate_seed_model", "must be a string"))
        seed_notes = provenance.get("candidate_seed_notes", "")
        if not isinstance(seed_notes, str):
            errors.append(ValidationError("provenance.candidate_seed_notes", "must be a string"))

    return errors


def _validate_format_specific(fmt: str, payload: Any) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(payload, dict):
        return [ValidationError(f"format_specific.{fmt}", "must be an object")]
    if fmt == "pptx":
        errors.extend(
            _validate_nested_annotations(
                payload.get("per_slide") or [],
                fmt=fmt,
                item_name="per_slide",
                required_fields=("slide_index", "title"),
            )
        )
    if fmt == "xlsx":
        errors.extend(
            _validate_nested_annotations(
                payload.get("per_sheet") or [],
                fmt=fmt,
                item_name="per_sheet",
                required_fields=("sheet_name",),
            )
        )
    return errors


def _validate_nested_annotations(
    items: Any,
    *,
    fmt: str,
    item_name: str,
    required_fields: tuple[str, ...],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(items, list):
        return [ValidationError(f"format_specific.{fmt}.{item_name}", "must be a list")]
    allowed_dimensions = set(DIMENSIONS_BY_FORMAT[fmt])
    for index, item in enumerate(items):
        path = f"format_specific.{fmt}.{item_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(ValidationError(path, "must be an object"))
            continue
        for required_field in required_fields:
            if required_field not in item:
                errors.append(ValidationError(f"{path}.{required_field}", "missing required field"))
        for index_field in ("slide_index", "sheet_index"):
            if index_field in item:
                value = item[index_field]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    errors.append(ValidationError(f"{path}.{index_field}", "must be a positive integer"))
        if "title" in item and not isinstance(item["title"], str):
            errors.append(ValidationError(f"{path}.title", "must be a string"))
        if "sheet_name" in item and (not isinstance(item["sheet_name"], str) or not item["sheet_name"].strip()):
            errors.append(ValidationError(f"{path}.sheet_name", "must be a non-empty string"))
        applicable = item.get("applicable_dimensions") or []
        dimensions = item.get("dimensions") or {}
        if not isinstance(applicable, list) or not applicable:
            errors.append(ValidationError(f"{path}.applicable_dimensions", "must be a non-empty list"))
            applicable = []
        if not isinstance(dimensions, dict):
            errors.append(ValidationError(f"{path}.dimensions", "must be an object"))
            dimensions = {}
        seen: set[str] = set()
        for dimension in applicable:
            if dimension in seen:
                errors.append(ValidationError(f"{path}.applicable_dimensions", f"duplicate dimension: {dimension}"))
            seen.add(str(dimension))
            if dimension not in allowed_dimensions:
                errors.append(
                    ValidationError(
                        f"{path}.applicable_dimensions",
                        f"{dimension!r} is not applicable to {fmt}",
                    )
                )
            annotation = dimensions.get(dimension)
            if not isinstance(annotation, dict):
                errors.append(ValidationError(f"{path}.dimensions.{dimension}", "missing dimension annotation"))
                continue
            score = annotation.get("score")
            if not isinstance(score, int | float) or isinstance(score, bool):
                errors.append(ValidationError(f"{path}.dimensions.{dimension}.score", "must be numeric"))
            elif not math.isfinite(float(score)):
                errors.append(ValidationError(f"{path}.dimensions.{dimension}.score", "must be finite"))
            elif score < 0 or score > 1:
                errors.append(ValidationError(f"{path}.dimensions.{dimension}.score", "must be between 0 and 1"))
        for dimension in dimensions:
            if dimension not in applicable:
                errors.append(ValidationError(f"{path}.dimensions", f"{dimension!r} is not listed as applicable"))
            if dimension not in allowed_dimensions:
                errors.append(ValidationError(f"{path}.dimensions", f"{dimension!r} is not applicable to {fmt}"))
    return errors


def build_annotation_record(
    *,
    source_path: Path,
    fmt: str,
    doc_id: str,
    document_class: str,
    annotator: str,
    scores: dict[str, float],
    notes: dict[str, str] | None = None,
    applicable_dimensions: list[str] | None = None,
    edge_case_flags: list[str] | None = None,
    gold_remediation_path: str = "",
    known_bad_artifact_paths: list[str] | None = None,
    artifact_hashes: dict[str, Any] | None = None,
    annotation_version: str = "1.0",
    page_count: int | None = None,
    slide_count: int | None = None,
    sheet_count: int | None = None,
    per_slide: list[dict[str, Any]] | None = None,
    per_sheet: list[dict[str, Any]] | None = None,
    pairwise_comparisons: list[dict[str, Any]] | None = None,
    candidate_seed_model: str = "",
    candidate_seed_notes: str = "",
) -> dict[str, Any]:
    """Build one annotation record from CLI or tests."""
    fmt = infer_format(source_path, fmt)
    dimensions = applicable_dimensions or list(DIMENSIONS_BY_FORMAT[fmt])
    missing_scores = [dimension for dimension in dimensions if dimension not in scores]
    if missing_scores:
        joined = ", ".join(missing_scores)
        raise ValueError(f"Missing --score for applicable dimension(s): {joined}")

    notes = notes or {}
    known_bad_artifact_paths = list(known_bad_artifact_paths or [])
    pairwise_comparisons = enrich_pairwise_comparison_hashes(pairwise_comparisons or [])
    dimension_payload = {
        dimension: {
            "score": scores[dimension],
            "notes": notes.get(dimension, ""),
        }
        for dimension in dimensions
    }

    format_specific: dict[str, Any] = {
        "pdf": {"page_count": page_count or 0},
        "docx": {},
        "pptx": {"slide_count": slide_count or 0, "per_slide": per_slide or []},
        "xlsx": {"sheet_count": sheet_count or 0, "per_sheet": per_sheet or []},
    }

    record = {
        "doc_id": doc_id.strip(),
        "format": fmt,
        "source_path": str(source_path),
        "document_class": document_class.strip(),
        "edge_case_flags": sorted(set(edge_case_flags or [])),
        "gold_remediation_path": gold_remediation_path,
        "known_bad_artifact_paths": known_bad_artifact_paths,
        "artifact_hashes": artifact_hashes
        or build_artifact_hashes(
            source_path=source_path,
            gold_remediation_path=gold_remediation_path,
            known_bad_artifact_paths=known_bad_artifact_paths,
        ),
        "annotator": annotator.strip(),
        "annotated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": annotation_version,
        "provenance": {
            "gold_standard_source": "human_specialist",
            "human_verified": True,
            "candidate_seed_model": candidate_seed_model.strip(),
            "candidate_seed_notes": candidate_seed_notes.strip(),
        },
        "applicable_dimensions": dimensions,
        "dimensions": dimension_payload,
        "pairwise_comparisons": pairwise_comparisons,
        "format_specific": {fmt: format_specific[fmt]},
    }
    errors = validate_annotation_record(record)
    if errors:
        detail = "; ".join(str(error) for error in errors)
        raise ValueError(f"Invalid annotation record: {detail}")
    return record


def build_artifact_hashes(
    *,
    source_path: Path,
    gold_remediation_path: str = "",
    known_bad_artifact_paths: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Build immutable artifact hash metadata for paths that currently exist."""
    return {
        "source_sha256": _sha256_for_existing_artifact(str(source_path), root=root),
        "gold_remediation_sha256": _sha256_for_existing_artifact(gold_remediation_path, root=root),
        "known_bad_sha256": {
            path_value: digest
            for path_value in known_bad_artifact_paths or []
            if (digest := _sha256_for_existing_artifact(path_value, root=root))
        },
    }


def enrich_pairwise_comparison_hashes(
    comparisons: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return pairwise comparisons with stable hash fields for existing artifacts."""
    enriched: list[dict[str, Any]] = []
    for comparison in comparisons:
        payload = dict(comparison)
        payload.setdefault(
            "a_sha256",
            _sha256_for_existing_artifact(str(payload.get("a_path") or ""), root=root),
        )
        payload.setdefault(
            "b_sha256",
            _sha256_for_existing_artifact(str(payload.get("b_path") or ""), root=root),
        )
        enriched.append(payload)
    return enriched


def ensure_corpus_layout(root: Path) -> None:
    """Create the versioned annotation directory structure."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.jsonl").touch()
    for fmt in SUPPORTED_FORMATS:
        annotations_dir = root / "annotations" / fmt
        annotations_dir.mkdir(parents=True, exist_ok=True)
        (annotations_dir / ".gitkeep").touch()
        snapshots_dir = root / "snapshots" / fmt
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        (snapshots_dir / ".gitkeep").touch()


def write_annotation_record(
    record: dict[str, Any],
    *,
    root: Path = DEFAULT_CORPUS_ROOT,
    overwrite: bool = False,
) -> Path:
    """Write an annotation JSON file and append a manifest row."""
    errors = validate_annotation_record(record)
    if errors:
        detail = "; ".join(str(error) for error in errors)
        raise ValueError(f"Invalid annotation record: {detail}")
    ensure_corpus_layout(root)
    fmt = record["format"]
    doc_id = record["doc_id"]
    base = root / "annotations" / fmt
    annotation_path = base / f"{doc_id}.json"
    if not annotation_path.resolve().is_relative_to(base.resolve()):
        raise ValueError("doc_id escapes corpus root")
    if annotation_path.exists() and not overwrite:
        raise FileExistsError(f"Annotation already exists: {annotation_path}")
    annotation_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_row = build_manifest_row(record, annotation_path=annotation_path)
    manifest_path = root / "manifest.jsonl"
    _write_manifest_row(manifest_path, manifest_row, overwrite=overwrite)
    return annotation_path


def _write_manifest_row(
    manifest_path: Path,
    manifest_row: dict[str, Any],
    *,
    overwrite: bool,
) -> None:
    """Append or replace the manifest row for one annotation."""
    if not overwrite:
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest_row, sort_keys=True) + "\n")
        return

    target_path = str(manifest_row.get("annotation_path") or "")
    retained_lines: list[str] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            existing = json.loads(line)
        except json.JSONDecodeError:
            retained_lines.append(line)
            continue
        if not isinstance(existing, dict):
            retained_lines.append(line)
            continue
        if str(existing.get("annotation_path") or "") == target_path:
            continue
        retained_lines.append(json.dumps(existing, sort_keys=True))
    retained_lines.append(json.dumps(manifest_row, sort_keys=True))
    manifest_path.write_text("\n".join(retained_lines) + "\n", encoding="utf-8")


def build_manifest_row(record: dict[str, Any], *, annotation_path: Path) -> dict[str, Any]:
    """Build a manifest row bound to the annotation file and referenced artifacts."""
    return {
        "doc_id": record["doc_id"],
        "format": record["format"],
        "source_path": record["source_path"],
        "gold_remediation_path": record["gold_remediation_path"],
        "known_bad_artifact_paths": record["known_bad_artifact_paths"],
        "artifact_hashes": record["artifact_hashes"],
        "annotation_path": str(annotation_path),
        "annotation_sha256": sha256_file(annotation_path),
        "document_class": record["document_class"],
        "edge_case_flags": record["edge_case_flags"],
        "annotation_version": record["annotation_version"],
        "annotated_at": record["annotated_at"],
    }


def iter_annotation_paths(root: Path) -> list[Path]:
    """Return all annotation JSON files under a versioned corpus root."""
    paths: list[Path] = []
    for fmt in SUPPORTED_FORMATS:
        paths.extend(sorted((root / "annotations" / fmt).glob("*.json")))
    return paths


def load_manifest_rows(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load manifest rows, returning parsed rows and line-level errors."""
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.exists():
        return [], [f"missing manifest: {manifest_path}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"manifest line {line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"manifest line {line_number}: row must be an object")
            continue
        rows.append(row)
    return rows, errors


def summarize_corpus(root: Path) -> dict[str, Any]:
    """Summarize corpus annotations and validation state."""
    counts_by_format = {fmt: 0 for fmt in SUPPORTED_FORMATS}
    document_classes: dict[str, int] = {}
    edge_case_flags: dict[str, int] = {}
    validation_errors: dict[str, list[str]] = {}
    artifact_errors: dict[str, list[str]] = {}
    dimension_errors: dict[str, list[str]] = {}
    records_by_path: dict[str, dict[str, Any]] = {}

    annotation_paths = [path for path in iter_annotation_paths(root)]
    annotation_path_index = {
        _canonical_manifest_annotation_path(str(path), root=root): str(path)
        for path in annotation_paths
    }
    for path in annotation_paths:
        errors = validate_annotation_file(path)
        if errors:
            validation_errors[_canonical_manifest_annotation_path(str(path), root=root)] = [
                str(error) for error in errors
            ]
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        records_by_path[_canonical_manifest_annotation_path(str(path), root=root)] = record
        missing_artifacts = _missing_artifact_references(record, root=root)
        if missing_artifacts:
            artifact_errors[str(path)] = missing_artifacts
        missing_dimensions = _dimension_completeness_errors(record)
        if missing_dimensions:
            dimension_errors[str(path)] = missing_dimensions
        fmt = record["format"]
        counts_by_format[fmt] += 1
        doc_class = record["document_class"]
        document_classes[doc_class] = document_classes.get(doc_class, 0) + 1
        for flag in record.get("edge_case_flags", []):
            edge_case_flags[flag] = edge_case_flags.get(flag, 0) + 1

    manifest_rows, manifest_errors = load_manifest_rows(root)
    manifest_rows_by_path: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(manifest_rows, 1):
        annotation_path = _canonical_manifest_annotation_path(
            str(row.get("annotation_path") or ""),
            root=root,
        )
        if not annotation_path:
            manifest_errors.append(f"manifest row {index}: missing annotation_path")
            continue
        manifest_rows_by_path.setdefault(str(Path(annotation_path)), []).append(row)
    manifest_paths = set(manifest_rows_by_path)
    annotation_path_strings = {index_key for index_key in annotation_path_index}
    missing_manifest_entries = sorted(annotation_path_strings - manifest_paths)
    stale_manifest_entries = sorted(manifest_paths - annotation_path_strings)
    duplicate_manifest_entries = sorted(
        path for path, rows in manifest_rows_by_path.items() if len(rows) > 1
    )
    manifest_mismatch_entries: dict[str, list[str]] = {}
    for annotation_path, record in records_by_path.items():
        canonical_path = _canonical_manifest_annotation_path(annotation_path, root=root)
        rows = manifest_rows_by_path.get(canonical_path)
        if not rows:
            continue
        # Use the original (repo-relative) annotation path so the rebuilt
        # expected manifest row matches the relative paths stored in
        # manifest.jsonl. Passing the canonical absolute path would make every
        # row look drifted on machines whose absolute paths differ.
        original_path = annotation_path_index.get(canonical_path, annotation_path)
        errors = _manifest_metadata_errors(
            rows[-1],
            record,
            annotation_path=Path(original_path),
        )
        if errors:
            manifest_mismatch_entries[annotation_path] = errors

    total = sum(counts_by_format.values())
    office_total = sum(counts_by_format[fmt] for fmt in OFFICE_FORMATS)
    return {
        "root": str(root),
        "total_annotations": total,
        "counts_by_format": counts_by_format,
        "office_annotations": office_total,
        "document_classes": document_classes,
        "edge_case_flags": edge_case_flags,
        "manifest_rows": len(manifest_rows),
        "manifest_errors": manifest_errors,
        "missing_manifest_entries": missing_manifest_entries,
        "stale_manifest_entries": stale_manifest_entries,
        "duplicate_manifest_entries": duplicate_manifest_entries,
        "manifest_mismatch_entries": manifest_mismatch_entries,
        "validation_errors": validation_errors,
        "artifact_errors": artifact_errors,
        "dimension_errors": dimension_errors,
    }


def evaluate_phase_a_coverage(
    summary: dict[str, Any],
    *,
    min_total: int = PHASE_A_DEFAULT_MINIMUMS["total"],
    min_pdf: int = PHASE_A_DEFAULT_MINIMUMS["pdf"],
    min_office: int = PHASE_A_DEFAULT_MINIMUMS["office"],
) -> list[str]:
    """Return unmet Phase A corpus coverage requirements."""
    min_total = _require_non_negative_int("min_total", min_total)
    min_pdf = _require_non_negative_int("min_pdf", min_pdf)
    min_office = _require_non_negative_int("min_office", min_office)
    errors: list[str] = []
    counts = summary["counts_by_format"]
    total = int(summary["total_annotations"])
    office_total = int(summary["office_annotations"])
    if summary["validation_errors"]:
        errors.append(f"{len(summary['validation_errors'])} annotation file(s) failed validation")
    if summary.get("artifact_errors"):
        errors.append(
            f"{len(summary['artifact_errors'])} annotation file(s) have invalid source/gold/known-bad artifact references or hashes"
        )
    if summary.get("dimension_errors"):
        errors.append(f"{len(summary['dimension_errors'])} annotation file(s) have incomplete dimension coverage")
    if summary["manifest_errors"]:
        errors.append(f"{len(summary['manifest_errors'])} manifest error(s)")
    if summary["missing_manifest_entries"]:
        errors.append(f"{len(summary['missing_manifest_entries'])} annotation file(s) missing from manifest")
    if summary["stale_manifest_entries"]:
        errors.append(f"{len(summary['stale_manifest_entries'])} stale manifest entrie(s)")
    if summary.get("duplicate_manifest_entries"):
        errors.append(f"{len(summary['duplicate_manifest_entries'])} duplicate manifest entrie(s)")
    if summary.get("manifest_mismatch_entries"):
        errors.append(f"{len(summary['manifest_mismatch_entries'])} manifest entrie(s) drifted from annotation files")
    if total < min_total:
        errors.append(f"total annotations {total} < required {min_total}")
    if int(counts["pdf"]) < min_pdf:
        errors.append(f"PDF annotations {counts['pdf']} < required {min_pdf}")
    if office_total < min_office:
        errors.append(f"Office annotations {office_total} < required {min_office}")
    if not summary["document_classes"]:
        errors.append("no document classes represented")
    return errors


def _manifest_metadata_errors(
    row: dict[str, Any],
    record: dict[str, Any],
    *,
    annotation_path: Path,
) -> list[str]:
    errors: list[str] = []
    expected = build_manifest_row(record, annotation_path=annotation_path)
    for key, expected_value in expected.items():
        if row.get(key) != expected_value:
            errors.append(f"{key} does not match annotation")
    unexpected = sorted(set(row) - set(expected))
    for key in unexpected:
        errors.append(f"{key} is not a supported manifest field")
    return errors


def _missing_artifact_references(record: dict[str, Any], *, root: Path) -> list[str]:
    errors: list[str] = []
    source_path = str(record.get("source_path") or "").strip()
    source_artifact = _resolve_artifact_path(source_path, root=root)
    artifact_hashes = record.get("artifact_hashes") if isinstance(record.get("artifact_hashes"), dict) else {}
    if source_artifact is None:
        errors.append(f"missing source_path artifact: {source_path or '<empty>'}")
    else:
        expected = str(artifact_hashes.get("source_sha256") or "")
        if not expected:
            errors.append(f"missing source_sha256 for source_path artifact: {source_path}")
        elif expected != sha256_file(source_artifact):
            errors.append(f"source_sha256 must match source_path artifact bytes: {source_path}")
    gold_path = str(record.get("gold_remediation_path") or "").strip()
    if not gold_path:
        errors.append("missing gold_remediation_path")
    else:
        gold_artifact = _resolve_artifact_path(gold_path, root=root)
        if gold_artifact is None:
            errors.append(f"missing gold_remediation_path artifact: {gold_path}")
        else:
            expected = str(artifact_hashes.get("gold_remediation_sha256") or "")
            if not expected:
                errors.append(f"missing gold_remediation_sha256 for gold_remediation_path artifact: {gold_path}")
            elif expected != sha256_file(gold_artifact):
                errors.append(f"gold_remediation_sha256 must match gold_remediation_path artifact bytes: {gold_path}")
    known_bad_paths = record.get("known_bad_artifact_paths")
    if not isinstance(known_bad_paths, list) or not known_bad_paths:
        errors.append("missing known_bad_artifact_paths")
    else:
        known_bad_hashes = artifact_hashes.get("known_bad_sha256")
        if not isinstance(known_bad_hashes, dict):
            known_bad_hashes = {}
        for index, value in enumerate(known_bad_paths):
            path_value = str(value or "").strip()
            if not path_value:
                errors.append(f"known_bad_artifact_paths[{index}] is empty")
                continue
            artifact = _resolve_artifact_path(path_value, root=root)
            if artifact is None:
                errors.append(f"missing known_bad_artifact_paths[{index}] artifact: {path_value}")
                continue
            expected = str(known_bad_hashes.get(path_value) or "")
            if not expected:
                errors.append(f"missing known_bad_sha256 for known_bad_artifact_paths[{index}]: {path_value}")
            elif expected != sha256_file(artifact):
                errors.append(f"known_bad_sha256 must match known_bad_artifact_paths[{index}] artifact bytes: {path_value}")
    return errors


def _dimension_completeness_errors(record: dict[str, Any]) -> list[str]:
    fmt = str(record.get("format", ""))
    if fmt not in DIMENSIONS_BY_FORMAT:
        return []
    expected = set(DIMENSIONS_BY_FORMAT[fmt])
    applicable = set(record.get("applicable_dimensions") or [])
    dimensions = set((record.get("dimensions") or {}).keys())
    errors: list[str] = []
    missing_applicable = sorted(expected - applicable)
    if missing_applicable:
        errors.append(
            "missing applicable dimension(s): " + ", ".join(missing_applicable)
        )
    missing_annotations = sorted(expected - dimensions)
    if missing_annotations:
        errors.append(
            "missing dimension annotation(s): " + ", ".join(missing_annotations)
        )
    return errors


def _resolve_artifact_path(path_value: str, *, root: Path | None = None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.exists():
        return path
    if not path.is_absolute() and root is not None and (root / path).exists():
        return root / path
    if not path.is_absolute() and (REPO_ROOT / path).exists():
        return REPO_ROOT / path
    return None


def _sha256_for_existing_artifact(path_value: str, *, root: Path | None = None) -> str:
    path = _resolve_artifact_path(path_value, root=root)
    if path is None:
        return ""
    return sha256_file(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_annotation_file(path: Path) -> list[ValidationError]:
    """Load and validate one annotation file."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [ValidationError(str(path), f"invalid JSON: {exc}")]
    return validate_annotation_record(record)


def _cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_corpus_layout(root)
    print(f"initialized {root}")
    print(f"schema {SCHEMA_PATH}")
    return 0


def _cmd_dimensions(args: argparse.Namespace) -> int:
    fmt = args.format
    matrix = {fmt: DIMENSIONS_BY_FORMAT[fmt]} if fmt else DIMENSIONS_BY_FORMAT
    print(json.dumps(matrix, indent=2, sort_keys=True))
    return 0


def _cmd_annotate(args: argparse.Namespace) -> int:
    source_path = Path(args.source_path)
    fmt = infer_format(source_path, args.format)
    applicable_dimensions = args.dimension or list(DIMENSIONS_BY_FORMAT[fmt])
    scores = parse_dimension_scores(args.score or [])
    notes = parse_dimension_notes(args.note or [])
    if args.interactive:
        print(f"Annotating {source_path} as {fmt}")
        print("Applicable dimensions:")
        for dimension in applicable_dimensions:
            print(f"  - {dimension}")
        scores, notes = prompt_dimension_judgments(
            dimensions=applicable_dimensions,
            existing_scores=scores,
            existing_notes=notes,
        )
    pairwise_comparisons = parse_pairwise_comparisons(args.pairwise_json or [])
    per_slide = parse_format_specific_items(args.per_slide_json or [], item_name="per-slide")
    per_sheet = parse_format_specific_items(args.per_sheet_json or [], item_name="per-sheet")
    if args.interactive:
        pairwise_comparisons.extend(prompt_pairwise_comparisons())
    record = build_annotation_record(
        source_path=source_path,
        fmt=fmt,
        doc_id=args.doc_id,
        document_class=args.document_class,
        annotator=args.annotator,
        scores=scores,
        notes=notes,
        applicable_dimensions=applicable_dimensions,
        edge_case_flags=args.edge_case or [],
        gold_remediation_path=args.gold_remediation_path or "",
        known_bad_artifact_paths=args.known_bad_artifact_paths or [],
        artifact_hashes=build_artifact_hashes(
            source_path=source_path,
            gold_remediation_path=args.gold_remediation_path or "",
            known_bad_artifact_paths=args.known_bad_artifact_paths or [],
            root=Path(args.root),
        ),
        annotation_version=args.annotation_version,
        page_count=args.page_count,
        slide_count=args.slide_count,
        sheet_count=args.sheet_count,
        per_slide=per_slide,
        per_sheet=per_sheet,
        pairwise_comparisons=pairwise_comparisons,
        candidate_seed_model=args.candidate_seed_model or "",
        candidate_seed_notes=args.candidate_seed_note or "",
    )
    path = write_annotation_record(
        record,
        root=Path(args.root),
        overwrite=args.overwrite,
    )
    print(path)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    paths = [Path(args.annotation)] if args.annotation else iter_annotation_paths(root)
    if not paths:
        if args.allow_empty:
            print(f"no annotation JSON files found under {root}; allow-empty enabled")
            return 0
        print(f"no annotation JSON files found under {root}", file=sys.stderr)
        return 1

    failed = False
    for path in paths:
        errors = validate_annotation_file(path)
        if errors:
            failed = True
            print(f"{path}: FAIL", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
        else:
            print(f"{path}: OK")
    return 1 if failed else 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    root = Path(args.root)
    summary = summarize_corpus(root)
    errors = evaluate_phase_a_coverage(
        summary,
        min_total=args.min_total,
        min_pdf=args.min_pdf,
        min_office=args.min_office,
    )
    payload = {**summary, "phase_a_errors": errors, "phase_a_ready": not errors}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"root: {payload['root']}")
        print(f"total annotations: {payload['total_annotations']}")
        print(f"counts by format: {payload['counts_by_format']}")
        print(f"office annotations: {payload['office_annotations']}")
        print(f"document classes: {payload['document_classes']}")
        if errors:
            print("Phase A coverage: FAIL")
            for error in errors:
                print(f"  - {error}")
        else:
            print("Phase A coverage: OK")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create corpus directory layout")
    init_parser.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    init_parser.set_defaults(func=_cmd_init)

    dimensions_parser = subparsers.add_parser("dimensions", help="print format applicability matrix")
    dimensions_parser.add_argument("--format", choices=SUPPORTED_FORMATS)
    dimensions_parser.set_defaults(func=_cmd_dimensions)

    annotate_parser = subparsers.add_parser("annotate", help="write one specialist annotation")
    annotate_parser.add_argument("source_path")
    annotate_parser.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    annotate_parser.add_argument("--format", choices=SUPPORTED_FORMATS)
    annotate_parser.add_argument("--doc-id", required=True)
    annotate_parser.add_argument("--document-class", required=True)
    annotate_parser.add_argument("--annotator", required=True)
    annotate_parser.add_argument("--gold-remediation-path", default="")
    annotate_parser.add_argument(
        "--known-bad-artifact-path",
        "--known-bad-artifact",
        dest="known_bad_artifact_paths",
        action="append",
        default=[],
        help="known-bad artifact path used for behavioral discrimination, repeated",
    )
    annotate_parser.add_argument("--candidate-seed-model", default="", help="model used only to seed a candidate for human review")
    annotate_parser.add_argument("--candidate-seed-note", default="", help="free-text provenance note for any model-seeded candidate")
    annotate_parser.add_argument("--annotation-version", default="1.0")
    annotate_parser.add_argument("--dimension", action="append", choices=sorted({d for dims in DIMENSIONS_BY_FORMAT.values() for d in dims}))
    annotate_parser.add_argument("--score", action="append", help="dimension=score, repeated")
    annotate_parser.add_argument("--note", action="append", help="dimension=free-text note, repeated")
    annotate_parser.add_argument("--pairwise-json", action="append", help="pairwise comparison JSON object, repeated")
    annotate_parser.add_argument("--per-slide-json", action="append", help="PPTX per-slide annotation JSON object, repeated")
    annotate_parser.add_argument("--per-sheet-json", action="append", help="XLSX per-sheet annotation JSON object, repeated")
    annotate_parser.add_argument("--interactive", action="store_true", help="prompt for missing scores, notes, and pairwise comparisons")
    annotate_parser.add_argument("--edge-case", action="append", default=[])
    annotate_parser.add_argument("--page-count", type=int)
    annotate_parser.add_argument("--slide-count", type=int)
    annotate_parser.add_argument("--sheet-count", type=int)
    annotate_parser.add_argument("--overwrite", action="store_true")
    annotate_parser.set_defaults(func=_cmd_annotate)

    validate_parser = subparsers.add_parser("validate", help="validate annotation files")
    validate_parser.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    validate_parser.add_argument("--annotation")
    validate_parser.add_argument("--allow-empty", action="store_true")
    validate_parser.set_defaults(func=_cmd_validate)

    coverage_parser = subparsers.add_parser("coverage", help="check Phase A corpus coverage thresholds")
    coverage_parser.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    coverage_parser.add_argument("--min-total", type=int, default=PHASE_A_DEFAULT_MINIMUMS["total"])
    coverage_parser.add_argument("--min-pdf", type=int, default=PHASE_A_DEFAULT_MINIMUMS["pdf"])
    coverage_parser.add_argument("--min-office", type=int, default=PHASE_A_DEFAULT_MINIMUMS["office"])
    coverage_parser.add_argument("--json", action="store_true")
    coverage_parser.set_defaults(func=_cmd_coverage)

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
