"""DOCX decorative-skip proxy backed by OOXML decorative flags."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_remedy.behavioral_proxies.office._decorative import (
    decorative_shapes_from_ooxml,
    decorative_skip_result,
)
from project_remedy.behavioral_proxies.office._ooxml import is_docx_content_part
from project_remedy.behavioral_proxies.shared.base import (
    BehavioralTestResult,
    require_unit_interval,
)


class DOCXDecorativeSkipTest:
    test_name = "decorative_skip"
    dimension = "decorative"
    format = "docx"

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        return decorative_skip_result(
            decorative_shapes_from_ooxml(
                artifact_path,
                part_predicate=is_docx_content_part,
                target_local_names=("docPr",),
            ),
            test_name=self.test_name,
            fmt=self.format,
            parser_support="docx_ooxml_decorative_flag",
            threshold=require_unit_interval(
                "threshold",
                kwargs.get("threshold", 1.0),
            ),
            answerer=kwargs.get("answerer"),
            baseline_text=str(kwargs.get("baseline_text") or ""),
            candidate_text=str(kwargs.get("candidate_text") or ""),
        )
