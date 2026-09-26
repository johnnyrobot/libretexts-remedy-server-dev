"""XLSX behavioral proxies."""

from project_remedy.behavioral_proxies.office.xlsx.alt_text_substitution import (
    XLSXAltTextSubstitutionTest,
)
from project_remedy.behavioral_proxies.office.xlsx.sheet_navigation import (
    XLSXSheetNavigationTest,
)
from project_remedy.behavioral_proxies.office.xlsx.table_cell_lookup import (
    XLSXTableCellLookupTest,
)
from project_remedy.behavioral_proxies.office.transcript_analyzer import (
    XLSXScreenReaderTranscriptAnalyzer,
)

__all__ = [
    "XLSXAltTextSubstitutionTest",
    "XLSXSheetNavigationTest",
    "XLSXScreenReaderTranscriptAnalyzer",
    "XLSXTableCellLookupTest",
]
