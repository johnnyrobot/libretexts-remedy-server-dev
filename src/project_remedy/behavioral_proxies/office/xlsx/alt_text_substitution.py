"""XLSX chart/image alt-text substitution proxy over drawing OOXML."""

from __future__ import annotations

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
from project_remedy.pdf_checker import _is_generic_alt_text


@dataclass(frozen=True)
class XLSXDrawingObject:
    source: str
    object_index: int
    name: str
    title: str
    description: str

    @property
    def has_alt_text(self) -> bool:
        return bool(self.title.strip() or self.description.strip())

    @property
    def alt_text(self) -> str:
        return " ".join(
            part.strip()
            for part in (self.title, self.description)
            if part.strip()
        )

    @property
    def has_substitutive_alt_text(self) -> bool:
        return self.has_alt_text and not _is_generic_xlsx_drawing_alt_text(
            self.description.strip() or self.title.strip()
        )


@dataclass(frozen=True)
class XLSXAltTextAssessment:
    score: float
    presence_score: float
    specificity_score: float
    findings: tuple[dict[str, Any], ...]
    missing_count: int
    non_substitutive_count: int
    duplicate_count: int


class XLSXAltTextSubstitutionTest:
    test_name = "alt_text_substitution"
    dimension = "alt_text"
    format = "xlsx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        answerer: BehavioralAnswerer | None = kwargs.get("answerer")
        objects = _xlsx_drawing_objects(artifact_path)
        if not objects:
            return BehavioralTestResult(
                test_name=self.test_name,
                dimension=self.dimension,
                format=self.format,
                passed=True,
                score=1.0,
                threshold=0.80,
                confidence=0.30,
                metadata={
                    "applicable": False,
                    "parser_support": "xlsx_ooxml_drawing_cnvpr",
                    "drawing_object_count": 0,
                    "llm_answering_enabled": answerer is not None,
                },
            )

        assessment = assess_xlsx_drawing_alt_text(objects)
        heuristic_score = assessment.score
        score = heuristic_score
        findings = list(assessment.findings)
        alt_context = str(kwargs.get("candidate_text") or "") or "\n".join(
            item.alt_text for item in objects if item.has_substitutive_alt_text
        )
        baseline_text = str(kwargs.get("baseline_text") or "")
        questions = generate_comprehension_questions(
            baseline_text or alt_context,
            dimension="alt_text",
            limit=5,
        )
        metadata = {
            "applicable": True,
            "parser_support": "xlsx_ooxml_drawing_cnvpr",
            "drawing_object_count": len(objects),
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
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=score >= 0.80,
            score=round(score, 4),
            threshold=0.80,
            confidence=0.60,
            findings=findings,
            metadata=metadata,
        )


def assess_xlsx_drawing_alt_text(
    objects: list[XLSXDrawingObject],
) -> XLSXAltTextAssessment:
    if not objects:
        return XLSXAltTextAssessment(
            score=1.0,
            presence_score=0.0,
            specificity_score=0.0,
            findings=(),
            missing_count=0,
            non_substitutive_count=0,
            duplicate_count=0,
        )

    findings: list[dict[str, Any]] = []
    missing = [item for item in objects if not item.has_alt_text]
    non_substitutive = [
        item for item in objects if item.has_alt_text and not item.has_substitutive_alt_text
    ]
    substitutive_by_text: dict[str, list[XLSXDrawingObject]] = {}
    for item in objects:
        if item.has_substitutive_alt_text:
            normalized = " ".join(item.alt_text.casefold().split())
            substitutive_by_text.setdefault(normalized, []).append(item)

    for item in missing:
        findings.append(
            {
                "severity": "error",
                "issue": "xlsx_drawing_missing_alt_text",
                "source": item.source,
                "object_index": item.object_index,
                "name": item.name,
            }
        )
    for item in non_substitutive:
        findings.append(
            {
                "severity": "error",
                "issue": "xlsx_drawing_non_substitutive_alt_text",
                "source": item.source,
                "object_index": item.object_index,
                "name": item.name,
                "alt_text": item.alt_text,
            }
        )

    duplicate_count = 0
    for alt_text, duplicates in sorted(substitutive_by_text.items()):
        if len(duplicates) < 2:
            continue
        duplicate_count += len(duplicates) - 1
        findings.append(
            {
                "severity": "error",
                "issue": "xlsx_drawing_duplicated_substitutive_alt_text",
                "object_indices": [item.object_index for item in duplicates],
                "duplicate_count": len(duplicates),
                "alt_text": alt_text,
            }
        )

    substitutive_count = max(
        0,
        sum(1 for item in objects if item.has_substitutive_alt_text) - duplicate_count,
    )
    presence_score = (len(objects) - len(missing)) / len(objects)
    specificity_score = substitutive_count / len(objects)
    return XLSXAltTextAssessment(
        score=specificity_score,
        presence_score=presence_score,
        specificity_score=specificity_score,
        findings=tuple(findings),
        missing_count=len(missing),
        non_substitutive_count=len(non_substitutive),
        duplicate_count=duplicate_count,
    )


def _is_generic_xlsx_drawing_alt_text(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    if normalized in {
        "chart",
        "diagram",
        "figure",
        "graph",
        "image",
        "photo",
        "picture",
        "plot",
    }:
        return True
    return _is_generic_alt_text(text)


def _xlsx_drawing_objects(artifact_path: Path) -> list[XLSXDrawingObject]:
    if not artifact_path.exists():
        return []

    objects: list[XLSXDrawingObject] = []
    try:
        with ZipFile(artifact_path) as package:
            for part_name in sorted(package.namelist()):
                if not (part_name.startswith("xl/drawings/drawing") and part_name.endswith(".xml")):
                    continue
                content = read_zip_member_safely(package, part_name)
                if content is None:
                    continue
                objects.extend(_drawing_objects_from_xml(content, source=part_name))
    except (BadZipFile, OSError):
        return []
    return objects


def _drawing_objects_from_xml(content: bytes, *, source: str) -> list[XLSXDrawingObject]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []

    objects: list[XLSXDrawingObject] = []
    object_index = 0
    for element in root.iter():
        if _local_name(element.tag) != "cNvPr":
            continue
        object_index += 1
        objects.append(
            XLSXDrawingObject(
                source=source,
                object_index=object_index,
                name=_attr(element, "name"),
                title=_attr(element, "title"),
                description=_attr(element, "descr"),
            )
        )
    return objects


