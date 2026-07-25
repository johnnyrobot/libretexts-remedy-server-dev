"""Tests for the L0–L5 remediation-level classifier (Phase 0)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from project_remedy.levels import (
    LACCD_DISTRICT_UA1,
    LevelResult,
    StructureProbe,
    classify_level,
    is_font_clause_only,
    oversized_reason,
    probe_structure,
    select_shard,
    summarize_levels,
)
from project_remedy.pdf_acceptance import (
    PDFAcceptanceResult,
    PDFOpenabilityResult,
    VeraPDFResult,
)
from project_remedy.pdf_checker import CheckReport, CheckResult
from project_remedy.quality_judges.shared.base import QualityResult
from project_remedy.tag_tree_reader import (
    ScreenReaderIssue,
    Severity,
    TagTreeReport,
)
from project_remedy.tag_tree_reader import ValidationResult as TagTreeValidationResult


# --------------------------------------------------------------------------
# Fixtures: build real result objects (no mocks — the classifier reads these).
# --------------------------------------------------------------------------

_P = Path("/tmp/doc.pdf")


def make_probe(
    *,
    has_text: bool = True,
    has_struct_tree: bool = True,
    is_marked: bool = True,
    has_lang: bool = True,
    display_doc_title: bool = True,
    has_uaid: bool = True,
    page_count: int = 1,
) -> StructureProbe:
    return StructureProbe(
        has_text=has_text,
        has_struct_tree=has_struct_tree,
        is_marked=is_marked,
        has_lang=has_lang,
        display_doc_title=display_doc_title,
        has_uaid=has_uaid,
        page_count=page_count,
    )


def make_acceptance(
    *,
    openable: bool = True,
    page_count: int = 1,
    verapdf_checked: bool = True,
    verapdf_passed: bool = True,
    verapdf_violations: list | None = None,
    checker_results: list[CheckResult] | None = None,
    sr_issues: list[ScreenReaderIssue] | None = None,
    quality_overall_pass: bool | None = None,
) -> PDFAcceptanceResult:
    checker_report = CheckReport(
        file_path=_P, file_size=1000, page_count=page_count,
        results=checker_results or [],
    )
    tag_tree = TagTreeReport(
        file_path=_P, page_count=page_count, has_structure_tree=True, nodes=[],
    )
    tag_tree_result = TagTreeValidationResult(
        file_path=_P, tag_tree=tag_tree, issues=sr_issues or [],
        passed=not sr_issues,
    )
    verapdf_result = VeraPDFResult(
        checked=verapdf_checked, passed=verapdf_passed,
        violations=verapdf_violations or [],
    )
    quality_result = (
        None if quality_overall_pass is None
        else QualityResult(format="pdf", overall_pass=quality_overall_pass)
    )
    return PDFAcceptanceResult(
        file_path=_P,
        checker_report=checker_report,
        tag_tree_result=tag_tree_result,
        verapdf_result=verapdf_result,
        openability_result=PDFOpenabilityResult(
            checked=True, openable=openable, page_count=page_count,
        ),
        quality_result=quality_result,
    )


# --------------------------------------------------------------------------
# Gate boundaries (top-down; first match wins)
# --------------------------------------------------------------------------

def test_none_acceptance_is_l0():
    result = classify_level(None, make_probe())
    assert result.level == "L0"
    assert result.machine_certifiable is False
    assert "evaluation_error" in result.blocking_conditions


def test_not_openable_is_l0():
    acc = make_acceptance(openable=False)
    result = classify_level(acc, make_probe())
    assert result.level == "L0"


def test_no_text_is_l0_even_with_structure():
    # Image-only scan: structure flags don't matter if there's no text layer.
    acc = make_acceptance()
    probe = make_probe(has_text=False, has_struct_tree=True, is_marked=True)
    result = classify_level(acc, probe)
    assert result.level == "L0"


def test_text_without_struct_tree_is_l1():
    acc = make_acceptance(verapdf_checked=False, verapdf_passed=False)
    probe = make_probe(has_text=True, has_struct_tree=False, is_marked=False)
    result = classify_level(acc, probe)
    assert result.level == "L1"


def test_tagged_but_verapdf_fails_is_l2():
    acc = make_acceptance(verapdf_passed=False,
                          verapdf_violations=[{"id": "7.1-1", "description": "no UA id"}])
    probe = make_probe(has_struct_tree=True, is_marked=True)
    result = classify_level(acc, probe)
    assert result.level == "L2"
    assert "verapdf_failed" in result.blocking_conditions


def test_verapdf_passes_but_missing_uaid_is_l2():
    acc = make_acceptance(verapdf_passed=True)
    probe = make_probe(has_struct_tree=True, is_marked=True, has_uaid=False)
    result = classify_level(acc, probe)
    assert result.level == "L2"
    assert "missing_uaid" in result.blocking_conditions


def test_machine_verified_pdfua_is_l3():
    # veraPDF clean + lang + title + uaid, but quality layer not run → caps at L3.
    acc = make_acceptance(verapdf_passed=True, quality_overall_pass=None)
    probe = make_probe()
    result = classify_level(acc, probe)
    assert result.level == "L3"
    assert result.machine_certifiable is True
    assert "quality_layer_not_run" in result.blocking_conditions


def test_engine_complete_is_l4():
    # L3 gates met + conformant (no failures) + quality layer passed.
    acc = make_acceptance(verapdf_passed=True, quality_overall_pass=True)
    probe = make_probe()
    result = classify_level(acc, probe)
    assert result.level == "L4"


def test_never_returns_l5():
    # Even a perfect document must not be auto-promoted to L5.
    acc = make_acceptance(verapdf_passed=True, quality_overall_pass=True)
    result = classify_level(acc, make_probe())
    assert result.level != "L5"
    assert result.level in {"L0", "L1", "L2", "L3", "L4"}


def test_needs_human_lists_manual_checks_excluding_llm_handled():
    from project_remedy.compliance_report import _LLM_HANDLED_CHECKS

    llm_handled = next(iter(_LLM_HANDLED_CHECKS))
    checker_results = [
        CheckResult(rule_id="logical-reading-order", category="structure",
                    description="reading order", status="Manual Check Needed"),
        CheckResult(rule_id=llm_handled, category="content",
                    description="llm-handled", status="Manual Check Needed"),
    ]
    acc = make_acceptance(verapdf_passed=True, checker_results=checker_results)
    result = classify_level(acc, make_probe())
    assert "logical-reading-order" in result.needs_human
    assert llm_handled not in result.needs_human


def test_sub_scores_present():
    acc = make_acceptance(
        verapdf_passed=False,
        verapdf_violations=[{"id": "a"}, {"id": "b"}],
        sr_issues=[ScreenReaderIssue(rule_id="x", severity=Severity.ERROR,
                                     page=0, element="P", description="d")],
    )
    result = classify_level(acc, make_probe(page_count=3))
    assert result.sub_scores["verapdf_violations"] == 2
    assert result.sub_scores["sr_errors"] == 1
    assert result.sub_scores["page_count"] == 3


# --------------------------------------------------------------------------
# probe_structure against a real minimal PDF
# --------------------------------------------------------------------------

def test_probe_structure_on_untagged_pdf(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(pdf_path)
    pdf.close()

    probe = probe_structure(pdf_path)
    assert probe.has_struct_tree is False
    assert probe.is_marked is False
    assert probe.has_uaid is False
    assert probe.page_count == 1


# --------------------------------------------------------------------------
# Burndown summary aggregation (pure)
# --------------------------------------------------------------------------

def test_summarize_levels_counts_per_root_and_totals():
    records = [
        {"root": "/A", "level": "L0", "needs_human": ["x"]},
        {"root": "/A", "level": "L3", "needs_human": []},
        {"root": "/B", "level": "L3", "needs_human": ["y", "z"]},
    ]
    s = summarize_levels(records, vision_enabled=False,
                         generated_at="2026-06-25T00:00:00Z")
    assert s["totals"] == {"L0": 1, "L3": 2}
    assert s["by_root"]["/A"] == {"L0": 1, "L3": 1}
    assert s["by_root"]["/B"] == {"L3": 1}
    assert s["needs_human_total"] == 3
    assert s["vision_enabled"] is False
    assert s["generated_at"] == "2026-06-25T00:00:00Z"


# --------------------------------------------------------------------------
# Pathological-file guard
# --------------------------------------------------------------------------

def test_oversized_reason_under_limits_is_none():
    assert oversized_reason(file_size_bytes=2_000_000, page_count=10,
                            max_mb=30, max_pages=200) is None


def test_oversized_reason_too_many_pages():
    r = oversized_reason(file_size_bytes=1_000_000, page_count=500,
                         max_mb=30, max_pages=200)
    assert r is not None and "page" in r.lower()


def test_oversized_reason_too_large():
    r = oversized_reason(file_size_bytes=60 * 1024 * 1024, page_count=5,
                         max_mb=30, max_pages=200)
    assert r is not None and "mb" in r.lower()


def test_oversized_reason_at_boundary_is_allowed():
    # Exactly at the cap is allowed; only strictly over trips the guard.
    assert oversized_reason(file_size_bytes=30 * 1024 * 1024, page_count=200,
                            max_mb=30, max_pages=200) is None


# --------------------------------------------------------------------------
# Font-clause residue detector (font-rebuild escalation signal)
# --------------------------------------------------------------------------

def test_font_clause_only_true_when_all_721():
    viols = [
        {"id": "ISO 14289-1:2014-7.21.4.1-1"},
        {"id": "ISO 14289-1:2014-7.21.8-1"},
    ]
    assert is_font_clause_only(viols) is True


def test_font_clause_only_false_when_mixed():
    viols = [
        {"id": "ISO 14289-1:2014-7.21.4.1-1"},
        {"id": "ISO 14289-1:2014-7.1-1"},  # general clause, not fonts
    ]
    assert is_font_clause_only(viols) is False


def test_font_clause_only_false_when_empty():
    assert is_font_clause_only([]) is False


def test_font_clause_only_handles_rule_id_key():
    # Some producers use 'rule_id' instead of 'id'.
    assert is_font_clause_only([{"rule_id": "ISO 14289-1:2014-7.21.7-2"}]) is True


# --------------------------------------------------------------------------
# Shard selection (parallel workers)
# --------------------------------------------------------------------------

def test_select_shard_partitions_completely_and_disjointly():
    items = list(range(20))
    n = 8
    shards = [select_shard(items, shard_index=i, shard_count=n) for i in range(n)]
    # Every item appears in exactly one shard (complete + disjoint partition).
    flat = [x for s in shards for x in s]
    assert sorted(flat) == items
    assert len(flat) == len(set(flat))


def test_select_shard_single_shard_is_identity():
    items = [1, 2, 3]
    assert select_shard(items, shard_index=0, shard_count=1) == items


def test_select_shard_strided():
    items = list(range(10))
    assert select_shard(items, shard_index=0, shard_count=2) == [0, 2, 4, 6, 8]
    assert select_shard(items, shard_index=1, shard_count=2) == [1, 3, 5, 7, 9]
