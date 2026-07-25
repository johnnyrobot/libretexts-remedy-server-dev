"""DOCX behavioral proxies."""

from project_remedy.behavioral_proxies.office.docx.alt_text_substitution import (
    DOCXAltTextSubstitutionTest,
)
from project_remedy.behavioral_proxies.office.docx.decorative_skip import (
    DOCXDecorativeSkipTest,
)
from project_remedy.behavioral_proxies.office.docx.heading_navigation import (
    DOCXHeadingNavigationTest,
)
from project_remedy.behavioral_proxies.office.docx.reading_order_comprehension import (
    DOCXReadingOrderComprehensionTest,
)
from project_remedy.behavioral_proxies.office.docx.table_cell_lookup import (
    DOCXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.office.transcript_analyzer import (
    DOCXScreenReaderTranscriptAnalyzer,
)

__all__ = [
    "DOCXAltTextSubstitutionTest",
    "DOCXDecorativeSkipTest",
    "DOCXHeadingNavigationTest",
    "DOCXReadingOrderComprehensionTest",
    "DOCXScreenReaderTranscriptAnalyzer",
    "DOCXTableCellLookupTest",
]
