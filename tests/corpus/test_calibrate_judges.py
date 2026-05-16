from __future__ import annotations

import hashlib
import json

import tools.calibrate_judges as calibrate_judges
from project_remedy.vision_planner.experiment_store import ExperimentStore
from tools.annotate_corpus import build_annotation_record, write_annotation_record
from tools.calibrate_judges import (
    build_drift_alerts,
    build_rolling_drift_alerts,
    calibration_readiness_errors,
    CalibrationMetric,
    compute_cohens_kappa,
    DEFAULT_KAPPA_THRESHOLD,
    emit_drift_alerts,
    main,
    load_judge_comparison_rows,
    load_judge_result_rows,
    metrics_from_store_rows,
    run_audits_for_annotations,
    score_to_label,
    summarize_calibration,
    summarize_pairwise_calibration,
    JudgeComparisonRow,
    JudgeResultRow,
    judge_result_binding_errors,
    judge_comparison_binding_errors,
)


class _FakeDimensionScore:
    def __init__(self, score: float, judge_versions: list[str]) -> None:
        self.score = score
        self.judge_versions = judge_versions


class _FakeAuditResult:
    def __init__(self) -> None:
        self.dimensions = {
            "alt_text": _FakeDimensionScore(
                0.91,
                ["pdf_alt_text_quality:alt_text_judge_v1"],
            )
        }


def _source_binding(source) -> dict[str, str]:
    return {
        "artifact_path": str(source),
        "artifact_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def _external_judge_metadata() -> dict[str, str]:
    return {"judge_model": "llama3.1:8b"}


def test_score_labels_and_cohens_kappa() -> None:
    assert score_to_label(0.8) == "pass"
    assert score_to_label(0.79) == "fail"
    try:
        score_to_label(True)
    except ValueError as exc:
        assert "score must be numeric" in str(exc)
    else:
        raise AssertionError("boolean calibration score should fail")
    try:
        score_to_label(float("nan"))
    except ValueError as exc:
        assert "score must be finite" in str(exc)
    else:
        raise AssertionError("non-finite calibration score should fail")
    try:
        score_to_label(0.8, threshold=float("nan"))
    except ValueError as exc:
        assert "threshold must be finite" in str(exc)
    else:
        raise AssertionError("non-finite calibration threshold should fail")
    assert compute_cohens_kappa([("pass", "pass"), ("fail", "fail")]) == 1.0
    assert compute_cohens_kappa([("pass", "pass"), ("fail", "pass")]) == 0.0
    assert DEFAULT_KAPPA_THRESHOLD == 0.8


def test_summarize_calibration_groups_by_judge_format_and_dimension(tmp_path) -> None:
    records = [
        build_annotation_record(
            source_path=tmp_path / "a.pdf",
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        build_annotation_record(
            source_path=tmp_path / "b.pdf",
            fmt="pdf",
            doc_id="pdf-b",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.2},
        ),
    ]
    judge_rows = [
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.95,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
        ),
        JudgeResultRow(
            doc_id="pdf-b",
            format="pdf",
            dimension="alt_text",
            score=0.1,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
        ),
    ]

    metrics = summarize_calibration(records, judge_rows, measured_at="2026-05-08T00:00:00+00:00")

    assert len(metrics) == 1
    assert metrics[0].cohens_kappa == 1.0
    assert metrics[0].sample_size == 2
    assert metrics[0].format == "pdf"
    assert metrics[0].dimension == "alt_text"


def test_summarize_pairwise_calibration_uses_annotation_comparisons(tmp_path) -> None:
    records = [
        build_annotation_record(
            source_path=tmp_path / "source.pdf",
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        )
    ]
    records[0]["pairwise_comparisons"] = [
        {
            "a_path": "candidate-a.pdf",
            "b_path": "candidate-b.pdf",
            "a_sha256": "",
            "b_sha256": "",
            "winner": "a",
            "dimension": "alt_text",
            "rationale": "Candidate A has more specific alt text.",
        },
        {
            "a_path": "candidate-c.pdf",
            "b_path": "candidate-d.pdf",
            "a_sha256": "",
            "b_sha256": "",
            "winner": "b",
            "dimension": "alt_text",
            "rationale": "Candidate B preserves chart detail.",
        },
    ]
    judge_rows = [
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path="candidate-a.pdf",
            b_path="candidate-b.pdf",
            winner="A_better",
            judge_id="pdf_alt_text_pairwise",
            judge_version="alt_text_judge_v1",
        ),
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path="candidate-c.pdf",
            b_path="candidate-d.pdf",
            winner="B_better",
            judge_id="pdf_alt_text_pairwise",
            judge_version="alt_text_judge_v1",
        ),
    ]

    metrics = summarize_pairwise_calibration(
        records,
        judge_rows,
        measured_at="2026-05-08T00:00:00+00:00",
    )

    assert len(metrics) == 1
    assert metrics[0].judge_id == "pdf_alt_text_pairwise"
    assert metrics[0].cohens_kappa == 1.0
    assert metrics[0].sample_size == 2


