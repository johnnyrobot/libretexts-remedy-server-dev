"""XLSX quality judges."""

from project_remedy.quality_judges.office.xlsx.alt_text_judge import (
    XLSXAltTextQualityJudge,
)
from project_remedy.quality_judges.office.xlsx.complex_content_judge import (
    XLSXComplexContentJudge,
)
from project_remedy.quality_judges.office.xlsx.link_text_judge import (
    XLSXLinkTextJudge,
)
from project_remedy.quality_judges.office.xlsx.sheet_organization_judge import (
    XLSXSheetOrganizationJudge,
)
from project_remedy.quality_judges.office.xlsx.table_structure_judge import (
    XLSXTableStructureJudge,
)

__all__ = [
    "XLSXAltTextQualityJudge",
    "XLSXComplexContentJudge",
    "XLSXLinkTextJudge",
    "XLSXSheetOrganizationJudge",
    "XLSXTableStructureJudge",
]
