from __future__ import annotations

from project_remedy.vision_planner.quality_evaluation import (
    HoldoutABEvaluation,
    PromotionDecision,
    deterministic_corpus_split,
    evaluate_controlled_ab_success,
    evaluate_holdout_ab,
    evaluate_strategy_promotion,
)

DOC_1_SHA = "a" * 64
DOC_2_SHA = "b" * 64
DOC_3_SHA = "c" * 64


def _doc_sha(index: int) -> str:
    return f"{index:064x}"


def test_deterministic_corpus_split_is_stable_and_disjoint() -> None:
    records = [
        {
            "doc_id": f"doc-{index}",
            "format": "pdf",
            "source_sha256": _doc_sha(index + 1),
        }
        for index in range(12)
    ]

    first = deterministic_corpus_split(records, holdout_ratio=0.25, salt="test")
    second = deterministic_corpus_split(records, holdout_ratio=0.25, salt="test")

    assert first == second
    assert first.proposal_set
    assert first.holdout_set
    proposal_ids = {record["doc_id"] for record in first.proposal_set}
    holdout_ids = {record["doc_id"] for record in first.holdout_set}
    assert proposal_ids.isdisjoint(holdout_ids)
    assert proposal_ids | holdout_ids == {record["doc_id"] for record in records}


def test_deterministic_corpus_split_is_keyed_by_source_hash_not_doc_id() -> None:
    first_records = [
        {
            "doc_id": f"doc-{index}",
            "format": "pdf",
            "source_sha256": _doc_sha(index + 1),
        }
        for index in range(12)
    ]
    renamed_records = [
        {
            "doc_id": f"renamed-{index}",
            "format": "pdf",
            "source_sha256": _doc_sha(index + 1),
        }
        for index in range(12)
    ]

    first = deterministic_corpus_split(first_records, holdout_ratio=0.25, salt="test")
    renamed = deterministic_corpus_split(renamed_records, holdout_ratio=0.25, salt="test")

    assert {record["source_sha256"] for record in first.holdout_set} == {
        record["source_sha256"] for record in renamed.holdout_set
    }
    assert {record["source_sha256"] for record in first.proposal_set} == {
        record["source_sha256"] for record in renamed.proposal_set
    }


def test_deterministic_corpus_split_rejects_invalid_holdout_ratio() -> None:
    records = [{"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA}]

    for value, expected in (
        (float("nan"), "holdout_ratio must be finite"),
        (True, "holdout_ratio must be numeric"),
        (0.0, "holdout_ratio must be between 0 and 1"),
        (1.0, "holdout_ratio must be between 0 and 1"),
    ):
        try:
            deterministic_corpus_split(records, holdout_ratio=value)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid holdout ratio should fail")


def test_deterministic_corpus_split_rejects_invalid_salt() -> None:
    records = [{"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA}]

    for value in ("", "   ", True):
        try:
            deterministic_corpus_split(records, salt=value)  # type: ignore[arg-type]
        except ValueError as exc:
            assert "salt must be a non-empty string" in str(exc)
        else:
            raise AssertionError("invalid split salt should fail")


def test_deterministic_corpus_split_rejects_malformed_record_collections() -> None:
    for records in (
        None,
        1,
        "doc-1",
        b"doc-1",
        {"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA},
    ):
        try:
            deterministic_corpus_split(records, holdout_ratio=0.25)  # type: ignore[arg-type]
        except ValueError as exc:
            assert "split records must be an iterable of objects" in str(exc)
        else:
            raise AssertionError("malformed split records collection should fail")


def test_deterministic_corpus_split_requires_enough_records() -> None:
    for records in (
        [],
        [{"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA}],
    ):
        try:
            deterministic_corpus_split(records, holdout_ratio=0.25)
        except ValueError as exc:
            assert "corpus split requires at least two records" in str(exc)
        else:
            raise AssertionError("undersized corpus split should fail")


def test_deterministic_corpus_split_rejects_missing_document_identity() -> None:
    for record in (
        {"source_sha256": DOC_1_SHA},
        {"doc_id": "", "source_sha256": DOC_1_SHA},
        {"document_hash": "", "source_sha256": DOC_1_SHA},
        {"doc_id": 123, "source_sha256": DOC_1_SHA},
    ):
        try:
            deterministic_corpus_split([record], holdout_ratio=0.25)
        except ValueError as exc:
            assert "missing doc_id, document_hash, or source_path" in str(exc)
        else:
            raise AssertionError("missing split identity should fail")


def test_deterministic_corpus_split_rejects_duplicate_document_identity() -> None:
    records = [
        {"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA},
        {"doc_id": " doc-1 ", "format": "pdf", "source_sha256": DOC_2_SHA},
    ]

    try:
        deterministic_corpus_split(records, holdout_ratio=0.25)
    except ValueError as exc:
        assert "duplicate corpus split document: doc-1" in str(exc)
    else:
        raise AssertionError("duplicate split identity should fail")


def test_deterministic_corpus_split_rejects_missing_source_hash() -> None:
    try:
        deterministic_corpus_split(
            [{"doc_id": "doc-1", "format": "pdf"}],
            holdout_ratio=0.25,
        )
    except ValueError as exc:
        assert "split record for doc-1 missing source_sha256" in str(exc)
    else:
        raise AssertionError("missing split source hash should fail")


def test_deterministic_corpus_split_rejects_duplicate_source_hash() -> None:
    records = [
        {"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA},
        {
            "doc_id": "doc-2",
            "format": "pdf",
            "artifact_hashes": {"source_sha256": DOC_1_SHA},
        },
    ]

    try:
        deterministic_corpus_split(records, holdout_ratio=0.25)
    except ValueError as exc:
        assert "duplicate corpus split source artifact: doc-2 and doc-1" in str(exc)
    else:
        raise AssertionError("duplicate split source hash should fail")


def test_deterministic_corpus_split_rejects_conflicting_source_hash_metadata() -> None:
    try:
        deterministic_corpus_split(
            [
                {
                    "doc_id": "doc-1",
                    "format": "pdf",
                    "source_sha256": DOC_1_SHA,
                    "artifact_hashes": {"source_sha256": DOC_2_SHA},
                }
            ],
            holdout_ratio=0.25,
        )
    except ValueError as exc:
        assert (
            "split record for doc-1 source_sha256 conflicts with "
            "artifact_hashes.source_sha256"
        ) in str(exc)
    else:
        raise AssertionError("conflicting split source hash metadata should fail")


def test_deterministic_corpus_split_rejects_malformed_source_hash_metadata() -> None:
    cases = [
        (
            {
                "doc_id": "doc-1",
                "format": "pdf",
                "source_sha256": True,
                "artifact_hashes": {"source_sha256": DOC_1_SHA},
            },
            "split record for doc-1 source_sha256 must be a non-empty string",
        ),
        (
            {
                "doc_id": "doc-1",
                "format": "pdf",
                "source_sha256": DOC_1_SHA,
                "artifact_hashes": [],
            },
            "split record for doc-1 artifact_hashes must be an object",
        ),
        (
            {
                "doc_id": "doc-1",
                "format": "pdf",
                "source_sha256": DOC_1_SHA,
                "artifact_hashes": {"source_sha256": True},
            },
            (
                "split record for doc-1 artifact_hashes.source_sha256 "
                "must be a non-empty string"
            ),
        ),
    ]

    for record, expected in cases:
        try:
            deterministic_corpus_split([record], holdout_ratio=0.25)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed split source hash metadata should fail")


def test_deterministic_corpus_split_rejects_malformed_source_hash() -> None:
    for source_sha256 in ("bad", "A" * 64):
        try:
            deterministic_corpus_split(
                [{"doc_id": "doc-1", "format": "pdf", "source_sha256": source_sha256}],
                holdout_ratio=0.25,
            )
        except ValueError as exc:
            assert "split record for doc-1 source_sha256 must be a sha256 hex digest" in str(exc)
        else:
            raise AssertionError("malformed split source hash should fail")


def test_deterministic_corpus_split_rejects_non_object_records() -> None:
    try:
        deterministic_corpus_split(["doc-1"], holdout_ratio=0.25)  # type: ignore[list-item]
    except ValueError as exc:
        assert "split record 1 must be an object" in str(exc)
    else:
        raise AssertionError("non-object split record should fail")


def test_strategy_promotion_requires_target_lift_without_other_regression() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70, "reading_order": 0.91},
        candidate_scores={"alt_text": 0.76, "reading_order": 0.90},
    )

    assert decision.promoted is True
    assert decision.target_lift == 0.06
    assert decision.regressions == {}


def test_strategy_promotion_rejects_insufficient_lift() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70, "reading_order": 0.91},
        candidate_scores={"alt_text": 0.74, "reading_order": 0.91},
    )

    assert decision.promoted is False
    assert "target lift" in decision.reason


def test_strategy_promotion_rejects_non_target_regression() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70, "reading_order": 0.91},
        candidate_scores={"alt_text": 0.77, "reading_order": 0.88},
    )

    assert decision.promoted is False
    assert decision.regressions == {"reading_order": -0.03}
    assert "regression" in decision.reason


def test_strategy_promotion_rejects_missing_non_target_scores() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70, "reading_order": 0.91},
        candidate_scores={"alt_text": 0.77},
    )

    assert decision.promoted is False
    assert decision.target_lift == 0.07
    assert "reading_order" in decision.reason


def test_strategy_promotion_rejects_extra_candidate_non_target_scores() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70},
        candidate_scores={"alt_text": 0.77, "reading_order": 0.91},
    )

    assert decision.promoted is False
    assert decision.target_lift == 0.07
    assert "missing from baseline" in decision.reason
    assert "reading_order" in decision.reason


