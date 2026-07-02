"""Office Remediation-Level classifier (L0-L4) — PRD §3.1, FR3.

OOXML has no PDF-style tag tree: heading styles + ``w:tblHeader`` + ``docPr``
alt attributes *are* the structure layer, so the level gates read those
signals. Reuses ``levels.LevelResult`` (FR3 — one shared contract for the
District burndown report) and carries the identical never-L5 invariant.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_remedy.levels import LevelResult
from project_remedy.models import FileType
from project_remedy.office_acceptance import OfficeAcceptanceResult
from project_remedy.office_rules import NS, qn_w

logger = logging.getLogger(__name__)

OFFICE_PROFILE_NAME = "LACCD-DistrictUA1-Office"


@dataclass(frozen=True)
class OfficeStructureProbe:
    """Raw structural facts read straight from the OOXML parts. Never LLM-derived."""

    has_text: bool
    has_heading_structure: bool
    has_table_header_marks: bool
    has_alt_text_signal: bool
    paragraph_count: int
    table_count: int
    image_count: int


_EMPTY_PROBE = OfficeStructureProbe(False, False, False, False, 0, 0, 0)


def probe_office_structure(path: Path, file_type: FileType) -> OfficeStructureProbe:
    """Read structural facts from a docx. Never raises (mirrors levels.probe_structure)."""
    if file_type != FileType.DOCX:
        raise ValueError(
            f"office_levels Phase 1 supports DOCX only, got {file_type} (pptx/xlsx are Phase 2/3)"
        )
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.warning("probe_office_structure failed for %s: %s", path, exc)
        return _EMPTY_PROBE

    has_text = any((t.text or "").strip() for t in root.iter(qn_w("t")))

    has_heading = False
    paragraph_count = 0
    for p in root.iter(qn_w("p")):
        paragraph_count += 1
        p_pr = p.find(qn_w("pPr"))
        if p_pr is None:
            continue
        style = p_pr.find(qn_w("pStyle"))
        style_val = ((style.get(qn_w("val")) if style is not None else "") or "").lower()
        if style_val.startswith(("heading", "title")) or p_pr.find(qn_w("outlineLvl")) is not None:
            has_heading = True

    has_tbl_header = root.find(f".//{qn_w('tblHeader')}") is not None
    table_count = sum(1 for _ in root.iter(qn_w("tbl")))

    image_count = 0
    has_alt = False
    for kind in ("inline", "anchor"):
        for container in root.iter(f"{{{NS['wp']}}}{kind}"):
            doc_pr = container.find(f"{{{NS['wp']}}}docPr")
            if doc_pr is None:
                continue
            image_count += 1
            if (doc_pr.get("descr") or "").strip() or (doc_pr.get("title") or "").strip():
                has_alt = True

    return OfficeStructureProbe(
        has_text=has_text,
        has_heading_structure=has_heading,
        has_table_header_marks=has_tbl_header,
        has_alt_text_signal=has_alt,
        paragraph_count=paragraph_count,
        table_count=table_count,
        image_count=image_count,
    )


def classify_level(
    acceptance: OfficeAcceptanceResult | None,
    probe: OfficeStructureProbe,
    *,
    profile_name: str = OFFICE_PROFILE_NAME,
) -> LevelResult:
    """Classify an Office document into L0-L4. Never returns L5 (invariant)."""
    sub_scores = _build_sub_scores(acceptance, probe)
    needs_human = (
        [r.rule_id for r in acceptance.checker_report.results if r.status == "Manual Check Needed"]
        if acceptance is not None
        else []
    )

    def result(level: str, blocking: list[str], *, machine: bool = True) -> LevelResult:
        # Defensive: the classifier must never emit L5 (same invariant as levels.py).
        assert level in {"L0", "L1", "L2", "L3", "L4"}, f"illegal level {level!r}"
        return LevelResult(
            level=level,
            machine_certifiable=machine,
            sub_scores=sub_scores,
            blocking_conditions=blocking,
            needs_human=needs_human,
            profile=profile_name,
        )

    if acceptance is None:
        return result("L0", ["evaluation_error"], machine=False)
    if not acceptance.openable:
        return result("L0", ["not_openable"], machine=False)
    if not probe.has_text:
        return result("L0", ["no_text_layer"])
    if not (probe.has_heading_structure or probe.has_table_header_marks or probe.has_alt_text_signal):
        return result("L1", ["no_structural_signal"])

    failed = [r.rule_id for r in acceptance.checker_failures]
    if failed:
        return result("L2", failed)

    # L3 reached: all deterministic rules pass. L4 = L3 + quality layer green
    # (audit_office_quality's QualityResult, attached by the caller — FR3).
    l4_blockers: list[str] = []
    if acceptance.quality_result is None:
        l4_blockers.append("quality_layer_not_run")
    elif not acceptance.quality_result.overall_pass:
        l4_blockers.append("quality_failed")
    if l4_blockers:
        return result("L3", l4_blockers)
    return result("L4", [])


def _build_sub_scores(
    acceptance: OfficeAcceptanceResult | None, probe: OfficeStructureProbe
) -> dict[str, Any]:
    failed = len(acceptance.checker_failures) if acceptance is not None else 0
    manual = (
        sum(1 for r in acceptance.checker_report.results if r.status == "Manual Check Needed")
        if acceptance is not None
        else 0
    )
    return {
        "failed_rule_count": failed,
        "manual_check_count": manual,
        "paragraph_count": probe.paragraph_count,
        "table_count": probe.table_count,
        "image_count": probe.image_count,
    }
