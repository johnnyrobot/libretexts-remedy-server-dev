from __future__ import annotations

import json
from pathlib import Path

import tools.capture_corpus_snapshots as capture_snapshots
from tools.annotate_corpus import build_annotation_record, write_annotation_record
from tools.capture_corpus_snapshots import (
    build_snapshot_payload,
    capture_record_snapshot,
    endpoint_for_record,
    main,
    sha256_hex,
    write_snapshot_payload,
)
from tools.verify_corpus_snapshots import validate_snapshot_payload


def test_endpoint_selection_uses_office_specific_endpoint_for_office_formats() -> None:
    assert endpoint_for_record({"format": "pdf"}, mode="format") == "/v1/remediate"
    assert endpoint_for_record({"format": "docx"}, mode="format") == "/v1/office/remediate"
    assert endpoint_for_record({"format": "pptx"}, mode="generic") == "/v1/remediate"


def test_snapshot_payload_is_verifier_compatible(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }
    initial = {"id": "job-1", "status": "queued"}
    final = {"id": "job-1", "status": "done", "metadata_json": "{}"}
    result_bytes = b"%PDF-1.4\n%%EOF"

    payload = build_snapshot_payload(
        record=record,
        endpoint="/v1/remediate",
        initial_response=initial,
        final_response=final,
        result_bytes=result_bytes,
        annotation_sha256="d" * 64,
    )

    assert payload["quality_false"] is True
    assert payload["quality_result_absent"] is True
    assert payload["default_response_metadata"] == {}
    assert payload["annotation_sha256"] == "d" * 64
    assert payload["source_sha256"] == sha256_hex(b"source-pdf")
    assert payload["default_output_sha256"] == sha256_hex(result_bytes)
    assert validate_snapshot_payload(payload, record=record) == []


def test_snapshot_payload_records_default_response_metadata(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }
    payload = build_snapshot_payload(
        record=record,
        endpoint="/v1/remediate",
        initial_response={"id": "job-1", "status": "queued"},
        final_response={
            "id": "job-1",
            "status": "done",
            "metadata_json": json.dumps({"quality_result": {"overall_pass": True}}),
        },
        result_bytes=b"%PDF-1.4\n%%EOF",
        annotation_sha256="d" * 64,
    )

    assert payload["quality_result_absent"] is False
    assert payload["default_response_metadata"] == {
        "quality_result": {"overall_pass": True}
    }
    assert validate_snapshot_payload(payload, record=record) == [
        "quality_result_absent must be True",
        "default_response_metadata must not contain quality_result",
    ]