def test_strategy_promotion_rejects_target_only_score_maps() -> None:
    decision = evaluate_strategy_promotion(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        baseline_scores={"alt_text": 0.70},
        candidate_scores={"alt_text": 0.77},
    )

    assert decision.promoted is False
    assert decision.target_lift == 0.07
    assert "non-target dimensions missing" in decision.reason


def test_strategy_promotion_rejects_invalid_thresholds() -> None:
    baseline = {"alt_text": 0.70, "reading_order": 0.91}
    candidate = {"alt_text": 0.77, "reading_order": 0.91}

    for kwargs, expected in (
        ({"min_target_lift": float("nan")}, "min_target_lift must be finite"),
        ({"min_target_lift": True}, "min_target_lift must be numeric"),
        (
            {"min_target_lift": 0.01},
            "min_target_lift must be at least 0.05",
        ),
        (
            {"max_other_regression": -0.01},
            "max_other_regression must be between 0 and 1",
        ),
        (
            {"max_other_regression": 0.03},
            "max_other_regression must be at most 0.02",
        ),
    ):
        try:
            evaluate_strategy_promotion(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                baseline_scores=baseline,
                candidate_scores=candidate,
                **kwargs,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid promotion threshold should fail")


def test_strategy_promotion_rejects_malformed_score_maps() -> None:
    malformed_cases = [
        (
            {"alt_text": True},
            {"alt_text": 0.77},
            "baseline scores dimension 'alt_text' score must be numeric",
        ),
        (
            {"alt_text": 0.70},
            {"alt_text": float("nan")},
            "candidate scores dimension 'alt_text' score must be finite",
        ),
        (
            {"alt_text": 0.70},
            {"alt_text": 1.2},
            "candidate scores dimension 'alt_text' score must be between 0.0 and 1.0",
        ),
        (
            {"": 0.70},
            {"alt_text": 0.77},
            "baseline scores dimension name must be non-empty",
        ),
        (
            {123: 0.70},
            {"alt_text": 0.77},
            "baseline scores dimension name must be non-empty",
        ),
        (
            {"alt_text": 0.70, " alt_text ": 0.71},
            {"alt_text": 0.77},
            "baseline scores dimension name must be canonical",
        ),
        (
            {"visual_polish": 0.70},
            {"visual_polish": 0.77},
            "baseline scores dimension 'visual_polish' is unsupported",
        ),
    ]

    for baseline_scores, candidate_scores, expected in malformed_cases:
        try:
            evaluate_strategy_promotion(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                baseline_scores=baseline_scores,
                candidate_scores=candidate_scores,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed promotion score map should fail")


def test_strategy_promotion_rejects_malformed_format_metadata() -> None:
    baseline = {"alt_text": 0.70, "reading_order": 0.91}
    candidate = {"alt_text": 0.77, "reading_order": 0.91}

    for document_format, expected in (
        (True, "document_format must be a non-empty string"),
        (" PDF ", "document_format must be canonical"),
        ("txt", "document_format unsupported format: txt"),
    ):
        try:
            evaluate_strategy_promotion(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                baseline_scores=baseline,
                candidate_scores=candidate,
                document_format=document_format,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed promotion format metadata should fail")


def test_strategy_promotion_rejects_format_inapplicable_dimensions() -> None:
    try:
        evaluate_strategy_promotion(
            strategy_name="improve_sheet_organization_workbook",
            target_dimension="sheet_organization",
            baseline_scores={
                "sheet_organization": 0.70,
                "reading_order": 0.91,
            },
            candidate_scores={
                "sheet_organization": 0.77,
                "reading_order": 0.91,
            },
            document_format="xlsx",
        )
    except ValueError as exc:
        assert (
            "baseline scores dimension 'reading_order' "
            "is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("format-inapplicable promotion dimension should fail")


def test_strategy_promotion_rejects_format_inapplicable_target_dimension() -> None:
    try:
        evaluate_strategy_promotion(
            strategy_name="tighten_reading_order_workbook",
            target_dimension="reading_order",
            baseline_scores={
                "reading_order": 0.70,
                "sheet_organization": 0.91,
            },
            candidate_scores={
                "reading_order": 0.77,
                "sheet_organization": 0.91,
            },
            document_format="xlsx",
        )
    except ValueError as exc:
        assert (
            "target_dimension dimension 'reading_order' "
            "is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("format-inapplicable promotion target should fail")


def test_strategy_promotion_rejects_empty_identifiers() -> None:
    for kwargs, expected in (
        ({"strategy_name": ""}, "strategy_name must be a non-empty string"),
        ({"target_dimension": ""}, "target_dimension must be a non-empty string"),
        (
            {"target_dimension": " alt_text "},
            "target_dimension must be a canonical quality dimension",
        ),
        (
            {"target_dimension": "visual_polish"},
            "target_dimension is not a supported quality dimension: visual_polish",
        ),
    ):
        params = {
            "strategy_name": "improve_alt_text_paper",
            "target_dimension": "alt_text",
            "baseline_scores": {"alt_text": 0.70},
            "candidate_scores": {"alt_text": 0.77},
        }
        params.update(kwargs)
        try:
            evaluate_strategy_promotion(**params)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("empty promotion identifiers should fail")


def test_holdout_ab_evaluation_aggregates_common_holdout_docs() -> None:
    evaluation = evaluate_holdout_ab(
        strategy_name=" improve_alt_text_paper ",
        target_dimension="alt_text",
        holdout_records=[
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            {"doc_id": "doc-2", "source_sha256": DOC_2_SHA},
        ],
        baseline_results=[
            _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70, "reading_order": 0.91}),
            _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.72, "reading_order": 0.89}),
        ],
        candidate_results=[
            _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.78, "reading_order": 0.90}),
            _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.76, "reading_order": 0.89}),
        ],
    )

    assert evaluation.sample_size == 2
    assert evaluation.run_id.startswith("holdout-ab-")
    assert evaluation.strategy_name == "improve_alt_text_paper"
    assert evaluation.decision.strategy_name == "improve_alt_text_paper"
    assert evaluation.evaluated_doc_ids == ["doc-1", "doc-2"]
    assert evaluation.source_hashes == {"doc-1": DOC_1_SHA, "doc-2": DOC_2_SHA}
    assert evaluation.baseline_scores == {"alt_text": 0.71, "reading_order": 0.9}
    assert evaluation.candidate_scores == {"alt_text": 0.77, "reading_order": 0.895}
    assert evaluation.decision.promoted is True
    assert evaluation.decision.target_lift == 0.06


