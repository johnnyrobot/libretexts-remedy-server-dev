"""SQLite-backed experiment tracking for Meta-Harness auto-prompt evolution.

Records (document_type, fix_sequence, outcome) tuples and harness variant
metadata. Provides queries for the proposer and scorer to understand what
has been tried and what works.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from project_remedy.quality_judges.shared.dimensions import (
    ALL_QUALITY_DIMENSIONS,
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)

logger = logging.getLogger(__name__)
QUALITY_DIMENSION_SET = set(ALL_QUALITY_DIMENSIONS)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExperimentRecord:
    """A single experiment run: one harness variant applied to one document."""

    experiment_id: str = ""
    harness_id: str = ""
    document_hash: str = ""
    document_format: str = "pdf"
    document_type: str = ""           # e.g. "table_heavy", "mixed_structure"
    violation_types: list[str] = field(default_factory=list)
    fix_sequence: list[dict] = field(default_factory=list)  # operations applied
    violations_before: int = 0
    violations_after: int = 0
    passed: bool = False
    elapsed_seconds: float = 0.0
    confidence: float = 0.0
    quality_dimensions: dict[str, float] = field(default_factory=dict)
    behavioral_results: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    created_at: str = ""


@dataclass
class HarnessVariant:
    """Metadata for a harness variant (prompt configuration)."""

    harness_id: str = ""
    parent_id: str | None = None      # which harness it was derived from
    description: str = ""
    status: str = "active"            # active, retired, promoted
    conformance_rate: float = 0.0
    manual_review_rate: float = 0.0
    destructive_edit_count: int = 0
    avg_seconds: float = 0.0
    total_docs: int = 0
    passed_docs: int = 0
    created_at: str = ""
    retired_at: str | None = None
    promoted_at: str | None = None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS harness_variants (
    harness_id              TEXT PRIMARY KEY,
    parent_id               TEXT,
    description             TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'active',
    conformance_rate        REAL NOT NULL DEFAULT 0.0,
    manual_review_rate      REAL NOT NULL DEFAULT 0.0,
    destructive_edit_count  INTEGER NOT NULL DEFAULT 0,
    avg_seconds             REAL NOT NULL DEFAULT 0.0,
    total_docs              INTEGER NOT NULL DEFAULT 0,
    passed_docs             INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    retired_at              TEXT,
    promoted_at             TEXT,
    harness_config_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experiment_records (
    experiment_id       TEXT PRIMARY KEY,
    harness_id          TEXT NOT NULL,
    document_hash       TEXT NOT NULL,
    document_format     TEXT NOT NULL DEFAULT 'pdf',
    document_type       TEXT NOT NULL DEFAULT '',
    violation_types_json TEXT NOT NULL DEFAULT '[]',
    fix_sequence_json   TEXT NOT NULL DEFAULT '[]',
    violations_before   INTEGER NOT NULL DEFAULT 0,
    violations_after    INTEGER NOT NULL DEFAULT 0,
    passed              INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds     REAL NOT NULL DEFAULT 0.0,
    confidence          REAL NOT NULL DEFAULT 0.0,
    quality_dimensions_json TEXT NOT NULL DEFAULT '{}',
    behavioral_results_json TEXT NOT NULL DEFAULT '{}',
    error               TEXT,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (harness_id) REFERENCES harness_variants(harness_id)
);

CREATE INDEX IF NOT EXISTS idx_exp_harness ON experiment_records(harness_id);
CREATE INDEX IF NOT EXISTS idx_exp_document ON experiment_records(document_hash);
CREATE INDEX IF NOT EXISTS idx_exp_passed ON experiment_records(passed);
CREATE INDEX IF NOT EXISTS idx_exp_doc_type ON experiment_records(document_type);
CREATE INDEX IF NOT EXISTS idx_variant_status ON harness_variants(status);

CREATE TABLE IF NOT EXISTS pareto_frontier (
    harness_id          TEXT PRIMARY KEY,
    conformance_rate    REAL NOT NULL DEFAULT 0.0,
    manual_review_rate  REAL NOT NULL DEFAULT 0.0,
    destructive_edit_count INTEGER NOT NULL DEFAULT 0,
    avg_seconds         REAL NOT NULL DEFAULT 0.0,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (harness_id) REFERENCES harness_variants(harness_id)
);

CREATE TABLE IF NOT EXISTS evolution_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration   INTEGER NOT NULL,
    action      TEXT NOT NULL,
    harness_id  TEXT NOT NULL,
    details     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_calibration (
    judge_id           TEXT NOT NULL,
    judge_version      TEXT NOT NULL,
    format             TEXT NOT NULL,
    dimension          TEXT NOT NULL,
    cohens_kappa       REAL NOT NULL,
    sample_size        INTEGER NOT NULL,
    measured_at        TEXT NOT NULL,
    PRIMARY KEY (judge_id, judge_version, format, dimension, measured_at)
);
"""


