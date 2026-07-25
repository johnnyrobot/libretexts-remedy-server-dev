"""Narrow PDF link-text quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.quality_judges.pdf._heuristics import PDFHeuristicJudge
from project_remedy.quality_judges.shared.base import QualityDimensionScore
from project_remedy.quality_judges.shared.link_text import descriptive_link_text


class PDFLinkTextJudge(PDFHeuristicJudge):
    judge_id = "pdf_link_text"
    judge_version = "link_text_judge_v1"
    dimension = "link_text"
    prompt_name = "link_text_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        report = self._report(artifact_path, **kwargs)
        links = [node for node in report.nodes if node.tag == "Link"]
        if not links:
            return self._score(
                score=1.0,
                per_criterion={"descriptive_link_text": 1.0},
                confidence=1.0,
            )

        descriptive = 0
        findings: list[dict[str, Any]] = []
        for index, node in enumerate(links, start=1):
            text = node.text or node.alt_text
            if descriptive_link_text(text):
                descriptive += 1
                continue
            findings.append(
                {
                    "severity": "error",
                    "issue": "non_descriptive_link_text",
                    "link_index": index,
                    "page": node.page,
                    "text": node.text or node.alt_text,
                }
            )
        score = descriptive / len(links)
        return self._score(
            score=score,
            per_criterion={"descriptive_link_text": score},
            findings=findings,
            confidence=0.70,
        )
