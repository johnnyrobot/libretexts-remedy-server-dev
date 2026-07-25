"""Fan-in: parsed blocks + vision output → RebuildRequest.

Pure function. Replaces ImagePlaceholder blocks with FigureBlock (alt
from vision) or ArtifactBlock (decorative flag set). Builds the
AssetRef dict from extracted images. Pydantic's model_validator
enforces the dangling-asset_ref invariant.
"""
from __future__ import annotations

from pathlib import Path

from project_remedy.models import ExtractedImage
from project_remedy.rebuild.ast import (
    ArtifactBlock,
    AssetRef,
    Block,
    Conformance,
    FigureBlock,
    ListBlock,
    ListItem,
    Metadata,
    PageSettings,
    RebuildRequest,
)
from project_remedy.rebuild.markdown_parser import ImagePlaceholder
from project_remedy.rebuild.vision_enricher import ImageSemantics


class ASTBuildError(RuntimeError):
    """Composer could not assemble a valid RebuildRequest."""


_SUPPORTED_MIMES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


def build(
    block_tree: list,
    image_semantics: dict[str, ImageSemantics],
    extracted_images: list[ExtractedImage],
    metadata: Metadata,
    page: PageSettings,
    conformance: Conformance,
    *,
    image_dir: Path | None = None,
) -> RebuildRequest:
    """Merge parsed blocks + vision output into a RebuildRequest.

    image_dir: directory where ExtractedImage.filename entries live on disk.
    Required for the rebuild-tier production path (extractor writes images
    to JOB_DIR/{id}/images/). When None, falls back to treating filenames
    as absolute-if-exist-else-literal (legacy behavior for tests that
    synthesize ExtractedImage with bare filenames).
    """
    if not block_tree:
        raise ASTBuildError("no content to rebuild (block_tree is empty)")

    images_by_name = {img.filename: img for img in extracted_images}
    assets: dict[str, AssetRef] = {}

    substituted = [
        _substitute(node, image_semantics, images_by_name, assets, image_dir)
        for node in block_tree
    ]
    substituted = [b for b in substituted if b is not None]
    if not substituted:
        raise ASTBuildError("every block was filtered during substitution")

    try:
        return RebuildRequest(
            metadata=metadata,
            page=page,
            conformance=conformance,
            content=substituted,
            assets=assets,
        )
    except Exception as exc:
        raise ASTBuildError(f"RebuildRequest validation failed: {exc}") from exc


def _substitute(
    node,
    semantics: dict[str, ImageSemantics],
    images_by_name: dict[str, ExtractedImage],
    assets: dict[str, AssetRef],
    image_dir: Path | None,
) -> Block | None:
    """Recursively replace ImagePlaceholder with Figure/Artifact; update assets."""
    if isinstance(node, ImagePlaceholder):
        if node.filename not in images_by_name:
            raise ASTBuildError(
                f"image placeholder references unknown file: {node.filename!r}"
            )
        asset_ref = node.filename
        assets[asset_ref] = _make_asset(images_by_name[asset_ref], image_dir)
        sem = semantics.get(asset_ref)
        if sem is None or sem.decorative or not sem.alt.strip():
            return ArtifactBlock(asset_ref=asset_ref)
        return FigureBlock(asset_ref=asset_ref, alt=sem.alt)

    if isinstance(node, ListBlock):
        new_items = []
        for item in node.items:
            new_body = [
                _substitute(c, semantics, images_by_name, assets, image_dir)
                for c in item.body
            ]
            new_body = [b for b in new_body if b is not None]
            new_items.append(ListItem(label_runs=item.label_runs, body=new_body))
        return ListBlock(ordered=node.ordered, items=new_items)

    return node


def _make_asset(img: ExtractedImage, image_dir: Path | None) -> AssetRef:
    suffix = Path(img.filename).suffix.lstrip(".").lower()
    mime = _SUPPORTED_MIMES.get(suffix, "image/png")
    if image_dir is not None:
        resolved = (image_dir / img.filename).resolve()
        path = str(resolved)
    else:
        # Back-compat for callers that already pass absolute paths in filename
        p = Path(img.filename)
        path = str(p.resolve() if p.exists() else p)
    return AssetRef(path=path, mime=mime)
