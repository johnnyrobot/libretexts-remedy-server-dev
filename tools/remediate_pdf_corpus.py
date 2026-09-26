"""Remediate and audit the desktop PDF corpus.

This is a local operations helper, not part of the HTTP API. It runs the same
engine calls used by the API (`fix_and_verify` + `evaluate_pdf_acceptance`) and
writes a JSONL manifest so long corpus runs can be resumed.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_remedy.config import load_config
from project_remedy.pdf_acceptance import evaluate_pdf_acceptance
from project_remedy.pdf_fixer import fix_and_verify
from project_remedy.tag_tree_reader import Severity


DEFAULT_INPUT_ROOTS = [
    Path.home() / "Desktop" / "Chicano Studies Docs",
    Path.home() / "Desktop" / "sample pdfs",
    Path.home() / "Desktop" / "Syllabus Examples",
]
DEFAULT_OUTPUT_ROOT = Path.home() / "Desktop" / "remediated_pdfs"


@dataclass
class CorpusRecord:
    source: str
    output: str
    status: str
    elapsed_seconds: float
    acceptance_passed: bool
    clean: bool
    checker_failures: list[dict[str, Any]]
    manual_checks: list[dict[str, Any]]
    screen_reader_errors: list[dict[str, Any]]
    verapdf_passed: bool
    verapdf_violations: list[dict[str, Any]]
    non_blocking_verapdf_warnings: int
    visual_diff: dict[str, Any] | None
    warning_reasons: list[str]
    fix_changes: list[str]
    fix_skipped: list[str]
    error: str = ""
    completed_at: str = ""


def _source_files(input_roots: list[Path]) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for root in input_roots:
        for path in sorted(root.rglob("*.pdf")):
            files.append((root, path))
    return files


def _output_path(output_root: Path, root: Path, source: Path) -> Path:
    return output_root / root.name / source.relative_to(root)


def _manifest_done(manifest_path: Path) -> set[str]:
    done: set[str] = set()
    for source, record in _manifest_latest(manifest_path).items():
        if record.get("status") in {"clean", "accepted"} and record.get("clean"):
            done.add(source)
    return done


def _manifest_latest(manifest_path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not manifest_path.exists():
        return latest
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        source = str(record.get("source", ""))
        if source:
            latest[source] = record
    return latest


def _manual_checks(acceptance) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": result.rule_id,
            "description": result.description,
            "details": list(result.details),
        }
        for result in acceptance.checker_report.results
        if result.status == "Manual Check Needed"
    ]


def _checker_failures(acceptance) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": result.rule_id,
            "description": result.description,
            "details": list(result.details),
        }
        for result in acceptance.checker_failures
        if not acceptance._is_source_font_checker_failure(result)
    ]


def _screen_reader_errors(acceptance) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": issue.rule_id,
            "description": issue.description,
            "page": issue.page,
            "element": issue.element,
        }
        for issue in acceptance.tag_tree_result.issues
        if issue.severity == Severity.ERROR
    ]


def _visual_diff(acceptance) -> dict[str, Any] | None:
    result = acceptance.visual_diff_result
    if result is None:
        return None
    return {
        "checked": result.checked,
        "passed": result.passed,
        "total_pages": result.total_pages,
        "differing_pages": [page + 1 for page in result.differing_pages],
        "max_page_diff": result.max_page_diff,
        "error": result.error,
    }


def _is_clean(acceptance) -> bool:
    manual_checks = _manual_checks(acceptance)
    checker_failures = _checker_failures(acceptance)
    screen_reader_errors = _screen_reader_errors(acceptance)
    visual = acceptance.visual_diff_result
    visual_ok = visual is None or not visual.checked or visual.passed
    verapdf_ok = (
        not acceptance.verapdf_result.checked
        or acceptance.verapdf_result.passed
        or len(acceptance.non_blocking_verapdf_warnings)
        == len(acceptance.verapdf_result.violations)
    )
    return (
        acceptance.openable
        and acceptance.passed
        and not checker_failures
        and not manual_checks
        and not screen_reader_errors
        and visual_ok
        and verapdf_ok
    )


def _evaluate(source: Path, output: Path, config) -> tuple[Any, bool]:
    acceptance = evaluate_pdf_acceptance(output, config=config, original_path=source)
    return acceptance, _is_clean(acceptance)


def _record(
    *,
    source: Path,
    output: Path,
    status: str,
    elapsed_seconds: float,
    acceptance,
    clean: bool,
    fix_changes: list[str],
    fix_skipped: list[str],
    error: str = "",
) -> CorpusRecord:
    return CorpusRecord(
        source=str(source),
        output=str(output),
        status=status,
        elapsed_seconds=round(elapsed_seconds, 2),
        acceptance_passed=bool(acceptance and acceptance.passed),
        clean=clean,
        checker_failures=[] if acceptance is None else _checker_failures(acceptance),
        manual_checks=[] if acceptance is None else _manual_checks(acceptance),
        screen_reader_errors=[] if acceptance is None else _screen_reader_errors(acceptance),
        verapdf_passed=bool(acceptance and acceptance.verapdf_result.passed),
        verapdf_violations=[] if acceptance is None else acceptance.verapdf_result.violations,
        non_blocking_verapdf_warnings=(
            0 if acceptance is None else len(acceptance.non_blocking_verapdf_warnings)
        ),
        visual_diff=None if acceptance is None else _visual_diff(acceptance),
        warning_reasons=[] if acceptance is None else list(acceptance.warning_reasons),
        fix_changes=fix_changes,
        fix_skipped=fix_skipped,
        error=error,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _append_record(manifest_path: Path, record: CorpusRecord) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        fh.flush()


def run(args: argparse.Namespace) -> int:
    input_roots = [Path(root).expanduser() for root in args.input_root]
    output_root = Path(args.output_root).expanduser()
    manifest_path = Path(args.manifest).expanduser()
    config = load_config()
    fix_config = (
        None
        if os.environ.get("PDF_CORPUS_FIX_WITHOUT_VISION", "").lower()
        in {"1", "true", "yes"}
        else config
    )
    latest_records = _manifest_latest(manifest_path) if args.resume else {}
    done = _manifest_done(manifest_path) if args.resume else set()
    files = _source_files(input_roots)
    limit = args.limit if args.limit and args.limit > 0 else None
    selected = files[:limit] if limit else files

    failures = 0
    for index, (root, source) in enumerate(selected, 1):
        output = _output_path(output_root, root, source)
        if str(source) in done:
            print(f"[{index}/{len(selected)}] SKIP clean {source.name}", flush=True)
            continue

        print(f"[{index}/{len(selected)}] {source}", flush=True)
        start = time.time()
        acceptance = None
        fix_changes: list[str] = []
        fix_skipped: list[str] = []
        try:
            latest = latest_records.get(str(source), {})
            known_failed = (
                not args.audit_only
                and latest.get("status") in {"failed", "error"}
                and not latest.get("clean")
            )
            if args.audit_only and not output.exists():
                raise FileNotFoundError(f"missing output: {output}")

            if not args.audit_only and (args.force or known_failed or not output.exists()):
                output.parent.mkdir(parents=True, exist_ok=True)
                input_path = source
                print(f"    stage=fix input={input_path.name}", flush=True)
                report = fix_and_verify(
                    input_path,
                    output,
                    config=fix_config,
                    original_path=source,
                    conformance_repair=True,
                )
                fix_changes.extend(report.changes)
                fix_skipped.extend(report.skipped)

            print("    stage=acceptance", flush=True)
            acceptance, clean = _evaluate(source, output, config)
            if not clean and not args.audit_only:
                print("    stage=refix", flush=True)
                report = fix_and_verify(
                    output,
                    output,
                    config=fix_config,
                    original_path=source,
                    conformance_repair=True,
                )
                fix_changes.extend(report.changes)
                fix_skipped.extend(report.skipped)
                print("    stage=reacceptance", flush=True)
                acceptance, clean = _evaluate(source, output, config)

            status = "clean" if clean else "failed"
            if not clean:
                failures += 1
            record = _record(
                source=source,
                output=output,
                status=status,
                elapsed_seconds=time.time() - start,
                acceptance=acceptance,
                clean=clean,
                fix_changes=fix_changes,
                fix_skipped=fix_skipped,
            )
        except Exception as exc:  # noqa: BLE001 - corpus runner records every failure
            failures += 1
            record = _record(
                source=source,
                output=output,
                status="error",
                elapsed_seconds=time.time() - start,
                acceptance=acceptance,
                clean=False,
                fix_changes=fix_changes,
                fix_skipped=fix_skipped,
                error=str(exc),
            )

        _append_record(manifest_path, record)
        print(
            f"    -> {record.status} clean={record.clean} "
            f"failures={len(record.checker_failures)} "
            f"manual={len(record.manual_checks)} "
            f"sr={len(record.screen_reader_errors)} "
            f"elapsed={record.elapsed_seconds}s",
            flush=True,
        )

    print(f"Done. failures={failures} manifest={manifest_path}", flush=True)
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", action="append", default=[])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_OUTPUT_ROOT / "corpus_acceptance_manifest.jsonl"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.input_root:
        args.input_root = [str(root) for root in DEFAULT_INPUT_ROOTS]
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
