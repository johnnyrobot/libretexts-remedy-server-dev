"""PPTX heading semantics quality judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared._helpers import safe_ratio
from project_remedy.quality_judges.shared.base import QualityDimensionScore
from project_remedy.quality_judges.shared.pptx_metadata import validate_slide_count
from project_remedy.quality_judges.shared.pptx_slide_titles import (
    pptx_slide_title_signals,
)


class PPTXHeadingSemanticsJudge(OfficeHeuristicJudge):
    judge_id = "pptx_heading_semantics_quality"
    judge_version = "heading_semantics_judge_v1"
    dimension = "heading_semantics"
    format = "pptx"
    file_type = FileType.PPTX
    prompt_name = "heading_semantics_judge_v1.md"
    rule_ids = ("pptx-slide-titles",)

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        slide_count = validate_slide_count(kwargs.get("slide_count"))
        if not artifact_path.exists():
            return super().judge(artifact_path, **kwargs)
        signals = pptx_slide_title_signals(artifact_path, slide_count=slide_count)
        if not signals:
            return self._score(
                score=1.0,
                per_criterion={"slide_title_navigation": 0.0},
                confidence=0.35,
            )
        failures = [
            signal
            for signal in signals
            if signal.issue in {
                "missing_slide_title_placeholder",
                "empty_slide_title",
                "non_descriptive_slide_title",
            }
        ]
        score = (len(signals) - len(failures)) / len(signals)
        return self._score(
            score=score,
            per_criterion={
                "slide_title_presence": safe_ratio(
                    sum(1 for signal in signals if signal.has_title_placeholder and signal.title_text),
                    len(signals),
                ),
                "slide_title_navigation": score,
            },
            findings=[
                {
                    "severity": "error",
                    "issue": signal.issue,
                    "slide_index": signal.slide_index,
                    "title_text": signal.title_text,
                    "has_title_placeholder": signal.has_title_placeholder,
                }
                for signal in failures
            ],
            confidence=0.65,
        )
