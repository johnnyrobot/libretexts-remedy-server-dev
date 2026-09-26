from __future__ import annotations

import sqlite3
from pathlib import Path

from project_remedy.vision_planner.experiment_store import (
    ExperimentRecord,
    ExperimentStore,
)
from project_remedy.vision_planner.scorer import (
    HarnessScorer,
    ScoringResultV2,
    compute_document_class_breakdown,
    compute_dimension_metrics_by_format,
    compute_dimension_metrics_from_experiments,
)


def _record(
    experiment_id: str,
    *,
    passed: bool,
    alt_text: float,
    reading_order: float = 0.9,
    behavioral_alt_text: bool = True,
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id,
        harness_id="h1",
        document_hash=f"doc-{experiment_id}",
        document_type="scientific_paper",
        violation_types=[],
        fix_sequence=[],
        violations_before=0,
        violations_after=0,
        passed=passed,
        elapsed_seconds=1.0,
        confidence=0.9,
        quality_dimensions={
            "alt_text": alt_text,
            "reading_order": reading_order,
        },
        behavioral_results={
            "alt_text_substitution": behavioral_alt_text,
        },
    )


def test_experiment_store_round_trips_quality_dimensions() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(_record("e1", passed=True, alt_text=0.6, behavioral_alt_text=False))

    records = store.get_experiments_for_harness("h1")

    assert len(records) == 1
    assert records[0].document_format == "pdf"
    assert records[0].quality_dimensions == {"alt_text": 0.6, "reading_order": 0.9}
    assert records[0].behavioral_results == {"alt_text_substitution": False}


def test_experiment_store_round_trips_format_specific_quality_dimensions() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="workbook-1",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            quality_dimensions={"sheet_organization": 0.7},
            behavioral_results={"sheet_navigation": False},
        )
    )

    records = store.get_experiments_for_harness("h1")

    assert len(records) == 1
    assert records[0].document_format == "xlsx"
    assert records[0].quality_dimensions == {"sheet_organization": 0.7}
    assert records[0].behavioral_results == {"sheet_navigation": False}


def test_experiment_store_rejects_malformed_quality_payloads() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    invalid_records = [
        ExperimentRecord(
            experiment_id="non-object-quality",
            harness_id="h1",
            document_hash="doc-non-object-quality",
            document_type="scientific_paper",
            quality_dimensions=["alt_text"],  # type: ignore[arg-type]
        ),
        ExperimentRecord(
            experiment_id="blank-quality-key",
            harness_id="h1",
            document_hash="doc-blank-quality-key",
            document_type="scientific_paper",
            quality_dimensions={"": 0.9},
        ),
        ExperimentRecord(
            experiment_id="numeric-quality-key",
            harness_id="h1",
            document_hash="doc-numeric-quality-key",
            document_type="scientific_paper",
            quality_dimensions={123: 0.9},  # type: ignore[dict-item]
        ),
        ExperimentRecord(
            experiment_id="non-canonical-quality-key",
            harness_id="h1",
            document_hash="doc-non-canonical-quality-key",
            document_type="scientific_paper",
            quality_dimensions={" alt_text ": 0.9},
        ),
        ExperimentRecord(
            experiment_id="unknown-quality-key",
            harness_id="h1",
            document_hash="doc-unknown-quality-key",
            document_type="scientific_paper",
            quality_dimensions={"visual_polish": 0.9},
        ),
        _record("bool-score", passed=True, alt_text=True),
        _record("nan-score", passed=True, alt_text=float("nan")),
        _record("out-of-range", passed=True, alt_text=1.2),
        ExperimentRecord(
            experiment_id="non-object-behavioral",
            harness_id="h1",
            document_hash="doc-non-object-behavioral",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results=["alt_text_substitution"],  # type: ignore[arg-type]
        ),
        ExperimentRecord(
            experiment_id="blank-behavioral-key",
            harness_id="h1",
            document_hash="doc-blank-behavioral-key",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={"": True},
        ),
        ExperimentRecord(
            experiment_id="numeric-behavioral-key",
            harness_id="h1",
            document_hash="doc-numeric-behavioral-key",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={123: True},  # type: ignore[dict-item]
        ),
        ExperimentRecord(
            experiment_id="non-canonical-behavioral-key",
            harness_id="h1",
            document_hash="doc-non-canonical-behavioral-key",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={" alt_text_substitution ": True},
        ),
        ExperimentRecord(
            experiment_id="unknown-behavioral-key",
            harness_id="h1",
            document_hash="doc-unknown-behavioral-key",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={"visual_polish_proxy": True},
        ),
        ExperimentRecord(
            experiment_id="bad-format",
            harness_id="h1",
            document_hash="doc-bad-format",
            document_format="txt",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
        ),
        ExperimentRecord(
            experiment_id="non-canonical-format",
            harness_id="h1",
            document_hash="doc-non-canonical-format",
            document_format=" PDF ",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
        ),
        ExperimentRecord(
            experiment_id="inapplicable-quality-format",
            harness_id="h1",
            document_hash="doc-inapplicable-quality-format",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            quality_dimensions={"reading_order": 0.9},
        ),
        ExperimentRecord(
            experiment_id="inapplicable-behavioral-format",
            harness_id="h1",
            document_hash="doc-inapplicable-behavioral-format",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            quality_dimensions={"sheet_organization": 0.9},
            behavioral_results={"reading_order_comprehension": False},
        ),
        ExperimentRecord(
            experiment_id="bad-behavioral",
            harness_id="h1",
            document_hash="doc-bad-behavioral",
            document_type="scientific_paper",
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={"alt_text_substitution": "yes"},
        ),
    ]

    for record in invalid_records:
        try:
            store.record_experiment(record)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed quality evidence should be rejected")

    assert store.get_experiments_for_harness("h1") == []


