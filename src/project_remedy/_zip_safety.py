"""Shared safety limits for decoding untrusted uploaded documents.

These helpers bound resource usage when reading attacker-controlled OOXML
(Office) ZIP packages and Pillow-decoded images, mitigating decompression
"bomb" inputs that inflate from a few KB on disk to gigabytes in memory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zipfile import ZipFile

# Bounds the decompressed size of a *single* OOXML part (e.g. one document.xml
# or drawing XML). 50 MiB is generous for legitimate Office parts while
# preventing a tiny "zip bomb" entry from inflating to GBs in memory.
MAX_OOXML_PART_BYTES = 50 * 1024 * 1024

# Bounds the number of pixels Pillow will decode for an image extracted from an
# uploaded PDF. 128M pixels comfortably covers legitimate 300-600 DPI document
# scans (e.g. a 600 DPI A0 page) while preventing decompression bombs from
# decoding hundreds of MB. Oversized images raise Image.DecompressionBombError.
MAX_IMAGE_PIXELS = 128_000_000


def read_zip_member_safely(
    package: ZipFile,
    name: str,
    *,
    max_bytes: int = MAX_OOXML_PART_BYTES,
) -> bytes | None:
    """Read a ZIP member, refusing parts whose decompressed size exceeds a cap.

    Consults the member's declared decompressed ``file_size`` before reading.
    Returns ``None`` if the member is missing or exceeds ``max_bytes`` so that
    callers can treat an oversized part the same as an unavailable one. Returns
    the decompressed bytes otherwise.
    """
    try:
        info = package.getinfo(name)
    except KeyError:
        return None
    if info.file_size > max_bytes:
        return None
    return package.read(name)