def test_holdout_ab_evaluation_rejects_invalid_run_id() -> None:
    for value in ("", "   ", True):
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                run_id=value,  # type: ignore[arg-type]
                holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
                baseline_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.70, "reading_order": 0.91},
                    ),
                ],
                candidate_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.76, "reading_order": 0.90},
                    ),
                ],
            )
        except ValueError as exc:
            assert "run_id must be a non-empty string" in str(exc)
        else:
            raise AssertionError("invalid holdout run ID should fail")


def test_holdout_ab_evaluation_rejects_non_holdout_result_rows() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
                _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.99}),
            ],
        )
    except ValueError as exc:
        assert "non-holdout" in str(exc)
        assert "doc-2" in str(exc)
    else:
        raise AssertionError("expected holdout contamination rejection")


def test_holdout_ab_evaluation_requires_holdout_records() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[],
            baseline_results=[],
            candidate_results=[],
        )
    except ValueError as exc:
        assert "requires at least one holdout record" in str(exc)
    else:
        raise AssertionError("expected empty holdout rejection")


def test_holdout_ab_evaluation_rejects_non_object_rows() -> None:
    cases = [
        (
            ["doc-1"],
            [_result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70, "reading_order": 0.91})],
            [_result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76, "reading_order": 0.90})],
            "holdout record 1 must be an object",
        ),
        (
            [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            ["doc-1"],
            [_result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76, "reading_order": 0.90})],
            "baseline result 1 must be an object",
        ),
        (
            [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            [_result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70, "reading_order": 0.91})],
            ["doc-1"],
            "candidate result 1 must be an object",
        ),
    ]

    for holdout_records, baseline_results, candidate_results, expected in cases:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=holdout_records,  # type: ignore[arg-type]
                baseline_results=baseline_results,  # type: ignore[arg-type]
                candidate_results=candidate_results,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected non-object holdout A/B row rejection")


def test_holdout_ab_evaluation_rejects_malformed_record_collections() -> None:
    valid_holdout = [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}]
    valid_baseline = [
        _result_row(
            "doc-1",
            DOC_1_SHA,
            {"alt_text": 0.70, "reading_order": 0.91},
        ),
    ]
    valid_candidate = [
        _result_row(
            "doc-1",
            DOC_1_SHA,
            {"alt_text": 0.76, "reading_order": 0.90},
        ),
    ]
    cases = [
        (
            None,
            valid_baseline,
            valid_candidate,
            "holdout_records must be an iterable of objects",
        ),
        (
            1,
            valid_baseline,
            valid_candidate,
            "holdout_records must be an iterable of objects",
        ),
        (
            "doc-1",
            valid_baseline,
            valid_candidate,
            "holdout_records must be an iterable of objects",
        ),
        (
            b"doc-1",
            valid_baseline,
            valid_candidate,
            "holdout_records must be an iterable of objects",
        ),
        (
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            valid_baseline,
            valid_candidate,
            "holdout_records must be an iterable of objects",
        ),
        (
            valid_holdout,
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            valid_candidate,
            "baseline_results must be an iterable of objects",
        ),
        (
            valid_holdout,
            valid_baseline,
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            "candidate_results must be an iterable of objects",
        ),
    ]

    for holdout_records, baseline_results, candidate_results, expected in cases:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=holdout_records,  # type: ignore[arg-type]
                baseline_results=baseline_results,  # type: ignore[arg-type]
                candidate_results=candidate_results,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed holdout A/B record collection should fail")


