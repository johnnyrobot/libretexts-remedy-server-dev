from __future__ import annotations

import hashlib
import json

import pytest

from tools.annotate_corpus import (
    DIMENSIONS_BY_FORMAT,
    build_annotation_record,
    evaluate_phase_a_coverage,
    load_manifest_rows,
    load_schema,
    main,
    parse_dimension_scores,
    parse_format_specific_items,
    parse_pairwise_comparisons,
    prompt_dimension_judgments,
    sha256_file,
    summarize_corpus,
    validate_annotation_record,
    write_annotation_record,
)


def test_schema_is_format_aware_and_lists_all_supported_formats() -> None:
    schema = load_schema()

    assert schema["properties"]["format"]["enum"] == ["pdf", "docx", "pptx", "xlsx"]
    assert "format_specific" in schema["properties"]
    assert schema["properties"]["provenance"]["$ref"] == "#/$defs/provenance"
    assert "known_bad_artifact_paths" in schema["required"]
    assert schema["properties"]["known_bad_artifact_paths"]["uniqueItems"] is True
    assert "artifact_hashes" in schema["required"]
    assert schema["properties"]["artifact_hashes"]["$ref"] == "#/$defs/artifact_hashes"
    assert schema["$defs"]["provenance"]["properties"]["gold_standard_source"]["const"] == "human_specialist"
    assert schema["$defs"]["provenance"]["properties"]["human_verified"]["const"] is True
    assert sorted(schema["properties"]["format_specific"]["properties"]) == [
        "docx",
        "pdf",
        "pptx",
        "xlsx",
    ]
    assert (
        schema["$defs"]["pptx_specific"]["properties"]["per_slide"]["items"]["$ref"]
        == "#/$defs/pptx_slide_annotation"
    )
    assert (
        schema["$defs"]["xlsx_specific"]["properties"]["per_sheet"]["items"]["$ref"]
        == "#/$defs/xlsx_sheet_annotation"
    )


def test_annotation_validator_enforces_format_dimension_matrix(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "workbook.xlsx",
        fmt="xlsx",
        doc_id="xlsx-001",
        document_class="spreadsheet_workbook",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["xlsx"]},
    )

    assert validate_annotation_record(record) == []

    record["applicable_dimensions"] = [*record["applicable_dimensions"], "reading_order"]
    record["dimensions"]["reading_order"] = {"score": 0.1}
    errors = validate_annotation_record(record)

    assert any("reading_order" in str(error) and "xlsx" in str(error) for error in errors)


def test_annotation_validator_rejects_non_finite_scores(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-nan-score",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    record["dimensions"]["alt_text"]["score"] = float("nan")

    errors = [str(error) for error in validate_annotation_record(record)]

    assert "dimensions.alt_text.score: must be finite" in errors


def test_parse_dimension_scores_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="Score for 'alt_text' must be finite"):
        parse_dimension_scores(["alt_text=nan"])


def test_annotation_record_requires_human_gold_provenance(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-provenance",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        candidate_seed_model="draft-model-v1",
        candidate_seed_notes="Model output was corrected by the specialist.",
    )

    assert record["provenance"] == {
        "gold_standard_source": "human_specialist",
        "human_verified": True,
        "candidate_seed_model": "draft-model-v1",
        "candidate_seed_notes": "Model output was corrected by the specialist.",
    }
    assert validate_annotation_record(record) == []

    record["provenance"] = {
        "gold_standard_source": "model_output",
        "human_verified": False,
        "candidate_seed_model": 123,
        "candidate_seed_notes": None,
    }
    errors = [str(error) for error in validate_annotation_record(record)]

    assert "provenance.gold_standard_source: must be human_specialist" in errors
    assert "provenance.human_verified: must be true" in errors
    assert "provenance.candidate_seed_model: must be a string" in errors
    assert "provenance.candidate_seed_notes: must be a string" in errors


