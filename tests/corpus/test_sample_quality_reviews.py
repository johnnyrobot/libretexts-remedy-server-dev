from __future__ import annotations

import hashlib
import json

from project_remedy.vision_planner.experiment_store import ExperimentRecord, ExperimentStore
from tools.sample_quality_reviews import (
    ReviewCandidate,
    append_queue_items,
    candidate_priority_reasons,
    candidates_from_experiments,
    load_candidates_jsonl,
    main,
    sample_review_candidates,
)


def test_sampler_prioritizes_weak_dimensions_high_variance_and_low_confidence() -> None:
    candidates = [
        ReviewCandidate(
            doc_id="low-priority",
            format="pdf",
            quality_dimensions={"alt_text": 0.95},
        ),
        ReviewCandidate(
            doc_id="high-priority",
            format="pdf",
            quality_dimensions={"alt_text": 0.45},
            dimension_variance={"alt_text": 0.08},
            behavioral_confidence={"alt_text_substitution": 0.3},
        ),
    ]

    sampled = sample_review_candidates(
        candidates,
        limit=1,
        random_fraction=0.0,
        salt="test",
    )

    assert sampled[0]["doc_id"] == "high-priority"
    assert sampled[0]["status"] == "queued"
    assert sampled[0]["weak_dimensions"] == ["alt_text"]
    assert sampled[0]["priority_reasons"] == [
        "weak_dimensions:alt_text",
        "high_variance:alt_text",
        "low_behavioral_confidence:alt_text_substitution",
    ]


def test_candidate_without_priority_signals_is_random_stratum() -> None:
    reasons = candidate_priority_reasons(
        ReviewCandidate(
            doc_id="random",
            format="docx",
            quality_dimensions={"alt_text": 0.9},
        )
    )

    assert reasons == ["random_stratum"]


def test_sampler_treats_same_doc_id_in_different_formats_as_distinct() -> None:
    sampled = sample_review_candidates(
        [
            ReviewCandidate(
                doc_id="shared-id",
                format="pdf",
                quality_dimensions={"alt_text": 0.4},
            ),
            ReviewCandidate(
                doc_id="shared-id",
                format="docx",
                quality_dimensions={"alt_text": 0.4},
            ),
        ],
        limit=2,
        random_fraction=0.5,
        salt="cross-format",
    )

    assert {(row["format"], row["doc_id"]) for row in sampled} == {
        ("pdf", "shared-id"),
        ("docx", "shared-id"),
    }


def test_sampler_tie_breaker_is_stable_for_same_doc_id_across_formats() -> None:
    candidates = [
        ReviewCandidate(
            doc_id="shared-id",
            format="pdf",
            quality_dimensions={"alt_text": 0.4},
        ),
        ReviewCandidate(
            doc_id="shared-id",
            format="docx",
            quality_dimensions={"alt_text": 0.4},
        ),
    ]

    first = sample_review_candidates(
        candidates,
        limit=1,
        random_fraction=0.0,
        salt="cross-format-stable",
    )
    reversed_first = sample_review_candidates(
        list(reversed(candidates)),
        limit=1,
        random_fraction=0.0,
        salt="cross-format-stable",
    )

    assert (first[0]["format"], first[0]["doc_id"]) == (
        reversed_first[0]["format"],
        reversed_first[0]["doc_id"],
    )


