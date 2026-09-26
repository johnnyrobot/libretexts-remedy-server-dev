"""Screen-reader transcript analysis for PDF behavioral proxies."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.transcript_analysis import (
    analyze_transcript_text,
)
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


def analyze_tag_tree_report(report: TagTreeReport) -> list[dict[str, Any]]:
    """Return structured transcript findings from a tag-tree report."""
    findings: list[dict[str, Any]] = []
    if not report.has_structure_tree:
        findings.append(
            {
                "severity": "error",
                "issue": "missing_structure_tree",
                "message": "PDF has no structure tree for screen-reader traversal.",
            }
        )
        return findings

    findings.extend(
        analyze_transcript_text(
            report.reading_order_text,
            source="pdf_tag_tree",
        )
    )

    last_page = -1
    for node_index, node in enumerate(report.nodes, start=1):
        if not (node.text or node.alt_text or "").strip():
            continue
        if node.page < last_page:
            findings.append(
                {
                    "severity": "error",
                    "issue": "page_order_backtracking",
                    "message": "Screen-reader order returns to an earlier page after later-page content.",
                    "node_index": node_index,
                    "page": node.page,
                    "previous_page": last_page,
                }
            )
            break
        last_page = node.page

    block_counts = Counter(
        " ".join((node.text or node.alt_text or "").split())
        for node in report.nodes
        if (node.text or node.alt_text or "").strip()
    )
    for block, count in sorted(block_counts.items()):
        if len(block) < 40 or count < 3:
            continue
        findings.append(
            {
                "severity": "warning",
                "issue": "repeated_transcript_block",
                "message": f"Transcript block repeats {count} times.",
                "preview": block[:120],
            }
        )

    return findings


class PDFTranscriptAnalyzer:
    """Best-effort transcript analyzer; produces findings, not a hard gate."""

    test_name = "screen_reader_transcript_analysis"
    dimension = "reading_order"
    format = "pdf"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        report = kwargs.get("tag_tree_report") or read_tag_tree(artifact_path)
        findings = analyze_tag_tree_report(report)
        transcript_text = kwargs.get("transcript_text")
        if isinstance(transcript_text, str):
            findings.extend(
                analyze_transcript_text(
                    transcript_text,
                    source="provided_screen_reader_transcript",
                )
            )
        errors = [finding for finding in findings if finding.get("severity") == "error"]
        return BehavioralTestResult(
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=not errors,
            score=0.0 if errors else 1.0,
            threshold=1.0,
            confidence=0.8,
            findings=findings,
            metadata={
                "advisory_only": True,
                "transcript_sources": [
                    "pdf_tag_tree",
                    *(
                        ["provided_screen_reader_transcript"]
                        if isinstance(transcript_text, str)
                        else []
                    ),
                ],
            },
        )
