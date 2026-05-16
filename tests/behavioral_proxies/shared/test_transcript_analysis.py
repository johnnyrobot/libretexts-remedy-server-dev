from __future__ import annotations

from project_remedy.behavioral_proxies.shared.transcript_analysis import (
    analyze_transcript_text,
)


def test_raw_transcript_analysis_flags_empty_transcript() -> None:
    findings = analyze_transcript_text(" \n\t")

    assert findings == [
        {
            "severity": "error",
            "issue": "empty_transcript",
            "message": "Screen-reader transcript is empty.",
            "source": "provided_transcript",
        }
    ]


def test_raw_transcript_analysis_flags_repeated_lines_and_unlabeled_objects() -> None:
    repeated = "Quarterly revenue table repeated by the reader"
    findings = analyze_transcript_text(
        f"{repeated}\nGraphic\n{repeated}\n{repeated}",
        source="nvda",
    )

    assert findings == [
        {
            "severity": "warning",
            "issue": "repeated_transcript_line",
            "message": "Transcript line repeats 3 times.",
            "preview": repeated,
            "count": 3,
            "source": "nvda",
        },
        {
            "severity": "error",
            "issue": "unlabeled_object_announcement",
            "message": "Transcript announces an object without accessible text.",
            "line_index": 2,
            "announcement": "Graphic",
            "source": "nvda",
        },
    ]


def test_raw_transcript_analysis_flags_generated_object_announcements() -> None:
    findings = analyze_transcript_text(
        "Graphic 12\nUnlabeled image\nCompany logo graphic",
        source="nvda",
    )

    assert findings == [
        {
            "severity": "error",
            "issue": "unlabeled_object_announcement",
            "message": "Transcript announces an object without accessible text.",
            "line_index": 1,
            "announcement": "Graphic 12",
            "source": "nvda",
        },
        {
            "severity": "error",
            "issue": "unlabeled_object_announcement",
            "message": "Transcript announces an object without accessible text.",
            "line_index": 2,
            "announcement": "Unlabeled image",
            "source": "nvda",
        },
    ]


def test_raw_transcript_analysis_flags_unlabeled_form_controls() -> None:
    findings = analyze_transcript_text(
        "Submit button\n"
        "button\n"
        "checkbox not checked\n"
        "blank edit required\n"
        "Email text field",
        source="nvda",
    )

    assert findings == [
        {
            "severity": "error",
            "issue": "unlabeled_control_announcement",
            "message": "Transcript announces a form control without an accessible label.",
            "line_index": 2,
            "announcement": "button",
            "source": "nvda",
        },
        {
            "severity": "error",
            "issue": "unlabeled_control_announcement",
            "message": "Transcript announces a form control without an accessible label.",
            "line_index": 3,
            "announcement": "checkbox not checked",
            "source": "nvda",
        },
        {
            "severity": "error",
            "issue": "unlabeled_control_announcement",
            "message": "Transcript announces a form control without an accessible label.",
            "line_index": 4,
            "announcement": "blank edit required",
            "source": "nvda",
        },
    ]


def test_raw_transcript_analysis_flags_vague_link_announcements() -> None:
    findings = analyze_transcript_text(
        "Quarterly report link\nClick here link\nRead more visited link",
        source="jaws",
    )

    assert findings == [
        {
            "severity": "warning",
            "issue": "vague_link_announcement",
            "message": "Transcript announces a non-descriptive link.",
            "line_index": 2,
            "announcement": "Click here link",
            "link_text": "click here",
            "source": "jaws",
        },
        {
            "severity": "warning",
            "issue": "vague_link_announcement",
            "message": "Transcript announces a non-descriptive link.",
            "line_index": 3,
            "announcement": "Read more visited link",
            "link_text": "read more",
            "source": "jaws",
        },
    ]


def test_raw_transcript_analysis_flags_heading_level_jumps() -> None:
    findings = analyze_transcript_text(
        "Heading level 1 Annual report\n"
        "Paragraph intro\n"
        "Heading level 3 Q1 details\n"
        "Heading 2 Revenue",
        source="voiceover",
    )

    assert findings == [
        {
            "severity": "warning",
            "issue": "heading_level_jump",
            "message": "Transcript heading outline skips one or more levels.",
            "line_index": 3,
            "heading_level": 3,
            "previous_heading_level": 1,
            "previous_heading_line_index": 1,
            "announcement": "Heading level 3 Q1 details",
            "source": "voiceover",
        }
    ]
