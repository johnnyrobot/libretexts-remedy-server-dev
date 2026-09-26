"""Shared raw screen-reader transcript analysis helpers."""

from __future__ import annotations

import re
from typing import Any

_VAGUE_LINK_TEXT = {
    "click here",
    "here",
    "learn more",
    "more",
    "read more",
}

_OBJECT_ROLES = {"graphic", "image", "picture", "shape"}
_UNLABELED_OBJECT_WORDS = {"blank", "empty", "unlabeled"}
_CONTROL_ROLE_PHRASES = (
    ("button",),
    ("checkbox",),
    ("combo", "box"),
    ("edit",),
    ("list", "box"),
    ("radio", "button"),
    ("text", "field"),
)
_CONTROL_STATE_WORDS = {
    "blank",
    "checked",
    "collapsed",
    "dimmed",
    "empty",
    "expanded",
    "invalid",
    "not",
    "off",
    "on",
    "pressed",
    "required",
    "selected",
    "unavailable",
    "unchecked",
    "unlabeled",
    "unpressed",
}

_HEADING_RE = re.compile(
    r"\bheading(?:\s+level)?\s+(?P<level>[1-6])\b",
    re.IGNORECASE,
)


def analyze_transcript_text(
    transcript: str,
    *,
    source: str = "provided_transcript",
) -> list[dict[str, Any]]:
    """Return structured findings from raw screen-reader transcript text."""
    lines = [" ".join(line.split()) for line in transcript.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return [
            {
                "severity": "error",
                "issue": "empty_transcript",
                "message": "Screen-reader transcript is empty.",
                "source": source,
            }
        ]

    findings: list[dict[str, Any]] = []
    repeated = _repeated_lines(lines)
    for line, count in repeated.items():
        findings.append(
            {
                "severity": "warning",
                "issue": "repeated_transcript_line",
                "message": f"Transcript line repeats {count} times.",
                "preview": line[:120],
                "count": count,
                "source": source,
            }
        )

    for index, line in enumerate(lines, start=1):
        if _is_unlabeled_object_announcement(line):
            findings.append(
                {
                    "severity": "error",
                    "issue": "unlabeled_object_announcement",
                    "message": "Transcript announces an object without accessible text.",
                    "line_index": index,
                    "announcement": line,
                    "source": source,
                }
            )

        if _is_unlabeled_control_announcement(line):
            findings.append(
                {
                    "severity": "error",
                    "issue": "unlabeled_control_announcement",
                    "message": "Transcript announces a form control without an accessible label.",
                    "line_index": index,
                    "announcement": line,
                    "source": source,
                }
            )

        link_text = _announced_link_text(line)
        if link_text in _VAGUE_LINK_TEXT:
            findings.append(
                {
                    "severity": "warning",
                    "issue": "vague_link_announcement",
                    "message": "Transcript announces a non-descriptive link.",
                    "line_index": index,
                    "announcement": line,
                    "link_text": link_text,
                    "source": source,
                }
            )

    findings.extend(_heading_level_findings(lines, source=source))

    return findings


def _is_unlabeled_object_announcement(line: str) -> bool:
    normalized = line.casefold().strip(" .:;-")
    if normalized in _OBJECT_ROLES:
        return True

    tokens = re.findall(r"[a-z0-9]+", normalized)
    if not tokens:
        return False
    if tokens[0] in _OBJECT_ROLES:
        tail = tokens[1:]
        return bool(tail) and all(
            token.isdigit() or token in _UNLABELED_OBJECT_WORDS
            for token in tail
        )
    if tokens[-1] in _OBJECT_ROLES:
        head = tokens[:-1]
        return bool(head) and all(
            token.isdigit() or token in _UNLABELED_OBJECT_WORDS
            for token in head
        )
    return False


def _is_unlabeled_control_announcement(line: str) -> bool:
    normalized = line.casefold().strip(" .:;-")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if not tokens:
        return False
    for role_phrase in _CONTROL_ROLE_PHRASES:
        remainder = _tokens_without_role(tokens, role_phrase)
        if remainder is None:
            continue
        content_tokens = [
            token
            for token in remainder
            if not token.isdigit() and token not in _CONTROL_STATE_WORDS
        ]
        if not content_tokens:
            return True
    return False


def _tokens_without_role(
    tokens: list[str],
    role_phrase: tuple[str, ...],
) -> list[str] | None:
    width = len(role_phrase)
    for index in range(0, len(tokens) - width + 1):
        if tuple(tokens[index : index + width]) == role_phrase:
            return tokens[:index] + tokens[index + width :]
    return None


def _repeated_lines(lines: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in lines:
        if len(line) < 20:
            continue
        counts[line] = counts.get(line, 0) + 1
    return {
        line: count
        for line, count in sorted(counts.items())
        if count >= 3
    }


def _announced_link_text(line: str) -> str:
    """Return normalized link text if a transcript line announces a link."""
    normalized = line.casefold().strip(" .:;-")
    if "link" not in normalized:
        return ""
    normalized = re.sub(r"\b(link|visited|unvisited)\b", "", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip(" .:;-")


def _heading_level_findings(lines: list[str], *, source: str) -> list[dict[str, Any]]:
    """Flag heading outline jumps in raw transcript announcements."""
    findings: list[dict[str, Any]] = []
    previous_level = 0
    previous_line_index = 0
    for index, line in enumerate(lines, start=1):
        match = _HEADING_RE.search(line)
        if match is None:
            continue
        level = int(match.group("level"))
        if previous_level and level > previous_level + 1:
            findings.append(
                {
                    "severity": "warning",
                    "issue": "heading_level_jump",
                    "message": "Transcript heading outline skips one or more levels.",
                    "line_index": index,
                    "heading_level": level,
                    "previous_heading_level": previous_level,
                    "previous_heading_line_index": previous_line_index,
                    "announcement": line,
                    "source": source,
                }
            )
        previous_level = level
        previous_line_index = index
    return findings
