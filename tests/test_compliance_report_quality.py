from __future__ import annotations

from project_remedy.compliance_report import (
    Conformance,
    DocumentReport,
    OriginalDocInfo,
    WCAGResult,
    _render_html,
)


def _report(*, quality_result: dict | None = None) -> DocumentReport:
    return DocumentReport(
        document_name="Sample",
        original=OriginalDocInfo(
            file_path="/tmp/source.pdf",
            file_type="pdf",
            file_size=100,
            source_url="",
            is_tagged=False,
            has_language=False,
            has_title=False,
            page_count=1,
        ),
        remediated_path="/tmp/remediated.pdf",
        remediated_size=120,
        remediated_pages=1,
        check_results=[],
        sr_issues=[],
        tag_count=0,
        verapdf_checked=False,
        verapdf_passed=True,
        verapdf_violations=[],
        wcag_results=[
            WCAGResult("1.1.1", "Non-text Content", "A", "PASS", "")
        ],
        conformance=Conformance.CONFORMANT,
        generated_at="2026-05-08T00:00:00+00:00",
        quality_result=quality_result or {},
    )


def test_document_report_omits_quality_result_when_absent() -> None:
    payload = _report().to_dict()

    assert "quality_result" not in payload


def test_document_report_serializes_quality_result_when_present() -> None:
    quality = {
        "format": "pdf",
        "overall_pass": True,
        "dimensions": {
            "alt_text": {
                "score": 0.9,
                "confidence": 0.8,
            }
        },
    }

    payload = _report(quality_result=quality).to_dict()
    html = _render_html(_report(quality_result=quality), "", "#003366")

    assert payload["quality_result"] == quality
    assert "Quality Layer" in html
    assert "Alt Text" in html