def test_failure_patterns_include_dimension_aware_quality_signals() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(_record("e1", passed=True, alt_text=0.6, behavioral_alt_text=False))
    store.record_experiment(_record("e2", passed=False, alt_text=0.7, behavioral_alt_text=True))

    patterns = store.get_failure_patterns("h1")

    assert patterns["weak_dimensions_overall"] == {"alt_text": 0.65}
    assert patterns["weak_dimensions_by_doc_type"] == {
        "scientific_paper": {"alt_text": 0.65}
    }
    assert patterns["weak_dimensions_by_format"] == {
        "pdf": {"alt_text": 0.65}
    }
    assert patterns["weak_dimensions_by_format_and_doc_type"] == {
        "pdf": {"scientific_paper": {"alt_text": 0.65}}
    }
    assert patterns["compliance_passes_quality_fails"] == [
        {"doc_hash": "doc-e1", "weak_dims": ["alt_text"]}
    ]
    assert patterns["behavioral_proxy_failures_by_dim"] == {"alt_text": 1}
    assert patterns["behavioral_proxy_failures_by_format"] == {
        "pdf": {"alt_text": 1}
    }


def test_failure_patterns_keep_format_specific_quality_signals_separate() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="pdf-1",
            harness_id="h1",
            document_hash="pdf-1",
            document_format="pdf",
            document_type="report",
            passed=True,
            quality_dimensions={"alt_text": 0.9},
            behavioral_results={"alt_text_substitution": False},
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="xlsx-1",
            document_format="xlsx",
            document_type="report",
            passed=True,
            quality_dimensions={"alt_text": 0.3, "sheet_organization": 0.4},
            behavioral_results={"sheet_navigation": False},
        )
    )

    patterns = store.get_failure_patterns("h1")

    assert patterns["weak_dimensions_overall"] == {
        "alt_text": 0.6,
        "sheet_organization": 0.4,
    }
    assert patterns["weak_dimensions_by_format"] == {
        "xlsx": {"alt_text": 0.3, "sheet_organization": 0.4}
    }
    assert patterns["weak_dimensions_by_format_and_doc_type"] == {
        "xlsx": {"report": {"alt_text": 0.3, "sheet_organization": 0.4}}
    }
    assert patterns["behavioral_proxy_failures_by_format"] == {
        "pdf": {"alt_text": 1},
        "xlsx": {"sheet_organization": 1},
    }


def test_judge_calibration_records_are_persisted() -> None:
    store = ExperimentStore(":memory:")
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.82,
        sample_size=30,
        measured_at="2026-05-08T00:00:00+00:00",
    )

    rows = store.list_judge_calibration(format="pdf", dimension="alt_text")

    assert rows == [
        {
            "judge_id": "pdf_alt_text_quality",
            "judge_version": "v1",
            "format": "pdf",
            "dimension": "alt_text",
            "cohens_kappa": 0.82,
            "sample_size": 30,
            "measured_at": "2026-05-08T00:00:00+00:00",
        }
    ]


