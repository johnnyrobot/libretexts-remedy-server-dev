"""Per-document accessibility compliance report generator.

Produces a before/after report for each remediated PDF showing:
- Original source document info and accessibility state
- Remediated PDF check results (34 checks + 9 screen reader checks)
- WCAG 2.1 AA conformance mapping
- Overall conformance determination

Usage::

    from project_remedy.compliance_report import generate_document_report
    report = generate_document_report(
        original_path=Path("downloads/pdf/doc.pdf"),
        remediated_path=Path("remediated-pdfs/doc.pdf"),
        output_dir=Path("compliance/documents/"),
    )
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pikepdf

from project_remedy.config import PipelineConfig
from project_remedy.pdf_acceptance import PDFAcceptanceResult, evaluate_pdf_acceptance
from project_remedy.pdf_checker import (
    CheckReport,
    CheckResult,
)
from project_remedy.tag_tree_reader import (
    ScreenReaderIssue,
    Severity,
    ValidationResult as SRValidationResult,
)


# ---------------------------------------------------------------------------
# WCAG 2.1 AA ↔ check mapping
# ---------------------------------------------------------------------------

@dataclass
class WCAGCriterion:
    id: str            # e.g. "1.1.1"
    name: str          # e.g. "Non-text Content"
    level: str         # "A" or "AA"
    rule_ids: list[str]  # our check rule_ids that map to this criterion


WCAG_MAPPING: list[WCAGCriterion] = [
    WCAGCriterion("1.1.1", "Non-text Content", "A",
                  ["alt-figures", "alt-elements", "sr-figure-no-alt", "sr-figure-short-alt"]),
    WCAGCriterion("1.3.1", "Info and Relationships", "A",
                  ["doc-tagged", "page-content-tagged", "page-annotations-tagged",
                   "sr-table-no-headers", "sr-list-no-items", "sr-no-tags"]),
    WCAGCriterion("1.3.2", "Meaningful Sequence", "A",
                  ["doc-reading-order", "sr-repeated-content", "sr-untagged-page"]),
    WCAGCriterion("1.3.3", "Sensory Characteristics", "A", []),
    WCAGCriterion("1.4.1", "Use of Color", "A", ["doc-color-contrast"]),
    WCAGCriterion("1.4.3", "Contrast (Minimum)", "AA", ["doc-color-contrast"]),
    WCAGCriterion("1.4.5", "Images of Text", "AA", ["doc-not-image-only"]),
    WCAGCriterion("2.1.1", "Keyboard", "A", ["page-tab-order"]),
    WCAGCriterion("2.1.2", "No Keyboard Trap", "A", []),
    WCAGCriterion("2.2.1", "Timing Adjustable", "A", ["page-no-timed-responses"]),
    WCAGCriterion("2.3.1", "Three Flashes or Below Threshold", "A", ["page-no-screen-flicker"]),
    WCAGCriterion("2.4.1", "Bypass Blocks", "A", ["doc-bookmarks"]),
    WCAGCriterion("2.4.2", "Page Titled", "A", ["doc-display-title"]),
    WCAGCriterion("2.4.4", "Link Purpose (In Context)", "A",
                  ["page-no-repetitive-links"]),
    WCAGCriterion("2.4.5", "Multiple Ways", "AA", ["doc-bookmarks"]),
    WCAGCriterion("2.4.6", "Headings and Labels", "AA",
                  ["alt-heading-nesting", "sr-heading-skip", "sr-heading-start", "sr-no-headings"]),
    WCAGCriterion("2.4.7", "Focus Visible", "AA", ["page-tab-order"]),
    WCAGCriterion("3.1.1", "Language of Page", "A", ["doc-language", "sr-no-lang"]),
    WCAGCriterion("3.1.2", "Language of Parts", "AA", []),
    WCAGCriterion("3.2.3", "Consistent Navigation", "AA", []),
    WCAGCriterion("3.2.4", "Consistent Identification", "AA", []),
    WCAGCriterion("4.1.1", "Parsing", "A", ["doc-tagged"]),
    WCAGCriterion("4.1.2", "Name, Role, Value", "A",
                  ["forms-tooltips", "page-annotations-tagged"]),
]


# ---------------------------------------------------------------------------
# Issue normalization
# ---------------------------------------------------------------------------


def _build_normalized_issues(acceptance: PDFAcceptanceResult) -> list[dict]:
    """Build a canonical issues array from checker, SR, and veraPDF results.

    Each issue has: code, source, severity, fixable, blocking, description.
    """
    issues: list[dict] = []

    # Checker failures.
    for r in acceptance.checker_report.results:
        if r.status == "Failed":
            issues.append({
                "code": r.rule_id,
                "source": "checker",
                "severity": "error",
                "fixable": r.fixable,
                "blocking": False,
                "description": r.description,
            })

    # Screen reader errors and warnings.
    for i in acceptance.tag_tree_result.issues:
        if i.severity == Severity.ERROR:
            issues.append({
                "code": i.rule_id,
                "source": "screen-reader",
                "severity": "error",
                "fixable": True,
                "blocking": False,
                "description": i.description,
            })
        elif i.severity == Severity.WARNING:
            issues.append({
                "code": i.rule_id,
                "source": "screen-reader",
                "severity": "warning",
                "fixable": True,
                "blocking": False,
                "description": i.description,
            })

    # veraPDF violations.
    if acceptance.verapdf_result.checked and acceptance.verapdf_result.violations:
        for v in acceptance.verapdf_result.violations:
            is_font = PDFAcceptanceResult._is_source_font_limitation(v)
            issues.append({
                "code": v.get("id", "unknown-rule"),
                "source": "verapdf",
                "severity": "error",
                "fixable": not is_font,
                "blocking": False,
                "description": v.get("description", ""),
            })

    return issues


# ---------------------------------------------------------------------------
# Conformance determination
# ---------------------------------------------------------------------------

class Conformance:
    CONFORMANT = "Conformant"
    PARTIALLY = "Partially Conformant"
    NOT_CONFORMANT = "Not Conformant"


def _determine_conformance(
    acceptance: PDFAcceptanceResult,
) -> str:
    """Determine overall document conformance.

    A file is Conformant when its remaining issues are all non-blocking:
    - Checker failures that are fixable cosmetic/navigational issues
    - veraPDF violations that are source-font limitations
    - SR warnings (not errors)
    """
    all_failed = [
        r for r in acceptance.checker_report.results
        if r.status == "Failed"
        or (r.status == "Manual Check Needed" and r.rule_id not in _LLM_HANDLED_CHECKS)
    ]
    # Checker failures that don't block content access for screen readers.
    # These are real WCAG issues but are cosmetic/navigational — they don't
    # prevent a screen reader user from accessing the document content.
    _NON_BLOCKING_CHECKER = {
        "doc-display-title",    # 2.4.2 — title bar display, not content
        "page-tab-order",       # 2.4.3 — focus order, navigational
        "doc-bookmarks",        # 2.4.5 — bookmarks in large docs
        "page-char-encoding",   # source font limitation — degraded encoding
    }
    blocking_failed = [r for r in all_failed if r.rule_id not in _NON_BLOCKING_CHECKER]
    sr_errors = acceptance.screen_reader_errors
    verapdf_failed = (
        acceptance.verapdf_result.checked and not acceptance.verapdf_result.passed
    )
    warning_reasons = list(getattr(acceptance, "warning_reasons", []) or [])

    if not getattr(acceptance, "openable", acceptance.passed):
        return Conformance.NOT_CONFORMANT
    if acceptance.passed and not warning_reasons:
        return Conformance.CONFORMANT

    # When the only issues are non-blocking checker failures, source-font
    # veraPDF violations, and SR warnings (not errors) → Conformant.
    # The document content is accessible even if cosmetic metadata or
    # inherited font limitations remain.
    verapdf_all_source_font = (
        acceptance.verapdf_result.passed
        or (
            acceptance.verapdf_result.checked
            and acceptance.verapdf_result.violations  # guard against all([])
            and all(
                acceptance._is_source_font_limitation(v)
                for v in acceptance.verapdf_result.violations
            )
        )
        or not acceptance.verapdf_result.checked
    )
    # Also require no validator runtime errors — a crashed validator with
    # empty violation lists should not be treated as clean.
    has_runtime_errors = bool(
        getattr(acceptance, "checker_error", None)
        or getattr(acceptance, "screen_reader_error", None)
        or (acceptance.verapdf_result.checked and acceptance.verapdf_result.error)
    )
    if (
        not blocking_failed
        and not sr_errors
        and verapdf_all_source_font
        and not has_runtime_errors
    ):
        return Conformance.CONFORMANT

    if warning_reasons:
        return Conformance.PARTIALLY
    if not verapdf_failed and len(all_failed) <= 3 and len(sr_errors) <= 2:
        return Conformance.PARTIALLY
    return Conformance.NOT_CONFORMANT


def _determine_wcag_status(
    criterion: WCAGCriterion,
    check_results: list[CheckResult],
    sr_issues: list[ScreenReaderIssue],
) -> tuple[str, str]:
    """Determine PASS/FAIL and build remarks for a single WCAG criterion.

    Returns (status, remarks).
    """
    if not criterion.rule_ids:
        return "N/A", "Not applicable to static PDF documents"

    # Gather matching check results.
    matching_checks = [r for r in check_results if r.rule_id in criterion.rule_ids]
    matching_sr = [i for i in sr_issues if i.rule_id in criterion.rule_ids]

    if not matching_checks and not matching_sr:
        return "N/A", "No applicable checks for this document"

    failed_checks = [r for r in matching_checks if r.status == "Failed"]
    sr_errors = [i for i in matching_sr if i.severity == Severity.ERROR]

    if not failed_checks and not sr_errors:
        return "PASS", ""

    remarks_parts = []
    for r in failed_checks:
        remarks_parts.append(f"{r.description}: {'; '.join(r.details[:2])}" if r.details else r.description)
    for i in sr_errors:
        remarks_parts.append(i.description)

    return "FAIL", "; ".join(remarks_parts)


# ---------------------------------------------------------------------------
# Original document analysis
# ---------------------------------------------------------------------------

@dataclass
class OriginalDocInfo:
    """Accessibility state of the original source document."""
    file_path: str
    file_type: str
    file_size: int
    source_url: str
    is_tagged: bool
    has_language: bool
    has_title: bool
    page_count: int


def _analyze_original(original_path: Path, source_url: str = "") -> OriginalDocInfo:
    """Quick accessibility scan of the original source document."""
    suffix = original_path.suffix.lower().lstrip(".")
    stat = original_path.stat()

    is_tagged = False
    has_language = False
    has_title = False
    page_count = 0

    if suffix == "pdf":
        try:
            with pikepdf.open(original_path) as pdf:
                page_count = len(pdf.pages)
                is_tagged = bool(pdf.Root.get("/StructTreeRoot"))
                lang = pdf.Root.get("/Lang")
                has_language = bool(lang and str(lang).strip())
                try:
                    with pdf.open_metadata() as meta:
                        has_title = bool(meta.get("dc:title", "").strip())
                except Exception:
                    pass
        except Exception:
            pass
    else:
        # Non-PDF originals: can't check accessibility without converting.
        page_count = 0

    return OriginalDocInfo(
        file_path=str(original_path),
        file_type=suffix or "unknown",
        file_size=stat.st_size,
        source_url=source_url,
        is_tagged=is_tagged,
        has_language=has_language,
        has_title=has_title,
        page_count=page_count,
    )


# ---------------------------------------------------------------------------
# Report data model
# ---------------------------------------------------------------------------

@dataclass
class WCAGResult:
    criterion_id: str
    criterion_name: str
    level: str
    status: str   # PASS, FAIL, N/A
    remarks: str


@dataclass
class DocumentReport:
    """Complete compliance report for a single document."""

    # Document identity.
    document_name: str
    original: OriginalDocInfo
    remediated_path: str
    remediated_size: int
    remediated_pages: int

    # Check results.
    check_results: list[dict]   # serialized CheckResult list
    sr_issues: list[dict]       # serialized ScreenReaderIssue list
    tag_count: int
    verapdf_checked: bool
    verapdf_passed: bool
    verapdf_violations: list[dict]

    # WCAG mapping.
    wcag_results: list[WCAGResult]
    conformance: str

    # Metadata.
    generated_at: str
    report_filename: str = ""  # basename of the HTML report file (for linking)
    generator: str = "Remedy Server"

    # Normalized issues (canonical union of checker, SR, and veraPDF).
    issues: list[dict] = field(default_factory=list)

    # Visual fidelity diff (original vs remediated, page-by-page pixel comparison).
    visual_diff: dict = field(default_factory=dict)  # keys: checked, passed, total_pages, differing_pages, max_page_diff

    # Screen reader readability score (0-100 composite).
    screen_reader_readability: float = 0.0
    screen_reader_readability_details: dict = field(default_factory=dict)

    # Optional quality-layer result, present only for opt-in quality audits.
    quality_result: dict = field(default_factory=dict)

    @property
    def source_font_only(self) -> bool:
        """True when all veraPDF violations are source-font limitations."""
        if not self.verapdf_violations:
            return False
        from project_remedy.pdf_acceptance import PDFAcceptanceResult
        return all(
            PDFAcceptanceResult._is_source_font_limitation(v)
            for v in self.verapdf_violations
        )

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.check_results if r["status"] == "Passed")

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.check_results if r["status"] == "Failed")

    @property
    def na_checks(self) -> int:
        return sum(1 for r in self.check_results if r["status"] == "Not Applicable")

    @property
    def applicable_checks(self) -> int:
        return len(self.check_results) - self.na_checks

    @property
    def sr_error_count(self) -> int:
        return sum(1 for i in self.sr_issues if i["severity"] == "error")

    @property
    def sr_warning_count(self) -> int:
        return sum(1 for i in self.sr_issues if i["severity"] == "warning")

    @property
    def wcag_pass_count(self) -> int:
        return sum(1 for w in self.wcag_results if w.status == "PASS")

    @property
    def wcag_fail_count(self) -> int:
        return sum(1 for w in self.wcag_results if w.status == "FAIL")

    @property
    def wcag_na_count(self) -> int:
        return sum(1 for w in self.wcag_results if w.status == "N/A")

    @property
    def verapdf_violation_count(self) -> int:
        return len(self.verapdf_violations)

    @property
    def issue_summary(self) -> dict:
        return {
            "total": len(self.issues),
            "fixable": sum(1 for i in self.issues if i.get("fixable")),
            "source_limited": sum(1 for i in self.issues if not i.get("fixable")),
            "blocking": sum(1 for i in self.issues if i.get("blocking")),
        }

    @classmethod
    def from_dict(cls, data: dict, *, report_filename: str = "") -> "DocumentReport":
        """Rehydrate a serialized report from its JSON representation."""
        original_data = data.get("original") or {}
        verapdf_data = data.get("verapdf") or {}
        return cls(
            document_name=data.get("document_name", ""),
            original=OriginalDocInfo(**original_data),
            remediated_path=data.get("remediated_path", ""),
            remediated_size=int(data.get("remediated_size", 0) or 0),
            remediated_pages=int(data.get("remediated_pages", 0) or 0),
            check_results=list(data.get("check_results") or []),
            sr_issues=list(data.get("sr_issues") or []),
            tag_count=int(data.get("tag_count", 0) or 0),
            verapdf_checked=bool(verapdf_data.get("checked", False)),
            verapdf_passed=bool(verapdf_data.get("passed", False)),
            verapdf_violations=list(verapdf_data.get("violations") or []),
            wcag_results=[
                WCAGResult(**item)
                for item in (data.get("wcag_results") or [])
            ],
            conformance=data.get("conformance", Conformance.NOT_CONFORMANT),
            generated_at=data.get("generated_at", ""),
            report_filename=report_filename or data.get("report_filename", ""),
            generator=data.get("generator", "Remedy Server"),
            issues=list(data.get("issues") or []),
            visual_diff=dict(data.get("visual_diff") or {}),
            screen_reader_readability=float(data.get("screen_reader_readability", 0.0) or 0.0),
            screen_reader_readability_details=dict(data.get("screen_reader_readability_details") or {}),
            quality_result=dict(data.get("quality_result") or {}),
        )

    def to_dict(self) -> dict:
        d = {
            "document_name": self.document_name,
            "original": asdict(self.original),
            "remediated_path": self.remediated_path,
            "remediated_size": self.remediated_size,
            "remediated_pages": self.remediated_pages,
            "conformance": self.conformance,
            "check_results": self.check_results,
            "sr_issues": self.sr_issues,
            "tag_count": self.tag_count,
            "verapdf": {
                "checked": self.verapdf_checked,
                "passed": self.verapdf_passed,
                "violations": self.verapdf_violations,
            },
            "wcag_results": [asdict(w) for w in self.wcag_results],
            "summary": {
                "passed_checks": self.passed_checks,
                "failed_checks": self.failed_checks,
                "sr_errors": self.sr_error_count,
                "sr_warnings": self.sr_warning_count,
                "verapdf_checked": self.verapdf_checked,
                "verapdf_passed": self.verapdf_passed,
                "verapdf_violations": self.verapdf_violation_count,
                "wcag_pass": self.wcag_pass_count,
                "wcag_fail": self.wcag_fail_count,
                "wcag_na": self.wcag_na_count,
            },
            "visual_diff": self.visual_diff,
            "issues": self.issues,
            "issue_summary": self.issue_summary,
            "screen_reader_readability": self.screen_reader_readability,
            "screen_reader_readability_details": self.screen_reader_readability_details,
            "generated_at": self.generated_at,
            "report_filename": self.report_filename,
            "generator": self.generator,
        }
        if self.quality_result:
            d["quality_result"] = self.quality_result
        return d


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def calculate_screen_reader_readability(
    pdf_path: Path,
    tag_tree_result: SRValidationResult,
    checker_report: CheckReport,
) -> tuple[float, dict]:
    """Compute a 0-100 screen reader readability score.

    Components:
        Text extractability (30 pts): printable chars / total chars via fitz.
        Tag coverage (25 pts): % of pages with StructParents + tags per page.
        Alt text quality (20 pts): figures with meaningful (>10 char) alt text.
        Heading structure (15 pts): proper H1-H6 hierarchy.
        Table/list accessibility (10 pts): tables have TH, lists have LI in L.

    Returns (score, details_dict) where details_dict has per-component scores.
    """
    details: dict = {}

    # --- Text extractability (30 pts) ---
    text_score = 30.0
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        total_chars = 0
        readable_chars = 0
        fffd_count = 0
        for page in doc:
            text = page.get_text()
            for ch in text:
                total_chars += 1
                if ch.isprintable() or ch in "\n\t\r ":
                    readable_chars += 1
                if ch == "\ufffd":
                    fffd_count += 1
        doc.close()
        if total_chars > 0:
            text_score = 30.0 * (readable_chars / total_chars)
        details["text_extractability"] = {
            "score": round(text_score, 1),
            "max": 30,
            "total_chars": total_chars,
            "readable_chars": readable_chars,
            "replacement_chars": fffd_count,
        }
    except Exception:
        details["text_extractability"] = {"score": 0, "max": 30, "error": "fitz unavailable"}
        text_score = 0.0

    # --- Tag coverage (25 pts) ---
    nodes = tag_tree_result.tag_tree.nodes
    page_count = tag_tree_result.tag_tree.page_count or 1
    tagged_pages = len(tag_tree_result.tag_tree.nodes_by_page())
    page_coverage = tagged_pages / page_count if page_count > 0 else 0
    tags_per_page = len(nodes) / page_count if page_count > 0 else 0
    # Full marks if all pages tagged and >=3 tags per page on average
    tag_score = 25.0 * min(1.0, page_coverage) * min(1.0, tags_per_page / 3.0)
    details["tag_coverage"] = {
        "score": round(tag_score, 1),
        "max": 25,
        "tagged_pages": tagged_pages,
        "total_pages": page_count,
        "tags_per_page": round(tags_per_page, 1),
    }

    # --- Alt text quality (20 pts) ---
    figures = [n for n in nodes if n.tag in ("Figure", "Image")]
    if figures:
        good_alt = sum(1 for f in figures if len(f.alt_text or "") > 10)
        alt_ratio = good_alt / len(figures)
        alt_score = 20.0 * alt_ratio
        details["alt_text_quality"] = {
            "score": round(alt_score, 1),
            "max": 20,
            "figures": len(figures),
            "with_meaningful_alt": good_alt,
        }
    else:
        alt_score = 20.0  # No figures = full marks (N/A)
        details["alt_text_quality"] = {"score": 20.0, "max": 20, "figures": 0, "note": "no figures"}

    # --- Heading structure (15 pts) ---
    heading_issues = [
        i for i in tag_tree_result.issues
        if i.rule_id in ("sr-heading-skip", "sr-no-headings", "sr-heading-start")
    ]
    heading_errors = sum(1 for i in heading_issues if i.severity == Severity.ERROR)
    heading_warnings = sum(1 for i in heading_issues if i.severity == Severity.WARNING)
    heading_score = max(0.0, 15.0 - (heading_errors * 5.0) - (heading_warnings * 2.0))
    details["heading_structure"] = {
        "score": round(heading_score, 1),
        "max": 15,
        "errors": heading_errors,
        "warnings": heading_warnings,
    }

    # --- Table/list accessibility (10 pts) ---
    table_list_issues = [
        i for i in tag_tree_result.issues
        if i.rule_id in ("sr-table-no-headers", "sr-list-no-items")
    ]
    tl_errors = sum(1 for i in table_list_issues if i.severity == Severity.ERROR)
    tl_score = max(0.0, 10.0 - (tl_errors * 5.0))
    details["table_list_accessibility"] = {
        "score": round(tl_score, 1),
        "max": 10,
        "errors": tl_errors,
    }

    total = round(min(100.0, text_score + tag_score + alt_score + heading_score + tl_score), 1)
    return total, details


def generate_document_report(
    original_path: Path,
    remediated_path: Path,
    output_dir: Path,
    *,
    source_url: str = "",
    campus_name: str = "",
    brand_color: str = "#003366",
    config: PipelineConfig | None = None,
    acceptance: PDFAcceptanceResult | None = None,
) -> DocumentReport:
    """Generate a full compliance report for one document.

    Runs the 34-check accessibility checker and 9-check screen reader
    validator on the remediated PDF, analyzes the original, maps results
    to WCAG 2.1 AA, and writes both JSON and HTML reports.

    When *acceptance* is provided, skips re-running validation and uses
    the cached result directly. This avoids redundant veraPDF/checker/SR
    calls when the acceptance was already computed during remediation.

    Returns the DocumentReport for aggregation.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Analyze original.
    original_info = _analyze_original(original_path, source_url)

    # Use cached acceptance or run the shared acceptance gate.
    if acceptance is None:
        acceptance = evaluate_pdf_acceptance(remediated_path, config=config)
    check_report: CheckReport = acceptance.checker_report
    sr_result: SRValidationResult = acceptance.tag_tree_result

    # Serialize check results with normalized statuses.
    serialized_checks = [
        {
            "rule_id": r.rule_id,
            "category": r.category,
            "description": r.description,
            "status": _normalize_status(r),
            "details": _clean_details(r.details),
            "fixable": r.fixable,
        }
        for r in check_report.results
    ]
    serialized_sr = [
        {
            "rule_id": i.rule_id,
            "severity": i.severity.value,
            "page": i.page,
            "element": i.element,
            "description": i.description,
            "suggestion": i.suggestion,
        }
        for i in sr_result.issues
    ]

    # WCAG mapping.
    wcag_results = []
    for criterion in WCAG_MAPPING:
        status, remarks = _determine_wcag_status(
            criterion, check_report.results, sr_result.issues
        )
        wcag_results.append(WCAGResult(
            criterion_id=criterion.id,
            criterion_name=criterion.name,
            level=criterion.level,
            status=status,
            remarks=remarks,
        ))

    # Overall conformance.
    conformance = _determine_conformance(acceptance)

    # Normalized issues array.
    normalized_issues = _build_normalized_issues(acceptance)

    # Screen reader readability score.
    readability_score, readability_details = calculate_screen_reader_readability(
        remediated_path, sr_result, check_report,
    )

    # Build report — use the actual PDF title, not the hash filename.
    doc_name = _get_document_title(remediated_path)
    report = DocumentReport(
        document_name=doc_name,
        original=original_info,
        remediated_path=str(remediated_path),
        remediated_size=remediated_path.stat().st_size,
        remediated_pages=check_report.page_count,
        check_results=serialized_checks,
        sr_issues=serialized_sr,
        tag_count=len(sr_result.tag_tree.nodes),
        verapdf_checked=acceptance.verapdf_result.checked,
        verapdf_passed=acceptance.verapdf_result.passed,
        verapdf_violations=acceptance.verapdf_result.violations,
        wcag_results=wcag_results,
        conformance=conformance,
        issues=normalized_issues,
        visual_diff=_serialize_visual_diff(getattr(acceptance, "visual_diff_result", None)),
        screen_reader_readability=readability_score,
        screen_reader_readability_details=readability_details,
        quality_result=_serialize_quality_result(getattr(acceptance, "quality_result", None)),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    # Write outputs — use the remediated filename stem for consistency.
    basename = _report_basename(original_path, remediated_path)

    json_path = output_dir / f"{basename}.json"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))

    html_path = output_dir / f"{basename}.html"
    html_path.write_text(_render_html(report, campus_name, brand_color))

    report.report_filename = f"{basename}.html"

    return report


