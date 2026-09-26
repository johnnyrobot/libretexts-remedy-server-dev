from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_corpus_snapshots import summarize_snapshot_gate


CORPUS_ROOT = Path("tools/corpus_annotations/v1")


def test_pdf_corpus_default_flow_snapshots_are_present_when_pdf_corpus_exists() -> None:
    pdf_annotations = sorted((CORPUS_ROOT / "annotations" / "pdf").glob("*.json"))
    if not pdf_annotations:
        pytest.skip("PDF annotated corpus is not present yet")

    summary = summarize_snapshot_gate(CORPUS_ROOT)
    missing_pdf = [
        path
        for path in summary["missing_snapshots"]
        if "/snapshots/pdf/" in path
    ]
    invalid_pdf = {
        path: errors
        for path, errors in summary["invalid_snapshots"].items()
        if "/snapshots/pdf/" in path
    }

    assert missing_pdf == []
    assert invalid_pdf == {}
