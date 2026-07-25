"""No-dependency coverage gate for the quality-layer modules.

This intentionally uses Python's stdlib ``trace`` module instead of adding a
coverage dependency. It is narrower than coverage.py: it measures execution of
AST statement lines in the quality-layer source files while running the
quality-focused pytest suite.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
import trace
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TARGETS = (
    "backend/app/quality_routes.py",
    "backend/app/quality_calibration.py",
    "src/project_remedy/quality_judges",
    "src/project_remedy/behavioral_proxies",
    "src/project_remedy/vision_planner/scorer.py",
    "src/project_remedy/vision_planner/experiment_store.py",
    "src/project_remedy/vision_planner/proposer.py",
    "src/project_remedy/vision_planner/quality_evaluation.py",
    "tools/annotate_corpus.py",
    "tools/calibrate_judges.py",
    "tools/capture_corpus_snapshots.py",
    "tools/sample_quality_reviews.py",
    "tools/verify_behavioral_corpus.py",
    "tools/verify_corpus_snapshots.py",
)

DEFAULT_PYTEST_ARGS = (
    "-q",
    "tests/quality_judges/shared",
    "tests/behavioral_proxies/shared",
    "tests/quality_judges/pdf",
    "tests/quality_judges/office",
    "tests/behavioral_proxies/pdf",
    "tests/behavioral_proxies/office",
    "tests/corpus",
    "tests/api/test_quality_routes.py",
    "tests/api/test_quality_opt_in_routes.py",
    "tests/vision_planner/test_quality_evaluation.py",
    "tests/vision_planner/test_quality_metrics_extension.py",
    "tests/vision_planner/test_proposer_dimension_aware.py",
    "tests/test_compliance_report_quality.py",
    "tests/test_engine_quality_opt_in.py",
    "tests/test_ollama_client_quality.py",
)


def _require_percent_threshold(value: float) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError("threshold must be finite")
    if numeric < 0.0 or numeric > 100.0:
        raise ValueError("threshold must be between 0 and 100")
    return numeric


@dataclass(frozen=True)
class FileCoverage:
    path: str
    covered_lines: int
    executable_lines: int
    percent: float


@dataclass(frozen=True)
class CoverageSummary:
    covered_lines: int
    executable_lines: int
    percent: float
    threshold: float
    passed: bool
    pytest_exit_code: int
    files: list[FileCoverage]

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered_lines": self.covered_lines,
            "executable_lines": self.executable_lines,
            "percent": self.percent,
            "threshold": self.threshold,
            "passed": self.passed,
            "pytest_exit_code": self.pytest_exit_code,
            "files": [
                {
                    "path": item.path,
                    "covered_lines": item.covered_lines,
                    "executable_lines": item.executable_lines,
                    "percent": item.percent,
                }
                for item in self.files
            ],
        }


def target_python_files(targets: tuple[str, ...] = DEFAULT_TARGETS) -> list[Path]:
    """Resolve quality-layer Python source files from the default target set."""
    files: list[Path] = []
    for target in targets:
        path = REPO_ROOT / target
        if path.is_dir():
            files.extend(
                item
                for item in sorted(path.rglob("*.py"))
                if item.name != "__init__.py" and "__pycache__" not in item.parts
            )
        elif path.exists():
            files.append(path)
    return files


def executable_statement_lines(path: Path) -> set[int]:
    """Return AST statement start lines used as the coverage denominator."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt | ast.ExceptHandler) and hasattr(node, "lineno"):
            lines.add(node.lineno)
    return lines


def run_quality_tests_under_trace(pytest_args: tuple[str, ...]) -> tuple[int, dict[tuple[str, int], int]]:
    """Run pytest with tracing enabled and return pytest exit code plus counts."""
    tracer = trace.Trace(
        count=True,
        trace=False,
        ignoredirs=(str(REPO_ROOT / ".venv"),),
    )
    namespace: dict[str, Any] = {"pytest_args": list(pytest_args)}
    try:
        tracer.runctx(
            "import pytest\npytest_exit_code = pytest.main(pytest_args)",
            namespace,
            namespace,
        )
    except SystemExit as exc:
        namespace["pytest_exit_code"] = int(exc.code or 0)
    return int(namespace.get("pytest_exit_code", 0)), tracer.results().counts


def summarize_coverage(
    *,
    files: list[Path],
    counts: dict[tuple[str, int], int],
    threshold: float,
    pytest_exit_code: int,
) -> CoverageSummary:
    """Build aggregate and per-file statement coverage from trace counts."""
    threshold = _require_percent_threshold(threshold)
    executable_by_file = {
        str(path.resolve()): executable_statement_lines(path)
        for path in files
    }
    executed_by_file: dict[str, set[int]] = {
        path: set()
        for path in executable_by_file
    }

    for (filename, line_number), _count in counts.items():
        resolved = str(Path(filename).resolve())
        executable = executable_by_file.get(resolved)
        if executable is not None and line_number in executable:
            executed_by_file[resolved].add(line_number)

    file_rows: list[FileCoverage] = []
    for path in sorted(executable_by_file):
        executable = len(executable_by_file[path])
        covered = len(executed_by_file[path])
        percent = round((covered / executable * 100.0) if executable else 100.0, 2)
        file_rows.append(
            FileCoverage(
                path=str(Path(path).relative_to(REPO_ROOT)),
                covered_lines=covered,
                executable_lines=executable,
                percent=percent,
            )
        )

    total_executable = sum(row.executable_lines for row in file_rows)
    total_covered = sum(row.covered_lines for row in file_rows)
    total_percent = round(
        (total_covered / total_executable * 100.0) if total_executable else 100.0,
        2,
    )
    return CoverageSummary(
        covered_lines=total_covered,
        executable_lines=total_executable,
        percent=total_percent,
        threshold=threshold,
        passed=pytest_exit_code == 0 and total_percent >= threshold,
        pytest_exit_code=pytest_exit_code,
        files=file_rows,
    )


def _cmd_check(args: argparse.Namespace) -> int:
    threshold = _require_percent_threshold(args.threshold)
    files = target_python_files()
    pytest_exit, counts = run_quality_tests_under_trace(tuple(args.pytest_args or DEFAULT_PYTEST_ARGS))
    summary = summarize_coverage(
        files=files,
        counts=counts,
        threshold=threshold,
        pytest_exit_code=pytest_exit,
    )
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    else:
        print(
            "quality coverage: "
            f"{summary.percent:.2f}% "
            f"({summary.covered_lines}/{summary.executable_lines}) "
            f"threshold={summary.threshold:.2f}%"
        )
        for item in summary.files:
            if item.executable_lines and item.percent < 50.0:
                print(
                    f"low file: {item.path} "
                    f"{item.percent:.2f}% ({item.covered_lines}/{item.executable_lines})"
                )
    if pytest_exit != 0:
        return pytest_exit
    return 0 if summary.passed else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="run quality tests and enforce coverage")
    check.add_argument("--threshold", type=float, default=70.0)
    check.add_argument("--json", action="store_true")
    check.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="optional pytest args after --",
    )
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI prints concise failures.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