def test_annotation_record_tracks_known_bad_artifact_references(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-known-bad",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        known_bad_artifact_paths=["known-bad-a.pdf"],
    )

    assert record["known_bad_artifact_paths"] == ["known-bad-a.pdf"]
    assert validate_annotation_record(record) == []

    record["known_bad_artifact_paths"] = [
        "known-bad-a.pdf",
        "known-bad-a.pdf",
        "",
    ]
    errors = [str(error) for error in validate_annotation_record(record)]

    assert "known_bad_artifact_paths: duplicate path: known-bad-a.pdf" in errors
    assert "known_bad_artifact_paths[2]: must be a non-empty string" in errors


def test_annotation_record_tracks_artifact_hashes(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    source.write_bytes(b"source-bytes")
    gold.write_bytes(b"gold-bytes")
    known_bad.write_bytes(b"known-bad-bytes")

    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-artifact-hashes",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        gold_remediation_path=str(gold),
        known_bad_artifact_paths=[str(known_bad)],
    )

    assert record["artifact_hashes"] == {
        "source_sha256": hashlib.sha256(b"source-bytes").hexdigest(),
        "gold_remediation_sha256": hashlib.sha256(b"gold-bytes").hexdigest(),
        "known_bad_sha256": {
            str(known_bad): hashlib.sha256(b"known-bad-bytes").hexdigest(),
        },
    }
    assert validate_annotation_record(record) == []

    record["artifact_hashes"]["source_sha256"] = "not-a-hash"
    errors = [str(error) for error in validate_annotation_record(record)]

    assert "artifact_hashes.source_sha256: must be empty or a sha256 hex digest" in errors


