"""PPTX slide-title navigation proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office._checks import report_for, result_from_rules
from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.behavioral_proxies.shared.llm_answering import (
    BehavioralAnswerer,
    score_answer_retention,
)
from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion
from project_remedy.models import FileType
from project_remedy.quality_judges.shared.pptx_metadata import validate_slide_count
from project_remedy.quality_judges.shared.pptx_slide_titles import (
    pptx_slide_title_signals,
)


class PPTXSlideTitleNavigationTest:
    test_name = "slide_title_navigation"
    dimension = "slide_title"
    format = "pptx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        slide_count = validate_slide_count(kwargs.get("slide_count"))
        if artifact_path.exists():
            signals = pptx_slide_title_signals(artifact_path, slide_count=slide_count)
            return _result_from_title_signals(
                signals,
                answerer=kwargs.get("answerer"),
                navigation_questions=_pptx_slide_title_navigation_questions(artifact_path),
                baseline_text=str(kwargs.get("baseline_text") or ""),
                candidate_text=str(kwargs.get("candidate_text") or ""),
            )
        return result_from_rules(
            report_for(artifact_path, FileType.PPTX, kwargs),
            test_name=self.test_name,
            dimension=self.dimension,
            fmt=self.format,
            rule_ids=("pptx-slide-titles",),
            threshold=0.85,
        )


def _result_from_title_signals(
    signals,
    *,
    answerer: BehavioralAnswerer | None = None,
    navigation_questions: list[GeneratedQuestion] | None = None,
    baseline_text: str = "",
    candidate_text: str = "",
) -> BehavioralTestResult:
    if not signals:
        return BehavioralTestResult(
            test_name="slide_title_navigation",
            dimension="slide_title",
            format="pptx",
            passed=True,
            score=1.0,
            threshold=0.85,
            confidence=0.35,
            metadata={
                "applicable": False,
                "parser_support": "python_pptx_slide_titles",
                "slide_count": 0,
                "llm_answering_enabled": answerer is not None,
            },
        )
    structural_score = sum(signal.score for signal in signals) / len(signals)
    score = structural_score
    findings = [
        {
            "severity": "error" if signal.score == 0.0 else "warning",
            "issue": signal.issue,
            "slide_index": signal.slide_index,
            "title_text": signal.title_text,
            "has_title_placeholder": signal.has_title_placeholder,
        }
        for signal in signals
        if signal.issue
    ]
    questions = list(navigation_questions or [])
    metadata = {
        "applicable": True,
        "parser_support": "python_pptx_slide_titles",
        "slide_count": len(signals),
        "llm_answering_enabled": answerer is not None,
        "navigation_question_count": len(questions),
        "per_slide": [
            {
                "slide_index": signal.slide_index,
                "title_text": signal.title_text,
                "has_title_placeholder": signal.has_title_placeholder,
                "score": signal.score,
                "passed": signal.passed,
                "issue": signal.issue,
            }
            for signal in signals
        ],
    }
    if answerer is not None and questions:
        candidate_context = candidate_text or _title_list_text(signals)
        retention = score_answer_retention(
            questions=questions,
            baseline_context=baseline_text or candidate_context,
            candidate_context=candidate_context,
            answerer=answerer,
        )
        score = min(structural_score, retention.retention)
        findings.extend(retention.findings)
        metadata.update(
            {
                "baseline_accuracy": retention.baseline_accuracy,
                "candidate_accuracy": retention.candidate_accuracy,
                "answer_accuracy_retention": retention.retention,
            }
        )
    return BehavioralTestResult(
        test_name="slide_title_navigation",
        dimension="slide_title",
        format="pptx",
        passed=score >= 0.85,
        score=round(score, 4),
        threshold=0.85,
        confidence=0.65,
        findings=findings,
        metadata=metadata,
    )


def _pptx_slide_title_navigation_questions(artifact_path: Path) -> list[GeneratedQuestion]:
    if not artifact_path.exists():
        return []
    try:
        from pptx import Presentation
    except ImportError:
        return []
    try:
        presentation = Presentation(str(artifact_path))
    except Exception:  # noqa: BLE001 - malformed input makes questions unavailable.
        return []

    questions: list[GeneratedQuestion] = []
    for _slide_index, slide in enumerate(presentation.slides, start=1):
        title_shape = slide.shapes.title
        title_text = ""
        if title_shape is not None:
            title_text = " ".join(str(getattr(title_shape, "text", "") or "").split())
        if not title_text:
            continue
        for shape in slide.shapes:
            if shape is title_shape or not getattr(shape, "has_text_frame", False):
                continue
            text = " ".join(str(shape.text_frame.text or "").split())
            if len(text.split()) < 4:
                continue
            questions.append(
                GeneratedQuestion(
                    question=(
                        f"Which slide title contains information about this content: {text[:120]}?"
                    ),
                    expected_answer=title_text,
                    source_dimension="slide_title",
                )
            )
            break
        if len(questions) >= 5:
            break
    return questions


def _title_list_text(signals) -> str:
    return "\n".join(
        f"Slide {signal.slide_index}: {signal.title_text}"
        for signal in signals
        if signal.title_text
    )
