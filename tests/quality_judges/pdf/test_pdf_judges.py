from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from project_remedy.quality_judges.pdf.audit import audit_pdf_quality
from project_remedy.behavioral_proxies.shared.base import BehavioralModelSeparationError
from project_remedy.quality_judges.pdf import (
    PDFAltTextQualityJudge,
    PDFComplexContentJudge,
    PDFDecorativeJudge,
    PDFHeadingSemanticsJudge,
    PDFLinkTextJudge,
    PDFReadingOrderJudge,
    PDFTableStructureJudge,
)
from project_remedy.quality_judges.shared.base import (
    ModelSeparationError,
    QualityJudgeConfig,
)
from project_remedy.quality_judges.shared.ensemble import QualityJudgeEnsemble
from project_remedy.tag_tree_reader import TagNode, TagTreeReport


def _config() -> QualityJudgeConfig:
    return QualityJudgeConfig(
        backend="ollama",
        model="llama3.1:8b",
        production_models=("gemma4:31b-cloud",),
    )


def _pipeline_config() -> SimpleNamespace:
    return SimpleNamespace(
        api=SimpleNamespace(
            text_model="gemma4:31b-cloud",
            vision_model="gemma4-vision:27b",
            escalation_model="",
            quality_judge_backend="ollama",
            quality_judge_model="llama3.1:8b",
            quality_judge_base_url="",
            behavioral_test_backend="ollama",
            behavioral_test_model="qwen2.5:7b",
            behavioral_test_cache_path="",
        )
    )


def _node(
    tag: str,
    *,
    depth: int = 1,
    text: str = "",
    alt_text: str = "",
    page: int = 0,
) -> TagNode:
    return TagNode(
        tag=tag,
        depth=depth,
        page=page,
        text=text,
        alt_text=alt_text,
        lang="",
        children_count=0,
        has_content=True,
    )


def _good_report() -> TagTreeReport:
    paragraph = (
        "The report explains the enrollment trend over five years. "
        "It also identifies the largest accessibility risks for students."
    )
    return TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("H1", text="Accessibility Report"),
            _node("P", text=paragraph),
            _node("Figure", alt_text="Line chart showing revenue growth across 4 quarters"),
            _node("Link", text="Download the full accessibility report"),
            _node("Table", depth=1),
            _node("TR", depth=2),
            _node("TH", depth=3, text="Quarter"),
            _node("TD", depth=3, text="Q1"),
            _node("Formula", text="Equation y = 2x + 5 shows the projected trend."),
        ],
    )


def _bad_alt_report() -> TagTreeReport:
    return TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[_node("Figure", alt_text="image")],
    )


def test_pdf_judges_return_dimension_scores_for_good_report() -> None:
    judges = [
        PDFAltTextQualityJudge(_config()),
        PDFReadingOrderJudge(_config()),
        PDFHeadingSemanticsJudge(_config()),
        PDFTableStructureJudge(_config()),
        PDFLinkTextJudge(_config()),
        PDFDecorativeJudge(_config()),
        PDFComplexContentJudge(_config()),
    ]
    report = _good_report()

    scores = [
        judge.judge(Path("unused.pdf"), tag_tree_report=report)
        for judge in judges
    ]

    assert {score.dimension for score in scores} == {
        "alt_text",
        "reading_order",
        "heading_semantics",
        "table_structure",
        "link_text",
        "decorative",
        "complex_content",
    }
    assert all(score.format == "pdf" for score in scores)
    assert all(score.score >= 0.8 for score in scores)
    assert all(score.judge_versions for score in scores)


def test_pdf_judge_instantiation_enforces_model_separation() -> None:
    bad_config = QualityJudgeConfig(
        backend="ollama",
        model="gemma4:9b",
        production_models=("gemma4:31b-cloud",),
    )

    with pytest.raises(ModelSeparationError):
        PDFAltTextQualityJudge(bad_config)


def test_pdf_judge_pairwise_compare_uses_separate_reports() -> None:
    result = PDFAltTextQualityJudge(_config()).compare(
        Path("a.pdf"),
        Path("b.pdf"),
        tag_tree_report_a=_good_report(),
        tag_tree_report_b=_bad_alt_report(),
    )

    assert result == "A_better"


def test_pdf_link_text_judge_flags_raw_urls_and_generic_text() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("Link", text="https://example.com/report"),
            _node("Link", text="www.example.com/report"),
            _node("Link", text="example.com/report"),
            _node("Link", text="click here"),
            _node("Link", text="Quarterly revenue report"),
        ],
    )

    score = PDFLinkTextJudge(_config()).judge(Path("fixture.pdf"), tag_tree_report=report)

    assert score.score == 0.2
    assert [finding["text"] for finding in score.sample_findings] == [
        "https://example.com/report",
        "www.example.com/report",
        "example.com/report",
        "click here",
    ]


def test_pdf_complex_content_judge_ignores_simple_figures() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("Figure", alt_text="Company logo"),
            _node("Image", alt_text="Author headshot"),
        ],
    )

    score = PDFComplexContentJudge(_config()).judge(
        Path("fixture.pdf"),
        tag_tree_report=report,
    )

    assert score.score == 1.0
    assert score.sample_findings == []


