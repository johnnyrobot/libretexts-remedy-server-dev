"""In-memory ``DatabaseManager`` for the HTML-conversion pipeline.

The engine's ``extractor`` / ``converter`` / ``validator`` modules were
originally built to run inside a long-lived corpus pipeline with SQLite
state. In the HTTP API, each request is transient — the API layer in
``backend/app/jobs.py`` handles its own queue persistence.

This module keeps a minimal ``DatabaseManager`` interface so those
engine modules continue to work as pure functions, backed by an
in-memory dict keyed by ``DocumentJob.id``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from project_remedy.models import DocumentJob


class DatabaseManager:
    """Minimal in-memory job state. Thread-safe via asyncio lock."""

    def __init__(self) -> None:
        self._jobs: dict[str, DocumentJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, job: DocumentJob) -> DocumentJob:
        async with self._lock:
            self._jobs[job.id] = job
        return job

    async def update_job(self, job: DocumentJob) -> DocumentJob:
        async with self._lock:
            self._jobs[job.id] = job
        return job

    async def get_job(self, job_id: str) -> DocumentJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self) -> list[DocumentJob]:
        async with self._lock:
            return list(self._jobs.values())

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            return self._jobs.pop(job_id, None) is not None

    # Pipeline modules may call record_* helpers. Stub them all as no-ops.
    async def record_event(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    async def record_validation(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    async def log_validation(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None
