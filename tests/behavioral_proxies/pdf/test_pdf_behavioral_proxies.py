from __future__ import annotations

from pathlib import Path

from project_remedy.behavioral_proxies.pdf.alt_text_substitution import (
    PDFAltTextSubstitutionTest,
    score_alt_text_substitution_report,
)
from project_remedy.behavioral_proxies.pdf.decorative_skip_test import (
    PDFDecorativeSkipTest,
    score_decorative_skip_report,
)
from project_remedy.behavioral_proxies.pdf.heading_navigation import (
    PDFHeadingNavigationTest,
    score_heading_navigation_report,
)
from project_remedy.behavioral_proxies.pdf.reading_order_comprehension import (
    PDFReadingOrderComprehensionTest,
    score_reading_order_report,
)
from project_remedy.behavioral_proxies.pdf.table_cell_lookup import (
    PDFTableCellLookupTest,
    score_table_cell_lookup_report,
)
from project_remedy.behavioral_proxies.pdf.transcript_analyzer import (
    PDFTranscriptAnalyzer,
    analyze_tag_tree_report,
)
from project_remedy.tag_tree_reader import TagNode, TagTreeReport


class _ContextEchoAnswerer:
    def answer(self, *, question: str, context: str) -> str:  # noqa: ARG002
        sentences = [part.strip() for part in context.split(".") if part.strip()]
        return sentences[0] + "." if sentences else ""


class _CandidateMissAnswerer:
    def answer(self, *, question: str, context: str) -> str:  # noqa: ARG002
        if "candidate missing" in context:
            return "I cannot determine the answer."
        sentences = [part.strip() for part in context.split(".") if part.strip()]
        return sentences[0] + "." if sentences else ""


class _TableValueAnswerer:
    def answer(self, *, question: str, context: str) -> str:  # noqa: ARG002
        if "120" in context:
            return "120"
        return "I cannot determine the value."


class _HeadingLocationAnswerer:
    def answer(self, *, question: str, context: str) -> str:
        if "enrollment trend" in question.lower() and "Enrollment" in context:
            return "Enrollment"
        return "I cannot determine the heading."


def _node(
    tag: str,
    *,
    depth: int = 1,
    text: str = "",
    alt_text: str = "",
    page: int = 0,
    has_content: bool = True,
) -> TagNode:
    return TagNode(
        tag=tag,
        depth=depth,
        page=page,
        text=text,
        alt_text=alt_text,
        lang="",
        children_count=0,
        has_content=has_content,
    )


def _report(nodes: list[TagNode], *, has_structure_tree: bool = True) -> TagTreeReport:
    return TagTreeReport(
        file_path=Path("fixture.pdf"),
        page_count=1,
        has_structure_tree=has_structure_tree,
        nodes=nodes,
    )


def test_alt_text_substitution_scores_meaningful_alt_text() -> None:
    good = _report([
        _node("Figure", alt_text="Line chart showing revenue growth by quarter")
    ])
    bad = _report([
        _node("Figure", alt_text="image"),
        _node("Figure", alt_text=""),
    ])

    assert score_alt_text_substitution_report(good).passed is True
    bad_result = score_alt_text_substitution_report(bad)
    assert bad_result.passed is False
    assert bad_result.score == 0.0
    assert len(bad_result.findings) == 2


def test_pdf_behavioral_proxy_run_rejects_invalid_thresholds() -> None:
    report = _report([])
    tests = [
        PDFAltTextSubstitutionTest(),
        PDFDecorativeSkipTest(),
        PDFHeadingNavigationTest(),
        PDFReadingOrderComprehensionTest(),
        PDFTableCellLookupTest(),
    ]

    for proxy in tests:
        for value, expected in (
            (True, "threshold must be numeric"),
            (float("nan"), "threshold must be finite"),
            (1.5, "threshold must be between 0 and 1"),
        ):
            try:
                proxy.run(Path("fixture.pdf"), tag_tree_report=report, threshold=value)
            except ValueError as exc:
                assert expected in str(exc)
            else:
                raise AssertionError(
                    f"{proxy.test_name} should reject invalid threshold"
                )


def test_alt_text_substitution_flags_duplicate_descriptions() -> None:
    result = score_alt_text_substitution_report(
        _report(
            [
                _node("Figure", alt_text="Line chart showing revenue growth by quarter"),
                _node("Figure", alt_text="Line chart showing revenue growth by quarter"),
            ]
        )
    )

    assert result.passed is False
    assert result.score == 0.5
    assert result.findings[0]["issue"] == "duplicated_substitutive_alt_text"


def test_alt_text_substitution_can_use_injected_answerer_for_retention() -> None:
    text = "The chart shows revenue rose 18 percent in Q4."
    result = score_alt_text_substitution_report(
        _report([
            _node("Figure", alt_text=text)
        ]),
        answerer=_ContextEchoAnswerer(),
        baseline_text=text,
    )

    assert result.passed is True
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["answer_accuracy_retention"] == 1.0


