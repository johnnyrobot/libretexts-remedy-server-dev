"""Quality dimension applicability matrix."""

from __future__ import annotations


ALL_QUALITY_DIMENSIONS: tuple[str, ...] = (
    "alt_text",
    "reading_order",
    "heading_semantics",
    "table_structure",
    "link_text",
    "decorative",
    "complex_content",
    "sheet_organization",
    "slide_title",
)


DIMENSIONS_BY_FORMAT: dict[str, tuple[str, ...]] = {
    "pdf": (
        "alt_text",
        "reading_order",
        "heading_semantics",
        "table_structure",
        "link_text",
        "decorative",
        "complex_content",
    ),
    "docx": (
        "alt_text",
        "reading_order",
        "heading_semantics",
        "table_structure",
        "link_text",
        "decorative",
        "complex_content",
    ),
    "pptx": (
        "alt_text",
        "reading_order",
        "heading_semantics",
        "table_structure",
        "link_text",
        "decorative",
        "complex_content",
        "slide_title",
    ),
    "xlsx": (
        "alt_text",
        "table_structure",
        "link_text",
        "complex_content",
        "sheet_organization",
    ),
}


def not_applicable_dimensions(fmt: str) -> tuple[str, ...]:
    """Return dimensions that should be represented as n/a for a format."""
    applicable = set(DIMENSIONS_BY_FORMAT.get(fmt, ()))
    return tuple(
        dimension
        for dimension in ALL_QUALITY_DIMENSIONS
        if dimension not in applicable
    )


def dimension_from_behavioral_test(test_name: str) -> str:
    """Map a behavioral proxy test name to its quality dimension."""
    if test_name.startswith("alt_text"):
        return "alt_text"
    if test_name.startswith(("reading_order", "slide_reading_order")):
        return "reading_order"
    if test_name.startswith("screen_reader"):
        return "reading_order"
    if test_name.startswith("heading"):
        return "heading_semantics"
    if test_name.startswith("table"):
        return "table_structure"
    if test_name.startswith("decorative"):
        return "decorative"
    if test_name.startswith("link"):
        return "link_text"
    if test_name.startswith("complex"):
        return "complex_content"
    if test_name.startswith("slide_title"):
        return "slide_title"
    if test_name.startswith("sheet"):
        return "sheet_organization"
    return test_name