def test_sampler_rejects_malformed_sampling_arguments() -> None:
    for limit, random_fraction, expected in [
        (True, 0.2, "limit must be a positive integer"),
        (0, 0.2, "limit must be a positive integer"),
        (1, float("nan"), "random_fraction must be finite"),
        (1, -0.1, "random_fraction must be between 0 and 1"),
    ]:
        try:
            sample_review_candidates(
                [],
                limit=limit,
                random_fraction=random_fraction,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed sampling argument should fail")


def test_sampler_validates_direct_candidate_shape() -> None:
    for candidate, expected in [
        (["pdf-1"], "must be a ReviewCandidate"),
        (
            ReviewCandidate(
                doc_id="xlsx-1",
                format="xlsx",
                quality_dimensions={"reading_order": 0.4},
            ),
            "quality_dimensions contains dimension(s) not applicable to xlsx",
        ),
        (
            ReviewCandidate(
                doc_id="pdf-1",
                format="pdf",
                behavioral_confidence={"": 0.5},
            ),
            "behavioral_confidence keys must be non-empty strings",
        ),
        (
            ReviewCandidate(
                doc_id="pdf-1",
                format="pdf",
                behavioral_confidence={" alt_text_substitution ": 0.5},
            ),
            "behavioral_confidence keys must be canonical test names",
        ),
        (
            ReviewCandidate(
                doc_id="xlsx-1",
                format="xlsx",
                behavioral_confidence={"reading_order_comprehension": 0.5},
            ),
            "behavioral confidence 'reading_order_comprehension' maps to dimension "
            "'reading_order', which is not applicable to xlsx",
        ),
    ]:
        try:
            sample_review_candidates([candidate], limit=1)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed direct candidate should fail")


def test_sampler_binds_direct_candidate_source_hash(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    sampled = sample_review_candidates(
        [
            ReviewCandidate(
                doc_id="pdf-1",
                format="pdf",
                source_path=str(source),
            )
        ],
        limit=1,
    )

    assert sampled[0]["source_sha256"] == hashlib.sha256(b"%PDF-1.4\n%%EOF").hexdigest()


def test_candidates_from_experiments_uses_quality_signals() -> None:
    candidates = candidates_from_experiments(
        [
            ExperimentRecord(
                experiment_id="e1",
                harness_id="h1",
                document_hash="doc-1",
                document_type="paper",
                quality_dimensions={"alt_text": 0.4},
                behavioral_results={"alt_text_substitution": False},
            ),
            ExperimentRecord(
                experiment_id="e2",
                harness_id="h1",
                document_hash="doc-2",
                document_type="paper",
            ),
        ],
        fmt="pdf",
    )

    assert candidates == [
        ReviewCandidate(
            doc_id="doc-1",
            format="pdf",
            document_class="paper",
            quality_dimensions={"alt_text": 0.4},
            behavioral_confidence={"alt_text_substitution": 0.0},
        )
    ]


def test_candidates_from_experiments_validates_format_dimensions() -> None:
    candidates = candidates_from_experiments(
        [
            ExperimentRecord(
                experiment_id="e1",
                harness_id="h1",
                document_hash="workbook-1",
                document_format="xlsx",
                document_type="spreadsheet_workbook",
                quality_dimensions={"sheet_organization": 0.4},
            ),
        ],
        fmt="xlsx",
    )

    assert candidates == [
        ReviewCandidate(
            doc_id="workbook-1",
            format="xlsx",
            document_class="spreadsheet_workbook",
            quality_dimensions={"sheet_organization": 0.4},
        )
    ]


def test_candidates_from_experiments_rejects_inapplicable_dimensions() -> None:
    try:
        candidates_from_experiments(
            [
                ExperimentRecord(
                    experiment_id="e1",
                    harness_id="h1",
                    document_hash="workbook-1",
                    document_format="xlsx",
                    document_type="spreadsheet_workbook",
                    quality_dimensions={"reading_order": 0.4},
                ),
            ],
            fmt="xlsx",
        )
    except ValueError as exc:
        assert (
            "experiment e1: quality_dimensions contains dimension(s) "
            "not applicable to xlsx: reading_order"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable experiment dimension should fail")


def test_candidates_from_experiments_rejects_inapplicable_behavioral_results() -> None:
    try:
        candidates_from_experiments(
            [
                ExperimentRecord(
                    experiment_id="e1",
                    harness_id="h1",
                    document_hash="workbook-1",
                    document_format="xlsx",
                    behavioral_results={"reading_order_comprehension": False},
                ),
            ],
            fmt="xlsx",
        )
    except ValueError as exc:
        assert (
            "experiment e1: behavioral confidence 'reading_order_comprehension' "
            "maps to dimension 'reading_order', which is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable behavioral result should fail")


def test_review_sampler_cli_writes_jsonl_queue(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    queue_path = tmp_path / "queue.jsonl"
    source_pdf = tmp_path / "pdf-1.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    candidates_path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "doc_id": "pdf-1",
                    "format": "pdf",
                    "source_path": str(source_pdf),
                    "document_class": "paper",
                    "quality_dimensions": {"alt_text": 0.4},
                },
                {
                    "doc_id": "docx-1",
                    "format": "docx",
                    "source_path": "docx-1.docx",
                    "quality_dimensions": {"alt_text": 0.9},
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(
        [
            "sample",
            "--input",
            str(candidates_path),
            "--queue",
            str(queue_path),
            "--format",
            "pdf",
            "--limit",
            "1",
        ]
    ) == 0

    rows = [
        json.loads(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["doc_id"] == "pdf-1"
    assert rows[0]["format"] == "pdf"
    assert rows[0]["source_sha256"] == hashlib.sha256(b"%PDF-1.4\n%%EOF").hexdigest()
    assert rows[0]["status"] == "queued"


def test_append_queue_items_skips_existing_open_items(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text(
        "\n".join(
            [
                json.dumps({"doc_id": "pdf-1", "format": "pdf", "status": "queued"}),
                json.dumps(
                    {
                        "doc_id": "docx-1",
                        "format": "docx",
                        "status": "completed",
                        "completed_at": "2026-05-08T00:00:00+00:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    written = append_queue_items(
        queue_path,
        [
            {"doc_id": "pdf-1", "format": "pdf"},
            {"doc_id": "docx-1", "format": "docx"},
            {"doc_id": "pptx-1", "format": "pptx"},
            {"doc_id": "pptx-1", "format": "pptx"},
        ],
    )

    rows = [
        json.loads(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert written == 2
    assert [row["doc_id"] for row in rows] == [
        "pdf-1",
        "docx-1",
        "docx-1",
        "pptx-1",
    ]


def test_append_queue_items_rejects_inapplicable_weak_dimensions(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    try:
        append_queue_items(
            queue_path,
            [
                {
                    "doc_id": "xlsx-1",
                    "format": "xlsx",
                    "weak_dimensions": ["reading_order"],
                }
            ],
        )
    except ValueError as exc:
        assert (
            "queue item weak_dimensions contains dimension(s) "
            "not applicable to xlsx: reading_order"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable queue weak dimension should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_non_object_new_items(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    try:
        append_queue_items(queue_path, [["pdf-1"]])
    except ValueError as exc:
        assert "queue item must be an object" in str(exc)
    else:
        raise AssertionError("non-object queue item should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_unqueued_new_status(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    try:
        append_queue_items(
            queue_path,
            [{"doc_id": "pdf-1", "format": "pdf", "status": "claimed"}],
        )
    except ValueError as exc:
        assert "queue item status must be queued" in str(exc)
    else:
        raise AssertionError("non-queued new item status should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_malformed_new_source_sha(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    for bad_value in ("bad", False, None):
        try:
            append_queue_items(
                queue_path,
                [{"doc_id": "pdf-1", "format": "pdf", "source_sha256": bad_value}],
            )
        except ValueError as exc:
            assert "queue item source_sha256 must be a sha256 hex digest" in str(exc)
        else:
            raise AssertionError("malformed queue source hash should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_non_string_weak_dimensions(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    for bad_value, expected in [
        ([123], "weak_dimensions must contain non-empty strings"),
        (False, "weak_dimensions must be a list"),
        (None, "weak_dimensions must be a list"),
    ]:
        try:
            append_queue_items(
                queue_path,
                [{"doc_id": "pdf-1", "format": "pdf", "weak_dimensions": bad_value}],
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("non-string weak dimension should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_duplicate_weak_dimensions(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    try:
        append_queue_items(
            queue_path,
            [
                {
                    "doc_id": "pdf-1",
                    "format": "pdf",
                    "weak_dimensions": ["alt_text", "alt_text"],
                }
            ],
        )
    except ValueError as exc:
        assert "weak_dimensions must not contain duplicates" in str(exc)
    else:
        raise AssertionError("duplicate weak dimensions should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_malformed_sampling_metadata(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"

    for bad_field, bad_value, expected in [
        ("priority_score", True, "priority_score must be numeric"),
        ("priority_score", float("nan"), "priority_score must be finite"),
        ("priority_score", -0.1, "priority_score must be non-negative"),
        ("priority_reasons", "weak", "priority_reasons must be a list"),
        ("sampled_at", "2026-05-08T00:00:00", "sampled_at must include a timezone"),
    ]:
        item = {"doc_id": "pdf-1", "format": "pdf", bad_field: bad_value}
        try:
            append_queue_items(queue_path, [item])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"malformed {bad_field} should fail")

    assert not queue_path.exists()


def test_append_queue_items_rejects_malformed_existing_queue(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text("{not-json\n", encoding="utf-8")

    try:
        append_queue_items(queue_path, [{"doc_id": "pdf-1", "format": "pdf"}])
    except ValueError as exc:
        assert "invalid JSON at line 1" in str(exc)
    else:
        raise AssertionError("malformed existing queue row should fail")


def test_append_queue_items_rejects_non_object_existing_queue_rows(tmp_path) -> None:
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text('["pdf-1"]\n', encoding="utf-8")

    try:
        append_queue_items(queue_path, [{"doc_id": "pdf-1", "format": "pdf"}])
    except ValueError as exc:
        assert "row 1 must be an object" in str(exc)
    else:
        raise AssertionError("non-object existing queue row should fail")


def test_append_queue_items_rejects_malformed_existing_queue_state(tmp_path) -> None:
    for row, expected in [
        (
            {"doc_id": "pdf-1", "format": "pdf", "source_sha256": False},
            "source_sha256 must be a sha256 hex digest",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "weak_dimensions": False},
            "weak_dimensions must be a list",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "status": "claimed"},
            "claimed_by is required for claimed status",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "claimed",
                "claimed_by": "specialist-a",
            },
            "claimed_at is required for claimed status",
        ),
        (
            {"doc_id": "pdf-1", "format": "pdf", "status": "completed"},
            "completed_at is required for completed status",
        ),
        (
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "status": "completed",
                "completed_by": " ",
                "completed_at": "2026-05-08T00:00:00+00:00",
            },
            "completed_by must be a non-empty string",
        ),
    ]:
        queue_path = tmp_path / "queue.jsonl"
        queue_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

        try:
            append_queue_items(queue_path, [{"doc_id": "docx-1", "format": "docx"}])
        except ValueError as exc:
            assert expected in str(exc)
            assert "row 1 invalid" in str(exc)
        else:
            raise AssertionError("malformed existing queue state should fail")


def test_review_sampler_cli_samples_experiment_store_records(tmp_path) -> None:
    store_path = tmp_path / "experiments.db"
    queue_path = tmp_path / "queue.jsonl"
    store = ExperimentStore(store_path)
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e1",
            harness_id="h1",
            document_hash="doc-1",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.4},
            behavioral_results={"alt_text_substitution": False},
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e2",
            harness_id="h1",
            document_hash="doc-2",
            document_type="marketing",
            quality_dimensions={"alt_text": 0.95},
            behavioral_results={"alt_text_substitution": True},
        )
    )

    assert main(
        [
            "sample-experiments",
            "--store",
            str(store_path),
            "--harness-id",
            "h1",
            "--queue",
            str(queue_path),
            "--limit",
            "1",
            "--random-fraction",
            "0",
        ]
    ) == 0

    rows = [
        json.loads(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["doc_id"] == "doc-1"
    assert rows[0]["document_class"] == "scientific_paper"
    assert rows[0]["weak_dimensions"] == ["alt_text"]


def test_review_sampler_cli_uses_stored_experiment_format_by_default(tmp_path) -> None:
    store_path = tmp_path / "experiments.db"
    queue_path = tmp_path / "queue.jsonl"
    store = ExperimentStore(store_path)
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="workbook-1",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            quality_dimensions={"sheet_organization": 0.4},
            behavioral_results={"sheet_navigation": False},
        )
    )

    assert main(
        [
            "sample-experiments",
            "--store",
            str(store_path),
            "--harness-id",
            "h1",
            "--queue",
            str(queue_path),
            "--limit",
            "1",
            "--random-fraction",
            "0",
        ]
    ) == 0

    rows = [
        json.loads(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [
        {
            "doc_id": "workbook-1",
            "document_class": "spreadsheet_workbook",
            "format": "xlsx",
            "priority_reasons": [
                "weak_dimensions:sheet_organization",
                "low_behavioral_confidence:sheet_navigation",
            ],
            "priority_score": 3.0,
            "sampled_at": rows[0]["sampled_at"],
            "source_path": "",
            "source_sha256": "",
            "status": "queued",
            "weak_dimensions": ["sheet_organization"],
        }
    ]


def test_review_sampler_cli_filters_experiment_records_by_explicit_format(tmp_path) -> None:
    store_path = tmp_path / "experiments.db"
    queue_path = tmp_path / "queue.jsonl"
    store = ExperimentStore(store_path)
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="pdf-1",
            harness_id="h1",
            document_hash="pdf-1",
            document_format="pdf",
            quality_dimensions={"alt_text": 0.4},
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="workbook-1",
            document_format="xlsx",
            quality_dimensions={"sheet_organization": 0.4},
        )
    )

    assert main(
        [
            "sample-experiments",
            "--store",
            str(store_path),
            "--harness-id",
            "h1",
            "--queue",
            str(queue_path),
            "--format",
            "xlsx",
            "--limit",
            "1",
            "--random-fraction",
            "0",
        ]
    ) == 0

    rows = [
        json.loads(line)
        for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "workbook-1"
    assert rows[0]["format"] == "xlsx"


def test_load_candidates_jsonl_validates_shape(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps({"doc_id": "xlsx-1", "format": "xlsx"}) + "\n",
        encoding="utf-8",
    )

    candidates = load_candidates_jsonl(candidates_path)

    assert candidates == [ReviewCandidate(doc_id="xlsx-1", format="xlsx")]


def test_load_candidates_jsonl_rejects_non_object_rows(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(json.dumps(["pdf-1"]) + "\n", encoding="utf-8")

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "row must be an object" in str(exc)
    else:
        raise AssertionError("non-object candidate row should fail")


def test_load_candidates_jsonl_rejects_non_string_identity_fields(tmp_path) -> None:
    for field_name, bad_value, expected in [
        ("doc_id", 123, "doc_id is required"),
        ("source_path", None, "source_path must be a string"),
        ("source_sha256", None, "source_sha256 must be a string"),
        ("document_class", False, "document_class must be a string"),
    ]:
        candidates_path = tmp_path / f"{field_name}.jsonl"
        row = {"doc_id": "pdf-1", "format": "pdf", field_name: bad_value}
        candidates_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

        try:
            load_candidates_jsonl(candidates_path)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"non-string {field_name} should fail")


def test_load_candidates_jsonl_accepts_format_specific_dimensions(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "quality_dimensions": {"sheet_organization": 0.7},
                "dimension_variance": {"sheet_organization": 0.05},
                "behavioral_confidence": {"sheet_navigation": 0.25},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    candidates = load_candidates_jsonl(candidates_path)

    assert candidates == [
        ReviewCandidate(
            doc_id="xlsx-1",
            format="xlsx",
            quality_dimensions={"sheet_organization": 0.7},
            dimension_variance={"sheet_organization": 0.05},
            behavioral_confidence={"sheet_navigation": 0.25},
        )
    ]


def test_load_candidates_jsonl_rejects_inapplicable_quality_dimension(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "quality_dimensions": {"reading_order": 0.7},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert (
            "quality_dimensions contains dimension(s) not applicable to xlsx: "
            "reading_order"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable quality dimension should fail")


def test_load_candidates_jsonl_rejects_inapplicable_variance_dimension(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "dimension_variance": {"reading_order": 0.05},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert (
            "dimension_variance contains dimension(s) not applicable to xlsx: "
            "reading_order"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable variance dimension should fail")


def test_load_candidates_jsonl_rejects_inapplicable_behavioral_confidence(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "behavioral_confidence": {"reading_order_comprehension": 0.7},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert (
            "behavioral confidence 'reading_order_comprehension' maps to dimension "
            "'reading_order', which is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("inapplicable behavioral confidence should fail")


def test_load_candidates_jsonl_rejects_unknown_behavioral_confidence(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "behavioral_confidence": {"keyboard_probe": 0.7},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "unsupported behavioral confidence test: keyboard_probe" in str(exc)
    else:
        raise AssertionError("unknown behavioral confidence should fail")


def test_load_candidates_jsonl_rejects_non_object_quality_dimensions(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-1",
                "format": "xlsx",
                "quality_dimensions": ["sheet_organization"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "quality_dimensions must be an object" in str(exc)
    else:
        raise AssertionError("non-object quality dimensions should fail")


def test_load_candidates_jsonl_rejects_empty_non_object_score_maps(tmp_path) -> None:
    for field_name, expected in [
        ("quality_dimensions", "quality_dimensions must be an object"),
        ("dimension_variance", "dimension_variance must be an object"),
        ("behavioral_confidence", "behavioral_confidence must be an object"),
    ]:
        candidates_path = tmp_path / f"{field_name}.jsonl"
        candidates_path.write_text(
            json.dumps({"doc_id": "pdf-1", "format": "pdf", field_name: []}) + "\n",
            encoding="utf-8",
        )

        try:
            load_candidates_jsonl(candidates_path)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"empty non-object {field_name} should fail")


def test_load_candidates_jsonl_rejects_out_of_range_quality_scores(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "quality_dimensions": {"alt_text": 1.2},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "quality_dimensions.alt_text must be between 0.0 and 1.0" in str(exc)
    else:
        raise AssertionError("out-of-range quality score should fail")


def test_load_candidates_jsonl_rejects_boolean_quality_scores(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "quality_dimensions": {"alt_text": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "quality_dimensions.alt_text must be numeric" in str(exc)
    else:
        raise AssertionError("boolean quality score should fail")


def test_load_candidates_jsonl_rejects_non_finite_quality_scores(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "quality_dimensions": {"alt_text": float("nan")},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "quality_dimensions.alt_text must be finite" in str(exc)
    else:
        raise AssertionError("non-finite quality score should fail")


def test_load_candidates_jsonl_rejects_out_of_range_variance_scores(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "dimension_variance": {"alt_text": -0.01},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "dimension_variance.alt_text must be between 0.0 and 1.0" in str(exc)
    else:
        raise AssertionError("out-of-range variance score should fail")


def test_load_candidates_jsonl_rejects_boolean_behavioral_confidence(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "behavioral_confidence": {"alt_text_substitution": False},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "behavioral_confidence.alt_text_substitution must be numeric" in str(exc)
    else:
        raise AssertionError("boolean behavioral confidence should fail")


def test_load_candidates_jsonl_rejects_non_finite_behavioral_confidence(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "behavioral_confidence": {"alt_text_substitution": float("nan")},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "behavioral_confidence.alt_text_substitution must be finite" in str(exc)
    else:
        raise AssertionError("non-finite behavioral confidence should fail")


def test_load_candidates_jsonl_rejects_invalid_behavioral_confidence(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "behavioral_confidence": {"alt_text_substitution": 1.5},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert (
            "behavioral_confidence.alt_text_substitution must be between 0.0 and 1.0"
            in str(exc)
        )
    else:
        raise AssertionError("out-of-range behavioral confidence should fail")


def test_load_candidates_jsonl_binds_source_hashes(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    digest = hashlib.sha256(b"%PDF-1.4\n%%EOF").hexdigest()
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "source_path": str(source),
                "source_sha256": digest,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    candidates = load_candidates_jsonl(candidates_path)

    assert candidates[0].source_sha256 == digest


def test_load_candidates_jsonl_rejects_source_hash_mismatch(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "doc_id": "pdf-1",
                "format": "pdf",
                "source_path": str(source),
                "source_sha256": "0" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_candidates_jsonl(candidates_path)
    except ValueError as exc:
        assert "source_sha256 must match source_path bytes" in str(exc)
    else:
        raise AssertionError("mismatched source hash should fail")
