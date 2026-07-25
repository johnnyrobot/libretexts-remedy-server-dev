"""Async subprocess wrapper for the QuestPDF rebuild sidecar.

The sidecar is a native AOT .NET binary that reads a JSON RebuildRequest
on stdin and writes a PDF on stdout. Structured JSON errors land on
stderr when the sidecar fails.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
from dataclasses import dataclass

from project_remedy.rebuild.ast import RebuildRequest

logger = logging.getLogger(__name__)


class SidecarError(RuntimeError):
    """The sidecar exited non-zero or produced no PDF."""


class SidecarTimeout(SidecarError):
    """The sidecar exceeded the configured timeout."""


@dataclass
class QuestPdfSidecar:
    binary_path: pathlib.Path
    timeout_s: float = 30.0
    args: list[str] | None = None

    async def render(self, request: RebuildRequest) -> bytes:
        payload = request.model_dump_json().encode("utf-8")
        argv = [str(self.binary_path), *(self.args or [])]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(payload), timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SidecarTimeout(
                f"sidecar timed out after {self.timeout_s}s",
            ) from exc

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise SidecarError(
                f"sidecar exited {proc.returncode}: {err or '<no stderr>'}",
            )
        if stderr:
            logger.debug("sidecar stderr: %s", stderr.decode("utf-8", errors="replace"))
        if not stdout.startswith(b"%PDF"):
            raise SidecarError("sidecar output is not a PDF (missing %PDF magic bytes)")
        return stdout
