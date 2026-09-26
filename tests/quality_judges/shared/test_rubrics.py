from __future__ import annotations

from pathlib import Path
import subprocess

from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)
from project_remedy.quality_judges.shared.rubric_loader import (
    RUBRICS_DIR,
    criterion_ids_for_dimension,
    load_all_rubrics,
    load_rubric,
)
from project_remedy.quality_judges.shared.base import QualityDimensionScore


def test_shared_rubrics_cover_every_quality_dimension() -> None:
    rubrics = load_all_rubrics()

    assert set(rubrics) == set(ALL_QUALITY_DIMENSIONS)
    for dimension, rubric in rubrics.items():
        assert rubric.dimension == dimension
        assert rubric.version == "rubric_v1"
        assert rubric.criteria
        assert all(criterion.id for criterion in rubric.criteria)
        assert all(criterion.scale in {"0-1", "1-5"} for criterion in rubric.criteria)
        assert all(criterion.description for criterion in rubric.criteria)


def test_shared_rubric_applicability_matches_dimension_matrix() -> None:
    expected_by_dimension = {
        dimension: {
            fmt
            for fmt, dimensions in DIMENSIONS_BY_FORMAT.items()
            if dimension in dimensions
        }
        for dimension in ALL_QUALITY_DIMENSIONS
    }

    for dimension, expected_formats in expected_by_dimension.items():
        rubric = load_rubric(dimension)
        assert set(rubric.applies_to) == expected_formats


def test_shared_rubric_files_are_version_controlled_artifacts() -> None:
    repo_root = Path(__file__).parents[3]
    rubric_files = sorted(RUBRICS_DIR.glob("*.yaml"))

    assert {path.stem for path in rubric_files} == set(ALL_QUALITY_DIMENSIONS)
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            *[str(path.relative_to(repo_root)) for path in rubric_files],
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_behavioral_test_names_map_to_quality_dimensions() -> None:
    assert dimension_from_behavioral_test("alt_text_substitution") == "alt_text"
    assert dimension_from_behavioral_test("slide_reading_order_comprehension") == "reading_order"
    assert dimension_from_behavioral_test("screen_reader_transcript_analysis") == "reading_order"
    assert dimension_from_behavioral_test("heading_navigation") == "heading_semantics"
    assert dimension_from_behavioral_test("table_cell_lookup") == "table_structure"
    assert dimension_from_behavioral_test("decorative_skip") == "decorative"
    assert dimension_from_behavioral_test("slide_title_navigation") == "slide_title"
    assert dimension_from_behavioral_test("sheet_navigation") == "sheet_organization"


def test_quality_dimension_score_rejects_criteria_missing_from_rubric() -> None:
    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            per_criterion={"not_in_rubric": 0.9},
        )
    except ValueError as exc:
        assert "not present in the versioned rubric" in str(exc)
    else:
        raise AssertionError("unknown per-criterion key should be rejected")


def test_quality_dimension_score_rejects_invalid_score_ranges() -> None:
    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=1.01,
        )
    except ValueError as exc:
        assert "score must be between 0 and 1" in str(exc)
    else:
        raise AssertionError("invalid score should be rejected")

    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            confidence=-0.1,
        )
    except ValueError as exc:
        assert "confidence must be between 0 and 1" in str(exc)
    else:
        raise AssertionError("invalid confidence should be rejected")

    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=float("nan"),
        )
    except ValueError as exc:
        assert "score must be finite" in str(exc)
    else:
        raise AssertionError("non-finite score should be rejected")

    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            variance=float("nan"),
        )
    except ValueError as exc:
        assert "variance must be finite" in str(exc)
    else:
        raise AssertionError("non-finite variance should be rejected")


def test_quality_dimension_score_rejects_invalid_per_criterion_values() -> None:
    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="pdf",
            score=0.9,
            per_criterion={"substitutive_alt_text": float("nan")},
        )
    except ValueError as exc:
        assert "per_criterion.substitutive_alt_text must be finite" in str(exc)
    else:
        raise AssertionError("non-finite criterion score should be rejected")