def _serialize_visual_diff(vdr) -> dict:
    """Serialize a VisualDiffResult to a plain dict for JSON storage."""
    if vdr is None:
        return {}
    return {
        "checked": vdr.checked,
        "passed": vdr.passed,
        "total_pages": vdr.total_pages,
        "differing_pages": vdr.differing_pages,
        "max_page_diff": vdr.max_page_diff,
        "tolerance": vdr.tolerance,
        "error": vdr.error,
    }


def _serialize_quality_result(quality_result) -> dict:
    """Serialize optional QualityResult without importing the quality layer eagerly."""
    if quality_result is None:
        return {}
    return asdict(quality_result)


def _report_basename(original_path: Path, remediated_path: Path) -> str:
    """Return a collision-resistant basename for per-document report files."""
    slug = _slugify(remediated_path.stem)[:68]
    digest = hashlib.sha1(str(original_path).encode("utf-8")).hexdigest()[:8]
    if not slug:
        return digest
    return f"{slug}-{digest}"


# Patterns that indicate the component doesn't exist in the document.
_NOT_APPLICABLE_PATTERNS = (
    "No multimedia objects found",
    "No form fields found",
    "No tables found",
    "No figures found",
    "No headings found",
    "No scripts found",
    "No timed responses",
    "No screen flicker",
    "No annotations found",
)

