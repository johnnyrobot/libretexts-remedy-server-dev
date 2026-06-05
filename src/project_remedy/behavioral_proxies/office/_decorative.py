"""Shared OOXML decorative-shape helpers for Office behavioral proxies."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from project_remedy._zip_safety import read_zip_member_safely
from project_remedy.behavioral_proxies.office._ooxml import (
    attr as _attr,
    local_name as _local_name,
)
from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)


@dataclass(frozen=True)
class DecorativeShape:
    source: str
    object_index: int
    decorative_value: str
    title: str
    description: str

    @property
    def has_accessible_text(self) -> bool:
        return bool(self.title.strip() or self.description.strip())


def decorative_shapes_from_ooxml(
    artifact_path: Path,
    *,
    part_predicate: Callable[[str], bool],
    target_local_names: tuple[str, ...],
) -> list[DecorativeShape]:
    """Extract OOXML objects with a truthy decorative flag."""
    if not artifact_path.exists():
        return []

    shapes: list[DecorativeShape] = []
    try:
        with ZipFile(artifact_path) as package:
            for part_name in sorted(package.namelist()):
                if not part_predicate(part_name):
                    continue
                content = read_zip_member_safely(package, part_name)
                if content is None:
                    continue
                shapes.extend(
                    _decorative_shapes_from_xml(
                        content,
                        source=part_name,
                        target_local_names=target_local_names,
                    )
                )
    except (BadZipFile, OSError):
        return []
    return shapes


def decorative_skip_result(
    shapes: Iterable[DecorativeShape],
    *,
    test_name: str,
    fmt: str,
    parser_support: str,
    threshold: float = 1.0,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    """Build a behavioral result for decorative-skip checks."""
    items = list(shapes)
    if not items:
        return BehavioralTestResult(
            test_name=test_name,
            dimension="decorative",
            format=fmt,
            passed=True,
            score=1.0,
            threshold=threshold,
            confidence=0.30,
            metadata={
                "applicable": False,
                "parser_support": parser_support,
                "partial": True,
                "llm_answering_enabled": answerer is not None,
                "question_count": 0,
                "decorative_shape_count": 0,
            },
        )

    failures = [shape for shape in items if shape.has_accessible_text]
    structural_score = (len(items) - len(failures)) / len(items)
    score = structural_score
    findings = [
        {
            "severity": "error",
            "issue": "decorative_shape_has_accessible_text",
            "source": shape.source,
            "object_index": shape.object_index,
            "title": shape.title,
            "description": shape.description,
        }
        for shape in failures
    ]
    baseline_context = baseline_text or _decorative_shape_context(items)
    candidate_context = candidate_text
    questions = generate_comprehension_questions(
        baseline_context,
        dimension="decorative",
        limit=5,
    )
    metadata: dict[str, Any] = {
        "applicable": True,
        "parser_support": parser_support,
        "partial": True,
        "llm_answering_enabled": answerer is not None,
        "question_count": len(questions),
        "decorative_shape_count": len(items),
    }
    if answerer is not None and questions:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_context,
            candidate_context=candidate_context,
            answerer=answerer,
        )
        score = min(structural_score, retention.retention)
        findings.extend(retention.findings)
        metadata.update(
            {
                "baseline_accuracy": retention.baseline_accuracy,
                "candidate_accuracy": retention.candidate_accuracy,
                "answer_accuracy_retention": retention.retention,
            }
        )
    return BehavioralTestResult(
        test_name=test_name,
        dimension="decorative",
        format=fmt,
        passed=score >= threshold,
        score=round(score, 4),
        threshold=threshold,
        confidence=0.55,
        findings=findings,
        metadata=metadata,
    )


def _decorative_shape_context(shapes: Iterable[DecorativeShape]) -> str:
    return "\n".join(
        text
        for text in (
            " ".join((shape.title, shape.description)).strip()
            for shape in shapes
        )
        if text
    )


def _decorative_shapes_from_xml(
    content: bytes,
    *,
    source: str,
    target_local_names: tuple[str, ...],
) -> list[DecorativeShape]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []

    shapes: list[DecorativeShape] = []
    object_index = 0
    targets = set(target_local_names)
    for element in root.iter():
        if _local_name(element.tag) not in targets:
            continue
        decorative_value = _decorative_value(element)
        if not _is_truthy(decorative_value):
            continue
        object_index += 1
        shapes.append(
            DecorativeShape(
                source=source,
                object_index=object_index,
                decorative_value=decorative_value,
                title=_attr(element, "title"),
                description=_attr(element, "descr"),
            )
        )
    return shapes


def _decorative_value(element: ElementTree.Element) -> str:
    direct = _attr(element, "decorative")
    if direct:
        return direct
    for child in element.iter():
        if child is element or _local_name(child.tag) != "decorative":
            continue
        return _attr(child, "val") or _attr(child, "decorative") or (child.text or "")
    return ""


def _is_truthy(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "t", "yes", "on"}
