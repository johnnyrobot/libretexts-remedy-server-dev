from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_quality_layer_source_artifacts_are_git_trackable() -> None:
    repo_root = Path(__file__).parents[2]
    required_roots = [
        repo_root / "v2_docs/quality-layer-loop-stopping-criteria.md",
        repo_root / "src/project_remedy/vision_planner/dimension_strategy_map.yaml",
        repo_root / "tools/corpus_annotations/schema.json",
        repo_root / "tools/corpus_annotations/v1/manifest.jsonl",
    ]
    globs = [
        "v2_docs/*.md",
        "src/project_remedy/behavioral_proxies/**/*.py",
        "src/project_remedy/behavioral_proxies/**/prompts/*.md",
        "src/project_remedy/quality_judges/**/*.py",
        "src/project_remedy/quality_judges/**/prompts/*.md",
        "src/project_remedy/quality_judges/shared/rubrics/*.yaml",
        "backend/app/quality*.py",
        "tests/api/test_quality*.py",
        "tests/behavioral_proxies/**/*.py",
        "tests/corpus/test_*.py",
        "tests/quality_judges/**/*.py",
        "tests/vision_planner/test_*.py",
        "tools/annotate_corpus.py",
        "tools/calibrate_judges.py",
        "tools/capture_corpus_snapshots.py",
        "tools/quality_coverage.py",
        "tools/sample_quality_reviews.py",
        "tools/verify_behavioral_corpus.py",
        "tools/verify_corpus_snapshots.py",
    ]
    artifact_paths = set(required_roots)
    for pattern in globs:
        artifact_paths.update(repo_root.glob(pattern))

    missing = [path for path in required_roots if not path.exists()]
    assert not missing
    assert artifact_paths

    result = subprocess.run(
        [
            "git",
            "check-ignore",
            *[str(path.relative_to(repo_root)) for path in sorted(artifact_paths)],
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_ci_quality_checks_enforce_readiness_after_annotations_exist() -> None:
    repo_root = Path(__file__).parents[2]
    workflow = (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Enforce readiness when corpus annotations exist" in workflow
    assert "No corpus annotations committed yet; readiness remains advisory." in workflow
    enforce_section = workflow.split(
        "- name: Enforce readiness when corpus annotations exist",
        maxsplit=1,
    )[1].split("\n\n  security:", maxsplit=1)[0]

    assert "continue-on-error" not in enforce_section
    assert "tools/annotate_corpus.py coverage" in enforce_section
    assert "tools/verify_corpus_snapshots.py check" in enforce_section
    assert "tools/verify_behavioral_corpus.py check" in enforce_section
    assert "tools/calibrate_judges.py calibrate" in enforce_section
    assert "--enforce-readiness" in enforce_section


def test_ci_quality_checks_run_phase_g_holdout_tests() -> None:
    repo_root = Path(__file__).parents[2]
    workflow = (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "tests/vision_planner/test_quality_evaluation.py" in workflow
    assert "tests/vision_planner/test_proposer_dimension_aware.py" in workflow


def test_ci_quality_checks_compile_calibration_and_planner_surfaces() -> None:
    repo_root = Path(__file__).parents[2]
    workflow = (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    compile_section = workflow.split(
        "- name: Compile quality layer sources",
        maxsplit=1,
    )[1].split("- name: Run quality-focused tests", maxsplit=1)[0]

    for required_path in [
        "backend/app/quality_routes.py",
        "backend/app/quality_calibration.py",
        "src/project_remedy/vision_planner/scorer.py",
        "src/project_remedy/vision_planner/experiment_store.py",
        "src/project_remedy/vision_planner/proposer.py",
        "src/project_remedy/vision_planner/quality_evaluation.py",
    ]:
        assert required_path in compile_section


def test_quality_loop_stopping_criteria_are_documented() -> None:
    repo_root = Path(__file__).parents[2]
    criteria = (
        repo_root / "v2_docs/quality-layer-loop-stopping-criteria.md"
    ).read_text(encoding="utf-8")

    for required_phrase in [
        "Cohen's kappa",
        "3 unsuccessful prompt/rubric iterations",
        "Drift alerts do not auto-retrain",
        "byte-identical default-flow regression",
        "at least 3 controlled A/B runs",
        "5 percentage points of lift",
        "2 percentage points of regression",
        "3 consecutive iterations make no progress",
    ]:
        assert required_phrase in criteria


def test_quality_tool_clis_run_directly_from_repo_root() -> None:
    repo_root = Path(__file__).parents[2]
    tools = [
        "tools/annotate_corpus.py",
        "tools/calibrate_judges.py",
        "tools/capture_corpus_snapshots.py",
        "tools/quality_coverage.py",
        "tools/sample_quality_reviews.py",
        "tools/verify_behavioral_corpus.py",
        "tools/verify_corpus_snapshots.py",
    ]

    for tool in tools:
        result = subprocess.run(
            [sys.executable, tool, "--help"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 0, f"{tool} failed: {result.stderr}"
        assert "usage:" in result.stdout
