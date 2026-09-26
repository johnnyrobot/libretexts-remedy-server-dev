from __future__ import annotations

import hashlib
import json

from tools.annotate_corpus import build_annotation_record, write_annotation_record
from tools.verify_behavioral_corpus import (
    main,
    summarize_behavioral_discrimination,
)


def test_behavioral_discrimination_passes_when_gold_passes_and_known_bad_fails() -> None:
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "dimensions": {"alt_text": {"score": 0.9}},
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is True
    assert summary["pass_rate_by_format"]["pdf"] == 1.0
    assert summary["failed_entries"] == {}


def test_behavioral_discrimination_fails_missing_or_non_distinguishing_rows() -> None:
    annotations = [
        {"doc_id": "pdf-1", "format": "pdf"},
        {"doc_id": "pdf-2", "format": "pdf"},
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral_results": {"alt_text_substitution": True},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral_results": {"alt_text_substitution": True},
        },
        {
            "doc_id": "pdf-2",
            "format": "pdf",
            "variant": "gold",
            "behavioral_results": {"alt_text_substitution": True},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["pass_rate_by_format"]["pdf"] == 0.0
    assert "pdf-1" in summary["failed_entries"]
    assert "pdf-2" in summary["failed_entries"]
    assert "2 annotation(s) failed behavioral discrimination" in summary["errors"]


def test_behavioral_discrimination_rejects_duplicate_result_rows() -> None:
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "dimensions": {"alt_text": {"score": 0.9}},
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "reference",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == ["row 1: duplicate gold behavioral result row for pdf-1/pdf"]
    assert "row 1: duplicate gold behavioral result row for pdf-1/pdf" in summary["errors"]


def test_behavioral_discrimination_rejects_non_string_result_identity_fields() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": 123,
            "format": "pdf",
            "variant": "gold",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": 123,
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": 123,
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == [
        "row 0: doc_id must be a non-empty string",
        "row 1: format must be a non-empty string",
        "row 2: variant must be a string",
    ]


def test_behavioral_discrimination_rejects_non_string_annotation_identity_fields() -> None:
    annotations = [
        {"doc_id": 123, "format": "pdf"},
        {"doc_id": "pdf-1", "format": 123},
        {"doc_id": "txt-1", "format": "txt"},
    ]
    rows = [
        {
            "doc_id": "123",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "123",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["annotation_record_errors"] == {
        "<annotation:0>": ["annotation 0: doc_id must be a non-empty string"],
        "pdf-1": ["annotation 1: format must be a non-empty string"],
        "txt-1": ["annotation 2: unsupported format 'txt'"],
    }
    assert (
        "3 annotation(s) have invalid behavioral annotation identity"
        in summary["errors"]
    )
    assert summary["totals_by_format"]["pdf"] == 0


def test_behavioral_discrimination_rejects_inapplicable_test_dimensions() -> None:
    annotations = [
        {
            "doc_id": "xlsx-1",
            "format": "xlsx",
            "dimensions": {"sheet_organization": {"score": 0.9}},
        }
    ]
    rows = [
        {
            "doc_id": "xlsx-1",
            "format": "xlsx",
            "variant": "gold",
            "behavioral": {"reading_order_comprehension": {"passed": True}},
        },
        {
            "doc_id": "xlsx-1",
            "format": "xlsx",
            "variant": "known_bad",
            "behavioral": {
                "sheet_navigation": {
                    "dimension": "reading_order",
                    "passed": False,
                }
            },
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == [
        "row 0: behavioral test 'reading_order_comprehension' "
        "dimension 'reading_order' is not applicable to xlsx",
        "row 1: behavioral test 'sheet_navigation' "
        "dimension 'reading_order' is not applicable to xlsx",
    ]


def test_behavioral_discrimination_accepts_explicit_xlsx_transcript_dimension() -> None:
    annotations = [{"doc_id": "xlsx-1", "format": "xlsx"}]
    rows = [
        {
            "doc_id": "xlsx-1",
            "format": "xlsx",
            "variant": "gold",
            "behavioral": {
                "screen_reader_transcript_analysis": {
                    "dimension": "sheet_organization",
                    "passed": True,
                }
            },
        },
        {
            "doc_id": "xlsx-1",
            "format": "xlsx",
            "variant": "known_bad",
            "behavioral": {
                "screen_reader_transcript_analysis": {
                    "dimension": "sheet_organization",
                    "passed": False,
                }
            },
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is True
    assert summary["row_errors"] == []
    assert summary["pass_rate_by_format"]["xlsx"] == 1.0


def test_behavioral_discrimination_rejects_malformed_test_names_and_dimensions() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {
                123: {"passed": True},
                "alt_text_substitution": {"dimension": 123, "passed": True},
            },
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {
                "alt_text_substitution": {"passed": False},
            },
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == [
        "row 0: behavioral test name must be a non-empty string",
        "row 0: behavioral test 'alt_text_substitution' dimension must be a string",
    ]


def test_behavioral_discrimination_rejects_malformed_present_result_alias() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": [],
            "behavioral_results": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == ["row 0: behavioral results must be an object"]


def test_behavioral_discrimination_rejects_invalid_result_value_payloads() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {
                "alt_text_substitution": {"score": 1.2, "threshold": 0.8},
            },
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {
                "alt_text_substitution": {
                    "passed": "no",
                    "score": 0.2,
                    "threshold": -0.1,
                },
            },
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == [
        "row 0: behavioral test 'alt_text_substitution' score "
        "must be between 0.0 and 1.0",
        "row 1: behavioral test 'alt_text_substitution' passed must be a boolean",
        "row 1: behavioral test 'alt_text_substitution' threshold "
        "must be between 0.0 and 1.0",
    ]


def test_behavioral_discrimination_rejects_non_finite_result_values() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {
                "alt_text_substitution": {"score": float("nan"), "threshold": 0.8},
            },
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {
                "alt_text_substitution": {"score": 0.2, "threshold": float("nan")},
            },
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == [
        "row 0: behavioral test 'alt_text_substitution' score must be finite",
        "row 1: behavioral test 'alt_text_substitution' threshold must be finite",
    ]


def test_behavioral_discrimination_rejects_non_object_results_payload() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": ["alt_text_substitution"],
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is False
    assert summary["row_errors"] == ["row 0: behavioral results must be an object"]


def test_behavioral_discrimination_rejects_invalid_min_pass_rate() -> None:
    annotations = [{"doc_id": "pdf-1", "format": "pdf"}]

    for value, expected in (
        (float("nan"), "min_pass_rate must be finite"),
        (True, "min_pass_rate must be numeric"),
        (1.5, "min_pass_rate must be between 0 and 1"),
    ):
        try:
            summarize_behavioral_discrimination(
                annotations,
                [],
                min_pass_rate=value,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid min_pass_rate should fail")


def test_behavioral_discrimination_uses_score_threshold_payloads() -> None:
    annotations = [{"doc_id": "docx-1", "format": "docx"}]
    rows = [
        {
            "doc_id": "docx-1",
            "format": "docx",
            "artifact_role": "gold_remediation",
            "behavioral": {"table_cell_lookup": {"score": 0.96, "threshold": 0.95}},
        },
        {
            "doc_id": "docx-1",
            "format": "docx",
            "artifact_role": "baseline_bad",
            "behavioral": {"table_cell_lookup": {"score": 0.2, "threshold": 0.95}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows)

    assert summary["ready"] is True
    assert summary["pass_rate_by_format"]["docx"] == 1.0


def test_behavioral_discrimination_requires_known_bad_artifact_references(tmp_path) -> None:
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "known_bad_artifact_paths": [],
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["known_bad_artifact_errors"]["pdf-1"] == ["missing known_bad_artifact_paths"]
    assert "1 annotation(s) missing known_bad artifact references" in summary["errors"]


def test_behavioral_discrimination_rejects_non_string_known_bad_artifact_paths(tmp_path) -> None:
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "known_bad_artifact_paths": [123, ""],
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": "123",
            "artifact_sha256": "0" * 64,
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["known_bad_artifact_errors"]["pdf-1"] == [
        "known_bad_artifact_paths[0] must be a string",
        "known_bad_artifact_paths[1] is empty",
    ]
    assert (
        "known_bad row artifact_path must match one known_bad_artifact_paths entry"
        in summary["result_artifact_errors"]["pdf-1"]
    )


def test_behavioral_discrimination_accepts_existing_known_bad_artifact_references(tmp_path) -> None:
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    gold.write_bytes(b"%PDF-1.4\n%%EOF")
    known_bad.write_bytes(b"%PDF-1.4\n%%EOF")
    artifact_digest = hashlib.sha256(b"%PDF-1.4\n%%EOF").hexdigest()
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "gold_remediation_path": str(gold),
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": artifact_digest,
                "known_bad_sha256": {
                    str(known_bad): artifact_digest,
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "artifact_path": str(gold),
            "artifact_sha256": artifact_digest,
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": str(known_bad),
            "artifact_sha256": artifact_digest,
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is True
    assert summary["known_bad_artifact_errors"] == {}
    assert summary["result_artifact_errors"] == {}


def test_behavioral_discrimination_rejects_known_bad_artifact_hash_mismatch(tmp_path) -> None:
    known_bad = tmp_path / "known-bad.pdf"
    known_bad.write_bytes(b"%PDF-1.4\n%%EOF")
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": "",
                "known_bad_sha256": {
                    str(known_bad): "0" * 64,
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert any(
        "known_bad_sha256 must match" in error
        for error in summary["known_bad_artifact_errors"]["pdf-1"]
    )


def test_behavioral_discrimination_requires_result_artifact_binding(tmp_path) -> None:
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    gold.write_bytes(b"gold")
    known_bad.write_bytes(b"known-bad")
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "gold_remediation_path": str(gold),
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": hashlib.sha256(b"gold").hexdigest(),
                "known_bad_sha256": {
                    str(known_bad): hashlib.sha256(b"known-bad").hexdigest(),
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": str(known_bad),
            "artifact_sha256": "0" * 64,
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["result_artifact_errors"]["pdf-1"] == [
        "gold row missing artifact_path",
        "gold row missing artifact_sha256",
        "known_bad row artifact_sha256 must match known_bad_sha256",
    ]
    assert "1 annotation(s) have behavioral result artifact binding errors" in summary["errors"]


def test_behavioral_discrimination_rejects_non_string_gold_annotation_artifact_metadata(tmp_path) -> None:
    known_bad = tmp_path / "known-bad.pdf"
    known_bad.write_bytes(b"known-bad")
    known_bad_digest = hashlib.sha256(b"known-bad").hexdigest()
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "gold_remediation_path": 123,
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": 123,
                "known_bad_sha256": {
                    str(known_bad): known_bad_digest,
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "artifact_path": "123",
            "artifact_sha256": "123",
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": str(known_bad),
            "artifact_sha256": known_bad_digest,
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["result_artifact_errors"]["pdf-1"] == [
        "annotation gold_remediation_path must be a string",
        "annotation gold_remediation_sha256 must be a string",
    ]
    assert "1 annotation(s) have behavioral result artifact binding errors" in summary["errors"]


def test_behavioral_discrimination_requires_result_model_metadata(tmp_path) -> None:
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    gold.write_bytes(b"gold")
    known_bad.write_bytes(b"known-bad")
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "gold_remediation_path": str(gold),
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": hashlib.sha256(b"gold").hexdigest(),
                "known_bad_sha256": {
                    str(known_bad): hashlib.sha256(b"known-bad").hexdigest(),
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "artifact_path": str(gold),
            "artifact_sha256": hashlib.sha256(b"gold").hexdigest(),
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": str(known_bad),
            "artifact_sha256": hashlib.sha256(b"known-bad").hexdigest(),
            "behavioral_model": "qwen2.5:7b",
            "artifact_generator_model": "qwen2.5:14b-cloud",
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["result_model_errors"]["pdf-1"] == [
        "gold row missing behavioral_model",
        "known_bad row behavioral_model family must differ from artifact "
        "generator model 'qwen2.5:14b-cloud'",
    ]
    assert (
        "1 annotation(s) have behavioral result model metadata errors"
        in summary["errors"]
    )


def test_behavioral_discrimination_rejects_non_string_artifact_and_model_metadata(tmp_path) -> None:
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    gold.write_bytes(b"gold")
    known_bad.write_bytes(b"known-bad")
    annotations = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "gold_remediation_path": str(gold),
            "known_bad_artifact_paths": [str(known_bad)],
            "artifact_hashes": {
                "source_sha256": "",
                "gold_remediation_sha256": hashlib.sha256(b"gold").hexdigest(),
                "known_bad_sha256": {
                    str(known_bad): hashlib.sha256(b"known-bad").hexdigest(),
                },
            },
        }
    ]
    rows = [
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "gold",
            "artifact_path": 123,
            "artifact_sha256": hashlib.sha256(b"gold").hexdigest(),
            "behavioral_model": "qwen2.5:7b",
            "behavioral": {"alt_text_substitution": {"passed": True}},
        },
        {
            "doc_id": "pdf-1",
            "format": "pdf",
            "variant": "known_bad",
            "artifact_path": str(known_bad),
            "artifact_sha256": hashlib.sha256(b"known-bad").hexdigest(),
            "behavioral_model": "qwen2.5:7b",
            "artifact_generator_model": 123,
            "behavioral": {"alt_text_substitution": {"passed": False}},
        },
    ]

    summary = summarize_behavioral_discrimination(annotations, rows, root=tmp_path)

    assert summary["ready"] is False
    assert summary["result_artifact_errors"]["pdf-1"] == [
        "gold row artifact_path must be a string",
    ]
    assert summary["result_model_errors"]["pdf-1"] == [
        "known_bad row artifact_generator_model must be a string",
    ]


def test_behavioral_corpus_cli_checks_annotation_root_and_jsonl_results(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    gold.write_bytes(b"%PDF-1.4\n%%EOF")
    known_bad.write_bytes(b"%PDF-1.4\n%%EOF")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-1",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        gold_remediation_path=str(gold),
        known_bad_artifact_paths=[str(known_bad)],
    )
    write_annotation_record(record, root=root)
    results = root / "behavioral_results.jsonl"
    results.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": "pdf-1",
                        "format": "pdf",
                        "variant": "gold",
                        "artifact_path": str(gold),
                        "artifact_sha256": record["artifact_hashes"]["gold_remediation_sha256"],
                        "behavioral_model": "qwen2.5:7b",
                        "behavioral": {"alt_text_substitution": {"passed": True}},
                    }
                ),
                json.dumps(
                    {
                        "doc_id": "pdf-1",
                        "format": "pdf",
                        "variant": "known_bad",
                        "artifact_path": str(known_bad),
                        "artifact_sha256": record["artifact_hashes"]["known_bad_sha256"][str(known_bad)],
                        "behavioral_model": "qwen2.5:7b",
                        "behavioral": {"alt_text_substitution": {"passed": False}},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["check", "--root", str(root), "--results", str(results), "--json"]) == 0


def test_behavioral_corpus_cli_fails_without_annotations(tmp_path) -> None:
    results = tmp_path / "behavioral_results.jsonl"
    results.write_text("", encoding="utf-8")

    assert main(["check", "--root", str(tmp_path / "empty"), "--results", str(results)]) == 1
