"""PDF quality audit orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from project_remedy.behavioral_proxies.pdf import (
    PDFAltTextSubstitutionTest,
    PDFDecorativeSkipTest,
    PDFHeadingNavigationTest,
    PDFReadingOrderComprehensionTest,
    PDFTableCellLookupTest,
    PDFTranscriptAnalyzer,
)
from project_remedy.behavioral_proxies.shared.base import (
    behavioral_config_from_pipeline,
    run_behavioral_tests,
)
from project_remedy.config import PipelineConfig, load_config
from project_remedy.quality_judges.pdf import (
    PDFAltTextQualityJudge,
    PDFComplexContentJudge,
    PDFDecorativeJudge,
    PDFHeadingSemanticsJudge,
    PDFLinkTextJudge,
    PDFReadingOrderJudge,
    PDFTableStructureJudge,
)
from project_remedy.quality_judges.shared.base import (
    QualityResult,
    quality_config_from_pipeline,
)
from project_remedy.quality_judges.shared.ensemble import (
    QualityJudgeEnsemble,
    apply_behavioral_precedence,
)
from project_remedy.tag_tree_reader import TagTreeReport, read_tag_tree


def audit_pdf_quality(
    pdf_path: Path,
    *,
    config: PipelineConfig | None = None,
    tag_tree_report: TagTreeReport | None = None,
) -> QualityResult:
    """Run the inactive PDF quality judge ensemble for an uploaded PDF."""
    pipeline_config = config or load_config()
    judge_config = quality_config_from_pipeline(pipeline_config)
    behavioral_config = behavioral_config_from_pipeline(pipeline_config)
    report = tag_tree_report or read_tag_tree(pdf_path)
    judges = [
        PDFAltTextQualityJudge(judge_config),
        PDFReadingOrderJudge(judge_config),
        PDFHeadingSemanticsJudge(judge_config),
        PDFTableStructureJudge(judge_config),
        PDFLinkTextJudge(judge_config),
        PDFDecorativeJudge(judge_config),
        PDFComplexContentJudge(judge_config),
    ]
    behavioral_tests = [
        PDFReadingOrderComprehensionTest(),
        PDFAltTextSubstitutionTest(),
        PDFHeadingNavigationTest(),
        PDFTableCellLookupTest(),
        PDFDecorativeSkipTest(),
        PDFTranscriptAnalyzer(),
    ]
    behavioral = run_behavioral_tests(
        behavioral_tests,
        pdf_path,
        cache_path=behavioral_config.cache_path,
        behavioral_model=behavioral_config.model,
        tag_tree_report=report,
    )
    ensemble_result = QualityJudgeEnsemble(judges).judge(pdf_path, tag_tree_report=report)
    # ``replace`` re-runs ``QualityResult.__post_init__`` so the behavioral
    # cross-field validation (key/test_name agreement, format match) fires
    # instead of being bypassed by post-construction assignment. Matches the
    # office audit, which passes ``behavioral`` to the constructor directly.
    result = replace(ensemble_result, behavioral=behavioral)
    return apply_behavioral_precedence(result)
