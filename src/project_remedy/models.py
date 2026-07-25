"""Core data models for the PDF accessibility remediation engine.

Includes the generic ``DocumentJob`` used by the HTML-conversion path
(``extractor`` → ``converter`` → ``vision`` → ``validator``). The HTTP
API layer in ``backend/app/`` has its own async ``Job`` for queue state;
``DocumentJob`` here is engine-level content state during conversion.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class FileType(enum.Enum):
    """Supported document file types."""

    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    PPTX = "pptx"
    PPT = "ppt"
    XLSX = "xlsx"
    XLS = "xls"


class JobStatus(enum.Enum):
    """Lifecycle state of a ``DocumentJob`` passing through the HTML pipeline."""

    DISCOVERED = "discovered"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    PLANNING = "planning"
    PLANNED = "planned"
    CONVERTING = "converting"
    CONVERTED = "converted"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REMEDIATING = "remediating"
    REMEDIATED = "remediated"
    FLAGGED = "flagged"
    FAILED = "failed"


@dataclass
class ExtractedImage:
    """Metadata for an image extracted from a PDF."""

    filename: str
    page_number: int
    xref: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "page_number": self.page_number,
            "xref": self.xref,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractedImage:
        return cls(
            filename=data["filename"],
            page_number=data["page_number"],
            xref=data["xref"],
            width=data["width"],
            height=data["height"],
        )


@dataclass
class ValidationResult:
    """Result from a single accessibility validation tool."""

    tool: str  # axe, pa11y, lighthouse, wave
    score: float | None = None
    violations: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = False
    page_key: str = ""
    page_title: str = ""
    page_path: str = ""


@dataclass
class RenderedPage:
    """A deployable HTML artifact derived from a document."""

    page_key: str
    kind: str
    title: str
    relative_path: str
    html: str
    source_page_range: str = ""
    section_slug: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_key": self.page_key,
            "kind": self.kind,
            "title": self.title,
            "relative_path": self.relative_path,
            "html": self.html,
            "source_page_range": self.source_page_range,
            "section_slug": self.section_slug,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderedPage:
        return cls(
            page_key=data.get("page_key", ""),
            kind=data.get("kind", "canonical"),
            title=data.get("title", ""),
            relative_path=data.get("relative_path", ""),
            html=data.get("html", ""),
            source_page_range=data.get("source_page_range", ""),
            section_slug=data.get("section_slug", ""),
        )


@dataclass
class DocumentJob:
    """Content-state envelope passed through the HTML-conversion pipeline.

    Distinct from ``backend.app.jobs.Job`` — that tracks HTTP-layer queue
    state; this tracks document-content state during extract → plan →
    convert → validate.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    url: str = ""
    source_page_url: str = ""
    link_text: str = ""
    link_context: str = ""
    file_type: FileType | None = None
    local_path: str = ""
    file_hash: str = ""
    file_size: int = 0
    status: JobStatus = JobStatus.DISCOVERED
    ocr_markdown: str = ""
    html_plan: str = ""
    generated_html: str = ""
    generated_pages_json: str = "[]"
    final_html_path: str = ""
    remediated_document_path: str = ""
    remediated_pdf_path: str = ""
    validation_results: list[ValidationResult] = field(default_factory=list)
    extracted_images_json: str = "[]"
    remediation_count: int = 0
    error_message: str = ""
    warning_message: str = ""
    acceptance_warnings_json: str = "[]"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "source_page_url": self.source_page_url,
            "link_text": self.link_text,
            "link_context": self.link_context,
            "file_type": self.file_type.value if self.file_type else None,
            "local_path": self.local_path,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "status": self.status.value,
            "ocr_markdown": self.ocr_markdown,
            "html_plan": self.html_plan,
            "generated_html": self.generated_html,
            "generated_pages_json": self.generated_pages_json,
            "extracted_images_json": self.extracted_images_json,
            "final_html_path": self.final_html_path,
            "remediated_document_path": self.remediated_document_path,
            "remediated_pdf_path": self.remediated_pdf_path,
            "remediation_count": self.remediation_count,
            "error_message": self.error_message,
            "warning_message": self.warning_message,
            "acceptance_warnings_json": self.acceptance_warnings_json,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def get_rendered_pages(self) -> list[RenderedPage]:
        """Return persisted rendered pages, with a canonical fallback."""
        try:
            raw_pages = json.loads(self.generated_pages_json or "[]")
        except json.JSONDecodeError:
            raw_pages = []

        pages = [
            RenderedPage.from_dict(page)
            for page in raw_pages
            if isinstance(page, dict)
        ]
        if pages:
            return pages

        if self.generated_html:
            return [
                RenderedPage(
                    page_key="canonical",
                    kind="canonical",
                    title=self.link_text.strip() or "Document",
                    relative_path="",
                    html=self.generated_html,
                )
            ]

        return []

    def set_rendered_pages(self, pages: list[RenderedPage]) -> None:
        """Persist rendered pages to JSON and sync the canonical payload."""
        self.generated_pages_json = json.dumps(
            [page.to_dict() for page in pages],
            ensure_ascii=False,
        )
        canonical = next(
            (page for page in pages if page.kind == "canonical"),
            None,
        )
        if canonical:
            self.generated_html = canonical.html

    def get_extracted_images(self) -> list[ExtractedImage]:
        try:
            raw = json.loads(self.extracted_images_json or "[]")
        except json.JSONDecodeError:
            return []
        return [ExtractedImage.from_dict(item) for item in raw if isinstance(item, dict)]

    def set_extracted_images(self, images: list[ExtractedImage]) -> None:
        self.extracted_images_json = json.dumps(
            [img.to_dict() for img in images],
            ensure_ascii=False,
        )

    def get_acceptance_warnings(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.acceptance_warnings_json or "[]")
        except json.JSONDecodeError:
            return []
        return [item for item in raw if isinstance(item, dict)]

    def set_acceptance_warnings(self, warnings: list[dict[str, Any]]) -> None:
        self.acceptance_warnings_json = json.dumps(warnings, ensure_ascii=False)
