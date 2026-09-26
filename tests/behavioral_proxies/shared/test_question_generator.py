from __future__ import annotations

from project_remedy.behavioral_proxies.shared.question_generator import (
    generate_comprehension_questions,
)


def test_question_generator_uses_targeted_cloze_for_values() -> None:
    questions = generate_comprehension_questions(
        "The report explains enrollment trends over five years.",
        dimension="reading_order",
    )

    assert len(questions) == 1
    assert questions[0].source_dimension == "reading_order"
    assert questions[0].expected_answer == "five years"
    assert "____" in questions[0].question
    assert "source sentence" not in questions[0].question


def test_question_generator_falls_back_to_sentence_detail_span() -> None:
    questions = generate_comprehension_questions(
        "The memo identifies the largest accessibility risks for students.",
        dimension="alt_text",
    )

    assert questions[0].expected_answer == "accessibility risks for students"
    assert questions[0].question.endswith('"?')