def test_annotation_validator_rejects_schema_unknown_fields(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-strict-schema",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    record["model_generated_gold"] = True
    record["provenance"]["unreviewed_source"] = "model"

    errors = [str(error) for error in validate_annotation_record(record)]

    assert "model_generated_gold: unknown field" in errors
    assert "provenance.unreviewed_source: unknown field" in errors


def test_annotation_validator_rejects_format_specific_and_metadata_shape_errors(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-strict-format",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        edge_case_flags=["multi_column"],
    )
    record["format_specific"]["pptx"] = {"per_slide": []}
    record["edge_case_flags"] = ["multi_column", "multi_column", ""]
    record["annotated_at"] = "2026-05-08T00:00:00"

    errors = [str(error) for error in validate_annotation_record(record)]

    assert "format_specific.pptx: not allowed for pdf annotation" in errors
    assert "edge_case_flags: duplicate flag: multi_column" in errors
    assert "edge_case_flags[2]: must be a non-empty string" in errors
    assert "annotated_at: must include a timezone" in errors


def test_annotation_cli_init_annotate_and_validate(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")

    assert main(["init", "--root", str(root)]) == 0

    score_args: list[str] = []
    for dimension in DIMENSIONS_BY_FORMAT["pdf"]:
        score_args.extend(["--score", f"{dimension}=0.8"])

    result = main(
        [
            "annotate",
            str(source),
            "--root",
            str(root),
            "--doc-id",
            "pdf-001",
            "--document-class",
            "paper",
            "--annotator",
            "specialist_a",
            "--candidate-seed-model",
            "draft-model-v1",
            "--candidate-seed-note",
            "human corrected candidate",
            "--edge-case",
            "multi_column",
            "--page-count",
            "3",
            *score_args,
        ]
    )

    assert result == 0
    annotation_path = root / "annotations" / "pdf" / "pdf-001.json"
    assert annotation_path.exists()

    record = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert record["format"] == "pdf"
    assert record["format_specific"]["pdf"]["page_count"] == 3
    assert record["edge_case_flags"] == ["multi_column"]
    assert record["provenance"]["gold_standard_source"] == "human_specialist"
    assert record["provenance"]["human_verified"] is True
    assert record["provenance"]["candidate_seed_model"] == "draft-model-v1"
    assert record["provenance"]["candidate_seed_notes"] == "human corrected candidate"

    manifest_lines = [
        line
        for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(manifest_lines) == 1
    assert json.loads(manifest_lines[0])["doc_id"] == "pdf-001"

    assert main(["validate", "--root", str(root)]) == 0


def test_annotation_cli_interactive_walkthrough_prompts_for_missing_scores(monkeypatch, tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"PK\x03\x04fake")
    answers = iter(
        [
            "0.9",
            "charts are useful",
            "0.8",
            "",
            "0.7",
            "",
            "0.95",
            "",
            "0.85",
            "",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = main(
        [
            "annotate",
            str(source),
            "--root",
            str(root),
            "--doc-id",
            "xlsx-001",
            "--document-class",
            "spreadsheet_workbook",
            "--annotator",
            "specialist_a",
            "--interactive",
        ]
    )

    assert result == 0
    annotation_path = root / "annotations" / "xlsx" / "xlsx-001.json"
    record = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert record["dimensions"]["alt_text"]["score"] == 0.9
    assert record["dimensions"]["alt_text"]["notes"] == "charts are useful"
    assert record["applicable_dimensions"] == list(DIMENSIONS_BY_FORMAT["xlsx"])


def test_prompt_dimension_judgments_reprompts_invalid_scores() -> None:
    answers = iter(["bad", "nan", "1.2", "0.75", "usable after correction"])

    scores, notes = prompt_dimension_judgments(
        dimensions=["alt_text"],
        input_fn=lambda prompt="": next(answers),
    )

    assert scores == {"alt_text": 0.75}
    assert notes == {"alt_text": "usable after correction"}


def test_pairwise_comparisons_can_be_added_to_annotations(tmp_path) -> None:
    comparisons = parse_pairwise_comparisons(
        [
            json.dumps(
                {
                    "a_path": "a.pdf",
                    "b_path": "b.pdf",
                    "winner": "a",
                    "dimension": "alt_text",
                    "rationale": "A is more specific.",
                }
            )
        ]
    )
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-pairwise",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        pairwise_comparisons=comparisons,
    )

    assert validate_annotation_record(record) == []
    assert record["pairwise_comparisons"][0]["winner"] == "a"
    assert record["pairwise_comparisons"][0]["a_sha256"] == ""
    assert record["pairwise_comparisons"][0]["b_sha256"] == ""


def test_annotation_validation_rejects_incomplete_pairwise_comparisons(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-pairwise-invalid",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    record["pairwise_comparisons"] = [
        {
            "a_path": "",
            "winner": "candidate-a",
            "dimension": "reading_order",
            "rationale": 123,
            "extra": True,
        }
    ]

    errors = [str(error) for error in validate_annotation_record(record)]

    assert "pairwise_comparisons[0].b_path: missing required field" in errors
    assert "pairwise_comparisons[0].a_sha256: missing required field" in errors
    assert "pairwise_comparisons[0].b_sha256: missing required field" in errors
    assert "pairwise_comparisons[0].a_path: must be non-empty" in errors
    assert "pairwise_comparisons[0].extra: unknown field" in errors
    assert "pairwise_comparisons[0].rationale: must be a string" in errors
    assert "pairwise_comparisons[0].winner: must be a, b, or tied" in errors


def test_pairwise_comparisons_track_candidate_hashes(tmp_path) -> None:
    candidate_a = tmp_path / "candidate-a.pdf"
    candidate_b = tmp_path / "candidate-b.pdf"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b.write_bytes(b"candidate-b")
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-pairwise-hashes",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        pairwise_comparisons=[
            {
                "a_path": str(candidate_a),
                "b_path": str(candidate_b),
                "winner": "a",
                "dimension": "alt_text",
                "rationale": "Candidate A is more specific.",
            }
        ],
    )

    comparison = record["pairwise_comparisons"][0]
    assert comparison["a_sha256"] == hashlib.sha256(b"candidate-a").hexdigest()
    assert comparison["b_sha256"] == hashlib.sha256(b"candidate-b").hexdigest()


def test_pptx_annotation_cli_accepts_per_slide_json(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"PK\x03\x04fake")
    per_slide = {
        "slide_index": 1,
        "title": "Quarterly Results",
        "applicable_dimensions": ["alt_text", "reading_order", "table_structure"],
        "dimensions": {
            "alt_text": {"score": 0.9, "notes": "Chart descriptions are specific."},
            "reading_order": {"score": 0.8},
            "table_structure": {"score": 0.95},
        },
    }
    score_args: list[str] = []
    for dimension in DIMENSIONS_BY_FORMAT["pptx"]:
        score_args.extend(["--score", f"{dimension}=0.8"])

    result = main(
        [
            "annotate",
            str(source),
            "--root",
            str(root),
            "--doc-id",
            "pptx-001",
            "--document-class",
            "slide_deck",
            "--annotator",
            "specialist_a",
            "--slide-count",
            "1",
            "--per-slide-json",
            json.dumps(per_slide),
            *score_args,
        ]
    )

    assert result == 0
    record = json.loads(
        (root / "annotations" / "pptx" / "pptx-001.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["format_specific"]["pptx"]["slide_count"] == 1
    assert record["format_specific"]["pptx"]["per_slide"] == [per_slide]
    assert validate_annotation_record(record) == []


def test_pptx_per_slide_annotations_require_title_and_positive_index(tmp_path) -> None:
    record = build_annotation_record(
        source_path=tmp_path / "deck.pptx",
        fmt="pptx",
        doc_id="pptx-bad-slide",
        document_class="slide_deck",
        annotator="specialist_a",
        scores={dimension: 0.8 for dimension in DIMENSIONS_BY_FORMAT["pptx"]},
    )
    record["format_specific"]["pptx"]["per_slide"] = [
        {
            "slide_index": 0,
            "applicable_dimensions": ["reading_order"],
            "dimensions": {"reading_order": {"score": 0.6}},
        }
    ]

    errors = [str(error) for error in validate_annotation_record(record)]

    assert "format_specific.pptx.per_slide[0].title: missing required field" in errors
    assert "format_specific.pptx.per_slide[0].slide_index: must be a positive integer" in errors


def test_xlsx_per_sheet_annotations_validate_applicable_dimensions(tmp_path) -> None:
    per_sheet = parse_format_specific_items(
        [
            json.dumps(
                {
                    "sheet_index": 1,
                    "sheet_name": "Q3 Revenue",
                    "purpose": "Quarterly revenue summary",
                    "applicable_dimensions": ["sheet_organization", "table_structure"],
                    "dimensions": {
                        "sheet_organization": {"score": 0.9},
                        "table_structure": {"score": 0.85},
                    },
                }
            )
        ],
        item_name="per-sheet",
    )
    record = build_annotation_record(
        source_path=tmp_path / "workbook.xlsx",
        fmt="xlsx",
        doc_id="xlsx-sheet",
        document_class="spreadsheet_workbook",
        annotator="specialist_a",
        scores={dimension: 0.8 for dimension in DIMENSIONS_BY_FORMAT["xlsx"]},
        sheet_count=1,
        per_sheet=per_sheet,
    )

    assert validate_annotation_record(record) == []

    record["format_specific"]["xlsx"]["per_sheet"][0]["applicable_dimensions"].append(
        "reading_order"
    )
    record["format_specific"]["xlsx"]["per_sheet"][0]["dimensions"]["reading_order"] = {
        "score": 0.2
    }
    errors = validate_annotation_record(record)

    assert any("reading_order" in str(error) and "xlsx" in str(error) for error in errors)


def test_annotation_cli_validate_allow_empty_is_ci_friendly(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"

    assert main(["init", "--root", str(root)]) == 0
    assert main(["validate", "--root", str(root)]) == 1
    assert main(["validate", "--root", str(root), "--allow-empty"]) == 0


def test_write_annotation_record_rejects_invalid_records(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-invalid-write",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    del record["artifact_hashes"]

    with pytest.raises(ValueError, match="artifact_hashes"):
        write_annotation_record(record, root=root)

    assert not root.exists()


def test_corpus_coverage_gate_reports_phase_a_readiness(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source_pdf = tmp_path / "source.pdf"
    source_docx = tmp_path / "source.docx"
    gold_pdf = tmp_path / "gold.pdf"
    gold_docx = tmp_path / "gold.docx"
    known_bad_pdf = tmp_path / "known-bad.pdf"
    known_bad_docx = tmp_path / "known-bad.docx"
    for artifact in (source_pdf, source_docx, gold_pdf, gold_docx, known_bad_pdf, known_bad_docx):
        artifact.write_bytes(b"artifact")
    pdf_record = build_annotation_record(
        source_path=source_pdf,
        fmt="pdf",
        doc_id="pdf-001",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold_pdf),
        known_bad_artifact_paths=[str(known_bad_pdf)],
    )
    docx_record = build_annotation_record(
        source_path=source_docx,
        fmt="docx",
        doc_id="docx-001",
        document_class="technical_doc",
        annotator="specialist_a",
        scores={dimension: 0.8 for dimension in DIMENSIONS_BY_FORMAT["docx"]},
        gold_remediation_path=str(gold_docx),
        known_bad_artifact_paths=[str(known_bad_docx)],
    )
    write_annotation_record(pdf_record, root=root)
    write_annotation_record(docx_record, root=root)

    summary = summarize_corpus(root)

    assert summary["total_annotations"] == 2
    assert summary["counts_by_format"]["pdf"] == 1
    assert summary["office_annotations"] == 1
    assert evaluate_phase_a_coverage(summary, min_total=2, min_pdf=1, min_office=1) == []

    errors = evaluate_phase_a_coverage(summary)
    assert "total annotations 2 < required 50" in errors
    assert "PDF annotations 1 < required 30" in errors
    assert "Office annotations 1 < required 20" in errors


def test_corpus_coverage_gate_rejects_invalid_minimums(tmp_path) -> None:
    summary = {
        "counts_by_format": {"pdf": 0, "docx": 0, "pptx": 0, "xlsx": 0},
        "total_annotations": 0,
        "office_annotations": 0,
        "document_classes": {},
        "validation_errors": {},
        "artifact_errors": {},
        "dimension_errors": {},
        "manifest_errors": [],
        "missing_manifest_entries": [],
        "stale_manifest_entries": [],
        "duplicate_manifest_entries": [],
        "manifest_mismatch_entries": {},
    }

    with pytest.raises(ValueError, match="min_total must be a non-negative integer"):
        evaluate_phase_a_coverage(summary, min_total=-1)
    with pytest.raises(ValueError, match="min_pdf must be a non-negative integer"):
        evaluate_phase_a_coverage(summary, min_pdf=True)
    assert main(
        [
            "coverage",
            "--root",
            str(tmp_path / "empty"),
            "--min-office",
            "-1",
            "--json",
        ]
    ) == 2


def test_corpus_coverage_gate_requires_source_and_gold_artifacts(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    record = build_annotation_record(
        source_path=tmp_path / "missing-source.pdf",
        fmt="pdf",
        doc_id="pdf-missing-artifacts",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
    )
    write_annotation_record(record, root=root)

    summary = summarize_corpus(root)
    errors = evaluate_phase_a_coverage(
        summary,
        min_total=1,
        min_pdf=1,
        min_office=0,
    )

    artifact_errors = next(iter(summary["artifact_errors"].values()))
    assert "missing source_path artifact" in artifact_errors[0]
    assert "missing gold_remediation_path" in artifact_errors[1]
    assert "missing known_bad_artifact_paths" in artifact_errors[2]
    assert "1 annotation file(s) have invalid source/gold/known-bad artifact references or hashes" in errors


def test_corpus_coverage_gate_rejects_artifact_hash_mismatches(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    source.write_bytes(b"source")
    gold.write_bytes(b"gold")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-artifact-hash-mismatch",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold),
    )
    write_annotation_record(record, root=root)
    gold.write_bytes(b"changed-gold")

    summary = summarize_corpus(root)
    errors = evaluate_phase_a_coverage(
        summary,
        min_total=1,
        min_pdf=1,
        min_office=0,
    )

    artifact_errors = next(iter(summary["artifact_errors"].values()))
    assert any("gold_remediation_sha256 must match" in error for error in artifact_errors)
    assert "1 annotation file(s) have invalid source/gold/known-bad artifact references or hashes" in errors


def test_corpus_coverage_gate_requires_known_bad_artifact_hashes(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    source.write_bytes(b"source")
    gold.write_bytes(b"gold")
    known_bad.write_bytes(b"known-bad")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-known-bad-hash-mismatch",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold),
        known_bad_artifact_paths=[str(known_bad)],
    )
    write_annotation_record(record, root=root)
    known_bad.write_bytes(b"changed-known-bad")

    summary = summarize_corpus(root)

    artifact_errors = next(iter(summary["artifact_errors"].values()))
    assert any("known_bad_sha256 must match" in error for error in artifact_errors)


def test_corpus_coverage_gate_rejects_manifest_metadata_drift(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    source.write_bytes(b"source")
    gold.write_bytes(b"gold")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-manifest-drift",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold),
    )
    annotation_path = write_annotation_record(record, root=root)
    manifest_path = root / "manifest.jsonl"
    row = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert row["artifact_hashes"] == record["artifact_hashes"]
    assert len(row["annotation_sha256"]) == 64
    row["artifact_hashes"]["source_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    summary = summarize_corpus(root)
    errors = evaluate_phase_a_coverage(
        summary,
        min_total=1,
        min_pdf=1,
        min_office=0,
    )

    assert summary["manifest_mismatch_entries"] == {
        str(annotation_path): ["artifact_hashes does not match annotation"]
    }
    assert "1 manifest entrie(s) drifted from annotation files" in errors


def test_write_annotation_record_overwrite_replaces_manifest_row(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    known_bad = tmp_path / "known-bad.pdf"
    source.write_bytes(b"source")
    gold.write_bytes(b"gold")
    known_bad.write_bytes(b"known-bad")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-overwrite",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.8 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold),
        known_bad_artifact_paths=[str(known_bad)],
    )
    annotation_path = write_annotation_record(record, root=root)
    updated = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-overwrite",
        document_class="paper",
        annotator="specialist_a",
        scores={dimension: 0.9 for dimension in DIMENSIONS_BY_FORMAT["pdf"]},
        gold_remediation_path=str(gold),
        known_bad_artifact_paths=[str(known_bad)],
    )

    assert write_annotation_record(updated, root=root, overwrite=True) == annotation_path

    manifest_rows, manifest_errors = load_manifest_rows(root)
    summary = summarize_corpus(root)
    assert manifest_errors == []
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["annotation_path"] == str(annotation_path)
    assert manifest_rows[0]["annotation_sha256"] == sha256_file(annotation_path)
    assert summary["duplicate_manifest_entries"] == []
    assert summary["manifest_mismatch_entries"] == {}


def test_phase_a_coverage_gate_requires_all_applicable_format_dimensions(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    source = tmp_path / "source.pdf"
    gold = tmp_path / "gold.pdf"
    source.write_bytes(b"source")
    gold.write_bytes(b"gold")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-partial-dimensions",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        gold_remediation_path=str(gold),
    )
    write_annotation_record(record, root=root)

    summary = summarize_corpus(root)
    errors = evaluate_phase_a_coverage(
        summary,
        min_total=1,
        min_pdf=1,
        min_office=0,
    )

    dimension_errors = next(iter(summary["dimension_errors"].values()))
    assert "missing applicable dimension(s):" in dimension_errors[0]
    assert "reading_order" in dimension_errors[0]
    assert "missing dimension annotation(s):" in dimension_errors[1]
    assert "1 annotation file(s) have incomplete dimension coverage" in errors