def test_snapshot_payload_marks_quality_true_metadata_as_not_default(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    payload = build_snapshot_payload(
        record=record,
        endpoint="/v1/remediate",
        initial_response={"id": "job-1", "status": "queued"},
        final_response={
            "id": "job-1",
            "status": "done",
            "metadata_json": json.dumps({"quality": True}),
        },
        result_bytes=b"%PDF-1.4\n%%EOF",
        annotation_sha256="d" * 64,
    )

    assert payload["quality_false"] is False
    assert validate_snapshot_payload(payload, record=record) == [
        "quality_false must be True",
        "default_response_metadata.quality must be absent or False",
    ]


def test_snapshot_payload_accepts_explicit_quality_false_metadata(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    payload = build_snapshot_payload(
        record=record,
        endpoint="/v1/remediate",
        initial_response={"id": "job-1", "status": "queued"},
        final_response={
            "id": "job-1",
            "status": "done",
            "metadata_json": json.dumps({"quality": False}),
        },
        result_bytes=b"%PDF-1.4\n%%EOF",
        annotation_sha256="d" * 64,
    )

    assert payload["quality_false"] is True
    assert validate_snapshot_payload(payload, record=record) == []


def test_snapshot_payload_rejects_malformed_default_metadata_json(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    try:
        build_snapshot_payload(
            record=record,
            endpoint="/v1/remediate",
            initial_response={"id": "job-1", "status": "queued"},
            final_response={
                "id": "job-1",
                "status": "done",
                "metadata_json": "{not-json",
            },
            result_bytes=b"%PDF-1.4\n%%EOF",
            annotation_sha256="d" * 64,
        )
    except ValueError as exc:
        assert "metadata_json must be valid JSON" in str(exc)
    else:
        raise AssertionError("malformed metadata_json should fail snapshot capture")


def test_snapshot_payload_rejects_non_object_default_metadata_json(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    try:
        build_snapshot_payload(
            record=record,
            endpoint="/v1/remediate",
            initial_response={"id": "job-1", "status": "queued"},
            final_response={
                "id": "job-1",
                "status": "done",
                "metadata_json": "[]",
            },
            result_bytes=b"%PDF-1.4\n%%EOF",
            annotation_sha256="d" * 64,
        )
    except ValueError as exc:
        assert "metadata_json must decode to an object" in str(exc)
    else:
        raise AssertionError("non-object metadata_json should fail snapshot capture")


def test_write_snapshot_payload_uses_verifier_path(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    record = {
        "doc_id": "docx-001",
        "format": "docx",
        "source_path": str(tmp_path / "source.docx"),
    }
    payload = {
        "doc_id": "docx-001",
        "format": "docx",
        "source_path": str(tmp_path / "source.docx"),
        "endpoint": "/v1/office/remediate",
        "quality_false": True,
        "quality_result_absent": True,
        "default_response_metadata": {},
        "job_id": "job-1",
        "final_job_status": "done",
        "annotation_sha256": "d" * 64,
        "source_sha256": "c" * 64,
        "default_response_sha256": "a" * 64,
        "default_output_sha256": "b" * 64,
        "captured_at": "2026-05-08T00:00:00+00:00",
    }

    path = write_snapshot_payload(root, record, payload)

    assert path == root / "snapshots" / "docx" / "docx-001.json"
    assert json.loads(path.read_text(encoding="utf-8"))["doc_id"] == "docx-001"


def test_capture_record_snapshot_submits_polls_and_downloads_result(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"fake-docx")
    record = {
        "doc_id": "docx-001",
        "format": "docx",
        "source_path": str(source),
    }
    calls: list[tuple[str, str]] = []

    def fake_post_file(url: str, file_path: Path, *, api_key: str) -> dict:
        calls.append(("post", url))
        assert file_path == source
        assert api_key == "secret"
        return {"id": "job-1", "status": "queued"}

    def fake_poll_job(
        base_url: str,
        job_id: str,
        *,
        api_key: str,
        poll_interval: float,
        timeout_seconds: float,
    ) -> dict:
        calls.append(("poll", f"{base_url}:{job_id}"))
        assert api_key == "secret"
        assert poll_interval == 0.01
        assert timeout_seconds == 2.0
        return {"id": job_id, "status": "done", "metadata_json": "{}"}

    def fake_get_bytes(url: str, *, api_key: str) -> bytes:
        calls.append(("get", url))
        assert api_key == "secret"
        return b"default-output"

    monkeypatch.setattr(capture_snapshots, "_post_file", fake_post_file)
    monkeypatch.setattr(capture_snapshots, "_poll_job", fake_poll_job)
    monkeypatch.setattr(capture_snapshots, "_get_bytes", fake_get_bytes)

    payload = capture_record_snapshot(
        record,
        base_url="http://api.example",
        api_key="secret",
        endpoint_mode="format",
        poll_interval=0.01,
        timeout_seconds=2.0,
        annotation_sha256="d" * 64,
    )

    assert calls == [
        ("post", "http://api.example/v1/office/remediate"),
        ("poll", "http://api.example:job-1"),
        ("get", "http://api.example/v1/jobs/job-1/result"),
    ]
    assert payload["endpoint"] == "/v1/office/remediate"
    assert payload["annotation_sha256"] == "d" * 64
    assert payload["source_sha256"] == sha256_hex(b"fake-docx")
    assert payload["default_output_sha256"] == sha256_hex(b"default-output")


def test_capture_record_snapshot_rejects_non_string_upload_job_id(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    monkeypatch.setattr(
        capture_snapshots,
        "_post_file",
        lambda url, file_path, *, api_key: {"id": 123, "status": "queued"},
    )

    try:
        capture_record_snapshot(
            record,
            base_url="http://api.example",
            api_key="",
            endpoint_mode="format",
            poll_interval=0.01,
            timeout_seconds=1.0,
        )
    except ValueError as exc:
        assert "upload response job id must be a non-empty string" in str(exc)
    else:
        raise AssertionError("non-string upload job id should fail snapshot capture")


def test_capture_record_snapshot_rejects_mismatched_final_job_id(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    monkeypatch.setattr(
        capture_snapshots,
        "_post_file",
        lambda url, file_path, *, api_key: {"id": "job-1", "status": "queued"},
    )
    monkeypatch.setattr(
        capture_snapshots,
        "_poll_job",
        lambda base_url, job_id, *, api_key, poll_interval, timeout_seconds: {
            "id": "job-2",
            "status": "done",
            "metadata_json": "{}",
        },
    )

    try:
        capture_record_snapshot(
            record,
            base_url="http://api.example",
            api_key="",
            endpoint_mode="format",
            poll_interval=0.01,
            timeout_seconds=1.0,
        )
    except ValueError as exc:
        assert "final job id must match upload job id" in str(exc)
    else:
        raise AssertionError("mismatched final job id should fail snapshot capture")


def test_capture_record_snapshot_rejects_malformed_polling_arguments(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(source),
    }

    for poll_interval, timeout_seconds, expected in [
        (True, 1.0, "poll_interval must be a finite non-negative number"),
        (float("nan"), 1.0, "poll_interval must be a finite non-negative number"),
        (-0.1, 1.0, "poll_interval must be a finite non-negative number"),
        (0.01, False, "timeout_seconds must be a finite positive number"),
        (0.01, float("inf"), "timeout_seconds must be a finite positive number"),
        (0.01, 0.0, "timeout_seconds must be a finite positive number"),
    ]:
        try:
            capture_record_snapshot(
                record,
                base_url="http://api.example",
                api_key="",
                endpoint_mode="format",
                poll_interval=poll_interval,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed polling argument should fail snapshot capture")


def test_capture_record_snapshot_rejects_missing_source(tmp_path) -> None:
    record = {
        "doc_id": "pdf-001",
        "format": "pdf",
        "source_path": str(tmp_path / "missing.pdf"),
    }

    try:
        capture_record_snapshot(
            record,
            base_url="http://api.example",
            api_key="",
            endpoint_mode="format",
            poll_interval=0.01,
            timeout_seconds=1.0,
        )
    except FileNotFoundError as exc:
        assert "missing source artifact" in str(exc)
    else:
        raise AssertionError("missing source artifact should fail snapshot capture")


def test_capture_http_json_helpers_require_object_payloads(monkeypatch) -> None:
    monkeypatch.setattr(
        capture_snapshots,
        "_get_bytes",
        lambda url, *, api_key: b"[]",
    )

    try:
        capture_snapshots._get_json("http://api.example/v1/jobs/job-1", api_key="")
    except ValueError as exc:
        assert "job response must decode to an object" in str(exc)
    else:
        raise AssertionError("non-object job response should fail")

    monkeypatch.setattr(
        capture_snapshots,
        "_get_bytes",
        lambda url, *, api_key: b"{not-json",
    )

    try:
        capture_snapshots._get_json("http://api.example/v1/jobs/job-1", api_key="")
    except ValueError as exc:
        assert "job response must be valid JSON" in str(exc)
    else:
        raise AssertionError("invalid job JSON should fail")


def test_poll_job_rejects_malformed_job_status(monkeypatch) -> None:
    for payload, expected in [
        ({"id": "job-1"}, "job job-1 status must be a non-empty string"),
        ({"id": "job-1", "status": 123}, "job job-1 status must be a non-empty string"),
        ({"id": "job-1", "status": "cancelled"}, "job job-1 status is unsupported: cancelled"),
    ]:
        monkeypatch.setattr(
            capture_snapshots,
            "_get_json",
            lambda url, *, api_key, payload=payload: payload,
        )

        try:
            capture_snapshots._poll_job(
                "http://api.example",
                "job-1",
                api_key="",
                poll_interval=0.0,
                timeout_seconds=1.0,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed job status should fail polling")


def test_poll_job_accepts_pending_then_terminal_status(monkeypatch) -> None:
    responses = iter(
        [
            {"id": "job-1", "status": "queued"},
            {"id": "job-1", "status": "running"},
            {"id": "job-1", "status": "done"},
        ]
    )
    monkeypatch.setattr(
        capture_snapshots,
        "_get_json",
        lambda url, *, api_key: next(responses),
    )
    monkeypatch.setattr(capture_snapshots.time, "sleep", lambda seconds: None)

    payload = capture_snapshots._poll_job(
        "http://api.example",
        "job-1",
        api_key="",
        poll_interval=0.0,
        timeout_seconds=1.0,
    )

    assert payload == {"id": "job-1", "status": "done"}


def test_capture_cli_writes_snapshot_payload(monkeypatch, tmp_path, capsys) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    annotation = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-001",
        document_class="paper",
        annotator="specialist-a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    write_annotation_record(annotation, root=root)

    def fake_capture_record_snapshot(
        record: dict,
        *,
        base_url: str,
        api_key: str,
        endpoint_mode: str,
        poll_interval: float,
        timeout_seconds: float,
        annotation_sha256: str,
    ) -> dict:
        assert record["doc_id"] == "pdf-001"
        assert base_url == "http://api.example"
        assert api_key == "secret"
        assert endpoint_mode == "format"
        assert poll_interval == 0.01
        assert timeout_seconds == 1.0
        assert annotation_sha256 == sha256_hex((root / "annotations" / "pdf" / "pdf-001.json").read_bytes())
        return {
            "doc_id": "pdf-001",
            "format": "pdf",
            "source_path": str(source),
            "endpoint": "/v1/remediate",
            "quality_false": True,
            "quality_result_absent": True,
            "default_response_metadata": {},
            "job_id": "job-1",
            "final_job_status": "done",
            "annotation_sha256": annotation_sha256,
            "source_sha256": sha256_hex(source.read_bytes()),
            "default_response_sha256": "a" * 64,
            "default_output_sha256": "b" * 64,
            "captured_at": "2026-05-08T00:00:00+00:00",
        }

    monkeypatch.setattr(
        capture_snapshots,
        "capture_record_snapshot",
        fake_capture_record_snapshot,
    )

    exit_code = main(
        [
            "capture",
            "--root",
            str(root),
            "--base-url",
            "http://api.example",
            "--api-key",
            "secret",
            "--poll-interval",
            "0.01",
            "--timeout-seconds",
            "1.0",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["failed"] == []
    assert output["selected"] == 1
    assert output["captured"] == [str(root / "snapshots" / "pdf" / "pdf-001.json")]
    assert (root / "snapshots" / "pdf" / "pdf-001.json").exists()
    payload = json.loads((root / "snapshots" / "pdf" / "pdf-001.json").read_text(encoding="utf-8"))
    assert payload["annotation_sha256"] == sha256_hex(
        (root / "annotations" / "pdf" / "pdf-001.json").read_bytes()
    )


def test_capture_cli_fails_when_format_filter_matches_no_annotations(tmp_path, capsys) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist-a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )

    exit_code = main(["capture", "--root", str(root), "--format", "docx", "--json"])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["selected"] == 0
    assert "no annotation JSON files matched capture filter" in output["error"]


def test_capture_cli_rejects_malformed_polling_arguments(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "capture",
            "--root",
            str(tmp_path / "corpus" / "v1"),
            "--poll-interval",
            "nan",
        ]
    )

    assert exit_code == 2
    assert "poll_interval must be a finite non-negative number" in capsys.readouterr().err


def test_capture_cli_rejects_invalid_snapshot_payload(monkeypatch, tmp_path, capsys) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist-a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )

    def fake_capture_record_snapshot(
        record: dict,
        *,
        base_url: str,
        api_key: str,
        endpoint_mode: str,
        poll_interval: float,
        timeout_seconds: float,
        annotation_sha256: str,
    ) -> dict:
        return {
            "doc_id": "pdf-001",
            "format": "pdf",
            "source_path": str(source),
            "endpoint": "/v1/remediate",
            "quality_false": True,
            "quality_result_absent": True,
            "default_response_metadata": {},
            "job_id": "job-1",
            "final_job_status": "done",
            "annotation_sha256": annotation_sha256,
            "source_sha256": "0" * 64,
            "default_response_sha256": "a" * 64,
            "default_output_sha256": "b" * 64,
            "captured_at": "2026-05-08T00:00:00+00:00",
        }

    monkeypatch.setattr(
        capture_snapshots,
        "capture_record_snapshot",
        fake_capture_record_snapshot,
    )

    exit_code = main(["capture", "--root", str(root), "--json"])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["captured"] == []
    assert output["selected"] == 1
    assert "invalid snapshot payload" in output["failed"][0]
    assert not (root / "snapshots" / "pdf" / "pdf-001.json").exists()
