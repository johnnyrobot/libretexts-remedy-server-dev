"""DOCX alt-text substitution proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office._alt_text import (
    alt_text_substitution_result,
    docx_alt_text_objects,
)
from project_remedy.behavioral_proxies.office._checks import report_for, result_from_rules
from project_remedy.behavioral_proxies.shared.base import BehavioralTestResult
from project_remedy.models import FileType


class DOCXAltTextSubstitutionTest:
    test_name = "alt_text_substitution"
    dimension = "alt_text"
    format = "docx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        if artifact_path.exists():
            return alt_text_substitution_result(
                docx_alt_text_objects(artifact_path),
                test_name=self.test_name,
                fmt=self.format,
                parser_support="docx_ooxml_drawing_alt_text",
                answerer=kwargs.get("answerer"),
                baseline_text=str(kwargs.get("baseline_text") or ""),
                candidate_text=str(kwargs.get("candidate_text") or ""),
            )
        return result_from_rules(
            report_for(artifact_path, FileType.DOCX, kwargs),
            test_name=self.test_name,
            dimension=self.dimension,
            fmt=self.format,
            rule_ids=("docx-alt-text",),
            threshold=0.80,
        )