def test_build_drift_alerts_returns_structured_payload() -> None:
    metrics = [
        summarize_calibration(
            [
                {
                    "doc_id": "pdf-a",
                    "format": "pdf",
                    "dimensions": {"alt_text": {"score": 0.9}},
                },
                {
                    "doc_id": "pdf-b",
                    "format": "pdf",
                    "dimensions": {"alt_text": {"score": 0.2}},
                },
            ],
            [
                JudgeResultRow(
                    doc_id="pdf-a",
                    format="pdf",
                    dimension="alt_text",
                    score=0.9,
                    judge_id="pdf_alt_text_quality",
                    judge_version="alt_text_judge_v1",
                ),
                JudgeResultRow(
                    doc_id="pdf-b",
                    format="pdf",
                    dimension="alt_text",
                    score=0.9,
                    judge_id="pdf_alt_text_quality",
                    judge_version="alt_text_judge_v1",
                ),
            ],
            measured_at="2026-05-08T00:00:00+00:00",
        )[0]
    ]

    alerts = build_drift_alerts(metrics, kappa_threshold=0.7, min_samples=1)

    assert alerts == [
        {
            "event": "quality_judge_drift",
            "judge_id": "pdf_alt_text_quality",
            "judge_version": "alt_text_judge_v1",
            "format": "pdf",
            "dimension": "alt_text",
            "cohens_kappa": 0.0,
            "kappa_threshold": 0.7,
            "sample_size": 2,
            "measured_at": "2026-05-08T00:00:00+00:00",
        }
    ]


def test_build_rolling_drift_alerts_uses_weighted_recent_window() -> None:
    metrics = [
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.95,
            sample_size=4,
            measured_at="2026-05-06T00:00:00+00:00",
        ),
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.40,
            sample_size=2,
            measured_at="2026-05-07T00:00:00+00:00",
        ),
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.20,
            sample_size=2,
            measured_at="2026-05-08T00:00:00+00:00",
        ),
    ]

    alerts = build_rolling_drift_alerts(
        metrics,
        kappa_threshold=0.7,
        min_samples=4,
        rolling_window=2,
    )

    assert alerts == [
        {
            "event": "quality_judge_drift",
            "judge_id": "pdf_alt_text_quality",
            "judge_version": "alt_text_judge_v1",
            "format": "pdf",
            "dimension": "alt_text",
            "cohens_kappa": 0.3,
            "kappa_threshold": 0.7,
            "sample_size": 4,
            "measured_at": "2026-05-08T00:00:00+00:00",
            "rolling_window": 2,
            "window_measurements": 2,
            "window_start": "2026-05-07T00:00:00+00:00",
            "window_end": "2026-05-08T00:00:00+00:00",
        }
    ]


def test_build_rolling_drift_alerts_orders_by_timezone_aware_instant() -> None:
    metrics = [
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.95,
            sample_size=1,
            measured_at="2026-05-08T22:00:00+00:00",
        ),
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.10,
            sample_size=1,
            measured_at="2026-05-09T05:00:00+00:00",
        ),
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.20,
            sample_size=1,
            measured_at="2026-05-08T23:30:00-07:00",
        ),
    ]

    alerts = build_rolling_drift_alerts(
        metrics,
        kappa_threshold=0.7,
        min_samples=2,
        rolling_window=2,
    )

    assert alerts[0]["cohens_kappa"] == 0.15
    assert alerts[0]["window_start"] == "2026-05-09T05:00:00+00:00"
    assert alerts[0]["window_end"] == "2026-05-08T23:30:00-07:00"
    assert alerts[0]["measured_at"] == "2026-05-08T23:30:00-07:00"


def test_drift_alert_helpers_reject_invalid_thresholds() -> None:
    metrics = [
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.2,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )
    ]

    try:
        build_drift_alerts(metrics, kappa_threshold=float("nan"), min_samples=1)
    except ValueError as exc:
        assert "kappa_threshold must be finite" in str(exc)
    else:
        raise AssertionError("non-finite kappa threshold should fail")

    try:
        build_rolling_drift_alerts(
            metrics,
            kappa_threshold=0.8,
            min_samples=1,
            rolling_window=0,
        )
    except ValueError as exc:
        assert "rolling_window must be a positive integer" in str(exc)
    else:
        raise AssertionError("non-positive rolling window should fail")


