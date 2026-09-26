from __future__ import annotations

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityResult,
)
from project_remedy.quality_judges.shared.ensemble import apply_behavioral_precedence


def test_failing_behavioral_proxy_overrides_passing_judge_dimension() -> None:
    result = QualityResult(
        format="pdf",
        dimensions={
            "alt_text": QualityDimensionScore("alt_text", "pdf", 1.0),
        },
        behavioral={
            "alt_text_substitution": BehavioralTestResult(
                test_name="alt_text_substitution",
                dimension="alt_text",
                format="pdf",
                passed=False,
                score=0.0,
                threshold=0.8,
                metadata={"applicable": True},
            )
        },
        overall_pass=True,
        failing_dimensions=[],
    )

    updated = apply_behavioral_precedence(result)

    assert updated.overall_pass is False
    assert updated.failing_dimensions == ["alt_text"]


def test_passing_behavioral_proxy_overrides_failing_judge_dimension() -> None:
    result = QualityResult(
        format="pdf",
        dimensions={
            "heading_semantics": QualityDimensionScore("heading_semantics", "pdf", 0.5),
        },
        behavioral={
            "heading_navigation": BehavioralTestResult(
                test_name="heading_navigation",
                dimension="heading_semantics",
                format="pdf",
                passed=True,
                score=1.0,
                threshold=0.85,
                metadata={"applicable": True},
            )
        },
        overall_pass=False,
        failing_dimensions=["heading_semantics"],
    )

    updated = apply_behavioral_precedence(result)

    assert updated.overall_pass is True
    assert updated.failing_dimensions == []


def test_behavioral_precedence_ignores_advisory_and_inapplicable_tests() -> None:
    result = QualityResult(
        format="pdf",
        dimensions={
            "reading_order": QualityDimensionScore("reading_order", "pdf", 1.0),
            "decorative": QualityDimensionScore("decorative", "pdf", 1.0),
        },
        behavioral={
            "screen_reader_transcript_analysis": BehavioralTestResult(
                test_name="screen_reader_transcript_analysis",
                dimension="reading_order",
                format="pdf",
                passed=False,
                metadata={"advisory_only": True},
            ),
            "decorative_skip": BehavioralTestResult(
                test_name="decorative_skip",
                dimension="decorative",
                format="pdf",
                passed=False,
                metadata={"applicable": False},
            ),
        },
        overall_pass=True,
        failing_dimensions=[],
    )

    updated = apply_behavioral_precedence(result)

    assert updated.overall_pass is True
    assert updated.failing_dimensions == []


def test_quality_result_rejects_mismatched_dimension_key() -> None:
    try:
        QualityResult(
            format="pdf",
            dimensions={
                "reading_order": QualityDimensionScore("alt_text", "pdf", 1.0),
            },
        )
    except ValueError as exc:
        assert (
            "quality result dimension key 'reading_order' must match score "
            "dimension 'alt_text'"
        ) in str(exc)
    else:
        raise AssertionError("mismatched dimension key should be rejected")


def test_quality_result_rejects_mismatched_dimension_format() -> None:
    try:
        QualityResult(
            format="pdf",
            dimensions={
                "alt_text": QualityDimensionScore("alt_text", "docx", 1.0),
            },
        )
    except ValueError as exc:
        assert "must match result format 'pdf'" in str(exc)
    else:
        raise AssertionError("mismatched dimension format should be rejected")


def test_quality_result_rejects_mismatched_behavioral_key_and_format() -> None:
    try:
        QualityResult(
            format="pdf",
            behavioral={
                "wrong_key": BehavioralTestResult(
                    test_name="alt_text_substitution",
                    dimension="alt_text",
                    format="pdf",
                    passed=True,
                ),
            },
        )
    except ValueError as exc:
        assert (
            "quality result behavioral key 'wrong_key' must match test name "
            "'alt_text_substitution'"
        ) in str(exc)
    else:
        raise AssertionError("mismatched behavioral key should be rejected")

    try:
        QualityResult(
            format="pdf",
            behavioral={
                "alt_text_substitution": BehavioralTestResult(
                    test_name="alt_text_substitution",
                    dimension="alt_text",
                    format="docx",
                    passed=True,
                ),
            },
        )
    except ValueError as exc:
        assert "must match result format 'pdf'" in str(exc)
    else:
        raise AssertionError("mismatched behavioral format should be rejected")


def test_quality_result_rejects_invalid_status_dimensions() -> None:
    try:
        QualityResult(
            format="xlsx",
            failing_dimensions=["reading_order"],
        )
    except ValueError as exc:
        assert "failing dimension 'reading_order' is not applicable to xlsx" in str(exc)
    else:
        raise AssertionError("inapplicable failing dimension should be rejected")

    try:
        QualityResult(
            format="pdf",
            not_applicable_dimensions=["alt_text"],
        )
    except ValueError as exc:
        assert "not_applicable dimension 'alt_text' applies to pdf" in str(exc)
    else:
        raise AssertionError("applicable n/a dimension should be rejected")

    try:
        QualityResult(
            format="pdf",
            not_applicable_dimensions=["not_a_dimension"],
        )
    except ValueError as exc:
        assert "unknown not_applicable dimension: not_a_dimension" in str(exc)
    else:
        raise AssertionError("unknown n/a dimension should be rejected")

    try:
        QualityResult(
            format="pdf",
            failing_dimensions=["alt_text", "alt_text"],
        )
    except ValueError as exc:
        assert "duplicate failing dimension: alt_text" in str(exc)
    else:
        raise AssertionError("duplicate failing dimensions should be rejected")


def test_quality_result_rejects_invalid_container_shapes() -> None:
    try:
        QualityResult(format="pdf", overall_pass="yes")
    except ValueError as exc:
        assert "overall_pass must be a boolean" in str(exc)
    else:
        raise AssertionError("non-boolean overall_pass should be rejected")

    try:
        QualityResult(format="pdf", not_applicable_dimensions="slide_title")
    except ValueError as exc:
        assert "not_applicable_dimensions must be a list" in str(exc)
    else:
        raise AssertionError("non-list not_applicable_dimensions should be rejected")


def test_quality_result_rejects_malformed_nested_result_objects() -> None:
    invalid_cases = [
        (
            {"dimensions": {"": QualityDimensionScore("alt_text", "pdf", 1.0)}},
            "dimensions keys must be non-empty strings",
        ),
        (
            {"dimensions": {"alt_text": {"dimension": "alt_text"}}},
            "dimensions values must be QualityDimensionScore objects",
        ),
        (
            {
                "behavioral": {
                    "": BehavioralTestResult(
                        test_name="alt_text_substitution",
                        dimension="alt_text",
                        format="pdf",
                        passed=True,
                    )
                }
            },
            "behavioral keys must be non-empty strings",
        ),
        (
            {"behavioral": {"alt_text_substitution": {"passed": True}}},
            "behavioral values must be BehavioralTestResult objects",
        ),
    ]

    for kwargs, message in invalid_cases:
        try:
            QualityResult(format="pdf", **kwargs)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"malformed nested result should fail: {kwargs}")
