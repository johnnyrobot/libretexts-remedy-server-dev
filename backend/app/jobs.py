"""In-process job store + async worker.

Jobs are persisted to a tiny SQLite table so state survives restart.
The worker task consumes them from an asyncio.Queue and calls the
engine wrapper. Files for each job live under ``settings.job_dir/{id}/``.

Each job has a ``kind`` discriminator so a single ``/v1/jobs/{id}``
endpoint works for remediation, conversion, office remediation, etc.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable

from backend.app.execution import OwnedExecution, Reservation, ExecutionDeadline, ExecutionStopped


log = logging.getLogger("project_remedy.backend.jobs")


JobRunner = Callable[["Job"], Awaitable[None]]

# Terminal statuses eligible for retention-based pruning.
TERMINAL_STATUSES = frozenset({"done", "failed"})


# Known job kinds. The worker dispatches on this value.
JOB_KIND_REMEDIATE_PDF = "remediate_pdf"
JOB_KIND_REMEDIATE_OFFICE = "remediate_office"
JOB_KIND_CONVERT_PDF_TO_HTML = "convert_pdf_to_html"
JOB_KIND_CONVERT_OFFICE_TO_HTML = "convert_office_to_html"
JOB_KIND_CONVERT_HTML_TO_PDF = "convert_html_to_pdf"
JOB_KIND_VISION_PLAN_RUN = "vision_plan_run"


@dataclass
class Job:
    id: str
    kind: str                 # see JOB_KIND_* constants
    status: str               # queued | running | done | failed
    stage: str                # free-text current step
    progress: float           # 0.0 – 1.0
    input_path: str
    output_path: str
    report_path: str
    error: str
    created_at: str
    updated_at: str
    result_media_type: str = "application/pdf"
    metadata_json: str = "{}"
    deadline_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    """SQLite-backed job registry. Safe for single-process concurrent access."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'remediate_pdf',
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT '',
                    progress REAL NOT NULL DEFAULT 0.0,
                    input_path TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    report_path TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    result_media_type TEXT NOT NULL DEFAULT 'application/pdf',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    deadline_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Forward-compat: add columns if upgrading from an older DB.
            for _col, ddl in (
                ("deadline_at", "ALTER TABLE jobs ADD COLUMN deadline_at TEXT NOT NULL DEFAULT ''"),
                ("kind", "ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'remediate_pdf'"),
                ("result_media_type", "ALTER TABLE jobs ADD COLUMN result_media_type TEXT NOT NULL DEFAULT 'application/pdf'"),
                ("metadata_json", "ALTER TABLE jobs ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"),
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.execute("""CREATE TABLE IF NOT EXISTS submission_intents (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                phase TEXT NOT NULL,
                staging_path TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                input_bytes INTEGER NOT NULL,
                intent_json TEXT NOT NULL
            )""")

    async def create(
        self,
        input_path: Path,
        *,
        kind: str = JOB_KIND_REMEDIATE_PDF,
        result_media_type: str = "application/pdf",
        deadline_at: str = "",
    ) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        job = Job(
            id=uuid.uuid4().hex,
            kind=kind,
            status="queued",
            stage="queued",
            progress=0.0,
            input_path=str(input_path),
            output_path="",
            report_path="",
            error="",
            created_at=now,
            updated_at=now,
            result_media_type=result_media_type,
            deadline_at=deadline_at,
        )
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO jobs(id,kind,status,stage,progress,input_path,output_path,report_path,error,result_media_type,metadata_json,deadline_at,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (job.id, job.kind, job.status, job.stage, job.progress,
                     job.input_path, job.output_path, job.report_path,
                     job.error, job.result_media_type, job.metadata_json, job.deadline_at,
                     job.created_at, job.updated_at),
                )
        return job

    async def prepare_upload(self, staging: Path, job_dir: Path, suffix: str, *, kind: str,
                             result_media_type: str, metadata_json: str, deadline_at: str) -> Job:
        """Durably own complete intent before filesystem publication/eligibility."""
        root = job_dir.resolve()
        if (staging.is_symlink() or staging.parent.resolve() != root
                or not staging.name.startswith("_staging-") or not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix)):
            raise ValueError("Invalid submission path ownership.")
        if not isinstance(json.loads(metadata_json), dict):
            raise ValueError("Submission options must be an object.")
        digest, size = _submission_bytes(staging, sync=True)
        _sync_submission_directory(root)
        # Admission routes may have just created the configured directory tree.
        # Persist its names as well as the input entry before committing intent.
        for ancestor in root.parents:
            _sync_submission_directory(ancestor)
        now = datetime.now(timezone.utc).isoformat()
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, kind=kind, status="queued", stage="finalizing", progress=0.,
                  input_path=str(root / job_id / f"input{suffix}"), output_path="", report_path="",
                  error="", created_at=now, updated_at=now, result_media_type=result_media_type,
                  metadata_json=metadata_json, deadline_at=deadline_at)
        intent = json.dumps({"version": 1, "job": job.to_dict()}, sort_keys=True)
        async with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                values = job.to_dict()
                conn.execute(f"INSERT INTO jobs ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
                conn.execute("INSERT INTO submission_intents VALUES (?, 'prepared', ?, ?, ?, ?)",
                             (job.id, str(root / staging.name), digest, size, intent))
        return job

    async def upload_owned(self, staging: Path) -> bool:
        async with self._lock:
            with self._connect() as conn:
                return conn.execute("SELECT 1 FROM submission_intents WHERE staging_path=?",
                    (str(staging.parent.resolve() / staging.name),)).fetchone() is not None

    async def _submission(self, job_id: str):
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM submission_intents WHERE job_id=?", (job_id,)).fetchone()
                job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return (dict(row), _row_to_job(job)) if row and job else None

    async def quarantine_upload(self, job_id: str) -> None:
        """Retain inputs and durable ownership evidence; never automatically replay."""
        async with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""UPDATE submission_intents SET phase='quarantined' WHERE job_id=?
                    AND phase IN ('prepared','ready')""", (job_id,))
                conn.execute("""UPDATE jobs SET status='failed',stage='submission_quarantined',
                    error='Submission recovery quarantined; input retained for operator review.',updated_at=?
                    WHERE id=? AND status='queued'""", (datetime.now(timezone.utc).isoformat(), job_id))

    async def _advance_upload(self, job_id: str, expected_phase: str) -> Job | None:
        transitions = {"prepared": ("ready", "queued", "queued", 0.),
                       "ready": ("dispatched", "running", "starting", .05)}
        phase, status, stage, progress = transitions[expected_phase]
        async with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                intent = conn.execute("SELECT * FROM submission_intents WHERE job_id=?", (job_id,)).fetchone()
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not intent or not row or row["status"] != "queued" or intent["phase"] != expected_phase:
                    return None
                job = _row_to_job(row)
                _submission_intent(intent, job)
                conn.execute("UPDATE submission_intents SET phase=? WHERE job_id=?", (phase, job_id))
                conn.execute("UPDATE jobs SET status=?,stage=?,progress=?,updated_at=? WHERE id=?",
                             (status, stage, progress, datetime.now(timezone.utc).isoformat(), job_id))
                return _row_to_job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    async def finish_upload(self, job_id: str, job_dir: Path) -> Job | None:
        """Idempotently reconcile a prepared move and commit validated eligibility."""
        record = await self._submission(job_id)
        if record is None:
            await self.quarantine_upload(job_id)  # legacy intent/options are unknown
            return None
        intent, job = record
        if job.status != "queued":
            return None
        if intent["phase"] not in {"prepared", "ready"}:
            await self.quarantine_upload(job_id)
            return None
        try:
            _submission_intent(intent, job)
            root = job_dir.resolve()
            final, staging = Path(job.input_path), Path(intent["staging_path"])
            if (not re.fullmatch(r"[0-9a-f]{32}", job.id) or final.parent != root / job.id
                    or not re.fullmatch(r"input\.[a-z0-9]{1,10}", final.name)
                    or final.parent.is_symlink() or staging.parent != root
                    or not staging.name.startswith("_staging-") or staging.is_symlink() or final.is_symlink()):
                raise ValueError("Invalid submission path ownership.")
            if intent["phase"] == "prepared" and not final.exists():
                _check_submission_bytes(staging, intent)
                final.parent.mkdir(exist_ok=True)
                _sync_submission_directory(root)
                staging.rename(final)
            elif staging.exists():
                raise ValueError("Ambiguous submission input paths.")
            _check_submission_bytes(final, intent, sync=True)
            _sync_submission_directory(final.parent)
            _sync_submission_directory(root)
            return await self._advance_upload(job_id, "prepared") if intent["phase"] == "prepared" else job
        except (OSError, ValueError, KeyError, TypeError):
            await self.quarantine_upload(job_id)
            return None

    async def claim_upload(self, job_id: str, job_dir: Path) -> Job | None:
        """Validate committed bytes/options, then atomically mark dispatch intent."""
        record = await self._submission(job_id)
        if record is None:
            await self.quarantine_upload(job_id)
            return None
        intent, job = record
        if job.status != "queued":
            return None
        if intent["phase"] != "ready":
            await self.quarantine_upload(job_id)
            return None
        if await self.finish_upload(job_id, job_dir) is None:
            return None
        try:
            return await self._advance_upload(job_id, "ready")
        except (ValueError, KeyError, TypeError):
            await self.quarantine_upload(job_id)
            return None

    async def recover_uploads(self, job_dir: Path, capacity: int) -> list[Job]:
        """Bound file reconciliation to capacity; quarantine excess/unknown intent."""
        if capacity <= 0:
            raise ValueError("Recovery capacity must be positive.")
        async with self._lock:
            with self._connect() as conn:
                selected = [row[0] for row in conn.execute(
                    "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT ?", (capacity,))]
                placeholders = ",".join("?" for _ in (selected or [""]))
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(f"""UPDATE submission_intents SET phase='quarantined' WHERE job_id IN (
                    SELECT id FROM jobs WHERE status='queued' AND id NOT IN ({placeholders}))""", selected or [""])
                conn.execute(f"""UPDATE jobs SET status='failed',stage='submission_quarantined',
                    error='Restart queue capacity exceeded; input retained for operator review.',updated_at=?
                    WHERE status='queued' AND id NOT IN ({placeholders})""",
                    [datetime.now(timezone.utc).isoformat(), *(selected or [""])])
        ready = []
        for job_id in selected:
            job = await self.get(job_id)
            try:
                expired = job.deadline_at and datetime.fromisoformat(job.deadline_at) <= datetime.now(timezone.utc)
            except (ValueError, TypeError):
                await self.quarantine_upload(job_id)
                continue
            if expired:
                await self.update(job_id, status="failed", stage="timed_out", error="Engine execution deadline exceeded; input retained.")
                continue
            recovered = await self.finish_upload(job_id, job_dir)
            if recovered is not None:
                ready.append(recovered)
        return ready

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    async def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: float | None = None,
        input_path: str | None = None,
        output_path: str | None = None,
        report_path: str | None = None,
        error: str | None = None,
        result_media_type: str | None = None,
        metadata_json: str | None = None,
    ) -> Job | None:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not row:
                    return None
                updates: dict = {}
                if status is not None:
                    updates["status"] = status
                if stage is not None:
                    updates["stage"] = stage
                if progress is not None:
                    updates["progress"] = progress
                if input_path is not None:
                    updates["input_path"] = input_path
                if output_path is not None:
                    updates["output_path"] = output_path
                if report_path is not None:
                    updates["report_path"] = report_path
                if error is not None:
                    updates["error"] = error
                if result_media_type is not None:
                    updates["result_media_type"] = result_media_type
                if metadata_json is not None:
                    updates["metadata_json"] = metadata_json
                updates["updated_at"] = datetime.now(timezone.utc).isoformat()
                if updates:
                    cols = ", ".join(f"{k}=?" for k in updates)
                    params = list(updates.values()) + [job_id]
                    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", params)
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    async def delete(self, job_id: str) -> bool:
        async with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                return cur.rowcount > 0

    async def list_older_than(self, cutoff: datetime) -> list[Job]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE created_at < ?",
                    (cutoff.isoformat(),),
                ).fetchall()
        return [_row_to_job(r) for r in rows]

    async def list_by_statuses(self, statuses: Iterable[str]) -> list[Job]:
        values = tuple(statuses)
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at,id",
                    values,
                ).fetchall()
        return [_row_to_job(r) for r in rows]

    async def fail_running_jobs(self, error: str) -> int:
        """Mark jobs left running by a prior process as failed."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """UPDATE jobs
                       SET status='failed', stage='interrupted', error=?, updated_at=?
                       WHERE status='running'""",
                    (error, now),
                )
                return cur.rowcount

    async def ping(self) -> None:
        """Raise if SQLite cannot be opened and queried."""
        async with self._lock:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()


def _submission_bytes(path: Path, *, sync: bool = False) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Submission input is missing or unsafe.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = os.fstat(stream.fileno()).st_size
        if size <= 0:
            raise ValueError("Empty submission input.")
        if sync:
            os.fsync(stream.fileno())
    return digest, size


def _check_submission_bytes(path: Path, intent, *, sync: bool = False) -> None:
    if _submission_bytes(path, sync=sync) != (intent["input_sha256"], intent["input_bytes"]):
        raise ValueError("Submission input changed.")


def _sync_submission_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _submission_intent(intent, job: Job) -> None:
    document = json.loads(intent["intent_json"])
    if document["version"] != 1:
        raise ValueError("Unknown submission version.")
    expected = document["job"]
    if any(getattr(job, name) != expected[name] for name in (
            "id", "kind", "input_path", "result_media_type", "metadata_json", "deadline_at", "created_at")):
        raise ValueError("Submission intent changed.")


def _row_to_job(row) -> Job:
    keys = set(row.keys())
    return Job(
        id=row["id"],
        kind=row["kind"] if "kind" in keys else JOB_KIND_REMEDIATE_PDF,
        status=row["status"],
        stage=row["stage"],
        progress=row["progress"],
        input_path=row["input_path"],
        output_path=row["output_path"],
        report_path=row["report_path"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        result_media_type=row["result_media_type"] if "result_media_type" in keys else "application/pdf",
        metadata_json=row["metadata_json"] if "metadata_json" in keys else "{}",
        deadline_at=row["deadline_at"] if "deadline_at" in keys else "",
    )


class JobWorker:
    """Consumes a queue of job IDs and runs them in-process."""

    def __init__(self, store: JobStore, runner: JobRunner, *, concurrency: int = 1,
                 execution: OwnedExecution | None = None, job_dir: Path | None = None) -> None:
        self.store = store
        self.runner = runner
        self.concurrency = max(1, int(concurrency))
        self.execution = execution or OwnedExecution(concurrency=concurrency)
        self.job_dir = job_dir
        self._reservations: dict[str, Reservation] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def start(self) -> None:
        if self.is_running:
            return
        self._tasks = [
            asyncio.create_task(self._loop(i), name=f"job-worker-{i + 1}")
            for i in range(self.concurrency)
        ]

    async def stop(self) -> None:
        tasks = list(self._tasks)
        self._tasks = []
        if not tasks:
            return
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for reservation in self._reservations.values():
            reservation.release()
        self._reservations.clear()

    async def enqueue(self, job_id: str, reservation: Reservation | None = None) -> None:
        if reservation is None:
            job = await self.store.get(job_id)
            now = datetime.now(timezone.utc)
            deadline = (datetime.fromisoformat(job.deadline_at) if job and job.deadline_at
                        else datetime.fromisoformat(job.created_at) + timedelta(seconds=self.execution.total_seconds))
            reservation = self.execution.reserve(remaining=(deadline - now).total_seconds())
        reservation.transferred = True
        self._reservations[job_id] = reservation
        self.queue.put_nowait(job_id)

    def reservation_for(self, job_id: str) -> Reservation:
        return self._reservations[job_id]

    async def begin_dispatch(self, job_id: str) -> None:
        """Called by the runner only after actual shared capacity is acquired."""
        if self.job_dir is not None:
            if await self.store.claim_upload(job_id, self.job_dir) is None:
                raise ExecutionStopped("Submission is not dispatchable; input retained.")
        else:
            await self.store.update(job_id, status="running", stage="starting", progress=.05)

    async def _loop(self, _worker_index: int) -> None:
        while self.execution.accepting:
            job_id = await self.queue.get()
            quarantined = False
            try:
                if not self.execution.accepting:
                    quarantined = True
                    return
                job = await self.store.get(job_id)
                if not self.execution.accepting:
                    quarantined = True
                    return
                if not job:
                    continue
                reservation = self._reservations[job_id]
                if reservation.deadline <= time.monotonic():
                    raise ExecutionDeadline("Engine total deadline exceeded while queued.")
                await self.runner(job)
            except asyncio.CancelledError:
                # runner cancellation finishes owned-process termination first.
                current = await self.store.get(job_id)
                if current is not None and current.status == "running":
                    await self.store.update(job_id, status="failed", stage="interrupted",
                                            error="Engine execution interrupted by shutdown.")
                raise
            except ExecutionDeadline:
                await self.store.update(job_id, status="failed", stage="timed_out",
                                        error="Engine execution deadline exceeded.")
            except Exception as exc:  # noqa: BLE001
                log.error("Job %s failed (%s)", job_id, type(exc).__name__)
                reservation = self._reservations.get(job_id)
                retained = reservation is not None and reservation.retained
                current = await self.store.get(job_id)
                if current is not None and current.stage == "submission_quarantined" and not retained:
                    continue  # preserve the explicit journal failure, not a generic failure
                if current is not None and current.status == "queued" and not self.execution.accepting and not retained:
                    return  # never-dispatched work remains eligible for safe cold recovery
                await self.store.update(job_id, status="running" if retained else "failed",
                                        stage="termination_failed" if retained else "failed",
                                        error="Engine termination failed; service unavailable." if retained else "Engine operation failed.")
                if retained:
                    return  # quarantine pending work; never dispatch it after unknown cleanup
            finally:
                if not quarantined:
                    reservation = self._reservations.pop(job_id, None)
                    if reservation is not None:
                        reservation.release()
                self.queue.task_done()


def serialize_job(job: Job) -> dict:
    """Return a JSON-safe dict; hide internal paths."""
    d = job.to_dict()
    d.pop("input_path", None)
    d.pop("output_path", None)
    d.pop("report_path", None)
    return d


async def prune_expired_jobs(
    store: JobStore,
    job_dir: Path,
    retention_hours: int,
) -> int:
    """Delete jobs older than ``retention_hours`` with status in (done, failed).

    Returns the number of jobs pruned. Best-effort per-job: if removing
    one job's directory fails, log and continue with the next. The outer
    loop is wrapped so a single bad job cannot crash the caller.
    """
    if retention_hours <= 0:
        # Retention disabled; skip.
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    pruned = 0
    try:
        candidates = await store.list_older_than(cutoff)
    except Exception:  # noqa: BLE001
        log.exception("prune_expired_jobs: failed to list candidates")
        return 0

    for job in candidates:
        if job.status not in TERMINAL_STATUSES or job.stage == "submission_quarantined":
            continue
        try:
            await store.delete(job.id)
            shutil.rmtree(job_dir / job.id, ignore_errors=True)
            pruned += 1
        except Exception:  # noqa: BLE001
            log.exception("prune_expired_jobs: failed to prune job %s", job.id)
            continue

    if pruned:
        log.info("prune_expired_jobs: pruned %d expired job(s)", pruned)
    return pruned