def test_holdout_ab_evaluation_rejects_result_rows_without_document_id() -> None:
    for baseline_row in (
        {"source_sha256": DOC_1_SHA, "quality_dimensions": {"alt_text": 0.70}},
        {
            "doc_id": True,
            "source_sha256": DOC_1_SHA,
            "quality_dimensions": {"alt_text": 0.70},
        },
    ):
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
                baseline_results=[baseline_row],
                candidate_results=[
                    _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
                ],
            )
        except ValueError as exc:
            assert "baseline result missing doc_id" in str(exc)
        else:
            raise AssertionError("expected result row document ID rejection")


def test_holdout_ab_evaluation_rejects_non_string_holdout_identity() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[{"doc_id": 123, "source_sha256": DOC_1_SHA}],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
            ],
        )
    except ValueError as exc:
        assert "holdout record missing doc_id" in str(exc)
    else:
        raise AssertionError("expected non-string holdout identity rejection")


def test_holdout_ab_evaluation_rejects_duplicate_source_artifacts() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
                {
                    "doc_id": "doc-2",
                    "artifact_hashes": {"source_sha256": DOC_1_SHA},
                },
            ],
            baseline_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
                _result_row(
                    "doc-2",
                    DOC_1_SHA,
                    {"alt_text": 0.72, "reading_order": 0.89},
                ),
            ],
            candidate_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.76, "reading_order": 0.90},
                ),
                _result_row(
                    "doc-2",
                    DOC_1_SHA,
                    {"alt_text": 0.77, "reading_order": 0.89},
                ),
            ],
        )
    except ValueError as exc:
        assert "duplicate holdout source artifact: doc-2 and doc-1" in str(exc)
    else:
        raise AssertionError("expected duplicate holdout source artifact rejection")


def test_holdout_ab_evaluation_rejects_source_hash_mismatch() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {
                    "doc_id": "doc-1",
                    "artifact_hashes": {"source_sha256": "a" * 64},
                }
            ],
            baseline_results=[
                {
                    "doc_id": "doc-1",
                    "source_sha256": "a" * 64,
                    "quality_dimensions": {"alt_text": 0.70},
                },
            ],
            candidate_results=[
                {
                    "doc_id": "doc-1",
                    "source_sha256": "b" * 64,
                    "quality_dimensions": {"alt_text": 0.76},
                },
            ],
        )
    except ValueError as exc:
        assert "candidate result for doc-1 source_sha256 mismatch" in str(exc)
    else:
        raise AssertionError("expected holdout source hash mismatch rejection")


def test_holdout_ab_evaluation_rejects_conflicting_source_hash_metadata() -> None:
    cases = [
        (
            [
                {
                    "doc_id": "doc-1",
                    "source_sha256": DOC_1_SHA,
                    "artifact_hashes": {"source_sha256": DOC_2_SHA},
                }
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.76, "reading_order": 0.90},
                ),
            ],
            "holdout record for doc-1 source_sha256 conflicts with artifact_hashes.source_sha256",
        ),
        (
            [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            [
                {
                    "doc_id": "doc-1",
                    "source_sha256": DOC_1_SHA,
                    "artifact_hashes": {"source_sha256": DOC_2_SHA},
                    "quality_dimensions": {"alt_text": 0.70, "reading_order": 0.91},
                },
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.76, "reading_order": 0.90},
                ),
            ],
            "baseline result for doc-1 source_sha256 conflicts with artifact_hashes.source_sha256",
        ),
    ]

    for holdout_records, baseline_results, candidate_results, expected in cases:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=holdout_records,
                baseline_results=baseline_results,
                candidate_results=candidate_results,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected conflicting source hash metadata rejection")


def test_holdout_ab_evaluation_rejects_malformed_source_hash_metadata() -> None:
    cases = [
        (
            [
                {
                    "doc_id": "doc-1",
                    "source_sha256": True,
                    "artifact_hashes": {"source_sha256": DOC_1_SHA},
                }
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.76, "reading_order": 0.90},
                ),
            ],
            "holdout record for doc-1 source_sha256 must be a non-empty string",
        ),
        (
            [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            [
                {
                    "doc_id": "doc-1",
                    "source_sha256": DOC_1_SHA,
                    "artifact_hashes": [],
                    "quality_dimensions": {"alt_text": 0.70, "reading_order": 0.91},
                },
            ],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.76, "reading_order": 0.90},
                ),
            ],
            "baseline result for doc-1 artifact_hashes must be an object",
        ),
        (
            [{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            [
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
            ],
            [
                {
                    "doc_id": "doc-1",
                    "source_sha256": DOC_1_SHA,
                    "artifact_hashes": {"source_sha256": True},
                    "quality_dimensions": {"alt_text": 0.76, "reading_order": 0.90},
                },
            ],
            (
                "candidate result for doc-1 artifact_hashes.source_sha256 "
                "must be a non-empty string"
            ),
        ),
    ]

    for holdout_records, baseline_results, candidate_results, expected in cases:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=holdout_records,  # type: ignore[arg-type]
                baseline_results=baseline_results,  # type: ignore[arg-type]
                candidate_results=candidate_results,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected malformed source hash metadata rejection")


def test_holdout_ab_evaluation_rejects_out_of_range_dimension_scores() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 1.20}),
            ],
        )
    except ValueError as exc:
        assert "candidate result for doc-1 dimension 'alt_text'" in str(exc)
        assert "between 0.0 and 1.0" in str(exc)
    else:
        raise AssertionError("expected out-of-range score rejection")


def test_holdout_ab_evaluation_rejects_malformed_dimension_names() -> None:
    malformed_results = [
        (
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA, "quality_dimensions": {1: 0.70}},
            "baseline result for doc-1 dimension name must be non-empty",
        ),
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "dimensions": {"alt_text": {"score": 0.70}, " alt_text ": {"score": 0.71}},
            },
            "baseline result for doc-1 dimension name must be canonical",
        ),
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "quality_dimensions": {"visual_polish": 0.70},
            },
            "baseline result for doc-1 dimension 'visual_polish' is unsupported",
        ),
    ]

    for baseline_row, expected in malformed_results:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
                baseline_results=[baseline_row],
                candidate_results=[
                    _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
                ],
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected malformed dimension name rejection")


