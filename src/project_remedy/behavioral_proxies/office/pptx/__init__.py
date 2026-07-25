"""PPTX behavioral proxies."""

from project_remedy.behavioral_proxies.office.pptx.alt_text_substitution import (
    PPTXAltTextSubstitutionTest,
)
from project_remedy.behavioral_proxies.office.pptx.decorative_skip import (
    PPTXDecorativeSkipTest,
)
from project_remedy.behavioral_proxies.office.pptx.slide_reading_order_comprehension import (
    PPTXSlideReadingOrderComprehensionTest,
)
from project_remedy.behavioral_proxies.office.pptx.slide_title_navigation import (
    PPTXSlideTitleNavigationTest,
)
from project_remedy.behavioral_proxies.office.pptx.table_cell_lookup import (
    PPTXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.office.transcript_analyzer import (
    PPTXScreenReaderTranscriptAnalyzer,
)

__all__ = [
    "PPTXAltTextSubstitutionTest",
    "PPTXDecorativeSkipTest",
    "PPTXSlideReadingOrderComprehensionTest",
    "PPTXSlideTitleNavigationTest",
    "PPTXScreenReaderTranscriptAnalyzer",
    "PPTXTableCellLookupTest",
]
