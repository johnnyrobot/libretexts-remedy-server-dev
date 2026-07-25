"""Version-controlled shared quality-judge rubric loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from project_remedy.quality_judges.shared.dimensions import ALL_QUALITY_DIMENSIONS


RUBRICS_DIR = Path(__file__).resolve().parent / "rubrics"


@dataclass(frozen=True)
class RubricCriterion:
    id: str
    scale: str
    description: str


@dataclass(frozen=True)
class QualityRubric:
    dimension: str
    version: str
    applies_to: tuple[str, ...]
    criteria: tuple[RubricCriterion, ...]


def load_rubric(dimension: str) -> QualityRubric:
    """Load one shared rubric by quality dimension."""
    if dimension not in ALL_QUALITY_DIMENSIONS:
        raise ValueError(f"unknown quality dimension: {dimension}")
    path = RUBRICS_DIR / f"{dimension}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing quality rubric: {path}")
    return _rubric_from_payload(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def load_all_rubrics() -> dict[str, QualityRubric]:
    """Load all shared rubric files keyed by dimension."""
    return {dimension: load_rubric(dimension) for dimension in ALL_QUALITY_DIMENSIONS}


def criterion_ids_for_dimension(dimension: str) -> set[str]:
    """Return allowed per-criterion score keys for one dimension."""
    return {criterion.id for criterion in load_rubric(dimension).criteria}


def _rubric_from_payload(payload: dict[str, Any]) -> QualityRubric:
    criteria = tuple(
        RubricCriterion(
            id=str(item["id"]),
            scale=str(item["scale"]),
            description=str(item["description"]),
        )
        for item in payload.get("criteria", [])
    )
    return QualityRubric(
        dimension=str(payload["dimension"]),
        version=str(payload["version"]),
        applies_to=tuple(str(item) for item in payload.get("applies_to", [])),
        criteria=criteria,
    )
