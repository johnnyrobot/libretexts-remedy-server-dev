"""PPTX slide reading-order quality judge scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.models import FileType
from project_remedy.quality_judges.office._heuristics import OfficeHeuristicJudge
from project_remedy.quality_judges.shared.pptx_reading_order import (
    pptx_slide_reading_order_signals,
)
from project_remedy.quality_judges.shared.base import QualityDimensionScore


class PPTXSlideReadingOrderJudge(OfficeHeuristicJudge):
    judge_id = "pptx_slide_reading_order_quality"
    judge_version = "slide_reading_order_judge_v1"
    dimension = "reading_order"
    format = "pptx"
    file_type = FileType.PPTX
    prompt_name = "slide_reading_order_judge_v1.md"

    def judge(self, artifact_path: Path, **kwargs: Any) -> QualityDimensionScore:
        signals = pptx_slide_reading_order_signals(
            artifact_path,
            slide_count=kwargs.get("slide_count"),
        )
        parser_available = any(signal.issue != "parser_unavailable" for signal in signals)
        confidence = 0.45 if parser_available else 0.20
        per_slide = [
            {
                "slide_index": signal.slide_index,
                "score": signal.score,
                "confidence": confidence,
                "parser_support": "python_pptx_shape_order",
                "passed": signal.passed,
                "issue": signal.issue,
                "title_text": signal.title_text,
                "first_object_text": signal.first_object_text,
                "previous_object_text": signal.previous_object_text,
                "out_of_order_object_text": signal.out_of_order_object_text,
                "object_count": signal.object_count,
                "shape_order_texts": list(signal.shape_order_texts),
                "visual_order_texts": list(signal.visual_order_texts),
            }
            for signal in signals
        ]
        if not signals:
            score = 1.0
        else:
            score = sum(signal.score for signal in signals) / len(signals)
        findings = [
            {
                "severity": "error",
                "issue": signal.issue,
                "slide_index": signal.slide_index,
                "title_text": signal.title_text,
                "first_object_text": signal.first_object_text,
                "previous_object_text": signal.previous_object_text,
                "out_of_order_object_text": signal.out_of_order_object_text,
            }
            for signal in signals
            if not signal.passed
        ]
        findings.append(
            {
                "severity": "info",
                "issue": "pptx_reading_order_shape_order_signal",
                "per_slide": per_slide,
            }
        )
        return self._score(
            score=score,
            per_criterion={
                "shape_order_title_first": (
                    sum(signal.title_first_score for signal in signals) / len(signals)
                    if signals
                    else 0.0
                ),
                "shape_order_visual_sequence": (
                    sum(signal.visual_sequence_score for signal in signals) / len(signals)
                    if signals
                    else 0.0
                ),
            },
            findings=findings,
            confidence=confidence,
        )
