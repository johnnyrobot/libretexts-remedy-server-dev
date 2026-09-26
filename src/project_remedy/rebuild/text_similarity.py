"""Jaccard text similarity between two PDFs.

Used by the rebuild-tier acceptance gate to catch content loss — if a
rebuilt PDF's sentence set disagrees meaningfully with the original's,
the tier fails acceptance. Fast, deterministic, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")
_BULLET_PREFIX = re.compile(r"^[\-\*\u2022]\s+")


def text_similarity(original_pdf: Path, rebuilt_pdf: Path) -> float:
    """Jaccard similarity on sentence tokens. Range [0.0, 1.0].

    Both empty → 0.0 (no shared content to report on).
    One empty → 0.0 (intersection is empty).
    """
    a = _sentences(original_pdf)
    b = _sentences(rebuilt_pdf)
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _sentences(pdf_path: Path) -> frozenset[str]:
    doc = fitz.open(str(pdf_path))
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    if not text.strip():
        return frozenset()
    # Collapse all whitespace (including PDF line-wrap newlines) to single
    # spaces BEFORE sentence splitting. Original PDFs often break mid-sentence
    # at line-wrap boundaries ("to the\nsemantic rebuild tier"); the rebuilt
    # PDF joins them ("to the semantic rebuild tier"). Without this collapse,
    # Jaccard compares fragment-sets from the original to full-sentence-sets
    # from the rebuild — wildly different tokens for the same content.
    text = _WHITESPACE.sub(" ", text)
    sentences = _SENTENCE_SPLIT.split(text)
    normalized = {
        _WHITESPACE.sub(" ", _BULLET_PREFIX.sub("", s.strip()).lower())
        for s in sentences
    }
    normalized.discard("")
    # Drop any sentence that's just a bullet character after stripping
    normalized.discard("\u2022")
    return frozenset(normalized)
