from __future__ import annotations

from pathlib import Path

from tools import quality_coverage


def test_executable_statement_lines_counts_function_body(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "def run(value):",
                "    if value:",
                "        return 1",
                "    return 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert quality_coverage.executable_statement_lines(source) == {1, 2, 3, 4}


def test_summarize_coverage_uses_trace_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(quality_coverage, "REPO_ROOT", tmp_path)
    source = tmp_path / "quality.py"
    source.write_text(
        "\n".join(
            [
                "def run(value):",
                "    if value:",
                "        return 1",
                "    return 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = quality_coverage.summarize_coverage(
        files=[source],
        counts={
            (str(source), 1): 1,
            (str(source), 2): 1,
            (str(source), 3): 1,
        },
        threshold=70.0,
        pytest_exit_code=0,
    )

    assert summary.percent == 75.0
    assert summary.passed is True
    assert summary.files[0].path == "quality.py"


def test_summarize_coverage_fails_below_threshold(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(quality_coverage, "REPO_ROOT", tmp_path)
    source = tmp_path / "quality.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")

    summary = quality_coverage.summarize_coverage(
        files=[source],
        counts={(str(source), 1): 1},
        threshold=80.0,
        pytest_exit_code=0,
    )

    assert summary.percent == 50.0
    assert summary.passed is False


def test_summarize_coverage_rejects_invalid_thresholds(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(quality_coverage, "REPO_ROOT", tmp_path)
    source = tmp_path / "quality.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")

    for value, expected in (
        (float("nan"), "threshold must be finite"),
        (True, "threshold must be numeric"),
        (101.0, "threshold must be between 0 and 100"),
    ):
        try:
            quality_coverage.summarize_coverage(
                files=[source],
                counts={},
                threshold=value,
                pytest_exit_code=0,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid quality coverage threshold should fail")


def test_quality_coverage_cli_rejects_invalid_threshold_before_pytest(monkeypatch) -> None:
    def fail_if_called(_pytest_args):
        raise AssertionError("pytest should not run for invalid thresholds")

    monkeypatch.setattr(quality_coverage, "run_quality_tests_under_trace", fail_if_called)

    assert quality_coverage.main(["check", "--threshold", "nan"]) == 2


def test_target_python_files_excludes_package_init_files() -> None:
    files = quality_coverage.target_python_files(
        ("src/project_remedy/quality_judges/shared",)
    )

    names = {Path(path).name for path in files}
    assert "__init__.py" not in names
    assert "base.py" in names


def test_default_quality_coverage_targets_include_behavioral_and_planner_gates() -> None:
    paths = {
        path.relative_to(quality_coverage.REPO_ROOT).as_posix()
        for path in quality_coverage.target_python_files()
    }

    assert "tools/verify_behavioral_corpus.py" in paths
    assert "src/project_remedy/vision_planner/scorer.py" in paths
    assert "src/project_remedy/vision_planner/experiment_store.py" in paths
    assert "src/project_remedy/vision_planner/proposer.py" in paths
    assert "src/project_remedy/vision_planner/quality_evaluation.py" in paths
    assert "tests/vision_planner/test_quality_evaluation.py" in quality_coverage.DEFAULT_PYTEST_ARGS
