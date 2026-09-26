"""/v1/pdf/* synchronous analysis endpoints.

Each endpoint takes a multipart PDF upload, runs a single engine
function, returns the result as JSON, and cleans up the temp file.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pikepdf
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from slowapi import Limiter

from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings


_PDF_MAGIC = b"%PDF-"


async def _stage_pdf(file: UploadFile, settings: Settings) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .pdf accepted.",
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max upload size ({settings.max_upload_mb} MB).",
        )
    if not contents.startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Not a valid PDF.",
        )
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    staging = settings.job_dir / f"_pdf-{uuid.uuid4().hex}.pdf"
    staging.write_bytes(contents)
    return staging


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / Paths / enums for JSON output."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "value") and obj.__class__.__bases__[0].__name__ == "Enum":
        return obj.value
    return obj


def build_router(settings: Settings, limiter: Limiter, upload_rate_limit: str) -> APIRouter:
    router = APIRouter(prefix="/v1/pdf")
    require_key = Depends(require_api_key_dependency(settings))
    upload_limit = limiter.limit(upload_rate_limit)

    # ------------------------------------------------------------------
    # /check — 32 accessibility checks
    # ------------------------------------------------------------------

    @router.post("/check", dependencies=[require_key])
    @upload_limit
    async def check(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        from project_remedy.pdf_checker import PDFAccessibilityChecker

        path = await _stage_pdf(file, settings)
        try:
            checker = PDFAccessibilityChecker(path)
            report = checker.run_all()
            return JSONResponse(_to_jsonable({
                "file_size": report.file_size,
                "page_count": report.page_count,
                "results": [
                    {
                        "rule_id": r.rule_id,
                        "description": r.description,
                        "category": r.category,
                        "status": r.status,
                        "fixable": r.fixable,
                        "details": r.details,
                    }
                    for r in report.results
                ],
                "passed_count": sum(1 for r in report.results if r.status == "Passed"),
                "failed_count": sum(1 for r in report.results if r.status == "Failed"),
                "manual_count": sum(1 for r in report.results if r.status not in ("Passed", "Failed")),
            }))
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /tags — structure tree
    # ------------------------------------------------------------------

    @router.post("/tags", dependencies=[require_key])
    @upload_limit
    async def tags(
        request: Request,
        max_depth: int = 10,
        file: UploadFile = File(...),
    ) -> JSONResponse:
        from project_remedy.pdf_checker import _get_struct_type, walk_structure_tree

        path = await _stage_pdf(file, settings)
        try:
            tag_list: list[dict[str, Any]] = []
            with pikepdf.open(path) as pdf:
                for node, depth, _parent in walk_structure_tree(pdf):
                    if depth > max_depth:
                        continue
                    tag_list.append({
                        "depth": depth,
                        "type": _get_struct_type(node) or "",
                        "has_alt": bool(node.get("/Alt")) if hasattr(node, "get") else False,
                        "has_actual_text": bool(node.get("/ActualText")) if hasattr(node, "get") else False,
                    })
            return JSONResponse({"total": len(tag_list), "tags": tag_list})
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /info — document metadata
    # ------------------------------------------------------------------

    @router.post("/info", dependencies=[require_key])
    @upload_limit
    async def info(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        path = await _stage_pdf(file, settings)
        try:
            out: dict[str, Any] = {"filename": file.filename, "file_size": path.stat().st_size}
            with pikepdf.open(path) as pdf:
                out["pages"] = len(pdf.pages)
                out["pdf_version"] = str(pdf.pdf_version)
                with pdf.open_metadata() as meta:
                    out["metadata"] = {
                        k: str(v) for k, v in meta.items()
                        if isinstance(v, (str, int, float))
                    }
                root = pdf.Root
                out["tagged"] = bool(root.get("/StructTreeRoot"))
                out["language"] = str(root.get("/Lang", ""))
                mark_info = root.get("/MarkInfo", {})
                out["marked"] = bool(mark_info.get("/Marked", False)) if mark_info else False
                view_prefs = root.get("/ViewerPreferences", {})
                out["display_doc_title"] = bool(view_prefs.get("/DisplayDocTitle", False)) if view_prefs else False
                # Fonts inventory
                fonts: set[str] = set()
                for page in pdf.pages:
                    resources = page.get("/Resources", {})
                    fonts_dict = resources.get("/Font", {}) if resources else {}
                    for fkey in (fonts_dict or {}):
                        fonts.add(str(fkey))
                out["font_resource_keys"] = sorted(fonts)
            return JSONResponse(out)
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /reading-order — reading order analysis (stub delegating to engine)
    # ------------------------------------------------------------------

    @router.post("/reading-order", dependencies=[require_key])
    @upload_limit
    async def reading_order(
        request: Request,
        page: int | None = None, file: UploadFile = File(...)
    ) -> JSONResponse:
        from project_remedy.xy_cut import BBox, xy_cut_sort

        path = await _stage_pdf(file, settings)
        try:
            import fitz  # pymupdf
            doc = fitz.open(path)
            pages_out: list[dict[str, Any]] = []
            try:
                page_range = range(page - 1, page) if page else range(len(doc))
                for p_idx in page_range:
                    if p_idx < 0 or p_idx >= len(doc):
                        continue
                    pg = doc[p_idx]
                    blocks = pg.get_text("dict")["blocks"]
                    bboxes = []
                    for b in blocks:
                        if b.get("type") != 0:  # text blocks only
                            continue
                        x0, y0, x1, y1 = b["bbox"]
                        bboxes.append(BBox(x0=x0, y0=y0, x1=x1, y1=y1, index=len(bboxes)))
                    order = [b.index for b in xy_cut_sort(bboxes, pg.rect.width, pg.rect.height)]
                    pages_out.append({
                        "page": p_idx + 1,
                        "block_count": len(bboxes),
                        "reading_order": order,
                    })
            finally:
                doc.close()
            return JSONResponse({"pages": pages_out})
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /screen-reader — screen-reader simulation
    # ------------------------------------------------------------------

    @router.post("/screen-reader", dependencies=[require_key])
    @upload_limit
    async def screen_reader(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        from project_remedy.tag_tree_reader import validate_tag_tree

        path = await _stage_pdf(file, settings)
        try:
            result = validate_tag_tree(path)
            return JSONResponse(_to_jsonable({
                "passed": result.passed,
                "transcript": [asdict(frag) for frag in result.tag_tree.fragments] if result.tag_tree else [],
                "issues": [asdict(iss) for iss in result.issues],
                "summary": {
                    "error_count": sum(1 for i in result.issues if i.severity.value == "error"),
                    "warning_count": sum(1 for i in result.issues if i.severity.value == "warning"),
                    "fragment_count": len(result.tag_tree.fragments) if result.tag_tree else 0,
                },
            }))
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /alt-text/audit — find missing or generic alt text
    # ------------------------------------------------------------------

    @router.post("/alt-text/audit", dependencies=[require_key])
    @upload_limit
    async def alt_text_audit(
        request: Request,
        missing_only: bool = False, file: UploadFile = File(...)
    ) -> JSONResponse:
        from project_remedy.pdf_checker import _get_struct_type, walk_structure_tree

        path = await _stage_pdf(file, settings)
        try:
            findings: list[dict[str, Any]] = []
            with pikepdf.open(path) as pdf:
                for node, depth, _parent in walk_structure_tree(pdf):
                    stype = _get_struct_type(node) or ""
                    if stype not in ("Figure", "Formula"):
                        continue
                    alt = str(node.get("/Alt", "")) if hasattr(node, "get") else ""
                    actual = str(node.get("/ActualText", "")) if hasattr(node, "get") else ""
                    is_generic = alt.strip().lower() in ("", "image", "figure", "graphic", "photo")
                    if missing_only and alt:
                        continue
                    findings.append({
                        "type": stype,
                        "depth": depth,
                        "alt": alt,
                        "actual_text": actual,
                        "missing": not alt,
                        "generic": is_generic and bool(alt),
                    })
            return JSONResponse({
                "total_figures": len(findings),
                "missing_count": sum(1 for f in findings if f["missing"]),
                "generic_count": sum(1 for f in findings if f["generic"]),
                "findings": findings,
            })
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /artifacts — artifact inventory
    # ------------------------------------------------------------------

    @router.post("/artifacts", dependencies=[require_key])
    @upload_limit
    async def artifacts(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        path = await _stage_pdf(file, settings)
        try:
            counts: dict[str, int] = {}
            with pikepdf.open(path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    try:
                        content = page.Contents.read_bytes() if hasattr(page, "Contents") else b""
                    except Exception:
                        content = b""
                    # count "/Artifact" markers in content
                    n = content.count(b"/Artifact")
                    if n:
                        counts[f"page_{page_idx+1}"] = n
            return JSONResponse({
                "page_counts": counts,
                "total": sum(counts.values()),
            })
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # /fonts/check — font validation
    # ------------------------------------------------------------------

    @router.post("/fonts/check", dependencies=[require_key])
    @upload_limit
    async def fonts_check(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        path = await _stage_pdf(file, settings)
        try:
            report: list[dict[str, Any]] = []
            with pikepdf.open(path) as pdf:
                seen: set[int] = set()
                for page in pdf.pages:
                    resources = page.get("/Resources", {})
                    fonts = resources.get("/Font", {}) if resources else {}
                    for fkey, font in (fonts or {}).items():
                        # Dedup by object id
                        try:
                            oid = font.objgen if hasattr(font, "objgen") else id(font)
                        except Exception:
                            oid = id(font)
                        if oid in seen:
                            continue
                        seen.add(oid)
                        info = {
                            "key": str(fkey),
                            "subtype": str(font.get("/Subtype", "")),
                            "base_font": str(font.get("/BaseFont", "")),
                            "has_tounicode": bool(font.get("/ToUnicode")),
                            "has_encoding": bool(font.get("/Encoding")),
                            "embedded": bool(font.get("/FontDescriptor", {}).get("/FontFile")
                                              or font.get("/FontDescriptor", {}).get("/FontFile2")
                                              or font.get("/FontDescriptor", {}).get("/FontFile3")),
                        }
                        report.append(info)
            return JSONResponse({
                "total": len(report),
                "missing_tounicode": sum(1 for f in report if not f["has_tounicode"]),
                "not_embedded": sum(1 for f in report if not f["embedded"]),
                "fonts": report,
            })
        finally:
            path.unlink(missing_ok=True)

    return router
