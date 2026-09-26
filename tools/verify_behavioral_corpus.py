"""Verify behavioral proxy gold-vs-known-bad corpus discrimination.

The PRD requires behavioral proxies to distinguish specialist gold artifacts
from known-bad artifacts on at least 95% of corpus entries per format. This
tool checks committed/collected behavioral result rows against the annotation
manifest once corpus artifacts exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from project_remedy.quality_judges.shared.dimensions import (
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)
from project_remedy.behavioral_proxies.shared.base import behavioral_model_family
from tools.annotate_corpus import (
    DEFAULT_CORPUS_ROOT,
    SUPPORTED_FORMATS,
    iter_annotation_paths,
    validate_annotation_file,
)


DEFAULT_RESULTS_PATH = DEFAULT_CORPUS_ROOT / "behavioral_results.jsonl"
GOLD_VARIANTS = {"gold", "gold_remediation", "human_gold", "reference"}
KNOWN_BAD_VARIANTS = {"known_bad", "known-bad", "bad", "baseline_bad"}
BEHAVIORAL_RESULT_FIELDS = ("behavioral", "behavioral_results", "results")


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


def load_annotation_records(root: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Load valid annotation records and validation errors keyed by path."""
    records: list[dict[str, Any]] = []
    errors: dict[str, list[str]] = {}
    for path in iter_annotation_paths(root):
        validation_errors = validate_annotation_file(path)
        if validation_errors:
            errors[str(path)] = [str(error) for error in validation_errors]
            continue
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records, errors