def test_drift_alert_helpers_reject_malformed_metrics() -> None:
    base_metric = CalibrationMetric(
        judge_id="pdf_alt_text_quality",
        judge_version="alt_text_judge_v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.2,
        sample_size=1,
        measured_at="2026-05-08T00:00:00+00:00",
    )
    invalid_metrics = [
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "cohens_kappa": float("nan")}
            ),
            "metric 1.cohens_kappa must be finite",
        ),
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "sample_size": 1.5}
            ),
            "metric 1.sample_size must be a positive integer",
        ),
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "measured_at": "2026-05-08T00:00:00"}
            ),
            "metric 1.measured_at must include a timezone",
        ),
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "format": "txt"}
            ),
            "metric 1: unsupported format: txt",
        ),
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "format": "xlsx", "dimension": "reading_order"}
            ),
            "metric 1: dimension 'reading_order' is not applicable to xlsx",
        ),
        (
            CalibrationMetric(
                **{**base_metric.__dict__, "judge_id": ""}
            ),
            "metric 1.judge_id must be a non-empty string",
        ),
    ]

    for metric, expected in invalid_metrics:
        try:
            build_drift_alerts(
                [metric],
                kappa_threshold=0.8,
                min_samples=1,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed calibration metric should fail")


def test_emit_drift_alerts_rejects_malformed_alerts_before_side_effects(tmp_path) -> None:
    alert_log = tmp_path / "drift_alerts.jsonl"

    try:
        emit_drift_alerts(
            [
                {
                    "event": "quality_judge_drift",
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    "format": "xlsx",
                    "dimension": "reading_order",
                    "cohens_kappa": 0.2,
                    "kappa_threshold": 0.8,
                    "sample_size": 1,
                    "measured_at": "2026-05-08T00:00:00+00:00",
                }
            ],
            alert_log=alert_log,
        )
    except ValueError as exc:
        assert "dimension 'reading_order' is not applicable to xlsx" in str(exc)
    else:
        raise AssertionError("malformed drift alert should fail")

    assert not alert_log.exists()


def test_emit_drift_alerts_rejects_non_http_webhook_url(tmp_path) -> None:
    alert = {
        "event": "quality_judge_drift",
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "format": "pdf",
        "dimension": "alt_text",
        "cohens_kappa": 0.2,
        "kappa_threshold": 0.8,
        "sample_size": 1,
        "measured_at": "2026-05-08T00:00:00+00:00",
    }

    try:
        emit_drift_alerts([alert], webhook_url="file:///tmp/drift-alert")
    except ValueError as exc:
        assert "alert_webhook must be an http(s) URL" in str(exc)
    else:
        raise AssertionError("non-http drift alert webhook should fail")


def test_emit_drift_alerts_rejects_bad_webhook_before_log_side_effect(tmp_path) -> None:
    alert_log = tmp_path / "drift_alerts.jsonl"
    alert = {
        "event": "quality_judge_drift",
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "format": "pdf",
        "dimension": "alt_text",
        "cohens_kappa": 0.2,
        "kappa_threshold": 0.8,
        "sample_size": 1,
        "measured_at": "2026-05-08T00:00:00+00:00",
    }

    try:
        emit_drift_alerts(
            [alert],
            alert_log=alert_log,
            webhook_url="file:///tmp/drift-alert",
        )
    except ValueError as exc:
        assert "alert_webhook must be an http(s) URL" in str(exc)
    else:
        raise AssertionError("invalid drift alert webhook should fail before logging")

    assert not alert_log.exists()


def test_metrics_from_store_rows_round_trips_calibration_records(tmp_path) -> None:
    store = ExperimentStore(tmp_path / "quality_experiments.db")
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="alt_text_judge_v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=0.81,
        sample_size=7,
        measured_at="2026-05-08T00:00:00+00:00",
    )

    metrics = metrics_from_store_rows(store.list_judge_calibration())

    assert metrics == [
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.81,
            sample_size=7,
            measured_at="2026-05-08T00:00:00+00:00",
        )
    ]


def test_metrics_from_store_rows_rejects_corrupted_persisted_rows() -> None:
    base_row = {
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "format": "pdf",
        "dimension": "alt_text",
        "cohens_kappa": 0.81,
        "sample_size": 7,
        "measured_at": "2026-05-08T00:00:00+00:00",
    }
    invalid_rows = [
        ({"cohens_kappa": float("nan")}, "cohens_kappa must be finite"),
        ({"sample_size": 1.5}, "sample_size must be a positive integer"),
        ({"sample_size": "7"}, "sample_size must be a positive integer"),
        ({"measured_at": "2026-05-08T00:00:00"}, "measured_at must include a timezone"),
    ]

    for patch, expected in invalid_rows:
        row = dict(base_row)
        row.update(patch)
        try:
            metrics_from_store_rows([row])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("corrupted persisted calibration row should fail")


def test_calibration_readiness_requires_registered_judges_threshold_and_samples() -> None:
    records = [
        {
            "doc_id": "pdf-a",
            "format": "pdf",
            "dimensions": {"alt_text": {"score": 0.9}},
        }
    ]
    metrics = [
        CalibrationMetric(
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            format="pdf",
            dimension="alt_text",
            cohens_kappa=0.79,
            sample_size=1,
            measured_at="2026-05-08T00:00:00+00:00",
        )
    ]

    errors = calibration_readiness_errors(
        records,
        metrics,
        kappa_threshold=0.8,
        min_samples=2,
    )

    assert any("pdf/alt_text pdf_alt_text_quality:alt_text_judge_v1" in error for error in errors)
    assert any("sample too small" in error for error in errors)
    assert any("below threshold" in error for error in errors)
    assert any("missing calibration metric: pdf/reading_order" in error for error in errors)