def test_holdout_ab_evaluation_rejects_format_inapplicable_dimensions() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_sheet_organization_workbook",
            target_dimension="sheet_organization",
            holdout_records=[
                {"doc_id": "sheet-1", "format": "xlsx", "source_sha256": DOC_1_SHA}
            ],
            baseline_results=[
                _result_row(
                    "sheet-1",
                    DOC_1_SHA,
                    {"sheet_organization": 0.70, "reading_order": 0.91},
                ),
            ],
            candidate_results=[
                _result_row(
                    "sheet-1",
                    DOC_1_SHA,
                    {"sheet_organization": 0.77, "alt_text": 0.91},
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "baseline result for sheet-1 dimension 'reading_order' "
            "is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("expected format-inapplicable dimension rejection")


def test_holdout_ab_evaluation_rejects_result_format_mismatch() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "format": "pdf", "source_sha256": DOC_1_SHA}
            ],
            baseline_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                    fmt="xlsx",
                ),
            ],
            candidate_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.77, "reading_order": 0.91},
                ),
            ],
        )
    except ValueError as exc:
        assert "baseline result for doc-1 format 'xlsx' does not match holdout format 'pdf'" in str(exc)
    else:
        raise AssertionError("expected result format mismatch rejection")


def test_holdout_ab_evaluation_rejects_malformed_format_metadata() -> None:
    for holdout_record, expected in (
        (
            {"doc_id": "doc-1", "format": " PDF ", "source_sha256": DOC_1_SHA},
            "holdout record for doc-1 format must be canonical",
        ),
        (
            {"doc_id": "doc-1", "format": "txt", "source_sha256": DOC_1_SHA},
            "holdout record for doc-1 unsupported format: txt",
        ),
        (
            {"doc_id": "doc-1", "format": 123, "source_sha256": DOC_1_SHA},
            "holdout record for doc-1 format must be a non-empty string",
        ),
    ):
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=[holdout_record],
                baseline_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.70, "reading_order": 0.91},
                    ),
                ],
                candidate_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.77, "reading_order": 0.91},
                    ),
                ],
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected malformed format metadata rejection")


def test_holdout_ab_evaluation_rejects_malformed_score_payloads() -> None:
    malformed_results = [
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "quality_dimensions": [],
            },
            "baseline result for doc-1 quality_dimensions must be an object",
        ),
        (
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            "baseline result for doc-1 must include quality_dimensions or dimensions",
        ),
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "quality_dimensions": {},
            },
            "baseline result for doc-1 must include at least one dimension score",
        ),
        (
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA, "dimensions": {}},
            "baseline result for doc-1 must include at least one dimension score",
        ),
        (
            {"doc_id": "doc-1", "source_sha256": DOC_1_SHA, "dimensions": []},
            "baseline result for doc-1 dimensions must be an object",
        ),
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "dimensions": {"alt_text": {}},
            },
            "baseline result for doc-1 dimension 'alt_text' missing score",
        ),
        (
            {
                "doc_id": "doc-1",
                "source_sha256": DOC_1_SHA,
                "dimensions": {"alt_text": "good"},
            },
            "baseline result for doc-1 dimension 'alt_text' must be numeric or an object with score",
        ),
    ]

    for baseline_row, expected in malformed_results:
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
                baseline_results=[baseline_row],
                candidate_results=[
                    _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
                ],
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected malformed score payload rejection")


def test_holdout_ab_evaluation_rejects_non_finite_dimension_scores() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": float("nan")}),
            ],
        )
    except ValueError as exc:
        assert "candidate result for doc-1 dimension 'alt_text'" in str(exc)
        assert "must be finite" in str(exc)
    else:
        raise AssertionError("expected non-finite score rejection")


def test_holdout_ab_evaluation_requires_hash_bound_holdout_records() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[{"doc_id": "doc-1"}],
            baseline_results=[
                {"doc_id": "doc-1", "quality_dimensions": {"alt_text": 0.70}},
            ],
            candidate_results=[
                {"doc_id": "doc-1", "quality_dimensions": {"alt_text": 0.76}},
            ],
        )
    except ValueError as exc:
        assert "holdout record for doc-1 missing source_sha256" in str(exc)
    else:
        raise AssertionError("expected hash-bound holdout rejection")


def test_holdout_ab_evaluation_requires_complete_holdout_rows() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
                {"doc_id": "doc-2", "source_sha256": DOC_2_SHA},
            ],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
                _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.72}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.76}),
            ],
        )
    except ValueError as exc:
        assert "candidate results missing holdout document(s): doc-2" in str(exc)
    else:
        raise AssertionError("expected incomplete holdout row rejection")


def test_holdout_ab_evaluation_rejects_per_doc_missing_target_dimension() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
                {"doc_id": "doc-2", "source_sha256": DOC_2_SHA},
            ],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70, "reading_order": 0.91}),
                _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.72, "reading_order": 0.89}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.78, "reading_order": 0.90}),
                _result_row("doc-2", DOC_2_SHA, {"reading_order": 0.89}),
            ],
        )
    except ValueError as exc:
        assert "candidate result for doc-2 missing target dimension alt_text" in str(exc)
    else:
        raise AssertionError("expected missing per-document target rejection")


def test_holdout_ab_evaluation_rejects_per_doc_missing_non_target_dimensions() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
                {"doc_id": "doc-2", "source_sha256": DOC_2_SHA},
            ],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70, "reading_order": 0.91}),
                _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.72, "reading_order": 0.89}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.78, "reading_order": 0.90}),
                _result_row("doc-2", DOC_2_SHA, {"alt_text": 0.76}),
            ],
        )
    except ValueError as exc:
        assert (
            "candidate result for doc-2 missing non-target dimension(s): "
            "reading_order"
        ) in str(exc)
    else:
        raise AssertionError("expected missing per-document non-target rejection")


def test_holdout_ab_evaluation_rejects_target_only_dimension_evidence() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            ],
            baseline_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.70}),
            ],
            candidate_results=[
                _result_row("doc-1", DOC_1_SHA, {"alt_text": 0.78}),
            ],
        )
    except ValueError as exc:
        assert (
            "baseline result for doc-1 missing non-target dimension evidence"
        ) in str(exc)
    else:
        raise AssertionError("expected target-only dimension evidence rejection")


