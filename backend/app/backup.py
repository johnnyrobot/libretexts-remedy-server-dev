"""Online SQLite backup of the JobStore.

Uses ``sqlite3.Connection.backup()`` — the supported online-backup API —
to copy the JobStore DB while the app keeps running. Safe with WAL mode
(enabled in ``JobStore._connect``). All blocking sqlite work is dispatched
to a thread executor so the event loop is never paused.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger("project_remedy.backend.backup")


# Filename prefix/suffix so pruning only touches our own artefacts.
_FILE_PREFIX = "jobs_"
_FILE_SUFFIX = ".db"


def _do_backup_sync(db_path: Path, dest_path: Path) -> int:
    """Blocking implementation — runs in an executor thread.

    Returns the byte size of the created backup file.
    """
    # ``sqlite3.connect`` will happily create a file for a missing DB,
    # which would silently produce an empty backup. Surface that up front
    # so callers see a real error.
    if not db_path.exists():
        raise sqlite3.OperationalError(
            f"source database does not exist: {db_path}"
        )

    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return dest_path.stat().st_size


def _prune_old_backups(backup_dir: Path, keep_n: int) -> list[Path]:
    """Keep only the newest ``keep_n`` files matching ``jobs_*.db``.

    Returns the list of deleted paths (for logging/tests).
    """
    files = sorted(
        p for p in backup_dir.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}") if p.is_file()
    )
    if len(files) <= keep_n:
        return []
    to_delete = files[: len(files) - keep_n]
    deleted: list[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
        except OSError:  # pragma: no cover - permission / race
            logger.exception("failed to prune old backup %s", path)
    return deleted


async def backup_jobstore(
    db_path: Path,
    backup_dir: Path,
    keep_n: int,
) -> Path:
    """Write a timestamped online backup of ``db_path`` and prune old ones.

    Filename: ``jobs_YYYYMMDD_HHMMSSZ.db`` (UTC; lexicographic sort ==
    chronological sort). Returns the path of the created backup file.

    Blocking sqlite work is wrapped in ``loop.run_in_executor`` so the
    event loop keeps running. Uses ``sqlite3.Connection.backup()``, which
    is safe with WAL mode and a concurrent worker writing to the DB.
    """
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    dest_path = backup_dir / f"{_FILE_PREFIX}{stamp}{_FILE_SUFFIX}"

    loop = asyncio.get_running_loop()
    try:
        size = await loop.run_in_executor(None, _do_backup_sync, db_path, dest_path)
    except Exception:
        # Clean up any partial artefact so pruning / listings stay sane.
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
        logger.exception("jobstore backup failed: %s", db_path)
        raise

    # Pruning is cheap (directory listing + unlink) but still filesystem IO;
    # keep it off the event loop for consistency.
    await loop.run_in_executor(None, _prune_old_backups, backup_dir, keep_n)

    logger.info(
        "jobstore backup written: path=%s bytes=%d keep_n=%d",
        dest_path,
        size,
        keep_n,
    )
    return dest_path
