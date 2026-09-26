"""DOCX quality judges."""

from project_remedy.quality_judges.office.docx.alt_text_judge import (
    DOCXAltTextQualityJudge,
)
from project_remedy.quality_judges.office.docx.complex_content_judge import (
    DOCXComplexContentJudge,
)
from project_remedy.quality_judges.office.docx.decorative_judge import (
    DOCXDecorativeJudge,
)
from project_remedy.quality_judges.office.docx.heading_semantics_judge import (
    DOCXHeadingSemanticsJudge,
)
from project_remedy.quality_judges.office.docx.link_text_judge import (
    DOCXLinkTextJudge,
)
from project_remedy.quality_judges.office.docx.reading_order_judge import (
    DOCXReadingOrderJudge,
)
from project_remedy.quality_judges.office.docx.table_structure_judge import (
    DOCXTableStructureJudge,
)

__all__ = [
    "DOCXAltTextQualityJudge",
    "DOCXComplexContentJudge",
    "DOCXDecorativeJudge",
    "DOCXHeadingSemanticsJudge",
    "DOCXLinkTextJudge",
    "DOCXReadingOrderJudge",
    "DOCXTableStructureJudge",
]