def test_holdout_ab_evaluation_rejects_per_doc_extra_candidate_dimensions() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
            ],
            baseline_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
            ],
            candidate_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {
                        "alt_text": 0.78,
                        "reading_order": 0.90,
                        "table_structure": 0.88,
                    },
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "candidate result for doc-1 contains non-baseline dimension(s): "
            "table_structure"
        ) in str(exc)
    else:
        raise AssertionError("expected extra per-document candidate dimension rejection")


def test_holdout_ab_evaluation_rejects_inconsistent_cross_doc_dimensions() -> None:
    try:
        evaluate_holdout_ab(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            holdout_records=[
                {"doc_id": "doc-1", "source_sha256": DOC_1_SHA},
                {"doc_id": "doc-2", "source_sha256": DOC_2_SHA},
            ],
            baseline_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.70, "reading_order": 0.91},
                ),
                _result_row(
                    "doc-2",
                    DOC_2_SHA,
                    {"alt_text": 0.72, "table_structure": 0.89},
                ),
            ],
            candidate_results=[
                _result_row(
                    "doc-1",
                    DOC_1_SHA,
                    {"alt_text": 0.78, "reading_order": 0.90},
                ),
                _result_row(
                    "doc-2",
                    DOC_2_SHA,
                    {"alt_text": 0.76, "table_structure": 0.89},
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "holdout evaluation dimension coverage for doc-2 differs "
            "from other holdout documents"
        ) in str(exc)
        assert "missing reading_order" in str(exc)
        assert "extra table_structure" in str(exc)
    else:
        raise AssertionError("expected inconsistent cross-document dimension rejection")


def test_holdout_ab_evaluation_rejects_invalid_promotion_thresholds() -> None:
    for kwargs, expected in (
        ({"min_target_lift": float("nan")}, "min_target_lift must be finite"),
        ({"min_target_lift": 0.01}, "min_target_lift must be at least 0.05"),
        (
            {"max_other_regression": 0.03},
            "max_other_regression must be at most 0.02",
        ),
    ):
        try:
            evaluate_holdout_ab(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                holdout_records=[{"doc_id": "doc-1", "source_sha256": DOC_1_SHA}],
                baseline_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.70, "reading_order": 0.91},
                    ),
                ],
                candidate_results=[
                    _result_row(
                        "doc-1",
                        DOC_1_SHA,
                        {"alt_text": 0.76, "reading_order": 0.90},
                    ),
                ],
                **kwargs,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected invalid holdout threshold rejection")


def test_controlled_ab_success_requires_three_promoted_runs() -> None:
    decision = evaluate_controlled_ab_success(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        evaluations=[
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-1",
                evaluated_doc_ids=["doc-1"],
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-2",
                evaluated_doc_ids=["doc-2"],
            ),
        ],
    )

    assert decision.passed is False
    assert decision.successful_experiments == 2
    assert "2 < required 3" in decision.reason


def test_controlled_ab_success_passes_after_three_promoted_runs() -> None:
    decision = evaluate_controlled_ab_success(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        evaluations=[
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-1",
                evaluated_doc_ids=["doc-1"],
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-2",
                evaluated_doc_ids=["doc-2"],
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-3",
                evaluated_doc_ids=["doc-3"],
            ),
        ],
    )

    assert decision.passed is True
    assert decision.successful_experiments == 3
    assert decision.reason == "controlled A/B success criterion met"


def test_controlled_ab_success_rejects_any_non_target_regression() -> None:
    decision = evaluate_controlled_ab_success(
        strategy_name="improve_alt_text_paper",
        target_dimension="alt_text",
        evaluations=[
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-1",
                evaluated_doc_ids=["doc-1"],
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                run_id="run-2",
                evaluated_doc_ids=["doc-2"],
                regressions={"reading_order": -0.04},
                candidate_scores={"alt_text": 0.76, "reading_order": 0.86},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={"reading_order": -0.04},
                    promoted=False,
                    reason="non-target dimension regression exceeded threshold",
                ),
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-3",
                evaluated_doc_ids=["doc-3"],
            ),
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="run-4",
                evaluated_doc_ids=["doc-4"],
            ),
        ],
    )

    assert decision.passed is False
    assert decision.regressions == {"run_2": {"reading_order": -0.04}}
    assert "regressed" in decision.reason


def test_controlled_ab_success_rejects_mixed_strategy_or_dimension() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            evaluations=[
                _ab_run(
                    "tighten_reading_order_paper",
                    "reading_order",
                    promoted=True,
                    run_id="run-1",
                ),
            ],
        )
    except ValueError as exc:
        assert "strategy mismatch" in str(exc)
    else:
        raise AssertionError("expected mixed strategy rejection")


