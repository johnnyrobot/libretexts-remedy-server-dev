"""office-verify rule registry — the machine-readable §4 catalog of the PRD.

Every rule declares the exact OOXML part/element/attribute it reads
(``xml_refs``, FR2). ``rule_id`` is the canonical, stable, diffable id (G1).
``emitted_id`` is the id written into ``OfficeCheckResult.rule_id``: for the
five rules that predate office-verify it stays the legacy id
(``docx-title`` …) because ``quality_judges/office/_heuristics.py`` and six
``behavioral_proxies`` modules filter checker results by those exact strings
(NFR4/AC7); net-new rules emit their canonical id.
"""

from __future__ import annotations

from dataclasses import dataclass

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def qn_w(local: str) -> str:
    """Clark-notation name in the main wordprocessingml namespace."""
    return f"{{{NS['w']}}}{local}"


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str          # canonical "OOXML-DOCX-<checkpoint>.<condition>"
    emitted_id: str       # id written into OfficeCheckResult.rule_id
    format: str           # "docx" | "pptx" | "xlsx"
    checkpoint: str       # checkpoint group name from PRD §4
    description: str
    wcag_ref: str         # WCAG 2.1 success criterion, e.g. "1.1.1"
    xml_refs: tuple[str, ...]  # FR2: exact parts/elements/attributes read
    fixable: bool         # FR6: True only with a real office_remediator path
    flag_status: str      # status when the condition trips: "Failed" | "Manual Check Needed"


RULE_CATALOG: tuple[RuleSpec, ...] = (
    RuleSpec(
        "OOXML-DOCX-1.1", "docx-title", "docx", "Document metadata",
        "Document title metadata is present", "2.4.2",
        ("docProps/core.xml -> dc:title",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-1.2", "docx-language", "docx", "Document metadata",
        "Document language metadata is present", "3.1.1",
        ("docProps/core.xml -> dc:language",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.1", "docx-headings", "docx", "Heading structure",
        "Document includes heading/title styles", "1.3.1",
        ("word/document.xml -> w:p/w:pPr/w:pStyle/@w:val",
         "word/document.xml -> w:p/w:pPr/w:outlineLvl/@w:val"), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.2", "OOXML-DOCX-2.2", "docx", "Heading structure",
        "Heading levels do not skip (e.g. H1 to H3 without H2)", "2.4.6",
        ("word/document.xml -> w:p/w:pPr/w:pStyle/@w:val",
         "word/document.xml -> w:p/w:pPr/w:outlineLvl/@w:val"), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.3", "OOXML-DOCX-2.3", "docx", "Heading structure",
        "Document does not open on a body paragraph before any heading/title", "2.4.6",
        ("word/document.xml -> first non-empty w:p style",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-3.1", "docx-alt-text", "docx", "Images",
        "Every inline/anchored image exposes non-empty descr or title", "1.1.1",
        ("word/document.xml -> w:drawing//wp:inline/wp:docPr/@descr|@title",
         "word/document.xml -> w:drawing//wp:anchor/wp:docPr/@descr|@title"), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-3.2", "OOXML-DOCX-3.2", "docx", "Images",
        "Alt text is not a filename/placeholder pattern", "1.1.1",
        ("word/document.xml -> wp:docPr/@descr value pattern",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-4.1", "docx-table-headers", "docx", "Tables",
        "First row of every table is marked as a repeating header", "1.3.1",
        ("word/document.xml -> w:tbl/w:tr[1]/w:trPr/w:tblHeader",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-4.2", "OOXML-DOCX-4.2", "docx", "Tables",
        "No merged cells (gridSpan/vMerge) in the header row", "1.3.1",
        ("word/document.xml -> w:tbl/w:tr[1]//w:tcPr/w:gridSpan",
         "word/document.xml -> w:tbl/w:tr[1]//w:tcPr/w:vMerge"), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-5.1", "OOXML-DOCX-5.1", "docx", "Lists",
        "Visual bullet/number patterns are backed by real w:numPr list structure", "1.3.1",
        ("word/document.xml -> w:p text pattern vs w:p/w:pPr/w:numPr",), False, "Manual Check Needed",
    ),
    RuleSpec(
        "OOXML-DOCX-6.1", "OOXML-DOCX-6.1", "docx", "Hyperlinks",
        "Hyperlink display text is not a bare URL or generic phrase", "2.4.4",
        ("word/document.xml -> w:hyperlink//w:t vs @r:id target",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-7.1", "OOXML-DOCX-7.1", "docx", "Color-only meaning",
        "No paragraph relies solely on run color adjacent to color-reference text", "1.4.1",
        ("word/document.xml -> w:r/w:rPr/w:color/@w:val co-occurring with color phrases",),
        False, "Manual Check Needed",
    ),
)

RULE_SPECS_BY_ID: dict[str, RuleSpec] = {spec.rule_id: spec for spec in RULE_CATALOG}
