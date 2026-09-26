"""PPTX quality judges."""

from project_remedy.quality_judges.office.pptx.alt_text_judge import (
    PPTXAltTextQualityJudge,
)
from project_remedy.quality_judges.office.pptx.complex_content_judge import (
    PPTXComplexContentJudge,
)
from project_remedy.quality_judges.office.pptx.decorative_judge import (
    PPTXDecorativeJudge,
)
from project_remedy.quality_judges.office.pptx.heading_semantics_judge import (
    PPTXHeadingSemanticsJudge,
)
from project_remedy.quality_judges.office.pptx.link_text_judge import (
    PPTXLinkTextJudge,
)
from project_remedy.quality_judges.office.pptx.slide_reading_order_judge import (
    PPTXSlideReadingOrderJudge,
)
from project_remedy.quality_judges.office.pptx.slide_title_judge import (
    PPTXSlideTitleJudge,
)
from project_remedy.quality_judges.office.pptx.table_structure_judge import (
    PPTXTableStructureJudge,
)

__all__ = [
    "PPTXAltTextQualityJudge",
    "PPTXComplexContentJudge",
    "PPTXDecorativeJudge",
    "PPTXHeadingSemanticsJudge",
    "PPTXLinkTextJudge",
    "PPTXSlideReadingOrderJudge",
    "PPTXSlideTitleJudge",
    "PPTXTableStructureJudge",
]
