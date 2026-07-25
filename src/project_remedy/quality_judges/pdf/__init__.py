"""PDF quality judges."""

from project_remedy.quality_judges.pdf.alt_text_judge import PDFAltTextQualityJudge
from project_remedy.quality_judges.pdf.complex_content_judge import (
    PDFComplexContentJudge,
)
from project_remedy.quality_judges.pdf.decorative_judge import PDFDecorativeJudge
from project_remedy.quality_judges.pdf.heading_semantics_judge import (
    PDFHeadingSemanticsJudge,
)
from project_remedy.quality_judges.pdf.link_text_judge import PDFLinkTextJudge
from project_remedy.quality_judges.pdf.reading_order_judge import PDFReadingOrderJudge
from project_remedy.quality_judges.pdf.table_structure_judge import (
    PDFTableStructureJudge,
)

__all__ = [
    "PDFAltTextQualityJudge",
    "PDFComplexContentJudge",
    "PDFDecorativeJudge",
    "PDFHeadingSemanticsJudge",
    "PDFLinkTextJudge",
    "PDFReadingOrderJudge",
    "PDFTableStructureJudge",
]