# ---------------------------------------------------------------------------
# ExperimentStore
# ---------------------------------------------------------------------------


class ExperimentStore:
    """SQLite-backed store for experiment tracking.

    For file-backed databases, uses connection-per-call for thread safety.
    For in-memory databases, reuses a single connection (since each new
    connection to :memory: creates a separate database).
    """

    def __init__(self, db_path: Path | str = ":memory:"):
        self._db_path = str(db_path)
        self._is_memory = self._db_path == ":memory:"
        # For in-memory DBs, keep a persistent connection
        if self._is_memory:
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys=ON")
        else:
            self._persistent_conn = None
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, yield it, and commit/rollback on exit.

        For in-memory databases, reuses a single persistent connection.
        For file-backed databases, opens and closes per call.
        """
        if self._persistent_conn is not None:
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            except Exception:
                self._persistent_conn.rollback()
                raise
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Apply additive migrations for databases created by older versions."""
        # Each entry: (table, column, column_definition). Additive only — never
        # drop or alter existing columns; backfill via DEFAULT clauses instead.
        additive_columns = [
            ("experiment_records", "quality_dimensions_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("experiment_records", "behavioral_results_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("experiment_records", "document_format", "TEXT NOT NULL DEFAULT 'pdf'"),
        ]
        for table, column, definition in additive_columns:
            self._ensure_column(conn, table, column, definition)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_doc_format "
            "ON experiment_records(document_format)"
        )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # -- Harness variants ---------------------------------------------------

    def register_variant(
        self,
        harness_id: str,
        description: str = "",
        parent_id: str | None = None,
        harness_config: dict | None = None,
    ) -> HarnessVariant:
        """Register a new harness variant."""
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(harness_config or {})

        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO harness_variants
                   (harness_id, parent_id, description, status, created_at, harness_config_json)
                   VALUES (?, ?, ?, 'active', ?, ?)""",
                (harness_id, parent_id, description, now, config_json),
            )

        return HarnessVariant(
            harness_id=harness_id,
            parent_id=parent_id,
            description=description,
            status="active",
            created_at=now,
        )

    def get_variant(self, harness_id: str) -> HarnessVariant | None:
        """Get a harness variant by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM harness_variants WHERE harness_id = ?",
                (harness_id,),
            ).fetchone()

        if row is None:
            return None

        return HarnessVariant(
            harness_id=row["harness_id"],
            parent_id=row["parent_id"],
            description=row["description"],
            status=row["status"],
            conformance_rate=row["conformance_rate"],
            manual_review_rate=row["manual_review_rate"],
            destructive_edit_count=row["destructive_edit_count"],
            avg_seconds=row["avg_seconds"],
            total_docs=row["total_docs"],
            passed_docs=row["passed_docs"],
            created_at=row["created_at"],
            retired_at=row["retired_at"],
            promoted_at=row["promoted_at"],
        )

    def list_variants(self, status: str | None = None) -> list[HarnessVariant]:
        """List all variants, optionally filtered by status."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM harness_variants WHERE status = ? ORDER BY created_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM harness_variants ORDER BY created_at",
                ).fetchall()

        return [
            HarnessVariant(
                harness_id=r["harness_id"],
                parent_id=r["parent_id"],
                description=r["description"],
                status=r["status"],
                conformance_rate=r["conformance_rate"],
                manual_review_rate=r["manual_review_rate"],
                destructive_edit_count=r["destructive_edit_count"],
                avg_seconds=r["avg_seconds"],
                total_docs=r["total_docs"],
                passed_docs=r["passed_docs"],
                created_at=r["created_at"],
                retired_at=r["retired_at"],
                promoted_at=r["promoted_at"],
            )
            for r in rows
        ]

    def update_variant_metrics(
        self,
        harness_id: str,
        conformance_rate: float,
        manual_review_rate: float,
        destructive_edit_count: int,
        avg_seconds: float,
        total_docs: int,
        passed_docs: int,
    ) -> None:
        """Update computed metrics on a variant after scoring."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE harness_variants
                   SET conformance_rate = ?,
                       manual_review_rate = ?,
                       destructive_edit_count = ?,
                       avg_seconds = ?,
                       total_docs = ?,
                       passed_docs = ?
                   WHERE harness_id = ?""",
                (
                    conformance_rate,
                    manual_review_rate,
                    destructive_edit_count,
                    avg_seconds,
                    total_docs,
                    passed_docs,
                    harness_id,
                ),
            )

    def set_variant_status(
        self, harness_id: str, status: str
    ) -> None:
        """Change a variant's status (active, retired, promoted)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if status == "retired":
                conn.execute(
                    "UPDATE harness_variants SET status = ?, retired_at = ? WHERE harness_id = ?",
                    (status, now, harness_id),
                )
            elif status == "promoted":
                conn.execute(
                    "UPDATE harness_variants SET status = ?, promoted_at = ? WHERE harness_id = ?",
                    (status, now, harness_id),
                )
            else:
                conn.execute(
                    "UPDATE harness_variants SET status = ? WHERE harness_id = ?",
                    (status, harness_id),
                )

    # -- Experiment records --------------------------------------------------

    def record_experiment(self, record: ExperimentRecord) -> None:
        """Insert an experiment record."""
        _validate_experiment_quality_payload(record)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO experiment_records
                   (experiment_id, harness_id, document_hash, document_format, document_type,
                    violation_types_json, fix_sequence_json,
                    violations_before, violations_after, passed,
                    elapsed_seconds, confidence, quality_dimensions_json,
                    behavioral_results_json, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.experiment_id,
                    record.harness_id,
                    record.document_hash,
                    record.document_format,
                    record.document_type,
                    json.dumps(record.violation_types),
                    json.dumps(record.fix_sequence),
                    record.violations_before,
                    record.violations_after,
                    1 if record.passed else 0,
                    record.elapsed_seconds,
                    record.confidence,
                    json.dumps(record.quality_dimensions),
                    json.dumps(record.behavioral_results),
                    record.error,
                    record.created_at or datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_experiments_for_harness(self, harness_id: str) -> list[ExperimentRecord]:
        """Get all experiment records for a specific harness variant."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM experiment_records WHERE harness_id = ? ORDER BY created_at",
                (harness_id,),
            ).fetchall()
        return [self._row_to_experiment(r) for r in rows]

    def get_experiments_for_document(self, document_hash: str) -> list[ExperimentRecord]:
        """Get all experiment records for a specific document across harnesses."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM experiment_records WHERE document_hash = ? ORDER BY created_at",
                (document_hash,),
            ).fetchall()
        return [self._row_to_experiment(r) for r in rows]

    def get_failure_patterns(self, harness_id: str) -> dict[str, Any]:
        """Analyze failure patterns for a harness variant.

        Returns dict with:
        - failing_doc_types: {doc_type: count}
        - failing_violation_types: {violation_type: count}
        - common_errors: {error: count}
        - destructive_docs: list of document hashes where violations increased
        """
        experiments = self.get_experiments_for_harness(harness_id)
        failing = [e for e in experiments if not e.passed]

        doc_types: dict[str, int] = {}
        violation_types: dict[str, int] = {}
        errors: dict[str, int] = {}
        destructive: list[str] = []

        for exp in failing:
            doc_types[exp.document_type] = doc_types.get(exp.document_type, 0) + 1
            for vt in exp.violation_types:
                violation_types[vt] = violation_types.get(vt, 0) + 1
            if exp.error:
                errors[exp.error] = errors.get(exp.error, 0) + 1

        for exp in experiments:
            if exp.violations_after > exp.violations_before:
                destructive.append(exp.document_hash)

        weak_overall = _weak_dimensions_overall(experiments)
        weak_by_doc_type = _weak_dimensions_by_doc_type(experiments)
        weak_by_format = _weak_dimensions_by_format(experiments)
        weak_by_format_doc_type = _weak_dimensions_by_format_and_doc_type(experiments)
        compliance_quality_fails = [
            {
                "doc_hash": exp.document_hash,
                "weak_dims": [
                    dimension
                    for dimension, score in exp.quality_dimensions.items()
                    if score < 0.8
                ],
            }
            for exp in experiments
            if exp.passed and any(score < 0.8 for score in exp.quality_dimensions.values())
        ]
        behavioral_failures: dict[str, int] = {}
        behavioral_failures_by_format: dict[str, dict[str, int]] = {}
        for exp in experiments:
            for test_name, passed in exp.behavioral_results.items():
                if not passed:
                    dimension = dimension_from_behavioral_test(test_name)
                    behavioral_failures[dimension] = behavioral_failures.get(dimension, 0) + 1
                    format_failures = behavioral_failures_by_format.setdefault(
                        exp.document_format,
                        {},
                    )
                    format_failures[dimension] = format_failures.get(dimension, 0) + 1

        return {
            "failing_doc_types": doc_types,
            "failing_violation_types": violation_types,
            "common_errors": errors,
            "destructive_docs": destructive,
            "weak_dimensions_overall": weak_overall,
            "weak_dimensions_by_doc_type": weak_by_doc_type,
            "weak_dimensions_by_format": weak_by_format,
            "weak_dimensions_by_format_and_doc_type": weak_by_format_doc_type,
            "compliance_passes_quality_fails": compliance_quality_fails,
            "behavioral_proxy_failures_by_dim": behavioral_failures,
            "behavioral_proxy_failures_by_format": behavioral_failures_by_format,
        }

    def compute_success_rate(self, harness_id: str) -> float:
        """Compute the conformance rate for a harness variant."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed_count
                   FROM experiment_records WHERE harness_id = ?""",
                (harness_id,),
            ).fetchone()

        if row is None or row["total"] == 0:
            return 0.0
        return row["passed_count"] / row["total"]

    # -- Pareto frontier ----------------------------------------------------

    def update_pareto_frontier(self) -> list[dict]:
        """Recompute and persist the Pareto frontier from all active variants."""
        variants = self.list_variants(status="active")
        # Also include promoted variants
        promoted = self.list_variants(status="promoted")
        all_candidates = variants + promoted

        if not all_candidates:
            return []

        # Filter to variants with at least one experiment
        scored = [v for v in all_candidates if v.total_docs > 0]
        if not scored:
            return []

        frontier = []
        for candidate in scored:
            dominated = False
            for other in scored:
                if other.harness_id == candidate.harness_id:
                    continue
                if _dominates(other, candidate):
                    dominated = True
                    break
            if not dominated:
                frontier.append(candidate)

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM pareto_frontier")
            for v in frontier:
                conn.execute(
                    """INSERT INTO pareto_frontier
                       (harness_id, conformance_rate, manual_review_rate,
                        destructive_edit_count, avg_seconds, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        v.harness_id,
                        v.conformance_rate,
                        v.manual_review_rate,
                        v.destructive_edit_count,
                        v.avg_seconds,
                        now,
                    ),
                )

        return [
            {
                "harness_id": v.harness_id,
                "conformance_rate": v.conformance_rate,
                "manual_review_rate": v.manual_review_rate,
                "destructive_edit_count": v.destructive_edit_count,
                "avg_seconds": v.avg_seconds,
            }
            for v in frontier
        ]

    def get_pareto_frontier(self) -> list[dict]:
        """Get the current Pareto frontier."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pareto_frontier ORDER BY conformance_rate DESC",
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Evolution log ------------------------------------------------------

    def log_evolution(
        self, iteration: int, action: str, harness_id: str, details: str = ""
    ) -> None:
        """Log an evolution action (propose, promote, retire, etc.)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO evolution_log (iteration, action, harness_id, details, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (iteration, action, harness_id, details, now),
            )

    def get_evolution_log(self, limit: int = 50) -> list[dict]:
        """Get recent evolution log entries."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_log ORDER BY log_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Judge calibration --------------------------------------------------

    def record_judge_calibration(
        self,
        *,
        judge_id: str,
        judge_version: str,
        format: str,
        dimension: str,
        cohens_kappa: float,
        sample_size: int,
        measured_at: str | None = None,
    ) -> None:
        """Persist one judge-human agreement measurement."""
        for field_name, value in (
            ("judge_id", judge_id),
            ("judge_version", judge_version),
            ("format", format),
            ("dimension", dimension),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if format not in DIMENSIONS_BY_FORMAT:
            raise ValueError(f"unsupported calibration format: {format}")
        if dimension not in DIMENSIONS_BY_FORMAT[format]:
            raise ValueError(
                f"calibration dimension {dimension!r} is not applicable to {format}"
            )
        if isinstance(cohens_kappa, bool):
            raise ValueError("cohens_kappa must be numeric")
        kappa = float(cohens_kappa)
        if not math.isfinite(kappa):
            raise ValueError("cohens_kappa must be finite")
        if kappa < 0 or kappa > 1:
            raise ValueError("cohens_kappa must be between 0 and 1")
        if isinstance(sample_size, bool):
            raise ValueError("sample_size must be a positive integer")
        if not isinstance(sample_size, int):
            raise ValueError("sample_size must be a positive integer")
        samples = sample_size
        if samples <= 0:
            raise ValueError("sample_size must be a positive integer")
        measured = measured_at or datetime.now(timezone.utc).isoformat()
        try:
            parsed_measured = datetime.fromisoformat(measured.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("measured_at must be an ISO date-time string") from exc
        if parsed_measured.tzinfo is None:
            raise ValueError("measured_at must include a timezone")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO judge_calibration
                   (judge_id, judge_version, format, dimension,
                    cohens_kappa, sample_size, measured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    judge_id,
                    judge_version,
                    format,
                    dimension,
                    kappa,
                    samples,
                    measured,
                ),
            )

    def list_judge_calibration(
        self,
        *,
        format: str | None = None,
        dimension: str | None = None,
    ) -> list[dict]:
        """List judge-human agreement measurements."""
        query = "SELECT * FROM judge_calibration"
        params: list[str] = []
        clauses: list[str] = []
        if format is not None:
            clauses.append("format = ?")
            params.append(format)
        if dimension is not None:
            clauses.append("dimension = ?")
            params.append(dimension)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return sorted(
            [dict(row) for row in rows],
            key=_calibration_sort_key,
            reverse=True,
        )

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_experiment(row: sqlite3.Row) -> ExperimentRecord:
        experiment_id = row["experiment_id"]
        record = ExperimentRecord(
            experiment_id=row["experiment_id"],
            harness_id=row["harness_id"],
            document_hash=row["document_hash"],
            document_format=row["document_format"],
            document_type=row["document_type"],
            violation_types=json.loads(row["violation_types_json"]),
            fix_sequence=json.loads(row["fix_sequence_json"]),
            violations_before=row["violations_before"],
            violations_after=row["violations_after"],
            passed=bool(row["passed"]),
            elapsed_seconds=row["elapsed_seconds"],
            confidence=row["confidence"],
            quality_dimensions=_load_experiment_json_field(
                row,
                "quality_dimensions_json",
                experiment_id=experiment_id,
            ),
            behavioral_results=_load_experiment_json_field(
                row,
                "behavioral_results_json",
                experiment_id=experiment_id,
            ),
            error=row["error"],
            created_at=row["created_at"],
        )
        try:
            _validate_experiment_quality_payload(record)
        except ValueError as exc:
            raise ValueError(
                f"experiment {experiment_id} has invalid persisted quality evidence: {exc}"
            ) from exc
        return record


# ---------------------------------------------------------------------------
# Pareto helpers
# ---------------------------------------------------------------------------


def _dominates(a: HarnessVariant, b: HarnessVariant) -> bool:
    """Return True if variant a Pareto-dominates variant b.

    Maximize: conformance_rate
    Minimize: manual_review_rate, destructive_edit_count, avg_seconds
    """
    checks = [
        a.conformance_rate >= b.conformance_rate,
        a.manual_review_rate <= b.manual_review_rate,
        a.destructive_edit_count <= b.destructive_edit_count,
        a.avg_seconds <= b.avg_seconds,
    ]
    strict = [
        a.conformance_rate > b.conformance_rate,
        a.manual_review_rate < b.manual_review_rate,
        a.destructive_edit_count < b.destructive_edit_count,
        a.avg_seconds < b.avg_seconds,
    ]
    return all(checks) and any(strict)


def _validate_experiment_quality_payload(record: ExperimentRecord) -> None:
    """Reject malformed per-dimension quality evidence before persistence."""
    document_format = _validate_experiment_format(record.document_format)
    applicable_dimensions = set(DIMENSIONS_BY_FORMAT[document_format])
    if not isinstance(record.quality_dimensions, dict):
        raise ValueError("quality_dimensions must be an object")
    for dimension, score in record.quality_dimensions.items():
        if not isinstance(dimension, str) or not dimension.strip():
            raise ValueError("quality_dimensions keys must be non-empty strings")
        if dimension != dimension.strip():
            raise ValueError("quality_dimensions keys must be canonical dimension names")
        if dimension not in QUALITY_DIMENSION_SET:
            raise ValueError(f"unsupported quality dimension: {dimension}")
        if dimension not in applicable_dimensions:
            raise ValueError(
                f"quality dimension {dimension!r} is not applicable to {document_format}"
            )
        if isinstance(score, bool):
            raise ValueError(
                f"quality_dimensions.{dimension} must be numeric"
            )
        try:
            numeric = float(score)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"quality_dimensions.{dimension} must be numeric"
            ) from exc
        if not math.isfinite(numeric):
            raise ValueError(f"quality_dimensions.{dimension} must be finite")
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError(
                f"quality_dimensions.{dimension} must be between 0.0 and 1.0"
            )

    if not isinstance(record.behavioral_results, dict):
        raise ValueError("behavioral_results must be an object")
    for test_name, passed in record.behavioral_results.items():
        if not isinstance(test_name, str) or not test_name.strip():
            raise ValueError("behavioral_results keys must be non-empty strings")
        if test_name != test_name.strip():
            raise ValueError("behavioral_results keys must be canonical test names")
        dimension = dimension_from_behavioral_test(test_name)
        if dimension not in QUALITY_DIMENSION_SET:
            raise ValueError(
                f"unsupported behavioral result test: {test_name}"
            )
        if dimension not in applicable_dimensions:
            raise ValueError(
                f"behavioral result {test_name!r} maps to dimension "
                f"{dimension!r}, which is not applicable to {document_format}"
            )
        if not isinstance(passed, bool):
            raise ValueError(
                f"behavioral_results.{test_name} must be a boolean"
            )


def _validate_experiment_format(document_format: str) -> str:
    if not isinstance(document_format, str) or not document_format.strip():
        raise ValueError("document_format must be a non-empty string")
    if document_format != document_format.strip().lower():
        raise ValueError("document_format must be canonical")
    if document_format not in DIMENSIONS_BY_FORMAT:
        raise ValueError(f"unsupported document_format: {document_format}")
    return document_format


def _load_experiment_json_field(
    row: sqlite3.Row,
    field_name: str,
    *,
    experiment_id: str,
) -> Any:
    try:
        return json.loads(row[field_name])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"experiment {experiment_id} {field_name} must contain valid JSON"
        ) from exc


