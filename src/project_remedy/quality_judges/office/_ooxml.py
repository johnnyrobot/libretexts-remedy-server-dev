"""Shared OOXML part-name and XML-attribute helpers for Office quality judges."""

from __future__ import annotations

from xml.etree import ElementTree


def local_name(name: str) -> str:
    """Return the local part of a namespaced XML tag/attribute name."""
    return name.rsplit("}", 1)[-1] if "}" in name else name


def attr(element: ElementTree.Element, name: str) -> str:
    """Return the trimmed attribute value matching ``name`` ignoring namespace."""
    for key, value in element.attrib.items():
        if local_name(key) == name:
            return str(value).strip()
    return ""


def is_docx_content_part(part_name: str) -> bool:
    """Return True for DOCX body, header, and footer XML parts."""
    return (
        part_name == "word/document.xml"
        or (part_name.startswith("word/header") and part_name.endswith(".xml"))
        or (part_name.startswith("word/footer") and part_name.endswith(".xml"))
    )


def is_pptx_slide_part(part_name: str) -> bool:
    """Return True for PPTX slide XML parts."""
    return part_name.startswith("ppt/slides/slide") and part_name.endswith(".xml")


def is_xlsx_sheet_part(part_name: str) -> bool:
    """Return True for XLSX worksheet XML parts."""
    return part_name.startswith("xl/worksheets/sheet") and part_name.endswith(".xml")
