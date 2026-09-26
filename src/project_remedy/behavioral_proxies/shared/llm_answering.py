"""Shared answer-retention helpers for LLM-backed behavioral proxies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from project_remedy.behavioral_proxies.shared.question_generator import GeneratedQuestion


class BehavioralAnswerer(Protocol):
    """Synchronous adapter for an independent behavioral answerer model."""

    def answer(self, *, question: str, context: str) -> str:
        """Answer one question using only the supplied serialized context."""


@dataclass(frozen=True)
class AnswerRetentionResult:
    """Accuracy-retention score from baseline and candidate contexts."""

    baseline_accuracy: float
    candidate_accuracy: float
    retention: float
    findings: list[dict]


def score_answer_retention(
    *,
    questions: list[GeneratedQuestion],
    baseline_context: str,
    candidate_context: str,
    answerer: BehavioralAnswerer,
) -> AnswerRetentionResult:
    """Ask an answerer over both contexts and compute retained accuracy."""
    baseline_correct = 0
    candidate_correct = 0
    findings: list[dict] = []
    for index, question in enumerate(questions, start=1):
        baseline_answer = answerer.answer(
            question=question.question,
            context=baseline_context,
        )
        candidate_answer = answerer.answer(
            question=question.question,
            context=candidate_context,
        )
        baseline_ok = answer_matches_expected(
            baseline_answer,
            question.expected_answer,
        )
        candidate_ok = answer_matches_expected(
            candidate_answer,
            question.expected_answer,
        )
        baseline_correct += int(baseline_ok)
        candidate_correct += int(candidate_ok)
        if baseline_ok and not candidate_ok:
            findings.append(
                {
                    "severity": "error",
                    "issue": "llm_answer_retention_loss",
                    "question_index": index,
                    "question": question.question,
                    "expected_answer": question.expected_answer,
                    "candidate_answer": candidate_answer,
                }
            )

    count = max(len(questions), 1)
    baseline_accuracy = baseline_correct / count
    candidate_accuracy = candidate_correct / count
    retention = (
        candidate_accuracy / baseline_accuracy
        if baseline_accuracy > 0
        else candidate_accuracy
    )
    return AnswerRetentionResult(
        baseline_accuracy=round(baseline_accuracy, 4),
        candidate_accuracy=round(candidate_accuracy, 4),
        retention=round(min(retention, 1.0), 4),
        findings=findings,
    )


def answer_matches_expected(answer: str, expected: str) -> bool:
    """Return true when an answer preserves the expected information."""
    answer_norm = _normalize(answer)
    expected_norm = _normalize(expected)
    if not answer_norm or not expected_norm:
        return False
    return expected_norm in answer_norm or answer_norm in expected_norm


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