def _calibration_sort_key(row: dict[str, Any]) -> tuple[int, datetime, str]:
    raw_measured_at = row.get("measured_at")
    if isinstance(raw_measured_at, str):
        try:
            parsed = datetime.fromisoformat(raw_measured_at.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                return (0, parsed.astimezone(timezone.utc), raw_measured_at)
    return (
        1,
        datetime.max.replace(tzinfo=timezone.utc),
        str(raw_measured_at),
    )


def _mean_below_threshold(
    dimension_scores: dict[str, list[float]],
    *,
    threshold: float,
) -> dict[str, float]:
    """Return the mean per dimension where the mean is strictly below threshold."""
    return {
        dimension: round(sum(scores) / len(scores), 4)
        for dimension, scores in dimension_scores.items()
        if scores and (sum(scores) / len(scores)) < threshold
    }


def _weak_dimensions_overall(
    experiments: list[ExperimentRecord],
    *,
    threshold: float = 0.8,
) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for exp in experiments:
        for dimension, score in exp.quality_dimensions.items():
            values.setdefault(dimension, []).append(score)
    return _mean_below_threshold(values, threshold=threshold)


def _weak_dimensions_grouped_by(
    experiments: list[ExperimentRecord],
    *,
    threshold: float,
    group_key,
    require_doc_type: bool,
) -> dict[str, dict[str, float]]:
    """Group experiments by ``group_key(exp)`` and return weak dims per group."""
    grouped: dict[str, dict[str, list[float]]] = {}
    for exp in experiments:
        if require_doc_type and not exp.document_type:
            continue
        bucket = grouped.setdefault(group_key(exp), {})
        for dimension, score in exp.quality_dimensions.items():
            bucket.setdefault(dimension, []).append(score)

    result: dict[str, dict[str, float]] = {}
    for key, dimensions in grouped.items():
        weak = _mean_below_threshold(dimensions, threshold=threshold)
        if weak:
            result[key] = weak
    return result


def _weak_dimensions_by_doc_type(
    experiments: list[ExperimentRecord],
    *,
    threshold: float = 0.8,
) -> dict[str, dict[str, float]]:
    return _weak_dimensions_grouped_by(
        experiments,
        threshold=threshold,
        group_key=lambda exp: exp.document_type,
        require_doc_type=True,
    )


def _weak_dimensions_by_format(
    experiments: list[ExperimentRecord],
    *,
    threshold: float = 0.8,
) -> dict[str, dict[str, float]]:
    return _weak_dimensions_grouped_by(
        experiments,
        threshold=threshold,
        group_key=lambda exp: exp.document_format,
        require_doc_type=False,
    )


def _weak_dimensions_by_format_and_doc_type(
    experiments: list[ExperimentRecord],
    *,
    threshold: float = 0.8,
) -> dict[str, dict[str, dict[str, float]]]:
    result: dict[str, dict[str, dict[str, float]]] = {}
    for fmt in {exp.document_format for exp in experiments}:
        format_records = [exp for exp in experiments if exp.document_format == fmt]
        weak_by_doc_type = _weak_dimensions_by_doc_type(
            format_records,
            threshold=threshold,
        )
        if weak_by_doc_type:
            result[fmt] = weak_by_doc_type
    return result
