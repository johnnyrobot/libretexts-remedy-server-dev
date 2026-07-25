"""Deterministic helpers for behavioral proxy question generation."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedQuestion:
    """A comprehension/navigation question used by behavioral proxies."""

    question: str
    expected_answer: str
    source_dimension: str


_VALUE_RE = re.compile(
    r"\b("
    r"Q[1-4]|"
    r"\d+(?:[.,]\d+)?|"
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|billion"
    r")"
    r"(?:\s*(?:%|percent|percentage|points?|years?|months?|days?|"
    r"quarters?|pages?|students?|people|items?|dollars?|usd|employees?))?",
    re.IGNORECASE,
)

_CAPITALIZED_PHRASE_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9'_-]+(?:\s+|$)){2,}"
)
_WORD_RE = re.compile(r"[A-Za-z0-9%][A-Za-z0-9%'-]*")


def sentence_candidates(text: str, *, min_words: int = 6, limit: int = 10) -> list[str]:
    """Extract stable sentence-like snippets for downstream question generation."""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    candidates = [
        sentence.strip()
        for sentence in sentences
        if len(sentence.split()) >= min_words
    ]
    return candidates[:limit]


def generate_comprehension_questions(
    text: str,
    *,
    dimension: str,
    limit: int = 5,
) -> list[GeneratedQuestion]:
    """Generate deterministic cloze-style questions from source text."""
    questions: list[GeneratedQuestion] = []
    for index, sentence in enumerate(sentence_candidates(text, limit=limit), start=1):
        answer = _answer_span(sentence)
        cloze = _cloze_sentence(sentence, answer)
        questions.append(
            GeneratedQuestion(
                question=(
                    f"What detail completes source statement {index}: "
                    f'"{cloze}"?'
                ),
                expected_answer=answer,
                source_dimension=dimension,
            )
        )
    return questions


def _answer_span(sentence: str) -> str:
    value_match = _VALUE_RE.search(sentence)
    if value_match:
        return value_match.group(0).strip()

    proper_name_match = _CAPITALIZED_PHRASE_RE.search(sentence)
    if proper_name_match:
        return " ".join(proper_name_match.group(0).split())

    words = [match.group(0) for match in _WORD_RE.finditer(sentence)]
    if not words:
        return sentence.strip()
    span_length = min(4, len(words))
    return " ".join(words[-span_length:])


def _cloze_sentence(sentence: str, answer: str) -> str:
    if not answer:
        return sentence
    pattern = re.compile(re.escape(answer), re.IGNORECASE)
    cloze = pattern.sub("____", sentence, count=1)
    return cloze if cloze != sentence else f"{sentence} [answer: ____]"