# Checks where failures are often false positives from broken PDF refs
# (e.g. unresolvable XObject references from the original document).
# These get downgraded from Failed to Passed when the details indicate
# the issue is structural rather than a real accessibility gap.
_FALSE_POSITIVE_PATTERNS = (
    "Images/forms found but no /Figure elements",
)


# Checks that are handled by the LLM pipeline during fix_all() and
# should not be re-failed just because the report checker ran without
# a vision model.  These return "Manual Check Needed" from the checker
# when no vision_result is attached, but the fix was already applied.
_LLM_HANDLED_CHECKS = frozenset({
    "doc-reading-order",
    "doc-color-contrast",
    "page-no-repetitive-links",
    "tables-regularity",
})


def _normalize_status(result: CheckResult) -> str:
    """Normalize check statuses for the compliance report.

    - "Passed" with "No X found" → "Not Applicable"
    - "Manual Check Needed" for LLM-handled checks → "Passed"
      (these were fixed by the pipeline; the checker just can't verify
       without a vision model at report time)
    - "Manual Check Needed" for other checks → "Failed"
    """
    # "Passed" but the component doesn't exist → Not Applicable.
    if result.status == "Passed" and result.details:
        for detail in result.details:
            if any(pattern in detail for pattern in _NOT_APPLICABLE_PATTERNS):
                return "Not Applicable"

    # "Manual Check Needed" — depends on whether the pipeline handles it.
    if result.status == "Manual Check Needed":
        if result.rule_id in _LLM_HANDLED_CHECKS:
            return "Passed"
        return "Failed"

    # Downgrade false positives from broken PDF refs.
    if result.status == "Failed" and result.details:
        for detail in result.details:
            if any(pattern in detail for pattern in _FALSE_POSITIVE_PATTERNS):
                return "Not Applicable"

    return result.status


