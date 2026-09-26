"""OOXML decorative-flag scoring helpers for Office quality judges."""

from __future__ import annotations

from pathlib import Path

from project_remedy.behavioral_proxies.office._decorative import (
    DecorativeShape,
    decorative_shapes_from_ooxml,
)
from project_remedy.quality_judges.office._ooxml import (
    is_docx_content_part,
    is_pptx_slide_part,
)
from project_remedy.quality_judges.shared.base import QualityDimensionScore


def docx_decorative_shapes(artifact_path: Path) -> list[DecorativeShape]:
    """Return DOCX shapes marked decorative in body/header/footer OOXML."""
    return decorative_shapes_from_ooxml(
        artifact_path,
        part_predicate=is_docx_content_part,
        target_local_names=("docPr",),
    )


def pptx_decorative_shapes(artifact_path: Path) -> list[DecorativeShape]:
    """Return PPTX shapes marked decorative in slide OOXML."""
    return decorative_shapes_from_ooxml(
        artifact_path,
        part_predicate=is_pptx_slide_part,
        target_local_names=("cNvPr",),
    )


def score_decorative_shapes(
    shapes: list[DecorativeShape],
    *,
    judge_id: str,
    judge_version: str,
    fmt: str,
) -> QualityDimensionScore:
    """Score decorative objects by whether they correctly omit accessible text."""
    if not shapes:
        return QualityDimensionScore(
            dimension="decorative",
            format=fmt,
            score=1.0,
            variance=0.0,
            per_criterion={"decorative_flag_parser_coverage": 0.0},
            judge_versions=[f"{judge_id}:{judge_version}"],
            sample_findings=[],
            confidence=0.30,
        )

    failures = [shape for shape in shapes if shape.has_accessible_text]
    score = (len(shapes) - len(failures)) / len(shapes)
    findings = [
        {
            "severity": "warning",
            "issue": "decorative_shape_has_accessible_text",
            "source": shape.source,
            "object_index": shape.object_index,
            "title": shape.title,
            "description": shape.description,
        }
        for shape in failures
    ]
    return QualityDimensionScore(
        dimension="decorative",
        format=fmt,
        score=round(score, 4),
        variance=0.0,
        per_criterion={"decorative_skip_semantics": round(score, 4)},
        judge_versions=[f"{judge_id}:{judge_version}"],
        sample_findings=findings[:5],
        confidence=0.55,
    )
