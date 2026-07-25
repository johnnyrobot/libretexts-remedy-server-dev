"""OOXML link-text helpers for Office quality judges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from defusedxml.ElementTree import fromstring as _safe_fromstring

from project_remedy._zip_safety import read_zip_member_safely
from project_remedy.quality_judges.office._ooxml import (
    attr,
    is_docx_content_part,
    is_pptx_slide_part,
    is_xlsx_sheet_part,
    local_name,
)
from project_remedy.quality_judges.shared.base import QualityDimensionScore
from project_remedy.quality_judges.shared.link_text import descriptive_link_text


@dataclass(frozen=True)
class OfficeLink:
    source: str
    link_index: int
    text: str
    target: str


def docx_links(artifact_path: Path) -> list[OfficeLink]:
    """Extract external DOCX hyperlinks from document, header, and footer parts."""
    return _links_from_ooxml_package(
        artifact_path,
        part_predicate=is_docx_content_part,
        rels_path_for=_docx_rels_path_for,
        extractor=_extract_docx_links,
    )


def pptx_links(artifact_path: Path) -> list[OfficeLink]:
    """Extract PPTX text hyperlinks from slide parts."""
    return _links_from_ooxml_package(
        artifact_path,
        part_predicate=is_pptx_slide_part,
        rels_path_for=_pptx_rels_path_for,
        extractor=_extract_pptx_links,
    )


def xlsx_links(artifact_path: Path) -> list[OfficeLink]:
    """Extract XLSX worksheet hyperlinks with their display text when present."""
    return _links_from_ooxml_package(
        artifact_path,
        part_predicate=is_xlsx_sheet_part,
        rels_path_for=_xlsx_rels_path_for,
        extractor=_extract_xlsx_links,
    )


def score_office_links(
    links: list[OfficeLink],
    *,
    judge_id: str,
    judge_version: str,
    fmt: str,
    dimension: str = "link_text",
) -> QualityDimensionScore:
    """Score Office links for descriptive visible text."""
    if not links:
        return QualityDimensionScore(
            dimension=dimension,
            format=fmt,
            score=1.0,
            variance=0.0,
            per_criterion={"link_text_parser_coverage": 0.0},
            judge_versions=[f"{judge_id}:{judge_version}"],
            sample_findings=[],
            confidence=0.30,
        )

    failures = [link for link in links if not descriptive_link_text(link.text, link.target)]
    score = (len(links) - len(failures)) / len(links)
    findings = [
        {
            "severity": "warning",
            "issue": "non_descriptive_link_text",
            "source": link.source,
            "link_index": link.link_index,
            "text": link.text,
            "target": link.target,
        }
        for link in failures
    ]
    return QualityDimensionScore(
        dimension=dimension,
        format=fmt,
        score=round(score, 4),
        variance=0.0,
        per_criterion={"descriptive_link_text": round(score, 4)},
        judge_versions=[f"{judge_id}:{judge_version}"],
        sample_findings=findings[:5],
        confidence=0.60,
    )


def _links_from_ooxml_package(
    artifact_path: Path,
    *,
    part_predicate: Callable[[str], bool],
    rels_path_for: Callable[[str], str],
    extractor: Callable[[bytes, dict[str, str], str], list[OfficeLink]],
) -> list[OfficeLink]:
    if not artifact_path.exists():
        return []
    links: list[OfficeLink] = []
    try:
        with ZipFile(artifact_path) as package:
            for part_name in sorted(package.namelist()):
                if not part_predicate(part_name):
                    continue
                content = read_zip_member_safely(package, part_name)
                if content is None:
                    continue
                relationships = _relationships(package, rels_path_for(part_name))
                links.extend(extractor(content, relationships, part_name))
    except (BadZipFile, OSError):
        return []
    return links


def _relationships(package: ZipFile, rels_path: str) -> dict[str, str]:
    content = read_zip_member_safely(package, rels_path)
    if content is None:
        return {}
    try:
        root = _safe_fromstring(content)
    except ElementTree.ParseError:
        return {}
    return {
        str(element.attrib.get("Id") or ""): str(element.attrib.get("Target") or "")
        for element in root.iter()
        if local_name(element.tag) == "Relationship"
    }


def _extract_docx_links(
    content: bytes,
    relationships: dict[str, str],
    source: str,
) -> list[OfficeLink]:
    try:
        root = _safe_fromstring(content)
    except ElementTree.ParseError:
        return []
    links: list[OfficeLink] = []
    for element in root.iter():
        if local_name(element.tag) != "hyperlink":
            continue
        rel_id = attr(element, "id")
        target = relationships.get(rel_id, "")
        text = _descendant_text(element, "t")
        if target:
            links.append(OfficeLink(source, len(links) + 1, text, target))
    return links


def _extract_pptx_links(
    content: bytes,
    relationships: dict[str, str],
    source: str,
) -> list[OfficeLink]:
    try:
        root = _safe_fromstring(content)
    except ElementTree.ParseError:
        return []
    links: list[OfficeLink] = []
    for run in root.iter():
        if local_name(run.tag) != "r":
            continue
        rel_id = ""
        for child in run.iter():
            if local_name(child.tag) == "hlinkClick":
                rel_id = attr(child, "id")
                break
        if not rel_id:
            continue
        links.append(
            OfficeLink(
                source=source,
                link_index=len(links) + 1,
                text=_descendant_text(run, "t"),
                target=relationships.get(rel_id, ""),
            )
        )
    return links


def _extract_xlsx_links(
    content: bytes,
    relationships: dict[str, str],
    source: str,
) -> list[OfficeLink]:
    try:
        root = _safe_fromstring(content)
    except ElementTree.ParseError:
        return []
    links: list[OfficeLink] = []
    for element in root.iter():
        if local_name(element.tag) != "hyperlink":
            continue
        rel_id = attr(element, "id")
        links.append(
            OfficeLink(
                source=source,
                link_index=len(links) + 1,
                text=attr(element, "display"),
                target=relationships.get(rel_id, attr(element, "location")),
            )
        )
    return links


def _descendant_text(element: ElementTree.Element, tag_local_name: str) -> str:
    return " ".join(
        (child.text or "").strip()
        for child in element.iter()
        if local_name(child.tag) == tag_local_name and (child.text or "").strip()
    )


def _docx_rels_path_for(part_name: str) -> str:
    if part_name == "word/document.xml":
        return "word/_rels/document.xml.rels"
    directory, filename = part_name.rsplit("/", 1)
    return f"{directory}/_rels/{filename}.rels"


def _pptx_rels_path_for(part_name: str) -> str:
    filename = part_name.rsplit("/", 1)[-1]
    return f"ppt/slides/_rels/{filename}.rels"


def _xlsx_rels_path_for(part_name: str) -> str:
    filename = part_name.rsplit("/", 1)[-1]
    return f"xl/worksheets/_rels/{filename}.rels"