def test_pdf_complex_content_judge_scores_chart_descriptions() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("Figure", alt_text="Revenue chart"),
            _node(
                "Image",
                alt_text="Flowchart showing intake request through review to final approval",
            ),
        ],
    )

    score = PDFComplexContentJudge(_config()).judge(
        Path("fixture.pdf"),
        tag_tree_report=report,
    )

    assert score.score == 0.5
    assert score.sample_findings == [
        {
            "severity": "warning",
            "issue": "thin_complex_content_description",
            "content_index": 1,
            "page": 0,
            "description": "Revenue chart",
        }
    ]


def test_pdf_table_structure_judge_requires_non_empty_header_cells() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("Table", depth=1),
            _node("TR", depth=2),
            _node("TH", depth=3, text=""),
            _node("TD", depth=3, text="Q1"),
        ],
    )

    score = PDFTableStructureJudge(_config()).judge(
        Path("fixture.pdf"),
        tag_tree_report=report,
    )

    assert score.score == 0.0
    assert score.sample_findings[0]["has_headers"] is True
    assert score.sample_findings[0]["has_non_empty_headers"] is False


def test_pdf_decorative_judge_treats_whitespace_alt_as_empty() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node(
                "Figure",
                text="This chart contains data but has whitespace alt text.",
                alt_text="   ",
            ),
        ],
    )

    score = PDFDecorativeJudge(_config()).judge(
        Path("fixture.pdf"),
        tag_tree_report=report,
    )

    assert score.score == 0.0
    assert score.sample_findings[0]["issue"] == "informative_figure_skipped"


def test_pdf_heading_semantics_judge_scores_generic_and_duplicate_headings() -> None:
    report = TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=True,
        nodes=[
            _node("H1", text="Section"),
            _node("H2", text="Findings"),
            _node("H2", text="Findings"),
        ],
    )

    score = PDFHeadingSemanticsJudge(_config()).judge(
        Path("fixture.pdf"),
        tag_tree_report=report,
    )

    assert score.score == 0.0
    assert score.per_criterion["heading_label_descriptiveness"] == pytest.approx(
        2 / 3,
        abs=0.0001,
    )
    assert score.per_criterion["heading_label_uniqueness"] == pytest.approx(
        1 / 3,
        abs=0.0001,
    )
    assert [finding["issue"] for finding in score.sample_findings] == [
        "non_descriptive_heading",
        "duplicate_heading",
        "duplicate_heading",
    ]


def test_pdf_judge_prompts_are_version_controlled_files() -> None:
    prompt_dir = Path("src/project_remedy/quality_judges/pdf/prompts")
    judges = [
        PDFAltTextQualityJudge,
        PDFReadingOrderJudge,
        PDFHeadingSemanticsJudge,
        PDFTableStructureJudge,
        PDFLinkTextJudge,
        PDFDecorativeJudge,
        PDFComplexContentJudge,
    ]

    for judge_cls in judges:
        assert (prompt_dir / judge_cls.prompt_name).exists()


def test_quality_judge_ensemble_aggregates_by_dimension() -> None:
    result = QualityJudgeEnsemble(
        [
            PDFAltTextQualityJudge(_config()),
            PDFHeadingSemanticsJudge(_config()),
        ],
        thresholds={"alt_text": 0.8, "heading_semantics": 0.8},
    ).judge(Path("unused.pdf"), tag_tree_report=_good_report())

    assert result.format == "pdf"
    assert result.overall_pass is True
    assert sorted(result.dimensions) == ["alt_text", "heading_semantics"]
    assert result.failing_dimensions == []
    assert result.not_applicable_dimensions == ["sheet_organization", "slide_title"]


def test_quality_judge_ensemble_rejects_invalid_thresholds() -> None:
    for thresholds, expected in (
        ({"alt_text": True}, "thresholds.alt_text must be numeric"),
        ({"alt_text": float("nan")}, "thresholds.alt_text must be finite"),
        ({"alt_text": 1.5}, "thresholds.alt_text must be between 0 and 1"),
        ({"not_a_dimension": 0.8}, "threshold dimension unsupported: not_a_dimension"),
    ):
        with pytest.raises(ValueError, match=expected):
            QualityJudgeEnsemble([], thresholds=thresholds)


def test_pdf_quality_audit_includes_behavioral_proxy_results() -> None:
    result = audit_pdf_quality(
        Path("unused.pdf"),
        config=_pipeline_config(),
        tag_tree_report=_good_report(),
    )

    assert sorted(result.behavioral) == [
        "alt_text_substitution",
        "decorative_skip",
        "heading_navigation",
        "reading_order_comprehension",
        "screen_reader_transcript_analysis",
        "table_cell_lookup",
    ]
    assert result.behavioral["alt_text_substitution"].dimension == "alt_text"
    assert result.behavioral["table_cell_lookup"].passed is True
    assert (
        result.behavioral["alt_text_substitution"].metadata["behavioral_model"]
        == "qwen2.5:7b"
    )


def test_pdf_quality_audit_enforces_behavioral_model_separation() -> None:
    config = _pipeline_config()
    config.api.behavioral_test_model = "gemma4:9b"

    with pytest.raises(BehavioralModelSeparationError):
        audit_pdf_quality(
            Path("unused.pdf"),
            config=config,
            tag_tree_report=_good_report(),
        )