def test_quality_dimension_score_rejects_malformed_structured_fields() -> None:
    invalid_cases = [
        (
            {"per_criterion": [("substitutive_alt_text", 0.9)]},
            "per_criterion must be an object",
        ),
        (
            {"per_criterion": {"": 0.9}},
            "per_criterion keys must be non-empty strings",
        ),
        (
            {"judge_versions": "alt_text_judge_v1"},
            "judge_versions must be a list",
        ),
        (
            {"judge_versions": ["alt_text_judge_v1", ""]},
            "judge_versions entries must be non-empty strings",
        ),
        (
            {"sample_findings": {"issue": "missing_alt"}},
            "sample_findings must be a list",
        ),
        (
            {"sample_findings": ["missing_alt"]},
            "sample_findings entries must be objects",
        ),
    ]

    for kwargs, message in invalid_cases:
        try:
            QualityDimensionScore(
                dimension="alt_text",
                format="pdf",
                score=0.9,
                **kwargs,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"malformed structured field should fail: {kwargs}")


def test_quality_dimension_score_rejects_inapplicable_format_dimension() -> None:
    try:
        QualityDimensionScore(
            dimension="reading_order",
            format="xlsx",
            score=0.9,
        )
    except ValueError as exc:
        assert "quality score dimension 'reading_order' is not applicable to xlsx" in str(exc)
    else:
        raise AssertionError("inapplicable score dimension should be rejected")

    try:
        QualityDimensionScore(
            dimension="alt_text",
            format="txt",
            score=0.9,
        )
    except ValueError as exc:
        assert "unsupported quality score format: txt" in str(exc)
    else:
        raise AssertionError("unsupported score format should be rejected")


def test_current_proxy_criterion_ids_are_backed_by_rubrics() -> None:
    required = {
        "alt_text": {
            "substitutive_alt_text",
            "ooxml_alt_text_presence",
            "ooxml_alt_text_specificity",
            "xlsx_drawing_alt_text_parser_coverage",
            "drawing_alt_text_presence",
            "drawing_alt_text_specificity",
            "deterministic_rule_coverage",
        },
        "reading_order": {
            "transcript_comprehension_proxy",
            "linear_document_order_proxy",
            "shape_order_title_first",
            "shape_order_visual_sequence",
            "deterministic_rule_coverage",
        },
        "heading_semantics": {
            "outline_navigation",
            "heading_label_descriptiveness",
            "heading_label_uniqueness",
            "visual_heading_semantics",
            "slide_title_navigation",
            "slide_title_presence",
            "slide_title_descriptiveness",
            "slide_title_uniqueness",
            "deterministic_rule_coverage",
        },
        "table_structure": {
            "cell_lookup_structure",
            "repeated_header_rows",
            "non_empty_header_cells",
            "pptx_table_shape_parser_coverage",
            "pptx_table_header_row_presence",
            "table_header_cells_present",
            "excel_table_presence",
            "header_row_presence",
            "banded_rows",
            "total_row_presence",
            "deterministic_rule_coverage",
        },
        "link_text": {
            "descriptive_link_text",
            "link_text_parser_coverage",
            "deterministic_rule_coverage",
        },
        "decorative": {
            "safe_decorative_skips",
            "decorative_flag_parser_coverage",
            "decorative_skip_semantics",
            "deterministic_rule_coverage",
        },
        "complex_content": {
            "data_level_description",
            "complex_object_parser_coverage",
            "formula_context",
            "equation_context",
            "deterministic_rule_coverage",
        },
        "sheet_organization": {
            "sheet_name_descriptiveness",
            "sheet_purpose_alignment",
            "visible_data_sheets",
            "deterministic_rule_coverage",
        },
        "slide_title": {
            "slide_title_quality",
            "slide_title_presence",
            "slide_title_descriptiveness",
            "slide_title_uniqueness",
            "deterministic_rule_coverage",
        },
    }

    for dimension, criterion_ids in required.items():
        assert criterion_ids <= criterion_ids_for_dimension(dimension)
