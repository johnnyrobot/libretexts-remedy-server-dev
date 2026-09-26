"""OOXML alt-text helpers for Office quality judges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from project_remedy.quality_judges.office._ooxml import (
    attr,
    is_docx_content_part,
    is_pptx_slide_part,
    local_name,
)
from project_remedy.quality_judges.shared.alt_text import (
    alt_text_value,
    assess_office_alt_text,
    has_alt_text,
)
from project_remedy.quality_judges.shared.base import QualityDimensionScore


ALT_OBJECT_KEYWORDS = {
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
    """Extract DOCX drawing objects that can carry alt text."""
    return _alt_objects_from_ooxml(
        artifact_path,
        part_predicate=is_docx_content_part,
        target_local_names=("docPr", "cNvPr"),
        require_keyword=False,
    )


def pptx_alt_text_objects(artifact_path: Path) -> list[OfficeAltTextObject]:
    """Extract PPTX non-text drawing objects that can carry alt text."""
    return _alt_objects_from_ooxml(
        artifact_path,
        part_predicate=is_pptx_slide_part,
        target_local_names=("cNvPr",),
        require_keyword=True,
    )


def score_alt_text_objects(
    objects: list[OfficeAltTextObject],
    *,
    judge_id: str,
    judge_version: str,
    fmt: str,
) -> QualityDimensionScore | None:
    """Return an alt-text score from OOXML objects, or None when inapplicable."""
    if not objects:
        return None

    assessment = assess_office_alt_text(
        objects,
        missing_issue="office_object_missing_alt_text",
        generic_issue="office_object_non_substitutive_alt_text",
        duplicate_issue="office_object_duplicated_substitutive_alt_text",
    )
    return QualityDimensionScore(
        dimension="alt_text",
        format=fmt,
        score=round(assessment.score, 4),
        variance=0.0,
        per_criterion={
            "ooxml_alt_text_presence": round(assessment.presence_score, 4),
            "ooxml_alt_text_specificity": round(assessment.specificity_score, 4),
        },
        judge_versions=[f"{judge_id}:{judge_version}"],
        sample_findings=list(assessment.findings[:5]),
        confidence=0.62,
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
        if local_name(element.tag) not in targets:
            continue
        name = attr(element, "name")
        title = attr(element, "title")
        description = attr(element, "descr")
        key = (name, title, description)
        if key in seen:
            continue
        if require_keyword and not _label_has_alt_keyword(name, title, description):
            continue
        seen.add(key)
        items.append(
            OfficeAltTextObject(
                source=source,
                object_index=len(items) + 1,
                name=name,
                title=title,
                description=description,
            )
        )
    return items


def _label_has_alt_keyword(name: str, title: str, description: str) -> bool:
    normalized = " ".join(part for part in (name, title, description) if part).lower()
    return any(keyword in normalized for keyword in ALT_OBJECT_KEYWORDS)