def test_judge_calibration_rows_sort_by_timezone_aware_instant() -> None:
    store = ExperimentStore(":memory:")
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.9,
        sample_size=30,
        measured_at="2026-05-09T01:00:00+02:00",
    )
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.7,
        sample_size=30,
        measured_at="2026-05-09T00:30:00+00:00",
    )

    rows = store.list_judge_calibration(format="pdf", dimension="alt_text")

    assert [row["cohens_kappa"] for row in rows] == [0.7, 0.9]


def test_judge_calibration_rejects_invalid_metric_values() -> None:
    store = ExperimentStore(":memory:")

    invalid_rows = [
        {"judge_id": "", "format": "pdf", "dimension": "alt_text", "cohens_kappa": 0.8, "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"judge_version": "", "format": "pdf", "dimension": "alt_text", "cohens_kappa": 0.8, "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"format": "txt", "dimension": "alt_text", "cohens_kappa": 0.8, "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"format": "xlsx", "dimension": "reading_order", "cohens_kappa": 0.8, "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"cohens_kappa": 1.2, "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"cohens_kappa": float("nan"), "sample_size": 30, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"cohens_kappa": 0.8, "sample_size": 0, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"cohens_kappa": 0.8, "sample_size": 1.5, "measured_at": "2026-05-08T00:00:00+00:00"},
        {"cohens_kappa": 0.8, "sample_size": 30, "measured_at": "2026-05-08T00:00:00"},
    ]

    for row in invalid_rows:
        try:
            judge_id = row.pop("judge_id", "pdf_alt_text_quality")
            judge_version = row.pop("judge_version", "v1")
            fmt = row.pop("format", "pdf")
            dimension = row.pop("dimension", "alt_text")
            store.record_judge_calibration(
                judge_id=judge_id,
                judge_version=judge_version,
                format=fmt,
                dimension=dimension,
                **row,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid calibration metric should be rejected")

    assert store.list_judge_calibration() == []


def test_scorer_returns_v2_result_with_per_dimension_metrics() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(_record("e1", passed=True, alt_text=0.6, behavioral_alt_text=False))
    store.record_experiment(_record("e2", passed=True, alt_text=0.8, behavioral_alt_text=True))

    result = HarnessScorer(store, min_docs_for_scoring=1).score_variant("h1")

    assert isinstance(result, ScoringResultV2)
    assert result.per_dimension["alt_text"].quality_score == 0.7
    assert result.per_dimension["alt_text"].behavioral_pass_rate == 0.5
    assert result.per_dimension["alt_text"].sample_size == 2
    assert result.document_class_breakdown == {
        "scientific_paper": {"alt_text": 0.7, "reading_order": 0.9}
    }
    assert result.format_breakdown == {
        "pdf": {"alt_text": 0.7, "reading_order": 0.9}
    }


def test_scorer_format_breakdown_uses_experiment_record_formats() -> None:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    store.record_experiment(
        ExperimentRecord(
            experiment_id="pdf-1",
            harness_id="h1",
            document_hash="doc-pdf",
            document_format="pdf",
            document_type="scientific_paper",
            passed=True,
            quality_dimensions={"alt_text": 0.7},
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="doc-xlsx",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            passed=True,
            quality_dimensions={"sheet_organization": 0.6},
        )
    )

    result = HarnessScorer(store, min_docs_for_scoring=1).score_variant("h1")

    assert result is not None
    assert result.per_dimension["pdf:alt_text"].format == "pdf"
    assert result.per_dimension["xlsx:sheet_organization"].format == "xlsx"
    assert result.format_breakdown == {
        "pdf": {"alt_text": 0.7},
        "xlsx": {"sheet_organization": 0.6},
    }


def test_dimension_metrics_can_be_computed_without_behavioral_results() -> None:
    metrics = compute_dimension_metrics_from_experiments(
        [
            ExperimentRecord(
                quality_dimensions={"table_structure": 0.75},
                behavioral_results={},
            )
        ]
    )

    assert metrics["table_structure"].quality_score == 0.75
    assert metrics["table_structure"].behavioral_pass_rate == 0.0


def test_dimension_metrics_include_behavioral_only_dimensions() -> None:
    metrics = compute_dimension_metrics_from_experiments(
        [
            ExperimentRecord(
                quality_dimensions={},
                behavioral_results={"alt_text_substitution": False},
            ),
            ExperimentRecord(
                quality_dimensions={},
                behavioral_results={"alt_text_substitution": True},
            ),
        ]
    )

    assert metrics["alt_text"].quality_score == 0.0
    assert metrics["alt_text"].behavioral_pass_rate == 0.5
    assert metrics["alt_text"].sample_size == 2


def test_dimension_metrics_support_format_specific_dimensions() -> None:
    metrics = compute_dimension_metrics_from_experiments(
        [
            ExperimentRecord(
                document_format="xlsx",
                quality_dimensions={"sheet_organization": 0.75},
                behavioral_results={"sheet_navigation": False},
            )
        ],
        fmt="xlsx",
    )

    assert metrics["sheet_organization"].format == "xlsx"
    assert metrics["sheet_organization"].quality_score == 0.75
    assert metrics["sheet_organization"].behavioral_pass_rate == 0.0


def test_dimension_metrics_by_format_uses_record_formats() -> None:
    metrics = compute_dimension_metrics_by_format(
        [
            ExperimentRecord(
                document_format="pdf",
                quality_dimensions={"alt_text": 0.75},
            ),
            ExperimentRecord(
                document_format="xlsx",
                quality_dimensions={"sheet_organization": 0.65},
            ),
        ]
    )

    assert metrics["pdf:alt_text"].format == "pdf"
    assert metrics["pdf:alt_text"].quality_score == 0.75
    assert metrics["xlsx:sheet_organization"].format == "xlsx"
    assert metrics["xlsx:sheet_organization"].quality_score == 0.65


def test_dimension_metrics_rejects_malformed_format() -> None:
    for fmt, expected in (
        (True, "fmt must be a non-empty string"),
        (" PDF ", "fmt must be canonical"),
        ("txt", "unsupported metrics format: txt"),
    ):
        try:
            compute_dimension_metrics_from_experiments(
                [ExperimentRecord(quality_dimensions={"alt_text": 0.75})],
                fmt=fmt,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed metrics format should fail")


def test_dimension_metrics_rejects_format_inapplicable_dimensions() -> None:
    try:
        compute_dimension_metrics_from_experiments(
            [
                ExperimentRecord(
                    document_format="xlsx",
                    quality_dimensions={"reading_order": 0.75},
                    behavioral_results={},
                )
            ],
            fmt="xlsx",
        )
    except ValueError as exc:
        assert (
            "quality_dimensions dimension 'reading_order' "
            "is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("format-inapplicable quality metric should fail")

    try:
        compute_dimension_metrics_from_experiments(
            [
                ExperimentRecord(
                    document_format="xlsx",
                    quality_dimensions={"sheet_organization": 0.75},
                    behavioral_results={"reading_order_comprehension": False},
                )
            ],
            fmt="xlsx",
        )
    except ValueError as exc:
        assert (
            "behavioral_results.reading_order_comprehension "
            "dimension 'reading_order' is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("format-inapplicable behavioral metric should fail")


def test_dimension_metrics_rejects_malformed_quality_scores() -> None:
    for score, expected in (
        (True, "quality_dimensions.alt_text must be numeric"),
        ("high", "quality_dimensions.alt_text must be numeric"),
        (float("nan"), "quality_dimensions.alt_text must be finite"),
        (1.2, "quality_dimensions.alt_text must be between 0.0 and 1.0"),
    ):
        try:
            compute_dimension_metrics_from_experiments(
                [ExperimentRecord(quality_dimensions={"alt_text": score})]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed quality metric score should fail")


def test_document_class_breakdown_rejects_malformed_quality_scores() -> None:
    try:
        compute_document_class_breakdown(
            [
                ExperimentRecord(
                    document_type="scientific_paper",
                    quality_dimensions={"alt_text": True},
                )
            ]
        )
    except ValueError as exc:
        assert "quality_dimensions.alt_text must be numeric" in str(exc)
    else:
        raise AssertionError("malformed document-class quality score should fail")


def test_dimension_metrics_rejects_non_boolean_behavioral_results() -> None:
    try:
        compute_dimension_metrics_from_experiments(
            [
                ExperimentRecord(
                    quality_dimensions={},
                    behavioral_results={"alt_text_substitution": "yes"},
                )
            ]
        )
    except ValueError as exc:
        assert "behavioral_results.alt_text_substitution must be a boolean" in str(exc)
    else:
        raise AssertionError("non-boolean behavioral metric should fail")


def test_experiment_store_additive_migration_for_existing_database(tmp_path) -> None:
    db_path = tmp_path / "experiments.db"
    _create_legacy_experiment_db(db_path)

    store = ExperimentStore(db_path)
    store.register_variant("h1")
    store.record_experiment(_record("e1", passed=True, alt_text=0.9))

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(experiment_records)").fetchall()
        }
        calibration_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='judge_calibration'"
        ).fetchone()

    assert "quality_dimensions_json" in columns
    assert "behavioral_results_json" in columns
    assert "document_format" in columns
    assert calibration_exists is not None


def test_experiment_store_rejects_corrupted_persisted_quality_evidence(tmp_path) -> None:
    cases = [
        (
            "bad-quality-json",
            "{bad-json",
            "{}",
            "pdf",
            "quality_dimensions_json must contain valid JSON",
        ),
        (
            "non-object-quality",
            '["alt_text"]',
            "{}",
            "pdf",
            "quality_dimensions must be an object",
        ),
        (
            "unknown-quality",
            '{"visual_polish": 0.9}',
            "{}",
            "pdf",
            "unsupported quality dimension: visual_polish",
        ),
        (
            "bad-behavioral-json",
            "{}",
            "{bad-json",
            "pdf",
            "behavioral_results_json must contain valid JSON",
        ),
        (
            "non-object-behavioral",
            "{}",
            '["alt_text_substitution"]',
            "pdf",
            "behavioral_results must be an object",
        ),
        (
            "unknown-behavioral",
            "{}",
            '{"visual_polish_proxy": true}',
            "pdf",
            "unsupported behavioral result test: visual_polish_proxy",
        ),
        (
            "bad-format",
            '{"alt_text": 0.9}',
            "{}",
            "txt",
            "unsupported document_format: txt",
        ),
        (
            "inapplicable-format-dimension",
            '{"reading_order": 0.9}',
            "{}",
            "xlsx",
            "quality dimension 'reading_order' is not applicable to xlsx",
        ),
    ]

    for experiment_id, quality_json, behavioral_json, document_format, expected in cases:
        db_path = tmp_path / f"{experiment_id}.db"
        store = ExperimentStore(db_path)
        store.register_variant("h1")
        _insert_raw_experiment_row(
            db_path,
            experiment_id=experiment_id,
            document_format=document_format,
            quality_dimensions_json=quality_json,
            behavioral_results_json=behavioral_json,
        )

        try:
            store.get_experiments_for_harness("h1")
        except ValueError as exc:
            assert expected in str(exc)
            assert f"experiment {experiment_id}" in str(exc)
        else:
            raise AssertionError("corrupted persisted quality evidence should fail")


def _insert_raw_experiment_row(
    db_path: Path,
    *,
    experiment_id: str,
    document_format: str = "pdf",
    quality_dimensions_json: str,
    behavioral_results_json: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO experiment_records
               (experiment_id, harness_id, document_hash, document_format, quality_dimensions_json,
                behavioral_results_json, created_at)
               VALUES (?, 'h1', ?, ?, ?, ?, '2026-05-09T00:00:00+00:00')""",
            (
                experiment_id,
                f"doc-{experiment_id}",
                document_format,
                quality_dimensions_json,
                behavioral_results_json,
            ),
        )


def _create_legacy_experiment_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE harness_variants (
                harness_id              TEXT PRIMARY KEY,
                parent_id               TEXT,
                description             TEXT NOT NULL DEFAULT '',
                status                  TEXT NOT NULL DEFAULT 'active',
                conformance_rate        REAL NOT NULL DEFAULT 0.0,
                manual_review_rate      REAL NOT NULL DEFAULT 0.0,
                destructive_edit_count  INTEGER NOT NULL DEFAULT 0,
                avg_seconds             REAL NOT NULL DEFAULT 0.0,
                total_docs              INTEGER NOT NULL DEFAULT 0,
                passed_docs             INTEGER NOT NULL DEFAULT 0,
                created_at              TEXT NOT NULL,
                retired_at              TEXT,
                promoted_at             TEXT,
                harness_config_json     TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE experiment_records (
                experiment_id       TEXT PRIMARY KEY,
                harness_id          TEXT NOT NULL,
                document_hash       TEXT NOT NULL,
                document_type       TEXT NOT NULL DEFAULT '',
                violation_types_json TEXT NOT NULL DEFAULT '[]',
                fix_sequence_json   TEXT NOT NULL DEFAULT '[]',
                violations_before   INTEGER NOT NULL DEFAULT 0,
                violations_after    INTEGER NOT NULL DEFAULT 0,
                passed              INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds     REAL NOT NULL DEFAULT 0.0,
                confidence          REAL NOT NULL DEFAULT 0.0,
                error               TEXT,
                created_at          TEXT NOT NULL
            );
            """
        )
