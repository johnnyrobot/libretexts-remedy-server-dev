"""Registry of quality judges that require calibration before active use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JudgeCalibrationRequirement:
    """A concrete judge version that must meet calibration thresholds."""

    judge_id: str
    judge_version: str
    format: str
    dimension: str

    def to_dict(self) -> dict[str, str]:
        return {
            "judge_id": self.judge_id,
            "judge_version": self.judge_version,
            "format": self.format,
            "dimension": self.dimension,
        }


def required_judge_calibrations(fmt: str) -> tuple[JudgeCalibrationRequirement, ...]:
    """Return the current judge versions that must be calibrated for a format."""
    return tuple(_REQUIREMENTS_BY_FORMAT.get(fmt, ()))


def _requirement(judge_cls: type[Any]) -> JudgeCalibrationRequirement:
    return JudgeCalibrationRequirement(
        judge_id=str(judge_cls.judge_id),
        judge_version=str(judge_cls.judge_version),
        format=str(judge_cls.format),
        dimension=str(judge_cls.dimension),
    )


def _build_requirements() -> dict[str, tuple[JudgeCalibrationRequirement, ...]]:
    from project_remedy.quality_judges.office.docx import (
        DOCXAltTextQualityJudge,
        DOCXComplexContentJudge,
        DOCXDecorativeJudge,
        DOCXHeadingSemanticsJudge,
        DOCXLinkTextJudge,
        DOCXReadingOrderJudge,
        DOCXTableStructureJudge,
    )
    from project_remedy.quality_judges.office.pptx import (
        PPTXAltTextQualityJudge,
        PPTXComplexContentJudge,
        PPTXDecorativeJudge,
        PPTXHeadingSemanticsJudge,
        PPTXLinkTextJudge,
        PPTXSlideReadingOrderJudge,
        PPTXSlideTitleJudge,
        PPTXTableStructureJudge,
    )
    from project_remedy.quality_judges.office.xlsx import (
        XLSXAltTextQualityJudge,
        XLSXComplexContentJudge,
        XLSXLinkTextJudge,
        XLSXSheetOrganizationJudge,
        XLSXTableStructureJudge,
    )
    from project_remedy.quality_judges.pdf import (
        PDFAltTextQualityJudge,
        PDFComplexContentJudge,
        PDFDecorativeJudge,
        PDFHeadingSemanticsJudge,
        PDFLinkTextJudge,
        PDFReadingOrderJudge,
        PDFTableStructureJudge,
    )

    return {
        "pdf": tuple(
            _requirement(cls)
            for cls in (
                PDFAltTextQualityJudge,
                PDFReadingOrderJudge,
                PDFHeadingSemanticsJudge,
                PDFTableStructureJudge,
                PDFLinkTextJudge,
                PDFDecorativeJudge,
                PDFComplexContentJudge,
            )
        ),
        "docx": tuple(
            _requirement(cls)
            for cls in (
                DOCXAltTextQualityJudge,
                DOCXReadingOrderJudge,
                DOCXHeadingSemanticsJudge,
                DOCXTableStructureJudge,
                DOCXLinkTextJudge,
                DOCXDecorativeJudge,
                DOCXComplexContentJudge,
            )
        ),
        "pptx": tuple(
            _requirement(cls)
            for cls in (
                PPTXAltTextQualityJudge,
                PPTXSlideReadingOrderJudge,
                PPTXHeadingSemanticsJudge,
                PPTXTableStructureJudge,
                PPTXLinkTextJudge,
                PPTXDecorativeJudge,
                PPTXComplexContentJudge,
                PPTXSlideTitleJudge,
            )
        ),
        "xlsx": tuple(
            _requirement(cls)
            for cls in (
                XLSXAltTextQualityJudge,
                XLSXTableStructureJudge,
                XLSXLinkTextJudge,
                XLSXComplexContentJudge,
                XLSXSheetOrganizationJudge,
            )
        ),
    }


_REQUIREMENTS_BY_FORMAT = _build_requirements()