def test_controlled_ab_success_rejects_invalid_required_experiments() -> None:
    for value, expected in (
        (0, "required_experiments must be a positive integer"),
        (True, "required_experiments must be a positive integer"),
        (1.5, "required_experiments must be a positive integer"),
        (2, "required_experiments must be at least 3"),
    ):
        try:
            evaluate_controlled_ab_success(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                evaluations=[],
                required_experiments=value,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected invalid required experiment count rejection")


def test_controlled_ab_success_rejects_malformed_evaluation_collections() -> None:
    for evaluations in (None, 1, "run-1", b"run-1", {"run-1": object()}):
        try:
            evaluate_controlled_ab_success(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                evaluations=evaluations,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            assert (
                "evaluations must be an iterable of HoldoutABEvaluation"
            ) in str(exc)
        else:
            raise AssertionError("malformed controlled A/B evidence collection should fail")


def test_controlled_ab_success_rejects_malformed_run_evidence() -> None:
    class EqualToAnyReason:
        def __eq__(self, other: object) -> bool:
            return True

    malformed_runs = [
        (
            "not-an-evaluation",
            "evaluation 1 must be a HoldoutABEvaluation",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                run_id="",
            ),
            "evaluation 1 run_id must be a non-empty string",
        ),
        (
            _ab_run(
                "",
                "alt_text",
                promoted=True,
            ),
            "evaluation 1 strategy_name must be a non-empty string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "",
                promoted=True,
            ),
            "evaluation 1 target_dimension must be a non-empty string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                evaluated_doc_ids=[],
            ),
            "evaluation 1 must include evaluated_doc_ids",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                evaluated_doc_ids=["doc-1", "doc-1"],
            ),
            "evaluation 1 evaluated_doc_ids must not contain duplicates",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                source_hashes={},
            ),
            "evaluation 1 source_hashes must be a non-empty object",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                evaluated_doc_ids=["doc-1", "doc-2"],
                source_hashes={"doc-1": DOC_1_SHA},
            ),
            "evaluation 1 source_hashes missing evaluated document(s): doc-2",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                source_hashes={"doc-1": DOC_1_SHA, "doc-2": DOC_2_SHA},
            ),
            "evaluation 1 source_hashes contain non-evaluated document(s): doc-2",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                evaluated_doc_ids=["doc-1", "doc-2"],
                source_hashes={"doc-1": DOC_1_SHA, "doc-2": DOC_1_SHA},
            ),
            "evaluation 1 source_hashes duplicate source artifact: doc-2 and doc-1",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                source_hashes={1: DOC_1_SHA},  # type: ignore[dict-item]
            ),
            "evaluation 1 source_hashes document ID must be non-empty",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                source_hashes={"doc-1": "not-a-hash"},
            ),
            "evaluation 1 source_hashes['doc-1'] source_sha256 must be a sha256 hex digest",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                source_hashes={"doc-1": "A" * 64},
            ),
            "evaluation 1 source_hashes['doc-1'] source_sha256 must be a sha256 hex digest",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                baseline_scores={},
                candidate_scores={"alt_text": 0.76, "reading_order": 0.90},
            ),
            "evaluation 1 baseline scores must include at least one dimension score",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                baseline_scores={"alt_text": 0.70, "reading_order": 0.90},
                candidate_scores={},
            ),
            "evaluation 1 candidate scores must include at least one dimension score",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                baseline_scores={"alt_text": 0.70},
                candidate_scores={"alt_text": 0.76},
            ),
            "evaluation 1 scores must include at least one non-target dimension",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                baseline_scores={"alt_text": 0.70},
                candidate_scores={"alt_text": 0.76, "reading_order": 0.90},
            ),
            "evaluation 1 candidate scores contain non-baseline dimension(s): reading_order",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                baseline_scores={"alt_text": 0.70, "reading_order": 0.90},
                candidate_scores={"alt_text": 0.76},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted=False,
                    reason="non-target dimension missing from candidate evaluation: reading_order",
                ),
            ),
            "evaluation 1 candidate scores missing non-target dimension(s): reading_order",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                baseline_scores={"reading_order": 0.9},
            ),
            "evaluation 1 baseline scores missing target dimension alt_text",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision strategy_name must be a non-empty string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="",
                    target_lift=0.06,
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision target_dimension must be a non-empty string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="other_strategy",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision strategy mismatch",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=float("nan"),
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision target_lift must be finite",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted="yes",  # type: ignore[arg-type]
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision promoted must be a boolean",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted=True,
                    reason=EqualToAnyReason(),  # type: ignore[arg-type]
                ),
            ),
            "evaluation 1 decision reason must be a string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={"reading_order": float("nan")},
                    promoted=False,
                    reason="not promoted",
                ),
            ),
            "evaluation 1 decision regression 'reading_order' must be finite",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                candidate_scores={"alt_text": 0.76, "reading_order": 0.85},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={1: -0.05},  # type: ignore[dict-item]
                    promoted=False,
                    reason="non-target dimension regression exceeded threshold",
                ),
            ),
            "evaluation 1 decision regression dimension name must be a non-empty string",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                candidate_scores={"alt_text": 0.76, "reading_order": 0.85},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={" reading_order ": -0.05},
                    promoted=False,
                    reason="non-target dimension regression exceeded threshold",
                ),
            ),
            "evaluation 1 decision regression dimension name must be canonical",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=False,
                candidate_scores={"alt_text": 0.76, "reading_order": 0.85},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={"visual_polish": -0.05},
                    promoted=False,
                    reason="non-target dimension regression exceeded threshold",
                ),
            ),
            "evaluation 1 decision regression dimension 'visual_polish' is unsupported",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                candidate_scores={"alt_text": 0.72, "reading_order": 0.90},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision target_lift does not match score maps",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                candidate_scores={"alt_text": 0.72, "reading_order": 0.90},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.02,
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision promoted does not match score-derived criteria",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                candidate_scores={"alt_text": 0.76, "reading_order": 0.85},
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={},
                    promoted=True,
                    reason="promotion criteria met",
                ),
            ),
            "evaluation 1 decision regressions do not match score-derived regressions",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                decision=PromotionDecision(
                    strategy_name="improve_alt_text_paper",
                    target_dimension="alt_text",
                    target_lift=0.06,
                    regressions={},
                    promoted=True,
                    reason="manually approved",
                ),
            ),
            "evaluation 1 decision reason does not match score-derived criteria",
        ),
    ]

    for run, expected in malformed_runs:
        try:
            evaluate_controlled_ab_success(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                evaluations=[run],  # type: ignore[list-item]
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed controlled A/B run should fail")


def test_controlled_ab_success_rejects_malformed_run_formats() -> None:
    malformed_runs = [
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={},
            ),
            "evaluation 1 formats must be a non-empty object",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                evaluated_doc_ids=["doc-1", "doc-2"],
                formats={"doc-1": "pdf"},
            ),
            "evaluation 1 formats missing evaluated document(s): doc-2",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={"doc-1": "pdf", "doc-2": "pdf"},
            ),
            "evaluation 1 formats contain non-evaluated document(s): doc-2",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={1: "pdf"},  # type: ignore[dict-item]
            ),
            "evaluation 1 formats document ID must be non-empty",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={" doc-1 ": "pdf", "doc-1": "pdf"},
            ),
            "evaluation 1 formats document IDs must be unique",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={"doc-1": " PDF "},
            ),
            "evaluation 1 formats['doc-1'] must be canonical",
        ),
        (
            _ab_run(
                "improve_alt_text_paper",
                "alt_text",
                promoted=True,
                formats={"doc-1": "txt"},
            ),
            "evaluation 1 formats['doc-1'] unsupported format: txt",
        ),
    ]

    for run, expected in malformed_runs:
        try:
            evaluate_controlled_ab_success(
                strategy_name="improve_alt_text_paper",
                target_dimension="alt_text",
                evaluations=[run],
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("malformed controlled A/B run format should fail")


def test_controlled_ab_success_rejects_format_inapplicable_dimensions() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_sheet_organization_workbook",
            target_dimension="sheet_organization",
            evaluations=[
                _ab_run(
                    "improve_sheet_organization_workbook",
                    "sheet_organization",
                    promoted=True,
                    evaluated_doc_ids=["sheet-1"],
                    source_hashes={"sheet-1": DOC_1_SHA},
                    formats={"sheet-1": "xlsx"},
                    baseline_scores={
                        "sheet_organization": 0.70,
                        "reading_order": 0.90,
                    },
                    candidate_scores={
                        "sheet_organization": 0.76,
                        "reading_order": 0.90,
                    },
                    decision=PromotionDecision(
                        strategy_name="improve_sheet_organization_workbook",
                        target_dimension="sheet_organization",
                        target_lift=0.06,
                        promoted=True,
                        reason="promotion criteria met",
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "evaluation 1 baseline scores dimension 'reading_order' "
            "is not applicable to xlsx"
        ) in str(exc)
    else:
        raise AssertionError("format-inapplicable controlled A/B dimension should fail")


def test_controlled_ab_success_rejects_duplicate_run_ids() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            evaluations=[
                _ab_run("improve_alt_text_paper", "alt_text", promoted=True, run_id="run-1"),
                _ab_run("improve_alt_text_paper", "alt_text", promoted=True, run_id="run-1"),
            ],
        )
    except ValueError as exc:
        assert "duplicate controlled A/B run_id: run-1" in str(exc)
    else:
        raise AssertionError("expected duplicate controlled A/B run ID rejection")


def test_controlled_ab_success_rejects_duplicate_evidence_with_distinct_run_ids() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            evaluations=[
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-1",
                    evaluated_doc_ids=["doc-1"],
                ),
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-2",
                    evaluated_doc_ids=["doc-1"],
                ),
            ],
        )
    except ValueError as exc:
        assert "duplicate controlled A/B evidence: run-2 duplicates run-1" in str(exc)
    else:
        raise AssertionError("expected duplicate controlled A/B evidence rejection")


