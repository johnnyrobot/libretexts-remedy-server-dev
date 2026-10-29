"""API backend settings.

Reads from environment variables (.env file is honoured via python-dotenv
if present). Engine-level settings live in ``project_remedy.config``;
this module covers only HTTP-layer concerns.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from dotenv import load_dotenv


_PRODUCTION_ENVS = {"prod", "production"}


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw is not None else default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return float(raw) if raw is not None else default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _reviewer_required() -> bool:
    raw = _env("REMEDY_REVIEWER_REQUIRED", "true").strip().lower()
    if raw not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise ValueError("REMEDY_REVIEWER_REQUIRED must be an explicit boolean")
    return raw in {"1", "true", "yes", "on"}


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """HTTP backend settings."""

    # Runtime mode.
    app_env: str = "development"
    docs_enabled: bool = True

    # Auth. If empty, auth is disabled (dev mode).
    api_key: str = ""
    ollama_api_key: str = ""

    # Uploads.
    max_upload_mb: int = 50

    # Storage.
    job_store_path: Path = Path("./jobs.db")
    job_dir: Path = Path("./job_data")
    job_retention_hours: int = 24
    prune_interval_hours: int = 1

    # JobStore backups. Periodic online SQLite backups of ``job_store_path``.
    backup_dir: Path = Path("./job_backups")
    backup_keep_n: int = 24
    backup_interval_hours: int = 1

    # Queue.
    worker_concurrency: int = 1

    # CORS.
    cors_allow_origins: list[str] = field(default_factory=lambda: ["*"])

    # Optional local bridge to the LibreTexts CXone remediation service.
    cxone_integration_enabled: bool = False
    cxone_bridge_base_url: str = "http://127.0.0.1:5175"
    cxone_bridge_timeout_seconds: float = 300.0
    cxone_health_timeout_seconds: float = 5.0
    remedy_reviewer_required: bool = True
    remedy_bridge_service_key_file: Path | None = None

    @cached_property
    def bridge_service_key(self) -> str:
        """Parse once; report fixed diagnostics without file paths or contents."""
        if self.remedy_bridge_service_key_file is None:
            raise ValueError("REMEDY_BRIDGE_SERVICE_KEY_FILE is required")
        try:
            with self.remedy_bridge_service_key_file.open("rb") as stream:
                raw = stream.read(66)
        except OSError:
            raise ValueError("REMEDY_BRIDGE_SERVICE_KEY_FILE is unreadable") from None
        if not re.fullmatch(rb"[0-9a-f]{64}\n?", raw):
            raise ValueError("REMEDY_BRIDGE_SERVICE_KEY_FILE must contain 64 lowercase hex characters with optional LF")
        return raw.rstrip(b"\n").decode("ascii")

    # Quality-layer reviewer/calibration storage.
    quality_experiment_store_path: Path = Path("./quality_experiments.db")
    quality_review_queue_path: Path = Path("./quality_review_queue.jsonl")
    quality_review_submission_path: Path = Path("./quality_review_submissions.jsonl")
    quality_corpus_root_path: Path = Path("./tools/corpus_annotations/v1")
    reviewer_keys: list[str] = field(default_factory=list)
    quality_require_calibration: bool = False
    quality_min_cohens_kappa: float = 0.8
    quality_min_calibration_samples: int = 1
    quality_max_calibration_age_days: int = 0

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in _PRODUCTION_ENVS

    def validation_errors(self) -> list[str]:
        """Return startup-blocking configuration errors."""
        errors: list[str] = []
        if self.max_upload_mb <= 0:
            errors.append("MAX_UPLOAD_MB must be greater than 0")
        if self.worker_concurrency < 1:
            errors.append("WORKER_CONCURRENCY must be at least 1")
        if self.job_retention_hours < 0:
            errors.append("JOB_RETENTION_HOURS must be 0 or greater")
        if self.prune_interval_hours <= 0:
            errors.append("PRUNE_INTERVAL_HOURS must be greater than 0")
        if self.backup_keep_n < 1:
            errors.append("JOB_BACKUP_KEEP_N must be at least 1")
        if self.backup_interval_hours <= 0:
            errors.append("JOB_BACKUP_INTERVAL_HOURS must be greater than 0")
        if self.quality_min_cohens_kappa < 0 or self.quality_min_cohens_kappa > 1:
            errors.append("QUALITY_MIN_COHENS_KAPPA must be between 0 and 1")
        if self.quality_min_calibration_samples < 1:
            errors.append("QUALITY_MIN_CALIBRATION_SAMPLES must be at least 1")
        if self.quality_max_calibration_age_days < 0:
            errors.append("QUALITY_MAX_CALIBRATION_AGE_DAYS must be 0 or greater")
        if self.cxone_bridge_timeout_seconds <= 0:
            errors.append("CXONE_BRIDGE_TIMEOUT_SECONDS must be greater than 0")
        if not 1 <= self.cxone_health_timeout_seconds <= 15:
            errors.append("CXONE_HEALTH_TIMEOUT_SECONDS must be between 1 and 15")
        if self.cxone_integration_enabled:
            if self.remedy_reviewer_required:
                if not self.api_key.strip():
                    errors.append("APP_API_KEY is required for authenticated CXone forwarding")
                try:
                    self.bridge_service_key
                except ValueError as exc:
                    errors.append(str(exc))
            else:
                from urllib.parse import urlsplit
                target = urlsplit(self.cxone_bridge_base_url)
                if self.is_production or target.hostname not in {"127.0.0.1", "::1", "localhost"}:
                    errors.append("Legacy CXone mode is allowed only in development on loopback")
        if self.job_store_path.exists() and self.job_store_path.is_dir():
            errors.append(
                "JOB_STORE_PATH points to a directory; mount the containing "
                "directory and set JOB_STORE_PATH to a file such as /app/state/jobs.db"
            )

        if self.is_production:
            if not self.api_key.strip():
                errors.append("APP_API_KEY must be set when APP_ENV=production")
            if not self.ollama_api_key.strip():
                errors.append("OLLAMA_API_KEY must be set when APP_ENV=production")
            if any(origin == "*" for origin in self.cors_allow_origins):
                errors.append(
                    "CORS_ALLOW_ORIGINS must not contain '*' when APP_ENV=production"
                )
        return errors


def load_settings(env_path: Path | None = None) -> Settings:
    """Load settings from env, optionally merging a .env file first."""
    load_dotenv(env_path or Path(".env"), override=False)
    app_env = _env("APP_ENV", _env("ENVIRONMENT", "development")).strip().lower()
    docs_default = app_env not in _PRODUCTION_ENVS
    return Settings(
        app_env=app_env,
        docs_enabled=_env_bool("APP_DOCS_ENABLED", docs_default),
        api_key=_env("APP_API_KEY", ""),
        ollama_api_key=_env("OLLAMA_API_KEY", ""),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 50),
        job_store_path=Path(_env("JOB_STORE_PATH", "./jobs.db")),
        job_dir=Path(_env("JOB_DIR", "./job_data")),
        job_retention_hours=_env_int("JOB_RETENTION_HOURS", 24),
        prune_interval_hours=_env_int("PRUNE_INTERVAL_HOURS", 1),
        backup_dir=Path(_env("JOB_BACKUP_DIR", "./job_backups")),
        backup_keep_n=_env_int("JOB_BACKUP_KEEP_N", 24),
        backup_interval_hours=_env_int("JOB_BACKUP_INTERVAL_HOURS", 1),
        worker_concurrency=_env_int("WORKER_CONCURRENCY", 1),
        cors_allow_origins=_env_list("CORS_ALLOW_ORIGINS", ["*"]),
        cxone_bridge_base_url=_env(
            "CXONE_BRIDGE_BASE_URL",
            "http://127.0.0.1:5175",
        ),
        cxone_integration_enabled=_env_bool("CXONE_INTEGRATION_ENABLED", False),
        cxone_bridge_timeout_seconds=_env_float("CXONE_BRIDGE_TIMEOUT_SECONDS", 300.0),
        cxone_health_timeout_seconds=_env_float("CXONE_HEALTH_TIMEOUT_SECONDS", 5.0),
        remedy_reviewer_required=_reviewer_required(),
        remedy_bridge_service_key_file=(Path(_env("REMEDY_BRIDGE_SERVICE_KEY_FILE"))
                                        if _env("REMEDY_BRIDGE_SERVICE_KEY_FILE") else None),
        quality_experiment_store_path=Path(
            _env("QUALITY_EXPERIMENT_STORE_PATH", "./quality_experiments.db")
        ),
        quality_review_queue_path=Path(
            _env("QUALITY_REVIEW_QUEUE_PATH", "./quality_review_queue.jsonl")
        ),
        quality_review_submission_path=Path(
            _env("QUALITY_REVIEW_SUBMISSION_PATH", "./quality_review_submissions.jsonl")
        ),
        quality_corpus_root_path=Path(
            _env("QUALITY_CORPUS_ROOT_PATH", "./tools/corpus_annotations/v1")
        ),
        reviewer_keys=_env_list("APP_REVIEWER_KEYS", []),
        quality_require_calibration=_env_bool(
            "QUALITY_REQUIRE_CALIBRATION",
            app_env in _PRODUCTION_ENVS,
        ),
        quality_min_cohens_kappa=_env_float("QUALITY_MIN_COHENS_KAPPA", 0.8),
        quality_min_calibration_samples=_env_int("QUALITY_MIN_CALIBRATION_SAMPLES", 1),
        quality_max_calibration_age_days=_env_int("QUALITY_MAX_CALIBRATION_AGE_DAYS", 0),
    )
