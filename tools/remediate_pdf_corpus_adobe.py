"""Remediate PDFs in the Chicano Studies corpus with Adobe Accessibility checks.

Workflow per document:
1. Run the built-in fixer on the source PDF.
2. Run Adobe Accessibility checker.
3. If there are remaining non-allowed manual/check failures, apply targeted fixes
   (`page-content-tagged`, `alt-associated`, `alt-elements`) and retry.
4. Repeat until clean or max attempts reached.

The script is designed for one-by-one corpus remediation with resume support:
- outputs are written to ``output_root/<filename>.pdf``
- manifest rows are written to JSONL for auditability
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import pikepdf

# Ensure this script always imports the local project code, not any globally
# installed remedy package.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from project_remedy.adobe_checker import AdobeCheckResult, check_accessibility
from project_remedy.config import load_config
from project_remedy.pdf_checker import PDFAccessibilityChecker
from project_remedy.pdf_fixer import (
    fix_all,
    fix_alt_text_elements,
    fix_accessibility_permission,
    fix_alt_hides_annotation,
    fix_screen_flicker,
    fix_remove_scripts,
    fix_timed_responses,
    fix_char_encoding,
    fix_repetitive_links,
    fix_figures_alt_text,
    fix_link_annotations,
    fix_annotation_descriptions,
    fix_annotations_tagged,
    fix_tab_order,
    fix_redundant_alt_text,
    fix_orphan_alt_text,
    fix_mark_info,
    fix_bookmarks,
    fix_image_only_pdf,
    fix_untagged_content,
    fix_marked_content_missing_mcids,
    fix_page_retag,
    fix_table_summary,
    fix_table_regularity,
    fix_heading_nesting,
    _rebuild_pdf_with_tesseract_ocr,
)

DEFAULT_INPUT_ROOT = Path.home() / "Desktop" / "Chicano Studies Docs"
DEFAULT_OUTPUT_ROOT = Path.home() / "Desktop" / "Chicano-remedy-server-v2"
ALLOWED_MANUAL_CHECKS = {
    ("document", "logical reading order"),
    ("document", "color contrast"),
}
ALLOWED_MANUAL_CHECK_IDS = {
    "doc-reading-order",
    "doc-color-contrast",
    "doc-use-of-color",
}
ADOBE_CHECK_TO_FIX: dict[str, str] = {
    "page-content-tagged": "page-content-tagged",
    "doc-tagged": "doc-tagged",
    "doc-language": "doc-language",
    "doc-display-title": "doc-display-title",
    "tagged content": "page-content-tagged",
    "associated with content": "alt-associated",
    "nested alternate text": "alt-redundant",
    "nested alternate text and layout": "alt-redundant",
    "figures alternate text": "alt-figures",
    "figure alternate text": "alt-figures",
    "hides annotation": "alt-hides-annotation",
    "hides annotations": "alt-hides-annotation",
    "hidden annotation": "alt-hides-annotation",
    "summary": "tables-summary",
    "table summary": "tables-summary",
    "tables summary": "tables-summary",
    "tables-regularity": "tables-regularity",
    "other elements alternate text": "alt-elements",
    "accessibility permission flag": "doc-accessibility-permission",
    "image-only pdf": "doc-not-image-only",
    "tagged pdf": "doc-tagged",
    "logical reading order": "doc-reading-order",
    "bookmarks": "doc-bookmarks",
    "tagged annotations": "page-annotations-tagged",
    "character encoding": "page-char-encoding",
    "tagged multimedia": "page-multimedia-tagged",
    "scripts": "page-no-scripts",
    "timed responses": "page-no-timed-responses",
    "navigation links": "page-no-repetitive-links",
    "appropriate nesting": "headings-nesting",
}


@dataclass
class CorpusRecord:
    source: str
    output: str
    status: str
    attempts: int
    checked: bool
    passed: bool
    issues: list[dict[str, Any]]
    manual_checks: list[dict[str, Any]]
    error: str = ""
    reported_at: str = ""


def _normalize(v: object) -> str:
    return str(v or "").strip().lower()


def _safe_key(record: dict[str, Any], *keys: str) -> tuple[str, str]:
    return tuple(_normalize(record.get(k, "")) for k in keys)


def _is_allowed_manual(issue: dict[str, Any]) -> bool:
    if _normalize(issue.get("check")) in ALLOWED_MANUAL_CHECK_IDS:
        return True
    return _safe_key(issue, "category", "check") in ALLOWED_MANUAL_CHECKS


def _is_manual_status(status: str) -> bool:
    status_norm = _normalize(status)
    return (
        status_norm.startswith("needs manual")
        or status_norm == "manual check needed"
        or status_norm == "manual"
    )


_NON_BLOCKING_STATUSES = {"skipped", "n/a", "not applicable"}


def _issue_is_blocking(issue: dict[str, Any]) -> bool:
    status = _normalize(issue.get("status"))
    if status == "failed":
        return True
    if status.startswith("pass") or status in _NON_BLOCKING_STATUSES:
        return False
    # "manual check needed", "needs manual ...", or any other status containing
    # "manual" — blocking unless the issue is on the allow-list.
    if "manual" in status:
        return not _is_allowed_manual(issue)
    # Conservative: unknown status treated as blocking.
    return True


_ADOBE_FIX_RULE_IDS = frozenset(ADOBE_CHECK_TO_FIX.values())


def _adobe_to_fix_rule(issue: dict[str, Any]) -> str | None:
    check = _normalize(issue.get("check"))
    if check in ADOBE_CHECK_TO_FIX:
        return ADOBE_CHECK_TO_FIX[check]

    # Local checker emits canonical rule ids directly.
    if check in _ADOBE_FIX_RULE_IDS:
        return check

    # Fallback for slightly different wording from future reports.
    for key, rule in ADOBE_CHECK_TO_FIX.items():
        if key in check:
            return rule
    return None


def _local_checker_issues(pdf_path: Path) -> list[dict[str, Any]]:
    report = PDFAccessibilityChecker(pdf_path).run_all()
    issues: list[dict[str, Any]] = []
    for result in report.results:
        if result.status == "Passed":
            continue
        check = result.rule_id
        normalized_check = _normalize(check)
        if normalized_check == "doc-use-of-color":
            check = "doc-color-contrast"
        status = result.status
        if status == "Failed" and _normalize(check) in ALLOWED_MANUAL_CHECK_IDS:
            status = "Needs manual check"
        if status == "Manual Check Needed":
            status = "Needs manual check"
        issues.append(
            {
                "category": result.category,
                "check": check,
                "status": status,
                "description": result.description,
                "details": result.details,
            }
        )
    return issues


def _is_local_fallback_allowed(exc: AdobeCheckResult, output: Path) -> tuple[bool, list[dict[str, Any]]]:
    error = _normalize(exc.error).lower()
    if not exc.error:
        return False, []
    quota_terms = (
        "quota exceeded",
        "429",
        "too many requests",
    )
    if not any(term in error for term in quota_terms):
        return False, []
    try:
        issues = _local_checker_issues(output)
    except Exception:
        return False, []
    return True, issues


def _rebuild_char_encoding_with_ocr(pdf_path: Path) -> tuple[bool, str]:
    """Run a Tesseract OCR rebuild for stubborn character-encoding failures."""
    with TemporaryDirectory(prefix="project_remedy_char_ocr_") as temp_dir:
        try:
            rebuilt = _rebuild_pdf_with_tesseract_ocr(
                pdf_path,
                Path(temp_dir),
            )
        except Exception as exc:
            return False, f"OCR rebuild failed: {exc}"

        shutil.copyfile(rebuilt, pdf_path)
        return True, "Rebuilt searchable text layer with OCR"


def _rebuild_and_refix_char_encoding_with_ocr(pdf_path: Path) -> tuple[bool, str]:
    """OCR rebuild and then run full fixer pass to restore structure."""
    ok, msg = _rebuild_char_encoding_with_ocr(pdf_path)
    if not ok:
        return False, msg

    try:
        fix_all(
            pdf_path,
            pdf_path,
            config=None,
        )
    except Exception as exc:
        return False, f"OCR rebuild succeeded but full fixer pass failed: {exc}"

    return True, "Rebuilt searchable text layer with OCR and reapplied full fixer"


def _fix_page_content_tagged(pdf: "pikepdf.Pdf") -> list[str]:
    """Tag untagged page content, falling back through MCID and retag passes."""
    return (
        fix_untagged_content(pdf)
        or fix_marked_content_missing_mcids(pdf)
        or fix_page_retag(pdf)
        or []
    )


# Rule -> single-arg fixer that takes a pikepdf.Pdf and returns the change list.
# Order is preserved when iterating; matches the prior if-chain ordering.
_RULE_FIXERS: tuple[tuple[str, "Callable[[pikepdf.Pdf], list[str]]"], ...] = (
    ("page-content-tagged", _fix_page_content_tagged),
    ("alt-associated", lambda pdf: fix_orphan_alt_text(pdf, force=True, associated_only=True)),
    ("alt-elements", fix_alt_text_elements),
    ("alt-figures", fix_figures_alt_text),
    ("alt-redundant", fix_redundant_alt_text),
    ("alt-hides-annotation", lambda pdf: fix_alt_hides_annotation(pdf, force=True)),
    ("page-no-flicker", fix_screen_flicker),
    ("page-no-scripts", fix_remove_scripts),
    ("page-no-timed-responses", fix_timed_responses),
    ("page-char-encoding", fix_char_encoding),
    ("page-no-repetitive-links", fix_repetitive_links),
    ("page-annotations-tagged", fix_annotations_tagged),
    ("page-link-contents", fix_link_annotations),
    ("page-annotation-contents", fix_annotation_descriptions),
    ("page-tab-order", fix_tab_order),
    ("tables-summary", fix_table_summary),
    ("tables-regularity", fix_table_regularity),
    ("doc-accessibility-permission", fix_accessibility_permission),
    ("doc-not-image-only", fix_image_only_pdf),
    ("doc-tagged", fix_mark_info),
    ("doc-bookmarks", fix_bookmarks),
    ("headings-nesting", fix_heading_nesting),
)


def _apply_targeted_fixes(pdf_path: Path, rules: set[str]) -> tuple[bool, list[str]]:
    if not rules:
        return False, []
    changes: list[str] = []

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        for rule, fixer in _RULE_FIXERS:
            if rule not in rules:
                continue
            added = fixer(pdf) or []
            if added:
                changes.extend(added)

        if changes:
            pdf.save(str(pdf_path))

    return bool(changes), changes


_STRUCTURAL_RECOVERY_RULES = {
    "doc-tagged",
    "doc-language",
    "doc-display-title",
    "page-content-tagged",
    "page-tab-order",
}


def _load_manifest(path: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    if not path.exists():
        return records

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        source = str(payload.get("source") or payload.get("input_path", ""))
        if source:
            records[source] = payload
    return records


def _manifest_path_for(output_root: Path) -> Path:
    return output_root / "adobe_goal_manifest.jsonl"


def _append_manifest(path: Path, record: CorpusRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def run_corpus(
    input_root: Path,
    output_root: Path,
    *,
    manifest_path: Path,
    max_attempts: int = 4,
    limit: int | None = None,
    resume: bool = False,
    force: bool = False,
) -> int:
    # Ensure .env credentials are loaded regardless of caller environment.
    load_config()

    # Objective-specific policy: allow deep fixes on larger documents
    # that are otherwise skipped to protect latency.
    os.environ.setdefault("PDF_LARGE_DOC_DEEP_FIXES", "1")
    os.environ.setdefault("PDF_UNTAGGED_CONTENT_ALLOW_LARGE", "1")
    os.environ.setdefault("PDF_CHAR_ENCODING_ALLOW_LARGE", "1")

    manifest_rows = _load_manifest(manifest_path) if resume else {}
    files = sorted(input_root.rglob("*.pdf"))
    if limit is not None:
        files = files[: max(0, limit)]

    failures = 0
    done = {
        source for source, row in manifest_rows.items()
        if row.get("status") == "clean"
        and row.get("passed", False)
    } if resume else set()

    for index, source in enumerate(files, 1):
        output = output_root / source.name
        if not force and str(source) in done:
            print(f"[{index}/{len(files)}] SKIP {source.name}")
            continue

        print(f"[{index}/{len(files)}] PROCESS {source.name}")
        start = time.time()
        attempts = 0
        record_status = "blocked"
        record_error = ""
        all_issues: list[dict[str, Any]] = []
        manual_checks: list[dict[str, Any]] = []
        checked = False
        passed = False

        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            if force or not output.exists():
                fix_all(
                    source,
                    output,
                    config=None,
                )
            ocr_rebuilt_once = False

            for cycle in range(max_attempts):
                attempts = cycle + 1
                adobe: AdobeCheckResult = check_accessibility(output)
                checked = adobe.checked
                issues = []
                if adobe.checked:
                    issues = adobe.issues
                else:
                    fallback_allowed, local_issues = _is_local_fallback_allowed(adobe, output)
                    if not fallback_allowed:
                        raise RuntimeError(adobe.error or "Adobe check failed")
                    checked = True
                    issues = local_issues
                    print("    fallback: using local checker (Adobe quota error)")

                blocking_issues = [issue for issue in issues if _issue_is_blocking(issue)]
                manual_only = [
                    issue for issue in issues
                    if _is_manual_status(issue.get("status", "")) and _is_allowed_manual(issue)
                ]

                all_issues = [
                    {
                        "category": issue.get("category", ""),
                        "check": issue.get("check", ""),
                        "status": issue.get("status", ""),
                        "description": issue.get("description", ""),
                    }
                    for issue in blocking_issues + manual_only
                ]
                manual_checks = [
                    {
                        "category": issue.get("category", ""),
                        "check": issue.get("check", ""),
                        "status": issue.get("status", ""),
                        "description": issue.get("description", ""),
                    }
                    for issue in manual_only
                ]

                if not blocking_issues:
                    # Only allowed manual checks remain.
                    passed = True
                    record_status = "clean"
                    break

                # Map remaining blocking issues to our fixer functions.
                fix_rules = set()
                for issue in blocking_issues:
                    rule = _adobe_to_fix_rule(issue)
                    if rule:
                        fix_rules.add(rule)

                if "page-char-encoding" in fix_rules and not ocr_rebuilt_once:
                    ocr_rebuilt_once = True
                    changed, message = _rebuild_and_refix_char_encoding_with_ocr(output)
                    if changed:
                        print(
                            f"    ocr-rebuild retry={attempts} "
                            f"message={message}"
                        )
                        continue
                    print(f"    ocr-rebuild failed retry={attempts}: {message}")

                if not fix_rules:
                    record_error = "No mapped fixer for blocking Adobe issue(s)"
                    break
                if attempts >= max_attempts:
                    record_error = f"Reached max attempts with unresolved issues: {sorted(fix_rules)}"
                    break

                changed, details = _apply_targeted_fixes(output, fix_rules)
                if not changed and fix_rules.intersection(_STRUCTURAL_RECOVERY_RULES):
                    try:
                        full_fix = fix_all(output, output, config=None)
                        if full_fix.changes:
                            details.extend(full_fix.changes)
                            changed = True
                            print(
                                f"    full-repair retry={attempts} "
                                f"changes={len(full_fix.changes)}"
                            )
                    except Exception as exc:
                        print(f"    full-repair failed: {exc}")
                if not changed:
                    record_error = (
                        f"Blocking rules unresolved and no fixer output: {sorted(fix_rules)}"
                    )
                    break
                print(f"    retry={attempts} rules={sorted(fix_rules)} changes={len(details)}")

            if passed:
                print(f"    status=PASS attempts={attempts}")
            else:
                print(f"    status={record_status} attempts={attempts} issues={len(all_issues)}")
                failures += 1

        except Exception as exc:
            failures += 1
            record_error = str(exc)
            record_status = "error"
            print(f"    ERROR {record_error}")
        finally:
            _append_manifest(
                manifest_path,
                CorpusRecord(
                    source=str(source),
                    output=str(output),
                    status=record_status,
                    attempts=attempts,
                    checked=checked,
                    passed=passed,
                    issues=all_issues,
                    manual_checks=manual_checks,
                    error=record_error,
                    reported_at=datetime.now(timezone.utc).isoformat(),
                ),
            )
            print(f"    completed in {time.time() - start:.2f}s")

    print(f"done. manifest={manifest_path}")
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else _manifest_path_for(output_root)
    )
    limit = args.limit if args.limit > 0 else None

    rc = run_corpus(
        input_root,
        output_root,
        manifest_path=manifest_path,
        max_attempts=max(1, args.max_attempts),
        limit=limit,
        resume=args.resume,
        force=args.force,
    )
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