def test_controlled_ab_success_rejects_reused_source_artifacts_across_runs() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            evaluations=[
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-1",
                    evaluated_doc_ids=["doc-1"],
                ),
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-2",
                    evaluated_doc_ids=["doc-renamed"],
                    source_hashes={"doc-renamed": DOC_1_SHA},
                    candidate_scores={"alt_text": 0.77, "reading_order": 0.90},
                    decision=PromotionDecision(
                        strategy_name="improve_alt_text_paper",
                        target_dimension="alt_text",
                        target_lift=0.07,
                        promoted=True,
                        reason="promotion criteria met",
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "controlled A/B source artifact reused across runs: "
            "run-2 reuses source artifact from run-1"
        ) in str(exc)
    else:
        raise AssertionError("expected reused controlled A/B source artifact rejection")


def test_controlled_ab_success_rejects_reused_document_ids_across_runs() -> None:
    try:
        evaluate_controlled_ab_success(
            strategy_name="improve_alt_text_paper",
            target_dimension="alt_text",
            evaluations=[
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-1",
                    evaluated_doc_ids=["doc-1"],
                ),
                _ab_run(
                    "improve_alt_text_paper",
                    "alt_text",
                    promoted=True,
                    run_id="run-2",
                    evaluated_doc_ids=[" doc-1 "],
                    source_hashes={"doc-1": DOC_2_SHA},
                    candidate_scores={"alt_text": 0.77, "reading_order": 0.90},
                    decision=PromotionDecision(
                        strategy_name="improve_alt_text_paper",
                        target_dimension="alt_text",
                        target_lift=0.07,
                        promoted=True,
                        reason="promotion criteria met",
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert (
            "controlled A/B document reused across runs: "
            "run-2 reuses doc-1 from run-1"
        ) in str(exc)
    else:
        raise AssertionError("expected reused controlled A/B document ID rejection")


def _ab_run(
    strategy_name: str,
    target_dimension: str,
    *,
    promoted: bool,
    run_id: str = "run-1",
    regressions: dict[str, float] | None = None,
    evaluated_doc_ids: list[str] | None = None,
    source_hashes: dict[str, str] | None = None,
    formats: dict[str, str] | None = None,
    baseline_scores: dict[str, float] | None = None,
    candidate_scores: dict[str, float] | None = None,
    decision: PromotionDecision | None = None,
) -> HoldoutABEvaluation:
    doc_ids = evaluated_doc_ids if evaluated_doc_ids is not None else ["doc-1"]
    return HoldoutABEvaluation(
        strategy_name=strategy_name,
        target_dimension=target_dimension,
        run_id=run_id,
        evaluated_doc_ids=doc_ids,
        source_hashes=source_hashes
        if source_hashes is not None
        else _source_hashes_for_doc_ids(doc_ids),
        formats=formats
        if formats is not None
        else _formats_for_doc_ids(doc_ids),
        baseline_scores=baseline_scores
        if baseline_scores is not None
        else {target_dimension: 0.70, "reading_order": 0.90},
        candidate_scores=candidate_scores
        if candidate_scores is not None
        else {target_dimension: 0.76, "reading_order": 0.90},
        decision=decision
        or PromotionDecision(
            strategy_name=strategy_name,
            target_dimension=target_dimension,
            target_lift=0.06,
            regressions=regressions or {},
            promoted=promoted,
            reason="promotion criteria met" if promoted else "not promoted",
        ),
    )


def _formats_for_doc_ids(doc_ids: list[str]) -> dict[str, str]:
    return {doc_id.strip(): "pdf" for doc_id in doc_ids}


def _source_hashes_for_doc_ids(doc_ids: list[str]) -> dict[str, str]:
    default_hashes = {
        "doc-1": DOC_1_SHA,
        "doc-2": DOC_2_SHA,
        "doc-3": DOC_3_SHA,
        "doc-4": "d" * 64,
    }
    return {
        doc_id: default_hashes.get(doc_id, f"{index + 16:064x}")
        for index, doc_id in enumerate(doc_ids)
    }


def _result_row(
    doc_id: str,
    source_sha256: str,
    quality_dimensions: dict[str, float],
    *,
    fmt: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "doc_id": doc_id,
        "source_sha256": source_sha256,
        "quality_dimensions": quality_dimensions,
    }
    if fmt is not None:
        row["format"] = fmt
    return row
