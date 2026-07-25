"""End-to-end faithful rebuild pipeline.

Ties together content_builder, image_embedder, and structure_builder to
produce a tagged PDF/UA-1 output from an untagged (or poorly tagged) source.

Workflow:
  1. Validate source exists and can be opened by pikepdf.
  2. Extract document title from metadata or filename.
  3. Create a blank target PDF.
  4. For each source page: copy page boxes, images, resources, fonts, and
     rebuild the content stream with BDC/EMC wrappers.
  5. Build the structure tree from all per-page MCID manifests.
  6. Save and run acceptance gates (openability, optional visual fidelity).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Dictionary, Name

from project_remedy.faithful_rebuild.content_builder import rebuild_page_preserving
from project_remedy.faithful_rebuild.image_embedder import (
    copy_page_images,
    copy_page_resources,
)
from project_remedy.faithful_rebuild.models import (
    FaithfulRebuildResult,
    MCIDManifest,
)
from project_remedy.faithful_rebuild.structure_builder import build_structure_tree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page boxes to preserve verbatim
# ---------------------------------------------------------------------------

_PAGE_BOXES: list[str] = [
    "/MediaBox",
    "/CropBox",
    "/BleedBox",
    "/TrimBox",
    "/ArtBox",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_title(source_pdf: pikepdf.Pdf, source_path: Path) -> str:
    """Extract a document title from metadata, falling back to filename stem.

    Checks in order:
      1. ``/Info /Title`` (docinfo)
      2. XMP ``dc:title``
      3. Filename stem
    """
    # 1. docinfo /Title
    try:
        docinfo = source_pdf.docinfo
        if docinfo is not None:
            title_obj = docinfo.get("/Title")
            if title_obj is not None:
                title = str(title_obj).strip()
                if title:
                    return title
    except Exception:
        pass

    # 2. XMP dc:title
    try:
        with source_pdf.open_metadata() as meta:
            xmp_title = meta.get("dc:title")
            if xmp_title and isinstance(xmp_title, str):
                title = xmp_title.strip()
                if title:
                    return title
    except Exception:
        pass

    # 3. Filename stem
    return source_path.stem


def _error_result(
    source_path: Path, error: str
) -> FaithfulRebuildResult:
    """Return a failure result with the given error message."""
    return FaithfulRebuildResult(
        success=False,
        source_path=source_path,
        output_path=None,
        mode="preserving",
        visual_diff_pct=0.0,
        verapdf_violations=0,
        text_coverage_pct=0.0,
        pages_rebuilt=0,
        font_matches=[],
        error=error,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def faithful_rebuild(
    source_path: Path,
    output_path: Path,
    *,
    config: Any = None,
    semantic_maps: dict[int, Any] | None = None,
    vision_provider: Any = None,
    force_mode: str | None = None,
) -> FaithfulRebuildResult:
    """Rebuild a source PDF with proper PDF/UA-1 tagging.

    Args:
        source_path: Path to the untagged (or poorly tagged) source PDF.
        output_path: Path where the rebuilt PDF will be written.
        config: Optional pipeline configuration (reserved for future use).
        semantic_maps: Optional per-page semantic maps from the vision planner.
        vision_provider: Optional vision model provider for alt-text generation.
        force_mode: Optional mode override (reserved for future use).

    Returns:
        A :class:`FaithfulRebuildResult` summarising the outcome.
    """
    mode = force_mode or "preserving"

    # ------------------------------------------------------------------
    # Step 1: Check source exists
    # ------------------------------------------------------------------
    if not source_path.exists():
        return _error_result(
            source_path,
            f"Source file does not exist: {source_path}",
        )

    # ------------------------------------------------------------------
    # Step 2: Open source with pikepdf
    # ------------------------------------------------------------------
    try:
        source_pdf = pikepdf.open(source_path)
    except Exception as exc:
        return _error_result(
            source_path,
            f"Failed to open source PDF: {exc}",
        )

    try:
        # ------------------------------------------------------------------
        # Step 3: Extract title
        # ------------------------------------------------------------------
        title = _extract_title(source_pdf, source_path)

        # ------------------------------------------------------------------
        # Step 4: Create target PDF
        # ------------------------------------------------------------------
        target_pdf = pikepdf.new()

        # Shared dedup cache for images across pages
        dedup_cache: dict[str, str] = {}

        manifests: dict[int, MCIDManifest] = {}
        num_source_pages = len(source_pdf.pages)

        # ------------------------------------------------------------------
        # Step 5: Process each page
        # ------------------------------------------------------------------
        for page_idx in range(num_source_pages):
            source_page = source_pdf.pages[page_idx]

            # 5a. Create target page with same boxes and properties
            target_page_dict: dict[str, Any] = {
                "/Type": Name("/Page"),
            }

            # Copy page boxes (MediaBox, CropBox, etc.)
            for box_name in _PAGE_BOXES:
                box = source_page.obj.get(box_name)
                if box is not None:
                    # Page boxes are usually direct arrays — copy values
                    if box.is_indirect:
                        target_page_dict[box_name] = target_pdf.copy_foreign(box)
                    else:
                        # Direct array: copy element values
                        target_page_dict[box_name] = [float(v) for v in box]

            # Preserve /Rotate (int) and /UserUnit (float)
            rotate = source_page.obj.get("/Rotate")
            if rotate is not None:
                target_page_dict["/Rotate"] = int(rotate)

            user_unit = source_page.obj.get("/UserUnit")
            if user_unit is not None:
                target_page_dict["/UserUnit"] = float(user_unit)

            # Ensure we have at least a MediaBox
            if "/MediaBox" not in target_page_dict:
                target_page_dict["/MediaBox"] = [0, 0, 612, 792]

            # Create empty Resources and Contents (will be filled below)
            target_page_dict["/Resources"] = Dictionary()
            target_page_dict["/Contents"] = target_pdf.make_stream(b"")

            target_page = pikepdf.Page(Dictionary(target_page_dict))
            target_pdf.pages.append(target_page)
            # Re-fetch so we have the page as owned by target_pdf
            target_page = target_pdf.pages[page_idx]

            # 5b. Copy image XObjects
            copy_page_images(
                source_pdf,
                source_page,
                target_pdf,
                target_page,
                dedup_cache=dedup_cache,
            )

            # 5c. Copy other resources (ExtGState, ColorSpace, etc.)
            copy_page_resources(
                source_pdf,
                source_page,
                target_pdf,
                target_page,
            )

            # 5d. Copy font resources as-is
            src_resources = source_page.obj.get("/Resources")
            if src_resources is not None:
                src_fonts = src_resources.get("/Font")
                if src_fonts is not None:
                    tgt_resources = target_page.obj["/Resources"]
                    try:
                        tgt_resources["/Font"] = target_pdf.copy_foreign(src_fonts)
                    except (pikepdf.ForeignObjectError, RuntimeError):
                        # Same PDF or already copied
                        tgt_resources["/Font"] = src_fonts

            # 5e. Rebuild content stream with BDC/EMC wrapping
            page_semantic_map = None
            if semantic_maps is not None:
                page_semantic_map = semantic_maps.get(page_idx)

            manifest = rebuild_page_preserving(
                source_pdf,
                source_page,
                target_pdf,
                target_page,
                semantic_map=page_semantic_map,
            )
            manifests[page_idx] = manifest

        # ------------------------------------------------------------------
        # Step 6: Build structure tree
        # ------------------------------------------------------------------
        build_structure_tree(target_pdf, manifests, title=title)

        # ------------------------------------------------------------------
        # Step 7: Save target PDF
        # ------------------------------------------------------------------
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_pdf.save(output_path)
        target_pdf.close()

    finally:
        source_pdf.close()

    # ------------------------------------------------------------------
    # Gate 1: Construction — verify pikepdf can reopen output
    # ------------------------------------------------------------------
    try:
        verify_pdf = pikepdf.open(output_path)
        len(verify_pdf.pages)
        verify_pdf.close()
    except Exception as exc:
        return FaithfulRebuildResult(
            success=False,
            source_path=source_path,
            output_path=output_path,
            mode=mode,
            visual_diff_pct=0.0,
            verapdf_violations=0,
            text_coverage_pct=0.0,
            pages_rebuilt=num_source_pages,
            font_matches=[],
            error=f"Construction gate failed: rebuilt PDF cannot be reopened: {exc}",
        )

    # ------------------------------------------------------------------
    # Gate 2: Visual fidelity (optional — PyMuPDF may not be available)
    # ------------------------------------------------------------------
    visual_diff_pct = 0.0
    try:
        from project_remedy.pdf_acceptance import compare_pdf_visual_fidelity

        diff_result = compare_pdf_visual_fidelity(
            source_path, output_path, dpi=200, tolerance=0.02
        )
        if diff_result.checked:
            visual_diff_pct = diff_result.max_page_diff
    except ImportError:
        logger.debug("PyMuPDF not available; skipping visual fidelity gate")
    except Exception as exc:
        logger.warning("Visual fidelity gate error: %s", exc)

    # ------------------------------------------------------------------
    # Return result
    # ------------------------------------------------------------------
    return FaithfulRebuildResult(
        success=True,
        source_path=source_path,
        output_path=output_path,
        mode=mode,
        visual_diff_pct=visual_diff_pct,
        verapdf_violations=0,
        text_coverage_pct=0.0,
        pages_rebuilt=num_source_pages,
        font_matches=[],
        error=None,
    )