def test_alt_text_substitution_flags_answer_retention_loss() -> None:
    result = score_alt_text_substitution_report(
        _report([
            _node("Figure", alt_text="Bar chart showing quarterly revenue")
        ]),
        answerer=_ContextEchoAnswerer(),
        baseline_text="The chart shows revenue rose 18 percent in Q4.",
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["answer_accuracy_retention"] == 0.0
    assert result.findings[0]["issue"] == "llm_answer_retention_loss"


def test_heading_navigation_detects_skipped_heading_levels() -> None:
    result = score_heading_navigation_report(
        _report([
            _node("H1", text="Annual report"),
            _node("H3", text="Skipped section"),
        ])
    )

    assert result.passed is False
    assert result.findings[0]["issue"] == "heading_level_skip"


def test_heading_navigation_flags_empty_heading_text() -> None:
    result = score_heading_navigation_report(
        _report([
            _node("H1", text=""),
            _node("H2", text="Methods"),
        ])
    )

    assert result.passed is False
    assert result.findings[0]["issue"] == "empty_heading"


def test_heading_navigation_flags_generic_and_duplicate_headings() -> None:
    result = score_heading_navigation_report(
        _report([
            _node("H1", text="Section"),
            _node("H2", text="Findings"),
            _node("H2", text="Findings"),
        ])
    )

    assert result.passed is False
    assert result.metadata["non_descriptive_heading_count"] == 1
    assert result.metadata["duplicate_heading_count"] == 2
    assert [finding["issue"] for finding in result.findings] == [
        "non_descriptive_heading",
        "duplicate_heading",
        "duplicate_heading",
    ]


def test_heading_navigation_can_use_injected_answerer() -> None:
    result = score_heading_navigation_report(
        _report(
            [
                _node("H1", text="Enrollment"),
                _node("P", text="The enrollment trend improved over five years."),
            ]
        ),
        answerer=_HeadingLocationAnswerer(),
    )

    assert result.passed is True
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["navigation_question_count"] == 1
    assert result.metadata["answer_accuracy_retention"] == 1.0


def test_heading_navigation_flags_answer_retention_loss() -> None:
    result = score_heading_navigation_report(
        _report(
            [
                _node("H1", text="Enrollment"),
                _node("P", text="The enrollment trend improved over five years."),
            ]
        ),
        answerer=_HeadingLocationAnswerer(),
        candidate_text="candidate missing outline",
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["answer_accuracy_retention"] == 0.0
    assert result.findings[0]["issue"] == "llm_answer_retention_loss"


def test_table_cell_lookup_requires_rows_headers_and_cells() -> None:
    good = _report([
        _node("Table", depth=1),
        _node("TR", depth=2),
        _node("TH", depth=3, text="Quarter"),
        _node("TD", depth=3, text="Q1"),
    ])
    bad = _report([
        _node("Table", depth=1),
        _node("TR", depth=2),
        _node("TD", depth=3, text="Q1"),
    ])

    assert score_table_cell_lookup_report(good).passed is True
    bad_result = score_table_cell_lookup_report(bad)
    assert bad_result.passed is False
    assert bad_result.findings[0]["has_headers"] is False


def test_table_cell_lookup_requires_data_cells_not_only_headers() -> None:
    result = score_table_cell_lookup_report(
        _report(
            [
                _node("Table", depth=1),
                _node("TR", depth=2),
                _node("TH", depth=3, text="Quarter"),
                _node("TH", depth=3, text="Revenue"),
            ]
        )
    )

    assert result.passed is False
    assert result.findings[0]["has_data_cells"] is False


def test_table_cell_lookup_requires_non_empty_headers_and_data_cells() -> None:
    empty_header = score_table_cell_lookup_report(
        _report(
            [
                _node("Table", depth=1),
                _node("TR", depth=2),
                _node("TH", depth=3, text=""),
                _node("TD", depth=3, text="Q1"),
            ]
        )
    )
    empty_data = score_table_cell_lookup_report(
        _report(
            [
                _node("Table", depth=1),
                _node("TR", depth=2),
                _node("TH", depth=3, text="Quarter"),
                _node("TD", depth=3, text=""),
            ]
        )
    )

    assert empty_header.passed is False
    assert empty_header.findings[0]["has_headers"] is True
    assert empty_header.findings[0]["has_non_empty_headers"] is False
    assert empty_data.passed is False
    assert empty_data.findings[0]["has_data_cells"] is True
    assert empty_data.findings[0]["has_non_empty_data_cells"] is False


def test_table_cell_lookup_can_use_injected_answerer_for_retention() -> None:
    result = score_table_cell_lookup_report(
        _report(
            [
                _node("Table", depth=1),
                _node("TR", depth=2),
                _node("TH", depth=3, text="Quarter"),
                _node("TH", depth=3, text="Revenue"),
                _node("TR", depth=2),
                _node("TD", depth=3, text="Q1"),
                _node("TD", depth=3, text="120"),
            ]
        ),
        answerer=_TableValueAnswerer(),
        baseline_text="Quarter Q1 revenue is 120.",
    )

    assert result.passed is True
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["lookup_question_count"] == 1
    assert result.metadata["answer_accuracy_retention"] == 1.0


def test_table_cell_lookup_flags_answer_retention_loss() -> None:
    result = score_table_cell_lookup_report(
        _report(
            [
                _node("Table", depth=1),
                _node("TR", depth=2),
                _node("TH", depth=3, text="Quarter"),
                _node("TH", depth=3, text="Revenue"),
                _node("TR", depth=2),
                _node("TD", depth=3, text="Q1"),
                _node("TD", depth=3, text="120"),
            ]
        ),
        answerer=_TableValueAnswerer(),
        baseline_text="Quarter Q1 revenue is 120.",
        candidate_text="candidate missing table value.",
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["answer_accuracy_retention"] == 0.0
    assert result.findings[0]["issue"] == "llm_answer_retention_loss"


def test_decorative_skip_flags_informative_empty_alt_figures() -> None:
    result = score_decorative_skip_report(
        _report([
            _node("Figure", text="This figure contains data but has no alt text.", alt_text="")
        ])
    )

    assert result.passed is False
    assert result.findings[0]["issue"] == "informative_figure_skipped"


def test_decorative_skip_treats_whitespace_alt_as_empty() -> None:
    result = score_decorative_skip_report(
        _report([
            _node(
                "Figure",
                text="This chart contains data but has whitespace alt text.",
                alt_text="   ",
            )
        ])
    )

    assert result.passed is False
    assert result.metadata["decorative_candidates"] == 1
    assert result.findings[0]["issue"] == "informative_figure_skipped"


def test_decorative_skip_can_use_injected_answerer_for_retention() -> None:
    context = "The decorative divider uses teal diagonal lines in the header."
    result = score_decorative_skip_report(
        _report([_node("Figure", alt_text="")]),
        answerer=_ContextEchoAnswerer(),
        baseline_text=context,
        candidate_text=context,
    )

    assert result.passed is True
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["question_count"] == 1
    assert result.metadata["answer_accuracy_retention"] == 1.0


def test_decorative_skip_flags_answer_retention_loss() -> None:
    result = score_decorative_skip_report(
        _report([_node("Figure", alt_text="")]),
        answerer=_ContextEchoAnswerer(),
        baseline_text="The decorative divider uses teal diagonal lines in the header.",
        candidate_text="candidate missing decorative detail.",
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["answer_accuracy_retention"] == 0.0
    assert result.findings[0]["issue"] == "llm_answer_retention_loss"


def test_reading_order_proxy_generates_deterministic_questions() -> None:
    text = (
        "The report explains the enrollment trend over five years. "
        "It also identifies the largest accessibility risks for students."
    )
    result = score_reading_order_report(_report([_node("P", text=text)]))

    assert result.passed is True
    assert result.metadata["question_count"] == 2
    assert result.metadata["llm_answering_enabled"] is False


def test_reading_order_proxy_can_use_injected_answerer_for_retention() -> None:
    text = "The report explains enrollment trends over five years."
    result = score_reading_order_report(
        _report([_node("P", text=text)]),
        answerer=_ContextEchoAnswerer(),
        baseline_text=text,
    )

    assert result.passed is True
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["answer_accuracy_retention"] == 1.0
    assert result.metadata["candidate_accuracy"] == 1.0


def test_reading_order_proxy_flags_answer_retention_loss() -> None:
    baseline = "The report explains enrollment trends over five years."
    result = score_reading_order_report(
        _report([_node("P", text="candidate missing context.")]),
        answerer=_CandidateMissAnswerer(),
        baseline_text=baseline,
    )

    assert result.passed is False
    assert result.metadata["llm_answering_enabled"] is True
    assert result.metadata["answer_accuracy_retention"] == 0.0
    assert result.findings[0]["issue"] == "llm_answer_retention_loss"


def test_transcript_analyzer_reports_missing_structure_tree() -> None:
    findings = analyze_tag_tree_report(_report([], has_structure_tree=False))

    assert findings == [
        {
            "severity": "error",
            "issue": "missing_structure_tree",
            "message": "PDF has no structure tree for screen-reader traversal.",
        }
    ]


def test_transcript_analyzer_flags_page_order_backtracking() -> None:
    findings = analyze_tag_tree_report(
        _report(
            [
                _node("P", text="First page", page=0),
                _node("P", text="Third page", page=2),
                _node("P", text="Second page", page=1),
            ]
        )
    )

    assert findings[0]["issue"] == "page_order_backtracking"


def test_pdf_transcript_analyzer_accepts_provided_screen_reader_transcript() -> None:
    result = PDFTranscriptAnalyzer().run(
        Path("fixture.pdf"),
        tag_tree_report=_report([_node("P", text="Document body text.")]),
        transcript_text="Graphic",
    )

    assert result.passed is False
    assert result.metadata["advisory_only"] is True
    assert result.metadata["transcript_sources"] == [
        "pdf_tag_tree",
        "provided_screen_reader_transcript",
    ]
    assert result.findings[0]["issue"] == "unlabeled_object_announcement"
