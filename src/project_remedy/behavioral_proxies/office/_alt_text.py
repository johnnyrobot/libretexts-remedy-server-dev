"""OOXML alt-text behavioral proxy helpers for Office artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from project_remedy.behavioral_proxies.office._ooxml import (
    attr as _attr,
    is_docx_content_part as _is_docx_content_part,
    is_pptx_slide_part as _is_pptx_slide_part,
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
from project_remedy.quality_judges.shared.alt_text import (
    alt_text_value,
    assess_office_alt_text,
    has_alt_text,
)


_ALT_OBJECT_KEYWORDS = {
    "picture",
    "image",
    "photo",
    "chart",
    "graph",
    "diagram",
    "figure",
}


@dataclass(frozen=True)
class OfficeAltTextObject:
    source: str
    object_index: int
    name: str
    title: str
    description: str

    @property
    def has_alt_text(self) -> bool:
        return has_alt_text(self)

    @property
    def alt_text(self) -> str:
        return alt_text_value(self)

    @property
    def label(self) -> str:
        return " ".join(part for part in (self.name, self.title, self.description) if part)


def docx_alt_text_objects(artifact_path: Path) -> list[OfficeAltTextObject]:
    return _alt_objects_from_ooxml(
        artifact_path,
        part_predicate=_is_docx_content_part,
        target_local_names=("docPr", "cNvPr"),
        require_keyword=False,
    )


def pptx_alt_text_objects(artifact_path: Path) -> list[OfficeAltTextObject]:
    return _alt_objects_from_ooxml(
        artifact_path,
        part_predicate=_is_pptx_slide_part,
        target_local_names=("cNvPr",),
        require_keyword=True,
    )


def alt_text_substitution_result(
    objects: list[OfficeAltTextObject],
    *,
    test_name: str,
    fmt: str,
    parser_support: str,
    answerer: BehavioralAnswerer | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    if not objects:
        return BehavioralTestResult(
            test_name=test_name,
            dimension="alt_text",
            format=fmt,
            passed=True,
            score=1.0,
            threshold=0.80,
            confidence=0.35,
            metadata={
                "applicable": False,
                "parser_support": parser_support,
                "object_count": 0,
                "llm_answering_enabled": answerer is not None,
            },
        )

    assessment = assess_office_alt_text(
        objects,
        missing_issue="office_object_missing_alt_text",
        generic_issue="office_object_non_substitutive_alt_text",
        duplicate_issue="office_object_duplicated_substitutive_alt_text",
    )
    heuristic_score = assessment.score
    score = heuristic_score
    alt_context = candidate_text or "\n".join(
        item.alt_text for item in objects if item.has_alt_text
    )
    questions = generate_comprehension_questions(
        baseline_text or alt_context,
        dimension="alt_text",
        limit=5,
    )
    findings = list(assessment.findings)
    metadata = {
        "applicable": True,
        "parser_support": parser_support,
        "object_count": len(objects),
        "missing_alt_text_count": assessment.missing_count,
        "non_substitutive_alt_text_count": assessment.non_substitutive_count,
        "duplicate_alt_text_count": assessment.duplicate_count,
        "llm_answering_enabled": answerer is not None,
        "question_count": len(questions),
    }
    if answerer is not None and questions:
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or alt_context,
            candidate_context=alt_context,
            answerer=answerer,
        )
        score = min(heuristic_score, retention.retention)
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
        dimension="alt_text",
        format=fmt,
        passed=score >= 0.80,
        score=round(score, 4),
        threshold=0.80,
        confidence=0.62,
        findings=findings,
        metadata=metadata,
    )


def _alt_objects_from_ooxml(
    artifact_path: Path,
    *,
    part_predicate: Callable[[str], bool],
    target_local_names: tuple[str, ...],
    require_keyword: bool,
) -> list[OfficeAltTextObject]:
    if not artifact_path.exists():
        return []
    objects: list[OfficeAltTextObject] = []
    try:
        with ZipFile(artifact_path) as package:
            for part_name in sorted(package.namelist()):
                if not part_predicate(part_name):
                    continue
                objects.extend(
                    _alt_objects_from_xml(
                        package.read(part_name),
                        source=part_name,
                        target_local_names=target_local_names,
                        require_keyword=require_keyword,
                    )
                )
    except (BadZipFile, OSError):
        return []
    return objects


def _alt_objects_from_xml(
    content: bytes,
    *,
    source: str,
    target_local_names: tuple[str, ...],
    require_keyword: bool,
) -> list[OfficeAltTextObject]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []

    targets = set(target_local_names)
    items: list[OfficeAltTextObject] = []
    seen: set[tuple[str, str, str]] = set()
    for element in root.iter():
        if _local_name(element.tag) not in targets:
            continue
        item = OfficeAltTextObject(
            source=source,
            object_index=0,
            name=_attr(element, "name"),
            title=_attr(element, "title"),
            description=_attr(element, "descr"),
        )
        if require_keyword and not _is_alt_relevant(item):
            continue
        key = (item.name, item.title, item.description)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            OfficeAltTextObject(
                source=item.source,
                object_index=len(items) + 1,
                name=item.name,
                title=item.title,
                description=item.description,
            )
        )
    return items


def _is_alt_relevant(item: OfficeAltTextObject) -> bool:
    return any(keyword in item.label.lower() for keyword in _ALT_OBJECT_KEYWORDS)
