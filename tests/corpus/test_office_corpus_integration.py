from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_corpus_snapshots import summarize_snapshot_gate


CORPUS_ROOT = Path("tools/corpus_annotations/v1")
OFFICE_FORMATS = ("docx", "pptx", "xlsx")


def test_office_corpus_default_flow_snapshots_are_present_when_office_corpus_exists() -> None:
    office_annotations = [
        path
        for fmt in OFFICE_FORMATS
        for path in sorted((CORPUS_ROOT / "annotations" / fmt).glob("*.json"))
    ]
    if not office_annotations:
        pytest.skip("Office annotated corpus is not present yet")

    summary = summarize_snapshot_gate(CORPUS_ROOT)
    missing_office = [
        path
        for path in summary["missing_snapshots"]
        if any(f"/snapshots/{fmt}/" in path for fmt in OFFICE_FORMATS)
    ]
    invalid_office = {
        path: errors
        for path, errors in summary["invalid_snapshots"].items()
        if any(f"/snapshots/{fmt}/" in path for fmt in OFFICE_FORMATS)
    }

    assert missing_office == []
    assert invalid_office == {}
