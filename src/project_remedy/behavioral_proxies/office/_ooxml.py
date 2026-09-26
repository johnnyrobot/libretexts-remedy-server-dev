"""Shared OOXML helpers for Office behavioral proxies."""

from __future__ import annotations

from xml.etree import ElementTree


def local_name(name: str) -> str:
    """Strip an XML namespace from a tag/attribute name."""
    return name.rsplit("}", 1)[-1] if "}" in name else name


def attr(element: ElementTree.Element, target: str) -> str:
    """Return a namespaced attribute value matched by its local name."""
    for key, value in element.attrib.items():
        if local_name(key) == target:
            return str(value).strip()
    return ""


def is_docx_content_part(part_name: str) -> bool:
    """Return true for the DOCX parts behavioral proxies scan."""
    return (
        part_name == "word/document.xml"
        or (part_name.startswith("word/header") and part_name.endswith(".xml"))
        or (part_name.startswith("word/footer") and part_name.endswith(".xml"))
    )


def is_pptx_slide_part(part_name: str) -> bool:
    """Return true for PPTX slide parts behavioral proxies scan."""
    return part_name.startswith("ppt/slides/slide") and part_name.endswith(".xml")
