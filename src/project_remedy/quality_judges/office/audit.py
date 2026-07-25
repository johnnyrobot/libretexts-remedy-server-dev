"""Office quality audit orchestration for DOCX, PPTX, and XLSX."""

from __future__ import annotations

from pathlib import Path

from project_remedy.behavioral_proxies.office.docx import (
    DOCXAltTextSubstitutionTest,
    DOCXDecorativeSkipTest,
    DOCXHeadingNavigationTest,
    DOCXReadingOrderComprehensionTest,
    DOCXScreenReaderTranscriptAnalyzer,
    DOCXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.office.pptx import (
    PPTXAltTextSubstitutionTest,
    PPTXDecorativeSkipTest,
    PPTXSlideReadingOrderComprehensionTest,
    PPTXSlideTitleNavigationTest,
    PPTXScreenReaderTranscriptAnalyzer,
    PPTXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.office.xlsx import (
    XLSXAltTextSubstitutionTest,
    XLSXSheetNavigationTest,
    XLSXScreenReaderTranscriptAnalyzer,
    XLSXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.shared.base import (
    behavioral_config_from_pipeline,
    run_behavioral_tests,
)
from project_remedy.config import PipelineConfig, load_config
from project_remedy.models import FileType
from project_remedy.office_acceptance import run_office_checker, run_office_screen_reader_checks
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
from project_remedy.quality_judges.shared.base import (
    QualityResult,
    QualityJudge,
    quality_config_from_pipeline,
)
from project_remedy.quality_judges.shared.dimensions import not_applicable_dimensions
from project_remedy.quality_judges.shared.ensemble import apply_behavioral_precedence


_FORMAT_BY_FILE_TYPE = {
    FileType.DOCX: "docx",
    FileType.PPTX: "pptx",
    FileType.XLSX: "xlsx",
}

_JUDGES_BY_FILE_TYPE: dict[FileType, tuple[type[QualityJudge], ...]] = {
    FileType.DOCX: (
        DOCXAltTextQualityJudge,
        DOCXReadingOrderJudge,
        DOCXHeadingSemanticsJudge,
        DOCXTableStructureJudge,
        DOCXLinkTextJudge,
        DOCXDecorativeJudge,
        DOCXComplexContentJudge,
    ),
    FileType.PPTX: (
        PPTXAltTextQualityJudge,
        PPTXSlideReadingOrderJudge,
        PPTXHeadingSemanticsJudge,
        PPTXTableStructureJudge,
        PPTXLinkTextJudge,
        PPTXDecorativeJudge,
        PPTXComplexContentJudge,
        PPTXSlideTitleJudge,
    ),
    FileType.XLSX: (
        XLSXAltTextQualityJudge,
        XLSXTableStructureJudge,
        XLSXLinkTextJudge,
        XLSXComplexContentJudge,
        XLSXSheetOrganizationJudge,
    ),
}

_BEHAVIORAL_BY_FILE_TYPE = {
    FileType.DOCX: (
        DOCXAltTextSubstitutionTest,
        DOCXReadingOrderComprehensionTest,
        DOCXHeadingNavigationTest,
        DOCXTableCellLookupTest,
        DOCXDecorativeSkipTest,
        DOCXScreenReaderTranscriptAnalyzer,
    ),
    FileType.PPTX: (
        PPTXAltTextSubstitutionTest,
        PPTXSlideReadingOrderComprehensionTest,
        PPTXSlideTitleNavigationTest,
        PPTXTableCellLookupTest,
        PPTXDecorativeSkipTest,
        PPTXScreenReaderTranscriptAnalyzer,
    ),
    FileType.XLSX: (
        XLSXAltTextSubstitutionTest,
        XLSXTableCellLookupTest,
        XLSXSheetNavigationTest,
        XLSXScreenReaderTranscriptAnalyzer,
    ),
}


def audit_office_quality(
    file_path: Path,
    *,
    file_type: FileType,
    config: PipelineConfig | None = None,
) -> QualityResult:
    """Run deterministic Office quality scaffolding over existing checks."""
    fmt = _FORMAT_BY_FILE_TYPE.get(file_type)
    if fmt is None:
        raise ValueError(f"Unsupported Office quality audit type: {file_type}")

    pipeline_config = config or load_config()
    quality_config = quality_config_from_pipeline(pipeline_config)
    behavioral_config = behavioral_config_from_pipeline(pipeline_config)

    checker_report = run_office_checker(file_path, file_type)
    screen_reader_result = run_office_screen_reader_checks(file_path, file_type)
    dimensions = {}
    failing: list[str] = []
    for judge_cls in _JUDGES_BY_FILE_TYPE[file_type]:
        score = judge_cls(quality_config).judge(file_path, checker_report=checker_report)
        dimensions[score.dimension] = score
        if score.score < 0.8:
            failing.append(score.dimension)

    result = QualityResult(
        format=fmt,
        dimensions=dimensions,
        behavioral=run_behavioral_tests(
            (test_cls() for test_cls in _BEHAVIORAL_BY_FILE_TYPE[file_type]),
            file_path,
            cache_path=behavioral_config.cache_path,
            behavioral_model=behavioral_config.model,
            checker_report=checker_report,
            screen_reader_result=screen_reader_result,
        ),
        overall_pass=not failing,
        failing_dimensions=failing,
        not_applicable_dimensions=list(not_applicable_dimensions(fmt)),
    )
    return apply_behavioral_precedence(result)
