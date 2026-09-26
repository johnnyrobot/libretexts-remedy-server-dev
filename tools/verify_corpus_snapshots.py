"""Verify committed corpus default-flow snapshot records.

This gate is intentionally strict about evidence and conservative about what
it proves. It verifies that every annotated corpus item has a stored
``quality=false`` snapshot record with stable hashes and no quality result in
the default response metadata. Generating and refreshing those snapshots is a
separate corpus operation using the real remediation endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.annotate_corpus import (
    DEFAULT_CORPUS_ROOT,
    SUPPORTED_FORMATS,
    iter_annotation_paths,
    validate_annotation_file,
)


_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_OFFICE_FORMATS = {"docx", "pptx", "xlsx"}


def expected_default_endpoint(fmt: str) -> str:
    """Return the PRD-required default remediation endpoint for a format."""
    return "/v1/office/remediate" if fmt in _OFFICE_FORMATS else "/v1/remediate"


def snapshot_path_for(root: Path, record: dict[str, Any]) -> Path:
    """Return the expected snapshot path for one annotation record."""
    return root / "snapshots" / record["format"] / f"{record['doc_id']}.json"


def validate_snapshot_payload(
    payload: Any,
    *,
    record: dict[str, Any],
    annotation_path: Path | None = None,
) -> list[str]:
    """Validate one snapshot payload against its annotation record."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["snapshot payload must be an object"]
    expected_strings = {
        "doc_id": record["doc_id"],
        "format": record["format"],
        "source_path": record["source_path"],
        "endpoint": expected_default_endpoint(str(record["format"])),
        "final_job_status": "done",
    }
    for key, value in expected_strings.items():
        if payload.get(key) != value:
            errors.append(f"{key} must be {value!r}")
    for key in ("quality_false", "quality_result_absent"):
        if payload.get(key) is not True:
            errors.append(f"{key} must be True")
    if "quality_result" in payload:
        errors.append("snapshot payload must not contain quality_result")
    metadata = payload.get("default_response_metadata")
    if not isinstance(metadata, dict):
        errors.append("default_response_metadata must be an object")
    else:
        if "quality" in metadata and metadata["quality"] is not False:
            errors.append("default_response_metadata.quality must be absent or False")
        if "quality_result" in metadata:
            errors.append("default_response_metadata must not contain quality_result")
        if payload.get("quality_result_absent") is not ("quality_result" not in metadata):
            errors.append(
                "quality_result_absent must match default_response_metadata"
            )
    annotation_sha = payload.get("annotation_sha256")
    if not isinstance(annotation_sha, str) or not _SHA256_RE.match(annotation_sha):
        errors.append("annotation_sha256 must be a sha256 hex digest")
    elif annotation_path is not None:
        actual = _sha256_file(annotation_path)
        if annotation_sha != actual:
            errors.append("annotation_sha256 must match annotation file bytes")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        errors.append("job_id must be non-empty")
    for key in ("default_response_sha256", "default_output_sha256"):
        value = payload.get(key)
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            errors.append(f"{key} must be a sha256 hex digest")
    source_sha = payload.get("source_sha256")
    if not isinstance(source_sha, str) or not _SHA256_RE.match(source_sha):
        errors.append("source_sha256 must be a sha256 hex digest")
    else:
        artifact_hashes = record.get("artifact_hashes")
        if isinstance(artifact_hashes, dict):
            expected_source_sha = artifact_hashes.get("source_sha256")
            if not isinstance(expected_source_sha, str) or not _SHA256_RE.match(expected_source_sha):
                errors.append("annotation artifact_hashes.source_sha256 must be a sha256 hex digest")
            elif source_sha != expected_source_sha:
                errors.append("source_sha256 must match annotation artifact_hashes.source_sha256")
        source_path = Path(str(record.get("source_path") or ""))
        if source_path.exists():
            actual = _sha256_file(source_path)
            if source_sha != actual:
                errors.append("source_sha256 must match source_path artifact bytes")
    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        errors.append("captured_at must be non-empty")
    else:
        try:
            parsed_captured_at = datetime.fromisoformat(
                captured_at.strip().replace("Z", "+00:00")
            )
        except ValueError:
            errors.append("captured_at must be an ISO date-time string")
        else:
            if parsed_captured_at.tzinfo is None:
                errors.append("captured_at must include a timezone")
    return errors


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def summarize_snapshot_gate(root: Path) -> dict[str, Any]:
    """Summarize missing or invalid snapshot records for a corpus root."""
    missing: list[str] = []
    invalid: dict[str, list[str]] = {}
    annotation_errors: dict[str, list[str]] = {}
    total_annotations = 0
    expected_snapshot_paths: set[str] = set()

    for annotation_path in iter_annotation_paths(root):
        errors = validate_annotation_file(annotation_path)
        if errors:
            annotation_errors[str(annotation_path)] = [str(error) for error in errors]
            continue
        total_annotations += 1
        record = json.loads(annotation_path.read_text(encoding="utf-8"))
        snapshot_path = snapshot_path_for(root, record)
        expected_snapshot_paths.add(str(snapshot_path))
        if not snapshot_path.exists():
            missing.append(str(snapshot_path))
            continue
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            invalid[str(snapshot_path)] = [f"invalid JSON: {exc}"]
            continue
        snapshot_errors = validate_snapshot_payload(
            payload,
            record=record,
            annotation_path=annotation_path,
        )
        if snapshot_errors:
            invalid[str(snapshot_path)] = snapshot_errors

    existing_snapshot_paths = {
        str(path)
        for fmt in SUPPORTED_FORMATS
        for path in sorted((root / "snapshots" / fmt).glob("*.json"))
    }
    stale_snapshots = sorted(existing_snapshot_paths - expected_snapshot_paths)

    return {
        "root": str(root),
        "total_annotations": total_annotations,
        "missing_snapshots": missing,
        "stale_snapshots": stale_snapshots,
        "invalid_snapshots": invalid,
        "annotation_errors": annotation_errors,
        "ready": bool(total_annotations)
        and not missing
        and not stale_snapshots
        and not invalid
        and not annotation_errors,
    }


def ensure_snapshot_layout(root: Path) -> None:
    """Create empty snapshot directories for all supported formats."""
    for fmt in SUPPORTED_FORMATS:
        path = root / "snapshots" / fmt
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").touch()


def _cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_snapshot_layout(root)
    print(f"initialized snapshot layout under {root}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    summary = summarize_snapshot_gate(root)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ready"] else 1

    print(f"root: {summary['root']}")
    print(f"total annotations: {summary['total_annotations']}")
    print(f"missing snapshots: {len(summary['missing_snapshots'])}")
    print(f"stale snapshots: {len(summary['stale_snapshots'])}")
    print(f"invalid snapshots: {len(summary['invalid_snapshots'])}")
    print(f"annotation errors: {len(summary['annotation_errors'])}")
    print("snapshot gate: OK" if summary["ready"] else "snapshot gate: FAIL")
    for path in summary["missing_snapshots"]:
        print(f"  missing: {path}", file=sys.stderr)
    for path in summary["stale_snapshots"]:
        print(f"  stale: {path}", file=sys.stderr)
    for label_prefix, mapping in (
        ("invalid", summary["invalid_snapshots"]),
        ("annotation", summary["annotation_errors"]),
    ):
        for path, errors in mapping.items():
            for error in errors:
                print(f"  {label_prefix} {path}: {error}", file=sys.stderr)
    return 0 if summary["ready"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create snapshot directory layout")
    init.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    init.set_defaults(func=_cmd_init)

    check = subparsers.add_parser("check", help="verify default-flow snapshots")
    check.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_cmd_check)

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