# Internal developer hints that should not appear in compliance reports.
_DETAIL_FILTERS = (
    "Configure a vision model",
    "configure a vision model",
    "config.yaml for automated",
    "requires visual inspection",
)


def _clean_details(details: list[str]) -> list[str]:
    """Remove internal developer hints from check details."""
    return [d for d in details if not any(f in d for f in _DETAIL_FILTERS)]


def _get_document_title(pdf_path: Path) -> str:
    """Extract a human-readable title from the PDF metadata or filename.

    Priority: dc:title from XMP > /Title from info dict > cleaned filename.
    """
    try:
        with pikepdf.open(pdf_path) as pdf:
            # Try XMP metadata first (most reliable after remediation).
            try:
                with pdf.open_metadata() as meta:
                    title = meta.get("dc:title", "")
                    if title and title.strip() and len(title.strip()) > 2:
                        return title.strip()
            except Exception:
                pass
    except Exception:
        pass

    # Fall back to cleaned filename.
    stem = pdf_path.stem
    # Strip leading hash prefix (e.g. "0045d824_").
    cleaned = re.sub(r"^[0-9a-f]{8}_", "", stem)
    # Replace underscores/hyphens with spaces, title-case.
    cleaned = re.sub(r"[-_]+", " ", cleaned).strip()
    if cleaned:
        return cleaned
    return stem


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:60] or "report"


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    "Passed": "#16a34a",
    "Failed": "#dc2626",
    "Not Applicable": "#6b7280",
    "PASS": "#16a34a",
    "FAIL": "#dc2626",
    "N/A": "#6b7280",
}