def load_behavioral_result_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load behavioral result rows from JSONL."""
    if not path.exists():
        return [], [f"missing behavioral results file: {path}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line {line_number}: row must be an object")
            continue
        rows.append(payload)
    return rows, errors


def summarize_behavioral_discrimination(
    annotations: Iterable[Mapping[str, Any]],
    result_rows: Iterable[Mapping[str, Any]],
    *,
    min_pass_rate: float = 0.95,
    root: Path | None = None,
) -> dict[str, Any]:
    """Summarize gold-vs-known-bad discrimination against annotation records."""
    min_pass_rate = _require_unit_interval("min_pass_rate", min_pass_rate)
    annotation_list = [dict(record) for record in annotations]
    rows_by_role: dict[tuple[str, str, str], dict[str, Any]] = {}
    row_errors: list[str] = []
    for index, row in enumerate(result_rows):
        identity_errors = _behavioral_result_row_identity_errors(row, index=index)
        if identity_errors:
            row_errors.extend(identity_errors)
            continue
        doc_id = row["doc_id"].strip()
        fmt = row["format"].strip().lower()
        variant = _variant(row)
        if fmt not in SUPPORTED_FORMATS:
            row_errors.append(f"row {index}: unsupported format {fmt!r}")
            continue
        behavioral_errors = _behavioral_row_errors(row, fmt=fmt, index=index)
        if behavioral_errors:
            row_errors.extend(behavioral_errors)
            continue
        if variant not in GOLD_VARIANTS | KNOWN_BAD_VARIANTS:
            row_errors.append(f"row {index}: unsupported variant {variant!r}")
            continue
        role = _variant_role(variant)
        role_key = (doc_id, fmt, role)
        if role_key in rows_by_role:
            row_errors.append(f"row {index}: duplicate {role} behavioral result row for {doc_id}/{fmt}")
            continue
        rows_by_role[role_key] = dict(row)

    totals_by_format = {fmt: 0 for fmt in SUPPORTED_FORMATS}
    passed_by_format = {fmt: 0 for fmt in SUPPORTED_FORMATS}
    failed_entries: dict[str, list[str]] = {}
    evaluated_entries: dict[str, list[str]] = {fmt: [] for fmt in SUPPORTED_FORMATS}
    known_bad_artifact_errors: dict[str, list[str]] = {}
    result_artifact_errors: dict[str, list[str]] = {}
    result_model_errors: dict[str, list[str]] = {}
    annotation_record_errors: dict[str, list[str]] = {}

    for index, record in enumerate(annotation_list):
        identity_errors = _annotation_record_identity_errors(record, index=index)
        if identity_errors:
            annotation_key = _annotation_error_key(record, index=index)
            annotation_record_errors[annotation_key] = identity_errors
            continue
        doc_id = record["doc_id"].strip()
        fmt = record["format"].strip().lower()
        totals_by_format[fmt] += 1
        gold_row = rows_by_role.get((doc_id, fmt, "gold"))
        bad_row = rows_by_role.get((doc_id, fmt, "known_bad"))
        entry_errors = _entry_errors(doc_id=doc_id, gold_row=gold_row, bad_row=bad_row)
        if root is not None:
            artifact_errors = _known_bad_artifact_errors(record, root=root)
            if artifact_errors:
                artifact_key = doc_id or f"<annotation:{len(known_bad_artifact_errors)}>"
                known_bad_artifact_errors[artifact_key] = artifact_errors
                entry_errors.extend(artifact_errors)
            binding_errors = []
            if gold_row is not None:
                binding_errors.extend(_result_artifact_binding_errors(record, gold_row, role="gold"))
            if bad_row is not None:
                binding_errors.extend(_result_artifact_binding_errors(record, bad_row, role="known_bad"))
            if binding_errors:
                result_key = doc_id or f"<annotation:{len(result_artifact_errors)}>"
                result_artifact_errors[result_key] = binding_errors
                entry_errors.extend(binding_errors)
            model_errors = []
            if gold_row is not None:
                model_errors.extend(_result_model_metadata_errors(record, gold_row, role="gold"))
            if bad_row is not None:
                model_errors.extend(
                    _result_model_metadata_errors(record, bad_row, role="known_bad")
                )
            if model_errors:
                model_key = doc_id or f"<annotation:{len(result_model_errors)}>"
                result_model_errors[model_key] = model_errors
                entry_errors.extend(model_errors)
        if entry_errors:
            failed_entries[doc_id] = entry_errors
            continue

        gold_results = _behavioral_passes(gold_row or {})
        bad_results = _behavioral_passes(bad_row or {})
        comparable = sorted(set(gold_results) & set(bad_results))
        if not comparable:
            failed_entries[doc_id] = ["no comparable behavioral tests for gold and known_bad rows"]
            continue
        failures = [
            test_name
            for test_name in comparable
            if gold_results[test_name] is not True or bad_results[test_name] is not False
        ]
        evaluated_entries[fmt].append(doc_id)
        if failures:
            failed_entries[doc_id] = [
                "behavioral test(s) did not distinguish gold from known_bad: "
                + ", ".join(failures)
            ]
            continue
        passed_by_format[fmt] += 1

    pass_rate_by_format = {
        fmt: (passed_by_format[fmt] / totals_by_format[fmt] if totals_by_format[fmt] else 0.0)
        for fmt in SUPPORTED_FORMATS
    }
    errors = list(row_errors)
    for fmt, total in totals_by_format.items():
        if total and pass_rate_by_format[fmt] < min_pass_rate:
            errors.append(
                f"{fmt} behavioral discrimination pass rate "
                f"{pass_rate_by_format[fmt]:.3f} < required {min_pass_rate:.3f}"
            )
    if not annotation_list:
        errors.append("no annotation JSON files found")
    if known_bad_artifact_errors:
        errors.append(f"{len(known_bad_artifact_errors)} annotation(s) missing known_bad artifact references")
    if result_artifact_errors:
        errors.append(f"{len(result_artifact_errors)} annotation(s) have behavioral result artifact binding errors")
    if result_model_errors:
        errors.append(f"{len(result_model_errors)} annotation(s) have behavioral result model metadata errors")
    if annotation_record_errors:
        errors.append(f"{len(annotation_record_errors)} annotation(s) have invalid behavioral annotation identity")
    if failed_entries:
        errors.append(f"{len(failed_entries)} annotation(s) failed behavioral discrimination")

    return {
        "total_annotations": len(annotation_list),
        "totals_by_format": totals_by_format,
        "passed_by_format": passed_by_format,
        "pass_rate_by_format": pass_rate_by_format,
        "evaluated_entries": evaluated_entries,
        "failed_entries": failed_entries,
        "known_bad_artifact_errors": known_bad_artifact_errors,
        "result_artifact_errors": result_artifact_errors,
        "result_model_errors": result_model_errors,
        "annotation_record_errors": annotation_record_errors,
        "row_errors": row_errors,
        "min_pass_rate": min_pass_rate,
        "errors": errors,
        "ready": not errors,
    }


def _variant(row: Mapping[str, Any]) -> str:
    for key in ("variant", "artifact_role", "kind", "label"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().replace(" ", "_")
    return ""


def _annotation_record_identity_errors(
    record: Mapping[str, Any],
    *,
    index: int,
) -> list[str]:
    errors: list[str] = []
    doc_id = record.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        errors.append(f"annotation {index}: doc_id must be a non-empty string")
    fmt = record.get("format")
    if not isinstance(fmt, str) or not fmt.strip():
        errors.append(f"annotation {index}: format must be a non-empty string")
    elif fmt.strip().lower() not in SUPPORTED_FORMATS:
        errors.append(f"annotation {index}: unsupported format {fmt.strip().lower()!r}")
    return errors


def _annotation_error_key(record: Mapping[str, Any], *, index: int) -> str:
    doc_id = record.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        return doc_id.strip()
    return f"<annotation:{index}>"


def _behavioral_result_row_identity_errors(
    row: Mapping[str, Any],
    *,
    index: int,
) -> list[str]:
    errors: list[str] = []
    for field_name in ("doc_id", "format"):
        value = row.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"row {index}: {field_name} must be a non-empty string")
    for field_name in ("variant", "artifact_role", "kind", "label"):
        if field_name not in row:
            continue
        value = row.get(field_name)
        if value is not None and not isinstance(value, str):
            errors.append(f"row {index}: {field_name} must be a string")
    return errors


def _variant_role(variant: str) -> str:
    return "gold" if variant in GOLD_VARIANTS else "known_bad"


def _entry_errors(
    *,
    doc_id: str,
    gold_row: Mapping[str, Any] | None,
    bad_row: Mapping[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    if not gold_row:
        errors.append("missing gold behavioral result row")
    if not bad_row:
        errors.append("missing known_bad behavioral result row")
    if not doc_id:
        errors.append("annotation missing doc_id")
    return errors


def _known_bad_artifact_errors(record: Mapping[str, Any], *, root: Path) -> list[str]:
    paths = record.get("known_bad_artifact_paths")
    if not isinstance(paths, list) or not paths:
        return ["missing known_bad_artifact_paths"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(paths):
        if not isinstance(value, str):
            errors.append(f"known_bad_artifact_paths[{index}] must be a string")
            continue
        path_value = value.strip()
        if not path_value:
            errors.append(f"known_bad_artifact_paths[{index}] is empty")
            continue
        if path_value in seen:
            errors.append(f"known_bad_artifact_paths[{index}] is duplicated: {path_value}")
            continue
        seen.add(path_value)
        artifact_path = _resolve_artifact_path(path_value, root=root)
        if artifact_path is None:
            errors.append(f"missing known_bad_artifact_paths[{index}] artifact: {path_value}")
            continue
        artifact_hashes = record.get("artifact_hashes") if isinstance(record.get("artifact_hashes"), Mapping) else {}
        known_bad_hashes = artifact_hashes.get("known_bad_sha256") if isinstance(artifact_hashes, Mapping) else {}
        expected = known_bad_hashes.get(path_value) if isinstance(known_bad_hashes, Mapping) else ""
        if not isinstance(expected, str) or not expected:
            errors.append(f"missing known_bad_sha256 for known_bad_artifact_paths[{index}]: {path_value}")
        elif expected != _sha256_file(artifact_path):
            errors.append(f"known_bad_sha256 must match known_bad_artifact_paths[{index}] artifact bytes: {path_value}")
    return errors


def _result_artifact_binding_errors(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    role: str,
) -> list[str]:
    row_path, path_shape_errors = _optional_row_string(
        row,
        ("artifact_path", "path", "output_path"),
    )
    row_sha, sha_shape_errors = _optional_row_string(
        row,
        ("artifact_sha256", "sha256", "output_sha256", "artifact_hash"),
    )
    shape_errors = [
        f"{role} row {error}"
        for error in [*path_shape_errors, *sha_shape_errors]
    ]
    if shape_errors:
        return shape_errors
    if role == "gold":
        metadata_errors: list[str] = []
        expected_path_value = record.get("gold_remediation_path")
        if expected_path_value is not None and not isinstance(expected_path_value, str):
            metadata_errors.append("annotation gold_remediation_path must be a string")
            expected_path = ""
        else:
            expected_path = (expected_path_value or "").strip()
        artifact_hashes = record.get("artifact_hashes") if isinstance(record.get("artifact_hashes"), Mapping) else {}
        expected_sha_value = artifact_hashes.get("gold_remediation_sha256")
        if expected_sha_value is not None and not isinstance(expected_sha_value, str):
            metadata_errors.append("annotation gold_remediation_sha256 must be a string")
            expected_sha = ""
        else:
            expected_sha = expected_sha_value or ""
        if metadata_errors:
            return metadata_errors
        return _expected_result_artifact_errors(
            row_path=row_path,
            row_sha=row_sha,
            expected_path=expected_path,
            expected_sha=expected_sha,
            label="gold",
            path_label="gold_remediation_path",
            sha_label="gold_remediation_sha256",
        )
    known_bad_paths = [
        path.strip()
        for path in record.get("known_bad_artifact_paths") or []
        if isinstance(path, str) and path.strip()
    ]
    artifact_hashes = record.get("artifact_hashes") if isinstance(record.get("artifact_hashes"), Mapping) else {}
    known_bad_hashes = artifact_hashes.get("known_bad_sha256") if isinstance(artifact_hashes, Mapping) else {}
    expected_sha = known_bad_hashes.get(row_path) if isinstance(known_bad_hashes, Mapping) else ""
    errors: list[str] = []
    if not row_path:
        errors.append("known_bad row missing artifact_path")
        return errors
    if row_path not in known_bad_paths:
        errors.append("known_bad row artifact_path must match one known_bad_artifact_paths entry")
    if not isinstance(expected_sha, str) or not expected_sha:
        errors.append("annotation missing known_bad_sha256 for known_bad row artifact_path")
    elif not row_sha:
        errors.append("known_bad row missing artifact_sha256")
    elif row_sha != expected_sha:
        errors.append("known_bad row artifact_sha256 must match known_bad_sha256")
    return errors


def _optional_row_string(
    row: Mapping[str, Any],
    field_names: tuple[str, ...],
) -> tuple[str, list[str]]:
    errors: list[str] = []
    for field_name in field_names:
        if field_name not in row:
            continue
        value = row.get(field_name)
        if value is None:
            continue
        if not isinstance(value, str):
            errors.append(f"{field_name} must be a string")
            continue
        if value.strip():
            return value.strip(), errors
    return "", errors


def _expected_result_artifact_errors(
    *,
    row_path: str,
    row_sha: str,
    expected_path: str,
    expected_sha: str,
    label: str,
    path_label: str,
    sha_label: str,
) -> list[str]:
    errors: list[str] = []
    if not row_path:
        errors.append(f"{label} row missing artifact_path")
    elif row_path != expected_path:
        errors.append(f"{label} row artifact_path must match {path_label}")
    if not expected_sha:
        errors.append(f"annotation missing {sha_label}")
    elif not row_sha:
        errors.append(f"{label} row missing artifact_sha256")
    elif row_sha != expected_sha:
        errors.append(f"{label} row artifact_sha256 must match {sha_label}")
    return errors


def _result_model_metadata_errors(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    role: str,
) -> list[str]:
    behavioral_models, model_errors = _behavioral_models_from_row(row)
    errors = [f"{role} row {error}" for error in model_errors]
    errors.extend(
        f"{role} row {error}" for error in _artifact_generator_model_metadata_errors(row)
    )
    if not behavioral_models:
        errors.append(f"{role} row missing behavioral_model")
        return errors
    if len(behavioral_models) > 1:
        errors.append(f"{role} row behavioral_model metadata must be consistent")
        return errors

    behavioral_model = next(iter(behavioral_models))
    behavioral_family = behavioral_model_family(behavioral_model)
    if not behavioral_family:
        errors.append(f"{role} row behavioral_model must be a non-empty string")
        return errors

    for generator_model in _artifact_generator_models(record, row):
        generator_family = behavioral_model_family(generator_model)
        if not generator_family:
            continue
        if behavioral_model.strip().lower() == generator_model.strip().lower():
            errors.append(
                f"{role} row behavioral_model must differ from artifact generator model"
            )
        elif behavioral_family == generator_family:
            errors.append(
                f"{role} row behavioral_model family must differ from artifact "
                f"generator model {generator_model!r}"
            )
    return errors


def _artifact_generator_model_metadata_errors(row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "artifact_generator_model",
        "generated_by_model",
        "candidate_seed_model",
        "remediation_model",
    ):
        if key not in row:
            continue
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{key} must be a string")
    return errors


def _behavioral_models_from_row(row: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    models: set[str] = set()
    errors: list[str] = []
    for key in ("behavioral_model", "answerer_model"):
        if key in row:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{key} must be a non-empty string")
            else:
                models.add(value.strip())

    raw = _behavioral_result_payload(row)
    if isinstance(raw, Mapping):
        for test_name, payload in raw.items():
            if not isinstance(payload, Mapping):
                continue
            metadata = payload.get("metadata")
            if not isinstance(metadata, Mapping) or "behavioral_model" not in metadata:
                continue
            value = metadata.get("behavioral_model")
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"behavioral test {test_name!r} metadata.behavioral_model "
                    "must be a non-empty string"
                )
            else:
                models.add(value.strip())
    return models, errors


def _artifact_generator_models(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
) -> list[str]:
    models: list[str] = []
    for key in (
        "artifact_generator_model",
        "generated_by_model",
        "candidate_seed_model",
        "remediation_model",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            models.append(value.strip())

    provenance = record.get("provenance")
    if isinstance(provenance, Mapping):
        value = provenance.get("candidate_seed_model")
        if isinstance(value, str) and value.strip():
            models.append(value.strip())
    return models


def _resolve_artifact_path(path_value: str, *, root: Path) -> Path | None:
    path = Path(path_value)
    if path.exists():
        return path
    if not path.is_absolute() and (root / path).exists():
        return root / path
    if not path.is_absolute() and (REPO_ROOT / path).exists():
        return REPO_ROOT / path
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _behavioral_passes(row: Mapping[str, Any]) -> dict[str, bool | None]:
    raw = _behavioral_result_payload(row)
    if not isinstance(raw, Mapping):
        return {}
    passes: dict[str, bool | None] = {}
    for test_name, value in raw.items():
        if isinstance(test_name, str) and test_name.strip():
            passes[test_name] = _passed(value)
    return passes


def _behavioral_row_errors(
    row: Mapping[str, Any],
    *,
    fmt: str,
    index: int,
) -> list[str]:
    raw = _behavioral_result_payload(row)
    if not isinstance(raw, Mapping):
        return [f"row {index}: behavioral results must be an object"]
    applicable = set(DIMENSIONS_BY_FORMAT[fmt])
    errors: list[str] = []
    for test_name, value in raw.items():
        if not isinstance(test_name, str) or not test_name.strip():
            errors.append(f"row {index}: behavioral test name must be a non-empty string")
            continue
        dimension = ""
        if isinstance(value, Mapping):
            raw_dimension = value.get("dimension")
            if raw_dimension is not None:
                if not isinstance(raw_dimension, str):
                    errors.append(
                        f"row {index}: behavioral test {test_name!r} dimension "
                        "must be a string"
                    )
                    errors.extend(
                        _behavioral_value_errors(
                            value,
                            test_name=test_name,
                            index=index,
                        )
                    )
                    continue
                dimension = raw_dimension.strip()
        if not dimension:
            dimension = dimension_from_behavioral_test(test_name)
        if dimension not in applicable:
            errors.append(
                f"row {index}: behavioral test {test_name!r} dimension "
                f"{dimension!r} is not applicable to {fmt}"
            )
        errors.extend(_behavioral_value_errors(value, test_name=test_name, index=index))
    return errors


def _behavioral_result_payload(row: Mapping[str, Any]) -> Any:
    for field_name in BEHAVIORAL_RESULT_FIELDS:
        if field_name in row:
            return row.get(field_name)
    return {}


def _behavioral_value_errors(
    value: Any,
    *,
    test_name: str,
    index: int,
) -> list[str]:
    """Validate one behavioral result payload before pass/fail inference."""
    if isinstance(value, bool):
        return []
    if not isinstance(value, Mapping):
        return [
            f"row {index}: behavioral test {test_name!r} result must be a boolean "
            "or an object"
        ]

    errors: list[str] = []
    if "passed" in value and not isinstance(value.get("passed"), bool):
        errors.append(
            f"row {index}: behavioral test {test_name!r} passed must be a boolean"
        )

    for key in ("score", "threshold"):
        if key not in value:
            continue
        raw = value.get(key)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            errors.append(
                f"row {index}: behavioral test {test_name!r} {key} must be numeric"
            )
            continue
        numeric = float(raw)
        if not math.isfinite(numeric):
            errors.append(
                f"row {index}: behavioral test {test_name!r} {key} must be finite"
            )
            continue
        if numeric < 0.0 or numeric > 1.0:
            errors.append(
                f"row {index}: behavioral test {test_name!r} {key} "
                "must be between 0.0 and 1.0"
            )

    return errors


def _passed(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, Mapping):
        return None
    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed
    score = value.get("score")
    threshold = value.get("threshold")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        if not math.isfinite(float(score)):
            return None
        if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
            if not math.isfinite(float(threshold)):
                return None
            return float(score) >= float(threshold)
        return float(score) >= 0.8
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="check behavioral corpus discrimination")
    check.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    check.add_argument("--results", default=str(DEFAULT_RESULTS_PATH))
    check.add_argument("--min-pass-rate", type=float, default=0.95)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_cmd_check)
    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    annotations, annotation_errors = load_annotation_records(root)
    rows, row_errors = load_behavioral_result_rows(Path(args.results))
    summary = summarize_behavioral_discrimination(
        annotations,
        rows,
        min_pass_rate=args.min_pass_rate,
        root=root,
    )
    summary["root"] = str(root)
    summary["results"] = str(Path(args.results))
    summary["annotation_errors"] = annotation_errors
    summary["result_load_errors"] = row_errors
    summary["errors"] = [
        *summary["errors"],
        *[f"{path}: {len(errors)} validation error(s)" for path, errors in annotation_errors.items()],
        *row_errors,
    ]
    summary["ready"] = not summary["errors"]
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"root: {summary['root']}")
        print(f"results: {summary['results']}")
        print(f"total annotations: {summary['total_annotations']}")
        print(f"pass rate by format: {summary['pass_rate_by_format']}")
        if summary["errors"]:
            print("Behavioral corpus discrimination: FAIL")
            for error in summary["errors"]:
                print(f"  - {error}")
        else:
            print("Behavioral corpus discrimination: OK")
    return 1 if summary["errors"] else 0


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
