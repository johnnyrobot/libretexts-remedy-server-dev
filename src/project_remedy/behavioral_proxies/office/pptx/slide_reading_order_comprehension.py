"""PPTX slide reading-order comprehension proxy scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)
from project_remedy.quality_judges.shared.pptx_reading_order import (
    pptx_slide_reading_order_signals,
)


class PPTXSlideReadingOrderComprehensionTest:
    test_name = "slide_reading_order_comprehension"
    dimension = "reading_order"
    format = "pptx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        answerer: BehavioralAnswerer | None = kwargs.get("answerer")
        signals = pptx_slide_reading_order_signals(
            artifact_path,
            slide_count=kwargs.get("slide_count"),
        )
        parser_available = any(signal.issue != "parser_unavailable" for signal in signals)
        per_slide = []
        findings = []
        slide_scores = []
        for signal in signals:
            slide_score = signal.score
            slide_findings: list[dict[str, Any]] = []
            if not signal.passed:
                slide_findings.append(
                    {
                        "severity": "error",
                        "issue": signal.issue,
                        "slide_index": signal.slide_index,
                        "title_text": signal.title_text,
                        "first_object_text": signal.first_object_text,
                        "previous_object_text": signal.previous_object_text,
                        "out_of_order_object_text": signal.out_of_order_object_text,
                    }
                )
            entry = {
                "slide_index": signal.slide_index,
                "passed": signal.passed,
                "score": slide_score,
                "llm_answering_enabled": answerer is not None,
                "parser_support": "python_pptx_shape_order",
                "issue": signal.issue,
                "title_text": signal.title_text,
                "first_object_text": signal.first_object_text,
                "previous_object_text": signal.previous_object_text,
                "out_of_order_object_text": signal.out_of_order_object_text,
                "object_count": signal.object_count,
                "serialized_text": signal.serialized_text,
                "shape_order_texts": list(signal.shape_order_texts),
                "visual_order_texts": list(signal.visual_order_texts),
            }
            if answerer is not None:
                baseline_context = _baseline_context_for_slide(
                    kwargs.get("baseline_per_slide_text") or kwargs.get("baseline_text"),
                    signal.slide_index,
                )
                candidate_context = signal.serialized_text or "\n".join(
                    part
                    for part in (signal.title_text, signal.first_object_text)
                    if part
                )
                question_source = baseline_context or candidate_context
                questions = generate_comprehension_questions(
                    question_source,
                    dimension="reading_order",
                    limit=5,
                )
                entry["question_count"] = len(questions)
                if questions:
                    retention = score_answer_retention(
                        questions=questions,
                        baseline_context=baseline_context or candidate_context,
                        candidate_context=candidate_context,
                        answerer=answerer,
                    )
                    slide_score = min(slide_score, retention.retention)
                    entry.update(
                        {
                            "score": round(slide_score, 4),
                            "passed": slide_score >= 0.90,
                            "baseline_accuracy": retention.baseline_accuracy,
                            "candidate_accuracy": retention.candidate_accuracy,
                            "answer_accuracy_retention": retention.retention,
                        }
                    )
                    for finding in retention.findings:
                        enriched = dict(finding)
                        enriched["slide_index"] = signal.slide_index
                        slide_findings.append(enriched)
            per_slide.append(entry)
            findings.extend(slide_findings)
            slide_scores.append(slide_score)

        score = 1.0 if not slide_scores else sum(slide_scores) / len(slide_scores)
        if answerer is not None:
            confidence = 0.55
        elif parser_available:
            confidence = 0.45
        else:
            confidence = 0.20
        return BehavioralTestResult(
            test_name=self.test_name,
            dimension=self.dimension,
            format=self.format,
            passed=score >= 0.90,
            score=round(score, 4),
            threshold=0.90,
            confidence=confidence,
            findings=findings,
            metadata={
                "applicable": True,
                "llm_answering_enabled": answerer is not None,
                "slide_count": len(signals),
                "per_slide": per_slide,
            },
        )


def _baseline_context_for_slide(raw: Any, slide_index: int) -> str:
    if isinstance(raw, dict):
        return str(raw.get(slide_index) or raw.get(str(slide_index)) or "")
    if isinstance(raw, (list, tuple)):
        try:
            return str(raw[slide_index - 1])
        except IndexError:
            return ""
    if isinstance(raw, str):
        if "\f" in raw:
            parts = raw.split("\f")
            return parts[slide_index - 1] if slide_index <= len(parts) else ""
        return raw if slide_index == 1 else ""
    return ""
