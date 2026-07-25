"""Bulk vision enrichment for rebuild-tier images.

Takes the extractor's list of extracted images and, for each, asks a
VisionProvider two questions:
  1. Is this image purely decorative?
  2. If not, write a concise alt text for a screen reader.

Returns a dict keyed by ExtractedImage.filename.

Per-image failure is absorbed: the image's semantics become
`ImageSemantics(alt="", decorative=True, confidence=0.0)` so the
downstream ast_builder can safely emit an ArtifactBlock. If *every*
image fails (or the provider is unavailable), the whole pass raises
VisionEnrichmentError so the rebuild job surfaces the issue.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from project_remedy.models import ExtractedImage

logger = logging.getLogger(__name__)


class VisionEnrichmentError(RuntimeError):
    """All images failed vision enrichment."""


@dataclass(frozen=True)
class ImageSemantics:
    alt: str
    decorative: bool
    confidence: float


# Reused from existing src/project_remedy/vision_prompts.py:
#   figure_alt_prompt()           → alt-text generator
#   image_classification_prompt() → decorative classifier
# This module wraps both into one per-image call that returns a
# single JSON blob with both fields.

_COMBINED_PROMPT = """\
Classify this image and generate alt text in a single JSON response.

Respond with ONLY valid JSON in this exact shape:
{
  "decorative": true | false,
  "alt": "<concise screen-reader-usable description, OR empty string if decorative>"
}

Rules:
- "decorative" = true when the image is purely visual (ornament, bullet,
  divider, background pattern, logo that's redundant with text nearby).
- "decorative" = false when the image conveys information (chart, diagram,
  photograph with content, text embedded in an image).
- "alt" must be ≤ 125 characters. If decorative is true, alt MUST be "".
- No markdown, no explanation — ONLY the JSON object.
"""


async def enrich(
    images: list[ExtractedImage],
    provider,
    *,
    concurrency: int = 4,
) -> dict[str, ImageSemantics]:
    """Classify + describe each image. Keyed by filename."""
    if not images:
        return {}

    semaphore = asyncio.Semaphore(concurrency)
    results: dict[str, ImageSemantics] = {}
    failure_count = 0

    async def _one(image: ExtractedImage) -> None:
        nonlocal failure_count
        async with semaphore:
            try:
                # The provider's .analyze_image takes Path-or-str + prompt.
                # Real providers live in src/project_remedy/pdf_vision.py.
                raw = await provider.analyze_image(Path(image.filename), _COMBINED_PROMPT)
                parsed = _parse(raw)
                results[image.filename] = ImageSemantics(
                    alt=parsed["alt"],
                    decorative=parsed["decorative"],
                    confidence=1.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "rebuild.vision.image job_id=? filename=%s error=%s",
                    image.filename, exc,
                )
                results[image.filename] = ImageSemantics(alt="", decorative=True, confidence=0.0)
                failure_count += 1

    await asyncio.gather(*(_one(img) for img in images))

    if failure_count == len(images):
        raise VisionEnrichmentError(
            f"all {len(images)} vision calls failed; rebuild cannot proceed"
        )

    logger.info(
        "rebuild.vision images=%d succeeded=%d failed=%d",
        len(images),
        len(images) - failure_count,
        failure_count,
    )
    return results


def _parse(raw) -> dict:
    """Parse a vision provider's response into {'decorative': bool, 'alt': str}."""
    if isinstance(raw, dict):
        return {
            "decorative": bool(raw.get("decorative", True)),
            "alt": str(raw.get("alt", ""))[:125],
        }
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        # Strip common wrappers the model might emit.
        s = raw.strip()
        if s.startswith("```"):
            s = s.strip("`").lstrip("json").strip()
        obj = json.loads(s)
        return {
            "decorative": bool(obj.get("decorative", True)),
            "alt": str(obj.get("alt", ""))[:125],
        }
    raise ValueError(f"vision response not parseable: {type(raw).__name__}")
