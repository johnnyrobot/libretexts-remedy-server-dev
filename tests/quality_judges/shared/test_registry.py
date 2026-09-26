from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from project_remedy.quality_judges import pdf
from project_remedy.quality_judges.office import docx, pptx, xlsx

from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT
from project_remedy.quality_judges.shared.registry import required_judge_calibrations


def test_required_judge_calibrations_cover_applicable_dimensions() -> None:
    for fmt, dimensions in DIMENSIONS_BY_FORMAT.items():
        requirements = required_judge_calibrations(fmt)

        assert {requirement.dimension for requirement in requirements} == set(dimensions)
        assert all(requirement.format == fmt for requirement in requirements)
        assert all(requirement.judge_id for requirement in requirements)
        assert all(requirement.judge_version for requirement in requirements)


def test_pptx_registry_includes_distinct_slide_title_judge() -> None:
    requirements = required_judge_calibrations("pptx")

    assert any(
        requirement.dimension == "slide_title"
        and requirement.judge_id == "pptx_slide_title_quality"
        for requirement in requirements
    )


def test_judge_prompt_markdown_files_are_not_gitignored() -> None:
    repo_root = Path(__file__).parents[3]
    prompt_files = sorted(
        (repo_root / "src/project_remedy/quality_judges").glob("**/prompts/*.md")
    )

    assert prompt_files
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            *[str(path.relative_to(repo_root)) for path in prompt_files],
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_required_judge_calibrations_have_exact_versioned_prompt_files() -> None:
    repo_root = Path(__file__).parents[3]
    prompt_root = repo_root / "src/project_remedy/quality_judges"
    expected: set[Path] = set()
    for fmt in DIMENSIONS_BY_FORMAT:
        for requirement in required_judge_calibrations(fmt):
            if fmt == "pdf":
                expected.add(prompt_root / "pdf/prompts" / f"{requirement.judge_version}.md")
            else:
                expected.add(
                    prompt_root
                    / "office"
                    / fmt
                    / "prompts"
                    / f"{requirement.judge_version}.md"
                )

    actual = set(prompt_root.glob("**/prompts/*.md"))

    assert actual == expected
    assert all(path.read_text(encoding="utf-8").strip() for path in actual)


def test_registered_judge_versions_have_pairwise_compare_mode() -> None:
    classes_by_slice = {
        (
            str(judge_cls.format),
            str(judge_cls.dimension),
            str(judge_cls.judge_id),
            str(judge_cls.judge_version),
        ): judge_cls
        for judge_cls in _all_registered_judge_classes()
    }

    for fmt in DIMENSIONS_BY_FORMAT:
        for requirement in required_judge_calibrations(fmt):
            key = (
                requirement.format,
                requirement.dimension,
                requirement.judge_id,
                requirement.judge_version,
            )
            judge_cls = classes_by_slice[key]
            assert callable(getattr(judge_cls, "judge", None))
            assert callable(getattr(judge_cls, "compare", None))


def _all_registered_judge_classes() -> list[type[Any]]:
    modules = (pdf, docx, pptx, xlsx)
    return [
        getattr(module, name)
        for module in modules
        for name in module.__all__
    ]
