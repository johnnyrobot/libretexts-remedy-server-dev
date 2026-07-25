"""Capture default-flow corpus snapshot records from a running Remedy API."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.annotate_corpus import (
    DEFAULT_CORPUS_ROOT,
    iter_annotation_paths,
    validate_annotation_file,
)
from tools.verify_corpus_snapshots import snapshot_path_for, validate_snapshot_payload


OFFICE_FORMATS = {"docx", "pptx", "xlsx"}
JOB_STATUSES = {"queued", "running", "done", "failed"}
TERMINAL_JOB_STATUSES = {"done", "failed"}


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def build_snapshot_payload(
    *,
    record: dict[str, Any],
    endpoint: str,
    initial_response: dict[str, Any],
    final_response: dict[str, Any],
    result_bytes: bytes,
    annotation_sha256: str = "",
) -> dict[str, Any]:
    """Build a verifier-compatible default-flow snapshot payload."""
    initial_json = json.dumps(initial_response, sort_keys=True, separators=(",", ":")).encode()
    metadata = _metadata_dict(final_response)
    return {
        "doc_id": record["doc_id"],
        "format": record["format"],
        "source_path": record["source_path"],
        "endpoint": endpoint,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quality_false": "quality" not in metadata or metadata["quality"] is False,
        "quality_result_absent": "quality_result" not in metadata,
        "default_response_metadata": metadata,
        "job_id": final_response.get("id", initial_response.get("id", "")),
        "annotation_sha256": annotation_sha256,
        "source_sha256": sha256_hex(Path(record["source_path"]).read_bytes()),
        "default_response_sha256": sha256_hex(initial_json),
        "default_output_sha256": sha256_hex(result_bytes),
        "final_job_status": final_response.get("status", ""),
    }


def endpoint_for_record(record: dict[str, Any], *, mode: str) -> str:
    """Return the default-flow endpoint to use for an annotation record."""
    fmt = record["format"]
    if mode == "generic":
        return "/v1/remediate"
    if mode == "format":
        return "/v1/office/remediate" if fmt in OFFICE_FORMATS else "/v1/remediate"
    raise ValueError(f"unsupported endpoint mode: {mode}")


def write_snapshot_payload(root: Path, record: dict[str, Any], payload: dict[str, Any]) -> Path:
    """Write one snapshot payload at the verifier's expected path."""
    path = snapshot_path_for(root, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def capture_record_snapshot(
    record: dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    endpoint_mode: str,
    poll_interval: float,
    timeout_seconds: float,
    annotation_sha256: str = "",
) -> dict[str, Any]:
    """Submit one corpus artifact and return its snapshot payload."""
    poll_interval, timeout_seconds = _validate_capture_timing(
        poll_interval,
        timeout_seconds,
        doc_id=record["doc_id"],
    )
    source_path = Path(record["source_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"{record['doc_id']}: missing source artifact {source_path}")
    endpoint = endpoint_for_record(record, mode=endpoint_mode)
    initial = _post_file(
        f"{base_url.rstrip('/')}{endpoint}",
        source_path,
        api_key=api_key,
    )
    job_id = _required_response_string(
        initial,
        "id",
        label="upload response job id",
        doc_id=record["doc_id"],
    )
    final = _poll_job(
        base_url.rstrip("/"),
        job_id,
        api_key=api_key,
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
    )
    if final.get("status") != "done":
        raise RuntimeError(f"{record['doc_id']}: job did not complete: {final}")
    final_job_id = final.get("id")
    if final_job_id is not None:
        if not isinstance(final_job_id, str) or not final_job_id.strip():
            raise ValueError(f"{record['doc_id']}: final job id must be a non-empty string")
        if final_job_id.strip() != job_id:
            raise ValueError(f"{record['doc_id']}: final job id must match upload job id")
    final_for_payload = dict(final)
    final_for_payload["id"] = job_id
    result_bytes = _get_bytes(
        f"{base_url.rstrip('/')}/v1/jobs/{job_id}/result",
        api_key=api_key,
    )
    return build_snapshot_payload(
        record=record,
        endpoint=endpoint,
        initial_response=initial,
        final_response=final_for_payload,
        result_bytes=result_bytes,
        annotation_sha256=annotation_sha256,
    )


def load_valid_annotation_records(root: Path) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    """Load all valid annotations from a corpus root."""
    records: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for path in iter_annotation_paths(root):
        validation_errors = validate_annotation_file(path)
        if validation_errors:
            errors.extend(f"{path}: {error}" for error in validation_errors)
            continue
        records.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return records, errors


def _post_file(url: str, file_path: Path, *, api_key: str) -> dict[str, Any]:
    boundary = f"----remedy-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body = _multipart_body(
        boundary=boundary,
        field_name="file",
        filename=file_path.name,
        content_type=content_type,
        data=file_path.read_bytes(),
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return _decode_json_object(response.read(), label="upload response")


def _poll_job(
    base_url: str,
    job_id: str,
    *,
    api_key: str,
    poll_interval: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        payload = _get_json(f"{base_url}/v1/jobs/{job_id}", api_key=api_key)
        status = _job_status(payload, job_id=job_id)
        if status in TERMINAL_JOB_STATUSES:
            return payload
        if time.monotonic() >= deadline:
            raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds}s")
        time.sleep(poll_interval)


def _get_json(url: str, *, api_key: str) -> dict[str, Any]:
    return _decode_json_object(_get_bytes(url, api_key=api_key), label="job response")


def _decode_json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must decode to an object")
    return payload


def _required_response_string(
    payload: dict[str, Any],
    key: str,
    *,
    label: str,
    doc_id: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{doc_id}: {label} must be a non-empty string")
    return value.strip()


def _job_status(payload: dict[str, Any], *, job_id: str) -> str:
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError(f"job {job_id} status must be a non-empty string")
    status_value = status.strip()
    if status_value not in JOB_STATUSES:
        raise ValueError(f"job {job_id} status is unsupported: {status_value}")
    return status_value


def _require_finite_number(
    value: Any,
    *,
    field: str,
    doc_id: str,
    allow_zero: bool,
) -> float:
    """Validate a finite number argument, optionally requiring strictly positive."""
    description = "non-negative" if allow_zero else "positive"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{doc_id}: {field} must be a finite {description} number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{doc_id}: {field} must be a finite {description} number")
    if numeric < 0.0 or (not allow_zero and numeric == 0.0):
        raise ValueError(f"{doc_id}: {field} must be a finite {description} number")
    return numeric


def _validate_capture_timing(
    poll_interval: Any,
    timeout_seconds: Any,
    *,
    doc_id: str,
) -> tuple[float, float]:
    return (
        _require_finite_number(poll_interval, field="poll_interval", doc_id=doc_id, allow_zero=True),
        _require_finite_number(timeout_seconds, field="timeout_seconds", doc_id=doc_id, allow_zero=False),
    )


def _get_bytes(url: str, *, api_key: str) -> bytes:
    headers = {"X-API-Key": api_key} if api_key else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read()


def _multipart_body(
    *,
    boundary: str,
    field_name: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> bytes:
    return b"".join(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )


def _metadata_dict(job_payload: dict[str, Any]) -> dict[str, Any]:
    raw = job_payload.get("metadata_json")
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("metadata_json must be a JSON object string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("metadata_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("metadata_json must decode to an object")
    return parsed


def _cmd_capture(args: argparse.Namespace) -> int:
    root = Path(args.root)
    _validate_capture_timing(
        args.poll_interval,
        args.timeout_seconds,
        doc_id="capture",
    )
    records, errors = load_valid_annotation_records(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    if not records:
        print(f"no annotation JSON files found under {root}", file=sys.stderr)
        return 1

    captured: list[str] = []
    failed: list[str] = []
    selected_records = [
        (annotation_path, record)
        for annotation_path, record in records
        if not args.format or record["format"] == args.format
    ]
    if not selected_records:
        message = f"no annotation JSON files matched capture filter under {root}"
        if args.json:
            print(
                json.dumps(
                    {"captured": [], "failed": [], "selected": 0, "error": message},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(message, file=sys.stderr)
        return 1

    for annotation_path, record in selected_records:
        try:
            annotation_sha256 = sha256_hex(annotation_path.read_bytes())
            payload = capture_record_snapshot(
                record,
                base_url=args.base_url,
                api_key=args.api_key,
                endpoint_mode=args.endpoint_mode,
                poll_interval=args.poll_interval,
                timeout_seconds=args.timeout_seconds,
                annotation_sha256=annotation_sha256,
            )
            snapshot_errors = validate_snapshot_payload(
                payload,
                record=record,
                annotation_path=annotation_path,
            )
            if snapshot_errors:
                detail = "; ".join(snapshot_errors)
                raise ValueError(f"invalid snapshot payload: {detail}")
            path = write_snapshot_payload(root, record, payload)
            captured.append(str(path))
        except (OSError, TimeoutError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            failed.append(f"{record['doc_id']}: {exc}")

    result = {"captured": captured, "failed": failed, "selected": len(selected_records)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"captured: {len(captured)}")
        print(f"failed: {len(failed)}")
        for item in failed:
            print(f"  {item}", file=sys.stderr)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="capture default-flow snapshots")
    capture.add_argument("--root", default=str(DEFAULT_CORPUS_ROOT))
    capture.add_argument("--base-url", default="http://127.0.0.1:8000")
    capture.add_argument("--api-key", default="")
    capture.add_argument("--format", choices=("pdf", "docx", "pptx", "xlsx"))
    capture.add_argument("--endpoint-mode", choices=("format", "generic"), default="format")
    capture.add_argument("--poll-interval", type=float, default=1.0)
    capture.add_argument("--timeout-seconds", type=float, default=300.0)
    capture.add_argument("--json", action="store_true")
    capture.set_defaults(func=_cmd_capture)

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
