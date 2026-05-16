from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.annotate_corpus import build_annotation_record, write_annotation_record
from tools.verify_corpus_snapshots import main, summarize_snapshot_gate


def _snapshot(
    doc_id: str,
    fmt: str,
    source_path: str,
    *,
    annotation_path: Path | None = None,
) -> dict:
    source = Path(source_path)
    return {
        "doc_id": doc_id,
        "format": fmt,
        "source_path": source_path,
        "endpoint": "/v1/office/remediate"
        if fmt in {"docx", "pptx", "xlsx"}
        else "/v1/remediate",
        "captured_at": "2026-05-08T00:00:00+00:00",
        "quality_false": True,
        "quality_result_absent": True,
        "default_response_metadata": {},
        "job_id": "job-1",
        "final_job_status": "done",
        "annotation_sha256": hashlib.sha256(annotation_path.read_bytes()).hexdigest()
        if annotation_path is not None
        else "d" * 64,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()
        if source.exists()
        else "c" * 64,
        "default_response_sha256": "a" * 64,
        "default_output_sha256": "b" * 64,
    }


def test_snapshot_gate_fails_when_annotation_is_missing_default_snapshot(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    write_annotation_record(
        build_annotation_record(
            source_path=tmp_path / "source.pdf",
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["missing_snapshots"] == [str(root / "snapshots" / "pdf" / "pdf-001.json")]
    assert main(["check", "--root", str(root)]) == 1


def test_snapshot_gate_accepts_quality_false_hash_snapshot(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.docx"
    source.write_bytes(b"source-docx")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="docx",
            doc_id="docx-001",
            document_class="technical_doc",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    snapshot_path = root / "snapshots" / "docx" / "docx-001.json"
    snapshot_path.write_text(
        json.dumps(
            _snapshot(
                "docx-001",
                "docx",
                str(source),
                annotation_path=annotation_path,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is True
    assert summary["missing_snapshots"] == []
    assert summary["stale_snapshots"] == []
    assert summary["invalid_snapshots"] == {}
    assert main(["check", "--root", str(root), "--json"]) == 0


def test_snapshot_gate_rejects_wrong_default_endpoint(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pptx"
    source.write_bytes(b"source-pptx")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pptx",
            doc_id="pptx-001",
            document_class="slide_deck",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pptx-001", "pptx", str(source), annotation_path=annotation_path)
    payload["endpoint"] = "/v1/remediate"
    snapshot_path = root / "snapshots" / "pptx" / "pptx-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["endpoint must be '/v1/office/remediate'"]
    }


def test_snapshot_gate_rejects_non_object_snapshot_payload(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(["not-an-object"]), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["snapshot payload must be an object"]
    }


def test_snapshot_gate_rejects_incomplete_job_snapshot(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["final_job_status"] = "failed"
    payload["job_id"] = ""
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): [
            "final_job_status must be 'done'",
            "job_id must be non-empty",
        ]
    }


def test_snapshot_gate_rejects_coerced_boolean_and_string_fields(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["quality_false"] = 1
    payload["quality_result_absent"] = 1
    payload["job_id"] = ["job-1"]
    payload["captured_at"] = ["2026-05-08T00:00:00+00:00"]
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): [
            "quality_false must be True",
            "quality_result_absent must be True",
            "quality_result_absent must match default_response_metadata",
            "job_id must be non-empty",
            "captured_at must be non-empty",
        ]
    }


def test_snapshot_gate_rejects_default_metadata_with_quality_result(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["default_response_metadata"] = {"quality_result": {"overall_pass": True}}
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): [
            "default_response_metadata must not contain quality_result",
            "quality_result_absent must match default_response_metadata",
        ]
    }


def test_snapshot_gate_rejects_default_metadata_with_quality_requested(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["default_response_metadata"] = {"quality": True}
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["default_response_metadata.quality must be absent or False"]
    }


def test_snapshot_gate_accepts_explicit_quality_false_metadata(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["default_response_metadata"] = {"quality": False}
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is True
    assert summary["invalid_snapshots"] == {}


def test_snapshot_gate_rejects_top_level_quality_result(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["quality_result"] = {"overall_pass": True}
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["snapshot payload must not contain quality_result"]
    }


def test_snapshot_gate_rejects_timezone_less_capture_timestamp(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-pdf")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["captured_at"] = "2026-05-08T00:00:00"
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["captured_at must include a timezone"]
    }


def test_snapshot_gate_rejects_source_hash_mismatch(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-v1")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    payload["source_sha256"] = "d" * 64
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): [
            "source_sha256 must match annotation artifact_hashes.source_sha256",
            "source_sha256 must match source_path artifact bytes",
        ]
    }


def test_snapshot_gate_rejects_annotation_source_hash_mismatch(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-v1")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    record = json.loads(annotation_path.read_text(encoding="utf-8"))
    record["artifact_hashes"]["source_sha256"] = "0" * 64
    annotation_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["source_sha256 must match annotation artifact_hashes.source_sha256"]
    }


def test_snapshot_gate_rejects_stale_annotation_hash(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-v1")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    payload = _snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    record = json.loads(annotation_path.read_text(encoding="utf-8"))
    record["document_class"] = "updated-paper"
    annotation_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["invalid_snapshots"] == {
        str(snapshot_path): ["annotation_sha256 must match annotation file bytes"]
    }


def test_snapshot_gate_rejects_stale_snapshot_files(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-v1")
    annotation_path = write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-001",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    snapshot_path = root / "snapshots" / "pdf" / "pdf-001.json"
    snapshot_path.write_text(
        json.dumps(_snapshot("pdf-001", "pdf", str(source), annotation_path=annotation_path)),
        encoding="utf-8",
    )
    stale_path = root / "snapshots" / "pdf" / "stale-doc.json"
    stale_path.write_text(json.dumps({"doc_id": "stale-doc"}), encoding="utf-8")

    summary = summarize_snapshot_gate(root)

    assert summary["ready"] is False
    assert summary["missing_snapshots"] == []
    assert summary["stale_snapshots"] == [str(stale_path)]
