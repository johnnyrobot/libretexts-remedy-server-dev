"""PDF behavioral proxy tests."""

from project_remedy.behavioral_proxies.pdf.alt_text_substitution import (
    PDFAltTextSubstitutionTest,
    score_alt_text_substitution_report,
)
from project_remedy.behavioral_proxies.pdf.decorative_skip_test import (
    PDFDecorativeSkipTest,
    score_decorative_skip_report,
)
from project_remedy.behavioral_proxies.pdf.heading_navigation import (
    PDFHeadingNavigationTest,
    score_heading_navigation_report,
)
from project_remedy.behavioral_proxies.pdf.reading_order_comprehension import (
    PDFReadingOrderComprehensionTest,
    score_reading_order_report,
)
from project_remedy.behavioral_proxies.pdf.table_cell_lookup import (
    PDFTableCellLookupTest,
    score_table_cell_lookup_report,
)
from project_remedy.behavioral_proxies.pdf.transcript_analyzer import (
    PDFTranscriptAnalyzer,
    analyze_tag_tree_report,
)

__all__ = [
    "PDFAltTextSubstitutionTest",
    "PDFDecorativeSkipTest",
    "PDFHeadingNavigationTest",
    "PDFReadingOrderComprehensionTest",
    "PDFTableCellLookupTest",
    "PDFTranscriptAnalyzer",
    "analyze_tag_tree_report",
    "score_alt_text_substitution_report",
    "score_decorative_skip_report",
    "score_heading_navigation_report",
    "score_reading_order_report",
    "score_table_cell_lookup_report",
]
