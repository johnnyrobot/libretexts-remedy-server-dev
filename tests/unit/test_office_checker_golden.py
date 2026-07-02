"""AC2 golden regression + AC7/§10 catalog-implementation parity."""

from __future__ import annotations

from project_remedy.models import FileType
from project_remedy.office_acceptance import run_office_checker
from project_remedy.office_checker import DOCX_RULES, OfficeAccessibilityChecker
from project_remedy.office_rules import RULE_CATALOG
from tests.unit.office_fixtures import make_docx


def test_catalog_implementation_parity():
    """§10 risk: every cataloged rule id must have a registered implementation."""
    docx_ids = {spec.rule_id for spec in RULE_CATALOG if spec.format == "docx"}
    assert docx_ids == set(DOCX_RULES)


def _known_bad_docx(tmp_path):
    return make_docx(
        tmp_path / "known_bad.docx",
        title="", language="",
        body_paragraphs=["This document opens on plain body text with no heading anywhere."],
        tables=1, mark_table_headers=False, merge_header_cells=True,
        inline_images=1, image_alt=None,
        manual_bullets=["• unstructured bullet item"],
        hyperlinks=[("https://example.com", "https://example.com")],
    )


def test_known_bad_docx_fails_exactly_the_expected_rules(tmp_path):
    report = OfficeAccessibilityChecker(_known_bad_docx(tmp_path)).run_all()
    failed = {r.rule_id for r in report.results if r.status == "Failed"}
    manual = {r.rule_id for r in report.results if r.status == "Manual Check Needed"}
    assert failed == {
        "docx-title", "docx-language", "docx-headings",
        "docx-alt-text", "docx-table-headers",
        "OOXML-DOCX-2.3", "OOXML-DOCX-4.2", "OOXML-DOCX-6.1",
    }
    assert manual == {"OOXML-DOCX-5.1"}
    assert len(report.results) == 12  # every cataloged rule evaluated (AC7)


def test_run_office_checker_docx_now_uses_the_engine(tmp_path):
    report = run_office_checker(_known_bad_docx(tmp_path), FileType.DOCX)
    assert len(report.results) == 12
    assert {r.rule_id for r in report.results} >= {"docx-title", "OOXML-DOCX-2.2"}


def test_deterministic_output(tmp_path):
    """NFR1: same bytes in, identical report out."""
    from dataclasses import asdict

    path = _known_bad_docx(tmp_path)
    first = [asdict(r) for r in OfficeAccessibilityChecker(path).run_all().results]
    second = [asdict(r) for r in OfficeAccessibilityChecker(path).run_all().results]
    assert first == second