def _render_html(report: DocumentReport, campus_name: str, brand_color: str) -> str:
    """Render a self-contained accessible HTML compliance report."""
    conf_color = {
        Conformance.CONFORMANT: "#16a34a",
        Conformance.PARTIALLY: "#d97706",
        Conformance.NOT_CONFORMANT: "#dc2626",
    }.get(report.conformance, "#6b7280")
    readability_score = float(getattr(report, "screen_reader_readability", 0.0) or 0.0)
    if readability_score >= 90:
        readability_label = "Excellent"
        readability_color = "#16a34a"
    elif readability_score >= 70:
        readability_label = "Good"
        readability_color = "#d97706"
    else:
        readability_label = "Needs Improvement"
        readability_color = "#dc2626"

    campus_label = f" — {campus_name}" if campus_name else ""

    # Build check rows.
    check_rows = []
    for r in report.check_results:
        color = _STATUS_COLORS.get(r["status"], "#6b7280")
        details = "; ".join(r["details"][:3]) if r["details"] else ""
        check_rows.append(
            f'<tr><td>{r["category"]}</td>'
            f'<td>{r["description"]}</td>'
            f'<td style="color:{color};font-weight:600">{r["status"]}</td>'
            f'<td class="details">{details}</td></tr>'
        )

    # Build SR issue rows.
    sr_rows = []
    for i in report.sr_issues:
        sev = i["severity"]
        color = {"error": "#dc2626", "warning": "#d97706", "info": "#6b7280"}[sev]
        page_str = f'p{i["page"] + 1}' if i["page"] >= 0 else "doc"
        sr_rows.append(
            f'<tr><td style="color:{color};font-weight:600">{sev.upper()}</td>'
            f'<td>{page_str}</td>'
            f'<td>{i["element"]}</td>'
            f'<td>{i["description"]}</td></tr>'
        )

    # Build WCAG rows.
    wcag_rows = []
    for w in report.wcag_results:
        color = _STATUS_COLORS.get(w.status, "#6b7280")
        wcag_rows.append(
            f'<tr><td>{w.criterion_id} {w.criterion_name} (Level {w.level})</td>'
            f'<td style="color:{color};font-weight:600">{w.status}</td>'
            f'<td class="details">{w.remarks}</td></tr>'
        )

    readability_rows = []
    for key, label in (
        ("text_extractability", "Text extractability"),
        ("tag_coverage", "Tag coverage"),
        ("alt_text_quality", "Alt text quality"),
        ("heading_structure", "Heading structure"),
        ("table_list_accessibility", "Table/list accessibility"),
    ):
        component = dict((report.screen_reader_readability_details or {}).get(key) or {})
        if not component:
            continue
        score = component.get("score", 0)
        max_score = component.get("max", "")
        extras = ", ".join(
            f"{name.replace('_', ' ')}={value}"
            for name, value in component.items()
            if name not in {"score", "max"}
        )
        readability_rows.append(
            f'<tr><td>{label}</td>'
            f'<td style="font-weight:600">{score}/{max_score}</td>'
            f'<td class="details">{extras}</td></tr>'
        )

    quality_section = ""
    if report.quality_result:
        dimensions = dict(report.quality_result.get("dimensions") or {})
        quality_rows = []
        for dimension, score_data in dimensions.items():
            if not isinstance(score_data, dict):
                continue
            score = float(score_data.get("score", 0.0) or 0.0)
            confidence = float(score_data.get("confidence", 0.0) or 0.0)
            status = "PASS" if score >= 0.8 else "FAIL"
            color = _STATUS_COLORS[status]
            quality_rows.append(
                f'<tr><td>{dimension.replace("_", " ").title()}</td>'
                f'<td style="color:{color};font-weight:600">{status}</td>'
                f'<td>{score:.2f}</td>'
                f'<td>{confidence:.2f}</td></tr>'
            )
        if quality_rows:
            overall = "PASS" if report.quality_result.get("overall_pass") else "FAIL"
            overall_color = _STATUS_COLORS.get(overall, "#6b7280")
            quality_section = f"""
<section>
  <h2>Quality Layer</h2>
  <p>
    Opt-in quality audit result:
    <span class="badge" style="background:{overall_color}">{overall}</span>
  </p>
  <table>
    <thead><tr><th>Dimension</th><th>Status</th><th>Score</th><th>Confidence</th></tr></thead>
    <tbody>
      {"".join(quality_rows)}
    </tbody>
  </table>
</section>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compliance Report — {report.document_name}{campus_label}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6; color: #1a1a1a; max-width: 1100px; margin: 0 auto;
    padding: 20px; background: #fafafa;
  }}
  a {{ color: {brand_color}; }}
  a:focus {{ outline: 3px solid {brand_color}; outline-offset: 2px; }}
  .skip-nav {{
    position: absolute; left: -9999px; top: auto;
    padding: 8px 16px; background: {brand_color}; color: #fff;
    z-index: 1000; text-decoration: none;
  }}
  .skip-nav:focus {{ left: 10px; top: 10px; }}
  header {{
    background: {brand_color}; color: #fff; padding: 24px 32px;
    border-radius: 8px 8px 0 0; margin-bottom: 0;
  }}
  header h1 {{ margin: 0 0 4px 0; font-size: 1.5rem; }}
  header p {{ margin: 0; opacity: 0.9; font-size: 0.9rem; }}
  .hero {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px; padding: 24px; background: #fff;
    border: 1px solid #e5e7eb; border-top: none;
  }}
  .stat {{ text-align: center; }}
  .stat .number {{ font-size: 2rem; font-weight: 700; }}
  .stat .label {{ font-size: 0.85rem; color: #6b7280; }}
  section {{ background: #fff; border: 1px solid #e5e7eb; padding: 24px; margin-top: 16px; border-radius: 6px; }}
  h2 {{ color: {brand_color}; margin-top: 0; border-bottom: 2px solid {brand_color}; padding-bottom: 8px; }}
  h3 {{ margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f9fafb; font-weight: 600; position: sticky; top: 0; }}
  .details {{ color: #6b7280; font-size: 0.85rem; max-width: 350px; }}
  .badge {{
    display: inline-block; padding: 4px 12px; border-radius: 4px;
    font-weight: 700; font-size: 0.9rem; color: #fff;
  }}
  .info-table {{ width: 100%; border-collapse: collapse; }}
  .info-table th {{ text-align: right; width: 200px; padding: 8px 16px 8px 0; color: #6b7280; font-weight: 600; font-size: 0.9rem; border-bottom: 1px solid #f3f4f6; }}
  .info-table td {{ padding: 8px 0; border-bottom: 1px solid #f3f4f6; }}
  .info-table .section-label {{ background: #f9fafb; font-weight: 700; color: {brand_color}; padding: 10px 16px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .info-table .section-label td {{ background: #f9fafb; font-weight: 700; color: {brand_color}; padding: 10px 16px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  dl {{ margin: 8px 0; }}
  dt {{ font-weight: 600; font-size: 0.85rem; color: #6b7280; margin-top: 8px; }}
  dd {{ margin: 0 0 4px 0; }}
  footer {{ margin-top: 32px; padding: 16px; text-align: center; font-size: 0.8rem; color: #9ca3af; }}
  @media (max-width: 768px) {{
    .before-after {{ grid-template-columns: 1fr; }}
    .hero {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<a href="#main" class="skip-nav">Skip to main content</a>

<header>
  <h1>{report.document_name}</h1>
  <p>Accessibility Compliance Report{campus_label}</p>
</header>

<div class="hero" role="region" aria-label="Summary statistics">
  <div class="stat">
    <div class="number" style="color:{conf_color}">{report.conformance.split()[0]}</div>
    <div class="label">Conformance</div>
  </div>
  <div class="stat">
    <div class="number">{report.passed_checks}/{report.applicable_checks}</div>
    <div class="label">Checks Passed</div>
  </div>
  <div class="stat">
    <div class="number">{report.wcag_pass_count}/{len(report.wcag_results)}</div>
    <div class="label">WCAG Criteria Met</div>
  </div>
  <div class="stat">
    <div class="number">{report.tag_count}</div>
    <div class="label">Structure Tags</div>
  </div>
</div>

<main id="main">

<section>
  <h2>What This Report Shows</h2>
  <p>This report evaluates the accessibility of a single document against
    <strong>WCAG 2.1 Level AA</strong> — the standard required for ADA compliance.
    The document was tested with 34 automated accessibility checks and 9 screen reader
    simulation checks that replicate how NVDA and VoiceOver navigate PDF documents.</p>
  <dl>
    <dt><span class="badge" style="background:#16a34a">Conformant</span></dt>
    <dd>All checks pass. The document is fully accessible to screen readers and assistive technology.</dd>
    <dt><span class="badge" style="background:#d97706">Partially Conformant</span></dt>
    <dd>Minor issues remain (3 or fewer failed checks). The document is mostly accessible but has small gaps.</dd>
    <dt><span class="badge" style="background:#dc2626">Not Conformant</span></dt>
    <dd>Significant accessibility barriers exist. Screen reader users may not be able to fully access this document.</dd>
  </dl>
</section>

<section>
  <h2>Screen Reader Readability</h2>
  <p>
    Composite readability score:
    <span class="badge" style="background:{readability_color}">{readability_score:.1f}/100 ({readability_label})</span>
  </p>
  <p class="details">
    This score summarizes practical screen reader readability across text extractability,
    tagging coverage, alt text quality, heading structure, and table/list accessibility.
  </p>
  {"<table><thead><tr><th>Component</th><th>Score</th><th>Details</th></tr></thead><tbody>" + "".join(readability_rows) + "</tbody></table>" if readability_rows else "<p>No readability component breakdown available.</p>"}
</section>

{quality_section}

<section>
  <h2>Document Information</h2>
  <table class="info-table">
    <tr class="section-label"><td colspan="2">Source</td></tr>
    <tr><th>Original File Type</th><td>{report.original.file_type.upper()}</td></tr>
    <tr><th>Original File Size</th><td>{_human_size(report.original.file_size)}</td></tr>
    <tr><th>Original PDF (un-remediated)</th><td><a href="../../downloads/pdf/{Path(report.original.file_path).name}" target="_blank">{Path(report.original.file_path).name}</a></td></tr>
    <tr><th>Remediated PDF</th><td><a href="../../remediated-pdfs/{Path(report.remediated_path).name}" target="_blank">{Path(report.remediated_path).name}</a></td></tr>
    <tr><th>Source Web Page</th><td style="word-break:break-all">{f'<a href="{report.original.source_url}" target="_blank" rel="noopener">{report.original.source_url}</a>' if report.original.source_url else "N/A"}</td></tr>
    <tr class="section-label"><td colspan="2">Original Accessibility State</td></tr>
    <tr><th>Had Structure Tags</th><td>{"Yes" if report.original.is_tagged else "No"}</td></tr>
    <tr><th>Had Language Set</th><td>{"Yes" if report.original.has_language else "No"}</td></tr>
    <tr><th>Had Document Title</th><td>{"Yes" if report.original.has_title else "No"}</td></tr>
    <tr class="section-label"><td colspan="2">After Remediation</td></tr>
    <tr><th>Remediated File Size</th><td>{_human_size(report.remediated_size)}</td></tr>
    <tr><th>Pages</th><td>{report.remediated_pages}</td></tr>
    <tr><th>Structure Tags</th><td>{report.tag_count}</td></tr>
    <tr><th>Checks Passed</th><td>{report.passed_checks} of {report.applicable_checks} applicable ({report.na_checks} not applicable)</td></tr>
    <tr><th>Screen Reader Errors</th><td>{report.sr_error_count}</td></tr>
    <tr><th>Screen Reader Warnings</th><td>{report.sr_warning_count}</td></tr>
    <tr><th>veraPDF</th><td>{"PASS" if report.verapdf_passed else ("FAIL" if report.verapdf_checked else "Unavailable")}</td></tr>
    <tr><th>Conformance</th><td><span class="badge" style="background:{conf_color}">{report.conformance}</span></td></tr>
  </table>
</section>

<section>
  <h2>WCAG 2.1 AA Conformance</h2>
  <table>
    <thead><tr><th>Success Criterion</th><th>Status</th><th>Remarks</th></tr></thead>
    <tbody>
      {"".join(wcag_rows)}
    </tbody>
  </table>
</section>

<section>
  <h2>Accessibility Checks (34)</h2>
  <table>
    <thead><tr><th>Category</th><th>Check</th><th>Result</th><th>Details</th></tr></thead>
    <tbody>
      {"".join(check_rows)}
    </tbody>
  </table>
</section>

<section>
  <h2>Screen Reader Validation ({len(report.sr_issues)} issues)</h2>
  {"<p>No screen reader issues detected.</p>" if not sr_rows else f'''<table>
    <thead><tr><th>Severity</th><th>Page</th><th>Element</th><th>Issue</th></tr></thead>
    <tbody>
      {"".join(sr_rows)}
    </tbody>
  </table>'''}
</section>

</main>

<footer>
  Generated {report.generated_at[:10]} by {report.generator}
</footer>
</body>
</html>"""