def test_calibration_cli_records_metrics_from_judge_results_jsonl(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    source_a = tmp_path / "a.pdf"
    source_b = tmp_path / "b.pdf"
    source_a.write_bytes(b"%PDF-1.4\n%%EOF")
    source_b.write_bytes(b"%PDF-1.4\n%%EOF")

    write_annotation_record(
        build_annotation_record(
            source_path=source_a,
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    write_annotation_record(
        build_annotation_record(
            source_path=source_b,
            fmt="pdf",
            doc_id="pdf-b",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.2},
        ),
        root=root,
    )
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "doc_id": "pdf-a",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_a),
                    **_external_judge_metadata(),
                },
                {
                    "doc_id": "pdf-b",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.1,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_b),
                    **_external_judge_metadata(),
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(judge_results),
            "--store",
            str(store_path),
            "--json",
        ]
    )

    assert result == 0
    stored = ExperimentStore(store_path).list_judge_calibration(
        format="pdf",
        dimension="alt_text",
    )
    assert len(stored) == 1
    assert stored[0]["judge_id"] == "pdf_alt_text_quality"
    assert stored[0]["cohens_kappa"] == 1.0
    assert stored[0]["sample_size"] == 2


def test_load_judge_result_rows_rejects_inapplicable_dimension(tmp_path) -> None:
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        json.dumps(
            {
                "doc_id": "xlsx-a",
                "format": "xlsx",
                "dimension": "reading_order",
                "score": 0.9,
                "judge_id": "xlsx_reading_order_quality",
                "judge_version": "v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_judge_result_rows(judge_results)
    except ValueError as exc:
        assert "dimension 'reading_order' is not applicable to xlsx" in str(exc)
    else:
        raise AssertionError("inapplicable judge result dimension should fail")


def test_load_judge_result_rows_rejects_boolean_score_and_empty_fields(tmp_path) -> None:
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": "pdf-a",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "score": True,
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                    }
                ),
                json.dumps(
                    {
                        "doc_id": "",
                        "format": "pdf",
                        "dimension": "alt_text",
                        "score": 0.9,
                        "judge_id": "pdf_alt_text_quality",
                        "judge_version": "alt_text_judge_v1",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_judge_result_rows(judge_results)
    except ValueError as exc:
        assert "score must be numeric" in str(exc)
    else:
        raise AssertionError("boolean judge result score should fail")

    judge_results.write_text(judge_results.read_text(encoding="utf-8").splitlines()[1] + "\n", encoding="utf-8")
    try:
        load_judge_result_rows(judge_results)
    except ValueError as exc:
        assert "doc_id must be a non-empty string" in str(exc)
    else:
        raise AssertionError("empty judge result doc_id should fail")


def test_load_judge_result_rows_rejects_non_string_identity_and_metadata(tmp_path) -> None:
    judge_results = tmp_path / "judge_results.jsonl"
    base_row = {
        "doc_id": "pdf-a",
        "format": "pdf",
        "dimension": "alt_text",
        "score": 0.9,
        "judge_id": "pdf_alt_text_quality",
        "judge_version": "alt_text_judge_v1",
        "artifact_path": "source.pdf",
        "artifact_sha256": "a" * 64,
        "judge_model": "llama3.1:8b",
    }

    for field_name, value, expected in [
        ("judge_id", 123, "judge_id must be a non-empty string"),
        ("artifact_path", 123, "artifact_path must be a string"),
        ("artifact_sha256", 123, "artifact_sha256 must be a string"),
        ("judge_model", 123, "judge_model must be a string"),
        (
            "artifact_generator_model",
            123,
            "artifact_generator_model must be a string",
        ),
    ]:
        row = dict(base_row)
        row[field_name] = value
        judge_results.write_text(json.dumps(row) + "\n", encoding="utf-8")
        try:
            load_judge_result_rows(judge_results)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"non-string {field_name} should fail")


def test_load_judge_result_rows_rejects_non_finite_score(tmp_path) -> None:
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        json.dumps(
            {
                "doc_id": "pdf-a",
                "format": "pdf",
                "dimension": "alt_text",
                "score": float("nan"),
                "judge_id": "pdf_alt_text_quality",
                "judge_version": "alt_text_judge_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_judge_result_rows(judge_results)
    except ValueError as exc:
        assert "score must be finite" in str(exc)
    else:
        raise AssertionError("non-finite judge result score should fail")


def test_load_judge_comparison_rows_rejects_inapplicable_dimension(tmp_path) -> None:
    judge_comparisons = tmp_path / "judge_comparisons.jsonl"
    judge_comparisons.write_text(
        json.dumps(
            {
                "format": "xlsx",
                "dimension": "reading_order",
                "a_path": "candidate-a.xlsx",
                "b_path": "candidate-b.xlsx",
                "winner": "a",
                "judge_id": "xlsx_reading_order_pairwise",
                "judge_version": "v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_judge_comparison_rows(judge_comparisons)
    except ValueError as exc:
        assert "dimension 'reading_order' is not applicable to xlsx" in str(exc)
    else:
        raise AssertionError("inapplicable judge comparison dimension should fail")


def test_load_judge_comparison_rows_rejects_empty_required_fields(tmp_path) -> None:
    judge_comparisons = tmp_path / "judge_comparisons.jsonl"
    judge_comparisons.write_text(
        json.dumps(
            {
                "format": "pdf",
                "dimension": "alt_text",
                "a_path": "",
                "b_path": "candidate-b.pdf",
                "winner": "a",
                "judge_id": "pdf_alt_text_pairwise",
                "judge_version": "alt_text_judge_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_judge_comparison_rows(judge_comparisons)
    except ValueError as exc:
        assert "a_path must be a non-empty string" in str(exc)
    else:
        raise AssertionError("empty pairwise candidate path should fail")


def test_load_judge_comparison_rows_rejects_non_string_identity_and_metadata(tmp_path) -> None:
    judge_comparisons = tmp_path / "judge_comparisons.jsonl"
    base_row = {
        "format": "pdf",
        "dimension": "alt_text",
        "a_path": "candidate-a.pdf",
        "b_path": "candidate-b.pdf",
        "winner": "a",
        "judge_id": "pdf_alt_text_pairwise",
        "judge_version": "alt_text_judge_v1",
        "a_sha256": "a" * 64,
        "b_sha256": "b" * 64,
        "judge_model": "llama3.1:8b",
    }

    for field_name, value, expected in [
        ("judge_id", 123, "judge_id must be a non-empty string"),
        ("winner", 123, "winner must be a non-empty string"),
        ("a_sha256", 123, "a_sha256 must be a string"),
        ("b_sha256", 123, "b_sha256 must be a string"),
        ("judge_model", 123, "judge_model must be a string"),
        (
            "artifact_generator_model",
            123,
            "artifact_generator_model must be a string",
        ),
    ]:
        row = dict(base_row)
        row[field_name] = value
        judge_comparisons.write_text(json.dumps(row) + "\n", encoding="utf-8")
        try:
            load_judge_comparison_rows(judge_comparisons)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"non-string {field_name} should fail")


def test_judge_result_binding_errors_require_source_artifact_hash(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    other_source = tmp_path / "other.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    other_source.write_bytes(b"%PDF-1.4\nchanged\n%%EOF")
    records = [
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        )
    ]
    rows = [
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.9,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
        ),
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.9,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            artifact_path=str(other_source),
            artifact_sha256=hashlib.sha256(other_source.read_bytes()).hexdigest(),
        ),
    ]

    errors = judge_result_binding_errors(records, rows)

    assert "judge result row 1 pdf-a/pdf/alt_text: missing artifact_path" in errors
    assert "judge result row 1 pdf-a/pdf/alt_text: missing artifact_sha256" in errors
    assert "judge result row 1 pdf-a/pdf/alt_text: missing judge_model" in errors
    assert "judge result row 2 pdf-a/pdf/alt_text: artifact_path must match source_path" in errors
    assert "judge result row 2 pdf-a/pdf/alt_text: artifact_sha256 must match source_sha256" in errors
    assert "judge result row 2 pdf-a/pdf/alt_text: missing judge_model" in errors


def test_judge_result_binding_errors_reject_duplicate_rows(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    records = [
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        )
    ]
    row = JudgeResultRow(
        doc_id="pdf-a",
        format="pdf",
        dimension="alt_text",
        score=0.9,
        judge_id="pdf_alt_text_quality",
        judge_version="alt_text_judge_v1",
        **_source_binding(source),
        **_external_judge_metadata(),
    )

    errors = judge_result_binding_errors(records, [row, row])

    assert "judge result row 2 pdf-a/pdf/alt_text: duplicate judge result row" in errors


def test_judge_result_binding_errors_require_model_metadata_and_separation(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-a",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
        candidate_seed_model="qwen2.5:14b-cloud",
    )
    rows = [
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.9,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            **_source_binding(source),
        ),
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.9,
            judge_id="pdf_alt_text_quality_alt",
            judge_version="alt_text_judge_v1",
            judge_model="qwen2.5:7b",
            artifact_generator_model="qwen2.5:14b-cloud",
            **_source_binding(source),
        ),
    ]

    errors = judge_result_binding_errors([record], rows)

    assert "judge result row 1 pdf-a/pdf/alt_text: missing judge_model" in errors
    assert (
        "judge result row 2 pdf-a/pdf/alt_text: judge_model family must differ "
        "from artifact generator model 'qwen2.5:14b-cloud'"
    ) in errors


def test_run_audits_for_annotations_binds_source_hash_and_rejects_drift(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-a",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )

    monkeypatch.setattr(
        calibrate_judges,
        "_audit_record",
        lambda source_path, fmt, *, config=None: _FakeAuditResult(),
    )
    rows, skipped = run_audits_for_annotations([record])

    assert skipped == []
    assert rows == [
        JudgeResultRow(
            doc_id="pdf-a",
            format="pdf",
            dimension="alt_text",
            score=0.91,
            judge_id="pdf_alt_text_quality",
            judge_version="alt_text_judge_v1",
            artifact_path=str(source),
            artifact_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    ]

    source.write_bytes(b"%PDF-1.4\nchanged\n%%EOF")
    rows, skipped = run_audits_for_annotations([record])

    assert rows == []
    assert skipped == [f"pdf-a: source artifact hash mismatch {source}"]


def test_calibration_cli_rejects_unbound_judge_results_jsonl(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    write_annotation_record(
        build_annotation_record(
            source_path=source,
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        json.dumps(
            {
                "doc_id": "pdf-a",
                "format": "pdf",
                "dimension": "alt_text",
                "score": 0.9,
                "judge_id": "pdf_alt_text_quality",
                "judge_version": "alt_text_judge_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(judge_results),
            "--store",
            str(store_path),
            "--json",
        ]
    )

    assert result == 2
    assert ExperimentStore(store_path).list_judge_calibration() == []


def test_calibration_cli_enforce_readiness_fails_missing_registered_judges(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    source_a = tmp_path / "a.pdf"
    source_b = tmp_path / "b.pdf"
    source_a.write_bytes(b"%PDF-1.4\n%%EOF")
    source_b.write_bytes(b"%PDF-1.4\n%%EOF")
    for doc_id, source, score in (
        ("pdf-a", source_a, 0.9),
        ("pdf-b", source_b, 0.2),
    ):
        write_annotation_record(
            build_annotation_record(
                source_path=source,
                fmt="pdf",
                doc_id=doc_id,
                document_class="paper",
                annotator="specialist_a",
                applicable_dimensions=["alt_text"],
                scores={"alt_text": score},
            ),
            root=root,
        )
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "doc_id": "pdf-a",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_a),
                    **_external_judge_metadata(),
                },
                {
                    "doc_id": "pdf-b",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.1,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_b),
                    **_external_judge_metadata(),
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(judge_results),
            "--store",
            str(store_path),
            "--dry-run",
            "--enforce-readiness",
            "--json",
        ]
    )

    assert result == 1
    assert ExperimentStore(store_path).list_judge_calibration() == []


def test_calibration_cli_records_pairwise_comparison_metrics(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF")
    record = build_annotation_record(
        source_path=source,
        fmt="pdf",
        doc_id="pdf-a",
        document_class="paper",
        annotator="specialist_a",
        applicable_dimensions=["alt_text"],
        scores={"alt_text": 0.9},
    )
    record["pairwise_comparisons"] = [
        {
            "a_path": "candidate-a.pdf",
            "b_path": "candidate-b.pdf",
            "a_sha256": "",
            "b_sha256": "",
            "winner": "a",
            "dimension": "alt_text",
            "rationale": "Candidate A is more useful.",
        },
        {
            "a_path": "candidate-c.pdf",
            "b_path": "candidate-d.pdf",
            "a_sha256": "",
            "b_sha256": "",
            "winner": "b",
            "dimension": "alt_text",
            "rationale": "Candidate B captures the data.",
        },
    ]
    write_annotation_record(record, root=root)
    judge_comparisons = tmp_path / "judge_comparisons.jsonl"
    judge_comparisons.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "format": "pdf",
                    "dimension": "alt_text",
                    "a_path": "candidate-a.pdf",
                    "b_path": "candidate-b.pdf",
                    "winner": "A_better",
                    "judge_id": "pdf_alt_text_pairwise",
                    "judge_version": "alt_text_judge_v1",
                    **_external_judge_metadata(),
                },
                {
                    "format": "pdf",
                    "dimension": "alt_text",
                    "a_path": "candidate-c.pdf",
                    "b_path": "candidate-d.pdf",
                    "winner": "B_better",
                    "judge_id": "pdf_alt_text_pairwise",
                    "judge_version": "alt_text_judge_v1",
                    **_external_judge_metadata(),
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(tmp_path / "empty_judge_results.jsonl"),
            "--judge-comparisons",
            str(judge_comparisons),
            "--store",
            str(store_path),
            "--json",
        ]
    )

    assert result == 2

    (tmp_path / "empty_judge_results.jsonl").write_text("", encoding="utf-8")
    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(tmp_path / "empty_judge_results.jsonl"),
            "--judge-comparisons",
            str(judge_comparisons),
            "--store",
            str(store_path),
            "--json",
        ]
    )

    assert result == 0
    stored = ExperimentStore(store_path).list_judge_calibration(
        format="pdf",
        dimension="alt_text",
    )
    assert stored[0]["judge_id"] == "pdf_alt_text_pairwise"
    assert stored[0]["cohens_kappa"] == 1.0
    assert stored[0]["sample_size"] == 2


def test_judge_comparison_binding_errors_require_candidate_hashes(tmp_path) -> None:
    candidate_a = tmp_path / "candidate-a.pdf"
    candidate_b = tmp_path / "candidate-b.pdf"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b.write_bytes(b"candidate-b")
    records = [
        build_annotation_record(
            source_path=tmp_path / "source.pdf",
            fmt="pdf",
            doc_id="pdf-a",
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
    ]
    rows = [
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path=str(candidate_a),
            b_path=str(candidate_b),
            winner="a",
            judge_id="pdf_alt_text_pairwise",
            judge_version="alt_text_judge_v1",
        ),
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path=str(candidate_a),
            b_path=str(candidate_b),
            winner="a",
            judge_id="pdf_alt_text_pairwise",
            judge_version="alt_text_judge_v1",
            a_sha256="0" * 64,
            b_sha256=hashlib.sha256(b"candidate-b").hexdigest(),
        ),
    ]

    errors = judge_comparison_binding_errors(records, rows)

    assert "judge comparison row 1 pdf/alt_text: missing a_sha256" in errors
    assert "judge comparison row 1 pdf/alt_text: missing b_sha256" in errors
    assert "judge comparison row 2 pdf/alt_text: a_sha256 must match annotation pairwise comparison" in errors


def test_judge_comparison_binding_errors_reject_duplicate_rows(tmp_path) -> None:
    candidate_a = tmp_path / "candidate-a.pdf"
    candidate_b = tmp_path / "candidate-b.pdf"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b.write_bytes(b"candidate-b")
    records = [
        build_annotation_record(
            source_path=tmp_path / "source.pdf",
            fmt="pdf",
            doc_id="pdf-a",
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
    ]
    row = JudgeComparisonRow(
        format="pdf",
        dimension="alt_text",
        a_path=str(candidate_a),
        b_path=str(candidate_b),
        winner="a",
        judge_id="pdf_alt_text_pairwise",
        judge_version="alt_text_judge_v1",
        a_sha256=hashlib.sha256(b"candidate-a").hexdigest(),
        b_sha256=hashlib.sha256(b"candidate-b").hexdigest(),
        **_external_judge_metadata(),
    )

    errors = judge_comparison_binding_errors(records, [row, row])

    assert "judge comparison row 2 pdf/alt_text: duplicate judge comparison row" in errors


def test_judge_comparison_binding_errors_require_model_metadata_and_separation(tmp_path) -> None:
    candidate_a = tmp_path / "candidate-a.pdf"
    candidate_b = tmp_path / "candidate-b.pdf"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b.write_bytes(b"candidate-b")
    records = [
        build_annotation_record(
            source_path=tmp_path / "source.pdf",
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
            candidate_seed_model="qwen2.5:14b-cloud",
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
    ]
    rows = [
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path=str(candidate_a),
            b_path=str(candidate_b),
            winner="a",
            judge_id="pdf_alt_text_pairwise",
            judge_version="alt_text_judge_v1",
            a_sha256=hashlib.sha256(b"candidate-a").hexdigest(),
            b_sha256=hashlib.sha256(b"candidate-b").hexdigest(),
        ),
        JudgeComparisonRow(
            format="pdf",
            dimension="alt_text",
            a_path=str(candidate_a),
            b_path=str(candidate_b),
            winner="a",
            judge_id="pdf_alt_text_pairwise_alt",
            judge_version="alt_text_judge_v1",
            a_sha256=hashlib.sha256(b"candidate-a").hexdigest(),
            b_sha256=hashlib.sha256(b"candidate-b").hexdigest(),
            judge_model="qwen2.5:7b",
            artifact_generator_model="qwen2.5:14b-cloud",
        ),
    ]

    errors = judge_comparison_binding_errors(records, rows)

    assert "judge comparison row 1 pdf/alt_text: missing judge_model" in errors
    assert (
        "judge comparison row 2 pdf/alt_text: judge_model family must differ "
        "from artifact generator model 'qwen2.5:14b-cloud'"
    ) in errors


def test_calibration_cli_rejects_unbound_pairwise_comparison_rows(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    candidate_a = tmp_path / "candidate-a.pdf"
    candidate_b = tmp_path / "candidate-b.pdf"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b.write_bytes(b"candidate-b")
    record = build_annotation_record(
        source_path=tmp_path / "source.pdf",
        fmt="pdf",
        doc_id="pdf-a",
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
    write_annotation_record(record, root=root)
    judge_comparisons = tmp_path / "judge_comparisons.jsonl"
    judge_comparisons.write_text(
        json.dumps(
            {
                "format": "pdf",
                "dimension": "alt_text",
                "a_path": str(candidate_a),
                "b_path": str(candidate_b),
                "winner": "A_better",
                "judge_id": "pdf_alt_text_pairwise",
                "judge_version": "alt_text_judge_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-comparisons",
            str(judge_comparisons),
            "--store",
            str(store_path),
            "--dry-run",
            "--json",
        ]
    )

    assert result == 2


def test_calibration_cli_writes_structured_drift_alert_log(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    alert_log = tmp_path / "drift_alerts.jsonl"
    source_a = tmp_path / "a.pdf"
    source_b = tmp_path / "b.pdf"
    source_a.write_bytes(b"%PDF-1.4\n%%EOF")
    source_b.write_bytes(b"%PDF-1.4\n%%EOF")

    write_annotation_record(
        build_annotation_record(
            source_path=source_a,
            fmt="pdf",
            doc_id="pdf-a",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.9},
        ),
        root=root,
    )
    write_annotation_record(
        build_annotation_record(
            source_path=source_b,
            fmt="pdf",
            doc_id="pdf-b",
            document_class="paper",
            annotator="specialist_a",
            applicable_dimensions=["alt_text"],
            scores={"alt_text": 0.2},
        ),
        root=root,
    )
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "doc_id": "pdf-a",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_a),
                    **_external_judge_metadata(),
                },
                {
                    "doc_id": "pdf-b",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_b),
                    **_external_judge_metadata(),
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(judge_results),
            "--store",
            str(store_path),
            "--alert-log",
            str(alert_log),
            "--dry-run",
            "--json",
        ]
    )

    assert result == 0
    rows = [json.loads(line) for line in alert_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "quality_judge_drift"
    assert rows[0]["cohens_kappa"] == 0.0


def test_calibration_cli_can_emit_rolling_window_drift_alert(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"
    alert_log = tmp_path / "drift_alerts.jsonl"
    source_a = tmp_path / "a.pdf"
    source_b = tmp_path / "b.pdf"
    source_a.write_bytes(b"%PDF-1.4\n%%EOF")
    source_b.write_bytes(b"%PDF-1.4\n%%EOF")
    store = ExperimentStore(store_path)
    store.record_judge_calibration(
        judge_id="pdf_alt_text_quality",
        judge_version="alt_text_judge_v1",
        format="pdf",
        dimension="alt_text",
        cohens_kappa=1.0,
        sample_size=2,
        measured_at="2026-05-07T00:00:00+00:00",
    )
    for doc_id, source, score in (
        ("pdf-a", source_a, 0.9),
        ("pdf-b", source_b, 0.2),
    ):
        write_annotation_record(
            build_annotation_record(
                source_path=source,
                fmt="pdf",
                doc_id=doc_id,
                document_class="paper",
                annotator="specialist_a",
                applicable_dimensions=["alt_text"],
                scores={"alt_text": score},
            ),
            root=root,
        )
    judge_results = tmp_path / "judge_results.jsonl"
    judge_results.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "doc_id": "pdf-a",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_a),
                    **_external_judge_metadata(),
                },
                {
                    "doc_id": "pdf-b",
                    "format": "pdf",
                    "dimension": "alt_text",
                    "score": 0.9,
                    "judge_id": "pdf_alt_text_quality",
                    "judge_version": "alt_text_judge_v1",
                    **_source_binding(source_b),
                    **_external_judge_metadata(),
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "calibrate",
            "--root",
            str(root),
            "--judge-results",
            str(judge_results),
            "--store",
            str(store_path),
            "--rolling-window",
            "2",
            "--alert-log",
            str(alert_log),
            "--dry-run",
            "--json",
        ]
    )

    assert result == 0
    rows = [json.loads(line) for line in alert_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["cohens_kappa"] == 0.5
    assert rows[0]["rolling_window"] == 2
    assert rows[0]["window_measurements"] == 2


def test_calibration_cli_rejects_invalid_threshold_arguments(tmp_path) -> None:
    root = tmp_path / "corpus" / "v1"
    store_path = tmp_path / "quality_experiments.db"

    assert main(
        [
            "calibrate",
            "--root",
            str(root),
            "--store",
            str(store_path),
            "--score-threshold",
            "nan",
            "--json",
        ]
    ) == 2
    assert main(
        [
            "calibrate",
            "--root",
            str(root),
            "--store",
            str(store_path),
            "--kappa-threshold",
            "1.5",
            "--json",
        ]
    ) == 2
    assert main(
        [
            "calibrate",
            "--root",
            str(root),
            "--store",
            str(store_path),
            "--min-samples",
            "0",
            "--json",
        ]
    ) == 2
    assert main(
        [
            "calibrate",
            "--root",
            str(root),
            "--store",
            str(store_path),
            "--rolling-window",
            "0",
            "--json",
        ]
    ) == 2
